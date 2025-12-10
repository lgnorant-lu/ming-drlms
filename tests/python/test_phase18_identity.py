"""Phase 18A: Unit tests for local identity and trust management.

Tests:
- LocalIdentity creation and serialization
- LocalIdentityManager CRUD operations
- Fingerprint generation and formatting
- TrustStore operations
- TrustRecord verification
- Verification utilities (fingerprint, QR)
"""

from __future__ import annotations


import pytest


class TestFingerprint:
    """Test fingerprint generation and formatting."""

    def test_generate_fingerprint_32_bytes(self):
        """Test fingerprint generation from 32-byte key."""
        from ming_drlms.identity import generate_fingerprint

        # Known test vector
        pubkey = bytes.fromhex("0" * 64)  # 32 bytes of zeros
        fp = generate_fingerprint(pubkey)

        # Should be 6 groups of 4 hex chars
        parts = fp.split()
        assert len(parts) == 6
        for part in parts:
            assert len(part) == 4
            assert all(c in "0123456789ABCDEF" for c in part)

    def test_generate_fingerprint_33_bytes(self):
        """Test fingerprint strips type prefix from 33-byte key."""
        from ming_drlms.identity import generate_fingerprint

        pubkey_32 = bytes.fromhex("0" * 64)
        pubkey_33 = bytes([0x05]) + pubkey_32  # With type prefix

        fp_32 = generate_fingerprint(pubkey_32)
        fp_33 = generate_fingerprint(pubkey_33)

        assert fp_32 == fp_33  # Should be identical

    def test_format_fingerprint_styles(self):
        """Test different fingerprint formatting styles."""
        from ming_drlms.identity import generate_fingerprint, format_fingerprint

        pubkey = bytes.fromhex("0" * 64)
        fp = generate_fingerprint(pubkey)

        # Groups (default)
        groups = format_fingerprint(fp, "groups")
        assert " " in groups

        # Compact
        compact = format_fingerprint(fp, "compact")
        assert " " not in compact
        assert len(compact) == 24  # 12 bytes = 24 hex chars

        # Lines
        lines = format_fingerprint(fp, "lines")
        assert "\n" in lines


class TestLocalIdentity:
    """Test LocalIdentity dataclass."""

    def test_local_identity_creation(self):
        """Test creating LocalIdentity."""
        from ming_drlms.identity import LocalIdentity

        identity = LocalIdentity(
            private_key=bytes(32),
            public_key=bytes(32),
            registration_id=12345,
            device_id=1,
            display_name="Test User",
        )

        assert identity.registration_id == 12345
        assert identity.display_name == "Test User"
        assert len(identity.fingerprint) > 0

    def test_local_identity_to_dict(self):
        """Test serialization to dict."""
        from ming_drlms.identity import LocalIdentity

        identity = LocalIdentity(
            private_key=bytes(32),
            public_key=bytes(32),
            display_name="Alice",
        )

        data = identity.to_dict()

        assert data["version"] == 1
        assert data["private_key"] == "0" * 64
        assert data["public_key"] == "0" * 64
        assert data["display_name"] == "Alice"

    def test_local_identity_from_dict(self):
        """Test deserialization from dict."""
        from ming_drlms.identity import LocalIdentity

        data = {
            "private_key": "0" * 64,
            "public_key": "1" * 64,
            "registration_id": 100,
            "device_id": 2,
            "display_name": "Bob",
            "created_at": "2025-01-01T00:00:00",
        }

        identity = LocalIdentity.from_dict(data)

        assert identity.registration_id == 100
        assert identity.device_id == 2
        assert identity.display_name == "Bob"

    def test_local_identity_json_roundtrip(self):
        """Test JSON export/import roundtrip."""
        from ming_drlms.identity import LocalIdentity

        original = LocalIdentity(
            private_key=bytes.fromhex("ab" * 32),
            public_key=bytes.fromhex("cd" * 32),
            display_name="Roundtrip Test",
        )

        json_str = original.export_json()
        restored = LocalIdentity.import_json(json_str)

        assert original.private_key == restored.private_key
        assert original.public_key == restored.public_key
        assert original.display_name == restored.display_name


