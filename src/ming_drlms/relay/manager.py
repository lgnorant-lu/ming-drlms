"""Phase 16A: Relay Manager Module.

Implements parallel write strategy and unified relay management:
- Parallel writes to multiple healthy relays
- Automatic failover and retry
- Integration with discovery and health checking
- Offline queue integration
- RCV-01: Storage receipt verification
"""

from __future__ import annotations

import asyncio
import logging
import time
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, TYPE_CHECKING
from urllib.parse import urlencode
import urllib.request
import urllib.error

from .discovery import RelayDiscovery, RelayEndpoint, DiscoveryPriority
from .health import HealthChecker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WriteStatus(Enum):
    """Status of a relay write operation."""

    SUCCESS = "success"
    PARTIAL = "partial"  # Some relays succeeded
    QUEUED = "queued"  # All failed, queued for retry
    FAILED = "failed"  # All failed, not queued


@dataclass
class StorageReceipt:
    """RCV-01: Storage receipt from a relay.

    Phase 17A: Extended with XEdDSA signature fields.
    """

    relay_url: str
    relay_id: str
    server_seq: int
    server_ts: int
    signature: str  # HMAC signature (legacy)
    verified: bool = False  # HMAC verified
    # Phase 17A: XEdDSA fields
    xeddsa_signature: Optional[str] = None
    relay_pubkey: Optional[str] = None
    xeddsa_verified: bool = False


@dataclass
class WriteResult:
    """Result of a parallel write operation."""

    status: WriteStatus
    success_count: int = 0
    total_relays: int = 0
    event_id: Optional[str] = None
    failed_relays: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    server_seqs: dict[str, int] = field(default_factory=dict)
    # RCV-01: Storage receipts from successful writes
    receipts: list[StorageReceipt] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status in (WriteStatus.SUCCESS, WriteStatus.PARTIAL)

    @property
    def verified_count(self) -> int:
        """RCV-01: Count of verified receipts."""
        return sum(1 for r in self.receipts if r.verified)


@dataclass
class ReadResult:
    """Result of a relay read operation."""

    success: bool
    events: list[dict[str, Any]] = field(default_factory=list)
    source_relay: Optional[str] = None
    error: Optional[str] = None


