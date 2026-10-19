"""Engineered per-stock features (SMA / RSI / MACD / ATR / Bollinger / volume z).

    GET  /v1/features/scan-snapshot   the opportunity scanner's one-row-per-stock snapshot (see _SNAPSHOT_SQL)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, normalise_symbol, page_params, parse_date, row_to_dict
from nidp.services.daas_api.routers._fundamentals_source import source_columns


router = APIRouter(prefix="/features", tags=["features"], dependencies=[Depends(require_api_key)])

# Columns the strategy engine's evaluator needs — the DSL feature whitelist
# (STOCK_FEATURE_COLS) plus identifiers. Kept in sync with the per-symbol
# endpoint below so the bulk path returns the same shape.
# `sector` + the fundamental/ownership/risk columns are required so a strategy
# built from the copilot stock-screener (fundamental predicates + sector) can
# actually screen/backtest on the DaaS path — the evaluator reads these keys.
_FEATURE_COLS = """
    symbol, as_of_date, close, sector,
    sma20, sma50, sma100, sma200, sma50_slope,
    dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
    rsi14, macd, macd_signal, macd_hist,
    return_5d_pct, return_20d_pct, return_60d_pct,
    atr14, atr_pct, bb_width, bb_pos,
    avg_volume_20, vol_z20, deliv_pct_avg_20, deliv_trend10,
    swing_high_20, swing_low_20, pivot_breakout_flag,
    accumulation_score,
    pe_ttm, pb, ev_ebitda, pe_vs_sector_pct, dividend_yield_pct,
    roe_pct, roce_pct, profit_margin_pct, interest_coverage, earnings_consistency_score,
    revenue_growth_3y_cagr_pct, eps_growth_3y_cagr_pct,
    revenue_growth_yoy_pct, pat_growth_yoy_pct, eps_growth_yoy_pct, profit_margin_trend_pct,
    debt_to_equity, debt_trend_pct, liquidity_score,
    market_cap_cr,
    return_252d_pct, volatility_1y_pct, beta_1y, max_drawdown_1y_pct, momentum_score,
    promoter_pct, promoter_pledged_pct, fii_pct, dii_pct,
    fii_pct_change_qoq, promoter_pct_change_qoq
"""
# Both routes below also return fundamentals_source / fundamentals_as_of (migration 162):
# where the row's roe_pct, roce_pct, debt_to_equity, pb and market_cap_cr came from, and the
# day they are as of — see _fundamentals_source.source_columns.
# Hard caps so a single call can't ask for an unbounded scan.
_BULK_MAX_SYMBOLS = 300
_BULK_MAX_ROWS = 400_000


@router.get("/stocks/{symbol}", summary="Daily engineered features for one symbol")
async def stock_features(
    symbol: str = Path(...),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        source_cols = await source_columns(conn)
        rows = await conn.fetch(
            f"""
            SELECT symbol, as_of_date, close, sector,
                   sma20, sma50, sma100, sma200, sma50_slope,
                   dist_200dma_pct, dist_52w_high_pct, dist_52w_low_pct,
                   rsi14, macd, macd_signal, macd_hist,
                   return_5d_pct, return_20d_pct, return_60d_pct,
                   atr14, atr_pct, bb_width, bb_pos,
                   avg_volume_20, vol_z20,
                   deliv_pct_avg_20, deliv_trend10,
                   swing_high_20, swing_low_20, pivot_breakout_flag,
                   accumulation_score, accumulation_signals,
                   pe_ttm, pb, ev_ebitda, pe_vs_sector_pct, dividend_yield_pct,
                   roe_pct, roce_pct, profit_margin_pct, interest_coverage, earnings_consistency_score,
                   revenue_growth_3y_cagr_pct, eps_growth_3y_cagr_pct,
                   revenue_growth_yoy_pct, pat_growth_yoy_pct, eps_growth_yoy_pct, profit_margin_trend_pct,
                   debt_to_equity, debt_trend_pct, liquidity_score,
                   market_cap_cr,
                   return_252d_pct, volatility_1y_pct, beta_1y, max_drawdown_1y_pct, momentum_score,
                   promoter_pct, promoter_pledged_pct, fii_pct, dii_pct,
                   fii_pct_change_qoq, promoter_pct_change_qoq,
                   {source_cols}
              FROM nidp.stock_features_daily
             WHERE symbol = $1
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY as_of_date DESC
             LIMIT $4 OFFSET $5
            """,
            sym, d_start, d_end, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"symbol": sym})


@router.get("/stocks/{symbol}/latest", summary="Most-recent feature row for one symbol")
async def latest_features(symbol: str = Path(...)) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM nidp.stock_features_daily
             WHERE symbol = $1
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            sym,
        )
    if row is None:
        return {"data": None, "error": "not_found"}
    return {"data": row_to_dict(row)}


@router.get("/calendar", summary="Distinct trading dates with feature snapshots")
async def feature_calendar(
    start: Optional[str] = Query(None, description="Inclusive YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="Inclusive YYYY-MM-DD"),
) -> Dict[str, Any]:
    """Distinct as_of_date values present in stock_features_daily, ascending.

    The strategy backtest needs the real trading calendar to sweep dates;
    this replaces its direct `SELECT DISTINCT as_of_date` SQL so the app
    never has to reach NIDP's Postgres directly.
    """
    d_start = parse_date(start, field="start")
    d_end = parse_date(end, field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT as_of_date
              FROM nidp.stock_features_daily
             WHERE ($1::date IS NULL OR as_of_date >= $1)
               AND ($2::date IS NULL OR as_of_date <= $2)
             ORDER BY as_of_date
            """,
            d_start, d_end,
        )
    dates = [r["as_of_date"].isoformat() for r in rows]
    return {"dates": dates, "count": len(dates)}