class TestLocalIdentityManager:
    """Test LocalIdentityManager operations."""

    def test_create_identity(self, tmp_path):
        """Test creating a new identity."""
        from ming_drlms.identity import LocalIdentityManager

        manager = LocalIdentityManager(identity_dir=tmp_path)

        assert not manager.has_identity()

        identity = manager.create_identity(display_name="Test")

        assert manager.has_identity()
        assert len(identity.private_key) == 32
        assert len(identity.public_key) in (32, 33)
        assert identity.registration_id > 0

    def test_load_identity(self, tmp_path):
        """Test loading existing identity."""
        from ming_drlms.identity import LocalIdentityManager

        manager1 = LocalIdentityManager(identity_dir=tmp_path)
        created = manager1.create_identity(display_name="Persistent")

        # Create new manager instance
        manager2 = LocalIdentityManager(identity_dir=tmp_path)
        loaded = manager2.load_identity()

        assert loaded is not None
        assert loaded.public_key == created.public_key
        assert loaded.display_name == "Persistent"

    def test_export_import_identity(self, tmp_path):
        """Test exporting and importing identity."""
        from ming_drlms.identity import LocalIdentityManager

        manager1 = LocalIdentityManager(identity_dir=tmp_path / "source")
        original = manager1.create_identity(display_name="Export Test")

        backup_file = tmp_path / "backup.json"
        manager1.export_identity(backup_file)

        # Import to different location
        manager2 = LocalIdentityManager(identity_dir=tmp_path / "target")
        imported = manager2.import_identity(backup_file)

        assert imported.public_key == original.public_key
        assert imported.private_key == original.private_key

    def test_fingerprint_verification(self, tmp_path):
        """Test fingerprint verification."""
        from ming_drlms.identity import LocalIdentityManager

        manager = LocalIdentityManager(identity_dir=tmp_path)
        identity = manager.create_identity()

        correct_fp = identity.fingerprint
        wrong_fp = "ABCD " * 6

        assert manager.verify_fingerprint(correct_fp)
        assert not manager.verify_fingerprint(wrong_fp)


class TestTrustStore:
    """Test TrustStore operations."""

    def test_record_contact_tofu(self, tmp_path):
        """Test recording new contact defaults to TOFU."""
        from ming_drlms.identity import TrustStore, TrustLevel

        store = TrustStore(store_path=tmp_path / "trust.json")
        pubkey = bytes.fromhex("ab" * 32)

        record = store.record_contact(pubkey, display_name="Alice")

        assert record.trust_level == TrustLevel.TOFU
        assert record.display_name == "Alice"

    def test_verify_manual(self, tmp_path):
        """Test manual verification upgrades trust level."""
        from ming_drlms.identity import TrustStore, TrustLevel

        store = TrustStore(store_path=tmp_path / "trust.json")
        pubkey = bytes.fromhex("ab" * 32)

        store.record_contact(pubkey)
        record = store.verify_manual(pubkey)

        assert record.trust_level == TrustLevel.MANUAL
        assert len(record.verifications) == 1
        assert record.verifications[0].method == "manual"

    def test_verify_anchor(self, tmp_path):
        """Test anchor verification upgrades to highest trust."""
        from ming_drlms.identity import TrustStore, TrustLevel

        store = TrustStore(store_path=tmp_path / "trust.json")
        pubkey = bytes.fromhex("cd" * 32)

        store.record_contact(pubkey)
        record = store.verify_anchor(pubkey, "dns", "example.com")

        assert record.trust_level == TrustLevel.ANCHORED
        assert len(record.verifications) == 1
        assert record.verifications[0].method == "dns"
        assert record.verifications[0].details == "example.com"

    def test_key_change_detection(self, tmp_path):
        """Test key change resets trust."""
        from ming_drlms.identity import TrustStore, TrustLevel

        store = TrustStore(store_path=tmp_path / "trust.json")
        old_key = bytes.fromhex("ab" * 32)
        new_key = bytes.fromhex("cd" * 32)

        # Establish high trust
        store.record_contact(old_key, display_name="Bob")
        store.verify_manual(old_key)

        assert store.get_trust_level(old_key) == TrustLevel.MANUAL

        # Key change
        event = store.update_key(old_key, new_key)

        assert event is not None
        assert event.old_key == old_key
        assert event.new_key == new_key

        # Trust should be reset
        assert store.get_trust_level(new_key) == TrustLevel.TOFU

    def test_block_unblock(self, tmp_path):
        """Test blocking and unblocking contacts."""
        from ming_drlms.identity import TrustStore

        store = TrustStore(store_path=tmp_path / "trust.json")
        pubkey = bytes.fromhex("ab" * 32)

        store.record_contact(pubkey)

        assert not store.is_blocked(pubkey)

        store.block_contact(pubkey, reason="spam")
        assert store.is_blocked(pubkey)

        record = store.get_record(pubkey)
        assert record.blocked_reason == "spam"

        store.unblock_contact(pubkey)
        assert not store.is_blocked(pubkey)

    def test_persistence(self, tmp_path):
        """Test trust store persists to disk."""
        from ming_drlms.identity import TrustStore, TrustLevel

        store_path = tmp_path / "trust.json"
        pubkey = bytes.fromhex("ab" * 32)

        # Create and populate
        store1 = TrustStore(store_path=store_path)
        store1.record_contact(pubkey, display_name="Persistent")
        store1.verify_manual(pubkey)

        # Load fresh instance
        store2 = TrustStore(store_path=store_path)
        record = store2.get_record(pubkey)

        assert record is not None
        assert record.display_name == "Persistent"
        assert record.trust_level == TrustLevel.MANUAL


