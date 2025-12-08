"""Phase 15.5: TUI commands for identity management (XEdDSA).

Commands:
    /identity           - Show current identity status
    /identity create    - Create a new X25519 identity
    /identity show      - Show identity details
    /identity export    - Export private key (hex)
    /identity import    - Import from private key
    /identity delete    - Delete identity
    /identity help      - Show help

Note: Phase 15.5 uses X25519 identity stored in LocalKeyStore.
"""

from __future__ import annotations

from typing import Any


def register_identity_commands(handler: Any) -> None:
    """Register identity management commands."""

    def _identity(args: str) -> None:
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "" or subcmd == "show":
            _identity_show()
        elif subcmd == "create":
            _identity_create()
        elif subcmd == "export":
            _identity_export()
        elif subcmd == "import":
            _identity_import(subargs)
        elif subcmd == "delete":
            _identity_delete()
        elif subcmd == "help":
            _identity_help()
        else:
            handler.screen.show_system_message(
                f"Unknown subcommand: {subcmd}. Use /identity help"
            )

    def _identity_show() -> None:
        """Show current identity status."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None:
            handler.screen.show_system_message(
                "[Identity] IdentityManager not initialized"
            )
            return

        if not im.has_identity():
            handler.screen.show_system_message(
                "[Identity] No identity. Use /identity create"
            )
            return

        try:
            pubkey = im.get_pubkey_hex()
            username = getattr(im, "_username", "unknown")
            handler.screen.show_system_message("── Identity (Phase 15.5 XEdDSA) ──")
            handler.screen.show_system_message(f"  User:   {username}")
            handler.screen.show_system_message(f"  Pubkey: {pubkey[:32]}...")
            handler.screen.show_system_message(f"          ...{pubkey[32:]}")
            handler.screen.show_system_message(
                "  Store:  LocalKeyStore (e2ee_keys.json)"
            )
            handler.screen.show_system_message("──────────────────────────────────")
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Error: {e}")

    def _identity_create() -> None:
        """Create a new X25519 identity."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None:
            handler.screen.show_system_message(
                "[Identity] IdentityManager not initialized"
            )
            return

        if im.has_identity():
            handler.screen.show_system_message(
                "[Identity] Identity already exists for this user"
            )
            return

        try:
            # Get username from IdentityManager
            username = getattr(im, "_username", None)
            if not username:
                handler.screen.show_system_message("[Identity] No username configured")
                return

            # Generate new X25519 identity via Signal Protocol
            from ...core.e2ee_store import LocalKeyStore
            from ...core.pysignal.context import create_signal_context
            from ...core.pysignal.keys import generate_device_keys

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

            # Invalidate cache so IdentityManager picks up new keys
            im.invalidate_cache()

            # Get the new public key
            pubkey = im.get_pubkey_hex()
            handler.screen.show_system_message(
                f"[Identity] Created X25519 identity for '{username}'"
            )
            handler.screen.show_system_message(f"[Identity] Pubkey: {pubkey[:32]}...")
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Failed to create: {e}")

    def _identity_export() -> None:
        """Export identity private key."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None or not im.has_identity():
            handler.screen.show_system_message("[Identity] No identity to export")
            return

        try:
            privkey = im.export_identity()
            handler.screen.show_system_message("── Private Key (KEEP SECRET!) ──")
            handler.screen.show_system_message(f"  {privkey.hex()}")
            handler.screen.show_system_message("────────────────────────────────")
            handler.screen.show_system_message(
                "This is your X25519 private key. Store securely!"
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Export failed: {e}")

    def _identity_import(privkey_hex: str) -> None:
        """Import identity from private key."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None:
            handler.screen.show_system_message(
                "[Identity] IdentityManager not initialized"
            )
            return

        if im.has_identity():
            handler.screen.show_system_message(
                "[Identity] Identity already exists. Use /identity delete first"
            )
            return

        privkey_hex = privkey_hex.strip()
        if len(privkey_hex) != 64:
            handler.screen.show_system_message(
                "[Identity] Private key must be 64 hex characters (32 bytes)"
            )
            return

        try:
            privkey = bytes.fromhex(privkey_hex)
        except ValueError as ve:
            handler.screen.show_system_message(f"[Identity] Invalid hex: {ve}")
            return

        try:
            username = getattr(im, "_username", None)
            if not username:
                handler.screen.show_system_message("[Identity] No username configured")
                return

            # Import: use private key to generate full key bundle
            from ...core.e2ee_store import LocalKeyStore, SignalKeyPair
            from ...core.pysignal.context import create_signal_context
            from ...core.pysignal.keys import generate_device_keys

            # Generate other keys (signed_pre_key, pre_keys) with new randomness
            ctx = create_signal_context()
            keys = generate_device_keys(ctx)

            # Replace identity with imported private key
            # Derive public key from private key using curve25519
            from ...core.pysignal.signature import _derive_public_from_private

            pubkey = _derive_public_from_private(ctx, privkey)

            # Create identity with imported private key
            imported_identity = SignalKeyPair(
                private_key=privkey,
                public_key=pubkey,
            )

            ks = LocalKeyStore()
            ks.store_keys(
                username,
                registration_id=keys.registration_id,
                device_id=keys.device_id,
                identity=imported_identity,
                signed_pre_key=keys.signed_pre_key,
                pre_keys=keys.pre_keys,
            )

            im.invalidate_cache()
            pubkey_hex = im.get_pubkey_hex()
            handler.screen.show_system_message(
                f"[Identity] Imported identity for '{username}'"
            )
            handler.screen.show_system_message(
                f"[Identity] Pubkey: {pubkey_hex[:32]}..."
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Import failed: {e}")

    def _identity_delete() -> None:
        """Delete current identity."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None or not im.has_identity():
            handler.screen.show_system_message("[Identity] No identity to delete")
            return

        try:
            username = getattr(im, "_username", None)
            if not username:
                handler.screen.show_system_message("[Identity] No username configured")
                return

            from ...core.e2ee_store import LocalKeyStore

            ks = LocalKeyStore()
            ks.delete_user_state(username)

            im.invalidate_cache()
            handler.screen.show_system_message(
                f"[Identity] Deleted identity for '{username}'"
            )
            handler.screen.show_system_message(
                "[Identity] Use /identity create to make a new one"
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Delete failed: {e}")

    def _identity_help() -> None:
        """Show identity command help."""
        handler.screen.show_system_message("── Identity Commands (Phase 15.5) ──")
        handler.screen.show_system_message(
            "  /identity           - Show current identity"
        )
        handler.screen.show_system_message(
            "  /identity create    - Create new X25519 identity"
        )
        handler.screen.show_system_message(
            "  /identity show      - Show identity details"
        )
        handler.screen.show_system_message(
            "  /identity export    - Export private key (backup)"
        )
        handler.screen.show_system_message(
            "  /identity import <key> - Import from private key"
        )
        handler.screen.show_system_message("  /identity delete    - Delete identity")
        handler.screen.show_system_message("────────────────────────────────────")
        handler.screen.show_system_message(
            "Note: Identity is stored in LocalKeyStore (e2ee_keys.json)."
        )

    handler.commands["/identity"] = _identity
