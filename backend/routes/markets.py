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
    since = date.today() - timedelta(days=3)   # asyncpg $1::date needs a date obj, not a str
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


# ════════════════════════════════════════════════════════════════════════
# Market Pulse — Phase 1 aux endpoints (movers-by-cap, FII/DII history, CA)
# All read the same NIDP data lake via the direct PG pool that backs the home
# aggregator above; each is a cheap SQL read behind the same market-hours TTL.
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
                      pg_builder, empty: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer DaaS (which reads the populated NIDP data lake); fall back to the
    app's direct PG pool. On some environments (staging) the app's own Postgres
    carries the nidp.* schema but no rows, so DaaS is the real source there; on
    prod either path has data. Returns `empty` only if both are unavailable."""
    from services.copilot_tools import daas_client
    if daas_client.is_configured():
        try:
            data = await getattr(daas_client, daas_method)(**daas_kwargs)
            if data is not None:
                return data
        except Exception as e:  # noqa: BLE001
            logger.warning("markets %s via DaaS failed: %s", daas_method, e)
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        return empty
    return await pg_builder(pool)


# SEBI-style cap buckets as stored by NIDP (migration 053, stock_features_daily).
_CAP_BUCKET = {"large": "LARGE_CAP", "mid": "MID_CAP", "small": "SMALL_CAP"}


async def _movers_by_cap(pool, cap: str) -> Dict[str, Any]:
    """Top-5 gainers / losers within a market-cap segment (latest EOD).

    Joins the Nifty-500 momentum card (analytics.stock_card — carries the daily
    % change) to nidp.stock_features_daily (carries market_cap_bucket). Falls
    back to empty lists when the segment is unpopulated rather than fabricate.
    """
    bucket = _CAP_BUCKET.get(cap)
    if bucket is None:
        return {"as_of": None, "cap": cap, "gainers": [], "losers": []}

    sql = """
        SELECT sc.symbol, sc.company_name, sc.close, sc.pct_change
          FROM analytics.stock_card sc
          JOIN nidp.stock_features_daily f
            ON f.symbol = sc.symbol
           AND f.as_of_date = (SELECT max(as_of_date) FROM nidp.stock_features_daily)
         WHERE sc.as_of_date = (SELECT max(as_of_date) FROM analytics.stock_card)
           AND sc.in_nifty500
           AND sc.pct_change IS NOT NULL
           AND f.market_cap_bucket = $1
         ORDER BY sc.pct_change {dir}
         LIMIT 5
    """
    try:
        async with pool.acquire() as conn:
            as_of = await conn.fetchval("SELECT max(as_of_date) FROM analytics.stock_card")
            if as_of is None:
                return {"as_of": None, "cap": cap, "gainers": [], "losers": []}
            gainers = await conn.fetch(sql.format(dir="DESC"), bucket)
            losers = await conn.fetch(sql.format(dir="ASC"), bucket)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.movers cap=%s failed: %s", cap, e)
        return {"as_of": None, "cap": cap, "gainers": [], "losers": []}

    def _row(r) -> Dict[str, Any]:
        return {
            "symbol":     r["symbol"],
            "name":       r["company_name"] or r["symbol"],
            "price":      round(float(r["close"]), 2) if r["close"] is not None else None,
            "change_pct": round(float(r["pct_change"]), 2) if r["pct_change"] is not None else None,
        }

    return {
        "as_of":   as_of.isoformat(),
        "cap":     cap,
        "gainers": [_row(r) for r in gainers],
        "losers":  [_row(r) for r in losers],
    }


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
        lambda pool: _movers_by_cap(pool, cap),
        {"as_of": None, "cap": cap, "gainers": [], "losers": []},
    ))
    return {"ok": True, **data}


def _fd_row(r) -> Dict[str, Any]:
    """A single FII/DII pivot row (buy/sell/net for both, ₹ crore)."""
    def _n(v) -> Optional[float]:
        return round(float(v), 2) if v is not None else None
    return {
        "fii_buy":  _n(r["fii_buy"]),  "fii_sell": _n(r["fii_sell"]),  "fii_net": _n(r["fii_net"]),
        "dii_buy":  _n(r["dii_buy"]),  "dii_sell": _n(r["dii_sell"]),  "dii_net": _n(r["dii_net"]),
    }


async def _fii_dii_series(pool, days: int = 90) -> Dict[str, Any]:
    """Daily (last `days` sessions) + monthly (last 18 months) FII/DII EQUITY_CASH
    flows, pivoted so each row carries FII & DII buy/sell/net in ₹ crore.
    """
    daily_sql = """
        SELECT as_of_date,
               SUM(buy_value_cr)  FILTER (WHERE category='FII') AS fii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='FII') AS fii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='FII') AS fii_net,
               SUM(buy_value_cr)  FILTER (WHERE category='DII') AS dii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='DII') AS dii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='DII') AS dii_net
          FROM nidp.fii_dii_flows
         WHERE segment='EQUITY_CASH' AND category IN ('FII','DII')
           AND as_of_date >= (current_date - $1::int)
         GROUP BY as_of_date
         ORDER BY as_of_date DESC
    """
    monthly_sql = """
        SELECT date_trunc('month', as_of_date)::date AS month,
               SUM(buy_value_cr)  FILTER (WHERE category='FII') AS fii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='FII') AS fii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='FII') AS fii_net,
               SUM(buy_value_cr)  FILTER (WHERE category='DII') AS dii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='DII') AS dii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='DII') AS dii_net
          FROM nidp.fii_dii_flows
         WHERE segment='EQUITY_CASH' AND category IN ('FII','DII')
           AND as_of_date >= (date_trunc('month', current_date) - interval '17 months')
         GROUP BY month
         ORDER BY month DESC
    """
    try:
        async with pool.acquire() as conn:
            daily = await conn.fetch(daily_sql, days)
            monthly = await conn.fetch(monthly_sql)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.fii_dii series failed: %s", e)
        return {"as_of": None, "daily": [], "monthly": []}

    return {
        "as_of":   daily[0]["as_of_date"].isoformat() if daily else None,
        "daily":   [{"date": r["as_of_date"].isoformat(), **_fd_row(r)} for r in daily],
        "monthly": [{"month": r["month"].isoformat(), **_fd_row(r)} for r in monthly],
    }


@router.get("/fii-dii")
async def markets_fii_dii(request: Request, days: int = 90):
    """FII/DII cash-segment flows: daily series + monthly aggregates + summary
    table rows. Real data from nidp.fii_dii_flows (NSE provisional).
    """
    await get_current_user(request)
    days = max(7, min(int(days or 90), 365))
    data = await _aux_cached(f"fii_dii:{days}", lambda: _daas_first(
        "get_market_pulse_fii_dii", {"days": days},
        lambda pool: _fii_dii_series(pool, days),
        {"as_of": None, "daily": [], "monthly": []},
    ))
    return {"ok": True, **data}


# Action types the calendar surfaces, in display order (matches the filter rail).
_CA_TYPES = ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"]


def _ca_value_label(r) -> Optional[str]:
    """A compact human value for one corporate action (mirrors the copilot card)."""
    at = (r["action_type"] or "").upper()
    if at == "DIVIDEND" and r["dividend_amount"] is not None:
        return f"₹{float(r['dividend_amount']):g}"
    if at == "SPLIT":
        if r["face_value_pre"] is not None and r["face_value_post"] is not None:
            return f"FV ₹{float(r['face_value_pre']):g} → ₹{float(r['face_value_post']):g}"
        return r["ratio"] or None
    if at in ("BONUS", "RIGHTS") and r["ratio"]:
        return r["ratio"]
    if r["ratio"]:
        return r["ratio"]
    return (r["purpose"] or None)


async def _corporate_actions(pool, d_from: str, d_to: str,
                             a_type: Optional[str], q: Optional[str],
                             limit: int, offset: int) -> Dict[str, Any]:
    """Filtered corporate-action calendar over nidp.corporate_actions, joined to
    ref.security_master for the company name. Returns the page + per-type counts
    over the whole date window (so the filter rail shows full counts)."""
    list_sql = """
        SELECT ca.symbol, sm.security_name AS name,
               ca.action_type, ca.action_subtype, ca.purpose, ca.ratio,
               ca.face_value_pre, ca.face_value_post, ca.dividend_amount,
               ca.record_date, ca.ex_date
          FROM nidp.corporate_actions ca
          LEFT JOIN ref.security_master sm
                 ON sm.entity_type = 'EQUITY' AND sm.symbol = ca.symbol
         WHERE ca.ex_date >= $1::date AND ca.ex_date <= $2::date
           AND ($3::text IS NULL OR ca.action_type = $3)
           AND ($4::text IS NULL OR ca.symbol ILIKE $4 OR sm.security_name ILIKE $4)
         ORDER BY ca.ex_date ASC, ca.symbol
         LIMIT $5 OFFSET $6
    """
    count_sql = """
        SELECT action_type, count(*) AS n
          FROM nidp.corporate_actions
         WHERE ex_date >= $1::date AND ex_date <= $2::date
         GROUP BY action_type
    """
    like = f"%{q}%" if q else None
    df, dt = date.fromisoformat(d_from), date.fromisoformat(d_to)  # asyncpg $::date needs date objs
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(list_sql, df, dt, a_type, like, limit, offset)
            counts = await conn.fetch(count_sql, df, dt)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.corporate_actions failed: %s", e)
        return {"from": d_from, "to": d_to, "actions": [], "type_counts": {}}

    type_counts = {r["action_type"]: int(r["n"]) for r in counts if r["action_type"]}
    actions = [{
        "symbol":      r["symbol"],
        "name":        r["name"] or r["symbol"],
        "action_type": r["action_type"],
        "subtype":     r["action_subtype"],
        "ex_date":     r["ex_date"].isoformat() if r["ex_date"] else None,
        "record_date": r["record_date"].isoformat() if r["record_date"] else None,
        "value_label": _ca_value_label(r),
        "dividend_amount": float(r["dividend_amount"]) if r["dividend_amount"] is not None else None,
        "ratio":       r["ratio"],
        "purpose":     r["purpose"],
    } for r in rows]
    return {"from": d_from, "to": d_to, "actions": actions, "type_counts": type_counts}


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
        lambda pool: _corporate_actions(pool, d_from, d_to, a_type, q, limit, offset),
        {"from": d_from, "to": d_to, "actions": [], "type_counts": {}},
    ))
    return {"ok": True, "types": _CA_TYPES, **data}


# ════════════════════════════════════════════════════════════════════════
# Market Pulse — Phase 2: Articles (classified filings) + Daily Iris brief
# ════════════════════════════════════════════════════════════════════════

def _read_min(subject: Optional[str], description: Optional[str]) -> int:
    """Honest reading-time estimate (~200 wpm). NSE filings often have no body,
    so this is usually 1; never fabricated beyond the text we actually have."""
    text = (description or subject or "").strip()
    words = len(text.split())
    return max(1, min(round(words / 200) or 1, 6))


async def _articles(pool, days: int, category: Optional[str], impact: Optional[str],
                    sentiment: Optional[str], q: Optional[str],
                    limit: int, offset: int) -> Dict[str, Any]:
    """Classified NSE/BSE announcements as an article feed. Real data only —
    no LLM, no fabrication. When no category filter is set we hide the routine
    'regulatory'/'other' noise so it reads like market news, not a filing log."""
    since = date.today() - timedelta(days=days)   # asyncpg $1::date needs a date obj, not a str
    like = f"%{q}%" if q else None
    list_sql = """
        SELECT announcement_id, source, ticker_symbol, company_name, subject,
               description, event_category, impact_score, sentiment,
               filed_at, attachment_url
          FROM nidp.corporate_announcements
         WHERE filed_at >= $1::date
           AND ($2::text IS NULL OR event_category = $2)
           AND ($3::text IS NULL OR impact_score = $3)
           AND ($4::text IS NULL OR sentiment = $4)
           AND ($5::text IS NULL OR subject ILIKE $5 OR company_name ILIKE $5 OR ticker_symbol ILIKE $5)
           AND ($2::text IS NOT NULL OR event_category IS NULL OR event_category NOT IN ('regulatory', 'other'))
         ORDER BY (impact_score='high') DESC, filed_at DESC
         LIMIT $6 OFFSET $7
    """
    cat_sql = """
        SELECT event_category, count(*) AS n
          FROM nidp.corporate_announcements
         WHERE filed_at >= $1::date AND event_category IS NOT NULL
           AND event_category NOT IN ('regulatory', 'other')
         GROUP BY event_category
         ORDER BY n DESC
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(list_sql, since, category, impact, sentiment, like, limit, offset)
            cats = await conn.fetch(cat_sql, since)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.articles failed: %s", e)
        return {"articles": [], "categories": {}}

    articles = []
    for r in rows:
        subject = (r["subject"] or "").strip()
        desc = (r["description"] or "").strip()
        articles.append({
            "id":        r["announcement_id"],
            "title":     subject or "Corporate announcement",
            "summary":   desc[:240] or None,
            "company":   r["company_name"] or r["ticker_symbol"],
            "symbol":    r["ticker_symbol"],
            "category":  (r["event_category"] or "markets").replace("_", " ").title(),
            "impact":    r["impact_score"],
            "sentiment": r["sentiment"],
            "when":      r["filed_at"].isoformat() if r["filed_at"] else None,
            "source":    r["source"],
            "url":       r["attachment_url"],
            "read_min":  _read_min(subject, desc),
        })
    categories = {r["event_category"]: int(r["n"]) for r in cats}
    return {"articles": articles, "categories": categories}


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
):
    """Stock-market news & analysis — classified NSE/BSE filings as an article
    grid, filterable by category / impact / sentiment / search. Real data only.
    """
    await get_current_user(request)
    days = max(1, min(int(days or 7), 30))
    limit = max(1, min(int(limit or 60), 120))
    offset = max(0, int(offset or 0))
    impact = impact.lower() if impact else None
    sentiment = sentiment.lower() if sentiment else None
    category = category.lower() if category else None
    key = f"articles:{days}:{category}:{impact}:{sentiment}:{q}:{limit}:{offset}"
    data = await _aux_cached(key, lambda: _daas_first(
        "get_market_pulse_articles",
        {"days": days, "category": category, "impact": impact, "sentiment": sentiment, "q": q, "limit": limit, "offset": offset},
        lambda pool: _articles(pool, days, category, impact, sentiment, q, limit, offset),
        {"articles": [], "categories": {}},
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


async def _build_daily_brief(pool) -> Dict[str, Any]:
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

    fii_dii = await _fii_dii(pool)
    movers = await _top_movers(pool)
    news = await _news(pool, limit=4)
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
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            return {"ok": False, "error": "no_pg_pool", "brief": None}
        doc = await _build_daily_brief(pool)
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
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}
    doc = await _build_daily_brief(pool)
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
    from services import pg_client, sector_analysis
    docs = [d async for d in db.market_sector_analysis.find({}, {"_id": 0})]
    diagnostic = None
    if not docs:
        pool = await pg_client.get_pool()
        if pool is None:
            return {"ok": False, "error": "no_pg_pool", "sectors": [], "llm_enabled": sector_analysis.is_llm_configured()}
        docs = await sector_analysis.build_all_metrics(pool, _iso_utc())
        await _store_sector_docs(docs)
        if not docs:
            # Empty build → surface the data state so a blank grid is diagnosable.
            diagnostic = await sector_analysis.diagnose(pool)
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
    from services import pg_client, sector_analysis
    doc = await db.market_sector_analysis.find_one({"slug": slug}, {"_id": 0})
    if doc is None:
        pool = await pg_client.get_pool()
        if pool is None:
            return {"ok": False, "error": "no_pg_pool", "sector": None}
        built = await sector_analysis.build_all_metrics(pool, _iso_utc())
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
    from services import pg_client, sector_analysis
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}
    docs = await sector_analysis.build_all_metrics(pool, _iso_utc())
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
# returns an identical shape whether sourced over DaaS or the direct PG pool.
# ════════════════════════════════════════════════════════════════════════

