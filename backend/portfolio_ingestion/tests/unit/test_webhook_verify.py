"""Unit tests for HMAC webhook signature verification (T3.3)."""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from portfolio_ingestion.services.webhook_verify import (
    WebhookSignatureError,
    verify_signature,
)

SECRET = "test-webhook-secret-abc123"


def _make_sig(body: bytes, secret: str = SECRET, ts: int | None = None) -> str:
    t = ts if ts is not None else int(time.time())
    payload = f"{t}.".encode() + body
    mac = hmac.new(key=secret.encode(), msg=payload, digestmod=hashlib.sha256)
    return f"t={t},v1={mac.hexdigest()}"


def test_valid_signature_passes():
    body = b'{"external_id":"u1","pan":"ABCDE1234F"}'
    sig = _make_sig(body)
    verify_signature(body, sig, SECRET)  # should not raise


def test_missing_header_raises():
    with pytest.raises(WebhookSignatureError, match="missing"):
        verify_signature(b"body", None, SECRET)


def test_empty_header_raises():
    with pytest.raises(WebhookSignatureError):
        verify_signature(b"body", "", SECRET)


def test_wrong_secret_raises():
    body = b'{"x":1}'
    sig = _make_sig(body, secret="wrong-secret")
    with pytest.raises(WebhookSignatureError, match="mismatch"):
        verify_signature(body, sig, SECRET)


def test_expired_signature_raises():
    body = b'{"x":1}'
    old_ts = int(time.time()) - 400   # > 300 s ago
    sig = _make_sig(body, ts=old_ts)
    with pytest.raises(WebhookSignatureError, match="expired"):
        verify_signature(body, sig, SECRET)


def test_future_timestamp_raises():
    body = b'{"x":1}'
    future_ts = int(time.time()) + 120
    sig = _make_sig(body, ts=future_ts)
    with pytest.raises(WebhookSignatureError, match="future"):
        verify_signature(body, sig, SECRET)


def test_malformed_header_raises():
    with pytest.raises(WebhookSignatureError, match="must contain"):
        verify_signature(b"body", "no-equals-sign-at-all", SECRET)


def test_tampered_body_raises():
    original = b'{"x":1}'
    tampered = b'{"x":2}'
    sig = _make_sig(original)
    with pytest.raises(WebhookSignatureError, match="mismatch"):
        verify_signature(tampered, sig, SECRET)
