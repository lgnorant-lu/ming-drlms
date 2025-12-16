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
from . import compression  # Phase 23: Compression integration
from .. import log

logger = log.get_logger("core.e2ee_runtime")

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
        # Independent read-path store/builder/cipher for decrypting cached
        # sender keys. When running in a constrained or mocked environment
        # (e.g. tests with MagicMocks instead of a real C bridge), these may
        # fail to initialise; in that case we gracefully degrade to using the
        # main store/cipher only.
        self._read_store: SignalStore | None = None
        self._group_builder_read: GroupSessionBuilder | None = None
        self._group_cipher_read: GroupCipher | None = None
        try:
            read_store = SignalStore(self._context)
            builder_read = GroupSessionBuilder(read_store, self._context)
            cipher_read = GroupCipher(read_store)
        except Exception as exc:  # pragma: no cover - defensive, mainly for tests
            try:
                logger.debug("E2EEngine read-path initialisation failed: %s", exc)
            except Exception:
                pass
        else:
            self._read_store = read_store
            self._group_builder_read = builder_read
            self._group_cipher_read = cipher_read
        self._group_sender_keys: Dict[str, SenderKeyRecord] = {}
        self._group_distribution_targets: Dict[str, set[str]] = {}
        self._load_cached_sender_keys()
        self._initialise_signal_store()
        # When read-path store creation fails (e.g. under MagicMock-based
        # tests), fall back to initialising only the primary store.
        target_store = self._read_store or self._store
        self._initialise_signal_store_for(target_store)
        self._restore_sender_keys_into_store()
        try:
            logger.debug(
                "E2EEngine initialised: user=%s device_id=%s sender_keys=%d",
                self._username,
                getattr(self._state, "device_id", None),
                len(getattr(self._state, "sender_keys", {}) or {}),
            )
        except Exception:
            pass

        # Phase 27: PQC key cache for hybrid encryption
        self._peer_pqc_keys: Dict[str, bytes] = {}  # peer -> ML-KEM-768 public key
        self._my_pqc_kem = None  # Lazy-loaded ML-KEM instance for decryption

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def encrypt(self, peer: str, plaintext: bytes) -> room_pb2.SignalEncryptedPayload:
        session = self._ensure_session(peer)
        try:
            logger.debug(
                "E2EE encrypt: user=%s peer=%s dev=%s len=%s",
                self._username,
                session.name,
                session.device_id,
                len(plaintext) if hasattr(plaintext, "__len__") else None,
            )
        except Exception:
            pass
        # Phase 23: Compression
        # 尝试压缩明文
        compressed_text, comp_type = compression.compress(plaintext, min_size=128)

        result = self._store.encrypt(session.name, session.device_id, compressed_text)
        payload = room_pb2.SignalEncryptedPayload()
        payload.type = proto_type_from_lib(result.message_type)
        payload.ciphertext = result.ciphertext  # type: ignore[attr-defined]
        payload.compression_type = int(comp_type)  # type: ignore[attr-defined]
        payload.sender = self._username  # type: ignore[attr-defined]
        payload.sender_device_id = self._state.device_id  # type: ignore[attr-defined]
        payload.sender_registration_id = self._state.registration_id  # type: ignore[attr-defined]
        if result.pre_key_id is not None:
            payload.pre_key_id = int(result.pre_key_id)  # type: ignore[attr-defined]
        if result.signed_pre_key_id is not None:
            payload.signed_pre_key_id = int(result.signed_pre_key_id)  # type: ignore[attr-defined]
        try:
            logger.debug(
                "E2EE encrypt result: type=%s pre_key=%s signed_pre_key=%s",
                result.message_type,
                result.pre_key_id,
                result.signed_pre_key_id,
            )
        except Exception:
            pass
        # 将远端身份写入密钥仓库，便于后续校验
        identity = self._store.get_remote_identity(session.name, session.device_id)
        if identity:
            self._key_store.record_remote_identity(
                self._username, session.name, session.device_id, identity
            )

        # Phase 27: Hybrid PQC encryption layer
        peer_pqc_pub = self._peer_pqc_keys.get(peer)
        if peer_pqc_pub and len(peer_pqc_pub) == 1184:
            try:
                from .hybrid_crypto import hybrid_encrypt, is_hybrid_available

                if is_hybrid_available():
                    # Get peer's X25519 public key for hybrid encryption
                    peer_x25519_pub = (
                        identity[:32] if identity and len(identity) >= 32 else None
                    )
                    if peer_x25519_pub:
                        hybrid_result = hybrid_encrypt(
                            payload.ciphertext,  # Wrap Signal ciphertext
                            peer_x25519_pub,
                            peer_pqc_pub,
                        )
                        payload.pqc_ciphertext = hybrid_result.pqc_ciphertext
                        payload.pqc_ephemeral = hybrid_result.ephemeral_pub
                        payload.pqc_wrapped = hybrid_result.wrapped_ciphertext
                        # Clear original ciphertext (now in pqc_wrapped)
                        payload.ciphertext = b""
                        logger.debug(
                            "Phase 27: Applied hybrid PQC encryption for %s", peer
                        )
            except Exception as e:
                logger.warning(
                    "Phase 27: Hybrid encryption failed, using classic: %s", e
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
        try:
            logger.debug(
                "E2EE encrypt_group start: room=%s gid=%s sender=%s dev=%s len=%s",
                room_name,
                group_id,
                self._username,
                self._state.device_id,
                len(plaintext) if hasattr(plaintext, "__len__") else None,
            )
        except Exception:
            pass
        result = self._group_cipher.encrypt(name, plaintext)
        payload = room_pb2.SignalEncryptedPayload()
        payload.type = room_pb2.SignalCiphertextType.SIGNAL_CIPHERTEXT_TYPE_MESSAGE  # type: ignore[attr-defined]
        payload.ciphertext = result.ciphertext  # type: ignore[attr-defined]
        payload.sender = self._username  # type: ignore[attr-defined]
        payload.sender_device_id = self._state.device_id  # type: ignore[attr-defined]
        payload.sender_registration_id = self._state.registration_id  # type: ignore[attr-defined]
        payload.group_id = group_id  # type: ignore[attr-defined]
        payload.sender_key_iteration = result.iteration  # type: ignore[attr-defined]
        try:
            logger.debug(
                "E2EE encrypt_group done: gid=%s iter=%s ct_len=%s",
                group_id,
                result.iteration,
                len(result.ciphertext)
                if hasattr(result.ciphertext, "__len__")
                else None,
            )
        except Exception:
            pass
        return payload

    def decrypt(self, event: room_pb2.SignalEncryptedPayload) -> DecryptResult:
        # The type hint `event: RoomEvent` is misleading here.
        # Based on usage, `event` is expected to be `room_pb2.SignalEncryptedPayload`.
        # The `RoomEvent` dataclass in `mproto_v2_client.py` has `payload: bytes`,
        # but this `decrypt` method expects a structured object with fields like `sender`, `payload_type`, etc.
        # The `event.payload` used below refers to the `ciphertext` field of `SignalEncryptedPayload`.
        peer = event.sender or ""
        device_id = event.sender_device_id or 1
        try:
            logger.debug(
                "E2EE decrypt: room=%s peer=%s dev=%s payload_len=%s type=%s",
                getattr(
                    event, "room_name", "N/A"
                ),  # RoomEvent has room_name, SignalEncryptedPayload does not
                peer,
                device_id,
                len(event.ciphertext) if event.ciphertext else 0,
                event.type,
            )
        except Exception:
            pass

        # Phase 27: Check for hybrid PQC encryption
        signal_ciphertext = event.ciphertext
        if event.pqc_wrapped and len(event.pqc_wrapped) > 0:
            try:
                from .hybrid_crypto import hybrid_decrypt

                # Need my X25519 private key and PQC KEM instance
                my_x25519_priv = self._state.identity_key.private_key

                # Lazy-load my PQC KEM instance
                if self._my_pqc_kem is None:
                    pqc_pub = getattr(self._state, "pqc_public_key", None)
                    if pqc_pub:
                        # PQC decryption requires secret key storage
                        # which is not yet implemented (NYI)
                        # MLKEM768 instance needed here would require
                        # importing the secret key from storage
                        logger.warning(
                            "Phase 27: PQC decryption requires secret key storage (NYI)"
                        )

                if self._my_pqc_kem is not None:
                    signal_ciphertext = hybrid_decrypt(
                        event.pqc_wrapped,
                        event.pqc_ciphertext,
                        event.pqc_ephemeral,
                        my_x25519_priv,
                        self._my_pqc_kem,
                    )
                    logger.debug("Phase 27: Decrypted hybrid PQC message from %s", peer)
                else:
                    # Fallback: use pqc_wrapped directly if we can't decrypt
                    # This shouldn't happen in production
                    logger.warning(
                        "Phase 27: No PQC KEM available, cannot decrypt hybrid message"
                    )
                    raise SignalBridgeError(
                        "Cannot decrypt PQC-encrypted message: no PQC key"
                    )
            except ImportError:
                logger.warning("Phase 27: hybrid_crypto import failed")
                raise SignalBridgeError(
                    "Cannot decrypt PQC-encrypted message: liboqs not available"
                )

        cipher = Ciphertext(
            ciphertext=signal_ciphertext,
            message_type=lib_type_from_proto(event.type),
            registration_id=int(event.sender_registration_id or 0),
            pre_key_id=int(event.pre_key_id or 0),
            signed_pre_key_id=int(event.signed_pre_key_id or 0),
        )
        result = self._store.decrypt(
            peer,
            device_id,
            cipher,
        )
        logger.debug(
            "E2EE decrypt: peer=%s dev=%s msg_type=%s pre_key_id=%s",
            peer,
            device_id,
            result.info.message_type,
            result.info.pre_key_id,
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

        # Phase 23: Decompression
        comp_type = getattr(event, "compression_type", 0)
        plaintext = compression.decompress(result.plaintext, comp_type)
        result.plaintext = plaintext

        try:
            logger.debug(
                "E2EE decrypt done: peer=%s dev=%s msg_type=%s pre_key_id=%s len=%d",
                peer,
                device_id,
                result.info.message_type,
                result.info.pre_key_id,
                len(plaintext),
            )
        except Exception:
            pass
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
        try:
            logger.debug(
                "E2EE decrypt_group: room=%s gid=%s sender=%s dev=%s payload_len=%s",
                event.room_name,
                group_id,
                sender,
                device_id,
                len(event.payload) if hasattr(event.payload, "__len__") else None,
            )
        except Exception:
            pass
        # Prefer the dedicated read-path cipher when available; otherwise
        # fall back to the main group cipher (useful in test environments
        # where only the primary cipher is mocked).
        cipher = self._group_cipher_read or self._group_cipher
        if cipher is None:  # pragma: no cover - should not happen in normal usage
            raise SignalBridgeError("group cipher unavailable")
        return cipher.decrypt(name, event.payload)

    def close(self) -> None:
        self._store.close()
        try:
            if self._read_store is not None:
                self._read_store.close()
        except Exception:
            pass
        self._context.close()
        if self._group_builder is not None:
            self._group_builder.close()
            self._group_builder = None
        if self._group_builder_read is not None:
            self._group_builder_read.close()
            self._group_builder_read = None

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

    def _initialise_signal_store_for(self, store: SignalStore) -> None:
        state = self._state
        store.set_identity(
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
            store.put_signed_pre_key_record(
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
            store.put_pre_key_record(key_id, encoded)

    def _load_cached_sender_keys(self) -> None:
        sender_keys = getattr(self._state, "sender_keys", {}) or {}
        for record in sender_keys.values():
            self._group_sender_keys[record.index()] = record

    def _restore_sender_keys_into_store(self) -> None:
        sender_keys = getattr(self._state, "sender_keys", {}) or {}
        for record in sender_keys.values():
            try:
                name = SenderKeyName(
                    group_id=record.group_id,
                    sender=record.sender,
                    device_id=int(record.sender_device_id),
                )
                if record.sender == self._username:
                    blob = getattr(record, "record_blob", None)
                    if blob:
                        c_name, _refs = name.to_c_struct(self._store._ffi)
                        try:
                            self._store._lib.drlms_sender_key_record_import(
                                self._store.handle,
                                c_name,
                                blob,
                                len(blob),
                            )
                        except Exception:
                            pass
                    try:
                        if self._group_builder_read is not None:
                            self._group_builder_read.process_session(
                                name, record.distribution
                            )
                    except Exception:
                        pass
                    else:
                        try:
                            self._key_store.remove_sender_key(self._username, record)
                        except Exception:
                            pass
                else:
                    try:
                        if self._group_builder_read is not None:
                            self._group_builder_read.process_session(
                                name, record.distribution
                            )
                    except Exception:
                        pass
            except Exception:
                pass

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

        # Phase 27: Cache peer's PQC public key if available
        pqc_pub = getattr(bundle, "pqc_public_key", None)
        if pqc_pub and len(pqc_pub) == 1184:
            self._peer_pqc_keys[peer] = pqc_pub
            logger.debug("Phase 27: Cached PQC public key for %s", peer)

        session = _PeerSession(name=peer, device_id=int(bundle.device_id or 1))
        self._sessions[key] = session
        return session

    def _sender_key_index(self, room_name: str, group_id: str) -> str:
        return f"{room_name}|{group_id}|{self._username}|{self._state.device_id}"

    def _group_distribution_key(self, room_name: str, group_id: str) -> str:
        return f"{room_name}|{group_id}"

    def _ensure_sender_key(self, room_name: str, group_id: str) -> SenderKeyRecord:
        index = self._sender_key_index(room_name, group_id)
        if not self._group_builder:
            raise SignalBridgeError("group session builder unavailable")
        name = SenderKeyName(
            group_id=group_id,
            sender=self._username,
            device_id=self._state.device_id,
        )
        distribution = self._group_builder.create_session(name)
        try:
            logger.debug(
                "E2EE ensure_sender_key: room=%s gid=%s sender=%s dev=%s key_id=%s iter=%s dist_len=%s",
                room_name,
                group_id,
                self._username,
                self._state.device_id,
                distribution.key_id,
                distribution.iteration,
                len(distribution.bytes)
                if hasattr(distribution.bytes, "__len__")
                else None,
            )
        except Exception:
            pass
        blob_bytes: bytes | None = None
        try:
            c_name, _refs = name.to_c_struct(self._store._ffi)
            out_ptr = self._store._ffi.new("uint8_t **")
            out_len = self._store._ffi.new("size_t *")
            rc = self._store._lib.drlms_sender_key_record_export(
                self._store.handle, c_name, out_ptr, out_len
            )
            if rc == 0 and out_ptr[0] != self._store._ffi.NULL and int(out_len[0]) > 0:
                # Copy out-of-line blob into Python-managed bytes. The C heap
                # allocation is intentionally left to be reclaimed at process
                # teardown to avoid cross-CRT free() issues on Windows.
                blob_bytes = bytes(self._store._ffi.buffer(out_ptr[0], int(out_len[0])))
        except Exception:
            blob_bytes = None
        record = SenderKeyRecord(
            room_name=room_name,
            group_id=group_id,
            sender=self._username,
            sender_device_id=self._state.device_id,
            sender_registration_id=self._state.registration_id,
            sender_key_id=distribution.key_id,
            sender_key_iteration=distribution.iteration,
            distribution=distribution.bytes,
            record_blob=blob_bytes,
        )
        self._key_store.store_sender_key(self._username, record)
        self._group_sender_keys[index] = record
        self._state.sender_keys[index] = record
        try:
            if self._group_builder_read is not None:
                self._group_builder_read.process_session(name, record.distribution)
        except Exception:
            pass
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
        try:
            logger.debug(
                "E2EE process_sender_key_distribution: room=%s gid=%s sender=%s dev=%s key_id=%s iter=%s len=%s",
                distribution.room_name,
                distribution.group_id,
                distribution.sender,
                distribution.sender_device_id,
                distribution.sender_key_id,
                distribution.sender_key_iteration,
                len(distribution.distribution_message)
                if hasattr(distribution.distribution_message, "__len__")
                else None,
            )
        except Exception:
            pass
        self._group_builder.process_session(name, distribution.distribution_message)
        try:
            if self._group_builder_read is not None:
                self._group_builder_read.process_session(
                    name, distribution.distribution_message
                )
        except Exception:
            pass

        logger.info(
            "Phase 24: Processing Sender Key from %s for room %s (key_id=%s)",
            distribution.sender,
            distribution.room_name,
            distribution.sender_key_id,
        )

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

        # Phase 24 FIX: Remove deduplication check to ensure key is ALWAYS distributed
        # Previous bug: if bob joins empty room (0 members), cache says "distributed to []"
        # Then alice joins, but bob never redistributes because cache thinks it's done
        # Solution: Always distribute, let network/protocol handle duplicates if any

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

        # Phase 24 CRITICAL FIX: Use a SEPARATE MP2Client connection for sender key push
        # The main self._client is used by the subscription loop, so we cannot use it
        # for request-response operations without causing socket data corruption.
        try:
            from .mproto_v2_client import MP2Client

            temp_client = MP2Client(
                host=self._client.host,
                port=self._client.port,
                timeout=10.0,
                token_store=self._client._token_store,
            )
            try:
                code, message = temp_client.e2ee_sender_key_push(
                    self._username, target_user, distribution
                )
            finally:
                temp_client.close()
        except Exception as e:
            logger.warning(
                "Phase 24: distribute_sender_key temp client failed: %s, retrying with main client",
                e,
            )
            # Fallback to main client (may still fail due to socket contention)
            code, message = self._client.e2ee_sender_key_push(
                self._username, target_user, distribution
            )

        if code != 0:
            raise SignalBridgeError(
                f"sender key push to {target_user} failed: {code} {message}"
            )
        try:
            logger.info(
                "Phase 24: Distributed Sender Key: room=%s target=%s key_id=%s iter=%s",
                room_name,
                target_user,
                record.sender_key_id,
                record.sender_key_iteration,
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Phase 24: Sender Key 自动请求机制
    # -------------------------------------------------------------------------

    def request_sender_keys_for_room(
        self,
        room_name: str,
        group_id: str,
        members: list[tuple[str, int]],
    ) -> None:
        """Request Sender Keys from all room members.

        Called when subscribing to a room to ensure we can decrypt messages
        from all existing members. Phase 24 MVP records missing keys and
        logs warnings; automatic distribution happens when members next send.

        Args:
            room_name: Room name
            group_id: Group ID (usually same as room_name)
            members: List of (username, device_id) tuples
        """
        missing_members: list[tuple[str, int]] = []
        for username, device_id in members:
            if username == self._username:
                continue

            index = f"{room_name}|{group_id}|{username}|{device_id}"
            if index in self._group_sender_keys:
                try:
                    logger.debug(
                        "E2EE already have sender_key: room=%s user=%s dev=%s",
                        room_name,
                        username,
                        device_id,
                    )
                except Exception:
                    pass
                continue

            missing_members.append((username, device_id))
            try:
                logger.info(
                    "E2EE missing sender_key: room=%s user=%s dev=%s",
                    room_name,
                    username,
                    device_id,
                )
            except Exception:
                pass

        if missing_members:
            try:
                logger.warning(
                    "E2EE room=%s missing sender_keys from %d members: %s - sending requests",
                    room_name,
                    len(missing_members),
                    missing_members[:5],
                )
            except Exception:
                pass

            for username, device_id in missing_members:
                dist = SignalSenderKeyDistribution(
                    room_name=room_name,
                    group_id=group_id,
                    sender=self._username,
                    sender_device_id=1,  # TODO: get actual device_id
                    sender_registration_id=0,
                    distribution_message=b"",
                    sender_key_id=0,
                    sender_key_iteration=0,
                )
                try:
                    self._client.e2ee_sender_key_request(
                        self._username,
                        username,
                        dist,
                    )
                    logger.debug("Sent sender_key_request to %s", username)
                except Exception as e:
                    logger.error(
                        "Failed to request sender key from %s: %s", username, e
                    )

    def handle_sender_key_request(
        self,
        room_name: str,
        group_id: str,
        requester: str,
        requester_device: int,
    ) -> None:
        """Handle incoming Sender Key Request from another user.

        Automatically re-distribute Sender Key to the requester.

        Args:
            room_name: Room name
            group_id: Group ID
            requester: Username of requester
            requester_device: Device ID of requester (currently unused)
        """
        _ = requester_device  # Reserved for future use
        try:
            logger.debug(
                "E2EE handle_sender_key_request: room=%s from=%s dev=%s",
                room_name,
                requester,
                requester_device,
            )
        except Exception:
            pass

        try:
            self.distribute_sender_key(
                room_name=room_name,
                group_id=group_id,
                target_user=requester,
            )
            try:
                logger.info(
                    "E2EE responded to sender_key_request: room=%s to=%s",
                    room_name,
                    requester,
                )
            except Exception:
                pass
        except Exception as e:
            try:
                logger.error(
                    "E2EE failed to handle sender_key_request: room=%s from=%s error=%s",
                    room_name,
                    requester,
                    e,
                )
            except Exception:
                pass
