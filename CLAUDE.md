# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cerberus is a Django middleware package for collecting and streaming HTTP request metrics to a backend analytics server. It captures request metadata (IP, endpoint, method, scheme) along with custom application-level metrics and sends them asynchronously via TCP.

## Architecture

### Core Components

**Data Flow:**
1. `CerberusMiddleware` intercepts Django requests/responses
2. Metrics are queued into an async `asyncio.Queue` (thread-safe producer-consumer pattern)
3. Background task `process_queue()` continuously drains the queue
4. `AsyncTCPClient` maintains persistent TCP connection and sends JSON-encoded data

**Key Files:**
- `src/cerberus_django/structs.py`: Defines `CoreData` dataclass for metric structure
- `src/cerberus_django/middleware.py`: Main middleware implementation with async queue processing
- `src/cerberus_django/utils.py`: PII hashing utilities using HMAC-SHA256
- `src/cerberus_django/__init__.py`: Package initialization and exports

### Middleware Configuration

The middleware expects a `CERBERUS_CONFIG` dictionary in Django settings:

**Option 1: Auto-fetch secret key (recommended)**
```python
CERBERUS_CONFIG = {
    'token': 'your-auth-token',
    'backend_url': 'https://cerberus.example.com',  # Backend HTTP URL
}
```
The middleware will automatically fetch the shared `secret_key` from `GET /api/secret-key` on startup.

**Option 2: Manually configure secret key**
```python
CERBERUS_CONFIG = {
    'token': 'your-auth-token',
    'secret_key': 'your-hmac-secret-key',  # Manually set
}
```

**PII Pseudoanonymization**: If `secret_key` is available (either auto-fetched or manually configured), the middleware will hash PII fields (currently `source_ip`) using HMAC-SHA256 before transmission. This ensures consistent pseudoanonymization - the same IP will always hash to the same value with a given key, enabling analytics while protecting privacy. If `secret_key` cannot be fetched or configured, raw values are sent with a warning logged.

### TCP Client Architecture

- `AsyncTCPClient` manages a single persistent connection to the backend server
- Connection is lazy-initialized on first send
- Auto-reconnects on failure with locking to prevent race conditions
- **Backend configuration**: Currently hardcoded in middleware.py:40 as `AsyncTCPClient('BACKEND_HOST', 12345)`. To use this middleware, you must modify this line to point to your actual analytics backend server's TCP endpoint.

### Custom Metrics Pattern

Views can attach custom metrics to responses that will be included in `CoreData.custom_data`:
```python
response.data['_cerberus_metrics'] = {...}
```
The middleware automatically extracts and removes this field from responses (middleware.py:94-96).

## Important Implementation Details

1. **Secret Key Distribution**: On middleware initialization, if `backend_url` is configured but `secret_key` is not, the middleware automatically fetches the shared secret key via HTTP GET from `/api/secret-key` (middleware.py:71-81, utils.py:28-54). The fetch is synchronous and happens once at Django startup. Uses Bearer token authentication.

2. **PII Hashing**: Uses HMAC-SHA256 for consistent pseudoanonymization of PII fields (middleware.py:100-102, utils.py:6-26). Hashing is optional and controlled by `CERBERUS_CONFIG['secret_key']`. The same input always produces the same hash with a given key, enabling analytics on pseudonymized data.

3. **Event Loop Handling**: The middleware handles multiple event loop scenarios (running loop, no loop, ASGI vs WSGI) with fallbacks at middleware.py:113-121

4. **Queue Task Lifecycle**: `ensure_queue_task()` ensures the background queue processor starts exactly once per application lifecycle (middleware.py:55-64)

5. **Connection Resilience**: TCP client closes and nullifies writer on send failures, triggering reconnection on next attempt (middleware.py:34-37)

6. **Import Path**: Middleware uses explicit relative imports (`from .structs import CoreData`, `from .utils import hash_pii, fetch_secret_key`) to ensure proper package resolution

## Development and Testing

**Installation in Django Project:**

1. Add the `cerberus/src` directory to your Python path in your Django project
2. Add to Django's `MIDDLEWARE`: `'cerberus_django.CerberusMiddleware'`
3. Configure `CERBERUS_CONFIG` dictionary in settings (see Middleware Configuration section)
4. **Important**: Edit middleware.py to configure TCP backend host/port before deployment

**Example - Adding to Python path:**
```python
# In your Django settings.py or manage.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'cerberus', 'src'))
```

**Dependencies:**
- Django framework (any version with middleware support)
- Python `asyncio` (standard library)
- `requests` library (for HTTP secret key fetching)

**Testing Considerations:**
- No test suite currently exists
- Manual testing requires a running backend TCP server that accepts JSON-encoded `CoreData` objects
- The middleware silently handles connection failures and prints errors to stdout
- Backend server (separate repository) should provide `GET /api/secret-key` endpoint returning `{"secret_key": "..."}`

**ASGI vs WSGI:**
- Designed for ASGI applications but includes WSGI fallback logic
- Event loop handling ensures compatibility with both deployment modes
