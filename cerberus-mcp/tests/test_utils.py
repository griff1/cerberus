"""Tests for cerberus_mcp utility functions."""

import pytest

from cerberus_core import REDACTED
from cerberus_mcp.utils import sanitize_arguments, summarize_result, _truncate_value
from cerberus_mcp.config import MAX_ARG_STRING_LENGTH


class TestSanitizeArguments:
    """Tests for argument sanitization before event capture."""

    def test_redacts_sensitive_keys(self):
        args = {"query": "hello", "password": "secret", "api_key": "sk-123"}
        result = sanitize_arguments(args)
        assert result["query"] == "hello"
        assert result["password"] == REDACTED
        assert result["api_key"] == REDACTED

    def test_case_insensitive_key_matching(self):
        args = {"Password": "secret", "API_KEY": "key"}
        result = sanitize_arguments(args)
        assert result["Password"] == REDACTED
        assert result["API_KEY"] == REDACTED

    def test_truncates_long_strings(self):
        long_str = "x" * (MAX_ARG_STRING_LENGTH + 100)
        args = {"text": long_str}
        result = sanitize_arguments(args)
        assert len(result["text"]) < len(long_str)
        assert "chars" in result["text"]

    def test_preserves_short_strings(self):
        args = {"name": "alice"}
        result = sanitize_arguments(args)
        assert result["name"] == "alice"

    def test_preserves_numeric_values(self):
        args = {"count": 42, "ratio": 3.14, "flag": True}
        result = sanitize_arguments(args)
        assert result["count"] == 42
        assert result["ratio"] == 3.14
        assert result["flag"] is True

    def test_returns_none_for_empty_input(self):
        assert sanitize_arguments(None) is None
        assert sanitize_arguments({}) is None

    def test_non_dict_input_wrapped(self):
        result = sanitize_arguments("raw string")
        assert "_raw" in result
        assert result["_raw"] == "raw string"

    def test_non_string_keys_do_not_crash(self):
        args = {0: "positional", "query": "hello"}
        result = sanitize_arguments(args)
        assert result[0] == "positional"
        assert result["query"] == "hello"

    def test_sanitizes_nested_dicts(self):
        args = {"config": {"token": "abc", "host": "localhost"}}
        result = sanitize_arguments(args)
        assert result["config"]["token"] == REDACTED
        assert result["config"]["host"] == "localhost"

    def test_sanitizes_nested_lists(self):
        args = {"items": [{"password": "secret"}, {"name": "alice"}]}
        result = sanitize_arguments(args)
        assert result["items"][0]["password"] == REDACTED
        assert result["items"][1]["name"] == "alice"

    def test_sanitizes_tuple_values(self):
        args = {"data": ({"password": "secret"}, {"name": "alice"})}
        result = sanitize_arguments(args)
        assert isinstance(result["data"], list)
        assert result["data"][0]["password"] == REDACTED
        assert result["data"][1]["name"] == "alice"


class TestTruncateValue:
    """Tests for _truncate_value helper."""

    def test_none_passthrough(self):
        assert _truncate_value(None) is None

    def test_bool_passthrough(self):
        assert _truncate_value(True) is True
        assert _truncate_value(False) is False

    def test_int_passthrough(self):
        assert _truncate_value(42) == 42

    def test_float_passthrough(self):
        assert _truncate_value(3.14) == 3.14

    def test_short_string_passthrough(self):
        assert _truncate_value("hello") == "hello"

    def test_long_string_truncated(self):
        s = "a" * (MAX_ARG_STRING_LENGTH + 50)
        result = _truncate_value(s)
        assert len(result) < len(s)
        assert result.startswith("a" * MAX_ARG_STRING_LENGTH)

    def test_list_summarized(self):
        result = _truncate_value([1, 2, 3])
        assert "list" in result
        assert "3" in result

    def test_dict_summarized(self):
        result = _truncate_value({"a": 1, "b": 2})
        assert "dict" in result
        assert "2" in result

    def test_bytes_summarized(self):
        result = _truncate_value(b"hello")
        assert "bytes" in result
        assert "5" in result

    def test_unknown_type_summarized(self):
        result = _truncate_value(object())
        assert "object" in result


class TestSummarizeResult:
    """Tests for result summarization."""

    def test_none_result(self):
        assert summarize_result(None) == "None"

    def test_string_result(self):
        result = summarize_result("hello world")
        assert "str" in result
        assert "11" in result

    def test_list_result(self):
        result = summarize_result([1, 2, 3])
        assert "list" in result
        assert "3" in result

    def test_dict_result(self):
        result = summarize_result({"a": 1})
        assert "dict" in result
        assert "1" in result

    def test_bytes_result(self):
        result = summarize_result(b"data")
        assert "bytes" in result
        assert "4" in result

    def test_bool_result(self):
        assert summarize_result(True) == "True"
        assert summarize_result(False) == "False"

    def test_int_result(self):
        assert summarize_result(42) == "42"

    def test_float_result(self):
        assert summarize_result(3.14) == "3.14"

    def test_custom_object_with_len(self):
        class CustomSeq:
            def __len__(self):
                return 5
        result = summarize_result(CustomSeq())
        assert "CustomSeq" in result
        assert "5" in result

    def test_custom_object_without_len(self):
        class Custom:
            pass
        result = summarize_result(Custom())
        assert result == "Custom"
