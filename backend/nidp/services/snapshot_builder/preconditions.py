"""Pre-build gate: refuse to build the snapshot if any contributing
source for `target_date` has a BLOCK validation finding, or if a
hard requirement (bhavcopy, index_close) is missing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class PreflightResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    blocking_findings: list[dict] = field(default_factory=list)

    def add(self, reason: str) -> None:
        self.ok = False
        self.reasons.append(reason)


# Domains that MUST exist for a meaningful snapshot. Other domains are
# best-effort (FII/DII may not land on certain holidays, RBI on bank
# holidays, etc.).
HARD_REQUIRED = ("prices_eod",)
SOFT_RECOMMENDED = ("delivery_data", "index_eod", "fii_dii_flows", "rbi_yields")


async def preflight(conn: asyncpg.Connection, target_date: date) -> PreflightResult:
    res = PreflightResult(ok=True)

    # Check for blocking findings on any source-run that contributed
    # to this date (joins via job_log → contributing tables).
    blocks = await conn.fetch(
        """
        SELECT vf.ingester, vf.rule_name, vf.message, vf.severity
          FROM nidp.validation_findings vf
         WHERE vf.target_date = $1::date
           AND vf.failure_class = 'BLOCK'
        """,
        target_date,
    )
    if blocks:
        for b in blocks:
            res.blocking_findings.append(dict(b))
            res.add(
                f"BLOCK finding {b['ingester']}/{b['rule_name']}: {b['message']}"
            )

    # Hard-required: prices_eod has at least N rows for the date.
    bhav_count = await conn.fetchval(
        """
        SELECT count(*) FROM nidp.prices_eod
         WHERE as_of_date = $1::date
           AND series IN ('EQ','BE','BZ','SM')
        """,
        target_date,
    )
    if (bhav_count or 0) < 1500:
        res.add(f"prices_eod has only {bhav_count} rows for {target_date} (need ≥ 1500)")

    # Soft-recommended: log warnings (don't block) when missing.
    for table in SOFT_RECOMMENDED:
        n = await conn.fetchval(
            f"SELECT count(*) FROM nidp.{table} WHERE as_of_date = $1::date",
            target_date,
        )
        if not n:
            logger.warning(
                "snapshot %s: soft-recommended domain %s has 0 rows; "
                "carry-forward will apply",
                target_date, table,
            )

    return res
