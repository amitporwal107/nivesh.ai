"""Every entry path x every reason (Phase 1 criteria 1.1 acceptance; TESTCASES B M-1 to M-11, A U-3).

One account, one database, all six position-creating paths behind the real correlation middleware:
    P1 desk cash POST · P2 desk strategy POST · P3 journal create · P4 journal ENTRY fill · P5 AI-trader signals ·
    P6 AI-trader confirm
under the OWNER'S DEFAULT profile (0.5 / 3 / 10 / 25 / 2 / 4 / 10 / 1.5). First every path is shown to succeed with valid
inputs (the same risk policy, consistent decisions); then each reason is set up once and every applicable path must refuse
it: 409 (P5: the ticket is rejected, 200), NO trade / journal entry / fill written, the account's reservations, counters
and blocked funds UNCHANGED, and exactly ONE new risk_decisions row from the service carrying the reason code, the
policy version, a limits version and the request's correlation id. The flag `fno_risk_gate` is OFF throughout (U-3).

Harness: tests/test_ai_trader_execution.py's `world` (in-memory Mongo with the shared operator semantics, the clock at
Wednesday 2026-10-21 10:30 IST, MOCK end-of-day bars flat at each symbol's price) with the desk and journal routers
mounted on the same database. MOCK — not real data: FIXA..FIXD / FIXU, every price, lot and expiry are made up.
"""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any, Callable, Dict

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from core.correlation import CorrelationMiddleware
from deps import get_current_user
from routes import ai_trader as ai_route
from routes import desk_trading as desk_route
from routes import positional_journal as journal
from services import desk_strategy_trades as strat
from services import desk_trading as desk
from services import paper_account as acct
from services import risk_controls as rc
from services import risk_gate
from services.ai_trader import execution
from services.ai_trader.risk_governor import Decision, Intent
from services.risk_gate import reference
from tests.test_ai_trader_execution import NOW, candidate, strategy_record, world  # noqa: F401  (`world` is a fixture)

U = {"X-Test-User": "user_a"}
EXPIRY = "2026-10-29"
PATHS = ("P1_desk_cash", "P2_desk_strategy", "P3_journal_create", "P4_journal_fill", "P5_ai_signal", "P6_ai_confirm")
POLICY = "universal-risk-v1"


def leg(side, strike, price, lots=1):
    return {"kind": "option", "side": side, "lots": lots, "lot_size": 50, "entry_price": price, "expiry": EXPIRY,
            "strike": strike, "option_type": "call", "price_source": "MOCK"}


def strategy_body(legs=None, **over):
    body = {"kind": "strategy", "underlying": "FIXU", "direction": "bullish", "family": "bull_call_spread",
            "reference_price": 1000.0, "stop_underlying": 950.0, "target_underlying": 1150.0,
            "legs": legs or [leg("buy", 1000, 30), leg("sell", 1100, 10)],
            "signal": {"signal_at": "2026-10-20T10:00:00Z", "rule_version": "mock-rules v1",
                       "evidence_summary": "MOCK idea for the risk matrix."}}
    body.update(over)
    return body


