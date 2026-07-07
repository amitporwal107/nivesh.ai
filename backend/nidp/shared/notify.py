"""Out-of-band operator notifications for NIDP jobs.

Dependency-free (stdlib `smtplib` only) email sender plus an optional
Telegram fallback that mirrors the gating pattern in
`deploy/vm/health_check.sh`. Every channel is **env-gated**: if the
channel isn't configured the send is a no-op that logs a warning and
returns False — it never raises, so a notification failure can never
take down the job that called it.

Why this exists: the recovery jobs (`feed_reconciler`, `dlq_redrive`)
need to tell a human when a gap could NOT be healed or a DLQ entry needs
investigation. The existing alert paths either don't reach a person
(Grafana → in-app banner) or are broken (`health_check.sh`), so these
jobs notify directly.

Configuration (all optional; read from the process env / nidp.env):
    Email (preferred channel — chosen for Phase 1):
        NIDP_ALERT_SMTP_HOST   e.g. smtp.gmail.com
        NIDP_ALERT_SMTP_PORT   default 587 (STARTTLS); 465 → implicit SSL
        NIDP_ALERT_SMTP_USER   SMTP login (optional for open relays)
        NIDP_ALERT_SMTP_PASS   SMTP password / app password
        NIDP_ALERT_EMAIL_FROM  From: address (defaults to SMTP_USER)
        NIDP_ALERT_EMAIL_TO    comma-separated recipient list
    Telegram (optional fallback — reuses health_check.sh's tokens):
        NIDP_TELEGRAM_BOT_TOKEN
        NIDP_TELEGRAM_CHAT_ID

Usage:
    from nidp.shared.notify import notify
    notify("NIDP reconciler: 2 gaps could not be healed", body=details)
"""
from __future__ import annotations

import logging
import os
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)


def _recipients() -> list[str]:
    raw = os.environ.get("NIDP_ALERT_EMAIL_TO", "")
    return [a.strip() for a in raw.split(",") if a.strip()]


def email_configured() -> bool:
    return bool(os.environ.get("NIDP_ALERT_SMTP_HOST")) and bool(_recipients())


def send_email(subject: str, body: str) -> bool:
    """Send one alert email. Returns True on success, False if the channel
    is unconfigured or the send failed (never raises)."""
    host = os.environ.get("NIDP_ALERT_SMTP_HOST")
    to_addrs = _recipients()
    if not host or not to_addrs:
        logger.warning(
            "notify.send_email: SMTP not configured "
            "(NIDP_ALERT_SMTP_HOST / NIDP_ALERT_EMAIL_TO) — skipping email: %s",
            subject,
        )
        return False

    port = int(os.environ.get("NIDP_ALERT_SMTP_PORT", "587"))
    user = os.environ.get("NIDP_ALERT_SMTP_USER")
    password = os.environ.get("NIDP_ALERT_SMTP_PASS")
    from_addr = os.environ.get("NIDP_ALERT_EMAIL_FROM") or user or "nidp-alerts@localhost"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                if user:
                    smtp.login(user, password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
                if user:
                    smtp.login(user, password or "")
                smtp.send_message(msg)
        logger.info("notify.send_email: sent %r to %s", subject, to_addrs)
        return True
    except Exception:                                              # noqa: BLE001
        logger.exception("notify.send_email: send failed for %r", subject)
        return False


def send_telegram(text: str) -> bool:
    """Optional fallback channel. Returns True on success, False otherwise
    (never raises)."""
    token = os.environ.get("NIDP_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("NIDP_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception:                                              # noqa: BLE001
        logger.exception("notify.send_telegram: send failed")
        return False


def notify(subject: str, body: Optional[str] = None) -> bool:
    """Send an operator alert over every configured channel.

    Email is the primary channel; Telegram is attempted too if configured.
    Returns True if at least one channel accepted the message. Logs and
    returns False (without raising) if no channel is configured — the
    caller (a recovery job) must never crash because alerting is down.
    """
    body = body or subject
    sent = False
    if email_configured():
        sent = send_email(subject, body) or sent
    if send_telegram(f"{subject}\n\n{body}"):
        sent = True
    if not sent:
        logger.warning(
            "notify: no alert channel is configured/available — alert NOT "
            "delivered (subject=%r). Configure NIDP_ALERT_SMTP_* to enable email.",
            subject,
        )
    return sent
