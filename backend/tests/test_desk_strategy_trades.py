"""Smart trading desk — instrument-aware paper trades: futures and option strategies (PRD §17.2 #7, §17.6, §17.7).

Covers services/desk_strategy_trades.py and the strategy branches of routes/desk_trading.py. Same harness as
test_desk_trading.py (in-memory Mongo, the clock fixed at 2026-10-12 10:30 IST, a fake data platform); on top of it
the fake serves GET /v1/fno/{symbol}/history the way the data platform's contract_history route does.

MOCK — not real data: the FIXU underlying, its bars and its option/futures rows are made up. Every expected figure
is worked out by hand below from those rows, not read back from the code.

The worked example (a bull call spread, 1 lot of 250 on FIXU, expiry 2026-10-27, reference 1215, stop 1180, target 1400):
    leg 0  buy  call 1300 at 40      leg 1  sell call 1360 at 15
    net premium at entry = −40 × 250 + 15 × 250 = −10,000 + 3,750 = −₹6,250 (a debit)
    session 13 Oct   marks 50 / 20   P&L = (50 − 40) × 250 − (20 − 15) × 250 = 2,500 − 1,250 = +1,250
    session 14 Oct   marks 30 / 10   P&L = (30 − 40) × 250 − (10 − 15) × 250 = −2,500 + 1,250 = −1,250
    session 15 Oct   marks 110 / 60  P&L = 70 × 250 − 45 × 250 = 17,500 − 11,250 = +6,250   (high 1405 ≥ target 1400)
    MFE = +6,250, MAE = −1,250 · mark premium = −110 × 250 + 60 × 250 = −12,500
    costs (0.05% of the traded value + ₹20 a side, each leg):
        entry  40×250×0.0005 = 5.00 · 15×250×0.0005 = 1.875 · brokerage 2 × 20 = 40      → 46.875
        exit   110×250×0.0005 = 13.75 · 60×250×0.0005 = 7.50 · brokerage 40              → 61.25
        total 108.125 · net = 6,250 − 108.125 = 6,141.875
    expiry settlement, underlying closing 1,330 on 27 Oct: 1300 call = 30, 1360 call = 0
        P&L = (30 − 40) × 250 − (0 − 15) × 250 = −2,500 + 3,750 = +1,250
"""
from __future__ import annotations

import copy
from datetime import date
from typing import Any, Dict, List, Optional

import pytest

from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services import paper_account as acct
from services.copilot_tools import daas_client
from services.risk_gate import reference
from tests.test_desk_trading import (  # noqa: F401  (`world` and `api` are fixtures)
    A, B, NOW, TRADES_URL, api, bar, open_trade, trade_body, trades, world,
)

EXPIRY = "2026-10-27"


def obar(day: str, open_: float, high: float, low: float, close: float) -> Dict[str, Any]:
    row = bar(day, high, low, close)
    row["open_price"] = open_
    return row


def crow(day: str, settle: Optional[float], close: Optional[float] = None, underlying: Optional[float] = None) -> Dict[str, Any]:
    """One /v1/fno/{symbol}/history row (the columns contract_history selects)."""
    return {"as_of_date": day, "settle_price": settle, "close_price": close, "prev_close_price": None,
            "underlying_price": underlying, "ticker_symbol": "FIXU", "expiry_date": EXPIRY}


# MOCK — not real data
UNDERLYING = [
    obar("2026-10-12", 1210, 1230, 1200, 1215),
    obar("2026-10-13", 1220, 1250, 1205, 1240),
    obar("2026-10-14", 1240, 1260, 1190, 1195),
    obar("2026-10-15", 1250, 1405, 1240, 1400),
]
CALL_1300 = [crow("2026-10-13", 50, 49), crow("2026-10-14", 30, 29), crow("2026-10-15", 110, 109)]
CALL_1360 = [crow("2026-10-13", 20, 19), crow("2026-10-14", 10, 9), crow("2026-10-15", 60, 59)]


def call(side: str, strike: float, price: float, lots: int = 1, **over) -> Dict[str, Any]:
    leg = {"kind": "option", "side": side, "lots": lots, "lot_size": 250, "entry_price": price, "expiry": EXPIRY,
           "strike": strike, "option_type": "call", "price_source": "NSE F&O bhavcopy close, 2026-10-09"}
    leg.update(over)
    return leg


def put(side: str, strike: float, price: float, lots: int = 1) -> Dict[str, Any]:
    return call(side, strike, price, lots, option_type="put")


def future(side: str, price: float, lots: int = 1) -> Dict[str, Any]:
    return {"kind": "future", "side": side, "lots": lots, "lot_size": 250, "entry_price": price, "expiry": EXPIRY,
            "strike": None, "option_type": None, "price_source": "NSE F&O bhavcopy settle, 2026-10-09"}


def signal(**over) -> Dict[str, Any]:
    s = {"signal_at": "2026-10-12T03:30:00Z", "rule_version": "strategy-rules v1.0", "model_version": None,
         "source_refs": [{"kind": "scanner", "ref": "FIXU-2026-10-12", "as_of": "2026-10-09"}],
         "evidence_summary": "Futures long build-up with the stock above its 20-day high."}
    s.update(over)
    return s


def strategy_body(**over) -> Dict[str, Any]:
    body = {"kind": "strategy", "underlying": "FIXU", "direction": "bullish", "family": "bull_call_spread",
            "reference_price": 1215.0, "stop_underlying": 1180.0, "target_underlying": 1400.0,
            "legs": [call("buy", 1300, 40), call("sell", 1360, 15)], "signal": signal(), "strategy_plan_id": "plan-1"}
    body.update(over)
    return body


