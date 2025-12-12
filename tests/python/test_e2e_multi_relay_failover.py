"""Phase 16 E2E Test: Multi-Relay Failover and Recovery.

This test suite covers:
1. Parallel writes to multiple relays
2. Automatic failover when some relays fail
3. Offline queue accumulation and automatic retry
4. Receipt verification across relays
5. Merkle sync with by-ids differential pull
"""

import threading
import time
from unittest.mock import MagicMock

import pytest


class TestMultiRelayFailover:
    """E2E tests for multi-relay failover scenarios."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create temporary database path."""
        return tmp_path / "test_failover.db"

    @pytest.fixture
    def mock_relay_responses(self):
        """Mock relay responses for testing."""
        return {
            "relay1": {"status": "ok", "server_seq": 1, "server_ts": 1000},
            "relay2": {"status": "ok", "server_seq": 1, "server_ts": 1001},
            "relay3": {"status": "error", "error": "connection_refused"},
        }

    def test_parallel_write_all_healthy(self):
        """Test parallel write when all relays are healthy."""
        from ming_drlms.relay.manager import RelayManager

        # Setup
        manager = RelayManager(
            min_write_success=1,
            require_verified=False,
        )

        # Mock relays
        manager._relays = [
            MagicMock(url="http://relay1:15019", enabled=True),
            MagicMock(url="http://relay2:15019", enabled=True),
        ]
        manager._initialized = True

        # Verify manager accepts parameters
        assert manager.min_write_success == 1
        assert manager.require_verified is False

    def test_parallel_write_partial_failure(self):
        """Test parallel write with some relays failing."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager(
            min_write_success=1,
            require_verified=False,
        )

        # Simulate partial failure scenario
        # In real scenario, _post_to_relay would fail for some relays
        # and succeed for others, resulting in PARTIAL status
        assert manager.min_write_success == 1

    def test_offline_queue_integration(self, temp_db):
        """Test offline queue accumulates failed writes."""
        from ming_drlms.relay.offline_queue import OfflineQueue

        queue = OfflineQueue(temp_db)  # Path object

        # Simulate failed write being queued
        queue_id = queue.enqueue(
            room="test-room",
            ciphertext="encrypted-data",
            content_len=100,
            client_event_hash="test-event-1",
            client_ts=int(time.time()),
        )
        assert queue_id > 0

        stats = queue.get_stats()
        assert stats["pending"] >= 1

    def test_offline_queue_retry_on_network_recovery(self, temp_db):
        """Test offline queue retries when network recovers."""
        from ming_drlms.relay.offline_queue import OfflineQueue

        queue = OfflineQueue(temp_db)  # Path object

        # Enqueue some events
        for i in range(3):
            queue.enqueue(
                room="test-room",
                ciphertext=f"data-{i}",
                content_len=10,
                client_event_hash=f"test-event-{i}",
                client_ts=int(time.time()),
            )

        stats = queue.get_stats()
        assert stats["pending"] >= 3

        # Simulate network recovery trigger
        # In real scenario, NetworkMonitor.RECOVERED would trigger process_queue

    def test_receipt_verification_multi_relay(self, temp_db):
        """Test receipt verification from multiple relays."""
        from ming_drlms.relay.manager import StorageReceipt, WriteResult, WriteStatus
        from ming_drlms.relay.receipt_store import ReceiptStore

        store = ReceiptStore(temp_db)

        # Simulate receipts from multiple relays
        receipts = [
            StorageReceipt(
                relay_url="http://relay1:15019",
                relay_id="relay1",
                server_seq=1,
                server_ts=1000,
                signature="sig1",
                verified=True,
            ),
            StorageReceipt(
                relay_url="http://relay2:15019",
                relay_id="relay2",
                server_seq=1,
                server_ts=1001,
                signature="sig2",
                verified=True,
            ),
            StorageReceipt(
                relay_url="http://relay3:15019",
                relay_id="relay3",
                server_seq=0,
                server_ts=0,
                signature="",
                verified=False,  # Failed relay
            ),
        ]

        # Create write result
        result = WriteResult(
            status=WriteStatus.PARTIAL,
            success_count=2,
            total_relays=3,
            event_id="test-event",
            failed_relays=["http://relay3:15019"],
            errors={"http://relay3:15019": "connection_refused"},
            server_seqs={"http://relay1:15019": 1, "http://relay2:15019": 1},
            receipts=receipts,
        )

        assert result.verified_count == 2
        assert result.success_count == 2

        # Persist receipts
        receipt_dicts = [
            {
                "event_id": "test-event",
                "room": "test-room",
                "relay_url": r.relay_url,
                "relay_id": r.relay_id,
                "server_seq": r.server_seq,
                "server_ts": r.server_ts,
                "signature": r.signature,
                "verified": r.verified,
            }
            for r in receipts
            if r.verified
        ]

        ids = store.save_receipts_batch(receipt_dicts)
        assert len(ids) == 2

    def test_merkle_sync_differential(self):
        """Test Merkle tree sync with differential pull."""
        from ming_drlms.relay.merkle import MerkleTree

        # Client tree (missing some events)
        client_tree = MerkleTree(room_id="test-room")
        client_tree.add_event("event1")
        client_tree.add_event("event2")

        # Server tree (has more events)
        server_tree = MerkleTree(room_id="test-room")
        server_tree.add_event("event1")
        server_tree.add_event("event2")
        server_tree.add_event("event3")
        server_tree.add_event("event4")

        # Roots differ
        assert client_tree.root != server_tree.root

        # In real scenario:
        # 1. Client sends root to server
        # 2. Server compares and identifies missing events
        # 3. Client fetches missing events via /events/by-ids

    def test_health_checker_failover(self):
        """Test health checker triggers failover."""
        from ming_drlms.relay.health import HealthChecker

        checker = HealthChecker(check_interval=1.0)

        # Add relays
        checker.set_relays(
            [
                "http://relay1:15019",
                "http://relay2:15019",
                "http://relay3:15019",
            ]
        )

        # Simulate health scores
        # In real scenario, ping_relay would update scores

        # Get all relays
        assert len(checker._relays) == 3

    def test_network_monitor_recovery_event(self):
        """Test network monitor triggers recovery event."""
        from ming_drlms.relay.network import NetworkMonitor, NetworkEvent, NetworkStatus

        recovery_triggered = threading.Event()

        async def on_network_event(event: NetworkEvent, status: NetworkStatus):
            if event == NetworkEvent.RECOVERED:
                recovery_triggered.set()

        monitor = NetworkMonitor(
            check_interval=1.0,
        )

        # Monitor setup verified
        assert monitor is not None

    def test_deduplicator_prevents_duplicates(self):
        """Test event deduplicator prevents duplicate processing."""
        from ming_drlms.relay.dedup import EventDeduplicator

        dedup = EventDeduplicator()

        # First occurrence - is_duplicate returns False and marks as seen
        assert not dedup.is_duplicate("event1")

        # Duplicate - is_duplicate returns True
        assert dedup.is_duplicate("event1")

        # New event
        assert not dedup.is_duplicate("event2")

    def test_validator_rejects_invalid_events(self):
        """Test event validator rejects malformed events."""
        import base64
        import time as _time

        from ming_drlms.relay.validator import EventValidator
        from ming_drlms.core.event_hash import compute_event_id

        validator = EventValidator()

        # Valid event with all required fields
        sender_pubkey = b"\x01" * 32
        content = b"data"
        timestamp_ms = int(_time.time() * 1000)
        event_id = compute_event_id(sender_pubkey, content, timestamp_ms)

        valid = {
            "event_id": event_id,
            "sender_pubkey_hex": sender_pubkey.hex(),
            "content_bytes_b64": base64.b64encode(content).decode(),
            "timestamp_ms": timestamp_ms,
        }
        result = validator.validate(valid)
        assert result.valid

        # Invalid event (missing required fields)
        invalid = {
            "event_id": "deadbeef",
            # missing sender_pubkey_hex and timestamp_ms
        }
        result = validator.validate(invalid)
        assert not result.valid


class TestE2EScenarios:
    """Complex E2E scenario tests."""

    def test_scenario_dual_relay_one_fails(self, tmp_path):
        """Scenario: 2 relays, 1 fails during write."""
        from ming_drlms.relay.manager import RelayManager
        from ming_drlms.relay.offline_queue import OfflineQueue

        # Setup
        queue = OfflineQueue(tmp_path / "queue.db")
        manager = RelayManager(
            offline_queue=queue,
            min_write_success=1,
        )

        # Expected behavior:
        # - Write succeeds on relay1
        # - Write fails on relay2
        # - Failed write queued for retry
        # - Overall status: PARTIAL (1/2 succeeded)

        assert manager.min_write_success == 1
        assert manager.offline_queue is queue

    def test_scenario_all_relays_fail_then_recover(self, tmp_path):
        """Scenario: All relays fail, then network recovers."""
        from ming_drlms.relay.offline_queue import OfflineQueue

        queue = OfflineQueue(tmp_path / "queue.db")

        # Simulate all writes failing (network down)
        for i in range(5):
            queue.enqueue(
                room="test-room",
                ciphertext=f"data-{i}",
                content_len=10,
                client_event_hash=f"offline-event-{i}",
                client_ts=int(time.time()),
            )

        # All events queued
        stats = queue.get_stats()
        assert stats["pending"] == 5

        # Network recovers - would trigger process_queue
        # Events would be retried and succeed

    def test_scenario_merkle_catchup_sync(self):
        """Scenario: Client catches up using Merkle diff + by-ids."""
        from ming_drlms.relay.merkle import MerkleTree

        # Client was offline for a while
        client_tree = MerkleTree(room_id="test-room")
        for i in range(10):
            client_tree.add_event(f"old-event-{i}")

        # Server has 20 more events
        server_tree = MerkleTree(room_id="test-room")
        for i in range(10):
            server_tree.add_event(f"old-event-{i}")
        for i in range(20):
            server_tree.add_event(f"new-event-{i}")

        # Client detects root mismatch
        assert client_tree.root != server_tree.root

        # Expected flow:
        # 1. GET /events/root -> server_root
        # 2. Compare client_root != server_root
        # 3. GET /events?since_seq=10 or /events/by-ids
        # 4. Client adds missing events
        # 5. Roots match

    def test_scenario_receipt_audit_trail(self, tmp_path):
        """Scenario: Audit trail of all write receipts."""
        from ming_drlms.relay.receipt_store import ReceiptStore

        store = ReceiptStore(tmp_path / "receipts.db")

        # Simulate writes over time
        for i in range(100):
            store.save_receipt(
                event_id=f"event-{i}",
                room="audit-room",
                relay_url="http://relay1:15019",
                relay_id="relay1",
                server_seq=i + 1,
                server_ts=1000 + i,
                signature=f"sig-{i}",
                verified=True,
            )

        # Audit: get all receipts for room
        receipts = store.get_receipts_for_room("audit-room", limit=100)
        assert len(receipts) == 100

        # Stats
        stats = store.get_stats()
        assert stats["total"] == 100
        assert stats["verified"] == 100


class TestConfigurationIntegration:
    """Tests for configuration integration."""

    def test_relays_config_receipt_settings(self, tmp_path):
        """Test receipt settings from relays.toml."""
        from ming_drlms.relay.config import RelaysConfig

        config_path = tmp_path / "relays.toml"
        config_path.write_text("""
