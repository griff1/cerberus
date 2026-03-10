"""
Cerberus MCP - MCP server instrumentation for Cerberus monitoring

Instruments MCP (Model Context Protocol) servers to capture tool, resource,
and prompt call metrics, sending them to the Cerberus analytics pipeline
via WebSocket.
"""

from .server import CerberusMCP
from .structs import MCPEventData
from .config import VERSION as __version__

__all__ = ["CerberusMCP", "MCPEventData", "__version__"]
