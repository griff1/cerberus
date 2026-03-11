# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cerberus is a monorepo containing three Python packages for API and MCP server monitoring:

```
cerberus/
├── cerberus-core/          # Shared utilities (sanitization, constants)
│   ├── pyproject.toml
│   ├── src/cerberus_core/
│   │   ├── __init__.py
│   │   └── sanitization.py
│   └── tests/
├── cerberus-django/        # Django middleware for HTTP request monitoring
│   ├── pyproject.toml
│   └── src/cerberus_django/
│       ├── __init__.py
│       ├── middleware.py
│       ├── structs.py
│       └── utils.py
├── cerberus-mcp/           # MCP server instrumentation
│   ├── pyproject.toml
│   └── src/cerberus_mcp/
│       ├── __init__.py
│       ├── config.py
│       ├── server.py
│       ├── structs.py
│       ├── transport.py
│       └── utils.py
├── CLAUDE.md
├── LICENSE
└── publish_package.sh
```

All three packages are published independently to PyPI:
- `cerberus-core` — shared sanitization logic and sensitive key definitions
- `cerberus-django` — Django middleware (depends on cerberus-core)
- `cerberus-mcp` — MCP server wrapper (depends on cerberus-core)

## Packages

### cerberus-core

Shared utilities used by both cerberus-django and cerberus-mcp:
- `SENSITIVE_KEYS` — unified frozenset of key names to redact (passwords, tokens, PII, etc.)
- `SENSITIVE_HEADERS` — HTTP headers to always redact
- `REDACTED` — sentinel string `[REDACTED]`
- `sanitize_dict()` — recursive dict/list sanitization
- `hash_pii()` — HMAC-SHA256 pseudoanonymization for PII values

**Tests:** `cd cerberus-core && .venv/bin/python -m pytest tests/ -v`

### cerberus-django

Django middleware that intercepts HTTP requests/responses and streams metrics via WebSocket.

**Key behavior:**
- Captures headers, query params, body, user agent, source IP
- Sanitizes sensitive data using cerberus-core before transmission
- Hashes PII (source IP) with HMAC-SHA256 if secret_key is configured
- Background thread + async event loop for non-blocking WebSocket sends

**Configuration:** `CERBERUS_CONFIG` dict in Django settings with `token`, `client_id`, `ws_url`

### cerberus-mcp

Drop-in replacement for `FastMCP` that instruments MCP tool/resource/prompt calls.

**Key behavior:**
- Subclasses `FastMCP` — one-line change to instrument an MCP server
- Wraps handlers to capture timing, arguments, errors, results
- Extracts session/client identity from MCP Context objects
- Same WebSocket transport pattern as cerberus-django
- Schema reporting: on first event, introspects registered tools/resources/prompts via FastMCP internal registries (`_tool_manager`, `_resource_manager`, `_prompt_manager`) and emits a `mcp_schema_report` event with declared names, descriptions, `input_schema`, and prompt arguments
- Thread-safe schema reporting with `threading.Lock` to prevent duplicate reports from concurrent handlers
- Wrapper functions set `__wrapped__` attribute to preserve `inspect.signature()` chain for FastMCP parameter validation

**Configuration:** `CerberusMCP("name", cerberus_config={"token": ..., "client_id": ..., "ws_url": ...})`

**Key files:**
- `server.py` — `CerberusMCP` class, `_wrap_handler()`, `_emit_event()`, `_report_schema()`
- `structs.py` — `MCPEventData` dataclass
- `transport.py` — WebSocket transport
- `config.py` — Configuration handling

## Development

### Building packages
```bash
cd cerberus-core && uv build    # or cerberus-django / cerberus-mcp
```

### Publishing to PyPI
```bash
./publish_package.sh cerberus-core
./publish_package.sh cerberus-django
./publish_package.sh cerberus-mcp
```

### Running tests
```bash
cd cerberus-core && uv venv && uv pip install -e . pytest && .venv/bin/python -m pytest tests/ -v
```

### Debug logging
Set `CERBERUS_DEBUG=true` environment variable to enable verbose logging in both cerberus-django and cerberus-mcp.

## Architecture Notes

- Both cerberus-django and cerberus-mcp use the same event payload format (CoreData/MCPEventData) so event_ingest requires no changes
- MCP events use `mcp://` URI scheme in the `endpoint` field and `mcp_*` prefixed method names
- MCP-specific metadata (arguments, duration, session info) goes in `custom_data`
- Event queue is bounded (10,000 max for cerberus-mcp) to prevent unbounded memory growth
- WebSocket transport is shared pattern but not shared code (each package has its own copy for independence)

### MCP Event Methods

| Method | Description | Tracked In |
|--------|-------------|------------|
| `mcp_tool_call` | Tool invocation | `mcp_tool_discovery` |
| `mcp_resource_read` | Resource read | `mcp_resource_discovery` |
| `mcp_prompt_get` | Prompt invocation | `mcp_prompt_discovery` |
| `mcp_schema_report` | Schema introspection report (emitted once per server startup) | All three discovery tables (sets `description`, `input_schema`, `declared_arguments`, `schema_only=true`) |

### Schema Report Flow

1. `CerberusMCP._emit_event()` fires on the first actual tool/resource/prompt call
2. Thread-safe check via `_schema_report_lock` ensures `_report_schema()` runs exactly once
3. `_report_schema()` introspects FastMCP internals: `_tool_manager._tools`, `_resource_manager._resources`/`_templates`, `_prompt_manager._prompts`
4. Emits a single `mcp_schema_report` event with `custom_data` containing `tools`, `resources`, `prompts` arrays
5. `event_process` routes this to `MCPDiscoveryUpdater._handle_schema_report()` which creates `schema_only=True` records
6. On subsequent real calls, UPSERT clears `schema_only` to `False` via `existing AND EXCLUDED`
