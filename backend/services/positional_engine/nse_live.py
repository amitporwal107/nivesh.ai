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
SENSEX_TICKER = "^BSESN"   # BSE Sensex (the one non-NSE index we surface)
VIX_TICKER = "^INDIAVIX"

# Nifty 50 constituents (yfinance ".NS" tickers) → display name. Used to
# derive live gainers/losers + breadth when the NIDP data lake (richer,
# Nifty-500) isn't populated. Maintained here like SECTOR_TICKERS; yfinance
# silently skips any ticker it can't resolve, so a stale name just drops out.
NIFTY50_CONSTITUENTS: List[tuple] = [
    ("RELIANCE.NS", "Reliance Industries"), ("HDFCBANK.NS", "HDFC Bank"),
    ("ICICIBANK.NS", "ICICI Bank"), ("INFY.NS", "Infosys"), ("TCS.NS", "TCS"),
    ("ITC.NS", "ITC"), ("LT.NS", "Larsen & Toubro"), ("BHARTIARTL.NS", "Bharti Airtel"),
    ("SBIN.NS", "State Bank of India"), ("AXISBANK.NS", "Axis Bank"),
    ("KOTAKBANK.NS", "Kotak Mahindra Bank"), ("HINDUNILVR.NS", "Hindustan Unilever"),
    ("BAJFINANCE.NS", "Bajaj Finance"), ("M&M.NS", "Mahindra & Mahindra"),
    ("MARUTI.NS", "Maruti Suzuki"), ("SUNPHARMA.NS", "Sun Pharma"), ("NTPC.NS", "NTPC"),
    ("TATAMOTORS.NS", "Tata Motors"), ("HCLTECH.NS", "HCL Technologies"), ("TITAN.NS", "Titan"),
    ("ULTRACEMCO.NS", "UltraTech Cement"), ("POWERGRID.NS", "Power Grid"),
    ("ASIANPAINT.NS", "Asian Paints"), ("WIPRO.NS", "Wipro"), ("NESTLEIND.NS", "Nestlé India"),
    ("ADANIENT.NS", "Adani Enterprises"), ("ADANIPORTS.NS", "Adani Ports"), ("ONGC.NS", "ONGC"),
    ("COALINDIA.NS", "Coal India"), ("TATASTEEL.NS", "Tata Steel"), ("JSWSTEEL.NS", "JSW Steel"),
    ("BAJAJFINSV.NS", "Bajaj Finserv"), ("GRASIM.NS", "Grasim"), ("HINDALCO.NS", "Hindalco"),
    ("TECHM.NS", "Tech Mahindra"), ("DRREDDY.NS", "Dr. Reddy's"), ("CIPLA.NS", "Cipla"),
    ("BRITANNIA.NS", "Britannia"), ("EICHERMOT.NS", "Eicher Motors"), ("APOLLOHOSP.NS", "Apollo Hospitals"),
    ("BPCL.NS", "BPCL"), ("HEROMOTOCO.NS", "Hero MotoCorp"), ("INDUSINDBK.NS", "IndusInd Bank"),
    ("TATACONSUM.NS", "Tata Consumer"), ("BAJAJ-AUTO.NS", "Bajaj Auto"), ("SBILIFE.NS", "SBI Life"),
    ("HDFCLIFE.NS", "HDFC Life"), ("LTIM.NS", "LTIMindtree"), ("SHRIRAMFIN.NS", "Shriram Finance"),
    ("TRENT.NS", "Trent"), ("BEL.NS", "Bharat Electronics"),
]

