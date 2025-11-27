"""本地端到端密钥仓库，负责持久化身份密钥与预密钥。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .mproto_v2_client import SignalKeyPair, SignalPreKey, SignalSignedPreKey

__all__ = [
    "LocalKeyState",
    "LocalKeyStore",
    "SenderKeyRecord",
]


_CONFIG_DIR_ENV = "MING_DRLMS_CONFIG_DIR"
_DEFAULT_CONFIG_SUBDIR = "ming-drlms"
_KEYSTORE_FILENAME = "e2ee_keys.json"


def _default_config_dir() -> Path:
    env_path = os.environ.get(_CONFIG_DIR_ENV)
    if env_path:
        return Path(env_path).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / _DEFAULT_CONFIG_SUBDIR
    return Path.home() / ".config" / _DEFAULT_CONFIG_SUBDIR


def _default_store_path() -> Path:
    return _default_config_dir() / _KEYSTORE_FILENAME


def _encode_bytes(data: bytes | None) -> str | None:
    return data.hex() if data is not None else None


def _decode_bytes(payload: str | None) -> bytes | None:
    if payload is None:
        return None
    return bytes.fromhex(payload)


def _encode_key_pair(pair: SignalKeyPair | None) -> Mapping[str, str] | None:
    if pair is None:
        return None
    return {
        "public": pair.public_key.hex(),
        "private": pair.private_key.hex(),
    }


def _decode_key_pair(payload: Mapping[str, str] | None) -> SignalKeyPair | None:
    if not payload:
        return None
    try:
        public_key = bytes.fromhex(payload["public"])
        private_key = bytes.fromhex(payload["private"])
    except Exception as exc:  # pragma: no cover - 数据损坏时返回 None
        raise ValueError("invalid key pair payload") from exc
    return SignalKeyPair(public_key=public_key, private_key=private_key)


def _encode_sender_key_record(record: "SenderKeyRecord") -> Mapping[str, object]:
    payload: Dict[str, object] = {
        "room_name": record.room_name,
        "group_id": record.group_id,
        "sender": record.sender,
        "sender_device_id": int(record.sender_device_id),
        "sender_registration_id": int(record.sender_registration_id),
        "sender_key_id": int(record.sender_key_id),
        "sender_key_iteration": int(record.sender_key_iteration),
        "distribution": record.distribution.hex(),
    }
    if getattr(record, "record_blob", None) is not None:
        payload["record_blob"] = record.record_blob.hex()  # type: ignore[attr-defined]
    return payload


def _decode_sender_key_record(
    payload: Mapping[str, object] | None,
) -> "SenderKeyRecord" | None:
    if not payload:
        return None
    try:
        room_name = payload.get("room_name")
        group_id = payload.get("group_id")
        sender = payload.get("sender")
        sender_device_id = payload.get("sender_device_id")
        sender_registration_id = payload.get("sender_registration_id")
        sender_key_id = payload.get("sender_key_id")
        sender_key_iteration = payload.get("sender_key_iteration")
        distribution_hex = payload.get("distribution")
    except Exception:
        return None
    if (
        not isinstance(room_name, str)
        or not isinstance(group_id, str)
        or not isinstance(sender, str)
    ):
        return None
    try:
        device_id = int(sender_device_id)
        registration_id = int(sender_registration_id)
        key_id = int(sender_key_id)
        iteration = int(sender_key_iteration)
    except Exception:
        return None
    if not isinstance(distribution_hex, str):
        return None
    payload_bytes = _decode_bytes(distribution_hex)
    if payload_bytes is None:
        return None
    record_blob_hex = payload.get("record_blob")
    record_blob: Optional[bytes] = None
    if isinstance(record_blob_hex, str):
        record_blob = _decode_bytes(record_blob_hex)
    return SenderKeyRecord(
        room_name=room_name,
        group_id=group_id,
        sender=sender,
        sender_device_id=device_id,
        sender_registration_id=registration_id,
        sender_key_id=key_id,
        sender_key_iteration=iteration,
        distribution=payload_bytes,
        record_blob=record_blob,
    )


@dataclass(slots=True)
class SenderKeyRecord:
    room_name: str
    group_id: str
    sender: str
    sender_device_id: int
    sender_registration_id: int
    sender_key_id: int
    sender_key_iteration: int
    distribution: bytes
    record_blob: bytes | None = None

    def index(self) -> str:
        return f"{self.room_name}|{self.group_id}|{self.sender}|{self.sender_device_id}"


@dataclass(slots=True)
class LocalKeyState:
    registration_id: int
    device_id: int
    identity_key: SignalKeyPair
    signed_pre_key: SignalSignedPreKey | None
    pre_keys: Dict[int, SignalKeyPair]
    remote_identities: Dict[Tuple[str, int], bytes]
    sender_keys: Dict[str, SenderKeyRecord]


class LocalKeyStore:
    """面向多账号的本地密钥仓库。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else _default_store_path()
        self._data: Dict[str, object] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # 公共读取接口
    # ------------------------------------------------------------------
    def load_state(self, username: str) -> Optional[LocalKeyState]:
        payload = self._load_user_payload(username)
        if payload is None:
            return None

        identity_raw = payload.get("identity")
        if not isinstance(identity_raw, dict):
            return None
        identity_pair = _decode_key_pair(identity_raw)
        if identity_pair is None:
            return None

        try:
            registration_id = int(payload.get("registration_id", 0))
            device_id = int(payload.get("device_id", 0))
        except Exception:
            return None
        if registration_id <= 0 or device_id < 0:
            return None

        signed_raw = payload.get("signed_pre_key")
        signed_pre_key = None
        if isinstance(signed_raw, dict):
            pair = _decode_key_pair(signed_raw.get("key"))
            signature = _decode_bytes(signed_raw.get("signature"))
            timestamp = signed_raw.get("timestamp")
            if (
                pair is not None
                and signature is not None
                and isinstance(signed_raw.get("id"), int)
                and isinstance(timestamp, int)
            ):
                signed_pre_key = SignalSignedPreKey(
                    id=int(signed_raw["id"]),
                    key=pair,
                    signature=signature,
                    timestamp=int(timestamp),
                )

        pre_keys_raw = payload.get("pre_keys")
        pre_keys: Dict[int, SignalKeyPair] = {}
        if isinstance(pre_keys_raw, dict):
            for key, value in pre_keys_raw.items():
                try:
                    kid = int(key)
                except Exception:
                    continue
                pair = _decode_key_pair(value if isinstance(value, dict) else None)
                if pair is not None:
                    pre_keys[kid] = pair

        remote_raw = payload.get("remote_identities")
        remote_identities: Dict[Tuple[str, int], bytes] = {}
        if isinstance(remote_raw, dict):
            for key, encoded in remote_raw.items():
                if not isinstance(key, str) or not isinstance(encoded, str):
                    continue
                try:
                    name, device_str = key.rsplit("#", 1)
                    device = int(device_str)
                except Exception:
                    continue
                data = _decode_bytes(encoded)
                if data is not None:
                    remote_identities[(name, device)] = data

        sender_keys_raw = payload.get("sender_keys")
        sender_keys: Dict[str, SenderKeyRecord] = {}
        if isinstance(sender_keys_raw, dict):
            for key, record in sender_keys_raw.items():
                if not isinstance(record, dict):
                    continue
                entry = _decode_sender_key_record(record)
                if entry is not None:
                    sender_keys[key] = entry

        return LocalKeyState(
            registration_id=registration_id,
            device_id=device_id,
            identity_key=identity_pair,
            signed_pre_key=signed_pre_key,
            pre_keys=pre_keys,
            remote_identities=remote_identities,
            sender_keys=sender_keys,
        )

    # ------------------------------------------------------------------
    # 更新接口
    # ------------------------------------------------------------------
    def store_keys(
        self,
        username: str,
        *,
        registration_id: int,
        device_id: int,
        identity: SignalKeyPair,
        signed_pre_key: SignalSignedPreKey | None,
        pre_keys: Iterable[SignalPreKey],
    ) -> LocalKeyState:
        pre_key_map: Dict[int, SignalKeyPair] = {}
        for pk in pre_keys:
            pre_key_map[int(pk.id)] = pk.key

        payload = self._load_user_payload(username) or {}
        payload.update(
            {
                "registration_id": int(registration_id),
                "device_id": int(device_id),
                "identity": _encode_key_pair(identity),
                "pre_keys": {
                    str(kid): _encode_key_pair(pair)
                    for kid, pair in pre_key_map.items()
                },
            }
        )
        if signed_pre_key is not None:
            payload["signed_pre_key"] = {
                "id": int(signed_pre_key.id),
                "timestamp": int(signed_pre_key.timestamp),
                "signature": signed_pre_key.signature.hex(),
                "key": _encode_key_pair(signed_pre_key.key),
            }
        else:
            payload.pop("signed_pre_key", None)

        self._store_user_payload(username, payload)
        state = self.load_state(username)
        if state is None:
            raise RuntimeError("failed to reload key state after persist")
        return state

    def add_pre_keys(self, username: str, pre_keys: Iterable[SignalPreKey]) -> None:
        payload = self._load_user_payload(username)
        if payload is None:
            raise RuntimeError("identity not found; call store_keys first")
        pre_keys_map = payload.setdefault("pre_keys", {})
        if not isinstance(pre_keys_map, dict):
            pre_keys_map = {}
            payload["pre_keys"] = pre_keys_map
        for pk in pre_keys:
            pre_keys_map[str(int(pk.id))] = _encode_key_pair(pk.key)
        self._store_user_payload(username, payload)

    def remove_pre_key(self, username: str, key_id: int) -> None:
        payload = self._load_user_payload(username)
        if not payload:
            return
        pre_keys_map = payload.get("pre_keys")
        if isinstance(pre_keys_map, dict) and str(int(key_id)) in pre_keys_map:
            pre_keys_map.pop(str(int(key_id)), None)
            self._store_user_payload(username, payload)

    def update_signed_pre_key(
        self, username: str, signed_pre_key: SignalSignedPreKey | None
    ) -> None:
        payload = self._load_user_payload(username)
        if payload is None:
            raise RuntimeError("identity not found; call store_keys first")
        if signed_pre_key is None:
            payload.pop("signed_pre_key", None)
        else:
            payload["signed_pre_key"] = {
                "id": int(signed_pre_key.id),
                "timestamp": int(signed_pre_key.timestamp),
                "signature": signed_pre_key.signature.hex(),
                "key": _encode_key_pair(signed_pre_key.key),
            }
        self._store_user_payload(username, payload)

    def record_remote_identity(
        self, username: str, peer: str, device_id: int, identity: bytes
    ) -> None:
        payload = self._load_user_payload(username)
        if payload is None:
            payload = {}
        remote_map = payload.setdefault("remote_identities", {})
        if not isinstance(remote_map, dict):
            remote_map = {}
            payload["remote_identities"] = remote_map
        remote_map[f"{peer}#{device_id}"] = identity.hex()
        self._store_user_payload(username, payload)

    def get_remote_identity(
        self, username: str, peer: str, device_id: int
    ) -> Optional[bytes]:
        payload = self._load_user_payload(username)
        if not payload:
            return None
        remote_map = payload.get("remote_identities")
        if not isinstance(remote_map, dict):
            return None
        encoded = remote_map.get(f"{peer}#{device_id}")
        if isinstance(encoded, str):
            return _decode_bytes(encoded)
        return None

    def store_sender_key(self, username: str, record: SenderKeyRecord) -> None:
        payload = self._load_user_payload(username) or {}
        sender_map = payload.setdefault("sender_keys", {})
        if not isinstance(sender_map, dict):
            sender_map = {}
            payload["sender_keys"] = sender_map
        sender_map[record.index()] = _encode_sender_key_record(record)
        self._store_user_payload(username, payload)

    def list_sender_keys(
        self, username: str, *, room_name: Optional[str] = None
    ) -> list[SenderKeyRecord]:
        payload = self._load_user_payload(username)
        if not payload:
            return []
        sender_map = payload.get("sender_keys")
        if not isinstance(sender_map, dict):
            return []
        records: list[SenderKeyRecord] = []
        for entry in sender_map.values():
            if not isinstance(entry, dict):
                continue
            decoded = _decode_sender_key_record(entry)
            if decoded is None:
                continue
            if room_name and decoded.room_name != room_name:
                continue
            records.append(decoded)
        return records

    def remove_sender_key(self, username: str, record: SenderKeyRecord) -> None:
        payload = self._load_user_payload(username)
        if not payload:
            return
        sender_map = payload.get("sender_keys")
        if not isinstance(sender_map, dict):
            return
        key = record.index()
        if key in sender_map:
            sender_map.pop(key, None)
            self._store_user_payload(username, payload)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._data = {"users": {}}
            return
        except Exception:
            self._data = {"users": {}}
            return
        try:
            parsed = json.loads(raw)
        except Exception:
            self._data = {"users": {}}
            return
        if not isinstance(parsed, dict):
            parsed = {"users": {}}
        parsed.setdefault("users", {})
        if not isinstance(parsed["users"], dict):
            parsed["users"] = {}
        self._data = parsed

    def _load_user_payload(self, username: str) -> Optional[Dict[str, object]]:
        self._ensure_loaded()
        users = self._data.setdefault("users", {})
        if not isinstance(users, dict):
            self._data["users"] = users = {}
        payload = users.get(username)
        return payload if isinstance(payload, dict) else None

    def _store_user_payload(self, username: str, payload: Dict[str, object]) -> None:
        self._ensure_loaded()
        users = self._data.setdefault("users", {})
        if not isinstance(users, dict):
            users = {}
            self._data["users"] = users
        users[username] = payload
        self._persist()

    def _persist(self) -> None:
        path = self._path
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)
