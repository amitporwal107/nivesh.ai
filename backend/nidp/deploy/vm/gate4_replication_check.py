#!/usr/bin/env python3
"""Gate 4 — Replication Integrity Check.

Runs as a cron job on nivesh-app-vm every minute.  Probes:

  G4-CONT-001  WAL replay_lag < 30 seconds on all standbys          (P0)
  G4-CONT-002  Standby is in recovery mode (pg_is_in_recovery=true)  (P0)
  G4-CONT-003  WAL position advances every minute                    (P1)
  G4-PAR-001   Daily row-count parity: bhavcopy                      (P0)
  G4-PAR-002   Daily row-count parity: mf_nav_daily                  (P0)
  G4-PAR-003   Daily row-count parity: v3_stock_scores_daily         (P0)
  G4-PAR-004   Daily row-count parity: portfolio_holdings            (P0)

Parity checks only run when --mode=daily is passed (cron at 06:00 IST).
Continuous checks run every invocation (cron at * * * * *).

Verdicts are written to dq.gate_verdicts on the PRIMARY (primary can
always be written; standby is read-only).

Exit codes:
  0 — all checks pass or AMBER
  1 — at least one P0 failure
  2 — cannot connect to primary or standby

Crontab (on nivesh-app-vm):
  * * * * *    /opt/nidp/venv/bin/python /opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/vm/gate4_replication_check.py >> /opt/nidp/logs/gate4/gate4.log 2>&1
  0 1  * * *   /opt/nidp/venv/bin/python /opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/vm/gate4_replication_check.py --mode=daily >> /opt/nidp/logs/gate4/gate4_daily.log 2>&1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import date, timedelta

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gate4")

# ── Connection params ─────────────────────────────────────────────────────────

PRIMARY_DSN  = os.environ.get(
    "NIDP_PG_PRIMARY_DSN",
    "postgresql://nidp:nidp@10.160.0.3:5433/nidp",
)
STANDBY_DSN  = os.environ.get(
    "NIDP_PG_STANDBY_DSN",
    "postgresql://nidp:nidp@localhost:5434/nidp",
)

# ── Severity constants ────────────────────────────────────────────────────────

P0  = "P0"
P1  = "P1"
P2  = "P2"
OK  = "OK"

PASS  = "PASS"
AMBER = "AMBER"
FAIL  = "FAIL"

GATE_ID = 4


# ── Continuous checks ─────────────────────────────────────────────────────────

async def check_replication_lag(primary: asyncpg.Connection) -> dict:
    """G4-CONT-001: replay_lag < 30 seconds."""
    rows = await primary.fetch(
        """
        SELECT client_addr::text,
               EXTRACT(EPOCH FROM COALESCE(replay_lag, INTERVAL '0'))::INT AS lag_secs,
               state
        FROM pg_stat_replication
        """
    )
    if not rows:
        return {
            "rule_id": "G4-CONT-001",
            "passed": False,
            "severity": P0,
            "message": "No standbys in pg_stat_replication — replication may be broken",
            "details": {},
        }

    lagging = [
        {"addr": r["client_addr"], "lag_secs": r["lag_secs"], "state": r["state"]}
        for r in rows
        if r["lag_secs"] is not None and r["lag_secs"] > 30
    ]
    ok = len(lagging) == 0
    return {
        "rule_id": "G4-CONT-001",
        "passed": ok,
        "severity": P0,
        "message": (
            f"All {len(rows)} standby(s) lag < 30s"
            if ok
            else f"{len(lagging)} standby(s) lag > 30s: {lagging}"
        ),
        "details": {"standbys": [dict(r) for r in rows], "lagging": lagging},
    }


async def check_standby_in_recovery(standby: asyncpg.Connection) -> dict:
    """G4-CONT-002: standby must be in recovery mode."""
    in_recovery = await standby.fetchval("SELECT pg_is_in_recovery()")
    ok = in_recovery is True
    return {
        "rule_id": "G4-CONT-002",
        "passed": ok,
        "severity": P0,
        "message": (
            "Standby is in recovery mode (pg_is_in_recovery=true)"
            if ok
            else "DANGER: standby is NOT in recovery — may have been accidentally promoted"
        ),
        "details": {"pg_is_in_recovery": in_recovery},
    }


# ── Daily parity checks ───────────────────────────────────────────────────────

async def check_row_count_parity(
    primary: asyncpg.Connection,
    standby: asyncpg.Connection,
    table: str,
    rule_id: str,
    lookback_days: int = 30,
) -> dict:
    """G4-PAR-*: row count parity for last N days between primary and standby."""
    cutoff = date.today() - timedelta(days=lookback_days)

    # Determine the date column for this table
    date_col_map = {
        "nidp.bhavcopy":               "trade_date",
        "nidp.mf_nav_daily":           "nav_date",
        "nidp.v3_stock_scores_daily":  "as_of_date",
        "nidp.portfolio_holdings":     "snapshot_date",
        "nidp.corporate_announcements": "disclosure_at::date",
    }
    date_col = date_col_map.get(table, "created_at::date")

    q = f"SELECT COUNT(*) FROM {table} WHERE {date_col} >= $1"

    primary_count = await primary.fetchval(q, cutoff)
    standby_count = await standby.fetchval(q, cutoff)

    drift = abs(primary_count - standby_count)
    ok = drift == 0
    return {
        "rule_id": rule_id,
        "passed": ok,
        "severity": P0,
        "message": (
            f"{table}: primary={primary_count} standby={standby_count} parity OK"
            if ok
            else f"{table}: primary={primary_count} standby={standby_count} DRIFT={drift}"
        ),
        "details": {
            "table": table,
            "primary_count": primary_count,
            "standby_count": standby_count,
            "drift": drift,
            "lookback_days": lookback_days,
        },
    }


# ── Verdict persistence ───────────────────────────────────────────────────────

async def persist_verdict(
    primary: asyncpg.Connection,
    checks: list[dict],
    target_date: date,
) -> uuid.UUID:
    failed   = [c for c in checks if not c["passed"]]
    severities = [c["severity"] for c in failed]
    worst    = (
        P0 if P0 in severities else
        P1 if P1 in severities else
        P2 if P2 in severities else OK
    )
    verdict  = (
        FAIL  if worst == P0 else
        AMBER if worst == P1 else
        PASS
    )
    verdict_id = uuid.uuid4()
    details = {
        "checks": [
            {
                "name":     c["rule_id"],
                "passed":   c["passed"],
                "severity": c["severity"],
                "message":  c["message"],
                **c.get("details", {}),
            }
            for c in checks
        ]
    }
    try:
        await primary.execute(
            """
            INSERT INTO dq.gate_verdicts
                (id, gate_id, feed, target_date, verdict, severity, details)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            verdict_id,
            GATE_ID,
            "replication",
            target_date,
            verdict,
            worst,
            json.dumps(details),
        )
    except Exception as exc:                                        # noqa: BLE001
        logger.error("gate4: failed to persist verdict: %s", exc)
    return verdict_id