@pytest.fixture
def h(world, monkeypatch, risk_mock_inputs):
    """The shared harness: one database behind the desk, journal and AI-trader routers, the owner's default profile."""
    db = world.db
    db["risk_profiles"].docs.clear()                                  # the owner's defaults apply
    world.prices.update({s: 1000.0 for s in ("FIXA", "FIXB", "FIXC", "FIXD", "FIXU", "FIXZ")})
    world.candidates = [candidate("FIXC", 1000.0)]
    monkeypatch.setattr(desk_route, "db", db)
    monkeypatch.setattr(journal, "db", db)
    monkeypatch.setattr(rc, "_indexes_ready", False)
    monkeypatch.setattr(rc, "utcnow", lambda: NOW)

    async def user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(desk_route, "get_current_user", user)
    monkeypatch.setattr(journal, "get_current_user", user)

    async def flag_off(_db, _user):
        return False
    monkeypatch.setattr(risk_gate, "enabled_for", flag_off)

    async def lookup(underlying, expiries, today):
        return {e: {"listed": True, "lot_size": 50, "source": reference.BHAVCOPY_SOURCE, "as_of": "2026-10-20",
                    "error": None} for e in expiries}
    monkeypatch.setattr(reference, "lookup", lookup)

    async def no_fno_rows(underlying, leg_, start):
        return []                                                     # no F&O session rows on record
    monkeypatch.setattr(strat, "fetch_contract_rows", no_fno_rows)

    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)
    for r in (desk_route.router, journal.router, ai_route.router):
        app.include_router(r)
    app.dependency_overrides[get_current_user] = user
    world.client = TestClient(app)
    world.inputs = risk_mock_inputs
    # P4 needs a journal trade (recorded before Phase 1: no plan) and P6 an assisted ticket awaiting confirmation.
    db["trade_journal"].docs.append({"_id": "j1", "user_id": "user_a", "nse_symbol": "FIXB", "capital_alloc_rs": 20000.0,
                                     "stop_loss": 950.0, "target": 1150.0, "fills": [], "status": "OPEN",
                                     "opened_at": "2026-10-19T04:00:00+00:00"})
    paper = strategy_record(stage="paper", sid="strat-p")
    assisted = strategy_record(stage="assisted", sid="strat-a")
    db.strategies.docs.extend([paper, assisted])
    intent = Intent(symbol="FIXD", quantity=40, entry_price=1000.0, stop_price=950.0, target_price=1150.0)
    ticket = execution.new_ticket("user_a", assisted, intent, Decision("approve", 40, 40, []), as_of="2026-10-20",
                                  mode="assisted", now=NOW)
    ticket["_id"] = "tk1"
    db.tickets.docs.append(ticket)
    return world


def post_path(h, path: str, cid: str, over: Dict[str, Any]):
    headers = {**U, "X-Correlation-ID": cid}
    c = h.client
    if path == "P1_desk_cash":
        body = {"symbol": "FIXA", "quantity": 20, "entry_price": 1000.0, "stop_price": 950.0, "target_price": 1150.0}
        body.update(over.get("cash", {}))
        return c.post("/api/desk/paper-trades", json=body, headers=headers)
    if path == "P2_desk_strategy":
        return c.post("/api/desk/paper-trades", json=strategy_body(**over.get("strategy", {})), headers=headers)
    if path == "P3_journal_create":
        body = {"nse_symbol": "FIXA", "capital_alloc_rs": 20000, "stop_loss": 950, "target": 1150}
        body.update(over.get("journal", {}))
        return c.post("/api/positional/journal", json=body, headers=headers)
    if path == "P4_journal_fill":
        body = {"stage": "PILOT", "qty": 10, "price": 1000, "kind": "ENTRY"}
        body.update(over.get("fill", {}))
        return c.post("/api/positional/journal/j1/fill", json=body, headers=headers)
    if path == "P5_ai_signal":
        if "spec" in over:
            h.db.strategies.docs[0]["spec"]["exit"].update(over["spec"])
        return c.post("/api/ai-trader/strategies/strat-p/signals", json={"as_of": "2026-10-20", "mode": "paper"},
                      headers=headers)
    if path == "P6_ai_confirm":
        if "ticket" in over:
            h.db.tickets.docs[0].update(over["ticket"])
        return c.post("/api/ai-trader/tickets/tk1/confirm", headers=headers)
    raise AssertionError(path)


def state(h) -> Dict[str, Any]:
    """What a refusal must leave untouched: positions, fills, tickets' status, and the whole paper account."""
    acc = copy.deepcopy(h.db[acct.ACCOUNTS].docs)
    for a in acc:
        a.pop("updated_at", None)
        a.pop("equity_peak_rs", None)                                 # the peak may be raised by any read
        a.pop("equity_peak_at", None)
    return {"trades": len(h.db.trades.docs), "journal": len(h.db["trade_journal"].docs),
            "fills": [len(d.get("fills") or []) for d in h.db["trade_journal"].docs],
            "ai_trades": sum(1 for t in h.db.trades.docs if (t.get("source") or {}).get("kind") == "ai_trader"),
            "account": acc}


def service_rows(h):
    return [r for r in h.db[rc.DECISIONS].docs if r.get("source") == "risk_service"]


# ── baseline: every path succeeds under the same policy with valid inputs ────
@pytest.mark.parametrize("path", PATHS)
def test_valid_inputs_pass_every_path_and_are_recorded_and_reserved(h, path):
    r = post_path(h, path, f"corr-ok-{path}", {})
    assert r.status_code in (200, 201), r.text
    (row,) = service_rows(h)
    assert row["outcome"] in ("allowed", "reduced") and row["policy_version"] == POLICY
    assert row["correlation_id"] == f"corr-ok-{path}" and row["limits_version"].startswith("rp-0-")
    if path == "P5_ai_signal":
        assert r.json()["tickets"][0]["status"] == "executed_paper"
    acc = h.db[acct.ACCOUNTS].docs[0]
    assert acct.reservation_invariants(acc) == [] and len(acc["reservations"]) == 1     # reserved, and consistent


