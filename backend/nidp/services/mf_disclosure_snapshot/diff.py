"""Snapshot diff → mf_scheme_events.

Two-table scan: for each scheme, find the latest snapshot strictly
before today's snapshot_date and compare load-bearing fields. Each
changed field becomes one mf_scheme_events row.

Field → event_type:
    ter_pct / ter_pct_direct   → 'ter_change'
    risk_o_meter               → 'risk_change'
    primary_manager            → 'manager_change'
    secondary_manager          → 'manager_change'

Idempotent: events are deduped by (scheme_code, event_type, event_date,
new_value) so re-running on the same snapshot pair produces no
duplicates.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


_LATEST_PRIOR_SQL = """
WITH this_snap AS (
  SELECT scheme_code, snapshot_date, ter_pct, ter_pct_direct,
         risk_o_meter, primary_manager, secondary_manager
    FROM nidp.mf_scheme_disclosure_snapshot
   WHERE snapshot_date = $1::date
),
prior_snap AS (
  SELECT DISTINCT ON (scheme_code) scheme_code, snapshot_date,
         ter_pct, ter_pct_direct, risk_o_meter,
         primary_manager, secondary_manager
    FROM nidp.mf_scheme_disclosure_snapshot
   WHERE snapshot_date < $1::date
   ORDER BY scheme_code, snapshot_date DESC
)
SELECT t.scheme_code,
       t.ter_pct          AS new_ter,         p.ter_pct          AS old_ter,
       t.ter_pct_direct   AS new_ter_d,       p.ter_pct_direct   AS old_ter_d,
       t.risk_o_meter     AS new_risk,        p.risk_o_meter     AS old_risk,
       t.primary_manager  AS new_pm,          p.primary_manager  AS old_pm,
       t.secondary_manager AS new_sm,         p.secondary_manager AS old_sm
  FROM this_snap t
  JOIN prior_snap p USING (scheme_code)
"""

_INSERT_EVENT_SQL = """
INSERT INTO nidp.mf_scheme_events
    (scheme_code, event_type, event_date, old_value, new_value,
     source, source_ref, source_run_id)
SELECT $1, $2, $3::date, $4::jsonb, $5::jsonb, 'snapshot_diff', $6, $7
 WHERE NOT EXISTS (
    SELECT 1 FROM nidp.mf_scheme_events
     WHERE scheme_code = $1
       AND event_type  = $2
       AND event_date  = $3::date
       AND new_value   = $5::jsonb
 )
"""


def _diff_one(row: dict) -> list[tuple[str, dict, dict]]:
    """Return list of (event_type, old_value, new_value) changes."""
    out: list[tuple[str, dict, dict]] = []

    if row["new_ter"] != row["old_ter"] and (row["new_ter"] is not None or row["old_ter"] is not None):
        out.append(("ter_change",
                    {"plan": "regular", "ter_pct": float(row["old_ter"]) if row["old_ter"] is not None else None},
                    {"plan": "regular", "ter_pct": float(row["new_ter"]) if row["new_ter"] is not None else None}))
    if row["new_ter_d"] != row["old_ter_d"] and (row["new_ter_d"] is not None or row["old_ter_d"] is not None):
        out.append(("ter_change",
                    {"plan": "direct", "ter_pct": float(row["old_ter_d"]) if row["old_ter_d"] is not None else None},
                    {"plan": "direct", "ter_pct": float(row["new_ter_d"]) if row["new_ter_d"] is not None else None}))
    if row["new_risk"] != row["old_risk"] and (row["new_risk"] is not None or row["old_risk"] is not None):
        out.append(("risk_change",
                    {"risk_o_meter": row["old_risk"]},
                    {"risk_o_meter": row["new_risk"]}))
    if row["new_pm"] != row["old_pm"] and (row["new_pm"] is not None or row["old_pm"] is not None):
        out.append(("manager_change",
                    {"role": "primary", "name": row["old_pm"]},
                    {"role": "primary", "name": row["new_pm"]}))
    if row["new_sm"] != row["old_sm"] and (row["new_sm"] is not None or row["old_sm"] is not None):
        out.append(("manager_change",
                    {"role": "secondary", "name": row["old_sm"]},
                    {"role": "secondary", "name": row["new_sm"]}))
    return out


async def emit_events_from_snapshot(
    snapshot_date: date, run_id: uuid.UUID,
) -> int:
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(_LATEST_PRIOR_SQL, snapshot_date)
        for r in rows:
            for event_type, old_val, new_val in _diff_one(dict(r)):
                result = await conn.execute(
                    _INSERT_EVENT_SQL,
                    r["scheme_code"], event_type, snapshot_date,
                    json.dumps(old_val), json.dumps(new_val),
                    snapshot_date.isoformat(), run_id,
                )
                # asyncpg execute returns 'INSERT 0 N'
                if result.endswith(" 1"):
                    inserted += 1
    logger.info("mf_disclosure_snapshot diff: %d events emitted", inserted)
    return inserted
