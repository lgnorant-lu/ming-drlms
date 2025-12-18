"""Phase 28.1 (Soul Injection): Real E2EE & Blossom Integration.

This module defines the MCP tools that AI agents can call.
Updated for "Phase 28.1" to wiring real Hybrid Crypto and Blossom Network components.

Tools:
    - generate_identity: Create/Restore identity (supporting Quantum security level)
    - store_secret: Encrypts with HybridCrypto and uploads to Blossom Network
    - retrieve_secret: Downloads from Blossom Network and decrypts with HybridCrypto

SECURITY NOTE:
    - Now using REAL encryption (X25519 or X25519+ML-KEM-768).
    - Data is stored on decentralized Blossom servers.
"""

from __future__ import annotations

import logging
import json
import base64
import os
from pathlib import Path

# Standard crypto imports (always available)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PublicKey,
    X25519PrivateKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .server import mcp

# --- CORE WIRING ---
from ming_drlms.core.identity_manager import IdentityManager
from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.nostr_derivation import generate_mnemonic
from ming_drlms.core.blossom import BlossomClient

# Graceful degradation for crypto
import_success = False
import_error = None

try:
    from ming_drlms.core.hybrid_crypto import HybridCrypto
    from ming_drlms.core.pqc_kem import is_pqc_available

    import_success = True
except ImportError as e:
    import_error = str(e)
    HybridCrypto = None  # type: ignore

    def is_pqc_available() -> bool:
        return False


# Log import result (bypassing stdio hijack)
try:
    import os
    from pathlib import Path

    def _get_log_path(filename: str) -> Path:
        log_dir = os.environ.get("DRLMS_LOG_DIR")
        if log_dir:
            path = Path(log_dir)
        else:
            # Fallback based on OS
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

    with open(_get_log_path("import_debug.log"), "a", encoding="utf-8") as f:
        import datetime

        f.write(f"\n[{datetime.datetime.now().isoformat()}] tools.py crypto import\n")
        f.write(f"Success: {import_success}\n")
        if import_error:
            f.write(f"Error: {import_error}\n")
except Exception:
    pass

logger = logging.getLogger("ming_drlms.mcp.tools")


@mcp.tool()
def generate_identity(
    username: str,
    security_level: str = "standard",
) -> dict:
    """Generate or restore a cryptographic identity.

    Creates a new identity for the Agent.

    Args:
        username: User identifier (e.g., "agent-007")
        security_level: 'standard' (X25519) or 'quantum' (X25519 + ML-KEM-768)

    Returns:
        Dictionary containing the public identity (safe to share).
    """
    logger.info("Generating identity for %s (level=%s)", username, security_level)

    # 1. Liboqs Graceful Degradation Check
    if security_level == "quantum" and not is_pqc_available():
        logger.warning("[PQC] liboqs not found! Downgrading to standard security.")
        security_level = "standard"

    keystore = LocalKeyStore()

    # Check if exists
    state = keystore.load_state(username)
    created = False

    if state is None:
        # Create new
        mnemonic = generate_mnemonic()
        logger.info("Auto-generated mnemonic for new identity '%s'", username)

        # IdentityManager autodetects liboqs
        manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=keystore)
        created = True
    else:
        # Load existing
        manager = IdentityManager(username, keystore=keystore)

    # Determine actual security level from generated/loaded identity
    # Even if environment check failed ("is_pqc_available() == False"),
    # we might have loaded an existing identity that HAS valid PQC keys.
    # We should report the level based on what the identity actually possesses.
    actual_level = "quantum" if manager.has_pqc_key() else "standard"

    # Prepare return dict
    result = {
        "username": username,
        "pubkey_hex": manager.get_pubkey_hex(),
        "security_level": actual_level,
        "has_pqc": manager.has_pqc_key(),
        "created": created,
        "fingerprint": manager.get_pubkey_hex()[:16],
    }

    # Add PQC key hex if available (for easy transfer)
    pqc_pub = manager.get_pqc_public_key()
    if pqc_pub:
        result["pqc_pubkey_hex"] = pqc_pub.hex()

    return result


