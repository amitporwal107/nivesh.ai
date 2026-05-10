"""Synthetic Failure Injector (FR-11).

Inject controlled defects to test that the gate catches them under
replay. Each injection is logged in `audit.replay_failures` so the
replay can self-validate detection rate.

Failure types implemented:
  - schema_drift          — drop a required column from the day's rows
  - duplicate_keys        — duplicate primary-key rows
  - null_injection        — overwrite N% of a required column with NULL
  - delayed_arrival       — backdate ingested_at by hours
  - cross_source_mismatch — corrupt one side of a cross-source check

These are NOT applied to the real warehouse — they're applied to a
*shadow* slice that the engine creates for the replay. The replay
target is `audit.replay_shadow_*` tables (unimplemented at MVP) OR the
engine writes the injected-defect row into `audit.replay_failures` so
the gate's expectation runner can flag it.

For MVP, we focus on the audit trail: record the *intent* of injection
and let the replay's expectation runner detect the row via a regular
DQ rule. This unblocks calibration without rewriting the warehouse.
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


FAILURE_TYPES = (
    "schema_drift",
    "duplicate_keys",
    "null_injection",
    "delayed_arrival",
    "cross_source_mismatch",
)


@dataclass
class InjectedFailure:
    failure_id:    str
    target_date:   date
    domain:        str
    failure_type:  str
    target_table:  Optional[str]
    rows_affected: int
    payload:       Dict[str, Any]

    def as_dict(self) -> dict:
        return {
            "failure_id":    self.failure_id,
            "target_date":   self.target_date.isoformat(),
            "domain":        self.domain,
            "failure_type":  self.failure_type,
            "target_table":  self.target_table,
            "rows_affected": self.rows_affected,
            "payload":       self.payload,
        }


def plan_failures(
    target_date: date,
    domain: str,
    *,
    seed: Optional[int] = None,
    rate: float = 0.10,
) -> List[InjectedFailure]:
    """Decide which (deterministic) failures to inject for a date+domain.

    `rate` controls how often each defect category fires (e.g. 0.10 →
    each of the 5 categories has a 10% chance per date). Use a fixed
    `seed` for reproducible runs.
    """
    rnd = random.Random(seed if seed is not None else hash((target_date, domain)))
    out: List[InjectedFailure] = []

    table_for_domain = {
        "mf":     "nidp.mf_nav_daily",
        "equity": "nidp.prices_eod",
    }
    table = table_for_domain.get(domain) or "nidp.prices_eod"

    for ftype in FAILURE_TYPES:
        if rnd.random() >= rate:
            continue
        rows_affected = max(1, int(rnd.gauss(50, 20)))
        out.append(InjectedFailure(
            failure_id=str(uuid.uuid4()),
            target_date=target_date,
            domain=domain,
            failure_type=ftype,
            target_table=table,
            rows_affected=rows_affected,
            payload={"seed": seed, "rate": rate, "ftype": ftype},
        ))

    return out


async def persist_failure(
    conn: asyncpg.Connection,
    replay_id: str,
    f: InjectedFailure,
    *,
    detected: Optional[bool] = None,
    detected_by: Optional[str] = None,
) -> None:
    """Write the injection record into audit.replay_failures."""
    await conn.execute(
        """
        INSERT INTO audit.replay_failures
            (failure_id, replay_id, target_date, domain,
             failure_type, target_table, rows_affected,
             detected, detected_by, payload_json)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
        ON CONFLICT (failure_id) DO NOTHING
        """,
        f.failure_id, replay_id, f.target_date, f.domain,
        f.failure_type, f.target_table, f.rows_affected,
        detected, detected_by, json.dumps(f.payload),
    )


async def update_detection(
    conn: asyncpg.Connection,
    failure_id: str,
    detected: bool,
    detected_by: str,
) -> None:
    await conn.execute(
        """
        UPDATE audit.replay_failures
           SET detected     = $2,
               detected_by  = $3
         WHERE failure_id   = $1::uuid
        """,
        failure_id, detected, detected_by,
    )
