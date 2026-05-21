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

You author TWO KINDS of rules — pick whichever fits each expectation:

  per_row     — a SQL predicate evaluated per row. Examples below.
                Use when the expectation is about the *contents* of each row.

  aggregate   — a single boolean SQL expression evaluated once per (table, date).
                Typically a parenthesised SELECT. Use when the expectation is
                about the TABLE AS A WHOLE: row count floors, freshness, parity
                against parsed source files, schema consistency over time.

GOOD per_row expectations:
  * "close BETWEEN low AND high"  (intraday consistency)
  * "abs(close-prev_close)/prev_close <= 0.20 OR EXISTS(corp_action on same date)"  (circuit band)
  * "scheme_code ~ '^[0-9]{5,7}$'"  (AMFI scheme codes)
  * "delivery_qty <= traded_qty"  (impossible to deliver more than traded)
  * "EXTRACT(DOW FROM as_of_date) BETWEEN 1 AND 5 OR source = 'manual_override'"

GOOD aggregate expectations (use rule_kind='aggregate'):
  * "(SELECT count(*) >= 2300 FROM nidp.prices_eod WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.prices_eod))"
       — daily NSE bhavcopy must land at least 2,300 stocks
  * "(SELECT max(nav_date) >= CURRENT_DATE - INTERVAL '2 days' FROM nidp.mf_nav_daily)"
       — AMFI NAV must be fresh
  * "(SELECT count(*) FILTER (WHERE close_price > 0) >= 0.99 * count(*) FROM nidp.prices_eod WHERE as_of_date = CURRENT_DATE)"
       — at least 99% of today's rows have a positive close
  * "(SELECT count(*) >= 0.90 * COALESCE((SELECT row_count FROM nidp.parsed_archive_files WHERE ingester='bhavcopy' AND target_date = (SELECT max(as_of_date) FROM nidp.prices_eod) ORDER BY created_at DESC LIMIT 1), 0) FROM nidp.prices_eod WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.prices_eod))"
       — landed rows must be at least 90% of what the parser read from source
         (catches transformation/schema drops between parse and DB write)

