"""AI Expectation Author — proposes strict business expectations per feed.

Inputs:
  - dataset_name (a NIDP table)
  - 1000 stratified sample rows
  - column schema
  - last-30d failure history (so AI learns what's actually breaking)
  - feed metadata (asset class, source, expected frequency)

Output: a list of dq.expectation_proposals rows (status='proposed').

Nothing auto-applies — admin/data-steward reviews each proposal in the UI
and clicks "Promote to active" to move it into dq.expectations_active.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from nidp.shared.storage.pg import get_pool
from .llm import LlmClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a senior financial-data auditor authoring strict business
expectations for an Indian capital-markets dataset (NSE/BSE/AMFI/RBI).

Goal: propose 10-30 STRICT business-aware expectations that go beyond
trivial null-checks and type-checks. Examples of GOOD expectations:
  * "close BETWEEN low AND high"  (intraday consistency)
  * "abs(close-prev_close)/prev_close <= 0.20 OR EXISTS(corp_action on same date)"  (circuit band)
  * "scheme_code REGEX '^[0-9]{5,7}$'"  (AMFI scheme codes)
  * "delivery_qty <= traded_qty"  (impossible to deliver more than traded)
  * "as_of_date NOT IN ('Sat','Sun') unless source='manual_override'"
  * "for at least 95% of NIFTY-50 symbols, prior_close on T = close on T-1"

BAD expectations (don't propose these):
  * "column X is not null" — too obvious, already covered
  * "column X is numeric" — too obvious, already covered
  * Untestable subjective rules

Return STRICT JSON with this shape:
{
  "feed": "<dataset_name>",
  "proposed_expectations": [
    {
      "name": "<snake_case_unique_name>",
      "description": "<1-line plain English>",
      "expression": "<SQL fragment evaluatable as a WHERE clause that *passes* when valid>",
      "severity": "INFO|WARN|ERROR|CRITICAL",
      "rationale": "<why this catches real issues — cite the schema or recent failures>",
      "business_impact": "<what breaks downstream if this fails>"
    },
    ...
  ]
}

Hard rules:
- Return ONLY the JSON object, no prose.
- Use SQL that PostgreSQL can evaluate against the actual column names.
- Each expression is a boolean predicate; rows for which it is FALSE are flagged.
- Severity guidelines: CRITICAL = corrupts downstream analytics; ERROR = blocks publish gate; WARN = log only; INFO = telemetry only.
- Do NOT propose null-checks unless they encode a *business* rule (e.g., "isin must be non-null only for active equities").
- Prefer compound predicates that reflect Indian-market mechanics (circuit bands, lot sizes, tick rules, settlement cycles).
"""


