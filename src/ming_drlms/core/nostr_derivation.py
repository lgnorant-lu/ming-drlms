"""Phase 27: Nostr Key Derivation from BIP39 Mnemonic (NIP-06).

This module provides deterministic Nostr key derivation from a BIP39 mnemonic
using the standard NIP-06 derivation path.

Reference: https://github.com/nostr-protocol/nips/blob/master/06.md
Path: m/44'/1237'/account'/0/index

Dependencies:
    - bip_utils >= 2.10.0
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from bip_utils import (
        Bip39MnemonicValidator,
        Bip39SeedGenerator,
        Bip39MnemonicGenerator,
        Bip32Slip10Secp256k1,
    )

    BIP_UTILS_AVAILABLE = True
except ImportError:
    BIP_UTILS_AVAILABLE = False


__all__ = [
    "NostrKeyPair",
    "derive_nostr_keys",
    "validate_mnemonic",
    "generate_signal_seed",
    "generate_mnemonic",
]


@dataclass(frozen=True, slots=True)
class NostrKeyPair:
    """Nostr key pair derived from mnemonic.

    Attributes:
        private_key: 32-byte Secp256k1 private key (raw bytes)
        public_key: 33-byte compressed Secp256k1 public key
        public_key_x_only: 32-byte x-only public key (for Nostr npub)
    """

    private_key: bytes
    public_key: bytes
    public_key_x_only: bytes

    def private_key_hex(self) -> str:
        """Get private key as hex string (nsec format input)."""
        return self.private_key.hex()

    def public_key_hex(self) -> str:
        """Get x-only public key as hex string (npub format input)."""
        return self.public_key_x_only.hex()


def validate_mnemonic(mnemonic: str, language: str = "english") -> bool:
    """Validate a BIP39 mnemonic phrase.

    Args:
        mnemonic: Space-separated mnemonic words
        language: Language for validation (default: english) - currently not used

    Returns:
        True if mnemonic is valid, False otherwise
    """
    if not BIP_UTILS_AVAILABLE:
        raise ImportError("bip_utils is required for mnemonic validation")

    try:
        # bip_utils 2.10.0: Bip39MnemonicValidator() takes no args
        # Validate() takes the mnemonic string directly
        Bip39MnemonicValidator().Validate(mnemonic)
        return True
    except Exception:
        return False


def derive_nostr_keys(
    mnemonic: str,
    account: int = 0,
    index: int = 0,
    passphrase: str = "",
) -> NostrKeyPair:
    """Derive Nostr keys from BIP39 mnemonic using NIP-06.

    NIP-06 specifies the derivation path: m/44'/1237'/account'/0/index
    where 1237 is the Nostr coin type registered in SLIP-44.

    Args:
        mnemonic: BIP39 mnemonic phrase (12, 15, 18, 21, or 24 words)
        account: Account index (default: 0)
        index: Key index within account (default: 0)
        passphrase: Optional BIP39 passphrase

    Returns:
        NostrKeyPair with derived keys

    Raises:
        ImportError: If bip_utils is not installed
        ValueError: If mnemonic is invalid
    """
    if not BIP_UTILS_AVAILABLE:
        raise ImportError(
            "bip_utils is required for NIP-06 derivation. "
            "Install with: pip install bip_utils"
        )

    # Validate mnemonic
    if not validate_mnemonic(mnemonic):
        raise ValueError("Invalid BIP39 mnemonic")

    # Generate seed from mnemonic
    seed = Bip39SeedGenerator(mnemonic).Generate(passphrase)

    # Derive key using SLIP-10 Secp256k1 (compatible with Nostr)
    # Path: m/44'/1237'/account'/0/index
    bip32_ctx = Bip32Slip10Secp256k1.FromSeed(seed)
    derived = bip32_ctx.DerivePath(f"m/44'/1237'/{account}'/0/{index}")

    # Extract keys
    private_key = derived.PrivateKey().Raw().ToBytes()
    public_key_compressed = derived.PublicKey().RawCompressed().ToBytes()

    # X-only public key (drop the 02/03 prefix, keep only X coordinate)
    # For Nostr, we use the x-only format (32 bytes)
    public_key_x_only = public_key_compressed[1:]  # Remove prefix byte

    return NostrKeyPair(
        private_key=private_key,
        public_key=public_key_compressed,
        public_key_x_only=public_key_x_only,
    )


def generate_signal_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Generate a 32-byte seed for Signal/X25519 key derivation.

    This uses HKDF to derive a separate key for Signal protocol
    from the same mnemonic, ensuring key separation.

    Args:
        mnemonic: BIP39 mnemonic phrase
        passphrase: Optional BIP39 passphrase

    Returns:
        32-byte seed suitable for X25519 key generation
    """
    if not BIP_UTILS_AVAILABLE:
        raise ImportError("bip_utils is required")

    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    # Generate master seed
    master_seed = Bip39SeedGenerator(mnemonic).Generate(passphrase)

    # Derive Signal-specific seed using HKDF
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"ming-drlms-signal-x25519-v1",
    )
    return hkdf.derive(master_seed)


def generate_pqc_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Generate a seed for PQC (ML-KEM-768) key derivation.

    Args:
        mnemonic: BIP39 mnemonic phrase
        passphrase: Optional BIP39 passphrase

    Returns:
        Seed suitable for ML-KEM-768 deterministic key generation
    """
    if not BIP_UTILS_AVAILABLE:
        raise ImportError("bip_utils is required")

    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    master_seed = Bip39SeedGenerator(mnemonic).Generate(passphrase)

    # ML-KEM-768 needs 64 bytes for deterministic key generation
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=None,
        info=b"ming-drlms-mlkem768-v1",
    )
    return hkdf.derive(master_seed)


def generate_mnemonic(strength: int = 128) -> str:
    """Generate a random BIP39 mnemonic phrase.

    Args:
        strength: Entropy strength (128=12words, 256=24words)

    Returns:
        Space-separated mnemonic string
    """
    if not BIP_UTILS_AVAILABLE:
        raise ImportError("bip_utils is required")

    return Bip39MnemonicGenerator().FromWordsNumber(12 if strength == 128 else 24)
