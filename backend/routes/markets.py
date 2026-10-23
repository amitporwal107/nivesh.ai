"""Markets home — a single aggregator for the V5 /markets dashboard.

Composes data that already lives in the platform; it does NOT recompute or
duplicate anything:

  • indices  + breadth + sector heatmap  ← positional_engine.market_dashboard.build()
  • Sensex + Nifty Bank live values       ← positional_engine.nse_live snapshot
  • top gainers / losers                  ← analytics.mv_top_momentum  (Nifty 500, latest EOD)
  • FII / DII cash flows                  ← nidp.fii_dii_flows         (EQUITY_CASH segment)
  • market news headlines                 ← nidp.corporate_event_signals (post-event AI signals)
  • global cues / world indices / commodities ← positional_engine.nse_live global snapshot (Yahoo)
  • market_state / is_live / session          ← NSE hours by the IST clock AND the NSE holiday list
                                                (DaaS /v1/holidays → nidp.nse_holidays, segment CM)

One round of cheap SQL behind a market-hours-adaptive cache (30s open /
300s closed) — this backs a dashboard, not a ticker.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

from deps import db, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets"])

_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def _ttl() -> float:
    from services.positional_engine import nse_live as _nl
    return 30.0 if _nl._is_market_open_ist() else 300.0


def _abs_change(close: Optional[float], change_pct: Optional[float]) -> Optional[float]:
    """Reconstruct the absolute point change from close + pct (yfinance gives us pct)."""
    if close is None or change_pct is None:
        return None
    prev = close / (1.0 + change_pct / 100.0)
    return round(close - prev, 2)


def _index_tile(name: str, close: Optional[float], change_pct: Optional[float],
                *, is_vix: bool = False, trend: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if close is None:
        return None
    return {
        "name":       name,
        "value":      close,
        "change":     _abs_change(close, change_pct),
        "change_pct": change_pct,
        "is_vix":     is_vix,
        "trend":      trend,
        "spark":      [],
    }


# The three home-page helpers below read NIDP data through the NIDP (DaaS)
# API, like the rest of this module. They used to run SQL against nidp.* /
# analytics.* on the app's own pool, which only works when both databases are
# the same server; with the app and NIDP on separate hosts those relations do
# not exist here and the panels came back empty.

_MOVER_CAPS = ("large", "mid", "small")


async def _top_movers(limit: int = 4) -> Dict[str, Any]:
    """Top gainers / losers across the Nifty-500 (latest EOD).

    DaaS serves movers per market-cap segment, so the three segments are
    merged and re-ranked here.
    """
    from services.copilot_tools import daas_client
    empty: Dict[str, Any] = {"as_of": None, "gainers": [], "losers": []}
    if not daas_client.is_configured():
        return empty
    as_of: Optional[str] = None
    gainers: Dict[str, Dict[str, Any]] = {}
    losers: Dict[str, Dict[str, Any]] = {}
    for cap in _MOVER_CAPS:
        try:
            data = await daas_client.get_market_pulse_movers(cap=cap)
        except Exception as e:  # noqa: BLE001
            logger.warning("markets.home top_movers(%s) via DaaS failed: %s", cap, e)
            continue
        if not data:
            continue
        as_of = as_of or data.get("as_of")
        for bucket, rows in ((gainers, data.get("gainers")), (losers, data.get("losers"))):
            for r in rows or []:
                if r.get("symbol") and r.get("change_pct") is not None:
                    bucket.setdefault(r["symbol"], r)

    def _row(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "symbol":     r["symbol"],
            "name":       r.get("name") or r["symbol"],
            "price":      round(float(r["price"]), 2) if r.get("price") is not None else None,
            "change_pct": round(float(r["change_pct"]), 2),
        }

    top = sorted(gainers.values(), key=lambda r: r["change_pct"], reverse=True)[:limit]
    bottom = sorted(losers.values(), key=lambda r: r["change_pct"])[:limit]
    return {"as_of": as_of, "gainers": [_row(r) for r in top], "losers": [_row(r) for r in bottom]}


async def _fii_dii() -> Optional[Dict[str, Any]]:
    """Latest day's FII & DII net cash (equity cash segment), in ₹ crore."""
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        return None
    try:
        data = await daas_client.get_market_pulse_fii_dii(days=7)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.home fii_dii via DaaS failed: %s", e)
        return None
    daily = (data or {}).get("daily") or []
    if not daily:
        return None
    latest = daily[0]                      # DaaS returns the series newest-first
    fii, dii = latest.get("fii_net"), latest.get("dii_net")
    if fii is None and dii is None:
        return None
    return {
        "as_of":      latest.get("date"),
        "fii_net_cr": round(float(fii), 2) if fii is not None else None,
        "dii_net_cr": round(float(dii), 2) if dii is not None else None,
    }


