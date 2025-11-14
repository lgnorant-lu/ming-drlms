"""High-level M-Proto-v2 client used by the Python CLI."""

from __future__ import annotations

import hashlib
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator, Iterable, Optional, cast

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
        nonce = self._parse_challenge_nonce(frame)

        response_digest = hashlib.sha256((stored_hash + nonce).encode()).hexdigest()
        auth_req = auth_pb2.AuthRequest()
        auth_req.username = username
        auth_req.response = response_digest
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
        record = TokenRecord(
            username=username,
            host=self.host,
            port=self.port,
            access_token=auth_resp.access_token,
            access_expires_at=time.time() + max(30, float(expires_in)),
            refresh_token=auth_resp.refresh_token,
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
        )

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
                frame = read_frame(sock)
                if frame.msg_type == common_pb2.MSG_TYPE_ROOM_EVENT:
                    import binascii
                    import sys

                    sys.stderr.write(
                        f"DEBUG: room event frame payload len={len(frame.payload)}\n"
                    )
                    sys.stderr.write(
                        f"DEBUG: room event frame payload hex={binascii.hexlify(frame.payload).decode()}\n"
                    )
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
                    )
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
            import sys

            sys.stderr.write(
                f"DEBUG: get_room_members sending access_token length={len(record.access_token) if record and record.access_token is not None else 'None'}\n"
            )
        except Exception:
            pass
        payload = req.SerializeToString()
        try:
            import binascii
            import sys

            sys.stderr.write(
                f"DEBUG: serialized RoomMemberListRequest ({len(payload)} bytes): {binascii.hexlify(payload).decode()}\n"
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
    "login_flow",
]
