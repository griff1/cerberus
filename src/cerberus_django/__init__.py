"""
Cerberus Django - HTTP request metrics middleware

A Django middleware for capturing and streaming HTTP request metrics
to a backend analytics server via WebSocket.
"""

from .middleware import CerberusMiddleware
from .structs import CoreData
from .utils import hash_pii

__version__ = "0.1.0"
__all__ = ["CerberusMiddleware", "CoreData", "hash_pii", "__version__"]