@mcp.tool()
def list_identities() -> str:
    """List all locally available cryptographic identities.

    Use this tool to find usernames and public keys before calling other tools.

    Returns:
        JSON string of identity summaries.
    """
    import sys

    sys.stderr.write("[DEBUG] list_identities called\n")

    keystore = LocalKeyStore()
    sys.stderr.write(f"[DEBUG] Keystore path: {keystore._path}\n")

    results = []

    try:
        if os.path.exists(keystore._path):
            with open(keystore._path, "r", encoding="utf-8") as f:
                root_data = json.load(f)

            # Handle "users" nesting (standard schema)
            users_data = root_data.get("users", root_data)

            sys.stderr.write(f"[DEBUG] Loaded {len(users_data)} potential entries\n")

            for uname, info in users_data.items():
                if not isinstance(info, dict):
                    continue

                # Extract Identity Key (Signal Format)
                # stored as: "identity": {"public": "hex", "private": "hex"}
                ident = info.get("identity")
                pub_hex = "unknown"
                if isinstance(ident, dict) and "public" in ident:
                    pub_hex = ident["public"]
                    # Strip Signal type prefix (0x05) if present (33 bytes -> 32 bytes)
                    if len(pub_hex) == 66 and pub_hex.startswith("05"):
                        pub_hex = pub_hex[2:]  # Remove first byte
                elif isinstance(ident, str):  # Legacy/fallback
                    pub_hex = ident
                    if len(pub_hex) == 66 and pub_hex.startswith("05"):
                        pub_hex = pub_hex[2:]

                # Extract PQC Key (Direct Hex)
                pqc_hex = info.get("pqc_public_key")

                # Extract Nostr Key (Direct Hex, Phase 28.2)
                nostr_hex = info.get("nostr_public_key")

                results.append(
                    {
                        "username": uname,
                        "pubkey_hex": pub_hex,
                        "pqc_pubkey_hex": pqc_hex,
                        "nostr_pubkey_hex": nostr_hex,
                        "has_pqc": bool(pqc_hex),
                    }
                )
        else:
            sys.stderr.write("[DEBUG] Keystore file not found\n")
            logger.warning(f"Keystore not found at {keystore._path}")

    except Exception as e:
        logger.error(f"Failed to list identities: {e}")
        return json.dumps([])

    if not results:
        sys.stderr.write("[DEBUG] Results empty, adding diagnostic\n")
        results.append(
            {
                "username": "[SYSTEM_DIAGNOSTIC]",
                "pubkey_hex": f"Keystore Path: {keystore._path} (Exists: {os.path.exists(keystore._path)})",
                "has_pqc": False,
            }
        )

    return json.dumps(results, indent=2)


# ============================================================================
# Ephemeral KeyStore for Temporary Identities
# ============================================================================


class EphemeralKeyStore(LocalKeyStore):
    """In-memory key store that does not persist to disk.

    Used for creating temporary identities needed for Blossom NIP-98
    authentication without cluttering the user's permanent keystore.

    Implementation Notes:
    - Overrides _persist() to prevent disk writes
    - Initializes with correct {"users": {}} structure
    - Thread-safe like parent class
    """

    def __init__(self) -> None:
        # Initialize path (dummy, never used for I/O)
        self._path = Path(":memory:")

        # Initialize with correct structure matching LocalKeyStore
        self._data: dict = {"users": {}}

        # Mark as already loaded to skip file I/O
        self._loaded = True

        # Thread safety
        import threading

        self._lock = threading.Lock()

    def _persist(self) -> None:
        """No-op: ephemeral store doesn't persist to disk.

        This is called by _store_user_payload after updating _data.
        We skip the file write but keep the data in memory.
        """
        pass  # Data stays in self._data, accessible via _load_user_payload


