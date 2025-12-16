"""Phase 27: Unit tests for nostr_derivation.py.

Tests BIP39 mnemonic validation, Nostr key derivation (NIP-06),
and Signal/PQC seed generation.
"""

import pytest


class TestValidateMnemonic:
    """Tests for validate_mnemonic function."""

    def test_valid_12_word_mnemonic(self):
        """Valid 12-word mnemonic should return True."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        # Standard test vector (from BIP39)
        mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        assert validate_mnemonic(mnemonic) is True

    def test_valid_24_word_mnemonic(self):
        """Valid 24-word mnemonic should return True."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        mnemonic = (
            "abandon abandon abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon abandon abandon art"
        )
        assert validate_mnemonic(mnemonic) is True

    def test_invalid_mnemonic_wrong_words(self):
        """Invalid words should return False."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        mnemonic = "invalid words that are not in bip39 wordlist at all testing"
        assert validate_mnemonic(mnemonic) is False

    def test_invalid_mnemonic_wrong_checksum(self):
        """Wrong checksum should return False."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        # Valid words but wrong checksum
        mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon"
        assert validate_mnemonic(mnemonic) is False

    def test_empty_mnemonic(self):
        """Empty mnemonic should return False."""
        from ming_drlms.core.nostr_derivation import validate_mnemonic

        assert validate_mnemonic("") is False


class TestDeriveNostrKeys:
    """Tests for derive_nostr_keys function (NIP-06)."""

    # Test vector from NIP-06 reference implementation
    TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

    def test_derive_nostr_keys_returns_keypair(self):
        """derive_nostr_keys should return NostrKeyPair dataclass."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys, NostrKeyPair

        result = derive_nostr_keys(self.TEST_MNEMONIC)
        assert isinstance(result, NostrKeyPair)

    def test_private_key_is_32_bytes(self):
        """Secp256k1 private key should be 32 bytes."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result = derive_nostr_keys(self.TEST_MNEMONIC)
        assert len(result.private_key) == 32

    def test_public_key_compressed_is_33_bytes(self):
        """Compressed Secp256k1 public key should be 33 bytes."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result = derive_nostr_keys(self.TEST_MNEMONIC)
        assert len(result.public_key) == 33
        assert result.public_key[0] in (0x02, 0x03)  # Compressed prefix

    def test_public_key_x_only_is_32_bytes(self):
        """X-only public key (for Nostr npub) should be 32 bytes."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result = derive_nostr_keys(self.TEST_MNEMONIC)
        assert len(result.public_key_x_only) == 32

    def test_deterministic_derivation(self):
        """Same mnemonic should always produce same keys."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result1 = derive_nostr_keys(self.TEST_MNEMONIC)
        result2 = derive_nostr_keys(self.TEST_MNEMONIC)

        assert result1.private_key == result2.private_key
        assert result1.public_key == result2.public_key
        assert result1.public_key_x_only == result2.public_key_x_only

    def test_different_accounts_produce_different_keys(self):
        """Different account indices should produce different keys."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result0 = derive_nostr_keys(self.TEST_MNEMONIC, account=0)
        result1 = derive_nostr_keys(self.TEST_MNEMONIC, account=1)

        assert result0.private_key != result1.private_key
        assert result0.public_key != result1.public_key

    def test_passphrase_changes_keys(self):
        """Adding passphrase should produce different keys."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result_no_pass = derive_nostr_keys(self.TEST_MNEMONIC)
        result_with_pass = derive_nostr_keys(self.TEST_MNEMONIC, passphrase="secret")

        assert result_no_pass.private_key != result_with_pass.private_key

    def test_hex_properties(self):
        """Hex string properties should work correctly."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        result = derive_nostr_keys(self.TEST_MNEMONIC)

        assert len(result.private_key_hex()) == 64  # 32 bytes = 64 hex chars
        assert len(result.public_key_hex()) == 64  # 32 bytes = 64 hex chars
        assert result.private_key_hex() == result.private_key.hex()
        assert result.public_key_hex() == result.public_key_x_only.hex()

    def test_invalid_mnemonic_raises_value_error(self):
        """Invalid mnemonic should raise ValueError."""
        from ming_drlms.core.nostr_derivation import derive_nostr_keys

        with pytest.raises(ValueError, match="Invalid BIP39 mnemonic"):
            derive_nostr_keys("invalid mnemonic words")


class TestGenerateSignalSeed:
    """Tests for generate_signal_seed function."""

    TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

    def test_returns_32_bytes(self):
        """Signal seed should be 32 bytes for X25519."""
        from ming_drlms.core.nostr_derivation import generate_signal_seed

        seed = generate_signal_seed(self.TEST_MNEMONIC)
        assert len(seed) == 32

    def test_deterministic(self):
        """Same mnemonic should produce same seed."""
        from ming_drlms.core.nostr_derivation import generate_signal_seed

        seed1 = generate_signal_seed(self.TEST_MNEMONIC)
        seed2 = generate_signal_seed(self.TEST_MNEMONIC)
        assert seed1 == seed2

    def test_passphrase_changes_seed(self):
        """Passphrase should produce different seed."""
        from ming_drlms.core.nostr_derivation import generate_signal_seed

        seed_no_pass = generate_signal_seed(self.TEST_MNEMONIC)
        seed_with_pass = generate_signal_seed(self.TEST_MNEMONIC, passphrase="test")
        assert seed_no_pass != seed_with_pass

    def test_different_from_nostr_private_key(self):
        """Signal seed should be different from Nostr private key."""
        from ming_drlms.core.nostr_derivation import (
            derive_nostr_keys,
            generate_signal_seed,
        )

        nostr = derive_nostr_keys(self.TEST_MNEMONIC)
        signal_seed = generate_signal_seed(self.TEST_MNEMONIC)
        assert nostr.private_key != signal_seed


class TestGeneratePqcSeed:
    """Tests for generate_pqc_seed function."""

    TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

    def test_returns_64_bytes(self):
        """PQC seed should be 64 bytes for ML-KEM-768."""
        from ming_drlms.core.nostr_derivation import generate_pqc_seed

        seed = generate_pqc_seed(self.TEST_MNEMONIC)
        assert len(seed) == 64

    def test_deterministic(self):
        """Same mnemonic should produce same seed."""
        from ming_drlms.core.nostr_derivation import generate_pqc_seed

        seed1 = generate_pqc_seed(self.TEST_MNEMONIC)
        seed2 = generate_pqc_seed(self.TEST_MNEMONIC)
        assert seed1 == seed2

    def test_different_from_signal_seed(self):
        """PQC seed should be different from Signal seed."""
        from ming_drlms.core.nostr_derivation import (
            generate_signal_seed,
            generate_pqc_seed,
        )

        signal = generate_signal_seed(self.TEST_MNEMONIC)
        pqc = generate_pqc_seed(self.TEST_MNEMONIC)
        # First 32 bytes comparison (since PQC is 64 bytes)
        assert signal != pqc[:32]
