"""Tests for event_hash module - Nostr-style Hash ID and signatures."""

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ming_drlms.core.event_hash import (
    EventHashError,
    EventSignature,
    compute_event_id,
    create_signed_event,
    sign_event,
    verify_event,
    verify_event_signature,
)


class TestComputeEventId:
    """Tests for compute_event_id function."""

    def test_basic_computation(self):
        """Event ID should be deterministic sha256 hash."""
        pubkey = b"\x01" * 32
        content = b"hello world"
        ts = 1733644800000  # 2024-12-08 in ms

        event_id = compute_event_id(pubkey, content, ts)

        assert len(event_id) == 64  # hex sha256
        assert all(c in "0123456789abcdef" for c in event_id)

    def test_deterministic(self):
        """Same inputs should produce same event ID."""
        pubkey = b"\x02" * 32
        content = b"test content"
        ts = 1733644800000

        id1 = compute_event_id(pubkey, content, ts)
        id2 = compute_event_id(pubkey, content, ts)

        assert id1 == id2

    def test_different_pubkey_different_id(self):
        """Different pubkey should produce different event ID."""
        content = b"same content"
        ts = 1733644800000

        id1 = compute_event_id(b"\x01" * 32, content, ts)
        id2 = compute_event_id(b"\x02" * 32, content, ts)

        assert id1 != id2

    def test_different_content_different_id(self):
        """Different content should produce different event ID."""
        pubkey = b"\x01" * 32
        ts = 1733644800000

        id1 = compute_event_id(pubkey, b"content A", ts)
        id2 = compute_event_id(pubkey, b"content B", ts)

        assert id1 != id2

    def test_different_timestamp_different_id(self):
        """Different timestamp should produce different event ID."""
        pubkey = b"\x01" * 32
        content = b"same content"

        id1 = compute_event_id(pubkey, content, 1733644800000)
        id2 = compute_event_id(pubkey, content, 1733644800001)

        assert id1 != id2

    def test_invalid_pubkey_length(self):
        """Should raise error for invalid pubkey length."""
        with pytest.raises(EventHashError, match="32 bytes"):
            compute_event_id(b"\x01" * 31, b"content", 1000)

        with pytest.raises(EventHashError, match="32 bytes"):
            compute_event_id(b"\x01" * 33, b"content", 1000)

    def test_empty_content(self):
        """Should handle empty content."""
        pubkey = b"\x01" * 32
        event_id = compute_event_id(pubkey, b"", 1000)
        assert len(event_id) == 64


class TestSignEvent:
    """Tests for sign_event function."""

    def test_sign_produces_64_byte_signature(self):
        """Sign should produce 64-byte Ed25519 signature."""
        private_key = Ed25519PrivateKey.generate()
        event_id = "a" * 64  # Valid hex event ID

        signature = sign_event(event_id, private_key)

        assert len(signature) == 64

    def test_sign_different_keys_different_signatures(self):
        """Different keys should produce different signatures."""
        key1 = Ed25519PrivateKey.generate()
        key2 = Ed25519PrivateKey.generate()
        event_id = "b" * 64

        sig1 = sign_event(event_id, key1)
        sig2 = sign_event(event_id, key2)

        assert sig1 != sig2


