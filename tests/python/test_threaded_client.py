"""Tests for threaded_client module."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator
from unittest import mock

import pytest

from ming_drlms.core.threaded_client import (
    ThreadedRoomClient,
)
from ming_drlms.core.mproto_v2_client import RoomEvent, MP2Error


@pytest.fixture
def mock_mp2_client():
    """Fixture providing a mocked MP2Client."""
    with mock.patch("ming_drlms.core.threaded_client.MP2Client") as MockClient:
        yield MockClient


def test_threaded_client_initialization():
    """Test that ThreadedRoomClient can be initialized with correct parameters."""
    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
        since_id=100,
        timeout=15.0,
    )

    assert client.host == "127.0.0.1"
    assert client.port == 8080
    assert client.username == "alice"
    assert client.room == "general"
    assert client.since_id == 100
    assert client.timeout == 15.0
    assert not client.is_running()


def test_start_creates_daemon_thread(mock_mp2_client):
    """Test that start() creates a daemon thread."""

    # Create a generator that yields one item then waits
    def slow_generator() -> Generator[RoomEvent, None, None]:
        yield RoomEvent(
            room_name="general",
            event_id=1,
            payload=b"test",
            display_token="token",
        )
        time.sleep(1.0)  # Keep thread alive

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = slow_generator()

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    event_callback = mock.Mock()
    client.start(on_event=event_callback)

    # Give thread time to start
    time.sleep(0.1)

    assert client.is_running()
    assert client._thread is not None
    assert client._thread.daemon is True
    assert client._thread.name.startswith("ThreadedRoomClient-")

    client.stop()


def test_start_raises_if_already_running(mock_mp2_client):
    """Test that start() raises RuntimeError if already running."""

    # Create a blocking generator to keep the thread alive
    def blocking_generator() -> Generator[RoomEvent, None, None]:
        while True:
            time.sleep(0.1)
            yield RoomEvent(
                room_name="general",
                event_id=1,
                payload=b"test",
                display_token="token",
            )

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = blocking_generator()

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    event_callback = mock.Mock()
    client.start(on_event=event_callback)

    try:
        with pytest.raises(RuntimeError, match="already running"):
            client.start(on_event=event_callback)
    finally:
        client.stop()


def test_event_callback_invoked_on_message(mock_mp2_client):
    """Test that on_event callback is invoked when events are received."""
    test_event = RoomEvent(
        room_name="general",
        event_id=42,
        payload=b"Hello, World!",
        display_token="abc123",
    )

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = iter([test_event])

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    received_events = []

    def on_event(event: RoomEvent):
        received_events.append(event)

    client.start(on_event=on_event)

    # Wait for the thread to process the event
    time.sleep(0.2)

    client.stop()

    assert len(received_events) == 1
    assert received_events[0].event_id == 42
    assert received_events[0].payload == b"Hello, World!"


def test_multiple_events_callback(mock_mp2_client):
    """Test that multiple events are correctly dispatched."""
    events = [
        RoomEvent(
            room_name="general",
            event_id=i,
            payload=f"msg{i}".encode(),
            display_token=f"t{i}",
        )
        for i in range(5)
    ]

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = iter(events)

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    received_events = []

    def on_event(event: RoomEvent):
        received_events.append(event)

    client.start(on_event=on_event)
    time.sleep(0.3)  # Give thread time to process all events
    client.stop()

    assert len(received_events) == 5
    for i, event in enumerate(received_events):
        assert event.event_id == i
        assert event.payload == f"msg{i}".encode()


def test_error_callback_invoked_on_exception(mock_mp2_client):
    """Test that on_error callback is invoked when an exception occurs."""
    test_error = MP2Error("Connection failed")

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.side_effect = test_error

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    received_errors = []

    def on_error(exc: Exception):
        received_errors.append(exc)

    event_callback = mock.Mock()
    client.start(on_event=event_callback, on_error=on_error)

    time.sleep(0.2)  # Wait for error to propagate
    client.stop()

    assert len(received_errors) == 1
    assert isinstance(received_errors[0], MP2Error)
    assert str(received_errors[0]) == "Connection failed"


def test_callback_exception_does_not_crash_thread(mock_mp2_client):
    """Test that exceptions in on_event callback don't crash the subscription loop."""
    events = [
        RoomEvent(
            room_name="general",
            event_id=i,
            payload=f"msg{i}".encode(),
            display_token=f"t{i}",
        )
        for i in range(3)
    ]

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = iter(events)

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    received_events = []
    received_errors = []

    def on_event(event: RoomEvent):
        if event.event_id == 1:
            raise ValueError("Callback error")
        received_events.append(event)

    def on_error(exc: Exception):
        received_errors.append(exc)

    client.start(on_event=on_event, on_error=on_error)
    time.sleep(0.3)
    client.stop()

    # Events 0 and 2 should be received, event 1 should trigger error callback
    assert len(received_events) == 2
    assert received_events[0].event_id == 0
    assert received_events[1].event_id == 2

    assert len(received_errors) == 1
    assert isinstance(received_errors[0], ValueError)