# ── the reasons ──────────────────────────────────────────────────────────────
def _kill(h):
    h.db[rc.CONTROLS].docs.append({"user_id": "user_a", "kill_switch": True, "halted": False, "reason": "MOCK stop"})


def _tiny_budget(h):
    from tests.risk_helpers import loose_profile_doc
    from services import risk_profile
    h.db["risk_profiles"].docs.append({**loose_profile_doc("user_a"),
                                       "limits": {**risk_profile.NAMED[risk_profile.OWNER_DEFAULT], "per_trade_risk_pct": 0.05}})


def _account(h, **fields):
    h.db[acct.ACCOUNTS].docs.append({"user_id": "user_a", "cash_rs": 1_000_000.0, "blocked_rs": 0.0,
                                     "starting_capital_rs": 1_000_000.0, **fields})


def _open_risk_full(h):
    _account(h, open_risk_rs=30_000.0)                                # 3% of Rs 10 lakh already reserved


def _sector_full(h):
    _account(h, exposure_rs=250_000.0, sector_rs={"MOCK_SECTOR": 250_000.0}, reservations=[
        {"id": "r-sector", "trade_id": "t-elsewhere", "store": desk.TRADES, "kind": "cash", "symbol": "OTHER",
         "sector": "MOCK Sector", "sector_key": "MOCK_SECTOR", "risk_rs": 0.0, "exposure_rs": 250_000.0, "funding_rs": 0.0,
         "positions": 0, "at": NOW.isoformat()}])


def _closed(h, *, closed_at: str, net: float, symbol: str = "FIXZ"):
    doc = desk.new_trade("user_a", {"symbol": symbol, "quantity": 100, "entry_price": 1000.0, "stop_price": 900.0,
                                    "target_price": 1300.0}, NOW)
    doc.update(status="closed", opened_at=closed_at, closed_at=closed_at, exit_price=1000.0 + net / 100,
               realized_pnl_rs=net, net_pnl_rs=net, exit_reason="stop", open_key=None)
    h.db.trades.docs.append(doc)


def _daily_loss(h):
    _closed(h, closed_at=(NOW - timedelta(hours=1)).isoformat(), net=-25_000.0)          # today: 2.4% of start-of-day


def _weekly_loss(h):
    _closed(h, closed_at="2026-10-19T05:00:00+00:00", net=-45_000.0)                    # Monday: 4.3% of start-of-week


def _drawdown(h):
    _account(h, equity_peak_rs=1_200_000.0)                           # equity Rs 10 lakh: 16.7% below the peak


def _unmarked_structure(h):
    doc = strat.new_strategy_trade("user_a", strategy_body(legs=[leg("buy", 1050, 20), leg("sell", 1150, 5)]), NOW)
    doc["opened_at"] = "2026-10-14T04:00:00+00:00"                     # sessions since, and no F&O marks on record
    doc["open_key"] = strat.structure_key(doc)
    h.db.trades.docs.append(doc)


def _stale_market(h):
    h.inputs["market_as_of"] = "2026-10-13"                            # 5 sessions before the reference session


def _no_funds(h):
    _account(h, blocked_rs=999_900.0)                                 # Rs 100 available