#   $1 = index_name   $2 = target period_end (DATE, nullable → latest quarter)
_EARNINGS_CTE = """
WITH params AS (
    SELECT COALESCE($2::date,
                    (SELECT MAX(period_end) FROM nidp.nse_financials_quarterly
                      WHERE LOWER(period_type) = 'quarterly')) AS pe
),
idx AS (
    SELECT DISTINCT ic.symbol, ic.industry
      FROM nidp.index_constituents ic
     WHERE ic.index_name = $1
       AND ic.as_of_date = (SELECT MAX(as_of_date) FROM nidp.index_constituents
                             WHERE index_name = $1)
),
prior_q AS (
    SELECT MAX(period_end) AS pe FROM nidp.nse_financials_quarterly
     WHERE LOWER(period_type) = 'quarterly' AND period_end < (SELECT pe FROM params)
),
fin AS (
    SELECT symbol, period_end, revenue_from_ops_cr AS rev, pat_cr AS pat,
           ROW_NUMBER() OVER (PARTITION BY symbol, period_end
                              ORDER BY consolidated DESC) AS rn
      FROM nidp.nse_financials_quarterly
     WHERE LOWER(period_type) = 'quarterly'
       AND period_end IN ((SELECT pe FROM params),
                          ((SELECT pe FROM params) - INTERVAL '1 year')::date,
                          (SELECT pe FROM prior_q))
),
cur AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end =  (SELECT pe FROM params)),
yoy AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end = ((SELECT pe FROM params) - INTERVAL '1 year')::date),
qoq AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end =  (SELECT pe FROM prior_q)),
j AS (
    SELECT idx.industry              AS sector,
           (cur.symbol IS NOT NULL)  AS declared,
           cur.rev AS crev, cur.pat AS cpat,
           yoy.rev AS yrev, yoy.pat AS ypat,
           qoq.rev AS qrev, qoq.pat AS qpat
      FROM idx
      LEFT JOIN cur ON cur.symbol = idx.symbol
      LEFT JOIN yoy ON yoy.symbol = idx.symbol
      LEFT JOIN qoq ON qoq.symbol = idx.symbol
)
"""

