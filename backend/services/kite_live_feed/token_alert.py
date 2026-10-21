"""Morning alert when the platform Kite session is missing.

On NSE trading days from 08:30 IST, while there is no valid platform token (none stored, expired, or Kite refuses it), an
alert goes out every KITE_TOKEN_ALERT_INTERVAL_MIN minutes (default 30) with a freshly created login link and the time left to
the open. When a valid token appears, ONE "Kite connected" confirmation is sent and the alerts stop. After the 15:30 close the
alerts stop quietly; non-trading days are silent.

Channels are the repo's own notifiers (nidp/shared/notify.py): email when NIDP_ALERT_SMTP_HOST + NIDP_ALERT_EMAIL_TO
are set, Telegram when NIDP_TELEGRAM_BOT_TOKEN + NIDP_TELEGRAM_CHAT_ID are set; if neither fires, the app mailer
(services/email_service.py) to KITE_TOKEN_ALERT_EMAIL_TO when its SMTP secrets exist. The channels that fired are logged. A failing
or unconfigured channel never raises into the feed.

Idempotent across containers: the day's state is one Mongo doc (`kite_live_snapshot` / `token_alert`), and a send is claimed
by an atomic conditional update on `last_sent_at`, so two containers cannot both send for the same interval.
This is NOT an auto-login: a human taps the link (Zerodha 2FA); nothing here logs in for them.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from . import config as cfg
from . import platform_token as pt

logger = logging.getLogger(__name__)

INTERVAL_ENV, INTERVAL_DEFAULT_MIN = "KITE_TOKEN_ALERT_INTERVAL_MIN", 30
START, OPEN, CLOSE = dtime(8, 30), dtime(9, 15), dtime(15, 30)
DOC_ID = "token_alert"
STATE_NAME = "TOKEN_ALERT"


def interval_minutes(env: Optional[Dict[str, str]] = None) -> int:
    raw = (env if env is not None else os.environ).get(INTERVAL_ENV)
    try:
        v = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return INTERVAL_DEFAULT_MIN
    return max(5, min(240, v))


def default_notifier(subject: str, body: str) -> List[str]:
    """Send over every configured operator channel; returns the channels that accepted the message."""
    from nidp.shared import notify as n
    fired: List[str] = []
    if n.email_configured() and n.send_email(subject, body):
        fired.append("email")
    if n.send_telegram(f"{subject}\n\n{body}"):
        fired.append("telegram")
    if not fired:
        # The app's own mailer (SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD in the secrets store), to the addresses named in
        # KITE_TOKEN_ALERT_EMAIL_TO. No default recipient is invented.
        to = [a.strip() for a in os.environ.get("KITE_TOKEN_ALERT_EMAIL_TO", "").split(",") if a.strip()]
        try:
            from services import email_service
            if to and email_service.is_configured():
                import html
                for addr in to:
                    asyncio.run(email_service.send_email(addr, subject, body, f"<pre>{html.escape(body)}</pre>"))
                fired.append("app_email")
        except Exception as e:  # noqa: BLE001
            logger.warning("kite token alert: app mailer failed (%s)", type(e).__name__)
    return fired


def time_to_open(now: datetime) -> str:
    t = now.astimezone(cfg.IST)
    opens = datetime.combine(t.date(), OPEN, tzinfo=cfg.IST)
    if t >= opens:
        return "The market is already open, so live prices are down right now."
    mins = int((opens - t).total_seconds() // 60)
    h, m = divmod(mins, 60)
    return f"The market opens at 09:15 IST, in {h}h {m}m." if h else f"The market opens at 09:15 IST, in {m} minutes."


class TokenAlerter:
    def __init__(self, db, *, notifier: Callable[[str, str], List[str]] = default_notifier, interval_min: Optional[int] = None,
                 collection: str = "kite_live_snapshot", key_getter: Callable[[], str] = cfg.get_api_key):
        self.db, self.notifier, self.col, self.key_getter = db, notifier, collection, key_getter
        self.interval_min = interval_min if interval_min is not None else interval_minutes()
        self.active = False
        self.count = 0
        self.last_sent_at: Optional[datetime] = None
        self.confirmed = False
        self.last_channels: List[str] = []

    def state(self) -> Dict[str, Any]:
        return {"state": STATE_NAME if self.active else None, "alerts_sent_today": self.count, "confirmed": self.confirmed,
                "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None, "interval_minutes": self.interval_min}

    async def _send(self, subject: str, body: str) -> List[str]:
        try:
            fired = await asyncio.to_thread(self.notifier, subject, body)
        except Exception as e:  # noqa: BLE001 — alerting must never break the feed
            logger.warning("kite token alert: notifier failed (%s)", type(e).__name__)
            fired = []
        self.last_channels = list(fired or [])
        if fired:
            logger.info("kite token alert: %r sent via %s", subject, ",".join(fired))
        else:
            logger.warning("kite token alert: %r NOT delivered, no channel accepted it (set NIDP_ALERT_SMTP_* or NIDP_TELEGRAM_*)", subject)
        return self.last_channels

    async def run_pass(self, now: datetime, *, valid: bool, reason: str) -> Dict[str, Any]:
        """One pass, called by the feed leader each tick. `valid` = the platform token works; `reason` = the session reason."""
        now = now.astimezone(timezone.utc)
        t = now.astimezone(cfg.IST)
        day = t.date().isoformat()
        out: Dict[str, Any] = {"sent": False, "confirmed": False}
        coll = self.db[self.col]
        doc = await coll.find_one({"_id": DOC_ID})
        if not doc or doc.get("day") != day:
            doc = {"_id": DOC_ID, "day": day, "count": 0, "last_sent_at": None, "confirmed": False, "updated_at": now}
            await coll.replace_one({"_id": DOC_ID}, doc, upsert=True)
        self.count, self.confirmed = int(doc.get("count") or 0), bool(doc.get("confirmed"))
        self.last_sent_at = pt.aware(doc.get("last_sent_at"))
        trading_day = reason not in ("weekend", "holiday")
        if valid:
            self.active = False
            if self.count > 0 and not self.confirmed:
                res = await coll.update_one({"_id": DOC_ID, "day": day, "confirmed": False}, {"$set": {"confirmed": True, "updated_at": now}})
                if res.matched_count:
                    self.confirmed = True
                    await self._send("Kite connected: live prices are back", "The platform Kite session is valid again. Live prices resumed. No further reminders today.")
                    out["confirmed"] = True
            return out
        in_window = trading_day and START <= t.time() < CLOSE
        self.active = in_window
        if not in_window:
            return out
        cutoff = now - timedelta(minutes=self.interval_min)
        res = await coll.update_one(
            {"_id": DOC_ID, "day": day, "$or": [{"last_sent_at": None}, {"last_sent_at": {"$lte": cutoff}}]},
            {"$set": {"last_sent_at": now, "updated_at": now}, "$inc": {"count": 1}})
        if not res.matched_count:
            return out                                           # not due, or another container claimed this interval
        self.count += 1
        self.last_sent_at = now
        key = ""
        try:
            key = self.key_getter()
            state = await pt.create_login_state(self.db, "token_alert", now)
            link = pt.login_url(key, state["state"]) if key else "(KITE_API_KEY is not configured, so no login link can be made)"
            valid_for = f"This link works once and expires in {pt.state_ttl_minutes()} minutes; the next reminder carries a new one."
        except Exception as e:  # noqa: BLE001
            logger.warning("kite token alert: login link could not be created (%s)", type(e).__name__)
            link, valid_for = "(login link could not be created; use Live feed > Log in to Kite in the app)", ""
        body = "\n".join(x for x in [
            "The platform Kite session for live prices is not connected, so the desk and every screen show end-of-day figures.",
            time_to_open(now),
            f"Log in to Kite (a human step, Zerodha 2FA): {link}",
            valid_for,
            f"Reminder #{self.count} today; one every {self.interval_min} minutes until Kite is connected.",
        ] if x)
        await self._send("Kite login needed: live prices are off", body)
        out["sent"] = True
        return out
