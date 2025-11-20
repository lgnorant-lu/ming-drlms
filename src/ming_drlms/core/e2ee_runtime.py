"""E2EE 运行时，用于协调 Signal CFFI、密钥仓库与 MP2 客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ming_drlms.proto.schema.v2 import room_pb2

from .e2ee_store import LocalKeyState, LocalKeyStore, SenderKeyRecord
from .mproto_v2_client import (
    MP2Client,
    RoomEvent,
    SignalSenderKeyDistribution,
)
from .pysignal import (
    Ciphertext,
    DecryptResult,
    GroupCipher,
    GroupDecryptResult,
    GroupSessionBuilder,
    SenderKeyName,
    SignalBridgeError,
    SignalContext,
    SignalStore,
    create_signal_context,
    encode_pre_key_record,
    encode_signed_pre_key_record,
)

_LIB_SIGNAL_MESSAGE_TYPE = 2
_LIB_SIGNAL_PRE_KEY_TYPE = 3


def lib_type_from_proto(payload_type: Optional[int]) -> int:
    if payload_type == room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY:  # type: ignore[attr-defined]
        return _LIB_SIGNAL_PRE_KEY_TYPE
    return _LIB_SIGNAL_MESSAGE_TYPE


def proto_type_from_lib(lib_type: int) -> int:
    if lib_type == _LIB_SIGNAL_PRE_KEY_TYPE:
        return room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_PREKEY  # type: ignore[attr-defined]
    return room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE  # type: ignore[attr-defined]


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
        signal_context: SignalContext | None = None,
        signal_store: SignalStore | None = None,
        group_builder: GroupSessionBuilder | None = None,
        group_cipher: GroupCipher | None = None,
    ) -> None:
        self._username = username
        self._key_store = key_store
        self._client = mp2_client
        self._context = (
            signal_context if signal_context is not None else create_signal_context()
        )
        self._store = (
            signal_store if signal_store is not None else SignalStore(self._context)
        )
        self._state = self._load_local_state()
        self._sessions: Dict[Tuple[str, int], _PeerSession] = {}
        self._group_builder: GroupSessionBuilder | None = (
            group_builder
            if group_builder is not None
            else GroupSessionBuilder(self._store, self._context)
        )
        self._group_cipher = (
            group_cipher if group_cipher is not None else GroupCipher(self._store)
        )
        self._group_sender_keys: Dict[str, SenderKeyRecord] = {}
        self._group_distribution_targets: Dict[str, set[str]] = {}
        self._load_cached_sender_keys()
        self._initialise_signal_store()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def encrypt(self, peer: str, plaintext: bytes) -> room_pb2.SignalEncryptedPayload:
        session = self._ensure_session(peer)
        result = self._store.encrypt(session.name, session.device_id, plaintext)
        payload = room_pb2.SignalEncryptedPayload()
        payload.type = proto_type_from_lib(result.message_type)
        payload.ciphertext = result.ciphertext  # type: ignore[attr-defined]
        payload.sender = self._username  # type: ignore[attr-defined]
        payload.sender_device_id = self._state.device_id  # type: ignore[attr-defined]
        payload.sender_registration_id = self._state.registration_id  # type: ignore[attr-defined]
        if result.pre_key_id is not None:
            payload.pre_key_id = int(result.pre_key_id)  # type: ignore[attr-defined]
        if result.signed_pre_key_id is not None:
            payload.signed_pre_key_id = int(result.signed_pre_key_id)  # type: ignore[attr-defined]
        # 将远端身份写入密钥仓库，便于后续校验
        identity = self._store.get_remote_identity(session.name, session.device_id)
        if identity:
            self._key_store.record_remote_identity(
                self._username, session.name, session.device_id, identity
            )
        return payload

    def encrypt_group(
        self, room_name: str, group_id: str, plaintext: bytes
    ) -> room_pb2.SignalEncryptedPayload:
        record = self._ensure_sender_key(room_name, group_id)
        _ = record  # keep reference for clarity
        name = SenderKeyName(
            group_id=group_id,
            sender=self._username,
            device_id=self._state.device_id,
        )
        result = self._group_cipher.encrypt(name, plaintext)
        payload = room_pb2.SignalEncryptedPayload()
        payload.type = room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE  # type: ignore[attr-defined]
        payload.ciphertext = result.ciphertext  # type: ignore[attr-defined]
        payload.sender = self._username  # type: ignore[attr-defined]
        payload.sender_device_id = self._state.device_id  # type: ignore[attr-defined]
        payload.sender_registration_id = self._state.registration_id  # type: ignore[attr-defined]
        payload.group_id = group_id  # type: ignore[attr-defined]
        payload.sender_key_iteration = result.iteration  # type: ignore[attr-defined]
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

    def decrypt_group(self, event: RoomEvent) -> GroupDecryptResult:
        if not event.payload:
            raise SignalBridgeError("group event payload 为空")
        group_id = event.group_id or event.room_name
        if not group_id:
            raise SignalBridgeError("无法确定群聊标识")
        sender = event.sender or ""
        if not sender:
            raise SignalBridgeError("群聊事件缺少 sender")
        device_id = int(event.sender_device_id or 1)
        name = SenderKeyName(
            group_id=group_id,
            sender=sender,
            device_id=device_id,
        )
        return self._group_cipher.decrypt(name, event.payload)

    def close(self) -> None:
        self._store.close()
        self._context.close()
        if self._group_builder is not None:
            self._group_builder.close()
            self._group_builder = None

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

    def _load_cached_sender_keys(self) -> None:
        sender_keys = getattr(self._state, "sender_keys", {}) or {}
        for record in sender_keys.values():
            self._group_sender_keys[record.index()] = record

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

    def _sender_key_index(self, room_name: str, group_id: str) -> str:
        return f"{room_name}|{group_id}|{self._username}|{self._state.device_id}"

    def _group_distribution_key(self, room_name: str, group_id: str) -> str:
        return f"{room_name}|{group_id}"

    def _ensure_sender_key(self, room_name: str, group_id: str) -> SenderKeyRecord:
        index = self._sender_key_index(room_name, group_id)
        existing = self._group_sender_keys.get(index)
        if existing is not None:
            return existing
        if not self._group_builder:
            raise SignalBridgeError("group session builder unavailable")
        name = SenderKeyName(
            group_id=group_id,
            sender=self._username,
            device_id=self._state.device_id,
        )
        distribution = self._group_builder.create_session(name)
        record = SenderKeyRecord(
            room_name=room_name,
            group_id=group_id,
            sender=self._username,
            sender_device_id=self._state.device_id,
            sender_registration_id=self._state.registration_id,
            sender_key_id=distribution.key_id,
            sender_key_iteration=distribution.iteration,
            distribution=distribution.bytes,
        )
        self._key_store.store_sender_key(self._username, record)
        self._group_sender_keys[index] = record
        self._state.sender_keys[index] = record
        return record

    def process_sender_key_distribution(
        self, distribution: SignalSenderKeyDistribution
    ) -> None:
        if not self._group_builder:
            raise SignalBridgeError("group session builder unavailable")
        name = SenderKeyName(
            group_id=distribution.group_id,
            sender=distribution.sender,
            device_id=distribution.sender_device_id,
        )
        self._group_builder.process_session(name, distribution.distribution_message)
        record = SenderKeyRecord(
            room_name=distribution.room_name,
            group_id=distribution.group_id,
            sender=distribution.sender,
            sender_device_id=distribution.sender_device_id,
            sender_registration_id=distribution.sender_registration_id,
            sender_key_id=distribution.sender_key_id,
            sender_key_iteration=distribution.sender_key_iteration,
            distribution=distribution.distribution_message,
        )
        index = record.index()
        self._key_store.store_sender_key(self._username, record)
        self._group_sender_keys[index] = record
        self._state.sender_keys[index] = record

    def distribute_sender_key(
        self, room_name: str, group_id: str, target_user: str
    ) -> None:
        if target_user == self._username:
            return
        cache_key = self._group_distribution_key(room_name, group_id)
        sent = self._group_distribution_targets.setdefault(cache_key, set())
        if target_user in sent:
            return
        record = self._ensure_sender_key(room_name, group_id)
        distribution = SignalSenderKeyDistribution(
            room_name=room_name,
            group_id=group_id,
            sender=self._username,
            sender_device_id=self._state.device_id,
            sender_registration_id=self._state.registration_id,
            distribution_message=record.distribution,
            sender_key_id=record.sender_key_id,
            sender_key_iteration=record.sender_key_iteration,
        )
        code, message = self._client.e2ee_sender_key_push(
            self._username, target_user, distribution
        )
        if code != 0:
            raise SignalBridgeError(
                f"sender key push to {target_user} failed: {code} {message}"
            )
        sent.add(target_user)