BAD expectations (don't propose these):
  * "column X is not null"  — too obvious, already covered
  * "column X is numeric"   — too obvious, already covered
  * Untestable subjective rules

Hard requirements for THIS dataset:
  - Use the catalog_description to understand what the table represents.
  - Use the daily_landed_row_count_history to pick a sensible floor.
  - Use the recent_source_archive (parsed_archive_files.row_count) to author
    a parity rule comparing landed rows to parsed-from-source rows.
  - Treat the existing_active_rules as already-covered ground — propose
    DIFFERENT expectations that add value.
  - Recent failure_history shows what's been tripping — strengthen those
    areas with tighter expectations.

Return STRICT JSON with this shape:
{
  "feed": "<dataset_name>",
  "proposed_expectations": [
    {
      "name": "<snake_case_unique_name>",
      "description": "<1-line plain English>",
      "expression": "<SQL fragment — per-row predicate OR full boolean (SELECT ...) for aggregate>",
      "rule_kind": "per_row|aggregate",
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
- Severity guidelines: CRITICAL = corrupts downstream analytics; ERROR = blocks publish gate; WARN = log only; INFO = telemetry only.
- Prefer compound predicates that reflect Indian-market mechanics (circuit bands, lot sizes, tick rules, settlement cycles).
- Always include AT LEAST ONE aggregate rule of each of these flavours when applicable:
    * row-count floor against latest target_date
    * freshness against CURRENT_DATE - <cadence_lag>
    * parity vs parsed_archive_files.row_count (catches transformation drops)
"""


async def propose_expectations(
    dataset_name: str,
    *,
    feed_metadata: Optional[Dict[str, Any]] = None,
    sample_size: int = 1000,
    failure_history_days: int = 30,
    llm: Optional[LlmClient] = None,
) -> Dict[str, Any]:
    """Generate proposals for one feed; persist to dq.expectation_proposals.

    The prompt context (2026-05-21 enrichment) now includes:
      - Data Catalogue description (source / stores / use) — so the LLM knows
        what the table IS, not just the column types.
      - 30-day landed-row-count history — so it can author p-percentile-based
        floor expressions without us hand-computing them.
      - Latest parsed_archive_files row_count + raw_archive_files SHA-256 —
        so it can author "rows landed >= 0.9 * rows parsed from source" parity
        rules to catch transformation drops.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        column_schema = await _fetch_schema(conn, dataset_name)
        if not column_schema:
            raise ValueError(f"dataset {dataset_name!r} has no schema in information_schema")

        sample_rows = await _stratified_sample(conn, dataset_name, sample_size)
        existing_rules = await conn.fetch(
            """SELECT name, expression, severity, rule_kind
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
        catalog_desc = await _fetch_catalog_description(conn, dataset_name)
        landed_history = await _fetch_landed_history(conn, dataset_name)
        source_archive = await _fetch_recent_archive(conn, dataset_name)

    user_prompt = json.dumps(
        {
            "dataset_name": dataset_name,
            "feed_metadata": feed_metadata or {},
            "catalog_description": catalog_desc,
            "column_schema": column_schema,
            "sample_rows_count": len(sample_rows),
            "sample_rows": sample_rows[:50],          # 50 is plenty for the LLM; full 1000 only used to extract patterns
            "existing_active_rules": [dict(r) for r in existing_rules],
            "recent_failure_history": [dict(r) for r in recent_failures],
            # ── New context from migration 064 enrichment ──
            "daily_landed_row_count_history": landed_history,
            "recent_source_archive": source_archive,
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


async def _fetch_catalog_description(conn, dataset: str) -> Optional[Dict[str, str]]:
    """Best-effort fetch of the catalog blurb (source/stores/use). Returns
    None when the dataset isn't in the catalog table. The catalog text
    lives in code today (catalog.py:_TABLE_DESC) but if a future migration
    moves it into a table we can pull from here without a code change."""
    try:
        row = await conn.fetchrow(
            """SELECT source, stores, use_case FROM dq.dataset_catalog
                WHERE dataset_name = $1""",
            dataset,
        )
        if row:
            return {"source": row["source"], "stores": row["stores"], "use": row["use_case"]}
    except Exception:                                                       # noqa: BLE001
        # Catalog table optional — no fallback yet, just return None.
        return None
    return None


async def _fetch_landed_history(conn, dataset: str, days: int = 30) -> List[Dict[str, Any]]:
    """30-day daily row-count history for the dataset. Drives floor authoring.
    Returns [] if dataset has no obvious date column."""
    sch = await conn.fetchrow(
        """SELECT table_schema, table_name
             FROM information_schema.tables
            WHERE table_name = $1
              AND table_schema IN ('nidp','features','events','analytics','ref','graph','portfolio')
            ORDER BY CASE table_schema WHEN 'nidp' THEN 0 ELSE 1 END LIMIT 1""",
        dataset,
    )
    if not sch:
        return []
    cols = await conn.fetch(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2""",
        sch["table_schema"], sch["table_name"],
    )
    col_names = {c["column_name"] for c in cols}
    date_col = next(
        (c for c in ("as_of_date","target_date","nav_date","snapshot_date",
                     "as_of_month","period_end","filed_at","event_date",
                     "ex_date","published_at")
         if c in col_names),
        None,
    )
    if not date_col:
        return []
    try:
        rows = await conn.fetch(
            f"""SELECT date_trunc('day', "{date_col}")::date AS d, count(*) AS n
                  FROM "{sch['table_schema']}"."{sch['table_name']}"
                 WHERE "{date_col}" > CURRENT_DATE - INTERVAL '{int(days)} days'
                 GROUP BY 1 ORDER BY 1 DESC LIMIT 60"""
        )
    except Exception:                                                      # noqa: BLE001
        return []
    return [{"date": r["d"].isoformat(), "rows": int(r["n"])} for r in rows]


async def _fetch_recent_archive(conn, dataset: str) -> Optional[Dict[str, Any]]:
    """Most recent parsed_archive_files row for the ingester whose name
    matches `dataset`. Lets the LLM author parity rules:
       landed_rows >= 0.90 * parsed_archive_files.row_count
    which catches transformation drops between parse and DB write."""
    try:
        row = await conn.fetchrow(
            """SELECT ingester, target_date::text AS target_date,
                      row_count, file_bytes, file_sha256
                 FROM nidp.parsed_archive_files
                WHERE ingester = $1
                ORDER BY created_at DESC LIMIT 1""",
            dataset,
        )
    except Exception:                                                      # noqa: BLE001
        return None
    return dict(row) if row else None


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
        rule_kind = rule.get("rule_kind", "per_row")
        if rule_kind not in ("per_row", "aggregate"):
            rule_kind = "per_row"
        rule_id = await conn.fetchval(
            """
            INSERT INTO dq.expectations_active (
                dataset_name, name, description, expression, severity,
                source, active, rule_kind, rationale, business_impact,
                promoted_by, promoted_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                'promoted', TRUE, $6, $7, $8,
                $9, NOW()
            )
            ON CONFLICT (dataset_name, name) DO UPDATE SET
                active = TRUE,
                rule_kind = EXCLUDED.rule_kind,
                promoted_by = EXCLUDED.promoted_by,
                promoted_at = NOW()
            RETURNING rule_id
            """,
            prop["dataset_name"],
            rule["name"], rule.get("description"), rule["expression"], rule.get("severity", "ERROR"),
            rule_kind, rule.get("rationale"), rule.get("business_impact"),
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