@router.post("/bulk", summary="Daily engineered features for many symbols over a date range")
async def features_bulk(
    body: Dict[str, Any] = Body(
        ...,
        example={"symbols": ["RELIANCE", "TCS", "INFY"],
                 "start": "2021-01-01", "end": "2026-01-01"},
    ),
) -> Dict[str, Any]:
    """Bulk feature rows keyed by symbol, each a date-ascending list.

    Collapses the strategy engine's per-symbol fan-out into a few calls.
    The caller chunks the universe into <= _BULK_MAX_SYMBOLS batches.
    """
    raw = body.get("symbols") or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="symbols must be a list")
    symbols = [normalise_symbol(s) for s in raw if isinstance(s, str) and s.strip()]
    if not symbols:
        return {"data": {}, "count": 0, "requested": len(raw)}
    if len(symbols) > _BULK_MAX_SYMBOLS:
        raise HTTPException(status_code=400,
                            detail=f"too many symbols ({len(symbols)}); max {_BULK_MAX_SYMBOLS} per call")
    d_start = parse_date(body.get("start"), field="start")
    d_end = parse_date(body.get("end"), field="end")
    pool = await get_pool()
    async with pool.acquire() as conn:
        source_cols = await source_columns(conn)
        rows = await conn.fetch(
            f"""
            SELECT {_FEATURE_COLS.rstrip()}, {source_cols}
              FROM nidp.stock_features_daily
             WHERE symbol = ANY($1::text[])
               AND ($2::date IS NULL OR as_of_date >= $2)
               AND ($3::date IS NULL OR as_of_date <= $3)
             ORDER BY symbol, as_of_date
             LIMIT {_BULK_MAX_ROWS}
            """,
            symbols, d_start, d_end,
        )
    data: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        data.setdefault(r["symbol"], []).append(row_to_dict(r))
    return {"data": data, "count": len(rows), "symbols": len(data), "requested": len(symbols)}


