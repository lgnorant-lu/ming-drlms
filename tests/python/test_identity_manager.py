"""Unit tests for Phase 15A: IdentityManager."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest


class TestIdentity:
    """Tests for the Identity dataclass."""

    def test_identity_creation(self) -> None:
        """Identity can be created with valid 32-byte seed and pubkey."""
        from ming_drlms.core.identity_manager import Identity

        seed = secrets.token_bytes(32)
        pubkey = secrets.token_bytes(32)

        identity = Identity(seed=seed, public_key=pubkey, alias="test")

        assert identity.seed == seed
        assert identity.public_key == pubkey
        assert identity.alias == "test"

    def test_identity_invalid_seed_length(self) -> None:
        """Identity raises ValueError for invalid seed length."""
        from ming_drlms.core.identity_manager import Identity

        with pytest.raises(ValueError, match="seed must be exactly 32 bytes"):
            Identity(seed=b"short", public_key=secrets.token_bytes(32))

    def test_identity_invalid_pubkey_length(self) -> None:
        """Identity raises ValueError for invalid pubkey length."""
        from ming_drlms.core.identity_manager import Identity

        with pytest.raises(ValueError, match="public_key must be exactly 32 bytes"):
            Identity(seed=secrets.token_bytes(32), public_key=b"short")

    def test_identity_default_alias(self) -> None:
        """Identity has empty alias by default."""
        from ming_drlms.core.identity_manager import Identity

        identity = Identity(
            seed=secrets.token_bytes(32), public_key=secrets.token_bytes(32)
        )
        assert identity.alias == ""


class TestIdentityManagerCreation:
    """Tests for IdentityManager identity creation."""

    def test_create_identity_generates_valid_keypair(self, tmp_path: Path) -> None:
        """create_identity generates a valid Ed25519 keypair."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")

        identity = manager.create_identity(alias="test-alias")

        assert len(identity.seed) == 32
        assert len(identity.public_key) == 32
        assert identity.alias == "test-alias"
        assert manager.has_identity()

    def test_create_identity_persists_to_file(self, tmp_path: Path) -> None:
        """create_identity saves identity to JSON file."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"
        manager = IdentityManager(path)
        manager.create_identity(alias="persisted")

        assert path.exists()

        data = json.loads(path.read_text())
        assert "seed" in data
        assert "public_key" in data
        assert data["alias"] == "persisted"
        assert len(data["seed"]) == 64  # hex string

    def test_create_identity_prevents_overwrite_by_default(
        self, tmp_path: Path
    ) -> None:
        """create_identity raises error if identity already exists."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        with pytest.raises(IdentityError, match="already exists"):
            manager.create_identity()

    def test_create_identity_force_overwrite(self, tmp_path: Path) -> None:
        """create_identity with force=True overwrites existing identity."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        first = manager.create_identity()
        second = manager.create_identity(force=True)

        assert first.seed != second.seed
        assert first.public_key != second.public_key


class TestIdentityManagerImportExport:
    """Tests for IdentityManager import/export functionality."""

    def test_export_identity_returns_seed(self, tmp_path: Path) -> None:
        """export_identity returns the 32-byte seed."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        identity = manager.create_identity()

        exported = manager.export_identity()

        assert exported == identity.seed
        assert len(exported) == 32

    def test_export_identity_no_identity_raises(self, tmp_path: Path) -> None:
        """export_identity raises IdentityError if no identity loaded."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError

        manager = IdentityManager(tmp_path / "identity.json")

        with pytest.raises(IdentityError, match="No identity loaded"):
            manager.export_identity()

    def test_import_identity_from_seed(self, tmp_path: Path) -> None:
        """import_identity restores identity from seed."""
        from ming_drlms.core.identity_manager import IdentityManager

        # First create and export
        manager1 = IdentityManager(tmp_path / "id1.json")
        original = manager1.create_identity(alias="original")
        seed = manager1.export_identity()

        # Then import in a new manager
        manager2 = IdentityManager(tmp_path / "id2.json")
        imported = manager2.import_identity(seed, alias="imported")

        assert imported.seed == original.seed
        assert imported.public_key == original.public_key
        assert imported.alias == "imported"

    def test_import_identity_invalid_seed_length(self, tmp_path: Path) -> None:
        """import_identity raises ValueError for invalid seed length."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")

        with pytest.raises(ValueError, match="seed must be exactly 32 bytes"):
            manager.import_identity(b"too-short")

    def test_import_identity_prevents_overwrite_by_default(
        self, tmp_path: Path
    ) -> None:
        """import_identity raises error if identity exists."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        with pytest.raises(IdentityError, match="already exists"):
            manager.import_identity(secrets.token_bytes(32))


class TestIdentityManagerSigning:
    """Tests for IdentityManager signing functionality."""

    def test_sign_returns_64_byte_signature(self, tmp_path: Path) -> None:
        """sign() returns a 64-byte Ed25519 signature."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        signature = manager.sign(b"hello world")

        assert len(signature) == 64

    def test_sign_no_identity_raises(self, tmp_path: Path) -> None:
        """sign() raises IdentityError if no identity loaded."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError

        manager = IdentityManager(tmp_path / "identity.json")

        with pytest.raises(IdentityError, match="No identity loaded"):
            manager.sign(b"data")

    def test_sign_and_verify_roundtrip(self, tmp_path: Path) -> None:
        """Signature created by sign() can be verified."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        data = b"test message"
        signature = manager.sign(data)
        pubkey = manager.get_pubkey()

        assert manager.verify(data, signature, pubkey)

    def test_verify_wrong_data_fails(self, tmp_path: Path) -> None:
        """verify() returns False for wrong data."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        signature = manager.sign(b"correct data")
        pubkey = manager.get_pubkey()

        assert not manager.verify(b"wrong data", signature, pubkey)

    def test_verify_wrong_signature_fails(self, tmp_path: Path) -> None:
        """verify() returns False for wrong signature."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        data = b"test data"
        pubkey = manager.get_pubkey()
        bad_signature = secrets.token_bytes(64)

        assert not manager.verify(data, bad_signature, pubkey)

    def test_verify_wrong_pubkey_fails(self, tmp_path: Path) -> None:
        """verify() returns False for wrong public key."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        data = b"test data"
        signature = manager.sign(data)
        bad_pubkey = secrets.token_bytes(32)

        assert not manager.verify(data, signature, bad_pubkey)


class TestIdentityManagerPubkey:
    """Tests for public key retrieval."""

    def test_get_pubkey_returns_32_bytes(self, tmp_path: Path) -> None:
        """get_pubkey() returns 32-byte public key."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        pubkey = manager.get_pubkey()

        assert len(pubkey) == 32

    def test_get_pubkey_hex_returns_64_chars(self, tmp_path: Path) -> None:
        """get_pubkey_hex() returns 64-character hex string."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        hex_key = manager.get_pubkey_hex()

        assert len(hex_key) == 64
        assert hex_key == manager.get_pubkey().hex()

    def test_get_pubkey_no_identity_raises(self, tmp_path: Path) -> None:
        """get_pubkey() raises IdentityError if no identity loaded."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError

        manager = IdentityManager(tmp_path / "identity.json")

        with pytest.raises(IdentityError, match="No identity loaded"):
            manager.get_pubkey()