@pytest.fixture
def sworld(world, monkeypatch):
    """`world` plus the F&O history read: rows by (kind, strike, option_type), served the way the route does."""
    world.rows["FIXU"] = copy.deepcopy(UNDERLYING)
    world.contracts = {("option", 1300.0, "CE"): copy.deepcopy(CALL_1300), ("option", 1360.0, "CE"): copy.deepcopy(CALL_1360)}
    world.history_fail = None
    world.history_calls = []
    prices_get = daas_client._get

    async def fake_get(path: str, params=None, timeout: float = 10.0, *, creds=None):
        if not path.startswith("/fno/"):
            return await prices_get(path, params, timeout)
        assert path.endswith("/history"), f"the desk read {path}"
        world.history_calls.append(dict(params))
        if world.history_fail:
            raise world.history_fail
        key = (params["kind"], params.get("strike"), params.get("option_type"))
        rows = [r for r in world.contracts.get(key, []) if r["as_of_date"] >= params["start"]]
        return {"data": sorted(rows, key=lambda r: r["as_of_date"]), "count": len(rows),
                "pagination": {"limit": params["limit"], "offset": params["offset"], "total": None, "next_offset": None}}

    monkeypatch.setattr(svc.daas_client, "_get", fake_get)

    # The exchange lot the desk checks every structure against when the F&O risk gate is off
    # (strat.check_exchange_lots → services/risk_gate/reference.lookup). MOCK — not real data: FIXU's lot is 250.
    world.lots = {EXPIRY: 250, "2026-11-24": 250}
    world.lot_lookups = []

    async def lookup(underlying, expiries, today):
        world.lot_lookups.append((underlying, sorted(expiries)))
        return {e: ({"listed": True, "lot_size": world.lots[e], "source": reference.BHAVCOPY_SOURCE, "as_of": "2026-10-09",
                     "error": None} if world.lots.get(e) else
                    {"listed": None, "lot_size": None, "source": None, "as_of": None, "error": "the data platform could not be read"})
                for e in expiries}
    monkeypatch.setattr(reference, "lookup", lookup)
    return world


def post_strategy(api, who=A, **over):
    return api.post(TRADES_URL, json=strategy_body(**over), headers=who)


def open_strategy(api, who=A, **over) -> Dict[str, Any]:
    r = post_strategy(api, who, **over)
    assert r.status_code == 201, r.text
    return r.json()["trade"]


def only_strategy(body: Dict[str, Any]) -> Dict[str, Any]:
    [row] = [t for t in body["trades"] if t["kind"] == "strategy"]
    return row


# ── create: the schema ───────────────────────────────────────────────────────
def test_create_stores_the_strategy_with_its_legs_signal_and_lifecycle(api, sworld):
    t = open_strategy(api)
    assert t["kind"] == "strategy" and t["rules_version"] == "desk-paper-v3"
    assert (t["underlying"], t["direction"], t["family"], t["strategy_plan_id"]) == ("FIXU", "bullish", "bull_call_spread", "plan-1")
    assert t["summary_text"] == "Bull call spread 1300/1360 · 27 Oct · 1 lot"
    assert [leg["label"] for leg in t["legs"]] == ["Buy 1 lot call 1300 27 Oct", "Sell 1 lot call 1360 27 Oct"]
    assert t["signal"]["evidence_summary"].startswith("Futures long build-up") and t["signal"]["rule_version"] == "strategy-rules v1.0"
    assert t["signal"]["signal_at"] == "2026-10-12T03:30:00+00:00"
    assert t["net_premium_rs"] == -6250.0                       # −40 × 250 + 15 × 250
    assert t["mark_premium_rs"] is None and t["gross_pnl_rs"] is None      # no session after the opening one is read yet
    assert t["entry_record_intact"] is True and len(t["entry_record_hash"]) == 64
    assert t["cost_model"]["slippage_pct_per_side"] == 0.05 and t["cost_model"]["brokerage_rs_per_side"] == 20.0
    [doc] = sworld.db.trades.docs
    assert doc["kind"] == "strategy" and [e["type"] for e in doc["events"]] == ["created", "entered"]
    assert doc["risk"]["defined_risk"] is True