ALL_TICKERS = (
    [NIFTY_TICKER, SENSEX_TICKER, VIX_TICKER]
    + [t for t, _ in SECTOR_TICKERS]
    + [t for t, _ in NIFTY50_CONSTITUENTS]
)

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
        "sensex":          None,
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
    sensex = yf_out.get(SENSEX_TICKER)
    if sensex:
        out["sensex"] = {
            "close":      sensex.get("close"),
            "change_pct": sensex.get("change_pct"),
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

    # ── Live gainers / losers + breadth from the Nifty-50 universe ──────
    movers: List[Dict[str, Any]] = []
    advances = declines = unchanged = 0
    for ticker, name in NIFTY50_CONSTITUENTS:
        s = yf_out.get(ticker)
        if not s:
            continue
        change = s.get("change_pct")
        if change is None:
            continue
        movers.append({
            "symbol":     ticker.replace(".NS", ""),
            "name":       name,
            "close":      s.get("close"),
            "change_pct": change,
        })
        if change > 0.05:
            advances += 1
        elif change < -0.05:
            declines += 1
        else:
            unchanged += 1
    if movers:
        ranked = sorted(movers, key=lambda m: m["change_pct"], reverse=True)
        out["gainers"] = ranked[:4]
        out["losers"] = sorted(movers, key=lambda m: m["change_pct"])[:4]
        out["breadth"] = {
            "advances":  advances,
            "declines":  declines,
            "unchanged": unchanged,
            "universe":  len(movers),
        }
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


# ── Index tape sparklines ───────────────────────────────────────────────
# The six benchmarks the Markets "tape" shows, each with a daily-close
# sparkline. (display name, yfinance ticker, is_vix). Smallcap has no
# reliable yfinance daily-history ticker, so the broad Nifty 500 takes the
# sixth slot — a real index rather than an empty tile.
TAPE_INDICES: List[tuple] = [
    ("Nifty 50",        "^NSEI",      False),
    ("Sensex",          "^BSESN",     False),
    ("Nifty Bank",      "^NSEBANK",   False),
    ("Nifty Midcap 50", "^NSEMDCP50", False),
    ("Nifty 500",       "^CRSLDX",    False),
    ("India VIX",       "^INDIAVIX",  True),
]

_SPARK_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def _fetch_index_history() -> Dict[str, List[float]]:
    """Daily closes (~1 month) per tape ticker, for sparklines.

    Synchronous yfinance call. Any ticker Yahoo can't resolve simply drops
    out — the caller renders that tile without a sparkline.
    """
    import yfinance as yf
    tickers = [t for _, t, _ in TAPE_INDICES]
    out: Dict[str, List[float]] = {}
    try:
        data = yf.download(
            " ".join(tickers), period="1mo", interval="1d",
            progress=False, threads=True,
        )
        if data.empty or "Close" not in data.columns:
            return out
        for t in tickers:
            try:
                col = data["Close"][t] if len(tickers) > 1 else data["Close"]
                series = [round(float(x), 2) for x in col.dropna().tolist()]
                if series:
                    out[t] = series[-24:]   # last ~24 sessions is enough to read
            except (KeyError, IndexError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance index history failed: %s", e)
    return out


async def get_index_tape() -> List[Dict[str, Any]]:
    """Six benchmark tiles with value, change_pct and a daily-close sparkline.

    Daily bars move slowly, so this is cached for 10 min regardless of
    session state. value/change_pct are derived from the EOD series tail;
    callers may overlay fresher intraday values from get_live_snapshot().
    A tile whose history is unavailable still returns with value=None and an
    empty spark so the caller can decide whether to drop it.
    """
    now = time.time()
    if _SPARK_CACHE["data"] and (now - _SPARK_CACHE["ts"]) < 600.0:
        return _SPARK_CACHE["data"]

    hist = await asyncio.to_thread(_fetch_index_history)
    if not hist:
        return _SPARK_CACHE["data"] or []   # keep last good tape if Yahoo blips

    tape: List[Dict[str, Any]] = []
    for name, ticker, is_vix in TAPE_INDICES:
        series = hist.get(ticker) or []
        value = series[-1] if series else None
        prev = series[-2] if len(series) >= 2 else None
        change_pct = round((value - prev) / prev * 100, 2) if value is not None and prev else None
        tape.append({
            "name":       name,
            "value":      value,
            "change_pct": change_pct,
            "is_vix":     is_vix,
            "trend":      _vix_trend(change_pct) if is_vix else None,
            "spark":      series,
        })

    _SPARK_CACHE["data"] = tape
    _SPARK_CACHE["ts"] = now
    return tape


# ── Global cues, world indices & commodities ────────────────────────────
# yfinance covers world indices, commodity futures and FX out of the box, so
# the Markets page's "global cues", "global indices" and "commodities" rows
# run off the same proxy as the NSE snapshot. US/Europe print their previous
# close while Asia and futures tick live; period='2d' yields change vs the
# prior session in every case. Nothing here is recomputed — it's a passthrough
# of real Yahoo quotes, and any ticker Yahoo can't resolve simply drops out.

GLOBAL_INDEX_TICKERS: List[tuple] = [
    # (ticker, name, region, sub)
    ("^DJI",      "Dow Jones",     "us",     "US"),
    ("^GSPC",     "S&P 500",       "us",     "US"),
    ("^IXIC",     "Nasdaq",        "us",     "US"),
    ("^FTSE",     "FTSE 100",      "europe", "UK"),
    ("^GDAXI",    "DAX",           "europe", "DE"),
    ("^FCHI",     "CAC 40",        "europe", "FR"),
    ("^STOXX50E", "Euro Stoxx 50", "europe", "EU"),
    ("^N225",     "Nikkei 225",    "asia",   "JP"),
    ("^HSI",      "Hang Seng",     "asia",   "HK"),
    ("000001.SS", "Shanghai",      "asia",   "CN"),
    ("^KS11",     "Kospi",         "asia",   "KR"),
    ("^AXJO",     "ASX 200",       "asia",   "AU"),
    ("^STI",      "Straits Times", "asia",   "SG"),
]

COMMODITY_TICKERS: List[tuple] = [
    # (ticker, name, unit)
    ("BZ=F", "Brent Crude", "$/bbl"),
    ("CL=F", "WTI Crude",   "$/bbl"),
    ("NG=F", "Natural Gas", "$/MMBtu"),
    ("GC=F", "Gold",        "$/oz"),
    ("SI=F", "Silver",      "$/oz"),
]

# "Global cues / pre-market" — the handful of prints that set the tone for the
# Indian open. featured=True renders as the highlighted lead card. (GIFT Nifty
# and the India 10Y G-Sec have no reliable free Yahoo feed, so we surface the
# fetchable global tone-setters instead of faking those two.)
CUE_TICKERS: List[tuple] = [
    # (ticker, name, sub, featured)
    ("ES=F",  "S&P 500 Futures", "pre-market", True),
    ("INR=X", "USD / INR",       "spot",       False),
    ("BZ=F",  "Brent Crude",     "$/bbl",      False),
    ("^TNX",  "US 10Y Treasury", "yield %",    False),
]

_GLOBAL_TICKERS = sorted(
    {t for t, *_ in GLOBAL_INDEX_TICKERS}
    | {t for t, *_ in COMMODITY_TICKERS}
    | {t for t, *_ in CUE_TICKERS}
)

_GLOBAL_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def _fetch_global_batch() -> Dict[str, Dict[str, Any]]:
    """Synchronous yfinance batch for world indices, commodity futures and FX.

    Returns {ticker: {close, change_pct}} using the same 2-day window logic as
    the NSE batch so change_pct is always vs the prior session.
    """
    import yfinance as yf
    out: Dict[str, Dict[str, Any]] = {}
    try:
        data = yf.download(
            " ".join(_GLOBAL_TICKERS),
            period="2d",
            interval="1d",
            progress=False,
            threads=True,
        )
        if data.empty or "Close" not in data.columns:
            return out
        for t in _GLOBAL_TICKERS:
            try:
                col = data["Close"][t] if len(_GLOBAL_TICKERS) > 1 else data["Close"]
                series = col.dropna()
                if len(series) >= 2:
                    cur = float(series.iloc[-1])
                    prev = float(series.iloc[-2])
                    pct = (cur - prev) / prev * 100 if prev else None
                    out[t] = {
                        "close":      round(cur, 2),
                        "change_pct": round(pct, 2) if pct is not None else None,
                    }
                elif len(series) == 1:
                    out[t] = {"close": round(float(series.iloc[-1]), 2), "change_pct": None}
            except (KeyError, IndexError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance global batch failed: %s", e)
    return out


async def get_global_snapshot() -> Optional[Dict[str, Any]]:
    """Global cues, world indices (US / Europe / Asia) and commodities for the
    Markets page. Cached 60s. Returns None only when we have no data at all
    (no cache and the fetch failed)."""
    now = time.time()
    if _GLOBAL_CACHE["data"] and (now - _GLOBAL_CACHE["ts"]) < 60.0:
        return _GLOBAL_CACHE["data"]

    raw = await asyncio.to_thread(_fetch_global_batch)
    if not raw:
        return _GLOBAL_CACHE["data"]   # may be stale

    def _quote(ticker, name, *, sub=None, region=None, unit=None, featured=False):
        q = raw.get(ticker)
        if not q or q.get("close") is None:
            return None
        return {
            "name":       name,
            "sub":        sub,
            "value":      q.get("close"),
            "change_pct": q.get("change_pct"),
            "region":     region,
            "unit":       unit,
            "featured":   featured,
        }

    global_indices: Dict[str, List[Dict[str, Any]]] = {"us": [], "europe": [], "asia": []}
    for t, name, region, sub in GLOBAL_INDEX_TICKERS:
        q = _quote(t, name, sub=sub, region=region)
        if q:
            global_indices[region].append(q)

    commodities = [q for t, name, unit in COMMODITY_TICKERS
                   if (q := _quote(t, name, unit=unit))]
    cues = [q for t, name, sub, featured in CUE_TICKERS
            if (q := _quote(t, name, sub=sub, featured=featured))]

    result = {
        "global_cues":    cues,
        "global_indices": global_indices,
        "commodities":    commodities,
        "fetched_at":     datetime.now(IST).isoformat(),
    }
    _GLOBAL_CACHE["data"] = result
    _GLOBAL_CACHE["ts"] = now
    return result


# ── "Explore" lists: 52-week high / low + most active ───────────────────
# One 1-year daily batch over the Nifty-50 universe gives us 52-week
# high/low distance and the latest day's volume. Cached 5 min (52w levels
# move slowly; this backs an on-demand drawer, not a ticker).
_EXPLORE_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def _fetch_explore_batch() -> Dict[str, Dict[str, Any]]:
    """Synchronous yfinance 1y history for the Nifty-50 universe.

    Returns {ticker: {close, change_pct, high_52w, low_52w, volume, turnover}}.
    """
    import yfinance as yf
    tickers = [t for t, _ in NIFTY50_CONSTITUENTS]
    out: Dict[str, Dict[str, Any]] = {}
    try:
        data = yf.download(
            " ".join(tickers), period="1y", interval="1d",
            progress=False, threads=True,
        )
        if data.empty or "Close" not in data.columns:
            return out
        for t in tickers:
            try:
                close = data["Close"][t].dropna()
                high = data["High"][t].dropna()
                low = data["Low"][t].dropna()
                vol = data["Volume"][t].dropna()
                if len(close) < 2:
                    continue
                cur = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                latest_vol = int(vol.iloc[-1]) if len(vol) else None
                out[t] = {
                    "close":      round(cur, 2),
                    "change_pct": round((cur - prev) / prev * 100, 2) if prev else None,
                    "high_52w":   round(float(high.max()), 2) if len(high) else None,
                    "low_52w":    round(float(low.min()), 2) if len(low) else None,
                    "volume":     latest_vol,
                    "turnover":   (latest_vol * cur) if latest_vol else None,
                }
            except (KeyError, IndexError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance explore batch failed: %s", e)
    return out


async def get_explore_lists() -> Optional[Dict[str, Any]]:
    """52-week-high / 52-week-low / most-active lists over the Nifty-50
    universe, derived live from yfinance. Returns None only if we have no
    data at all (no cache + fetch failed)."""
    now = time.time()
    if _EXPLORE_CACHE["data"] and (now - _EXPLORE_CACHE["ts"]) < 300.0:
        return _EXPLORE_CACHE["data"]

    raw = await asyncio.to_thread(_fetch_explore_batch)
    if not raw:
        return _EXPLORE_CACHE["data"]

    name_by_ticker = dict(NIFTY50_CONSTITUENTS)
    rows: List[Dict[str, Any]] = []
    for t, d in raw.items():
        rows.append({"symbol": t.replace(".NS", ""), "name": name_by_ticker.get(t, t), **d})

    def _from_high(r: Dict[str, Any]) -> Optional[float]:
        h, c = r.get("high_52w"), r.get("close")
        return (c - h) / h * 100 if h and c else None   # ≤ 0; nearer 0 = nearer high

    def _from_low(r: Dict[str, Any]) -> Optional[float]:
        lo, c = r.get("low_52w"), r.get("close")
        return (c - lo) / lo * 100 if lo and c else None  # ≥ 0; nearer 0 = nearer low

    def _base(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"symbol": r["symbol"], "name": r["name"], "price": r.get("close"),
                "change_pct": r.get("change_pct")}

    highs = sorted((r for r in rows if _from_high(r) is not None), key=_from_high, reverse=True)[:10]
    lows = sorted((r for r in rows if _from_low(r) is not None), key=_from_low)[:10]
    actives = sorted((r for r in rows if r.get("turnover")), key=lambda r: r["turnover"], reverse=True)[:10]

    result = {
        "high_52w":    [{**_base(r), "from_high_pct": round(_from_high(r), 2)} for r in highs],
        "low_52w":     [{**_base(r), "from_low_pct": round(_from_low(r), 2)} for r in lows],
        "most_active": [{**_base(r), "volume": r.get("volume")} for r in actives],
        "universe":    "Nifty 50",
        "fetched_at":  datetime.now(IST).isoformat(),
    }
    _EXPLORE_CACHE["data"] = result
    _EXPLORE_CACHE["ts"] = now
    return result