class TestIdentityManagerAlias:
    """Tests for alias management."""

    def test_get_alias(self, tmp_path: Path) -> None:
        """get_alias() returns the alias."""
        from ming_drlms.core.identity_manager import IdentityManager

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity(alias="my-alias")

        assert manager.get_alias() == "my-alias"

    def test_set_alias(self, tmp_path: Path) -> None:
        """set_alias() updates the alias and persists."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"
        manager = IdentityManager(path)
        manager.create_identity(alias="old")

        manager.set_alias("new")

        assert manager.get_alias() == "new"

        # Verify persistence
        data = json.loads(path.read_text())
        assert data["alias"] == "new"

    def test_get_alias_no_identity_raises(self, tmp_path: Path) -> None:
        """get_alias() raises IdentityError if no identity."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError

        manager = IdentityManager(tmp_path / "identity.json")

        with pytest.raises(IdentityError, match="No identity loaded"):
            manager.get_alias()


class TestIdentityManagerPersistence:
    """Tests for identity persistence and loading."""

    def test_auto_load_on_init(self, tmp_path: Path) -> None:
        """IdentityManager auto-loads existing identity on init."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"

        # Create and persist
        manager1 = IdentityManager(path)
        manager1.create_identity(alias="auto-load")
        original_pubkey = manager1.get_pubkey()

        # New manager should auto-load
        manager2 = IdentityManager(path)

        assert manager2.has_identity()
        assert manager2.get_pubkey() == original_pubkey
        assert manager2.get_alias() == "auto-load"

    def test_auto_load_disabled(self, tmp_path: Path) -> None:
        """IdentityManager with auto_load=False doesn't load."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"

        manager1 = IdentityManager(path)
        manager1.create_identity()

        manager2 = IdentityManager(path, auto_load=False)

        assert not manager2.has_identity()

    def test_delete_identity(self, tmp_path: Path) -> None:
        """delete_identity removes identity and file."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"
        manager = IdentityManager(path)
        manager.create_identity()

        assert path.exists()
        assert manager.has_identity()

        manager.delete_identity()

        assert not manager.has_identity()
        assert not path.exists()

    def test_corrupted_file_ignored(self, tmp_path: Path) -> None:
        """Corrupted identity file is silently ignored."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"
        path.write_text("not valid json")

        manager = IdentityManager(path)

        assert not manager.has_identity()

    def test_invalid_hex_in_file_ignored(self, tmp_path: Path) -> None:
        """Invalid hex values in identity file are ignored."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"
        path.write_text(json.dumps({"seed": "not-hex", "public_key": "also-not-hex"}))

        manager = IdentityManager(path)

        assert not manager.has_identity()

    def test_mismatched_pubkey_ignored(self, tmp_path: Path) -> None:
        """Identity file with mismatched pubkey is ignored."""
        from ming_drlms.core.identity_manager import IdentityManager

        path = tmp_path / "identity.json"
        # Valid seed but wrong pubkey
        seed = secrets.token_bytes(32)
        wrong_pubkey = secrets.token_bytes(32)
        path.write_text(
            json.dumps(
                {
                    "seed": seed.hex(),
                    "public_key": wrong_pubkey.hex(),
                }
            )
        )

        manager = IdentityManager(path)

        assert not manager.has_identity()


class TestIdentityManagerLocalKeyStoreIntegration:
    """Tests for LocalKeyStore integration."""

    def test_sync_to_local_keystore(self, tmp_path: Path) -> None:
        """sync_to_local_keystore writes identity to LocalKeyStore."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        identity_path = tmp_path / "identity.json"
        keystore_path = tmp_path / "e2ee_keys.json"

        manager = IdentityManager(identity_path)
        manager.create_identity()

        keystore = LocalKeyStore(keystore_path)
        manager.sync_to_local_keystore(keystore, "testuser", device_id=2)

        # Verify keystore has the identity
        state = keystore.load_state("testuser")
        assert state is not None
        assert state.identity_key.public_key == manager.get_pubkey()
        assert state.identity_key.private_key == manager.export_identity()
        assert state.device_id == 2
        assert 1 <= state.registration_id <= 16383

    def test_sync_to_local_keystore_no_identity_raises(self, tmp_path: Path) -> None:
        """sync_to_local_keystore raises if no identity."""
        from ming_drlms.core.identity_manager import IdentityManager, IdentityError
        from ming_drlms.core.e2ee_store import LocalKeyStore

        manager = IdentityManager(tmp_path / "identity.json")
        keystore = LocalKeyStore(tmp_path / "e2ee_keys.json")

        with pytest.raises(IdentityError, match="No identity loaded"):
            manager.sync_to_local_keystore(keystore, "testuser")

    def test_sync_to_local_keystore_custom_registration_id(
        self, tmp_path: Path
    ) -> None:
        """sync_to_local_keystore uses custom registration_id if provided."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        manager = IdentityManager(tmp_path / "identity.json")
        manager.create_identity()

        keystore = LocalKeyStore(tmp_path / "e2ee_keys.json")
        manager.sync_to_local_keystore(
            keystore, "testuser", device_id=1, registration_id=12345
        )

        state = keystore.load_state("testuser")
        assert state is not None
        assert state.registration_id == 12345
