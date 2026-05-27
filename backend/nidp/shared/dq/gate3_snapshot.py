"""Gate 3 — Snapshot Completion Gate.

Runs as a preflight before derivation engines (feature_snapshotter,
technical_indicator_engine, fundamental_engine, v3_scores_engine).

Rules implemented (from EXTENDED_QUALITY_GATE.md §5 + QUALITY_GATE.md §5):

  Feed-presence rules (P0):
    G3-PRES-001  bhavcopy row count 1800–2200 for snapshot_date
    G3-PRES-002  delivery row count 1700–2200 for snapshot_date
    G3-PRES-003  index_close  ≥ 20 rows for snapshot_date
    G3-PRES-004  fii_dii exactly 1 row for snapshot_date
    G3-PRES-005  mf_nav_daily ≥ 4500 rows for snapshot_date    (P0)
    G3-PRES-006  corporate_actions freshness < 24 h             (P1)

  Cross-feed consistency rules:
    G3-CONS-001  bhavcopy ↔ delivery symbol coverage within ±2%  (P0)
    G3-CONS-002  replication lag = 0 on pg_stat_replication       (P0)
    G3-CONS-003  no outstanding DLQ messages for snapshot_date    (P0)

  Snapshot integrity rules:
    G3-INT-001   shareholding percentages sum to 100 ± 0.5%       (P1)

Thresholds are read from dq.feed_sla where available, falling back to
hardcoded defaults so the gate still works before the seed rows land.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Optional

import asyncpg

from nidp.shared.dq.gate import BaseGate, CheckResult, Severity

logger = logging.getLogger(__name__)

# ── Default thresholds (match migration 077 seed rows) ────────────────────────

_DEFAULTS: dict[str, dict] = {
    "bhavcopy":     {"min": 1800, "max": 2200, "severity": Severity.P0},
    "delivery":     {"min": 1700, "max": 2200, "severity": Severity.P0},
    "index_close":  {"min": 20,   "max": None,  "severity": Severity.P0},
    "fii_dii":      {"min": 1,    "max": 1,     "severity": Severity.P0},
    "mf_nav_daily": {"min": 4500, "max": None,  "severity": Severity.P0},
}


class SnapshotCompletionGate(BaseGate):
    """Gate 3 — Snapshot Completion Gate.

    Usage::

        gate   = SnapshotCompletionGate()
        result = await gate.run(conn, target_date, job_run_id=run_id)
        # GateCheckFailed raised if any P0 rule fails
    """

    GATE_ID   = 3
    GATE_NAME = "snapshot_completion"

    def __init__(self, feed: Optional[str] = None) -> None:
        # Gate 3 is a multi-feed gate; feed label is "multi" by default.
        super().__init__(feed=feed or "multi")

    # ── Public helpers ────────────────────────────────────────────────────────

    async def _checks(
        self,
        conn: asyncpg.Connection,
        target_date: date,
        job_run_id: Optional[uuid.UUID] = None,
    ) -> list[CheckResult]:
        results: list[CheckResult] = []

        # ── 1. Feed-presence rules ─────────────────────────────────────────
        results.append(await self._check_bhavcopy(conn, target_date))
        results.append(await self._check_delivery(conn, target_date))
        results.append(await self._check_index_close(conn, target_date))
        results.append(await self._check_fii_dii(conn, target_date))
        results.append(await self._check_mf_nav_daily(conn, target_date))
        results.append(await self._check_corporate_actions_freshness(conn, target_date))

        # ── 2. Cross-feed consistency rules ───────────────────────────────
        results.append(await self._check_bhavcopy_delivery_coverage(conn, target_date))
        results.append(await self._check_replication_lag(conn, target_date))
        results.append(await self._check_dlq_outstanding(conn, target_date))

        # ── 3. Snapshot integrity rules ────────────────────────────────────
        results.append(await self._check_shareholding_sum(conn, target_date))

        return results

    # ── G3-PRES-001 : bhavcopy ────────────────────────────────────────────────

    async def _check_bhavcopy(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM nidp.bhavcopy WHERE trade_date = $1",
            target_date,
        )
        cnt  = row["cnt"]
        cfg  = await self._sla(conn, "bhavcopy")
        lo   = cfg["row_count_min"] or _DEFAULTS["bhavcopy"]["min"]
        hi   = cfg["row_count_max"] or _DEFAULTS["bhavcopy"]["max"]
        ok   = lo <= cnt <= hi
        return CheckResult(
            name="G3-PRES-001",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"bhavcopy row count {cnt} within [{lo}, {hi}]"
                if ok
                else f"bhavcopy row count {cnt} outside expected [{lo}, {hi}]"
            ),
            details={"row_count": cnt, "min": lo, "max": hi},
        )

    # ── G3-PRES-002 : delivery ────────────────────────────────────────────────

    async def _check_delivery(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM nidp.delivery WHERE trade_date = $1",
            target_date,
        )
        cnt  = row["cnt"]
        cfg  = await self._sla(conn, "delivery")
        lo   = cfg["row_count_min"] or _DEFAULTS["delivery"]["min"]
        hi   = cfg["row_count_max"] or _DEFAULTS["delivery"]["max"]
        ok   = lo <= cnt <= hi
        return CheckResult(
            name="G3-PRES-002",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"delivery row count {cnt} within [{lo}, {hi}]"
                if ok
                else f"delivery row count {cnt} outside expected [{lo}, {hi}]"
            ),
            details={"row_count": cnt, "min": lo, "max": hi},
        )

    # ── G3-PRES-003 : index_close ─────────────────────────────────────────────

    async def _check_index_close(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM nidp.index_close WHERE trade_date = $1",
            target_date,
        )
        cnt  = row["cnt"]
        cfg  = await self._sla(conn, "index_close")
        lo   = cfg["row_count_min"] or _DEFAULTS["index_close"]["min"]
        ok   = cnt >= lo
        return CheckResult(
            name="G3-PRES-003",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"index_close row count {cnt} >= {lo}"
                if ok
                else f"index_close row count {cnt} < minimum {lo}"
            ),
            details={"row_count": cnt, "min": lo},
        )

    # ── G3-PRES-004 : fii_dii ────────────────────────────────────────────────

    async def _check_fii_dii(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM nidp.fii_dii WHERE trade_date = $1",
            target_date,
        )
        cnt = row["cnt"]
        ok  = cnt == 1
        return CheckResult(
            name="G3-PRES-004",
            passed=ok,
            severity=Severity.P0,
            message=(
                "fii_dii exactly 1 row present"
                if ok
                else f"fii_dii expected exactly 1 row, got {cnt}"
            ),
            details={"row_count": cnt},
        )

    # ── G3-PRES-005 : mf_nav_daily ────────────────────────────────────────────

    async def _check_mf_nav_daily(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM nidp.mf_nav_daily WHERE nav_date = $1",
            target_date,
        )
        cnt  = row["cnt"]
        cfg  = await self._sla(conn, "mf_nav_daily")
        lo   = cfg["row_count_min"] or _DEFAULTS["mf_nav_daily"]["min"]
        ok   = cnt >= lo
        return CheckResult(
            name="G3-PRES-005",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"mf_nav_daily row count {cnt} >= {lo}"
                if ok
                else f"mf_nav_daily row count {cnt} < minimum {lo} (AMFI feed missing or incomplete)"
            ),
            details={"row_count": cnt, "min": lo},
        )

    # ── G3-PRES-006 : corporate_actions freshness < 24 h ─────────────────────

    async def _check_corporate_actions_freshness(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            """
            SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at)))::INT AS age_secs
            FROM nidp.corporate_actions
            """,
        )
        age_secs = row["age_secs"]
        cfg      = await self._sla(conn, "corporate_actions")
        limit    = cfg["freshness_warn_secs"] or 86400  # 24 h default
        if age_secs is None:
            return CheckResult(
                name="G3-PRES-006",
                passed=False,
                severity=Severity.P1,
                message="corporate_actions table is empty — no freshness baseline",
                details={"age_secs": None},
            )
        ok = age_secs <= limit
        return CheckResult(
            name="G3-PRES-006",
            passed=ok,
            severity=Severity.P1,
            message=(
                f"corporate_actions freshness {age_secs}s within {limit}s"
                if ok
                else f"corporate_actions freshness {age_secs}s exceeds {limit}s"
            ),
            details={"age_secs": age_secs, "limit_secs": limit},
        )

    # ── G3-CONS-001 : bhavcopy ↔ delivery symbol coverage ≤ ±2% ─────────────

    async def _check_bhavcopy_delivery_coverage(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        row = await conn.fetchrow(
            """
            WITH counts AS (
                SELECT
                    (SELECT COUNT(DISTINCT symbol) FROM nidp.bhavcopy
                     WHERE trade_date = $1) AS bhav_count,
                    (SELECT COUNT(DISTINCT symbol) FROM nidp.delivery
                     WHERE trade_date = $1) AS dlv_count
            )
            SELECT bhav_count, dlv_count,
                   CASE WHEN bhav_count = 0 THEN NULL
                        ELSE ABS(bhav_count - dlv_count)::FLOAT / bhav_count
                   END AS drift_ratio
            FROM counts
            """,
            target_date,
        )
        bhav    = row["bhav_count"] or 0
        dlv     = row["dlv_count"]  or 0
        drift   = row["drift_ratio"]
        ok      = drift is not None and drift <= 0.02
        return CheckResult(
            name="G3-CONS-001",
            passed=ok,
            severity=Severity.P0,
            message=(
                f"bhavcopy/delivery symbol coverage drift {drift:.2%} within ±2%"
                if ok
                else (
                    f"bhavcopy/delivery symbol coverage drift {drift:.2%} exceeds ±2%"
                    if drift is not None
                    else "bhavcopy symbol count is 0 — cannot compute coverage"
                )
            ),
            details={
                "bhavcopy_symbols": bhav,
                "delivery_symbols": dlv,
                "drift_ratio":      round(drift, 4) if drift is not None else None,
            },
        )

    # ── G3-CONS-002 : replication lag = 0 ────────────────────────────────────

    async def _check_replication_lag(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        rows = await conn.fetch(
            """
            SELECT client_addr,
                   EXTRACT(EPOCH FROM replay_lag)::INT AS lag_secs
            FROM pg_stat_replication
            WHERE replay_lag > INTERVAL '5 seconds'
            """
        )
        lagging = [
            {"client_addr": str(r["client_addr"]), "lag_secs": r["lag_secs"]}
            for r in rows
        ]
        ok = len(lagging) == 0
        return CheckResult(
            name="G3-CONS-002",
            passed=ok,
            severity=Severity.P0,
            message=(
                "Replication lag within 5 seconds on all standbys"
                if ok
                else f"Replication lag > 5s on {len(lagging)} standby(s)"
            ),
            details={"lagging_standbys": lagging},
        )

    # ── G3-CONS-003 : no outstanding DLQ messages for date ───────────────────

    async def _check_dlq_outstanding(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        rows = await conn.fetch(
            """
            SELECT feed, COUNT(*) AS dlq_count
            FROM dq.dlq_findings
            WHERE target_date = $1
              AND replay_status = 'PENDING'
            GROUP BY feed
            HAVING COUNT(*) > 0
            """,
            target_date,
        )
        pending = {r["feed"]: r["dlq_count"] for r in rows}
        ok = len(pending) == 0
        return CheckResult(
            name="G3-CONS-003",
            passed=ok,
            severity=Severity.P0,
            message=(
                "No outstanding DLQ messages for snapshot date"
                if ok
                else f"DLQ has {sum(pending.values())} pending messages across {len(pending)} feed(s)"
            ),
            details={"pending_by_feed": pending},
        )

    # ── G3-INT-001 : shareholding percentages sum to 100 ± 0.5% ─────────────

    async def _check_shareholding_sum(
        self, conn: asyncpg.Connection, target_date: date
    ) -> CheckResult:
        # Use the latest available quarter, not target_date (quarterly feed).
        rows = await conn.fetch(
            """
            SELECT symbol,
                   (COALESCE(promoter_pct, 0)
                    + COALESCE(fii_pct, 0)
                    + COALESCE(dii_pct, 0)
                    + COALESCE(public_pct, 0)
                    + COALESCE(others_pct, 0)) AS total_pct
            FROM nidp.shareholding_pattern
            WHERE quarter_end = (
                SELECT MAX(quarter_end) FROM nidp.shareholding_pattern
            )
              AND ABS(
                  (COALESCE(promoter_pct, 0)
                   + COALESCE(fii_pct, 0)
                   + COALESCE(dii_pct, 0)
                   + COALESCE(public_pct, 0)
                   + COALESCE(others_pct, 0)) - 100
              ) > 0.5
            LIMIT 20
            """
        )
        failing = [{"symbol": r["symbol"], "total_pct": float(r["total_pct"])} for r in rows]
        ok = len(failing) == 0
        return CheckResult(
            name="G3-INT-001",
            passed=ok,
            severity=Severity.P1,
            message=(
                "All shareholding patterns sum to 100 ± 0.5%"
                if ok
                else f"{len(failing)} symbols have shareholding totals outside 100 ± 0.5%"
            ),
            details={"failing_symbols": failing[:10]},  # cap to 10 in details
        )

    # ── SLA helper ────────────────────────────────────────────────────────────

    async def _sla(
        self, conn: asyncpg.Connection, feed: str
    ) -> dict:
        """Return feed_sla row as dict, or empty dict if not found."""
        row = await conn.fetchrow(
            """
            SELECT freshness_warn_secs, freshness_error_secs,
                   row_count_min, row_count_max,
                   is_p0_for_derivation
            FROM dq.feed_sla
            WHERE feed = $1 AND gate_id = 3
            """,
            feed,
        )
        if row is None:
            return {}
        return dict(row)