_EARNINGS_METRICS = """
    COUNT(*)                                                         AS members,
    COUNT(*) FILTER (WHERE declared)                                 AS declared,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (crev - yrev) / yrev * 100)
          FILTER (WHERE crev IS NOT NULL AND yrev > 0)::numeric, 1)   AS sales_yoy,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (cpat - ypat) / ypat * 100)
          FILTER (WHERE cpat IS NOT NULL AND ypat > 0)::numeric, 1)   AS profit_yoy,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (crev - qrev) / qrev * 100)
          FILTER (WHERE crev IS NOT NULL AND qrev > 0)::numeric, 1)   AS sales_qoq,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (cpat - qpat) / qpat * 100)
          FILTER (WHERE cpat IS NOT NULL AND qpat > 0)::numeric, 1)   AS profit_qoq,
    COUNT(*) FILTER (WHERE cpat IS NOT NULL AND ypat IS NOT NULL AND cpat >  ypat) AS grew,
    COUNT(*) FILTER (WHERE cpat IS NOT NULL AND ypat IS NOT NULL AND cpat <= ypat) AS shrank,
    COUNT(*) FILTER (WHERE cpat IS NOT NULL AND ypat IS NULL)                      AS no_compare
"""

_EARN_SECTOR_SQL = _EARNINGS_CTE + "SELECT sector, " + _EARNINGS_METRICS + """
  FROM j
 WHERE sector IS NOT NULL
 GROUP BY sector
 ORDER BY declared DESC, members DESC
"""

