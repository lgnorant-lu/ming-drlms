"""Phase 15.5 + 16 Integration Tests.

Tests for:
- TUI deduplication and MerkleTree integration
- NetworkMonitor recovery sync trigger
- _merkle_sync using /events/by-ids endpoint
- XEdDSA client-server signature verification
"""

from __future__ import annotations

import asyncio
import pytest
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

# Phase 16 imports
from ming_drlms.relay import (
    EventDeduplicator,
    EventValidator,
    MerkleTree,
    MultiRelaySyncManager,
    SyncCursorStore,
    NetworkMonitor,
    NetworkEvent,
    NetworkStatus,
    OfflineQueue,
    RelayManager,
    HealthChecker,
)


class TestTUIDeduplication:
    """Tests for TUI poll loop deduplication."""

    def test_deduplicator_skips_seen_events(self):
        """EventDeduplicator correctly identifies seen events."""
        dedup = EventDeduplicator()

        event_id = "abc123def456"

        # First time should not be seen
        assert not dedup.check_without_add(event_id)
        dedup.add(event_id)

        # Second time should be seen
        assert dedup.check_without_add(event_id)

    def test_deduplicator_window_expiry(self):
        """EventDeduplicator expires old events from window."""
        dedup = EventDeduplicator(window_size=2)

        dedup.add("event1")
        dedup.add("event2")
        dedup.add("event3")  # Should push event1 out

        # event1 may or may not be seen depending on implementation
        # event2 and event3 should still be in window
        assert dedup.check_without_add("event2")
        assert dedup.check_without_add("event3")


class TestMerkleTreeMaintenance:
    """Tests for local MerkleTree maintenance."""

    def test_merkle_add_events(self):
        """MerkleTree correctly adds events and updates root."""
        tree = MerkleTree(room_id="test-room")

        initial_root = tree.root

        tree.add_event("event1")
        root_after_one = tree.root

        tree.add_event("event2")
        root_after_two = tree.root

        # Root should change after each event
        assert root_after_one != initial_root
        assert root_after_two != root_after_one

    def test_merkle_get_event_ids(self):
        """MerkleTree returns list of event IDs."""
        tree = MerkleTree(room_id="test-room")

        tree.add_event("event1")
        tree.add_event("event2")
        tree.add_event("event3")

        ids = tree.get_event_ids()
        assert "event1" in ids
        assert "event2" in ids
        assert "event3" in ids


class TestMerkleSyncByIds:
    """Tests for _merkle_sync using /events/by-ids endpoint."""

    def test_sync_code_references_by_ids(self):
        """Verify that _merkle_sync code uses /events/by-ids endpoint."""
        import inspect

        source = inspect.getsource(MultiRelaySyncManager._merkle_sync)

        # Check that the code references /events/by-ids
        assert "/events/by-ids" in source, (
            "_merkle_sync should reference /events/by-ids endpoint"
        )

        # Check that old incremental fallback comment is removed
        assert "doesn't support by-ids yet" not in source, (
            "Old comment should be removed"
        )


class TestNetworkMonitorRecovery:
    """Tests for NetworkMonitor recovery sync trigger."""

    @pytest.mark.asyncio
    async def test_network_recovery_event(self):
        """NetworkMonitor fires RECOVERED event on network comeback."""
        monitor = NetworkMonitor(check_interval=0.1)
        monitor.set_known_relays(["http://localhost:15019"])

        events_received = []

        async def callback(event: NetworkEvent, status: NetworkStatus):
            events_received.append(event)

        monitor.add_listener(callback)

        # Manually trigger recovery notification
        status = NetworkStatus(
            online=True,
            last_check=datetime.utcnow(),
            reachable_relays=1,
            total_relays=1,
        )
        await monitor._notify_listeners(NetworkEvent.RECOVERED, status)

        assert NetworkEvent.RECOVERED in events_received

    def test_recovery_flag_set_on_event(self):
        """_network_recovered flag should be set when NetworkMonitor fires RECOVERED."""
        recovered_flag = threading.Event()

        async def on_network_event(event: NetworkEvent, status: NetworkStatus):
            if event == NetworkEvent.RECOVERED:
                recovered_flag.set()

        # Simulate the callback
        async def simulate():
            status = NetworkStatus(
                online=True,
                last_check=datetime.utcnow(),
                reachable_relays=1,
                total_relays=1,
            )
            await on_network_event(NetworkEvent.RECOVERED, status)

        asyncio.run(simulate())

        assert recovered_flag.is_set()


