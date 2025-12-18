"""Test suite for NostrSigner (Phase 28.2)."""

import pytest

# Check if coincurve is available
try:
    import coincurve  # noqa: F401

    COINCURVE_AVAILABLE = True
except ImportError:
    COINCURVE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not COINCURVE_AVAILABLE, reason="coincurve library required (pip install coincurve)"
)


class TestNostrSigner:
    """Test NostrSigner abstraction."""

    def test_initialization(self):
        """Test signer initialization with valid key."""
        from ming_drlms.core.nostr_signer import NostrSigner

        # Valid 32-byte private key (0x01, coincurve rejects all-zeros)
        private_key = bytes.fromhex(
            "0000000000000000000000000000000000000000000000000000000000000001"
        )
        signer = NostrSigner(private_key)
        assert signer is not None

    def test_initialization_invalid_length(self):
        """Test signer rejects invalid key length."""
        from ming_drlms.core.nostr_signer import NostrSigner

        with pytest.raises(ValueError, match="must be 32 bytes"):
            NostrSigner(b"short")

    def test_get_pubkey_hex(self):
        """Test public key extraction."""
        from ming_drlms.core.nostr_signer import NostrSigner

        # Known test vector (example)
        private_key = bytes.fromhex(
            "0000000000000000000000000000000000000000000000000000000000000001"
        )
        signer = NostrSigner(private_key)
        pubkey = signer.get_pubkey_hex()

        # Should be 64-char hex (32 bytes)
        assert len(pubkey) == 64
        assert all(c in "0123456789abcdef" for c in pubkey)

    def test_sign_event(self):
        """Test event signing."""
        from ming_drlms.core.nostr_signer import NostrSigner
        import time

        private_key = bytes.fromhex(
            "0000000000000000000000000000000000000000000000000000000000000001"
        )
        signer = NostrSigner(private_key)

        event = {
            "pubkey": signer.get_pubkey_hex(),
            "created_at": int(time.time()),
            "kind": 1,
            "tags": [],
            "content": "Test message",
        }

        signature = signer.sign_event(event)

        # Schnorr signature should be 128-char hex (64 bytes)
        assert len(signature) == 128
        assert all(c in "0123456789abcdef" for c in signature)

    def test_sign_event_missing_field(self):
        """Test signing rejects malformed event."""
        from ming_drlms.core.nostr_signer import NostrSigner

        private_key = bytes.fromhex(
            "0000000000000000000000000000000000000000000000000000000000000001"
        )
        signer = NostrSigner(private_key)

        # Missing 'kind' field
        incomplete_event = {
            "pubkey": "test",
            "created_at": 123456,
            "tags": [],
            "content": "test",
        }

        with pytest.raises(ValueError, match="missing required field"):
            signer.sign_event(incomplete_event)

    def test_integration_with_identity_manager(self):
        """Test get_nostr_signer() integration."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.nostr_derivation import generate_mnemonic
        from ming_drlms.core.e2ee_store import LocalKeyStore
        import tempfile
        import os

        # Use temporary keystore
        with tempfile.TemporaryDirectory() as tmpdir:
            keystore_path = os.path.join(tmpdir, "test_keys.json")
            keystore = LocalKeyStore(keystore_path)

            # Generate identity with mnemonic
            mnemonic = generate_mnemonic()
            username = "test_nostr_signer"
            identity = IdentityManager.from_mnemonic(
                mnemonic, username, keystore=keystore
            )

            # Should be able to get signer
            signer = identity.get_nostr_signer()
            assert signer is not None

            # Signer should work
            pubkey = signer.get_pubkey_hex()
            assert len(pubkey) == 64

            # Sign a test event
            import time

            event = {
                "pubkey": pubkey,
                "created_at": int(time.time()),
                "kind": 1,
                "tags": [],
                "content": "Integration test",
            }
            sig = signer.sign_event(event)
            assert len(sig) == 128

    def test_identity_without_nostr_key_raises(self):
        """Test that old identities without Nostr keys raise error."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.e2ee_store import LocalKeyStore
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            keystore_path = os.path.join(tmpdir, "test_keys.json")
            keystore = LocalKeyStore(keystore_path)

            # Create identity the old way (without from_mnemonic)
            username = "legacy_user"
            identity = IdentityManager(username, keystore=keystore)

            # Should raise ValueError
            with pytest.raises(ValueError, match="No Nostr key found"):
                identity.get_nostr_signer()
