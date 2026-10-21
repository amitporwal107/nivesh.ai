"""Kite Connect minute-bar client: auth handshake and historical candle fetch.

Credentials resolve exactly as backend/services/brokers/zerodha.py does — GSM then env,
under BROKER_ZERODHA_API_KEY / BROKER_ZERODHA_API_SECRET — so there is one credential path
for the whole repo. Nothing here ever prints a key, a secret or an access token.

Kite's access_token expires daily (~06:00 IST) and renewal needs an interactive Zerodha
login, so `login_url` / `exchange_request_token` are run by a human once a day; every other
function takes the resulting token.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Kite caps a single historical_data call by interval; minute is the tightest.
MAX_DAYS = {"minute": 60, "3minute": 100, "5minute": 100, "15minute": 200, "60minute": 400, "day": 2000}
IST = "Asia/Kolkata"


# Local credential files, used only when GSM and env are both empty (dev / research runs).
# Values are read at call time and never printed, logged or passed through argv.
# One file, two lines: line 1 = api_key, line 2 = api_secret.
CRED_FILE = "/app/.KITE.API.KEY"
KEY_LINE, SECRET_LINE = 0, 1


def _from_file(line: int, path: str = CRED_FILE) -> str:
    """Read one line of the credential file. Never printed, logged or passed via argv."""
    try:
        with open(path) as fh:
            lines = [l.strip() for l in fh if l.strip()]
    except OSError:
        return ""
    return lines[line] if len(lines) > line else ""


def _conf(key: str, file_line: int = -1) -> str:
    """Read a Nivesh secret: GSM -> env -> local file (same order as brokers/zerodha.py,
    plus a file fallback so research runs need no shell-visible secrets)."""
    try:
        from helpers import secrets as _s
        v = (_s.get(key) or "").strip()
        if v:
            return v
    except Exception:  # noqa: BLE001 — secrets helper is optional outside the backend
        pass
    v = (os.environ.get(key) or "").strip()
    return v or (_from_file(file_line) if file_line >= 0 else "")


def api_key() -> str:
    return _conf("BROKER_ZERODHA_API_KEY", KEY_LINE)


def _api_secret() -> str:
    return _conf("BROKER_ZERODHA_API_SECRET", SECRET_LINE)


def kite(access_token: str = ""):
    """A kiteconnect.KiteConnect client; imported lazily so callers boot without the SDK."""
    try:
        from kiteconnect import KiteConnect
    except ImportError as e:
        raise RuntimeError("kiteconnect SDK not installed (pip install kiteconnect)") from e
    k = api_key()
    if not k:
        raise RuntimeError("BROKER_ZERODHA_API_KEY is unset (checked GSM then env)")
    kc = KiteConnect(api_key=k)
    if access_token:
        kc.set_access_token(access_token)
    return kc


def login_url() -> str:
    """The URL a human opens to log in. Safe to print: it carries the api_key only."""
    return kite().login_url()


def exchange_request_token(request_token: str) -> dict:
    """Trade the one-shot request_token for a daily access_token. Returns the raw session."""
    secret = _api_secret()
    if not secret:
        raise RuntimeError("BROKER_ZERODHA_API_SECRET is unset (checked GSM then env)")
    return kite().generate_session(request_token, api_secret=secret)


@dataclass(frozen=True)
class Instrument:
    token: int
    symbol: str
    exchange: str


def nse_equity_instruments(access_token: str) -> list[Instrument]:
    """Every NSE EQ instrument, for mapping symbol -> instrument_token."""
    rows = kite(access_token).instruments("NSE")
    return [Instrument(int(r["instrument_token"]), str(r["tradingsymbol"]), "NSE")
            for r in rows if r.get("segment") == "NSE" and r.get("instrument_type") == "EQ"]


def candles(access_token: str, token: int, start: date, end: date, interval: str = "minute") -> list[dict]:
    """Historical candles for one instrument. Kite bounds the window per interval, so callers
    that need more must chunk with `windows`."""
    return kite(access_token).historical_data(
        instrument_token=token, from_date=start, to_date=end, interval=interval, continuous=False, oi=False)


def windows(start: date, end: date, interval: str) -> list[tuple[date, date]]:
    """Split [start, end] into chunks Kite will accept for `interval`."""
    span = MAX_DAYS.get(interval, 60)
    out, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=span - 1), end)
        out.append((cur, stop))
        cur = stop + timedelta(days=1)
    return out
