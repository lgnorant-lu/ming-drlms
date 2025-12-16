"""Phase 27: Post-Quantum Key Encapsulation Mechanism Wrapper.

This module provides a high-level wrapper for ML-KEM-768 (Kyber768)
key encapsulation using the liboqs-python library.

ML-KEM-768 is one of the NIST-standardized post-quantum algorithms
providing 128-bit classical security and quantum resistance.

Dependencies:
    - liboqs-python >= 0.14.1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import oqs

    LIBOQS_AVAILABLE = True
except (ImportError, RuntimeError, OSError, AttributeError):
    LIBOQS_AVAILABLE = False


__all__ = [
    "MLKEM768",
    "PQCKeyPair",
    "hybrid_key_derive",
    "is_pqc_available",
]


# ML-KEM-768 key/ciphertext sizes
MLKEM768_PUBLIC_KEY_SIZE = 1184
MLKEM768_SECRET_KEY_SIZE = 2400
MLKEM768_CIPHERTEXT_SIZE = 1088
MLKEM768_SHARED_SECRET_SIZE = 32


def is_pqc_available() -> bool:
    """Check if liboqs is available for PQC operations."""
    return LIBOQS_AVAILABLE


@dataclass(frozen=True, slots=True)
class PQCKeyPair:
    """ML-KEM-768 key pair.

    Attributes:
        public_key: 1184-byte ML-KEM-768 public key
        secret_key: 2400-byte ML-KEM-768 secret key (optional, for storage)
    """

    public_key: bytes
    secret_key: Optional[bytes] = None

    def public_key_hex(self) -> str:
        """Get public key as hex string."""
        return self.public_key.hex()


class MLKEM768:
    """ML-KEM-768 (Kyber768) Key Encapsulation Mechanism.

    This class wraps liboqs KeyEncapsulation for ML-KEM-768.
    It provides methods for:
    - Generating key pairs
    - Encapsulating shared secrets (sender side)
    - Decapsulating ciphertexts (receiver side)

    Example usage:
        # Key generation (receiver)
        kem = MLKEM768()
        public_key = kem.generate_keypair()

        # Encapsulation (sender)
        sender_kem = MLKEM768()
        ciphertext, shared_secret = sender_kem.encapsulate(public_key)

        # Decapsulation (receiver)
        shared_secret = kem.decapsulate(ciphertext)
    """

    ALGORITHM = "ML-KEM-768"

    def __init__(self) -> None:
        """Initialize ML-KEM-768 wrapper."""
        if not LIBOQS_AVAILABLE:
            raise ImportError(
                "liboqs-python is required for PQC. "
                "Install with: pip install liboqs-python"
            )
        self._kem: Optional[oqs.KeyEncapsulation] = None
        self._public_key: Optional[bytes] = None
        self._has_secret_key = False

    def _ensure_kem(self) -> oqs.KeyEncapsulation:
        """Lazily initialize KEM instance."""
        if self._kem is None:
            self._kem = oqs.KeyEncapsulation(self.ALGORITHM)
        return self._kem

    def generate_keypair(self) -> bytes:
        """Generate a new ML-KEM-768 key pair.

        The secret key is stored internally for later decapsulation.
        Only the public key is returned for sharing.

        Returns:
            1184-byte public key
        """
        kem = self._ensure_kem()
        self._public_key = kem.generate_keypair()
        self._has_secret_key = True
        return self._public_key

    def generate_keypair_from_seed(self, seed: bytes) -> bytes:
        """Generate key pair deterministically from seed.

        Args:
            seed: Seed bytes (must match required length)

        Returns:
            1184-byte public key
        """
        kem = self._ensure_kem()
        required_len = kem.length_keypair_seed
        if len(seed) < required_len:
            # Extend seed using HKDF if too short
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives import hashes

            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=required_len,
                salt=None,
                info=b"mlkem768-keypair-seed",
            )
            seed = hkdf.derive(seed)

        self._public_key = kem.generate_keypair_seed(seed[:required_len])
        self._has_secret_key = True
        return self._public_key

    def encapsulate(self, peer_public_key: bytes) -> Tuple[bytes, bytes]:
        """Encapsulate a shared secret for a peer's public key.

        This is called by the sender to create:
        - A ciphertext to send to the receiver
        - A shared secret (same as receiver will derive)

        Args:
            peer_public_key: Receiver's 1184-byte ML-KEM-768 public key

        Returns:
            Tuple of (ciphertext: 1088 bytes, shared_secret: 32 bytes)

        Raises:
            ValueError: If public key size is incorrect
        """
        if len(peer_public_key) != MLKEM768_PUBLIC_KEY_SIZE:
            raise ValueError(
                f"Invalid public key size: {len(peer_public_key)}, "
                f"expected {MLKEM768_PUBLIC_KEY_SIZE}"
            )

        kem = self._ensure_kem()
        ciphertext, shared_secret = kem.encap_secret(peer_public_key)
        return ciphertext, shared_secret

    def decapsulate(self, ciphertext: bytes) -> bytes:
        """Decapsulate a ciphertext to recover the shared secret.

        This is called by the receiver using their secret key.
        The secret key must have been generated via generate_keypair().

        Args:
            ciphertext: 1088-byte ciphertext from sender

        Returns:
            32-byte shared secret

        Raises:
            ValueError: If no secret key available or ciphertext size wrong
        """
        if not self._has_secret_key:
            raise ValueError("No secret key available. Call generate_keypair() first.")

        if len(ciphertext) != MLKEM768_CIPHERTEXT_SIZE:
            raise ValueError(
                f"Invalid ciphertext size: {len(ciphertext)}, "
                f"expected {MLKEM768_CIPHERTEXT_SIZE}"
            )

        kem = self._ensure_kem()
        return kem.decap_secret(ciphertext)

    def export_keypair(self) -> PQCKeyPair:
        """Export the current key pair for storage.

        Returns:
            PQCKeyPair with public and secret keys
        """
        if not self._has_secret_key or self._public_key is None:
            raise ValueError("No key pair generated")

        kem = self._ensure_kem()
        return PQCKeyPair(
            public_key=self._public_key,
            secret_key=kem.export_secret_key(),
        )

    def import_secret_key(self, secret_key: bytes) -> None:
        """Import a previously exported secret key.

        Args:
            secret_key: 2400-byte ML-KEM-768 secret key
        """
        if len(secret_key) != MLKEM768_SECRET_KEY_SIZE:
            raise ValueError(
                f"Invalid secret key size: {len(secret_key)}, "
                f"expected {MLKEM768_SECRET_KEY_SIZE}"
            )

        # liboqs-python doesn't have direct secret key import
        # We need to store it and reconstruct the KEM state
        # For now, we'll raise NotImplementedError
        raise NotImplementedError(
            "Secret key import not yet supported. "
            "Use generate_keypair_from_seed() for deterministic key recovery."
        )

    def close(self) -> None:
        """Clean up resources."""
        if self._kem is not None:
            self._kem = None
            self._public_key = None
            self._has_secret_key = False

    def __enter__(self) -> "MLKEM768":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def hybrid_key_derive(
    x25519_shared: bytes,
    pqc_shared: bytes,
    info: bytes = b"ming-drlms-hybrid-pqxdh-v1",
) -> bytes:
    """Derive hybrid shared secret from X25519 and ML-KEM-768 secrets.

    This combines classical ECDH and post-quantum KEM shared secrets
    using HKDF to provide security against both classical and quantum
    adversaries.

    Args:
        x25519_shared: 32-byte X25519 DH shared secret
        pqc_shared: 32-byte ML-KEM-768 shared secret
        info: HKDF info parameter for domain separation

    Returns:
        32-byte hybrid shared secret
    """
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    # Concatenate shared secrets
    combined = x25519_shared + pqc_shared

    # Derive final key using HKDF
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=info,
    )
    return hkdf.derive(combined)
