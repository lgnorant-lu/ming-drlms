"""Phase 15B: TUI commands for contact management.

Commands:
    /contacts         - List all contacts
    /contacts add <pubkey> [alias] - Add contact manually
    /contacts trust <pubkey>       - Mark contact as trusted
    /contacts block <pubkey>       - Block a contact
    /contacts remove <pubkey>      - Remove a contact
"""

from __future__ import annotations

from typing import Any


def register_contact_commands(handler: Any) -> None:
    """Register contact management commands."""

    def _contacts(args: str) -> None:
        parts = args.strip().split(maxsplit=2)
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "" or subcmd == "list":
            _contacts_list()
        elif subcmd == "add":
            # /contacts add <pubkey> [alias]
            if len(parts) < 2:
                handler.screen.show_system_message(
                    "Usage: /contacts add <pubkey_hex> [alias]"
                )
                return
            pubkey_hex = parts[1]
            alias = parts[2] if len(parts) > 2 else ""
            _contacts_add(pubkey_hex, alias)
        elif subcmd == "trust":
            if len(parts) < 2:
                handler.screen.show_system_message(
                    "Usage: /contacts trust <pubkey_hex>"
                )
                return
            _contacts_trust(parts[1])
        elif subcmd == "block":
            if len(parts) < 2:
                handler.screen.show_system_message(
                    "Usage: /contacts block <pubkey_hex>"
                )
                return
            _contacts_block(parts[1])
        elif subcmd == "remove":
            if len(parts) < 2:
                handler.screen.show_system_message(
                    "Usage: /contacts remove <pubkey_hex>"
                )
                return
            _contacts_remove(parts[1])
        elif subcmd == "help":
            _contacts_help()
        else:
            handler.screen.show_system_message(
                f"Unknown subcommand: {subcmd}. Use /contacts help"
            )

    def _contacts_list() -> None:
        """List all contacts."""
        cm = getattr(handler.controller, "_contact_manager", None)
        if cm is None:
            handler.screen.show_system_message(
                "[Contacts] ContactManager not initialized"
            )
            return

        contacts = cm.get_contacts()
        if not contacts:
            handler.screen.show_system_message("[Contacts] No contacts yet")
            return

        handler.screen.show_system_message(f"── Contacts ({len(contacts)}) ──")
        for c in contacts:
            trust_icon = {
                "verified": "✓",
                "unverified": "?",
                "blocked": "✗",
                "unknown": "·",
            }.get(c.trust.value, "·")
            alias = c.alias or "(no alias)"
            handler.screen.show_system_message(
                f"  [{trust_icon}] {alias}: {c.pubkey_hex[:24]}..."
            )
        handler.screen.show_system_message("─────────────────────")

    def _contacts_add(pubkey_hex: str, alias: str) -> None:
        """Add a contact manually."""
        cm = getattr(handler.controller, "_contact_manager", None)
        if cm is None:
            handler.screen.show_system_message(
                "[Contacts] ContactManager not initialized"
            )
            return

        pubkey_hex = pubkey_hex.strip()
        if len(pubkey_hex) != 64:
            handler.screen.show_system_message(
                "[Contacts] Pubkey must be 64 hex characters"
            )
            return

        try:
            from ming_drlms.core.contact_manager import TrustLevel

            pubkey = bytes.fromhex(pubkey_hex)
            cm.add_contact(pubkey, alias=alias.strip(), trust=TrustLevel.UNVERIFIED)
            handler.screen.show_system_message(
                f"[Contacts] Added: {pubkey_hex[:24]}... alias={alias or '(none)'}"
            )
        except ValueError as ve:
            handler.screen.show_system_message(f"[Contacts] Invalid hex: {ve}")
        except Exception as e:
            handler.screen.show_system_message(f"[Contacts] Failed: {e}")

    def _contacts_trust(pubkey_hex: str) -> None:
        """Mark contact as trusted."""
        cm = getattr(handler.controller, "_contact_manager", None)
        if cm is None:
            handler.screen.show_system_message(
                "[Contacts] ContactManager not initialized"
            )
            return

        try:
            from ming_drlms.core.contact_manager import TrustLevel

            pubkey = bytes.fromhex(pubkey_hex.strip())
            cm.set_trust(pubkey, TrustLevel.VERIFIED)
            handler.screen.show_system_message(
                f"[Contacts] Marked as VERIFIED: {pubkey_hex[:24]}..."
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Contacts] Failed: {e}")

    def _contacts_block(pubkey_hex: str) -> None:
        """Block a contact."""
        cm = getattr(handler.controller, "_contact_manager", None)
        if cm is None:
            handler.screen.show_system_message(
                "[Contacts] ContactManager not initialized"
            )
            return

        try:
            from ming_drlms.core.contact_manager import TrustLevel

            pubkey = bytes.fromhex(pubkey_hex.strip())
            cm.set_trust(pubkey, TrustLevel.BLOCKED)
            handler.screen.show_system_message(
                f"[Contacts] BLOCKED: {pubkey_hex[:24]}..."
            )
        except Exception as e:
            handler.screen.show_system_message(f"[Contacts] Failed: {e}")

    def _contacts_remove(pubkey_hex: str) -> None:
        """Remove a contact."""
        cm = getattr(handler.controller, "_contact_manager", None)
        if cm is None:
            handler.screen.show_system_message(
                "[Contacts] ContactManager not initialized"
            )
            return

        try:
            pubkey = bytes.fromhex(pubkey_hex.strip())
            if cm.remove_contact(pubkey):
                handler.screen.show_system_message(
                    f"[Contacts] Removed: {pubkey_hex[:24]}..."
                )
            else:
                handler.screen.show_system_message("[Contacts] Contact not found")
        except Exception as e:
            handler.screen.show_system_message(f"[Contacts] Failed: {e}")

    def _contacts_help() -> None:
        """Show contacts command help."""
        handler.screen.show_system_message("── Contacts Commands ──")
        handler.screen.show_system_message("  /contacts           - List all contacts")
        handler.screen.show_system_message("  /contacts add <pk> [alias] - Add contact")
        handler.screen.show_system_message(
            "  /contacts trust <pk>       - Mark verified"
        )
        handler.screen.show_system_message(
            "  /contacts block <pk>       - Block contact"
        )
        handler.screen.show_system_message(
            "  /contacts remove <pk>      - Remove contact"
        )
        handler.screen.show_system_message("────────────────────────")

    handler.commands["/contacts"] = _contacts
