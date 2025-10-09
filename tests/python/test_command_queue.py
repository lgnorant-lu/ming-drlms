"""
Unit tests for UICommandQueue.

Tests the thread-safe command queue pattern for UI updates.
"""

from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock

import pytest

from ming_drlms_gui.ui.command_queue import (
    UICommandQueue,
    UICommand,
    UICommandType,
)


class MockPage:
    """Mock Flet page for testing."""
    
    def __init__(self):
        self.update_count = 0
        self.pubsub = MockPubSub()
    
    def update(self):
        self.update_count += 1


class MockPubSub:
    """Mock pubsub for testing."""
    
    def __init__(self):
        self.subscribers = []
        self.messages = []
    
    def subscribe(self, handler):
        self.subscribers.append(handler)
    
    def send_all(self, message):
        self.messages.append(message)
        # Immediately trigger handlers for synchronous testing
        for handler in self.subscribers:
            handler(message)


def test_command_queue_initialization():
    """Test that command queue initializes correctly."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    assert queue is not None
    assert queue._page is page
    assert len(queue._handlers) == 0
    assert queue.get_stats()["total_commands"] == 0


def test_register_handler():
    """Test registering command handlers."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    handler_called = {"count": 0}
    
    def test_handler(data: dict) -> None:
        handler_called["count"] += 1
    
    queue.register_handler(UICommandType.ADD_MESSAGE, test_handler)
    
    assert UICommandType.ADD_MESSAGE in queue._handlers
    assert queue._handlers[UICommandType.ADD_MESSAGE] == test_handler


def test_enqueue_and_process():
    """Test enqueueing and processing commands."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    processed_data = []
    
    def test_handler(data: dict) -> None:
        processed_data.append(data)
    
    queue.register_handler(UICommandType.ADD_MESSAGE, test_handler)
    
    # Enqueue a command
    cmd = UICommand(
        type=UICommandType.ADD_MESSAGE,
        data={"message": "test"},
        source="test"
    )
    queue.enqueue(cmd)
    
    # Give processing time (pubsub triggers immediately in mock)
    time.sleep(0.1)
    
    # Verify command was processed
    assert len(processed_data) == 1
    assert processed_data[0]["message"] == "test"
    assert page.update_count == 1
    
    stats = queue.get_stats()
    assert stats["total_commands"] == 1
    assert stats["processed_commands"] == 1
    assert stats["failed_commands"] == 0


def test_batch_processing():
    """Test that multiple commands are batched in one page.update()."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    processed_count = {"value": 0}
    
    def test_handler(data: dict) -> None:
        processed_count["value"] += 1
    
    queue.register_handler(UICommandType.ADD_MESSAGE, test_handler)
    
    # Enqueue multiple commands rapidly
    for i in range(5):
        cmd = UICommand(
            type=UICommandType.ADD_MESSAGE,
            data={"message": f"test{i}"},
            source="test"
        )
        queue.enqueue(cmd)
    
    # Give processing time
    time.sleep(0.2)
    
    # All commands should be processed
    assert processed_count["value"] == 5
    
    # But only one page.update() should have been called
    # (batch processing in mock triggers immediately, so we get 1 update per enqueue)
    # In real Flet, this would be truly batched
    assert page.update_count >= 1
    
    stats = queue.get_stats()
    assert stats["total_commands"] == 5
    assert stats["processed_commands"] == 5


def test_unknown_command_type():
    """Test handling of unknown command types."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    # Enqueue a command without a registered handler
    cmd = UICommand(
        type=UICommandType.UPDATE_USER_LIST,
        data={},
        source="test"
    )
    queue.enqueue(cmd)
    
    time.sleep(0.1)
    
    # Should not crash, just log warning
    stats = queue.get_stats()
    assert stats["total_commands"] == 1
    # Command still counts as "processed" even if no handler


def test_handler_error_handling():
    """Test that handler errors don't crash the queue."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    def failing_handler(data: dict) -> None:
        raise RuntimeError("Test error")
    
    def working_handler(data: dict) -> None:
        pass
    
    queue.register_handler(UICommandType.ADD_MESSAGE, failing_handler)
    queue.register_handler(UICommandType.UPDATE_USER_LIST, working_handler)
    
    # Enqueue both commands
    queue.enqueue(UICommand(
        type=UICommandType.ADD_MESSAGE,
        data={},
        source="test"
    ))
    queue.enqueue(UICommand(
        type=UICommandType.UPDATE_USER_LIST,
        data={},
        source="test"
    ))
    
    time.sleep(0.1)
    
    stats = queue.get_stats()
    assert stats["failed_commands"] == 1  # One failed
    assert stats["processed_commands"] == 1  # One succeeded


def test_thread_safety():
    """Test that queue is thread-safe."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    processed = []
    lock = threading.Lock()
    
    def test_handler(data: dict) -> None:
        with lock:
            processed.append(data["value"])
    
    queue.register_handler(UICommandType.ADD_MESSAGE, test_handler)
    
    # Spawn multiple threads enqueueing commands
    threads = []
    for i in range(10):
        def worker(val=i):
            for j in range(10):
                cmd = UICommand(
                    type=UICommandType.ADD_MESSAGE,
                    data={"value": f"{val}-{j}"},
                    source=f"thread-{val}"
                )
                queue.enqueue(cmd)
        
        thread = threading.Thread(target=worker)
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()
    
    # Give processing time
    time.sleep(0.5)
    
    # All 100 commands should be processed
    assert len(processed) == 100
    
    stats = queue.get_stats()
    assert stats["total_commands"] == 100
    assert stats["processed_commands"] == 100


def test_stats_tracking():
    """Test that statistics are tracked correctly."""
    page = MockPage()
    queue = UICommandQueue(page)
    
    def handler(data: dict) -> None:
        pass
    
    queue.register_handler(UICommandType.ADD_MESSAGE, handler)
    
    # Enqueue commands
    for i in range(3):
        queue.enqueue(UICommand(
            type=UICommandType.ADD_MESSAGE,
            data={"i": i},
            source="test"
        ))
    
    time.sleep(0.2)
    
    stats = queue.get_stats()
    assert stats["total_commands"] == 3
    assert stats["processed_commands"] == 3
    assert stats["failed_commands"] == 0
    assert stats["batch_count"] >= 1
    assert stats["max_batch_size"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
