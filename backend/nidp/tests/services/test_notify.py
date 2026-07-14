"""Unit tests for nidp.shared.notify (email/telegram alert helper).

No network: SMTP is monkeypatched. Verifies the env-gating contract
(unconfigured → False, never raises) and the composed EmailMessage.
"""
from __future__ import annotations

from nidp.shared import notify


def _clear(monkeypatch):
    for k in ("NIDP_ALERT_SMTP_HOST", "NIDP_ALERT_EMAIL_TO",
              "NIDP_ALERT_SMTP_USER", "NIDP_ALERT_SMTP_PASS",
              "NIDP_ALERT_EMAIL_FROM", "NIDP_ALERT_SMTP_PORT",
              "NIDP_TELEGRAM_BOT_TOKEN", "NIDP_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)


def test_email_unconfigured_returns_false(monkeypatch):
    """TC-9: SMTP unconfigured → send_email returns False, no exception."""
    _clear(monkeypatch)
    assert notify.email_configured() is False
    assert notify.send_email("subject", "body") is False


def test_notify_no_channel_returns_false(monkeypatch):
    """TC-9: no channel configured → notify() returns False, never raises."""
    _clear(monkeypatch)
    assert notify.notify("subj", "body") is False


def test_email_configured_sends(monkeypatch):
    """TC-10: configured → builds EmailMessage(from/to/subject) + sends."""
    _clear(monkeypatch)
    monkeypatch.setenv("NIDP_ALERT_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("NIDP_ALERT_SMTP_PORT", "587")
    monkeypatch.setenv("NIDP_ALERT_EMAIL_TO", "ops@test.com, ops2@test.com")
    monkeypatch.setenv("NIDP_ALERT_EMAIL_FROM", "nidp@test.com")

    sent: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def has_extn(self, _x):
            return False

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["msg"] = msg

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)

    assert notify.email_configured() is True
    assert notify.send_email("Subj", "Body") is True
    assert sent["host"] == "smtp.test"
    assert sent["msg"]["To"] == "ops@test.com, ops2@test.com"
    assert sent["msg"]["From"] == "nidp@test.com"
    assert sent["msg"]["Subject"] == "Subj"
    assert sent["msg"].get_content().strip() == "Body"
