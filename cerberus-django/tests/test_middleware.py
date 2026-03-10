"""Tests for cerberus_django middleware extraction and sanitization helpers."""

import json
import logging
import queue as thread_queue
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from cerberus_core import REDACTED
from cerberus_django.middleware import (
    CerberusMiddleware,
    _extract_body,
    _extract_headers,
    _extract_query_params,
    event_queue,
)


@pytest.fixture
def rf():
    return RequestFactory()


class TestExtractHeaders:
    """Tests for _extract_headers."""

    def test_extracts_standard_http_headers(self, rf):
        request = rf.get("/", HTTP_ACCEPT="text/html", HTTP_HOST="example.com")
        headers = _extract_headers(request)
        assert headers["Accept"] == "text/html"
        assert headers["Host"] == "example.com"

    def test_includes_content_type_and_length(self, rf):
        request = rf.post(
            "/",
            data=b"{}",
            content_type="application/json",
        )
        headers = _extract_headers(request)
        assert headers["Content-Type"] == "application/json"

    def test_redacts_cookie_header(self, rf):
        request = rf.get("/", HTTP_COOKIE="session=abc123")
        headers = _extract_headers(request)
        assert headers["Cookie"] == REDACTED

    def test_redacts_x_api_key_header(self, rf):
        request = rf.get("/", HTTP_X_API_KEY="sk-secret")
        headers = _extract_headers(request)
        assert headers["X-Api-Key"] == REDACTED

    def test_hashes_authorization_with_secret_key(self, rf):
        request = rf.get("/", HTTP_AUTHORIZATION="Bearer token123")
        headers = _extract_headers(request, secret_key="test-key")
        assert headers["Authorization"] != "Bearer token123"
        assert headers["Authorization"] != REDACTED
        assert len(headers["Authorization"]) == 64  # SHA-256 hex

    def test_redacts_authorization_without_secret_key(self, rf):
        request = rf.get("/", HTTP_AUTHORIZATION="Bearer token123")
        headers = _extract_headers(request, secret_key=None)
        assert headers["Authorization"] == REDACTED

    def test_returns_none_for_no_headers(self):
        request = MagicMock()
        request.META = {}
        headers = _extract_headers(request)
        assert headers is None

    def test_consistent_authorization_hash(self, rf):
        """Same Authorization value + same key = same hash."""
        request = rf.get("/", HTTP_AUTHORIZATION="Bearer abc")
        h1 = _extract_headers(request, secret_key="key")
        h2 = _extract_headers(request, secret_key="key")
        assert h1["Authorization"] == h2["Authorization"]


class TestExtractQueryParams:
    """Tests for _extract_query_params."""

    def test_extracts_simple_params(self, rf):
        request = rf.get("/?page=1&sort=name")
        params = _extract_query_params(request)
        assert params["page"] == "1"
        assert params["sort"] == "name"

    def test_redacts_sensitive_params(self, rf):
        request = rf.get("/?api_key=secret&token=xyz&page=1")
        params = _extract_query_params(request)
        assert params["api_key"] == REDACTED
        assert params["token"] == REDACTED
        assert params["page"] == "1"

    def test_redacts_password_param(self, rf):
        request = rf.get("/?password=hunter2")
        params = _extract_query_params(request)
        assert params["password"] == REDACTED

    def test_returns_none_for_no_params(self, rf):
        request = rf.get("/")
        params = _extract_query_params(request)
        assert params is None

    def test_multi_value_params(self, rf):
        request = rf.get("/?tag=a&tag=b&tag=c")
        params = _extract_query_params(request)
        assert params["tag"] == ["a", "b", "c"]

    def test_single_value_not_wrapped_in_list(self, rf):
        request = rf.get("/?name=alice")
        params = _extract_query_params(request)
        assert params["name"] == "alice"
        assert not isinstance(params["name"], list)


