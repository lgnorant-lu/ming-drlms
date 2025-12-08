"""Unit tests for Phase 15B: ContactManager."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest


class TestContact:
    """Tests for the Contact dataclass."""

    def test_contact_creation(self) -> None:
        """Contact can be created with valid 32-byte pubkey."""
        from ming_drlms.core.contact_manager import Contact, TrustLevel

        pubkey = secrets.token_bytes(32)
        contact = Contact(pubkey=pubkey, alias="Alice", trust=TrustLevel.VERIFIED)

        assert contact.pubkey == pubkey
        assert contact.alias == "Alice"
        assert contact.trust == TrustLevel.VERIFIED
        assert contact.added_at > 0

    def test_contact_invalid_pubkey_length(self) -> None:
        """Contact raises ValueError for invalid pubkey length."""
        from ming_drlms.core.contact_manager import Contact

        with pytest.raises(ValueError, match="pubkey must be exactly 32 bytes"):
            Contact(pubkey=b"short")

    def test_contact_pubkey_hex(self) -> None:
        """Contact.pubkey_hex returns correct hex string."""
        from ming_drlms.core.contact_manager import Contact

        pubkey = bytes.fromhex("a" * 64)
        contact = Contact(pubkey=pubkey)

        assert contact.pubkey_hex == "a" * 64


class TestContactManagerBasic:
    """Tests for ContactManager basic operations."""

    def test_add_contact(self, tmp_path: Path) -> None:
        """add_contact adds a new contact."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        contact = manager.add_contact(pubkey, alias="Bob", trust=TrustLevel.VERIFIED)

        assert contact.pubkey == pubkey
        assert contact.alias == "Bob"
        assert contact.trust == TrustLevel.VERIFIED
        assert manager.count() == 1

    def test_add_contact_invalid_pubkey(self, tmp_path: Path) -> None:
        """add_contact raises ValueError for invalid pubkey."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")

        with pytest.raises(ValueError, match="pubkey must be exactly 32 bytes"):
            manager.add_contact(b"short")

    def test_add_contact_update_existing(self, tmp_path: Path) -> None:
        """add_contact updates existing contact."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey, alias="Old", trust=TrustLevel.UNVERIFIED)
        contact = manager.add_contact(pubkey, alias="New", trust=TrustLevel.VERIFIED)

        assert contact.alias == "New"
        assert contact.trust == TrustLevel.VERIFIED
        assert manager.count() == 1

    def test_remove_contact(self, tmp_path: Path) -> None:
        """remove_contact removes a contact."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey)
        assert manager.count() == 1

        result = manager.remove_contact(pubkey)
        assert result is True
        assert manager.count() == 0

    def test_remove_contact_not_found(self, tmp_path: Path) -> None:
        """remove_contact returns False if not found."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        result = manager.remove_contact(secrets.token_bytes(32))

        assert result is False

    def test_get_contact(self, tmp_path: Path) -> None:
        """get_contact retrieves a contact by pubkey."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey, alias="Test")
        contact = manager.get_contact(pubkey)

        assert contact is not None
        assert contact.alias == "Test"

    def test_get_contact_not_found(self, tmp_path: Path) -> None:
        """get_contact returns None if not found."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        contact = manager.get_contact(secrets.token_bytes(32))

        assert contact is None

    def test_get_contact_by_alias(self, tmp_path: Path) -> None:
        """get_contact_by_alias finds contact by alias."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey, alias="Alice")
        contact = manager.get_contact_by_alias("alice")  # case-insensitive

        assert contact is not None
        assert contact.pubkey == pubkey

    def test_get_contacts(self, tmp_path: Path) -> None:
        """get_contacts returns all contacts sorted."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")

        manager.add_contact(secrets.token_bytes(32), alias="Zack")
        manager.add_contact(secrets.token_bytes(32), alias="Alice")
        manager.add_contact(secrets.token_bytes(32), alias="Bob")

        contacts = manager.get_contacts()

        assert len(contacts) == 3
        assert contacts[0].alias == "Alice"
        assert contacts[1].alias == "Bob"
        assert contacts[2].alias == "Zack"

    def test_get_contacts_filtered_by_trust(self, tmp_path: Path) -> None:
        """get_contacts filters by trust level."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        manager = ContactManager(tmp_path / "contacts.json")

        manager.add_contact(secrets.token_bytes(32), trust=TrustLevel.VERIFIED)
        manager.add_contact(secrets.token_bytes(32), trust=TrustLevel.UNVERIFIED)
        manager.add_contact(secrets.token_bytes(32), trust=TrustLevel.VERIFIED)

        verified = manager.get_contacts(trust=TrustLevel.VERIFIED)

        assert len(verified) == 2


class TestContactManagerTrust:
    """Tests for trust level management."""

    def test_set_trust(self, tmp_path: Path) -> None:
        """set_trust updates trust level."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey, trust=TrustLevel.UNVERIFIED)
        manager.set_trust(pubkey, TrustLevel.VERIFIED)

        contact = manager.get_contact(pubkey)
        assert contact is not None
        assert contact.trust == TrustLevel.VERIFIED

    def test_set_trust_not_found(self, tmp_path: Path) -> None:
        """set_trust raises ContactError if not found."""
        from ming_drlms.core.contact_manager import (
            ContactManager,
            ContactError,
            TrustLevel,
        )

        manager = ContactManager(tmp_path / "contacts.json")

        with pytest.raises(ContactError, match="Contact not found"):
            manager.set_trust(secrets.token_bytes(32), TrustLevel.VERIFIED)

    def test_is_known(self, tmp_path: Path) -> None:
        """is_known returns True for known contacts."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        assert not manager.is_known(pubkey)
        manager.add_contact(pubkey)
        assert manager.is_known(pubkey)

    def test_is_trusted(self, tmp_path: Path) -> None:
        """is_trusted returns True only for VERIFIED contacts."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey, trust=TrustLevel.UNVERIFIED)
        assert not manager.is_trusted(pubkey)

        manager.set_trust(pubkey, TrustLevel.VERIFIED)
        assert manager.is_trusted(pubkey)

    def test_is_blocked(self, tmp_path: Path) -> None:
        """is_blocked returns True for BLOCKED contacts."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        manager = ContactManager(tmp_path / "contacts.json")
        pubkey = secrets.token_bytes(32)

        manager.add_contact(pubkey, trust=TrustLevel.BLOCKED)
        assert manager.is_blocked(pubkey)


class TestContactManagerPersistence:
    """Tests for contact persistence."""

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        """Contacts are persisted and loaded correctly."""
        from ming_drlms.core.contact_manager import ContactManager, TrustLevel

        path = tmp_path / "contacts.json"
        pubkey = secrets.token_bytes(32)

        # Create and persist
        manager1 = ContactManager(path)
        manager1.add_contact(pubkey, alias="Persistent", trust=TrustLevel.VERIFIED)

        # Load in new manager
        manager2 = ContactManager(path)

        assert manager2.count() == 1
        contact = manager2.get_contact(pubkey)
        assert contact is not None
        assert contact.alias == "Persistent"
        assert contact.trust == TrustLevel.VERIFIED

    def test_corrupted_file_ignored(self, tmp_path: Path) -> None:
        """Corrupted file is silently ignored."""
        from ming_drlms.core.contact_manager import ContactManager

        path = tmp_path / "contacts.json"
        path.write_text("not valid json")

        manager = ContactManager(path)
        assert manager.count() == 0

    def test_clear(self, tmp_path: Path) -> None:
        """clear removes all contacts."""
        from ming_drlms.core.contact_manager import ContactManager

        manager = ContactManager(tmp_path / "contacts.json")
        manager.add_contact(secrets.token_bytes(32))
        manager.add_contact(secrets.token_bytes(32))

        manager.clear()

        assert manager.count() == 0
