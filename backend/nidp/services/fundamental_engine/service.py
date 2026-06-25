"""Fundamental Analytics Engine — computes Piotroski F-Score, Altman Z-Score,
and valuation signals for all NSE EQ stocks.

Flow for each run:
  1. Call nidp.populate_stock_features_extended(target_date) — fills ROE, D/E,
     market_cap_bucket, promoter_pct, sector, shareholding into stock_features_daily.
  1b. Call nidp.populate_stock_features_v3(target_date) — fills 3Y CAGR metrics
     (revenue_growth_3y_cagr_pct, profit_margin_trend_pct, debt_trend_pct) from
     annual Screener.in P&L data. V3 Health score primitives.
  2. Fetch latest + prior-year quarterly financials from v_stock_fundamentals_latest
     and nse_financials_quarterly for multi-quarter signals.
  3. Compute Piotroski F-Score and Altman Z-Score in Python.
  4. Compute sector median PE from the populated rows.
  5. Compute valuation signal (undervalued / fairly_valued / overvalued).
  6. Upsert scores + signals back to stock_features_daily.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import asyncpg

from .calculator import (
    compute_altman_z,
    compute_piotroski,
    valuation_signal,
)

logger = logging.getLogger(__name__)

SOURCE = "COPILOT_FUND_ENGINE"
BATCH_SIZE = 200

# The shared asyncpg pool sets command_timeout=30 (see nidp/shared/storage/pg.py),
# but populate_stock_features_extended / _v3 are bulk UPDATEs over the whole universe
# that take ~35s on staging. At 30s asyncpg cancels them with an empty-message
# TimeoutError, which left shareholding/fundamentals columns silently blank for the
# latest date. Override the per-statement timeout for these heavy maintenance calls.
_POPULATE_TIMEOUT_S = 600


@dataclass
class FundRunReport:
    target_date: date
    run_id: str
    symbols_found: int = 0
    symbols_scored: int = 0
    symbols_skipped: int = 0
    rows_upserted: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def log(self) -> None:
        logger.info(
            "fund_engine_complete date=%s run=%s found=%d scored=%d skipped=%d upserted=%d errors=%d duration_ms=%d",
            self.target_date, self.run_id, self.symbols_found, self.symbols_scored,
            self.symbols_skipped, self.rows_upserted, len(self.errors), self.duration_ms,
        )

    def as_dict(self) -> dict:
        return {
            "target_date": str(self.target_date),
            "run_id": self.run_id,
            "symbols_found": self.symbols_found,
            "symbols_scored": self.symbols_scored,
            "symbols_skipped": self.symbols_skipped,
            "rows_upserted": self.rows_upserted,
            "errors": self.errors[:20],
            "duration_ms": self.duration_ms,
        }


# ── Step 1: populate standard fundamental columns ─────────────────────

async def _populate_extended(conn: asyncpg.Connection, target_date: date) -> int:
    """Call the existing SQL function that joins fundamentals/shareholding/sector."""
    try:
        rows = await conn.fetchval(
            "SELECT nidp.populate_stock_features_extended($1)",
            target_date,
            timeout=_POPULATE_TIMEOUT_S,
        )
        logger.info("fund_engine_populate_extended date=%s rows_updated=%s", target_date, rows)
        return rows or 0
    except Exception as exc:
        # %r so an empty-message TimeoutError still shows its type — silent blanks
        # were caused by this being logged as an empty string and ignored.
        logger.error("fund_engine_populate_extended_error date=%s error=%r", target_date, exc)
        raise


async def _populate_v3(conn: asyncpg.Connection, target_date: date) -> int:
    """Call populate_stock_features_v3 — computes 3Y CAGR metrics from annual P&L.

    Fills revenue_growth_3y_cagr_pct, profit_margin_trend_pct, debt_trend_pct
    in stock_features_daily. Must run after _populate_extended (which fills the
    balance sheet columns that debt_trend uses).
    """
    try:
        rows = await conn.fetchval(
            "SELECT nidp.populate_stock_features_v3($1)",
            target_date,
            timeout=_POPULATE_TIMEOUT_S,
        )
        logger.info("fund_engine_populate_v3 date=%s rows_updated=%s", target_date, rows)
        return rows or 0
    except Exception as exc:
        logger.error("fund_engine_populate_v3_error date=%s error=%r", target_date, exc)
        raise


# ── Step 2: fetch financial data for scoring ──────────────────────────

async def _fetch_latest_fundamentals(conn: asyncpg.Connection) -> dict[str, dict]:
    """Fetch the latest quarterly fundamentals for all symbols."""
    rows = await conn.fetch(
        """
        SELECT symbol, period_end, period_type, consolidated,
               revenue_from_ops_cr, pat_cr, eps_basic, eps_diluted, face_value,
               total_equity_cr, long_term_debt_cr, short_term_debt_cr,
               cash_and_equiv_cr, ebitda_cr, finance_costs_cr, depreciation_cr,
               revenue_ttm_cr, pat_ttm_cr, eps_ttm,
               revenue_growth_yoy_pct, pat_growth_yoy_pct, eps_growth_yoy_pct
          FROM nidp.v_stock_fundamentals_latest
        """
    )
    return {r["symbol"]: dict(r) for r in rows}


async def _fetch_prior_year_quarters(
    conn: asyncpg.Connection,
    symbols: list[str],
) -> dict[str, dict]:
    """Fetch prior-year same quarter for Piotroski delta signals."""
    rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (symbol) symbol, period_end, consolidated
              FROM nidp.nse_financials_quarterly
             WHERE period_type = 'QUARTERLY'
             ORDER BY symbol, consolidated DESC, period_end DESC
        )
        SELECT f.symbol, f.period_end, f.consolidated,
               f.revenue_from_ops_cr, f.pat_cr, f.eps_basic, f.face_value,
               f.total_equity_cr, f.long_term_debt_cr, f.short_term_debt_cr,
               f.cash_and_equiv_cr, f.ebitda_cr, f.finance_costs_cr, f.depreciation_cr
          FROM nidp.nse_financials_quarterly f
          JOIN latest l ON l.symbol = f.symbol
                        AND l.consolidated = f.consolidated
         WHERE f.symbol = ANY($1::text[])
           AND f.period_type = 'QUARTERLY'
           AND f.period_end = (l.period_end - INTERVAL '1 year')::date
        """,
        symbols,
    )
    return {r["symbol"]: dict(r) for r in rows}


