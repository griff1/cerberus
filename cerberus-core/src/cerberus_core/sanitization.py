"""
Cerberus Core Sanitization

Shared sensitive key definitions, PII hashing, and recursive sanitization
logic used by both cerberus-django and cerberus-mcp to ensure consistent
data hygiene.
"""

import hashlib
import hmac

# Sentinel value for redacted fields
REDACTED = '[REDACTED]'

# HTTP headers whose values should always be redacted
SENSITIVE_HEADERS = frozenset({
    'HTTP_AUTHORIZATION',
    'HTTP_COOKIE',
    'HTTP_SET_COOKIE',
    'HTTP_X_API_KEY',
    'HTTP_X_AUTH_TOKEN',
    'HTTP_PROXY_AUTHORIZATION',
})

# Keys (case-insensitive) whose values should be redacted in bodies,
# query parameters, and MCP arguments
SENSITIVE_KEYS = frozenset({
    'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
    'api_secret', 'access_token', 'refresh_token', 'authorization',
    'auth', 'credential', 'credentials', 'private_key', 'ssh_key',
    'session_id', 'session_token', 'cookie',
    'credit_card', 'card_number', 'cvv', 'ssn',
})


def hash_pii(value, secret_key):
    """Consistently hash PII using HMAC-SHA256 for pseudoanonymization.

    Produces a stable hex digest — the same input always yields the same hash,
    enabling analytics (e.g., "same user across requests") without storing
    the raw PII value.

    Args:
        value: The PII string to hash (e.g., IP address, auth token)
        secret_key: Secret key for HMAC (from cerberus config)

    Returns:
        Hex-encoded HMAC-SHA256 digest, or None if value is None
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = value.encode('utf-8')
    if isinstance(secret_key, str):
        secret_key = secret_key.encode('utf-8')

    return hmac.new(secret_key, value, hashlib.sha256).hexdigest()


def sanitize_dict(data, _depth=0, _max_depth=20):
    """Recursively redact sensitive keys in a dict or list.

    Walks nested dicts and lists, replacing values whose keys match
    SENSITIVE_KEYS (case-insensitive) with REDACTED.  Recursion is
    capped at ``_max_depth`` levels to prevent stack overflow from
    adversarial deeply-nested payloads.

    Args:
        data: Dict or list to sanitize
        _depth: Current recursion depth (internal — do not set)
        _max_depth: Maximum recursion depth before redacting entire subtree

    Returns:
        New sanitized structure with sensitive values replaced
    """
    if _depth > _max_depth:
        return REDACTED

    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                sanitized[key] = REDACTED
            elif isinstance(value, (dict, list)):
                sanitized[key] = sanitize_dict(value, _depth + 1, _max_depth)
            else:
                sanitized[key] = value
        return sanitized
    if isinstance(data, list):
        return [
            sanitize_dict(item, _depth + 1, _max_depth) if isinstance(item, (dict, list)) else item
            for item in data
        ]
    return data
