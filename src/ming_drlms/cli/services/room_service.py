from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from ming_drlms.core.mproto_v2_client import (
    AuthenticationError,
    MP2Error,
    RoomEvent,
    RoomMember,
)
from ming_drlms.proto.schema.v2 import room_pb2
from ming_drlms.core.pysignal import SignalBridgeError
from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.e2ee_runtime import E2EEngine, proto_type_from_lib

from ..mproto_runtime import create_mp2_client
from ..utils import tcp_connect, recv_line, login


class RoomServiceError(RuntimeError):
    """Raised when room related operations fail."""


@dataclass(slots=True)
class PublishResult:
    bytes_sent: int
    ephemeral: bool


@dataclass(slots=True)
class CommandResult:
    lines: List[str]

    @property
    def first(self) -> str:
        return self.lines[0] if self.lines else ""


@dataclass(slots=True)
class RoomInfo:
    name: str
    details: dict[str, object]
    raw: List[str]

    def as_dict(self) -> dict[str, object]:
        payload = {"room": self.name}
        payload.update(self.details)
        return payload


class RoomService:
    def __init__(
        self,
        *,
        client_factory: Callable[..., contextmanager] = create_mp2_client,
        tcp_connect_fn: Callable[..., object] = tcp_connect,
        login_fn: Callable[..., bool] = login,
        recv_line_fn: Callable[..., str] = recv_line,
    ) -> None:
        self._client_factory = client_factory
        self._tcp_connect = tcp_connect_fn
        self._login = login_fn
        self._recv_line = recv_line_fn

    # ------------------------------------------------------------------
    # MP2 operations
    # ------------------------------------------------------------------
    def subscribe(
        self,
        *,
        host: str,
        port: int,
        user: str,
        room: str,
        since_id: int,
        token_store: Optional[object],
        timeout: float,
        e2ee_store: Optional[Path | str] = None,
    ) -> Iterator[RoomEvent]:
        try:
            key_store = self._build_key_store(e2ee_store) if e2ee_store else None
            with self._client_factory(
                host,
                port,
                timeout=timeout,
                token_store_path=token_store,
            ) as client:
                engine = None
                if key_store is not None:
                    try:
                        engine = E2EEngine(
                            username=user,
                            key_store=key_store,
                            mp2_client=client,
                        )
                    except SignalBridgeError as exc:
                        raise RoomServiceError(str(exc)) from exc
                sender_key_callback = (
                    engine.process_sender_key_distribution
                    if engine is not None
                    else None
                )
                try:
                    for event in client.subscribe(
                        user,
                        room,
                        since_id=since_id,
                        sender_key_callback=sender_key_callback,
                    ):
                        if engine is not None:
                            try:
                                if (
                                    event.kind
                                    == room_pb2.RoomEventKind.ROOM_EVENT_KIND_MEMBER_JOINED
                                    and event.presence is not None
                                ):
                                    new_member = event.presence.get("user_id", "")
                                    if new_member and new_member != user:
                                        engine.distribute_sender_key(
                                            room, room, new_member
                                        )

                                if event.group_id:
                                    group_result = engine.decrypt_group(event)
                                    event = replace(
                                        event,
                                        payload=group_result.plaintext,
                                        sender_key_iteration=group_result.iteration,
                                        payload_type=room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE,  # type: ignore[attr-defined]
                                    )
                                else:
                                    result = engine.decrypt(event)
                                    event = replace(
                                        event,
                                        payload=result.plaintext,
                                        payload_type=proto_type_from_lib(
                                            result.info.message_type
                                        ),
                                    )
                            except SignalBridgeError as exc:
                                raise RoomServiceError(f"E2EE 解密失败: {exc}") from exc
                        yield event
                except SignalBridgeError as exc:
                    raise RoomServiceError(f"E2EE sender key 处理失败: {exc}") from exc
                finally:
                    if engine is not None:
                        engine.close()
        except (AuthenticationError, MP2Error, OSError) as exc:
            raise RoomServiceError(str(exc)) from exc

    def publish(
        self,
        *,
        host: str,
        port: int,
        user: str,
        room: str,
        payload: bytes,
        ephemeral: bool,
        token_store: Optional[object],
        timeout: float,
        e2ee_store: Optional[Path | str] = None,
    ) -> PublishResult:
        try:
            key_store = self._build_key_store(e2ee_store) if e2ee_store else None
            with self._client_factory(
                host,
                port,
                timeout=timeout,
                token_store_path=token_store,
            ) as client:
                engine = None
                ciphertext = payload
                encrypted_proto = None
                if key_store is not None:
                    try:
                        engine = E2EEngine(
                            username=user,
                            key_store=key_store,
                            mp2_client=client,
                        )
                        try:
                            members = client.get_room_members(user, room)
                        except (AuthenticationError, MP2Error) as exc:
                            raise RoomServiceError(str(exc)) from exc
                        for member in members:
                            if member.user_id != user:
                                engine.distribute_sender_key(room, room, member.user_id)
                        encrypted_proto = engine.encrypt_group(room, room, payload)
                        ciphertext = bytes(encrypted_proto.ciphertext)  # type: ignore[attr-defined]
                    except SignalBridgeError as exc:
                        raise RoomServiceError(str(exc)) from exc
                try:
                    client.publish(
                        user,
                        room,
                        ciphertext,
                        ephemeral=ephemeral,
                        encrypted_payload=encrypted_proto,
                    )
                finally:
                    if engine is not None:
                        engine.close()
        except (AuthenticationError, MP2Error, OSError) as exc:
            raise RoomServiceError(str(exc)) from exc
        return PublishResult(bytes_sent=len(payload), ephemeral=ephemeral)

    def list_rooms(
        self,
        *,
        host: str,
        port: int,
        user: str,
        token_store_path: Optional[object] = None,
        offset: int = 0,
        limit: int = 100,
        prefix: str = "",
    ) -> tuple[list[object], int, bool]:
        try:
            with self._client_factory(
                host,
                port,
                timeout=10.0,
                token_store_path=token_store_path,
            ) as client:
                return client.list_rooms(
                    user, offset=offset, limit=limit, prefix=prefix
                )
        except (MP2Error, AuthenticationError) as exc:
            raise RoomServiceError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Legacy protocol helpers
    # ------------------------------------------------------------------
    @contextmanager
    def _legacy_connection(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
    ) -> Iterator[object]:
        try:
            sock = self._tcp_connect(host, port)
        except OSError as exc:
            raise RoomServiceError(str(exc)) from exc
        try:
            if not self._login(sock, user, password):
                raise RoomServiceError("login failed")
            yield sock
        finally:
            try:
                try:
                    sock.sendall(b"QUIT\n")
                except Exception:
                    pass
                sock.close()
            except Exception:
                pass

    def fetch_info(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
    ) -> RoomInfo:
        with self._legacy_connection(
            host=host, port=port, user=user, password=password
        ) as sock:
            payload = f"ROOMINFO|{room}\n".encode()
            sock.sendall(payload)
            raw_lines: List[str] = []
            info_payload: Optional[str] = None
            while True:
                line = self._recv_line(sock)
                if not line:
                    break
                raw_lines.append(line)
                if line.startswith("ERR|"):
                    raise RoomServiceError(line)
                if line.startswith("OK|ROOMINFO|"):
                    info_payload = line[3:]
                    break
                if line.startswith("ROOMINFO|"):
                    info_payload = line
                    break
                if line.startswith("OK"):
                    continue
            if not info_payload:
                raise RoomServiceError("ROOMINFO not returned")
            room_name, details = self._parse_roominfo(info_payload)
            return RoomInfo(name=room_name, details=details, raw=raw_lines)

    @staticmethod
    def _build_key_store(path: Optional[Path | str]) -> LocalKeyStore:
        if path is None:
            return LocalKeyStore()
        if isinstance(path, Path):
            resolved = path.expanduser()
        else:
            resolved = Path(path).expanduser()
        return LocalKeyStore(resolved)

    def create_room(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
        policy: str,
    ) -> CommandResult:
        return self._execute_simple_command(
            host=host,
            port=port,
            user=user,
            password=password,
            command=f"CREATE|{room}|{policy}\n",
        )

    def set_policy(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
        policy: str,
    ) -> CommandResult:
        return self._execute_simple_command(
            host=host,
            port=port,
            user=user,
            password=password,
            command=f"SETPOLICY|{room}|{policy}\n",
        )

    def set_storage_policy(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
        policy: str,
    ) -> CommandResult:
        return self._execute_simple_command(
            host=host,
            port=port,
            user=user,
            password=password,
            command=f"SETSTORAGE|{room}|{policy}\n",
        )

    def transfer_owner(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        room: str,
        new_owner: str,
    ) -> CommandResult:
        return self._execute_simple_command(
            host=host,
            port=port,
            user=user,
            password=password,
            command=f"TRANSFER|{room}|{new_owner}\n",
            capture_additional=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _execute_simple_command(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        command: str,
        capture_additional: bool = False,
    ) -> CommandResult:
        with self._legacy_connection(
            host=host, port=port, user=user, password=password
        ) as sock:
            sock.sendall(command.encode())
            lines: List[str] = []
            while True:
                line = self._recv_line(sock)
                if not line:
                    break
                lines.append(line)
                if line.startswith("ERR|"):
                    raise RoomServiceError(line)
                if line.startswith("OK") and not capture_additional:
                    break
                if not capture_additional:
                    break
                if len(lines) >= 2:
                    break
            if not lines:
                raise RoomServiceError("no response received")
            return CommandResult(lines=lines)

    @staticmethod
    def _parse_roominfo(payload: str) -> tuple[str, dict[str, object]]:
        parts = payload.split("|")
        if len(parts) < 2:
            raise RoomServiceError("malformed ROOMINFO line")
        if parts[0] != "ROOMINFO":
            raise RoomServiceError("malformed ROOMINFO line")
        room_name = parts[1]
        data: dict[str, object] = {}
        if len(parts) >= 7 and parts[2].isdigit():
            total_instances = RoomService._safe_int(parts[2])
            total_subs = RoomService._safe_int(parts[3])
            storage_policy = RoomService._safe_int(parts[4])
            max_capacity = RoomService._safe_int(parts[5])
            owner = parts[6] if len(parts) > 6 else ""
            policy = RoomService._safe_int(parts[7]) if len(parts) > 7 else 0
            data.update(
                {
                    "total_instances": total_instances,
                    "total_subscribers": total_subs,
                    "storage_policy": storage_policy,
                    "max_capacity": max_capacity,
                    "owner": owner,
                    "policy": policy,
                    "storage_policy_name": "ephemeral"
                    if storage_policy == 1
                    else "persistent",
                }
            )
        elif len(parts) >= 6:
            owner = parts[2]
            policy = RoomService._safe_int(parts[3])
            subs = RoomService._safe_int(parts[4])
            last_event_id = RoomService._safe_int(parts[5])
            data.update(
                {
                    "owner": owner,
                    "policy": policy,
                    "subs": subs,
                    "last_event_id": last_event_id,
                }
            )
        else:
            raise RoomServiceError("malformed ROOMINFO line")
        return room_name, data

    @staticmethod
    def _safe_int(value: str) -> int:
        try:
            return int(value)
        except ValueError:
            return 0

    def get_room_members_mp2(
        self,
        *,
        host: str,
        port: int,
        user: str,
        room: str,
        token_store_path: Optional[object] = None,
    ) -> list[RoomMember]:
        try:
            with self._client_factory(
                host,
                port,
                timeout=10.0,
                token_store_path=token_store_path,
            ) as client:
                return client.get_room_members(user, room)
        except (MP2Error, AuthenticationError) as exc:
            raise RoomServiceError(str(exc)) from exc


__all__ = [
    "RoomService",
    "RoomServiceError",
    "PublishResult",
    "RoomInfo",
    "CommandResult",
]
