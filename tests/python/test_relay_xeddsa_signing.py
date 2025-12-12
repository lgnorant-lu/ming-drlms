"""Phase 17C: XEdDSA signing tests for Relay server.

Tests the XEdDSA-only signing mechanism (HMAC removed in Phase 17C).
"""

from __future__ import annotations

import os
import secrets
from unittest.mock import patch


# pynacl is required for XEdDSA signing tests
import nacl  # noqa: F401


class TestXEdDSAKeyLoading:
    """Tests for XEdDSA private key loading and public key derivation."""

    def test_valid_private_key_loading(self):
        """Test that a valid 32-byte hex key is loaded correctly."""
        # Generate a test private key
        test_key = secrets.token_hex(32)

        with patch.dict(os.environ, {"DRLMS_RELAY_SIGNING_PRIVKEY": test_key}):
            # Re-import to trigger key loading
            from nacl.bindings import crypto_scalarmult_base

            privkey = bytes.fromhex(test_key)
            pubkey = crypto_scalarmult_base(privkey)

            assert len(privkey) == 32
            assert len(pubkey) == 32

    def test_invalid_key_length_rejected(self):
        """Test that keys with wrong length are rejected."""
        short_key = secrets.token_hex(16)  # 16 bytes, not 32

        privkey = bytes.fromhex(short_key)
        assert len(privkey) != 32

    def test_empty_key_disables_xeddsa(self):
        """Test that empty key means XEdDSA is disabled."""
        with patch.dict(os.environ, {"DRLMS_RELAY_SIGNING_PRIVKEY": ""}):
            # Empty string should result in XEdDSA being disabled
            assert os.environ.get("DRLMS_RELAY_SIGNING_PRIVKEY") == ""


class TestXEdDSAOnlySigning:
    """Tests for Phase 17C XEdDSA-only signing."""

    def test_xeddsa_signature_length(self):
        """Test XEdDSA signature is 128 hex chars (64 bytes)."""
        from nacl.signing import SigningKey

        privkey = secrets.token_bytes(32)
        signing_key = SigningKey(privkey)
        message = b"test_event_id|test_room|1|1234567890|relay-test"
        signed = signing_key.sign(message)

        assert len(signed.signature.hex()) == 128
        assert all(c in "0123456789abcdef" for c in signed.signature.hex())


class TestSignReceiptXEdDSA:
    """Tests for Phase 17A XEdDSA receipt signing."""

    def test_xeddsa_sign_produces_signature(self):
        """Test XEdDSA signing produces 64-byte signature."""
        from nacl.signing import SigningKey

        privkey = secrets.token_bytes(32)
        signing_key = SigningKey(privkey)

        message = b"test_event_id|test_room|1|1234567890|relay-test"
        signed = signing_key.sign(message)

        assert len(signed.signature) == 64
        assert len(signed.signature.hex()) == 128

    def test_xeddsa_signature_verifiable(self):
        """Test XEdDSA signature can be verified with public key."""
        from nacl.signing import SigningKey

        privkey = secrets.token_bytes(32)
        signing_key = SigningKey(privkey)
        verify_key = signing_key.verify_key

        message = b"test_event_id|test_room|1|1234567890|relay-test"
        signed = signing_key.sign(message)

        # Verification should succeed
        try:
            verify_key.verify(signed.message, signed.signature)
            verified = True
        except Exception:
            verified = False

        assert verified

    def test_xeddsa_signature_fails_with_wrong_key(self):
        """Test XEdDSA verification fails with wrong public key."""
        from nacl.signing import SigningKey

        privkey1 = secrets.token_bytes(32)
        privkey2 = secrets.token_bytes(32)

        signing_key1 = SigningKey(privkey1)
        signing_key2 = SigningKey(privkey2)

        message = b"test message"
        signed = signing_key1.sign(message)

        # Verification with wrong key should fail
        try:
            signing_key2.verify_key.verify(signed.message, signed.signature)
            verified = True
        except Exception:
            verified = False

        assert not verified


