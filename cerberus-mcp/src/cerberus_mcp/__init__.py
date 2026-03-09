"""
Cerberus MCP - MCP server instrumentation for Cerberus monitoring

Instruments MCP (Model Context Protocol) servers to capture tool, resource,
and prompt call metrics, sending them to the Cerberus analytics pipeline
via WebSocket.
"""

from .server import CerberusMCP
from .structs import MCPEventData

__version__ = "0.1.0"
__all__ = ["CerberusMCP", "MCPEventData", "__version__"]
