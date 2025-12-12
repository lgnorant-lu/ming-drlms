#!/usr/bin/env python3
"""
Test X25519 Private Key Clamping Consistency.

This regression test verifies that identity private keys are properly clamped
according to Signal Protocol requirements. Without proper clamping, signature
verification will fail with INVALID_KEY (-1002) errors.

Run with: python -m pytest tests/python/test_signal_key_clamping.py -v
"""


from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


def clamp_private_key(private_key_bytes: bytes) -> bytes:
    """Apply X25519 bit clamping to private key."""
    clamped = bytearray(private_key_bytes)
    clamped[0] &= 248  # Clear lowest 3 bits
    clamped[31] &= 127  # Clear highest bit
    clamped[31] |= 64  # Set second-highest bit
    return bytes(clamped)


class TestKeyClampingConsistency:
    """Test that identity keys are properly clamped."""

    def test_new_identity_is_clamped(self, tmp_path, monkeypatch):
        """Test that newly created identities have clamped private keys."""
        from ming_drlms.identity.local_identity import LocalIdentityManager

        # Use temp directory for identity
        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        # Create new identity
        manager = LocalIdentityManager()
        identity = manager.create_identity(display_name="TestUser")

        # Verify private key is clamped
        private_bytes = identity.private_key
        clamped = clamp_private_key(private_bytes)

        assert private_bytes == clamped, (
            "Private key is not clamped! "
            f"Original: {private_bytes.hex()}, "
            f"Clamped: {clamped.hex()}"
        )

    def test_clamped_private_derives_correct_public(self, tmp_path, monkeypatch):
        """Test that stored public key matches clamped private key derivation."""
        from ming_drlms.identity.local_identity import LocalIdentityManager

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        manager = LocalIdentityManager()
        identity = manager.create_identity(display_name="TestUser")

        # Derive public from stored private
        priv_obj = X25519PrivateKey.from_private_bytes(identity.private_key)
        derived_public = priv_obj.public_key().public_bytes_raw()

        assert identity.public_key == derived_public, (
            "Public key mismatch! "
            f"Stored: {identity.public_key.hex()}, "
            f"Derived: {derived_public.hex()}"
        )

    def test_clamping_is_idempotent(self):
        """Test that clamping an already-clamped key produces same result."""
        import secrets

        for _ in range(10):
            raw_key = secrets.token_bytes(32)
            clamped_once = clamp_private_key(raw_key)
            clamped_twice = clamp_private_key(clamped_once)

            assert clamped_once == clamped_twice, "Clamping should be idempotent"


class TestOPKSerialization:
    """Test that OPKs have correct format for Signal Protocol."""

    def test_opk_has_type_prefix(self, tmp_path, monkeypatch):
        """Test that generated OPKs have 0x05 type prefix."""
        from ming_drlms.relay.keyserver import OPKManager

        monkeypatch.setenv("MING_DRLMS_CONFIG_DIR", str(tmp_path))

        manager = OPKManager()
        opks = manager.generate_opks(5)

        for opk in opks:
            assert len(opk.public_key) == 33, (
                f"OPK should be 33 bytes, got {len(opk.public_key)}"
            )
            assert opk.public_key[0] == 0x05, (
                f"OPK should have 0x05 prefix, got 0x{opk.public_key[0]:02x}"
            )
