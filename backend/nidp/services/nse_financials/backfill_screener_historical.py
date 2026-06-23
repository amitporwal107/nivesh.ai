"""Historical Screener.in backfill — Nifty 500 companies, last N days of quarters.

Processes symbols in tier order (T0=Nifty50 first, T3=Nifty500 tail last) so
the most important stocks are populated first.  Each Screener.in page fetch
yields up to 13 quarters; we write every quarter whose period_end falls within
the lookback window.

Feed failures are reported immediately via:
  • ERROR log (picked up by Grafana / Cloud Logging)
  • nidp.job_log row with status='FAILED'
  • nidp.exception_queue entry (surfaces in the DQ dashboard)

Usage:
    python -m nidp.services.nse_financials.backfill_screener_historical
    python -m nidp.services.nse_financials.backfill_screener_historical --days 365
    python -m nidp.services.nse_financials.backfill_screener_historical --tier 0
    python -m nidp.services.nse_financials.backfill_screener_historical --symbols RELIANCE,TCS --force
    python -m nidp.services.nse_financials.backfill_screener_historical --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

from .ir_scraper import fetch_screener_quarters
from .llm_extractor import (
    parse_all_screener_quarters,
    parse_screener_balance_sheet,
    parse_screener_profit_loss,
)
from .writer import upsert_financials

# Global flag — set when Screener.in rate-limits us; stops new fetches
_rate_limited = False

logger = logging.getLogger(__name__)

_INGESTER = "screener_backfill_historical"

# Tier definitions (evaluated as set differences so each symbol appears once)
_TIER_INDICES = {
    0: "Nifty 50",
    1: "Nifty 100",   # minus T0
    2: "Nifty 200",   # minus T0+T1
    3: "Nifty 500",   # minus T0+T1+T2
}

# Tier 4 (SD-07/SD-08): everything the engine scores beyond Nifty 500 — small/micro
# caps. This historical backfill is what populates multi-year annual P&L (→ 3Y CAGR)
# and shareholding history (→ promoter/FII/DII QoQ), neither of which exists for these
# names today. Symbols come from the full scored universe, not an index.
_FULL_UNIVERSE_TIER = 4


# ── DB helpers ──────────────────────────────────────────────────────────────

async def _load_tiered_symbols(
    conn,
    max_tier: int,
    symbols_override: Optional[list[str]],
) -> list[tuple[int, str]]:
    """Return [(tier, symbol), ...] in processing order (T0 first)."""
    if symbols_override:
        return [(0, s.upper().strip()) for s in symbols_override]

    seen: set[str] = set()
    result: list[tuple[int, str]] = []
    for tier in range(max_tier + 1):
        index_name = _TIER_INDICES.get(tier)
        if index_name:
            rows = await conn.fetch(
                """
                SELECT DISTINCT symbol
                  FROM nidp.index_constituents
                 WHERE index_name = $1
                   AND as_of_date = (
                         SELECT MAX(as_of_date) FROM nidp.index_constituents
                          WHERE index_name = $1
                       )
                 ORDER BY symbol
                """,
                index_name,
            )
        elif tier == _FULL_UNIVERSE_TIER:
            # Beyond the index tiers: every scored stock, missing-fundamentals first.
            rows = await conn.fetch(
                "SELECT symbol FROM nidp.v_screener_backfill_universe "
                "ORDER BY has_fundamentals, symbol"
            )
        else:
            continue
        for r in rows:
            sym = r["symbol"]
            if sym not in seen:
                seen.add(sym)
                result.append((tier, sym))
    return result


async def _already_ingested(conn, symbol: str, since_date: str) -> bool:
    """True if every quarter since since_date already has a screener_in row."""
    count = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT period_end)
          FROM nidp.nse_financials_quarterly
         WHERE symbol = $1
           AND source = 'screener_in'
           AND period_end >= $2
        """,
        symbol, date.fromisoformat(since_date),
    )
    # Heuristic: if we already have ≥ 4 quarters in window, skip
    return (count or 0) >= 4