_EARN_SUMMARY_SQL = _EARNINGS_CTE + "SELECT " + _EARNINGS_METRICS + """,
       (SELECT pe FROM params)  AS period_end,
       (SELECT pe FROM prior_q) AS prior_q
  FROM j
"""


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


def _earn_pct(v) -> Optional[float]:
    return round(float(v), 1) if v is not None else None


def _earn_metrics(r) -> Dict[str, Any]:
    return {
        "members":    int(r["members"]),
        "declared":   int(r["declared"]),
        "sales_yoy":  _earn_pct(r["sales_yoy"]),
        "profit_yoy": _earn_pct(r["profit_yoy"]),
        "sales_qoq":  _earn_pct(r["sales_qoq"]),
        "profit_qoq": _earn_pct(r["profit_qoq"]),
        "grew":       int(r["grew"]),
        "shrank":     int(r["shrank"]),
        "no_compare": int(r["no_compare"]),
    }


def _earnings_empty(index: str) -> Dict[str, Any]:
    return {"index": index, "period_end": None, "quarter": None, "summary": None,
            "sectors": [], "available_indices": [], "available_quarters": []}


async def _earnings_pg(pool, index: str, quarter: Optional[str]) -> Dict[str, Any]:
    """Direct-PG fallback when DaaS is unavailable (prod app PG carries the rows)."""
    pe_param = None
    if quarter:
        try:
            pe_param = date.fromisoformat(quarter)
        except ValueError:
            pe_param = None
    try:
        async with pool.acquire() as conn:
            sectors = await conn.fetch(_EARN_SECTOR_SQL, index, pe_param)
            summary = await conn.fetchrow(_EARN_SUMMARY_SQL, index, pe_param)
            quarters = await conn.fetch(
                """SELECT DISTINCT period_end FROM nidp.nse_financials_quarterly
                    WHERE LOWER(period_type) = 'quarterly'
                    ORDER BY period_end DESC LIMIT 8""")
            indices = await conn.fetch(
                """SELECT index_name FROM (
                       SELECT ic.index_name, COUNT(*) AS n
                         FROM nidp.index_constituents ic
                        WHERE ic.as_of_date = (SELECT MAX(as_of_date)
                                                 FROM nidp.index_constituents i2
                                                WHERE i2.index_name = ic.index_name)
                        GROUP BY ic.index_name) t
                    ORDER BY n DESC""")
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.earnings PG fallback failed: %s", e)
        return _earnings_empty(index)

    period_end = summary["period_end"] if summary else None
    summary_obj = None
    if summary and summary["declared"]:
        m = _earn_metrics(summary)
        summary_obj = {
            "members": m["members"], "declared": m["declared"],
            "profit_grew": m["grew"], "profit_shrank": m["shrank"], "no_compare": m["no_compare"],
            "sales_yoy": m["sales_yoy"], "profit_yoy": m["profit_yoy"],
            "sales_qoq": m["sales_qoq"], "profit_qoq": m["profit_qoq"],
        }
    return {
        "index":      index,
        "period_end": period_end.isoformat() if period_end else None,
        "quarter":    _quarter_label(period_end),
        "summary":    summary_obj,
        "sectors":    [{"sector": r["sector"], **_earn_metrics(r)} for r in sectors],
        "available_indices":  [r["index_name"] for r in indices],
        "available_quarters": [
            {"period_end": r["period_end"].isoformat(), "label": _quarter_label(r["period_end"])}
            for r in quarters],
    }


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
        lambda pool: _earnings_pg(pool, index, quarter),
        _earnings_empty(index),
    ))
    return {"ok": True, **data}


