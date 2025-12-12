"""Phase 18A: Manual identity verification utilities.

Provides:
- Fingerprint display and comparison
- QR code generation and scanning
- Verification session management

Manual verification is Level 1 in the trust hierarchy, providing
stronger assurance than TOFU but not requiring external infrastructure.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, TYPE_CHECKING

from .local_identity import generate_fingerprint, format_fingerprint

if TYPE_CHECKING:
    pass

__all__ = [
    "VerificationSession",
    "create_verification_qr_data",
    "parse_verification_qr_data",
    "compare_fingerprints",
    "FingerprintDisplay",
]


@dataclass
class FingerprintDisplay:
    """Helper for displaying fingerprints in various formats."""

    public_key: bytes

    @property
    def fingerprint(self) -> str:
        """Standard 6-group format: 7A3F 9B2C 4E1D 8F5A 2C7B 1D9E"""
        return generate_fingerprint(self.public_key)

    @property
    def compact(self) -> str:
        """Compact format without spaces: 7A3F9B2C4E1D8F5A2C7B1D9E"""
        return self.fingerprint.replace(" ", "")

    @property
    def two_lines(self) -> str:
        """Two-line format for easier reading:
        7A3F 9B2C 4E1D
        8F5A 2C7B 1D9E
        """
        return format_fingerprint(self.fingerprint, "lines")

    @property
    def numeric(self) -> str:
        """Numeric-only format for phone verification.

        Converts hex to decimal groups.
        """
        fp = self.compact
        # Convert each 4-char hex group to 5-digit decimal
        groups = []
        for i in range(0, len(fp), 4):
            hex_group = fp[i : i + 4]
            num = int(hex_group, 16)
            groups.append(f"{num:05d}")
        return " ".join(groups)

    @property
    def emoji(self) -> str:
        """Emoji representation for visual comparison.

        Maps each hex digit to an emoji for easier visual matching.
        """
        emoji_map = {
            "0": "🔴",
            "1": "🟠",
            "2": "🟡",
            "3": "🟢",
            "4": "🔵",
            "5": "🟣",
            "6": "⚫",
            "7": "⚪",
            "8": "🟤",
            "9": "💜",
            "A": "💙",
            "B": "💚",
            "C": "💛",
            "D": "🧡",
            "E": "❤️",
            "F": "🖤",
        }
        fp = self.compact
        return "".join(emoji_map.get(c.upper(), "❓") for c in fp[:12])


def compare_fingerprints(fp1: str, fp2: str) -> bool:
    """Compare two fingerprints for equality.

    Handles different formats (with/without spaces, case insensitive).

    Args:
        fp1: First fingerprint.
        fp2: Second fingerprint.

    Returns:
        True if fingerprints match.
    """
    clean1 = fp1.replace(" ", "").replace("-", "").upper()
    clean2 = fp2.replace(" ", "").replace("-", "").upper()
    return clean1 == clean2


@dataclass
class VerificationSession:
    """Manages a manual verification session between two parties.

    Usage:
        # User A initiates
        session = VerificationSession.create(user_a_pubkey, user_b_pubkey)
        print(f"Compare this code: {session.safety_number}")

        # User B does the same
        session_b = VerificationSession.create(user_b_pubkey, user_a_pubkey)
        # session.safety_number == session_b.safety_number
    """

    local_pubkey: bytes
    remote_pubkey: bytes
    created_at: datetime

    @classmethod
    def create(cls, local_pubkey: bytes, remote_pubkey: bytes) -> "VerificationSession":
        """Create a new verification session."""
        return cls(
            local_pubkey=local_pubkey,
            remote_pubkey=remote_pubkey,
            created_at=datetime.now(),
        )

    @property
    def safety_number(self) -> str:
        """Compute deterministic safety number for this pair.

        The safety number is the same regardless of who is "local" vs "remote",
        making it suitable for out-of-band comparison.

        Format: 12 groups of 5 digits (60 digits total)
        Example: 05765 43298 12847 ...
        """
        # Sort keys to ensure deterministic ordering
        key1, key2 = sorted(
            [
                self._normalize(self.local_pubkey),
                self._normalize(self.remote_pubkey),
            ]
        )

        # Hash concatenation
        combined = key1 + key2
        hash_bytes = hashlib.sha256(combined).digest()

        # Convert to numeric groups
        groups = []
        for i in range(0, 30, 5):  # Use 30 bytes for 12 groups
            if i + 5 <= len(hash_bytes):
                chunk = hash_bytes[i : i + 5]
                # Convert 5 bytes to decimal, mod 100000 for 5 digits
                num = int.from_bytes(chunk, "big") % 100000
                groups.append(f"{num:05d}")

        return " ".join(groups[:12])  # 12 groups

    @property
    def safety_number_display(self) -> str:
        """Safety number formatted for display (3 groups per line)."""
        groups = self.safety_number.split()
        lines = []
        for i in range(0, len(groups), 3):
            lines.append(" ".join(groups[i : i + 3]))
        return "\n".join(lines)

    @property
    def qr_data(self) -> str:
        """Generate data for QR code verification."""
        return create_verification_qr_data(self.local_pubkey)

    def verify_qr(self, scanned_data: str) -> Tuple[bool, Optional[str]]:
        """Verify scanned QR code data.

        Args:
            scanned_data: Data from scanned QR code.

        Returns:
            Tuple of (success, error_message).
        """
        result = parse_verification_qr_data(scanned_data)
        if result is None:
            return False, "Invalid QR code format"

        scanned_pubkey = result

        if self._normalize(scanned_pubkey) == self._normalize(self.remote_pubkey):
            return True, None
        else:
            return False, "Public key mismatch"

    def _normalize(self, key: bytes) -> bytes:
        """Normalize public key (strip type prefix)."""
        if len(key) == 33:
            return key[1:]
        return key


def create_verification_qr_data(public_key: bytes) -> str:
    """Create QR code data for identity verification.

    Format: drlms-verify:v1:<base64_pubkey>:<fingerprint>

    The fingerprint is included for manual verification if QR scanning fails.

    Args:
        public_key: Public key to encode.

    Returns:
        QR code data string.
    """
    # Normalize key
    if len(public_key) == 33:
        public_key = public_key[1:]

    pubkey_b64 = base64.urlsafe_b64encode(public_key).decode().rstrip("=")
    fingerprint = generate_fingerprint(public_key).replace(" ", "")

    return f"drlms-verify:v1:{pubkey_b64}:{fingerprint}"


def parse_verification_qr_data(data: str) -> Optional[bytes]:
    """Parse QR code data and extract public key.

    Args:
        data: QR code data string.

    Returns:
        Public key bytes if valid, None otherwise.
    """
    if not data.startswith("drlms-verify:"):
        return None

    parts = data.split(":")
    if len(parts) < 3:
        return None

    version = parts[1]
    if version != "v1":
        return None

    pubkey_b64 = parts[2]

    # Add padding back
    padding = 4 - (len(pubkey_b64) % 4)
    if padding != 4:
        pubkey_b64 += "=" * padding

    try:
        return base64.urlsafe_b64decode(pubkey_b64)
    except Exception:
        return None


def create_verification_challenge() -> Tuple[str, str]:
    """Create a challenge-response pair for verification.

    Used when QR code isn't available - one party reads challenge,
    other party computes and reads response.

    Returns:
        Tuple of (challenge, expected_response).
    """
    import secrets

    challenge = secrets.token_hex(4).upper()  # 8 hex chars
    response = hashlib.sha256(challenge.encode()).hexdigest()[:8].upper()
    return challenge, response


class VerificationUI:
    """Helper class for building verification UIs.

    Provides formatted output for TUI/CLI verification flows.
    """

    @staticmethod
    def format_safety_number_box(safety_number: str, width: int = 50) -> str:
        """Format safety number in a box for display.

        Args:
            safety_number: Safety number string.
            width: Box width.

        Returns:
            Formatted box string.
        """
        groups = safety_number.split()
        lines = []
        for i in range(0, len(groups), 3):
            lines.append("  ".join(groups[i : i + 3]))

        border = "─" * (width - 2)

        result = [f"┌{border}┐"]
        result.append(f"│{'Safety Number'.center(width - 2)}│")
        result.append(f"├{border}┤")
        for line in lines:
            result.append(f"│{line.center(width - 2)}│")
        result.append(f"└{border}┘")

        return "\n".join(result)

    @staticmethod
    def format_fingerprint_comparison(
        local_fp: str,
        remote_fp: str,
        local_name: str = "Your fingerprint",
        remote_name: str = "Their fingerprint",
    ) -> str:
        """Format fingerprint comparison for display.

        Args:
            local_fp: Local party's fingerprint.
            remote_fp: Remote party's fingerprint.
            local_name: Label for local fingerprint.
            remote_name: Label for remote fingerprint.

        Returns:
            Formatted comparison string.
        """
        match = compare_fingerprints(local_fp, remote_fp)
        status = "✓ MATCH" if match else "✗ MISMATCH"

        lines = [
            f"{local_name}:",
            f"  {format_fingerprint(local_fp, 'lines').replace(chr(10), chr(10) + '  ')}",
            "",
            f"{remote_name}:",
            f"  {format_fingerprint(remote_fp, 'lines').replace(chr(10), chr(10) + '  ')}",
            "",
            f"Status: {status}",
        ]

        return "\n".join(lines)

    @staticmethod
    def format_key_change_warning(
        contact_name: str,
        old_fingerprint: str,
        new_fingerprint: str,
    ) -> str:
        """Format key change warning for display.

        Args:
            contact_name: Name of the contact.
            old_fingerprint: Previous fingerprint.
            new_fingerprint: New fingerprint.

        Returns:
            Formatted warning string.
        """
        return f"""
⚠️  SECURITY WARNING ⚠️

{contact_name}'s identity key has changed!

Possible reasons:
• {contact_name} reinstalled the app or switched devices
• {contact_name}'s account may be compromised
• Someone may be impersonating {contact_name}

Old fingerprint:
  {format_fingerprint(old_fingerprint, "lines").replace(chr(10), chr(10) + "  ")}

New fingerprint:
  {format_fingerprint(new_fingerprint, "lines").replace(chr(10), chr(10) + "  ")}

Recommendation: Contact {contact_name} through another channel to verify.
"""
