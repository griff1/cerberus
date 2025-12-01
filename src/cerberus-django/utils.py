import hmac
import hashlib
import requests
from typing import Optional

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

def fetch_secret_key(backend_url: str, token: str, timeout: int = 5) -> Optional[str]:
    """
    Fetch the shared HMAC secret key from the backend server.

    Args:
        backend_url: Base URL of the backend server (e.g., 'https://cerberus.example.com')
        token: Client authentication token
        timeout: Request timeout in seconds (default: 5)

    Returns:
        The secret key string, or None if fetch fails

    Raises:
        requests.RequestException: On network/HTTP errors
    """
    try:
        response = requests.get(
            f"{backend_url.rstrip('/')}/api/secret-key",
            headers={'Authorization': f'Bearer {token}'},
            timeout=timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get('secret_key')
    except requests.RequestException as e:
        print(f"Failed to fetch secret key from {backend_url}: {e}")
        return None