# ── Drill-down: the companies behind one sector card ────────────────────
# Mirrors backend/nidp/services/daas_api/routers/market_pulse.py verbatim.
#   $1 = index_name   $2 = period_end (DATE, nullable)   $3 = sector (industry)
_EARN_COMPANIES_SQL = """
WITH params AS (
    SELECT COALESCE($2::date,
                    (SELECT MAX(period_end) FROM nidp.nse_financials_quarterly
                      WHERE LOWER(period_type) = 'quarterly')) AS pe
),
idx AS (
    SELECT DISTINCT ic.symbol, ic.company_name
      FROM nidp.index_constituents ic
     WHERE ic.index_name = $1
       AND ic.as_of_date = (SELECT MAX(as_of_date) FROM nidp.index_constituents
                             WHERE index_name = $1)
       AND ic.industry = $3
),
prior_q AS (
    SELECT MAX(period_end) AS pe FROM nidp.nse_financials_quarterly
     WHERE LOWER(period_type) = 'quarterly' AND period_end < (SELECT pe FROM params)
),
fin AS (
    SELECT symbol, period_end, revenue_from_ops_cr AS rev, pat_cr AS pat,
           ROW_NUMBER() OVER (PARTITION BY symbol, period_end
                              ORDER BY consolidated DESC) AS rn
      FROM nidp.nse_financials_quarterly
     WHERE LOWER(period_type) = 'quarterly'
       AND period_end IN ((SELECT pe FROM params),
                          ((SELECT pe FROM params) - INTERVAL '1 year')::date,
                          (SELECT pe FROM prior_q))
),
cur AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end =  (SELECT pe FROM params)),
yoy AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end = ((SELECT pe FROM params) - INTERVAL '1 year')::date),
qoq AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end =  (SELECT pe FROM prior_q))
SELECT idx.symbol, idx.company_name,
       (cur.symbol IS NOT NULL)                                            AS declared,
       cur.rev AS revenue_cr, cur.pat AS pat_cr,
       CASE WHEN yoy.rev > 0 THEN ROUND(((cur.rev - yoy.rev) / yoy.rev * 100)::numeric, 1) END AS sales_yoy,
       CASE WHEN yoy.pat > 0 THEN ROUND(((cur.pat - yoy.pat) / yoy.pat * 100)::numeric, 1) END AS profit_yoy,
       CASE WHEN qoq.rev > 0 THEN ROUND(((cur.rev - qoq.rev) / qoq.rev * 100)::numeric, 1) END AS sales_qoq,
       CASE WHEN qoq.pat > 0 THEN ROUND(((cur.pat - qoq.pat) / qoq.pat * 100)::numeric, 1) END AS profit_qoq,
       (cur.pat IS NOT NULL AND yoy.pat IS NOT NULL AND cur.pat >  yoy.pat) AS profit_grew
  FROM idx
  LEFT JOIN cur ON cur.symbol = idx.symbol
  LEFT JOIN yoy ON yoy.symbol = idx.symbol
  LEFT JOIN qoq ON qoq.symbol = idx.symbol
 ORDER BY (cur.symbol IS NOT NULL) DESC, profit_yoy DESC NULLS LAST, idx.symbol
"""


