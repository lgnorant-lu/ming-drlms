"""Phase 15.5 XEdDSA End-to-End Integration Tests

This module provides comprehensive E2E tests for the XEdDSA implementation:
1. Key generation via Signal Protocol
2. Identity storage in LocalKeyStore
3. XEdDSA signing via IdentityManager/RelaySigner
4. XEdDSA verification via relay_crypto
5. Full Relay event sign → envelope → verify cycle

These tests verify the complete integration of the Phase 15.5 XEdDSA
implementation without mocking the C layer.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest


@pytest.fixture
def temp_keystore(tmp_path: Path):
    """Create a temporary LocalKeyStore with generated keys."""
    from ming_drlms.core.e2ee_store import LocalKeyStore
    from ming_drlms.core.pysignal.context import create_signal_context
    from ming_drlms.core.pysignal.keys import generate_device_keys

    ks_path = tmp_path / "e2ee_keys.json"
    ks = LocalKeyStore(ks_path)

    ctx = create_signal_context()
    keys = generate_device_keys(ctx)
    ks.store_keys(
        "test_user",
        registration_id=keys.registration_id,
        device_id=keys.device_id,
        identity=keys.identity,
        signed_pre_key=keys.signed_pre_key,
        pre_keys=keys.pre_keys,
    )
    return ks


class TestXEdDSAKeyGeneration:
    """Test XEdDSA key generation and storage."""

    def test_generate_device_keys_creates_valid_identity(self, tmp_path: Path) -> None:
        """Signal Protocol generates valid X25519 identity keypair."""
        from ming_drlms.core.pysignal.context import create_signal_context
        from ming_drlms.core.pysignal.keys import generate_device_keys

        ctx = create_signal_context()
        keys = generate_device_keys(ctx)

        # Verify key structure
        assert keys.identity is not None
        assert len(keys.identity.private_key) == 32
        assert len(keys.identity.public_key) in (32, 33)  # May have type prefix
        assert keys.registration_id > 0

    def test_identity_stored_in_keystore(self, temp_keystore) -> None:
        """Identity is correctly stored and retrievable from LocalKeyStore."""
        state = temp_keystore.load_state("test_user")

        assert state is not None
        assert state.identity_key is not None
        assert len(state.identity_key.private_key) == 32
        assert len(state.identity_key.public_key) in (32, 33)


class TestIdentityManagerXEdDSA:
    """Test IdentityManager XEdDSA signing capabilities."""

    def test_identity_manager_has_identity(self, temp_keystore) -> None:
        """IdentityManager correctly detects identity existence."""
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        assert mgr.has_identity() is True

        mgr_no_id = IdentityManager("nonexistent_user", keystore=temp_keystore)
        assert mgr_no_id.has_identity() is False

    def test_identity_manager_get_pubkey(self, temp_keystore) -> None:
        """IdentityManager returns 32-byte X25519 public key."""
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        pubkey = mgr.get_pubkey()

        assert isinstance(pubkey, bytes)
        assert len(pubkey) == 32

    def test_identity_manager_xeddsa_sign(self, temp_keystore) -> None:
        """IdentityManager produces 64-byte XEdDSA signature."""
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        message = b"Test message for XEdDSA signing"

        signature = mgr.sign(message)

        assert isinstance(signature, bytes)
        assert len(signature) == 64

    def test_identity_manager_xeddsa_verify(self, temp_keystore) -> None:
        """IdentityManager correctly verifies XEdDSA signatures."""
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        message = b"Test message for XEdDSA verification"

        signature = mgr.sign(message)
        pubkey = mgr.get_pubkey()

        # Verify correct signature
        assert mgr.verify(message, signature, pubkey) is True

        # Verify tampered message fails
        assert mgr.verify(b"Tampered message", signature, pubkey) is False

        # Verify tampered signature fails
        tampered_sig = bytes([b ^ 0xFF for b in signature[:8]]) + signature[8:]
        assert mgr.verify(message, tampered_sig, pubkey) is False


class TestRelaySignerXEdDSA:
    """Test RelaySigner XEdDSA signing for Relay events."""

    def test_relay_signer_can_sign(self, temp_keystore) -> None:
        """RelaySigner correctly detects signing capability."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        signer = RelaySigner(identity_manager=mgr, username="test_user", device_id=1)

        assert signer.can_sign() is True

    def test_relay_signer_sign_event(self, temp_keystore) -> None:
        """RelaySigner creates valid signed envelope."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        signer = RelaySigner(identity_manager=mgr, username="test_user", device_id=1)

        envelope = signer.sign_event(
            room="test-room",
            content=b"Hello XEdDSA!",
            content_type="text",
            timestamp=1234567890,
        )

        # Verify envelope structure
        assert envelope.room == "test-room"
        assert envelope.sender_id == "test_user"
        assert envelope.device_id == 1
        assert envelope.timestamp == 1234567890
        assert len(envelope.signature_hex) == 128  # 64 bytes = 128 hex chars
        assert len(envelope.sender_pubkey_hex) == 64  # 32 bytes = 64 hex chars
        assert envelope.event_id  # Should be non-empty

    def test_relay_signer_envelope_verifiable(self, temp_keystore) -> None:
        """RelaySigner envelope can be verified with XEdDSA."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.clear_event import canonical_serialize
        from ming_drlms.core.relay_crypto import _xeddsa_verify

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        signer = RelaySigner(identity_manager=mgr, username="test_user", device_id=1)

        content = b"Verifiable message"
        envelope = signer.sign_event(
            room="verify-room",
            content=content,
            content_type="text",
            timestamp=1234567890,
        )

        # Reconstruct canonical serialization
        serialized = canonical_serialize(
            room="verify-room",
            ts=1234567890,
            sender_id="test_user",
            device_id=1,
            content_type="text",
            content_bytes=content,
        )

        # Verify with XEdDSA
        pubkey = bytes.fromhex(envelope.sender_pubkey_hex)
        signature = bytes.fromhex(envelope.signature_hex)

        assert _xeddsa_verify(pubkey, serialized, signature) is True