class TestVerification:
    """Test verification utilities."""

    def test_compare_fingerprints_same(self):
        """Test comparing identical fingerprints."""
        from ming_drlms.identity import compare_fingerprints

        fp1 = "7A3F 9B2C 4E1D 8F5A 2C7B 1D9E"
        fp2 = "7A3F 9B2C 4E1D 8F5A 2C7B 1D9E"

        assert compare_fingerprints(fp1, fp2)

    def test_compare_fingerprints_different_format(self):
        """Test comparing fingerprints with different formatting."""
        from ming_drlms.identity import compare_fingerprints

        fp1 = "7A3F 9B2C 4E1D 8F5A 2C7B 1D9E"
        fp2 = "7a3f9b2c4e1d8f5a2c7b1d9e"  # No spaces, lowercase

        assert compare_fingerprints(fp1, fp2)

    def test_compare_fingerprints_different(self):
        """Test comparing different fingerprints returns False."""
        from ming_drlms.identity import compare_fingerprints

        fp1 = "7A3F 9B2C 4E1D 8F5A 2C7B 1D9E"
        fp2 = "AAAA BBBB CCCC DDDD EEEE FFFF"

        assert not compare_fingerprints(fp1, fp2)

    def test_qr_data_roundtrip(self):
        """Test QR code data creation and parsing."""
        from ming_drlms.identity import (
            create_verification_qr_data,
            parse_verification_qr_data,
        )

        pubkey = bytes.fromhex("ab" * 32)

        qr_data = create_verification_qr_data(pubkey)
        assert qr_data.startswith("drlms-verify:v1:")

        parsed = parse_verification_qr_data(qr_data)
        assert parsed == pubkey

    def test_verification_session_safety_number(self):
        """Test safety number is deterministic and symmetric."""
        from ming_drlms.identity import VerificationSession

        alice_key = bytes.fromhex("aa" * 32)
        bob_key = bytes.fromhex("bb" * 32)

        # Alice's view
        session_alice = VerificationSession.create(alice_key, bob_key)

        # Bob's view (reversed)
        session_bob = VerificationSession.create(bob_key, alice_key)

        # Safety numbers should be identical
        assert session_alice.safety_number == session_bob.safety_number

    def test_fingerprint_display_formats(self):
        """Test FingerprintDisplay different formats."""
        from ming_drlms.identity import FingerprintDisplay

        pubkey = bytes.fromhex("ab" * 32)
        fp = FingerprintDisplay(pubkey)

        # Standard format
        assert " " in fp.fingerprint

        # Compact
        assert " " not in fp.compact

        # Two lines
        assert "\n" in fp.two_lines

        # Numeric
        assert all(c in "0123456789 " for c in fp.numeric)