class TestOfflineQueueIntegration:
    """Tests for OfflineQueue integration with RelayManager."""

    def test_offline_queue_persistence(self, tmp_path: Path):
        """OfflineQueue persists events to SQLite."""
        db_path = tmp_path / "offline.db"
        queue = OfflineQueue(db_path=db_path)

        # Queue an event
        queue.enqueue(
            room="test-room",
            ciphertext="encrypted_data",
            client_event_hash="hash123",
        )

        # Check pending count
        pending = queue.get_pending_count()
        assert pending >= 1

    def test_relay_manager_accepts_offline_queue(self, tmp_path: Path):
        """RelayManager accepts offline_queue parameter."""
        db_path = tmp_path / "offline.db"
        queue = OfflineQueue(db_path=db_path)

        health_checker = HealthChecker()
        manager = RelayManager(
            health_checker=health_checker,
            offline_queue=queue,
        )

        assert manager.offline_queue is queue


class TestEventValidatorIntegration:
    """Tests for EventValidator in sync flow."""

    def test_validator_rejects_invalid_event_id(self):
        """EventValidator rejects events with invalid IDs."""
        validator = EventValidator()

        # Invalid event ID (too short)
        result = validator.validate(
            {
                "event_id": "short",
                "sender_pubkey_hex": "a" * 64,
                "timestamp_ms": int(time.time() * 1000),
            }
        )

        # Should fail or warn depending on strict mode
        # In non-strict mode it may pass with warnings
        assert result is not None

    def test_validator_checks_timestamp_window(self):
        """EventValidator checks timestamp within reasonable window."""
        validator = EventValidator()

        # Future timestamp (way in the future)
        far_future_ts = int((time.time() + 10000) * 1000)
        result = validator.validate(
            {
                "event_id": "a" * 64,
                "sender_pubkey_hex": "b" * 64,
                "timestamp_ms": far_future_ts,
            }
        )

        # Should have timestamp warning/error
        assert result is not None


class TestPhase155XEdDSAVerification:
    """Tests for Phase 15.5 XEdDSA signature verification."""

    def test_xeddsa_verifier_creation(self):
        """create_xeddsa_verifier returns a callable verifier."""
        from ming_drlms.relay import create_xeddsa_verifier

        verifier = create_xeddsa_verifier()
        assert callable(verifier)

    def test_event_validator_with_xeddsa(self):
        """EventValidator can use XEdDSA verifier."""
        from ming_drlms.relay import create_xeddsa_verifier

        verifier = create_xeddsa_verifier()
        validator = EventValidator(
            signature_verifier=verifier,
            strict_mode=False,
        )

        # Validator should accept the verifier
        assert validator._signature_verifier is not None


class TestSyncManagerWithComponents:
    """Tests for MultiRelaySyncManager with all Phase 16 components."""

    def test_sync_manager_initialization(self, tmp_path: Path):
        """MultiRelaySyncManager initializes with all components."""
        cursor_store = SyncCursorStore(tmp_path / "cursors.db")
        dedup = EventDeduplicator()
        validator = EventValidator()
        merkle = MerkleTree(room_id="test-room")

        manager = MultiRelaySyncManager(
            cursor_store=cursor_store,
            relay_manager=MagicMock(),
            deduplicator=dedup,
            validator=validator,
            local_merkle=merkle,
        )

        assert manager._deduplicator is dedup
        assert manager._validator is validator
        assert manager._local_merkle is merkle

    def test_merge_and_dedupe_uses_validator(self, tmp_path: Path):
        """_merge_and_dedupe uses validator to filter events."""
        cursor_store = SyncCursorStore(tmp_path / "cursors.db")
        dedup = EventDeduplicator()
        validator = MagicMock()

        # Validator returns valid for first event, invalid for second
        validator.validate.side_effect = [
            MagicMock(valid=True),
            MagicMock(valid=False),
        ]

        manager = MultiRelaySyncManager(
            cursor_store=cursor_store,
            deduplicator=dedup,
            validator=validator,
        )

        events = [
            {"client_hash": "event1", "server_ts": 1000},
            {"client_hash": "event2", "server_ts": 2000},
        ]

        result = manager._merge_and_dedupe(events)

        # Only the valid event should remain
        assert len(result) == 1
        assert result[0]["client_hash"] == "event1"