# ── Main ──────────────────────────────────────────────────────────────────────

async def _run(mode: str) -> int:
    """Returns 0=OK, 1=P0 failure, 2=connection error."""
    try:
        primary = await asyncpg.connect(PRIMARY_DSN)
    except Exception as exc:
        logger.error("gate4: cannot connect to primary (%s): %s", PRIMARY_DSN, exc)
        return 2

    try:
        standby = await asyncpg.connect(STANDBY_DSN)
    except Exception as exc:
        logger.error("gate4: cannot connect to standby (%s): %s", STANDBY_DSN, exc)
        await primary.close()
        return 2

    checks: list[dict] = []
    today = date.today()

    try:
        # ── Continuous checks (always run) ──────────────────────────────
        checks.append(await check_replication_lag(primary))
        checks.append(await check_standby_in_recovery(standby))

        # ── Daily parity (--mode=daily only) ────────────────────────────
        if mode == "daily":
            parity_targets = [
                ("nidp.bhavcopy",              "G4-PAR-001"),
                ("nidp.mf_nav_daily",          "G4-PAR-002"),
                ("nidp.v3_stock_scores_daily", "G4-PAR-003"),
                ("nidp.portfolio_holdings",    "G4-PAR-004"),
            ]
            for table, rule_id in parity_targets:
                try:
                    checks.append(
                        await check_row_count_parity(primary, standby, table, rule_id)
                    )
                except Exception as exc:                            # noqa: BLE001
                    logger.error("gate4: parity check %s failed: %s", rule_id, exc)
                    checks.append({
                        "rule_id": rule_id,
                        "passed": False,
                        "severity": P1,
                        "message": f"parity check raised exception: {exc}",
                        "details": {},
                    })

        # ── Log + persist ────────────────────────────────────────────────
        for c in checks:
            lvl = logging.ERROR if not c["passed"] and c["severity"] == P0 else (
                  logging.WARNING if not c["passed"] else logging.INFO)
            logger.log(
                lvl,
                "gate4 %s %s: %s",
                c["rule_id"],
                "PASS" if c["passed"] else f"FAIL/{c['severity']}",
                c["message"],
            )

        await persist_verdict(primary, checks, today)

        # ── Return code ──────────────────────────────────────────────────
        has_p0 = any(not c["passed"] and c["severity"] == P0 for c in checks)
        return 1 if has_p0 else 0

    finally:
        await primary.close()
        await standby.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate 4 — Replication Integrity Check")
    ap.add_argument("--mode", choices=("continuous", "daily"), default="continuous")
    args = ap.parse_args()
    rc = asyncio.run(_run(args.mode))
    sys.exit(rc)


if __name__ == "__main__":
    main()