def test_a_document_without_kind_stays_a_cash_trade_and_kind_cash_is_accepted(api, sworld):
    cash = open_trade(api)
    assert cash["kind"] == "cash" and cash["rules_version"] == "desk-paper-v2"
    # Another symbol: a second open FIXA trade would be refused as a duplicate.
    r = api.post(TRADES_URL, json=trade_body(kind="cash", symbol="FIXB", entry_price=500.0, stop_price=480.0,
                                             target_price=520.0), headers=A)
    assert r.status_code == 201 and r.json()["trade"]["rules_version"] == "desk-paper-v2"
    assert "kind" not in sworld.db.trades.docs[0]               # the stored share document is not changed
    r = api.post(TRADES_URL, json=trade_body(kind="swing"), headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_kind")


BAD = [
    ("no legs", dict(legs=[]), "invalid_leg_count"),
    ("five legs", dict(legs=[call("buy", 1300 + 10 * i, 10) for i in range(5)]), "invalid_leg_count"),
    ("naked short call", dict(family="custom", legs=[call("sell", 1360, 15)]), "unbounded_loss"),
    ("short calls above the long", dict(family="custom", legs=[call("buy", 1300, 40), call("sell", 1360, 15, lots=2)]), "unbounded_loss"),
    ("naked short put", dict(family="custom", direction="bullish", legs=[put("sell", 1200, 12)]), "naked_short_put"),
    ("short future with a short call", dict(family="custom", legs=[future("sell", 1215), call("sell", 1300, 20)]), "unbounded_loss"),
    # TESTCASES F-2 (study A probe D1): a short future alone was accepted and stamped defined_risk: True.
    ("short future only", dict(family="short_future", direction="bearish", stop_underlying=1250.0, target_underlying=1150.0,
                               legs=[future("sell", 1215)]), "short_futures_not_supported"),
    # TESTCASES F-3: a future's loss is not capped by the structure, so the plan's stop on the underlying is required.
    ("long future without a stop", dict(family="long_future", stop_underlying=None, legs=[future("buy", 1215)]),
     "futures_stop_required"),
    ("mixed option expiries", dict(family="custom", legs=[call("buy", 1300, 40), call("sell", 1360, 15, expiry="2026-11-24")]), "mixed_option_expiries"),
    ("cash only", dict(family="custom", legs=[{"kind": "cash", "side": "buy", "lots": 10, "lot_size": 1, "entry_price": 1215.0,
                                              "expiry": None, "strike": None, "option_type": None, "price_source": "NSE end of day"}]),
     "cash_only_use_share_trade"),
    ("short cash", dict(family="custom", legs=[call("buy", 1300, 40), {"kind": "cash", "side": "sell", "lots": 10, "lot_size": 1,
                                                                       "entry_price": 1215.0, "expiry": None, "strike": None,
                                                                       "option_type": None, "price_source": "NSE end of day"}]),
     "short_cash_not_supported"),
    ("family not on the list", dict(family="wizard"), "invalid_family"),
    ("direction", dict(direction="sideways"), "invalid_direction"),
    ("stop above the reference (bullish)", dict(stop_underlying=1250.0), "stop_not_below_reference"),
    ("target below the reference (bullish)", dict(target_underlying=1200.0), "target_not_above_reference"),
    ("neutral with a level", dict(direction="neutral", target_underlying=None), "levels_not_supported_neutral"),
    ("conditional entry", dict(entry_rule="break_above"), "entry_rule_not_supported"),
    ("unknown entry rule", dict(entry_rule="whenever"), "invalid_entry_rule"),
    ("unknown field", dict(leverage=5), "unknown_field"),
    ("no signal", dict(signal=None), "invalid_signal"),
    ("signal without evidence", dict(signal=signal(evidence_summary="  ")), "invalid_evidence_summary"),
    ("signal in the future", dict(signal=signal(signal_at="2026-10-13T03:30:00Z")), "invalid_signal_at"),
    ("signal without a rule version", dict(signal=signal(rule_version=None)), "invalid_rule_version"),
    ("expired contract", dict(legs=[call("buy", 1300, 40, expiry="2026-10-09"), call("sell", 1360, 15, expiry="2026-10-09")]), "expiry_in_past"),
    ("option without a strike", dict(legs=[call("buy", None, 40), call("sell", 1360, 15)]), "invalid_strike"),
    ("future with a strike", dict(family="long_future", legs=[dict(future("buy", 1215), strike=1200.0)]), "invalid_future_leg"),
    ("zero lots", dict(legs=[call("buy", 1300, 40, lots=0), call("sell", 1360, 15)]), "invalid_lots"),
    ("no price source", dict(legs=[call("buy", 1300, 40, price_source=None), call("sell", 1360, 15)]), "invalid_price_source"),
    ("zero premium", dict(legs=[call("buy", 1300, 0), call("sell", 1360, 15)]), "invalid_entry_price"),
    ("max hold", dict(max_hold_sessions=0), "invalid_max_hold"),
]


@pytest.mark.parametrize("name,over,code", BAD, ids=[b[0] for b in BAD])
def test_a_bad_strategy_is_refused_with_its_code_and_nothing_is_stored(api, sworld, name, over, code):
    r = post_strategy(api, **over)
    detail = r.json()["detail"]
    # The newer refusals carry {code, message}; the older ones the bare code.
    assert (r.status_code, detail if isinstance(detail, str) else detail["code"]) == (422, code)
    assert sworld.db.trades.docs == []


GOOD = [
    ("long future", dict(family="long_future", legs=[future("buy", 1215)])),
    ("long put", dict(family="long_put", direction="bearish", stop_underlying=1250.0, target_underlying=1150.0, legs=[put("buy", 1200, 25)])),
    ("bull put spread", dict(family="bull_put_spread", legs=[put("sell", 1200, 25), put("buy", 1150, 10)])),
    ("iron condor", dict(family="iron_condor", direction="neutral", stop_underlying=None, target_underlying=None,
                         legs=[put("buy", 1100, 5), put("sell", 1150, 12), call("sell", 1300, 14), call("buy", 1350, 6)])),
    ("covered long future hedged by a call", dict(family="hedged_future", legs=[future("sell", 1215), call("buy", 1300, 20)],
                                                   direction="bearish", stop_underlying=1250.0, target_underlying=1150.0)),
]


@pytest.mark.parametrize("name,over", GOOD, ids=[g[0] for g in GOOD])
def test_defined_risk_structures_and_a_plain_futures_leg_are_accepted(api, sworld, name, over):
    t = open_strategy(api, **over)
    # TESTCASES F-1, F-7: any futures leg is NOT defined risk (it used to say True for a future, short ones included).
    has_future = any(leg["kind"] == "future" for leg in t["legs"])
    has_option = any(leg["kind"] == "option" for leg in t["legs"])
    assert t["risk"]["defined_risk"] is (not has_future) and t["risk"]["futures_exposure"] is has_future
    assert t["risk"]["note"] == ((strat.FUTURES_HEDGED_NOTE if has_option else strat.UNBOUNDED_NOTE) if has_future else None)


def test_strategy_trades_count_against_the_open_limit_with_share_trades(api, sworld):
    for i in range(99):                                          # 99 symbols: one symbol twice is now a duplicate
        sworld.db.trades.docs.append({**svc.new_trade("user_a", trade_body(symbol=f"FX{i}"), NOW), "_id": f"t{i}"})
    open_strategy(api)                                           # the 100th
    r = post_strategy(api, legs=[call("buy", 1310, 35), call("sell", 1370, 12)])   # another structure: not a duplicate
    assert (r.status_code, r.json()["detail"]) == (409, "open_trade_limit")
    r = api.post(TRADES_URL, json=trade_body(), headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "open_trade_limit")


# ── marks, P&L and the exit rules ────────────────────────────────────────────
def test_an_open_strategy_is_marked_leg_by_leg_on_the_bhavcopy(api, sworld):
    open_strategy(api)
    sworld.contracts[("option", 1300.0, "CE")] = CALL_1300[:1]            # only 13 Oct is read so far
    sworld.contracts[("option", 1360.0, "CE")] = CALL_1360[:1]
    sworld.rows["FIXU"] = UNDERLYING[:2]
    body = trades(api)
    t = only_strategy(body)
    assert t["status"] == "open"
    assert [(leg["mark"], leg["mark_date"], leg["mark_basis"]) for leg in t["legs"]] == [
        (50.0, "2026-10-13", "settle"), (20.0, "2026-10-13", "settle")]
    assert [leg["pnl_rs"] for leg in t["legs"]] == [2500.0, -1250.0]        # (50−40)×250 and −(20−15)×250
    assert t["gross_pnl_rs"] == 1250.0 and t["unrealized_pnl_rs"] == 1250.0
    assert t["mark_premium_rs"] == -7500.0                                  # −50 × 250 + 20 × 250
    assert t["costs_rs"] == pytest.approx(5 + 1.875 + 40 + 50 * 250 * 0.0005 + 20 * 250 * 0.0005 + 40, abs=0.01)
    assert t["net_pnl_rs"] == pytest.approx(1250.0 - t["costs_rs"], abs=0.01)
    assert t["costs_basis"].startswith("entry and exit sides")
    assert (t["mfe_rs"], t["mae_rs"], t["held_sessions"], t["checked_through"]) == (1250.0, 1250.0, 1, "2026-10-13")
    assert body["summary"]["open"] == 1 and body["summary"]["unrealized_pnl_rs"] == 1250.0
    assert sworld.history_calls[0]["kind"] == "option" and sworld.history_calls[0]["option_type"] == "CE"


def test_the_target_on_the_underlying_closes_every_leg_at_the_session_marks(api, sworld):
    open_strategy(api)
    body = trades(api)
    t = only_strategy(body)
    assert (t["status"], t["exit_reason"], t["exit_session"]) == ("closed", "target", "2026-10-15")
    assert [leg["mark"] for leg in t["legs"]] == [110.0, 60.0]
    assert [leg["pnl_rs"] for leg in t["legs"]] == [17500.0, -11250.0]
    assert t["gross_pnl_rs"] == 6250.0 and t["realized_pnl_rs"] == 6250.0 and t["unrealized_pnl_rs"] is None
    assert t["costs_rs"] == pytest.approx(108.125, abs=0.01)
    assert t["net_pnl_rs"] == pytest.approx(6141.875, abs=0.01)
    assert (t["mfe_rs"], t["mae_rs"], t["held_sessions"]) == (6250.0, -1250.0, 3)
    assert t["mark_premium_rs"] == -12500.0
    assert "exit_marked_at_session_marks" in [f["code"] for f in t["flags"]]
    assert body["summary"]["closed"] == 1 and body["summary"]["realized_pnl_rs"] == 6250.0
    assert body["summary"]["net_realized_pnl_rs"] == pytest.approx(6141.875, abs=0.01)


def test_exits_are_idempotent_and_the_lifecycle_log_records_state_changes_only(api, sworld):
    open_strategy(api)
    trades(api)
    writes = sworld.db.trades.writes
    again = only_strategy(trades(api))
    assert sworld.db.trades.writes == writes                      # the second read writes nothing
    assert again["status"] == "closed" and again["exit_reason"] == "target"
    [doc] = sworld.db.trades.docs
    assert [e["type"] for e in doc["events"]] == ["created", "entered", "exit_rule_fired", "closed"]
    assert doc["events"][2]["reason"] == "target" and doc["events"][2]["session"] == "2026-10-15"


def test_a_stop_and_a_target_in_one_session_count_as_the_stop_and_a_gap_is_flagged(api, sworld):
    open_strategy(api)
    sworld.rows["FIXU"] = [UNDERLYING[0], obar("2026-10-13", 1170, 1410, 1170, 1300)]       # opened below the stop, high above the target
    t = only_strategy(trades(api))
    assert (t["exit_reason"], t["exit_session"]) == ("stop", "2026-10-13")
    codes = [f["code"] for f in t["flags"]]
    assert "both_in_range" in codes and "gap_through_stop" in codes
    assert t["gross_pnl_rs"] == 1250.0                            # the legs close at the 13 Oct marks, not at the stop price


def test_a_bearish_trade_is_stopped_when_the_high_reaches_the_stop(api, sworld):
    sworld.contracts[("option", 1200.0, "PE")] = [crow("2026-10-13", 20), crow("2026-10-14", 12)]
    open_strategy(api, direction="bearish", family="long_put", reference_price=1215.0, stop_underlying=1250.0,
                  target_underlying=1150.0, legs=[put("buy", 1200, 25)])
    sworld.rows["FIXU"] = [UNDERLYING[0], obar("2026-10-13", 1220, 1235, 1205, 1210), obar("2026-10-14", 1215, 1252, 1210, 1240)]
    t = only_strategy(trades(api))
    assert (t["exit_reason"], t["exit_session"]) == ("stop", "2026-10-14")
    assert t["gross_pnl_rs"] == -3250.0                           # (12 − 25) × 250


def test_options_expire_at_intrinsic_value_against_the_underlying_close(api, sworld):
    open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0)
    sworld.rows["FIXU"] = [UNDERLYING[0], obar("2026-10-13", 1220, 1250, 1205, 1240), obar(EXPIRY, 1320, 1340, 1310, 1330)]
    sworld.contracts[("option", 1300.0, "CE")] = [crow("2026-10-13", 50), crow(EXPIRY, 31, 30.5, underlying=1330)]
    sworld.contracts[("option", 1360.0, "CE")] = [crow("2026-10-13", 20), crow(EXPIRY, 2, 1.5, underlying=1330)]
    t = only_strategy(trades(api))
    assert (t["status"], t["exit_reason"], t["exit_session"]) == ("closed", "expiry", EXPIRY)
    assert [(leg["mark"], leg["mark_basis"]) for leg in t["legs"]] == [(30.0, "expiry_intrinsic"), (0.0, "expiry_intrinsic")]
    assert t["gross_pnl_rs"] == 1250.0                            # (30 − 40) × 250 − (0 − 15) × 250
    assert [f["leg"] for f in t["flags"] if f["code"] == "expiry_settled"] == [0, 1]
    assert t["legs"][0]["mark_basis_text"].startswith("settled at intrinsic value")