async def _news(limit: int = 5) -> List[Dict[str, Any]]:
    """Recent material corporate announcements → headline list.

    Sourced from the classified NSE/BSE announcement feed; we keep only
    high/medium-impact items and drop the routine 'regulatory'/'other'
    noise so the section reads like market news, not a compliance log.
    """
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        return []
    try:
        # sort=material puts classified, higher-impact filings first; the
        # high/medium filter is applied here because the endpoint takes a
        # single impact value.
        data = await daas_client.get_market_pulse_articles(days=3, sort="material", limit=60)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.home news via DaaS failed: %s", e)
        return []

    picked = [
        a for a in ((data or {}).get("articles") or [])
        if (a.get("impact") or "").lower() in ("high", "medium")
        and (a.get("category") or "other").lower() not in ("regulatory", "other")
    ]
    # high before medium; the sort is stable, so the endpoint's own order
    # (most material first) is kept within each level
    picked.sort(key=lambda a: (a.get("impact") or "").lower() != "high")

    out: List[Dict[str, Any]] = []
    for a in picked[:limit]:
        company = a.get("company") or a.get("symbol") or ""
        subject = (a.get("title") or "").strip()
        title = f"{company} — {subject}".strip(" —") if company else subject
        out.append({
            "title":     title or "Corporate announcement",
            "category":  (a.get("category") or "markets").replace("_", " ").title(),
            "when":      a.get("when"),
            "symbol":    a.get("symbol"),
            "sentiment": a.get("sentiment"),
        })
    return out


def _breadth_tone(advances: Optional[int], declines: Optional[int]) -> str:
    if not advances or not declines:
        return "NEUTRAL"
    if advances >= declines * 1.2:
        return "POSITIVE"
    if declines >= advances * 1.2:
        return "NEGATIVE"
    return "NEUTRAL"


def _breadth(eod: Dict[str, Any], live_breadth: Dict[str, Any]) -> Dict[str, Any]:
    """Home-page breadth: NIDP's end-of-day count when it has one, else the live Nifty-50 count.

    `universe_kind` says which stocks `universe` counted (null when neither source answered):
      bhavcopy      every NSE stock with 21+ sessions of daily bars in stock_ohlcv (loaded from the NSE bhavcopy;
                    positional_engine.market_dashboard), end of day
      nifty50_live  the Nifty 50 constituents with a delayed quote (positional_engine.nse_live)
    `universe` stays the bare count it always was: the app's zod contract (MarketBreadthC) reads it as a number, so
    turning it into an object would fail the whole /markets/home parse.
    """
    advances = eod.get("advances")
    declines = eod.get("declines")
    universe = eod.get("universe_size")
    kind = "bhavcopy"
    if advances is None:
        advances = live_breadth.get("advances")
        declines = live_breadth.get("declines")
        universe = live_breadth.get("universe")
        unchanged = live_breadth.get("unchanged")
        kind = "nifty50_live"
    else:
        unchanged = None
        if universe is not None and declines is not None:
            unchanged = max(universe - advances - declines, 0)
    return {
        "advances":  advances,
        "declines":  declines,
        "unchanged": unchanged,
        "universe":  universe,
        "universe_kind": kind if advances is not None else None,
        "tone":      _breadth_tone(advances, declines),
        # Structural breadth from the NIDP EOD builder (full equity universe).
        # These stay EOD even intraday — they're computed off daily bars.
        "pct_above_20ema": eod.get("pct_above_20ema"),
        "pct_above_50ema": eod.get("pct_above_50ema"),
        "new_52w_highs":   eod.get("new_52w_highs"),
        "new_52w_lows":    eod.get("new_52w_lows"),
    }


# ── NSE session status (desk PRD §12.5: a maintained exchange calendar, not the weekday alone) ──

IST = timezone(timedelta(hours=5, minutes=30))
NSE_OPEN = (9, 15)
NSE_CLOSE = (15, 30)
CALENDAR_SOURCE = "NSE trading holidays (nidp.nse_holidays, segment CM)"
# A day's holiday answer is kept for six hours; a failed read is retried after two minutes.
_HOLIDAY_TTL_OK = 6 * 3600.0
_HOLIDAY_TTL_FAILED = 120.0
_HOLIDAY_CACHE: Dict[str, Tuple[float, Tuple[bool, Optional[str]]]] = {}


async def _nse_holiday(day: date) -> Tuple[bool, Optional[str]]:
    """(the calendar was read, the holiday's name or None) for one IST day, from the data platform's
    NSE holiday list. (False, None) when the data platform is not configured or does not answer."""
    from services.copilot_tools import daas_client
    key = day.isoformat()
    now = time.time()
    hit = _HOLIDAY_CACHE.get(key)
    if hit and now - hit[0] < (_HOLIDAY_TTL_OK if hit[1][0] else _HOLIDAY_TTL_FAILED):
        return hit[1]
    result: Tuple[bool, Optional[str]] = (False, None)
    if daas_client.is_configured():
        try:
            status, body = await daas_client.get_raw("/holidays", {"segment": "CM", "from": key, "to": key})
            rows = body.get("data") if status == 200 and isinstance(body, dict) else None
            if isinstance(rows, list):
                names = [str(r.get("description") or "NSE holiday").strip() for r in rows
                         if isinstance(r, dict) and str(r.get("holiday_date") or "")[:10] == key]
                result = (True, names[0] if names else None)
            else:
                logger.warning("markets.home holiday calendar answered HTTP %s", status)
        except daas_client.DaasError as e:
            logger.warning("markets.home holiday calendar failed: %s", e)
    _HOLIDAY_CACHE[key] = (now, result)
    return result


