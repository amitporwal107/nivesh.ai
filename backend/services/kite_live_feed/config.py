"""Configuration, credentials and the NSE session clock for the live quote feed.

Credentials are read at call time and never logged, returned or put in an error message:
  access token  : services.providers.kite_adapter.default_token()  (KITE_ACCESS_TOKEN secret, else the
                  file named by KITE_ACCESS_TOKEN_FILE, else the kite_bars daily token file)
  api key       : KITE_API_KEY, else line 1 ONLY of the file named by KITE_API_KEY_FILE, else
                  BROKER_ZERODHA_API_KEY. The API secret is never read: streaming and quotes need only key + token.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

IST = timezone(timedelta(hours=5, minutes=30))

ENABLED_ENV = "KITE_LIVE_FEED_ENABLED"
CADENCE_ENV = "KITE_LIVE_FEED_CADENCE_SECONDS"
FORCE_REST_ENV = "KITE_LIVE_FEED_FORCE_REST"
CADENCE_DEFAULT, CADENCE_MIN, CADENCE_MAX = 30, 2, 120
STALE_FACTOR = 2.5                      # data older than this many cadences is stale
MAX_INSTRUMENTS = 3000                  # Kite's per-connection WebSocket limit
REST_BATCH = 500                        # Kite's per-call limit for quote()
REST_SPACING_SECONDS = 1.1              # quote() is limited to 1 request/second
PRE_OPEN, OPEN, CLOSE = dtime(9, 0), dtime(9, 15), dtime(15, 30)
# Index options on the feed (NFO names, comma separated; empty turns them off), how many of the nearest unexpired expiries,
# and how many strikes each side of the at-the-money strike, CE and PE.
OPTION_UNDERLYINGS_ENV, OPTION_UNDERLYINGS_DEFAULT = "LIVE_OPTION_UNDERLYINGS", "NIFTY,BANKNIFTY"
OPTION_EXPIRIES_ENV, OPTION_EXPIRIES_DEFAULT = "LIVE_OPTION_EXPIRIES", 2
OPTION_STRIKES_ENV, OPTION_STRIKES_DEFAULT = "LIVE_OPTION_STRIKES_EACH_SIDE", 15
# The per-symbol Redis quote cache (seconds a key lives without a rewrite) and the 1-minute replay snapshots (days kept).
QUOTE_CACHE_TTL_ENV, QUOTE_CACHE_TTL_DEFAULT = "LIVE_QUOTE_CACHE_TTL_S", 600
MINUTE_TTL_ENV, MINUTE_TTL_DEFAULT = "LIVE_MINUTE_TTL_DAYS", 90


def _int_env(name: str, default: int, lo: int, hi: int, env: Optional[Dict[str, str]] = None) -> int:
    """An integer setting clamped to [lo, hi]; missing or unreadable is the default."""
    raw = (env if env is not None else os.environ).get(name)
    try:
        v = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def option_underlyings(env: Optional[Dict[str, str]] = None) -> List[str]:
    raw = (env if env is not None else os.environ).get(OPTION_UNDERLYINGS_ENV, OPTION_UNDERLYINGS_DEFAULT)
    out: List[str] = []
    for part in str(raw).split(","):
        s = part.strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def option_expiries(env: Optional[Dict[str, str]] = None) -> int:
    return _int_env(OPTION_EXPIRIES_ENV, OPTION_EXPIRIES_DEFAULT, 0, 4, env)


def option_strikes_each_side(env: Optional[Dict[str, str]] = None) -> int:
    return _int_env(OPTION_STRIKES_ENV, OPTION_STRIKES_DEFAULT, 0, 50, env)


def quote_cache_ttl_seconds(env: Optional[Dict[str, str]] = None) -> int:
    return _int_env(QUOTE_CACHE_TTL_ENV, QUOTE_CACHE_TTL_DEFAULT, 30, 86400, env)


def minute_ttl_days(env: Optional[Dict[str, str]] = None) -> int:
    return _int_env(MINUTE_TTL_ENV, MINUTE_TTL_DEFAULT, 1, 400, env)


def enabled(env: Optional[Dict[str, str]] = None) -> bool:
    raw = (env if env is not None else os.environ).get(ENABLED_ENV, "1")
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def cadence_seconds(env: Optional[Dict[str, str]] = None) -> int:
    """KITE_LIVE_FEED_CADENCE_SECONDS clamped to 2-120, default 30 (an unreadable value is the default)."""
    raw = (env if env is not None else os.environ).get(CADENCE_ENV)
    try:
        v = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return CADENCE_DEFAULT
    return max(CADENCE_MIN, min(CADENCE_MAX, v))


def stale_after_seconds(cadence: float) -> float:
    """Stale = the newest data is older than 2.5 cadences (75 s at the 30 s default)."""
    return STALE_FACTOR * cadence


def force_rest(env: Optional[Dict[str, str]] = None) -> bool:
    return str((env if env is not None else os.environ).get(FORCE_REST_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def get_token() -> str:
    from services.providers.kite_adapter import default_token
    return (default_token() or "").strip()


def get_api_key() -> str:
    try:
        from helpers import secrets
        v = (secrets.get("KITE_API_KEY") or "").strip()
    except Exception:  # noqa: BLE001 — the secrets helper is optional outside the backend
        v = ""
    v = v or os.environ.get("KITE_API_KEY", "").strip()
    if v:
        return v
    path = os.environ.get("KITE_API_KEY_FILE", "").strip()
    if path:
        try:
            with open(os.path.expanduser(path)) as fh:
                for line in fh:                       # line 1 only; the secret on line 2 is never read
                    return line.strip()
        except OSError:
            pass
    try:
        from nidp.services.kite_bars.client import api_key
        return (api_key() or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def fingerprint(token: str) -> str:
    """A non-reversible tag to tell "the token changed" without keeping or logging the token."""
    return hashlib.sha256(token.encode()).hexdigest()[:10] if token else ""


# ── session clock ────────────────────────────────────────────────────────────

def session_of(now: datetime, holidays: Set[date]) -> Tuple[str, str]:
    """(session, reason): NSE cash market 09:15-15:30 IST, pre-open from 09:00, closed on weekends and holidays."""
    t = now.astimezone(IST)
    if t.weekday() >= 5:
        return "closed", "weekend"
    if t.date() in holidays:
        return "closed", "holiday"
    c = t.time()
    if c < PRE_OPEN:
        return "closed", "before_open"
    if c < OPEN:
        return "pre_open", "pre_open"
    if c <= CLOSE:
        return "open", "regular_session"
    return "closed", "after_hours"


def last_close(now: datetime) -> datetime:
    """The most recent 15:30 IST on a weekday at or before `now` (holidays unknown here; the cost is one extra read)."""
    t = now.astimezone(IST)
    d = t.date()
    if t.time() < CLOSE or t.weekday() >= 5:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, CLOSE, tzinfo=IST)


async def load_holidays(day: date) -> Set[date]:
    """NSE cash-segment holidays on `day` (nidp.nse_holidays through the data platform). Raises when unreadable."""
    from services.copilot_tools import daas_client
    status, body = await daas_client.get_raw("/holidays", {"segment": "CM", "from": day.isoformat(), "to": day.isoformat()})
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise RuntimeError(f"holiday list: HTTP {status}")
    out: Set[date] = set()
    for r in body["data"]:
        try:
            out.add(date.fromisoformat(str(r.get("holiday_date"))[:10]))
        except (TypeError, ValueError):
            continue
    return out