def test_a_long_put_settles_at_strike_minus_the_close_and_a_future_at_its_final_settle():
    # Pure rule, no routes: put 1300 bought at 30 → underlying 1250 → (1300 − 1250) = 50 → (50 − 30) × 250 = +5,000;
    # future bought at 1215, final settle 1260 → (1260 − 1215) × 250 = +11,250.
    doc = strat.new_strategy_trade("u", strategy_body(       # a futures leg needs a stop; 1200 is never touched here
        family="custom", direction="bullish", stop_underlying=1200.0, target_underlying=None,
        legs=[put("buy", 1300, 30), future("buy", 1215)]), NOW)
    bars = [{"date": date(2026, 10, 27), "open": 1255.0, "high": 1262.0, "low": 1245.0, "close": 1250.0, "volume": 1.0, "series": "EQ"}]
    rows = [[crow(EXPIRY, 49, 49, underlying=1250)], [crow(EXPIRY, 1260, 1259, underlying=1250)]]
    sim = strat.simulate_strategy(doc, bars, rows)
    assert [(s["mark"], s["mark_basis"]) for s in sim["legs"]] == [(50.0, "expiry_intrinsic"), (1260.0, "final_settle")]
    assert sim["gross_pnl_rs"] == 16250.0 and sim["exit"]["exit_reason"] == "expiry"


