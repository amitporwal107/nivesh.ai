"""Paper-account reconciliation (services/paper_reconcile.py, paper_account.adjust, scripts/reconcile_paper_accounts.py).

Test cases RC-1 … RC-14 in test_reports/paper_exit_job_reconcile_TESTCASES.md.

The fake below follows tests/test_paper_account.py and tests/test_desk_trading.py (in-memory collections, `_id`
uniqueness, $set/$inc/$push) and adds what the reconciliation's idempotency rests on: `{"field": {"$ne": v}}` and
equality against an array field (Mongo matches when the array contains the value). It also counts deletes, so
"nothing is deleted" is asserted, not assumed.

MOCK — not real data. STAGING (RC-12) is copied from the staging read of 2026-10-27 (allow-list projection; the user id
replaced by "user_a"; trade ids kept so the expected output can be compared with the dry run in the report).
"""
from __future__ import annotations

import asyncio
import copy
import io
import itertools
import json
from contextlib import redirect_stdout
from typing import Any, Dict, List, Optional

import pytest
from pymongo.errors import DuplicateKeyError

from services import desk_trading as svc
from services import paper_account as acct
from services import paper_reconcile as rec

_ids = itertools.count(1)


def _match_value(doc_value: Any, cond: Any) -> bool:
    if isinstance(cond, dict):
        assert set(cond) == {"$ne"}, f"the fake does not know {cond}"
        target = cond["$ne"]
        return target not in doc_value if isinstance(doc_value, list) else doc_value != target
    if isinstance(doc_value, list) and not isinstance(cond, list):
        return cond in doc_value
    return doc_value == cond


def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    return all(_match_value(doc.get(k), v) for k, v in query.items())


class _Res:
    def __init__(self, matched: int = 0):
        self.matched_count = self.modified_count = matched


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction):
        self.docs = sorted(self.docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    async def to_list(self, n):
        return self.docs if n is None else self.docs[:n]


class Col:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.writes = 0
        self.deletes = 0
        self.fail_next_insert: Optional[Exception] = None

    def find(self, q, projection=None):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, q)])

    async def find_one(self, q, projection=None):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, q)), None)

    async def insert_one(self, doc):
        if self.fail_next_insert:
            exc, self.fail_next_insert = self.fail_next_insert, None
            raise exc
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", f"oid-{next(_ids)}")
        if any(d["_id"] == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key: _id")
        self.writes += 1
        self.docs.append(doc)

    async def update_one(self, q, update, upsert=False):
        assert set(update) <= {"$set", "$inc", "$push", "$setOnInsert"}, update
        for d in self.docs:
            if _matches(d, q):
                self.writes += 1
                d.update(copy.deepcopy(update.get("$set") or {}))
                for k, v in (update.get("$inc") or {}).items():
                    d[k] = (d.get(k) or 0) + v
                for k, v in (update.get("$push") or {}).items():
                    d.setdefault(k, []).append(copy.deepcopy(v))
                return _Res(1)
        if upsert:
            doc = dict(update.get("$setOnInsert") or {})
            doc.update(update.get("$set") or {})
            self.docs.append(doc)
            self.writes += 1
        return _Res(0)

    async def delete_one(self, q):
        self.deletes += 1
        raise AssertionError("the reconciliation must never delete")

    async def delete_many(self, q):
        self.deletes += 1
        raise AssertionError("the reconciliation must never delete")


class DB:
    def __init__(self):
        self.cols: Dict[str, Col] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, Col())

    def writes(self) -> int:
        return sum(c.writes for c in self.cols.values())

    def deletes(self) -> int:
        return sum(c.deletes for c in self.cols.values())


def run(coro):
    return asyncio.run(coro)


U = "user_a"
CREATED = "2026-10-21T23:33:40.059148+00:00"
COST = {"name": "strategy_engine default", "slippage_pct_per_side": 0.05, "brokerage_rs_per_side": 20.0,
        "source": "services/strategy_engine/backtest.py"}