def _earn_company(r) -> Dict[str, Any]:
    return {
        "symbol":      r["symbol"],
        "name":        r["company_name"] or r["symbol"],
        "declared":    bool(r["declared"]),
        "revenue_cr":  round(float(r["revenue_cr"]), 1) if r["revenue_cr"] is not None else None,
        "pat_cr":      round(float(r["pat_cr"]), 1) if r["pat_cr"] is not None else None,
        "sales_yoy":   _earn_pct(r["sales_yoy"]),
        "profit_yoy":  _earn_pct(r["profit_yoy"]),
        "sales_qoq":   _earn_pct(r["sales_qoq"]),
        "profit_qoq":  _earn_pct(r["profit_qoq"]),
        "profit_grew": None if r["profit_grew"] is None else bool(r["profit_grew"]),
    }


def _earnings_companies_empty(index: str, sector: str) -> Dict[str, Any]:
    return {"index": index, "sector": sector, "period_end": None, "quarter": None,
            "declared": 0, "members": 0, "companies": []}


async def _earnings_companies_pg(pool, index: str, quarter: Optional[str], sector: str) -> Dict[str, Any]:
    pe_param = None
    if quarter:
        try:
            pe_param = date.fromisoformat(quarter)
        except ValueError:
            pe_param = None
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_EARN_COMPANIES_SQL, index, pe_param, sector)
            period_end = await conn.fetchval(
                """SELECT COALESCE($1::date, (SELECT MAX(period_end) FROM nidp.nse_financials_quarterly
                                               WHERE LOWER(period_type) = 'quarterly'))""", pe_param)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.earnings companies PG fallback failed: %s", e)
        return _earnings_companies_empty(index, sector)
    return {
        "index":      index,
        "sector":     sector,
        "period_end": period_end.isoformat() if period_end else None,
        "quarter":    _quarter_label(period_end),
        "declared":   sum(1 for r in rows if r["declared"]),
        "members":    len(rows),
        "companies":  [_earn_company(r) for r in rows],
    }


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
        lambda pool: _earnings_companies_pg(pool, index, quarter, sector),
        _earnings_companies_empty(index, sector),
    ))
    return {"ok": True, **data}


