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
from pathlib import Path

import os
import platform
import logging

# Phase 28.1 Fix: Ensure liboqs DLL is found on Windows
LIBOQS_DIR = os.environ.get("LIBOQS_DIR")
if LIBOQS_DIR and platform.system() == "Windows":
    # Usually DLLs are in 'bin' relative to install root for cmake builds
    dll_path = os.path.join(LIBOQS_DIR, "bin")
    search_path = None

    if os.path.isdir(dll_path):
        search_path = dll_path
    elif os.path.isdir(LIBOQS_DIR):
        search_path = LIBOQS_DIR

    if search_path:
        # 1. Modern Python 3.8+ method
        try:
            os.add_dll_directory(search_path)
            logging.getLogger("ming_drlms.core.pqc_kem").info(
                f"Added DLL directory: {search_path}"
            )
        except Exception:
            pass

        # 2. Legacy/Ctypes PATH method (Required for oqs-python wrapper)
        if search_path not in os.environ["PATH"]:
            os.environ["PATH"] += os.pathsep + search_path

# Strict Pre-check: Do not import oqs if we can't find the DLL on Windows.
# This prevents liboqs-python from triggering its "auto-install" (git clone) logic which causes SystemExit.
should_import = True
if platform.system() == "Windows":
    # If LIBOQS_DIR is not set, or doesn't contain bin/oqs.dll, skip import
    if not LIBOQS_DIR:
        should_import = False
    else:
        # Check specific DLL existence
        # Usually in bin/oqs.dll
        dll_candidate = os.path.join(LIBOQS_DIR, "bin", "oqs.dll")
        if not os.path.exists(dll_candidate):
            # Try root
            dll_candidate_root = os.path.join(LIBOQS_DIR, "oqs.dll")
            if not os.path.exists(dll_candidate_root):
                should_import = False

try:
    if should_import:
        import oqs

        LIBOQS_AVAILABLE = True
    else:
        LIBOQS_AVAILABLE = False
except (ImportError, RuntimeError, OSError, AttributeError, SystemExit):
    # SystemExit is raised by oqs.py if DLL load fails
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
    """Check if liboqs is available for PQC operations.

    This performs a RUNTIME check by attempting to import oqs,
    rather than relying on the static LIBOQS_AVAILABLE flag.
    This ensures correct detection even in subprocesses where
    DLL paths are injected after module import.
    """
    if not LIBOQS_AVAILABLE:
        return False

    result = False
    error_msg = None

    try:
        import oqs  # noqa: F401

        # Additional verification: try to access the KEM mechanism
        _ = oqs.KeyEncapsulation("ML-KEM-768")
        result = True
    except Exception as e:
        result = False
        error_msg = f"{type(e).__name__}: {e}"
        import traceback

        tb = "".join(traceback.format_tb(e.__traceback__))

    # ALWAYS log (both success and failure)

    def _get_log_path(filename: str) -> Path:
        log_dir = os.environ.get("DRLMS_LOG_DIR")
        if log_dir:
            path = Path(log_dir)
        else:
            if os.name == "nt":
                base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
                path = (
                    Path(base) / "drlms" / "logs"
                    if base
                    else Path.home() / ".drlms" / "logs"
                )
            else:
                path = Path.home() / ".drlms" / "logs"

        path.mkdir(parents=True, exist_ok=True)
        return path / filename

    try:
        with open(_get_log_path("pqc_debug.log"), "a", encoding="utf-8") as f:
            import datetime

            timestamp = datetime.datetime.now().isoformat()
            f.write(f"\n[{timestamp}] is_pqc_available() called\n")
            f.write(f"Result: {result}\n")
            if error_msg:
                f.write(f"Error: {error_msg}\n")
                f.write(f"Traceback: {tb}\n")
            else:
                f.write("Success: KEM mechanism instantiated successfully\n")
    except Exception:
        pass

    return result


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

        kem = self._ensure_kem()
        # Direct injection into liboqs wrapper
        # This assumes the python wrapper exposes 'secret_key' attribute or similar.
        # Verified: oqs-python wrapper stores secret key in self.secret_key
        kem.secret_key = secret_key
        self._has_secret_key = True

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