class TestFullRelayCycle:
    """Test full Relay event cycle: sign → encode → decode → verify."""

    def test_full_relay_event_cycle(self, temp_keystore) -> None:
        """Full cycle: sign → envelope → JSON → base64 → decode → verify."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.relay_crypto import build_decrypt_and_verify

        # Setup
        mgr = IdentityManager("test_user", keystore=temp_keystore)
        signer = RelaySigner(identity_manager=mgr, username="test_user", device_id=1)

        # Step 1: Sign event
        content = b"Full cycle test message"
        envelope = signer.sign_event(
            room="cycle-room",
            content=content,
            content_type="text",
            timestamp=1234567890,
        )

        # Step 2: Encode as base64 (as would be sent to Relay)
        ciphertext_b64 = envelope.to_ciphertext_b64()

        # Step 3: Create identity resolver that returns the correct pubkey
        def identity_resolver(sender_id, device_id):
            if sender_id == "test_user":
                return mgr.get_pubkey()
            return b""

        # Step 4: Build decrypt and verify function
        decrypt_and_verify = build_decrypt_and_verify(
            engine_factory=None,
            identity_resolver=identity_resolver,
        )

        # Step 5: Simulate Relay event
        relay_event = {
            "room": "cycle-room",
            "ciphertext": ciphertext_b64,
            "server_ts": 1234567890,
        }

        # Step 6: Decrypt and verify
        result = decrypt_and_verify(relay_event)

        # Verify result
        assert result is not None
        assert result.get("verified") is True
        assert result.get("sender_id") == "test_user"
        assert result.get("device_id") == 1
        assert result.get("content_bytes") == content

    def test_tampered_signature_rejected(self, temp_keystore) -> None:
        """Tampered signature is correctly rejected."""
        from ming_drlms.core.identity_manager import IdentityManager
        from ming_drlms.core.relay_signer import RelaySigner
        from ming_drlms.core.relay_crypto import build_decrypt_and_verify

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        signer = RelaySigner(identity_manager=mgr, username="test_user", device_id=1)

        envelope = signer.sign_event(
            room="tamper-room",
            content=b"Original message",
            content_type="text",
            timestamp=1234567890,
        )

        # Tamper with signature
        tampered_sig = "ff" * 64  # Invalid signature

        # Create tampered envelope dict
        env_dict = envelope.to_dict()
        env_dict["signature_hex"] = tampered_sig
        ciphertext_b64 = base64.b64encode(json.dumps(env_dict).encode("utf-8")).decode(
            "ascii"
        )

        def identity_resolver(sender_id, device_id):
            return mgr.get_pubkey()

        decrypt_and_verify = build_decrypt_and_verify(
            engine_factory=None,
            identity_resolver=identity_resolver,
        )

        relay_event = {
            "room": "tamper-room",
            "ciphertext": ciphertext_b64,
            "server_ts": 1234567890,
        }

        # Should be rejected
        result = decrypt_and_verify(relay_event)
        assert result is None


class TestCrossPlatformCompatibility:
    """Test compatibility aspects of XEdDSA implementation."""

    def test_signature_consistency(self, temp_keystore) -> None:
        """Same message produces valid but different signatures (random nonce)."""
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        message = b"Consistency test message"

        sig1 = mgr.sign(message)
        sig2 = mgr.sign(message)

        # XEdDSA uses random nonce for security, so signatures differ
        # But both should be valid
        pubkey = mgr.get_pubkey()
        assert mgr.verify(message, sig1, pubkey) is True
        assert mgr.verify(message, sig2, pubkey) is True
        assert len(sig1) == 64
        assert len(sig2) == 64

    def test_public_key_format(self, temp_keystore) -> None:
        """Public key is in correct X25519 format."""
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        pubkey = mgr.get_pubkey()

        # Should be exactly 32 bytes (no type prefix)
        assert len(pubkey) == 32

        # Should be valid hex
        pubkey_hex = pubkey.hex()
        assert len(pubkey_hex) == 64
        assert all(c in "0123456789abcdef" for c in pubkey_hex)


class TestIdentityImportDelete:
    """Test identity import and delete functionality."""

    def test_identity_delete(self, tmp_path: Path) -> None:
        """Test deleting user identity from LocalKeyStore."""
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pysignal.context import create_signal_context
        from ming_drlms.core.pysignal.keys import generate_device_keys
        from ming_drlms.core.identity_manager import IdentityManager

        ks_path = tmp_path / "e2ee_keys.json"
        ks = LocalKeyStore(ks_path)

        ctx = create_signal_context()
        keys = generate_device_keys(ctx)
        ks.store_keys(
            "delete_test",
            registration_id=keys.registration_id,
            device_id=keys.device_id,
            identity=keys.identity,
            signed_pre_key=keys.signed_pre_key,
            pre_keys=keys.pre_keys,
        )

        mgr = IdentityManager("delete_test", keystore=ks)
        assert mgr.has_identity() is True

        # Delete identity
        result = ks.delete_user_state("delete_test")
        assert result is True

        # Create new IdentityManager to verify deletion (fresh state)
        mgr2 = IdentityManager("delete_test", keystore=ks)
        assert mgr2.has_identity() is False

    def test_identity_import_from_private_key(self, tmp_path: Path) -> None:
        """Test importing identity from private key."""
        from ming_drlms.core.e2ee_store import LocalKeyStore, SignalKeyPair
        from ming_drlms.core.pysignal.context import create_signal_context
        from ming_drlms.core.pysignal.keys import generate_device_keys
        from ming_drlms.core.pysignal.signature import _derive_public_from_private
        from ming_drlms.core.identity_manager import IdentityManager

        ks_path = tmp_path / "e2ee_keys.json"
        ks = LocalKeyStore(ks_path)

        # Generate original keys
        ctx = create_signal_context()
        keys = generate_device_keys(ctx)
        original_privkey = keys.identity.private_key

        # Store original
        ks.store_keys(
            "import_test",
            registration_id=keys.registration_id,
            device_id=keys.device_id,
            identity=keys.identity,
            signed_pre_key=keys.signed_pre_key,
            pre_keys=keys.pre_keys,
        )

        # Get original pubkey via IdentityManager (stripped of prefix)
        mgr = IdentityManager("import_test", keystore=ks)
        original_pubkey = mgr.get_pubkey()

        # Delete
        ks.delete_user_state("import_test")
        # Verify deletion with fresh instance
        mgr_deleted = IdentityManager("import_test", keystore=ks)
        assert mgr_deleted.has_identity() is False

        # Re-import using same private key
        derived_pubkey = _derive_public_from_private(ctx, original_privkey)
        imported_identity = SignalKeyPair(
            private_key=original_privkey,
            public_key=derived_pubkey,
        )
        new_keys = generate_device_keys(ctx)
        ks.store_keys(
            "import_test",
            registration_id=new_keys.registration_id,
            device_id=new_keys.device_id,
            identity=imported_identity,
            signed_pre_key=new_keys.signed_pre_key,
            pre_keys=new_keys.pre_keys,
        )

        # Verify imported identity has same public key (fresh instance)
        mgr_imported = IdentityManager("import_test", keystore=ks)
        assert mgr_imported.has_identity() is True
        assert mgr_imported.get_pubkey() == original_pubkey


class TestMP2LoginSignature:
    """Test MP2 login signature with XEdDSA."""

    def test_mp2_binding_message_format(self, temp_keystore) -> None:
        """Test MP2 binding message format for XEdDSA signing."""
        import time
        from ming_drlms.core.identity_manager import IdentityManager

        mgr = IdentityManager("test_user", keystore=temp_keystore)
        st = temp_keystore.load_state("test_user")

        # Build binding message same as MP2 client
        ts = int(time.time())
        binding_parts = [
            b"MP2-LOGIN-V1",
            b"test_user",
            str(st.device_id).encode("ascii"),
            str(st.registration_id).encode("ascii"),
            b"test_nonce",
            b"test_salt",
            str(ts).encode("ascii"),
        ]
        binding = b"|".join(binding_parts)

        # Sign with XEdDSA
        sig = mgr.sign(binding)

        # Verify signature
        assert len(sig) == 64
        assert mgr.verify(binding, sig, mgr.get_pubkey()) is True

    def test_protobuf_signature_type_field(self) -> None:
        """Test that SignatureType enum exists in generated protobuf."""
        from ming_drlms.proto.schema.v2 import auth_pb2

        # Verify enum values exist
        assert hasattr(auth_pb2, "SIG_TYPE_ED25519") or hasattr(
            auth_pb2, "SignatureType"
        )

        # Create ClientInfo and set signature_type
        client = auth_pb2.ClientInfo()
        client.signature_type = 1  # SIG_TYPE_XEDDSA
        assert client.signature_type == 1