REASONS: Dict[str, Dict[str, Any]] = {
    "M1_kill_switch": dict(setup=_kill, code="kill_switch_on", paths=PATHS),
    "M2_min_qty_over_budget": dict(setup=_tiny_budget, code=("min_qty_exceeds_budget", "min_lot_exceeds_budget"),
                                   paths=PATHS, over={"cash": {"stop_price": 450.0, "target_price": 2200.0},
                                                      "journal": {"stop_loss": 450, "target": 2200},
                                                      "spec": {"stoploss_pct": 55.0},
                                                      "ticket": {"stop_price": 450.0, "target_price": 2200.0}},
                                   extra_ok={"P4_journal_fill": "fill", }),
    "M3_open_risk": dict(setup=_open_risk_full, code="open_risk_exceeded", paths=PATHS),
    "M4_sector": dict(setup=_sector_full, code="sector_exceeded",
                      paths=("P1_desk_cash", "P2_desk_strategy", "P3_journal_create", "P5_ai_signal", "P6_ai_confirm")),
    "M5_daily_loss": dict(setup=_daily_loss, code="daily_loss_halt", paths=PATHS),
    "M6_weekly_loss": dict(setup=_weekly_loss, code="weekly_loss_halt", paths=PATHS),
    "M7_drawdown": dict(setup=_drawdown, code="drawdown_halt", paths=PATHS),
    "M8_drawdown_unknown": dict(setup=_unmarked_structure, code="drawdown_unknown", paths=PATHS),
    "M9_stale_market": dict(setup=_stale_market, code="market_state_stale", paths=PATHS),
    "M10_funds": dict(setup=_no_funds, code="insufficient_paper_funds",
                      paths=("P1_desk_cash", "P2_desk_strategy", "P3_journal_create", "P4_journal_fill",
                             "P5_ai_signal", "P6_ai_confirm")),
    "M11_reward_risk": dict(setup=lambda h: None, code=("reward_risk_too_low", "RR_TOO_LOW"),
                            paths=("P1_desk_cash", "P2_desk_strategy", "P3_journal_create", "P5_ai_signal"),
                            over={"cash": {"target_price": 1020.0}, "journal": {"target": 1020},
                                  "strategy": {"legs": [leg("buy", 1000, 60), leg("sell", 1050, 15)]},
                                  "spec": {"target_rr": 0.5}}),
}
CASES = [(reason, path) for reason, spec in REASONS.items() for path in spec["paths"]]


@pytest.mark.parametrize("reason,path", CASES, ids=[f"{r}-{p}" for r, p in CASES])
def test_every_path_refuses_every_reason_writes_nothing_and_records_one_decision(h, reason, path):
    spec = REASONS[reason]
    spec["setup"](h)
    if path == "P4_journal_fill" and reason == "M2_min_qty_over_budget":
        h.db["trade_journal"].docs[0]["stop_loss"] = 450.0            # the plan's stop: one share risks > Rs 500
    before = state(h)
    rows_before = len(service_rows(h))
    cid = f"corr-{reason}-{path}"
    r = post_path(h, path, cid, spec.get("over", {}))
    if path == "P5_ai_signal":
        assert r.status_code == 200, r.text
        (ticket,) = r.json()["tickets"]
        assert ticket["status"] == "rejected" and ticket["trade_id"] is None
    else:
        assert r.status_code == 409, r.text
    after = state(h)
    assert after["trades"] == before["trades"] and after["journal"] == before["journal"]
    assert after["fills"] == before["fills"] and after["ai_trades"] == before["ai_trades"]
    assert after["account"] == before["account"], "a refusal must leave no reservation and no funds blocked"
    new = service_rows(h)[rows_before:]
    assert len(new) == 1, [x.get("outcome") for x in new]
    row = new[0]
    wanted = spec["code"] if isinstance(spec["code"], tuple) else (spec["code"],)
    got = [x["code"] for x in row["reasons"]]
    assert row["outcome"] == "blocked" and any(c in got for c in wanted), (wanted, got)
    assert row["policy_version"] == POLICY and row["limits_version"] and row["correlation_id"] == cid
    assert row["path"] == {"P1_desk_cash": "desk_paper_trade", "P2_desk_strategy": "desk_paper_trade",
                           "P3_journal_create": "journal_create", "P4_journal_fill": "journal_fill",
                           "P5_ai_signal": "ai_trader_signal", "P6_ai_confirm": "ai_trader_confirm"}[path]


def test_a_reduce_on_the_desk_writes_nothing_and_names_the_size_that_fits(h):
    """A desk POST above the budget is not resized behind the user's back: 409 risk_reduce with the approved size."""
    r = post_path(h, "P1_desk_cash", "corr-reduce", {"cash": {"quantity": 500}})       # Rs 5 lakh: 50% of equity
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_reduce"
    d = r.json()["detail"]
    assert d["requested_qty"] == 500 and 0 < d["approved_qty"] < 500 and d["reasons"]
    assert h.db.trades.docs == [] and (not h.db[acct.ACCOUNTS].docs or h.db[acct.ACCOUNTS].docs[0]["reservations"] == [])
    again = post_path(h, "P1_desk_cash", "corr-reduce-2", {"cash": {"quantity": d["approved_qty"]}})
    assert again.status_code == 201, again.text