def test_a_leg_with_no_row_keeps_its_last_mark_and_is_flagged_never_filled_in(api, sworld):
    open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0)
    sworld.rows["FIXU"] = UNDERLYING[:3]
    sworld.contracts[("option", 1360.0, "CE")] = CALL_1360[:1]                  # no 1360 row on 14 Oct
    t = only_strategy(trades(api))
    assert [leg["mark"] for leg in t["legs"]] == [30.0, 20.0] and t["legs"][1]["mark_date"] == "2026-10-13"
    assert [(f["code"], f["leg"], f["session"]) for f in t["flags"] if f["code"] == "no_mark"] == [("no_mark", 1, "2026-10-14")]
    # 1300: (30 − 40) × 250 = −2,500 · 1360 kept at 20: −(20 − 15) × 250 = −1,250  → −3,750
    assert t["gross_pnl_rs"] == -3750.0


def test_a_leg_that_never_printed_leaves_the_strategy_without_a_pnl(api, sworld):
    open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0)
    sworld.rows["FIXU"] = UNDERLYING[:3]
    sworld.contracts[("option", 1360.0, "CE")] = []
    body = trades(api)
    t = only_strategy(body)
    assert t["legs"][1]["mark"] is None and t["legs"][1]["pnl_rs"] is None
    assert t["gross_pnl_rs"] is None and t["costs_rs"] is None and t["net_pnl_rs"] is None and t["mark_premium_rs"] is None
    assert body["summary"]["unrealized_pnl_rs"] is None and body["summary"]["unmarked_open"] == 1


def test_the_time_exit_closes_at_the_marks_of_the_last_session_held(api, sworld):
    open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0, max_hold_sessions=2)
    t = only_strategy(trades(api))
    assert (t["exit_reason"], t["exit_session"], t["held_sessions"]) == ("time", "2026-10-14", 2)
    assert t["gross_pnl_rs"] == -1250.0


def test_underlying_bars_missing_means_no_stop_check_and_a_flag(api, sworld):
    open_strategy(api)
    sworld.rows["FIXU"] = []
    t = only_strategy(trades(api))
    assert "underlying_bars_missing" in [f["code"] for f in t["flags"]]
    assert t["status"] == "open" and t["gross_pnl_rs"] == 6250.0           # marks still come from the bhavcopy rows


def test_prices_unavailable_keeps_the_trade_listed_with_no_marks(api, sworld):
    open_strategy(api)
    sworld.history_fail = daas_client.DaasError("down", status_code=503)
    body = trades(api)
    t = only_strategy(body)
    assert t["status"] == "open" and t["mark_error"] == "prices_unavailable"
    assert t["gross_pnl_rs"] is None and all(leg["mark"] is None for leg in t["legs"])
    assert body["marks_error"] == "prices_unavailable"
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (503, "prices_unavailable")
    assert sworld.db.trades.docs[0]["status"] == "open"


