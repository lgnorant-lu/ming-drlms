"""Phase 28 (Ultimate): MCP Tool Implementations.

This module defines the MCP tools that AI agents can call.
Updated for "Phase 28 Ultimate" to support Agent-to-Agent communication patterns.

Tools:
    - generate_identity: Create/Restore identity (supporting Quantum security level)
    - store_secret: Encrypt and store secret to Dead Drop (Blossom Network Mock)
    - retrieve_secret: Retrieve and decrypt secret from Dead Drop

SECURITY NOTE:
    - Metadata fields are NOT encrypted
    - All secrets are intended to be encrypted with hybrid PQC (Phase 28.1)
"""

from __future__ import annotations

import logging
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from .server import mcp

logger = logging.getLogger("ming_drlms.mcp.tools")


class BlossomMock:
    """Mock implementation of Blossom storage for Phase 28."""

    @staticmethod
    def _get_storage_dir() -> Path:
        # Use .drlms/blossom_mock for local dead drop
        import os

        base = os.environ.get("MING_DRLMS_CONFIG_DIR")
        if base:
            path = Path(base) / "blossom_mock"
        else:
            path = Path.home() / ".drlms" / "blossom_mock"

        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def store(cls, content: str, ttl_hours: int) -> str:
        """Store content and return a mock blossom URI."""
        blob_id = str(uuid.uuid4())
        data = {
            "content": content,
            "expires_at": time.time() + (ttl_hours * 3600),
            "created_at": time.time(),
        }

        path = cls._get_storage_dir() / f"{blob_id}.json"
        path.write_text(json.dumps(data))

        return f"blossom://{blob_id}"

    @classmethod
    def retrieve(cls, uri: str) -> Optional[str]:
        """Retrieve content from URI."""
        if not uri.startswith("blossom://"):
            raise ValueError("Invalid URI scheme")

        blob_id = uri.replace("blossom://", "")
        path = cls._get_storage_dir() / f"{blob_id}.json"

        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
            if time.time() > data.get("expires_at", 0):
                # Expired
                return None
            return data.get("content")
        except Exception:
            return None


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
    from ming_drlms.core.identity_manager import IdentityManager
    from ming_drlms.core.e2ee_store import LocalKeyStore

    logger.info("Generating identity for %s (level=%s)", username, security_level)

    keystore = LocalKeyStore()

    # Check if exists
    state = keystore.load_state(username)
    created = False

    if state is None:
        # Create new (using IdentityManager defaults)
        # Note: security_level 'quantum' implies we ensure PQC keys are generated
        # Phase 27 IdentityManager generates PQC keys by default if liboqs is present

        # Auto-generate mnemonic for the Agent
        from ming_drlms.core.nostr_derivation import generate_mnemonic

        mnemonic = generate_mnemonic()

        logger.info("Auto-generated mnemonic for new identity '%s'", username)
        manager = IdentityManager.from_mnemonic(mnemonic, username, keystore=keystore)
        created = True
    else:
        # Load existing
        manager = IdentityManager(username, keystore=keystore)

    return {
        "username": username,
        "pubkey_hex": manager.get_pubkey_hex(),
        "security_level": security_level,
        "has_pqc": manager.has_pqc_key(),
        "created": created,
        "fingerprint": manager.get_pubkey_hex()[:16],  # Short fingerprint
    }


@mcp.tool()
def store_secret(
    recipient_pubkey: str,
    secret_content: str,
    ttl_hours: int = 24,
) -> str:
    """Encrypt and store a secret to the Dead Drop (Blossom Network).

    This tool allows an Agent to send a secret to another Agent (identified by pubkey).

    Args:
        recipient_pubkey: The Hex Public Key of the recipient.
        secret_content: The actual secret data (will be encrypted).
        ttl_hours: Time-to-live in hours (default 24).

    Returns:
        A 'blossom://...' URI that refers to the stored secret.
    """
    # TODO (Phase 28.1): Perform E2EE encryption using recipient_pubkey
    # For now (Phase 28 Ultimate MVP): We store plaintext but MARK IT as such.
    # In a real scenario, this MUST be encrypted.

    logger.info("Storing secret for %s... (TTL=%dh)", recipient_pubkey[:8], ttl_hours)

    # Store to Blossom Mock
    # We wrap it to simulate an "Encrypted Message" envelope
    envelope = {
        "recipient": recipient_pubkey,
        "payload": secret_content,  # Plaintext for now (Mock Encryption)
        "encryption": "none (Phase 28.1 pending)",
    }

    uri = BlossomMock.store(json.dumps(envelope), ttl_hours)
    return uri


@mcp.tool()
def retrieve_secret(
    blossom_uri: str,
    recipient_username: str,  # Needed to look up private key for decryption
) -> dict:
    """Retrieve and decrypt a secret from a Dead Drop URI.

    Args:
        blossom_uri: The 'blossom://...' URI.
        recipient_username: The username of the recipient (to access private keys).

    Returns:
        The decrypted secret content and metadata.
    """
    from ming_drlms.core.e2ee_store import LocalKeyStore

    logger.info("Retrieving secret from %s for %s", blossom_uri, recipient_username)

    content_json = BlossomMock.retrieve(blossom_uri)
    if content_json is None:
        raise ValueError("Secret not found or expired")

    try:
        envelope = json.loads(content_json)
    except json.JSONDecodeError:
        raise ValueError("Invalid secret format")

    # Verify recipient matches (Mock Decryption Step)
    # in real E2EE, we would try to decrypt with private key.
    # Here we just check if we CAN load the identity (proof of ownership)

    keystore = LocalKeyStore()
    if keystore.load_state(recipient_username) is None:
        raise ValueError(f"Identity '{recipient_username}' not found locally")

    # TODO (Phase 28.1): Decrypt envelope['payload'] using private key

    return {
        "success": True,
        "secret_content": envelope.get("payload"),
        "sender_info": "unknown (anonymous)",
        "encryption_status": envelope.get("encryption"),
    }


@mcp.tool()
def hello_world(name: str = "World") -> str:
    """A simple hello world tool for testing."""
    return f"Hello, {name}! Phase 28 Ultimate MCP is ready."
