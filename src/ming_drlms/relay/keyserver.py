"""Phase 18B: Keyserver for PreKey Bundle distribution via Relay.

This module provides:
- Publishing PreKey Bundles to Relay keyserver rooms
- Querying PreKey Bundles from multiple Relays
- OPK (One-Time PreKey) management and replenishment
- Bundle caching and expiration handling

Keyserver rooms follow the naming convention: __keyserver__{relay_id}
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..identity import LocalIdentityManager

logger = logging.getLogger(__name__)

__all__ = [
    "PreKeyBundle",
    "KeyserverClient",
    "OPKManager",
    "BundleCache",
    "KEYSERVER_ROOM_PREFIX",
]

# Room naming convention
KEYSERVER_ROOM_PREFIX = "__keyserver__"

# Default configuration
DEFAULT_BUNDLE_TTL = 7 * 24 * 3600  # 7 days
DEFAULT_MIN_OPK_COUNT = 10
DEFAULT_TARGET_OPK_COUNT = 100
DEFAULT_QUERY_TIMEOUT = 5.0  # seconds


@dataclass
class OneTimePreKey:
    """A single One-Time PreKey."""

    id: int
    public_key: bytes

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "key": base64.b64encode(self.public_key).decode(),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "OneTimePreKey":
        return cls(
            id=data["id"],
            public_key=base64.b64decode(data["key"]),
        )


@dataclass
class PreKeyBundle:
    """Signal Protocol PreKey Bundle for key exchange.

    This contains all the public keys needed to establish a Signal session.
    """

    # Identity
    identity_key: bytes  # 32/33 bytes X25519 public key

    # Signed PreKey (rotated periodically)
    signed_prekey: bytes
    signed_prekey_id: int
    prekey_signature: bytes  # XEdDSA signature over signed_prekey

    # One-Time PreKeys (consumed on use)
    one_time_prekeys: List[OneTimePreKey] = field(default_factory=list)

    # Metadata
    registration_id: int = 0
    device_id: int = 1
    timestamp: int = 0
    expires_at: int = 0

    # Signature over entire bundle
    bundle_signature: Optional[bytes] = None

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())
        if self.expires_at == 0:
            self.expires_at = self.timestamp + DEFAULT_BUNDLE_TTL

    @property
    def identity_key_raw(self) -> bytes:
        """Get 32-byte identity key without type prefix."""
        if len(self.identity_key) == 33:
            return self.identity_key[1:]
        return self.identity_key

    @property
    def identity_key_hex(self) -> str:
        """Get identity key as hex string."""
        return self.identity_key_raw.hex()

    @property
    def fingerprint(self) -> str:
        """Get identity key fingerprint."""
        from ..identity import generate_fingerprint

        return generate_fingerprint(self.identity_key)

    @property
    def is_expired(self) -> bool:
        """Check if bundle has expired."""
        return time.time() > self.expires_at

    @property
    def opk_count(self) -> int:
        """Get number of available OPKs."""
        return len(self.one_time_prekeys)

    def get_opk(self, opk_id: Optional[int] = None) -> Optional[OneTimePreKey]:
        """Get a specific OPK by ID, or first available."""
        if opk_id is not None:
            for opk in self.one_time_prekeys:
                if opk.id == opk_id:
                    return opk
            return None
        return self.one_time_prekeys[0] if self.one_time_prekeys else None

    def to_dict(self) -> Dict:
        """Serialize to dictionary for JSON encoding."""
        return {
            "version": 1,
            "identity_key": base64.b64encode(self.identity_key).decode(),
            "signed_prekey": base64.b64encode(self.signed_prekey).decode(),
            "signed_prekey_id": self.signed_prekey_id,
            "prekey_signature": base64.b64encode(self.prekey_signature).decode(),
            "one_time_prekeys": [opk.to_dict() for opk in self.one_time_prekeys],
            "registration_id": self.registration_id,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "bundle_signature": base64.b64encode(self.bundle_signature).decode()
            if self.bundle_signature
            else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PreKeyBundle":
        """Deserialize from dictionary."""
        return cls(
            identity_key=base64.b64decode(data["identity_key"]),
            signed_prekey=base64.b64decode(data["signed_prekey"]),
            signed_prekey_id=data["signed_prekey_id"],
            prekey_signature=base64.b64decode(data["prekey_signature"]),
            one_time_prekeys=[
                OneTimePreKey.from_dict(opk) for opk in data.get("one_time_prekeys", [])
            ],
            registration_id=data.get("registration_id", 0),
            device_id=data.get("device_id", 1),
            timestamp=data.get("timestamp", 0),
            expires_at=data.get("expires_at", 0),
            bundle_signature=base64.b64decode(data["bundle_signature"])
            if data.get("bundle_signature")
            else None,
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> "PreKeyBundle":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def compute_hash(self) -> str:
        """Compute hash of bundle for signing."""
        # Hash identity_key + signed_prekey + timestamp
        data = (
            self.identity_key_raw
            + self.signed_prekey
            + self.timestamp.to_bytes(8, "big")
        )
        return hashlib.sha256(data).hexdigest()


@dataclass
class BundleEvent:
    """A PreKey Bundle published as a Relay event."""

    type: str = "prekey_bundle"
    version: int = 1
    sender: str = ""  # base64(identity_key)
    payload: Optional[PreKeyBundle] = None
    timestamp: int = 0
    expires_at: int = 0
    signature: Optional[str] = None  # XEdDSA signature hex

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "version": self.version,
            "sender": self.sender,
            "payload": self.payload.to_dict() if self.payload else None,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BundleEvent":
        return cls(
            type=data.get("type", "prekey_bundle"),
            version=data.get("version", 1),
            sender=data.get("sender", ""),
            payload=PreKeyBundle.from_dict(data["payload"])
            if data.get("payload")
            else None,
            timestamp=data.get("timestamp", 0),
            expires_at=data.get("expires_at", 0),
            signature=data.get("signature"),
        )


class BundleCache:
    """Local cache for fetched PreKey Bundles."""

    DEFAULT_CACHE_FILE = "bundle_cache.json"

    def __init__(self, cache_path: Optional[Path] = None):
        self._cache_path = cache_path or self._default_cache_path()
        self._cache: Dict[str, Dict] = {}  # fingerprint -> bundle_dict
        self._load()

    @staticmethod
    def _default_cache_path() -> Path:
        env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
        if env_path:
            return Path(env_path).expanduser() / BundleCache.DEFAULT_CACHE_FILE
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / "ming-drlms" / BundleCache.DEFAULT_CACHE_FILE
        return Path.home() / ".config" / "ming-drlms" / BundleCache.DEFAULT_CACHE_FILE

    def _fingerprint(self, identity_key: bytes | str) -> str:
        """Compute fingerprint for cache key."""
        # Handle string input (hex-encoded public key)
        if isinstance(identity_key, str):
            identity_key = bytes.fromhex(identity_key)
        if len(identity_key) == 33:
            identity_key = identity_key[1:]
        return hashlib.sha256(identity_key).hexdigest()[:16]

    def _load(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            self._cache = json.loads(self._cache_path.read_text())
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(self._cache, indent=2))

    def get(self, identity_key: bytes) -> Optional[PreKeyBundle]:
        """Get cached bundle for identity key."""
        fp = self._fingerprint(identity_key)
        data = self._cache.get(fp)
        if not data:
            return None

        bundle = PreKeyBundle.from_dict(data)
        if bundle.is_expired:
            del self._cache[fp]
            self._save()
            return None

        return bundle

    def put(self, bundle: PreKeyBundle) -> None:
        """Cache a bundle."""
        fp = self._fingerprint(bundle.identity_key)
        self._cache[fp] = bundle.to_dict()
        self._save()

    def remove(self, identity_key: bytes) -> bool:
        """Remove bundle from cache."""
        fp = self._fingerprint(identity_key)
        if fp in self._cache:
            del self._cache[fp]
            self._save()
            return True
        return False

    def clear_expired(self) -> int:
        """Remove expired entries, return count removed."""
        now = time.time()
        expired = [
            fp for fp, data in self._cache.items() if data.get("expires_at", 0) < now
        ]
        for fp in expired:
            del self._cache[fp]
        if expired:
            self._save()
        return len(expired)


class OPKManager:
    """Manages One-Time PreKey generation and replenishment.

    OPKs are consumed when someone initiates a session with you.
    This manager tracks used OPKs and triggers replenishment when low.
    """

    def __init__(
        self,
        min_count: int = DEFAULT_MIN_OPK_COUNT,
        target_count: int = DEFAULT_TARGET_OPK_COUNT,
        store_path: Optional[Path] = None,
    ):
        self.min_count = min_count
        self.target_count = target_count
        self._store_path = store_path or self._default_store_path()
        self._used_ids: set[int] = set()
        self._next_id: int = 1
        self._load()

    @staticmethod
    def _default_store_path() -> Path:
        env_path = os.environ.get("MING_DRLMS_CONFIG_DIR")
        if env_path:
            return Path(env_path).expanduser() / "opk_state.json"
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
            if base:
                return Path(base) / "ming-drlms" / "opk_state.json"
        return Path.home() / ".config" / "ming-drlms" / "opk_state.json"

    def _load(self) -> None:
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text())
            self._used_ids = set(data.get("used_ids", []))
            self._next_id = data.get("next_id", 1)
        except Exception:
            pass

    def _save(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "used_ids": list(self._used_ids),
            "next_id": self._next_id,
        }
        self._store_path.write_text(json.dumps(data))

    def mark_used(self, opk_id: int) -> None:
        """Mark an OPK as used (consumed)."""
        self._used_ids.add(opk_id)
        self._save()
        logger.debug("OPK %d marked as used", opk_id)

    def is_used(self, opk_id: int) -> bool:
        """Check if an OPK has been used."""
        return opk_id in self._used_ids

    def needs_replenishment(self, current_count: int) -> bool:
        """Check if OPKs need to be replenished."""
        return current_count < self.min_count

    def generate_opks(self, count: int) -> List[OneTimePreKey]:
        """Generate new OPKs.

        Returns list of OPKs with unique IDs.
        Actual key generation should be done by caller using proper crypto.
        """
        import secrets

        opks = []
        for _ in range(count):
            opk_id = self._next_id
            self._next_id += 1

            # Generate random key (32 bytes for X25519)
            # Apply X25519 bit clamping for consistency with Signal Protocol
            private_key_raw = secrets.token_bytes(32)
            private_clamped = bytearray(private_key_raw)
            private_clamped[0] &= 248
            private_clamped[31] &= 127
            private_clamped[31] |= 64
            private_key = bytes(private_clamped)

            # Derive public key
            try:
                from cryptography.hazmat.primitives.asymmetric.x25519 import (
                    X25519PrivateKey,
                )

                priv = X25519PrivateKey.from_private_bytes(private_key)
                public_key_raw = priv.public_key().public_bytes_raw()
                # Add 0x05 type prefix for Signal Protocol compatibility
                public_key = b"\x05" + public_key_raw
            except ImportError:
                # Fallback: just use random bytes (not secure, for testing only)
                public_key = b"\x05" + secrets.token_bytes(32)

            opks.append(OneTimePreKey(id=opk_id, public_key=public_key))

        self._save()
        return opks

    def get_replenishment_count(self, current_count: int) -> int:
        """Get number of OPKs to generate for replenishment."""
        if current_count >= self.min_count:
            return 0
        return self.target_count - current_count


class KeyserverClient:
    """Client for interacting with Keyserver rooms on Relays.

    Usage:
        client = KeyserverClient(relays=["https://relay1.example.com"])

        # Publish your bundle
        await client.publish_bundle(my_bundle)

        # Query someone's bundle
        bundle = await client.fetch_bundle(target_pubkey)
    """

    def __init__(
        self,
        relays: Optional[List[str]] = None,
        cache: Optional[BundleCache] = None,
        opk_manager: Optional[OPKManager] = None,
        timeout: float = DEFAULT_QUERY_TIMEOUT,
    ):
        self.relays = relays or []
        self.cache = cache or BundleCache()
        self.opk_manager = opk_manager or OPKManager()
        self.timeout = timeout

    def _keyserver_room(self, relay_url: str) -> str:
        """Get keyserver room ID for a relay."""
        # Extract relay ID from URL
        from urllib.parse import urlparse

        parsed = urlparse(relay_url)
        relay_id = parsed.netloc.replace(":", "_")
        return f"{KEYSERVER_ROOM_PREFIX}{relay_id}"

    async def publish_bundle(
        self,
        bundle: PreKeyBundle,
        sign_func: Optional[callable] = None,
    ) -> Dict[str, bool]:
        """Publish PreKey Bundle to all configured relays.

        Args:
            bundle: PreKeyBundle to publish
            sign_func: Optional function to sign the event (data) -> signature_hex

        Returns:
            Dict mapping relay URL to success status
        """
        import urllib.request
        import urllib.error

        results = {}

        # Create bundle event
        event = BundleEvent(
            sender=base64.b64encode(bundle.identity_key_raw).decode(),
            payload=bundle,
            timestamp=int(time.time()),
            expires_at=bundle.expires_at,
        )

        # Sign if function provided
        if sign_func:
            event_data = json.dumps(event.to_dict(), sort_keys=True)
            event.signature = sign_func(event_data.encode())

        event_json = json.dumps(event.to_dict())

        for relay_url in self.relays:
            room_id = self._keyserver_room(relay_url)

            try:
                # POST to relay
                url = f"{relay_url}/events"
                data = {
                    "room": room_id,
                    "ciphertext": event_json,
                    "client_ts": event.timestamp,
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        results[relay_url] = True
                        logger.info("Published bundle to %s", relay_url)
                    else:
                        results[relay_url] = False
                        logger.warning(
                            "Failed to publish bundle to %s: HTTP %d",
                            relay_url,
                            resp.status,
                        )
            except Exception as e:
                results[relay_url] = False
                logger.warning("Failed to publish bundle to %s: %s", relay_url, e)

        return results

    async def fetch_bundle(
        self,
        target_pubkey: bytes,
        use_cache: bool = True,
        verify_func: Optional[callable] = None,
    ) -> Optional[PreKeyBundle]:
        """Fetch PreKey Bundle for a target public key.

        Args:
            target_pubkey: Target's identity public key
            use_cache: Whether to check cache first
            verify_func: Optional function to verify signature (data, sig, pubkey) -> bool

        Returns:
            PreKeyBundle if found, None otherwise
        """
        import urllib.request
        import urllib.error

        # Check cache first
        if use_cache:
            cached = self.cache.get(target_pubkey)
            if cached:
                logger.debug("Using cached bundle for %s", cached.fingerprint[:16])
                return cached

        # Query relays
        target_b64 = base64.b64encode(
            target_pubkey[1:] if len(target_pubkey) == 33 else target_pubkey
        ).decode()

        for relay_url in self.relays:
            room_id = self._keyserver_room(relay_url)

            try:
                # GET events from keyserver room
                url = f"{relay_url}/events?room={room_id}&limit=100"

                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status != 200:
                        continue

                    data = json.loads(resp.read().decode())
                    if isinstance(data, list):
                        events = data
                    else:
                        events = data.get("events", [])

                    # Find matching bundle - collect all valid bundles and return the newest
                    best_bundle = None
                    best_timestamp = 0

                    for event_data in events:
                        ciphertext = event_data.get("ciphertext", "")
                        try:
                            event_dict = json.loads(ciphertext)
                            if event_dict.get("type") != "prekey_bundle":
                                continue
                            if event_dict.get("sender") != target_b64:
                                continue

                            event = BundleEvent.from_dict(event_dict)

                            # Verify signature if function provided
                            if verify_func and event.signature:
                                event_copy = event_dict.copy()
                                del event_copy["signature"]
                                event_json = json.dumps(event_copy, sort_keys=True)
                                if not verify_func(
                                    event_json.encode(),
                                    event.signature,
                                    target_pubkey,
                                ):
                                    logger.warning(
                                        "Bundle signature verification failed"
                                    )
                                    continue

                            # Check expiration and track the newest bundle
                            if event.payload and not event.payload.is_expired:
                                if event.timestamp > best_timestamp:
                                    best_timestamp = event.timestamp
                                    best_bundle = event.payload

                        except (json.JSONDecodeError, KeyError):
                            continue

                    # Return the newest bundle found
                    if best_bundle:
                        self.cache.put(best_bundle)
                        logger.info(
                            "Fetched bundle from %s for %s",
                            relay_url,
                            best_bundle.fingerprint[:16],
                        )
                        return best_bundle

            except Exception as e:
                logger.warning("Failed to query %s: %s", relay_url, e)
                continue

        logger.warning("No bundle found for target")
        return None

    async def check_and_republish(
        self,
        identity_manager: "LocalIdentityManager",
        force: bool = False,
    ) -> bool:
        """Check OPK count and republish bundle if needed.

        Args:
            identity_manager: LocalIdentityManager with current identity
            force: Force republish even if OPKs are sufficient

        Returns:
            True if bundle was republished
        """
        try:
            identity = identity_manager.get_identity()
        except ValueError:
            logger.warning("No identity available for republish check")
            return False

        # Check if we have a published bundle
        cached = self.cache.get(identity.public_key)

        current_opk_count = cached.opk_count if cached else 0

        if not force and not self.opk_manager.needs_replenishment(current_opk_count):
            return False

        # Generate new OPKs
        new_count = self.opk_manager.get_replenishment_count(current_opk_count)
        new_opks = self.opk_manager.generate_opks(new_count) if new_count > 0 else []

        # Combine with existing OPKs (if any)
        all_opks = []
        if cached:
            all_opks = [
                opk
                for opk in cached.one_time_prekeys
                if not self.opk_manager.is_used(opk.id)
            ]
        all_opks.extend(new_opks)

        # Create new bundle
        # Note: In production, signed_prekey should be properly generated
        bundle = PreKeyBundle(
            identity_key=identity.public_key,
            signed_prekey=identity.public_key,  # Placeholder
            signed_prekey_id=1,
            prekey_signature=bytes(64),  # Placeholder
            one_time_prekeys=all_opks,
            registration_id=identity.registration_id,
            device_id=identity.device_id,
        )

        # Publish
        results = await self.publish_bundle(bundle)
        success = any(results.values())

        if success:
            logger.info(
                "Republished bundle with %d OPKs (%d new)", len(all_opks), len(new_opks)
            )

        return success

    def on_opk_consumed(self, opk_id: int) -> None:
        """Handle OPK consumption notification.

        Call this when you receive a message that consumed an OPK.
        """
        self.opk_manager.mark_used(opk_id)
        logger.debug("OPK %d consumed", opk_id)
