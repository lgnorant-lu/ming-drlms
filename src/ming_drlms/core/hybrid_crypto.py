"""Phase 27: Hybrid Post-Quantum Encryption Layer.

This module provides hybrid encryption combining:
- X25519 Ephemeral Diffie-Hellman (classical)
- ML-KEM-768 Key Encapsulation (post-quantum)
- AES-256-GCM for symmetric encryption

The hybrid shared secret is derived as:
    shared = HKDF(X25519_shared || ML-KEM_shared, info="ming-drlms-hybrid")

This provides security against both classical and quantum adversaries.

Dependencies:
    - cryptography (for X25519, AES-GCM, HKDF)
    - liboqs-python (for ML-KEM-768), optional graceful degradation
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

try:
    from .pqc_kem import MLKEM768, is_pqc_available
except ImportError:
    MLKEM768 = None  # type: ignore
    is_pqc_available = lambda: False  # noqa: E731


__all__ = [
    "HybridEncryptResult",
    "HybridCrypto",  # ← Add class wrapper
    "hybrid_encrypt",
    "hybrid_decrypt",
    "is_hybrid_available",
]


# AES-GCM nonce size
NONCE_SIZE = 12
# HKDF info for hybrid key derivation
HYBRID_INFO = b"ming-drlms-pqc-hybrid-v1"


@dataclass(frozen=True, slots=True)
class HybridEncryptResult:
    """Result of hybrid encryption.

    Attributes:
        wrapped_ciphertext: AES-GCM encrypted payload (nonce || ciphertext || tag)
        pqc_ciphertext: ML-KEM-768 ciphertext (1088 bytes)
        ephemeral_pub: X25519 ephemeral public key (32 bytes)
    """

    wrapped_ciphertext: bytes
    pqc_ciphertext: bytes
    ephemeral_pub: bytes


# Static class wrapper for backward compatibility with tools.py
class HybridCrypto:
    """Static class wrapper for hybrid encryption functions."""

    @staticmethod
    def encrypt(
        plaintext: bytes, peer_x25519_pub: bytes, peer_pqc_pub: bytes
    ) -> HybridEncryptResult:
        """Wrapper for hybrid_encrypt function."""
        return hybrid_encrypt(plaintext, peer_x25519_pub, peer_pqc_pub)

    @staticmethod
    def hybrid_decrypt(
        wrapped_ciphertext: bytes,
        pqc_ciphertext: bytes,
        ephemeral_pub: bytes,
        my_x25519_priv: bytes,
        my_pqc_kem: "MLKEM768",
    ) -> bytes:
        """Wrapper for hybrid_decrypt function."""
        return hybrid_decrypt(
            wrapped_ciphertext,
            pqc_ciphertext,
            ephemeral_pub,
            my_x25519_priv,
            my_pqc_kem,
        )


def is_hybrid_available() -> bool:
    """Check if hybrid encryption is available (requires liboqs)."""
    return is_pqc_available()


def _derive_hybrid_key(
    x25519_shared: bytes,
    pqc_shared: bytes,
) -> bytes:
    """Derive 256-bit AES key from hybrid shared secrets."""
    combined = x25519_shared + pqc_shared
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=HYBRID_INFO,
    )
    return hkdf.derive(combined)


def hybrid_encrypt(
    plaintext: bytes,
    peer_x25519_pub: bytes,
    peer_pqc_pub: bytes,
) -> HybridEncryptResult:
    """Encrypt data using hybrid X25519 + ML-KEM-768 + AES-GCM.

    Process:
    1. Generate ephemeral X25519 key pair
    2. Compute X25519 shared secret with peer's public key
    3. Encapsulate shared secret using peer's ML-KEM-768 public key
    4. Derive AES key from combined shared secrets via HKDF
    5. Encrypt plaintext with AES-256-GCM

    Args:
        plaintext: Data to encrypt
        peer_x25519_pub: Peer's X25519 public key (32 bytes)
        peer_pqc_pub: Peer's ML-KEM-768 public key (1184 bytes)

    Returns:
        HybridEncryptResult with wrapped ciphertext and key material

    Raises:
        ImportError: If liboqs is not available
        ValueError: If key sizes are incorrect
    """
    if not is_pqc_available():
        raise ImportError("liboqs-python required for hybrid encryption")

    if len(peer_x25519_pub) != 32:
        raise ValueError(f"Invalid X25519 public key size: {len(peer_x25519_pub)}")

    if len(peer_pqc_pub) != 1184:
        raise ValueError(f"Invalid ML-KEM-768 public key size: {len(peer_pqc_pub)}")

    # 1. Generate ephemeral X25519 key pair
    ephemeral_priv = X25519PrivateKey.generate()
    ephemeral_pub = ephemeral_priv.public_key().public_bytes_raw()

    # 2. X25519 DH to derive shared secret
    peer_pub = X25519PublicKey.from_public_bytes(peer_x25519_pub)
    x25519_shared = ephemeral_priv.exchange(peer_pub)

    # 3. ML-KEM-768 encapsulation
    kem = MLKEM768()
    pqc_ciphertext, pqc_shared = kem.encapsulate(peer_pqc_pub)

    # 4. Derive AES key
    aes_key = _derive_hybrid_key(x25519_shared, pqc_shared)

    # 5. AES-GCM encryption
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)

    # Wrapped format: nonce || ciphertext (includes tag)
    wrapped = nonce + ciphertext

    return HybridEncryptResult(
        wrapped_ciphertext=wrapped,
        pqc_ciphertext=pqc_ciphertext,
        ephemeral_pub=ephemeral_pub,
    )


def hybrid_decrypt(
    wrapped_ciphertext: bytes,
    pqc_ciphertext: bytes,
    ephemeral_pub: bytes,
    my_x25519_priv: bytes,
    my_pqc_kem: "MLKEM768",
) -> bytes:
    """Decrypt hybrid-encrypted data.

    Process:
    1. Compute X25519 shared secret with ephemeral public key
    2. Decapsulate ML-KEM-768 ciphertext to get PQC shared secret
    3. Derive AES key from combined shared secrets
    4. Decrypt AES-GCM ciphertext

    Args:
        wrapped_ciphertext: AES-GCM encrypted data (nonce || ct || tag)
        pqc_ciphertext: ML-KEM-768 ciphertext (1088 bytes)
        ephemeral_pub: Sender's ephemeral X25519 public key (32 bytes)
        my_x25519_priv: My X25519 private key (32 bytes)
        my_pqc_kem: My ML-KEM-768 instance with secret key loaded

    Returns:
        Decrypted plaintext

    Raises:
        ValueError: If decryption fails or sizes are incorrect
    """
    if len(ephemeral_pub) != 32:
        raise ValueError(f"Invalid ephemeral public key size: {len(ephemeral_pub)}")

    if len(wrapped_ciphertext) < NONCE_SIZE + 16:  # minimum: nonce + tag
        raise ValueError("Wrapped ciphertext too short")

    # 1. X25519 DH
    my_priv = X25519PrivateKey.from_private_bytes(my_x25519_priv)
    peer_ephemeral = X25519PublicKey.from_public_bytes(ephemeral_pub)
    x25519_shared = my_priv.exchange(peer_ephemeral)

    # 2. ML-KEM-768 decapsulation
    pqc_shared = my_pqc_kem.decapsulate(pqc_ciphertext)

    # 3. Derive AES key
    aes_key = _derive_hybrid_key(x25519_shared, pqc_shared)

    # 4. AES-GCM decryption
    nonce = wrapped_ciphertext[:NONCE_SIZE]
    ciphertext = wrapped_ciphertext[NONCE_SIZE:]
    aesgcm = AESGCM(aes_key)

    return aesgcm.decrypt(nonce, ciphertext, None)
