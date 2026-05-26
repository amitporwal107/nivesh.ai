"""Run the Great-Expectations suites against today's data and persist
results to nidp.validation_findings (severity=WARN/ERROR/CRITICAL based
on % failed rows).

Invocation (CLI):
    python -m nidp.services.quality_gate.great_expectations_runner \
        --feeds amfi_nav,fii_dii,bhavcopy,index_close \
        --date 2026-05-08

Without args: runs all 4 suites against the most recent target_date in
each feed.

Wired into quality_gate/__main__.py so the daily cron tick automatically
writes findings.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

import asyncpg

from nidp.services.quality_gate.great_expectations_suites import SUITES

logger = logging.getLogger(__name__)

PG_DSN = (
    os.environ.get("NIDP_PG_DSN")
    or os.environ.get("NIDP_POSTGRES_URL")
    or os.environ.get("POSTGRES_URL")
    or "postgresql://postgres:postgres@localhost:5433/nidp"
)


# Map feed name → (table, columns to project, max sample rows).
# Sampling caps protect the GE engine from running out of RAM if a
# feed has tens of millions of rows (bhavcopy is ~3500/day, but a
# whole-history sweep should still cap somewhere).
FEED_QUERIES = {
    # Legacy aliases kept for backwards-compat; canonical names added below
    "amfi_nav": {
        "table":    "nidp.mf_nav_daily",
        "columns":  "scheme_code, scheme_name, nav, isin_growth, nav_date AS as_of_date",
        "date_col": "nav_date",
        "limit":    200_000,
    },
    "fii_dii": {
        "table":    "nidp.fii_dii_flows",
        "columns":  "category, as_of_date, buy_value_cr AS buy_value, sell_value_cr AS sell_value, net_value_cr AS net_value",
        "date_col": "as_of_date",
        "limit":    100_000,
    },
    "bhavcopy": {
        "table":    "nidp.prices_eod",
        "columns":  "symbol, series, as_of_date, open_price, high_price, low_price, close_price, volume, isin",
        "date_col": "as_of_date",
        "limit":    200_000,
    },
    "index_close": {
        "table":    "nidp.index_eod",
        "columns":  "index_name, as_of_date, open_price, high_price, low_price, close_price",
        "date_col": "as_of_date",
        "limit":    50_000,
    },
    # Additional feeds registered but not yet having GE suites — return empty
    "delivery":          {"table": "nidp.delivery_data",    "columns": "symbol, as_of_date, deliv_qty, deliv_pct",                                    "date_col": "as_of_date", "limit": 200_000},
    "fno_bhavcopy":      {"table": "nidp.fno_bhavcopy",     "columns": "symbol, as_of_date, expiry_date, option_type, close_price, open_interest",     "date_col": "as_of_date", "limit": 100_000},
    "bulk_deals":        {"table": "nidp.bulk_deals",        "columns": "symbol, as_of_date, client_name, quantity, price",                            "date_col": "as_of_date", "limit": 10_000},
    "block_deals":       {"table": "nidp.block_deals",       "columns": "symbol, as_of_date, client_name, quantity, price",                            "date_col": "as_of_date", "limit": 10_000},
    "corporate_actions": {"table": "nidp.corporate_actions", "columns": "symbol, ex_date AS as_of_date, action_type, value",                           "date_col": "ex_date",    "limit": 50_000},
    "rbi_yields":        {"table": "nidp.rbi_yields",        "columns": "tenor, as_of_date, yield_pct",                                                "date_col": "as_of_date", "limit": 10_000},
}


async def _fetch_rows(
    conn: asyncpg.Connection, feed: str, target_date: Optional[str],
) -> List[dict]:
    cfg = FEED_QUERIES[feed]
    date_col = cfg.get("date_col", "as_of_date")
    where, params = "", []
    if target_date:
        where = f" WHERE {date_col} = $1::date "
        params = [target_date]
    sql = (f"SELECT {cfg['columns']} FROM {cfg['table']}{where} "
           f"ORDER BY {date_col} DESC LIMIT {cfg['limit']}")
    rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def _persist_findings(
    conn: asyncpg.Connection, run_id: uuid.UUID, ingester: str,
    target_date: Optional[str], suite_result: dict,
) -> int:
    """Write per-expectation findings into nidp.validation_findings."""
    inserted = 0
    for f in suite_result["findings"]:
        if f["success"]:
            continue
        pct = f["unexpected_percent"]
        # Severity → CRITICAL > 25% bad rows, ERROR > 5%, else WARN.
        if   pct > 25: sev = "CRITICAL"
        elif pct >  5: sev = "ERROR"
        else:          sev = "WARN"
        try:
            await conn.execute("""
                INSERT INTO nidp.validation_findings
                  (job_run_id, ingester, target_date, rule_name, severity,
                   message, expected, actual, sample_payload)
                VALUES ($1, $2, $3::date, $4, $5, $6, $7, $8, $9::jsonb)
            """,
                run_id, ingester, target_date, f["expectation_type"], sev,
                f["message"][:500],
                json.dumps(f["kwargs"], default=str)[:1000],
                str(f["unexpected_count"]),
                json.dumps({
                    "column":              f["column"],
                    "columns":             f["columns"],
                    "element_count":       f["element_count"],
                    "unexpected_percent":  f["unexpected_percent"],
                    "partial_unexpected":  f["partial_unexpected_list"],
                }, default=str),
            )
            inserted += 1
        except Exception as e:                                         # noqa: BLE001
            logger.warning("could not insert finding %s: %s", f["expectation_type"], e)
    return inserted


async def run_suite(
    feed: str,
    target_date: Optional[str] = None,
    *,
    persist: bool = True,
) -> Dict[str, Any]:
    """Run one feed's GE suite. Returns a structured report."""
    if feed not in SUITES:
        raise ValueError(f"unknown feed: {feed}. Known: {sorted(SUITES)}")

    conn = await asyncpg.connect(PG_DSN)
    try:
        rows = await _fetch_rows(conn, feed, target_date)
        if not rows:
            logger.warning("GE: %s has 0 rows for %s — suite skipped", feed, target_date or "all")
            return {
                "feed":              feed,
                "target_date":       target_date,
                "row_count":         0,
                "skipped":           True,
                "expectation_count": 0,
                "successful_count":  0,
                "failed_count":      0,
                "success":           False,
            }

        suite        = SUITES[feed](expected_date=target_date)
        result       = suite.run(rows, target_date=target_date)
        result_dict  = result.to_dict()
        result_dict["row_count"] = len(rows)

        run_id = uuid.uuid4()
        if persist:
            n_findings = await _persist_findings(
                conn, run_id, feed, target_date, result_dict,
            )
            result_dict["findings_persisted"] = n_findings
            result_dict["validation_run_id"]  = str(run_id)
            logger.info(
                "GE %s · target_date=%s · expectations=%d · success=%d · failures=%d (%d persisted to validation_findings)",
                feed, target_date, result.expectation_count,
                result.successful_count, result.failed_count, n_findings,
            )
        return result_dict
    finally:
        await conn.close()


