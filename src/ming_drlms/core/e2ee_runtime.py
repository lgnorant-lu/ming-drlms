"""E2EE 运行时，用于协调 Signal CFFI、密钥仓库与 MP2 客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ming_drlms.proto.schema.v2 import room_pb2

from .e2ee_store import LocalKeyState, LocalKeyStore
from .mproto_v2_client import MP2Client, RoomEvent
from .pysignal import (
    Ciphertext,
    DecryptResult,
    SignalBridgeError,
    SignalStore,
    create_signal_context,
    encode_pre_key_record,
    encode_signed_pre_key_record,
)

_LIB_SIGNAL_MESSAGE_TYPE = 2
_LIB_SIGNAL_PRE_KEY_TYPE = 3


def lib_type_from_proto(payload_type: Optional[int]) -> int:
    if payload_type == room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY:
        return _LIB_SIGNAL_PRE_KEY_TYPE
    return _LIB_SIGNAL_MESSAGE_TYPE


def proto_type_from_lib(lib_type: int) -> int:
    if lib_type == _LIB_SIGNAL_PRE_KEY_TYPE:
        return room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY
    return room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE


@dataclass(slots=True)
class _PeerSession:
    name: str
    device_id: int


class E2EEngine:
    """封装 Signal 会话生命周期，支持加密与解密。"""

    def __init__(
        self,
        *,
        username: str,
        key_store: LocalKeyStore,
        mp2_client: MP2Client,
    ) -> None:
        self._username = username
        self._key_store = key_store
        self._client = mp2_client
        self._context = create_signal_context()
        self._store = SignalStore(self._context)
        self._state = self._load_local_state()
        self._sessions: Dict[Tuple[str, int], _PeerSession] = {}
        self._initialise_signal_store()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def encrypt(self, peer: str, plaintext: bytes) -> room_pb2.SignalEncryptedPayload:
        session = self._ensure_session(peer)
        result = self._store.encrypt(session.name, session.device_id, plaintext)
        payload = room_pb2.SignalEncryptedPayload()
        payload.type = proto_type_from_lib(result.message_type)
        payload.ciphertext = result.ciphertext
        payload.sender = self._username
        payload.sender_device_id = self._state.device_id
        payload.sender_registration_id = self._state.registration_id
        if result.pre_key_id is not None:
            payload.pre_key_id = int(result.pre_key_id)
        if result.signed_pre_key_id is not None:
            payload.signed_pre_key_id = int(result.signed_pre_key_id)
        # 将远端身份写入密钥仓库，便于后续校验
        identity = self._store.get_remote_identity(session.name, session.device_id)
        if identity:
            self._key_store.record_remote_identity(
                self._username, session.name, session.device_id, identity
            )
        return payload

    def decrypt(self, event: RoomEvent) -> DecryptResult:
        peer = event.sender or ""
        device_id = event.sender_device_id or 1
        cipher = Ciphertext(
            ciphertext=event.payload,
            message_type=lib_type_from_proto(event.payload_type),
            registration_id=int(event.sender_registration_id or 0),
            pre_key_id=int(event.pre_key_id or 0),
            signed_pre_key_id=int(event.signed_pre_key_id or 0),
        )
        result = self._store.decrypt(
            peer,
            device_id,
            cipher,
        )
        # 记录远端身份
        identity = self._store.get_remote_identity(peer, device_id)
        if identity:
            self._key_store.record_remote_identity(
                self._username, peer, device_id, identity
            )
        # 如果预密钥被消费，从仓库中移除
        if (
            result.info.message_type == _LIB_SIGNAL_PRE_KEY_TYPE
            and result.info.pre_key_id is not None
        ):
            self._key_store.remove_pre_key(self._username, int(result.info.pre_key_id))
        return result

    def close(self) -> None:
        self._store.close()
        self._context.close()

    # ------------------------------------------------------------------
    # 内部流程
    # ------------------------------------------------------------------
    def _load_local_state(self) -> LocalKeyState:
        state = self._key_store.load_state(self._username)
        if state is None:
            raise SignalBridgeError(
                f"未找到本地密钥，请先为用户 {self._username} 生成端到端密钥"
            )
        return state

    def _initialise_signal_store(self) -> None:
        state = self._state
        self._store.set_identity(
            public_key=state.identity_key.public_key,
            private_key=state.identity_key.private_key,
            registration_id=state.registration_id,
            device_id=state.device_id,
        )
        if state.signed_pre_key is not None:
            encoded = encode_signed_pre_key_record(
                self._context,
                key_id=state.signed_pre_key.id,
                timestamp=state.signed_pre_key.timestamp,
                public_key=state.signed_pre_key.key.public_key,
                private_key=state.signed_pre_key.key.private_key,
                signature=state.signed_pre_key.signature,
            )
            self._store.put_signed_pre_key_record(
                state.signed_pre_key.id,
                encoded,
            )
        for key_id, pair in state.pre_keys.items():
            encoded = encode_pre_key_record(
                self._context,
                key_id=key_id,
                public_key=pair.public_key,
                private_key=pair.private_key,
            )
            self._store.put_pre_key_record(key_id, encoded)

    def _ensure_session(self, peer: str) -> _PeerSession:
        key = (peer, 1)
        if key in self._sessions:
            return self._sessions[key]
        bundle = self._client.e2ee_fetch_prekey_bundle(self._username, peer)
        if bundle.code != 0:
            raise SignalBridgeError(
                f"获取用户 {peer} 的预密钥失败: {bundle.code} {bundle.message}"
            )
        if not bundle.identity_key:
            raise SignalBridgeError("预密钥包缺少远端身份公钥")

        existing = self._key_store.get_remote_identity(
            self._username, peer, int(bundle.device_id or 1)
        )
        if existing is not None and existing != bundle.identity_key:
            raise SignalBridgeError(f"检测到 {peer} 的身份公钥发生变化，拒绝建立会话")

        self._store.process_prekey_bundle(
            name=peer,
            device_id=int(bundle.device_id or 1),
            registration_id=int(bundle.registration_id),
            identity_key=bundle.identity_key,
            pre_key_id=int(bundle.pre_key_id),
            pre_key_public=bundle.pre_key_public or b"",
            signed_pre_key_id=int(bundle.signed_pre_key_id),
            signed_pre_key_public=bundle.signed_pre_key_public or b"",
            signed_pre_key_signature=bundle.signed_pre_key_signature or b"",
        )

        self._key_store.record_remote_identity(
            self._username,
            peer,
            int(bundle.device_id or 1),
            bundle.identity_key,
        )

        session = _PeerSession(name=peer, device_id=int(bundle.device_id or 1))
        self._sessions[key] = session
        return session
