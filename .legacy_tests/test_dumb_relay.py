"""Phase 15D: Dumb Relay integration tests.

Tests for the "dumb relay" architecture where:
- Server only stores and relays events (no user management)
- Client handles identity, signing, and verification
- All events are signed with Ed25519
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

import pytest


class TestRelaySigner:
    """Tests for RelaySigner using IdentityManager."""

    def test_signer_with_identity_manager(self, tmp_path: Path) -> None:
        """RelaySigner can sign using IdentityManager."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="testuser", device_id=1)

        assert signer.can_sign()
        assert signer.get_pubkey() == im.get_pubkey()

    def test_signer_sign_returns_64_bytes(self, tmp_path: Path) -> None:
        """RelaySigner.sign returns 64-byte signature."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="testuser")
        signature = signer.sign(b"test data")

        assert len(signature) == 64

    def test_signer_no_identity_raises(self, tmp_path: Path) -> None:
        """RelaySigner raises if no identity available."""
        from ming_drlms.core.relay_signer import RelaySigner

        signer = RelaySigner()  # No identity manager, no username

        assert not signer.can_sign()

        with pytest.raises(RuntimeError, match="No signing identity"):
            signer.get_pubkey()

        with pytest.raises(RuntimeError, match="No signing identity"):
            signer.sign(b"data")


class TestRelayEventEnvelope:
    """Tests for RelayEventEnvelope creation."""

    def test_sign_event_creates_valid_envelope(self, tmp_path: Path) -> None:
        """sign_event creates a complete envelope."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="alice", device_id=2)
        envelope = signer.sign_event("general", b"hello world", timestamp=1700000000)

        assert envelope.room == "general"
        assert envelope.sender_id == "alice"
        assert envelope.device_id == 2
        assert envelope.timestamp == 1700000000
        assert envelope.content_type == "text"
        assert envelope.content_bytes == b"hello world"
        assert len(envelope.signature_hex) == 128  # 64 bytes as hex
        assert len(envelope.sender_pubkey_hex) == 64  # 32 bytes as hex
        assert len(envelope.event_id) == 64  # SHA256 hex

    def test_envelope_to_dict(self, tmp_path: Path) -> None:
        """to_dict returns correct structure for JSON."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="bob")
        envelope = signer.sign_event("room1", b"test")

        d = envelope.to_dict()

        assert d["sender_id"] == "bob"
        assert d["device_id"] == 1
        assert "ts" in d
        assert d["content_type"] == "text"
        assert "content_bytes_b64" in d
        assert "signature_hex" in d
        assert "sender_pubkey_hex" in d
        assert "event_id" in d

    def test_envelope_to_ciphertext_b64(self, tmp_path: Path) -> None:
        """to_ciphertext_b64 returns valid base64 JSON."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="charlie")
        envelope = signer.sign_event("room2", b"content")

        b64 = envelope.to_ciphertext_b64()

        # Should be valid base64
        decoded = base64.b64decode(b64)
        # Should be valid JSON
        data = json.loads(decoded)
        assert data["sender_id"] == "charlie"


class TestSignatureVerification:
    """Tests for signature verification roundtrip."""

    def test_signed_event_can_be_verified(self, tmp_path: Path) -> None:
        """Signed event can be verified with IdentityManager."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.clear_event import canonical_serialize

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="dave", device_id=1)
        envelope = signer.sign_event("verifyroom", b"verify me")

        # Reconstruct the serialized data for verification
        serialized = canonical_serialize(
            room="verifyroom",
            ts=envelope.timestamp,
            sender_id="dave",
            device_id=1,
            content_type="text",
            content_bytes=b"verify me",
        )

        # Verify using IdentityManager
        signature = bytes.fromhex(envelope.signature_hex)
        pubkey = bytes.fromhex(envelope.sender_pubkey_hex)

        assert im.verify(serialized, signature, pubkey)

    def test_tampered_content_fails_verification(self, tmp_path: Path) -> None:
        """Tampered content fails verification."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.clear_event import canonical_serialize

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="eve", device_id=1)
        envelope = signer.sign_event("tamperroom", b"original")

        # Tamper: use different content
        tampered_serialized = canonical_serialize(
            room="tamperroom",
            ts=envelope.timestamp,
            sender_id="eve",
            device_id=1,
            content_type="text",
            content_bytes=b"tampered",  # Different!
        )

        signature = bytes.fromhex(envelope.signature_hex)
        pubkey = bytes.fromhex(envelope.sender_pubkey_hex)

        assert not im.verify(tampered_serialized, signature, pubkey)

    def test_wrong_pubkey_fails_verification(self, tmp_path: Path) -> None:
        """Wrong public key fails verification."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.clear_event import canonical_serialize

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        signer = RelaySigner(identity_manager=im, username="frank", device_id=1)
        envelope = signer.sign_event("wrongkey", b"content")

        serialized = canonical_serialize(
            room="wrongkey",
            ts=envelope.timestamp,
            sender_id="frank",
            device_id=1,
            content_type="text",
            content_bytes=b"content",
        )

        signature = bytes.fromhex(envelope.signature_hex)
        wrong_pubkey = secrets.token_bytes(32)  # Random wrong key

        assert not im.verify(serialized, signature, wrong_pubkey)


class TestConvenienceFunction:
    """Tests for sign_relay_event convenience function."""

    def test_sign_relay_event_with_identity_manager(self, tmp_path: Path) -> None:
        """sign_relay_event works with IdentityManager."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import sign_relay_event

        im = IdentityManager(tmp_path / "identity.json")
        im.create_identity()

        envelope = sign_relay_event(
            "myroom",
            b"my message",
            identity_manager=im,
            username="grace",
        )

        assert envelope.room == "myroom"
        assert envelope.sender_id == "grace"
        assert len(envelope.signature_hex) == 128