def session_state(now: datetime, *, calendar_read: bool, holiday: Optional[str]) -> Dict[str, Any]:
    """The NSE cash-market session at `now` (any tz-aware time; read in IST).

    Open only on a weekday that is not an NSE CM holiday, 09:15–15:30 IST. When the holiday list could
    not be read, `trading_day` is null for a weekday and the state follows the clock, which the caller
    says ("holidays not checked"). Special sessions (e.g. Muhurat trading) are not in the list.
    """
    t = now.astimezone(IST)
    minutes = t.hour * 60 + t.minute
    weekend = t.weekday() >= 5
    if weekend:
        trading_day: Optional[bool] = False
    elif holiday:
        trading_day = False
    else:
        trading_day = True if calendar_read else None
    in_hours = NSE_OPEN[0] * 60 + NSE_OPEN[1] <= minutes <= NSE_CLOSE[0] * 60 + NSE_CLOSE[1]
    if weekend:
        reason = "weekend"
    elif holiday:
        reason = "holiday"
    elif minutes < NSE_OPEN[0] * 60 + NSE_OPEN[1]:
        reason = "before_open"
    elif minutes > NSE_CLOSE[0] * 60 + NSE_CLOSE[1]:
        reason = "after_close"
    else:
        reason = "in_hours"
    open_now = trading_day is not False and in_hours
    return {
        "date": t.date().isoformat(),
        "state": "open" if open_now else "closed",
        "trading_day": trading_day,
        "reason": reason,
        "holiday": holiday if not weekend else None,
        "hours": f"{NSE_OPEN[0]:02d}:{NSE_OPEN[1]:02d}–{NSE_CLOSE[0]:02d}:{NSE_CLOSE[1]:02d} IST",
        "calendar": "ok" if calendar_read else "unavailable",
        "calendar_source": CALENDAR_SOURCE,
    }


async def _session_now() -> Dict[str, Any]:
    now = datetime.now(IST)
    read, holiday = await _nse_holiday(now.date())
    return session_state(now, calendar_read=read, holiday=holiday)