# ── closing ──────────────────────────────────────────────────────────────────
def test_closing_by_hand_uses_the_last_marks_and_nothing_else(api, sworld):
    t = open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0)
    sworld.rows["FIXU"] = UNDERLYING[:3]
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert r.status_code == 200, r.text
    c = r.json()["trade"]
    assert (c["status"], c["exit_reason"], c["exit_session"]) == ("closed", "manual", "2026-10-14")
    assert c["gross_pnl_rs"] == -1250.0 and c["realized_pnl_rs"] == -1250.0
    assert [e["type"] for e in c["events"]] == ["created", "entered", "closed"]
    assert api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A).status_code == 409
    again = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert again.json()["detail"] == "trade_already_closed"


def test_a_typed_exit_price_is_refused_for_a_strategy_and_other_users_get_404(api, sworld):
    t = open_strategy(api)
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 10}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "unknown_field")
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=B)
    assert (r.status_code, r.json()["detail"]) == (404, "trade_not_found")
    assert trades(api, B)["trades"] == []
    assert api.get(f"{TRADES_URL}/{t['id']}", headers=B).status_code == 404
    assert api.get(f"{TRADES_URL}/{t['id']}").status_code == 401


def test_closing_by_hand_when_the_rules_already_fired_answers_409_and_records_that_exit(api, sworld):
    t = open_strategy(api)
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "trade_already_closed")
    assert sworld.db.trades.docs[0]["exit_reason"] == "target"


# ── the single-trade read and "no retroactive changes" ───────────────────────
def test_the_single_trade_read_returns_the_signal_legs_and_lifecycle_and_writes_nothing(api, sworld):
    t = open_strategy(api)
    writes = sworld.db.trades.writes
    r = api.get(f"{TRADES_URL}/{t['id']}", headers=A)
    assert r.status_code == 200, r.text
    d = r.json()["trade"]
    assert d["signal"] == t["signal"] and [e["type"] for e in d["events"]] == ["created", "entered"]
    assert d["status"] == "open" and d["pending_exit"]["exit_reason"] == "target" and d["pending_exit"]["exit_session"] == "2026-10-15"
    assert d["gross_pnl_rs"] == 6250.0
    assert sworld.db.trades.writes == writes and sworld.db.trades.docs[0]["status"] == "open"     # read-only
    trades(api)                                                    # the list read records the exit
    d = api.get(f"{TRADES_URL}/{t['id']}", headers=A).json()["trade"]
    assert d["status"] == "closed" and d["pending_exit"] is None
    assert [e["type"] for e in d["events"]] == ["created", "entered", "exit_rule_fired", "closed"]


def test_the_single_trade_read_works_for_a_share_trade_too(api, sworld):
    t = open_trade(api)
    d = api.get(f"{TRADES_URL}/{t['id']}", headers=A).json()["trade"]
    assert d["kind"] == "cash" and [e["type"] for e in d["events"]] == ["created", "entered"]
    assert api.get(f"{TRADES_URL}/nope", headers=A).status_code == 404


def test_the_signal_and_the_entry_legs_can_never_be_changed_by_any_route(api, sworld, monkeypatch):
    t = open_strategy(api)
    before = copy.deepcopy(sworld.db.trades.docs[0])
    keys_written: List[set] = []
    original = sworld.db.trades.update_one

    async def spy(query, update):
        keys_written.append(set(update["$set"]))
        return await original(query, update)

    monkeypatch.setattr(sworld.db.trades, "update_one", spy)
    url = f"{TRADES_URL}/{t['id']}"
    attempts = [api.put(url, json={"signal": {"evidence_summary": "rewritten"}}, headers=A),
                api.patch(url, json={"legs": []}, headers=A),
                api.delete(url, headers=A),
                api.post(url, json={"signal": {}}, headers=A),
                api.post(f"{url}/close", json={"signal": {"evidence_summary": "rewritten"}}, headers=A),
                api.post(f"{url}/close", json={"legs": []}, headers=A),
                api.post(TRADES_URL, json=strategy_body(_id=t["id"]), headers=A)]
    assert [r.status_code for r in attempts] == [405, 405, 405, 405, 422, 422, 422]
    assert sworld.db.trades.docs == [before]                       # not a byte changed
    # The only write the service makes is the closing one, and it never names the immutable parts.
    trades(api)
    assert keys_written and all(not (k & {"signal", "legs", "underlying", "direction", "family", "reference_price",
                                         "stop_underlying", "target_underlying", "entry_record_hash", "opened_at"})
                                for k in keys_written)
    closed = sworld.db.trades.docs[0]
    for key in ("signal", "legs", "underlying", "direction", "family", "reference_price", "stop_underlying",
                "target_underlying", "entry_record_hash", "opened_at"):
        assert closed[key] == before[key]
    assert strat.record_hash(closed) == closed["entry_record_hash"]


def test_tampering_with_a_stored_leg_shows_in_the_record_check(api, sworld):
    t = open_strategy(api)
    sworld.db.trades.docs[0]["legs"][0]["entry_price"] = 1.0       # what a direct database edit would do
    d = api.get(f"{TRADES_URL}/{t['id']}", headers=A).json()["trade"]
    assert d["entry_record_intact"] is False