async def run_all(target_date: Optional[str] = None,
                  feeds: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    feeds_list = list(feeds) if feeds else list(SUITES.keys())
    out: Dict[str, Any] = {"target_date": target_date, "feeds": {}}
    for f in feeds_list:
        try:
            out["feeds"][f] = await run_suite(f, target_date)
        except Exception as e:                                         # noqa: BLE001
            logger.exception("GE %s crashed", f)
            out["feeds"][f] = {"feed": f, "error": str(e)}
    n_pass = sum(1 for v in out["feeds"].values() if v.get("success"))
    out["summary"] = {
        "feeds_total":     len(out["feeds"]),
        "feeds_pass":      n_pass,
        "feeds_fail":      len(out["feeds"]) - n_pass,
    }
    return out


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────
def _cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--feeds", default=None,
                   help="comma-separated list. Default: all 4 GE suites.")
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD. Default: each feed's latest target_date.")
    p.add_argument("--no-persist", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s · %(message)s")

    feeds = [f.strip() for f in args.feeds.split(",")] if args.feeds else None
    out = asyncio.run(run_all(target_date=args.date, feeds=feeds))
    print(json.dumps(out, indent=2, default=str))
    sys.exit(0 if out["summary"]["feeds_fail"] == 0 else 1)


if __name__ == "__main__":
    _cli()
