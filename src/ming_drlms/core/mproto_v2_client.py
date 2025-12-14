"""High-level M-Proto-v2 client used by the Python CLI."""

from __future__ import annotations

import hashlib
import os
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Optional, cast

from .. import log

from ming_drlms.proto.schema.v2 import (
    auth_pb2 as _auth_pb2,
    room_pb2 as _room_pb2,
    common_pb2 as _common_pb2,
    e2ee_pb2 as _e2ee_pb2,
)
from ming_drlms.proto.schema.v2 import message_types as _msg_types

auth_pb2 = cast(Any, _auth_pb2)
room_pb2 = cast(Any, _room_pb2)
common_pb2 = cast(Any, _common_pb2)
e2ee_pb2 = cast(Any, _e2ee_pb2)
msg_types = cast(Any, _msg_types)

from .mp2_transport import MP2Frame, read_frame, write_frame  # noqa: E402
from .token_store import TokenRecord, TokenStore  # noqa: E402
from ..users import parse_users  # noqa: E402

# Phase 15.5: Ed25519 imports removed - using XEdDSA exclusively via IdentityManager

logger = log.get_logger("core.mproto_v2_client")


class MP2Error(RuntimeError):
    """Base class for MP2 client errors."""


class AuthenticationError(MP2Error):
    """Raised when authentication or token refresh fails."""


@dataclass(slots=True)
class RoomMember:
    user_id: str
    device_id: int
    timestamp: str


@dataclass(slots=True)
class RoomFileMeta:
    filename: str
    size_bytes: int
    sha256_hex: str
    ephemeral: bool
    timestamp: str
    file_id: int | None = None
    compression_type: int = 0  # Phase 23


@dataclass(slots=True)
class RoomEvent:
    room_name: str
    event_id: int
    payload: bytes
    display_token: str
    # Optional v2 metadata
    kind: int | None = None
    sha256_hex: str | None = None
    instance_id: str | None = None
    timestamp: str | None = None
    file: RoomFileMeta | None = None
    payload_type: int | None = None
    sender: str | None = None
    sender_device_id: int | None = None
    sender_registration_id: int | None = None
    pre_key_id: int | None = None
    signed_pre_key_id: int | None = None
    presence: dict[str, Any] | None = None
    group_id: str | None = None
    sender_key_iteration: int | None = None


@dataclass(slots=True)
class SignalKeyPair:
    public_key: bytes
    private_key: bytes


@dataclass(slots=True)
class SignalPreKey:
    id: int
    key: SignalKeyPair


@dataclass(slots=True)
class SignalSignedPreKey:
    id: int
    key: SignalKeyPair
    signature: bytes
    timestamp: int


@dataclass(slots=True)
class E2EEGenerateKeysResult:
    code: int
    message: str
    registration_id: int
    pre_key_count: int
    device_id: int
    identity_key: SignalKeyPair | None
    signed_pre_key: SignalSignedPreKey | None
    pre_keys: tuple[SignalPreKey, ...]


@dataclass(slots=True)
class E2EEPreKeyBundle:
    code: int
    message: str
    identity_key: bytes | None
    registration_id: int
    device_id: int
    pre_key_id: int
    pre_key_public: bytes | None
    signed_pre_key_id: int
    signed_pre_key_public: bytes | None
    signed_pre_key_signature: bytes | None


@dataclass(slots=True)
class SignalSenderKeyDistribution:
    room_name: str
    group_id: str
    sender: str
    sender_device_id: int
    sender_registration_id: int
    distribution_message: bytes
    sender_key_id: int
    sender_key_iteration: int


