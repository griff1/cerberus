import requests
import os
import logging
from typing import Optional

from cerberus_core import hash_pii  # noqa: F401 — re-exported for backward compatibility

# Configure logging
logger = logging.getLogger(__name__)

# Enable debug logging via environment variable
DEBUG_ENABLED = os.getenv('CERBERUS_DEBUG', 'false').lower() in ('true', '1', 'yes')

def fetch_secret_key(backend_url: str, api_key: str, timeout: int = 5) -> Optional[str]:
    """
    Fetch the shared HMAC secret key from the backend server.

    Args:
        backend_url: Base URL of the backend server (e.g., 'https://cerberus.example.com')
        api_key: Client API key for authentication
        timeout: Request timeout in seconds (default: 5)

    Returns:
        The secret key string, or None if fetch fails

    Raises:
        requests.RequestException: On network/HTTP errors
    """
    if not backend_url.startswith('https://'):
        logger.warning(
            "[Cerberus] backend_url does not use https://. "
            "API key will be sent in plaintext. Use https:// in production."
        )

    try:
        url = f"{backend_url.rstrip('/')}/api/secret-key"
        if DEBUG_ENABLED:
            logger.info(f"[Cerberus] Making HTTP request to fetch secret key: {url}")

        response = requests.get(
            url,
            headers={'X-API-Key': api_key},
            timeout=timeout
        )

        if DEBUG_ENABLED:
            logger.info(f"[Cerberus] Secret key fetch response: {response.status_code}")

        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            logger.error(
                f"[Cerberus] Unexpected response format from {backend_url}: "
                f"expected dict, got {type(data).__name__}"
            )
            return None
        return data.get('secret_key')
    except (requests.RequestException, ValueError, AttributeError) as e:
        logger.error(f"[Cerberus] Failed to fetch secret key from {backend_url}: {e}")
        return None