@router.get("/home")
async def markets_home(request: Request):
    """Aggregate everything the Markets home dashboard renders, in one call.

    Real data only — each section degrades to empty/null rather than mock
    when its upstream source is unavailable.
    """
    await get_current_user(request)

    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _ttl():
        return {**_CACHE["data"], "_cache_hit": True}

    from services.positional_engine import market_dashboard as md, nse_live

    # ── indices + breadth + sectors (reuse the positional builder) ──────
    dash: Dict[str, Any] = {}
    try:
        dash = await md.build()
    except Exception as e:  # noqa: BLE001
        logger.error("markets.home dashboard build failed: %s", e, exc_info=True)
        dash = {}

    live = None
    try:
        live = await nse_live.get_live_snapshot()
    except Exception as e:  # noqa: BLE001
        logger.debug("markets.home live snapshot failed: %s", e)

    glob = None
    try:
        glob = await nse_live.get_global_snapshot()
    except Exception as e:  # noqa: BLE001
        logger.debug("markets.home global snapshot failed: %s", e)
    glob = glob or {}

    live = live or {}
    live_nifty = live.get("nifty50") or {}
    live_sensex = live.get("sensex") or {}
    live_vix = live.get("vix") or {}
    bank = next((s for s in (live.get("sectors") or []) if (s.get("sector") or "").lower() == "bank"), {})

    dash_nifty = dash.get("nifty") or {}
    dash_vix = dash.get("vix") or {}

    # ── Index tape: six benchmarks, each with a daily-close sparkline ────
    # The tape carries EOD values + sparklines for all six; we overlay the
    # four that the intraday live snapshot covers so they tick during hours.
    try:
        tape = await nse_live.get_index_tape()
    except Exception as e:  # noqa: BLE001
        logger.debug("markets.home index tape failed: %s", e)
        tape = []

    live_overlay = {
        "Nifty 50":   (live_nifty.get("close"), live_nifty.get("change_pct")),
        "Sensex":     (live_sensex.get("close"), live_sensex.get("change_pct")),
        "Nifty Bank": (bank.get("close"), bank.get("change_pct")),
        "India VIX":  (live_vix.get("value"), live_vix.get("change_pct")),
    }
    indices = []
    for t in tape:
        value, change_pct = t["value"], t["change_pct"]
        ov = live_overlay.get(t["name"])
        tile_day = t.get("as_of")
        if ov and ov[0] is not None:
            value, change_pct = ov[0], ov[1]
            tile_day = None          # the value is the live snapshot's now, not the daily bar's
        if value is None:
            continue
        indices.append({
            "as_of":      tile_day,
            "name":       t["name"],
            "value":      value,
            "change":     _abs_change(value, change_pct),
            "change_pct": change_pct,
            "is_vix":     t["is_vix"],
            "trend":      t["trend"],
            "spark":      t.get("spark") or [],
        })

    # Fallback: if the history fetch was unavailable, fall back to the
    # four NIDP/live tiles (no sparkline) so the tape never goes blank.
    if not indices:
        indices = [
            _index_tile("Nifty 50",
                        live_nifty.get("close") if live_nifty.get("close") is not None else dash_nifty.get("close"),
                        live_nifty.get("change_pct") if live_nifty.get("close") is not None else dash_nifty.get("change_pct")),
            _index_tile("Sensex", live_sensex.get("close"), live_sensex.get("change_pct")),
            _index_tile("Nifty Bank", bank.get("close"), bank.get("change_pct")),
            _index_tile("India VIX",
                        live_vix.get("value") if live_vix.get("value") is not None else dash_vix.get("value"),
                        live_vix.get("change_pct") if live_vix.get("value") is not None else dash_vix.get("change_pct"),
                        is_vix=True,
                        trend=(live_vix.get("trend") or dash_vix.get("trend"))),
        ]
        indices = [i for i in indices if i is not None]

    # ── Breadth: prefer NIDP's full-universe count; else live Nifty-50 ──
    breadth = _breadth(dash.get("breadth") or {}, live.get("breadth") or {})

    # ── Sectors: prefer NIDP heatmap; else the live sector indices ──────
    sectors = [
        {"name": s.get("sector"), "change_pct": s.get("ret_5d_pct")}
        for s in (dash.get("sector_heatmap") or [])
        if s.get("ret_5d_pct") is not None
    ]
    if not sectors:
        sectors = [
            {"name": s.get("sector"), "change_pct": s.get("change_pct")}
            for s in (live.get("sectors") or [])
            if s.get("change_pct") is not None
        ]

    # ── Movers: prefer NIDP Nifty-500; else live Nifty-50 ───────────────
    movers = await _top_movers()
    if not movers["gainers"] and not movers["losers"]:
        def _live_row(m: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "symbol":     m.get("symbol"),
                "name":       m.get("name") or m.get("symbol"),
                "price":      round(float(m["close"]), 2) if m.get("close") is not None else None,
                "change_pct": round(float(m["change_pct"]), 2) if m.get("change_pct") is not None else None,
            }
        live_gainers = [_live_row(m) for m in (live.get("gainers") or [])]
        live_losers = [_live_row(m) for m in (live.get("losers") or [])]
        if live_gainers or live_losers:
            movers = {
                "as_of":   (live.get("fetched_at") or "")[:10] or None,
                "gainers": live_gainers,
                "losers":  live_losers,
            }

    fii_dii = await _fii_dii()
    news = await _news()

    # The live feeds call any weekday in hours "live"; on an NSE holiday nothing trades, so nothing is.
    session = await _session_now()
    is_live = bool(dash.get("is_live") or live.get("is_live")) and session["state"] == "open"
    result = {
        "ok":           True,
        "as_of":        dash.get("as_of_date"),
        "is_live":      is_live,
        "market_state": session["state"],
        "session":      session,
        "fetched_at":   dash.get("fetched_at") or live.get("fetched_at"),
        # Rules-based deploy verdict (macro → breadth → trend) — drives the
        # Markets hero line and the deterministic "Copilot read".
        "verdict":        dash.get("deploy_verdict"),
        "verdict_reason": dash.get("verdict_reason"),
        "indices":      indices,
        "breadth":      breadth,
        "gainers":      movers["gainers"],
        "losers":       movers["losers"],
        "movers_as_of": movers["as_of"],
        "sectors":      sectors,
        "fii_dii":      fii_dii,
        "news":         news,
        "global_cues":    glob.get("global_cues", []),
        "global_indices": glob.get("global_indices", {"us": [], "europe": [], "asia": []}),
        "commodities":    glob.get("commodities", []),
    }

    _CACHE["ts"] = now
    _CACHE["data"] = result
    return result


# ════════════════════════════════════════════════════════════════════════
# Market Pulse — Phase 1 aux endpoints (movers-by-cap, FII/DII history, CA)
# All read the NIDP data lake through the DaaS API (see _daas_first), behind
# the same market-hours TTL as the home aggregator above.
# ════════════════════════════════════════════════════════════════════════

_AUX_CACHE: Dict[str, Any] = {}


async def _aux_cached(key: str, builder) -> Any:
    """Tiny param-keyed cache (same 30s-open / 300s-closed TTL as home)."""
    now = time.time()
    hit = _AUX_CACHE.get(key)
    if hit and (now - hit[0]) < _ttl():
        return hit[1]
    data = await builder()
    _AUX_CACHE[key] = (now, data)
    return data