class MP2Client:
    """Convenience wrapper around the MP2 framing layer."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float | None = 10.0,
        token_store: Optional[TokenStore] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._token_store = token_store or TokenStore()

    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.timeout is not None:
            sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.close()
        finally:
            self._sock = None

    def __enter__(self) -> "MP2Client":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()

    def pong(self, payload: bytes) -> None:
        """Send PONG response."""
        self.connect()
        sock = self._require_socket()
        write_frame(sock, common_pb2.MSG_TYPE_PONG, payload)

    def _read_response(self, expected_type: int) -> MP2Frame:
        """Read frames until expected type or error is received. Handles PING."""
        sock = self._require_socket()
        while True:
            frame = read_frame(sock)
            # Debug tracing via logger
            logger.debug(
                "_read_response: got %s, want %s",
                getattr(frame, "msg_type", None),
                expected_type,
            )

            if frame.msg_type == expected_type:
                return frame

            if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                return frame

            if frame.msg_type == common_pb2.MSG_TYPE_PING:
                # Respond to ping
                write_frame(sock, common_pb2.MSG_TYPE_PONG, frame.payload)
                continue

            # Ignore other messages (async events)
            logger.debug(
                "_read_response: ignoring %s", getattr(frame, "msg_type", None)
            )
            continue

    def login(
        self,
        username: str,
        *,
        password_hash: Optional[str] = None,
        users_file: Optional[Path | str] = None,
    ) -> TokenRecord:
        self.connect()
        sock = self._require_socket()

        stored_hash = password_hash or self._lookup_user_hash(username, users_file)
        if not stored_hash:
            raise AuthenticationError(
                "password hash not found; provide --password-hash or --users-file"
            )

        challenge = auth_pb2.AuthChallengeRequest()
        challenge.username = username
        write_frame(
            sock,
            common_pb2.MSG_TYPE_AUTH_CHALLENGE_REQUEST,
            challenge.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type != common_pb2.MSG_TYPE_AUTH_CHALLENGE_RESPONSE:
            raise AuthenticationError(
                f"expected AUTH_CHALLENGE_RESPONSE, got msg_type={frame.msg_type}"
            )
        ch = auth_pb2.AuthChallengeResponse()
        ch.ParseFromString(frame.payload)
        if not ch.nonce:
            raise AuthenticationError("challenge response missing nonce")
        nonce = ch.nonce
        server_salt = getattr(ch, "server_salt", "") or ""

        response_digest = hashlib.sha256((stored_hash + nonce).encode()).hexdigest()
        auth_req = auth_pb2.AuthRequest()
        auth_req.username = username
        auth_req.response = response_digest

        # 14C: attach ClientInfo with device/identity and binding signature (robust path)
        # Phase 22+: Use LocalIdentityManager + SignalStore for XEdDSA signing
        try:
            # Import logging for debug output
            import logging

            _mp2_log = logging.getLogger("ming_drlms.core.mproto_v2_client")

            # Get local identity (Phase 18+ unified identity)
            from ..identity import LocalIdentityManager

            local_im = LocalIdentityManager()

            if local_im.has_identity():
                identity = local_im.get_identity()
                ts = int(time.time())
                binding_parts = [
                    b"MP2-LOGIN-V1",
                    username.encode("utf-8"),
                    str(identity.device_id).encode("ascii"),
                    str(identity.registration_id).encode("ascii"),
                    (nonce or "").encode("ascii"),
                    (server_salt or "").encode("utf-8"),
                    str(ts).encode("ascii"),
                ]
                binding = b"|".join(binding_parts)

                pub = identity.public_key_raw  # 32-byte X25519 public key

                # XEdDSA signing via Signal Protocol C library
                from .pysignal.context import create_signal_context
                from .pysignal.store import SignalStore
                from .pysignal.signature import sign_bytes_with_store

                ctx = create_signal_context()
                store = SignalStore(ctx)

                # Initialize store with identity key
                id_pub = identity.public_key
                if len(id_pub) == 32:
                    id_pub = b"\x05" + id_pub

                store.set_identity(
                    public_key=id_pub,
                    private_key=identity.private_key,
                    registration_id=identity.registration_id,
                    device_id=identity.device_id,
                )

                sig = sign_bytes_with_store(
                    store, binding
                )  # XEdDSA signature (64 bytes)

                store.close()
                ctx.close()

                # Debug: Log signature generation details
                _mp2_log.debug(
                    "[MP2 Login] Using LocalIdentityManager + SignalStore XEdDSA"
                )
                _mp2_log.debug(
                    f"[MP2 Login] XEdDSA signing: binding_len={len(binding)}"
                )
                _mp2_log.debug(f"[MP2 Login] binding={binding!r}")
                _mp2_log.debug(f"[MP2 Login] pubkey: len={len(pub)} hex={pub.hex()}")
                _mp2_log.debug(
                    f"[MP2 Login] signature: len={len(sig)} hex={sig.hex()[:32]}..."
                )

                client = auth_pb2.ClientInfo()
                client.device_id = identity.device_id
                client.registration_id = identity.registration_id
                client.identity_pubkey = pub
                client.identity_sig = sig
                client.sig_ts = ts
                # signature_type: 1 = XEdDSA (Phase 15.5+)
                if hasattr(client, "signature_type"):
                    client.signature_type = 1
                try:
                    client.platform = os.name
                except Exception:
                    pass
                try:
                    if hasattr(auth_req, "client"):
                        auth_req.client.CopyFrom(client)
                        _mp2_log.debug("[MP2 Login] ClientInfo attached successfully")
                except Exception as e:
                    _mp2_log.warning(f"[MP2 Login] Failed to attach ClientInfo: {e}")
            else:
                _mp2_log.debug(
                    "[MP2 Login] No local identity found, skipping signature"
                )
        except Exception as e:
            # Non-fatal: proceed without ClientInfo if identity unavailable
            import logging

            _mp2_log = logging.getLogger("ming_drlms.core.mproto_v2_client")
            _mp2_log.debug(f"[MP2 Login] ClientInfo generation failed: {e}")

        write_frame(
            sock,
            common_pb2.MSG_TYPE_AUTH_REQUEST,
            auth_req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type != common_pb2.MSG_TYPE_AUTH_RESPONSE:
            if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                err = common_pb2.ErrorResponse()
                err.ParseFromString(frame.payload)
                raise AuthenticationError(f"auth failed: {err.code}: {err.message}")
            raise AuthenticationError(
                f"expected AUTH_RESPONSE, got msg_type={frame.msg_type}"
            )

        auth_resp = auth_pb2.AuthResponse()
        auth_resp.ParseFromString(frame.payload)
        if not auth_resp.access_token or not auth_resp.refresh_token:
            raise AuthenticationError("server did not return access/refresh tokens")

        expires_in = auth_resp.access_token_expires_in or 0
        accepted_device_id = None
        recorded_identity = None
        if hasattr(auth_resp, "accepted_device_id"):
            try:
                accepted_device_id = int(getattr(auth_resp, "accepted_device_id"))
            except Exception:
                accepted_device_id = None
        if hasattr(auth_resp, "recorded_identity"):
            try:
                recorded_identity = bool(getattr(auth_resp, "recorded_identity"))
            except Exception:
                recorded_identity = None

        record = TokenRecord(
            username=username,
            host=self.host,
            port=self.port,
            access_token=auth_resp.access_token,
            access_expires_at=time.time() + max(30, float(expires_in)),
            refresh_token=auth_resp.refresh_token,
            accepted_device_id=accepted_device_id,
            recorded_identity=recorded_identity,
        )
        self._token_store.store(record)
        return record

    def ensure_access_token(self, username: str) -> TokenRecord:
        record = self._token_store.load(username, self.host, self.port)
        if record is None:
            raise AuthenticationError(
                f"no cached token for {username}@{self.host}:{self.port}; please login"
            )
        now = time.time()
        if record.access_expires_at - now > 15:
            return record
        refreshed = self.refresh_token(record)
        self._token_store.store(refreshed)
        return refreshed

    def refresh_token(self, record: TokenRecord) -> TokenRecord:
        self.connect()
        sock = self._require_socket()

        request = auth_pb2.RefreshTokenRequest()
        request.refresh_token = record.refresh_token
        write_frame(
            sock,
            common_pb2.MSG_TYPE_REFRESH_TOKEN_REQUEST,
            request.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type != common_pb2.MSG_TYPE_REFRESH_TOKEN_RESPONSE:
            if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                err = common_pb2.ErrorResponse()
                err.ParseFromString(frame.payload)
                raise AuthenticationError(
                    f"token refresh failed: {err.code}: {err.message}"
                )
            raise AuthenticationError(
                f"expected REFRESH_TOKEN_RESPONSE, got msg_type={frame.msg_type}"
            )

        resp = auth_pb2.RefreshTokenResponse()
        resp.ParseFromString(frame.payload)
        if not resp.access_token:
            raise AuthenticationError("refresh response missing access token")
        expires_in = resp.access_token_expires_in or 0
        return TokenRecord(
            username=record.username,
            host=record.host,
            port=record.port,
            access_token=resp.access_token,
            access_expires_at=time.time() + max(30, float(expires_in)),
            refresh_token=record.refresh_token,
            accepted_device_id=record.accepted_device_id,
            recorded_identity=record.recorded_identity,
        )

    def create_room(
        self,
        username: str,
        room_name: str,
        *,
        storage_policy: int = 0,  # ROOM_STORAGE_PERSISTENT
        max_capacity: int = 0,
        max_instances: int = 0,
        max_ephemeral_events: int = 0,
    ) -> bool:
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomCreateRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.storage_policy = storage_policy
        req.max_capacity = max_capacity
        req.max_instances = max_instances
        req.max_ephemeral_events = max_ephemeral_events

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_CREATE_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_CREATE_RESPONSE:
            resp = room_pb2.RoomCreateResponse()
            resp.ParseFromString(frame.payload)
            return bool(resp.created)
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"create room failed: {err.code}: {err.message}")
        raise MP2Error(f"unexpected msg_type={frame.msg_type} during create room")

    def list_rooms(
        self,
        username: str,
        *,
        offset: int = 0,
        limit: int = 100,
        prefix: str = "",
    ) -> tuple[list[Any], int, bool]:
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomListRequest()
        req.access_token = record.access_token
        req.offset = offset
        req.limit = limit
        req.prefix = prefix

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_LIST_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_LIST_RESPONSE:
            resp = room_pb2.RoomListResponse()
            resp.ParseFromString(frame.payload)
            return list(resp.rooms), int(resp.total), bool(resp.has_more)
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"list rooms failed: {err.code}: {err.message}")
        raise MP2Error(f"unexpected msg_type={frame.msg_type} during list rooms")

    def get_history(
        self,
        username: str,
        room_name: str,
        *,
        since_id: int = 0,
        limit: int = 100,
        include_text: bool = True,
        include_files: bool = False,
    ) -> list[RoomEvent]:
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomHistoryRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.since_id = since_id
        req.limit = limit
        req.include_text = include_text
        req.include_files = include_files

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_HISTORY_REQUEST,
            req.SerializeToString(),
        )

        events: list[RoomEvent] = []
        while True:
            frame = read_frame(sock)
            if frame.msg_type == common_pb2.MSG_TYPE_ROOM_HISTORY_CHUNK:
                chunk = room_pb2.RoomHistoryChunk()
                chunk.ParseFromString(frame.payload)
                for event in chunk.events:
                    # Reuse parsing logic from subscribe if possible, or duplicate for now
                    # Duplicating for simplicity and to avoid refactoring subscribe right now
                    file_meta: RoomFileMeta | None = None
                    try:
                        if getattr(event, "file", None):
                            file_meta = RoomFileMeta(
                                filename=event.file.filename,
                                size_bytes=int(event.file.size_bytes),
                                sha256_hex=event.file.sha256_hex or "",
                                ephemeral=bool(event.file.ephemeral),
                                timestamp=event.file.timestamp or "",
                                compression_type=int(
                                    getattr(event.file, "compression_type", 0)
                                ),
                            )
                    except Exception:
                        file_meta = None

                    ciphertext = bytes(event.payload.ciphertext)
                    payload_type = (
                        int(event.payload.type)
                        if hasattr(event.payload, "type")
                        else None
                    )
                    sender = event.payload.sender or None
                    sender_device_id = (
                        int(event.payload.sender_device_id)
                        if getattr(event.payload, "sender_device_id", 0)
                        else None
                    )
                    sender_registration_id = (
                        int(event.payload.sender_registration_id)
                        if getattr(event.payload, "sender_registration_id", 0)
                        else None
                    )
                    pre_key_id = (
                        int(event.payload.pre_key_id)
                        if getattr(event.payload, "pre_key_id", 0)
                        else None
                    )
                    signed_pre_key_id = (
                        int(event.payload.signed_pre_key_id)
                        if getattr(event.payload, "signed_pre_key_id", 0)
                        else None
                    )
                    group_id = getattr(event.payload, "group_id", "") or None
                    sender_key_iteration = (
                        int(event.payload.sender_key_iteration)
                        if getattr(event.payload, "sender_key_iteration", 0)
                        else None
                    )

                    events.append(
                        RoomEvent(
                            room_name=event.room_name,
                            event_id=int(event.event_id),
                            payload=ciphertext,
                            display_token=event.display_token,
                            kind=int(getattr(event, "kind", 0))
                            if hasattr(event, "kind")
                            else None,
                            sha256_hex=(event.sha256_hex or None)
                            if hasattr(event, "sha256_hex")
                            else None,
                            instance_id=(event.instance_id or None)
                            if hasattr(event, "instance_id")
                            else None,
                            timestamp=(event.timestamp or None)
                            if hasattr(event, "timestamp")
                            else None,
                            file=file_meta,
                            payload_type=payload_type,
                            sender=sender,
                            sender_device_id=sender_device_id,
                            sender_registration_id=sender_registration_id,
                            pre_key_id=pre_key_id,
                            signed_pre_key_id=signed_pre_key_id,
                            group_id=group_id,
                            sender_key_iteration=sender_key_iteration,
                        )
                    )

                if not chunk.has_more:
                    break
            elif frame.msg_type == common_pb2.MSG_TYPE_ROOM_HISTORY_DONE:
                break
            elif frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                err = common_pb2.ErrorResponse()
                err.ParseFromString(frame.payload)
                raise MP2Error(f"get history failed: {err.code}: {err.message}")
            else:
                raise MP2Error(
                    f"unexpected msg_type={frame.msg_type} during get history"
                )

        return events

    def send_ping(self) -> None:
        """Send PING to server (async).

        Notes:
            Do NOT read the socket here to avoid races with the subscription reader.
            PONG is handled by the subscription loop.
        """
        self.connect()
        sock = self._require_socket()

        # Construct PingRequest
        req = common_pb2.PingRequest()
        req.timestamp_ms = int(time.time() * 1000)  # Current time in milliseconds
        req.client_id = f"{self.host}:{self.port}"

        write_frame(
            sock,
            common_pb2.MSG_TYPE_PING,
            req.SerializeToString(),
        )
        return None

    def publish(
        self,
        username: str,
        room_name: str,
        payload: bytes,
        *,
        ephemeral: bool = False,
        encrypted_payload: Optional[room_pb2.SignalEncryptedPayload] = None,
    ) -> None:
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomPublishRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        if encrypted_payload is None:
            payload_msg = room_pb2.SignalEncryptedPayload()
            payload_msg.type = (
                room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE
            )
            payload_msg.ciphertext = payload
            payload_msg.sender = username
        else:
            payload_msg = room_pb2.SignalEncryptedPayload()
            payload_msg.CopyFrom(encrypted_payload)
            if not payload_msg.ciphertext:
                payload_msg.ciphertext = payload
            if not payload_msg.sender:
                payload_msg.sender = username
        req.payload.CopyFrom(payload_msg)
        req.ephemeral = bool(ephemeral)
        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_PUB_REQUEST,
            req.SerializeToString(),
        )

        sock.settimeout(1.0)
        try:
            frame = read_frame(sock)
        except (ConnectionError, socket.timeout):
            return
        finally:
            if self.timeout is not None:
                sock.settimeout(self.timeout)
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"publish failed: {err.code}: {err.message}")

    def subscribe(
        self,
        username: str,
        room_name: str,
        *,
        since_id: int = 0,
        sender_key_callback: Optional[
            Callable[[SignalSenderKeyDistribution], None]
        ] = None,
        pong_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Iterable[RoomEvent]:
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomSubscribeRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.since_id = since_id
        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_SUB_REQUEST,
            req.SerializeToString(),
        )

        def _event_iter() -> Generator[RoomEvent, None, None]:
            while True:
                try:
                    frame = read_frame(sock)
                except socket.timeout:
                    # Keep-alive timeout: just continue loop to keep listening
                    # In a real impl we might want to send a PING here if idle too long
                    continue
                except (OSError, ConnectionError) as e:
                    logger.error("connection error during subscribe: %s", e)
                    break

                if frame.msg_type == common_pb2.MSG_TYPE_ROOM_EVENT:
                    # Debug trace of raw frame payload for diagnostics
                    try:
                        logger.debug(
                            "room event payload len=%d hex=%s",
                            len(frame.payload),
                            frame.payload.hex(),
                        )
                    except Exception:
                        pass
                    event = room_pb2.RoomEvent()
                    event.ParseFromString(frame.payload)
                    file_meta: RoomFileMeta | None = None
                    try:
                        if getattr(event, "file", None):
                            file_meta = RoomFileMeta(
                                filename=event.file.filename,
                                size_bytes=int(event.file.size_bytes),
                                sha256_hex=event.file.sha256_hex or "",
                                ephemeral=bool(event.file.ephemeral),
                                timestamp=event.file.timestamp or "",
                                compression_type=int(
                                    getattr(event.file, "compression_type", 0)
                                ),
                            )
                    except Exception:
                        file_meta = None
                    ciphertext = bytes(event.payload.ciphertext)
                    payload_type = (
                        int(event.payload.type)
                        if hasattr(event.payload, "type")
                        else None
                    )
                    sender = event.payload.sender or None
                    sender_device_id = (
                        int(event.payload.sender_device_id)
                        if getattr(event.payload, "sender_device_id", 0)
                        else None
                    )
                    sender_registration_id = (
                        int(event.payload.sender_registration_id)
                        if getattr(event.payload, "sender_registration_id", 0)
                        else None
                    )
                    pre_key_id = (
                        int(event.payload.pre_key_id)
                        if getattr(event.payload, "pre_key_id", 0)
                        else None
                    )
                    signed_pre_key_id = (
                        int(event.payload.signed_pre_key_id)
                        if getattr(event.payload, "signed_pre_key_id", 0)
                        else None
                    )
                    group_id = getattr(event.payload, "group_id", "") or None
                    sender_key_iteration = (
                        int(event.payload.sender_key_iteration)
                        if getattr(event.payload, "sender_key_iteration", 0)
                        else None
                    )
                    presence_data: dict[str, Any] | None = None
                    try:
                        if getattr(event, "presence", None):
                            presence_data = {
                                "user_id": event.presence.member.user_id,
                                "device_id": int(event.presence.member.device_id),
                                "timestamp": event.presence.member.timestamp,
                                "instance_id": event.presence.instance_id,
                            }
                    except Exception:
                        presence_data = None
                    yield RoomEvent(
                        room_name=event.room_name,
                        event_id=int(event.event_id),
                        payload=ciphertext,
                        display_token=event.display_token,
                        kind=int(getattr(event, "kind", 0))
                        if hasattr(event, "kind")
                        else None,
                        sha256_hex=(event.sha256_hex or None)
                        if hasattr(event, "sha256_hex")
                        else None,
                        instance_id=(event.instance_id or None)
                        if hasattr(event, "instance_id")
                        else None,
                        timestamp=(event.timestamp or None)
                        if hasattr(event, "timestamp")
                        else None,
                        file=file_meta,
                        payload_type=payload_type,
                        sender=sender,
                        sender_device_id=sender_device_id,
                        sender_registration_id=sender_registration_id,
                        pre_key_id=pre_key_id,
                        signed_pre_key_id=signed_pre_key_id,
                        presence=presence_data,
                        group_id=group_id,
                        sender_key_iteration=sender_key_iteration,
                    )
                elif frame.msg_type == msg_types.MSG_TYPE_E2EE_SENDER_KEY_PUSH:
                    if sender_key_callback is not None:
                        dist = e2ee_pb2.SignalSenderKeyDistribution()
                        dist.ParseFromString(frame.payload)
                        distribution = SignalSenderKeyDistribution(
                            room_name=dist.room_name,
                            group_id=dist.group_id,
                            sender=dist.sender,
                            sender_device_id=int(dist.sender_device_id),
                            sender_registration_id=int(dist.sender_registration_id),
                            distribution_message=bytes(dist.distribution_message),
                            sender_key_id=int(dist.sender_key_id),
                            sender_key_iteration=int(dist.sender_key_iteration),
                        )
                        sender_key_callback(distribution)
                    continue
                elif frame.msg_type == common_pb2.MSG_TYPE_PING:
                    # Respond to server ping and continue
                    write_frame(sock, common_pb2.MSG_TYPE_PONG, frame.payload)
                    continue
                elif frame.msg_type == common_pb2.MSG_TYPE_PONG:
                    # Update heartbeat based on PONG observed by the reader
                    try:
                        resp = common_pb2.PongResponse()
                        resp.ParseFromString(frame.payload)
                        if pong_callback is not None:
                            pong_callback(
                                int(resp.client_timestamp_ms), int(resp.timestamp_ms)
                            )
                    except Exception:
                        pass
                    continue
                elif frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                    err = common_pb2.ErrorResponse()
                    err.ParseFromString(frame.payload)
                    raise MP2Error(f"subscription error: {err.code}: {err.message}")
                else:
                    continue

        return _event_iter()

    def get_room_members(
        self,
        username: str,
        room_name: str,
    ) -> "list[RoomMember]":
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomMemberListRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        # Debug: log token presence for troubleshooting
        try:
            logger.debug(
                "get_room_members sending access_token length=%s",
                len(record.access_token)
                if record and record.access_token is not None
                else "None",
            )
        except Exception:
            pass
        payload = req.SerializeToString()
        try:
            logger.debug(
                "serialized RoomMemberListRequest (%d bytes): %s",
                len(payload),
                payload.hex(),
            )
        except Exception:
            pass
        write_frame(
            sock,
            msg_types.MSG_TYPE_ROOM_MEMBER_LIST_REQUEST,
            payload,
        )

        frame = read_frame(sock)
        if frame.msg_type == msg_types.MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE:
            resp = room_pb2.RoomMemberListResponse()
            resp.ParseFromString(frame.payload)
            members = []
            for member in resp.members:
                members.append(
                    RoomMember(
                        user_id=member.user_id,
                        device_id=int(member.device_id),
                        timestamp=member.timestamp,
                    )
                )
            return members
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"get room members failed: {err.code}: {err.message}")
        raise MP2Error(f"unexpected msg_type={frame.msg_type} during get room members")

    def e2ee_generate_keys(
        self,
        username: str,
        target_user: str,
        *,
        force: bool = False,
    ) -> E2EEGenerateKeysResult:
        self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = e2ee_pb2.E2EEGenerateKeysRequest()
        req.user_name = target_user
        req.force_regenerate = bool(force)
        write_frame(
            sock,
            msg_types.MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type == msg_types.MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE:
            resp = e2ee_pb2.E2EEGenerateKeysResponse()
            resp.ParseFromString(frame.payload)
            identity: SignalKeyPair | None = None
            if resp.identity_key is not None:
                identity = SignalKeyPair(
                    public_key=bytes(resp.identity_key.public_key),
                    private_key=bytes(resp.identity_key.private_key),
                )

            signed_pre_key: SignalSignedPreKey | None = None
            if resp.signed_pre_key is not None and resp.signed_pre_key.key:
                signed_pre_key = SignalSignedPreKey(
                    id=int(resp.signed_pre_key.id),
                    key=SignalKeyPair(
                        public_key=bytes(resp.signed_pre_key.key.public_key),
                        private_key=bytes(resp.signed_pre_key.key.private_key),
                    ),
                    signature=bytes(resp.signed_pre_key.signature),
                    timestamp=int(resp.signed_pre_key.timestamp),
                )

            pre_keys: list[SignalPreKey] = []
            for pk in resp.pre_keys:
                if not pk.key:
                    continue
                pre_keys.append(
                    SignalPreKey(
                        id=int(pk.id),
                        key=SignalKeyPair(
                            public_key=bytes(pk.key.public_key),
                            private_key=bytes(pk.key.private_key),
                        ),
                    )
                )

            return E2EEGenerateKeysResult(
                code=int(resp.code),
                message=resp.message,
                registration_id=int(resp.registration_id),
                pre_key_count=int(resp.pre_key_count),
                device_id=int(resp.device_id),
                identity_key=identity,
                signed_pre_key=signed_pre_key,
                pre_keys=tuple(pre_keys),
            )
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"e2ee generate keys failed: {err.code}: {err.message}")
        raise MP2Error(
            f"unexpected msg_type={frame.msg_type} during e2ee generate keys"
        )

    def e2ee_fetch_prekey_bundle(
        self,
        username: str,
        target_user: str,
    ) -> E2EEPreKeyBundle:
        self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = e2ee_pb2.E2EEPreKeyBundleRequest()
        req.user_name = target_user
        write_frame(
            sock,
            msg_types.MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type == msg_types.MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE:
            resp = e2ee_pb2.E2EEPreKeyBundleResponse()
            resp.ParseFromString(frame.payload)
            return E2EEPreKeyBundle(
                code=int(resp.code),
                message=resp.message,
                identity_key=bytes(resp.identity_key) if resp.identity_key else None,
                registration_id=int(resp.registration_id),
                device_id=int(resp.device_id),
                pre_key_id=int(resp.pre_key_id),
                pre_key_public=bytes(resp.pre_key_public)
                if resp.pre_key_public
                else None,
                signed_pre_key_id=int(resp.signed_pre_key_id),
                signed_pre_key_public=bytes(resp.signed_pre_key_public)
                if resp.signed_pre_key_public
                else None,
                signed_pre_key_signature=bytes(resp.signed_pre_key_signature)
                if resp.signed_pre_key_signature
                else None,
            )
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"e2ee pre-key bundle failed: {err.code}: {err.message}")
        raise MP2Error(
            f"unexpected msg_type={frame.msg_type} during e2ee pre-key bundle"
        )

    def e2ee_sender_key_push(
        self,
        username: str,
        target_user: str,
        distribution: SignalSenderKeyDistribution,
    ) -> tuple[int, str]:
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = e2ee_pb2.E2EESenderKeyPushRequest()
        req.access_token = record.access_token
        req.target_user = target_user
        req.distribution.room_name = distribution.room_name
        req.distribution.group_id = distribution.group_id
        req.distribution.sender = distribution.sender
        req.distribution.sender_device_id = distribution.sender_device_id
        req.distribution.sender_registration_id = distribution.sender_registration_id
        req.distribution.sender_key_id = distribution.sender_key_id
        req.distribution.sender_key_iteration = distribution.sender_key_iteration
        req.distribution.distribution_message = distribution.distribution_message
        write_frame(
            sock,
            msg_types.MSG_TYPE_E2EE_SENDER_KEY_PUSH,
            req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type == msg_types.MSG_TYPE_E2EE_SENDER_KEY_PUSH:
            resp = e2ee_pb2.E2EESenderKeyPushResponse()
            resp.ParseFromString(frame.payload)
            return int(resp.code), resp.message
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"sender key push failed: {err.code}: {err.message}")
        raise MP2Error(f"unexpected msg_type={frame.msg_type} during sender key push")

    # ------------------------------------------------------------------
    # File Protocol
    # ------------------------------------------------------------------
    def publish_file_begin(
        self,
        username: str,
        room_name: str,
        filename: str,
        size_bytes: int,
        sha256_hex: str,
        ephemeral: bool = False,
        compression_type: int = 0,
    ) -> str:
        """Begin file upload. Returns upload_id."""
        try:
            logger.debug(
                "file_publish_begin: user=%s room=%s filename=%s size=%s sha=%s ephemeral=%s comp=%s",
                username,
                room_name,
                filename,
                size_bytes,
                sha256_hex,
                ephemeral,
                compression_type,
            )
        except Exception:
            pass
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomFilePublishBegin()
        req.room_name = room_name
        req.access_token = record.access_token
        req.filename = filename
        req.size_bytes = size_bytes
        req.sha256_hex = sha256_hex
        req.ephemeral = ephemeral
        req.upload_id = str(uuid.uuid4())
        req.compression_type = compression_type

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_FILE_PUB_BEGIN,
            req.SerializeToString(),
        )

        frame = self._read_response(common_pb2.MSG_TYPE_ROOM_FILE_PUB_BEGIN)
        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_PUB_BEGIN:
            resp = room_pb2.RoomFilePublishBegin()
            resp.ParseFromString(frame.payload)
            try:
                logger.debug(
                    "file_publish_begin ok: room=%s upload_id=%s",
                    getattr(resp, "room_name", room_name),
                    getattr(resp, "upload_id", None),
                )
            except Exception:
                pass
            return resp.upload_id
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"file publish begin failed: {err.code}: {err.message}")
        raise MP2Error(
            f"unexpected msg_type={frame.msg_type} during file publish begin"
        )

    def publish_file_chunk(
        self,
        upload_id: str,
        data: bytes,
        offset: int,
        last_chunk: bool,
    ) -> None:
        """Send a file chunk."""
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomFilePublishChunk()
        req.upload_id = upload_id
        req.data = data
        req.offset = offset
        req.last_chunk = last_chunk

        try:
            logger.debug(
                "file_publish_chunk: upload_id=%s offset=%s len=%s last=%s",
                upload_id,
                offset,
                len(data) if hasattr(data, "__len__") else None,
                last_chunk,
            )
        except Exception:
            pass

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_FILE_PUB_CHUNK,
            req.SerializeToString(),
        )

    def publish_file_commit(
        self,
        upload_id: str,
    ) -> tuple[str, int]:
        """Commit file upload. Returns (room_name, event_id)."""
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomFilePublishCommit()
        req.upload_id = upload_id

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_FILE_PUB_COMMIT,
            req.SerializeToString(),
        )

        try:
            logger.debug("file_publish_commit: upload_id=%s", upload_id)
        except Exception:
            pass

        frame = self._read_response(common_pb2.MSG_TYPE_ROOM_FILE_PUB_RESULT)
        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_PUB_RESULT:
            resp = room_pb2.RoomFilePublishResult()
            resp.ParseFromString(frame.payload)
            try:
                logger.debug(
                    "file_publish_commit ok: upload_id=%s room=%s event_id=%s",
                    upload_id,
                    getattr(resp, "room_name", None),
                    getattr(resp, "event_id", None),
                )
            except Exception:
                pass
            return resp.room_name, int(resp.event_id)
        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"file publish commit failed: {err.code}: {err.message}")
        raise MP2Error(
            f"unexpected msg_type={frame.msg_type} during file publish commit"
        )

    def download_file(
        self,
        username: str,
        room_name: str,
        event_id: int,
    ) -> Generator[bytes, None, None]:
        """Download file. Yields data chunks."""
        try:
            logger.debug(
                "download_file start: room=%s event_id=%s", room_name, event_id
            )
        except Exception:
            pass
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomFileDownloadRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.event_id = event_id

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_REQUEST,
            req.SerializeToString(),
        )
        try:
            logger.debug(
                "download_file request sent: room=%s event_id=%s", room_name, event_id
            )
        except Exception:
            pass

        while True:
            frame = read_frame(sock)
            if frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_CHUNK:
                chunk = room_pb2.RoomFileDownloadChunk()
                chunk.ParseFromString(frame.payload)
                try:
                    logger.debug(
                        "download_file chunk: offset=%s len=%s last=%s",
                        getattr(chunk, "offset", 0),
                        len(chunk.data)
                        if getattr(chunk, "data", None) is not None
                        else 0,
                        bool(getattr(chunk, "last_chunk", 0)),
                    )
                except Exception:
                    pass

                # Phase 23: Compression Handling
                # Note: Decompression logic needs to happen AFTER receiving all chunks if using stream APIs,
                # BUT since we use "Whole File Compression", the client receives compressed chunks.
                # The client logic (caller of this generator) must handle saving chunks and then decompressing.
                # HOWEVER, to make it transparent, we can't easily decompress stream per chunk if it's Zstd without a streaming decompressor context.
                #
                # Given we agreed on "Temp-File Strategy":
                # 1. Receiver must know compression_type (from RoomFileMetadata in Event).
                # 2. download_file here yields chunks.
                #
                # The `download_file` generator just yields RAW protocol bytes.
                # Higher level function `RoomService.download_file` or `ChatController.download_file`
                # must handle the decompression after writing all chunks (or using streaming decompressor).
                #
                # The PROTOCOL chunk message `RoomFileDownloadChunk` has `compression_type`?
                # No, `RoomFileMetadata` (in Event) has it.
                # `RoomFileDownloadChunk` (Line 260 of proto) matches download request.
                #
                # We will pass the raw compressed bytes here. Decompression is higher-layer responsibility.

                yield chunk.data
                if chunk.last_chunk:
                    break
            elif frame.msg_type == common_pb2.MSG_TYPE_ROOM_FILE_DOWNLOAD_DONE:
                try:
                    logger.debug(
                        "download_file done: room=%s event_id=%s", room_name, event_id
                    )
                except Exception:
                    pass
                break
            elif frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
                err = common_pb2.ErrorResponse()
                err.ParseFromString(frame.payload)
                try:
                    logger.error(
                        "download_file failed: %s: %s (room=%s event_id=%s)",
                        getattr(err, "code", None),
                        getattr(err, "message", None),
                        room_name,
                        event_id,
                    )
                except Exception:
                    pass
                raise MP2Error(f"file download failed: {err.code}: {err.message}")
            else:
                raise MP2Error(
                    f"unexpected msg_type={frame.msg_type} during file download"
                )

    def clear_room_owner(self, username: str, room_name: str) -> dict:
        """Clear room owner (return to system ownership)

        Args:
            username: User performing the action
            room_name: Name of the room

        Returns:
            dict with 'success', 'message', 'previous_owner', 'room_name'

        Raises:
            MP2Error: If the operation fails
        """
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        # Build request
        req = room_pb2.RoomClearOwnerRequest()
        req.room_name = room_name
        req.access_token = record.access_token

        # Send request
        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_CLEAR_OWNER_REQUEST,
            req.SerializeToString(),
        )

        # Read response
        frame = read_frame(sock)

        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_CLEAR_OWNER_RESPONSE:
            resp = room_pb2.RoomClearOwnerResponse()
            resp.ParseFromString(frame.payload)
            return {
                "success": resp.success,
                "message": resp.message,
                "previous_owner": resp.previous_owner,
                "room_name": resp.room_name,
            }

        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"clear owner failed: {err.code}: {err.message}")

        raise MP2Error(f"unexpected msg_type={frame.msg_type} during clear owner")

    def set_room_policy(
        self,
        username: str,
        room_name: str,
        policy: int,  # 0=retain, 1=delegate, 2=teardown
    ) -> dict:
        """Set room policy using MP2 protocol

        Args:
            username: User performing the action
            room_name: Name of the room
            policy: Policy value (0=retain, 1=delegate, 2=teardown)

        Returns:
            dict with 'room_name', 'policy'
        """
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomSetPolicyRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.policy = policy

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_SET_POLICY_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)

        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_SET_POLICY_RESPONSE:
            resp = room_pb2.RoomSetPolicyResponse()
            resp.ParseFromString(frame.payload)
            return {"room_name": resp.room_name, "policy": resp.policy}

        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"set policy failed: {err.code}: {err.message}")

        raise MP2Error(f"unexpected msg_type={frame.msg_type}")

    def set_room_storage_policy(
        self,
        username: str,
        room_name: str,
        storage_policy: int,  # 0=persistent, 1=ephemeral
    ) -> dict:
        """Set room storage policy using MP2 protocol

        Args:
            username: User performing the action
            room_name: Name of the room
            storage_policy: Storage policy (0=persistent, 1=ephemeral)

        Returns:
            dict with 'room_name', 'storage_policy'
        """
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomSetStoragePolicyRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.storage_policy = storage_policy

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_SET_STORAGE_POLICY_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)

        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_SET_STORAGE_POLICY_RESPONSE:
            resp = room_pb2.RoomSetStoragePolicyResponse()
            resp.ParseFromString(frame.payload)
            return {"room_name": resp.room_name, "storage_policy": resp.storage_policy}

        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"set storage policy failed: {err.code}: {err.message}")

        raise MP2Error(f"unexpected msg_type={frame.msg_type}")

    def transfer_room_ownership(
        self, username: str, room_name: str, new_owner: str
    ) -> dict:
        """Transfer room ownership using MP2 protocol

        Args:
            username: Current owner
            room_name: Name of the room
            new_owner: New owner username

        Returns:
            dict with 'room_name', 'new_owner'
        """
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomTransferRequest()
        req.room_name = room_name
        req.access_token = record.access_token
        req.new_owner = new_owner

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_TRANSFER_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)

        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_TRANSFER_RESPONSE:
            resp = room_pb2.RoomTransferResponse()
            resp.ParseFromString(frame.payload)
            return {"room_name": resp.room_name, "new_owner": resp.new_owner}

        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"transfer ownership failed: {err.code}: {err.message}")

        raise MP2Error(f"unexpected msg_type={frame.msg_type}")

    def get_room_info(
        self,
        username: str,
        room_name: str,
    ) -> dict:
        """Get room info using MP2 protocol

        Args:
            username: User performing the action
            room_name: Name of the room

        Returns:
            dict containing room info
        """
        record = self.ensure_access_token(username)
        self.connect()
        sock = self._require_socket()

        req = room_pb2.RoomInfoRequest()
        req.access_token = record.access_token
        req.room_name = room_name

        write_frame(
            sock,
            common_pb2.MSG_TYPE_ROOM_INFO_REQUEST,
            req.SerializeToString(),
        )

        frame = read_frame(sock)
        if frame.msg_type == common_pb2.MSG_TYPE_ROOM_INFO_RESPONSE:
            resp = room_pb2.RoomInfoResponse()
            resp.ParseFromString(frame.payload)

            policy_map = {0: "retain", 1: "delegate", 2: "teardown"}
            storage_map = {0: "persistent", 1: "ephemeral"}

            return {
                "name": resp.room_name,
                "owner": resp.owner,
                "policy": resp.policy,
                "policy_name": policy_map.get(resp.policy, "unknown"),
                "storage_policy": resp.storage_policy,
                "storage_policy_name": storage_map.get(resp.storage_policy, "unknown"),
                "subscribers": resp.total_subscribers,
                "last_event_id": resp.last_event_id,
                "created_at": resp.created_at_epoch,
                "details": {
                    "subs": resp.total_subscribers,
                    "last_event_id": resp.last_event_id,
                },
            }

        if frame.msg_type == common_pb2.MSG_TYPE_ERROR_RESPONSE:
            err = common_pb2.ErrorResponse()
            err.ParseFromString(frame.payload)
            raise MP2Error(f"get room info failed: {err.code}: {err.message}")

        raise MP2Error(f"unexpected msg_type={frame.msg_type}")

    def _require_socket(self) -> socket.socket:
        if self._sock is None:
            raise RuntimeError("socket not connected")
        return self._sock

    @staticmethod
    def _parse_challenge_nonce(frame: MP2Frame) -> str:
        msg = auth_pb2.AuthChallengeResponse()
        msg.ParseFromString(frame.payload)
        if not msg.nonce:
            raise AuthenticationError("challenge response missing nonce")
        return msg.nonce

    @staticmethod
    def _lookup_user_hash(
        username: str, users_file: Optional[Path | str]
    ) -> Optional[str]:
        candidates: list[Path] = []
        if users_file:
            candidates.append(Path(users_file).expanduser())
        env_path = os.environ.get("DRLMS_USERS_FILE")
        if env_path:
            candidates.append(Path(env_path).expanduser())
        cwd = Path.cwd()
        candidates.extend(
            [
                cwd / "server_files" / "users.txt",
                cwd / "users.txt",
            ]
        )
        seen = set()
        for path in candidates:
            path = path.resolve()
            if path in seen or not path.exists():
                continue
            seen.add(path)
            try:
                for name, _scheme, encoded in parse_users(path):
                    if name == username:
                        return encoded
            except Exception:
                continue
        return None


def login_flow(
    host: str,
    port: int,
    username: str,
    *,
    password_hash: Optional[str] = None,
    users_file: Optional[Path | str] = None,
    timeout: float | None = 10.0,
    token_store: Optional[TokenStore] = None,
) -> TokenRecord:
    """Convenience wrapper used by CLI flows for MP2 authentication."""

    with MP2Client(
        host,
        port,
        timeout=timeout,
        token_store=token_store or TokenStore(),
    ) as client:
        return client.login(
            username,
            password_hash=password_hash,
            users_file=users_file,
        )


__all__ = [
    "MP2Client",
    "MP2Error",
    "AuthenticationError",
    "RoomEvent",
    "RoomMember",
    "SignalKeyPair",
    "SignalPreKey",
    "SignalSignedPreKey",
    "E2EEGenerateKeysResult",
    "E2EEPreKeyBundle",
    "SignalSenderKeyDistribution",
    "login_flow",
]