# ── both kinds together, and the cash rules left alone ───────────────────────
def test_the_list_carries_both_kinds_and_the_share_rules_ignore_strategy_documents(api, sworld):
    cash = open_trade(api, symbol="FIXA")
    s = open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0)
    body = trades(api)
    kinds = {t["id"]: t["kind"] for t in body["trades"]}
    assert kinds == {cash["id"]: "cash", s["id"]: "strategy"}
    assert body["summary"]["open"] == 2 and body["summary"]["closed"] == 0
    shares = [t for t in body["trades"] if t["kind"] == "cash"]
    assert shares[0]["rules_version"] == "desk-paper-v2" and body["rules_version"] == "desk-paper-v2"
    assert body["strategy_rules_version"] == "desk-paper-v3"
    calls = {c["symbol"] for c in sworld.calls}
    assert calls == {"FIXA", "FIXU"}                              # the share rule read FIXA only; FIXU came from the strategy read


def test_the_evening_check_script_path_leaves_strategy_trades_to_their_own_rules(sworld):
    import asyncio
    doc = strat.new_strategy_trade("u", strategy_body(), NOW)
    out, counts = asyncio.run(svc.apply_trade_exits(sworld.db, [doc], {"FIXU": [], }))
    assert out == [doc] and counts["paths"] == {}


# ── the paper account: a closed structure returns what it reserved ───────────
# The worked spread reserves its capital at risk, the strike span × the quantity: (1360 − 1300) × 250 = ₹15,000.
def _account(db, uid: str = "user_a") -> Dict[str, Any]:
    import asyncio
    return asyncio.run(acct.read(db, uid))


def _releases(db) -> List[Dict[str, Any]]:
    return [r for r in db[acct.LEDGER].docs if r["action"] == "release"]


def test_a_manual_close_returns_the_reservation_and_books_the_net_pnl(api, sworld):
    open_strategy(api, stop_underlying=1100.0, target_underlying=1500.0)
    assert sworld.db.trades.docs[0]["paper_reserved_rs"] == 15000.0
    assert _account(sworld.db)["blocked_rs"] == 15000.0
    sworld.rows["FIXU"] = UNDERLYING[:3]
    assert api.post(f"{TRADES_URL}/{sworld.db.trades.docs[0]['_id']}/close", json={}, headers=A).status_code == 200
    stored = sworld.db.trades.docs[0]
    # 14 Oct marks 30 / 10: gross −1,250; costs 46.875 + (30 + 10) × 250 × 0.0005 + 40 = 91.875; net −1,341.875
    assert stored["net_pnl_rs"] == pytest.approx(-1341.875, abs=0.01)
    a = _account(sworld.db)
    assert a["blocked_rs"] == 0.0
    assert a["cash_rs"] == pytest.approx(acct.DEFAULT_CAPITAL + stored["net_pnl_rs"], abs=0.01)
    [rel] = _releases(sworld.db)
    assert (rel["amount_rs"], rel["net_pnl_rs"], rel["trade_id"]) == (15000.0, stored["net_pnl_rs"], stored["_id"])


def test_an_exit_rule_close_returns_the_reservation_too(api, sworld):
    open_strategy(api)
    trades(api)                                                    # the list read fires the target (15 Oct)
    stored = sworld.db.trades.docs[0]
    assert (stored["status"], stored["exit_reason"]) == ("closed", "target")
    assert stored["net_pnl_rs"] == pytest.approx(6141.875, abs=0.01)  # 6,250 − 108.125
    a = _account(sworld.db)
    assert a["blocked_rs"] == 0.0 and a["cash_rs"] == pytest.approx(acct.DEFAULT_CAPITAL + 6141.875, abs=0.01)
    trades(api)                                                    # a second read changes nothing
    assert len(_releases(sworld.db)) == 1


def test_two_closes_racing_release_the_capital_once(api, sworld):
    """A manual close and an exit-rule close holding the same open copy: the status in the filter lets one win, and
    only the winner releases."""
    import asyncio
    open_strategy(api)
    doc = copy.deepcopy(sworld.db.trades.docs[0])
    _, sims, _ = asyncio.run(strat.apply_exits(sworld.db, [doc], persist=False))
    sim = sims[doc["_id"]]
    first = asyncio.run(strat.close_strategy_trade(sworld.db, doc, **sim["exit"], sim=sim))
    second = asyncio.run(strat.close_strategy_trade(sworld.db, doc, exit_reason="manual", exit_session=None,
                                                    exit_note=None, sim=sim))
    assert first[1] is True and second[1] is False
    assert second[0]["exit_reason"] == "target"                    # the first close stands
    assert len(_releases(sworld.db)) == 1
    a = _account(sworld.db)
    assert a["blocked_rs"] == 0.0 and a["cash_rs"] == pytest.approx(acct.DEFAULT_CAPITAL + 6141.875, abs=0.01)


def test_a_structure_opened_before_the_account_existed_releases_nothing_but_books_its_pnl(sworld):
    import asyncio
    doc = strat.new_strategy_trade("user_a", strategy_body(), NOW)  # no paper_reserved_rs, as an old trade
    asyncio.run(sworld.db.trades.insert_one(doc))
    _, sims, _ = asyncio.run(strat.apply_exits(sworld.db, [doc], persist=False))
    _, mine = asyncio.run(strat.close_strategy_trade(sworld.db, doc, **sims[doc["_id"]]["exit"], sim=sims[doc["_id"]]))
    assert mine is True
    a = _account(sworld.db)
    assert a["blocked_rs"] == 0.0, "the account must not be credited for a reservation it never took"
    assert a["cash_rs"] == pytest.approx(acct.DEFAULT_CAPITAL + 6141.875, abs=0.01)


