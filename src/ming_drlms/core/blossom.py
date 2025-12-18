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

# Default public Blossom servers (Ordered by stability)
DEFAULT_SERVERS = [
    "https://nostr.download",  # Most stable for API access
    "https://cdn.nostr.build",
    "https://nostr.build",  # Sometimes returns HTML
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
        """Create Blossom Authorization header (Nostr kind:24242).

        Phase 28.2: Clean implementation using NostrSigner abstraction.
        """
        if not self.identity_manager:
            logger.debug("No identity manager, skipping auth")
            return None

        import time
        import base64
        import json

        try:
            # Get NostrSigner from IdentityManager (Phase 28.2)
            signer = self.identity_manager.get_nostr_signer()
        except ValueError as e:
            logger.warning(f"Cannot get Nostr signer: {e}")
            return None
        except ImportError:
            logger.warning("secp256k1 library not available, skipping auth")
            return None

        # Prepare Nostr event (kind 24242 - Blossom Upload Auth)
        created_at = int(time.time())
        event = {
            "pubkey": signer.get_pubkey_hex(),
            "created_at": created_at,
            "kind": 24242,
            "tags": [
                ["t", "upload"],
                ["x", blob_sha256],
                ["expiration", str(created_at + 3600)],  # 1 hour
            ],
            "content": "Upload Blob",
        }

        try:
            # Sign event using NostrSigner
            signature = signer.sign_event(event)
            event_id = signer._compute_event_id(event)

            # Construct full event with ID and signature
            full_event = event.copy()
            full_event["id"] = event_id
            full_event["sig"] = signature

            # Base64 encode for Authorization header
            event_json = json.dumps(
                full_event, separators=(",", ":"), ensure_ascii=False
            )
            b64_event = base64.b64encode(event_json.encode("utf-8")).decode("ascii")

            logger.info("Generated Blossom auth header (kind:24242)")
            return f"Nostr {b64_event}"

        except Exception as e:
            logger.error(f"Failed to sign Blossom auth event: {e}", exc_info=True)
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
                except Exception as e:
                    # Diagnostic: Log the actual response for debugging
                    logger.error(f"JSON Parse Error: {type(e).__name__}: {e}")
                    logger.error(f"Response Status: {response.status_code}")
                    logger.error(f"Response Headers: {dict(response.headers)}")
                    logger.error(
                        f"Response Content-Type: {response.headers.get('content-type')}"
                    )
                    logger.error(
                        f"Response Body (first 500 chars): {response.text[:500]}"
                    )

                    # Try to return raw text as fallback
                    # Some servers might return plain text URL
                    if response.text and response.text.strip():
                        logger.warning(
                            "Attempting to parse non-JSON response as plain text"
                        )
                        # Check if it looks like a URL
                        text = response.text.strip()
                        if text.startswith("http") or text.startswith("blossom://"):
                            logger.info(f"Detected plain text URL response: {text}")
                            return {
                                "url": text,
                                "sha256": sha256_local,
                            }

                    raise Exception(
                        f"Invalid response from server (Not JSON): {response.text[:200]}"
                    )

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
        # Construct proper URL
        if sha256_or_url.startswith("http"):
            url = sha256_or_url
        elif sha256_or_url.startswith("blossom://"):
            # Extract SHA256 from blossom:// URI
            sha256 = sha256_or_url.replace("blossom://", "")
            # Try CDN endpoint first (more reliable for raw content)
            url = f"{self.server_url}/{sha256}"
        else:
            # Direct SHA256
            url = f"{self.server_url}/{sha256_or_url}"

        logger.debug(f"Downloading blob from: {url}")

        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()

            # Check if response is HTML (error page)
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type:
                logger.error("Server returned HTML instead of blob content")
                logger.error(f"URL: {url}")
                logger.error(f"Response snippet: {response.text[:300]}")

                # Try alternative URL format with .bin extension
                alt_url = f"{url}.bin"
                logger.warning(f"Trying alternative URL: {alt_url}")
                alt_response = httpx.get(
                    alt_url, timeout=self.timeout, follow_redirects=True
                )
                if (
                    alt_response.status_code == 200
                    and "text/html" not in alt_response.headers.get("content-type", "")
                ):
                    return alt_response.content

                raise Exception(
                    f"Server returned HTML instead of blob. "
                    f"URL might be incorrect or blob doesn't exist. "
                    f"URL: {url}"
                )

            return response.content
        except Exception as e:
            logger.error("Download failed (%s): %s", url, e)
            raise
