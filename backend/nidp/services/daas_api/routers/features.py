"""Engineered per-stock features (SMA / RSI / MACD / ATR / Bollinger / volume z).

    GET  /v1/features/scan-snapshot   the opportunity scanner's one-row-per-stock snapshot (see _SNAPSHOT_SQL)
    GET  /v1/features/reversal-snapshot   stocks near their 52-week low with adjusted bars, sector rotation, fundamentals
                                          and announcements (see _REVERSAL_*; the app applies reversal_rules)
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


# ── Reversal-candidate snapshot (Smart trading desk, reversal-rules.v1) ───────
# Pre-filter only: stocks whose stored 52-week-low distance is within max_dist_pct (+ a margin) and whose 20-session
# traded value clears the liquidity floor. The app re-computes the distance from the adjusted bars and applies every
# rule; nothing here scores or ranks. Counts of what the pre-filter dropped are returned so no exclusion is silent.
_REVERSAL_BARS = 260
_REVERSAL_MARGIN_PCT = 3.0
_REVERSAL_BENCH = "Nifty 500"
_REVERSAL_CANDIDATES_SQL = """
WITH d AS (SELECT MAX(as_of_date) AS d FROM nidp.stock_features_daily),
f AS (
    SELECT DISTINCT ON (symbol) * FROM nidp.stock_features_daily
     WHERE as_of_date = (SELECT d FROM d) ORDER BY symbol, source
),
sess AS (
    SELECT DISTINCT as_of_date FROM nidp.prices_eod
     WHERE as_of_date <= (SELECT d FROM d) ORDER BY as_of_date DESC LIMIT 20
),
tv AS (
    SELECT symbol, COUNT(*) AS n, COUNT(close_price * volume) AS valued,
           AVG(close_price * volume) AS avg_tv
      FROM (SELECT DISTINCT ON (symbol, as_of_date) symbol, as_of_date, close_price, volume
              FROM nidp.prices_eod WHERE as_of_date IN (SELECT as_of_date FROM sess)
             ORDER BY symbol, as_of_date, (series = 'EQ') DESC, (series = 'BE') DESC, series, source) x
     GROUP BY symbol
),
ref AS (
    SELECT r.* FROM nidp.security_reference_daily r
     WHERE r.as_of_date = (SELECT MAX(as_of_date) FROM nidp.security_reference_daily
                            WHERE as_of_date <= (SELECT d FROM d))
),
ind AS (
    SELECT DISTINCT ON (symbol) symbol, industry FROM nidp.index_constituents
     WHERE industry IS NOT NULL ORDER BY symbol, as_of_date DESC
)
SELECT f.symbol, f.as_of_date, f.sector, ind.industry, f.close, f.dist_52w_low_pct,
       CASE WHEN tv.n = 20 AND tv.valued = 20 THEN ROUND((tv.avg_tv / 1e7)::numeric, 2) END AS traded_value_cr_20d,
       f.roe_pct, f.debt_to_equity, f.interest_coverage AS interest_cover, f.promoter_pledged_pct, f.pe_ttm,
       f.revenue_growth_yoy_pct, f.pat_growth_yoy_pct, f.profit_margin_pct,
       ref.symbol IS NOT NULL AS has_reference, ref.series, ref.price_band_pct, ref.fno_eligible, ref.is_etf,
       (SELECT MIN(e.event_date) FROM nidp.event_calendar e
         WHERE e.symbol = f.symbol AND e.event_type = 'quarterly_results'
           AND e.event_date >= f.as_of_date AND e.event_date <= f.as_of_date + 45) AS next_results_date
  FROM f
  LEFT JOIN tv ON tv.symbol = f.symbol
  LEFT JOIN ref ON ref.symbol = f.symbol
  LEFT JOIN ind ON ind.symbol = f.symbol
 WHERE f.dist_52w_low_pct IS NOT NULL AND f.dist_52w_low_pct <= $1
 ORDER BY f.symbol
"""
_REVERSAL_BARS_SQL = """
SELECT symbol, as_of_date, adj_open, adj_high, adj_low, adj_close, adj_volume
  FROM (SELECT DISTINCT ON (symbol, as_of_date) * FROM nidp.prices_eod_adjusted
         WHERE symbol = ANY($1::text[]) AND as_of_date <= $2 ORDER BY symbol, as_of_date, source) a
 WHERE as_of_date >= (SELECT MIN(as_of_date) FROM (SELECT DISTINCT as_of_date FROM nidp.prices_eod_adjusted
                                                    WHERE as_of_date <= $2 ORDER BY as_of_date DESC LIMIT $3) z)
 ORDER BY symbol, as_of_date
