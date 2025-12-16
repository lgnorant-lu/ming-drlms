"""Phase 27: Unit tests for hybrid_crypto.py.

Tests hybrid X25519 + ML-KEM-768 + AES-GCM encryption.
"""

import pytest
import os


def _hybrid_available() -> bool:
    """Check if hybrid encryption is available."""
    try:
        from ming_drlms.core.hybrid_crypto import is_hybrid_available

        return is_hybrid_available()
    except ImportError:
        return False


class TestHybridAvailability:
    """Tests for hybrid availability detection."""

    def test_is_hybrid_available_returns_bool(self):
        """is_hybrid_available should return a boolean."""
        from ming_drlms.core.hybrid_crypto import is_hybrid_available

        result = is_hybrid_available()
        assert isinstance(result, bool)


class TestHybridEncryptResult:
    """Tests for HybridEncryptResult dataclass."""

    def test_dataclass_fields(self):
        """HybridEncryptResult should have correct fields."""
        from ming_drlms.core.hybrid_crypto import HybridEncryptResult

        result = HybridEncryptResult(
            wrapped_ciphertext=b"wrapped",
            pqc_ciphertext=b"pqc",
            ephemeral_pub=b"pub",
        )
        assert result.wrapped_ciphertext == b"wrapped"
        assert result.pqc_ciphertext == b"pqc"
        assert result.ephemeral_pub == b"pub"


class TestHybridKeyDerivation:
    """Tests for internal key derivation function."""

    def test_derive_hybrid_key_returns_32_bytes(self):
        """_derive_hybrid_key should return 32-byte AES key."""
        from ming_drlms.core.hybrid_crypto import _derive_hybrid_key

        x25519_shared = b"\x00" * 32
        pqc_shared = b"\x01" * 32

        key = _derive_hybrid_key(x25519_shared, pqc_shared)
        assert len(key) == 32

    def test_derive_hybrid_key_deterministic(self):
        """Same inputs should produce same key."""
        from ming_drlms.core.hybrid_crypto import _derive_hybrid_key

        x25519_shared = b"\xaa" * 32
        pqc_shared = b"\xbb" * 32

        key1 = _derive_hybrid_key(x25519_shared, pqc_shared)
        key2 = _derive_hybrid_key(x25519_shared, pqc_shared)
        assert key1 == key2

    def test_derive_hybrid_key_different_inputs(self):
        """Different inputs should produce different keys."""
        from ming_drlms.core.hybrid_crypto import _derive_hybrid_key

        key1 = _derive_hybrid_key(b"\x00" * 32, b"\x00" * 32)
        key2 = _derive_hybrid_key(b"\x01" * 32, b"\x00" * 32)
        key3 = _derive_hybrid_key(b"\x00" * 32, b"\x01" * 32)

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3


