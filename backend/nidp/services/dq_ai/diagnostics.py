"""Smell analyzer — explains *why* a dq run failed.

Inputs:
  - run_id (validation run with status FAIL or PARTIAL)
  - the dataset's recent score trend
  - up to 50 sample failed rows
  - up to 10 passing rows + column schema for context

Output: a row in dq.smell_diagnostics with:
  - 1-line ``smell`` headline
  - ranked root-cause hypotheses with confidence
  - concrete suggested fixes (optionally already-formed expectation expressions)
  - downstream impact estimate
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from nidp.shared.storage.pg import get_pool
from .llm import LlmClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a senior financial-data quality auditor for an Indian capital-markets
data platform (NSE/BSE/AMFI/RBI feeds). You diagnose why a dataset's quality
gate failed today.

Return STRICT JSON with this shape:
{
  "smell": "<single-sentence headline of what's wrong>",
  "root_causes": [
     {"hypothesis": "<short>", "confidence": <0..1>, "evidence": "<which rows/cols support this>"},
     ...
  ],
  "suggested_fixes": [
     {"action": "<short imperative>",
      "kind": "expectation|process|upstream",
      "expression": "<SQL-fragment if kind=expectation, else null>",
      "rationale": "<why this fix>"},
     ...
  ],
  "affected_subset": {"row_count": <int>, "sample_keys": [<up-to-10 identifying values>]},
  "blocking_for_intelligence": <true|false>,
  "estimated_impact": "<one short paragraph>"
}

Hard rules:
- Return ONLY the JSON object, no prose.
- Be specific about column names and value patterns.
- Suggest at most 5 root causes and 5 fixes.
- "blocking_for_intelligence" must be true when the failure could cause
  intelligence_layer / portfolio recommendations to use stale or wrong values
  (e.g., wrong close price, missing NAV).
"""


def _build_user_prompt(
    *,
    dataset_name: str,
    target_date: Optional[date],
    column_schema: List[Dict[str, str]],
    failed_rows: List[Dict[str, Any]],
    passing_rows: List[Dict[str, Any]],
    score_trend: List[Dict[str, Any]],
    failed_rules: List[Dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "dataset_name": dataset_name,
            "target_date": target_date.isoformat() if target_date else None,
            "column_schema": column_schema[:80],
            "failed_rules": failed_rules,
            "score_trend_30d": score_trend,
            "failed_rows_sample": failed_rows[:50],
            "passing_rows_sample": passing_rows[:10],
        },
        default=str,
    )


async def analyze_run(run_id: str, *, llm: Optional[LlmClient] = None) -> Dict[str, Any]:
    """Diagnose a failed validation_run and persist a smell_diagnostics row.

    Idempotency: re-running on the same run_id creates a fresh diagnostic
    row (we keep history rather than upsert; cheap, cumulative).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            """SELECT run_id, dataset_name, target_date, status, run_ts, notes
                 FROM dq.validation_runs WHERE run_id = $1::uuid""",
            run_id,
        )
        if run is None:
            raise ValueError(f"validation_run {run_id} not found")

        dataset = run["dataset_name"]
        target_date = run["target_date"]

        failed_rules = await conn.fetch(
            """SELECT rule_name, severity, count(*) AS failure_count
                 FROM dq.failed_rows WHERE run_id = $1::uuid
                GROUP BY rule_name, severity ORDER BY failure_count DESC LIMIT 20""",
            run_id,
        )

        sample_failed = await conn.fetch(
            """SELECT rule_name, column_name, observed_value,
                      expected_constraint, error_message, source_record_ref
                 FROM dq.failed_rows WHERE run_id = $1::uuid LIMIT 50""",
            run_id,
        )

        score_trend = await conn.fetch(
            """SELECT target_date, overall_score, quality_tier
                 FROM dq.quality_scores
                WHERE dataset_name = $1
                ORDER BY target_date DESC LIMIT 30""",
            dataset,
        )

        column_schema, passing_rows = await _fetch_dataset_context(conn, dataset, target_date)

    user_prompt = _build_user_prompt(
        dataset_name=dataset,
        target_date=target_date,
        column_schema=column_schema,
        failed_rows=[dict(r) for r in sample_failed],
        passing_rows=passing_rows,
        score_trend=[dict(r) for r in score_trend],
        failed_rules=[dict(r) for r in failed_rules],
    )

    llm = llm or LlmClient()
    out = llm.chat_json(SYSTEM_PROMPT, user_prompt, max_tokens=1800)
    parsed = out["data"]

    pool = await get_pool()
    async with pool.acquire() as conn:
        diagnostic_id = await conn.fetchval(
            """
            INSERT INTO dq.smell_diagnostics (
                run_id, dataset_name, target_date,
                smell, root_causes_json, suggested_fixes_json,
                affected_subset_json, sample_failed_rows,
                blocking_for_intelligence, estimated_impact,
                llm_model, llm_prompt_tokens, llm_completion_tokens
            ) VALUES (
                $1::uuid, $2, $3,
                $4, $5::jsonb, $6::jsonb,
                $7::jsonb, $8::jsonb,
                $9, $10,
                $11, $12, $13
            ) RETURNING diagnostic_id
            """,
            run_id, dataset, target_date,
            parsed.get("smell", "(no smell summary returned)"),
            json.dumps(parsed.get("root_causes", [])),
            json.dumps(parsed.get("suggested_fixes", [])),
            json.dumps(parsed.get("affected_subset")),
            json.dumps([dict(r) for r in sample_failed[:20]]),
            bool(parsed.get("blocking_for_intelligence", False)),
            parsed.get("estimated_impact", ""),
            out["model"], out["prompt_tokens"], out["completion_tokens"],
        )

    return {
        "diagnostic_id": str(diagnostic_id),
        "dataset": dataset,
        "smell": parsed.get("smell"),
        "root_causes": parsed.get("root_causes", []),
        "suggested_fixes": parsed.get("suggested_fixes", []),
    }


async def _fetch_dataset_context(conn, dataset: str, target_date) -> tuple[list, list]:
    """Best-effort fetch of column schema + 10 passing rows for the dataset.

    The dataset name is the same as the underlying table name in nidp/dq
    schemas (validated against information_schema for safety — no SQL
    injection, only a fixed-shape query).
    """
    table_lookup = await conn.fetchrow(
        """SELECT table_schema, table_name
             FROM information_schema.tables
            WHERE table_name = $1
              AND table_schema IN ('nidp','dq','features','events','analytics')
            ORDER BY CASE table_schema WHEN 'nidp' THEN 0 ELSE 1 END
            LIMIT 1""",
        dataset,
    )
    if table_lookup is None:
        return [], []

    schema = table_lookup["table_schema"]
    table = table_lookup["table_name"]

    cols = await conn.fetch(
        """SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position""",
        schema, table,
    )
    column_schema = [{"name": c["column_name"], "type": c["data_type"]} for c in cols]

    # Sample 10 rows using LIMIT only (no order, no date filter — defensive
    # against tables without a target_date column).
    try:
        sample = await conn.fetch(f'SELECT * FROM "{schema}"."{table}" LIMIT 10')
        passing = [dict(r) for r in sample]
    except Exception as e:                  # noqa: BLE001
        logger.warning("could not sample %s.%s: %s", schema, table, e)
        passing = []

    return column_schema, passing
