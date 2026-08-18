"""Daily feed health check.

Queries nidp.job_log for the last 24h and reports any feed that has NO
COMPLETED (status='OK') run. Emits a structured JSON summary to stdout
which Cloud Logging picks up. Exits 1 if any expected feed is missing
so Cloud Run flags the job FAILED — which surfaces in monitoring.

EXPECTED_FEEDS list below mirrors the daily-run feeds. Update when you
add/remove a feed. Weekly/monthly feeds get longer windows.

Environment:
    NIDP_HEALTH_LOOKBACK_HOURS  (default 30)  — how far back to look
    NIDP_HEALTH_FAIL_ON_GAPS    (default 1)   — exit 1 if gaps found

Usage:
    python -m nidp.services.feed_health_check
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from nidp.shared.logging_setup import setup_logging
from nidp.shared.storage.pg import get_pool
from nidp.shared.storage import reap_stale_runs

logger = logging.getLogger(__name__)

# Feeds expected to land at least once per WINDOW_HOURS — DERIVED from the
# canonical registry (WORK-0144), so the monitored set, the cron, and the drift
# test all flow from ONE source. Add/change a feed in nidp.shared.feed_registry.
# (ingester_name, max_age_hours, severity); severity ERROR = page, WARN = log.
from nidp.shared.feed_registry import expected_feeds as _expected_feeds

EXPECTED_FEEDS: list[tuple[str, int, str]] = _expected_feeds()


# History depth check — tables/columns the scoring engine relies on.
# (table, date_column, min_days_required, severity, comment)
# min_days_required = 0 means "report but don't fail"; for stock features
# the scoring engine needs ≥365 trading days for volatility_1y_pct.
DEPTH_CHECKS: list[tuple[str, str, int, str, str]] = [
    ("nidp.prices_eod",                "as_of_date",   365, "WARN", "stock CAGR / vol_1y / drawdown_1y need 252+ bars"),
    ("nidp.prices_eod_adjusted",       "as_of_date",   365, "WARN", "feeds populate_stock_price_features"),
    ("nidp.amfi_nav_daily",            "as_of_date",   365, "WARN", "MF return_1y / Sharpe / Sortino"),
    ("nidp.amfi_nav_daily",            "as_of_date",  1095, "WARN", "MF return_3y"),
    ("nidp.amfi_nav_daily",            "as_of_date",  1825, "WARN", "MF return_5y"),
    ("nidp.mf_holdings_monthly",       "as_of_month",   30, "WARN", "MF look-through quality view needs ≥1 recent disclosure"),
    ("nidp.stock_features_daily",      "as_of_date",     1, "ERROR", "Action Matrix scoring needs ≥1 fresh day"),
    ("analytics.fund_category_rank",   "as_of_date",     1, "ERROR", "MF Sharpe/Sortino/return rankings"),
]


async def _check_depths(conn) -> tuple[list[dict], list[dict]]:
    """Report MIN / MAX date per critical table and flag insufficient history.

    Returns (depth_rows, depth_gaps). depth_rows is informational;
    depth_gaps contains entries where the earliest-to-latest span is
    shorter than the scoring engine needs for a given factor.
    """
    depth_rows: list[dict] = []
    depth_gaps: list[dict] = []
    seen_tables: set[str] = set()

    for table, date_col, min_days, severity, comment in DEPTH_CHECKS:
        try:
            row = await conn.fetchrow(
                f"SELECT MIN({date_col}) AS first_date, "
                f"       MAX({date_col}) AS last_date, "
                f"       COUNT(DISTINCT {date_col}) AS distinct_dates "
                f"FROM {table}"
            )
        except Exception as exc:  # noqa: BLE001 — table might not exist yet
            depth_gaps.append({
                "table": table, "severity": severity,
                "reason": f"query failed: {exc}", "comment": comment,
            })
            continue

        if not row or row["first_date"] is None:
            depth_gaps.append({
                "table": table, "severity": severity,
                "reason": "table empty", "comment": comment,
            })
            continue

        span_days = (row["last_date"] - row["first_date"]).days
        # Emit the depth row once per table — multiple DEPTH_CHECKS rows
        # against the same table share the same span; only the min_days
        # bar differs.
        if table not in seen_tables:
            depth_rows.append({
                "table":          table,
                "first_date":     row["first_date"].isoformat(),
                "last_date":      row["last_date"].isoformat(),
                "span_days":      span_days,
                "distinct_dates": row["distinct_dates"],
            })
            seen_tables.add(table)

        if span_days < min_days:
            depth_gaps.append({
                "table":      table,
                "severity":   severity,
                "reason":     f"span {span_days}d < required {min_days}d",
                "first_date": row["first_date"].isoformat(),
                "comment":    comment,
            })

    return depth_rows, depth_gaps


async def check() -> dict:
    fail_on_gaps = os.environ.get("NIDP_HEALTH_FAIL_ON_GAPS", "1") == "1"

    # Close out runs stranded in RUNNING by a process that died. A stranded
    # row that is an ingester's latest run makes a dead feed look busy, so
    # the staleness checks below would never fire for it — reap first, then
    # measure. Threshold is generous so a genuinely long run is never shot.
    try:
        await reap_stale_runs.reap(
            int(os.environ.get("NIDP_STALE_RUN_MAX_AGE_HOURS",
                               reap_stale_runs.DEFAULT_MAX_AGE_HOURS)))
    except Exception:  # noqa: BLE001 - never let maintenance break the check
        logger.exception("stale-run reaper failed; continuing with health check")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Latest OK run per ingester
        rows = await conn.fetch(
            """
            SELECT ingester,
                   MAX(finished_at) AS last_ok
              FROM nidp.job_log
             WHERE status = 'OK'
               AND finished_at > NOW() - INTERVAL '14 days'
             GROUP BY ingester
            """
        )
        last_ok = {r["ingester"]: r["last_ok"] for r in rows}

        # Recent FAILED rows for context
        failed_rows = await conn.fetch(
            """
            SELECT ingester, target_date, started_at, error_message
              FROM nidp.job_log
             WHERE status = 'FAILED'
               AND started_at > NOW() - INTERVAL '36 hours'
             ORDER BY started_at DESC
             LIMIT 100
            """
        )

    now = datetime.now(timezone.utc)
    gaps: list[dict] = []
    healthy: list[dict] = []
    for ing, max_age_h, severity in EXPECTED_FEEDS:
        ok_ts = last_ok.get(ing)
        if ok_ts is None:
            gaps.append({
                "ingester": ing,
                "severity": severity,
                "reason":   f"no OK run in last 14 days",
                "last_ok":  None,
            })
            continue
        age_h = (now - ok_ts).total_seconds() / 3600
        if age_h > max_age_h:
            gaps.append({
                "ingester": ing,
                "severity": severity,
                "reason":   f"stale by {age_h:.1f}h (limit {max_age_h}h)",
                "last_ok":  ok_ts.isoformat(),
            })
        else:
            healthy.append({
                "ingester": ing,
                "last_ok":  ok_ts.isoformat(),
                "age_h":    round(age_h, 1),
            })

    error_gaps = [g for g in gaps if g["severity"] == "ERROR"]
    warn_gaps  = [g for g in gaps if g["severity"] == "WARN"]

    # History-depth check — answers "do we have enough days to compute
    # 3Y CAGR, 1Y volatility, etc.?"
    async with pool.acquire() as conn:
        depth_rows, depth_gaps = await _check_depths(conn)
    depth_error_gaps = [g for g in depth_gaps if g["severity"] == "ERROR"]

    summary = {
        "checked_at":         now.isoformat(),
        "expected_feeds":     len(EXPECTED_FEEDS),
        "healthy":            len(healthy),
        "gaps_total":         len(gaps),
        "gaps_error":         len(error_gaps),
        "gaps_warn":          len(warn_gaps),
        "gap_details":        gaps,
        "depth_checks":       depth_rows,
        "depth_gaps":         depth_gaps,
        "recent_failures":    [
            {
                "ingester":      r["ingester"],
                "target_date":   r["target_date"].isoformat() if r["target_date"] else None,
                "started_at":    r["started_at"].isoformat(),
                "error_message": (r["error_message"] or "")[:200],
            }
            for r in failed_rows
        ],
    }

    # Single-line JSON for Cloud Logging structured output
    print(json.dumps(summary, default=str))

    if error_gaps:
        logger.error("FEED HEALTH: %d ERROR-level gaps", len(error_gaps))
        for g in error_gaps:
            logger.error("  GAP %s severity=%s reason=%s last_ok=%s",
                         g["ingester"], g["severity"], g["reason"],
                         g["last_ok"])
    elif warn_gaps:
        logger.warning("FEED HEALTH: %d WARN-level gaps", len(warn_gaps))
    else:
        logger.info("FEED HEALTH: all %d feeds healthy", len(healthy))

    if depth_error_gaps:
        logger.error("FEED HEALTH: %d ERROR-level depth gaps", len(depth_error_gaps))
        for g in depth_error_gaps:
            logger.error("  DEPTH %s severity=%s reason=%s",
                         g["table"], g["severity"], g["reason"])
    elif depth_gaps:
        logger.warning("FEED HEALTH: %d depth gaps (informational)", len(depth_gaps))

    # Alert a human on ERROR-level gaps (feed stale / insufficient history).
    # Off-band via nidp.shared.notify (email/Telegram) — this detector was
    # previously unscheduled and reached no notifier (see HANDOFF §B7).
    if error_gaps or depth_error_gaps:
        from nidp.shared import notify as _notify
        body_lines = [f"{g['ingester']}: {g['reason']} (last_ok={g['last_ok']})"
                      for g in error_gaps]
        body_lines += [f"depth {g['table']}: {g['reason']}" for g in depth_error_gaps]
        _notify.notify(
            f"🔴 NIDP feed health: {len(error_gaps) + len(depth_error_gaps)} ERROR gap(s)",
            "\n".join(body_lines),
        )

    if fail_on_gaps and (error_gaps or depth_error_gaps):
        sys.exit(1)

    return summary


def main() -> None:
    setup_logging(service="feed_health_check")
    asyncio.run(check())


if __name__ == "__main__":
    main()
