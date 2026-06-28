"""Unit tests for the magic-link email path (services/email_service.py).

Pure / no-I/O coverage — no SMTP server or database required, so these run
anywhere. They lock down: (1) config gating (we never claim to send when SMTP
is unconfigured), (2) the validation-email content (link, expiry, address all
present in both text and HTML parts), and (3) the From-address fallback.
"""
import asyncio

import pytest

from helpers import secrets
from services import email_service


@pytest.fixture(autouse=True)
def _clear_smtp_overrides():
    """Ensure each test starts with no SMTP overrides in the secrets cache."""
    keys = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_STARTTLS"]
    saved = {k: secrets.get(k) for k in keys}
    for k in keys:
        secrets.set_override(k, None)
    yield
    for k, v in saved.items():
        secrets.set_override(k, v or None)


def test_is_configured_false_without_secrets():
    assert email_service.is_configured() is False


def test_is_configured_requires_host_user_and_password():
    secrets.set_override("SMTP_HOST", "smtp.example.com")
    assert email_service.is_configured() is False  # still missing user/pass
    secrets.set_override("SMTP_USERNAME", "apikey")
    assert email_service.is_configured() is False  # still missing pass
    secrets.set_override("SMTP_PASSWORD", "s3cret")
    assert email_service.is_configured() is True


def test_send_email_raises_when_not_configured():
    with pytest.raises(RuntimeError):
        asyncio.run(email_service.send_email("a@gmail.com", "s", "t", "<p>t</p>"))


def test_test_connection_reports_not_configured():
    res = asyncio.run(email_service.test_connection())
    assert res["ok"] is False
    assert "not configured" in res["error"].lower()


def test_from_address_falls_back_to_username():
    secrets.set_override("SMTP_USERNAME", "no-reply@nivesh.ai")
    assert email_service._from_address() == "no-reply@nivesh.ai"
    secrets.set_override("SMTP_FROM", "Nivesh <hello@nivesh.ai>")
    assert email_service._from_address() == "Nivesh <hello@nivesh.ai>"


def test_build_validation_email_contains_link_email_and_expiry():
    url = "https://app.niveshcopilot.com/api/auth/magic-link/validate?token=abc123"
    subject, text, html = email_service.build_validation_email("user@gmail.com", url, 24)

    assert "Nivesh" in subject
    for body in (text, html):
        assert url in body
        assert "user@gmail.com" in body
        assert "24 hours" in body
    # The HTML part must render the link as a clickable anchor.
    assert f'href="{url}"' in html


def test_build_message_sets_headers_and_multipart():
    secrets.set_override("SMTP_FROM", "Nivesh <no-reply@nivesh.ai>")
    msg = email_service._build_message(
        "user@gmail.com", "Subject here", "text body", "<p>html body</p>",
    )
    assert msg["To"] == "user@gmail.com"
    assert msg["From"] == "Nivesh <no-reply@nivesh.ai>"
    assert msg["Subject"] == "Subject here"
    # multipart/alternative: a plain part + an html part
    parts = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in parts
    assert "text/html" in parts
