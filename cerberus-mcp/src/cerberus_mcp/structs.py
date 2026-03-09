"""
Cerberus MCP Event Data Structures

Defines the MCPEventData dataclass that maps MCP server events to the
CoreData format expected by the Cerberus event_ingest pipeline.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class MCPEventData:
    """Data structure for MCP server event metrics.

    Maps MCP tool/resource/prompt calls to the CoreData format used by
    the Cerberus event pipeline, so event_ingest requires no changes.

    Field mapping:
        - token: API key for authentication (from cerberus_config)
        - source_ip: Client identifier or "mcp-local"
        - endpoint: mcp://{server_name}/{handler_name}
        - scheme: Always True (MCP uses structured transport)
        - method: Event type (mcp_tool_call, mcp_resource_read, mcp_prompt_get)
        - timestamp: ISO 8601 UTC timestamp
        - custom_data: MCP-specific metadata (see below)
        - headers: None (MCP has no HTTP headers)
        - query_params: None (MCP has no query params)
        - body: Sanitized arguments dict
        - user_agent: "cerberus-mcp/0.1.0"
        - user_id: MCP client ID if available

    custom_data fields:
        - mcp_server: Server name
        - handler_name: Tool/resource/prompt name
        - event_type: tool_call, resource_read, or prompt_get
        - duration_ms: Call duration in milliseconds
        - arguments: Sanitized arguments summary
        - error: Error message if call failed
        - result_summary: Type and size of result
        - session_id: UUID per ServerSession
        - client_name: MCP client name from ClientInfo
        - client_version: MCP client version from ClientInfo
        - request_id: MCP request ID
        - mcp_client_id: MCP client ID from context
    """
    token: str
    source_ip: str
    endpoint: str
    scheme: bool
    method: str
    timestamp: str  # ISO 8601 format timestamp
    custom_data: Optional[Dict] = None

    # Additional fields matching CoreData
    headers: Optional[Dict] = None
    query_params: Optional[Dict] = None
    body: Optional[Dict] = None
    user_agent: Optional[str] = None
    user_id: Optional[str] = None
