"""Transactional email sender (SMTP).

The app historically had NO outbound email path — the CAS-invite flow only
ever returned a shareable URL for the advisor to send by hand. The magic-link
whitelist-validation flow (routes/auth.py) is the first feature that must
actually *send* mail, so this module adds a small, dependency-free SMTP sender.

Config is read from the admin-managed secrets registry (helpers/secrets.py),
falling back to environment variables — same precedence as every other
integration in the app. Nothing here touches the user's Gmail: the product
promise is read-only Gmail access, so validation mail goes out over our own
SMTP relay, never the signed-in user's mailbox.

Keys (register in helpers/secrets.py KNOWN_SECRETS so the admin console can set
them):
    SMTP_HOST       — relay hostname (e.g. smtp.sendgrid.net). Unset = disabled.
    SMTP_PORT       — default 587 (STARTTLS) or 465 (implicit SSL)
    SMTP_USERNAME   — relay login
    SMTP_PASSWORD   — relay password / API key
    SMTP_FROM       — From header (e.g. 'Nivesh <no-reply@nivesh.ai>').
                      Falls back to SMTP_USERNAME when unset.
    SMTP_STARTTLS   — 'true' (default) to upgrade with STARTTLS on port 587.
                      Ignored when the port is 465 (implicit SSL is used).
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from helpers import secrets

logger = logging.getLogger(__name__)


def _cfg(key: str, default: str = "") -> str:
    val = secrets.get(key)
    return val if val else default


def is_configured() -> bool:
    """True when enough SMTP config exists to attempt a send.

    Host + credentials are the minimum. Without these we MUST NOT pretend a
    message went out — callers surface this as a real failure rather than
    silently succeeding.
    """
    return bool(_cfg("SMTP_HOST") and _cfg("SMTP_USERNAME") and _cfg("SMTP_PASSWORD"))


def _from_address() -> str:
    return _cfg("SMTP_FROM") or _cfg("SMTP_USERNAME")


def _build_message(to_email: str, subject: str, text_body: str, html_body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _from_address()
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    return msg


def _send_sync(msg: EmailMessage) -> None:
    """Blocking SMTP send — run via asyncio.to_thread from async callers."""
    host = _cfg("SMTP_HOST")
    port = int(_cfg("SMTP_PORT", "587") or "587")
    username = _cfg("SMTP_USERNAME")
    password = _cfg("SMTP_PASSWORD")
    use_starttls = _cfg("SMTP_STARTTLS", "true").lower() != "false"

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if use_starttls:
                server.starttls(context=context)
                server.ehlo()
            server.login(username, password)
            server.send_message(msg)


def _test_sync() -> dict:
    """Open a connection, do the TLS upgrade if configured, and authenticate —
    without sending a message. Mirrors _send_sync's connection logic so a green
    test means a real send would also connect + auth."""
    host = _cfg("SMTP_HOST")
    port = int(_cfg("SMTP_PORT", "587") or "587")
    username = _cfg("SMTP_USERNAME")
    password = _cfg("SMTP_PASSWORD")
    use_starttls = _cfg("SMTP_STARTTLS", "true").lower() != "false"

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
            server.login(username, password)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if use_starttls:
                server.starttls(context=context)
                server.ehlo()
            server.login(username, password)
    tls = "implicit-SSL" if port == 465 else ("STARTTLS" if use_starttls else "plaintext")
    return {"ok": True, "detail": f"Connected & authenticated to {host}:{port} ({tls})"}


async def test_connection() -> dict:
    """Admin 'Test' handler — verify SMTP host/port/creds/TLS without sending.
    Returns the {ok, detail|error} shape the admin secrets endpoint expects."""
    if not is_configured():
        return {"ok": False, "error": "SMTP not configured (need SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD)"}
    try:
        return await asyncio.to_thread(_test_sync)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}


async def send_email(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    """Send one email. Raises RuntimeError if SMTP isn't configured, and lets
    smtplib exceptions propagate so the caller can report a real failure."""
    if not is_configured():
        raise RuntimeError("SMTP is not configured (set SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD)")
    msg = _build_message(to_email, subject, text_body, html_body)
    await asyncio.to_thread(_send_sync, msg)


def build_validation_email(to_email: str, validation_url: str, expiry_hours: int) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the whitelist-validation mail.

    Kept as a pure function (no I/O) so it is unit-testable without an SMTP
    server or a database.
    """
    subject = "Confirm your email to access Nivesh"
    text_body = (
        f"Hi,\n\n"
        f"Confirm {to_email} to get access to Nivesh.\n\n"
        f"Open this link to verify — it expires in {expiry_hours} hours:\n"
        f"{validation_url}\n\n"
        f"Once verified, you'll be able to sign in with this address.\n\n"
        f"If you didn't request this, you can safely ignore this email — "
        f"no account or access is created until the link is opened.\n\n"
        f"— Nivesh\n"
    )
    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#0b0f0e;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e7ece9;">
    <div style="max-width:520px;margin:0 auto;padding:40px 28px;">
      <p style="font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#46e3a0;margin:0 0 18px;">Nivesh</p>
      <h1 style="font-size:24px;line-height:1.25;margin:0 0 14px;color:#ffffff;">Confirm your email</h1>
      <p style="font-size:15px;line-height:1.6;color:#aab4af;margin:0 0 24px;">
        Confirm <strong style="color:#e7ece9;">{to_email}</strong> to get access to Nivesh.
        This link expires in {expiry_hours} hours.
      </p>
      <p style="margin:0 0 28px;">
        <a href="{validation_url}"
           style="display:inline-block;background:#46e3a0;color:#06231a;font-weight:700;
                  text-decoration:none;padding:14px 26px;border-radius:10px;font-size:15px;">
          Verify email &rarr;
        </a>
      </p>
      <p style="font-size:13px;line-height:1.6;color:#7d877f;margin:0 0 8px;">
        Or paste this link into your browser:
      </p>
      <p style="font-size:13px;line-height:1.6;color:#46e3a0;word-break:break-all;margin:0 0 28px;">
        {validation_url}
      </p>
      <p style="font-size:12px;line-height:1.6;color:#6b746d;margin:0;border-top:1px solid #1b231f;padding-top:18px;">
        If you didn't request this, you can ignore this email — no access is granted
        until the link is opened.
      </p>
    </div>
  </body>
