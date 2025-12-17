"""Phase 28.1: Blossom Network Client.

This module provides a client for interacting with Blossom Servers (NIP-200ish/Media Servers).
It supports uploading blobs and downloading them via SHA256 validation.

Standard implementation uses HTTPX for async/sync requests.
"""

from __future__ import annotations

import logging
import hashlib
import os
import httpx
from typing import Optional, Dict

logger = logging.getLogger("ming_drlms.core.blossom")

# Default public Blossom servers (Fallback)
DEFAULT_SERVERS = [
    "https://nostr.build",
    "https://cdn.nostr.build",
]


class BlossomClient:
    """Client for interacting with Blossom servers."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        identity_manager: Optional[object] = None,
    ):
        """Initialize the client.

        Args:
            server_url: Explicit server URL. If None, uses env var or default.
            identity_manager: IdentityManager instance for signing auth events.
        """
        self.server_url = server_url or os.environ.get("MING_DRLMS_BLOSSOM_SERVER")
        if not self.server_url:
            self.server_url = DEFAULT_SERVERS[0]

        self.server_url = self.server_url.rstrip("/")
        self.timeout = 30.0
        self.identity_manager = identity_manager

    def _create_auth_header(self, blob_sha256: str) -> Optional[str]:
        """Create Blossom Authorization header (Nostr kind:24242)."""
        logger.debug(f"DEBUG: Entering _create_auth_header with hash {blob_sha256}")

        if not self.identity_manager:
            logger.debug("DEBUG: No identity manager, skipping auth")
            return None

        import time
        import base64
        import json

        # 1. Prepare event fields
        pubkey = self.identity_manager.get_pubkey_hex()
        created_at = int(time.time())
        expiration = str(created_at + 3600)  # 1 hour expiry

        tags = [["t", "upload"], ["x", blob_sha256], ["expiration", expiration]]
        content = "Upload Blob"
        kind = 24242

        # 2. Serialize for ID (NIP-01)
        # [0, <pubkey>, <created_at>, <kind>, <tags>, <content>]
        event_data = [0, pubkey, created_at, kind, tags, content]
        serialized = json.dumps(
            event_data, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        # 3. Sign
        try:
            event_id = hashlib.sha256(serialized).hexdigest()
            logger.debug(f"DEBUG: Event ID: {event_id}")

            privkey_hex = None

            # PHASE 28 FIX: Check for explicit Nostr private key first
            # (IdentityManager currently only stores X25519 E2EE keys)
            if hasattr(self.identity_manager, "nostr_private_key_hex"):
                privkey_hex = self.identity_manager.nostr_private_key_hex
                logger.debug(
                    f"DEBUG: Using injected nostr_private_key_hex (len={len(privkey_hex)})"
                )
            elif hasattr(self.identity_manager, "keystore"):
                # Legacy/Fallback (Incorrect for Nostr, but kept for structure)
                privkey_hex = self.identity_manager.keystore.load_key(
                    self.identity_manager.username
                )
                logger.debug("DEBUG: Using load_key from keystore")
            else:
                # Try accessing private _keystore if available
                ks = getattr(self.identity_manager, "_keystore", None)
                if ks:
                    # This is likely the X25519 key, not Nostr, but we try
                    privkey_hex = ks.load_key(self.identity_manager.username)
                    logger.debug("DEBUG: Using _keystore fallback")
                else:
                    logger.warning("No keystore found for auth")
                    return None

            if not privkey_hex:
                logger.warning("No private key found for auth")
                return None

            try:
                import secp256k1
            except ImportError as ie:
                logger.error(
                    f"Failed to import secp256k1: {ie}. Cannot sign auth event."
                )
                return None

            logger.debug("DEBUG: Signing with secp256k1...")
            privkey = secp256k1.PrivateKey(bytes.fromhex(privkey_hex))
            sig = privkey.schnorr_sign(
                bytes.fromhex(event_id), bip340tag=None, raw=True
            ).hex()
            logger.debug(f"DEBUG: Signature generated: {sig[:8]}...")

            # 4. Construct Full Event
            event = {
                "id": event_id,
                "pubkey": pubkey,
                "created_at": created_at,
                "kind": kind,
                "tags": tags,
                "content": content,
                "sig": sig,
            }

            # 5. Base64 Encode
            event_json = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
            b64_event = base64.b64encode(event_json.encode("utf-8")).decode("ascii")
            return f"Nostr {b64_event}"

        except Exception as e:
            logger.error(f"Failed to sign auth event: {e}", exc_info=True)
            return None

    def upload_blob(
        self, data: bytes, content_type: str = "application/octet-stream"
    ) -> Dict[str, str]:
        """Upload raw bytes to the Blossom server (PUT /upload).

        Args:
            data: The binary data to upload.
            content_type: MIME type.

        Returns:
            Dict containing 'url' and 'sha256'.
        """
        sha256_local = hashlib.sha256(data).hexdigest()
        url = f"{self.server_url}/upload"

        headers = {
            "Content-Type": content_type,
        }

        # Add Authorization if possible
        auth_header = self._create_auth_header(sha256_local)
        if auth_header:
            headers["Authorization"] = auth_header
            logger.info("Using Authenticated Upload (kind:24242)")
        else:
            logger.warning(
                "Attempting Unauthenticated Upload (likely to fail on nostr.build)"
            )

        try:
            # Blossom Spec: PUT /upload with raw body
            response = httpx.put(
                url, content=data, headers=headers, timeout=self.timeout
            )

            if response.status_code == 200:
                try:
                    resp_json = response.json()
                    # Handle Descriptor response
                    # { "url": "...", "sha256": "..." }
                    return {
                        "url": resp_json.get("url"),
                        "sha256": resp_json.get("sha256", sha256_local),
                    }
                except Exception:
                    # If not json, maybe fallback? But Blossom spec says JSON.
                    # nostr.build explicitly returns JSON on success.
                    logger.warning(f"Non-JSON response: {response.text[:200]}")
                    raise Exception("Invalid response from server (Not JSON)")

            raise Exception(
                f"Upload failed: HTTP {response.status_code} - {response.text[:200]}"
            )

        except Exception as e:
            logger.error("Upload failed: %s", e)
            raise

    def download_blob(self, sha256_or_url: str) -> bytes:
        """Download bytes from the server.

        Args:
            sha256_or_url: SHA256 hash or Full URL.

        Returns:
            Raw bytes.
        """
        if sha256_or_url.startswith("http"):
            url = sha256_or_url
        else:
            url = f"{self.server_url}/{sha256_or_url}"

        try:
            response = httpx.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error("Download failed (%s): %s", url, e)
            raise