async def _fetch_current_prices(
    conn: asyncpg.Connection,
    target_date: date,
    symbols: list[str],
) -> dict[str, float]:
    """Fetch close prices for Altman X4 (market cap) computation."""
    rows = await conn.fetch(
        """
        SELECT symbol, close_price
          FROM nidp.prices_eod
         WHERE symbol = ANY($1::text[])
           AND as_of_date = $2
           AND series = 'EQ'
           AND close_price > 0
        """,
        symbols, target_date,
    )
    return {r["symbol"]: float(r["close_price"]) for r in rows}


# ── Step 3-5: compute and upsert ─────────────────────────────────────

_SCORE_UPDATE_SQL = """
UPDATE nidp.stock_features_daily
   SET piotroski_score   = $3,
       piotroski_signals = $4,
       altman_z_score    = $5,
       valuation_signal  = $6,
       sector_median_pe  = $7,
       ingested_at       = NOW()
 WHERE symbol = $1
   AND as_of_date = $2
"""


async def _upsert_scores(conn: asyncpg.Connection, rows: list[tuple]) -> int:
    await conn.executemany(_SCORE_UPDATE_SQL, rows)
    return len(rows)


async def _compute_sector_medians(conn: asyncpg.Connection, target_date: date) -> dict[str, float]:
    """Compute sector median PE from already-populated stock_features_daily rows."""
    rows = await conn.fetch(
        """
        SELECT sector, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pe_ttm) AS median_pe
          FROM nidp.stock_features_daily
         WHERE as_of_date = $1
           AND sector IS NOT NULL
           AND pe_ttm BETWEEN 0 AND 200
         GROUP BY sector
        """,
        target_date,
    )
    return {r["sector"]: float(r["median_pe"]) for r in rows if r["median_pe"] is not None}


# ── Main entry point ─────────────────────────────────────────────────

