"""Tests for cerberus_mcp server instrumentation."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from cerberus_mcp.server import CerberusMCP, _extract_source_ip


class TestExtractSourceIp:
    """Tests for _extract_source_ip."""

    def test_returns_none_for_none_session(self):
        ctx = MagicMock()
        ctx.session = None
        assert _extract_source_ip(ctx) is None

    def test_returns_none_for_no_transport(self):
        ctx = MagicMock()
        ctx.session = MagicMock(spec=[])  # no _transport or transport attrs
        assert _extract_source_ip(ctx) is None

    def test_extracts_ip_from_asgi_scope_dict(self):
        ctx = MagicMock()
        transport = MagicMock(spec=[])
        transport._scope = {"client": ("192.168.1.1", 12345)}
        ctx.session._transport = transport
        result = _extract_source_ip(ctx)
        assert result == "192.168.1.1"

    def test_extracts_ip_from_starlette_request(self):
        ctx = MagicMock()
        transport = MagicMock(spec=[])
        request_obj = MagicMock()
        request_obj.client.host = "10.0.0.1"
        transport._request = request_obj
        ctx.session._transport = transport
        result = _extract_source_ip(ctx)
        assert result == "10.0.0.1"

    def test_extracts_ip_from_client_address(self):
        ctx = MagicMock()
        transport = MagicMock(spec=[])  # no scope/request attrs
        session = MagicMock(spec=["_transport", "client_address"])
        session._transport = transport
        session.client_address = ("172.16.0.1", 8080)
        ctx.session = session
        result = _extract_source_ip(ctx)
        assert result == "172.16.0.1"

    def test_returns_none_on_exception(self):
        ctx = MagicMock()
        type(ctx).session = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        assert _extract_source_ip(ctx) is None

    def test_returns_none_for_stdio_transport(self):
        """stdio transport has no network — should return None."""
        ctx = MagicMock()
        ctx.session._transport = MagicMock(spec=[])  # no scope/request
        ctx.session.client_address = None
        ctx.session._client_address = None
        assert _extract_source_ip(ctx) is None


class TestCerberusMCPInit:
    """Tests for CerberusMCP initialization."""

    @patch("cerberus_mcp.server.init_client")
    def test_initializes_transport_with_complete_config(self, mock_init):
        config = {"token": "tok", "client_id": "cid", "ws_url": "wss://backend:8765"}
        mcp = CerberusMCP("test-server", cerberus_config=config)
        mock_init.assert_called_once_with("wss://backend:8765", "tok", "cid")

    @patch("cerberus_mcp.server.init_client")
    def test_does_not_initialize_with_missing_config(self, mock_init):
        mcp = CerberusMCP("test-server", cerberus_config={"token": "tok"})
        mock_init.assert_not_called()

    @patch("cerberus_mcp.server.init_client")
    def test_server_name_override(self, mock_init):
        config = {
            "token": "tok", "client_id": "cid", "ws_url": "wss://b:8765",
            "server_name": "custom-name",
        }
        mcp = CerberusMCP("default-name", cerberus_config=config)
        assert mcp._server_name == "custom-name"


class TestExtractContextInfo:
    """Tests for CerberusMCP._extract_context_info."""

    @patch("cerberus_mcp.server.init_client")
    def test_filters_context_from_kwargs(self, mock_init):
        mcp = CerberusMCP("test")
        ctx = MagicMock()
        # Make _is_mcp_context return True for this mock
        with patch("cerberus_mcp.server._is_mcp_context", side_effect=lambda x: x is ctx):
            args, info = mcp._extract_context_info((), {"ctx": ctx, "query": "hello"})
        assert "ctx" not in args
        assert args["query"] == "hello"

    @patch("cerberus_mcp.server.init_client")
    def test_filters_context_from_positional_args(self, mock_init):
        mcp = CerberusMCP("test")
        ctx = MagicMock()
        with patch("cerberus_mcp.server._is_mcp_context", side_effect=lambda x: x is ctx):
            args, info = mcp._extract_context_info(("hello", ctx), {})
        assert "_arg0" in args
        assert args["_arg0"] == "hello"

    @patch("cerberus_mcp.server.init_client")
    def test_returns_empty_context_for_no_context_obj(self, mock_init):
        mcp = CerberusMCP("test")
        with patch("cerberus_mcp.server._is_mcp_context", return_value=False):
            args, info = mcp._extract_context_info((), {"query": "hello"})
        assert args == {"query": "hello"}
        assert info == {}


class TestWrapHandler:
    """Tests for handler wrapping and event emission."""

    @patch("cerberus_mcp.server.init_client")
    @patch("cerberus_mcp.server.queue_event")
    def test_sync_handler_emits_event(self, mock_queue, mock_init):
        mcp = CerberusMCP("test", cerberus_config={"token": "tok"})

        def my_tool(query: str) -> str:
            return "result"

        with patch("cerberus_mcp.server._is_mcp_context", return_value=False):
            wrapped = mcp._wrap_handler(my_tool, "my_tool", "tool_call", "mcp_tool_call")
            result = wrapped(query="hello")

        assert result == "result"
        mock_queue.assert_called_once()
        event = mock_queue.call_args[0][0]
        assert event.method == "mcp_tool_call"
        assert "my_tool" in event.endpoint

    @patch("cerberus_mcp.server.init_client")
    @patch("cerberus_mcp.server.queue_event")
    def test_async_handler_emits_event(self, mock_queue, mock_init):
        mcp = CerberusMCP("test", cerberus_config={"token": "tok"})

        async def my_tool(query: str) -> str:
            return "async result"

        with patch("cerberus_mcp.server._is_mcp_context", return_value=False):
            wrapped = mcp._wrap_handler(my_tool, "my_tool", "tool_call", "mcp_tool_call")
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(wrapped(query="hello"))
            finally:
                loop.close()

        assert result == "async result"
        mock_queue.assert_called_once()

    @patch("cerberus_mcp.server.init_client")
    @patch("cerberus_mcp.server.queue_event")
    def test_handler_error_captured(self, mock_queue, mock_init):
        mcp = CerberusMCP("test", cerberus_config={"token": "tok"})

        def failing_tool():
            raise ValueError("bad input")

        with patch("cerberus_mcp.server._is_mcp_context", return_value=False):
            wrapped = mcp._wrap_handler(failing_tool, "fail_tool", "tool_call", "mcp_tool_call")
            with pytest.raises(ValueError, match="bad input"):
                wrapped()

        mock_queue.assert_called_once()
        event = mock_queue.call_args[0][0]
        assert event.custom_data["error"] == "ValueError"


class TestResourceUriCapture:
    """Tests for resource URI being used as handler_name."""

    @patch("cerberus_mcp.server.init_client")
    @patch("cerberus_mcp.server.queue_event")
    def test_resource_uses_uri_as_handler_name(self, mock_queue, mock_init):
        mcp = CerberusMCP("test", cerberus_config={"token": "tok"})

        # Directly test that resource() uses the URI, not the function name
        # by calling _wrap_handler the way resource() does
        def get_settings() -> str:
            return '{"theme": "dark"}'

        uri = "config://settings"
        with patch("cerberus_mcp.server._is_mcp_context", return_value=False):
            wrapped = mcp._wrap_handler(get_settings, str(uri), "resource_read", "mcp_resource_read")
            wrapped()

        event = mock_queue.call_args[0][0]
        assert event.endpoint == "mcp://test/config://settings"
        assert event.custom_data["handler_name"] == "config://settings"


class TestSchemeField:
    """Tests for the scheme field using 'mcp' instead of True."""

    @patch("cerberus_mcp.server.init_client")
    @patch("cerberus_mcp.server.queue_event")
    def test_scheme_is_mcp_string(self, mock_queue, mock_init):
        mcp = CerberusMCP("test", cerberus_config={"token": "tok"})

        def my_tool():
            return "ok"

        with patch("cerberus_mcp.server._is_mcp_context", return_value=False):
            wrapped = mcp._wrap_handler(my_tool, "my_tool", "tool_call", "mcp_tool_call")
            wrapped()

        event = mock_queue.call_args[0][0]
        assert event.scheme == "mcp"
