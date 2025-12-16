"""Phase 27: Comprehensive pytest test suite for PQC modules.

Tests cover:
- nostr_derivation.py: BIP39 validation, NIP-06 key derivation
- pqc_kem.py: ML-KEM-768 wrapper (when liboqs available)
- hybrid_crypto.py: Hybrid encryption/decryption
- pqc_events.py: Kind 10050 event creation/validation

Both normal cases and edge cases are covered.
"""

import pytest
import base64

# Test data
TEST_MNEMONIC_12 = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
TEST_MNEMONIC_24 = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon art"
INVALID_MNEMONIC = "invalid mnemonic phrase that should fail validation"
EMPTY_MNEMONIC = ""

# Expected values for test mnemonic (12 words)
# These are deterministic outputs from NIP-06 derivation
EXPECTED_NOSTR_PUBKEY_PREFIX = "e8bcf38236"  # First 10 chars of x-only pubkey hex


# ============================================================================
# nostr_derivation.py tests
# ============================================================================


class TestValidateMnemonic:
    """Tests for validate_mnemonic function."""

    def test_valid_12_word_mnemonic(self):
        """Test validation of standard 12-word mnemonic."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        assert validate_mnemonic(TEST_MNEMONIC_12) is True

    def test_valid_24_word_mnemonic(self):
        """Test validation of 24-word mnemonic."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        assert validate_mnemonic(TEST_MNEMONIC_24) is True

    def test_invalid_mnemonic(self):
        """Test that invalid mnemonic returns False."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        assert validate_mnemonic(INVALID_MNEMONIC) is False

    def test_empty_mnemonic(self):
        """Test that empty string returns False."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        assert validate_mnemonic(EMPTY_MNEMONIC) is False

    def test_single_word(self):
        """Test single word is invalid."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        assert validate_mnemonic("abandon") is False

    def test_wrong_checksum(self):
        """Test mnemonic with wrong checksum."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        # Change last word to break checksum
        wrong = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon"
        assert validate_mnemonic(wrong) is False