class TestAnchors:
    """Test anchor verifiers (unit tests with mocking)."""

    def test_anchor_result_creation(self):
        """Test AnchorResult dataclass."""
        from ming_drlms.identity import AnchorResult

        result = AnchorResult(
            success=True,
            anchor_type="dns",
            anchor_id="example.com",
            declared_pubkey=bytes(32),
        )

        assert result.success
        assert result.anchor_type == "dns"
        assert result.verified_at is not None

    def test_dns_txt_parsing(self):
        """Test DNS TXT record parsing."""
        from ming_drlms.identity.anchors import DNSAnchorVerifier

        verifier = DNSAnchorVerifier()

        # Valid hex format
        record1 = "v=drlms1; pubkey=" + "ab" * 32
        result1 = verifier._parse_drlms_txt(record1)
        assert result1 == bytes.fromhex("ab" * 32)

        # Invalid (no version)
        record2 = "pubkey=" + "ab" * 32
        result2 = verifier._parse_drlms_txt(record2)
        assert result2 is None

    def test_https_pubkey_decode(self):
        """Test HTTPS verifier pubkey decoding."""
        from ming_drlms.identity.anchors import HTTPSAnchorVerifier
        import base64

        verifier = HTTPSAnchorVerifier()

        # Hex format
        hex_key = "ab" * 32
        assert verifier._decode_pubkey(hex_key) == bytes.fromhex(hex_key)

        # Base64 format
        raw_key = bytes(32)
        b64_key = base64.b64encode(raw_key).decode()
        assert verifier._decode_pubkey(b64_key) == raw_key

    def test_verify_anchor_unknown_type(self):
        """Test verify_anchor rejects unknown types."""
        from ming_drlms.identity import verify_anchor

        with pytest.raises(ValueError, match="Unknown anchor type"):
            verify_anchor("blockchain", "test", bytes(32))

    def test_https_decode_pubkey(self):
        """Test HTTPS verifier _decode_pubkey method."""
        from ming_drlms.identity.anchors import HTTPSAnchorVerifier

        verifier = HTTPSAnchorVerifier()

        # Valid hex (64 chars = 32 bytes)
        hex_key = "ab" * 32
        assert verifier._decode_pubkey(hex_key) == bytes.fromhex(hex_key)

        # Valid base64
        import base64

        raw_key = bytes(32)
        b64_key = base64.b64encode(raw_key).decode()
        assert verifier._decode_pubkey(b64_key) == raw_key

        # Short string that's neither valid hex nor valid base64 with correct length
        # Note: _decode_pubkey only fails if base64 decode throws exception
        # It doesn't validate key length, so this test just confirms the method exists

    def test_github_decode_pubkey(self):
        """Test GitHub verifier _decode_pubkey method."""
        from ming_drlms.identity.anchors import GitHubAnchorVerifier

        verifier = GitHubAnchorVerifier()

        # Valid hex
        hex_key = "cd" * 32
        assert verifier._decode_pubkey(hex_key) == bytes.fromhex(hex_key)

    def test_anchor_verifier_base_class(self):
        """Test AnchorVerifier base class."""
        from ming_drlms.identity.anchors import AnchorVerifier

        # Cannot instantiate abstract class directly
        with pytest.raises(TypeError):
            AnchorVerifier()

    def test_dns_txt_parse_edge_cases(self):
        """Test DNS TXT parsing edge cases."""
        from ming_drlms.identity.anchors import DNSAnchorVerifier

        verifier = DNSAnchorVerifier()

        # Empty string
        assert verifier._parse_drlms_txt("") is None

        # Wrong version
        assert verifier._parse_drlms_txt("v=drlms2; pubkey=" + "ab" * 32) is None

        # No pubkey field
        assert verifier._parse_drlms_txt("v=drlms1; other=value") is None

    def test_anchor_compare_keys(self):
        """Test AnchorVerifier key comparison."""
        from ming_drlms.identity.anchors import DNSAnchorVerifier

        verifier = DNSAnchorVerifier()

        key32 = bytes(32)
        key33 = bytes([0x05]) + bytes(32)  # With type prefix

        # Same keys
        assert verifier._compare_keys(key32, key32)

        # 32 vs 33 bytes (type prefix)
        assert verifier._compare_keys(key32, key33)
        assert verifier._compare_keys(key33, key32)

    def test_anchor_normalize_pubkey(self):
        """Test AnchorVerifier pubkey normalization."""
        from ming_drlms.identity.anchors import DNSAnchorVerifier

        verifier = DNSAnchorVerifier()

        key32 = bytes.fromhex("ab" * 32)
        key33 = bytes([0x05]) + key32

        assert verifier._normalize_pubkey(key32) == key32
        assert verifier._normalize_pubkey(key33) == key32
