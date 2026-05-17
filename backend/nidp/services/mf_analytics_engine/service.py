"""MF Analytics Engine — computes returns, risk, and category rankings.

Covers TASK-026 (returns) and TASK-027 (risk metrics).

Pipeline for each run:
  1. Fetch all active scheme codes + metadata from mf_scheme_master
  2. Fetch NAV history in bulk batches (by date window)
  3. For each scheme: compute returns and risk using calculator.py
  4. Fetch Nifty 50 index data for Alpha/Beta baseline
  5. Upsert into analytics.fund_category_rank
  6. Compute within-category rankings (return_1y_rank, sharpe_rank, composite_rank)

Performance notes:
  - 14,362 schemes × 1 year of NAV ≈ 3.6M rows in one query — too large
  - Batched by category (50–200 schemes per batch) to stay under 200k rows/fetch
  - Pure-numpy computation — no per-scheme round trips
  - ~2–4 minutes for all 14k schemes on e2-standard-4
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import asyncpg
import numpy as np

from .calculator import compute_returns, compute_risk_metrics

logger = logging.getLogger(__name__)

# Risk-free rate used for Sharpe/Sortino (India 10Y G-Sec proxy)
RISK_FREE_ANNUAL = 6.5

# NAV history window — 5 years + buffer for 5y CAGR
LOOKBACK_DAYS = 365 * 5 + 60

BATCH_SIZE = 150   # schemes per DB fetch
BENCHMARK = "Nifty 50"


@dataclass
class MfRunReport:
    rank_date: date
    run_id: str
    schemes_found: int = 0
    schemes_computed: int = 0
    schemes_skipped: int = 0
    rows_upserted: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def log(self) -> None:
        logger.info(
            "mf_engine_complete date=%s run=%s found=%d computed=%d skipped=%d "
            "upserted=%d errors=%d duration_ms=%d",
            self.rank_date, self.run_id, self.schemes_found, self.schemes_computed,
            self.schemes_skipped, self.rows_upserted, len(self.errors), self.duration_ms,
        )

    def as_dict(self) -> dict:
        return {
            "rank_date": str(self.rank_date),
            "run_id": self.run_id,
            "schemes_found": self.schemes_found,
            "schemes_computed": self.schemes_computed,
            "schemes_skipped": self.schemes_skipped,
            "rows_upserted": self.rows_upserted,
            "errors": self.errors[:20],
            "duration_ms": self.duration_ms,
        }


# ── DB helpers ────────────────────────────────────────────────────────

async def _fetch_schemes(conn: asyncpg.Connection) -> list[dict]:
    """All active schemes with metadata."""
    rows = await conn.fetch(
        """
        SELECT s.scheme_code, s.scheme_name, s.scheme_category,
               s.amc_id, s.launch_date,
               d.ter
          FROM nidp.mf_scheme_master s
          LEFT JOIN LATERAL (
              SELECT ter_pct AS ter
                FROM nidp.mf_scheme_disclosure_snapshot
               WHERE scheme_code = s.scheme_code
               ORDER BY snapshot_date DESC
               LIMIT 1
          ) d ON TRUE
         WHERE s.status = 'active'
           AND s.scheme_category IS NOT NULL
         ORDER BY s.scheme_category, s.scheme_code
        """
    )
    return [dict(r) for r in rows]


async def _fetch_nav_batch(
    conn: asyncpg.Connection,
    scheme_codes: list[str],
    since: date,
    until: date,
) -> dict[str, tuple[np.ndarray, list[date]]]:
    """Bulk-fetch NAV history for a batch of schemes.

    Returns: {scheme_code: (nav_array_oldest_first, date_list)}
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (scheme_code, nav_date)
               scheme_code, nav_date, nav
          FROM nidp.mf_nav_daily
         WHERE scheme_code = ANY($1::text[])
           AND nav_date >= $2
           AND nav_date <= $3
           AND nav > 0
         ORDER BY scheme_code, nav_date, source
        """,
        scheme_codes, since, until,
    )

    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r["scheme_code"], []).append((r["nav_date"], float(r["nav"])))

    result = {}
    for code, pairs in grouped.items():
        pairs.sort(key=lambda p: p[0])
        dates = [p[0] for p in pairs]
        navs = np.array([p[1] for p in pairs])
        result[code] = (navs, dates)
    return result


async def _fetch_benchmark(
    conn: asyncpg.Connection,
    since: date,
    until: date,
) -> Optional[np.ndarray]:
    """Fetch Nifty 50 close prices for Alpha/Beta computation."""
    rows = await conn.fetch(
        """
        SELECT as_of_date, close_price
          FROM nidp.index_eod
         WHERE index_name = $1
           AND as_of_date >= $2
           AND as_of_date <= $3
           AND close_price > 0
         ORDER BY as_of_date
        """,
        BENCHMARK, since, until,
    )
    if len(rows) < 30:
        return None
    return np.array([float(r["close_price"]) for r in rows])


# ── Ranking computation ────────────────────────────────────────────────

_RANK_SQL_1 = """
UPDATE analytics.fund_category_rank r
   SET return_1y_rank   = q.return_1y_rank,
       return_3y_rank   = q.return_3y_rank,
       return_5y_rank   = q.return_5y_rank,
       sharpe_rank      = q.sharpe_rank,
       sortino_rank     = q.sortino_rank,
       alpha_rank       = q.alpha_rank,
       ter_rank         = q.ter_rank,
       composite_rank   = q.composite_rank
  FROM (
    SELECT scheme_code,
           RANK() OVER w_ret1  AS return_1y_rank,
           RANK() OVER w_ret3  AS return_3y_rank,
           RANK() OVER w_ret5  AS return_5y_rank,
           RANK() OVER w_sh    AS sharpe_rank,
           RANK() OVER w_so    AS sortino_rank,
           RANK() OVER w_al    AS alpha_rank,
           RANK() OVER w_ter   AS ter_rank,
           CAST(
             0.30 * PERCENT_RANK() OVER w_ret1
           + 0.20 * PERCENT_RANK() OVER w_ret3
           + 0.25 * PERCENT_RANK() OVER w_sh
           + 0.10 * PERCENT_RANK() OVER w_so
           + 0.15 * (1 - PERCENT_RANK() OVER w_ter)
           AS NUMERIC(6,4)) AS composite_pct_rank
      FROM analytics.fund_category_rank
     WHERE rank_date = $1
     WINDOW
       w_ret1 AS (PARTITION BY category ORDER BY return_1y  DESC NULLS LAST),
       w_ret3 AS (PARTITION BY category ORDER BY return_3y  DESC NULLS LAST),
       w_ret5 AS (PARTITION BY category ORDER BY return_5y  DESC NULLS LAST),
       w_sh   AS (PARTITION BY category ORDER BY sharpe_1y  DESC NULLS LAST),
       w_so   AS (PARTITION BY category ORDER BY sortino_1y DESC NULLS LAST),
       w_al   AS (PARTITION BY category ORDER BY alpha_1y   DESC NULLS LAST),
       w_ter  AS (PARTITION BY category ORDER BY ter        ASC  NULLS LAST)
  ) q
 WHERE r.scheme_code = q.scheme_code
   AND r.rank_date   = $1