class TestDeriveNostrKeys:
    """Tests for derive_nostr_keys function."""

    def test_derive_from_valid_mnemonic(self):
        """Test key derivation from valid mnemonic."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        keys = derive_nostr_keys(TEST_MNEMONIC_12)

        # Check key sizes
        assert len(keys.private_key) == 32
        assert len(keys.public_key) == 33  # Compressed
        assert len(keys.public_key_x_only) == 32

        # Check expected prefix (deterministic)
        assert keys.public_key_hex().startswith(EXPECTED_NOSTR_PUBKEY_PREFIX)

    def test_derive_with_account_index(self):
        """Test derivation with different account index."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        keys0 = derive_nostr_keys(TEST_MNEMONIC_12, account=0)
        keys1 = derive_nostr_keys(TEST_MNEMONIC_12, account=1)

        # Different accounts should yield different keys
        assert keys0.private_key != keys1.private_key
        assert keys0.public_key != keys1.public_key

    def test_derive_with_passphrase(self):
        """Test derivation with BIP39 passphrase."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        keys_no_pass = derive_nostr_keys(TEST_MNEMONIC_12)
        keys_with_pass = derive_nostr_keys(TEST_MNEMONIC_12, passphrase="test")

        # Passphrase should change the derived keys
        assert keys_no_pass.private_key != keys_with_pass.private_key

    def test_derive_invalid_mnemonic_raises(self):
        """Test that invalid mnemonic raises ValueError."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        with pytest.raises(ValueError, match="Invalid BIP39 mnemonic"):
            derive_nostr_keys(INVALID_MNEMONIC)

    def test_deterministic_derivation(self):
        """Test that same mnemonic always yields same keys."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        keys1 = derive_nostr_keys(TEST_MNEMONIC_12)
        keys2 = derive_nostr_keys(TEST_MNEMONIC_12)

        assert keys1.private_key == keys2.private_key
        assert keys1.public_key == keys2.public_key


class TestGenerateSignalSeed:
    """Tests for generate_signal_seed function."""

    def test_generates_32_bytes(self):
        """Test that Signal seed is 32 bytes."""
        from ming_drlms.core.nostr_derivation import generate_signal_seed

        seed = generate_signal_seed(TEST_MNEMONIC_12)
        assert len(seed) == 32

    def test_deterministic(self):
        """Test deterministic generation."""
        from ming_drlms.core.nostr_derivation import generate_signal_seed

        seed1 = generate_signal_seed(TEST_MNEMONIC_12)
        seed2 = generate_signal_seed(TEST_MNEMONIC_12)
        assert seed1 == seed2

    def test_different_from_nostr_key(self):
        """Test that Signal seed differs from Nostr private key."""
        from ming_drlms.core.nostr_derivation import (
            generate_signal_seed,
            derive_nostr_keys,
        )

        signal_seed = generate_signal_seed(TEST_MNEMONIC_12)
        nostr_keys = derive_nostr_keys(TEST_MNEMONIC_12)
        assert signal_seed != nostr_keys.private_key


class TestGeneratePqcSeed:
    """Tests for generate_pqc_seed function."""

    def test_generates_64_bytes(self):
        """Test that PQC seed is 64 bytes (for ML-KEM-768)."""
        from ming_drlms.core.nostr_derivation import generate_pqc_seed

        seed = generate_pqc_seed(TEST_MNEMONIC_12)
        assert len(seed) == 64

    def test_deterministic(self):
        """Test deterministic generation."""
        from ming_drlms.core.nostr_derivation import generate_pqc_seed

        seed1 = generate_pqc_seed(TEST_MNEMONIC_12)
        seed2 = generate_pqc_seed(TEST_MNEMONIC_12)
        assert seed1 == seed2


# ============================================================================
# pqc_events.py tests
# ============================================================================


class TestPQCKeyEvent:
    """Tests for PQCKeyEvent class."""

    def test_create_event(self):
        """Test basic event creation."""
        from ming_drlms.core.pqc_events import PQCKeyEvent, KIND_PQC_KEY

        event = PQCKeyEvent(
            pubkey="a" * 64,
            pqc_public_key=b"\x00" * 1184,
            created_at=1734302800,
        )

        assert event.kind == KIND_PQC_KEY
        assert event.kind == 10050
        assert len(event.pqc_public_key) == 1184

    def test_content_base64(self):
        """Test base64 encoding of PQC key."""
        from ming_drlms.core.pqc_events import PQCKeyEvent

        pqc_key = b"\x01\x02\x03" + b"\x00" * 1181  # 1184 bytes
        event = PQCKeyEvent(
            pubkey="a" * 64,
            pqc_public_key=pqc_key,
            created_at=1734302800,
        )

        encoded = event.content_base64()
        decoded = base64.b64decode(encoded)
        assert decoded == pqc_key

    def test_compute_id_deterministic(self):
        """Test that event ID is deterministic."""
        from ming_drlms.core.pqc_events import PQCKeyEvent

        event1 = PQCKeyEvent(
            pubkey="a" * 64,
            pqc_public_key=b"\x00" * 1184,
            created_at=1734302800,
        )
        event2 = PQCKeyEvent(
            pubkey="a" * 64,
            pqc_public_key=b"\x00" * 1184,
            created_at=1734302800,
        )

        assert event1.compute_id() == event2.compute_id()

    def test_to_dict(self):
        """Test JSON serialization."""
        from ming_drlms.core.pqc_events import PQCKeyEvent

        event = PQCKeyEvent(
            pubkey="a" * 64,
            pqc_public_key=b"\x00" * 1184,
            created_at=1734302800,
        )

        d = event.to_dict()
        assert d["kind"] == 10050
        assert d["pubkey"] == "a" * 64
        assert d["created_at"] == 1734302800
        assert "content" in d
        assert "tags" in d

    def test_from_dict_roundtrip(self):
        """Test serialization roundtrip."""
        from ming_drlms.core.pqc_events import PQCKeyEvent

        original = PQCKeyEvent(
            pubkey="b" * 64,
            pqc_public_key=b"\xff" * 1184,
            created_at=1734302900,
            target_pubkey="c" * 64,
        )

        d = original.to_dict()
        restored = PQCKeyEvent.from_dict(d)

        assert restored.pubkey == original.pubkey
        assert restored.pqc_public_key == original.pqc_public_key
        assert restored.created_at == original.created_at
        assert restored.target_pubkey == original.target_pubkey


class TestCreatePqcKeyEvent:
    """Tests for create_pqc_key_event function."""

    def test_create_valid_event(self):
        """Test creating a valid event."""
        from ming_drlms.core.pqc_events import create_pqc_key_event

        event = create_pqc_key_event(
            pubkey_hex="d" * 64,
            pqc_public_key=b"\x00" * 1184,
        )

        assert event.pubkey == "d" * 64
        assert event.event_id is not None
        assert len(event.event_id) == 64  # SHA256 hex

    def test_invalid_pqc_key_size_raises(self):
        """Test that wrong PQC key size raises ValueError."""
        from ming_drlms.core.pqc_events import create_pqc_key_event

        with pytest.raises(ValueError, match="Invalid ML-KEM-768 public key size"):
            create_pqc_key_event(
                pubkey_hex="e" * 64,
                pqc_public_key=b"\x00" * 100,  # Wrong size
            )

    def test_with_target_pubkey(self):
        """Test event with target pubkey (directed)."""
        from ming_drlms.core.pqc_events import create_pqc_key_event

        event = create_pqc_key_event(
            pubkey_hex="f" * 64,
            pqc_public_key=b"\x00" * 1184,
            target_pubkey="0" * 64,
        )

        assert event.target_pubkey == "0" * 64

        d = event.to_dict()
        # Check "p" tag exists
        p_tags = [t for t in d["tags"] if t[0] == "p"]
        assert len(p_tags) == 1
        assert p_tags[0][1] == "0" * 64


class TestVerifyPqcKeyEvent:
    """Tests for verify_pqc_key_event function."""

    def test_verify_valid_event(self):
        """Test verification of valid event."""
        from ming_drlms.core.pqc_events import (
            create_pqc_key_event,
            verify_pqc_key_event,
        )

        event = create_pqc_key_event(
            pubkey_hex="1" * 64,
            pqc_public_key=b"\x00" * 1184,
        )

        assert verify_pqc_key_event(event) is True

    def test_verify_wrong_pqc_size(self):
        """Test verification fails with wrong PQC key size."""
        from ming_drlms.core.pqc_events import PQCKeyEvent, verify_pqc_key_event

        event = PQCKeyEvent(
            pubkey="2" * 64,
            pqc_public_key=b"\x00" * 100,  # Wrong size
            created_at=1734302800,
        )

        assert verify_pqc_key_event(event) is False

    def test_verify_tampered_id(self):
        """Test verification fails with tampered event ID."""
        from ming_drlms.core.pqc_events import (
            create_pqc_key_event,
            verify_pqc_key_event,
        )

        event = create_pqc_key_event(
            pubkey_hex="3" * 64,
            pqc_public_key=b"\x00" * 1184,
        )
        event.event_id = "0" * 64  # Tampered

        assert verify_pqc_key_event(event) is False


# ============================================================================
# hybrid_crypto.py tests
# ============================================================================

# Note: liboqs-dependent tests use pytest.importorskip inside test methods
# to avoid triggering liboqs download during test collection


class TestHybridCrypto:
    """Tests for hybrid_crypto module."""

    def test_is_hybrid_available(self):
        """Test availability check doesn't crash."""
        from ming_drlms.core.hybrid_crypto import is_hybrid_available

        # Should return bool regardless of liboqs availability
        result = is_hybrid_available()
        assert isinstance(result, bool)

    def test_hybrid_encrypt_decrypt_roundtrip(self):
        """Test full encryption/decryption cycle."""
        from ming_drlms.core.hybrid_crypto import is_hybrid_available

        if not is_hybrid_available():
            pytest.skip("liboqs not available")

        from ming_drlms.core.hybrid_crypto import hybrid_encrypt, hybrid_decrypt
        from ming_drlms.core.pqc_kem import MLKEM768
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        # Generate recipient keys
        x25519_priv = X25519PrivateKey.generate()
        x25519_pub = x25519_priv.public_key().public_bytes_raw()

        kem = MLKEM768()
        pqc_pub = kem.generate_keypair()

        # Encrypt
        plaintext = b"Hello, quantum-safe world!"
        result = hybrid_encrypt(plaintext, x25519_pub, pqc_pub)

        # Decrypt
        decrypted = hybrid_decrypt(
            result.wrapped_ciphertext,
            result.pqc_ciphertext,
            result.ephemeral_pub,
            x25519_priv.private_bytes_raw(),
            kem,
        )

        assert decrypted == plaintext