@mcp.tool()
def store_secret(
    recipient_x25519_hex: str,
    secret_content: str,
    recipient_pqc_hex: str | None = None,
    ttl_hours: int = 24,
) -> str:
    """Encrypt and store a secret to the Dead Drop (Blossom Network).

    Real E2EE Implementation.

    Args:
        recipient_x25519_hex: The recipient's primary X25519 public key (64-char hex).
        secret_content: The actual text content to encrypt.
        recipient_pqc_hex: (Optional) The recipient's PQC public key (ML-KEM-768) for Quantum-Resistant encryption.
                           If provided, Hybrid Encryption is used. Highly recommended.
        ttl_hours: Time-to-live in hours (default 24).

    Returns:
        A 'blossom://...' URI string that can be shared with the recipient.
    """
    logger.info("encrypting secret... (TTL=%dh)", ttl_hours)

    # Create Ephemeral Identity for Blossom NIP-98 Authentication
    # This temporary identity signs the HTTP upload request without polluting keystore
    auth_manager = None
    try:
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.nostr_derivation import generate_mnemonic

        logger.debug("[MCP] Generating ephemeral BIP39 mnemonic...")
        temp_mnemonic = generate_mnemonic()
        temp_username = f"blossom-uploader-{os.urandom(4).hex()}"
        ephemeral_store = EphemeralKeyStore()

        logger.debug(f"[MCP] Creating ephemeral identity: {temp_username}")
        auth_manager = IdentityManager.from_mnemonic(
            temp_mnemonic, temp_username, keystore=ephemeral_store
        )

        # Diagnostic: Verify identity was created
        logger.debug(f"[MCP] Ephemeral identity created: {temp_username}")
        logger.debug(
            f"[MCP] Keystore users: {list(ephemeral_store._data.get('users', {}).keys())}"
        )

        # Verify Nostr signer can be retrieved
        try:
            test_signer = auth_manager.get_nostr_signer()
            logger.debug(
                f"[MCP] Nostr signer OK: pubkey={test_signer.get_pubkey_hex()[:16]}..."
            )
        except Exception as e:
            logger.error(f"[MCP] Failed to get Nostr signer: {e}")
            raise

    except Exception as e:
        logger.error(f"[MCP] Failed to create ephemeral auth identity: {e}")
        import traceback

        logger.error(f"[MCP] Traceback: {traceback.format_exc()}")
        # Continue without auth (will likely fail) is BAD idea if we know it causes 401s.
        # Return error immediately so user knows why.
        error_msg = f"Failed to create ephemeral identity: {e} (Traceback in logs)"
        return json.dumps({"error": error_msg, "status": "auth_setup_failed"})

    try:
        peer_x25519 = bytes.fromhex(recipient_x25519_hex)
    except ValueError:
        return json.dumps({"error": "Invalid X25519 hex: must be 64 char hex"})

    # 2. Encrypt
    payload_bytes = secret_content.encode("utf-8")
    blob_b64 = ""
    alg = "standard-v1"

    # Diagnostic: Log PQC detection status
    pqc_available = is_pqc_available()
    logger.warning(
        f"[PQC DIAGNOSTIC] pqc_input={'present' if recipient_pqc_hex else 'absent'}, is_pqc_available()={pqc_available}, HybridCrypto={'loaded' if HybridCrypto else 'missing'}"
    )

    if recipient_pqc_hex and pqc_available and HybridCrypto:
        # --- QUANTUM HYBRID MODE ---
        try:
            peer_pqc_bytes = bytes.fromhex(recipient_pqc_hex)
        except ValueError:
            return json.dumps({"error": "Invalid PQC hex string"})

        logger.info("Using Hybrid PQC Encryption")
        # HybridCrypto returns a Result object, we need to serialize it
        res = HybridCrypto.encrypt(payload_bytes, peer_x25519, peer_pqc_bytes)

        # Serialize: wrapped_ct || pqc_ct || ephemeral_pub
        # We need to know lengths to parse back.
        # pqc_ct is fixed 1088 (ML-KEM-768), ephemeral is 32. wrapped is variable.
        # Format: [Ephemeral 32][PQC 1088][Wrapped Variable]
        combined_blob = res.ephemeral_pub + res.pqc_ciphertext + res.wrapped_ciphertext
        blob_b64 = base64.b64encode(combined_blob).decode("ascii")
        alg = "hybrid-v1"

    else:
        # --- STANDARD MODE (Fallback) ---
        if recipient_pqc_hex and not pqc_available:
            logger.warning(
                "PQC key provided but local PQC environment is missing. Falling back to Standard Mode."
            )

        logger.info("Using Standard X25519 Encryption")

        # Ephemeral Sender
        ephemeral_priv = X25519PrivateKey.generate()
        ephemeral_pub = ephemeral_priv.public_key().public_bytes_raw()

        # ECDH
        peer_pub_key = X25519PublicKey.from_public_bytes(peer_x25519)
        shared_secret = ephemeral_priv.exchange(peer_pub_key)

        # KDF (Simple SHA256)
        # We re-use logic similar to HybridCrypto but simpler
        import hashlib

        # HKDF to match Hybrid style but simpler context
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"ming-drlms-standard-v1",
        )
        aes_key = hkdf.derive(shared_secret)

        # AES-GCM
        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)

        # Format: [Ephemeral 32][Nonce 12][Ciphertext]
        combined_blob = ephemeral_pub + nonce + ciphertext
        blob_b64 = base64.b64encode(combined_blob).decode("ascii")
        alg = "standard-v1"

    # 3. Upload to Blossom with Authentication
    envelope = {"alg": alg, "blob": blob_b64}

    client = BlossomClient(identity_manager=auth_manager)
    try:
        blob_descr = client.upload_blob(json.dumps(envelope).encode("utf-8"))
    except Exception as e:
        return json.dumps({"error": f"Upload failed: {e}", "status": "network_error"})

    if "sha256" in blob_descr:
        uri = f"blossom://{blob_descr['sha256']}"
    elif "url" in blob_descr:
        uri = blob_descr["url"]
    else:
        # Fallback hash
        h = hashlib.sha256(json.dumps(envelope).encode("utf-8")).hexdigest()
        uri = f"blossom://{h}"

    logger.info(f"Stored ({alg}): %s", uri)

    # Return diagnostic info for debugging PQC activation
    return json.dumps(
        {
            "uri": uri,
            "encryption_mode": alg,
            "pqc_status": "available" if pqc_available else "unavailable",
            "note": "Share provided URI with the recipient.",
        }
    )