"""

_RANK_SQL_2 = """
UPDATE analytics.fund_category_rank outer_r
   SET composite_rank = inner_q.composite_rank
  FROM (
    SELECT scheme_code,
           RANK() OVER (PARTITION BY category ORDER BY composite_rank ASC NULLS LAST) AS composite_rank
      FROM analytics.fund_category_rank
     WHERE rank_date = $1
  ) inner_q
 WHERE outer_r.scheme_code = inner_q.scheme_code
   AND outer_r.rank_date   = $1
"""


_UPSERT_SQL = """
INSERT INTO analytics.fund_category_rank (
    scheme_code, rank_date,
    scheme_name, category, sub_category, amc_code,
    return_1m, return_3m, return_6m,
    return_1y, return_2y, return_3y, return_5y, return_ytd,
    return_since_launch_cagr,
    volatility_1y, sharpe_1y, sortino_1y, max_drawdown_1y,
    alpha_1y, beta_1y,
    ter,
    scheme_launch_date, data_since_date, nav_count,
    built_at
)
VALUES (
    $1, $2,
    $3, $4, $5, $6,
    $7, $8, $9,
    $10, $11, $12, $13, $14,
    $15,
    $16, $17, $18, $19,
    $20, $21,
    $22,
    $23, $24, $25,
    NOW()
)
ON CONFLICT (scheme_code, rank_date)
DO UPDATE SET
    scheme_name = EXCLUDED.scheme_name,
    category    = EXCLUDED.category,
    amc_code    = EXCLUDED.amc_code,
    return_1m   = EXCLUDED.return_1m,
    return_3m   = EXCLUDED.return_3m,
    return_6m   = EXCLUDED.return_6m,
    return_1y   = EXCLUDED.return_1y,
    return_2y   = EXCLUDED.return_2y,
    return_3y   = EXCLUDED.return_3y,
    return_5y   = EXCLUDED.return_5y,
    return_ytd  = EXCLUDED.return_ytd,
    return_since_launch_cagr = EXCLUDED.return_since_launch_cagr,
    volatility_1y   = EXCLUDED.volatility_1y,
    sharpe_1y       = EXCLUDED.sharpe_1y,
    sortino_1y      = EXCLUDED.sortino_1y,
    max_drawdown_1y = EXCLUDED.max_drawdown_1y,
    alpha_1y        = EXCLUDED.alpha_1y,
    beta_1y         = EXCLUDED.beta_1y,
    ter             = EXCLUDED.ter,
    scheme_launch_date = EXCLUDED.scheme_launch_date,
    data_since_date    = EXCLUDED.data_since_date,
    nav_count          = EXCLUDED.nav_count,
    built_at           = NOW()
