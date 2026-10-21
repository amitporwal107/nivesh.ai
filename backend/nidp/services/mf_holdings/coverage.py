"""Per-(amc, month) ingestion ledger for nidp.mf_holdings_monthly.

The daily service used to record only a month-level job_log row ("missing=10/14"), which
cannot say WHICH AMC-month is absent. That matters twice over:

  * nothing could heal a gap — a month skipped because the third-party index had not yet
    listed it stayed missing forever, and
  * the delta layer could not tell "this scheme sold out" from "we never fetched this AMC",
    which is the difference between a real finding and a fabricated one (§26.4, §26.8).

This module is the write/read side of that ledger. See migration 159.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Optional

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# Statuses worth re-attempting on a catch-up pass. EMPTY is the common one: AdvisorKhoj (and
# the AMC sites) lag the SEBI M+10 disclosure deadline, so a month fetched too early yields no
# file. That is a timing miss, not a verdict, so it stays retryable.
RETRYABLE = ("EMPTY", "ERROR")


_UPSERT_SQL = """
INSERT INTO nidp.mf_holdings_coverage
    (amc_id, as_of_month, status, rows_written, schemes_written, source_url,
     attempts, first_attempt_at, last_attempt_at, last_error)
VALUES ($1, $2, $3, $4, $5, $6, 1, now(), now(), $7)
ON CONFLICT (amc_id, as_of_month) DO UPDATE SET
    -- Status describes what we HOLD, not how the last attempt went. A re-run while the source is
    -- down must not downgrade OK to EMPTY: the rows from the earlier successful run are still in
    -- mf_holdings_monthly, so flipping the ledger would make it disagree with the data and would
    -- make the catch-up pass think a month it already has is missing. Seen live on 2026-10-22,
    -- when sbimf.com returned 503 for its whole host during a --all re-run of a month we held.
    -- The failed attempt is still visible via attempts/last_attempt_at/last_error.
    status          = CASE WHEN nidp.mf_holdings_coverage.status = 'OK' AND EXCLUDED.status <> 'OK'
                          THEN 'OK' ELSE EXCLUDED.status END,
    rows_written    = CASE WHEN nidp.mf_holdings_coverage.status = 'OK' AND EXCLUDED.status <> 'OK'
                          THEN nidp.mf_holdings_coverage.rows_written ELSE EXCLUDED.rows_written END,
    schemes_written = CASE WHEN nidp.mf_holdings_coverage.status = 'OK' AND EXCLUDED.status <> 'OK'
                          THEN nidp.mf_holdings_coverage.schemes_written ELSE EXCLUDED.schemes_written END,
    -- Keep the last URL we actually parsed: on a retry that fails, the previously good URL is
    -- more useful to an operator than a NULL.
    source_url      = coalesce(EXCLUDED.source_url, nidp.mf_holdings_coverage.source_url),
    attempts        = nidp.mf_holdings_coverage.attempts + 1,
    last_attempt_at = now(),
    last_error      = EXCLUDED.last_error
"""

# Kept deliberately: `status` answers "do we have this AMC-month?", and `last_error` answers
# "did the most recent attempt work?". Conflating the two is what made the original month-level
# job_log row useless for healing gaps.


async def record(
    amc_id: str,
    as_of_month: date,
    status: str,
    *,
    rows_written: int = 0,
    schemes_written: int = 0,
    source_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Write (or bump) the ledger row for one AMC-month."""
    if status not in ("OK", "EMPTY", "ERROR"):
        raise ValueError(f"unknown coverage status: {status!r}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            _UPSERT_SQL, amc_id, as_of_month, status,
            rows_written, schemes_written, source_url,
            (error or None) if status != "OK" else None,
        )


async def done_pairs(amcs: Iterable[str], months: Iterable[date]) -> set[tuple[str, date]]:
    """(amc, month) pairs already ingested OK — what a catch-up pass may skip.

    Only status='OK' counts. EMPTY/ERROR are explicitly not "done": re-attempting them is the
    whole point of the catch-up pass.
    """
    amcs, months = list(amcs), list(months)
    if not amcs or not months:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT amc_id, as_of_month FROM nidp.mf_holdings_coverage
             WHERE status = 'OK' AND amc_id = ANY($1::text[]) AND as_of_month = ANY($2::date[])
            """,
            amcs, months,
        )
    return {(r["amc_id"], r["as_of_month"]) for r in rows}


async def backfill_from_holdings() -> int:
    """Seed the ledger from holdings rows that predate it.

    mf_holdings_monthly already held a month of rows before this table existed. Without this,
    a catch-up pass would re-fetch AMC-months we demonstrably have, and the delta layer's
    coverage checks would read as gaps. The AMC is derived from the `source` tag's prefix
    (e.g. 'ICICI_PRU_DISCLOSURE_ADVISORKHOJ' -> 'icici_pru'), which is how the adapters build
    it; rows whose prefix matches no known adapter key are left alone rather than guessed at.

    Returns the number of ledger rows seeded or repaired. Safe to re-run: a row that already says
    OK is left alone; one that says EMPTY/ERROR while holdings exist is realigned to OK.
    """
    from nidp.shared.config import MF_AMC_TOP10, MF_AMC_TIER2, MF_AMC_TIER3

    known = sorted((*MF_AMC_TOP10, *MF_AMC_TIER2, *MF_AMC_TIER3), key=len, reverse=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT source, as_of_month, count(*) AS rows_written,
                   count(DISTINCT scheme_code) AS schemes_written,
                   min(source_url) AS source_url
              FROM nidp.mf_holdings_monthly
             GROUP BY source, as_of_month
            """
        )

    seeded = 0
    for r in rows:
        src = (r["source"] or "").lower()
        amc = next((a for a in known if src.startswith(a + "_")), None)
        if amc is None:
            logger.info("coverage seed: source=%r matches no adapter key — skipped", r["source"])
            continue
        async with pool.acquire() as conn:
            done = await conn.execute(
                """
                INSERT INTO nidp.mf_holdings_coverage
                    (amc_id, as_of_month, status, rows_written, schemes_written, source_url)
                VALUES ($1, $2, 'OK', $3, $4, $5)
                -- Also REPAIRS a row that says EMPTY/ERROR while the holdings are demonstrably
                -- present. That happens when a re-run hits a source outage (sbimf.com served 503
                -- for its whole host on 2026-10-22 during a --all pass over a month we held).
                -- The holdings table is the ground truth for "do we have it"; this realigns the
                -- ledger to it so the catch-up pass does not keep chasing a month already in hand.
                ON CONFLICT (amc_id, as_of_month) DO UPDATE SET
                    status          = 'OK',
                    rows_written    = EXCLUDED.rows_written,
                    schemes_written = EXCLUDED.schemes_written,
                    source_url      = coalesce(EXCLUDED.source_url,
                                               nidp.mf_holdings_coverage.source_url)
                WHERE nidp.mf_holdings_coverage.status <> 'OK'
                """,
                amc, r["as_of_month"], r["rows_written"], r["schemes_written"], r["source_url"],
            )
        if done.endswith("1"):
            seeded += 1
    logger.info("coverage seed: %d ledger row(s) created or repaired from existing holdings", seeded)
    return seeded
