"""nidp.corporate_transactions / corporate_transaction_filings writer (migration 155)."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared.storage.pg import get_pool

from .lifecycle import SOURCE_RANK, UNRESOLVED

logger = logging.getLogger(__name__)

# Bump when a rule in lifecycle.py changes, so rows can be re-derived selectively.
CLASSIFIER_VERSION = "lifecycle-v1"


async def upsert_transactions(txns: list[dict[str, Any]],
                              filings: list[dict[str, Any]],
                              run_id: uuid.UUID) -> dict[str, int]:
    """Write transactions and their filings.

    Stage is only overwritten when the incoming stage_source ranks HIGHER than
    the stored one (none < subject < description < document). That is what makes
    the QIP document pass a backfill: it upserts document-derived stages over
    UNRESOLVED metadata rows and cannot be undone by a later metadata re-run.
    """
    if not txns:
        return {"transactions": 0, "filings": 0}

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.corporate_transactions
                    (transaction_id, nse_symbol, family, txn_ordinal,
                     first_filed_on, last_filed_on, filing_count, stages_seen,
                     unresolved_count, confounded_count, lifecycle_ready,
                     classifier_version, source_run_id)
                VALUES ($1,$2,$3,$4,$5::date,$6::date,$7,$8::text[],$9,$10,$11,$12,$13)
                ON CONFLICT (transaction_id) DO UPDATE SET
                    first_filed_on   = EXCLUDED.first_filed_on,
                    last_filed_on    = EXCLUDED.last_filed_on,
                    filing_count     = EXCLUDED.filing_count,
                    stages_seen      = EXCLUDED.stages_seen,
                    unresolved_count = EXCLUDED.unresolved_count,
                    confounded_count = EXCLUDED.confounded_count,
                    lifecycle_ready  = EXCLUDED.lifecycle_ready,
                    classifier_version = EXCLUDED.classifier_version,
                    source_run_id    = EXCLUDED.source_run_id,
                    updated_at       = NOW()
                """,
                [(t["transaction_id"], t["nse_symbol"], t["family"], t["txn_ordinal"],
                  t["first_filed_on"], t["last_filed_on"], t["filing_count"],
                  t["stages_seen"], t["unresolved_count"], t["confounded_count"],
                  t["lifecycle_ready"], CLASSIFIER_VERSION, run_id) for t in txns])

            # rank is passed alongside so the guard is pure SQL and needs no read.
            await conn.executemany(
                """
                INSERT INTO nidp.corporate_transaction_filings
                    (announcement_id, source, transaction_id, nse_symbol, family,
                     filed_on, stage, stage_source, confounded,
                     classifier_version, source_run_id)
                VALUES ($1,$2,$3,$4,$5,$6::date,$7,$8,$9,$10,$11)
                ON CONFLICT (announcement_id, source) DO UPDATE SET
                    transaction_id = EXCLUDED.transaction_id,
                    filed_on       = EXCLUDED.filed_on,
                    confounded     = EXCLUDED.confounded,
                    source_run_id  = EXCLUDED.source_run_id,
                    updated_at     = NOW(),
                    -- Provenance guard: a weaker source never overwrites a
                    -- stronger one. stage, stage_source and classifier_version
                    -- move TOGETHER -- a row must never claim its stage came
                    -- from a classifier that did not produce it.
                    stage = CASE WHEN $12 > nidp.stage_source_rank(
                                     nidp.corporate_transaction_filings.stage_source)
                            THEN EXCLUDED.stage
                            ELSE nidp.corporate_transaction_filings.stage END,
                    stage_source = CASE WHEN $12 > nidp.stage_source_rank(
                                     nidp.corporate_transaction_filings.stage_source)
                            THEN EXCLUDED.stage_source
                            ELSE nidp.corporate_transaction_filings.stage_source END,
                    classifier_version = CASE WHEN $12 > nidp.stage_source_rank(
                                     nidp.corporate_transaction_filings.stage_source)
                            THEN EXCLUDED.classifier_version
                            ELSE nidp.corporate_transaction_filings.classifier_version END
                """,
                [(f["announcement_id"], f["source"], f["transaction_id"],
                  f["nse_symbol"], f["family"], f["filed_on"], f["stage"],
                  f["stage_source"], f["confounded"], CLASSIFIER_VERSION, run_id,
                  SOURCE_RANK.get(f["stage_source"], 0)) for f in filings])

    logger.info("corporate_transactions: %d transactions, %d filings (%s)",
                len(txns), len(filings), CLASSIFIER_VERSION)
    return {"transactions": len(txns), "filings": len(filings)}


async def readiness_report() -> list[dict[str, Any]]:
    """Per-family counts, with UNRESOLVED reported out loud rather than folded in."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT family,
                   bool_or(lifecycle_ready)                       AS lifecycle_ready,
                   count(*)                                       AS transactions,
                   sum(filing_count)                              AS filings,
                   sum(unresolved_count)                          AS unresolved,
                   sum(confounded_count)                          AS confounded,
                   count(*) FILTER (WHERE filing_count = unresolved_count)
                                                                  AS txns_with_no_readable_stage
            FROM nidp.corporate_transactions GROUP BY family ORDER BY family
            """)
    return [dict(r) for r in rows]