def test_stop_terminates_thread(mock_mp2_client):
    """Test that stop() properly terminates the subscription thread."""

    # Create a generator that yields indefinitely
    def infinite_generator() -> Generator[RoomEvent, None, None]:
        i = 0
        while True:
            yield RoomEvent(
                room_name="general",
                event_id=i,
                payload=f"msg{i}".encode(),
                display_token=f"t{i}",
            )
            i += 1
            time.sleep(0.05)

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = infinite_generator()

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    event_callback = mock.Mock()
    client.start(on_event=event_callback)

    assert client.is_running()

    client.stop(timeout=2.0)

    assert not client.is_running()
    assert mock_instance.close.called


def test_stop_does_nothing_if_not_running(mock_mp2_client):
    """Test that stop() is safe to call when client is not running."""
    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    # Should not raise
    client.stop()

    assert not client.is_running()


def test_client_context_manager_usage(mock_mp2_client):
    """Test that MP2Client is used as a context manager."""
    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = iter([])

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    event_callback = mock.Mock()
    client.start(on_event=event_callback)

    time.sleep(0.2)
    client.stop()

    # Verify that __enter__ and __exit__ were called
    mock_instance.__enter__.assert_called_once()
    mock_instance.__exit__.assert_called_once()


def test_token_store_path_integration(mock_mp2_client, tmp_path: Path):
    """Test that token_store_path is properly passed to TokenStore."""
    token_file = tmp_path / "tokens.json"

    with mock.patch("ming_drlms.core.threaded_client.TokenStore") as MockTokenStore:
        mock_instance = mock_mp2_client.return_value
        mock_instance.subscribe.return_value = iter([])

        client = ThreadedRoomClient(
            host="127.0.0.1",
            port=8080,
            username="alice",
            room="general",
            token_store_path=token_file,
        )

        event_callback = mock.Mock()
        client.start(on_event=event_callback)

        time.sleep(0.2)
        client.stop()

        # Verify TokenStore was initialized with the correct path
        MockTokenStore.assert_called_once_with(token_file)


def test_on_error_callback_raises_exception(mock_mp2_client):
    """Test that exceptions in on_error callback don't crash the thread."""
    test_error = MP2Error("Network failure")

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.side_effect = test_error

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    error_call_count = [0]

    def faulty_error_handler(exc: Exception):
        error_call_count[0] += 1
        raise RuntimeError("Error handler crashed!")

    event_callback = mock.Mock()
    client.start(on_event=event_callback, on_error=faulty_error_handler)

    time.sleep(0.2)
    client.stop()

    # Error handler should have been called once (then crashed, but thread survived)
    assert error_call_count[0] == 1


def test_unexpected_exception_in_subscription_loop(mock_mp2_client):
    """Test that unexpected exceptions are handled gracefully."""
    # Simulate a completely unexpected error type
    unexpected_error = KeyError("Unexpected error in subscription")

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.side_effect = unexpected_error

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    received_errors = []

    def on_error(exc: Exception):
        received_errors.append(exc)

    event_callback = mock.Mock()
    client.start(on_event=event_callback, on_error=on_error)

    time.sleep(0.2)
    client.stop()

    # The unexpected exception should be caught and passed to on_error
    assert len(received_errors) == 1
    assert isinstance(received_errors[0], KeyError)


def test_socket_close_exception_during_cleanup(mock_mp2_client):
    """Test that exceptions during socket cleanup are suppressed."""
    # Simulate socket.close() raising an exception
    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = iter([])
    mock_instance.close.side_effect = OSError("Socket already closed")

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    event_callback = mock.Mock()
    client.start(on_event=event_callback)

    time.sleep(0.2)

    # stop() should not raise even if close() fails
    client.stop()

    assert not client.is_running()


def test_stop_event_checked_during_iteration(mock_mp2_client):
    """Test that stop_event is properly checked during event iteration."""
    events_yielded = []

    def long_running_generator() -> Generator[RoomEvent, None, None]:
        for i in range(100):
            events_yielded.append(i)
            yield RoomEvent(
                room_name="general",
                event_id=i,
                payload=f"msg{i}".encode(),
                display_token=f"t{i}",
            )
            time.sleep(0.01)

    mock_instance = mock_mp2_client.return_value
    mock_instance.subscribe.return_value = long_running_generator()

    client = ThreadedRoomClient(
        host="127.0.0.1",
        port=8080,
        username="alice",
        room="general",
    )

    received_events = []

    def on_event(event: RoomEvent):
        received_events.append(event)

    client.start(on_event=on_event)

    # Let it process a few events
    time.sleep(0.15)

    # Stop should interrupt the loop
    client.stop(timeout=2.0)

    # Should have processed some but not all 100 events
    assert 0 < len(received_events) < 100
    assert not client.is_running()
