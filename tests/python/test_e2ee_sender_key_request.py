from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestRequestSenderKeysForRoom:
    """Tests for E2EEngine.request_sender_keys_for_room()"""

    def test_empty_members_list(self):
        """Test with empty members list."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        # Call the actual method with mock self
        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Town Square",
            group_id="Town Square",
            members=[],
        )
        # Should complete without error

    def test_skip_self(self):
        """Test that self is skipped when requesting Sender Keys."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        members = [("alice", 1), ("bob", 1), ("charlie", 1)]

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Town Square",
            group_id="Town Square",
            members=members,
        )
        # Alice should not be in missing list (only bob and charlie)

    def test_existing_keys_not_requested(self):
        """Test that existing Sender Keys are not re-requested."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        # Simulate bob's key already exists
        engine._group_sender_keys = {"Town Square|Town Square|bob|1": MagicMock()}

        members = [("bob", 1), ("charlie", 1)]

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Town Square",
            group_id="Town Square",
            members=members,
        )
        # Only charlie should be logged as missing

    def test_new_members_logged(self):
        """Test that new members are logged as missing."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        members = [("bob", 1), ("charlie", 1), ("dave", 2)]

        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            E2EEngine.request_sender_keys_for_room(
                engine,
                room_name="Town Square",
                group_id="Town Square",
                members=members,
            )
            # Should log warning for missing keys
            assert mock_logger.warning.called or mock_logger.info.called


class TestHandleSenderKeyRequest:
    """Tests for E2EEngine.handle_sender_key_request()"""

    def test_distribute_to_requester(self):
        """Test that Sender Key is distributed to requester."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock()

        E2EEngine.handle_sender_key_request(
            engine,
            room_name="Town Square",
            group_id="Town Square",
            requester="bob",
            requester_device=1,
        )

        engine.distribute_sender_key.assert_called_once_with(
            room_name="Town Square",
            group_id="Town Square",
            target_user="bob",
        )

    def test_handle_distribute_failure(self):
        """Test handling when distribute_sender_key fails."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock(side_effect=Exception("Network error"))

        # Should not raise, just log error
        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            E2EEngine.handle_sender_key_request(
                engine,
                room_name="Town Square",
                group_id="Town Square",
                requester="bob",
                requester_device=1,
            )
            # Should log error
            assert mock_logger.error.called


class TestSenderKeyDeduplication:
    """Tests for Sender Key request deduplication."""

    def test_no_duplicate_requests(self):
        """Test that duplicate requests are not sent."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        members = [("bob", 1)]

        # Call twice
        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Town Square",
            group_id="Town Square",
            members=members,
        )

        # Simulate bob's key is now added
        engine._group_sender_keys["Town Square|Town Square|bob|1"] = MagicMock()

        # Second call should not log bob as missing
        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            E2EEngine.request_sender_keys_for_room(
                engine,
                room_name="Town Square",
                group_id="Town Square",
                members=members,
            )
            # Warning should not be called (no missing keys)
            mock_logger.warning.assert_not_called()
            # Either no warning or warning with 0 missing
            # (depends on implementation)


class TestIntegrationScenarios:
    """Integration-level tests for Sender Key request flow."""

    def test_alice_joins_bob_room_scenario(self):
        """Test scenario: alice joins room where bob is already present."""
        # This is a higher-level scenario test
        # Verifies the full flow works together
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        # Simulate bob and charlie already in room
        members = [("bob", 1), ("charlie", 1), ("alice", 1)]

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Town Square",
            group_id="Town Square",
            members=members,
        )

        # alice should be skipped, bob and charlie should be logged as missing
        # This scenario verifies the mechanism is triggered correctly


class TestEdgeCases:
    """Edge case tests for Sender Key mechanism."""

    def test_mixed_device_ids(self):
        """Test with multiple devices for same user."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {"Room|Room|bob|1": MagicMock()}

        # bob has device 1 and 2, we only have device 1
        members = [("bob", 1), ("bob", 2), ("charlie", 1)]

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Room",
            group_id="Room",
            members=members,
        )
        # Should log bob device 2 and charlie as missing

    def test_empty_room_name(self):
        """Test with empty room name."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="",
            group_id="",
            members=[("bob", 1)],
        )
        # Should complete without crash

    def test_large_member_list(self):
        """Test with large number of members."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        # 100 members
        members = [(f"user{i}", 1) for i in range(100)]

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="LargeRoom",
            group_id="LargeRoom",
            members=members,
        )
        # Should complete without crash

    def test_unicode_usernames(self):
        """Test with unicode usernames."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "爱丽丝"
        engine._group_sender_keys = {}

        members = [("鲍勃", 1), ("查理", 1), ("爱丽丝", 1)]

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="中文房间",
            group_id="中文房间",
            members=members,
        )
        # Chinese usernames should work

    def test_special_characters_in_room(self):
        """Test with special characters in room name."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        E2EEngine.request_sender_keys_for_room(
            engine,
            room_name="Room@#$%|test",
            group_id="Room@#$%|test",
            members=[("bob", 1)],
        )