async def _daas_first(daas_method: str, daas_kwargs: Dict[str, Any],
                      empty: Dict[str, Any]) -> Dict[str, Any]:
    """Read through the NIDP (DaaS) API — the only path to NIDP data.

    The app reads NIDP exclusively over the API: the two databases are separate
    servers, so there is no SQL fallback. Returns `empty` when DaaS is not
    configured, errors, or has nothing for the request.
    """
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        logger.warning("markets %s: DaaS is not configured", daas_method)
        return empty
    try:
        data = await getattr(daas_client, daas_method)(**daas_kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets %s via DaaS failed: %s", daas_method, e)
        return empty
    return data if data is not None else empty


# SEBI-style cap buckets as stored by NIDP (migration 053, stock_features_daily).
_CAP_BUCKET = {"large": "LARGE_CAP", "mid": "MID_CAP", "small": "SMALL_CAP"}


@router.get("/movers")
async def markets_movers(request: Request, cap: str = "large"):
    """Top gainers / losers for one market-cap segment (large | mid | small).

    Real data only — Nifty-500 EOD bucketed by NIDP's market_cap_bucket.
    """
    await get_current_user(request)
    cap = (cap or "large").lower()
    if cap not in _CAP_BUCKET:
        cap = "large"
    data = await _aux_cached(f"movers:{cap}", lambda: _daas_first(
        "get_market_pulse_movers", {"cap": cap},
        {"as_of": None, "cap": cap, "gainers": [], "losers": []},
    ))
    return {"ok": True, **data}


@router.get("/fii-dii")
async def markets_fii_dii(request: Request, days: int = 90):
    """FII/DII cash-segment flows: daily series + monthly aggregates + summary
    table rows. Real data from nidp.fii_dii_flows (NSE provisional).
    """
    await get_current_user(request)
    days = max(7, min(int(days or 90), 365))
    data = await _aux_cached(f"fii_dii:{days}", lambda: _daas_first(
        "get_market_pulse_fii_dii", {"days": days},
        {"as_of": None, "daily": [], "monthly": []},
    ))
    return {"ok": True, **data}


# Action types the calendar surfaces, in display order (matches the filter rail).
_CA_TYPES = ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"]


@router.get("/corporate-actions")
async def markets_corporate_actions(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    action_type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """Corporate-action calendar (dividend/bonus/rights/split/merger/demerger/
    buyback), filterable by date range, type and a company/symbol search.

    Defaults to a forward 30-day window. Real data from nidp.corporate_actions.
    """
    await get_current_user(request)
    today = date.today()
    d_from = date_from or (today - timedelta(days=30)).isoformat()
    d_to = date_to or (today + timedelta(days=30)).isoformat()
    a_type = action_type.upper() if action_type else None
    if a_type and a_type not in _CA_TYPES:
        a_type = None
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))
    key = f"ca:{d_from}:{d_to}:{a_type}:{q}:{limit}:{offset}"
    data = await _aux_cached(key, lambda: _daas_first(
        "get_market_pulse_corporate_actions",
        {"date_from": d_from, "date_to": d_to, "action_type": a_type, "q": q, "limit": limit, "offset": offset},
        {"from": d_from, "to": d_to, "actions": [], "type_counts": {}},
    ))
    return {"ok": True, "types": _CA_TYPES, **data}


# ════════════════════════════════════════════════════════════════════════
# Market Pulse — Phase 2: Articles (classified filings) + Daily Iris brief
# ════════════════════════════════════════════════════════════════════════


@router.get("/articles")
async def markets_articles(
    request: Request,
    days: int = 7,
    category: Optional[str] = None,
    impact: Optional[str] = None,
    sentiment: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
    sort: str = "material",
):
    """Stock-market news & analysis — classified NSE/BSE filings as an article
    grid, filterable by category / impact / sentiment / search. Real data only.

    `sort` (Filings Home — docs/FILINGS_HOME_SPEC.md):
      material (default) — high impact first, then recency. Identical to the
                           previous, only behaviour, so existing callers are
                           unaffected.
      latest             — pure recency.
    `total` is the full count for the same predicate (NOT len(articles)), so the
    client can paginate.
    """
    await get_current_user(request)
    sort = (sort or "material").lower()
    if sort not in ("material", "latest"):
        # 400 rather than silently falling back: a caller that asked for an order
        # and quietly got a different one would mis-rank the feed.
        raise HTTPException(status_code=400, detail="sort must be 'material' or 'latest'")
    days = max(1, min(int(days or 7), 30))
    limit = max(1, min(int(limit or 60), 120))
    offset = max(0, int(offset or 0))
    impact = impact.lower() if impact else None
    sentiment = sentiment.lower() if sentiment else None
    category = category.lower() if category else None
    # `sort` MUST be in the cache key — without it the two orderings would share
    # a cached entry and serve each other's rows.
    key = f"articles:{days}:{category}:{impact}:{sentiment}:{q}:{limit}:{offset}:{sort}"
    data = await _aux_cached(key, lambda: _daas_first(
        "get_market_pulse_articles",
        {"days": days, "category": category, "impact": impact, "sentiment": sentiment, "q": q, "limit": limit, "offset": offset, "sort": sort},
        {"articles": [], "total": 0, "categories": {}},
    ))
    return {"ok": True, **data}


# ── Daily Iris Update — persisted grounded daily brief ──────────────────

def _ist_today() -> str:
    from datetime import datetime, timezone as _tz, timedelta as _td
    return datetime.now(_tz(_td(hours=5, minutes=30))).date().isoformat()


def _iso_utc() -> str:
    from datetime import datetime, timezone as _tz
    return datetime.now(_tz.utc).isoformat()