"""


def _scheme_category(raw_category: Optional[str]) -> tuple[str, Optional[str]]:
    """Normalise 'Equity Scheme - Large Cap Fund' → (category='Equity', sub='Large Cap Fund')."""
    if not raw_category:
        return "Other", None
    if " - " in raw_category:
        parts = raw_category.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return raw_category.strip(), None


# ── Main entry point ──────────────────────────────────────────────────

async def compute_for_date(
    pool: asyncpg.Pool,
    rank_date: date,
    *,
    only_schemes: Optional[list[str]] = None,
    batch_size: int = BATCH_SIZE,
) -> MfRunReport:
    """Compute all MF return and risk metrics for rank_date.

    Args:
        pool:         asyncpg pool
        rank_date:    the 'as of' date (typically last trading day)
        only_schemes: optional filter for testing
    """
    t0 = time.monotonic()
    run_id = str(uuid.uuid4())
    report = MfRunReport(rank_date=rank_date, run_id=run_id)

    since = rank_date - timedelta(days=LOOKBACK_DAYS)

    async with pool.acquire() as conn:
        # Step 1: scheme metadata
        schemes = await _fetch_schemes(conn)
        if only_schemes:
            schemes = [s for s in schemes if s["scheme_code"] in only_schemes]
        report.schemes_found = len(schemes)

        if not schemes:
            logger.warning("mf_engine_no_schemes date=%s", rank_date)
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report

        logger.info("mf_engine_start date=%s schemes=%d run=%s", rank_date, len(schemes), run_id)

        # Step 2: fetch Nifty 50 for benchmark (Alpha/Beta)
        bench_navs = await _fetch_benchmark(conn, since, rank_date)
        if bench_navs is None:
            logger.warning("mf_engine_no_benchmark benchmark=%s", BENCHMARK)

        # Step 3: process in batches
        scheme_codes = [s["scheme_code"] for s in schemes]
        meta_by_code = {s["scheme_code"]: s for s in schemes}

        upsert_rows: list[tuple] = []

        for i in range(0, len(scheme_codes), batch_size):
            batch_codes = scheme_codes[i: i + batch_size]
            try:
                nav_data = await _fetch_nav_batch(conn, batch_codes, since, rank_date)
            except Exception as exc:
                logger.error("mf_engine_fetch_error batch=%d error=%s", i, exc)
                report.errors.append(f"fetch_batch_{i}: {exc}")
                continue

            for code in batch_codes:
                meta = meta_by_code[code]
                nav_pair = nav_data.get(code)

                if nav_pair is None or len(nav_pair[0]) < 21:
                    report.schemes_skipped += 1
                    continue

                navs, nav_dates = nav_pair
                try:
                    rets = compute_returns(navs, rank_date)
                    risk = compute_risk_metrics(
                        navs, bench_navs, rets.get("return_1y"),
                        window_bars=252,
                    )
                    cat, sub_cat = _scheme_category(meta.get("scheme_category"))

                    upsert_rows.append((
                        code, rank_date,
                        meta.get("scheme_name"), cat, sub_cat, meta.get("amc_id"),
                        _r(rets.get("return_1m")),
                        _r(rets.get("return_3m")),
                        _r(rets.get("return_6m")),
                        _r(rets.get("return_1y")),
                        _r(rets.get("return_2y")),
                        _r(rets.get("return_3y")),
                        _r(rets.get("return_5y")),
                        _r(rets.get("return_ytd")),
                        _r(rets.get("return_since_launch_cagr")),
                        _r(risk.get("volatility_1y")),
                        _r(risk.get("sharpe_1y")),
                        _r(risk.get("sortino_1y")),
                        _r(risk.get("max_drawdown_1y")),
                        _r(risk.get("alpha_1y")),
                        _r(risk.get("beta_1y")),
                        _r(meta.get("ter")),
                        meta.get("launch_date"),
                        nav_dates[0],
                        len(navs),
                    ))
                    report.schemes_computed += 1

                except Exception as exc:
                    logger.warning("mf_engine_compute_error scheme=%s error=%s", code, exc)
                    report.errors.append(f"{code}: {exc}")

            logger.info("mf_engine_batch_done batch=%d-%d computed=%d",
                        i, i + len(batch_codes), report.schemes_computed)

        # Step 4: upsert all rows
        if upsert_rows:
            try:
                await conn.executemany(_UPSERT_SQL, upsert_rows)
                report.rows_upserted = len(upsert_rows)
                logger.info("mf_engine_upserted rows=%d", len(upsert_rows))
            except Exception as exc:
                logger.error("mf_engine_upsert_error date=%s error=%s", rank_date, exc)
                report.errors.append(f"upsert: {exc}")

        # Step 5: compute within-category rankings (two separate statements — asyncpg
        # does not support multiple commands in a single prepared statement)
        if report.rows_upserted > 0:
            try:
                await conn.execute(_RANK_SQL_1, rank_date)
                await conn.execute(_RANK_SQL_2, rank_date)
                logger.info("mf_engine_rankings_updated date=%s", rank_date)
            except Exception as exc:
                logger.warning("mf_engine_rank_error date=%s error=%s", rank_date, exc)
                report.errors.append(f"ranking: {exc}")

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.log()
    return report


_MAX_VAL = 99999.9999  # NUMERIC(10,4) max is 999999.9999; cap earlier to catch data errors

def _r(val) -> Optional[float]:
    """Round to 4 decimal places; None-safe. Clamps to ±99999.9999 to avoid DB overflow."""
    if val is None:
        return None
    try:
        v = float(val)
        if not np.isfinite(v):
            return None
        return round(max(-_MAX_VAL, min(_MAX_VAL, v)), 4)
    except (TypeError, ValueError):
        return None


# ── Pool factory ────────────────────────────────────────────────────────

async def create_pool(url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=6,
        command_timeout=180,
        statement_cache_size=0,
        server_settings={"search_path": "nidp,analytics,public"},
    )
