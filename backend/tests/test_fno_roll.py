"""F&O carry-forward roll (option C): RL-1 … RL-8 of test_reports/p2_trade_plan_lifecycle_TESTCASES.md.

The roll runs through the real routes (routes/desk_trading.py), services/fno_roll.py, the strategy simulator, the
desk cost card and the paper account, with the in-memory Mongo of tests/test_desk_trading.py.

MOCK — not real data: the NIFTY chain below. It is shaped exactly as GET /v1/fno/{symbol}?on=… and
GET /v1/fno/{symbol}/history send nidp.fno_bhavcopy rows. On the 2026-10-27 expiry day every expiring option's
`settle_price` is the UNDERLYING's settlement price (22753.2), as the idea-persistence study measured on staging
(56 of 56 legs): a roll that read it would book a 22,000-rupee premium. The roll must use `close_price`. Before the
roll session the spread trades between its premium stop and its premium target 1 (stored at entry, evaluated by the exit
rules since feat/p2-exits-backtest), so no rule closes it first.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import pytest

from routes import desk_trading as route
from services import desk_trading as svc
from services import paper_account as acct
from services import risk_controls as rc
from services import fno_roll as roll
from services.positional_engine import session_calendar
from tests.test_desk_trading import A, TRADES_URL, api, world  # noqa: F401  (fixtures)

OPENED = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)            # Tue 20 Oct, 10:30 IST
ROLL_EVENING = datetime(2026, 10, 27, 17, 0, tzinfo=timezone.utc)     # Tue 27 Oct, 22:30 IST: after the 22:15 F&O ingest
OLD_EXPIRY, NEXT_EXPIRY = "2026-10-27", "2026-11-03"
U_D = 22690.0


def frow(day, expiry, strike, ot, close, settle=None, underlying=U_D, lot=75):
    return {"as_of_date": day, "ticker_symbol": "NIFTY", "instrument_type": "IDO" if ot else "IDF", "expiry_date": expiry,
            "strike_price": strike, "option_type": ot, "close_price": close, "settle_price": settle if settle is not None else close,
            "underlying_price": underlying, "new_board_lot_qty": lot}


def day_rows(day="2026-10-27", missing=()):
    expiry_day = day == OLD_EXPIRY                 # on the expiry day an option's settle_price is the UNDERLYING's
    rows = [frow(day, OLD_EXPIRY, 22600.0, "CE", 90.5, settle=U_D if expiry_day else None),
            frow(day, OLD_EXPIRY, 22800.0, "CE", 0.5, settle=U_D if expiry_day else None),
            frow(day, OLD_EXPIRY, None, None, 22692.0)]
    for k in range(22500, 23251, 50):
        if float(k) in missing:
            continue
        rows.append(frow(day, NEXT_EXPIRY, float(k), "CE", round(max(5.0, 300.0 - (k - 22500) * 0.5), 2)))
        rows.append(frow(day, NEXT_EXPIRY, float(k), "PE", round(max(5.0, 50.0 + (k - 22500) * 0.5), 2)))
    return rows


def body():
    return {"kind": "strategy", "underlying": "NIFTY", "direction": "bullish", "family": "bull_call_spread",
            "reference_price": 22500.0, "stop_underlying": 22300.0, "target_underlying": 22900.0,
            "legs": [{"kind": "option", "side": "buy", "lots": 1, "lot_size": 75, "entry_price": 120.0, "expiry": OLD_EXPIRY,
                      "strike": 22600.0, "option_type": "call", "price_source": "NSE F&O bhavcopy close, 2026-10-19"},
                     {"kind": "option", "side": "sell", "lots": 1, "lot_size": 75, "entry_price": 40.0, "expiry": OLD_EXPIRY,
                      "strike": 22800.0, "option_type": "call", "price_source": "NSE F&O bhavcopy close, 2026-10-19"}],
            "signal": {"signal_at": "2026-10-19", "rule_version": "regime-fit-v1 (2026-10-22)", "evidence_summary": "MOCK idea"}}


@pytest.fixture
def chain(world, monkeypatch):
    """The data platform for the roll: the day's F&O rows, each contract's history, and no NIFTY share bars."""
    state: Dict[str, Any] = {"day": {"2026-10-27": day_rows()}, "calls": []}

    async def fake_get(path: str, params=None, timeout: float = 10.0, *, creds=None):
        params = params or {}
        state["calls"].append((path, dict(params)))
        if path.startswith("/prices/eod/"):
            return {"data": [], "count": 0, "pagination": {"limit": params.get("limit"), "offset": 0, "next_offset": None}}
        if path == "/fno/NIFTY/history":
            out = []
            for day in ("2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"):
                for r in state["day"].get(day) or day_rows(day):
                    if (str(r["expiry_date"]) == params["expiry"] and r["option_type"] == params.get("option_type")
                            and r["strike_price"] == params.get("strike") and day >= params["start"]):
                        out.append(r)
            return {"data": out, "count": len(out), "pagination": {"limit": params["limit"], "offset": 0, "next_offset": None}}
        if path == "/fno/NIFTY":
            data = state["day"].get(params["on"], [])
            return {"data": data, "count": len(data), "pagination": {"limit": params["limit"], "offset": 0, "next_offset": None}}
        raise AssertionError(f"unexpected read {path}")
    monkeypatch.setattr(svc.daas_client, "_get", fake_get)

    async def holidays(year):              # MOCK — no NSE holiday in these weeks
        return {date(year, 12, 25): "Christmas"}
    monkeypatch.setattr(session_calendar, "holidays_for_year", holidays)

    from services.risk_gate import reference

    async def lookup(underlying, expiries, today):        # MOCK — the exchange lot the gate-off path checks
        return {e: {"listed": True, "lot_size": 75, "source": reference.BHAVCOPY_SOURCE, "as_of": "2026-10-27", "error": None} for e in expiries}
    monkeypatch.setattr(reference, "lookup", lookup)
    world.state = state
    return world


def open_old(api, world) -> str:
    world.now = OPENED
    r = api.post(TRADES_URL, json=body(), headers=A)
    assert r.status_code == 201, r.text
    world.now = ROLL_EVENING
    return r.json()["trade"]["id"]


def roll_url(tid):
    return f"{TRADES_URL}/{tid}/roll"


# ── RL-1 / RL-5 / RL-7: the roll on the expiry evening ───────────────────────
def test_a_roll_closes_both_legs_at_the_close_and_opens_the_same_structure_on_the_next_expiry(api, chain):
    tid = open_old(api, chain)
    pre = api.get(roll_url(tid), headers=A).json()
    assert pre["eligible"] is True, pre
    p = pre["preview"]
    assert p["session"] == "2026-10-27" and p["sessions_to_expiry"] == 0
    assert [l["close"] for l in p["old"]["legs"]] == [90.5, 0.5]                       # close_price, never the 22690 settle
    # distance mode: 22600 + (22690 - 22500) = 22790 -> the nearest listed strike 22800: every strike +200
    assert p["strike_shift"] == 200.0 and [l["strike"] for l in p["new"]["legs"]] == [22800.0, 23000.0]
    assert p["new"]["expiry"] == NEXT_EXPIRY and [l["entry_price"] for l in p["new"]["legs"]] == [150.0, 50.0]
    assert p["costs"]["new_model"] == "desk-cost-v2" and p["costs"]["new_round_trip_estimate"]["total"] > 0
    assert p["costs"]["old_round_trip"]["total"] > 0
    assert len(chain.db.trades.docs) == 1                                               # the preview wrote nothing

    r = api.post(roll_url(tid), json={}, headers=A)
    assert r.status_code == 201, r.text
    old, new = (next(d for d in chain.db.trades.docs if d["_id"] == i) for i in (tid, r.json()["new"]["id"]))
    assert old["status"] == "closed" and old["exit_reason"] == "roll" and old["exit_session"] == "2026-10-27"
    assert [(l["exit_mark"], l["mark_basis"]) for l in old["exit_legs"]] == [(90.5, "roll_close"), (0.5, "roll_close")]
    assert old["realized_pnl_rs"] == round((90.5 - 120.0) * 75 - (0.5 - 40.0) * 75, 2)
    assert old["costs_breakdown"]["total"] > 0 and old["state"] == "CLOSED"
    assert [t["to"] for t in old["transitions"]][-2:] == ["EXIT_PENDING", "CLOSED"] and old["transitions"][-1]["source"] == "roll"
    # the link, both ways, and the plan's lineage
    assert old["rolled_to"] == new["_id"] and new["rolled_from"]["trade_id"] == tid
    assert new["signal"]["source_refs"][0] == {"kind": "rolled_from", "ref": tid, "as_of": "2026-10-27"}
    plan = next(d for d in chain.db["trade_plans"].docs if d["_id"] == new["trade_plan_id"])
    assert plan["lineage"]["rolled_from_trade_id"] == tid and plan["source"]["kind"] == "roll"
    assert [(l["strike"], l["expiry"], l["entry_price"], l["lots"], l["lot_size"]) for l in new["legs"]] == [
        (22800.0, NEXT_EXPIRY, 150.0, 1, 75), (23000.0, NEXT_EXPIRY, 50.0, 1, 75)]
    assert new["family"] == "bull_call_spread" and new["direction"] == "bullish" and new["reference_price"] == U_D
    assert (new["stop_underlying"], new["target_underlying"]) == (22300.0, 22900.0)      # carried: still on the right side
    assert new["state"] == "POSITION_OPEN" and new["transitions"][0]["source"] == "roll"
    assert new["exit_plan"]["options"]["status"] in ("ok", "unavailable")
    old_plan = old["exit_plan"]["options"]                  # the premium plan stored at the old entry did not fire first
    assert old_plan["status"] == "ok" and old_plan["planned_stop"] < 90.5 - 0.5 < old_plan["target_1"]
    acc = run_read(chain)
    assert acc["blocked_rs"] == new["paper_reserved_rs"]                                # the old reservation was released


def run_read(world):
    return asyncio.run(acct.read(world.db, "user_a"))


# ── RL-4: double click ───────────────────────────────────────────────────────
def test_a_double_click_rolls_once_and_answers_the_same_pair(api, chain):
    tid = open_old(api, chain)
    first = api.post(roll_url(tid), json={}, headers=A)
    second = api.post(roll_url(tid), json={}, headers={**A, "Idempotency-Key": "another-key-123"})
    assert first.status_code == 201 and second.status_code == 200 and second.json()["replayed"] is True
    assert second.json()["new"]["id"] == first.json()["new"]["id"]
    assert len(chain.db.trades.docs) == 2
    assert sum(1 for r in chain.db[acct.LEDGER].docs if r.get("action") == "reserve") == 2      # old + new, never a third


# ── RL-2: before the F&O bhavcopy is in ──────────────────────────────────────
def test_before_the_days_bhavcopy_is_in_the_roll_is_refused_and_nothing_changes(api, chain):
    tid = open_old(api, chain)
    chain.state["day"]["2026-10-27"] = []
    pre = api.get(roll_url(tid), headers=A).json()
    assert pre["eligible"] is False and pre["refusal"]["code"] == "roll_chain_not_ready" and "22:15 IST" in pre["refusal"]["message"]
    r = api.post(roll_url(tid), json={}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "roll_chain_not_ready"
    assert [d["status"] for d in chain.db.trades.docs] == ["open"]


# ── RL-3: a strike that is not listed ────────────────────────────────────────
def test_a_strike_not_listed_on_the_next_expiry_is_refused_by_name(api, chain):
    tid = open_old(api, chain)
    chain.state["day"]["2026-10-27"] = day_rows(missing=(23000.0,))
    r = api.post(roll_url(tid), json={}, headers=A)
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "strike_not_listed" and d["strike"] == 23000.0 and "23000" in d["message"]
    assert [x["status"] for x in chain.db.trades.docs] == ["open"]


def test_same_strike_mode_keeps_the_strikes(api, chain):
    tid = open_old(api, chain)
    p = api.get(roll_url(tid) + "?strike_mode=same", headers=A).json()["preview"]
    assert p["strike_shift"] == 0.0 and [l["strike"] for l in p["new"]["legs"]] == [22600.0, 22800.0]


# ── RL-6: the same risk checks as any entry ──────────────────────────────────
def test_the_kill_switch_refuses_a_roll_and_the_old_trade_stays_open(api, chain):
    tid = open_old(api, chain)
    asyncio.run(rc.set_control(chain.db, "user_a", field="kill_switch", value=True, reason="test", actor="user_a"))
    r = api.post(roll_url(tid), json={}, headers=A)
    assert r.status_code == 409
    assert [d["status"] for d in chain.db.trades.docs] == ["open"]
    assert chain.db[rc.DECISIONS].docs[-1]["detail"]["lifecycle"]["to"] == "REJECTED"


def test_a_roll_the_account_cannot_fund_is_refused_before_anything_closes(api, chain):
    tid = open_old(api, chain)
    chain.db[acct.ACCOUNTS].docs[0]["cash_rs"] = 100.0                                     # MOCK: a nearly empty account
    r = api.post(roll_url(tid), json={}, headers=A)
    # Phase 1: the roll's new structure is judged by the universal risk service before anything closes; with Rs 100 of
    # cash the funds (and the per-trade budget) refuse it there.
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_blocked"
    assert "insufficient_paper_funds" in [x["code"] for x in r.json()["detail"]["reasons"]]
    assert [d["status"] for d in chain.db.trades.docs] == ["open"]


# ── RL-8: not due, not a strategy, already closed ────────────────────────────
def test_a_trade_far_from_expiry_is_not_due(api, chain):
    tid = open_old(api, chain)
    chain.now = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)                     # 5 sessions before the expiry
    chain.state["day"]["2026-10-20"] = day_rows("2026-10-20")
    r = api.post(roll_url(tid), json={}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "roll_not_due" and r.json()["detail"]["sessions_to_expiry"] == 5


def test_a_cash_trade_or_a_closed_trade_cannot_roll(api, chain):
    chain.db.trades.docs.append({"_id": "cash1", "user_id": "user_a", "symbol": "FIXA", "status": "open"})   # MOCK share trade
    r = api.post(roll_url("cash1"), json={}, headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_a_strategy_trade"
    chain.db.trades.docs.clear()
    tid = open_old(api, chain)
    chain.db.trades.docs[0]["status"] = "closed"
    assert api.post(roll_url(tid), json={}, headers=A).json()["detail"]["code"] == "trade_already_closed"
    assert api.post(roll_url("nope"), json={}, headers=A).status_code == 404
    assert api.post(roll_url(tid), json={"strike_mode": "wide"}, headers=A).status_code == 422


# ── the pure rules ───────────────────────────────────────────────────────────
def test_sessions_to_expiry_counts_nse_sessions_only():
    hol = {date(2026, 11, 10): "MOCK holiday"}
    assert roll.sessions_to(date(2026, 11, 6), date(2026, 11, 11), hol) == 2            # Mon 9, (Tue 10 holiday), Wed 11
    assert roll.roll_session(date(2026, 10, 31), hol) == date(2026, 10, 30)               # Saturday -> Friday
    assert roll.roll_session(date(2026, 11, 10), hol) == date(2026, 11, 9)


def test_an_exit_the_rules_took_before_the_roll_wins():
    d = date(2026, 10, 27)
    assert roll.exit_before_roll({"exit": {"exit_reason": "expiry", "exit_session": d}}, d) is None
    assert roll.exit_before_roll({"exit": {"exit_reason": "stop", "exit_session": d}}, d)["exit_reason"] == "stop"
    assert roll.exit_before_roll({"exit": None}, d) is None


# ── Phase 1: the roll is judged by the universal risk service (feat/p1-universal-risk) ──────────────────────────
def test_p1_the_rolls_new_structure_is_decided_by_the_risk_service_and_reserved_after_the_old_one_closes(api, chain):
    """The new structure is decided on path desk_paper_roll against the book WITHOUT the one it replaces
    (replaces_trade_id), recorded, and reserved only after the old one closed: the account then holds exactly one
    reservation, the new trade's, and its counters equal its entries."""
    tid = open_old(api, chain)
    r = api.post(roll_url(tid), json={}, headers=A)
    assert r.status_code == 201, r.text
    new_id = r.json()["new"]["id"]
    rows = [d for d in chain.db[rc.DECISIONS].docs if d.get("source") == "risk_service"]
    roll_rows = [d for d in rows if d["path"] == "desk_paper_roll"]
    assert len(roll_rows) == 1 and roll_rows[0]["outcome"] == "allowed"
    assert roll_rows[0]["snapshot"]["request"]["replaces_trade_id"] == tid
    new = next(d for d in chain.db.trades.docs if d["_id"] == new_id)
    assert new["risk_reservation_id"] == roll_rows[0]["_id"] and new["risk_policy_version"] == "universal-risk-v2"
    (account,) = chain.db[acct.ACCOUNTS].docs
    assert [e["trade_id"] for e in account["reservations"]] == [new_id]
    assert acct.reservation_invariants(account) == []