class TestExtractBody:
    """Tests for _extract_body."""

    def test_extracts_json_body(self, rf):
        data = {"username": "alice", "role": "admin"}
        request = rf.post("/", data=json.dumps(data), content_type="application/json")
        body = _extract_body(request)
        assert body["username"] == "alice"
        assert body["role"] == "admin"

    def test_sanitizes_sensitive_keys_in_body(self, rf):
        data = {"username": "alice", "password": "hunter2", "api_key": "sk-123"}
        request = rf.post("/", data=json.dumps(data), content_type="application/json")
        body = _extract_body(request)
        assert body["username"] == "alice"
        assert body["password"] == REDACTED
        assert body["api_key"] == REDACTED

    def test_sanitizes_nested_body(self, rf):
        data = {"user": {"name": "alice", "token": "abc"}}
        request = rf.post("/", data=json.dumps(data), content_type="application/json")
        body = _extract_body(request)
        assert body["user"]["name"] == "alice"
        assert body["user"]["token"] == REDACTED

    def test_returns_none_for_get_request(self, rf):
        request = rf.get("/")
        body = _extract_body(request)
        assert body is None

    def test_returns_none_for_non_json_content(self, rf):
        request = rf.post("/", data="form=data", content_type="application/x-www-form-urlencoded")
        body = _extract_body(request)
        assert body is None

    def test_returns_none_for_invalid_json(self, rf):
        request = rf.post("/", data=b"not json{{{", content_type="application/json")
        body = _extract_body(request)
        assert body is None

    def test_returns_none_for_bare_json_string(self, rf):
        request = rf.post("/", data=json.dumps("just a string"), content_type="application/json")
        body = _extract_body(request)
        assert body is None

    def test_returns_none_for_bare_json_number(self, rf):
        request = rf.post("/", data=json.dumps(42), content_type="application/json")
        body = _extract_body(request)
        assert body is None

    def test_handles_json_list_body(self, rf):
        data = [{"password": "secret"}, {"name": "alice"}]
        request = rf.post("/", data=json.dumps(data), content_type="application/json")
        body = _extract_body(request)
        assert isinstance(body, list)
        assert body[0]["password"] == REDACTED
        assert body[1]["name"] == "alice"

    def test_handles_empty_body(self, rf):
        request = rf.post("/", data=b"", content_type="application/json")
        body = _extract_body(request)
        assert body is None

    def test_handles_raw_post_data_exception(self, rf):
        """Broad except should catch RawPostDataException without crashing."""
        request = rf.post("/", data=b"{}", content_type="application/json")
        # Simulate RawPostDataException by making body access raise
        # Use a mock to avoid mutating the class-level descriptor
        request = MagicMock()
        request.method = "POST"
        request.content_type = "application/json"
        type(request).body = property(lambda self: (_ for _ in ()).throw(Exception("body already read")))
        body = _extract_body(request)
        assert body is None
        # Clean up the property we set on MagicMock
        del type(request).body

    def test_put_method(self, rf):
        data = {"field": "value"}
        request = rf.put("/", data=json.dumps(data), content_type="application/json")
        body = _extract_body(request)
        assert body is not None
        assert body["field"] == "value"

    def test_patch_method(self, rf):
        data = {"field": "value"}
        request = rf.patch("/", data=json.dumps(data), content_type="application/json")
        body = _extract_body(request)
        assert body is not None
        assert body["field"] == "value"

    def test_delete_method_returns_none(self, rf):
        request = rf.delete("/")
        body = _extract_body(request)
        assert body is None


class TestSourceIpHandling:
    """Tests for source IP hashing and plaintext warning."""

    def _drain_queue(self):
        while not event_queue.empty():
            try:
                event_queue.get_nowait()
            except thread_queue.Empty:
                break

    @patch("cerberus_django.middleware.ensure_background_thread")
    def test_source_ip_hashed_with_secret_key(self, mock_bg, rf):
        with patch.dict("django.conf.settings.__dict__", {"CERBERUS_CONFIG": {
            "token": "tok", "client_id": "cid", "ws_url": "wss://b:8765",
            "secret_key": "test-key",
        }}):
            mw = CerberusMiddleware(lambda req: MagicMock(data={}))
            self._drain_queue()
            request = rf.get("/test")
            mw(request)
            event = event_queue.get_nowait()
            # Should be a 64-char hex hash, not the raw IP
            assert event.source_ip != request.META.get("REMOTE_ADDR")
            assert len(event.source_ip) == 64

    @patch("cerberus_django.middleware.ensure_background_thread")
    def test_source_ip_raw_without_secret_key_warns(self, mock_bg, rf, caplog):
        with patch.dict("django.conf.settings.__dict__", {"CERBERUS_CONFIG": {
            "token": "tok", "client_id": "cid", "ws_url": "wss://b:8765",
        }}):
            mw = CerberusMiddleware(lambda req: MagicMock(data={}))
            self._drain_queue()
            request = rf.get("/test")
            with caplog.at_level(logging.WARNING, logger="cerberus_django.middleware"):
                mw(request)
            event = event_queue.get_nowait()
            # IP should be the raw value (127.0.0.1 from RequestFactory)
            assert event.source_ip == "127.0.0.1"
            assert "plaintext" in caplog.text

    @patch("cerberus_django.middleware.ensure_background_thread")
    def test_source_ip_warning_only_once(self, mock_bg, rf, caplog):
        with patch.dict("django.conf.settings.__dict__", {"CERBERUS_CONFIG": {
            "token": "tok", "client_id": "cid", "ws_url": "wss://b:8765",
        }}):
            mw = CerberusMiddleware(lambda req: MagicMock(data={}))
            self._drain_queue()
            with caplog.at_level(logging.WARNING, logger="cerberus_django.middleware"):
                mw(rf.get("/one"))
                mw(rf.get("/two"))
            assert caplog.text.count("plaintext") == 1
