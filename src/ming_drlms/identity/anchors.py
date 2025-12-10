"""Phase 18A: External identity anchoring verification.

Supported anchor types:
- DNS TXT: _drlms.domain.com TXT "v=drlms1; pubkey=base64(...)"
- HTTPS Well-Known: https://domain.com/.well-known/drlms.json
- GitHub: Public gist or repo file containing identity declaration

All verifiers follow the same pattern:
1. Fetch the anchor data from external source
2. Parse and extract the declared public key
3. Compare with the claimed public key
4. Return verification result
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

__all__ = [
    "AnchorVerifier",
    "AnchorResult",
    "DNSAnchorVerifier",
    "HTTPSAnchorVerifier",
    "GitHubAnchorVerifier",
    "verify_anchor",
    "AnchorError",
]


class AnchorError(Exception):
    """Error during anchor verification."""

    pass


@dataclass
class AnchorResult:
    """Result of anchor verification."""

    success: bool
    anchor_type: str  # "dns", "https", "github"
    anchor_id: str  # domain, URL, or github user
    declared_pubkey: Optional[bytes] = None
    error: Optional[str] = None
    verified_at: datetime = None
    expires_at: Optional[datetime] = None
    raw_response: Optional[str] = None

    def __post_init__(self):
        if self.verified_at is None:
            self.verified_at = datetime.now()


class AnchorVerifier(ABC):
    """Base class for anchor verifiers."""

    TIMEOUT = 10  # seconds

    @property
    @abstractmethod
    def anchor_type(self) -> str:
        """Return anchor type identifier."""
        pass

    @abstractmethod
    def verify(self, anchor_id: str, expected_pubkey: bytes) -> AnchorResult:
        """Verify anchor against expected public key.

        Args:
            anchor_id: Anchor identifier (domain, URL, username).
            expected_pubkey: Expected public key (32 or 33 bytes).

        Returns:
            AnchorResult with verification status.
        """
        pass

    def _normalize_pubkey(self, key: bytes) -> bytes:
        """Normalize public key to 32 bytes (strip type prefix)."""
        if len(key) == 33:
            return key[1:]
        return key

    def _compare_keys(self, declared: bytes, expected: bytes) -> bool:
        """Compare two public keys (handles type prefix)."""
        return self._normalize_pubkey(declared) == self._normalize_pubkey(expected)


class DNSAnchorVerifier(AnchorVerifier):
    """Verify identity via DNS TXT record.

    Expected format:
        _drlms.example.com TXT "v=drlms1; pubkey=<base64 or hex>"

    Example:
        >>> verifier = DNSAnchorVerifier()
        >>> result = verifier.verify("example.com", expected_pubkey)
        >>> print(result.success)
    """

    @property
    def anchor_type(self) -> str:
        return "dns"

    def verify(self, domain: str, expected_pubkey: bytes) -> AnchorResult:
        """Verify DNS TXT anchor.

        Args:
            domain: Domain to check (without _drlms prefix).
            expected_pubkey: Expected public key.

        Returns:
            AnchorResult.
        """
        record_name = f"_drlms.{domain}"

        try:
            # Use system DNS resolver

            try:
                # Try using dnspython if available
                import dns.resolver

                answers = dns.resolver.resolve(record_name, "TXT")
                txt_records = [str(rdata).strip('"') for rdata in answers]
            except ImportError:
                # Fallback: use nslookup/dig via subprocess
                txt_records = self._query_dns_fallback(record_name)

            # Parse TXT records
            for record in txt_records:
                pubkey = self._parse_drlms_txt(record)
                if pubkey:
                    if self._compare_keys(pubkey, expected_pubkey):
                        return AnchorResult(
                            success=True,
                            anchor_type=self.anchor_type,
                            anchor_id=domain,
                            declared_pubkey=pubkey,
                            raw_response=record,
                        )
                    else:
                        return AnchorResult(
                            success=False,
                            anchor_type=self.anchor_type,
                            anchor_id=domain,
                            declared_pubkey=pubkey,
                            error="Public key mismatch",
                            raw_response=record,
                        )

            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=domain,
                error=f"No valid DRLMS TXT record found at {record_name}",
            )

        except Exception as e:
            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=domain,
                error=f"DNS query failed: {e}",
            )

    def _query_dns_fallback(self, record_name: str) -> List[str]:
        """Query DNS using system tools (fallback when dnspython unavailable)."""
        import subprocess
        import shutil

        # Try nslookup first (Windows)
        nslookup = shutil.which("nslookup")
        if nslookup:
            try:
                result = subprocess.run(
                    ["nslookup", "-type=TXT", record_name],
                    capture_output=True,
                    text=True,
                    timeout=self.TIMEOUT,
                )
                # Parse nslookup output
                records = []
                for line in result.stdout.split("\n"):
                    if "text =" in line.lower():
                        # Extract text between quotes
                        match = re.search(r'"([^"]+)"', line)
                        if match:
                            records.append(match.group(1))
                return records
            except Exception:
                pass

        # Try dig (Unix)
        dig = shutil.which("dig")
        if dig:
            try:
                result = subprocess.run(
                    ["dig", "+short", "TXT", record_name],
                    capture_output=True,
                    text=True,
                    timeout=self.TIMEOUT,
                )
                records = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        # Remove surrounding quotes
                        records.append(line.strip('"'))
                return records
            except Exception:
                pass

        raise AnchorError(
            "No DNS query tool available (install dnspython or ensure dig/nslookup is in PATH)"
        )

    def _parse_drlms_txt(self, record: str) -> Optional[bytes]:
        """Parse DRLMS TXT record format.

        Format: v=drlms1; pubkey=<base64 or hex>
        """
        # Check version
        if "v=drlms1" not in record.lower():
            return None

        # Extract pubkey
        match = re.search(r"pubkey=([A-Za-z0-9+/=]+|[0-9a-fA-F]+)", record)
        if not match:
            return None

        key_str = match.group(1)

        # Try hex first (64 chars = 32 bytes, 66 chars = 33 bytes)
        if len(key_str) in (64, 66) and all(
            c in "0123456789abcdefABCDEF" for c in key_str
        ):
            return bytes.fromhex(key_str)

        # Try base64
        try:
            return base64.b64decode(key_str)
        except Exception:
            return None


class HTTPSAnchorVerifier(AnchorVerifier):
    """Verify identity via HTTPS Well-Known endpoint.

    Expected format at https://domain/.well-known/drlms.json:
    {
        "version": 1,
        "identity_pubkey": "<base64 or hex>",
        "updated_at": "2025-01-01T00:00:00Z"
    }
    """

    WELL_KNOWN_PATH = "/.well-known/drlms.json"

    @property
    def anchor_type(self) -> str:
        return "https"

    def verify(self, domain: str, expected_pubkey: bytes) -> AnchorResult:
        """Verify HTTPS Well-Known anchor.

        Args:
            domain: Domain to check.
            expected_pubkey: Expected public key.

        Returns:
            AnchorResult.
        """
        url = f"https://{domain}{self.WELL_KNOWN_PATH}"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ming-drlms/1.0"},
            )

            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                if resp.status != 200:
                    return AnchorResult(
                        success=False,
                        anchor_type=self.anchor_type,
                        anchor_id=domain,
                        error=f"HTTP {resp.status}",
                    )

                data = json.loads(resp.read().decode())
                raw_response = json.dumps(data)

            # Check version
            if data.get("version") != 1:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=domain,
                    error=f"Unsupported version: {data.get('version')}",
                    raw_response=raw_response,
                )

            # Extract pubkey
            pubkey_str = data.get("identity_pubkey")
            if not pubkey_str:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=domain,
                    error="No identity_pubkey in response",
                    raw_response=raw_response,
                )

            pubkey = self._decode_pubkey(pubkey_str)
            if not pubkey:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=domain,
                    error="Invalid pubkey format",
                    raw_response=raw_response,
                )

            if self._compare_keys(pubkey, expected_pubkey):
                return AnchorResult(
                    success=True,
                    anchor_type=self.anchor_type,
                    anchor_id=domain,
                    declared_pubkey=pubkey,
                    raw_response=raw_response,
                )
            else:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=domain,
                    declared_pubkey=pubkey,
                    error="Public key mismatch",
                    raw_response=raw_response,
                )

        except urllib.error.HTTPError as e:
            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=domain,
                error=f"HTTP {e.code}: {e.reason}",
            )
        except urllib.error.URLError as e:
            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=domain,
                error=f"Connection failed: {e.reason}",
            )
        except json.JSONDecodeError as e:
            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=domain,
                error=f"Invalid JSON: {e}",
            )
        except Exception as e:
            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=domain,
                error=str(e),
            )

    def _decode_pubkey(self, key_str: str) -> Optional[bytes]:
        """Decode pubkey from hex or base64."""
        # Try hex
        if len(key_str) in (64, 66) and all(
            c in "0123456789abcdefABCDEF" for c in key_str
        ):
            return bytes.fromhex(key_str)

        # Try base64
        try:
            return base64.b64decode(key_str)
        except Exception:
            return None


class GitHubAnchorVerifier(AnchorVerifier):
    """Verify identity via GitHub gist or repository.

    Looks for a public gist or repo file named "drlms-identity.json":
    {
        "version": 1,
        "identity_pubkey": "<base64 or hex>",
        "github_user": "username"
    }
    """

    GIST_API = "https://api.github.com/users/{username}/gists"
    RAW_GIST = "https://gist.githubusercontent.com/{username}"
    IDENTITY_FILENAME = "drlms-identity.json"

    @property
    def anchor_type(self) -> str:
        return "github"

    def verify(self, username: str, expected_pubkey: bytes) -> AnchorResult:
        """Verify GitHub anchor.

        Args:
            username: GitHub username.
            expected_pubkey: Expected public key.

        Returns:
            AnchorResult.
        """
        try:
            # Try to find gist with drlms-identity.json
            gist_content = self._find_identity_gist(username)

            if not gist_content:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=username,
                    error=f"No {self.IDENTITY_FILENAME} found in public gists",
                )

            data = json.loads(gist_content)
            raw_response = gist_content

            # Verify username matches
            if data.get("github_user", "").lower() != username.lower():
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=username,
                    error=f"github_user mismatch: expected {username}",
                    raw_response=raw_response,
                )

            # Extract pubkey
            pubkey_str = data.get("identity_pubkey")
            if not pubkey_str:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=username,
                    error="No identity_pubkey in gist",
                    raw_response=raw_response,
                )

            pubkey = self._decode_pubkey(pubkey_str)
            if not pubkey:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=username,
                    error="Invalid pubkey format",
                    raw_response=raw_response,
                )

            if self._compare_keys(pubkey, expected_pubkey):
                return AnchorResult(
                    success=True,
                    anchor_type=self.anchor_type,
                    anchor_id=username,
                    declared_pubkey=pubkey,
                    raw_response=raw_response,
                )
            else:
                return AnchorResult(
                    success=False,
                    anchor_type=self.anchor_type,
                    anchor_id=username,
                    declared_pubkey=pubkey,
                    error="Public key mismatch",
                    raw_response=raw_response,
                )

        except Exception as e:
            return AnchorResult(
                success=False,
                anchor_type=self.anchor_type,
                anchor_id=username,
                error=str(e),
            )

    def _find_identity_gist(self, username: str) -> Optional[str]:
        """Find and fetch drlms-identity.json from user's gists."""
        url = self.GIST_API.format(username=username)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ming-drlms/1.0",
                "Accept": "application/vnd.github.v3+json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                gists = json.loads(resp.read().decode())

            # Find gist with our identity file
            for gist in gists:
                if self.IDENTITY_FILENAME in gist.get("files", {}):
                    file_info = gist["files"][self.IDENTITY_FILENAME]
                    raw_url = file_info.get("raw_url")

                    if raw_url:
                        req2 = urllib.request.Request(
                            raw_url,
                            headers={"User-Agent": "ming-drlms/1.0"},
                        )
                        with urllib.request.urlopen(
                            req2, timeout=self.TIMEOUT
                        ) as resp2:
                            return resp2.read().decode()

            return None

        except Exception:
            return None

    def _decode_pubkey(self, key_str: str) -> Optional[bytes]:
        """Decode pubkey from hex or base64."""
        # Try hex
        if len(key_str) in (64, 66) and all(
            c in "0123456789abcdefABCDEF" for c in key_str
        ):
            return bytes.fromhex(key_str)

        # Try base64
        try:
            return base64.b64decode(key_str)
        except Exception:
            return None


# Convenience function
def verify_anchor(
    anchor_type: str,
    anchor_id: str,
    expected_pubkey: bytes,
) -> AnchorResult:
    """Verify an identity anchor.

    Args:
        anchor_type: "dns", "https", or "github".
        anchor_id: Domain, URL, or GitHub username.
        expected_pubkey: Expected public key.

    Returns:
        AnchorResult.

    Raises:
        ValueError: If anchor_type is unknown.
    """
    verifiers = {
        "dns": DNSAnchorVerifier,
        "https": HTTPSAnchorVerifier,
        "github": GitHubAnchorVerifier,
    }

    if anchor_type not in verifiers:
        raise ValueError(f"Unknown anchor type: {anchor_type}")

    verifier = verifiers[anchor_type]()
    return verifier.verify(anchor_id, expected_pubkey)
