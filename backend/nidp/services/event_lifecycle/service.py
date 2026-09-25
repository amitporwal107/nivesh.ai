"""Build corporate transactions from resolved announcements (migration 155).

    python -m nidp.services.event_lifecycle --build
    python -m nidp.services.event_lifecycle --report

Reads nidp.v_announcement_security (migration 154) joined back to
corporate_announcements for `description`, classifies each filing, groups
filings into transactions, and writes both tables.

Both families are persisted. Only BUYBACK is marked lifecycle_ready — QIP's
stages are not readable from metadata (36% vs 82%) and arrive later from parsed
attachments. Persisting it now as honestly incomplete is better than holding it
back: the rows are real, and the readiness flag keeps them out of cohorts.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import date
from typing import Any

from nidp.shared.storage.pg import get_pool

from .lifecycle import (UNRESOLVED, classify_family, group_transactions,
                        is_confounded, is_lifecycle_ready, resolve_stage)
from .writer import readiness_report, upsert_transactions

logger = logging.getLogger(__name__)

# Only filings that already resolve to an NSE symbol are candidates: a
# transaction with no price series cannot enter a study, and 154 already tells
# BSE-only companies apart from unresolved ones.
#
# The LIKE list is a COARSE prefilter, not the classifier. classify_family() in
# lifecycle.py still decides — it is what rejects debt buybacks, Reg-32 deviation
# statements and warrant conversions. Without this the query scans all 219,538
# announcements through view 154's LATERAL and times out; with it, ~450 rows are
# loaded and Python classifies those. Any keyword added here must be WIDER than
# the classifier, never narrower, or filings would be dropped before it sees them.
_CANDIDATE_LIKE = (
    "lower(ca.subject) LIKE '%buyback%' OR lower(ca.subject) LIKE '%buy-back%' "
    "OR lower(ca.subject) LIKE '%qualified institution%' "
    "OR lower(ca.subject) LIKE '%preferential%'"
)
_SQL = f"""
SELECT v.announcement_id, v.source, v.nse_symbol, v.filed_at::date AS filed_on,
       coalesce(v.subject, '')                AS subject,
       coalesce(left(ca.description, 600), '') AS description
FROM nidp.corporate_announcements ca
JOIN nidp.v_announcement_security v
  ON v.announcement_id = ca.announcement_id AND v.source = ca.source
WHERE ({_CANDIDATE_LIKE})
  AND v.nse_symbol IS NOT NULL
"""


async def _load() -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return [dict(r) for r in await conn.fetch(_SQL)]


def classify_all(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filings that belong to a Phase-1 family, with stage and provenance."""
    out: list[dict[str, Any]] = []
    for r in rows:
        text = f"{r['subject']} {r['description']}"
        family = classify_family(r["subject"]) or classify_family(text)
        if not family:
            continue
        res = resolve_stage(r["subject"], r["description"])
        out.append({**r, "family": family, "stage": res.stage,
                    "stage_source": res.source, "confounded": is_confounded(text)})
    return out


def build(filings: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Group filings into transactions and summarise each."""
    grouped = group_transactions(filings)
    for f in grouped:
        f["transaction_id"] = f"{f['nse_symbol']}:{f['family']}:{f['txn_ordinal']}"

    by_txn: dict[str, list[dict]] = defaultdict(list)
    for f in grouped:
        by_txn[f["transaction_id"]].append(f)

    txns = []
    for tid, fs in by_txn.items():
        dates = [f["filed_on"] for f in fs]
        stages = sorted({f["stage"] for f in fs if f["stage"] != UNRESOLVED})
        txns.append({
            "transaction_id": tid,
            "nse_symbol": fs[0]["nse_symbol"],
            "family": fs[0]["family"],
            "txn_ordinal": fs[0]["txn_ordinal"],
            "first_filed_on": min(dates),
            "last_filed_on": max(dates),
            "filing_count": len(fs),
            "stages_seen": stages,
            "unresolved_count": sum(1 for f in fs if f["stage"] == UNRESOLVED),
            "confounded_count": sum(1 for f in fs if f["confounded"]),
            "lifecycle_ready": is_lifecycle_ready(fs[0]["family"]),
        })
    return txns, grouped


async def run(report_only: bool = False) -> dict[str, Any]:
    if report_only:
        return {"readiness": await readiness_report()}
    rows = await _load()
    filings = classify_all(rows)
    txns, grouped = build(filings)
    written = await upsert_transactions(txns, grouped, uuid.uuid4())
    unresolved = sum(t["unresolved_count"] for t in txns)
    total = sum(t["filing_count"] for t in txns)
    return {
        "candidates_scanned": len(rows),
        **written,
        "filings_unresolved_stage": unresolved,
        "filings_staged": total - unresolved,
        "confounded": sum(t["confounded_count"] for t in txns),
        "readiness": await readiness_report(),
    }
