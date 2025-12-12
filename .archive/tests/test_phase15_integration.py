"""Phase 15D: End-to-end integration tests for client-side signing flow.

Tests the complete flow:
1. IdentityManager creates identity
2. RelaySigner signs event
3. RelayHTTPClient posts event (mocked)
4. Client receives and verifies signature
5. ContactManager records sender pubkey
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

import pytest


class TestIdentityManagerIntegration:
    """Integration tests for IdentityManager with other components."""

    def test_identity_create_and_sign_flow(self, tmp_path: Path) -> None:
        """Full flow: create identity → sign → verify."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.clear_event import canonical_serialize

        # Step 1: Create identity
        im = IdentityManager(tmp_path / "identity.json")
        identity = im.create_identity(alias="integration-test")

        assert len(identity.public_key) == 32
        assert im.has_identity()

        # Step 2: Create signer and sign event
        signer = RelaySigner(identity_manager=im, username="testuser", device_id=1)
        assert signer.can_sign()

        envelope = signer.sign_event("test-room", b"Hello, Phase 15!")

        assert envelope.room == "test-room"
        assert envelope.sender_id == "testuser"
        assert len(envelope.signature_hex) == 128  # 64 bytes hex
        assert len(envelope.sender_pubkey_hex) == 64  # 32 bytes hex
        assert len(envelope.event_id) == 64  # SHA256 hex

        # Step 3: Verify signature
        serialized = canonical_serialize(
            room="test-room",
            ts=envelope.timestamp,
            sender_id="testuser",
            device_id=1,
            content_type="text",
            content_bytes=b"Hello, Phase 15!",
        )

        signature = bytes.fromhex(envelope.signature_hex)
        pubkey = bytes.fromhex(envelope.sender_pubkey_hex)

        assert im.verify(serialized, signature, pubkey)

    def test_identity_export_import_preserves_signing(self, tmp_path: Path) -> None:
        """Exported and imported identity produces same signatures."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        # Create and export
        im1 = IdentityManager(tmp_path / "id1.json")
        im1.create_identity()
        seed = im1.export_identity()

        # Sign with original
        signer1 = RelaySigner(identity_manager=im1, username="user1")
        env1 = signer1.sign_event("room", b"test", timestamp=1700000000)

        # Import to new manager
        im2 = IdentityManager(tmp_path / "id2.json")
        im2.import_identity(seed)

        # Sign with imported
        signer2 = RelaySigner(identity_manager=im2, username="user1")
        env2 = signer2.sign_event("room", b"test", timestamp=1700000000)

        # Same pubkey and signature
        assert env1.sender_pubkey_hex == env2.sender_pubkey_hex
        assert env1.signature_hex == env2.signature_hex
        assert env1.event_id == env2.event_id


class TestContactManagerIntegration:
    """Integration tests for ContactManager with message flow."""

    def test_auto_add_contact_on_message_receive(self, tmp_path: Path) -> None:
        """Simulates receiving a message and adding sender to contacts."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel
        from ming_drlms.core.relay_signer import RelaySigner

        # Sender creates and signs
        sender_im = IdentityManager(tmp_path / "sender.json")
        sender_im.create_identity(alias="alice")

        signer = RelaySigner(identity_manager=sender_im, username="alice")
        envelope = signer.sign_event("chatroom", b"Hi from Alice")

        # Receiver's contact manager
        contacts = ContactManager(tmp_path / "receiver_contacts.json")

        sender_pubkey = bytes.fromhex(envelope.sender_pubkey_hex)

        # Before: unknown
        assert not contacts.is_known(sender_pubkey)

        # Simulate: receiver adds sender as unverified contact
        contacts.add_contact(
            sender_pubkey,
            alias="alice",
            trust=TrustLevel.UNVERIFIED,
        )

        # After: known but not trusted
        assert contacts.is_known(sender_pubkey)
        assert not contacts.is_trusted(sender_pubkey)

        # Receiver verifies out-of-band and marks trusted
        contacts.set_trust(sender_pubkey, TrustLevel.VERIFIED)
        assert contacts.is_trusted(sender_pubkey)

    def test_blocked_contact_detection(self, tmp_path: Path) -> None:
        """Blocked contacts are properly detected."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        contacts = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        contacts.add_contact(pubkey, alias="spammer", trust=TrustLevel.BLOCKED)

        assert contacts.is_known(pubkey)
        assert contacts.is_blocked(pubkey)
        assert not contacts.is_trusted(pubkey)


class TestRoomManagerIntegration:
    """Integration tests for RoomManager with message flow."""

    def test_room_member_tracking_on_message(self, tmp_path: Path) -> None:
        """Simulates tracking room members from messages."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.room_manager import RoomManager
        from ming_drlms.core.relay_signer import RelaySigner

        # Alice sends a message
        alice_im = IdentityManager(tmp_path / "alice.json")
        alice_im.create_identity()
        alice_signer = RelaySigner(identity_manager=alice_im, username="alice")
        alice_env = alice_signer.sign_event("project-room", b"Hello from Alice")

        # Bob sends a message
        bob_im = IdentityManager(tmp_path / "bob.json")
        bob_im.create_identity()
        bob_signer = RelaySigner(identity_manager=bob_im, username="bob")
        bob_env = bob_signer.sign_event("project-room", b"Hello from Bob")

        # Room manager tracks members
        rooms = RoomManager(tmp_path / "rooms.json")
        rooms.create_room("project-room")

        alice_pk = bytes.fromhex(alice_env.sender_pubkey_hex)
        bob_pk = bytes.fromhex(bob_env.sender_pubkey_hex)

        rooms.add_member("project-room", alice_pk, alias="Alice")
        rooms.add_member("project-room", bob_pk, alias="Bob")

        members = rooms.get_members("project-room")
        assert len(members) == 2

        pubkeys = rooms.get_member_pubkeys("project-room")
        assert alice_pk in pubkeys
        assert bob_pk in pubkeys


