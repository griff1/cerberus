"""
Cerberus Core - Shared utilities for the Cerberus monitoring ecosystem

Provides common sanitization logic, sensitive key definitions, and
configuration helpers used by cerberus-django and cerberus-mcp.
"""

from .sanitization import (
    REDACTED,
    SENSITIVE_HEADERS,
    SENSITIVE_KEYS,
    hash_pii,
    sanitize_dict,
)

__version__ = "0.1.0"
__all__ = [
    "REDACTED",
    "SENSITIVE_HEADERS",
    "SENSITIVE_KEYS",
    "hash_pii",
    "sanitize_dict",
    "__version__",
]
