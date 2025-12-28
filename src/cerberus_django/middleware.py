from .structs import CoreData
from .utils import hash_pii, fetch_secret_key
from django.conf import settings
import asyncio
import json
import os
import logging
import websockets
import threading
import queue as thread_queue
from websocket import create_connection
import time

# Configure logging
logger = logging.getLogger(__name__)

# Enable debug logging via environment variable
DEBUG_ENABLED = os.getenv('CERBERUS_DEBUG', 'false').lower() in ('true', '1', 'yes')

# Use an asyncio.Queue for thread-safe, async producer-consumer pattern
# Lazy initialization to avoid creating Queue before event loop exists
buffer_queue = None

def get_buffer_queue():
    """Get or create the buffer queue lazily."""
    global buffer_queue
    if buffer_queue is None:
        try:
            buffer_queue = asyncio.Queue()
        except RuntimeError:
            # If there's no event loop yet, we'll try again later
            pass
    return buffer_queue

class AsyncWebSocketClient:
    def __init__(self, ws_url, api_key, client_id):
        self.ws_url = ws_url
        self.api_key = api_key
        self.client_id = client_id
        self.websocket = None
        self._lock = None

    @property
    def lock(self):
        """Lazy initialization of the lock to avoid creating it before event loop exists."""
        if self._lock is None:
            try:
                self._lock = asyncio.Lock()
            except RuntimeError:
                pass
        return self._lock

    async def connect(self):
        try:
            if DEBUG_ENABLED:
                logger.info(f"[Cerberus] Connecting to WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url)
            if DEBUG_ENABLED:
                logger.info(f"[Cerberus] WebSocket connected successfully")
        except Exception as e:
            self.websocket = None
            logger.error(f"[Cerberus] Failed to connect to WebSocket: {e}")

    async def send(self, event_data):
        """Send event data to backend via WebSocket.

        Args:
            event_data: CoreData object to send
        """
        async with self.lock:
            if self.websocket is None or self.websocket.closed:
                await self.connect()

            if self.websocket:
                try:
                    # Format data as expected by backend
                    payload = {
                        'api_key': self.api_key,
                        'client_id': self.client_id,
                        'token': event_data.token,
                        'source_ip': event_data.source_ip,
                        'endpoint': event_data.endpoint,
                        'scheme': event_data.scheme,
                        'method': event_data.method,
                        'custom_data': event_data.custom_data
                    }

                    json_data = json.dumps(payload)

                    if DEBUG_ENABLED:
                        logger.info(f"[Cerberus] Sending event to backend: {json_data[:150]}...")

                    await self.websocket.send(json_data)

                    # Wait for acknowledgment
                    response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)

                    if DEBUG_ENABLED:
                        logger.info(f"[Cerberus] Backend response: {response}")

                except asyncio.TimeoutError:
                    logger.warning("[Cerberus] Timeout waiting for backend response")
                except Exception as e:
                    logger.error(f"[Cerberus] Error sending data: {e}")
                    if self.websocket:
                        await self.websocket.close()
                    self.websocket = None

# WebSocket client will be initialized in middleware __init__
WS_CLIENT = None

# Background task to process the queue
async def process_queue():
    print("[Cerberus] Background process_queue task STARTED")
    while True:
        queue = get_buffer_queue()
        if queue is None:
            print("[Cerberus] Queue is None, waiting...")
            await asyncio.sleep(0.1)  # Wait for queue to be created
            continue

        print(f"[Cerberus] Waiting for item from queue (qsize: {queue.qsize()})...")
        data = await queue.get()
        print(f"[Cerberus] Got event from queue: {data.endpoint}")

        try:
            if WS_CLIENT:
                print(f"[Cerberus] Processing event for endpoint: {data.endpoint}")
                if DEBUG_ENABLED:
                    logger.info(f"[Cerberus] Processing queued event for endpoint: {data.endpoint}")
                await WS_CLIENT.send(data)
                print(f"[Cerberus] Event sent successfully")
            else:
                print("[Cerberus] WARNING: WebSocket client not initialized, skipping event")
                logger.warning("[Cerberus] WebSocket client not initialized, skipping event")
        except Exception as e:
            print(f"[Cerberus] ERROR sending data: {e}")
            logger.error(f"[Cerberus] Failed to send data from queue: {e}")
            import traceback
            traceback.print_exc()
        queue.task_done()

