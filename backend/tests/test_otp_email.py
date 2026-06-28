"""Unit tests for the OTP sign-in email path (services/email_service.py).

Pure / no-I/O coverage — mirrors test_magic_link_email.py. Locks down that the
code and expiry appear in both the text and HTML parts, the subject is header-
safe, and we never claim to send when SMTP is unconfigured. The route logic
(/auth/otp/*) needs the app/DB and is exercised in the integration env.
"""
import asyncio

import pytest

from helpers import secrets
from services import email_service


@pytest.fixture(autouse=True)
def _clear_smtp_overrides():
    """Each test starts with no SMTP overrides in the secrets cache."""
    keys = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_STARTTLS"]
    saved = {k: secrets.get(k) for k in keys}
    for k in keys:
        secrets.set_override(k, None)
    yield
    for k, v in saved.items():
        secrets.set_override(k, v or None)


def test_build_otp_email_contains_code_and_expiry():
    subject, text, html = email_service.build_otp_email("user@outlook.com", "123456", 10)
    assert "Nivesh" in subject
    assert "123456" in subject          # code surfaced in the subject for quick scan
    for body in (text, html):
        assert "123456" in body
        assert "10 minutes" in body


def test_build_otp_email_subject_is_header_safe():
    # No CR/LF in the subject — guards against header injection via the code.
    subject, _, _ = email_service.build_otp_email("user@outlook.com", "000111", 10)
    assert "\n" not in subject and "\r" not in subject


def test_send_otp_email_raises_when_not_configured():
    # Never pretend a code went out when SMTP is unconfigured.
    with pytest.raises(RuntimeError):
        asyncio.run(email_service.send_otp_email("user@outlook.com", "123456", 10))
