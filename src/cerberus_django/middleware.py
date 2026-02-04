"""
Cerberus Django Middleware

Captures HTTP request metrics and sends them asynchronously to a backend
analytics server via WebSocket.

This middleware is designed to work in both WSGI (synchronous) and ASGI
(asynchronous) Django deployments without requiring an event loop at import time.

Architecture:
- Middleware (sync): Captures request data and puts it in a thread-safe queue
- Background thread: Runs its own event loop to process queue and send via WebSocket
"""

from .structs import CoreData
from .utils import fetch_secret_key
from django.conf import settings
import asyncio
import json
import os
import logging
import threading
import queue as thread_queue
from datetime import datetime, timezone
import websockets

# Configure logging
logger = logging.getLogger(__name__)

# Enable debug logging via environment variable
DEBUG_ENABLED = os.getenv('CERBERUS_DEBUG', 'false').lower() in ('true', '1', 'yes')

# Thread-safe queue for events (no event loop required at import time)
event_queue = thread_queue.Queue()

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
        self._async_lock = None  # Created lazily within event loop context

    async def _get_lock(self):
        """Get or create async lock within the event loop context."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    async def connect(self):
        """Establish WebSocket connection to the backend."""
        try:
            if DEBUG_ENABLED:
                logger.info(f"[Cerberus] Connecting to WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url)
            if DEBUG_ENABLED:
                logger.info("[Cerberus] WebSocket connected successfully")
        except Exception as e:
            self.websocket = None
            logger.error(f"[Cerberus] Failed to connect to WebSocket: {e}")

    async def send(self, event_data):
        """Send event data to backend via WebSocket.

        Args:
            event_data: CoreData object to send
        """
        lock = await self._get_lock()
        async with lock:
            # Connect if not already connected
            if self.websocket is None:
                await self.connect()

            if self.websocket:
                try:
                    # Format data as expected by backend
                    payload = {
                        'api_key': self.api_key,
                        'client_id': self.client_id,
                        'token': event_data.token,
                        'remote_addr': event_data.source_ip,  # Backend expects 'remote_addr'
                        'endpoint': event_data.endpoint,
                        'scheme': event_data.scheme,
                        'method': event_data.method,
                        'timestamp': event_data.timestamp,
                        'custom_data': event_data.custom_data,
                        # Additional request details
                        'headers': event_data.headers,
                        'query_params': event_data.query_params,
                        'body': event_data.body,
                        'user_agent': event_data.user_agent,
                        'user_id': event_data.user_id,
                    }

                    json_data = json.dumps(payload)

                    if DEBUG_ENABLED:
                        logger.info(f"[Cerberus] Sending event to backend: {json_data[:200]}...")

                    await self.websocket.send(json_data)

                    # Wait for acknowledgment
                    response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)

                    if DEBUG_ENABLED:
                        logger.info(f"[Cerberus] Backend response: {response}")

                except asyncio.TimeoutError:
                    logger.warning("[Cerberus] Timeout waiting for backend response")
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("[Cerberus] WebSocket connection closed, will reconnect on next send")
                    self.websocket = None
                except Exception as e:
                    logger.error(f"[Cerberus] Error sending data: {e}")
                    if self.websocket:
                        try:
                            await self.websocket.close()
                        except Exception:
                            pass
                    self.websocket = None


# WebSocket client - initialized in middleware __init__, used by background thread
WS_CLIENT = None


def _queue_get_with_timeout():
    """Get an item from the queue with a 1-second timeout.

    This is a helper function for run_in_executor since we need to pass
    the timeout parameter.

    Returns:
        CoreData object or raises queue.Empty
    """
    return event_queue.get(block=True, timeout=1.0)


async def _process_queue_async():
    """Async coroutine that processes events from the thread-safe queue.

    Runs continuously in the background thread's event loop.
    """
    global WS_CLIENT

    if DEBUG_ENABLED:
        logger.info("[Cerberus] Background queue processor started")

    loop = asyncio.get_event_loop()

    while True:
        try:
            # Use run_in_executor to get from sync queue without blocking event loop
            data = await loop.run_in_executor(None, _queue_get_with_timeout)
        except thread_queue.Empty:
            # No events available, continue waiting
            continue
        except Exception as e:
            logger.error(f"[Cerberus] Error getting from queue: {e}")
            continue

        # Check for shutdown signal (None means stop)
        if data is None:
            if DEBUG_ENABLED:
                logger.info("[Cerberus] Received shutdown signal, stopping processor")
            break

        try:
            if WS_CLIENT:
                if DEBUG_ENABLED:
                    logger.info(f"[Cerberus] Processing event for endpoint: {data.endpoint}")
                await WS_CLIENT.send(data)
            else:
                logger.warning("[Cerberus] WebSocket client not initialized, skipping event")
        except Exception as e:
            logger.error(f"[Cerberus] Failed to send event: {e}")
        finally:
            event_queue.task_done()


def _run_event_loop_in_thread():
    """Run the async event processing loop in a dedicated thread.

    Creates its own event loop, independent of any Django event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if DEBUG_ENABLED:
        logger.info("[Cerberus] Background thread started with new event loop")

    try:
        loop.run_until_complete(_process_queue_async())
    except Exception as e:
        logger.error(f"[Cerberus] Background event loop error: {e}")
    finally:
        loop.close()
        if DEBUG_ENABLED:
            logger.info("[Cerberus] Background thread event loop closed")


