from unittest.mock import Mock, patch
import logging

from ming_drlms.core.e2ee_runtime import E2EEngine
from ming_drlms.core.mproto_v2_client import SignalSenderKeyDistribution

logger = logging.getLogger(__name__)


class TestSenderKeyPullMechanism:
    """Unit tests for Sender Key Pull (Request) mechanism."""

    def test_request_sender_keys_for_room_sends_requests_for_missing(self):
        """Verify that request_sender_keys_for_room sends requests for missing keys."""
        # Setup mock engine
        mock_client = Mock()

        engine = Mock(spec=E2EEngine)
        engine._username = "Bob"
        engine._client = mock_client
        engine._group_sender_keys = {}  # No keys cached

        # Call the actual method with mocked internals
        # We need to test the real implementation
        with patch.object(E2EEngine, "__init__", lambda self, **kw: None):
            real_engine = E2EEngine()
            real_engine._username = "Bob"
            real_engine._client = mock_client
            real_engine._group_sender_keys = {}

            # Mock the client method
            mock_client.e2ee_sender_key_request = Mock(return_value=(0, "ok"))

            # Call the method under test
            members = [("Alice", 1), ("Charlie", 1)]
            real_engine.request_sender_keys_for_room(
                room_name="test_room",
                group_id="test_room",
                members=members,
            )

            # Verify requests were sent for both members
            assert mock_client.e2ee_sender_key_request.call_count == 2

            # Verify the distribution objects
            calls = mock_client.e2ee_sender_key_request.call_args_list
            target_users = [
                c[0][1] for c in calls
            ]  # Second positional arg is target_user
            assert "Alice" in target_users
            assert "Charlie" in target_users

    def test_request_sender_keys_skips_self(self):
        """Verify that request_sender_keys_for_room skips requesting from self."""
        with patch.object(E2EEngine, "__init__", lambda self, **kw: None):
            engine = E2EEngine()
            engine._username = "Bob"
            engine._client = Mock()
            engine._group_sender_keys = {}
            engine._client.e2ee_sender_key_request = Mock(return_value=(0, "ok"))

            members = [("Bob", 1), ("Alice", 1)]  # Bob is self
            engine.request_sender_keys_for_room(
                room_name="test_room",
                group_id="test_room",
                members=members,
            )

            # Should only send to Alice, not Bob
            assert engine._client.e2ee_sender_key_request.call_count == 1
            call_args = engine._client.e2ee_sender_key_request.call_args
            assert call_args[0][1] == "Alice"

    def test_request_sender_keys_skips_existing_keys(self):
        """Verify that request_sender_keys_for_room skips members with existing keys."""
        with patch.object(E2EEngine, "__init__", lambda self, **kw: None):
            engine = E2EEngine()
            engine._username = "Bob"
            engine._client = Mock()
            # Alice's key already cached
            engine._group_sender_keys = {"test_room|test_room|Alice|1": Mock()}
            engine._client.e2ee_sender_key_request = Mock(return_value=(0, "ok"))

            members = [("Alice", 1), ("Charlie", 1)]
            engine.request_sender_keys_for_room(
                room_name="test_room",
                group_id="test_room",
                members=members,
            )

            # Should only send to Charlie (Alice already has key)
            assert engine._client.e2ee_sender_key_request.call_count == 1
            call_args = engine._client.e2ee_sender_key_request.call_args
            assert call_args[0][1] == "Charlie"

    def test_handle_sender_key_request_redistributes_key(self):
        """Verify that handle_sender_key_request calls distribute_sender_key."""
        with patch.object(E2EEngine, "__init__", lambda self, **kw: None):
            engine = E2EEngine()
            engine._username = "Alice"
            engine.distribute_sender_key = Mock()

            engine.handle_sender_key_request(
                room_name="test_room",
                group_id="test_room",
                requester="Bob",
                requester_device=1,
            )

            # Verify distribute_sender_key was called for Bob
            engine.distribute_sender_key.assert_called_once_with(
                room_name="test_room",
                group_id="test_room",
                target_user="Bob",
            )

    def test_handle_sender_key_request_handles_errors_gracefully(self):
        """Verify that handle_sender_key_request doesn't crash on distribute errors."""
        with patch.object(E2EEngine, "__init__", lambda self, **kw: None):
            engine = E2EEngine()
            engine._username = "Alice"
            engine.distribute_sender_key = Mock(side_effect=Exception("Network error"))

            # Should not raise
            engine.handle_sender_key_request(
                room_name="test_room",
                group_id="test_room",
                requester="Bob",
                requester_device=1,
            )

            # Verify it was called despite error
            engine.distribute_sender_key.assert_called_once()


class TestMProtoV2ClientSenderKeyRequest:
    """Unit tests for MP2Client e2ee_sender_key_request method."""

    def test_e2ee_sender_key_request_sends_type_505(self):
        """Verify that e2ee_sender_key_request sends message type 505."""
        from ming_drlms.core.mproto_v2_client import MP2Client, msg_types

        with patch.object(MP2Client, "__init__", lambda self, *a, **kw: None):
            client = MP2Client("127.0.0.1", 15035)
            client.host = "127.0.0.1"
            client.port = 15035
            client._sock = Mock()
            client._token_store = Mock()

            # Mock ensure_access_token
            mock_record = Mock()
            mock_record.access_token = "test_token"
            client.ensure_access_token = Mock(return_value=mock_record)
            client.connect = Mock()
            client._require_socket = Mock(return_value=client._sock)

            # Mock write_frame and read_frame
            with patch("ming_drlms.core.mproto_v2_client.write_frame") as mock_write:
                with patch("ming_drlms.core.mproto_v2_client.read_frame") as mock_read:
                    # Setup response
                    mock_frame = Mock()
                    mock_frame.msg_type = msg_types.MSG_TYPE_E2EE_SENDER_KEY_REQUEST
                    mock_frame.payload = b"\x08\x00\x12\x02ok"  # code=0, message="ok"
                    mock_read.return_value = mock_frame

                    dist = SignalSenderKeyDistribution(
                        room_name="test_room",
                        group_id="test_room",
                        sender="Bob",
                        sender_device_id=1,
                        sender_registration_id=0,
                        distribution_message=b"",
                        sender_key_id=0,
                        sender_key_iteration=0,
                    )

                    try:
                        client.e2ee_sender_key_request("Bob", "Alice", dist)
                    except Exception:
                        pass  # May fail on protobuf parsing, but we check write_frame

                    # Verify write_frame was called with type 505
                    assert mock_write.called
                    call_args = mock_write.call_args
                    msg_type_sent = call_args[0][1]  # Second positional arg
                    assert msg_type_sent == 505, (
                        f"Expected type 505, got {msg_type_sent}"
                    )


class TestThreadedClientSenderKeyRequestCallback:
    """Test that threaded_client properly handles sender key requests."""

    def test_on_sender_key_request_callback_defined(self):
        """Verify the callback wrapper is properly defined in threaded_client."""
        # This is a structural test - verify the code exists
        import inspect
        from ming_drlms.core.threaded_client import RobustThreadedRoomClient

        source = inspect.getsource(RobustThreadedRoomClient._run_subscription_loop)
        assert (
            "on_sender_key_request" in source or "sender_key_request_callback" in source
        )
