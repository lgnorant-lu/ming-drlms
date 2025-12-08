"""Phase 15A: TUI commands for identity management.

Commands:
    /identity           - Show current identity status
    /identity create    - Create a new identity
    /identity show      - Show identity details
    /identity export    - Export identity seed (hex)
    /identity import    - Import identity from seed
    /identity delete    - Delete current identity
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
            _identity_create(subargs)
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
            alias = im.get_alias() or "(no alias)"
            handler.screen.show_system_message("── Identity ──")
            handler.screen.show_system_message(f"  Alias:  {alias}")
            handler.screen.show_system_message(f"  Pubkey: {pubkey[:32]}...")
            handler.screen.show_system_message(f"          ...{pubkey[32:]}")
            handler.screen.show_system_message(f"  Path:   {im.path}")
            handler.screen.show_system_message("──────────────")
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Error: {e}")

    def _identity_create(alias: str) -> None:
        """Create a new identity."""
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

        try:
            identity = im.create_identity(alias=alias.strip())
            handler.screen.show_system_message(
                f"[Identity] Created! Pubkey: {identity.public_key.hex()[:32]}..."
            )
            if alias.strip():
                handler.screen.show_system_message(f"[Identity] Alias: {alias.strip()}")
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Failed to create: {e}")

    def _identity_export() -> None:
        """Export identity seed."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None or not im.has_identity():
            handler.screen.show_system_message("[Identity] No identity to export")
            return

        try:
            seed = im.export_identity()
            handler.screen.show_system_message("── Identity Seed (KEEP SECRET!) ──")
            handler.screen.show_system_message(f"  {seed.hex()}")
            handler.screen.show_system_message("──────────────────────────────────")
            handler.screen.show_system_message(
                "Use this 64-char hex to restore with /identity import <seed>"
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Export failed: {e}")

    def _identity_import(seed_hex: str) -> None:
        """Import identity from seed."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None:
            handler.screen.show_system_message(
                "[Identity] IdentityManager not initialized"
            )
            return

        if im.has_identity():
            handler.screen.show_system_message(
                "[Identity] Identity exists. Use /identity delete first"
            )
            return

        seed_hex = seed_hex.strip()
        if len(seed_hex) != 64:
            handler.screen.show_system_message(
                "[Identity] Seed must be 64 hex characters (32 bytes)"
            )
            return

        try:
            seed = bytes.fromhex(seed_hex)
            identity = im.import_identity(seed)
            handler.screen.show_system_message(
                f"[Identity] Imported! Pubkey: {identity.public_key.hex()[:32]}..."
            )
        except ValueError as ve:
            handler.screen.show_system_message(f"[Identity] Invalid hex: {ve}")
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Import failed: {e}")

    def _identity_delete() -> None:
        """Delete current identity."""
        im = getattr(handler.controller, "_identity_manager", None)
        if im is None or not im.has_identity():
            handler.screen.show_system_message("[Identity] No identity to delete")
            return

        try:
            im.delete_identity()
            handler.screen.show_system_message(
                "[Identity] Deleted. Use /identity create to make a new one"
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Identity] Delete failed: {e}")

    def _identity_help() -> None:
        """Show identity command help."""
        handler.screen.show_system_message("── Identity Commands ──")
        handler.screen.show_system_message(
            "  /identity           - Show current identity"
        )
        handler.screen.show_system_message(
            "  /identity create [alias] - Create new identity"
        )
        handler.screen.show_system_message(
            "  /identity show      - Show identity details"
        )
        handler.screen.show_system_message(
            "  /identity export    - Export seed (backup)"
        )
        handler.screen.show_system_message(
            "  /identity import <seed> - Import from seed"
        )
        handler.screen.show_system_message("  /identity delete    - Delete identity")
        handler.screen.show_system_message("───────────────────────")

    handler.commands["/identity"] = _identity