def ensure_background_thread():
    """Start the background processing thread if not already running.

    Thread-safe: Uses a lock to prevent race conditions during startup.
    The thread is a daemon thread, so it will automatically stop when
    the main process exits.
    """
    global _background_thread

    with _thread_lock:
        if _background_thread is not None and _background_thread.is_alive():
            return

        _background_thread = threading.Thread(
            target=_run_event_loop_in_thread,
            name="cerberus-event-sender",
            daemon=True  # Auto-shutdown when main process exits
        )
        _background_thread.start()

        if DEBUG_ENABLED:
            logger.info("[Cerberus] Started background event sender thread")


def _extract_headers(request):
    """Extract HTTP headers from Django request.

    Converts Django's META dict (with HTTP_ prefixed headers) to a clean dict.
    Only includes actual HTTP headers, not server variables.

    Args:
        request: Django HttpRequest object

    Returns:
        Dict of header name -> value
    """
    headers = {}
    for key, value in request.META.items():
        if key.startswith('HTTP_'):
            # Convert HTTP_CONTENT_TYPE to Content-Type
            header_name = key[5:].replace('_', '-').title()
            headers[header_name] = value
        elif key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            # These don't have HTTP_ prefix but are still headers
            header_name = key.replace('_', '-').title()
            headers[header_name] = value
    return headers if headers else None


def _extract_query_params(request):
    """Extract query parameters from Django request.

    Args:
        request: Django HttpRequest object

    Returns:
        Dict of query param name -> value (or list of values if multiple)
    """
    if not request.GET:
        return None

    params = {}
    for key in request.GET:
        values = request.GET.getlist(key)
        params[key] = values[0] if len(values) == 1 else values
    return params


def _extract_body(request):
    """Extract request body from Django request.

    Only attempts to parse JSON bodies. Returns None for non-JSON content.

    Args:
        request: Django HttpRequest object

    Returns:
        Parsed JSON body as dict, or None
    """
    if request.method not in ('POST', 'PUT', 'PATCH'):
        return None

    content_type = request.content_type or ''
    if 'application/json' not in content_type:
        return None

    try:
        if request.body:
            return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    return None


class CerberusMiddleware:
    """Django middleware for capturing and sending HTTP request metrics.

    Compatible with both WSGI and ASGI Django deployments.

    Configuration via CERBERUS_CONFIG in Django settings:
        - token: API key for authentication
        - client_id: Client identifier
        - ws_url: WebSocket URL for event_ingest backend
        - backend_url: HTTP URL for fetching secret key (optional)
        - secret_key: HMAC key for PII hashing (optional, auto-fetched if backend_url set)
    """

    def __init__(self, get_response):
        global WS_CLIENT

        self.get_response = get_response
        self.config = getattr(settings, 'CERBERUS_CONFIG', {})

        if DEBUG_ENABLED:
            logger.info("[Cerberus] Middleware initializing...")
            logger.info(f"[Cerberus] Config keys: {list(self.config.keys())}")

        # Auto-fetch secret_key from backend if not configured locally
        if 'secret_key' not in self.config and 'backend_url' in self.config:
            if DEBUG_ENABLED:
                logger.info(f"[Cerberus] Fetching secret key from backend: {self.config['backend_url']}")
            secret_key = fetch_secret_key(
                self.config['backend_url'],
                self.config.get('token', '')
            )
            if secret_key:
                self.config['secret_key'] = secret_key
                logger.info(f"[Cerberus] Successfully fetched secret key from {self.config['backend_url']}")
            else:
                logger.warning("[Cerberus] Failed to fetch secret key. PII will not be hashed.")

        # Initialize WebSocket client
        if 'ws_url' in self.config and 'token' in self.config and 'client_id' in self.config:
            WS_CLIENT = AsyncWebSocketClient(
                self.config['ws_url'],
                self.config['token'],
                self.config['client_id']
            )
            if DEBUG_ENABLED:
                logger.info(f"[Cerberus] WebSocket client initialized: {self.config['ws_url']}")
        else:
            logger.warning("[Cerberus] WebSocket client not initialized. Missing ws_url, token, or client_id in CERBERUS_CONFIG")

        # Start background thread for processing events
        ensure_background_thread()

    def __call__(self, request):
        """Process a request and queue metrics for async transmission.

        This method is synchronous and does not require an event loop.
        Events are placed in a thread-safe queue and processed by the
        background thread.
        """
        # Initialize custom_data attribute on the request object
        request.cerberus_metrics = {}

        # Extract request data BEFORE processing (body can only be read once)
        headers = _extract_headers(request)
        query_params = _extract_query_params(request)
        body = _extract_body(request)
        user_agent = request.META.get('HTTP_USER_AGENT')

        # Process the request
        response = self.get_response(request)

        # Extract user_id set by application (e.g., JWT auth decorators)
        user_id = getattr(request, 'cerberus_user_id', None)

        # Extract metrics from response if they exist
        metrics = {}
        if hasattr(response, 'data') and isinstance(response.data, dict):
            if '_cerberus_metrics' in response.data:
                metrics = response.data.pop('_cerberus_metrics')

        # Get source IP address
        source_ip = request.META.get('REMOTE_ADDR')

        # Create the event data with current timestamp
        d = CoreData(
            token=self.config.get('token', ''),
            source_ip=source_ip,
            endpoint=request.path,
            scheme=request.scheme == 'https',
            method=request.method,
            timestamp=datetime.now(timezone.utc).isoformat(),
            custom_data=metrics,
            headers=headers,
            query_params=query_params,
            body=body,
            user_agent=user_agent,
            user_id=user_id,
        )

        # Queue the event (non-blocking)
        try:
            event_queue.put_nowait(d)
            if DEBUG_ENABLED:
                logger.info(f"[Cerberus] Queued event: {request.method} {request.path}")
        except thread_queue.Full:
            logger.warning("[Cerberus] Event queue full, dropping event")

        return response
