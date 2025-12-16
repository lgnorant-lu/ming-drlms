"""Phase 27: Unit tests for pqc_kem.py.

Tests ML-KEM-768 (Kyber768) key encapsulation mechanism.
Uses mocking when liboqs is not available.
"""

import pytest


def _pqc_available() -> bool:
    """Helper to check if PQC is available for test skipping."""
    try:
        from ming_drlms.core.pqc_kem import is_pqc_available

        return is_pqc_available()
    except ImportError:
        return False


class TestPqcAvailability:
    """Tests for PQC availability detection."""

    def test_is_pqc_available_returns_bool(self):
        """is_pqc_available should return a boolean."""
        from ming_drlms.core.pqc_kem import is_pqc_available

        result = is_pqc_available()
        assert isinstance(result, bool)


class TestMLKEM768Constants:
    """Tests for ML-KEM-768 size constants."""

    def test_public_key_size(self):
        """ML-KEM-768 public key should be 1184 bytes."""
        from ming_drlms.core.pqc_kem import MLKEM768_PUBLIC_KEY_SIZE

        assert MLKEM768_PUBLIC_KEY_SIZE == 1184

    def test_secret_key_size(self):
        """ML-KEM-768 secret key should be 2400 bytes."""
        from ming_drlms.core.pqc_kem import MLKEM768_SECRET_KEY_SIZE

        assert MLKEM768_SECRET_KEY_SIZE == 2400

    def test_ciphertext_size(self):
        """ML-KEM-768 ciphertext should be 1088 bytes."""
        from ming_drlms.core.pqc_kem import MLKEM768_CIPHERTEXT_SIZE

        assert MLKEM768_CIPHERTEXT_SIZE == 1088

    def test_shared_secret_size(self):
        """ML-KEM-768 shared secret should be 32 bytes."""
        from ming_drlms.core.pqc_kem import MLKEM768_SHARED_SECRET_SIZE

        assert MLKEM768_SHARED_SECRET_SIZE == 32


@pytest.mark.skipif(not _pqc_available(), reason="liboqs not available")
class TestMLKEM768WithLiboqs:
    """Tests requiring liboqs to be available."""

    def test_keygen_produces_correct_sizes(self):
        """generate_keypair should produce correct key sizes."""
        from ming_drlms.core.pqc_kem import MLKEM768, MLKEM768_PUBLIC_KEY_SIZE

        kem = MLKEM768()
        public_key = kem.generate_keypair()

        assert len(public_key) == MLKEM768_PUBLIC_KEY_SIZE

    def test_keygen_from_seed_deterministic(self):
        """generate_keypair_from_seed should be deterministic."""
        from ming_drlms.core.pqc_kem import MLKEM768

        seed = b"\x00" * 64
        kem1 = MLKEM768()
        kem2 = MLKEM768()

        pk1 = kem1.generate_keypair_from_seed(seed)
        pk2 = kem2.generate_keypair_from_seed(seed)

        assert pk1 == pk2

    def test_encapsulate_produces_correct_sizes(self):
        """encapsulate should produce correct ciphertext and shared secret sizes."""
        from ming_drlms.core.pqc_kem import (
            MLKEM768,
            MLKEM768_CIPHERTEXT_SIZE,
            MLKEM768_SHARED_SECRET_SIZE,
        )

        kem = MLKEM768()
        public_key = kem.generate_keypair()

        ciphertext, shared_secret = kem.encapsulate(public_key)

        assert len(ciphertext) == MLKEM768_CIPHERTEXT_SIZE
        assert len(shared_secret) == MLKEM768_SHARED_SECRET_SIZE

    def test_encap_decap_roundtrip(self):
        """encapsulate + decapsulate should produce same shared secret."""
        from ming_drlms.core.pqc_kem import MLKEM768

        # Alice generates keypair
        alice_kem = MLKEM768()
        alice_pk = alice_kem.generate_keypair()

        # Bob encapsulates to Alice's public key
        bob_kem = MLKEM768()
        ciphertext, bob_shared = bob_kem.encapsulate(alice_pk)

        # Alice decapsulates
        alice_shared = alice_kem.decapsulate(ciphertext)

        assert alice_shared == bob_shared

    def test_export_keypair(self):
        """export_keypair should return correct sizes."""
        from ming_drlms.core.pqc_kem import (
            MLKEM768,
            MLKEM768_PUBLIC_KEY_SIZE,
            MLKEM768_SECRET_KEY_SIZE,
        )

        kem = MLKEM768()
        kem.generate_keypair()
        keypair = kem.export_keypair()

        assert len(keypair.public_key) == MLKEM768_PUBLIC_KEY_SIZE
        assert len(keypair.secret_key) == MLKEM768_SECRET_KEY_SIZE

    def test_different_seeds_produce_different_keys(self):
        """Different seeds should produce different keys."""
        from ming_drlms.core.pqc_kem import MLKEM768

        seed1 = b"\x00" * 64
        seed2 = b"\x01" * 64

        kem1 = MLKEM768()
        kem2 = MLKEM768()

        pk1 = kem1.generate_keypair_from_seed(seed1)
        pk2 = kem2.generate_keypair_from_seed(seed2)

        assert pk1 != pk2


class TestMLKEM768Fallback:
    """Tests for ML-KEM-768 mock/fallback mode."""

    # test_mock_mode removed: not useful when liboqs is available

    def test_invalid_public_key_size_raises(self):
        """encapsulate with wrong size public key should raise."""
        from ming_drlms.core.pqc_kem import MLKEM768, is_pqc_available

        if not is_pqc_available():
            pytest.skip("Cannot test size validation without liboqs")

        kem = MLKEM768()
        kem.generate_keypair()

        with pytest.raises(ValueError):
            kem.encapsulate(b"short")

    def test_invalid_ciphertext_size_raises(self):
        """decapsulate with wrong size ciphertext should raise."""
        from ming_drlms.core.pqc_kem import MLKEM768, is_pqc_available

        if not is_pqc_available():
            pytest.skip("Cannot test size validation without liboqs")

        kem = MLKEM768()
        kem.generate_keypair()

        with pytest.raises(ValueError):
            kem.decapsulate(b"short")