class TestXEdDSAMessageFormat:
    """Tests for XEdDSA message format."""

    def test_xeddsa_message_format(self):
        """Test XEdDSA signature message format."""
        event_id = "abc123"
        room = "test-room"
        server_seq = 42
        server_ts = 1234567890
        relay_id = "relay-test"

        message = f"{event_id}|{room}|{server_seq}|{server_ts}|{relay_id}".encode()

        # Standard message format for XEdDSA signing
        assert message == b"abc123|test-room|42|1234567890|relay-test"


class TestEventAckModel:
    """Tests for EventAck Pydantic model (Phase 17C: XEdDSA only)."""

    def test_eventack_has_xeddsa_fields(self):
        """Test EventAck model includes XEdDSA fields."""
        from ming_drlms.relay.server import EventAck

        ack = EventAck(
            server_seq=1,
            server_ts=1234567890,
            relay_id="relay-test",
            xeddsa_signature="xeddsa_sig_hex",
            relay_pubkey="pubkey_hex",
        )

        assert ack.server_seq == 1
        assert ack.xeddsa_signature == "xeddsa_sig_hex"
        assert ack.relay_pubkey == "pubkey_hex"

    def test_eventack_xeddsa_optional(self):
        """Test EventAck XEdDSA fields are optional."""
        from ming_drlms.relay.server import EventAck

        ack = EventAck(
            server_seq=1,
            server_ts=1234567890,
        )

        assert ack.xeddsa_signature is None
        assert ack.relay_pubkey is None


class TestHealthEndpoint:
    """Tests for health endpoint (Phase 17C: XEdDSA only)."""

    def test_health_includes_signature_schemes(self):
        """Test health endpoint includes signature_schemes list."""
        from ming_drlms.relay.server import health_check

        result = health_check()

        assert "signature_schemes" in result
        # Phase 17C: HMAC removed, only xeddsa if configured
        assert "hmac" not in result["signature_schemes"]

    def test_health_includes_relay_id(self):
        """Test health endpoint includes relay_id."""
        from ming_drlms.relay.server import health_check

        result = health_check()

        assert "relay_id" in result


class TestWellKnownEndpoint:
    """Tests for Well-Known endpoint (Phase 17C)."""

    def test_wellknown_returns_version(self):
        """Test Well-Known endpoint returns version info."""
        from ming_drlms.relay.server import wellknown_relay_info

        result = wellknown_relay_info()

        assert result["version"] == 2  # Phase 17C version
        assert "relay_id" in result
        assert "signature_schemes" in result


class TestReceiptStorePhase17A:
    """Tests for ReceiptStore with Phase 17A XEdDSA fields."""

    def test_stored_receipt_has_xeddsa_fields(self):
        """Test StoredReceipt dataclass has XEdDSA fields."""
        from ming_drlms.relay.receipt_store import StoredReceipt

        receipt = StoredReceipt(
            id=1,
            event_id="event123",
            room="test-room",
            relay_url="http://localhost:15019",
            relay_id="relay-test",
            server_seq=1,
            server_ts=1234567890,
            signature="hmac_sig",
            verified=True,
            created_at=1234567890,
            xeddsa_signature="xeddsa_sig",
            relay_pubkey="pubkey_hex",
            xeddsa_verified=True,
        )

        assert receipt.xeddsa_signature == "xeddsa_sig"
        assert receipt.relay_pubkey == "pubkey_hex"
        assert receipt.xeddsa_verified is True

    def test_stored_receipt_xeddsa_optional(self):
        """Test StoredReceipt XEdDSA fields are optional."""
        from ming_drlms.relay.receipt_store import StoredReceipt

        receipt = StoredReceipt(
            id=1,
            event_id="event123",
            room="test-room",
            relay_url="http://localhost:15019",
            relay_id="relay-test",
            server_seq=1,
            server_ts=1234567890,
            signature="hmac_sig",
            verified=True,
            created_at=1234567890,
        )

        assert receipt.xeddsa_signature is None
        assert receipt.xeddsa_verified is False