def _brief_narrative(nifty_pct, advances, declines, sectors_sorted, fii_dii,
                     vix_val, vix_pct, state, news_n) -> tuple:
    """Rules-based, fully grounded headline + bullets (same deterministic style
    as the Markets 'Copilot read'). No LLM — every clause maps to a real number."""
    tone = "little changed"
    if nifty_pct is not None:
        tone = "higher" if nifty_pct > 0.15 else "lower" if nifty_pct < -0.15 else "little changed"
    lead = sectors_sorted[0] if sectors_sorted and (sectors_sorted[0].get("change_pct") or 0) > 0 else None
    breadth_clause = ""
    if advances and declines:
        if advances >= declines * 1.2:
            breadth_clause = " as breadth stayed firmly positive"
        elif declines >= advances * 1.2:
            breadth_clause = ", though breadth stayed weak"
        else:
            breadth_clause = " with breadth mixed"
    verb = "closed" if state == "closed" else "are trading"
    headline = (f"Markets {verb} {tone}"
                + (f", led by {lead['name']}" if lead else "")
                + breadth_clause + ".")

    bullets: List[str] = []
    if nifty_pct is not None:
        bullets.append(f"Nifty 50 {'+' if nifty_pct >= 0 else ''}{nifty_pct:.2f}%")
    if advances and declines:
        bullets.append(f"Breadth: {advances:,} advancing vs {declines:,} declining")
    if fii_dii:
        fii = fii_dii.get("fii_net_cr")
        dii = fii_dii.get("dii_net_cr")
        if fii is not None:
            bullets.append(f"FII net {'+' if fii >= 0 else '−'}₹{abs(fii):,.0f} Cr in cash")
        if dii is not None:
            bullets.append(f"DII net {'+' if dii >= 0 else '−'}₹{abs(dii):,.0f} Cr in cash")
    if vix_val is not None:
        trend = ""
        if vix_pct is not None:
            trend = " (cooling)" if vix_pct < -1 else " (rising)" if vix_pct > 1 else ""
        bullets.append(f"India VIX at {vix_val:.2f}{trend}")
    if lead:
        bullets.append(f"Top sector: {lead['name']} {'+' if lead['change_pct'] >= 0 else ''}{lead['change_pct']:.2f}%")
    if news_n:
        bullets.append(f"{news_n} material corporate announcement{'s' if news_n != 1 else ''} today")
    if not bullets:
        bullets.append("Market data is refreshing — the full brief loads after the next NIDP tick.")
    return headline, bullets


async def _build_daily_brief() -> Dict[str, Any]:
    """Assemble today's brief from the SAME real feeds the /home dashboard uses."""
    from services.positional_engine import market_dashboard as md, nse_live

    dash: Dict[str, Any] = {}
    try:
        dash = await md.build()
    except Exception as e:  # noqa: BLE001
        logger.warning("daily_brief dashboard build failed: %s", e)
    live: Dict[str, Any] = {}
    try:
        live = await nse_live.get_live_snapshot() or {}
    except Exception:  # noqa: BLE001
        live = {}

    dash_nifty = dash.get("nifty") or {}
    live_nifty = live.get("nifty50") or {}
    nifty_close = live_nifty.get("close") if live_nifty.get("close") is not None else dash_nifty.get("close")
    nifty_pct = live_nifty.get("change_pct") if live_nifty.get("close") is not None else dash_nifty.get("change_pct")

    dash_vix = dash.get("vix") or {}
    live_vix = live.get("vix") or {}
    vix_val = live_vix.get("value") if live_vix.get("value") is not None else dash_vix.get("value")
    vix_pct = live_vix.get("change_pct") if live_vix.get("value") is not None else dash_vix.get("change_pct")

    b = dash.get("breadth") or {}
    advances, declines = b.get("advances"), b.get("declines")

    sectors = [{"name": s.get("sector"), "change_pct": s.get("ret_5d_pct")}
               for s in (dash.get("sector_heatmap") or []) if s.get("ret_5d_pct") is not None]
    sectors_sorted = sorted(sectors, key=lambda s: s["change_pct"], reverse=True)

    fii_dii = await _fii_dii()
    movers = await _top_movers()
    news = await _news(limit=4)
    state = "open" if nse_live._is_market_open_ist() else "closed"

    headline, bullets = _brief_narrative(
        nifty_pct, advances, declines, sectors_sorted, fii_dii, vix_val, vix_pct, state, len(news),
    )

    def _f(v):
        return round(float(v), 2) if v is not None else None

    return {
        "date":         _ist_today(),
        "generated_at": _iso_utc(),
        "headline":     headline,
        "bullets":      bullets,
        "market_state": state,
        "stats": {
            "nifty_close":      _f(nifty_close),
            "nifty_change_pct": _f(nifty_pct),
            "vix":              _f(vix_val),
            "vix_change_pct":   _f(vix_pct),
            "advances":         advances,
            "declines":         declines,
            "fii_net_cr":       fii_dii.get("fii_net_cr") if fii_dii else None,
            "dii_net_cr":       fii_dii.get("dii_net_cr") if fii_dii else None,
            "verdict":          dash.get("deploy_verdict"),
        },
        "top_sectors": sectors_sorted[:3],
        "movers":      {"gainers": movers["gainers"][:3], "losers": movers["losers"][:3]},
        "news":        [{"title": n["title"], "symbol": n["symbol"], "category": n["category"]} for n in news],
        "sources":     ["NIDP", "NSE", "Yahoo Finance"],
    }