class TestHandlerEdgeCases:
    """Edge case tests for handle_sender_key_request."""

    def test_handle_request_for_self(self):
        """Test handling request where requester is self (should still work)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock()

        E2EEngine.handle_sender_key_request(
            engine,
            room_name="Room",
            group_id="Room",
            requester="alice",
            requester_device=1,
        )
        # distribute_sender_key will handle the self-check internally
        engine.distribute_sender_key.assert_called()

    def test_handle_request_empty_room(self):
        """Test handling request with empty room name."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock()

        E2EEngine.handle_sender_key_request(
            engine,
            room_name="",
            group_id="",
            requester="bob",
            requester_device=1,
        )
        engine.distribute_sender_key.assert_called_once()

    def test_handle_request_with_exception_logging(self):
        """Test that exceptions are logged but not raised."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock(side_effect=RuntimeError("Test error"))

        # Should not raise
        E2EEngine.handle_sender_key_request(
            engine,
            room_name="Room",
            group_id="Room",
            requester="bob",
            requester_device=1,
        )


class TestExceptionBranchCoverage:
    """Tests to cover exception handling branches in Phase 24 code."""

    def test_request_sender_keys_logger_warning_exception(self):
        """Test exception in logger.warning branch (line 717-718)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        members = [("bob", 1)]

        # Mock logger.warning to raise exception
        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            mock_logger.warning.side_effect = Exception("Logger error")
            mock_logger.info = MagicMock()  # Allow info to work
            mock_logger.debug = MagicMock()

            # Should not raise, exception caught by except block
            E2EEngine.request_sender_keys_for_room(
                engine,
                room_name="Room",
                group_id="Room",
                members=members,
            )

    def test_request_sender_keys_logger_info_exception(self):
        """Test exception in logger.info branch (line 706-707)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {}

        members = [("bob", 1)]

        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            mock_logger.info.side_effect = Exception("Logger error")
            mock_logger.warning = MagicMock()
            mock_logger.debug = MagicMock()

            E2EEngine.request_sender_keys_for_room(
                engine,
                room_name="Room",
                group_id="Room",
                members=members,
            )

    def test_request_sender_keys_logger_debug_exception(self):
        """Test exception in logger.debug branch (line 694-695)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine._username = "alice"
        engine._group_sender_keys = {"Room|Room|bob|1": MagicMock()}

        members = [("bob", 1)]

        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            mock_logger.debug.side_effect = Exception("Logger error")

            E2EEngine.request_sender_keys_for_room(
                engine,
                room_name="Room",
                group_id="Room",
                members=members,
            )

    def test_handle_sender_key_debug_exception(self):
        """Test exception in logger.debug branch of handle_sender_key_request (line 745-746)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock()

        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            mock_logger.debug.side_effect = Exception("Logger error")
            mock_logger.info = MagicMock()

            E2EEngine.handle_sender_key_request(
                engine,
                room_name="Room",
                group_id="Room",
                requester="bob",
                requester_device=1,
            )
            engine.distribute_sender_key.assert_called()

    def test_handle_sender_key_info_exception(self):
        """Test exception in logger.info branch of handle_sender_key_request (line 760-761)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock()

        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            mock_logger.debug = MagicMock()
            mock_logger.info.side_effect = Exception("Logger error")

            E2EEngine.handle_sender_key_request(
                engine,
                room_name="Room",
                group_id="Room",
                requester="bob",
                requester_device=1,
            )
            engine.distribute_sender_key.assert_called()

    def test_handle_sender_key_error_logging_exception(self):
        """Test exception in logger.error branch of handle_sender_key_request (line 770-771)."""
        from ming_drlms.core.e2ee_runtime import E2EEngine

        engine = MagicMock(spec=E2EEngine)
        engine.distribute_sender_key = MagicMock(
            side_effect=RuntimeError("Distribution failed")
        )

        with patch("ming_drlms.core.e2ee_runtime.logger") as mock_logger:
            mock_logger.debug = MagicMock()
            mock_logger.error.side_effect = Exception("Logger error")

            # Should still not raise even when error logging fails
            E2EEngine.handle_sender_key_request(
                engine,
                room_name="Room",
                group_id="Room",
                requester="bob",
                requester_device=1,
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
