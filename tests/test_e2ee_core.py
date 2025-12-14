import os
import tempfile
import shutil
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from ming_drlms.core.e2ee_store import LocalKeyStore, LocalKeyState, SenderKeyRecord
from ming_drlms.core.mproto_v2_client import (
    SignalKeyPair,
    SignalSignedPreKey,
    SignalPreKey,
    MP2Client,
)
from ming_drlms.core.pysignal import (
    SignalContext,
    SignalStore,
    SignalBridgeError,
    GroupSessionBuilder,
    GroupCipher,
)
from ming_drlms.core.e2ee_runtime import E2EEngine


# Helper to create dummy keys
def _make_key_pair() -> SignalKeyPair:
    return SignalKeyPair(public_key=b"pub", private_key=b"priv")


class TestLocalKeyStore:
    @pytest.fixture
    def store_path(self):
        tmp_dir = tempfile.mkdtemp()
        path = Path(tmp_dir) / "test_store.json"
        yield path
        shutil.rmtree(tmp_dir)

    def test_init_creates_empty(self, store_path):
        store = LocalKeyStore(path=store_path)
        assert store._data == {}

    def test_store_and_load_keys(self, store_path):
        store = LocalKeyStore(path=store_path)
        username = "alice"
        identity = _make_key_pair()
        signed_pre_key = SignalSignedPreKey(
            id=1, key=_make_key_pair(), signature=b"sig", timestamp=1234567890
        )
        pre_keys = [
            SignalPreKey(id=1, key=_make_key_pair()),
            SignalPreKey(id=2, key=_make_key_pair()),
        ]

        state = store.store_keys(
            username,
            registration_id=100,
            device_id=1,
            identity=identity,
            signed_pre_key=signed_pre_key,
            pre_keys=pre_keys,
        )

        assert state.registration_id == 100
        assert state.device_id == 1
        assert state.identity_key.public_key == b"pub"
        assert len(state.pre_keys) == 2

        # Reload from disk
        store2 = LocalKeyStore(path=store_path)
        loaded_state = store2.load_state(username)
        assert loaded_state is not None
        assert loaded_state.registration_id == 100
        assert loaded_state.identity_key.public_key == b"pub"
        assert loaded_state.signed_pre_key is not None
        assert loaded_state.signed_pre_key.signature == b"sig"
        assert len(loaded_state.pre_keys) == 2

    def test_remote_identity(self, store_path):
        store = LocalKeyStore(path=store_path)
        username = "alice"
        # Must init user first
        store.store_keys(
            username,
            registration_id=1,
            device_id=1,
            identity=_make_key_pair(),
            signed_pre_key=None,
            pre_keys=[],
        )

        store.record_remote_identity(username, "bob", 1, b"bob_identity")
        fetched = store.get_remote_identity(username, "bob", 1)
        assert fetched == b"bob_identity"

        # Reload
        store2 = LocalKeyStore(path=store_path)
        fetched2 = store2.get_remote_identity(username, "bob", 1)
        assert fetched2 == b"bob_identity"

    def test_sender_keys(self, store_path):
        store = LocalKeyStore(path=store_path)
        username = "alice"

        record = SenderKeyRecord(
            room_name="room1",
            group_id="group1",
            sender="bob",
            sender_device_id=1,
            sender_registration_id=100,
            sender_key_id=5,
            sender_key_iteration=0,
            distribution=b"dist_data",
        )

        store.store_sender_key(username, record)

        keys = store.list_sender_keys(username, room_name="room1")
        assert len(keys) == 1
        assert keys[0].sender == "bob"

        keys_other = store.list_sender_keys(username, room_name="room2")
        assert len(keys_other) == 0

        store.remove_sender_key(username, record)
        keys_empty = store.list_sender_keys(username, room_name="room1")
        assert len(keys_empty) == 0

    def test_update_signed_pre_key(self, store_path):
        store = LocalKeyStore(path=store_path)
        username = "alice"
        store.store_keys(
            username,
            registration_id=1,
            device_id=1,
            identity=_make_key_pair(),
            signed_pre_key=None,
            pre_keys=[],
        )

        new_signed = SignalSignedPreKey(
            id=2, key=_make_key_pair(), signature=b"sig2", timestamp=999
        )
        store.update_signed_pre_key(username, new_signed)

        state = store.load_state(username)
        assert state is not None
        assert state.signed_pre_key is not None
        assert state.signed_pre_key.id == 2

        store.update_signed_pre_key(username, None)
        state = store.load_state(username)
        assert state is not None
        assert state.signed_pre_key is None

    def test_manage_pre_keys(self, store_path):
        store = LocalKeyStore(path=store_path)
        username = "alice"
        store.store_keys(
            username,
            registration_id=1,
            device_id=1,
            identity=_make_key_pair(),
            signed_pre_key=None,
            pre_keys=[],
        )

        new_keys = [SignalPreKey(id=10, key=_make_key_pair())]
        store.add_pre_keys(username, new_keys)

        state = store.load_state(username)
        assert state is not None
        assert 10 in state.pre_keys

        store.remove_pre_key(username, 10)
        state = store.load_state(username)
        assert state is not None
        assert 10 not in state.pre_keys

    def test_corrupt_store(self, store_path):
        store_path.write_text("invalid json", encoding="utf-8")
        store = LocalKeyStore(path=store_path)
        # Should handle gracefully and return empty/None
        assert store.load_state("alice") is None

        # Should overwrite corrupt file on save
        store.store_keys(
            "alice",
            registration_id=1,
            device_id=1,
            identity=_make_key_pair(),
            signed_pre_key=None,
            pre_keys=[],
        )
        assert store.load_state("alice") is not None

    def test_invalid_sender_key_record(self, store_path):
        store = LocalKeyStore(path=store_path)
        username = "alice"

        # Manually inject invalid record
        store._store_user_payload(
            username,
            {
                "sender_keys": {
                    "bad_key": {"room_name": 123}  # Invalid type
                }
            },
        )

        keys = store.list_sender_keys(username)
        assert len(keys) == 0

    def test_default_config_dir(self):
        with patch.dict(os.environ, {"MING_DRLMS_CONFIG_DIR": "/custom/path"}):
            from ming_drlms.core.e2ee_store import _default_config_dir

            assert _default_config_dir() == Path("/custom/path")

    def test_decode_errors(self):
        from ming_drlms.core.e2ee_store import (
            _decode_key_pair,
            _decode_sender_key_record,
        )

        assert _decode_key_pair(None) is None
        assert _decode_key_pair({}) is None  # Missing keys

        # Invalid hex
        with pytest.raises(ValueError):
            _decode_key_pair({"public": "zz", "private": "zz"})

        assert _decode_sender_key_record(None) is None
        assert _decode_sender_key_record({}) is None


