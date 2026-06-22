"""Markets home — a single aggregator for the V5 /markets dashboard.

Composes data that already lives in the platform; it does NOT recompute or
duplicate anything:

  • indices  + breadth + sector heatmap  ← positional_engine.market_dashboard.build()
  • Sensex + Nifty Bank live values       ← positional_engine.nse_live snapshot
  • top gainers / losers                  ← analytics.mv_top_momentum  (Nifty 500, latest EOD)
  • FII / DII cash flows                  ← nidp.fii_dii_flows         (EQUITY_CASH segment)
  • market news headlines                 ← nidp.corporate_event_signals (post-event AI signals)
  • global cues / world indices / commodities ← positional_engine.nse_live global snapshot (Yahoo)

One round of cheap SQL behind a market-hours-adaptive cache (30s open /
300s closed) — this backs a dashboard, not a ticker.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from deps import get_current_user

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


async def _top_movers(pool) -> Dict[str, Any]:
    """Top 4 gainers / losers from the Nifty-500 momentum matview (latest EOD)."""
    try:
        async with pool.acquire() as conn:
            as_of = await conn.fetchval("SELECT max(as_of_date) FROM analytics.mv_top_momentum")
            gainers = await conn.fetch(
                """
                SELECT symbol, company_name, close, pct_change
                FROM analytics.mv_top_momentum
                WHERE pct_change IS NOT NULL
                ORDER BY pct_change DESC
                LIMIT 4
                """
            )
            losers = await conn.fetch(
                """
                SELECT symbol, company_name, close, pct_change
                FROM analytics.mv_top_momentum
                WHERE pct_change IS NOT NULL
                ORDER BY pct_change ASC
                LIMIT 4
                """
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.home top_movers failed: %s", e)
        return {"as_of": None, "gainers": [], "losers": []}

    def _row(r) -> Dict[str, Any]:
        return {
            "symbol":     r["symbol"],
            "name":       r["company_name"] or r["symbol"],
            "price":      round(float(r["close"]), 2) if r["close"] is not None else None,
            "change_pct": round(float(r["pct_change"]), 2) if r["pct_change"] is not None else None,
        }

    return {
        "as_of":   as_of.isoformat() if as_of else None,
        "gainers": [_row(r) for r in gainers],
        "losers":  [_row(r) for r in losers],
    }


async def _fii_dii(pool) -> Optional[Dict[str, Any]]:
    """Latest day's FII & DII net cash (EQUITY_CASH segment), in ₹ crore."""
    try:
        async with pool.acquire() as conn:
            as_of = await conn.fetchval(
                "SELECT max(as_of_date) FROM nidp.fii_dii_flows WHERE segment = 'EQUITY_CASH'"
            )
            if as_of is None:
                return None
            rows = await conn.fetch(
                """
                SELECT category, net_value_cr
                FROM nidp.fii_dii_flows
                WHERE segment = 'EQUITY_CASH' AND as_of_date = $1
                  AND category IN ('FII', 'DII')
                """,
                as_of,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.home fii_dii failed: %s", e)
        return None

    net = {r["category"]: float(r["net_value_cr"]) if r["net_value_cr"] is not None else None for r in rows}
    if "FII" not in net and "DII" not in net:
        return None
    return {
        "as_of":      as_of.isoformat(),
        "fii_net_cr": round(net["FII"], 2) if net.get("FII") is not None else None,
        "dii_net_cr": round(net["DII"], 2) if net.get("DII") is not None else None,
    }


async def _news(pool, limit: int = 5) -> List[Dict[str, Any]]:
    """Recent material corporate announcements → headline list.

    Sourced from the classified NSE/BSE announcement feed; we keep only
    high/medium-impact items and drop the routine 'regulatory'/'other'
    noise so the section reads like market news, not a compliance log.
    """
    since = (date.today() - timedelta(days=3)).isoformat()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT company_name, ticker_symbol, subject, event_category,
                       sentiment, impact_score, filed_at
                FROM nidp.corporate_announcements
                WHERE filed_at >= $1::date
                  AND impact_score IN ('high', 'medium')
                  AND coalesce(event_category, 'other') NOT IN ('regulatory', 'other')
                ORDER BY (impact_score = 'high') DESC, filed_at DESC
                LIMIT $2
                """,
                since, limit,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.home news failed: %s", e)
        return []

    out: List[Dict[str, Any]] = []
    for r in rows:
        company = r["company_name"] or r["ticker_symbol"] or ""
        subject = (r["subject"] or "").strip()
        title = f"{company} — {subject}".strip(" —") if company else subject
        out.append({
            "title":     title or "Corporate announcement",
            "category":  (r["event_category"] or "markets").replace("_", " ").title(),
            "when":      r["filed_at"].isoformat() if r["filed_at"] else None,
            "symbol":    r["ticker_symbol"],
            "sentiment": r["sentiment"],
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

    from services import pg_client
    from services.positional_engine import market_dashboard as md, nse_live

    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

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
        if ov and ov[0] is not None:
            value, change_pct = ov[0], ov[1]
        if value is None:
            continue
        indices.append({
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
    b = dash.get("breadth") or {}
    advances = b.get("advances")
    declines = b.get("declines")
    universe = b.get("universe_size")
    if advances is None:
        lb = live.get("breadth") or {}
        advances = lb.get("advances")
        declines = lb.get("declines")
        universe = lb.get("universe")
        unchanged = lb.get("unchanged")
    else:
        unchanged = None
        if universe is not None and declines is not None:
            unchanged = max(universe - advances - declines, 0)
    breadth = {
        "advances":  advances,
        "declines":  declines,
        "unchanged": unchanged,
        "universe":  universe,
        "tone":      _breadth_tone(advances, declines),
        # Structural breadth from the NIDP EOD builder (full equity universe).
        # These stay EOD even intraday — they're computed off daily bars.
        "pct_above_20ema": b.get("pct_above_20ema"),
        "pct_above_50ema": b.get("pct_above_50ema"),
        "new_52w_highs":   b.get("new_52w_highs"),
        "new_52w_lows":    b.get("new_52w_lows"),
    }

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
    movers = await _top_movers(pool)
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

    fii_dii = await _fii_dii(pool)
    news = await _news(pool)

    is_live = bool(dash.get("is_live") or live.get("is_live"))
    result = {
        "ok":           True,
        "as_of":        dash.get("as_of_date"),
        "is_live":      is_live,
        "market_state": "open" if nse_live._is_market_open_ist() else "closed",
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
