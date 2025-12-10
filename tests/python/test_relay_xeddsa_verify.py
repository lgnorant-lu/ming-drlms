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


class TestVerifyReceipt:
    """Tests for _verify_receipt method with dual verification."""

    def test_xeddsa_only_verification(self):
        """Test verification with only XEdDSA (no HMAC key)."""
        from ming_drlms.relay.manager import RelayManager

        # Generate signature
        signing_key = nacl.signing.SigningKey.generate()
        message = b"event123|room1|42|1733800000|relay-test"
        signed = signing_key.sign(message)

        manager = RelayManager.__new__(RelayManager)
        hmac_verified, xeddsa_verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            signature="dummy_hmac_sig",
            xeddsa_signature=signed.signature.hex(),
            relay_pubkey=signing_key.verify_key.encode().hex(),
        )

        # HMAC should be trusted (no key), XEdDSA should verify
        assert hmac_verified is True
        assert xeddsa_verified is True

    def test_no_xeddsa_falls_back_to_hmac_trust(self):
        """Test that missing XEdDSA signature falls back to HMAC trust."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager.__new__(RelayManager)
        hmac_verified, xeddsa_verified = manager._verify_receipt(
            event_id="event123",
            room="room1",
            server_seq=42,
            server_ts=1733800000,
            relay_id="relay-test",
            signature="dummy_hmac_sig",
            xeddsa_signature=None,
            relay_pubkey=None,
        )

        # No HMAC key configured - should trust
        assert hmac_verified is True
        assert xeddsa_verified is False


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
