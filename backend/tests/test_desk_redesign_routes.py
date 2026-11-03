"""Four read-only routes for the desk redesign: TESTCASES SC, EX, CO, FR and ALL in
test_reports/desk_redesign_backend_TESTCASES.md.

    GET /api/desk/idea-scorecard              services/idea_scorecard.py
    GET /api/desk/exit-job-status             services/job_runs.trader_status
    GET /api/desk/paper-account/corrections   services/paper_reconcile.corrections
    GET /api/risk/freshness                   routes/risk_controls.freshness + risk_gate.service's freshness helpers

No network, no real database. Replaced, and by what:
  * `db` in both route modules   ReadOnlyDB below: Mongo filter semantics (tests.mongo_ops), projections applied, every
                                 call recorded, and ANY write raises (so a route that writes fails its test)
  * `get_current_user`           the X-Test-User header names a user; no header is 401
  * the risk inputs              services.risk_gate.inputs.instrument / sector_of / market_state, per test
  * the clock                    job_runs.utcnow and risk_controls._now
MOCK — not real data: every user, ledger row, job run, price, sector and regime below is made up. Only SC-1 reads a
real file: the committed research/p4_adx_rs/results_20261027/result.json. The failure cases use temporary copies.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import desk_trading as desk_route
from routes import risk_controls as risk_route
from services import idea_scorecard as scorecard
from services import job_runs
from services import paper_account as acct
from services import paper_reconcile as reconcile
from services import risk_book
from services.risk_gate import inputs as risk_inputs
from services.risk_gate import service as risk_service
from tests import mongo_ops
from tests.test_risk_gate import FakeDB
from tests.test_risk_service import book as risk_book_fixture

IST = timezone(timedelta(hours=5, minutes=30))
REPO = Path(__file__).resolve().parents[2]
RESULT = REPO / scorecard.RESULT_PATH
WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many",
          "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "bulk_write", "create_index", "drop")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def ist(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


# ── a read-only Mongo stand-in ───────────────────────────────────────────────
def _project(doc: Dict[str, Any], projection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if projection is None:
        return copy.deepcopy(doc)
    keep = {k for k, v in projection.items() if v and k != "_id"}
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k in keep}
    if projection.get("_id", 1) and "_id" in doc:
        out["_id"] = doc["_id"]
    return out


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        self.docs = sorted(self.docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n):
        return self.docs if n is None else self.docs[:n]


class ReadOnlyCollection:
    def __init__(self, name: str, db: "ReadOnlyDB"):
        self.name, self.db, self.docs = name, db, []

    def find(self, query, projection=None):
        self.db.calls.append({"col": self.name, "op": "find", "query": query, "projection": projection})
        return _Cursor([_project(d, projection) for d in self.docs if mongo_ops.match(d, query)])

    async def find_one(self, query, projection=None):
        self.db.calls.append({"col": self.name, "op": "find_one", "query": query, "projection": projection})
        doc = next((d for d in self.docs if mongo_ops.match(d, query)), None)
        return None if doc is None else _project(doc, projection)

    def __getattr__(self, name):
        if name in WRITES:
            def refuse(*a, **kw):
                self.db.writes.append((self.name, name))
                raise AssertionError(f"a read-only route called {name} on {self.name}")
            return refuse
        raise AttributeError(name)


class ReadOnlyDB:
    def __init__(self):
        self.cols: Dict[str, ReadOnlyCollection] = {}
        self.calls: List[Dict[str, Any]] = []
        self.writes: List[Any] = []

    def __getitem__(self, name):
        if name not in self.cols:
            self.cols[name] = ReadOnlyCollection(name, self)
        return self.cols[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


USERS = {"u1": {"user_id": "u1", "email": "one@example.com", "role": "user"},
         "u2": {"user_id": "u2", "email": "two@example.com", "role": "user"}}


@pytest.fixture
def h(monkeypatch):
    db = ReadOnlyDB()

    async def current_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return dict(USERS[who])

    for mod in (desk_route, risk_route):
        monkeypatch.setattr(mod, "db", db)
        monkeypatch.setattr(mod, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(desk_route.router)
    app.include_router(risk_route.router)
    client = TestClient(app)

    class H:
        pass
    out = H()
    out.db = db

    def get(path, who="u1"):
        return client.get(path, headers={"X-Test-User": who} if who else {})
    out.get = get
    return out


ROUTES = ("/api/desk/idea-scorecard", "/api/desk/exit-job-status", "/api/desk/paper-account/corrections",
          "/api/risk/freshness", "/api/risk/freshness?symbol=INFY")


# ── ALL-1 / ALL-2 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ROUTES)
def test_all1_every_route_needs_a_signed_in_user_and_reads_nothing_without_one(h, path):
    r = h.get(path, who=None)
    assert r.status_code == 401
    assert h.db.calls == [] and h.db.writes == []


# ── SC: the idea scorecard ───────────────────────────────────────────────────
def test_sc1_the_committed_study_is_served_exactly_as_the_file_has_it(h):
    r = h.get("/api/desk/idea-scorecard")
    assert r.status_code == 200, r.text
    body = r.json()
    raw = json.loads(RESULT.read_text())
    assert [s["name"] for s in body["splits"]] == ["discovery", "validation", "test"]
    for s in body["splits"]:
        assert [s["from"], s["to"]] == raw["bounds"][s["name"]]
        src = raw["splits"][s["name"]]
        assert s["dates"] == src["dates"]
        assert s["coverage_top_movers_outside_universe"] == src["coverage_top_movers_outside_universe"]
        assert [a["arm"] for a in s["arms"]] == ["B0", "A1", "A2", "A3"]
        for a in s["arms"]:
            f = src["arms"][a["arm"]]
            assert a["rank_ic"] == {"mean": f["ic"]["mean"], "nw_t": f["ic"]["t"], "se": f["ic"]["se"], "n": f["ic"]["n"]}
            assert a["top_decile_net_mean"] == f["top_decile_net_mean"]
            assert a["top_decile_hit_rate"] == f["top_hit_rate"]
            if a["arm"] != "B0":
                d = f["ic_diff_vs_B0"]
                assert (a["vs_b0"]["delta_ic"], a["vs_b0"]["nw_t"], a["vs_b0"]["permutation_p"]) == \
                    (d["mean"], d["t"], d["perm_p_one_sided"])
    test = {a["arm"]: a for a in body["splits"][2]["arms"]}
    assert test["B0"]["top_decile_net_mean"] == -0.00992                     # the negative is served as it is
    assert (test["A2"]["vs_b0"]["delta_ic"], test["A2"]["vs_b0"]["nw_t"], test["A2"]["permutation_p"]) == (0.0122, 3.18, 0.007)
    assert test["A2"]["vs_b0"]["by_regime"]["up"] == {"n": 0, "delta_ic": None, "nw_t": None}   # null, not 0
    assert body["study"]["registration_commit"] == raw["registration_commit"]
    assert body["study"]["signal_dates"] == 385
    assert body["decision"]["adopted"] is None
    assert body["decision"]["per_arm"] == raw["decision"]["per_arm"]
    assert h.db.calls == [] and h.db.writes == []                               # files only; no database


def test_sc2_b0_is_the_baseline_so_its_difference_and_permutation_p_are_null():
    body = scorecard.load()
    for s in body["splits"]:
        b0 = s["arms"][0]
        assert b0["arm"] == "B0" and b0["vs_b0"] is None and b0["permutation_p"] is None


def test_sc3_the_verdict_and_the_rs63_status_and_the_wording():
    body = scorecard.load()
    assert body["decision"]["verdict"] == "keep B0; the current ranking shows no measurable skill"
    assert body["decision"]["study_verdict"] == "keep B0 (no arm met every pre-registered condition)"
    assert body["rs63"]["status"] == "promising, awaiting its pre-registered confirmation"
    assert body["rs63"]["arm"] == "A2" and body["rs63"]["adopted"] is False
    text = json.dumps({k: v for k, v in body.items() if k != "disclaimer"}).lower()
    assert "pick" not in text and "recommend" not in text and "suggest" not in text
    assert body["disclaimer"].startswith("Ideas, not recommendations.")


def test_sc4_every_present_source_carries_the_sha256_of_its_bytes():
    body = scorecard.load()
    assert body["sources"][0]["path"] == scorecard.RESULT_PATH and body["sources"][0]["present"] is True
    for src in body["sources"]:
        if src["present"]:
            data = (REPO / src["path"]).read_bytes()
            assert src["sha256"] == hashlib.sha256(data).hexdigest() and src["bytes"] == len(data)


def _copy_study(tmp_path: Path, mutate=None, docs=True) -> Path:
    dest = tmp_path / scorecard.RESULT_PATH
    dest.parent.mkdir(parents=True)
    data = json.loads(RESULT.read_text())
    if mutate:
        mutate(data)
    dest.write_text(json.dumps(data))
    if docs:
        for rel, _role in scorecard.DOCUMENTS:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / rel, tmp_path / rel)
    return tmp_path


def test_sc5_a_missing_result_file_is_503_with_the_reason_and_no_numbers(h, tmp_path, monkeypatch):
    monkeypatch.setattr(scorecard, "REPO_ROOT", tmp_path)
    r = h.get("/api/desk/idea-scorecard")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "scorecard_unavailable" and scorecard.RESULT_PATH in detail["reason"]
    assert set(detail) == {"code", "reason", "study_id"}


@pytest.mark.parametrize("breaks, part", [
    ("not json", "not valid JSON"),
    ("no test split", "splits.test"),
    ("no B0", "splits.validation.arms.B0"),
])
def test_sc6_an_unreadable_or_incomplete_result_file_is_503(h, tmp_path, monkeypatch, breaks, part):
    if breaks == "not json":
        root = _copy_study(tmp_path)
        (root / scorecard.RESULT_PATH).write_text("{not json")
    elif breaks == "no test split":
        root = _copy_study(tmp_path, lambda d: d["splits"].pop("test"))
    else:
        root = _copy_study(tmp_path, lambda d: d["splits"]["validation"]["arms"].pop("B0"))
    monkeypatch.setattr(scorecard, "REPO_ROOT", root)
    r = h.get("/api/desk/idea-scorecard")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "scorecard_unavailable"
    assert part in r.json()["detail"]["reason"]


@pytest.mark.parametrize("mutate", [
    lambda d: d["decision"].__setitem__("adopted", "A2"),
    lambda d: d["splits"]["validation"]["arms"]["B0"]["ic"].__setitem__("t", 2.5),
    lambda d: d["splits"]["test"]["arms"]["B0"]["ic"].__setitem__("t", -2.0),
])
def test_sc7_a_file_that_contradicts_the_fixed_verdict_is_not_served(h, tmp_path, monkeypatch, mutate):
    monkeypatch.setattr(scorecard, "REPO_ROOT", _copy_study(tmp_path, mutate))
    r = h.get("/api/desk/idea-scorecard")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "scorecard_out_of_date"


def test_sc8_documents_are_listed_as_references_never_opened(h, tmp_path, monkeypatch):
    """Staging mounts research/ into the backend container but not docs/: the documents are references, not files the
    route reads, so their absence is not reported as an error (audit 2026-10-28: "not readable (FileNotFoundError)")."""
    monkeypatch.setattr(scorecard, "REPO_ROOT", _copy_study(tmp_path, docs=False))
    r = h.get("/api/desk/idea-scorecard")
    assert r.status_code == 200
    srcs = r.json()["sources"]
    assert srcs[0]["present"] is True and srcs[0]["kind"] == "data"
    assert [s["path"] for s in srcs[1:]] == [rel for rel, _ in scorecard.DOCUMENTS]
    assert all(s["kind"] == "reference" and s["present"] is None and s["sha256"] is None for s in srcs[1:])
    assert "Error" not in json.dumps(srcs)


# ── EX: when exits were last checked ─────────────────────────────────────────
JOB = "check_desk_alerts"
SECRET = "Traceback: mongodb://user:MOCK-secret@db-host/x"


def runrow(rid, at, status, session=None, **extra):
    started = at.isoformat()
    finished = None if status == job_runs.RUNNING else (at + timedelta(seconds=40)).isoformat()
    return {"_id": rid, "job": JOB, "started_at": started, "finished_at": finished, "status": status,
            "exit_code": 0, "session": session, "counts": {"trades_checked": 42, "users": 9}, "error": None,
            "dry_run": False, **extra}


MON_OK = runrow("mon-1", ist(2026, 10, 26, 20, 45), job_runs.OK, "2026-10-26")
MON_RETRY = runrow("mon-2", ist(2026, 10, 26, 22, 45), job_runs.SKIPPED_DONE, "2026-10-26")
TUE_OK = runrow("tue-1", ist(2026, 10, 27, 20, 45), job_runs.OK, "2026-10-27")
TUE_RETRY = runrow("tue-2", ist(2026, 10, 27, 22, 45), job_runs.SKIPPED_DONE, "2026-10-27")

EX_CASES = {
    "EX-1 ok": ([MON_OK, MON_RETRY, TUE_OK, TUE_RETRY], ist(2026, 10, 27, 23, 50), "ok", "ok"),
    "EX-2 late": ([MON_OK, MON_RETRY], ist(2026, 10, 27, 21, 0), "late", "ok"),
    "EX-3 missed": ([MON_OK, MON_RETRY], ist(2026, 10, 27, 21, 50), "missed", "missed"),
    "EX-4 never run": ([], ist(2026, 10, 27, 21, 50), "missed", "never_run"),
    "EX-5 running": ([MON_OK, MON_RETRY, runrow("tue-r", ist(2026, 10, 27, 20, 45), job_runs.RUNNING)],
                     ist(2026, 10, 27, 20, 50), "running", "running"),
    "EX-6 failed": ([MON_OK, MON_RETRY, runrow("tue-f", ist(2026, 10, 27, 20, 45), job_runs.FAILED, error=SECRET)],
                    ist(2026, 10, 27, 21, 0), "missed", "failed"),
}


@pytest.mark.parametrize("case", list(EX_CASES))
def test_ex1_to_ex7_the_trader_reading_and_its_agreement_with_the_admin_route(h, monkeypatch, case):
    rows, now, want_status, want_state = EX_CASES[case]
    h.db[job_runs.RUNS].docs = copy.deepcopy(rows)
    monkeypatch.setattr(job_runs, "utcnow", lambda: now)
    r = h.get("/api/desk/exit-job-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["state"]) == (want_status, want_state), body
    # EX-7: the admin route's reading of the same rows at the same moment (full documents, its own reads)
    admin_db = FakeDB()
    admin_db[job_runs.RUNS].docs = copy.deepcopy(rows)
    assert run(job_runs.read_health(admin_db, JOB, now))["state"] == body["state"]
    assert "secret" not in r.text.lower() and "trades_checked" not in r.text and "exit_code" not in r.text
    assert h.db.writes == []


def test_ex1_ok_names_the_session_that_was_checked(h, monkeypatch):
    rows, now, _s, _st = EX_CASES["EX-1 ok"]
    h.db[job_runs.RUNS].docs = copy.deepcopy(rows)
    monkeypatch.setattr(job_runs, "utcnow", lambda: now)
    body = h.get("/api/desk/exit-job-status").json()
    assert body["last_checked"]["session"] == "2026-10-27"
    assert body["last_checked"]["started_at"] == TUE_OK["started_at"]
    assert body["message"] == "Exits were checked after the 2026-10-27 close."


def test_ex2_late_names_the_slot_that_is_due(h, monkeypatch):
    rows, now, _s, _st = EX_CASES["EX-2 late"]
    h.db[job_runs.RUNS].docs = copy.deepcopy(rows)
    monkeypatch.setattr(job_runs, "utcnow", lambda: now)
    body = h.get("/api/desk/exit-job-status").json()
    assert "Tue 27 Oct 20:45" in body["message"] and body["last_checked"]["session"] == "2026-10-26"


def test_ex4_no_heartbeat_has_no_last_checked(h, monkeypatch):
    monkeypatch.setattr(job_runs, "utcnow", lambda: ist(2026, 10, 27, 21, 50))
    body = h.get("/api/desk/exit-job-status").json()
    assert body["last_checked"] is None and body["latest_run"] is None
    assert body["message"] == "No evening exit check has been recorded."


def test_ex8_every_heartbeat_read_is_an_allow_list_projection(h, monkeypatch):
    h.db[job_runs.RUNS].docs = copy.deepcopy([MON_OK, MON_RETRY])
    monkeypatch.setattr(job_runs, "utcnow", lambda: ist(2026, 10, 27, 21, 0))
    h.get("/api/desk/exit-job-status")
    reads = [c for c in h.db.calls if c["col"] == job_runs.RUNS]
    assert len(reads) == 2
    for c in reads:
        assert c["projection"] is not None
        assert {k for k, v in c["projection"].items() if v} <= set(job_runs.TRADER_FIELDS)
        assert c["query"]["job"] == JOB


# ── CO: the paper account's corrections ──────────────────────────────────────
def ledger_row(rid, uid, at, action, **extra):
    return {"_id": rid, "user_id": uid, "at": at, "action": action, "policy_version": acct.POLICY_VERSION,
            "snapshot": "MOCK-snapshot-label", **extra}


K_EXCL = "reconcile:closed_pnl_not_in_cash:t-excl"
K_VOID = "reconcile:closed_pnl_missing:t-void"
K_RES = "reconcile:open_trade_unreserved:t-res"
LEDGER = [
    ledger_row("r-1", "u1", "2026-10-20T04:00:00+00:00", "reserve", amount_rs=50_000.0, trade_id="t-res"),
    ledger_row("r-2", "u1", "2026-10-21T04:00:00+00:00", "release", amount_rs=10_000.0, net_pnl_rs=-40.1, trade_id="t-excl"),
    ledger_row(K_EXCL, "u1", "2026-10-27T10:00:00+00:00", acct.ADJUST, reason_code=reconcile.PNL_NOT_IN_CASH,
               trade_id="t-excl", symbol="FIXA", cash_delta_rs=0.0, blocked_delta_rs=0.0, actor="reconcile",
               run_id="recon-1", idempotency_key=K_EXCL, stamp=None,
               note="Owner decision 'exclude': Keep it out of the account (MOCK)."),
    ledger_row(K_VOID, "u1", "2026-10-27T10:00:01+00:00", acct.ADJUST, reason_code=reconcile.PNL_MISSING,
               trade_id="t-void", symbol="NIFTY", cash_delta_rs=0.0, blocked_delta_rs=0.0, actor="reconcile",
               run_id="recon-1", note="Owner decision 'void': Record that this trade has no cash effect (MOCK)."),
    ledger_row(K_RES, "u1", "2026-10-27T10:00:02+00:00", acct.ADJUST, reason_code=reconcile.OPEN_UNRESERVED,
               trade_id="t-res", symbol="ICICIBANK", cash_delta_rs=0.0, blocked_delta_rs=124_617.8, actor="reconcile",
               run_id="recon-1", note="Reserve the entry value for an open position that holds no reservation (MOCK).",
               stamp={"field": "paper_reserved_rs", "before": None, "after": 124_617.8}),
    ledger_row("revert:" + K_RES, "u1", "2026-10-27T11:00:00+00:00", acct.ADJUST, reason_code=reconcile.REVERT,
               reverts=K_RES, trade_id="t-res", symbol="ICICIBANK", cash_delta_rs=0.0, blocked_delta_rs=-124_617.8,
               actor="reconcile", run_id="revert-1", note=f"Reverses {K_RES} (run recon-1)."),
    ledger_row("reconcile:closed_pnl_not_in_cash:t-other", "u2", "2026-10-27T12:00:00+00:00", acct.ADJUST,
               reason_code=reconcile.PNL_NOT_IN_CASH, trade_id="t-other", symbol="OTHER", cash_delta_rs=-5.0,
               blocked_delta_rs=0.0, note="Owner decision 'exclude': u2's own (MOCK)."),
]


def test_co1_co2_the_callers_corrections_newest_first_with_decisions_and_reverts(h):
    h.db[acct.LEDGER].docs = copy.deepcopy(LEDGER)
    r = h.get("/api/desk/paper-account/corrections")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["corrections"]
    assert [c["id"] for c in rows] == ["revert:" + K_RES, K_RES, K_VOID, K_EXCL]          # u2 and reserve/release left out
    by = {c["id"]: c for c in rows}
    assert (by[K_EXCL]["decision"], by[K_EXCL]["kind"], by[K_EXCL]["in_force"]) == ("exclude", "owner_decision", True)
    assert by[K_EXCL]["reason"] == "A closed trade's P&L had not reached cash"
    assert by[K_EXCL]["at"] == "2026-10-27T10:00:00+00:00" and by[K_EXCL]["symbol"] == "FIXA"
    assert (by[K_VOID]["decision"], by[K_VOID]["in_force"]) == ("void", True)
    assert (by[K_RES]["decision"], by[K_RES]["kind"], by[K_RES]["in_force"]) == (None, "proposed", False)
    assert by[K_RES]["reverted_by"] == "revert:" + K_RES
    assert (by["revert:" + K_RES]["kind"], by["revert:" + K_RES]["reverts"]) == ("revert", K_RES)
    assert body["counts"]["excluded"] == 1 and body["counts"]["voided"] == 1
    assert body["counts"]["in_force"] == 2 and body["counts"]["reverted"] == 1
    assert "t-other" not in r.text and "OTHER" not in r.text
    assert h.db.writes == []


def test_co2_another_user_sees_only_their_own(h):
    h.db[acct.LEDGER].docs = copy.deepcopy(LEDGER)
    rows = h.get("/api/desk/paper-account/corrections", who="u2").json()["corrections"]
    assert [c["trade_id"] for c in rows] == ["t-other"]


def test_co3_the_ledger_read_is_filtered_to_the_user_and_projected(h):
    h.db[acct.LEDGER].docs = copy.deepcopy(LEDGER)
    r = h.get("/api/desk/paper-account/corrections")
    [read] = [c for c in h.db.calls if c["col"] == acct.LEDGER]
    assert read["query"] == {"user_id": "u1", "action": acct.ADJUST}
    assert set(read["projection"]) <= set(reconcile.CORRECTION_FIELDS)
    for c in r.json()["corrections"]:
        assert not {"user_id", "snapshot", "stamp", "policy_version", "idempotency_key"} & set(c)
    assert "MOCK-snapshot-label" not in r.text and "paper_reserved_rs" not in r.text


def test_co4_no_corrections_is_an_empty_list(h):
    body = h.get("/api/desk/paper-account/corrections").json()
    assert body["corrections"] == [] and body["count"] == 0
    assert body["counts"]["excluded"] == 0 and body["counts"]["voided"] == 0 and body["truncated"] is False


def test_co_decision_of_reads_only_the_owner_decision_prefix():
    assert reconcile.decision_of("Owner decision 'post_pnl': Post its net P&L.") == "post_pnl"
    assert reconcile.decision_of("Release 5.00 still reserved for a closed trade.") is None
    assert reconcile.decision_of(None) is None


# ── FR: input freshness ──────────────────────────────────────────────────────
NOW = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)        # Tuesday 10:30 IST; the reference session is Mon 26th


@pytest.fixture
def inputs_world(monkeypatch):
    w = {"inst": {"bars": [], "last_close": 1650.0, "last_close_as_of": "2026-10-26", "adv_rs": 5e9,
                  "adv_sessions": 20, "source": risk_inputs.BARS_SOURCE, "error": None},
         "sector": {"sector": "Information Technology", "as_of": "2026-09-30",
                    "source": risk_inputs.SECTOR_SOURCE + ", Nifty Total Market", "error": None},
         "market": {"vix": 14.2, "regime": "BEAR", "as_of": "2026-10-23", "key": "MOCK-key",
                    "source": risk_inputs.MARKET_SOURCE, "error": None},
         "calls": []}

    async def instrument(symbol, today):
        w["calls"].append(("instrument", symbol, today.isoformat()))
        return copy.deepcopy(w["inst"])

    async def sector_of(symbol):
        w["calls"].append(("sector_of", symbol))
        return copy.deepcopy(w["sector"])

    async def market_state():
        w["calls"].append(("market_state",))
        return copy.deepcopy(w["market"])

    monkeypatch.setattr(risk_inputs, "instrument", instrument)
    monkeypatch.setattr(risk_inputs, "sector_of", sector_of)
    monkeypatch.setattr(risk_inputs, "market_state", market_state)
    monkeypatch.setattr(risk_route, "_now", lambda: NOW)
    return w


def test_fr1_fr2_a_symbol_with_fresh_inputs_and_a_market_state_one_session_old(h, inputs_world):
    inputs_world["market"]["as_of"] = "2026-10-26"
    r = h.get("/api/risk/freshness?symbol=infy")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "INFY" and body["reference_session"] == "2026-10-26" and body["all_ok"] is True
    lc, sec, mk = (body["inputs"][k] for k in ("last_close", "sector", "market_state"))
    assert (lc["as_of"], lc["age_sessions"], lc["budget"], lc["status"], lc["value"]) == ("2026-10-26", 0, 2, "ok", 1650.0)
    assert (sec["status"], sec["budget"], sec["age_sessions"], sec["value"]) == ("ok", None, None, "Information Technology")
    assert (mk["status"], mk["regime"], mk["vix"]) == ("ok", "BEAR", 14.2)
    assert ("instrument", "INFY", "2026-10-27") in inputs_world["calls"]
    assert h.db.calls == [] and h.db.writes == []


def test_fr2_the_regime_as_of_friday_23_oct_is_one_session_old_on_tuesday_and_within_budget(h, inputs_world):
    mk = h.get("/api/risk/freshness").json()["inputs"]["market_state"]
    assert (mk["as_of"], mk["age_sessions"], mk["budget"], mk["ok"], mk["status"]) == ("2026-10-23", 1, 2, True, "ok")


def test_fr3_a_market_state_three_sessions_old_is_stale(h, inputs_world):
    inputs_world["market"]["as_of"] = "2026-10-21"
    body = h.get("/api/risk/freshness").json()
    mk = body["inputs"]["market_state"]
    assert (mk["status"], mk["ok"], mk["age_sessions"]) == ("stale", False, 3)
    assert "3 sessions" in mk["reason"] and "budget is 2" in mk["reason"]
    assert body["all_ok"] is False


def test_fr4_unreadable_sources_are_unknown_with_their_own_reasons(h, inputs_world):
    inputs_world["inst"].update(last_close=None, last_close_as_of=None,
                                error="the end-of-day bars could not be read (MOCK)")
    inputs_world["sector"].update(sector=None, as_of=None, error="INFY is on none of Nifty Total Market, Nifty 500")
    inputs_world["market"] = {"vix": None, "regime": None, "as_of": None, "key": None,
                              "source": risk_inputs.MARKET_SOURCE, "error": "the desk regime is unavailable"}
    body = h.get("/api/risk/freshness?symbol=INFY").json()
    lc, sec, mk = (body["inputs"][k] for k in ("last_close", "sector", "market_state"))
    assert (lc["status"], lc["as_of"], lc["reason"]) == ("unknown", None, "the end-of-day bars could not be read (MOCK)")
    assert (sec["status"], sec["reason"]) == ("unknown", "INFY is on none of Nifty Total Market, Nifty 500")
    assert (mk["status"], mk["as_of"], mk["reason"]) == ("unknown", None, "the desk regime is unavailable")
    assert body["all_ok"] is False


def test_fr5_without_a_symbol_only_the_market_state_is_judged(h, inputs_world):
    body = h.get("/api/risk/freshness").json()
    assert body["symbol"] is None
    assert body["inputs"]["last_close"]["status"] == "not_checked" and body["inputs"]["sector"]["status"] == "not_checked"
    assert inputs_world["calls"] == [("market_state",)]


@pytest.mark.parametrize("bad", ["IN%20FY%3B", "INFY$", "%3Cscript%3E"])
def test_fr6_a_bad_symbol_is_422(h, inputs_world, bad):
    r = h.get(f"/api/risk/freshness?symbol={bad}")
    assert r.status_code == 422 and r.json()["detail"] == "invalid_symbol"
    assert inputs_world["calls"] == []


@pytest.mark.parametrize("variant", ["fresh", "stale market", "unreadable"])
def test_fr7_the_route_and_the_risk_service_judge_the_same_inputs_identically(h, inputs_world, monkeypatch, variant):
    if variant == "stale market":
        inputs_world["market"]["as_of"] = "2026-10-20"
    if variant == "unreadable":
        inputs_world["inst"].update(last_close=None, last_close_as_of=None, error="MOCK bars unreadable")
        inputs_world["sector"].update(sector=None, error="MOCK lists unreadable")

    async def controls(db, uid):
        return {"kill_switch": False, "halted": False}

    async def read_book(db, uid, **kw):
        return risk_book_fixture()

    monkeypatch.setattr(risk_book, "controls", controls)
    monkeypatch.setattr(risk_book, "read", read_book)
    req = risk_service.EntryRequest(correlation_id="c1", user_id="u1", actor_id="u1", mode="paper",
                                    path="desk_paper_trade", symbol="INFY", quantity=10, entry_price=1650.0,
                                    stop_price=1600.0, target_price=1800.0)
    snap = run(risk_service.gather(FakeDB(), req, NOW))
    decision = risk_service.decide(req, snap)
    route = h.get("/api/risk/freshness?symbol=INFY").json()["inputs"]

    def core(rec):
        return {k: v for k, v in rec.items() if k not in ("status", "value", "regime", "vix", "key")}

    assert core(route["last_close"]) == snap["instrument"]["last_close_freshness"] == decision["freshness"]["last_close"]
    assert core(route["market_state"]) == snap["market"]["freshness"] == decision["freshness"]["market"]
    assert core(route["sector"]) == decision["freshness"]["sector"]
    blocked = {r["code"] for r in decision["reasons"] if r.get("check") == "inputs"} if decision.get("reasons") else set()
    if variant == "stale market":
        assert route["market_state"]["status"] == "stale" and "market_state_stale" in blocked
    if variant == "unreadable":
        assert {"last_close_unknown", "sector_unknown"} <= blocked