</html>
"""
    return subject, text_body, html_body


async def send_validation_email(to_email: str, validation_url: str, expiry_hours: int) -> None:
    subject, text_body, html_body = build_validation_email(to_email, validation_url, expiry_hours)
    await send_email(to_email, subject, text_body, html_body)
    logger.info("Sent whitelist-validation email")


def build_otp_email(to_email: str, code: str, expiry_minutes: int) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a 6-digit sign-in code.

    Pure function (no I/O) so it is unit-testable without SMTP or a database.
    The code is never logged; only this rendered body carries it.
    """
    subject = f"Your Nivesh sign-in code: {code}"
    text_body = (
        f"Hi,\n\n"
        f"Your one-time sign-in code for Nivesh is:\n\n"
        f"    {code}\n\n"
        f"Enter it on the login screen to sign in as {to_email}. "
        f"It expires in {expiry_minutes} minutes.\n\n"
        f"If you didn't request this, you can safely ignore this email — "
        f"the code is useless without access to the login screen.\n\n"
        f"— Nivesh\n"
    )
    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#0b0f0e;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#e7ece9;">
    <div style="max-width:520px;margin:0 auto;padding:40px 28px;">
      <p style="font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#46e3a0;margin:0 0 18px;">Nivesh</p>
      <h1 style="font-size:24px;line-height:1.25;margin:0 0 14px;color:#ffffff;">Your sign-in code</h1>
      <p style="font-size:15px;line-height:1.6;color:#aab4af;margin:0 0 24px;">
        Enter this code to sign in as <strong style="color:#e7ece9;">{to_email}</strong>.
        It expires in {expiry_minutes} minutes.
      </p>
      <p style="margin:0 0 28px;">
        <span style="display:inline-block;background:#0f1613;border:1px solid #1b231f;border-radius:12px;
                     padding:18px 30px;font-size:34px;font-weight:700;letter-spacing:.32em;
                     color:#ffffff;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">
          {code}
        </span>
      </p>
      <p style="font-size:12px;line-height:1.6;color:#6b746d;margin:0;border-top:1px solid #1b231f;padding-top:18px;">
        If you didn't request this, you can ignore this email — the code is
        useless without access to the login screen.
      </p>
    </div>
  </body>
</html>
"""
    return subject, text_body, html_body


async def send_otp_email(to_email: str, code: str, expiry_minutes: int) -> None:
    subject, text_body, html_body = build_otp_email(to_email, code, expiry_minutes)
    await send_email(to_email, subject, text_body, html_body)
    logger.info("Sent sign-in OTP email")