def test_a_close_with_an_unknown_pnl_returns_the_reservation_and_assumes_no_pnl(api, sworld):
    """A stop on a session before a leg's first row: that leg has no mark, so the structure has no P&L. The capital
    comes back; cash is not moved by a figure nobody knows."""
    import asyncio
    open_strategy(api)
    doc = copy.deepcopy(sworld.db.trades.docs[0])
    _, sims, _ = asyncio.run(strat.apply_exits(sworld.db, [doc], persist=False))
    sim = copy.deepcopy(sims[doc["_id"]])
    sim["legs"][1].update(mark=None, mark_date=None, mark_basis=None)
    sim["gross_pnl_rs"] = None
    stored, mine = asyncio.run(strat.close_strategy_trade(sworld.db, doc, **sim["exit"], sim=sim))
    assert mine is True and stored["net_pnl_rs"] is None
    a = _account(sworld.db)
    assert a["blocked_rs"] == 0.0 and a["cash_rs"] == acct.DEFAULT_CAPITAL


# ── the evening script runs the strategy exit rules too ──────────────────────
def test_the_evening_script_dry_run_reports_the_strategy_exit_and_writes_nothing(api, sworld):
    import asyncio
    from scripts import check_desk_alerts as script

    open_strategy(api)
    writes = sworld.db.trades.writes
    account = copy.deepcopy(sworld.db[acct.ACCOUNTS].docs)
    out = asyncio.run(script.run(sworld.db, dry_run=True))
    assert out["ok"] is True and out["open_strategy_trades"] == 1
    assert out["strategy_exits"] == {"target": 1} and out["strategy_not_checked"] == 0
    assert out["symbols"] == 0                                     # the share-trade read leaves FIXU to the strategy read
    assert sworld.db.trades.writes == writes and sworld.db.trades.docs[0]["status"] == "open"
    assert sworld.db[acct.ACCOUNTS].docs == account and _releases(sworld.db) == []


def test_the_evening_script_closes_the_strategy_and_returns_its_capital_once(api, sworld):
    import asyncio
    from scripts import check_desk_alerts as script

    open_strategy(api)
    out = asyncio.run(script.run(sworld.db))
    assert out["ok"] is True and out["strategy_exits"] == {"target": 1}
    doc = sworld.db.trades.docs[0]
    assert (doc["status"], doc["exit_reason"], doc["exit_session"]) == ("closed", "target", "2026-10-15")
    a = _account(sworld.db)
    assert a["blocked_rs"] == 0.0 and a["cash_rs"] == pytest.approx(acct.DEFAULT_CAPITAL + 6141.875, abs=0.01)

    writes = sworld.db.trades.writes + sworld.db[acct.ACCOUNTS].writes
    again = asyncio.run(script.run(sworld.db))
    assert again["open_strategy_trades"] == 0 and again["strategy_exits"] == {}
    assert sworld.db.trades.writes + sworld.db[acct.ACCOUNTS].writes == writes
    assert len(_releases(sworld.db)) == 1


def test_the_evening_script_says_when_strategy_prices_cannot_be_read(api, sworld, monkeypatch, caplog):
    import asyncio
    import logging

    import deps
    from scripts import check_desk_alerts as script

    open_strategy(api)
    sworld.history_fail = daas_client.DaasError("unreachable")
    out = asyncio.run(script.run(sworld.db))
    assert out["strategy_not_checked"] == 1 and out["ok"] is False   # nothing else to check, and this could not be read
    assert sworld.db.trades.docs[0]["status"] == "open"
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(deps, "db", sworld.db)
    monkeypatch.setattr("sys.argv", ["check_desk_alerts"])
    assert script.main() == 1
    assert "1 strategy trade(s) were not checked" in caplog.text


def test_costs_use_the_strategy_engine_constants():
    assert svc.COST_MODEL["slippage_pct_per_side"] == 0.05 and svc.COST_MODEL["brokerage_rs_per_side"] == 20.0
    doc = strat.new_strategy_trade("u", strategy_body(), NOW)
    assert strat.strategy_costs(doc, [110.0, 60.0]) == pytest.approx(108.125, abs=0.01)
    assert strat.strategy_costs(doc, [110.0, None]) is None


def test_the_defined_risk_rule_directly():
    legs = lambda *ls: [dict(l, index=i) for i, l in enumerate(ls)]       # noqa: E731
    assert strat.check_defined_risk(legs(call("buy", 1300, 40), call("sell", 1360, 15)))["defined_risk"] is True
    with pytest.raises(svc.DeskInputError) as e:
        strat.check_defined_risk(legs(call("sell", 1300, 40)))
    assert e.value.code == "unbounded_loss"
    with pytest.raises(svc.DeskInputError) as e:
        strat.check_defined_risk(legs(put("sell", 1300, 40), put("buy", 1250, 10, lots=1), put("sell", 1200, 5)))
    assert e.value.code == "naked_short_put"                                # two short puts, one long
    # Futures (TESTCASES F-1, F-2, F-7): never defined risk; a short futures-only structure is refused.
    assert strat.check_defined_risk(legs(future("buy", 1215))) == {"defined_risk": False, "futures_exposure": True,
                                                                   "note": strat.UNBOUNDED_NOTE}
    with pytest.raises(svc.DeskInputError) as e:
        strat.check_defined_risk(legs(future("sell", 1215)))
    assert e.value.code == "short_futures_not_supported" and "no limit on its loss" in e.value.message
    with pytest.raises(svc.DeskInputError) as e:                            # a calendar spread sells a future too
        strat.check_defined_risk(legs(future("buy", 1215), dict(future("sell", 1220), expiry="2026-11-24")))
    assert e.value.code == "short_futures_not_supported"
    hedged = strat.check_defined_risk(legs(future("sell", 1215), call("buy", 1300, 20)))
    assert hedged == {"defined_risk": False, "futures_exposure": True, "note": strat.FUTURES_HEDGED_NOTE}