async def _write_job_log(
    conn, run_id: str, symbol: str, tier: int,
    status: str, rows_inserted: int = 0, error_msg: Optional[str] = None,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO nidp.job_log
                (run_id, ingester, started_at, status, rows_inserted, error_message, metadata, finished_at)
            VALUES ($1, $2, NOW(), $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (run_id) DO UPDATE SET
                status         = EXCLUDED.status,
                rows_inserted  = EXCLUDED.rows_inserted,
                error_message  = EXCLUDED.error_message,
                finished_at    = NOW()
            """,
            run_id, _INGESTER, status, rows_inserted, error_msg,
            f'{{"symbol":"{symbol}","tier":{tier}}}',
        )
    except Exception as e:
        logger.debug("_write_job_log failed for %s: %s", symbol, e)


async def _report_failure(conn, symbol: str, tier: int, reason: str) -> None:
    """Write to exception_queue for immediate DQ dashboard visibility."""
    try:
        await conn.execute(
            """
            INSERT INTO nidp.exception_queue
                (target_date, domain, outcome, block_findings, reason)
            VALUES ($1, $2, 'REVIEW', 1, $3)
            ON CONFLICT (target_date, domain) DO UPDATE SET
                reason     = EXCLUDED.reason,
                resolved   = false,
                created_at = NOW()
            """,
            date.today(),
            f"screener_backfill/{symbol}",
            reason,
        )
        logger.error(
            "FEED FAILURE [tier=%d] %s: %s — logged to exception_queue",
            tier, symbol, reason,
        )
    except Exception as e:
        logger.error("FEED FAILURE [tier=%d] %s: %s (exception_queue write failed: %s)",
                     tier, symbol, reason, e)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _match_balance_sheet(
    quarter_period_end: str,
    bs_entries: list[dict],
) -> dict:
    """Return balance sheet columns for the most recent fiscal year end ≤ quarter_period_end.

    Screener.in balance sheet uses March 31 year-ends. For a quarter ending
    Jun/Sep/Dec, the most recent available balance sheet is the prior March year-end.
    For March quarters, the balance sheet from the same March year-end applies.
    """
    best: dict | None = None
    best_date: date | None = None
    q_date = date.fromisoformat(quarter_period_end)
    for entry in bs_entries:
        try:
            bs_date = date.fromisoformat(entry["period_end"])
        except (ValueError, KeyError):
            continue
        if bs_date <= q_date and (best_date is None or bs_date > best_date):
            best = entry
            best_date = bs_date

    if not best:
        return {}
    return {
        "equity_share_capital_cr": best.get("equity_share_capital_cr"),
        "total_equity_cr":         best.get("total_equity_cr"),
        "long_term_debt_cr":       best.get("long_term_debt_cr"),
    }


# ── Core per-symbol logic ────────────────────────────────────────────────────

async def _process_one(
    tier: int,
    symbol: str,
    since_date: str,
    semaphore: asyncio.Semaphore,
    delay_ms: int,
    force: bool,
    dry_run: bool,
) -> dict:
    """Fetch + upsert all quarters in window for one symbol. Returns stats dict."""
    run_id = str(uuid.uuid4())
    stats = {"symbol": symbol, "tier": tier, "outcome": "unknown", "quarters_written": 0}

    async with semaphore:
        await asyncio.sleep(delay_ms / 1000)

        pool = await get_pool()
        async with pool.acquire() as conn:

            if not force and not dry_run:
                if await _already_ingested(conn, symbol, since_date):
                    logger.debug("backfill_hist: %s already has ≥4 quarters, skipping", symbol)
                    stats["outcome"] = "skipped"
                    return stats

            if dry_run:
                logger.info("backfill_hist [DRY-RUN] T%d %s — would fetch", tier, symbol)
                stats["outcome"] = "dry_run"
                return stats

            # ── Fetch ────────────────────────────────────────────────────
            global _rate_limited
            if _rate_limited:
                stats["outcome"] = "rate_limited"
                return stats

            try:
                fetch_result = await fetch_screener_quarters(symbol)
            except RuntimeError as exc:
                # Screener.in rate-limit — halt all pending fetches
                _rate_limited = True
                reason = str(exc)
                logger.error(
                    "FEED FAILURE [RATE LIMIT] T%d %s: %s — halting remaining fetches",
                    tier, symbol, reason,
                )
                await _report_failure(conn, symbol, tier, f"RATE LIMIT: {reason}")
                await _write_job_log(conn, run_id, symbol, tier, "FAILED", error_msg=reason)
                stats["outcome"] = "rate_limited"
                return stats
            except Exception as exc:
                reason = f"fetch exception: {exc}"
                await _report_failure(conn, symbol, tier, reason)
                await _write_job_log(conn, run_id, symbol, tier, "FAILED", error_msg=reason)
                stats["outcome"] = "fetch_error"
                return stats

            if not fetch_result:
                reason = "symbol not found on Screener.in"
                await _report_failure(conn, symbol, tier, reason)
                await _write_job_log(conn, run_id, symbol, tier, "FAILED", error_msg=reason)
                stats["outcome"] = "not_found"
                return stats

            html, is_consolidated = fetch_result

            # ── Parse income statement quarters ──────────────────────────
            quarters = parse_all_screener_quarters(
                symbol, html, consolidated=is_consolidated, since_date=since_date
            )
            if not quarters:
                reason = "parse returned 0 quarters in window"
                await _report_failure(conn, symbol, tier, reason)
                await _write_job_log(conn, run_id, symbol, tier, "FAILED", error_msg=reason)
                stats["outcome"] = "parse_failed"
                return stats

            # ── Parse balance sheet (annual) ─────────────────────────────
            bs_entries = parse_screener_balance_sheet(
                symbol, html, consolidated=is_consolidated
            )

            # ── Parse annual P&L (profit-loss section) ───────────────────
            # Use since_year 3 years before lookback window to cover full 3Y CAGR
            # window even when main lookback is 1 year.
            try:
                lookback_year = date.fromisoformat(since_date).year
            except (ValueError, AttributeError):
                lookback_year = date.today().year - 1
            pl_entries = parse_screener_profit_loss(
                symbol, html,
                consolidated=is_consolidated,
                since_year=lookback_year - 3,
            )

            # ── Write income statement + balance sheet per quarter ───────
            written = 0
            for parsed, raw_data in quarters:
                if parsed.get("pat_cr") is None and parsed.get("revenue_from_ops_cr") is None:
                    continue  # no meaningful income data for this quarter

                # Merge nearest fiscal-year-end balance sheet into quarterly row
                q_end = parsed.get("period_end", "")
                if q_end and bs_entries:
                    bs = _match_balance_sheet(q_end, bs_entries)
                    for k, v in bs.items():
                        if v is not None and parsed.get(k) is None:
                            parsed[k] = v

                fid = await upsert_financials(
                    symbol, parsed, source="screener_in", raw_data=raw_data
                )
                if fid:
                    written += 1

            if written == 0:
                reason = f"0 quarters written (parsed {len(quarters)}, all null)"
                await _report_failure(conn, symbol, tier, reason)
                await _write_job_log(conn, run_id, symbol, tier, "FAILED", error_msg=reason)
                stats["outcome"] = "no_data"
                return stats

            # ── Write annual P&L records ─────────────────────────────────
            pl_written = 0
            for pl in pl_entries:
                fid = await upsert_financials(
                    symbol, pl, source="screener_in_annual", raw_data=None
                )
                if fid:
                    pl_written += 1

            # ── Shareholding: NOT written here ───────────────────────────
            # Shareholding has a single golden source — the NSE regulatory filing
            # (nse_shareholding → shareholding_pattern.source='NSE_SHP'). Screener is a
            # re-publisher and disagreed with NSE on most overlaps, so mixing them created
            # duplicate, inconsistent rows. Coverage/QoQ depth must come from backfilling
            # NSE history, not from Screener.
            shp_written = 0

            await _write_job_log(conn, run_id, symbol, tier, "OK", rows_inserted=written)
            logger.info(
                "backfill_hist: ✓ T%d %-15s  %d quarters  %d bs_years  %d pl_years  %d shp written  since=%s",
                tier, symbol, written, len(bs_entries), pl_written, shp_written, since_date,
            )
            stats.update({
                "outcome": "ok",
                "quarters_written": written,
                "bs_years": len(bs_entries),
                "pl_years": pl_written,
                "shp_quarters": shp_written,
            })
            return stats


# ── Orchestrator ─────────────────────────────────────────────────────────────

async def run(
    days: int = 365,
    max_tier: int = 4,
    symbols_override: Optional[list[str]] = None,
    concurrency: int = 1,
    delay_ms: int = 3000,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    setup_logging(service=_INGESTER)
    since_date = (date.today() - timedelta(days=days)).isoformat()

    pool = await get_pool()
    async with pool.acquire() as conn:
        tiered_symbols = await _load_tiered_symbols(conn, max_tier, symbols_override)

    total = len(tiered_symbols)
    tier_counts = {}
    for t, _ in tiered_symbols:
        tier_counts[t] = tier_counts.get(t, 0) + 1

    logger.info(
        "backfill_hist: starting — %d symbols, tiers=%s, since=%s, "
        "concurrency=%d, delay=%dms, force=%s, dry_run=%s",
        total, dict(sorted(tier_counts.items())), since_date,
        concurrency, delay_ms, force, dry_run,
    )

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        _process_one(tier, sym, since_date, semaphore, delay_ms, force, dry_run)
        for tier, sym in tiered_symbols
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outcome_counts: dict[str, int] = {}
    total_quarters = 0
    for (tier, sym), res in zip(tiered_symbols, results):
        if isinstance(res, Exception):
            logger.error("backfill_hist: unhandled exception for %s (T%d): %s", sym, tier, res)
            outcome_counts["exception"] = outcome_counts.get("exception", 0) + 1
        else:
            o = res.get("outcome", "unknown")
            outcome_counts[o] = outcome_counts.get(o, 0) + 1
            total_quarters += res.get("quarters_written", 0)

    logger.info(
        "backfill_hist: done — %d symbols, %d quarters written. %s",
        total, total_quarters,
        "  ".join(f"{k}={v}" for k, v in sorted(outcome_counts.items())),
    )
    await close_pool()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Historical Screener.in backfill (tier-ordered, full scored universe)"
    )
    p.add_argument("--days", type=int, default=365,
                   help="Lookback window in days (default: 365)")
    p.add_argument("--tier", type=int, default=4,
                   help="Max tier: 0=N50, 1=N100, 2=N200, 3=N500, 4=full scored universe (default: 4)")
    p.add_argument("--symbols", default=None,
                   help="Comma-separated symbol override (skips tier loading)")
    p.add_argument("--concurrency", type=int, default=1,
                   help="Max parallel Screener.in requests (default: 1 — do not increase without testing)")
    p.add_argument("--delay-ms", type=int, default=3000,
                   help="Delay between requests in ms (default: 3000 — keeps Screener.in rate limits safe)")
    p.add_argument("--force", action="store_true",
                   help="Re-ingest even if already has ≥4 quarters in window")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be fetched without writing to DB")
    a = p.parse_args()

    symbols = [s.strip() for s in a.symbols.split(",")] if a.symbols else None
    asyncio.run(run(
        days=a.days,
        max_tier=a.tier,
        symbols_override=symbols,
        concurrency=a.concurrency,
        delay_ms=a.delay_ms,
        force=a.force,
        dry_run=a.dry_run,
    ))


if __name__ == "__main__":
    main()
