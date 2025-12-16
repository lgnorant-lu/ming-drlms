"""Phase 27: Unit tests for IdentityManager.from_mnemonic.

Tests BIP39-based identity creation with Nostr + Signal + PQC keys.
"""

import pytest


# Standard BIP39 test mnemonic
TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


class TestIdentityManagerFromMnemonic:
    """Tests for IdentityManager.from_mnemonic class method."""

    @pytest.fixture
    def temp_keystore_path(self, tmp_path):
        """Provide a temporary path for keystore."""
        return tmp_path / "test_keystore.json"

    def test_creates_identity_manager(self, temp_keystore_path):
        """from_mnemonic should return IdentityManager instance."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore = LocalKeyStore(path=temp_keystore_path)
        manager = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )

        assert isinstance(manager, IdentityManager)

    def test_stores_identity_in_keystore(self, temp_keystore_path):
        """from_mnemonic should persist identity to keystore."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore = LocalKeyStore(path=temp_keystore_path)
        manager = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )

        # Verify identity exists
        assert manager.has_identity()

        # Verify public key is available
        identity = manager.get_identity()
        assert len(identity.public_key_raw) == 32  # X25519

    def test_deterministic_identity(self, temp_keystore_path):
        """Same mnemonic should produce same identity."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore1 = LocalKeyStore(path=temp_keystore_path)
        manager1 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "user1",
            keystore=keystore1,
        )

        keystore2 = LocalKeyStore(path=temp_keystore_path.parent / "keystore2.json")
        manager2 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "user2",
            keystore=keystore2,
        )

        # Same mnemonic = same derived keys
        assert manager1.get_pubkey() == manager2.get_pubkey()

    def test_passphrase_changes_identity(self, temp_keystore_path):
        """Different passphrase should produce different identity."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore1 = LocalKeyStore(path=temp_keystore_path)
        manager1 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "user1",
            keystore=keystore1,
        )

        keystore2 = LocalKeyStore(path=temp_keystore_path.parent / "keystore2.json")
        manager2 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "user2",
            passphrase="secret",
            keystore=keystore2,
        )

        assert manager1.get_pubkey() != manager2.get_pubkey()

    def test_pqc_key_stored_when_available(self, temp_keystore_path):
        """PQC key should be stored when liboqs is available."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pqc_kem import is_pqc_available

        keystore = LocalKeyStore(path=temp_keystore_path)
        manager = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )

        if is_pqc_available():
            assert manager.has_pqc_key()
            pqc_pub = manager.get_pqc_public_key()
            assert pqc_pub is not None
            assert len(pqc_pub) == 1184  # ML-KEM-768
        else:
            # Mock mode - PQC may or may not be available
            pass

    def test_pqc_private_key_stored(self, temp_keystore_path):
        """PQC private key should be stored for decapsulation."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pqc_kem import is_pqc_available

        if not is_pqc_available():
            pytest.skip("liboqs not available")

        keystore = LocalKeyStore(path=temp_keystore_path)
        manager = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )

        pqc_priv = manager.get_pqc_private_key()
        assert pqc_priv is not None
        assert len(pqc_priv) == 2400  # ML-KEM-768 secret key

    def test_existing_identity_not_overwritten(self, temp_keystore_path):
        """Existing identity should not be overwritten without regenerate flag."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore = LocalKeyStore(path=temp_keystore_path)

        # Create first identity
        manager1 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )
        pub1 = manager1.get_pubkey()

        # Try to create again - should return existing
        manager2 = IdentityManager.from_mnemonic(
            "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo wrong",  # Different mnemonic
            "test_user",
            keystore=keystore,
            regenerate_pqc=False,
        )
        pub2 = manager2.get_pubkey()

        # Should still have original keys (not regenerated)
        assert pub1 == pub2

    def test_regenerate_pqc_flag(self, temp_keystore_path):
        """regenerate_pqc=True should regenerate PQC keys."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pqc_kem import is_pqc_available

        if not is_pqc_available():
            pytest.skip("liboqs not available")

        keystore = LocalKeyStore(path=temp_keystore_path)

        # Create first identity
        manager1 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )
        pqc1 = manager1.get_pqc_public_key()

        # Regenerate with same mnemonic should produce same PQC key (deterministic)
        manager2 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
            regenerate_pqc=True,
        )
        pqc2 = manager2.get_pqc_public_key()

        # Same seed = same key
        assert pqc1 == pqc2

    def test_invalid_mnemonic_raises(self, temp_keystore_path):
        """Invalid mnemonic should raise ValueError."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore = LocalKeyStore(path=temp_keystore_path)

        with pytest.raises(ValueError, match="Invalid BIP39 mnemonic"):
            IdentityManager.from_mnemonic(
                "invalid mnemonic words that are not valid",
                "test_user",
                keystore=keystore,
            )

    def test_pubkey_hex_format(self, temp_keystore_path):
        """get_pubkey_hex should return valid hex string."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore = LocalKeyStore(path=temp_keystore_path)
        manager = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore,
        )

        hex_key = manager.get_pubkey_hex()
        assert len(hex_key) == 64  # 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in hex_key)


class TestIdentityManagerPersistence:
    """Tests for identity persistence across sessions."""

    def test_identity_persisted_across_instances(self, tmp_path):
        """Identity should be loadable from new IdentityManager instance."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore

        keystore_path = tmp_path / "keystore.json"

        # Create identity
        keystore1 = LocalKeyStore(path=keystore_path)
        manager1 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore1,
        )
        pub1 = manager1.get_pubkey()

        # Load from new instance
        keystore2 = LocalKeyStore(path=keystore_path)
        manager2 = IdentityManager("test_user", keystore=keystore2)

        assert manager2.has_identity()
        assert manager2.get_pubkey() == pub1

    def test_pqc_keys_persisted(self, tmp_path):
        """PQC keys should be loadable from new instance."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pqc_kem import is_pqc_available

        if not is_pqc_available():
            pytest.skip("liboqs not available")

        keystore_path = tmp_path / "keystore.json"

        # Create identity with PQC
        keystore1 = LocalKeyStore(path=keystore_path)
        manager1 = IdentityManager.from_mnemonic(
            TEST_MNEMONIC,
            "test_user",
            keystore=keystore1,
        )
        pqc_pub1 = manager1.get_pqc_public_key()
        _pqc_priv1 = manager1.get_pqc_private_key()  # noqa: F841

        # Load from new instance
        keystore2 = LocalKeyStore(path=keystore_path)
        manager2 = IdentityManager("test_user", keystore=keystore2)
        manager2._load_pqc_key()

        assert manager2.has_pqc_key()
        assert manager2.get_pqc_public_key() == pqc_pub1