"""
_REVERSAL_INDEX_SQL = """
SELECT as_of_date, close_price FROM nidp.index_eod
 WHERE index_name = $1 AND as_of_date <= $2 ORDER BY as_of_date DESC LIMIT $3
"""
# Quarterly results of the candidates (consolidated, latest 5 quarters): year-on-year growth and operating margin
# are derived in Python, so a missing quarter gives an unknown figure, never a zero.
_REVERSAL_QUARTERS_SQL = """
SELECT symbol, period_end, revenue_from_ops_cr, ebitda_cr, pat_cr, finance_costs_cr, pbt_cr, broadcast_at
  FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY period_end DESC) AS rn
          FROM nidp.nse_financials_quarterly
         WHERE symbol = ANY($1::text[]) AND period_type = 'quarterly' AND consolidated
           AND period_end <= $2) q
 WHERE rn <= 5 ORDER BY symbol, period_end DESC
"""
_REVERSAL_CASHFLOW_SQL = """
SELECT DISTINCT ON (symbol) symbol, period_end, cfo_cr FROM nidp.nse_financials_cashflow
 WHERE symbol = ANY($1::text[]) AND period_end <= $2 ORDER BY symbol, period_end DESC
"""
_REVERSAL_ANN_SQL = """
SELECT ticker_symbol AS symbol, filed_at, event_category, subject, impact_score, sentiment
  FROM nidp.corporate_announcements
 WHERE ticker_symbol = ANY($1::text[]) AND filed_at >= ($2::date - 30) AND filed_at < ($2::date + 1)
   AND impact_score IS NOT NULL
 ORDER BY ticker_symbol, filed_at DESC
"""
# Sector rotation: per industry (NSE classification) the median 20-session return of its stocks minus the benchmark's,
# at the latest date and 10 sessions earlier, and the share of its stocks above their 50-day average.
_REVERSAL_SECTOR_SQL = """
WITH dts AS (SELECT DISTINCT as_of_date FROM nidp.stock_features_daily ORDER BY as_of_date DESC LIMIT 11),
ind AS (SELECT DISTINCT ON (symbol) symbol, industry FROM nidp.index_constituents
         WHERE industry IS NOT NULL ORDER BY symbol, as_of_date DESC),
bx AS (
    SELECT as_of_date, (close_price / LAG(close_price, 20) OVER (ORDER BY as_of_date) - 1) * 100 AS idx_ret20
      FROM nidp.index_eod WHERE index_name = $1
),
per AS (
    SELECT i.industry, f.as_of_date, COUNT(*) AS n,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.return_20d_pct) AS med_ret20,
           100.0 * AVG(CASE WHEN f.close > f.sma50 THEN 1 ELSE 0 END) FILTER (WHERE f.sma50 IS NOT NULL) AS breadth50
      FROM (SELECT DISTINCT ON (symbol, as_of_date) * FROM nidp.stock_features_daily
             WHERE as_of_date IN (SELECT as_of_date FROM dts) ORDER BY symbol, as_of_date, source) f
      JOIN ind i ON i.symbol = f.symbol
     WHERE f.return_20d_pct IS NOT NULL
     GROUP BY i.industry, f.as_of_date
)
SELECT p.industry, p.as_of_date, p.n, p.med_ret20, p.breadth50, bx.idx_ret20
  FROM per p LEFT JOIN bx ON bx.as_of_date = p.as_of_date
 ORDER BY p.industry, p.as_of_date DESC