class RelayManager:
    """Unified manager for multi-relay operations.

    Features:
    - Parallel writes to all healthy relays
    - Automatic failover on failures
    - Health-aware relay selection
    - Integration with offline queue
    - RCV-01: Storage receipt verification and persistence
    """

    def __init__(
        self,
        discovery: Optional[RelayDiscovery] = None,
        health_checker: Optional[HealthChecker] = None,
        offline_queue: Optional[Any] = None,  # OfflineQueue (Phase 16D)
        receipt_store: Optional[Any] = None,  # ReceiptStore (RCV-01)
        write_timeout: float = 10.0,
        read_timeout: float = 10.0,
        min_write_success: int = 1,  # Minimum successful writes required
        require_verified: bool = False,  # RCV-01: Require verified receipt
        min_verified_count: int = 1,  # RCV-01: Min verified receipts
    ):
        """Initialize the relay manager.

        Args:
            discovery: Relay discovery service
            health_checker: Health checker service
            offline_queue: Offline queue for failed writes (Phase 16D)
            receipt_store: Receipt store for persistence (RCV-01)
            write_timeout: Timeout for write operations
            read_timeout: Timeout for read operations
            min_write_success: Minimum number of successful writes required
            require_verified: Whether to require verified receipts for success
            min_verified_count: Minimum verified receipts required
        """
        self.discovery = discovery or RelayDiscovery()
        self.health_checker = health_checker or HealthChecker()
        self.offline_queue = offline_queue
        self.receipt_store = receipt_store
        self.write_timeout = write_timeout
        self.read_timeout = read_timeout
        self.min_write_success = min_write_success
        self.require_verified = require_verified
        self.min_verified_count = min_verified_count

        self._relays: list[RelayEndpoint] = []
        self._initialized = False

    async def initialize(self, domain: Optional[str] = None) -> None:
        """Initialize the manager by discovering relays.

        Args:
            domain: Domain for DNS/Well-Known discovery
        """
        self._relays = await self.discovery.discover(domain=domain)
        relay_urls = [r.url for r in self._relays if r.enabled]
        self.health_checker.set_relays(relay_urls)
        self._initialized = True

        logger.info("RelayManager initialized with %d relays", len(relay_urls))

    def add_relay(self, url: str, priority: int = 1) -> None:
        """Manually add a relay to the manager.

        Args:
            url: Relay URL
            priority: Priority (lower = higher priority)
        """
        endpoint = RelayEndpoint(
            url=url,
            priority=DiscoveryPriority(min(priority, 5)),
        )
        self._relays.append(endpoint)
        self.health_checker.set_relays([r.url for r in self._relays])

    def get_healthy_relays(self, min_score: float = 0.3) -> list[str]:
        """Get list of healthy relay URLs.

        Args:
            min_score: Minimum health score threshold

        Returns:
            List of healthy relay URLs, sorted by score
        """
        return self.health_checker.get_healthy_relays(min_score)

    def get_all_relays(self) -> list[RelayEndpoint]:
        """Get all registered relay endpoints."""
        return self._relays.copy()

    def _verify_receipt(
        self,
        event_id: str,
        room: str,
        server_seq: int,
        server_ts: int,
        relay_id: str,
        xeddsa_signature: Optional[str] = None,
        relay_pubkey: Optional[str] = None,
    ) -> bool:
        """Phase 17C: Verify storage receipt XEdDSA signature.

        Args:
            event_id: Client event hash
            room: Room identifier
            server_seq: Server sequence number
            server_ts: Server timestamp
            relay_id: Relay identity
            xeddsa_signature: XEdDSA signature hex
            relay_pubkey: Relay's Ed25519 public key hex

        Returns:
            True if verified, False otherwise
        """
        if not xeddsa_signature or not relay_pubkey:
            logger.debug("Phase 17C: No XEdDSA signature for %s", relay_id)
            return False

        message = f"{event_id}|{room}|{server_seq}|{server_ts}|{relay_id}".encode()
        verified = self._verify_xeddsa(
            message, xeddsa_signature, relay_pubkey, relay_id
        )

        if verified:
            logger.debug("Phase 17C: XEdDSA verified for %s", relay_id)
        else:
            logger.warning("Phase 17C: XEdDSA verification failed for %s", relay_id)

        return verified

    def _verify_xeddsa(
        self,
        message: bytes,
        signature_hex: str,
        pubkey_hex: str,
        relay_id: str,
    ) -> bool:
        """Phase 17A: Verify XEdDSA signature.

        Args:
            message: Original message bytes
            signature_hex: 64-byte signature as hex
            pubkey_hex: Ed25519 public key as hex
            relay_id: For logging

        Returns:
            True if verified, False otherwise
        """
        try:
            from nacl.signing import VerifyKey
            import nacl.exceptions

            signature = bytes.fromhex(signature_hex)
            pubkey = bytes.fromhex(pubkey_hex)

            if len(signature) != 64:
                logger.warning("Phase 17A: Invalid signature length for %s", relay_id)
                return False
            if len(pubkey) != 32:
                logger.warning("Phase 17A: Invalid pubkey length for %s", relay_id)
                return False

            # Create verify key from Ed25519 public key
            # Note: Server signs with SigningKey which produces Ed25519 keys
            verify_key = VerifyKey(pubkey)
            verify_key.verify(message, signature)
            return True

        except nacl.exceptions.BadSignatureError:
            logger.warning("Phase 17A: XEdDSA verification failed for %s", relay_id)
            return False
        except ImportError:
            logger.debug("Phase 17A: pynacl not available for verification")
            return False
        except Exception as e:
            logger.warning("Phase 17A: XEdDSA error for %s: %s", relay_id, e)
            return False

    async def post_event(
        self,
        room: str,
        ciphertext: str,
        content_len: int = 0,
        client_event_hash: Optional[str] = None,
        client_ts: Optional[int] = None,
        target_relays: Optional[list[str]] = None,
    ) -> WriteResult:
        """Post an event to multiple relays in parallel.

        Args:
            room: Room identifier
            ciphertext: Encrypted event content
            content_len: Original content length
            client_event_hash: Client-computed event hash
            client_ts: Client timestamp
            target_relays: Specific relays to target (default: all healthy)

        Returns:
            WriteResult with success/failure details
        """
        # Get target relays
        if target_relays:
            relays = target_relays
        else:
            relays = self.get_healthy_relays()

        if not relays:
            logger.warning("No healthy relays available for write")
            # Queue for later if offline queue is available
            if self.offline_queue:
                await self._queue_event(
                    room, ciphertext, content_len, client_event_hash, client_ts
                )
                return WriteResult(
                    status=WriteStatus.QUEUED,
                    total_relays=0,
                )
            return WriteResult(status=WriteStatus.FAILED, total_relays=0)

        # Parallel write to all healthy relays
        async def _write_to_relay(
            relay_url: str,
        ) -> tuple[str, bool, Optional[str], Optional[dict]]:
            """Write to a single relay, return (url, success, error, response_dict)."""
            try:
                start = time.monotonic()
                result = await self._post_to_relay(
                    relay_url,
                    room,
                    ciphertext,
                    content_len,
                    client_event_hash,
                    client_ts,
                )
                latency_ms = (time.monotonic() - start) * 1000

                # Report success to health checker
                self.health_checker.report_success(relay_url, latency_ms)

                # Mark success in discovery cache
                self.discovery.mark_success(relay_url)

                return (relay_url, True, None, result)
            except Exception as e:
                # Report failure to health checker
                self.health_checker.report_failure(relay_url, str(e))
                return (relay_url, False, str(e), None)

        # Execute parallel writes
        tasks = [_write_to_relay(url) for url in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        success_count = 0
        failed_relays: list[str] = []
        errors: dict[str, str] = {}
        server_seqs: dict[str, int] = {}
        receipts: list[StorageReceipt] = []

        for result in results:
            if isinstance(result, Exception):
                continue
            url, success, error, response = result
            if success and response:
                success_count += 1
                server_seq = response.get("server_seq")
                if server_seq is not None:
                    server_seqs[url] = server_seq

                # Phase 17C: Extract and verify XEdDSA storage receipt
                relay_id = response.get("relay_id")
                server_ts = response.get("server_ts", 0)
                xeddsa_sig = response.get("xeddsa_signature")
                relay_pubkey = response.get("relay_pubkey")

                if relay_id and client_event_hash:
                    verified = self._verify_receipt(
                        client_event_hash,
                        room,
                        server_seq,
                        server_ts,
                        relay_id,
                        xeddsa_signature=xeddsa_sig,
                        relay_pubkey=relay_pubkey,
                    )
                    receipt = StorageReceipt(
                        relay_url=url,
                        relay_id=relay_id,
                        server_seq=server_seq,
                        server_ts=server_ts,
                        signature=xeddsa_sig or "",
                        verified=verified,
                        xeddsa_signature=xeddsa_sig,
                        relay_pubkey=relay_pubkey,
                        xeddsa_verified=verified,
                    )
                    receipts.append(receipt)
                    if verified:
                        logger.debug("Phase 17C: Receipt verified from %s", url)
                    else:
                        logger.warning(
                            "Phase 17C: Receipt verification failed from %s", url
                        )
            else:
                failed_relays.append(url)
                if error:
                    errors[url] = error

        # Determine status
        if success_count == 0:
            if self.offline_queue:
                await self._queue_event(
                    room,
                    ciphertext,
                    content_len,
                    client_event_hash,
                    client_ts,
                    failed_relays,
                )
                status = WriteStatus.QUEUED
            else:
                status = WriteStatus.FAILED
        elif success_count < len(relays):
            status = WriteStatus.PARTIAL
            # Queue partial failures for retry
            if self.offline_queue and failed_relays:
                await self._queue_partial(
                    room,
                    ciphertext,
                    content_len,
                    client_event_hash,
                    client_ts,
                    failed_relays,
                )
        else:
            status = WriteStatus.SUCCESS

        write_result = WriteResult(
            status=status,
            success_count=success_count,
            total_relays=len(relays),
            event_id=client_event_hash,
            failed_relays=failed_relays,
            errors=errors,
            server_seqs=server_seqs,
            receipts=receipts,
        )

        # RCV-01: Check verified receipt threshold if enabled
        if self.require_verified and status == WriteStatus.SUCCESS:
            if write_result.verified_count < self.min_verified_count:
                logger.warning(
                    "RCV-01: Insufficient verified receipts: %d < %d",
                    write_result.verified_count,
                    self.min_verified_count,
                )
                # Downgrade to partial if verification threshold not met
                write_result.status = WriteStatus.PARTIAL

        # RCV-01: Persist receipts if store is configured
        if self.receipt_store and receipts and client_event_hash:
            try:
                receipt_dicts = [
                    {
                        "event_id": client_event_hash,
                        "room": room,
                        "relay_url": r.relay_url,
                        "relay_id": r.relay_id,
                        "server_seq": r.server_seq,
                        "server_ts": r.server_ts,
                        "signature": r.signature,
                        "verified": r.verified,
                    }
                    for r in receipts
                ]
                self.receipt_store.save_receipts_batch(receipt_dicts)
                logger.debug("RCV-01: Persisted %d receipts", len(receipts))
            except Exception as e:
                logger.warning("RCV-01: Failed to persist receipts: %s", e)

        logger.info(
            "Parallel write: %d/%d succeeded (status=%s, verified=%d)",
            success_count,
            len(relays),
            write_result.status.value,
            write_result.verified_count,
        )

        return write_result

    async def _post_to_relay(
        self,
        relay_url: str,
        room: str,
        ciphertext: str,
        content_len: int,
        client_event_hash: Optional[str],
        client_ts: Optional[int],
    ) -> dict[str, Any]:
        """Post event to a single relay."""
        payload = {
            "room": room,
            "ciphertext": ciphertext,
            "content_len": content_len,
        }
        if client_event_hash:
            payload["client_event_hash"] = client_event_hash
        if client_ts:
            payload["client_ts"] = client_ts

        url = f"{relay_url.rstrip('/')}/events"
        data = json.dumps(payload).encode("utf-8")

        def _post() -> dict[str, Any]:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.write_timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _post)

    async def _queue_event(
        self,
        room: str,
        ciphertext: str,
        content_len: int,
        client_event_hash: Optional[str],
        client_ts: Optional[int],
        target_relays: Optional[list[str]] = None,
    ) -> None:
        """Queue event for later retry (Phase 16D integration)."""
        if not self.offline_queue:
            return
        self.offline_queue.enqueue(
            room=room,
            ciphertext=ciphertext,
            content_len=content_len,
            client_event_hash=client_event_hash,
            client_ts=client_ts,
            target_relays=target_relays,
        )
        logger.info("Event queued for retry: %s", client_event_hash)

    async def _queue_partial(
        self,
        room: str,
        ciphertext: str,
        content_len: int,
        client_event_hash: Optional[str],
        client_ts: Optional[int],
        failed_relays: list[str],
    ) -> None:
        """Queue partial failures for specific relays (Phase 16D integration)."""
        if not self.offline_queue:
            return
        self.offline_queue.enqueue(
            room=room,
            ciphertext=ciphertext,
            content_len=content_len,
            client_event_hash=client_event_hash,
            client_ts=client_ts,
            target_relays=failed_relays,
        )
        logger.info(
            "Partial failures queued for retry: %s -> %s",
            client_event_hash,
            failed_relays,
        )

    async def get_events(
        self,
        room: str,
        since_seq: int = 0,
        limit: int = 100,
        prefer_relay: Optional[str] = None,
    ) -> ReadResult:
        """Get events from a relay.

        Tries relays in health order until one succeeds.

        Args:
            room: Room identifier
            since_seq: Fetch events after this sequence number
            limit: Maximum number of events to fetch
            prefer_relay: Preferred relay URL (tried first if healthy)

        Returns:
            ReadResult with events or error
        """
        relays = self.get_healthy_relays()

        # Put preferred relay first if healthy
        if prefer_relay and prefer_relay in relays:
            relays.remove(prefer_relay)
            relays.insert(0, prefer_relay)

        if not relays:
            return ReadResult(success=False, error="No healthy relays available")

        # Try relays in order until one succeeds
        for relay_url in relays:
            try:
                start = time.monotonic()
                events = await self._get_from_relay(relay_url, room, since_seq, limit)
                latency_ms = (time.monotonic() - start) * 1000

                self.health_checker.report_success(relay_url, latency_ms)

                return ReadResult(
                    success=True,
                    events=events,
                    source_relay=relay_url,
                )
            except Exception as e:
                self.health_checker.report_failure(relay_url, str(e))
                logger.warning("Read failed from %s: %s", relay_url, e)
                continue

        return ReadResult(success=False, error="All relays failed")

    async def _get_from_relay(
        self,
        relay_url: str,
        room: str,
        since_seq: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Get events from a single relay."""
        params = urlencode({"room": room, "since_seq": since_seq, "limit": limit})
        url = f"{relay_url.rstrip('/')}/events?{params}"

        def _get() -> list[dict[str, Any]]:
            with urllib.request.urlopen(url, timeout=self.read_timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get)

    async def start(self, domain: Optional[str] = None) -> None:
        """Start the relay manager with monitoring.

        Args:
            domain: Domain for discovery
        """
        await self.initialize(domain)
        await self.health_checker.start_monitoring()

    async def stop(self) -> None:
        """Stop the relay manager and monitoring."""
        await self.health_checker.stop_monitoring()


__all__ = [
    "WriteStatus",
    "StorageReceipt",
    "WriteResult",
    "ReadResult",
    "RelayManager",
]