class TestVerifyEventSignature:
    """Tests for verify_event_signature function."""

    def test_valid_signature(self):
        """Should verify valid signature."""
        private_key = Ed25519PrivateKey.generate()
        pubkey = private_key.public_key().public_bytes_raw()
        event_id = "c" * 64

        signature = sign_event(event_id, private_key)
        result = verify_event_signature(event_id, signature, pubkey)

        assert result is True

    def test_invalid_signature(self):
        """Should reject invalid signature."""
        private_key = Ed25519PrivateKey.generate()
        pubkey = private_key.public_key().public_bytes_raw()
        event_id = "d" * 64

        # Create valid signature then tamper
        signature = sign_event(event_id, private_key)
        bad_signature = bytes([b ^ 0xFF for b in signature[:8]]) + signature[8:]

        result = verify_event_signature(event_id, bad_signature, pubkey)

        assert result is False

    def test_wrong_pubkey(self):
        """Should reject signature with wrong pubkey."""
        key1 = Ed25519PrivateKey.generate()
        key2 = Ed25519PrivateKey.generate()
        event_id = "e" * 64

        signature = sign_event(event_id, key1)
        wrong_pubkey = key2.public_key().public_bytes_raw()

        result = verify_event_signature(event_id, signature, wrong_pubkey)

        assert result is False

    def test_invalid_signature_length(self):
        """Should reject signature with wrong length."""
        pubkey = b"\x01" * 32
        event_id = "f" * 64

        assert verify_event_signature(event_id, b"\x00" * 63, pubkey) is False
        assert verify_event_signature(event_id, b"\x00" * 65, pubkey) is False

    def test_invalid_pubkey_length(self):
        """Should reject pubkey with wrong length."""
        event_id = "0" * 64
        signature = b"\x00" * 64

        assert verify_event_signature(event_id, signature, b"\x01" * 31) is False
        assert verify_event_signature(event_id, signature, b"\x01" * 33) is False


class TestCreateSignedEvent:
    """Tests for create_signed_event function."""

    def test_creates_complete_event_signature(self):
        """Should create EventSignature with all fields."""
        private_key = Ed25519PrivateKey.generate()
        content = b"test message"

        result = create_signed_event(content, private_key, timestamp_ms=1000)

        assert isinstance(result, EventSignature)
        assert len(result.event_id) == 64
        assert len(result.signature) == 64
        assert len(result.sender_pubkey) == 32
        assert result.timestamp_ms == 1000

    def test_auto_timestamp(self):
        """Should auto-generate timestamp if not provided."""
        private_key = Ed25519PrivateKey.generate()
        content = b"test"

        result = create_signed_event(content, private_key)

        assert result.timestamp_ms > 0

    def test_signature_is_verifiable(self):
        """Created signature should be verifiable."""
        private_key = Ed25519PrivateKey.generate()
        content = b"test content"

        result = create_signed_event(content, private_key, timestamp_ms=2000)

        # Verify using verify_event_signature
        is_valid = verify_event_signature(
            result.event_id,
            result.signature,
            result.sender_pubkey,
        )
        assert is_valid is True


class TestVerifyEvent:
    """Tests for verify_event function (full verification)."""

    def test_valid_event(self):
        """Should verify complete valid event."""
        private_key = Ed25519PrivateKey.generate()
        content = b"message content"
        ts = 3000

        signed = create_signed_event(content, private_key, timestamp_ms=ts)

        result = verify_event(
            content=content,
            event_id=signed.event_id,
            signature=signed.signature,
            sender_pubkey=signed.sender_pubkey,
            timestamp_ms=ts,
        )

        assert result is True

    def test_tampered_content(self):
        """Should detect tampered content."""
        private_key = Ed25519PrivateKey.generate()
        content = b"original"
        ts = 4000

        signed = create_signed_event(content, private_key, timestamp_ms=ts)

        # Verify with different content
        result = verify_event(
            content=b"tampered",
            event_id=signed.event_id,
            signature=signed.signature,
            sender_pubkey=signed.sender_pubkey,
            timestamp_ms=ts,
        )

        assert result is False

    def test_tampered_timestamp(self):
        """Should detect tampered timestamp."""
        private_key = Ed25519PrivateKey.generate()
        content = b"message"
        ts = 5000

        signed = create_signed_event(content, private_key, timestamp_ms=ts)

        # Verify with different timestamp
        result = verify_event(
            content=content,
            event_id=signed.event_id,
            signature=signed.signature,
            sender_pubkey=signed.sender_pubkey,
            timestamp_ms=ts + 1,  # Different timestamp
        )

        assert result is False

    def test_wrong_event_id(self):
        """Should detect wrong event ID."""
        private_key = Ed25519PrivateKey.generate()
        content = b"test"
        ts = 6000

        signed = create_signed_event(content, private_key, timestamp_ms=ts)

        # Use a fake event ID
        result = verify_event(
            content=content,
            event_id="0" * 64,  # Wrong ID
            signature=signed.signature,
            sender_pubkey=signed.sender_pubkey,
            timestamp_ms=ts,
        )

        assert result is False
