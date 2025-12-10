"""Phase 17B: XEdDSA verification tests for Relay client.

Tests the client-side XEdDSA signature verification in RelayManager.
"""

from __future__ import annotations


import nacl.signing


class TestVerifyXEdDSA:
    """Tests for _verify_xeddsa method in RelayManager."""

    def test_valid_signature_verifies(self):
        """Test that a valid XEdDSA signature verifies successfully."""
        from ming_drlms.relay.manager import RelayManager

        # Generate key pair
        signing_key = nacl.signing.SigningKey.generate()
        verify_key = signing_key.verify_key

        # Create message and sign
        message = b"event123|room1|42|1733800000|relay-test"
        signed = signing_key.sign(message)

        # Create manager and verify
        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=message,
            signature_hex=signed.signature.hex(),
            pubkey_hex=verify_key.encode().hex(),
            relay_id="test-relay",
        )

        assert result is True

    def test_invalid_signature_fails(self):
        """Test that an invalid signature fails verification."""
        from ming_drlms.relay.manager import RelayManager

        # Generate two different key pairs
        signing_key1 = nacl.signing.SigningKey.generate()
        signing_key2 = nacl.signing.SigningKey.generate()

        # Sign with key1, verify with key2's pubkey
        message = b"event123|room1|42|1733800000|relay-test"
        signed = signing_key1.sign(message)

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=message,
            signature_hex=signed.signature.hex(),
            pubkey_hex=signing_key2.verify_key.encode().hex(),
            relay_id="test-relay",
        )

        assert result is False

    def test_tampered_message_fails(self):
        """Test that a tampered message fails verification."""
        from ming_drlms.relay.manager import RelayManager

        signing_key = nacl.signing.SigningKey.generate()
        verify_key = signing_key.verify_key

        # Sign original message
        original = b"event123|room1|42|1733800000|relay-test"
        signed = signing_key.sign(original)

        # Verify with tampered message
        tampered = b"event999|room1|42|1733800000|relay-test"

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=tampered,
            signature_hex=signed.signature.hex(),
            pubkey_hex=verify_key.encode().hex(),
            relay_id="test-relay",
        )

        assert result is False

    def test_invalid_signature_length_fails(self):
        """Test that invalid signature length is rejected."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=b"test",
            signature_hex="abcd",  # Too short
            pubkey_hex="00" * 32,
            relay_id="test-relay",
        )

        assert result is False

    def test_invalid_pubkey_length_fails(self):
        """Test that invalid pubkey length is rejected."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=b"test",
            signature_hex="00" * 64,
            pubkey_hex="abcd",  # Too short
            relay_id="test-relay",
        )

        assert result is False

    def test_invalid_hex_signature_fails(self):
        """Test that invalid hex in signature is handled."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=b"test",
            signature_hex="ZZZZ" + "00" * 62,  # Invalid hex
            pubkey_hex="00" * 32,
            relay_id="test-relay",
        )

        assert result is False

    def test_invalid_hex_pubkey_fails(self):
        """Test that invalid hex in pubkey is handled."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=b"test",
            signature_hex="00" * 64,
            pubkey_hex="GGGG" + "00" * 28,  # Invalid hex
            relay_id="test-relay",
        )

        assert result is False

    def test_empty_message_signature(self):
        """Test signing and verifying empty message."""
        from ming_drlms.relay.manager import RelayManager

        signing_key = nacl.signing.SigningKey.generate()
        message = b""
        signed = signing_key.sign(message)

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=message,
            signature_hex=signed.signature.hex(),
            pubkey_hex=signing_key.verify_key.encode().hex(),
            relay_id="test-relay",
        )

        assert result is True

    def test_corrupted_signature_single_bit_fails(self):
        """Test that a single bit flip in signature fails."""
        from ming_drlms.relay.manager import RelayManager

        signing_key = nacl.signing.SigningKey.generate()
        message = b"test message"
        signed = signing_key.sign(message)

        # Corrupt single byte
        sig_bytes = bytearray(signed.signature)
        sig_bytes[0] ^= 0x01  # Flip one bit
        corrupted_sig = bytes(sig_bytes).hex()

        manager = RelayManager.__new__(RelayManager)
        result = manager._verify_xeddsa(
            message=message,
            signature_hex=corrupted_sig,
            pubkey_hex=signing_key.verify_key.encode().hex(),
            relay_id="test-relay",
        )

        assert result is False


class TestVerifyReceipt:
    """Tests for _verify_receipt method (Phase 17C: XEdDSA only)."""

    def test_xeddsa_verification_success(self):
        """Test successful XEdDSA verification."""
        from ming_drlms.relay.manager import RelayManager

        # Generate signature
        signing_key = nacl.signing.SigningKey.generate()
        message = b"event123|room1|42|1733800000|relay-test"
        signed = signing_key.sign(message)

        manager = RelayManager.__new__(RelayManager)
        verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            xeddsa_signature=signed.signature.hex(),
            relay_pubkey=signing_key.verify_key.encode().hex(),
        )

        assert verified is True

    def test_no_xeddsa_signature_fails(self):
        """Test that missing XEdDSA signature fails verification."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            xeddsa_signature=None,
            relay_pubkey=None,
        )

        # Phase 17C: No signature = not verified
        assert verified is False

    def test_xeddsa_with_pubkey_but_no_signature(self):
        """Test pubkey present but no signature."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            xeddsa_signature=None,
            relay_pubkey="00" * 32,  # Pubkey present
        )

        # XEdDSA not attempted (no signature)
        assert verified is False

    def test_xeddsa_with_signature_but_no_pubkey(self):
        """Test signature present but no pubkey."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            xeddsa_signature="00" * 64,  # Signature present
            relay_pubkey=None,
        )

        # XEdDSA not attempted (no pubkey)
        assert verified is False

    def test_invalid_xeddsa_fails(self):
        """Test that invalid XEdDSA signature fails."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            xeddsa_signature="invalid_sig",  # Invalid
            relay_pubkey="00" * 32,
        )

        assert verified is False


class TestStorageReceiptDataclass:
    """Tests for StorageReceipt with Phase 17A fields."""

    def test_storage_receipt_has_xeddsa_fields(self):
        """Test StorageReceipt includes XEdDSA fields."""
        from ming_drlms.relay.manager import StorageReceipt

        receipt = StorageReceipt(
            relay_url="http://localhost:8081",
            relay_id="relay-test",
            server_seq=1,
            server_ts=1733800000,
            signature="hmac_sig",
            verified=True,
            xeddsa_signature="xeddsa_sig",
            relay_pubkey="pubkey_hex",
            xeddsa_verified=True,
        )

        assert receipt.xeddsa_signature == "xeddsa_sig"
        assert receipt.relay_pubkey == "pubkey_hex"
        assert receipt.xeddsa_verified is True

    def test_storage_receipt_xeddsa_defaults(self):
        """Test StorageReceipt XEdDSA fields default to None/False."""
        from ming_drlms.relay.manager import StorageReceipt

        receipt = StorageReceipt(
            relay_url="http://localhost:8081",
            relay_id="relay-test",
            server_seq=1,
            server_ts=1733800000,
            signature="hmac_sig",
        )

        assert receipt.xeddsa_signature is None
        assert receipt.relay_pubkey is None
        assert receipt.xeddsa_verified is False