class TestE2EEngine:
    @pytest.fixture
    def mock_store(self):
        return MagicMock(spec=LocalKeyStore)

    @pytest.fixture
    def mock_client(self):
        return MagicMock(spec=MP2Client)

    @pytest.fixture
    def mock_signal_context(self):
        return MagicMock(spec=SignalContext)

    @pytest.fixture
    def mock_signal_store(self):
        return MagicMock(spec=SignalStore)

    @pytest.fixture
    def mock_group_builder(self):
        return MagicMock(spec=GroupSessionBuilder)

    @pytest.fixture
    def mock_group_cipher(self):
        return MagicMock(spec=GroupCipher)

    def test_init_loads_state(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup mock store to return a valid state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        assert engine._username == "alice"
        mock_store.load_state.assert_called_with("alice")
        mock_signal_store.set_identity.assert_called()

    def test_init_fails_no_state(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        mock_store.load_state.return_value = None

        with pytest.raises(SignalBridgeError, match="未找到本地密钥"):
            E2EEngine(
                username="alice",
                key_store=mock_store,
                mp2_client=mock_client,
                signal_context=mock_signal_context,
                signal_store=mock_signal_store,
                group_builder=mock_group_builder,
                group_cipher=mock_group_cipher,
            )

    def test_encrypt_ensure_session(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )
        # Setup mock client to return a prekey bundle
        bundle = MagicMock()
        bundle.code = 0
        bundle.device_id = 1
        bundle.registration_id = 100
        bundle.identity_key = b"bob_id"
        bundle.pre_key_id = 1
        bundle.signed_pre_key_id = 1
        mock_client.e2ee_fetch_prekey_bundle.return_value = bundle

        # Setup mock signal store encrypt result
        encrypt_result = MagicMock()
        encrypt_result.message_type = 3  # PREKEY_TYPE
        encrypt_result.ciphertext = b"cipher"
        encrypt_result.pre_key_id = 1
        encrypt_result.signed_pre_key_id = 1
        mock_signal_store.encrypt.return_value = encrypt_result

        # Setup remote identity check
        mock_store.get_remote_identity.return_value = None

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        payload = engine.encrypt("bob", b"hello")

        assert payload.ciphertext == b"cipher"
        mock_client.e2ee_fetch_prekey_bundle.assert_called_with("alice", "bob")
        mock_signal_store.process_prekey_bundle.assert_called()
        mock_store.record_remote_identity.assert_called()

    def test_decrypt(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        # Mock decrypt result
        decrypt_result = MagicMock()
        decrypt_result.info.message_type = 3  # PREKEY_TYPE
        decrypt_result.info.pre_key_id = 1
        decrypt_result.plaintext = (
            b"decrypted"  # Phase 23: Add plaintext for decompression
        )
        mock_signal_store.decrypt.return_value = decrypt_result

        # Mock event with Phase 23 fields
        event = MagicMock()
        event.sender = "bob"
        event.sender_device_id = 1
        event.ciphertext = b"cipher"  # Changed from payload
        event.type = 1  # PREKEY (changed from payload_type)
        event.sender_registration_id = 100
        event.pre_key_id = 1
        event.signed_pre_key_id = 1
        event.compression_type = 0  # Phase 23: No compression

        engine.decrypt(event)

        mock_signal_store.decrypt.assert_called()
        mock_store.remove_pre_key.assert_called_with("alice", 1)

    def test_encrypt_group(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        # Mock group session creation
        distribution = MagicMock()
        distribution.key_id = 1
        distribution.iteration = 0
        distribution.bytes = b"dist"
        mock_group_builder.create_session.return_value = distribution

        # Mock group encrypt
        encrypted = MagicMock()
        encrypted.ciphertext = b"group_cipher"
        encrypted.iteration = 0
        mock_group_cipher.encrypt.return_value = encrypted

        payload = engine.encrypt_group("room1", "group1", b"hello")

        assert payload.ciphertext == b"group_cipher"
        mock_group_builder.create_session.assert_called()
        mock_store.store_sender_key.assert_called()
        mock_group_cipher.encrypt.assert_called()

    def test_decrypt_group(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        event = MagicMock()
        event.payload = b"group_cipher"
        event.group_id = "group1"
        event.sender = "bob"
        event.sender_device_id = 1

        engine.decrypt_group(event)

        mock_group_cipher.decrypt.assert_called()

    def test_distribute_sender_key(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        # Mock group session creation
        distribution = MagicMock()
        distribution.key_id = 1
        distribution.iteration = 0
        distribution.bytes = b"dist"
        distribution.sender_key_id = 1
        distribution.sender_key_iteration = 0
        distribution.distribution_message = b"dist_msg"
        mock_group_builder.create_session.return_value = distribution

        mock_client.e2ee_sender_key_push.return_value = (0, "ok")

        engine.distribute_sender_key("room1", "group1", "bob")

        mock_client.e2ee_sender_key_push.assert_called()

        # Test cache - second call should not push
        engine.distribute_sender_key("room1", "group1", "bob")
        assert mock_client.e2ee_sender_key_push.call_count == 1

    def test_process_sender_key_distribution(
        self,
        mock_store,
        mock_client,
        mock_signal_context,
        mock_signal_store,
        mock_group_builder,
        mock_group_cipher,
    ):
        # Setup state
        mock_store.load_state.return_value = LocalKeyState(
            registration_id=1,
            device_id=1,
            identity_key=_make_key_pair(),
            signed_pre_key=None,
            pre_keys={},
            remote_identities={},
            sender_keys={},
        )

        engine = E2EEngine(
            username="alice",
            key_store=mock_store,
            mp2_client=mock_client,
            signal_context=mock_signal_context,
            signal_store=mock_signal_store,
            group_builder=mock_group_builder,
            group_cipher=mock_group_cipher,
        )

        dist = MagicMock()
        dist.room_name = "room1"
        dist.group_id = "group1"
        dist.sender = "bob"
        dist.sender_device_id = 1
        dist.sender_registration_id = 100
        dist.distribution_message = b"dist_msg"
        dist.sender_key_id = 1
        dist.sender_key_iteration = 0

        engine.process_sender_key_distribution(dist)

        mock_group_builder.process_session.assert_called()
        mock_store.store_sender_key.assert_called()
