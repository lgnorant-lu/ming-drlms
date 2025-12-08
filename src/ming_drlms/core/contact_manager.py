"""Phase 15B: Client-side contact management for Nostr-style identity.

This module manages contacts (known public keys) locally:
- Add/remove contacts by public key
- Assign aliases to contacts
- Track trust status (verified, unverified, blocked)
- Verify messages against known contact keys

Design principles:
- Client-side only, no server dependency
- Simple JSON file storage
- Compatible with IdentityManager for signature verification
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import time

__all__ = [
    "Contact",
    "ContactManager",
    "ContactError",
    "TrustLevel",
]


class ContactError(Exception):
    """Base exception for contact management errors."""

    pass


class TrustLevel(Enum):
    """Trust level for a contact."""

    UNKNOWN = "unknown"  # Never seen before
    UNVERIFIED = "unverified"  # Seen but not verified out-of-band
    VERIFIED = "verified"  # Verified via out-of-band channel
    BLOCKED = "blocked"  # Explicitly blocked


@dataclass(slots=True)
class Contact:
    """Represents a known contact with their public key.

    Attributes:
        pubkey: 32-byte Ed25519 public key (stored as hex internally)
        alias: Human-readable name for this contact
        trust: Trust level for this contact
        added_at: Unix timestamp when contact was added
        notes: Optional notes about this contact
    """

    pubkey: bytes
    alias: str = ""
    trust: TrustLevel = TrustLevel.UNVERIFIED
    added_at: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        if len(self.pubkey) != 32:
            raise ValueError("pubkey must be exactly 32 bytes")
        if self.added_at == 0:
            object.__setattr__(self, "added_at", int(time.time()))

    @property
    def pubkey_hex(self) -> str:
        """Get public key as hex string."""
        return self.pubkey.hex()


def _default_contacts_dir() -> Path:
    """Get the default directory for contacts storage."""
    env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
    if env_path:
        return Path(env_path).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "DRLMS"
    return Path.home() / ".config" / "drlms"


def _default_contacts_path() -> Path:
    """Get the default path for contacts.json."""
    return _default_contacts_dir() / "contacts.json"


class ContactManager:
    """Manages known contacts and their public keys.

    This class provides:
    - Adding/removing contacts by public key
    - Assigning aliases and trust levels
    - Looking up contacts by pubkey or alias
    - Persistence to a simple JSON file

    Example usage:
        >>> manager = ContactManager()
        >>> manager.add_contact(pubkey_bytes, alias="Alice", trust=TrustLevel.VERIFIED)
        >>> contact = manager.get_contact(pubkey_bytes)
        >>> contacts = manager.get_contacts()
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        auto_load: bool = True,
    ) -> None:
        """Initialize the contact manager.

        Args:
            path: Path to the contacts.json file. If None, uses default location.
            auto_load: If True, automatically load existing contacts on init.
        """
        self._path = Path(path) if path else _default_contacts_path()
        self._contacts: Dict[str, Contact] = {}  # pubkey_hex -> Contact

        if auto_load:
            self._try_load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_contact(
        self,
        pubkey: bytes,
        *,
        alias: str = "",
        trust: TrustLevel = TrustLevel.UNVERIFIED,
        notes: str = "",
    ) -> Contact:
        """Add a new contact or update existing one.

        Args:
            pubkey: 32-byte Ed25519 public key.
            alias: Human-readable name for this contact.
            trust: Trust level for this contact.
            notes: Optional notes.

        Returns:
            The created or updated Contact.

        Raises:
            ValueError: If pubkey is not 32 bytes.
        """
        if len(pubkey) != 32:
            raise ValueError("pubkey must be exactly 32 bytes")

        pubkey_hex = pubkey.hex()
        existing = self._contacts.get(pubkey_hex)

        if existing:
            # Update existing contact
            contact = Contact(
                pubkey=pubkey,
                alias=alias if alias else existing.alias,
                trust=trust,
                added_at=existing.added_at,
                notes=notes if notes else existing.notes,
            )
        else:
            # Create new contact
            contact = Contact(
                pubkey=pubkey,
                alias=alias,
                trust=trust,
                notes=notes,
            )

        self._contacts[pubkey_hex] = contact
        self._persist()
        return contact

    def remove_contact(self, pubkey: bytes) -> bool:
        """Remove a contact by public key.

        Args:
            pubkey: 32-byte public key of the contact to remove.

        Returns:
            True if contact was removed, False if not found.
        """
        pubkey_hex = pubkey.hex()
        if pubkey_hex in self._contacts:
            del self._contacts[pubkey_hex]
            self._persist()
            return True
        return False

    def get_contact(self, pubkey: bytes) -> Optional[Contact]:
        """Get a contact by public key.

        Args:
            pubkey: 32-byte public key.

        Returns:
            Contact if found, None otherwise.
        """
        return self._contacts.get(pubkey.hex())

    def get_contact_by_alias(self, alias: str) -> Optional[Contact]:
        """Get a contact by alias.

        Args:
            alias: Alias to search for (case-insensitive).

        Returns:
            First matching Contact, or None if not found.
        """
        alias_lower = alias.lower()
        for contact in self._contacts.values():
            if contact.alias.lower() == alias_lower:
                return contact
        return None

    def get_contacts(
        self,
        *,
        trust: Optional[TrustLevel] = None,
    ) -> List[Contact]:
        """Get all contacts, optionally filtered by trust level.

        Args:
            trust: If provided, only return contacts with this trust level.

        Returns:
            List of contacts.
        """
        contacts = list(self._contacts.values())
        if trust is not None:
            contacts = [c for c in contacts if c.trust == trust]
        return sorted(contacts, key=lambda c: (c.alias.lower(), c.pubkey_hex))

    def set_trust(self, pubkey: bytes, trust: TrustLevel) -> None:
        """Update the trust level for a contact.

        Args:
            pubkey: 32-byte public key.
            trust: New trust level.

        Raises:
            ContactError: If contact not found.
        """
        contact = self.get_contact(pubkey)
        if contact is None:
            raise ContactError("Contact not found")

        updated = Contact(
            pubkey=contact.pubkey,
            alias=contact.alias,
            trust=trust,
            added_at=contact.added_at,
            notes=contact.notes,
        )
        self._contacts[pubkey.hex()] = updated
        self._persist()

    def set_alias(self, pubkey: bytes, alias: str) -> None:
        """Update the alias for a contact.

        Args:
            pubkey: 32-byte public key.
            alias: New alias.

        Raises:
            ContactError: If contact not found.
        """
        contact = self.get_contact(pubkey)
        if contact is None:
            raise ContactError("Contact not found")

        updated = Contact(
            pubkey=contact.pubkey,
            alias=alias,
            trust=contact.trust,
            added_at=contact.added_at,
            notes=contact.notes,
        )
        self._contacts[pubkey.hex()] = updated
        self._persist()

    def is_known(self, pubkey: bytes) -> bool:
        """Check if a public key is known (in contacts).

        Args:
            pubkey: 32-byte public key.

        Returns:
            True if the pubkey is in contacts.
        """
        return pubkey.hex() in self._contacts

    def is_trusted(self, pubkey: bytes) -> bool:
        """Check if a public key is trusted (verified).

        Args:
            pubkey: 32-byte public key.

        Returns:
            True if the pubkey is in contacts with VERIFIED trust level.
        """
        contact = self.get_contact(pubkey)
        return contact is not None and contact.trust == TrustLevel.VERIFIED

    def is_blocked(self, pubkey: bytes) -> bool:
        """Check if a public key is blocked.

        Args:
            pubkey: 32-byte public key.

        Returns:
            True if the pubkey is in contacts with BLOCKED trust level.
        """
        contact = self.get_contact(pubkey)
        return contact is not None and contact.trust == TrustLevel.BLOCKED

    def count(self) -> int:
        """Get the total number of contacts."""
        return len(self._contacts)

    def clear(self) -> None:
        """Remove all contacts."""
        self._contacts.clear()
        self._persist()

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _try_load(self) -> None:
        """Try to load contacts from file, silently ignore if not found."""
        if not self._path.exists():
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            return

        contacts_list = data.get("contacts", [])
        if not isinstance(contacts_list, list):
            return

        for entry in contacts_list:
            if not isinstance(entry, dict):
                continue
            try:
                pubkey_hex = entry.get("pubkey", "")
                pubkey = bytes.fromhex(pubkey_hex)
                if len(pubkey) != 32:
                    continue

                trust_str = entry.get("trust", "unverified")
                try:
                    trust = TrustLevel(trust_str)
                except ValueError:
                    trust = TrustLevel.UNVERIFIED

                contact = Contact(
                    pubkey=pubkey,
                    alias=str(entry.get("alias", "")),
                    trust=trust,
                    added_at=int(entry.get("added_at", 0)),
                    notes=str(entry.get("notes", "")),
                )
                self._contacts[pubkey_hex] = contact
            except Exception:
                continue

    def _persist(self) -> None:
        """Persist contacts to file."""
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)

        contacts_list = []
        for contact in self._contacts.values():
            contacts_list.append(
                {
                    "pubkey": contact.pubkey_hex,
                    "alias": contact.alias,
                    "trust": contact.trust.value,
                    "added_at": contact.added_at,
                    "notes": contact.notes,
                }
            )

        data = {"contacts": contacts_list}

        # Write atomically via temp file
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._path)

    @property
    def path(self) -> Path:
        """Get the path to the contacts file."""
        return self._path