# ============================================================================
# pqc_kem.py tests (conditional on liboqs availability)
# ============================================================================


class TestPqcKem:
    """Tests for pqc_kem module."""

    def test_is_pqc_available(self):
        """Test availability check."""
        try:
            from ming_drlms.core.pqc_kem import is_pqc_available

            result = is_pqc_available()
            assert isinstance(result, bool)
        except RuntimeError:
            # liboqs not installed, this is expected
            pytest.skip("liboqs native library not available")

    def test_mlkem768_keygen(self):
        """Test ML-KEM-768 key generation."""
        try:
            from ming_drlms.core.pqc_kem import is_pqc_available, MLKEM768

            if not is_pqc_available():
                pytest.skip("liboqs not available")
        except RuntimeError:
            pytest.skip("liboqs native library not available")

        kem = MLKEM768()
        pub = kem.generate_keypair()

        assert len(pub) == 1184  # ML-KEM-768 public key size

    def test_mlkem768_encap_decap(self):
        """Test ML-KEM-768 encapsulation/decapsulation."""
        try:
            from ming_drlms.core.pqc_kem import is_pqc_available, MLKEM768

            if not is_pqc_available():
                pytest.skip("liboqs not available")
        except RuntimeError:
            pytest.skip("liboqs native library not available")

        # Recipient generates keypair
        recipient = MLKEM768()
        pub = recipient.generate_keypair()

        # Sender encapsulates
        sender = MLKEM768()
        ciphertext, shared_secret_sender = sender.encapsulate(pub)

        # Recipient decapsulates
        shared_secret_recipient = recipient.decapsulate(ciphertext)

        assert shared_secret_sender == shared_secret_recipient
        assert len(shared_secret_sender) == 32  # ML-KEM-768 shared secret size