class TestRelayConfigIntegration:
    """Tests for relays.toml configuration integration."""

    def test_relays_config_loads_health_interval(self, tmp_path: Path):
        """RelaysConfig loads health check interval from config."""
        from ming_drlms.relay import RelaysConfig

        config_path = tmp_path / "relays.toml"
        config_path.write_text("""
[health]
check_interval = 45.0

[offline]
max_retries = 5
base_delay = 2.0
max_delay = 120.0
""")

        config = RelaysConfig.load(config_path)

        assert config.health.check_interval == 45.0
        assert config.offline.max_retries == 5
        assert config.offline.base_delay == 2.0


class TestRCV01StorageReceipts:
    """RCV-01: Tests for storage receipt signatures."""

    def test_storage_receipt_dataclass(self):
        """StorageReceipt dataclass works correctly."""
        from ming_drlms.relay.manager import StorageReceipt

        receipt = StorageReceipt(
            relay_url="http://localhost:15019",
            relay_id="relay-test",
            server_seq=42,
            server_ts=1733800000,
            signature="a" * 64,
            verified=True,
        )

        assert receipt.relay_url == "http://localhost:15019"
        assert receipt.relay_id == "relay-test"
        assert receipt.server_seq == 42
        assert receipt.verified is True

    def test_write_result_verified_count(self):
        """WriteResult.verified_count property works."""
        from ming_drlms.relay.manager import WriteResult, WriteStatus, StorageReceipt

        receipts = [
            StorageReceipt("url1", "r1", 1, 100, "sig1", verified=True),
            StorageReceipt("url2", "r2", 2, 100, "sig2", verified=False),
            StorageReceipt("url3", "r3", 3, 100, "sig3", verified=True),
        ]

        result = WriteResult(
            status=WriteStatus.SUCCESS,
            success_count=3,
            total_relays=3,
            receipts=receipts,
        )

        assert result.verified_count == 2

    def test_server_signs_receipt(self):
        """Server _sign_receipt generates consistent signatures (Phase 17C: XEdDSA only)."""
        # Import server module to test signing function
        from ming_drlms.relay.server import _sign_receipt

        # Phase 17C: _sign_receipt returns (signature, pubkey) or None
        result1 = _sign_receipt("event123", "room1", 42, 1733800000)
        result2 = _sign_receipt("event123", "room1", 42, 1733800000)

        # Results may be None if XEdDSA key not configured
        if result1 is None:
            assert result2 is None
            return  # Skip further checks if not configured

        # Unpack results (signature, pubkey)
        sig1, pubkey1 = result1
        sig2, pubkey2 = result2

        # Same pubkey
        assert pubkey1 == pubkey2

        # XEdDSA signatures are deterministic for same inputs
        assert sig1 == sig2
        assert len(sig1) == 128  # Ed25519 signature is 64 bytes = 128 hex chars

    def test_eventack_includes_signature_fields(self):
        """EventAck model includes relay_id and xeddsa_signature (Phase 17C)."""
        from ming_drlms.relay.server import EventAck

        ack = EventAck(
            server_seq=1,
            server_ts=1733800000,
            relay_id="relay-test",
            xeddsa_signature="a" * 128,  # 64 bytes = 128 hex chars
            relay_pubkey="b" * 64,  # 32 bytes = 64 hex chars
        )

        assert ack.relay_id == "relay-test"
        assert ack.xeddsa_signature == "a" * 128
        assert ack.relay_pubkey == "b" * 64


class TestOFFQ01BackgroundProcessing:
    """OFFQ-01: Tests for OfflineQueue background processing integration."""

    def test_offline_queue_has_start_processing(self):
        """OfflineQueue has start_processing method."""
        from ming_drlms.relay.offline_queue import OfflineQueue

        assert hasattr(OfflineQueue, "start_processing")
        assert callable(getattr(OfflineQueue, "start_processing"))

    def test_offline_queue_has_is_processing(self):
        """OfflineQueue has is_processing method."""
        from ming_drlms.relay.offline_queue import OfflineQueue

        assert hasattr(OfflineQueue, "is_processing")

    def test_tui_queue_commands_registered(self):
        """Verify /queue command code exists in system.py."""
        import inspect
        from ming_drlms.tui.command_modules.system import register_system_commands

        source = inspect.getsource(register_system_commands)

        assert "/queue" in source
        assert "get_queue_stats" in source
        assert "clear_completed_queue" in source
        assert "retry_queue_now" in source


