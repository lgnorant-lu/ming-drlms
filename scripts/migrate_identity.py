#!/usr/bin/env python3
"""Phase 15.5: Identity Migration Script

This script helps migrate from the old Ed25519-based identity.json storage
to the new LocalKeyStore (e2ee_keys.json) with XEdDSA.

IMPORTANT: Ed25519 and X25519 use different curve representations, so the
old Ed25519 identity CANNOT be directly converted to X25519. Users must
generate a new X25519 identity and notify their contacts of the key change.

Usage:
    python scripts/migrate_identity.py --user <username>
    python scripts/migrate_identity.py --user <username> --force  # Skip confirmation

What this script does:
1. Checks if old identity.json exists
2. Checks if LocalKeyStore already has an identity
3. Offers to generate a new X25519 identity if needed
4. Backs up old identity.json to identity.json.bak
5. Optionally deletes the old identity.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def get_identity_json_path() -> Path:
    """Get the path to the old identity.json file."""
    env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if env_path:
        return Path(env_path).expanduser() / "identity.json"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "DRLMS" / "identity.json"
    return Path.home() / ".drlms" / "identity.json"


def get_keystore_path() -> Path:
    """Get the path to the LocalKeyStore file."""
    env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if env_path:
        return Path(env_path).expanduser() / "e2ee_keys.json"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "ming-drlms" / "e2ee_keys.json"
    return Path.home() / ".drlms" / "e2ee_keys.json"


def load_old_identity(path: Path) -> dict | None:
    """Load the old identity.json file."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"[ERROR] Failed to load identity.json: {e}")
        return None


def check_keystore_identity(username: str) -> bool:
    """Check if LocalKeyStore already has an identity for this user."""
    try:
        from ming_drlms.core.e2ee_store import LocalKeyStore

        ks = LocalKeyStore()
        state = ks.load_state(username)
        return state is not None and state.identity_key is not None
    except Exception:
        return False


def generate_new_identity(username: str) -> bool:
    """Generate a new X25519 identity using Signal Protocol."""
    try:
        from ming_drlms.core.e2ee_store import LocalKeyStore
        from ming_drlms.core.pysignal.context import create_signal_context
        from ming_drlms.core.pysignal.keys import generate_device_keys

        ctx = create_signal_context()
        keys = generate_device_keys(ctx)

        ks = LocalKeyStore()
        ks.store_keys(
            username,
            registration_id=keys.registration_id,
            device_id=keys.device_id,
            identity=keys.identity,
            signed_pre_key=keys.signed_pre_key,
            pre_keys=keys.pre_keys,
        )

        # Get the new public key
        state = ks.load_state(username)
        if state and state.identity_key:
            pub = state.identity_key.public_key
            if len(pub) == 33:
                pub = pub[1:]
            print(f"[OK] New X25519 identity generated for '{username}'")
            print(f"     Public key (hex): {pub.hex()}")
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to generate new identity: {e}")
        return False


def backup_old_identity(path: Path) -> bool:
    """Backup the old identity.json file."""
    backup_path = path.with_suffix(".json.bak")
    try:
        shutil.copy2(path, backup_path)
        print(f"[OK] Backed up identity.json to {backup_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to backup identity.json: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Migrate from Ed25519 identity.json to LocalKeyStore (XEdDSA)"
    )
    parser.add_argument(
        "--user",
        "-u",
        required=True,
        help="Username for the new identity in LocalKeyStore",
    )
    parser.add_argument(
        "--force", "-f", action="store_true", help="Skip confirmation prompts"
    )
    parser.add_argument(
        "--delete-old",
        action="store_true",
        help="Delete the old identity.json after migration",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Phase 15.5 Identity Migration Tool")
    print("=" * 60)
    print()

    # Check old identity
    old_path = get_identity_json_path()
    print(f"[CHECK] Old identity.json path: {old_path}")

    old_identity = load_old_identity(old_path)
    if old_identity:
        old_pubkey = old_identity.get("public_key", "")
        old_alias = old_identity.get("alias", "")
        print("[FOUND] Old Ed25519 identity exists")
        print(f"        Alias: {old_alias or '(none)'}")
        print(
            f"        Public key: {old_pubkey[:32]}..."
            if old_pubkey
            else "        Public key: (none)"
        )
    else:
        print(f"[INFO] No old identity.json found at {old_path}")

    # Check new keystore
    ks_path = get_keystore_path()
    print(f"[CHECK] LocalKeyStore path: {ks_path}")

    has_new_identity = check_keystore_identity(args.user)
    if has_new_identity:
        print(f"[FOUND] LocalKeyStore already has identity for '{args.user}'")

        # Get and display the X25519 public key
        try:
            from ming_drlms.core.e2ee_store import LocalKeyStore

            ks = LocalKeyStore()
            state = ks.load_state(args.user)
            if state and state.identity_key:
                pub = state.identity_key.public_key
                if len(pub) == 33:
                    pub = pub[1:]
                print(f"        X25519 Public key: {pub.hex()[:32]}...")
        except Exception:
            pass
    else:
        print(f"[INFO] No identity found in LocalKeyStore for '{args.user}'")

    print()
    print("-" * 60)
    print("MIGRATION NOTES:")
    print("-" * 60)
    print()
    print("  Ed25519 and X25519 use different curve representations.")
    print("  Your old Ed25519 identity CANNOT be directly converted.")
    print()
    print("  Phase 15.5 requires a new X25519 identity for:")
    print("    - E2EE encryption (ECDH key exchange)")
    print("    - Relay event signing (XEdDSA)")
    print()
    print("  After generating a new identity, you must:")
    print("    1. Notify your contacts of your new public key")
    print("    2. Re-establish E2EE sessions")
    print()
    print("-" * 60)

    if has_new_identity:
        print()
        print("[OK] You already have an X25519 identity in LocalKeyStore.")
        if old_identity:
            print("     The old identity.json can be safely removed.")
            if args.delete_old or args.force:
                backup_old_identity(old_path)
                try:
                    old_path.unlink()
                    print("[OK] Deleted old identity.json")
                except Exception as e:
                    print(f"[WARN] Could not delete identity.json: {e}")
            else:
                print("     Run with --delete-old to remove it after backup.")
        return 0

    # Need to generate new identity
    print()
    if not args.force:
        response = input(f"Generate new X25519 identity for '{args.user}'? [y/N] ")
        if response.lower() not in ("y", "yes"):
            print("[ABORT] Migration cancelled by user")
            return 1

    # Backup old identity if it exists
    if old_identity:
        backup_old_identity(old_path)

    # Generate new identity
    print()
    if generate_new_identity(args.user):
        print()
        print("[SUCCESS] Migration complete!")
        print()
        print("IMPORTANT: Share your new public key with your contacts.")

        if old_identity and (args.delete_old or args.force):
            try:
                old_path.unlink()
                print("[OK] Deleted old identity.json")
            except Exception as e:
                print(f"[WARN] Could not delete identity.json: {e}")

        return 0
    else:
        print("[FAILED] Migration failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
