"""Kite Connect wiring for research/index_history.

Reuses the existing, working client at nidp.services.kite_bars (backend worktree) for
auth and historical-candle fetch, instead of duplicating credential handling. That
worktree is added to sys.path lazily, only inside this module.

Nothing here ever prints, logs, or returns the api key, secret, or access token; only
`get_access_token()` returns the token value itself, and callers must not print it.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from typing import Any

# The worktree that owns the working Kite client (see task brief). Added once, lazily,
# so importing this module has no effect until a caller actually needs the client.
_BACKEND_PATH = "/app/.claude/worktrees/sweep/backend"

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 2.0
BETWEEN_CHUNK_SECONDS = 0.35  # politeness delay between chunked historical_data calls


def _ensure_backend_on_path() -> None:
    if _BACKEND_PATH not in sys.path:
        sys.path.insert(0, _BACKEND_PATH)


def get_access_token() -> str:
    """Today's Kite access token from the daily-refreshed token file. Empty if absent."""
    _ensure_backend_on_path()
    from nidp.services.kite_bars.auth import read_token
    return read_token()


def connect(access_token: str):
    """A kiteconnect.KiteConnect client, authenticated with `access_token`."""
    _ensure_backend_on_path()
    from nidp.services.kite_bars.client import kite
    return kite(access_token)


def indices_catalog(kc) -> list[dict]:
    """Every NSE instrument in the INDICES segment, straight from kc.instruments('NSE') —
    never hard-coded."""
    rows = kc.instruments("NSE")
    return [r for r in rows if r.get("segment") == "INDICES"]


def resolve(kc, names: list[str]) -> tuple[dict[str, int], list[str]]:
    """Exact tradingsymbol match against the live INDICES catalog.

    Returns (found: {name: instrument_token}, missing: [name, ...]).
    """
    catalog = {r["tradingsymbol"]: r for r in indices_catalog(kc)}
    found: dict[str, int] = {}
    missing: list[str] = []
    for name in names:
        row = catalog.get(name)
        if row is None:
            missing.append(name)
        else:
            found[name] = int(row["instrument_token"])
    return found, missing


def day_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into chunks Kite's day-interval endpoint accepts (~2000 days)."""
    _ensure_backend_on_path()
    from nidp.services.kite_bars.client import windows
    return windows(start, end, "day")


def fetch_day_history(kc, token: int, start: date, end: date) -> list[dict[str, Any]]:
    """Chunked, day-interval historical fetch for one instrument, with polite retry/
    backoff on transient/rate-limit errors. Returns kiteconnect's raw candle dicts
    (date/open/high/low/close/volume/oi), unsorted across chunks (caller dedupes/sorts)."""
    rows: list[dict[str, Any]] = []
    for w_start, w_end in day_windows(start, end):
        attempt = 0
        while True:
            try:
                chunk = kc.historical_data(
                    instrument_token=token,
                    from_date=w_start,
                    to_date=w_end,
                    interval="day",
                    continuous=False,
                    oi=False,
                )
                rows.extend(chunk)
                break
            except Exception:  # kiteconnect raises its own exception hierarchy
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        time.sleep(BETWEEN_CHUNK_SECONDS)
    return rows
