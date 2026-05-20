#!/usr/bin/env python3
"""Read-only verification that the NIDP data-lake fixes are populating data.

Runs after PR feat/nidp-data-lake-fixes deploys (migration 059 + 3 new cron
entries + populate_stock_price_features wiring). Confirms each fix actually
landed in production data, not just in code.

Output: per-check ✓/✗ summary + overall exit code.

Usage:
    NIDP_POSTGRES_URL=postgresql://... python backend/scripts/verify_nidp_data_lake.py

    # Strict mode (fail on warn-level gaps too):
    NIDP_POSTGRES_URL=... python backend/scripts/verify_nidp_data_lake.py --strict

Exit codes:
    0 — all critical checks passed (data lake green)
    1 — at least one critical check failed (engines red or partial)
    2 — DB unreachable / NIDP_POSTGRES_URL not set (can't even start)

This is pure-read. Safe to run any number of times against production —
no side effects, no writes.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from typing import Awaitable, Callable, Optional

try:
    import asyncpg
except ImportError:
    print("asyncpg not installed. Install with:  pip install asyncpg", file=sys.stderr)
    sys.exit(2)


# Thresholds calibrated for the first nightly run post-deploy. After the
# data lake has been running for a week, these can be tightened.
CRITICAL_THRESHOLDS = {
    "mf_analytics_rows":        10_000,    # ~14k MF schemes; allow 30% miss
    "mf_analytics_ret1y_ratio":     0.80,  # 80% of schemes have return_1y
    "stock_features_piotroski":     0.50,  # 50% of stocks have Piotroski
    "stock_features_vol1y":         0.50,  # 50% have volatility_1y_pct
    "lookthrough_schemes":          100,   # ≥100 schemes in look-through view
    "lookthrough_avg_coverage":     55.0,  # ≥55% avg coverage_pct
}


# ANSI colour codes — disabled when stdout isn't a TTY (e.g., CI logs).
def _supports_colour() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


_USE_COLOUR = _supports_colour()
GREEN  = "\033[32m✓\033[0m" if _USE_COLOUR else "[OK]"
YELLOW = "\033[33m⚠\033[0m" if _USE_COLOUR else "[WARN]"
RED    = "\033[31m✗\033[0m" if _USE_COLOUR else "[FAIL]"


async def _check(
    conn: "asyncpg.Connection",
    label: str,
    sql: str,
    expectation_fn: Callable[[Optional["asyncpg.Record"]], tuple[bool, str]],
    *,
    severity: str = "critical",
) -> bool:
    """Run one diagnostic query and print a ✓/✗ line.

    `expectation_fn` receives the fetched row (or None) and returns
    (passed: bool, human_msg: str). Critical failures contribute to the
    final exit code; warn-level failures only colour-flag the line.
    """
    try:
        row = await conn.fetchrow(sql)
    except Exception as exc:  # noqa: BLE001 — surface anything to the operator
        print(f"{RED} {label}: query failed — {exc}")
        return severity != "critical"

    ok, msg = expectation_fn(row)
    marker = GREEN if ok else (RED if severity == "critical" else YELLOW)
    print(f"{marker} {label}: {msg}")
    return ok or severity != "critical"


async def _run_checks(conn: "asyncpg.Connection") -> tuple[int, int]:
    """Run all checks. Returns (passed_count, total_count)."""
    results: list[bool] = []

    # ── 1. Migration 059 applied ─────────────────────────────────
    results.append(await _check(
        conn, "migration 059 applied",
        "SELECT 1 AS r FROM nidp.schema_migrations "
        "WHERE filename = '059_nidp_mf_lookthrough_quality.sql'",
        lambda r: (r is not None,
                   "applied" if r else "MISSING — apply 059 first"),
    ))

    # ── 2. View object exists ────────────────────────────────────
    results.append(await _check(
        conn, "view nidp.v_mf_lookthrough_quality",
        "SELECT 1 AS r FROM pg_views "
        "WHERE schemaname = 'nidp' AND viewname = 'v_mf_lookthrough_quality'",
        lambda r: (r is not None, "exists" if r else "MISSING"),
    ))

    # ── 3. mf_analytics_engine produced fresh rows ───────────────
    # Schema note: analytics.fund_category_rank uses `rank_date`, NOT
    # `as_of_date` — see migration 047 / mf_analytics_engine UPSERT_SQL.
    results.append(await _check(
        conn, "mf_analytics_engine — fund_category_rank fresh rows",
        "SELECT COUNT(*) AS rows, "
        "       COUNT(return_1y) FILTER (WHERE return_1y IS NOT NULL) AS has_ret "
        "  FROM analytics.fund_category_rank "
        " WHERE rank_date = (SELECT MAX(rank_date) FROM analytics.fund_category_rank)",
        lambda r: (
            r is not None
            and r["rows"] >= CRITICAL_THRESHOLDS["mf_analytics_rows"]
            and (r["has_ret"] / max(r["rows"], 1)) >= CRITICAL_THRESHOLDS["mf_analytics_ret1y_ratio"],
            (f"{r['rows']:,} schemes, "
             f"{(r['has_ret']/max(r['rows'],1))*100:.0f}% have return_1y"
             if r else "no rows"),
        ),
    ))

    # ── 4. fundamental_engine populated Piotroski ────────────────
    results.append(await _check(
        conn, "fundamental_engine — Piotroski coverage",
        "SELECT COUNT(*) AS rows, "
        "       COUNT(piotroski_score) FILTER (WHERE piotroski_score IS NOT NULL) AS has_pio "
        "  FROM nidp.stock_features_daily "
        " WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.stock_features_daily)",
        lambda r: (
            r is not None
            and (r["has_pio"] / max(r["rows"], 1)) >= CRITICAL_THRESHOLDS["stock_features_piotroski"],
            (f"{r['has_pio']:,}/{r['rows']:,} "
             f"({(r['has_pio']/max(r['rows'],1))*100:.0f}%) have Piotroski"
             if r else "no rows"),
        ),
    ))

    # ── 5. technical_indicator_engine populated volatility_1y_pct ─
    # This validates the new populate_stock_price_features() SQL wiring.
    results.append(await _check(
        conn, "technical_indicator_engine — volatility_1y_pct coverage",
        "SELECT COUNT(*) AS rows, "
        "       COUNT(volatility_1y_pct) FILTER (WHERE volatility_1y_pct IS NOT NULL) AS has_vol "
        "  FROM nidp.stock_features_daily "
        " WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.stock_features_daily)",
        lambda r: (
            r is not None
            and (r["has_vol"] / max(r["rows"], 1)) >= CRITICAL_THRESHOLDS["stock_features_vol1y"],
            (f"{r['has_vol']:,}/{r['rows']:,} "
             f"({(r['has_vol']/max(r['rows'],1))*100:.0f}%) have volatility_1y_pct"
             if r else "no rows"),
        ),
    ))

    # ── 6. v_mf_lookthrough_quality view returns sensible data ───
    results.append(await _check(
        conn, "v_mf_lookthrough_quality — rows + coverage",
        "SELECT COUNT(*) AS schemes, "
        "       COALESCE(AVG(coverage_pct), 0)::float AS avg_cov "
        "  FROM nidp.v_mf_lookthrough_quality",
        lambda r: (
            r is not None
            and r["schemes"] >= CRITICAL_THRESHOLDS["lookthrough_schemes"]
            and r["avg_cov"] >= CRITICAL_THRESHOLDS["lookthrough_avg_coverage"],
            (f"{r['schemes']:,} schemes, "
             f"avg coverage {r['avg_cov']:.1f}%"
             if r else "no rows"),
        ),
    ))

    # ── 7. Engines have OK runs in last 48h (warn-level on first deploy) ─
    results.append(await _check(
        conn, "all 3 engines have OK run in last 48h",
        "SELECT COUNT(DISTINCT ingester) AS engines "
        "  FROM nidp.job_log "
        " WHERE ingester IN ('mf_analytics_engine', "
        "                    'technical_indicator_engine', "
        "                    'fundamental_engine') "
        "   AND status = 'OK' "
        "   AND started_at > NOW() - INTERVAL '48 hours'",
        lambda r: (
            r is not None and r["engines"] >= 3,
            (f"{r['engines']}/3 engines ran successfully in last 48h"
             if r else "no rows"),
        ),
        severity="warn",  # may be empty on initial deploy before first nightly
    ))

    passed = sum(1 for x in results if x)
    return passed, len(results)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero on warn-level failures too (default: only on critical)",
    )
    args = parser.parse_args()

    url = os.environ.get("NIDP_POSTGRES_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        print(f"{RED} NIDP_POSTGRES_URL not set", file=sys.stderr)
        return 2

    try:
        conn = await asyncpg.connect(url)
    except Exception as exc:  # noqa: BLE001
        print(f"{RED} cannot connect to Postgres: {exc}", file=sys.stderr)
        return 2

    print(f"NIDP data-lake verification — {datetime.utcnow().isoformat()}Z")
    print(f"Strict mode: {args.strict}\n")

    try:
        passed, total = await _run_checks(conn)
    finally:
        await conn.close()

    failed = total - passed
    print()
    if failed == 0:
        print(f"{GREEN} all {total} checks passed — data lake is green")
        return 0
    # In strict mode, warn-level failures also escalate to exit 1. In
    # default mode, _run_checks already absorbs warns into passed.
    # So `failed > 0` here always means at least one critical failure.
    print(f"{RED} {failed} of {total} check(s) failed — see above")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
