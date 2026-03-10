"""
Cerberus MCP Transport Layer

WebSocket client for sending MCP events to the Cerberus event_ingest backend.
Uses the same queue + background thread + async event loop pattern as
cerberus_django middleware.
"""

import asyncio
import atexit
import json
import logging
import threading
import queue as thread_queue
import websockets

from .config import DEBUG_ENABLED, EVENT_QUEUE_MAXSIZE

logger = logging.getLogger(__name__)

# Thread-safe queue for MCP events (bounded to prevent unbounded memory growth)
event_queue = thread_queue.Queue(maxsize=EVENT_QUEUE_MAXSIZE)

# Background thread management
_background_thread = None
_thread_lock = threading.Lock()


class AsyncWebSocketClient:
    """WebSocket client for sending events to the backend.

    This client is used within the background thread's event loop,
    so it can safely use asyncio primitives.
    """

    def __init__(self, ws_url, api_key, client_id):
        self.ws_url = ws_url
        self.api_key = api_key
        self.client_id = client_id
        self.websocket = None
        self._async_lock = None  # Created on first use within the event loop thread

    async def connect(self):
        """Establish WebSocket connection to the backend."""
        try:
            if DEBUG_ENABLED:
                logger.info(f"[CerberusMCP] Connecting to WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url)
            if DEBUG_ENABLED:
                logger.info("[CerberusMCP] WebSocket connected successfully")
        except Exception as e:
            self.websocket = None
            logger.error(f"[CerberusMCP] Failed to connect to WebSocket: {e}")

    async def send(self, event_data):
        """Send event data to backend via WebSocket.

        Args:
            event_data: MCPEventData object to send
        """
        # Create lock on first use — safe because the event loop is
        # single-threaded so no concurrent coroutine can interleave here
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            # Connect if not already connected
            if self.websocket is None:
                await self.connect()

            if self.websocket:
                try:
                    # Format data as expected by backend (same as cerberus_django)
                    # api_key: client credential used by event_ingest for authentication
                    # token: duplicated from event_data for backward compat; backend uses api_key
                    payload = {
                        'api_key': self.api_key,
                        'client_id': self.client_id,
                        'token': event_data.token,
                        'remote_addr': event_data.source_ip,
                        'endpoint': event_data.endpoint,
                        'scheme': event_data.scheme,
                        'method': event_data.method,
                        'timestamp': event_data.timestamp,
                        'custom_data': event_data.custom_data,
                        'headers': event_data.headers,
                        'query_params': event_data.query_params,
                        'body': event_data.body,
                        'user_agent': event_data.user_agent,
                        'user_id': event_data.user_id,
                    }

                    json_data = json.dumps(payload)

                    if DEBUG_ENABLED:
                        logger.info(
                            f"[CerberusMCP] Sending event: "
                            f"{event_data.method} {event_data.endpoint} ({len(json_data)} bytes)"
                        )

                    await self.websocket.send(json_data)

                    # Wait for acknowledgment
                    response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)

                    if DEBUG_ENABLED:
                        logger.info(f"[CerberusMCP] Backend acknowledged ({len(response)} bytes)")

                except asyncio.TimeoutError:
                    logger.warning("[CerberusMCP] Timeout waiting for backend response")
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("[CerberusMCP] WebSocket connection closed, will reconnect on next send")
                    self.websocket = None
                except Exception as e:
                    logger.error(f"[CerberusMCP] Error sending data: {e}")
                    if self.websocket:
                        try:
                            await self.websocket.close()
                        except Exception:
                            pass
                    self.websocket = None


# WebSocket client instance - initialized by CerberusMCP server
_ws_client = None


def init_client(ws_url, api_key, client_id):
    """Initialize the WebSocket client and start the background thread.

    Args:
        ws_url: WebSocket URL for event_ingest backend
        api_key: API key for authentication
        client_id: Client identifier
    """
    global _ws_client

    if ws_url.startswith('ws://'):
        logger.warning(
            "[CerberusMCP] WebSocket URL uses unencrypted ws:// scheme. "
            "Use wss:// in production to protect API keys and event data in transit."
        )

    with _thread_lock:
        _ws_client = AsyncWebSocketClient(ws_url, api_key, client_id)
    _ensure_background_thread()
    if DEBUG_ENABLED:
        logger.info(f"[CerberusMCP] Transport initialized: {ws_url}")


def queue_event(event_data):
    """Queue an event for async transmission.

    Args:
        event_data: MCPEventData object to send
    """
    try:
        event_queue.put_nowait(event_data)
        if DEBUG_ENABLED:
            logger.info(f"[CerberusMCP] Queued event: {event_data.method} {event_data.endpoint}")
    except thread_queue.Full:
        logger.warning("[CerberusMCP] Event queue full, dropping event")


def _queue_get_with_timeout():
    """Get an item from the queue with a 1-second timeout."""
    return event_queue.get(block=True, timeout=1.0)


async def _process_queue_async():
    """Async coroutine that processes events from the thread-safe queue."""
    if DEBUG_ENABLED:
        logger.info("[CerberusMCP] Background queue processor started")

    loop = asyncio.get_running_loop()

    while True:
        try:
            data = await loop.run_in_executor(None, _queue_get_with_timeout)
        except thread_queue.Empty:
            continue
        except Exception as e:
            logger.error(f"[CerberusMCP] Error getting from queue: {e}")
            continue

        # Shutdown signal
        if data is None:
            if DEBUG_ENABLED:
                logger.info("[CerberusMCP] Received shutdown signal")
            break

        try:
            # Read client reference under lock for thread safety
            with _thread_lock:
                client = _ws_client
            if client:
                if DEBUG_ENABLED:
                    logger.info(f"[CerberusMCP] Processing event: {data.endpoint}")
                await client.send(data)
            else:
                logger.warning("[CerberusMCP] WebSocket client not initialized, skipping event")
        except Exception as e:
            logger.error(f"[CerberusMCP] Failed to send event: {e}")
        finally:
            event_queue.task_done()


def _run_event_loop_in_thread():
    """Run the async event processing loop in a dedicated thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if DEBUG_ENABLED:
        logger.info("[CerberusMCP] Background thread started with new event loop")

    try:
        loop.run_until_complete(_process_queue_async())
    except Exception as e:
        logger.error(f"[CerberusMCP] Background event loop error: {e}")
    finally:
        loop.close()
        if DEBUG_ENABLED:
            logger.info("[CerberusMCP] Background thread event loop closed")


def _ensure_background_thread():
    """Start the background processing thread if not already running."""
    global _background_thread

    with _thread_lock:
        if _background_thread is not None and _background_thread.is_alive():
            return

        _background_thread = threading.Thread(
            target=_run_event_loop_in_thread,
            name="cerberus-mcp-event-sender",
            daemon=True,
        )
        _background_thread.start()

        if DEBUG_ENABLED:
            logger.info("[CerberusMCP] Started background event sender thread")


def _shutdown():
    """Drain the event queue on process exit.

    Sends a shutdown sentinel (None) and waits briefly for the background
    thread to finish processing remaining events.
    """
    if _background_thread is not None and _background_thread.is_alive():
        try:
            event_queue.put_nowait(None)
        except thread_queue.Full:
            return
        _background_thread.join(timeout=2.0)


atexit.register(_shutdown)