"""
_SECTOR_MIN_STOCKS = 5


def _num(v: Any) -> Optional[float]:
    return None if v is None else float(v)


def _yoy(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    """Latest quarter against the same quarter a year earlier; None unless both exist and the base is positive."""
    if not rows:
        return None
    latest = rows[0]
    base = next((r for r in rows[1:] if 360 <= (latest["period_end"] - r["period_end"]).days <= 370), None)
    a, b = _num(latest.get(key)), _num(base.get(key)) if base else None
    if a is None or b is None or b <= 0:
        return None
    return round((a / b - 1.0) * 100.0, 2)


def _sector_contexts(rows: List[Any]) -> Dict[str, Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["industry"], []).append(row_to_dict(r))
    out: Dict[str, Dict[str, Any]] = {}
    for ind, items in by.items():
        items.sort(key=lambda x: x["as_of_date"], reverse=True)
        now, prev = items[0], items[-1] if len(items) > 1 else None

        def rs(it: Optional[Dict[str, Any]]) -> Optional[float]:
            if not it or it["med_ret20"] is None or it["idx_ret20"] is None or it["n"] < _SECTOR_MIN_STOCKS:
                return None
            return round(float(it["med_ret20"]) - float(it["idx_ret20"]), 2)
        a, b = rs(now), rs(prev)
        out[ind] = {"industry": ind, "stocks": now["n"], "as_of_date": now["as_of_date"],
                    "rs_20d": a, "rs_20d_prev": b,
                    "rs_change": None if a is None or b is None else round(a - b, 2),
                    "rs_change_sessions": (len(items) - 1) or None,
                    "breadth_above_50dma_pct": None if now["breadth50"] is None else round(float(now["breadth50"]), 1)}
    return out


@router.get("/reversal-snapshot", summary="Stocks near their 52-week low: adjusted bars, benchmark, sector rotation, fundamentals, announcements")
async def reversal_snapshot(max_dist_pct: float = Query(20.0, ge=1.0, le=40.0)) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        cands = await conn.fetch(_REVERSAL_CANDIDATES_SQL, max_dist_pct + _REVERSAL_MARGIN_PCT)
        if not cands:
            raise HTTPException(status_code=503, detail="feature store is empty")
        as_of = cands[0]["as_of_date"]
        rows = [row_to_dict(r) for r in cands]
        illiquid = sum(1 for r in rows if r["traded_value_cr_20d"] is None or float(r["traded_value_cr_20d"]) < 10.0)
        syms = [r["symbol"] for r in rows if r["traded_value_cr_20d"] is not None and float(r["traded_value_cr_20d"]) >= 10.0]
        bars = await conn.fetch(_REVERSAL_BARS_SQL, syms, as_of, _REVERSAL_BARS)
        idx = await conn.fetch(_REVERSAL_INDEX_SQL, _REVERSAL_BENCH, as_of, _REVERSAL_BARS)
        quarters = await conn.fetch(_REVERSAL_QUARTERS_SQL, syms, as_of)
        cash = await conn.fetch(_REVERSAL_CASHFLOW_SQL, syms, as_of)
        anns = await conn.fetch(_REVERSAL_ANN_SQL, syms, as_of)
        sectors = await conn.fetch(_REVERSAL_SECTOR_SQL, _REVERSAL_BENCH)
    bars_by: Dict[str, List[List[Any]]] = {}
    for b in bars:
        bars_by.setdefault(b["symbol"], []).append([str(b["as_of_date"]), _num(b["adj_open"]), _num(b["adj_high"]),
                                                    _num(b["adj_low"]), _num(b["adj_close"]), _num(b["adj_volume"])])
    q_by: Dict[str, List[Dict[str, Any]]] = {}
    for q in quarters:
        q_by.setdefault(q["symbol"], []).append(dict(q))
    cfo = {c["symbol"]: _num(c["cfo_cr"]) for c in cash}
    ann_by: Dict[str, List[Dict[str, Any]]] = {}
    for a in anns:
        d = row_to_dict(a)
        ann_by.setdefault(d["symbol"], []).append(d)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if r["symbol"] not in bars_by:
            continue
        q = q_by.get(r["symbol"], [])
        ebitda, rev = (_num(q[0]["ebitda_cr"]), _num(q[0]["revenue_from_ops_cr"])) if q else (None, None)
        r["revenue_growth_yoy_pct"] = _yoy(q, "revenue_from_ops_cr") if q else r["revenue_growth_yoy_pct"]
        r["pat_growth_yoy_pct"] = _yoy(q, "pat_cr") if q else r["pat_growth_yoy_pct"]
        r["operating_margin_pct"] = round(ebitda / rev * 100, 2) if ebitda is not None and rev else None
        r["latest_quarter_end"] = str(q[0]["period_end"]) if q else None
        r["cfo_cr"] = cfo.get(r["symbol"])
        r["bars"] = bars_by[r["symbol"]]
        r["announcements"] = ann_by.get(r["symbol"], [])
        out.append(r)
    idx_rows = sorted(((str(i["as_of_date"]), _num(i["close_price"])) for i in idx))
    return {
        "as_of": str(as_of), "benchmark": _REVERSAL_BENCH, "bar_fields": ["d", "o", "h", "l", "c", "v"],
        "benchmark_closes": [{"d": d, "c": c} for d, c in idx_rows],
        "sectors": _sector_contexts(sectors),
        "prefilter": {"max_dist_pct": max_dist_pct, "margin_pct": _REVERSAL_MARGIN_PCT,
                      "within_distance": len(rows), "dropped_illiquid_or_no_traded_value": illiquid,
                      "returned": len(out)},
        "source": ("nidp.stock_features_daily · nidp.prices_eod_adjusted · nidp.index_eod · nidp.nse_financials_quarterly · "
                   "nidp.nse_financials_cashflow · nidp.corporate_announcements · nidp.index_constituents (industry)"),
        "rows": out,
    }