# STAGING, 2026-10-27 read (see the module docstring).
STAGING_TRADES = [
    {"_id": "ef61108b-a124-49cc-a114-53b1db717b02", "user_id": U, "symbol": "NORTHARC", "quantity": 417, "entry_price": 280.66,
     "stop_price": 268.67, "target_price": 304.64, "opened_at": "2026-10-19T19:15:46.535827+00:00", "status": "closed",
     "closed_at": "2026-10-21T13:44:09.613891+00:00", "exit_price": 268.67, "exit_reason": "stop", "exit_session": "2026-10-21",
     "realized_pnl_rs": -4999.83, "costs_rs": 154.54, "net_pnl_rs": -5154.37, "held_sessions": 1, "observations": 1},
    {"_id": "ffa3904e-2245-4e60-a9d8-a37247425c62", "user_id": U, "symbol": "ICICIBANK", "quantity": 89, "entry_price": 1400.2,
     "stop_price": 1363.26, "target_price": 1474.07, "opened_at": "2026-10-20T03:03:38.453895+00:00", "status": "open"},
    *[{"_id": i, "user_id": U, "symbol": "HAL", "quantity": 25, "entry_price": 4989.0, "stop_price": 4822.25,
       "target_price": 5322.51, "opened_at": o, "status": "closed", "closed_at": "2026-10-23T11:49:52+00:00",
       "exit_price": 4790.0, "exit_reason": "stop", "exit_session": "2026-10-22", "realized_pnl_rs": -4975.0,
       "costs_rs": 162.24, "net_pnl_rs": -5137.24}
      for i, o in (("8faba557-d1c2-41df-9b9b-5b8e4362a0b6", "2026-10-20T04:53:45+00:00"),
                   ("4322e9b4-9043-418f-8d16-98fd626b0c82", "2026-10-20T05:25:34+00:00"),
                   ("ceda3285-8de0-4dbe-bbc4-e6377010ba23", "2026-10-21T16:35:46+00:00"))],
    {"_id": "38865edc-312f-4065-9923-e5d5249f8469", "user_id": U, "symbol": "FIXA", "quantity": 1, "entry_price": 100.0,
     "stop_price": 95.0, "target_price": 110.0, "opened_at": "2026-10-21T22:53:31.742865+00:00", "status": "closed",
     "closed_at": "2026-10-21T22:54:26.160528+00:00", "exit_price": 100.0, "exit_reason": "manual", "realized_pnl_rs": 0.0,
     "costs_rs": 40.1, "net_pnl_rs": -40.1, "held_sessions": 0, "observations": 0},
    {"_id": "3db5e174-0000-4000-8000-000000000001", "user_id": U, "symbol": "FIXC", "quantity": 10, "entry_price": 100.0,
     "stop_price": 95.0, "target_price": 110.0, "opened_at": "2026-10-21T23:33:40.057826+00:00", "status": "closed",
     "closed_at": "2026-10-21T23:33:40.285110+00:00", "exit_price": 100.0, "exit_reason": "manual", "realized_pnl_rs": 0.0,
     "costs_rs": 41.0, "net_pnl_rs": -41.0, "paper_reserved_rs": 1000.0},
    {"_id": "37681c72-2a64-4cb8-894b-e5e777213b2e", "user_id": U, "symbol": "ICICIBANK", "quantity": 89, "entry_price": 1400.2,
     "stop_price": 1363.26, "target_price": 1474.07, "opened_at": "2026-10-21T23:51:27.402431+00:00", "status": "open",
     "paper_reserved_rs": 124617.8},
    {"_id": "089db966-3918-4ef7-887b-1defe2b8a212", "user_id": U, "kind": "strategy", "underlying": "NIFTY", "symbol": "NIFTY",
     "family": "bull_call_spread", "cost_model": COST,
     "legs": [{"kind": "option", "side": "buy", "lots": 1, "lot_size": 65, "entry_price": 124.4, "expiry": "2026-10-27",
               "strike": 22600.0, "option_type": "call", "price_source": "NSE F&O bhavcopy close 2026-10-23"},
              {"kind": "option", "side": "sell", "lots": 1, "lot_size": 65, "entry_price": 53.35, "expiry": "2026-10-27",
               "strike": 22800.0, "option_type": "call", "price_source": "NSE F&O bhavcopy close 2026-10-23"}],
     "opened_at": "2026-10-24T23:07:32.379372+00:00", "status": "closed", "closed_at": "2026-10-24T23:08:32.897824+00:00",
     "exit_reason": "manual", "exit_note": "Closed with no end-of-day marks on record for it yet; it has no P&L.",
     "realized_pnl_rs": None, "costs_rs": None, "net_pnl_rs": None, "paper_reserved_rs": 13000.0, "held_sessions": 0,
     "observations": 0, "checked_through": None, "flags": [{"code": "underlying_bars_missing"}]},
]
STAGING_LEDGER = [
    {"user_id": U, "at": "2026-10-21T23:33:40.07+00:00", "action": "reserve", "amount_rs": 1000.0,
     "trade_id": "3db5e174-0000-4000-8000-000000000001", "symbol": "FIXC"},
    {"user_id": U, "at": "2026-10-21T23:33:40.28+00:00", "action": "release", "amount_rs": 1000.0, "net_pnl_rs": -41.0,
     "trade_id": "3db5e174-0000-4000-8000-000000000001", "symbol": "FIXC"},
    {"user_id": U, "at": "2026-10-21T23:51:27.40+00:00", "action": "reserve", "amount_rs": 124617.8,
     "trade_id": "37681c72-2a64-4cb8-894b-e5e777213b2e", "symbol": "ICICIBANK"},
    *[{"user_id": U, "at": "2026-10-23T11:49:52+00:00", "action": "release", "amount_rs": 0.0, "net_pnl_rs": -5137.24,
       "trade_id": i, "symbol": "HAL"}
      for i in ("ceda3285-8de0-4dbe-bbc4-e6377010ba23", "4322e9b4-9043-418f-8d16-98fd626b0c82",
                "8faba557-d1c2-41df-9b9b-5b8e4362a0b6")],
    {"user_id": U, "at": "2026-10-24T23:07:32.44+00:00", "action": "reserve", "amount_rs": 13000.0,
     "trade_id": "089db966-3918-4ef7-887b-1defe2b8a212", "symbol": "NIFTY"},
    {"user_id": U, "at": "2026-10-24T23:08:32.90+00:00", "action": "release", "amount_rs": 13000.0, "net_pnl_rs": None,
     "trade_id": "089db966-3918-4ef7-887b-1defe2b8a212", "symbol": "NIFTY"},
]
STAGING_ACCOUNT = {"user_id": U, "blocked_rs": 124617.79999999999, "cash_rs": 984547.28, "created_at": CREATED,
                   "policy_version": "paper-account-v1", "starting_capital_rs": 1000000.0}