@mcp.tool()
def retrieve_secret(blossom_uri: str, recipient_username: str) -> dict:
    """Retrieve and decrypt a secret from a Dead Drop URI.

    Args:
        blossom_uri: The 'blossom://...' URI.
        recipient_username: The username of the recipient.

    Returns:
        The decrypted secret content and metadata.
    """
    logger.info("Retrieving secret from %s", blossom_uri)

    # 1. Resolve Identity
    keystore = LocalKeyStore()
    if keystore.load_state(recipient_username) is None:
        raise ValueError(f"Identity '{recipient_username}' not found locally.")

    manager = IdentityManager(recipient_username, keystore=keystore)

    # 2. Download
    client = BlossomClient()
    sha256 = blossom_uri.replace("blossom://", "")

    try:
        blob_bytes = client.download_blob(sha256)
    except Exception as e:
        raise ValueError(f"Download failed: {e}")

    # 3. Decrypt
    try:
        try:
            envelope = json.loads(blob_bytes)
        except json.JSONDecodeError as e:
            # Debugging: Show first 200 chars of what we got
            snippet = blob_bytes[:200].decode("utf-8", errors="replace")
            # If it looks like HTML, warn about server error
            hint = " (Server returned HTML?)" if "<html" in snippet.lower() else ""
            raise ValueError(
                f"Invalid JSON envelope from Blossom{hint}: {e}. Content snippet: {snippet!r}"
            )
        alg = envelope.get("alg", "unknown")
        blob_data = base64.b64decode(envelope["blob"])

        plaintext = b""

        if alg == "hybrid-v1":
            if not is_pqc_available():
                raise ValueError(
                    "Received Hybrid encrypted message but liboqs is missing!"
                )

            # Parse: [Ephemeral 32][PQC 1088][Wrapped ...]
            ephemeral_pub = blob_data[:32]
            pqc_ct = blob_data[32 : 32 + 1088]
            wrapped_ct = blob_data[32 + 1088 :]

            my_x25519 = manager.get_identity().private_key

            # Use raw PQC secret key (not exposed by Manager directly? check Manager)
            # Manager has _pqc_private_key but protected.
            # We explicitly aliased get_pqc_private_key in verification step.
            pqc_priv = manager.get_pqc_private_key()
            if not pqc_priv:
                raise ValueError("No PQC private key found for identity")

            # Re-init MLKEM to load secret key
            from ming_drlms.core.pqc_kem import MLKEM768

            kem = MLKEM768()
            kem.import_secret_key(pqc_priv)

            plaintext = HybridCrypto.hybrid_decrypt(
                wrapped_ct, pqc_ct, ephemeral_pub, my_x25519, kem
            )

        elif alg == "standard-v1":
            # Parse: [Ephemeral 32][Nonce 12][Ciphertext]
            ephemeral_pub = blob_data[:32]
            nonce = blob_data[32:44]
            ciphertext = blob_data[44:]

            # ECDH
            my_priv = X25519PrivateKey.from_private_bytes(
                manager.get_identity().private_key
            )
            peer_pub = X25519PublicKey.from_public_bytes(ephemeral_pub)
            shared = my_priv.exchange(peer_pub)

            # KDF
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives import hashes

            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=b"ming-drlms-standard-v1",
            )
            aes_key = hkdf.derive(shared)

            aesgcm = AESGCM(aes_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        else:
            raise ValueError(f"Unknown encryption algorithm: {alg}")

        return {
            "success": True,
            "secret_content": plaintext.decode("utf-8"),
            "sender_info": "Anonymous",
            "encryption_status": f"e2ee-{alg}",
        }

    except Exception as e:
        logger.error("Decryption failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "encryption_status": "decryption-failed",
        }


@mcp.tool()
def hello_world(name: str = "World") -> str:
    """A simple hello world tool for testing."""
    return f"Hello, {name}! Phase 28.1 E2EE is ACTIVE. Build: 2025-12-19-FIXED"
