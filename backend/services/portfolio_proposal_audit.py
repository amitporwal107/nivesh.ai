"""Audit persistence for the copilot Portfolio Builder (PRD D4, plan Step 7).

Shapes the record from services.selection.build_audit_record() into the
portfolio_proposal_audit table (migration 023) and writes it to the main-app
Postgres. The jsonb columns (inputs/weights/picks/rejected) are stored as
json.dumps strings so asyncpg passes them straight to JSONB.

Two surfaces:
  - to_row()  : PURE — record dict -> column dict. Unit-verifiable here.
  - persist() : async DB write. Defensive — on a None pool or ANY error it
                logs and returns None, never raising into the builder. A failed
                audit write must not break proposal generation.

Honesty contract (CONTEXT.md §1): this env has NO DB and NO network, so the
live INSERT in persist() is UNVERIFIED — only to_row() (pure) and the
None-pool / fake-pool degrade paths are unit-tested. persist() never
fabricates a proposal_id for a write that did not happen: it returns the id
only after the INSERT executed (or None on any failure).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from services import pg_client

logger = logging.getLogger(__name__)

# Fields build_audit_record() must supply for a row to be persistable.
_REQUIRED_FIELDS = ("inputs", "scoring_config_version")


def to_row(
    record: Dict[str, Any],
    *,
    proposal_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Shape a build_audit_record() output into portfolio_proposal_audit columns.

    The jsonb columns are json.dumps'd so the DB driver stores them as JSONB.
    Raises ValueError if the record is missing a required field (inputs /
    scoring_config_version) — we never persist a half-formed audit row that
    would silently lose the proposal's provenance.
    """
    if not isinstance(record, dict):
        raise ValueError(f"audit record must be a dict, got {type(record).__name__}")
    missing = [f for f in _REQUIRED_FIELDS if record.get(f) is None]
    if missing:
        raise ValueError(f"audit record missing required field(s): {', '.join(missing)}")

    return {
        "proposal_id": proposal_id,
        "user_id": user_id,
        "inputs": json.dumps(record.get("inputs")),
        "weights": json.dumps(record.get("weights")),
        "scoring_config_version": record.get("scoring_config_version"),
        "picks": json.dumps(record.get("picks")),
        "rejected": json.dumps(record.get("rejected")),
    }


async def persist(
    record: Dict[str, Any],
    *,
    proposal_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """Insert an audit record; return the proposal_id (str) on success, else None.

    Generates a uuid4 proposal_id when not supplied. On a None pool (DB not
    configured) or ANY error (bad record, DB failure) this logs and returns
    None — it never raises into the proposal builder. DB path is UNVERIFIED in
    this env (no DB / no network).
    """
    pid = proposal_id or str(uuid.uuid4())
    try:
        row = to_row(record, proposal_id=pid, user_id=user_id)
    except ValueError as e:
        logger.warning("portfolio_proposal_audit: record not persistable: %s", e)
        return None

    pool = await pg_client.get_pool()
    if pool is None:
        logger.warning("portfolio_proposal_audit: no DB pool — audit not persisted (proposal_id=%s)", pid)
        return None

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO portfolio_proposal_audit
                    (proposal_id, user_id, inputs, weights,
                     scoring_config_version, picks, rejected)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6::jsonb, $7::jsonb)
                ON CONFLICT (proposal_id) DO NOTHING
                """,
                row["proposal_id"], row["user_id"], row["inputs"], row["weights"],
                row["scoring_config_version"], row["picks"], row["rejected"],
            )
        return pid
    except Exception as e:  # noqa: BLE001 — audit write must never break the builder
        logger.warning("portfolio_proposal_audit: persist failed (proposal_id=%s): %s", pid, e)
        return None
