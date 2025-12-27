from .structs import CoreData
from .utils import hash_pii, fetch_secret_key
from django.conf import settings
import asyncio
import json

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

class AsyncTCPClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.writer = None
        self._lock = None

    @property
    def lock(self):
        """Lazy initialization of the lock to avoid creating it before event loop exists."""
        if self._lock is None:
            try:
                self._lock = asyncio.Lock()
            except RuntimeError:
                # If there's no event loop yet, return a simple object that will be replaced later
                pass
        return self._lock

    async def connect(self):
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)
            self.writer = writer
        except Exception as e:
            self.writer = None
            print(f"Failed to connect to backend server: {e}")

    async def send(self, data):
        async with self.lock:
            if self.writer is None:
                await self.connect()
            if self.writer:
                try:
                    self.writer.write(data.encode('utf-8') + b'\n')
                    await self.writer.drain()
                except Exception as e:
                    print(f"Error sending data: {e}")
                    self.writer.close()
                    await self.writer.wait_closed()
                    self.writer = None

# Initialize the TCP client with placeholders
TCP_CLIENT = AsyncTCPClient('BACKEND_HOST', 12345)

# Background task to process the queue
async def process_queue():
    while True:
        queue = get_buffer_queue()
        if queue is None:
            await asyncio.sleep(0.1)  # Wait for queue to be created
            continue
        data = await queue.get()
        try:
            await TCP_CLIENT.send(json.dumps(data.__dict__))
        except Exception as e:
            print(f"Failed to send data from queue: {e}")
        queue.task_done()

# Ensure the background task is started only once
queue_task_started = False

def ensure_queue_task():
    global queue_task_started
    if not queue_task_started:
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(process_queue())
            queue_task_started = True
        except RuntimeError:
            # If no event loop is running, this will be handled later
            pass

class CerberusMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.config = getattr(settings, 'CERBERUS_CONFIG', {})

        # Auto-fetch secret_key from backend if not configured locally
        if 'secret_key' not in self.config and 'backend_url' in self.config:
            secret_key = fetch_secret_key(
                self.config['backend_url'],
                self.config.get('token', '')
            )
            if secret_key:
                self.config['secret_key'] = secret_key
                print(f"Successfully fetched secret key from {self.config['backend_url']}")
            else:
                print("Warning: Failed to fetch secret key. PII will not be hashed.")

        ensure_queue_task()

    def __call__(self, request):
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
            self.config.token,
            source_ip,
            request.path,
            request.scheme == 'https',
            request.method,
            custom_data=metrics
        )
        # Put the CoreData into the async queue
        queue = get_buffer_queue()
        if queue is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(queue.put(d))
                else:
                    loop.run_until_complete(queue.put(d))
            except RuntimeError:
                # If no event loop is running, fallback to synchronous put (should not happen in ASGI)
                asyncio.run(queue.put(d))

        return response
    