async def propose_expectations(
    dataset_name: str,
    *,
    feed_metadata: Optional[Dict[str, Any]] = None,
    sample_size: int = 1000,
    failure_history_days: int = 30,
    llm: Optional[LlmClient] = None,
) -> Dict[str, Any]:
    """Generate proposals for one feed; persist to dq.expectation_proposals."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        column_schema = await _fetch_schema(conn, dataset_name)
        if not column_schema:
            raise ValueError(f"dataset {dataset_name!r} has no schema in information_schema")

        sample_rows = await _stratified_sample(conn, dataset_name, sample_size)
        existing_rules = await conn.fetch(
            """SELECT name, expression, severity
                 FROM dq.expectations_active
                WHERE dataset_name = $1 AND active = TRUE""",
            dataset_name,
        )
        recent_failures = await conn.fetch(
            """SELECT rule_name, severity, count(*) AS n
                 FROM dq.failed_rows fr
                 JOIN dq.validation_runs vr ON vr.run_id = fr.run_id
                WHERE vr.dataset_name = $1
                  AND vr.run_ts >= NOW() - ($2 || ' days')::interval
                GROUP BY rule_name, severity ORDER BY n DESC LIMIT 30""",
            dataset_name, str(failure_history_days),
        )

    user_prompt = json.dumps(
        {
            "dataset_name": dataset_name,
            "feed_metadata": feed_metadata or {},
            "column_schema": column_schema,
            "sample_rows_count": len(sample_rows),
            "sample_rows": sample_rows[:50],          # 50 is plenty for the LLM; full 1000 only used to extract patterns
            "existing_active_rules": [dict(r) for r in existing_rules],
            "recent_failure_history": [dict(r) for r in recent_failures],
        },
        default=str,
    )

    llm = llm or LlmClient()
    out = llm.chat_json(SYSTEM_PROMPT, user_prompt, max_tokens=4000)
    parsed = out["data"]
    proposals = parsed.get("proposed_expectations", [])

    written: list[str] = []
    pool = await get_pool()
    async with pool.acquire() as conn:
        for rule in proposals:
            try:
                pid = await conn.fetchval(
                    """
                    INSERT INTO dq.expectation_proposals (
                        dataset_name, proposed_rule_json, status, llm_model
                    ) VALUES ($1, $2::jsonb, 'proposed', $3)
                    RETURNING proposal_id
                    """,
                    dataset_name, json.dumps(rule), out["model"],
                )
                written.append(str(pid))
            except Exception as e:                  # noqa: BLE001
                logger.warning("failed to persist proposal: %s", e)

    return {
        "dataset": dataset_name,
        "model": out["model"],
        "proposals_count": len(proposals),
        "written_count": len(written),
        "proposal_ids": written,
        "raw_proposals": proposals,
    }


async def _fetch_schema(conn, dataset: str) -> List[Dict[str, str]]:
    """Resolve dataset_name to (schema, table) and return column metadata."""
    row = await conn.fetchrow(
        """SELECT table_schema, table_name
             FROM information_schema.tables
            WHERE table_name = $1
              AND table_schema IN ('nidp','dq','features','events','analytics','ref','graph','portfolio','public')
            ORDER BY CASE table_schema WHEN 'nidp' THEN 0 ELSE 1 END LIMIT 1""",
        dataset,
    )
    if row is None:
        return []
    cols = await conn.fetch(
        """SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position""",
        row["table_schema"], row["table_name"],
    )
    return [{"name": c["column_name"], "type": c["data_type"]} for c in cols]


async def _stratified_sample(conn, dataset: str, n: int) -> List[Dict[str, Any]]:
    """Best-effort sample of N rows; falls back to plain LIMIT if the
    dataset has no obvious time column."""
    row = await conn.fetchrow(
        """SELECT table_schema, table_name
             FROM information_schema.tables
            WHERE table_name = $1
              AND table_schema IN ('nidp','dq','features','events','analytics','ref','graph','portfolio','public')
            ORDER BY CASE table_schema WHEN 'nidp' THEN 0 ELSE 1 END LIMIT 1""",
        dataset,
    )
    if row is None:
        return []
    schema, table = row["table_schema"], row["table_name"]

    # Prefer a TABLESAMPLE for large tables; fall back to LIMIT for small.
    try:
        rows = await conn.fetch(
            f'SELECT * FROM "{schema}"."{table}" TABLESAMPLE SYSTEM(1) LIMIT $1',
            n,
        )
    except Exception:
        try:
            rows = await conn.fetch(
                f'SELECT * FROM "{schema}"."{table}" LIMIT $1',
                n,
            )
        except Exception as e:                  # noqa: BLE001
            logger.warning("sample failed for %s.%s: %s", schema, table, e)
            return []
    return [dict(r) for r in rows]


async def accept_proposal(proposal_id: str, *, reviewer: str, notes: Optional[str] = None) -> Dict[str, Any]:
    """Promote an AI proposal into dq.expectations_active.

    Idempotent on (dataset_name, name) — re-accepting an already-promoted
    rule no-ops gracefully.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        prop = await conn.fetchrow(
            "SELECT * FROM dq.expectation_proposals WHERE proposal_id = $1::uuid",
            proposal_id,
        )
        if prop is None:
            raise ValueError(f"proposal {proposal_id} not found")
        if prop["status"] != "proposed":
            raise ValueError(f"proposal already {prop['status']}")

        rule = json.loads(prop["proposed_rule_json"]) if isinstance(prop["proposed_rule_json"], str) else prop["proposed_rule_json"]
        rule_id = await conn.fetchval(
            """
            INSERT INTO dq.expectations_active (
                dataset_name, name, description, expression, severity,
                source, active, rationale, business_impact,
                promoted_by, promoted_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                'promoted', TRUE, $6, $7,
                $8, NOW()
            )
            ON CONFLICT (dataset_name, name) DO UPDATE SET
                active = TRUE, promoted_by = EXCLUDED.promoted_by, promoted_at = NOW()
            RETURNING rule_id
            """,
            prop["dataset_name"],
            rule["name"], rule.get("description"), rule["expression"], rule.get("severity", "ERROR"),
            rule.get("rationale"), rule.get("business_impact"),
            reviewer,
        )
        await conn.execute(
            """UPDATE dq.expectation_proposals
                  SET status = 'accepted', reviewed_by = $2, reviewed_at = NOW(),
                      review_notes = $3, promoted_rule_id = $4
                WHERE proposal_id = $1::uuid""",
            proposal_id, reviewer, notes, rule_id,
        )
    return {"proposal_id": proposal_id, "rule_id": str(rule_id), "status": "accepted"}


async def reject_proposal(proposal_id: str, *, reviewer: str, reason: str) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE dq.expectation_proposals
                  SET status = 'rejected', reviewed_by = $2, reviewed_at = NOW(),
                      review_notes = $3
                WHERE proposal_id = $1::uuid AND status = 'proposed'""",
            proposal_id, reviewer, reason,
        )
    return {"proposal_id": proposal_id, "status": "rejected"}
