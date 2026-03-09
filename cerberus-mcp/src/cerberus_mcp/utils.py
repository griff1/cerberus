"""
Cerberus MCP Utilities

Argument sanitization and result summarization helpers for MCP event capture.
"""

import logging
import os

logger = logging.getLogger(__name__)

DEBUG_ENABLED = os.getenv('CERBERUS_DEBUG', 'false').lower() in ('true', '1', 'yes')

# Keys whose values should be redacted from captured arguments
SENSITIVE_KEYS = frozenset({
    'password', 'passwd', 'secret', 'token', 'api_key', 'apikey',
    'api_secret', 'access_token', 'refresh_token', 'authorization',
    'auth', 'credential', 'credentials', 'private_key', 'ssh_key',
    'session_id', 'session_token', 'cookie',
})

# Maximum length for string values in captured arguments
MAX_ARG_STRING_LENGTH = 200

# Maximum length for result summary strings
MAX_RESULT_LENGTH = 100


def sanitize_arguments(args):
    """Sanitize arguments before including in events.

    Redacts values for sensitive keys and truncates long strings.
    Returns a new dict safe for logging/transmission.

    Args:
        args: Dict of argument name -> value, or None

    Returns:
        Sanitized dict, or None if input is None/empty
    """
    if not args:
        return None

    if not isinstance(args, dict):
        return {"_raw": _truncate_value(str(args))}

    sanitized = {}
    for key, value in args.items():
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = _truncate_value(value)
    return sanitized


def _truncate_value(value):
    """Truncate a value for safe inclusion in event data.

    Args:
        value: Any value to truncate

    Returns:
        Truncated representation of the value
    """
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_ARG_STRING_LENGTH:
            return value[:MAX_ARG_STRING_LENGTH] + f"... ({len(value)} chars)"
        return value
    if isinstance(value, (list, tuple)):
        return f"[{type(value).__name__}, len={len(value)}]"
    if isinstance(value, dict):
        return f"[dict, keys={len(value)}]"
    if isinstance(value, bytes):
        return f"[bytes, len={len(value)}]"
    return f"[{type(value).__name__}]"


def summarize_result(result):
    """Summarize a result value for event data.

    Returns a short string describing the type and size of the result,
    not the full content.

    Args:
        result: The return value from an MCP handler

    Returns:
        String summary of the result
    """
    if result is None:
        return "None"
    if isinstance(result, str):
        return f"str(len={len(result)})"
    if isinstance(result, (list, tuple)):
        return f"{type(result).__name__}(len={len(result)})"
    if isinstance(result, dict):
        return f"dict(keys={len(result)})"
    if isinstance(result, bytes):
        return f"bytes(len={len(result)})"
    if isinstance(result, (bool, int, float)):
        return str(result)
    # For MCP-specific types, get the class name
    type_name = type(result).__name__
    if hasattr(result, '__len__'):
        try:
            return f"{type_name}(len={len(result)})"
        except TypeError:
            pass
    return type_name