# ============================================================================
# Edge cases and error handling
# ============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_tags_in_event(self):
        """Test event with no extra tags."""
        from ming_drlms.core.pqc_events import PQCKeyEvent

        event = PQCKeyEvent(
            pubkey="a" * 64,
            pqc_public_key=b"\x00" * 1184,
            created_at=1734302800,
            tags=[],
        )

        d = event.to_dict()
        # Should have at least algo and size tags
        assert len([t for t in d["tags"] if t[0] == "algo"]) == 1
        assert len([t for t in d["tags"] if t[0] == "size"]) == 1

    def test_unicode_in_mnemonic(self):
        """Test that unicode doesn't break validation."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        # Japanese mnemonic should be handled gracefully
        result = validate_mnemonic("あ い う え お か き く け こ さ し")
        # Should return False (not valid English) but not crash
        assert result is False

    def test_very_long_mnemonic(self):
        """Test very long invalid mnemonic."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        long_mnemonic = " ".join(["abandon"] * 100)
        assert validate_mnemonic(long_mnemonic) is False

    def test_pqc_event_zero_timestamp(self):
        """Test event with zero timestamp."""
        from ming_drlms.core.pqc_events import create_pqc_key_event

        event = create_pqc_key_event(
            pubkey_hex="a" * 64,
            pqc_public_key=b"\x00" * 1184,
        )

        # created_at should be current time, not zero
        assert event.created_at > 0

    def test_nostr_key_hex_format(self):
        """Test that hex output is correct format."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        keys = derive_nostr_keys(TEST_MNEMONIC_12)
        priv_hex = keys.private_key_hex()
        pub_hex = keys.public_key_hex()

        # Check they're valid hex
        assert all(c in "0123456789abcdef" for c in priv_hex)
        assert all(c in "0123456789abcdef" for c in pub_hex)

        # Check lengths
        assert len(priv_hex) == 64  # 32 bytes = 64 hex chars
        assert len(pub_hex) == 64  # 32 bytes = 64 hex chars
