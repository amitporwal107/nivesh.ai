"""Live indices fetcher for the Market Dashboard.

Primary source: **yfinance** (no auth, no IP bans, refreshes during NSE
market hours with ~1 min lag — close enough for a positional dashboard).

Fetches in one batch:
  • ^NSEI         — Nifty 50
  • ^INDIAVIX     — India VIX
  • ^NSEBANK      — Nifty Bank
  • ^CNXIT        — Nifty IT
  • ^CNXAUTO      — Nifty Auto
  • ^CNXFMCG      — Nifty FMCG
  • ^CNXPHARMA    — Nifty Pharma
  • ^CNXMETAL     — Nifty Metal
  • ^CNXENERGY    — Nifty Energy
  • ^CNXINFRA     — Nifty Infra
  • ^CNXMEDIA     — Nifty Media
  • ^CNXPSUBANK   — Nifty PSU Bank
  • ^CNXREALTY    — Nifty Realty
  • ^CNXFINANCE   — Nifty Financial Services

Cached 30s during market hours, 5min after-hours.

Why not NSE allIndices? NSE blocks the cloud IP block we're hosted on
(403 Forbidden on the homepage cookie-prime). yfinance proxies through
Yahoo's CDN which works reliably from anywhere.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# yfinance ticker → human-readable sector name shown on the dashboard.
SECTOR_TICKERS: List[tuple] = [
    ("^NSEBANK",     "Bank"),
    ("^CNXIT",       "IT"),
    ("^CNXAUTO",     "Auto"),
    ("^CNXFMCG",     "FMCG"),
    ("^CNXPHARMA",   "Pharma"),
    ("^CNXMETAL",    "Metal"),
    ("^CNXENERGY",   "Energy"),
    ("^CNXINFRA",    "Infra"),
    ("^CNXMEDIA",    "Media"),
    ("^CNXPSUBANK",  "PSU Bank"),
    ("^CNXREALTY",   "Realty"),
    ("^CNXFINANCE",  "Financial Services"),
]
NIFTY_TICKER = "^NSEI"
VIX_TICKER = "^INDIAVIX"

ALL_TICKERS = [NIFTY_TICKER, VIX_TICKER] + [t for t, _ in SECTOR_TICKERS]

_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}

IST = timezone(timedelta(hours=5, minutes=30))


def _is_market_open_ist() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= minute <= 15 * 60 + 30


def _ttl() -> float:
    return 30.0 if _is_market_open_ist() else 300.0


def _sector_tone(rs_pct: Optional[float]) -> str:
    if rs_pct is None:
        return "COOL"
    if rs_pct >= 1.5:
        return "HOT"
    if rs_pct >= 0.4:
        return "WARM"
    if rs_pct >= -0.4:
        return "COOL"
    return "COLD"


def _vix_trend(pct: Optional[float]) -> str:
    if pct is None:
        return "FLAT"
    if pct > 1.0:
        return "RISING"
    if pct < -1.0:
        return "FALLING"
    return "FLAT"


def _fetch_yf_batch() -> Dict[str, Dict[str, float]]:
    """Synchronous yfinance call. Returns {ticker: {close, prev_close, change_pct}}.

    Uses period='2d' so we always have current + previous trading day's
    close — change_pct = (cur - prev) / prev * 100.
    """
    import yfinance as yf
    out: Dict[str, Dict[str, float]] = {}
    try:
        data = yf.download(
            " ".join(ALL_TICKERS),
            period="2d",
            interval="1d",
            progress=False,
            threads=True,
        )
        if data.empty:
            return out
        if "Close" not in data.columns:
            return out
        for t in ALL_TICKERS:
            try:
                col = data["Close"][t] if len(ALL_TICKERS) > 1 else data["Close"]
                series = col.dropna()
                if len(series) >= 2:
                    cur = float(series.iloc[-1])
                    prev = float(series.iloc[-2])
                    pct = (cur - prev) / prev * 100 if prev else None
                    out[t] = {
                        "close":      round(cur, 2),
                        "prev_close": round(prev, 2),
                        "change_pct": round(pct, 2) if pct is not None else None,
                    }
                elif len(series) == 1:
                    out[t] = {
                        "close":      round(float(series.iloc[-1]), 2),
                        "prev_close": None,
                        "change_pct": None,
                    }
            except (KeyError, IndexError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance indices batch failed: %s", e)
    return out


def _parse_to_snapshot(yf_out: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "nifty50":         None,
        "vix":             None,
        "advances":        None,
        "declines":        None,
        "advance_decline": None,
        "sectors":         [],
    }
    nifty = yf_out.get(NIFTY_TICKER)
    if nifty:
        out["nifty50"] = {
            "close":      nifty.get("close"),
            "change_pct": nifty.get("change_pct"),
        }
    vix = yf_out.get(VIX_TICKER)
    if vix:
        out["vix"] = {
            "value":      vix.get("close"),
            "change_pct": vix.get("change_pct"),
            "trend":      _vix_trend(vix.get("change_pct")),
        }
    nifty_pct = (nifty or {}).get("change_pct") or 0.0
    for ticker, name in SECTOR_TICKERS:
        s = yf_out.get(ticker)
        if not s:
            continue
        change = s.get("change_pct")
        rs = (change or 0.0) - nifty_pct
        out["sectors"].append({
            "sector":           name,
            "close":            s.get("close"),
            "change_pct":       change,
            "rs_vs_nifty_pp":   round(rs, 2),
            "tone":             _sector_tone(rs),
        })
    out["sectors"].sort(key=lambda r: (r.get("change_pct") or -999), reverse=True)
    return out


async def get_live_snapshot() -> Optional[Dict[str, Any]]:
    """Top-level: returns parsed + cached snapshot. Use this as the live
    overlay source for Market Dashboard."""
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _ttl():
        return _CACHE["data"]

    yf_out = await asyncio.to_thread(_fetch_yf_batch)
    if not yf_out:
        return _CACHE["data"]   # may be stale

    parsed = _parse_to_snapshot(yf_out)
    parsed["fetched_at"] = datetime.now(IST).isoformat()
    parsed["is_live"] = _is_market_open_ist()

    _CACHE["data"] = parsed
    _CACHE["ts"] = now
    return parsed
