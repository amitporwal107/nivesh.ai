"""Simulation Lab — the committed snapshot behind Research → Simulation Lab (routes/sim_lab.py).

Every number the page shows comes from `sim_lab_snapshot.json`, generated from the frozen consecutive-session
simulation run (docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md, §2 frozen inputs). Nothing is computed
here and nothing else is read: this module opens that one file, checks its shape, and hands it over. A missing,
unreadable or wrong-schema snapshot returns None so the routes answer 503 instead of showing partial numbers — the
same rule as services/move_odds_diagnostics.py.

Two conventions worth knowing:
  · keys beginning with "_" are generator/editor notes and are stripped from the payload (as in move_odds);
  · a snapshot may carry `"fixture": true`. That is a development placeholder, not a run, and the flag is passed
    through so the page can say so in a banner. The generated snapshot does not set it.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SNAPSHOT = Path(__file__).with_name("sim_lab_snapshot.json")
SCHEMA = "sim-lab-1"
SCOPES = ("year", "replay")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SHA256 = re.compile(r"[0-9a-f]{64}")
RUN_KEYS = ("id", "code_commit", "prereg", "cost_model", "capital_inr", "prediction_commit",
            "dataset_sha256", "oof_sha256", "picks_sha256", "block", "sealed_note")
MATRIX_KEYS = ("runs", "secondary", "portfolio_variants", "random_control", "rank_bands")

# One parsed copy per (path, mtime, size): the snapshot carries every trade and candidate row, and re-parsing it on
# every request would be wasteful. A regenerated file changes mtime/size, so the next request re-reads it.
_cache: dict = {"key": None, "data": None}


def _valid(d: dict) -> bool:
    """The shape the routes rely on. Anything else is a 503, never a partially rendered page."""
    if d.get("schema") != SCHEMA:
        return False
    if not SHA256.fullmatch(str(d.get("source_sha256", ""))):
        return False
    if not isinstance(d.get("generated_at"), str) or not d["generated_at"]:
        return False
    if "fixture" in d and not isinstance(d["fixture"], bool):
        return False

    run = d.get("run")
    if not isinstance(run, dict) or not all(k in run for k in RUN_KEYS):
        return False

    sessions = d.get("sessions")
    if not isinstance(sessions, dict) or not all(isinstance(sessions.get(s), dict) for s in SCOPES):
        return False
    if not all(isinstance(sessions[s].get("count"), int) for s in SCOPES):
        return False
    if not all(isinstance(sessions["year"].get(k), str) for k in ("first", "last")):
        return False
    dates = sessions["replay"].get("dates")
    if not isinstance(dates, list) or not all(isinstance(x, str) and DATE.fullmatch(x) for x in dates):
        return False
    if len(dates) != sessions["replay"]["count"]:
        return False

    matrix = d.get("matrix")
    if not isinstance(matrix, dict):
        return False
    for scope in SCOPES:
        block = matrix.get(scope)
        if not isinstance(block, dict) or not all(k in block for k in MATRIX_KEYS):
            return False
        runs = block["runs"]
        if not isinstance(runs, dict) or not runs or not all(isinstance(v, dict) for v in runs.values()):
            return False
        if not isinstance(block["secondary"], dict) or not isinstance(block["portfolio_variants"], list):
            return False
        if not isinstance(block["random_control"], dict) or not isinstance(block["rank_bands"], dict):
            return False

    rec = d.get("reconciliation")
    if not isinstance(rec, dict) or not isinstance(rec.get("summary"), dict):
        return False
    if not isinstance(rec.get("classes"), list) or not all(isinstance(c, dict) for c in rec["classes"]):
        return False

    dq = d.get("data_quality")
    if not isinstance(dq, dict) or not all(isinstance(dq.get(s), dict) for s in SCOPES):
        return False
    if not isinstance(dq.get("sessions"), list):
        return False
    if not all(isinstance(s, dict) and isinstance(s.get("date"), str) for s in dq["sessions"]):
        return False

    scorecard = d.get("scorecard")
    if not isinstance(scorecard, dict) or not all(isinstance(scorecard.get(s), dict) for s in SCOPES):
        return False

    rc1 = d.get("rc1")
    if not isinstance(rc1, dict) or not all(isinstance(rc1.get(s), dict) for s in SCOPES):
        return False

    trades = d.get("trades")
    if not isinstance(trades, dict) or not trades:
        return False
    for rows in trades.values():
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            return False

    candidates = d.get("candidates")
    if not isinstance(candidates, list) or not all(isinstance(r, dict) for r in candidates):
        return False

    notes = d.get("notes")
    if not isinstance(notes, dict) or not isinstance(notes.get("internal_only"), bool):
        return False
    return True


def load_snapshot(path: Path = SNAPSHOT) -> Optional[dict]:
    """The validated snapshot, or None (→ the routes answer 503 snapshot_unavailable)."""
    try:
        stat = path.stat()
    except OSError as e:
        logger.warning("sim-lab snapshot missing (%s): %s", path, e)
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _cache["key"] == key:
        return _cache["data"]
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        logger.warning("sim-lab snapshot unreadable (%s): %s", path, e)
        return None
    if not isinstance(d, dict) or not _valid(d):
        logger.warning("sim-lab snapshot failed validation (%s)", path)
        return None
    data = {k: v for k, v in d.items() if not k.startswith("_")}
    _cache["key"], _cache["data"] = key, data
    return data


def _head(d: dict) -> dict:
    """The provenance every payload carries, so a screen can never mix two runs or miss the fixture flag."""
    return {"schema": d["schema"], "generated_at": d["generated_at"], "source_sha256": d["source_sha256"],
            "run_id": d["run"].get("id"), "fixture": bool(d.get("fixture"))}


def trade_configs(d: dict) -> list:
    """The configurations this snapshot holds trade rows for — what GET /trades accepts."""
    return sorted(d["trades"].keys())


def replay_dates(d: dict) -> list:
    return list(d["sessions"]["replay"]["dates"])


def run_view(d: dict) -> dict:
    """What was run, the sessions it covers, the scorecard, the data-quality report and the reconciliation.

    `data_quality` is passed whole, per-session rows included: the page's Data-quality tab lists every session, and
    the contract gives it no endpoint of its own.
    """
    return {**_head(d), "run": d["run"], "sessions": d["sessions"], "scorecard": d["scorecard"],
            "data_quality": d["data_quality"], "reconciliation": d["reconciliation"], "rc1": d["rc1"],
            "trade_configs": trade_configs(d), "notes": d["notes"]}


def matrix_view(d: dict, scope: str) -> dict:
    return {**_head(d), "scope": scope, "matrix": d["matrix"][scope]}


def trades_view(d: dict, config: str, scope: str) -> dict:
    """One run's trade rows. `scope=replay` keeps the trades whose decision day is in the replay window (the same
    subsetting the owner's design does); `scope=year` is every row the snapshot holds for that configuration."""
    rows = d["trades"][config]
    if scope == "replay":
        window = set(replay_dates(d))
        rows = [r for r in rows if r.get("decision_date") in window]
    return {**_head(d), "config": config, "scope": scope, "count": len(rows), "rows": rows}


def candidates_view(d: dict, date: str) -> dict:
    rows = [r for r in d["candidates"] if r.get("date") == date]
    return {**_head(d), "date": date, "count": len(rows), "rows": rows}