@pytest.mark.skipif(not _hybrid_available(), reason="liboqs not available")
class TestHybridEncryptDecrypt:
    """Tests for hybrid_encrypt and hybrid_decrypt requiring liboqs."""

    def test_encrypt_produces_valid_result(self):
        """hybrid_encrypt should produce HybridEncryptResult."""
        from ming_drlms.core.hybrid_crypto import hybrid_encrypt, HybridEncryptResult
        from ming_drlms.core.pqc_kem import MLKEM768, MLKEM768_CIPHERTEXT_SIZE
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        # Generate peer keys
        peer_x25519 = X25519PrivateKey.generate()
        peer_x25519_pub = peer_x25519.public_key().public_bytes_raw()

        peer_kem = MLKEM768()
        peer_pqc_pub = peer_kem.generate_keypair()

        # Encrypt
        plaintext = b"Hello, hybrid crypto!"
        result = hybrid_encrypt(plaintext, peer_x25519_pub, peer_pqc_pub)

        assert isinstance(result, HybridEncryptResult)
        assert len(result.ephemeral_pub) == 32
        assert len(result.pqc_ciphertext) == MLKEM768_CIPHERTEXT_SIZE
        assert len(result.wrapped_ciphertext) > 12 + 16  # nonce + tag

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypted data should decrypt correctly."""
        from ming_drlms.core.hybrid_crypto import hybrid_encrypt, hybrid_decrypt
        from ming_drlms.core.pqc_kem import MLKEM768
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        # Generate receiver keys (Bob)
        bob_x25519 = X25519PrivateKey.generate()
        bob_x25519_pub = bob_x25519.public_key().public_bytes_raw()
        bob_x25519_priv = bob_x25519.private_bytes_raw()

        bob_kem = MLKEM768()
        bob_pqc_pub = bob_kem.generate_keypair()

        # Alice encrypts
        plaintext = b"Secret message from Alice to Bob"
        result = hybrid_encrypt(plaintext, bob_x25519_pub, bob_pqc_pub)

        # Bob decrypts
        decrypted = hybrid_decrypt(
            result.wrapped_ciphertext,
            result.pqc_ciphertext,
            result.ephemeral_pub,
            bob_x25519_priv,
            bob_kem,
        )

        assert decrypted == plaintext

    def test_large_message_roundtrip(self):
        """Should handle large messages correctly."""
        from ming_drlms.core.hybrid_crypto import hybrid_encrypt, hybrid_decrypt
        from ming_drlms.core.pqc_kem import MLKEM768
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        bob_x25519 = X25519PrivateKey.generate()
        bob_x25519_pub = bob_x25519.public_key().public_bytes_raw()
        bob_x25519_priv = bob_x25519.private_bytes_raw()

        bob_kem = MLKEM768()
        bob_pqc_pub = bob_kem.generate_keypair()

        # Large message (1MB)
        plaintext = os.urandom(1024 * 1024)
        result = hybrid_encrypt(plaintext, bob_x25519_pub, bob_pqc_pub)
        decrypted = hybrid_decrypt(
            result.wrapped_ciphertext,
            result.pqc_ciphertext,
            result.ephemeral_pub,
            bob_x25519_priv,
            bob_kem,
        )

        assert decrypted == plaintext

    def test_empty_message_roundtrip(self):
        """Should handle empty messages."""
        from ming_drlms.core.hybrid_crypto import hybrid_encrypt, hybrid_decrypt
        from ming_drlms.core.pqc_kem import MLKEM768
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        bob_x25519 = X25519PrivateKey.generate()
        bob_x25519_pub = bob_x25519.public_key().public_bytes_raw()
        bob_x25519_priv = bob_x25519.private_bytes_raw()

        bob_kem = MLKEM768()
        bob_pqc_pub = bob_kem.generate_keypair()

        plaintext = b""
        result = hybrid_encrypt(plaintext, bob_x25519_pub, bob_pqc_pub)
        decrypted = hybrid_decrypt(
            result.wrapped_ciphertext,
            result.pqc_ciphertext,
            result.ephemeral_pub,
            bob_x25519_priv,
            bob_kem,
        )

        assert decrypted == plaintext


class TestHybridValidation:
    """Tests for input validation."""

    @pytest.mark.skipif(not _hybrid_available(), reason="liboqs not available")
    def test_invalid_x25519_key_size(self):
        """Wrong X25519 key size should raise ValueError."""
        from ming_drlms.core.hybrid_crypto import hybrid_encrypt
        from ming_drlms.core.pqc_kem import MLKEM768

        kem = MLKEM768()
        pqc_pub = kem.generate_keypair()

        with pytest.raises(ValueError, match="X25519"):
            hybrid_encrypt(b"test", b"short", pqc_pub)

    @pytest.mark.skipif(not _hybrid_available(), reason="liboqs not available")
    def test_invalid_pqc_key_size(self):
        """Wrong PQC key size should raise ValueError."""
        from ming_drlms.core.hybrid_crypto import hybrid_encrypt
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

        x25519 = X25519PrivateKey.generate()
        x25519_pub = x25519.public_key().public_bytes_raw()

        with pytest.raises(ValueError, match="ML-KEM-768"):
            hybrid_encrypt(b"test", x25519_pub, b"short")

    @pytest.mark.skipif(not _hybrid_available(), reason="liboqs not available")
    def test_short_wrapped_ciphertext(self):
        """Too short wrapped ciphertext should raise ValueError."""
        from ming_drlms.core.hybrid_crypto import hybrid_decrypt
        from ming_drlms.core.pqc_kem import MLKEM768

        kem = MLKEM768()
        kem.generate_keypair()  # Need to initialize

        with pytest.raises(ValueError, match="too short"):
            hybrid_decrypt(
                b"short",  # Too short
                b"\x00" * 1088,
                b"\x00" * 32,
                b"\x00" * 32,
                kem,
            )

    @pytest.mark.skipif(not _hybrid_available(), reason="liboqs not available")
    def test_invalid_ephemeral_key_size(self):
        """Wrong ephemeral key size should raise ValueError."""
        from ming_drlms.core.hybrid_crypto import hybrid_decrypt
        from ming_drlms.core.pqc_kem import MLKEM768

        kem = MLKEM768()
        kem.generate_keypair()

        with pytest.raises(ValueError, match="ephemeral"):
            hybrid_decrypt(
                b"\x00" * 50,  # Valid length
                b"\x00" * 1088,
                b"short",  # Invalid ephemeral size
                b"\x00" * 32,
                kem,
            )