ICICI1, NORTHARC, FIXA, NIFTY = (STAGING_TRADES[1]["_id"], STAGING_TRADES[0]["_id"], STAGING_TRADES[5]["_id"],
                                 STAGING_TRADES[8]["_id"])


@pytest.fixture
def db() -> DB:
    d = DB()
    d[svc.TRADES].docs = copy.deepcopy(STAGING_TRADES)
    d[acct.LEDGER].docs = [{**r, "_id": f"led-{n}"} for n, r in enumerate(copy.deepcopy(STAGING_LEDGER))]
    d[acct.ACCOUNTS].docs = [copy.deepcopy(STAGING_ACCOUNT)]
    for c in d.cols.values():
        c.writes = 0
    return d


def plan_of(db: DB, decisions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    data = run(rec.load(db))
    return rec.build_plan(data["accounts"], data["ledger"], data["trades"], decisions)


def issue(plan, code, trade_id=None):
    found = [i for i in plan["issues"] if i["code"] == code and (trade_id is None or i["trade_id"] == trade_id)]
    assert len(found) == 1, (code, trade_id, [(i["code"], i["trade_id"]) for i in plan["issues"]])
    return found[0]


def account(db: DB) -> Dict[str, Any]:
    return db[acct.ACCOUNTS].docs[0]


def checks_ok(db: DB) -> bool:
    return all(r["ok"] for r in rec.check(run(rec.load(db))))


# ── RC-12: the staging-shaped book, end to end ───────────────────────────────
def test_rc12_the_staging_book_gives_exactly_the_known_discrepancies(db):
    plan = plan_of(db)
    assert plan["counts"]["by_code"] == {rec.OPEN_UNRESERVED: 1, rec.PNL_MISSING: 1, rec.PNL_NOT_IN_CASH: 2,
                                         rec.DUPLICATES: 2}
    icici = issue(plan, rec.OPEN_UNRESERVED, ICICI1)
    assert icici["resolution"] == rec.PROPOSED
    [e] = icici["entries"]
    assert (e["blocked_delta_rs"], e["cash_delta_rs"], e["key"]) == (124617.8, 0.0, f"reconcile:{rec.OPEN_UNRESERVED}:{ICICI1}")
    assert e["stamp"] == {"field": "paper_reserved_rs", "before": None, "after": 124617.8}
    assert "before the paper account existed" in icici["evidence"]["why"]

    for tid, net in ((NORTHARC, -5154.37), (FIXA, -40.1)):
        i = issue(plan, rec.PNL_NOT_IN_CASH, tid)
        assert i["resolution"] == rec.DECISION and i["entries"] == [] and i["evidence"]["closed_before_account"] is True
        assert {o["option"]: o["cash_delta_rs"] for o in i["options"]} == {"post_pnl": net, "exclude": 0.0}

    nifty = issue(plan, rec.PNL_MISSING, NIFTY)
    assert nifty["resolution"] == rec.DECISION and nifty["entries"] == []
    assert {o["option"]: o["cash_delta_rs"] for o in nifty["options"]} == {"costs_at_entry_marks": -91.56, "void": 0.0}
    assert "60 s after it was opened" in nifty["evidence"]["why"]

    dups = sorted((i["symbol"], i["evidence"]["count"]) for i in plan["issues"] if i["code"] == rec.DUPLICATES)
    assert dups == [("HAL", 3), ("ICICIBANK", 2)]
    assert all(i["resolution"] == rec.REVIEW and not i["entries"] for i in plan["issues"] if i["code"] == rec.DUPLICATES)

    [acc] = plan["accounts"]
    assert acc["before"]["I1_ok"] and acc["before"]["I2_ok"] and acc["before"]["I3_ok"] and not acc["before"]["I4_ok"]
    assert acc["after_proposed"]["ok"] and acc["after_proposed"]["blocked_rs"] == 249235.6
    assert acc["after_proposed"]["available_rs"] == 735311.68
    assert plan["entries"] == icici["entries"], "only the derivable entry is proposed"


# ── RC-1 … RC-5: each discrepancy type ───────────────────────────────────────
def test_rc1_an_open_strategy_without_a_reservation_reserves_its_capital_at_risk(db):
    t = copy.deepcopy(STAGING_TRADES[8])
    t.update(_id="strat-open-0000-0000", status="open", closed_at=None, net_pnl_rs=None)
    t.pop("paper_reserved_rs")
    db[svc.TRADES].docs.append(t)
    [e] = issue(plan_of(db), rec.OPEN_UNRESERVED, t["_id"])["entries"]
    assert e["blocked_delta_rs"] == 13000.0 and "capital at risk" in e["note"]          # (22800 − 22600) × 65


def test_rc4_a_reservation_left_on_a_closed_trade_or_on_no_trade_is_released(db):
    db[acct.LEDGER].docs.append({"_id": "led-x", "user_id": U, "action": "reserve", "amount_rs": 500.0,
                                 "trade_id": NORTHARC, "symbol": "NORTHARC"})
    db[acct.LEDGER].docs.append({"_id": "led-y", "user_id": U, "action": "reserve", "amount_rs": 700.0,
                                 "trade_id": "ghost-trade-0001", "symbol": "GHOST"})
    account(db)["blocked_rs"] += 1200.0
    plan = plan_of(db)
    assert issue(plan, rec.ORPHAN_RESERVATION, NORTHARC)["entries"][0]["blocked_delta_rs"] == -500.0
    assert issue(plan, rec.ORPHAN_RESERVATION, "ghost-trade-0001")["entries"][0]["blocked_delta_rs"] == -700.0
    assert plan["accounts"][0]["before"]["I2_ok"] and not plan["accounts"][0]["before"]["I3_ok"]
    assert plan["accounts"][0]["after_proposed"]["ok"]


def test_rc2_a_pnl_closed_after_the_account_with_no_release_is_proposed_when_the_ledger_is_whole(db):
    late = copy.deepcopy(STAGING_TRADES[0])
    late.update(_id="late-0000-0000-0001", closed_at="2026-10-25T10:00:00+00:00", net_pnl_rs=-100.0)
    db[svc.TRADES].docs.append(late)
    i = issue(plan_of(db), rec.PNL_NOT_IN_CASH, late["_id"])
    assert i["resolution"] == rec.PROPOSED and i["entries"][0]["cash_delta_rs"] == -100.0


# ── RC-6: the dry run writes nothing ─────────────────────────────────────────
def test_rc6_planning_and_the_cli_dry_run_write_nothing(db, monkeypatch):
    import deps
    from scripts import reconcile_paper_accounts as cli

    plan_of(db)
    monkeypatch.setattr(deps, "db", db)
    monkeypatch.setattr("sys.argv", ["reconcile_paper_accounts", "--no-evidence"])
    out = io.StringIO()
    with redirect_stdout(out):
        assert cli.main() == 0
    assert db.writes() == 0 and db.deletes() == 0
    text = out.getvalue()
    assert "DRY RUN" in text and "124,617.80" in text and "--decide ef61108b:closed_pnl_not_in_cash=<post_pnl|exclude>" in text
    # RC-14: users appear only hashed.
    assert U not in text and rec.hash_user(U) in text
    monkeypatch.setattr("sys.argv", ["reconcile_paper_accounts", "--json", "--no-evidence"])
    out = io.StringIO()
    with redirect_stdout(out):
        assert cli.main() == 0
    body = json.loads(out.getvalue())
    assert U not in out.getvalue() and body["counts"]["entries"] == 1 and db.writes() == 0


# ── RC-7 / RC-8: apply exactly the plan, once ────────────────────────────────
def test_rc7_apply_writes_exactly_the_proposed_entries(db):
    before = copy.deepcopy(account(db))
    plan = plan_of(db)
    report = run(rec.apply(db, plan, "run-1", snapshot="snap-1"))
    assert report["moved"] == [e["key"] for e in plan["entries"]] and not report["skipped"]
    adj = [r for r in db[acct.LEDGER].docs if r["action"] == acct.ADJUST]
    assert len(adj) == 1
    [row] = adj
    assert row["_id"] == row["idempotency_key"] == f"reconcile:{rec.OPEN_UNRESERVED}:{ICICI1}"
    assert (row["reason_code"], row["trade_id"], row["actor"], row["run_id"], row["snapshot"]) == (
        rec.OPEN_UNRESERVED, ICICI1, "reconcile", "run-1", "snap-1")
    assert (row["blocked_delta_rs"], row["cash_delta_rs"]) == (124617.8, 0.0)
    assert account(db)["blocked_rs"] == pytest.approx(before["blocked_rs"] + 124617.8)
    assert account(db)["cash_rs"] == before["cash_rs"]
    trade = next(t for t in db[svc.TRADES].docs if t["_id"] == ICICI1)
    assert trade["paper_reserved_rs"] == 124617.8 and trade["reconciliation"][0]["key"] == row["_id"]
    assert sum(1 for t in db[svc.TRADES].docs if t.get("reconciliation")) == 1, "only the reserved trade is stamped"
    assert checks_ok(db)


def test_rc8_a_second_apply_writes_nothing(db):
    run(rec.apply(db, plan_of(db), "run-1"))
    writes, acc = db.writes(), copy.deepcopy(account(db))
    again = plan_of(db)
    assert again["entries"] == []
    report = run(rec.apply(db, again, "run-2"))
    assert report["moved"] == [] and db.writes() == writes and account(db) == acc
    # Re-applying the SAME (stale) plan is a no-op too: the key on the account refuses it.
    stale = plan_of(DBFrom(STAGING_TRADES))
    report = run(rec.apply(db, stale, "run-3"))
    assert report["moved"] == [] and account(db)["blocked_rs"] == acc["blocked_rs"]


def DBFrom(trades) -> DB:
    d = DB()
    d[svc.TRADES].docs = copy.deepcopy(trades)
    d[acct.LEDGER].docs = [{**r, "_id": f"led-{n}"} for n, r in enumerate(copy.deepcopy(STAGING_LEDGER))]
    d[acct.ACCOUNTS].docs = [copy.deepcopy(STAGING_ACCOUNT)]
    return d


def test_rc8_a_crash_between_the_account_write_and_the_ledger_row_is_completed_without_moving_twice(db):
    plan = plan_of(db)
    db[acct.LEDGER].fail_next_insert = RuntimeError("process killed")
    with pytest.raises(RuntimeError):
        run(rec.apply(db, plan, "run-1"))
    moved_once = account(db)["blocked_rs"]
    assert not [r for r in db[acct.LEDGER].docs if r["action"] == acct.ADJUST], "the row is missing after the crash"
    assert not rec.check(run(rec.load(db)))[0]["I2_ok"], "and the daily check sees it"
    report = run(rec.apply(db, plan, "run-1"))
    assert report["already_applied"] == [plan["entries"][0]["key"]]
    assert account(db)["blocked_rs"] == moved_once
    assert len([r for r in db[acct.LEDGER].docs if r["action"] == acct.ADJUST]) == 1 and checks_ok(db)


# ── RC-13: owner decisions ───────────────────────────────────────────────────
def test_rc13_a_decision_adds_its_option_and_a_bad_one_is_refused(db):
    decided = plan_of(db, {f"{NORTHARC[:8]}:{rec.PNL_NOT_IN_CASH}": "post_pnl",
                           f"{FIXA[:8]}:{rec.PNL_NOT_IN_CASH}": "exclude",
                           f"{NIFTY[:8]}:{rec.PNL_MISSING}": "costs_at_entry_marks"})
    assert decided["decision_errors"] == []
    deltas = sorted((e["trade_id"], e["cash_delta_rs"]) for e in decided["entries"])
    assert deltas == sorted([(ICICI1, 0.0), (NORTHARC, -5154.37), (FIXA, 0.0), (NIFTY, -91.56)])
    after = decided["accounts"][0]["after_proposed"]
    assert after["ok"] and after["cash_rs"] == round(984547.28 - 5154.37 - 91.56, 2)

    bad = plan_of(db, {f"{NORTHARC[:8]}:{rec.PNL_NOT_IN_CASH}": "double_it", "ffffffff:closed_pnl_missing": "void"})
    assert len(bad["decision_errors"]) == 2 and len(bad["entries"]) == 1

    run(rec.apply(db, decided, "run-1"))
    assert checks_ok(db)
    later = plan_of(db)
    resolved = {(i["code"], i["trade_id"]) for i in later["issues"] if i["resolution"] == rec.RESOLVED}
    assert resolved == {(rec.PNL_NOT_IN_CASH, FIXA), (rec.PNL_MISSING, NIFTY)}, \
        "a decided entry closes the question, the zero-amount 'exclude' included"
    assert later["entries"] == [] and not [i for i in later["issues"] if i["resolution"] == rec.DECISION]


def test_rc13_the_cli_refuses_an_apply_whose_decision_does_not_match(db, monkeypatch):
    import deps
    from scripts import reconcile_paper_accounts as cli

    monkeypatch.setattr(deps, "db", db)
    monkeypatch.setattr("sys.argv", ["reconcile_paper_accounts", "--apply", "--run-id", "run-1", "--snapshot", "s1",
                                     "--no-evidence", "--decide", f"{NORTHARC[:8]}:{rec.PNL_NOT_IN_CASH}=nope"])
    with redirect_stdout(io.StringIO()):
        assert cli.main() == 3
    assert db.writes() == 0
    monkeypatch.setattr("sys.argv", ["reconcile_paper_accounts", "--apply", "--run-id", "run-1", "--no-evidence"])
    with pytest.raises(SystemExit), redirect_stdout(io.StringIO()):
        cli.main()                                    # no --snapshot
    assert db.writes() == 0


# ── RC-9 / RC-11: revert, and nothing is ever deleted ────────────────────────
def test_rc9_revert_adds_opposite_entries_and_restores_the_account(db):
    original = copy.deepcopy(account(db))
    rows_before = len(db[acct.LEDGER].docs)
    plan = plan_of(db, {f"{NORTHARC[:8]}:{rec.PNL_NOT_IN_CASH}": "post_pnl"})
    run(rec.apply(db, plan, "run-1"))
    report = run(rec.revert(db, "run-1", "revert-1"))
    assert sorted(report["moved"]) == sorted(f"revert:{e['key']}" for e in plan["entries"]) and not report["skipped"]
    assert account(db)["cash_rs"] == pytest.approx(original["cash_rs"])
    assert account(db)["blocked_rs"] == pytest.approx(original["blocked_rs"])
    assert len(db[acct.LEDGER].docs) == rows_before + 2 * len(plan["entries"]), "originals kept, reversals added"
    trade = next(t for t in db[svc.TRADES].docs if t["_id"] == ICICI1)
    assert trade["paper_reserved_rs"] is None and [h["reason_code"] for h in trade["reconciliation"]] == [
        rec.OPEN_UNRESERVED, rec.REVERT]
    writes = db.writes()
    assert run(rec.revert(db, "run-1", "revert-1"))["moved"] == [] and db.writes() == writes
    # After a revert the issue is open again, under a new key generation.
    again = issue(plan_of(db), rec.OPEN_UNRESERVED, ICICI1)
    assert again["entries"][0]["key"].endswith("#2")
    assert db.deletes() == 0


def test_rc9_a_reservation_whose_trade_closed_since_is_not_reversed_twice(db):
    run(rec.apply(db, plan_of(db), "run-1"))
    trade = next(t for t in db[svc.TRADES].docs if t["_id"] == ICICI1)
    stored, mine = run(svc.close_trade(db, trade, exit_reason="manual", exit_price=1400.2, exit_session=None))
    assert mine and stored["status"] == "closed"
    blocked_after_close = account(db)["blocked_rs"]
    report = run(rec.revert(db, "run-1", "revert-1"))
    assert report["moved"] == [] and len(report["skipped"]) == 1
    assert account(db)["blocked_rs"] == blocked_after_close and checks_ok(db)
    assert db.deletes() == 0


# ── RC-10: the invariant check catches what it cannot explain ─────────────────
def test_rc10_a_planted_cash_and_blocked_mismatch_is_reported_with_no_number(db):
    account(db)["cash_rs"] += 1.0
    account(db)["blocked_rs"] += 5.0
    [row] = rec.check(run(rec.load(db)))
    assert not row["I1_ok"] and not row["I2_ok"] and not row["ok"]
    plan = plan_of(db)
    for code in (rec.ACCOUNT_CASH, rec.ACCOUNT_BLOCKED):
        i = issue(plan, code)
        assert i["resolution"] == rec.DECISION and i["entries"] == [] and i["options"] == []


def test_rc10_the_cli_check_exits_2_on_a_mismatch_and_0_when_clean(db, monkeypatch):
    import deps
    from scripts import reconcile_paper_accounts as cli

    monkeypatch.setattr(deps, "db", db)
    monkeypatch.setattr("sys.argv", ["reconcile_paper_accounts", "--check"])
    with redirect_stdout(io.StringIO()):
        assert cli.main() == 2                                 # I4: one open trade holds no reservation
    run(rec.apply(db, plan_of(db), "run-1"))
    with redirect_stdout(io.StringIO()):
        assert cli.main() == 0


def test_rc_adjust_never_creates_an_account():
    d = DB()
    with pytest.raises(LookupError):
        run(acct.adjust(d, "nobody", key="k1", cash_delta=1.0, row={}))
    assert d[acct.ACCOUNTS].docs == [] and d[acct.LEDGER].docs == []


def test_rc7_a_trade_that_closed_after_the_plan_is_not_reserved(db):
    """The plan is read, then the position closes (a list read or the evening job) before --apply: reserving it now
    would block capital for a position that no longer exists. The entry is skipped and the account is untouched."""
    plan = plan_of(db)
    trade = next(t for t in db[svc.TRADES].docs if t["_id"] == ICICI1)
    run(svc.close_trade(db, copy.deepcopy(trade), exit_reason="manual", exit_price=1400.2, exit_session=None))
    blocked = account(db)["blocked_rs"]
    report = run(rec.apply(db, plan, "run-1"))
    assert report["moved"] == [] and report["skipped"][0]["key"] == plan["entries"][0]["key"]
    assert account(db)["blocked_rs"] == blocked and checks_ok(db)
    assert "reconciliation" not in next(t for t in db[svc.TRADES].docs if t["_id"] == ICICI1)