async def compute_for_date(
    pool: asyncpg.Pool,
    target_date: date,
    *,
    only_symbols: Optional[list[str]] = None,
    skip_populate: bool = False,
) -> FundRunReport:
    """Run the full fundamental analytics pipeline for target_date.

    Args:
        pool:           asyncpg connection pool
        target_date:    date to process (must have TI engine rows in stock_features_daily)
        only_symbols:   optional symbol filter (default: all)
        skip_populate:  set True to skip populate_stock_features_extended (e.g. already run)
    """
    t0 = time.monotonic()
    run_id = str(uuid.uuid4())
    report = FundRunReport(target_date=target_date, run_id=run_id)

    async with pool.acquire() as conn:
        # Step 1: populate standard fundamental columns via SQL function
        if not skip_populate:
            await _populate_extended(conn, target_date)
            # Also populate V3-specific 3Y CAGR metrics (revenue growth, margin trend,
            # debt trend) from annual Screener P&L data. Must run after _populate_extended
            # so balance sheet debt columns are current.
            await _populate_v3(conn, target_date)

        # Find all symbols with stock_features_daily rows for target_date
        if only_symbols:
            rows = await conn.fetch(
                "SELECT DISTINCT symbol FROM nidp.stock_features_daily "
                "WHERE as_of_date = $1 AND symbol = ANY($2::text[])",
                target_date, only_symbols,
            )
        else:
            rows = await conn.fetch(
                "SELECT DISTINCT symbol FROM nidp.stock_features_daily WHERE as_of_date = $1",
                target_date,
            )
        symbols = [r["symbol"] for r in rows]
        report.symbols_found = len(symbols)

        if not symbols:
            logger.warning("fund_engine_no_rows date=%s — run TI engine first", target_date)
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report

        logger.info("fund_engine_start date=%s symbols=%d run=%s", target_date, len(symbols), run_id)

        # Step 2: fetch financial data
        latest_fundamentals = await _fetch_latest_fundamentals(conn)
        prior_year_quarters = await _fetch_prior_year_quarters(conn, symbols)
        prices = await _fetch_current_prices(conn, target_date, symbols)

        # Step 3: compute Piotroski + Altman per symbol
        score_rows: list[tuple] = []
        for symbol in symbols:
            latest = latest_fundamentals.get(symbol)
            if not latest:
                report.symbols_skipped += 1
                continue
            try:
                prior = prior_year_quarters.get(symbol)
                close = prices.get(symbol)

                f_score, f_signals = compute_piotroski(latest, prior)
                z_score = compute_altman_z(latest, close)
                # valuation signal requires PE — computed in step 1; will fill after medians
                score_rows.append((symbol, f_score, f_signals, z_score))
                report.symbols_scored += 1
            except Exception as exc:
                logger.warning("fund_engine_compute_error symbol=%s error=%s", symbol, exc)
                report.errors.append(f"{symbol}: {exc}")

        # Step 4: compute sector medians (now that PE is populated by step 1)
        sector_medians = await _compute_sector_medians(conn, target_date)

        # Step 5: fetch PE and sector per symbol for valuation signal, then upsert
        pe_sector_rows = await conn.fetch(
            """
            SELECT symbol, pe_ttm, sector
              FROM nidp.stock_features_daily
             WHERE as_of_date = $1
            """,
            target_date,
        )
        pe_by_symbol = {r["symbol"]: (_f(r["pe_ttm"]), r["sector"]) for r in pe_sector_rows}

        upsert_rows: list[tuple] = []
        for symbol, f_score, f_signals, z_score in score_rows:
            pe_ttm, sector = pe_by_symbol.get(symbol, (None, None))
            med_pe = sector_medians.get(sector) if sector else None
            val_signal = valuation_signal(pe_ttm, med_pe)
            upsert_rows.append((
                symbol, target_date,
                f_score, f_signals, z_score,
                val_signal, med_pe,
            ))

        if upsert_rows:
            try:
                n = await _upsert_scores(conn, upsert_rows)
                report.rows_upserted = n
            except Exception as exc:
                logger.error("fund_engine_upsert_error date=%s error=%s", target_date, exc)
                report.errors.append(f"upsert: {exc}")

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.log()
    return report


def _f(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ── Pool factory (reuse TI engine pattern) ───────────────────────────

async def create_pool(url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=6,
        command_timeout=120,
        statement_cache_size=0,
        server_settings={"search_path": "nidp,public"},
    )


# ── Backfill / cron adapter ─────────────────────────────────────────
# Matches the run(target_date) convention every NIDP ingester exposes,
# so this service can be invoked by nidp/backfill.py and run_service.sh.
async def run(target_date: Optional[date] = None) -> dict:
    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("NIDP_POSTGRES_URL not set")
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    pool = await create_pool(url)
    try:
        report = await compute_for_date(pool, target_date)
        return report.as_dict()
    finally:
        await pool.close()