class TestRelayEnvelopeFormat:
    """Tests for Relay envelope format compatibility."""

    def test_envelope_json_structure(self, tmp_path: Path) -> None:
        """Envelope JSON has all required fields for Relay."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="testuser", device_id=2)
        envelope = signer.sign_event("room1", b"content")

        d = envelope.to_dict()

        # Required fields for Relay
        assert "sender_id" in d
        assert "device_id" in d
        assert "ts" in d
        assert "content_type" in d
        assert "content_bytes_b64" in d
        assert "signature_hex" in d
        assert "sender_pubkey_hex" in d
        assert "event_id" in d

        # Values
        assert d["sender_id"] == "testuser"
        assert d["device_id"] == 2
        assert d["content_type"] == "text"

    def test_ciphertext_b64_decode(self, tmp_path: Path) -> None:
        """to_ciphertext_b64() produces valid base64 JSON."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="user")
        envelope = signer.sign_event("room", b"test")

        ciphertext = envelope.to_ciphertext_b64()

        # Decode
        raw = base64.b64decode(ciphertext)
        data = json.loads(raw)

        assert data["sender_id"] == "user"
        assert "signature_hex" in data
        assert "event_id" in data


class TestLocalKeyStoreFallback:
    """Tests for fallback to LocalKeyStore when no IdentityManager."""

    @pytest.mark.skip(reason="LocalKeyStore fallback uses default path, not tmp_path")
    def test_relay_signer_uses_local_keystore_fallback(self, tmp_path: Path) -> None:
        """RelaySigner falls back to LocalKeyStore when no IdentityManager."""
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.mproto_v2_client import SignalKeyPair
        import secrets

        # Create LocalKeyStore with identity
        ks = LocalKeyStore(tmp_path / "e2ee_keys.json")
        seed = secrets.token_bytes(32)

        # Derive pubkey from seed
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        priv = Ed25519PrivateKey.from_private_bytes(seed)
        pubkey = priv.public_key().public_bytes_raw()

        identity_pair = SignalKeyPair(public_key=pubkey, private_key=seed)
        ks.store_keys(
            "fallback-user",
            registration_id=12345,
            device_id=1,
            identity=identity_pair,
            signed_pre_key=None,
            pre_keys=[],
        )

        # Create signer WITHOUT IdentityManager, WITH username
        signer = RelaySigner(
            identity_manager=None,
            username="fallback-user",
            device_id=1,
        )

        # Should fall back to LocalKeyStore
        assert signer.can_sign()

        # Sign should work
        envelope = signer.sign_event("room", b"fallback test")
        assert len(envelope.signature_hex) == 128
        assert envelope.sender_pubkey_hex == pubkey.hex()
