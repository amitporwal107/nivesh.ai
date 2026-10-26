"""F&O lab backend B1: the decision snapshot, replay, lineage and live readiness (services/risk_gate/gate.py, replay.py,
readiness.py; routes/risk_controls.py). test_reports/fno_lab_backend_core_TESTCASES.md D-1, D-3, R-1 to R-6, L-1, L-2,
G-1 to G-3.

No network and no real database. Replaced, and by what:
  * the database            tests.test_risk_gate.FakeDB, with dotted-key matching added here so a journal fill's
                            `fills.risk_decision_id` can be found
  * the exchange reference  the `world` fixture of tests.test_risk_gate
  * the session and users   the `h` fixture of tests.test_risk_routes (X-Test-User header)
  * the live feed's status  `services.kite_live_feed.feed.get_feed`, per test

MOCK — not real data: every symbol, premium, id and feed state below is made up. Worked by hand: the bull call spread
(buy 100 C @ 6, sell 110 C @ 2, lot 50) risks Rs 200, the figure test_risk_gate works out.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict

import pytest

import tests.test_risk_gate as trg
from services import execution_modes as modes
from services import risk_controls as rc
from services.kite_live_feed import feed as live_feed
from services.oms import orders as oms
from services.risk_gate import gate, policy, readiness, replay
from tests.test_risk_gate import EXP, NOW, cash, judge, run, spread, struct, world  # noqa: F401 — `world` is a fixture
from tests.test_risk_routes import h  # noqa: F401 — fixture

STEPS = ["market_snapshot", "instrument_master", "regime", "agent_proposal", "schema_check", "pricing_margin",
         "risk_decision", "certification", "oms", "audit_record"]
CONDITIONS = ["agent_certified", "template_certified", "universe_certified", "adapter_certified", "risk_policy_matches",
              "market_data_fresh", "pricing_margin", "portfolio_risk", "user_authorization", "oms_reconciliation",
              "kill_switch", "evidence_persisted"]


def _get(doc: Any, dotted: str) -> list:
    """Every value at a dotted path, looking through lists the way Mongo does."""
    values = [doc]
    for part in dotted.split("."):
        nxt = []
        for v in values:
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, dict) and part in item:
                    nxt.append(item[part])
        values = nxt
    return values


@pytest.fixture(autouse=True)
def dotted_keys(monkeypatch):
    def matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for key, cond in query.items():
            assert not isinstance(cond, dict), f"the fake collection does not know {cond}"
            if cond not in _get(doc, key) and not (cond is None and not _get(doc, key)):
                return False
        return True
    monkeypatch.setattr(trg, "_matches", matches)


def row_of(db, decision_id: str) -> Dict[str, Any]:
    return next(d for d in db[rc.DECISIONS].docs if d["_id"] == decision_id)


def decide_for(db, req):
    return run(gate.check(db, req, now=NOW))


# ── D-1: the snapshot stored with every decision ─────────────────────────────
def test_D1_a_decision_stores_what_the_gate_read_with_its_version_and_hash(world):
    d = judge(world, struct(spread()))
    row = row_of(world.db, d.decision_id)
    snap = row["snapshot"]
    assert set(snap) == {"request", "today", "controls", "live_allowed", "references", "open_structures"}
    assert snap["request"]["symbol"] == "MOCKU" and len(snap["request"]["legs"]) == 2
    assert snap["today"] == "2026-10-21"                                  # an ISO string, not a date object
    assert snap["controls"] == {"kill_switch": False, "halted": False, "reason": None}
    assert snap["live_allowed"] is None and snap["open_structures"] == 0
    assert snap["references"][EXP]["lot_size"] == 50 and snap["references"][EXP]["as_of"] == "2026-10-20"
    assert row["snapshot_version"] == gate.SNAPSHOT_VERSION == "decision-snapshot-v1"
    assert row["snapshot_hash"] == gate.snapshot_hash(snap) and len(row["snapshot_hash"]) == 64
    assert json.loads(json.dumps(snap)) == snap                          # plain JSON types only


def test_D1_an_unreadable_kill_switch_is_stored_as_none_and_a_cash_trade_as_not_applicable(world):
    world.db.fail[(rc.CONTROLS, "find_one")] = RuntimeError("mongo unreachable")
    d = judge(world, cash())
    snap = row_of(world.db, d.decision_id)["snapshot"]
    assert snap["controls"] is None and snap["open_structures"] == "n/a" and snap["references"] == {}


# ── D-3: the list leaves the snapshot out ───────────────────────────────────
def test_D3_the_decision_list_does_not_carry_the_snapshot(h, world):
    decide_for(h.db, struct(spread()))
    r = h.call("GET", "/api/risk/decisions")
    assert r.status_code == 200 and r.json()["count"] == 1
    (item,) = r.json()["decisions"]
    assert "snapshot" not in item and item["snapshot_version"] == gate.SNAPSHOT_VERSION


# ── R-1, R-2: replay matches under the same code and policy ──────────────────
@pytest.mark.parametrize("blocked", [False, True])
def test_R1_R2_a_replay_reaches_the_same_decision_and_writes_nothing(world, blocked):
    if blocked:
        run(rc.set_control(world.db, "u1", field="kill_switch", value=True, reason="gap risk", actor="u1"))
    d = judge(world, struct(spread()))
    before = len(world.db[rc.DECISIONS].docs)
    out = replay.replay(row_of(world.db, d.decision_id))
    assert out["replayable"] is True and out["match"] is True and out["differences"] == []
    assert out["outcome_then"] == out["outcome_now"] == ("block" if blocked else "allow")
    assert out["reasons_then"] == out["reasons_now"] == (["kill_switch_on"] if blocked else [])
    assert out["checks_then"] == out["checks_now"] and [c["check"] for c in out["checks_now"]] == list(gate.CHECK_ORDER)
    assert out["inputs_hash_match"] is True and out["snapshot_hash_match"] is True
    assert out["policy_version_then"] == out["policy_version_now"] == policy.POLICY_VERSION
    assert out["capital_at_risk_then"] == out["capital_at_risk_now"] == 200.0
    assert out["writes"] == "none" and len(world.db[rc.DECISIONS].docs) == before


def test_R2_a_tighter_policy_now_replays_differently_and_says_so(world, monkeypatch):
    d = judge(world, struct(spread()))
    monkeypatch.setattr(policy, "LIMITS", dataclasses.replace(policy.LIMITS, max_capital_at_risk_rs=100.0))
    out = replay.replay(row_of(world.db, d.decision_id))
    assert out["match"] is False and (out["outcome_then"], out["outcome_now"]) == ("allow", "block")
    assert "Outcome was allow, replays as block." in out["differences"]
    assert out["snapshot_hash_match"] is True                             # the record itself is intact


# ── R-3: a tampered record cannot report a match ────────────────────────────
def test_R3_an_edited_snapshot_fails_its_hash_even_when_the_outcome_is_the_same(world):
    d = judge(world, struct(spread()))
    row = row_of(world.db, d.decision_id)
    row["snapshot"]["controls"]["reason"] = "edited after the fact"
    out = replay.replay(row)
    assert out["snapshot_hash_match"] is False and out["match"] is False
    assert out["outcome_then"] == out["outcome_now"] == "allow"
    assert "The stored snapshot does not hash to the recorded snapshot hash." in out["differences"]


def test_R3_an_edited_request_fails_the_inputs_hash(world):
    d = judge(world, struct(spread()))
    row = row_of(world.db, d.decision_id)
    row["snapshot"]["request"]["symbol"] = "OTHERU"
    out = replay.replay(row)
    assert out["inputs_hash_match"] is False and out["match"] is False


# ── R-4: rows that cannot be replayed say why ───────────────────────────────
def test_R4_a_gate_row_without_a_snapshot_is_not_replayable_with_the_reason(world):
    d = judge(world, struct(spread()))
    row = row_of(world.db, d.decision_id)
    for k in ("snapshot", "snapshot_version", "snapshot_hash"):
        row.pop(k)
    out = replay.replay(row)
    assert out["replayable"] is False and "before decision snapshots were stored" in out["reason"]


def test_R4_a_kill_switch_stream_row_is_not_replayable(world):
    run(rc.record_decision(world.db, "u1", action="journal_trade", outcome="denied",
                           reasons=[{"code": "kill_switch_on", "message": "kill switch on"}]))
    (row,) = world.db[rc.DECISIONS].docs
    out = replay.replay(row)
    assert out["replayable"] is False and "kill-switch stream" in out["reason"]


# ── R-5, R-6, L-2: who may read a decision ──────────────────────────────────
@pytest.mark.parametrize("path", ["replay", "lineage"])
def test_R5_R6_L2_only_the_owner_or_an_admin_reads_a_decision(h, world, path):
    d = decide_for(h.db, struct(spread()))
    method = "POST" if path == "replay" else "GET"
    url = f"/api/risk/decisions/{d.decision_id}/{path}"
    before = len(h.db[rc.DECISIONS].docs)
    assert h.call(method, url, who="u1").status_code == 200
    assert h.call(method, url, who="admin").status_code == 200
    assert h.call(method, url, who="admin_as_client").status_code == 200       # the signed-in person is an admin
    other = h.call(method, url, who="advisor_as_client")
    assert other.status_code == 404 and other.json()["detail"]["code"] == "decision_not_found"
    unknown = h.call(method, "/api/risk/decisions/no-such-id/" + path, who="u1")
    assert unknown.status_code == 404 and unknown.json()["detail"] == other.json()["detail"]
    assert h.call(method, url, who=None).status_code == 401
    assert len(h.db[rc.DECISIONS].docs) == before                              # neither route writes a decision


def test_R1_the_replay_route_answers_the_comparison(h, world):
    d = decide_for(h.db, struct(spread()))
    r = h.call("POST", f"/api/risk/decisions/{d.decision_id}/replay")
    body = r.json()
    assert r.status_code == 200 and body["match"] is True and body["decision_id"] == d.decision_id
    assert set(body) >= {"outcome_then", "outcome_now", "reasons_then", "reasons_now", "checks_then", "checks_now",
                         "inputs_hash_match", "snapshot_hash_match", "policy_version_then", "policy_version_now"}


# ── L-1: the ten lineage steps ──────────────────────────────────────────────
def test_L1_an_allowed_spread_marks_only_what_is_recorded(world):
    d = judge(world, struct(spread()))
    out = run(replay.lineage(world.db, row_of(world.db, d.decision_id)))
    by = {s["step"]: s for s in out["steps"]}
    assert [s["step"] for s in out["steps"]] == STEPS
    assert {k: v["status"] for k, v in by.items()} == {
        "market_snapshot": "not_recorded", "instrument_master": "recorded", "regime": "not_recorded",
        "agent_proposal": "not_applicable", "schema_check": "recorded", "pricing_margin": "recorded",
        "risk_decision": "recorded", "certification": "not_recorded", "oms": "not_recorded", "audit_record": "recorded"}
    assert out["recorded"] == 5 and out["replayable"] is True
    assert by["market_snapshot"]["backlog"] == "P0.3" and by["certification"]["backlog"] == "P3.1"
    assert by["instrument_master"]["ref"] == [EXP] and "as of 2026-10-20" in by["instrument_master"]["detail"]
    assert "Rs 200.00" in by["pricing_margin"]["detail"]
    assert by["risk_decision"]["ref"] == d.decision_id
    assert d.decision_id in by["audit_record"]["ref"] and row_of(world.db, d.decision_id)["snapshot_hash"][:12] in by["audit_record"]["detail"]


def test_L1_an_oms_order_and_a_journal_fill_that_carry_the_id_are_linked(world):
    d = judge(world, struct(spread()))
    world.db[oms.ORDERS].docs.append({"_id": "ord-fixture-1", "risk_decision_id": d.decision_id, "state": "filled",
                                      "client_order_id": "co-fixture-1"})
    world.db[replay.JOURNAL].docs.append({"_id": "jr-fixture-1", "status": "OPEN", "nse_symbol": "MOCKU",
                                          "fills": [{"stage": "E1", "risk_decision_id": d.decision_id}]})
    out = run(replay.lineage(world.db, row_of(world.db, d.decision_id)))
    by = {s["step"]: s for s in out["steps"]}
    assert by["oms"]["status"] == "recorded" and by["oms"]["ref"] == ["ord-fixture-1"]
    assert out["linked"]["trade_journal"] == [{"id": "jr-fixture-1", "status": "OPEN", "nse_symbol": "MOCKU"}]
    assert "1 paper record(s) carry this decision id" in by["audit_record"]["detail"]


def test_L1_a_blocked_decision_never_reaches_the_oms_and_cash_has_no_contract(world):
    blocked = judge(world, struct([trg.fut("buy", 100)]))                 # an unhedged future: undefined risk
    steps = {s["step"]: s["status"] for s in run(replay.lineage(world.db, row_of(world.db, blocked.decision_id)))["steps"]}
    assert steps["oms"] == "not_reached"
    shares = judge(world, cash(correlation_id="cid-2"))
    steps = {s["step"]: s["status"] for s in run(replay.lineage(world.db, row_of(world.db, shares.decision_id)))["steps"]}
    assert steps["instrument_master"] == "not_applicable"


# ── G-1 to G-3: the live readiness gate ─────────────────────────────────────
class _Feed:
    def __init__(self, status=None, error: Exception | None = None):
        self.status, self.error = status, error

    async def read_status(self):
        if self.error:
            raise self.error
        return self.status


FEED = {"state": "expired", "session": "open", "data_at": "2026-10-23T10:00:00+00:00", "universe": {"index_options": 1060}}


def test_G1_twelve_conditions_in_prd_order_none_passing(h, monkeypatch):
    monkeypatch.setattr(live_feed, "get_feed", lambda db=None: _Feed(FEED))
    r = h.call("GET", "/api/risk/live-readiness")
    body = r.json()
    assert r.status_code == 200 and [c["id"] for c in body["conditions"]] == CONDITIONS and body["count"] == 12
    assert all(c["status"] == "fail" and c["evidence"] and c["backlog"] for c in body["conditions"])
    assert body["enforceable"] == 0 and body["live_execution_available"] is modes.LIVE_EXECUTION_AVAILABLE is False
    assert body["policy_version"] == policy.POLICY_VERSION


def test_G2_the_rows_read_live_state(h, world, monkeypatch):
    monkeypatch.setattr(live_feed, "get_feed", lambda db=None: _Feed(FEED))
    h.gate_on.add("u1")
    run(rc.set_control(h.db, "u1", field="kill_switch", value=True, reason="gap risk", actor="u1"))
    run(modes.set_live_authorization(h.db, "u1", True, "fixture grant", "adm"))
    decide_for(h.db, struct(spread()))
    by = {c["id"]: c["evidence"] for c in h.call("GET", "/api/risk/live-readiness").json()["conditions"]}
    assert "gate is on for your account" in by["risk_policy_matches"]
    assert "Live feed expired, session open, data at 2026-10-23T10:00:00+00:00" in by["market_data_fresh"]
    assert "index_options 1060" in by["market_data_fresh"]
    assert by["user_authorization"].startswith("An admin has granted you live authorization")
    assert by["kill_switch"].startswith("Kill switch ON, trading halt off")
    assert by["evidence_persisted"].startswith("1 of your gate decisions are stored with a correlation id; 1 carry")
    assert "legs (4)" in by["portfolio_risk"] and "Rs 200,000" in by["portfolio_risk"]


def test_G3_unreadable_state_is_said_and_never_a_pass(h, monkeypatch):
    monkeypatch.setattr(live_feed, "get_feed", lambda db=None: _Feed(error=RuntimeError("redis down")))
    h.db.fail[(rc.CONTROLS, "find_one")] = RuntimeError("mongo unreachable")
    body = h.call("GET", "/api/risk/live-readiness").json()
    by = {c["id"]: c for c in body["conditions"]}
    assert by["market_data_fresh"]["status"] == "fail" and "could not be read" in by["market_data_fresh"]["evidence"]
    assert by["kill_switch"]["status"] == "fail" and "Kill switch could not be read" in by["kill_switch"]["evidence"]
    assert body["enforceable"] == 0
    assert h.call("GET", "/api/risk/live-readiness", who=None).status_code == 401


def test_G3_a_feed_with_no_status_yet_says_so(world):
    async def off():
        return False

    async def nothing():
        return None
    out = run(readiness.live_readiness(world.db, "u1", gate_enabled=off, feed_status=nothing, now=NOW))
    by = {c["id"]: c["evidence"] for c in out["conditions"]}
    assert by["market_data_fresh"].startswith("The live feed has not reported a status")
    assert "gate is off for your account" in by["risk_policy_matches"] and out["read_at"] == NOW.isoformat()
