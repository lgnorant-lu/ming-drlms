"""Phase 18A: Trust store for multi-level identity verification.

Trust Levels (from lowest to highest):
- Level 0: TOFU (Trust On First Use) - Default, first contact
- Level 1: MANUAL - Verified via fingerprint comparison or QR scan
- Level 2: SOCIAL - Vouched by N trusted contacts (Web of Trust)
- Level 3: ANCHORED - Verified via external anchors (DNS/HTTPS/GitHub)

Key change detection and warning is also handled here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Callable, Dict, List, Optional

__all__ = [
    "TrustLevel",
    "TrustRecord",
    "KeyChangeEvent",
    "TrustStore",
    "KeyChangePolicy",
]


class TrustLevel(IntEnum):
    """Trust level hierarchy."""

    UNKNOWN = -1  # Never seen before
    TOFU = 0  # Trust On First Use (default)
    MANUAL = 1  # Manually verified (fingerprint/QR)
    SOCIAL = 2  # Socially vouched (Web of Trust)
    ANCHORED = 3  # Externally anchored (DNS/HTTPS/GitHub)


class KeyChangePolicy(IntEnum):
    """Policy for handling public key changes."""

    WARN = 0  # Warn but allow communication
    BLOCK = 1  # Block until manually accepted
    RESET = 2  # Reset trust to TOFU automatically


@dataclass
class KeyChangeEvent:
    """Record of a public key change."""

    old_key: bytes
    new_key: bytes
    changed_at: datetime
    accepted: bool = False
    accepted_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "old_key": self.old_key.hex(),
            "new_key": self.new_key.hex(),
            "changed_at": self.changed_at.isoformat(),
            "accepted": self.accepted,
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "KeyChangeEvent":
        return cls(
            old_key=bytes.fromhex(data["old_key"]),
            new_key=bytes.fromhex(data["new_key"]),
            changed_at=datetime.fromisoformat(data["changed_at"]),
            accepted=data.get("accepted", False),
            accepted_at=datetime.fromisoformat(data["accepted_at"])
            if data.get("accepted_at")
            else None,
        )


@dataclass
class VerificationRecord:
    """Record of a verification event."""

    method: str  # "manual", "dns", "https", "github", "social"
    details: str  # e.g., "alice.example.com" for DNS
    verified_at: datetime
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "method": self.method,
            "details": self.details,
            "verified_at": self.verified_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "VerificationRecord":
        return cls(
            method=data["method"],
            details=data["details"],
            verified_at=datetime.fromisoformat(data["verified_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


@dataclass
class TrustRecord:
    """Trust record for a contact."""

    # Identity
    public_key: bytes
    display_name: str = ""

    # Trust level
    trust_level: TrustLevel = TrustLevel.TOFU

    # Verification history
    verifications: List[VerificationRecord] = field(default_factory=list)

    # Key change history
    key_history: List[KeyChangeEvent] = field(default_factory=list)

    # Timestamps
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)

    # Blocking status
    blocked: bool = False
    blocked_reason: str = ""

    @property
    def fingerprint(self) -> str:
        """Get fingerprint of this contact's public key."""
        from .local_identity import generate_fingerprint

        return generate_fingerprint(self.public_key)

    @property
    def public_key_hex(self) -> str:
        """Get public key as hex string."""
        key = self.public_key
        if len(key) == 33:
            key = key[1:]
        return key.hex()

    def add_verification(
        self,
        method: str,
        details: str,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Add a verification record and update trust level."""
        record = VerificationRecord(
            method=method,
            details=details,
            verified_at=datetime.now(),
            expires_at=expires_at,
        )
        self.verifications.append(record)

        # Update trust level based on method
        method_levels = {
            "manual": TrustLevel.MANUAL,
            "social": TrustLevel.SOCIAL,
            "dns": TrustLevel.ANCHORED,
            "https": TrustLevel.ANCHORED,
            "github": TrustLevel.ANCHORED,
        }

        new_level = method_levels.get(method, TrustLevel.TOFU)
        if new_level > self.trust_level:
            self.trust_level = new_level

    def record_key_change(self, new_key: bytes) -> KeyChangeEvent:
        """Record a public key change event."""
        event = KeyChangeEvent(
            old_key=self.public_key,
            new_key=new_key,
            changed_at=datetime.now(),
        )
        self.key_history.append(event)

        # Reset trust level
        self.trust_level = TrustLevel.TOFU
        self.verifications.clear()

        # Update public key
        self.public_key = new_key

        return event

    def accept_key_change(self) -> None:
        """Accept the most recent key change."""
        if self.key_history:
            self.key_history[-1].accepted = True
            self.key_history[-1].accepted_at = datetime.now()

    def to_dict(self) -> Dict:
        return {
            "public_key": self.public_key.hex(),
            "display_name": self.display_name,
            "trust_level": self.trust_level.value,
            "verifications": [v.to_dict() for v in self.verifications],
            "key_history": [k.to_dict() for k in self.key_history],
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "TrustRecord":
        return cls(
            public_key=bytes.fromhex(data["public_key"]),
            display_name=data.get("display_name", ""),
            trust_level=TrustLevel(data.get("trust_level", 0)),
            verifications=[
                VerificationRecord.from_dict(v) for v in data.get("verifications", [])
            ],
            key_history=[
                KeyChangeEvent.from_dict(k) for k in data.get("key_history", [])
            ],
            first_seen=datetime.fromisoformat(data["first_seen"])
            if "first_seen" in data
            else datetime.now(),
            last_seen=datetime.fromisoformat(data["last_seen"])
            if "last_seen" in data
            else datetime.now(),
            blocked=data.get("blocked", False),
            blocked_reason=data.get("blocked_reason", ""),
        )


class TrustStore:
    """Persistent storage for contact trust records.

    Example:
        >>> store = TrustStore()
        >>> store.record_contact(pubkey, display_name="Alice")
        >>> store.verify_manual(pubkey)
        >>> print(store.get_trust_level(pubkey))
        TrustLevel.MANUAL
    """

    DEFAULT_FILENAME = "trust_store.json"

    def __init__(
        self,
        store_path: Optional[Path] = None,
        key_change_policy: KeyChangePolicy = KeyChangePolicy.WARN,
    ) -> None:
        """Initialize trust store.

        Args:
            store_path: Path to store file. If None, uses default.
            key_change_policy: Policy for handling key changes.
        """
        self._store_path = store_path or self._default_store_path()
        self._key_change_policy = key_change_policy
        self._records: Dict[str, TrustRecord] = {}  # fingerprint -> record
        self._key_change_callbacks: List[
            Callable[[TrustRecord, KeyChangeEvent], None]
        ] = []

        self._load()

    @staticmethod
    def _default_store_path() -> Path:
        """Get default store path."""
        env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
        if env_path:
            return Path(env_path).expanduser() / TrustStore.DEFAULT_FILENAME
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / "ming-drlms" / TrustStore.DEFAULT_FILENAME
        return Path.home() / ".config" / "ming-drlms" / TrustStore.DEFAULT_FILENAME

    def _fingerprint(self, public_key: bytes) -> str:
        """Compute fingerprint for indexing."""
        from .local_identity import generate_fingerprint

        return generate_fingerprint(public_key).replace(" ", "")

    def _load(self) -> None:
        """Load records from disk."""
        if not self._store_path.exists():
            return

        try:
            data = json.loads(self._store_path.read_text())
            for fp, record_data in data.get("records", {}).items():
                self._records[fp] = TrustRecord.from_dict(record_data)
        except Exception:
            # Corrupted file, start fresh
            self._records = {}

    def _save(self) -> None:
        """Save records to disk."""
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "records": {fp: r.to_dict() for fp, r in self._records.items()},
        }
        self._store_path.write_text(json.dumps(data, indent=2))

    def on_key_change(
        self,
        callback: Callable[[TrustRecord, KeyChangeEvent], None],
    ) -> None:
        """Register callback for key change events.

        Args:
            callback: Function to call when key change detected.
        """
        self._key_change_callbacks.append(callback)

    def record_contact(
        self,
        public_key: bytes,
        display_name: str = "",
    ) -> TrustRecord:
        """Record first contact with a public key (TOFU).

        If already known, checks for key changes.

        Args:
            public_key: Contact's public key.
            display_name: Optional display name.

        Returns:
            TrustRecord for this contact.
        """
        fp = self._fingerprint(public_key)

        # Check if we know this fingerprint
        if fp in self._records:
            record = self._records[fp]
            record.last_seen = datetime.now()

            # Check for key change (same fingerprint but different raw key - shouldn't happen)
            if record.public_key != public_key:
                # This indicates a hash collision or corrupted data
                event = record.record_key_change(public_key)
                for callback in self._key_change_callbacks:
                    callback(record, event)

            self._save()
            return record

        # New contact - TOFU
        record = TrustRecord(
            public_key=public_key,
            display_name=display_name,
            trust_level=TrustLevel.TOFU,
            first_seen=datetime.now(),
            last_seen=datetime.now(),
        )
        self._records[fp] = record
        self._save()
        return record

    def update_key(
        self,
        old_key: bytes,
        new_key: bytes,
    ) -> Optional[KeyChangeEvent]:
        """Handle a public key update for a known contact.

        Args:
            old_key: Previous public key.
            new_key: New public key.

        Returns:
            KeyChangeEvent if key was updated, None if unknown contact.
        """
        old_fp = self._fingerprint(old_key)

        if old_fp not in self._records:
            return None

        record = self._records[old_fp]
        event = record.record_key_change(new_key)

        # Re-index with new fingerprint
        new_fp = self._fingerprint(new_key)
        del self._records[old_fp]
        self._records[new_fp] = record

        # Notify callbacks
        for callback in self._key_change_callbacks:
            callback(record, event)

        self._save()
        return event

    def get_record(self, public_key: bytes) -> Optional[TrustRecord]:
        """Get trust record for a public key.

        Args:
            public_key: Contact's public key.

        Returns:
            TrustRecord if known, None otherwise.
        """
        fp = self._fingerprint(public_key)
        return self._records.get(fp)

    def get_trust_level(self, public_key: bytes) -> TrustLevel:
        """Get trust level for a public key.

        Args:
            public_key: Contact's public key.

        Returns:
            TrustLevel (UNKNOWN if not in store).
        """
        record = self.get_record(public_key)
        if record is None:
            return TrustLevel.UNKNOWN
        return record.trust_level

    def verify_manual(self, public_key: bytes) -> TrustRecord:
        """Mark contact as manually verified (fingerprint/QR).

        Args:
            public_key: Contact's public key.

        Returns:
            Updated TrustRecord.
        """
        record = self.get_record(public_key)
        if record is None:
            record = self.record_contact(public_key)

        record.add_verification("manual", "fingerprint comparison")
        self._save()
        return record

    def verify_anchor(
        self,
        public_key: bytes,
        anchor_type: str,
        anchor_details: str,
        expires_at: Optional[datetime] = None,
    ) -> TrustRecord:
        """Mark contact as verified via external anchor.

        Args:
            public_key: Contact's public key.
            anchor_type: "dns", "https", or "github".
            anchor_details: The anchor identifier (domain, URL, username).
            expires_at: Optional expiration for this verification.

        Returns:
            Updated TrustRecord.
        """
        record = self.get_record(public_key)
        if record is None:
            record = self.record_contact(public_key)

        record.add_verification(anchor_type, anchor_details, expires_at)
        self._save()
        return record

    def verify_social(
        self,
        public_key: bytes,
        voucher_keys: List[bytes],
    ) -> TrustRecord:
        """Mark contact as socially verified (vouched by trusted contacts).

        Args:
            public_key: Contact's public key.
            voucher_keys: List of vouching contacts' public keys.

        Returns:
            Updated TrustRecord.
        """
        record = self.get_record(public_key)
        if record is None:
            record = self.record_contact(public_key)

        # Verify vouchers are trusted
        trusted_vouchers = [
            k for k in voucher_keys if self.get_trust_level(k) >= TrustLevel.MANUAL
        ]

        if len(trusted_vouchers) >= 2:  # Require at least 2 trusted vouchers
            voucher_fps = [self._fingerprint(k)[:8] for k in trusted_vouchers]
            record.add_verification("social", f"vouched by {', '.join(voucher_fps)}")

        self._save()
        return record

    def block_contact(self, public_key: bytes, reason: str = "") -> TrustRecord:
        """Block a contact.

        Args:
            public_key: Contact's public key.
            reason: Optional reason for blocking.

        Returns:
            Updated TrustRecord.
        """
        record = self.get_record(public_key)
        if record is None:
            record = self.record_contact(public_key)

        record.blocked = True
        record.blocked_reason = reason
        self._save()
        return record

    def unblock_contact(self, public_key: bytes) -> TrustRecord:
        """Unblock a contact.

        Args:
            public_key: Contact's public key.

        Returns:
            Updated TrustRecord.
        """
        record = self.get_record(public_key)
        if record is None:
            record = self.record_contact(public_key)

        record.blocked = False
        record.blocked_reason = ""
        self._save()
        return record

    def is_blocked(self, public_key: bytes) -> bool:
        """Check if a contact is blocked.

        Args:
            public_key: Contact's public key.

        Returns:
            True if blocked.
        """
        record = self.get_record(public_key)
        return record is not None and record.blocked

    def accept_key_change(self, public_key: bytes) -> bool:
        """Accept a pending key change.

        Args:
            public_key: Contact's current public key.

        Returns:
            True if key change was pending and accepted.
        """
        record = self.get_record(public_key)
        if record is None:
            return False

        if record.key_history and not record.key_history[-1].accepted:
            record.accept_key_change()
            self._save()
            return True

        return False

    def has_pending_key_change(self, public_key: bytes) -> bool:
        """Check if contact has unaccepted key change.

        Args:
            public_key: Contact's public key.

        Returns:
            True if there's a pending key change.
        """
        record = self.get_record(public_key)
        if record is None:
            return False

        return bool(record.key_history) and not record.key_history[-1].accepted

    def list_contacts(
        self,
        min_trust: TrustLevel = TrustLevel.UNKNOWN,
        include_blocked: bool = False,
    ) -> List[TrustRecord]:
        """List all known contacts.

        Args:
            min_trust: Minimum trust level to include.
            include_blocked: Whether to include blocked contacts.

        Returns:
            List of TrustRecords.
        """
        results = []
        for record in self._records.values():
            if record.trust_level < min_trust:
                continue
            if record.blocked and not include_blocked:
                continue
            results.append(record)

        return sorted(results, key=lambda r: (-r.trust_level, r.display_name))

    def revoke_trust(self, public_key: bytes) -> TrustRecord:
        """Revoke all verifications and reset to TOFU.

        Args:
            public_key: Contact's public key.

        Returns:
            Updated TrustRecord.
        """
        record = self.get_record(public_key)
        if record is None:
            record = self.record_contact(public_key)

        record.trust_level = TrustLevel.TOFU
        record.verifications.clear()
        self._save()
        return record

    def delete_contact(self, public_key: bytes) -> bool:
        """Remove a contact from the store.

        Args:
            public_key: Contact's public key.

        Returns:
            True if contact was found and removed.
        """
        fp = self._fingerprint(public_key)
        if fp in self._records:
            del self._records[fp]
            self._save()
            return True
        return False
