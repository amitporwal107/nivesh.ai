"""Regression test for the CAUGHT-badge direction bug found 2026-10-03 (live audit: 23 of 29
CAUGHT badges in a 10-session cohort were the p_down5_1d head firing on a stock that actually
rose). `_odds_badge()` must not badge CAUGHT off a head whose direction doesn't match the
symbol's realised move, when that move is known to the caller.

No database: `conn.fetch()` is a tiny fake that branches on which table the SQL names, mirroring
the stub style in test_movers_v4.py. No pytest-asyncio in this environment, so each async call is
driven with a plain `asyncio.run()` inside an ordinary sync test — no plugin needed."""
import asyncio
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

import pytest

MOVERS_PATH = Path(__file__).resolve().parent.parent / "nidp" / "services" / "daas_api" / "routers" / "movers.py"


@pytest.fixture(scope="module")
def mv():
    mp = pytest.MonkeyPatch()

    def _mod(name):
        m = types.ModuleType(name)
        mp.setitem(sys.modules, name, m)
        return m

    for pkg in ("nidp", "nidp.shared", "nidp.shared.storage", "nidp.services", "nidp.services.daas_api",
                "nidp.services.daas_api.routers"):
        _mod(pkg)
    pg = _mod("nidp.shared.storage.pg")
    sys.modules["nidp.shared.storage"].pg = pg
    mo = _mod("nidp.services.daas_api.routers.move_odds")
    mo.require_internal_plan = lambda: None
    spec = importlib.util.spec_from_file_location("movers_odds_badge_under_test", MOVERS_PATH)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        mp.undo()


def run(coro):
    return asyncio.run(coro)


class FakeConn:
    """`.fetch()` branches on which real table the SQL names — one run in window, estimates given."""

    def __init__(self, estimates):
        self._estimates = estimates  # list of dicts: {"head": ..., "p": ...}

    async def fetch(self, sql, *args):
        if "tpd_run_estimates" in sql:
            rows = sorted(
                ({"run_id": 1, "head": e["head"], "p": e["p"], "p_base_rate": 0.05,
                  "target_session": date(2026, 9, 17)} for e in self._estimates),
                key=lambda r: r["p"], reverse=True,
            )
            return rows
        # the nidp.tpd_runs query
        return [{"run_id": 1, "target_session": date(2026, 9, 17)}]


def test_up_move_caught_by_the_matching_up_head(mv):
    """realised move is UP; the up head clears the cutoff -> CAUGHT, scored off the up head."""
    conn = FakeConn([{"head": "p_up5_1d", "p": 0.55}, {"head": "p_down5_1d", "p": 0.30}])
    out = run(mv._odds_badge(conn, "DEMO", date(2026, 9, 17), realized_pct=0.07))
    assert out["state"] == "CAUGHT"
    assert out["head"] == "p_up5_1d"
    assert out["score"] == 0.55


def test_up_move_not_caught_when_only_the_down_head_was_scored(mv):
    """THE BUG: realised move is UP, but the only head scored at all is p_down5_1d (>= cutoff) --
    no up head exists in this run's estimates for this symbol. Before the fix this badged CAUGHT
    off the wrong-direction head. Must now be MISSED with the wrong-direction reason."""
    conn = FakeConn([{"head": "p_down5_1d", "p": 0.80}])
    out = run(mv._odds_badge(conn, "DEMO", date(2026, 9, 17), realized_pct=0.07))
    assert out["state"] == "MISSED"
    assert out["reason"] == "SCORED_WRONG_DIRECTION_ONLY"
    # transparency: still surfaces what WAS scored, just doesn't call it a catch
    assert out["head"] == "p_down5_1d"
    assert out["score"] == 0.80


def test_up_move_with_both_directions_scored_picks_the_matching_head_regardless_of_rank(mv):
    """Both directions were scored for this run. Even though the down head scores far higher,
    the up head (matching the realised move) is the one used -- and since ITS OWN p is below
    cutoff, this is a plain ranking miss, not a "wrong direction" case: the model did look the
    right way, it just wasn't confident. No `reason` field."""
    conn = FakeConn([{"head": "p_down5_1d", "p": 0.80}, {"head": "p_up5_1d", "p": 0.10}])
    out = run(mv._odds_badge(conn, "DEMO", date(2026, 9, 17), realized_pct=0.07))
    assert out["state"] == "MISSED"
    assert out["head"] == "p_up5_1d"
    assert out["score"] == 0.10
    assert "reason" not in out


def test_down_move_caught_by_the_matching_down_head(mv):
    """Symmetric case: realised move is DOWN, down head clears cutoff -> CAUGHT."""
    conn = FakeConn([{"head": "p_up5_1d", "p": 0.90}, {"head": "p_down5_1d", "p": 0.45}])
    out = run(mv._odds_badge(conn, "DEMO", date(2026, 9, 17), realized_pct=-0.06))
    assert out["state"] == "CAUGHT"
    assert out["head"] == "p_down5_1d"


def test_matching_direction_head_below_cutoff_is_a_real_miss(mv):
    """Realised move is UP; the only head scored is the matching up head, but its own p is
    below cutoff: a genuine ranking miss, not a coverage/direction issue -- no `reason` field."""
    conn = FakeConn([{"head": "p_up5_1d", "p": 0.20}])
    out = run(mv._odds_badge(conn, "DEMO", date(2026, 9, 17), realized_pct=0.07))
    assert out["state"] == "MISSED"
    assert out["head"] == "p_up5_1d"
    assert out["score"] == 0.20
    assert "reason" not in out


def test_unknown_direction_falls_back_to_old_global_top_behavior(mv):
    """When the caller doesn't know the realised move (realized_pct=None), direction can't be
    checked -- preserves the pre-fix behaviour of badging off the single highest-p head."""
    conn = FakeConn([{"head": "p_down5_1d", "p": 0.80}, {"head": "p_up5_1d", "p": 0.20}])
    out = run(mv._odds_badge(conn, "DEMO", date(2026, 9, 17), realized_pct=None))
    assert out["state"] == "CAUGHT"
    assert out["head"] == "p_down5_1d"
    assert "reason" not in out


def test_no_model_run_and_not_in_scored_universe_are_unaffected(mv):
    class EmptyRunsConn:
        async def fetch(self, sql, *args):
            return []

    out = run(mv._odds_badge(EmptyRunsConn(), "DEMO", date(2026, 9, 17), realized_pct=0.07))
    assert out["state"] == "NO_MODEL_RUN"

    class RunsNoEstimatesConn:
        async def fetch(self, sql, *args):
            if "tpd_run_estimates" in sql:
                return []
            return [{"run_id": 1, "target_session": date(2026, 9, 17)}]

    out = run(mv._odds_badge(RunsNoEstimatesConn(), "DEMO", date(2026, 9, 17), realized_pct=0.07))
    assert out["state"] == "MISSED"
    assert out["reason"] == "NOT_IN_SCORED_UNIVERSE"
