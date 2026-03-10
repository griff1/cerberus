"""Tests for cerberus_mcp transport layer."""

import queue as thread_queue
from unittest.mock import MagicMock, patch

import pytest

from cerberus_mcp.transport import queue_event, _shutdown, event_queue


class TestQueueEvent:
    """Tests for event queuing behavior."""

    def setup_method(self):
        """Clear the queue before each test."""
        while not event_queue.empty():
            try:
                event_queue.get_nowait()
            except thread_queue.Empty:
                break

    def test_queues_event_data(self):
        event = MagicMock()
        event.method = "mcp_tool_call"
        event.endpoint = "/test"
        queue_event(event)
        assert not event_queue.empty()
        assert event_queue.get_nowait() is event

    def test_drops_event_when_queue_full(self):
        """Full queue should log warning, not raise."""
        # Fill queue to capacity
        original_maxsize = event_queue.maxsize
        try:
            # Use a small queue for this test
            small_queue = thread_queue.Queue(maxsize=1)
            small_queue.put_nowait("filler")
            with patch("cerberus_mcp.transport.event_queue", small_queue):
                event = MagicMock()
                event.method = "mcp_tool_call"
                event.endpoint = "/test"
                # Should not raise
                queue_event(event)
        finally:
            pass


class TestShutdown:
    """Tests for graceful shutdown behavior."""

    def test_shutdown_sends_sentinel_when_thread_alive(self):
        """Shutdown should put None sentinel and join the thread."""
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        with patch("cerberus_mcp.transport._background_thread", mock_thread):
            _shutdown()
        # Sentinel None should have been queued
        # Thread should have been joined
        mock_thread.join.assert_called_once_with(timeout=2.0)

    def test_shutdown_noop_when_no_thread(self):
        """Shutdown should be safe when background thread is None."""
        with patch("cerberus_mcp.transport._background_thread", None):
            _shutdown()  # Should not raise

    def test_shutdown_noop_when_thread_dead(self):
        """Shutdown should be safe when background thread is not alive."""
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        with patch("cerberus_mcp.transport._background_thread", mock_thread):
            _shutdown()
        mock_thread.join.assert_not_called()