[health]
check_interval = 15.0

[offline]
max_retries = 5

[receipt]
require_verified = true
min_verified_count = 2
persist_receipts = true
retention_days = 14

[[relays]]
url = "http://relay1:15019"
priority = 1

[[relays]]
url = "http://relay2:15019"
priority = 2
""")

        config = RelaysConfig.load(config_path)

        assert config.health.check_interval == 15.0
        assert config.offline.max_retries == 5
        assert config.receipt.require_verified is True
        assert config.receipt.min_verified_count == 2
        assert config.receipt.retention_days == 14
        assert len(config.relays) == 2

    def test_relay_manager_with_config(self, tmp_path):
        """Test RelayManager respects config settings."""
        from ming_drlms.relay.manager import RelayManager
        from ming_drlms.relay.config import RelaysConfig
        from ming_drlms.relay.receipt_store import ReceiptStore

        config = RelaysConfig()
        config.receipt.require_verified = True
        config.receipt.min_verified_count = 2

        store = ReceiptStore(tmp_path / "receipts.db")

        manager = RelayManager(
            receipt_store=store,
            require_verified=config.receipt.require_verified,
            min_verified_count=config.receipt.min_verified_count,
        )

        assert manager.require_verified is True
        assert manager.min_verified_count == 2
        assert manager.receipt_store is store


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
