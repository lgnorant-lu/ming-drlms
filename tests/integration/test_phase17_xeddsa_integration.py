"""Phase 17: XEdDSA Integration Tests.

Tests the full dual signing flow with a real Relay server.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from typing import Generator

import pytest


@pytest.fixture(scope="module")
def relay_server_with_xeddsa() -> Generator[tuple[str, str], None, None]:
    """Start a Relay server with XEdDSA signing enabled.

    Yields:
        (base_url, pubkey_hex)
    """
    # Generate test keys
    privkey = secrets.token_hex(32)

    # Set environment
    import tempfile

    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()

    env = os.environ.copy()
    env["DRLMS_RELAY_SIGNING_PRIVKEY"] = privkey
    env["DRLMS_RELAY_SIGNING_KEY"] = secrets.token_hex(32)
    env["DRLMS_RELAY_ID"] = "test-relay-xeddsa"
    env["DRLMS_DB_PATH"] = db_path

    # Start server
    port = 18091
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "ming_drlms.relay.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for server to start
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                import urllib.request

                with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("status") == "ok":
                        pubkey = data.get("pubkey", "")
                        yield base_url, pubkey
                        return
            except Exception:
                time.sleep(0.2)

        pytest.skip("Relay server failed to start")

    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=5)
        # Cleanup temp db
        try:
            os.unlink(db_path)
        except Exception:
            pass


class TestHealthEndpointIntegration:
    """Integration tests for /health endpoint (Phase 17C)."""

    def test_health_returns_xeddsa_scheme(self, relay_server_with_xeddsa):
        """Test /health includes xeddsa in signature_schemes."""
        import urllib.request

        base_url, _ = relay_server_with_xeddsa
        with urllib.request.urlopen(f"{base_url}/health") as resp:
            data = json.loads(resp.read().decode())

        assert "xeddsa" in data.get("signature_schemes", [])
        # Phase 17C: HMAC removed
        assert "hmac" not in data.get("signature_schemes", [])

    def test_health_returns_pubkey(self, relay_server_with_xeddsa):
        """Test /health includes pubkey."""
        import urllib.request

        base_url, pubkey = relay_server_with_xeddsa
        with urllib.request.urlopen(f"{base_url}/health") as resp:
            data = json.loads(resp.read().decode())

        assert data.get("pubkey") == pubkey
        assert len(pubkey) == 64  # 32 bytes hex
        assert data.get("pubkey_type") == "ed25519"


class TestWellKnownEndpointIntegration:
    """Integration tests for /.well-known/drlms-relay.json endpoint."""

    def test_wellknown_returns_pubkey(self, relay_server_with_xeddsa):
        """Test Well-Known endpoint returns pubkey."""
        import urllib.request

        base_url, expected_pubkey = relay_server_with_xeddsa
        with urllib.request.urlopen(f"{base_url}/.well-known/drlms-relay.json") as resp:
            data = json.loads(resp.read().decode())

        assert data.get("pubkey") == expected_pubkey


class TestEventPostXEdDSAIntegration:
    """Integration tests for POST /events with XEdDSA signing (Phase 17C)."""

    def test_post_event_returns_xeddsa_signature(self, relay_server_with_xeddsa):
        """Test posting event returns XEdDSA signature (no HMAC in 17C)."""
        import urllib.request

        base_url, pubkey = relay_server_with_xeddsa

        body = json.dumps(
            {
                "room": "test-room",
                "ciphertext": "dGVzdCBtZXNzYWdl",
                "client_event_hash": "test123",
            }
        ).encode()

        req = urllib.request.Request(
            f"{base_url}/events",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        # Phase 17C: No HMAC signature
        assert "relay_signature" not in data

        # Check XEdDSA signature
        assert "xeddsa_signature" in data
        assert len(data["xeddsa_signature"]) == 128  # Ed25519 signature hex

        assert data.get("relay_pubkey") == pubkey

    def test_xeddsa_signature_is_verifiable(self, relay_server_with_xeddsa):
        """Test that returned XEdDSA signature can be verified."""
        import urllib.request
        import nacl.signing

        base_url, pubkey_hex = relay_server_with_xeddsa

        body = json.dumps(
            {
                "room": "verify-room",
                "ciphertext": "dGVzdA==",
                "client_event_hash": "verify123",
            }
        ).encode()

        req = urllib.request.Request(
            f"{base_url}/events",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        # Reconstruct message
        message = (
            f"verify123|verify-room|{data['server_seq']}|"
            f"{data['server_ts']}|{data['relay_id']}"
        ).encode()

        # Verify signature
        signature = bytes.fromhex(data["xeddsa_signature"])
        pubkey = bytes.fromhex(pubkey_hex)

        verify_key = nacl.signing.VerifyKey(pubkey)
        # Should not raise
        verify_key.verify(message, signature)