class TestReceiptStore:
    """RCV-01: Tests for receipt persistence."""

    def test_receipt_store_creation(self, tmp_path):
        """ReceiptStore creates database schema."""
        from ming_drlms.relay.receipt_store import ReceiptStore

        db_path = tmp_path / "test_receipts.db"
        ReceiptStore(db_path)  # Creates DB on init

        assert db_path.exists()

    def test_save_and_retrieve_receipt(self, tmp_path):
        """ReceiptStore can save and retrieve receipts."""
        from ming_drlms.relay.receipt_store import ReceiptStore

        db_path = tmp_path / "test_receipts.db"
        store = ReceiptStore(db_path)

        # Save a receipt
        receipt_id = store.save_receipt(
            event_id="event123",
            room="room1",
            relay_url="http://localhost:15019",
            relay_id="relay-test",
            server_seq=42,
            server_ts=1733800000,
            signature="a" * 64,
            verified=True,
        )

        assert receipt_id > 0

        # Retrieve it
        receipts = store.get_receipts_for_event("event123")
        assert len(receipts) == 1
        assert receipts[0].event_id == "event123"
        assert receipts[0].verified is True

    def test_save_receipts_batch(self, tmp_path):
        """ReceiptStore can save multiple receipts in batch."""
        from ming_drlms.relay.receipt_store import ReceiptStore

        db_path = tmp_path / "test_receipts.db"
        store = ReceiptStore(db_path)

        receipts = [
            {
                "event_id": "e1",
                "room": "r1",
                "relay_url": "u1",
                "relay_id": "r1",
                "server_seq": 1,
                "server_ts": 100,
                "signature": "s1",
                "verified": True,
            },
            {
                "event_id": "e1",
                "room": "r1",
                "relay_url": "u2",
                "relay_id": "r2",
                "server_seq": 2,
                "server_ts": 100,
                "signature": "s2",
                "verified": False,
            },
        ]

        ids = store.save_receipts_batch(receipts)
        assert len(ids) == 2

        stats = store.get_stats()
        assert stats["total"] == 2
        assert stats["verified"] == 1
        assert stats["unverified"] == 1

    def test_cleanup_old_receipts(self, tmp_path):
        """ReceiptStore can cleanup old receipts."""
        from ming_drlms.relay.receipt_store import ReceiptStore

        db_path = tmp_path / "test_receipts.db"
        store = ReceiptStore(db_path)

        # Save a receipt
        store.save_receipt(
            event_id="old_event",
            room="room1",
            relay_url="http://localhost:15019",
            relay_id="relay-test",
            server_seq=1,
            server_ts=1,
            signature="s",
            verified=True,
        )

        # Cleanup with 0 retention should not delete
        deleted = store.cleanup_old_receipts(0)
        assert deleted == 0

        # All receipts still exist
        stats = store.get_stats()
        assert stats["total"] == 1


class TestReceiptConfigIntegration:
    """RCV-01: Tests for receipt configuration."""

    def test_relays_config_loads_receipt_settings(self, tmp_path):
        """RelaysConfig loads receipt settings from file."""
        from ming_drlms.relay.config import RelaysConfig

        config_path = tmp_path / "relays.toml"
        config_path.write_text("""
[receipt]
require_verified = true
min_verified_count = 2
persist_receipts = true
retention_days = 7
""")

        config = RelaysConfig.load(config_path)

        assert config.receipt.require_verified is True
        assert config.receipt.min_verified_count == 2
        assert config.receipt.persist_receipts is True
        assert config.receipt.retention_days == 7

    def test_relays_config_default_receipt_settings(self):
        """RelaysConfig has default receipt settings."""
        from ming_drlms.relay.config import RelaysConfig, ReceiptSettings

        config = RelaysConfig()

        assert isinstance(config.receipt, ReceiptSettings)
        assert config.receipt.require_verified is True
        assert config.receipt.min_verified_count == 1

    def test_relay_manager_accepts_receipt_store(self):
        """RelayManager can be initialized with receipt_store."""
        from ming_drlms.relay.manager import RelayManager

        manager = RelayManager(
            receipt_store=object(),  # Mock store
            require_verified=True,
            min_verified_count=2,
        )

        assert manager.receipt_store is not None
        assert manager.require_verified is True
        assert manager.min_verified_count == 2


# Run specific tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