# Ensure the background task is started only once
queue_task_started = False

def ensure_queue_task():
    global queue_task_started
    print(f"[Cerberus] ensure_queue_task called, queue_task_started: {queue_task_started}")

    if not queue_task_started:
        try:
            loop = asyncio.get_event_loop()
            print(f"[Cerberus] Got event loop: {loop}")
            task = loop.create_task(process_queue())
            print(f"[Cerberus] Started background queue processing task: {task}")
            queue_task_started = True
        except RuntimeError as e:
            # If no event loop is running, this will be handled later
            print(f"[Cerberus] RuntimeError starting queue task: {e}")
            pass
    else:
        print(f"[Cerberus] Background task already started")

class CerberusMiddleware:
    def __init__(self, get_response):
        global WS_CLIENT

        self.get_response = get_response
        self.config = getattr(settings, 'CERBERUS_CONFIG', {})

        print("=" * 60)
        print("[Cerberus] Middleware initializing...")
        print(f"[Cerberus] Config: {list(self.config.keys())}")
        print(f"[Cerberus] DEBUG_ENABLED: {DEBUG_ENABLED}")
        print("=" * 60)

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

        ensure_queue_task()

    def __call__(self, request):
        print(f"[Cerberus] Processing request: {request.method} {request.path}")

        # Initialize custom_data attribute on the request object
        request.cerberus_metrics = {}

        # Process the request first
        response = self.get_response(request)
        
        # Extract metrics from response if they exist
        metrics = {}
        if hasattr(response, 'data') and isinstance(response.data, dict):
            if '_cerberus_metrics' in response.data:
                metrics = response.data.pop('_cerberus_metrics')
        
        # After the view has executed, create and store the CoreData
        # Hash PII (source IP) if secret_key is configured
        source_ip = request.META.get('REMOTE_ADDR')
        if 'secret_key' in self.config:
            source_ip = hash_pii(source_ip, self.config['secret_key'])

        d = CoreData(
            self.config.get('token', ''),
            source_ip,
            request.path,
            request.scheme == 'https',
            request.method,
            custom_data=metrics
        )
        # Put the CoreData into the async queue
        queue = get_buffer_queue()
        print(f"[Cerberus] Queue object: {queue}")

        if queue is not None:
            try:
                print(f"[Cerberus] Queueing event: {request.method} {request.path}")
                if DEBUG_ENABLED:
                    logger.info(f"[Cerberus] Queueing event: {request.method} {request.path}")

                loop = asyncio.get_event_loop()
                print(f"[Cerberus] Event loop: {loop}, is_running: {loop.is_running()}")

                if loop.is_running():
                    task = asyncio.create_task(queue.put(d))
                    print(f"[Cerberus] Created async task: {task}")
                else:
                    print(f"[Cerberus] Event loop not running, using run_until_complete")
                    loop.run_until_complete(queue.put(d))
                    print(f"[Cerberus] Event queued via run_until_complete")
            except RuntimeError as e:
                print(f"[Cerberus] RuntimeError: {e}")
                # If no event loop is running, fallback to synchronous put (should not happen in ASGI)
                asyncio.run(queue.put(d))
            except Exception as e:
                print(f"[Cerberus] Unexpected error queueing event: {e}")
                logger.error(f"[Cerberus] Error queueing event: {e}")
        else:
            print(f"[Cerberus] WARNING: Queue is None, event not queued!")

        return response
    