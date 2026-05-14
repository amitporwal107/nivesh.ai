"""Unit tests for core.logging_config — JSON formatter, masking, correlation ID."""
import json
import logging
import sys

import pytest

from core.logging_config import (
    JsonFormatter,
    get_correlation_id,
    mask_email,
    mask_pan,
    reset_correlation_id,
    set_correlation_id,
    _mask_value,
    _MASK,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_record(
    msg: str = "test message",
    level: int = logging.INFO,
    name: str = "test.logger",
    **extra,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name, level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


# ── JsonFormatter ─────────────────────────────────────────────────────────────

class TestJsonFormatter:
    def setup_method(self):
        self.fmt = JsonFormatter(service="test-svc", env="test", version="1.0")

    def _parse(self, record: logging.LogRecord) -> dict:
        return json.loads(self.fmt.format(record))

    def test_required_fields_present(self):
        out = self._parse(_make_record("hello"))
        assert "ts" in out
        assert out["level"] == "INFO"
        assert out["logger"] == "test.logger"
        assert out["msg"] == "hello"
        assert out["service"] == "test-svc"
        assert out["env"] == "test"
        assert out["version"] == "1.0"

    def test_ts_format(self):
        out = self._parse(_make_record("x"))
        # e.g. "2026-05-14T10:30:00.000Z"
        ts = out["ts"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_extra_fields_included(self):
        out = self._parse(_make_record("x", portfolio_id="pf_123"))
        assert out["portfolio_id"] == "pf_123"

    def test_sensitive_fields_masked(self):
        out = self._parse(_make_record("x", password="s3cr3t"))
        assert out["password"] == _MASK

        out2 = self._parse(_make_record("x", access_token="tok_abc"))
        assert out2["access_token"] == _MASK

    def test_correlation_id_included_when_set(self):
        token = set_correlation_id("abc123")
        try:
            out = self._parse(_make_record("x"))
            assert out["correlationId"] == "abc123"
        finally:
            reset_correlation_id(token)

    def test_no_correlation_id_when_empty(self):
        token = set_correlation_id("")
        try:
            out = self._parse(_make_record("x"))
            assert "correlationId" not in out
        finally:
            reset_correlation_id(token)

    def test_exc_info_formatted(self):
        try:
            raise ValueError("test error")
        except ValueError:
            record = _make_record("boom", level=logging.ERROR)
            record.exc_info = sys.exc_info()
        out = self._parse(record)
        assert "exc" in out
        assert "ValueError" in out["exc"]

    def test_debug_level(self):
        out = self._parse(_make_record("dbg", level=logging.DEBUG))
        assert out["level"] == "DEBUG"

    def test_warn_level(self):
        out = self._parse(_make_record("wrn", level=logging.WARNING))
        assert out["level"] == "WARNING"

    def test_stdlib_reserved_fields_not_duplicated(self):
        out = self._parse(_make_record("x"))
        # 'name' is a stdlib reserved field — should NOT appear as a separate key
        # (it is surfaced as 'logger' instead)
        assert "name" not in out

    def test_output_is_valid_json(self):
        record = _make_record("valid json test", elapsed_ms=42)
        raw = self.fmt.format(record)
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)


# ── Sensitive masking ─────────────────────────────────────────────────────────

class TestMaskValue:
    def test_password_masked(self):
        assert _mask_value("password", "secret") == _MASK

    def test_token_masked(self):
        assert _mask_value("token", "abc") == _MASK
        assert _mask_value("access_token", "abc") == _MASK
        assert _mask_value("refresh_token", "abc") == _MASK

    def test_otp_masked(self):
        assert _mask_value("otp", "123456") == _MASK

    def test_pan_masked(self):
        assert _mask_value("pan", "ABCDE1234F") == _MASK

    def test_aadhaar_masked(self):
        assert _mask_value("aadhaar", "1234") == _MASK

    def test_non_sensitive_not_masked(self):
        assert _mask_value("portfolio_id", "pf_123") == "pf_123"
        assert _mask_value("user_id", "u_456") == "u_456"
        assert _mask_value("elapsed_ms", 42) == 42


class TestMaskEmail:
    def test_normal_email(self):
        masked = mask_email("john.doe@example.com")
        assert "@example.com" in masked
        assert "jo***" in masked
        assert "doe" not in masked

    def test_short_local(self):
        masked = mask_email("ab@x.com")
        assert "@x.com" in masked
        assert "***" in masked

    def test_empty_email(self):
        assert mask_email("") == _MASK

    def test_no_at_sign(self):
        assert mask_email("invalidemail") == _MASK


class TestMaskPan:
    def test_standard_pan(self):
        masked = mask_pan("ABCDE1234F")
        assert masked.endswith("234F") or masked.endswith("1234F")
        assert "*" in masked

    def test_short_input(self):
        assert mask_pan("AB") == _MASK

    def test_empty_input(self):
        assert mask_pan("") == _MASK


# ── Correlation ID context var ────────────────────────────────────────────────

class TestCorrelationId:
    def test_default_is_empty_string(self):
        token = set_correlation_id("")
        try:
            assert get_correlation_id() == ""
        finally:
            reset_correlation_id(token)

    def test_set_and_get(self):
        token = set_correlation_id("req-abc-123")
        try:
            assert get_correlation_id() == "req-abc-123"
        finally:
            reset_correlation_id(token)

    def test_reset_restores_previous(self):
        outer = set_correlation_id("outer")
        inner = set_correlation_id("inner")
        assert get_correlation_id() == "inner"
        reset_correlation_id(inner)
        assert get_correlation_id() == "outer"
        reset_correlation_id(outer)