# ── Institutional positioning by sector (FII/DII holdings, latest quarter) ──
# Mirrors backend/nidp/services/daas_api/routers/market_pulse.py verbatim.
# Holding value = holding% × market cap (total_shares × EOD close), by sector.
_INSTITUTIONAL_POSITIONING_SQL = """
    SELECT sc.sector,
           SUM((sh.fii_pct/100.0) * sh.total_shares * p.close_price / 1e7) AS fii_cr,
           SUM((sh.dii_pct/100.0) * sh.total_shares * p.close_price / 1e7) AS dii_cr,
           count(*) AS n
      FROM nidp.shareholding_pattern sh
      JOIN analytics.stock_card sc
        ON sc.symbol = sh.symbol
       AND sc.as_of_date = (SELECT max(as_of_date) FROM analytics.stock_card)
      JOIN nidp.prices_eod p
        ON p.symbol = sh.symbol
       AND p.as_of_date = (SELECT max(as_of_date) FROM nidp.prices_eod)
     WHERE sh.period_end = (SELECT max(period_end) FROM nidp.shareholding_pattern)
       AND sc.sector IS NOT NULL
       AND sh.total_shares IS NOT NULL
       AND sh.fii_pct IS NOT NULL
     GROUP BY sc.sector
"""


async def _institutional_positioning_pg(pool) -> Dict[str, Any]:
    try:
        async with pool.acquire() as conn:
            period = await conn.fetchval("SELECT max(period_end) FROM nidp.shareholding_pattern")
            rows = await conn.fetch(_INSTITUTIONAL_POSITIONING_SQL)
    except Exception as e:  # noqa: BLE001
        logger.warning("markets.institutional_positioning PG fallback failed: %s", e)
        return {"period_end": None, "universe": "Nifty 500", "sectors": []}
    return {
        "period_end": period.isoformat() if period else None,
        "universe":   "Nifty 500",
        "sectors": [{
            "sector": r["sector"],
            "fii_cr": round(float(r["fii_cr"]), 2) if r["fii_cr"] is not None else None,
            "dii_cr": round(float(r["dii_cr"]), 2) if r["dii_cr"] is not None else None,
            "n":      int(r["n"]),
        } for r in rows],
    }


@router.get("/institutional-positioning")
async def markets_institutional_positioning(request: Request):
    """FII/DII *holdings* by sector from the latest quarterly shareholding
    pattern (holding% × market cap). A positioning snapshot, NOT buy/sell flows —
    NSE publishes only the current quarter, so quarter-over-quarter flows aren't
    derivable until the next filing lands."""
    await get_current_user(request)
    data = await _aux_cached("inst_positioning", lambda: _daas_first(
        "get_market_pulse_institutional_positioning", {},
        lambda pool: _institutional_positioning_pg(pool),
        {"period_end": None, "universe": "Nifty 500", "sectors": []},
    ))
    return {"ok": True, **data}
