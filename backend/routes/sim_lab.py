"""Simulation Lab — the Research page's frozen consecutive-session simulation runs
(docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md, SIM_DIAG_D1_D4_RESULTS.md).

    GET /api/sim-lab/run                          → the run, its frozen inputs, sessions, scorecard, data quality,
                                                    reconciliation and the RC-1 counts
    GET /api/sim-lab/matrix?scope=year|replay     → that scope's matrix block (runs A–H, secondary rows S*,
                                                    portfolio variants, the random control, the rank bands)
    GET /api/sim-lab/trades?config=A&scope=replay → one run's trade rows
    GET /api/sim-lab/candidates?date=YYYY-MM-DD   → one replay session's candidate ledger

Read-only research, never signals. Everything comes from the committed snapshot (services/sim_lab.py) — no DB, no
network, no other file — so every number is the frozen, published one. Only accounts on the sim_lab allowlist get
past the gate (403 feature_not_enabled otherwise, admins included). A missing or malformed snapshot is
503 snapshot_unavailable, never a partial page.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from feature_gate import require_feature
from services.sim_lab import (
    candidates_view, load_snapshot, matrix_view, replay_dates, run_view, trade_configs, trades_view,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sim-lab", tags=["sim_lab"])
FLAG = "sim_lab"
Scope = Literal["year", "replay"]


def _snapshot() -> dict:
    data = load_snapshot()
    if data is None:
        raise HTTPException(status_code=503, detail="snapshot_unavailable")
    return data


@router.get("/run")
async def run(user: dict = Depends(require_feature(FLAG))):
    """What was run and on what: the frozen input hashes, the sealed-block statement, the cost model, the sessions,
    the scorecard, the per-session data-quality report and the reconciliation against labels.py."""
    return {"data": run_view(_snapshot())}


@router.get("/matrix")
async def matrix(scope: Scope = "year", user: dict = Depends(require_feature(FLAG))):
    """One scope's comparison matrix. The runs are descriptive, on development data that has already been used: no
    configuration here is a candidate strategy (pre-registration §1)."""
    return {"data": matrix_view(_snapshot(), scope)}


@router.get("/trades")
async def trades(config: str = Query(..., min_length=1, max_length=8),
                 scope: Scope = "replay", user: dict = Depends(require_feature(FLAG))):
    """One configuration's trade rows. `config` is checked against the snapshot's own keys — an unknown one is 422,
    not an empty table that could read as "this run had no trades"."""
    data = _snapshot()
    if config not in data["trades"]:
        raise HTTPException(status_code=422, detail=f"config: not in this snapshot (have {', '.join(trade_configs(data))})")
    return {"data": trades_view(data, config, scope)}


@router.get("/candidates")
async def candidates(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
                     user: dict = Depends(require_feature(FLAG))):
    """One replay session's candidate ledger: every candidate with its rank, score, status and reason. A date outside
    the replay window is 422 — the ledger is only kept for those sessions."""
    data = _snapshot()
    if date not in replay_dates(data):
        raise HTTPException(status_code=422, detail="date: not a replay session in this snapshot")
    return {"data": candidates_view(data, date)}
