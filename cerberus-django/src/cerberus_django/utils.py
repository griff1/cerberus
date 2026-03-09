import hmac
import hashlib
import requests
import os
import logging
from typing import Optional

# Configure logging
logger = logging.getLogger(__name__)

# Enable debug logging via environment variable
DEBUG_ENABLED = os.getenv('CERBERUS_DEBUG', 'false').lower() in ('true', '1', 'yes')

def hash_pii(value, secret_key):
    """
    Consistently hash PII using HMAC-SHA256 for pseudoanonymization.

    Args:
        value: The PII string to hash (e.g., IP address)
        secret_key: Secret key for HMAC (from CERBERUS_CONFIG['secret_key'])

    Returns:
        Hex-encoded HMAC digest string
    """
    if value is None:
        return None

    # Convert both to bytes if they aren't already
    if isinstance(value, str):
        value = value.encode('utf-8')
    if isinstance(secret_key, str):
        secret_key = secret_key.encode('utf-8')

    return hmac.new(secret_key, value, hashlib.sha256).hexdigest()

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
        return data.get('secret_key')
    except requests.RequestException as e:
        logger.error(f"[Cerberus] Failed to fetch secret key from {backend_url}: {e}")
        return None