async def _store_brief(doc: Dict[str, Any]) -> None:
    try:
        await db.market_daily_brief.update_one({"date": doc["date"]}, {"$set": doc}, upsert=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("daily_brief store failed: %s", e)
    doc.pop("_id", None)


@router.get("/daily-brief")
async def markets_daily_brief(request: Request, date: Optional[str] = None):
    """Daily Iris Update — the persisted grounded market brief. Returns the
    given date's brief, or today's (lazily generating + storing it on first
    read so the feed self-heals without depending on the cron)."""
    await get_current_user(request)
    if date:
        doc = await db.market_daily_brief.find_one({"date": date}, {"_id": 0})
        return {"ok": bool(doc), "brief": doc}

    today = _ist_today()
    doc = await db.market_daily_brief.find_one({"date": today}, {"_id": 0})
    if doc is None:
        doc = await _build_daily_brief()
        await _store_brief(doc)
    return {"ok": True, "brief": doc}


@router.get("/daily-brief/history")
async def markets_daily_brief_history(request: Request, limit: int = 30):
    """Past briefs (newest first) — date + headline for the archive selector."""
    await get_current_user(request)
    limit = max(1, min(int(limit or 30), 90))
    cur = (db.market_daily_brief
           .find({}, {"_id": 0, "date": 1, "headline": 1, "generated_at": 1})
           .sort("date", -1).limit(limit))
    items = [d async for d in cur]
    return {"ok": True, "items": items}


@router.post("/daily-brief/generate")
async def markets_daily_brief_generate(request: Request):
    """(Re)generate + persist today's brief. Idempotent per IST date — wire a
    cron to hit this after the EOD NIDP tick; the GET also self-generates."""
    await get_current_user(request)
    doc = await _build_daily_brief()
    await _store_brief(doc)
    return {"ok": True, "brief": doc}


# ── Sector Analysis — AI sector-overview cards (grounded metrics + commentary) ──

def _sector_excerpt(md: Optional[str], n: int = 180) -> Optional[str]:
    """First non-heading line of the commentary, markdown-stripped, for cards."""
    import re
    for line in (md or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = re.sub(r"[*`_]", "", s)
        return (s[:n].rstrip() + "…") if len(s) > n else s
    return None


def _sector_card(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Trimmed view for the grid — drops the full commentary body."""
    c = doc.get("commentary_md")
    return {
        "slug":            doc.get("slug"),
        "name":            doc.get("name"),
        "icon":            doc.get("icon"),
        "blurb":           doc.get("blurb"),
        "benchmark_index": doc.get("benchmark_index"),
        "as_of_date":      doc.get("as_of_date"),
        "generated_at":    doc.get("generated_at"),
        "headline":        doc.get("headline"),
        "metrics":         doc.get("metrics", {}),
        "has_commentary":  bool(c),
        "excerpt":         _sector_excerpt(c),
    }


async def _store_sector_docs(docs: List[Dict[str, Any]]) -> None:
    for d in docs:
        d.pop("_id", None)
        try:
            await db.market_sector_analysis.update_one({"slug": d["slug"]}, {"$set": d}, upsert=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("sector_analysis store failed for %s: %s", d.get("slug"), e)
        d.pop("_id", None)


@router.get("/sectors")
async def markets_sectors(request: Request):
    """Sector Analysis grid — one card per sector profile, backed by real NIDP
    aggregates. Grounded metrics are built + persisted lazily on first read
    (cheap, no LLM); the AI commentary is generated per sector on detail view."""
    await get_current_user(request)
    from services import sector_analysis
    docs = [d async for d in db.market_sector_analysis.find({}, {"_id": 0})]
    diagnostic = None
    if not docs:
        docs = await sector_analysis.build_all_metrics(_iso_utc())
        await _store_sector_docs(docs)
        if not docs:
            # Empty build → surface the data state so a blank grid is diagnosable.
            diagnostic = await sector_analysis.diagnose()
    docs.sort(key=lambda d: d.get("name") or "")
    resp = {"ok": True, "sectors": [_sector_card(d) for d in docs],
            "llm_enabled": sector_analysis.is_llm_configured()}
    if diagnostic is not None:
        resp["diagnostic"] = diagnostic
    return resp


@router.get("/sectors/{slug}")
async def markets_sector_detail(request: Request, slug: str):
    """Full sector card: grounded metrics + top companies + AI commentary.
    The commentary is generated lazily on first view and then persisted."""
    await get_current_user(request)
    from services import sector_analysis
    doc = await db.market_sector_analysis.find_one({"slug": slug}, {"_id": 0})
    if doc is None:
        built = await sector_analysis.build_all_metrics(_iso_utc())
        if built:
            await _store_sector_docs(built)
        doc = next((d for d in built if d["slug"] == slug), None)
        if doc is None:
            return {"ok": False, "error": "not_found", "sector": None}
    if not doc.get("commentary_md"):
        doc = await sector_analysis.generate_commentary(doc)
        await _store_sector_docs([doc])
    doc.pop("_id", None)
    return {"ok": True, "sector": doc}


@router.post("/sectors/generate")
async def markets_sectors_generate(request: Request):
    """(Re)build all sector cards — fresh metrics + AI commentary for every
    profile. Wire a cron to hit this after the EOD NIDP tick. Auth required."""
    await get_current_user(request)
    from services import sector_analysis
    docs = await sector_analysis.build_all_metrics(_iso_utc())
    for d in docs:
        await sector_analysis.generate_commentary(d)
    await _store_sector_docs(docs)
    return {"ok": True, "count": len(docs), "llm_enabled": sector_analysis.is_llm_configured()}


@router.get("/explore")
async def markets_explore(request: Request):
    """52-week-high / 52-week-low / most-active lists for the Markets page
    Explore drawer. Live from Yahoo over the Nifty-50 universe.
    """
    await get_current_user(request)
    from services.positional_engine import nse_live
    try:
        lists = await nse_live.get_explore_lists()
    except Exception as e:  # noqa: BLE001
        logger.error("markets.explore failed: %s", e, exc_info=True)
        lists = None
    if not lists:
        return {"ok": False, "high_52w": [], "low_52w": [], "most_active": [], "universe": "Nifty 50"}
    return {"ok": True, **lists}


# ════════════════════════════════════════════════════════════════════════
# Earnings Tracker — per-sector results for one index + quarter.
#
# Real NIDP data only (nidp.nse_financials_quarterly + nidp.index_constituents);
# we have no analyst-consensus feed, so there is no beat/miss-vs-estimate — we
# report YoY/QoQ growth and a profit-grew / shrank / no-comparable split. The
# sector headline is the MEDIAN of per-company growth (robust to outliers and
# negative-base sign-flips). This PG fallback mirrors the DaaS implementation in
# backend/nidp/services/daas_api/routers/market_pulse.py verbatim, so the app
# is sourced over DaaS.
# ════════════════════════════════════════════════════════════════════════


def _quarter_label(pe) -> Optional[str]:
    """Indian-fiscal-year quarter label for a quarter-end date (Apr–Mar FY)."""
    if pe is None:
        return None
    m, y = pe.month, pe.year
    if   m == 3:  q, fy = 4, y
    elif m == 6:  q, fy = 1, y + 1
    elif m == 9:  q, fy = 2, y + 1
    elif m == 12: q, fy = 3, y + 1
    else:
        return pe.isoformat()
    return f"Q{q} FY{fy % 100:02d}"


def _earnings_empty(index: str) -> Dict[str, Any]:
    return {"index": index, "period_end": None, "quarter": None, "summary": None,
            "sectors": [], "available_indices": [], "available_quarters": []}


@router.get("/earnings")
async def markets_earnings(request: Request, index: str = "Nifty 500", quarter: Optional[str] = None):
    """Earnings Tracker — per-sector results for an index in a given quarter
    (latest filed quarter when omitted). Real NIDP financials; growth vs the
    year-ago and prior quarter plus a profit grew/shrank split (no analyst
    estimates exist, so there is deliberately no beat/miss-vs-estimate).
    """
    await get_current_user(request)
    index = (index or "Nifty 500").strip()
    data = await _aux_cached(f"earnings:{index}:{quarter or 'latest'}", lambda: _daas_first(
        "get_market_pulse_earnings", {"index": index, "quarter": quarter},
        _earnings_empty(index),
    ))
    return {"ok": True, **data}


def _earnings_companies_empty(index: str, sector: str) -> Dict[str, Any]:
    return {"index": index, "sector": sector, "period_end": None, "quarter": None,
            "declared": 0, "members": 0, "companies": []}


@router.get("/earnings/companies")
async def markets_earnings_companies(
    request: Request, sector: str, index: str = "Nifty 500", quarter: Optional[str] = None,
):
    """Drill-down for the Earnings Tracker: the individual companies behind one
    sector card, with each company's YoY/QoQ sales & profit growth."""
    await get_current_user(request)
    index = (index or "Nifty 500").strip()
    sector = (sector or "").strip()
    if not sector:
        return {"ok": True, **_earnings_companies_empty(index, sector)}
    data = await _aux_cached(f"earnings-co:{index}:{quarter or 'latest'}:{sector}", lambda: _daas_first(
        "get_market_pulse_earnings_companies",
        {"index": index, "sector": sector, "quarter": quarter},
        _earnings_companies_empty(index, sector),
    ))
    return {"ok": True, **data}


@router.get("/institutional-positioning")
async def markets_institutional_positioning(request: Request):
    """FII/DII *holdings* by sector from the latest quarterly shareholding
    pattern (holding% × market cap). A positioning snapshot, NOT buy/sell flows —
    NSE publishes only the current quarter, so quarter-over-quarter flows aren't
    derivable until the next filing lands."""
    await get_current_user(request)
    data = await _aux_cached("inst_positioning", lambda: _daas_first(
        "get_market_pulse_institutional_positioning", {},
        {"period_end": None, "universe": "Nifty 500", "sectors": []},
    ))
    return {"ok": True, **data}