# ── Opportunity-scanner snapshot (Smart trading desk, PRD §5.2 / §5.8) ──────
# One row per stock on the latest features date: the features the scanner's universe categories read, the NSE
# bhavcopy row of that SAME day (so price and indicators are aligned, PRD §5.6), the 20-session traded value, the
# security reference row (series, price band, F&O eligibility, ETF flag) and the nearest quarterly-results dates.
# The app (routes/positional.py GET /api/positional/scan-universe) applies the rules; nothing here filters.
_SNAPSHOT_SESSIONS = 20
_SNAPSHOT_SQL = """
WITH d AS (SELECT MAX(as_of_date) AS d FROM nidp.stock_features_daily),
sess AS (
    SELECT DISTINCT as_of_date FROM nidp.prices_eod
     WHERE as_of_date <= (SELECT d FROM d)
     ORDER BY as_of_date DESC
     LIMIT $1
),
px AS (
    -- one bhavcopy row per stock and session: the EQ series first, then BE, then any other
    SELECT DISTINCT ON (symbol, as_of_date) symbol, as_of_date, series, open_price, high_price, low_price,
           close_price, prev_close, volume
      FROM nidp.prices_eod
     WHERE as_of_date IN (SELECT as_of_date FROM sess)
     ORDER BY symbol, as_of_date, (series = 'EQ') DESC, (series = 'BE') DESC, series, source
),
tv AS (
    SELECT symbol, COUNT(*) AS traded_sessions, COUNT(close_price * volume) AS valued_sessions,
           AVG(close_price * volume) AS avg_traded_value
      FROM px GROUP BY symbol
),
ref AS (
    SELECT r.symbol, r.series, r.price_band_pct, r.band_raw, r.fno_eligible, r.is_etf, r.as_of_date
      FROM nidp.security_reference_daily r
     WHERE r.as_of_date = (SELECT MAX(as_of_date) FROM nidp.security_reference_daily
                            WHERE as_of_date <= (SELECT d FROM d))
),
f AS (
    SELECT DISTINCT ON (symbol) *
      FROM nidp.stock_features_daily
     WHERE as_of_date = (SELECT d FROM d)
     ORDER BY symbol, source
)
SELECT f.symbol, f.as_of_date, f.sector, ic.industry,
       f.close, f.sma50, f.sma50_slope, f.sma200, f.rsi14, f.macd_hist,
       f.return_5d_pct, f.return_20d_pct, f.return_60d_pct,
       f.vol_z20, f.avg_volume_20, f.atr_pct, f.volatility_1y_pct, f.beta_1y, f.max_drawdown_1y_pct,
       f.market_cap_cr, f.market_cap_bucket,
       p.as_of_date AS price_date, p.series AS price_series, p.open_price, p.high_price, p.low_price,
       p.close_price, p.prev_close, p.volume,
       tv.traded_sessions, tv.valued_sessions, tv.avg_traded_value,
       ref.symbol IS NOT NULL AS has_reference, ref.series, ref.price_band_pct, ref.band_raw, ref.fno_eligible,
       ref.is_etf, ref.as_of_date AS reference_as_of,
       (SELECT MAX(e.event_date) FROM nidp.event_calendar e
         WHERE e.symbol = f.symbol AND e.event_type = 'quarterly_results'
           AND e.event_date <= f.as_of_date AND e.event_date > f.as_of_date - 30) AS last_results_date,
       (SELECT MIN(e.event_date) FROM nidp.event_calendar e
         WHERE e.symbol = f.symbol AND e.event_type = 'quarterly_results'
           AND e.event_date > f.as_of_date AND e.event_date <= f.as_of_date + 45) AS next_results_date
  FROM f
  LEFT JOIN px p ON p.symbol = f.symbol AND p.as_of_date = f.as_of_date
  LEFT JOIN tv ON tv.symbol = f.symbol
  LEFT JOIN ref ON ref.symbol = f.symbol
  LEFT JOIN LATERAL (SELECT i.industry FROM nidp.index_constituents i
                      WHERE i.symbol = f.symbol AND i.industry IS NOT NULL
                      ORDER BY i.as_of_date DESC LIMIT 1) ic ON TRUE
 ORDER BY f.symbol
"""


def _snapshot_row(r: Any) -> Dict[str, Any]:
    d = row_to_dict(r)
    sessions, valued = d.pop("traded_sessions"), d.pop("valued_sessions")
    full = sessions == _SNAPSHOT_SESSIONS and valued == _SNAPSHOT_SESSIONS
    avg = d.pop("avg_traded_value")
    # ₹ crore a day; none unless every one of the last 20 sessions has a close and a volume (never a short mean).
    d["traded_value_cr_20d"] = round(avg / 1e7, 2) if full and avg is not None else None
    vol, avg_vol = d.get("volume"), d.get("avg_volume_20")
    # Relative volume: the day's volume over its 20-session average (the average excludes the day itself).
    d["rvol20"] = round(vol / avg_vol, 2) if vol is not None and avg_vol not in (None, 0) else None
    return d


@router.get("/scan-snapshot", summary="Latest feature row per stock with same-day price, traded value, reference flags and results dates")
async def scan_snapshot() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SNAPSHOT_SQL, _SNAPSHOT_SESSIONS)
    if not rows:
        raise HTTPException(status_code=503, detail="feature store is empty")
    out = [_snapshot_row(r) for r in rows]
    refs = sorted({r["reference_as_of"] for r in out if r.get("reference_as_of")})
    return {
        "as_of": out[0]["as_of_date"],
        "reference_as_of": refs[-1] if refs else None,
        "sessions": _SNAPSHOT_SESSIONS,
        "source": ("NIDP feature store (nidp.stock_features_daily) · NSE bhavcopy (nidp.prices_eod) · "
                   "NSE security reference (nidp.security_reference_daily) · NSE event calendar (nidp.event_calendar) · "
                   "NSE index constituents (nidp.index_constituents, industry)"),
        "count": len(out),
        "rows": out,
    }