class TestDumbRelayIntegration:
    """Integration tests for full dumb relay workflow."""

    def test_full_sign_encode_decode_verify_flow(self, tmp_path: Path) -> None:
        """Full flow: sign -> encode -> decode -> verify."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.clear_event import canonical_serialize

        # Sender creates and signs
        sender_im = IdentityManager(tmp_path / "sender.json")
        sender_im.create_identity(alias="sender")

        signer = RelaySigner(identity_manager=sender_im, username="sender_user")
        envelope = signer.sign_event("chatroom", b"Hello, receiver!")

        # Simulate Relay: encode to base64
        ciphertext = envelope.to_ciphertext_b64()

        # Receiver decodes
        raw = base64.b64decode(ciphertext)
        data = json.loads(raw)

        # Receiver verifies
        serialized = canonical_serialize(
            room="chatroom",
            ts=data["ts"],
            sender_id=data["sender_id"],
            device_id=data["device_id"],
            content_type=data["content_type"],
            content_bytes=base64.b64decode(data["content_bytes_b64"]),
        )

        signature = bytes.fromhex(data["signature_hex"])
        pubkey = bytes.fromhex(data["sender_pubkey_hex"])

        # Receiver uses their own IdentityManager for verification
        receiver_im = IdentityManager(tmp_path / "receiver.json")
        receiver_im.create_identity(alias="receiver")

        assert receiver_im.verify(serialized, signature, pubkey)

    def test_contact_trust_integration(self, tmp_path: Path) -> None:
        """Contacts can be trusted based on verified pubkeys."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel
        from ming_drlms.core.relay_signer import RelaySigner

        # Alice creates identity
        alice_im = IdentityManager(tmp_path / "alice.json")
        alice_im.create_identity(alias="alice")

        # Alice signs a message
        signer = RelaySigner(identity_manager=alice_im, username="alice")
        envelope = signer.sign_event("room", b"Hi from Alice")

        # Bob receives and verifies
        bob_im = IdentityManager(tmp_path / "bob.json")
        bob_im.create_identity(alias="bob")

        # Bob adds Alice to contacts after verification
        contacts = ContactManager(tmp_path / "bob_contacts.json")
        alice_pubkey = bytes.fromhex(envelope.sender_pubkey_hex)

        # First time: unknown
        assert not contacts.is_known(alice_pubkey)

        # After verification, Bob adds Alice as trusted
        contacts.add_contact(alice_pubkey, alias="Alice", trust=TrustLevel.VERIFIED)

        assert contacts.is_known(alice_pubkey)
        assert contacts.is_trusted(alice_pubkey)

    def test_room_member_tracking(self, tmp_path: Path) -> None:
        """Room members can be tracked by pubkey."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.room_manager import RoomManager
        from ming_drlms.core.relay_signer import RelaySigner

        # Charlie joins a room
        charlie_im = IdentityManager(tmp_path / "charlie.json")
        charlie_im.create_identity()

        rooms = RoomManager(tmp_path / "rooms.json")
        rooms.create_room("project-x")

        # Charlie sends a message
        signer = RelaySigner(identity_manager=charlie_im, username="charlie")
        envelope = signer.sign_event("project-x", b"My contribution")

        # Room tracks Charlie as member
        charlie_pubkey = bytes.fromhex(envelope.sender_pubkey_hex)
        rooms.add_member("project-x", charlie_pubkey, alias="Charlie")

        assert rooms.is_member("project-x", charlie_pubkey)
        members = rooms.get_members("project-x")
        assert len(members) == 1
        assert members[0].alias == "Charlie"
