"""Paper trades on the shared exit step: parity with the backtest, the opt-in research rules, versioned stop updates,
failed-close recovery, F&O premium exits and close-price marks, and the AI Trader's exits (N15).

Test cases TC-27, TC-31..TC-35, TC-40..TC-44, TC-50 (test_reports/p2_exits_backtest_TESTCASES.md).
MOCK — not real data: every symbol, bar and date below is made up."""
from __future__ import annotations

import asyncio
import copy
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services import exit_rules as er
from services import paper_account
from services.ai_trader import execution
from services.strategy_engine import backtest as bt

NOW = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)          # 09:30 IST, Monday 5 Oct 2026
OPENED = date(2026, 10, 5)


def tb(day: date, o, h, l, c) -> Dict[str, Any]:
    return {"date": day, "open": o, "high": h, "low": l, "close": c, "volume": 1.0, "series": "EQ"}


def sessions(start: date, n: int) -> List[date]:
    out, d = [], start
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def warmup(n: int = 15) -> List[Dict[str, Any]]:
    """n flat sessions up to and including OPENED, each with a true range of 2 → a Wilder ATR(14) of exactly 2."""
    days, d = [], OPENED
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return [tb(x, 100, 101, 99, 100) for x in sorted(days)]


def cash_trade(**over) -> Dict[str, Any]:
    body = {"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0}
    body.update(over)
    return svc.new_trade("user_a", body, NOW)


# ── TC-27: the backtest and the paper simulator agree on the same bars ─────────────────────────────────────
def _path(seed: int, n: int = 40) -> List[Dict[str, Any]]:
    rnd = random.Random(seed)
    px, out = 100.0, []
    for d in sessions(OPENED, n):
        o = round(px * (1 + rnd.uniform(-0.025, 0.025)), 2)
        h = round(max(o, px) * (1 + rnd.uniform(0, 0.03)), 2)
        l = round(min(o, px) * (1 - rnd.uniform(0, 0.03)), 2)
        c = round(rnd.uniform(l, h), 2)
        out.append(tb(d, o, h, l, c))
        px = c
    return out


class _Provider:
    def __init__(self, path):
        self.path = path
        self._dates = [OPENED] + [b["date"] for b in path]
        self.basis = {}

    async def prepare(self, *a):
        return None

    async def trading_dates(self, *a):
        return self._dates

    async def latest_date(self):
        return self._dates[-1]

    async def screen(self, spec, d):
        return [{"symbol": "FIXA", "close": 100.0, "adj_close": 100.0, "adj_factor": 1.0, "atr14": 2.0,
                 "accumulation_score": 1.0}] if d == OPENED else []

    async def exit_bars(self, symbols, d):
        b = next((x for x in self.path if x["date"] == d), None)
        return {"FIXA": dict(b)} if b and "FIXA" in symbols else {}


@pytest.mark.parametrize("trail", [None, 1.5, 2.0])
@pytest.mark.parametrize("seed", range(20))
def test_tc27_backtest_and_paper_agree_on_the_same_bars(monkeypatch, seed, trail):
    path = _path(seed)
    exit_spec = {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 20, **({"trailing_atr_mult": trail} if trail else {})}
    spec = {"version": "1", "asset_class": "STOCK", "name": "parity", "universe": {"type": "index", "ref": "NIFTY500"},
            "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]}, "exit": exit_spec,
            "ranking": {"by": "score", "limit": 5}, "rebalance": "daily"}
    monkeypatch.setattr(bt, "get_provider", lambda pool=None: _Provider(path))
    res = asyncio.run(bt.run_backtest(None, spec, from_date=OPENED, to_date=path[-1]["date"], starting_capital=1e6,
                                      max_positions=1, slippage_pct=0.0, brokerage_inr=0.0, cost_model=bt.COST_FLAT))
    [bt_trade] = res.trades
    paper = cash_trade(max_hold_sessions=20, **({"exit_rules": {"trailing_atr": {"k": trail}}} if trail else {}))
    sim = svc.simulate(paper, warmup() + path)
    ex = sim["exit"]
    if ex is None:
        assert bt_trade.exit_reason == "BACKTEST_END"
        return
    assert bt.REASON_CODE[ex["exit_reason"]] == bt_trade.exit_reason
    assert ex["exit_session"] == bt_trade.exit_date
    assert ex["exit_price"] == pytest.approx(bt_trade.exit_price)
    # The same stop versions, in the same sessions (the trail moved on the same closes to the same levels).
    assert [(h["session"], h["stop"], h["reason"]) for h in sim["stop_history"]] == \
        [(h["session"], h["stop"], h["reason"]) for h in bt_trade.stop_history]


# ── TC-31: the opt-in ATR trail on a paper trade ───────────────────────────────────────────────────────────
def test_tc31_an_opt_in_trail_records_its_stop_history_and_exits_as_trailing_stop():
    t = cash_trade(target_price=150.0, exit_rules={"trailing_atr": {"k": 2}})
    assert t["exit_rules"] == [{"code": "trailing_atr", "version": "trail-atr-v1", "params": {"k": 2.0, "atr_period": 14}}]
    d1, d2 = sessions(OPENED, 2)
    # Warm-up ATR 2, prev close 100. d1 O100 H110 L100 C109: TR 10 → ATR (2·13+10)/14 = 2.5714 → stop 110 − 5.14 = 104.86.
    sim = svc.simulate(t, warmup() + [tb(d1, 100, 110, 100, 109), tb(d2, 106, 107, 104, 105)])
    assert sim["exit"] == {"exit_reason": "trailing_stop", "exit_price": 104.86, "exit_session": d2,
                           "exit_note": "Closed at the trailing stop ₹104.86 (raised by the opt-in ATR trail)."}
    assert [(h["session"], h["stop"], h["reason"], h["version"]) for h in sim["stop_history"]] == [
        ("2026-10-05", 95.0, "initial", 1), (d1.isoformat(), 104.86, "trailing_atr", 2)]
    pub = svc.public_trade({**t, "status": "open"}, None, None, sim=sim)
    assert pub["exit_rules"][0]["label"].startswith("ATR trailing stop: highest high since entry − 2 × ATR(14)")
    assert (pub["current_stop"], pub["stop_version"], pub["exit_rules_version"]) == (104.86, 2, "exit-rules-v1")


def test_tc31_a_trail_with_too_few_bars_waits_and_says_so():
    t = cash_trade(target_price=150.0, exit_rules={"trailing_atr": {"k": 2}})
    (d1,) = sessions(OPENED, 1)
    sim = svc.simulate(t, [tb(d1, 100, 110, 100, 109)])      # no history before the entry: no ATR, never a stand-in
    assert sim["current_stop"] == 95.0 and [f["code"] for f in sim["flags"]] == ["atr_unavailable"]


def test_tc31_a_trail_reads_a_longer_history_before_the_entry():
    assert svc.lookback_days(cash_trade()) == svc.LOOKBACK_DAYS
    assert svc.lookback_days(cash_trade(exit_rules={"trailing_atr": {"k": 2}})) == 14 + 23      # ceil(14 × 1.6)
    assert svc.fetch_starts([cash_trade(exit_rules={"trend_ema": {"period": 20}})], "opened_at")["FIXA"] == OPENED - timedelta(days=46)


def test_tc31_invalid_exit_rules_are_refused_by_the_validator():
    with pytest.raises(svc.DeskInputError, match="invalid_exit_rules"):
        cash_trade(exit_rules={"trailing_atr": {"k": 0}})


# ── TC-32: a rule that is off changes nothing ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("seed", range(10))
def test_tc32_opt_in_rules_off_give_the_same_simulation(seed):
    path = warmup() + _path(seed)
    plain = svc.simulate(cash_trade(max_hold_sessions=15), path)
    for rules in (None, {}):
        other = svc.simulate(cash_trade(max_hold_sessions=15, exit_rules=rules), path)
        assert other == plain


# ── TC-33 / TC-34 / TC-35: versioned stop updates, double apply, failed close, counted reasons ──────────────
class _Res:
    def __init__(self, n):
        self.matched_count = n


class _Coll:
    def __init__(self, docs, fail_ids=()):
        self.docs = {d["_id"]: d for d in docs}
        self.fail_ids = set(fail_ids)
        self.writes = []

    async def update_one(self, flt, upd):
        if flt["_id"] in self.fail_ids:
            self.fail_ids.discard(flt["_id"])
            raise RuntimeError("write timed out")
        d = self.docs.get(flt["_id"])
        if d is None or any(d.get(k) != v for k, v in flt.items()):
            return _Res(0)
        d.update(copy.deepcopy(upd["$set"]))
        self.writes.append(flt["_id"])
        return _Res(1)

    async def find_one(self, flt):
        return copy.deepcopy(self.docs.get(flt["_id"]))


class _Db:
    def __init__(self, coll):
        self.c = coll

    def __getitem__(self, name):
        assert name == svc.TRADES
        return self.c


@pytest.fixture
def no_account(monkeypatch):
    calls = []

    async def release(db, uid, amount, **kw):
        calls.append(kw.get("trade_id"))
    monkeypatch.setattr(paper_account, "release", release)
    return calls


def _trail_bars():
    d1, d2, d3 = sessions(OPENED, 3)
    return {"FIXA": warmup() + [tb(d1, 100, 110, 100, 109)]}, {"FIXA": warmup() + [tb(d1, 100, 110, 100, 109), tb(d2, 106, 107, 104, 105)]}


def test_tc33_a_trail_move_is_stored_once_with_its_version(no_account):
    t = cash_trade(target_price=150.0, exit_rules={"trailing_atr": {"k": 2}})
    coll = _Coll([copy.deepcopy(t)])
    moved, _ = _trail_bars()
    out, counts = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(t)], moved))
    assert counts["stop_updates"] == 1 and coll.docs[t["_id"]]["stop_version"] == 2
    assert coll.docs[t["_id"]]["current_stop"] == 104.86
    # Applied again from the stored trade: nothing new to write.
    _, counts2 = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(coll.docs[t["_id"]])], moved))
    assert counts2["stop_updates"] == 0 and coll.writes == [t["_id"]]
    # A stale reader (it read version None/1 while the store holds 2) cannot overwrite the newer stop.
    _, counts3 = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(t)], moved))
    assert counts3["stop_update_conflicts"] == 1 and coll.writes == [t["_id"]]


def test_tc33_a_double_apply_closes_once(no_account):
    t = cash_trade(target_price=150.0, exit_rules={"trailing_atr": {"k": 2}})
    coll = _Coll([copy.deepcopy(t)])
    _, closing = _trail_bars()
    _, c1 = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(t)], closing))
    _, c2 = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(t)], closing))     # the same stale snapshot again
    assert (c1["trailing_stop"], c2["trailing_stop"], c2["already_closed"]) == (1, 0, 1)
    assert no_account == [t["_id"]]                                                        # the capital comes back once
    stored = coll.docs[t["_id"]]
    assert (stored["status"], stored["exit_reason"], stored["exit_price"]) == ("closed", "trailing_stop", 104.86)
    assert [h["reason"] for h in stored["stop_history"]] == ["initial", "trailing_atr"] and stored["exit_rules_version"] == "exit-rules-v1"


def test_tc34_a_failed_close_leaves_the_trade_open_counts_it_and_the_retry_closes_it_once(no_account):
    a = cash_trade(symbol="FIXA")
    b = cash_trade(symbol="FIXB")
    (d1,) = sessions(OPENED, 1)
    bars = {"FIXA": [tb(d1, 99, 100, 94, 96)], "FIXB": [tb(d1, 99, 100, 94, 96)]}
    coll = _Coll([copy.deepcopy(a), copy.deepcopy(b)], fail_ids=[a["_id"]])
    out, c1 = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(a), copy.deepcopy(b)], bars))
    assert (c1["exit_failed"], c1["failed_ids"], c1["stop"]) == (1, [a["_id"]], 1)
    assert coll.docs[a["_id"]]["status"] == "open" and coll.docs[b["_id"]]["status"] == "closed"
    _, c2 = asyncio.run(svc.apply_trade_exits(_Db(coll), [copy.deepcopy(coll.docs[a["_id"]])], bars))
    assert (c2["exit_failed"], c2["stop"]) == (0, 1) and coll.docs[a["_id"]]["status"] == "closed"
    assert sorted(no_account) == sorted([a["_id"], b["_id"]])


def test_tc35_a_dry_run_counts_every_new_reason():
    t = cash_trade(target_price=150.0, exit_rules={"trailing_atr": {"k": 2}})
    _, closing = _trail_bars()
    _, counts = asyncio.run(svc.apply_trade_exits(None, [t], closing, persist=False))
    assert counts["trailing_stop"] == 1


# ── TC-40 .. TC-44: F&O structures ─────────────────────────────────────────────────────────────────────────
EXPIRY = "2026-10-27"


def leg(side, strike, price, option_type="call"):
    return {"kind": "option", "side": side, "lots": 1, "lot_size": 250, "entry_price": price, "expiry": EXPIRY,
            "strike": strike, "option_type": option_type, "price_source": "NSE F&O bhavcopy close"}


def spread(**over):
    body = {"kind": "strategy", "underlying": "FIXU", "direction": "bullish", "family": "bull_call_spread",
            "reference_price": 1215.0, "stop_underlying": 1000.0, "target_underlying": 1500.0,
            "legs": [leg("buy", 1300, 40), leg("sell", 1360, 15)],
            "signal": {"signal_at": "2026-10-05T03:30:00Z", "rule_version": "strategy-rules v1.5", "source_refs": [],
                       "evidence_summary": "MOCK"}}
    body.update(over)
    return strat.new_strategy_trade("user_a", body, NOW)


def row(day, close, settle=None, underlying=None):
    return {"as_of_date": day.isoformat(), "close_price": close, "settle_price": settle, "underlying_price": underlying}


PLAN = {"kind": "debit", "entry": 25.0, "planned_stop": 17.5, "target_1": 32.5, "target_2": 40.0, "unit_shares": 250,
        "version": "strategy-levels-v2"}


def test_tc40_an_option_is_marked_at_its_close_never_the_settle_price():
    t = spread()
    (d1,) = sessions(OPENED, 1)
    # On an expiry-like row the settle column holds the UNDERLYING (1,215): marking at it would book (1215 − 40) × 250.
    sim = strat.simulate_strategy(t, [tb(d1, 1215, 1220, 1210, 1215)], [[row(d1, 45, settle=1215)], [row(d1, 17, settle=1215)]])
    assert [(s["mark"], s["mark_basis"]) for s in sim["legs"]] == [(45.0, "close"), (17.0, "close")]
    assert sim["gross_pnl_rs"] == 750.0                       # (45 − 40) × 250 − (17 − 15) × 250
    # A contract with a settle but no traded close has no mark: kept unmarked and flagged, never the settle.
    sim = strat.simulate_strategy(t, [tb(d1, 1215, 1220, 1210, 1215)], [[row(d1, None, settle=47)], [row(d1, 17)]])
    assert sim["legs"][0]["mark"] is None and sim["gross_pnl_rs"] is None
    assert [f["code"] for f in sim["flags"]] == ["no_mark"]


def test_tc41_the_premium_stop_closes_the_whole_structure():
    t = {**spread(), "exit_plan": {"options": PLAN}}
    d1, d2 = sessions(OPENED, 2)
    bars = [tb(d1, 1215, 1220, 1205, 1210), tb(d2, 1205, 1210, 1180, 1190)]
    # d1 value 38 − 14 = 24 a unit (above 17.5); d2 value 30 − 14 = 16 ≤ 17.5 → stop on the premium, at the d2 marks.
    sim = strat.simulate_strategy(t, bars, [[row(d1, 38), row(d2, 30)], [row(d1, 14), row(d2, 14)]])
    assert (sim["exit"]["exit_reason"], sim["exit"]["exit_basis"], sim["exit"]["exit_session"]) == ("stop", "premium", d2)
    assert sim["structure_value_per_unit"] == 16.0 and sim["gross_pnl_rs"] == -2250.0   # (30−40)×250 − (14−15)×250


def test_tc42_premium_target_1_closes_it_as_target():
    t = {**spread(), "exit_plan": {"options": PLAN}}
    (d1,) = sessions(OPENED, 1)
    sim = strat.simulate_strategy(t, [tb(d1, 1230, 1260, 1225, 1255)], [[row(d1, 50)], [row(d1, 15)]])
    assert (sim["exit"]["exit_reason"], sim["exit"]["exit_basis"]) == ("target", "premium")     # 50 − 15 = 35 ≥ 32.5


def test_tc42_an_underlying_stop_wins_over_a_premium_target_on_one_session():
    t = {**spread(stop_underlying=1200.0), "exit_plan": {"options": PLAN}}
    (d1,) = sessions(OPENED, 1)
    sim = strat.simulate_strategy(t, [tb(d1, 1230, 1260, 1195, 1255)], [[row(d1, 50)], [row(d1, 15)]])
    assert (sim["exit"]["exit_reason"], sim["exit"]["exit_basis"]) == ("stop", "underlying")


def test_tc43_without_a_stored_plan_only_the_existing_rules_apply():
    t = spread()
    (d1,) = sessions(OPENED, 1)
    sim = strat.simulate_strategy(t, [tb(d1, 1215, 1220, 1205, 1210)], [[row(d1, 30)], [row(d1, 14)]])
    assert sim["exit"] is None and sim["structure_value_per_unit"] is None       # value 16 would be a premium stop
    assert strat.public_strategy_trade(t, sim)["premium_plan"] is None
    # A plan on a structure with a future is not used either.
    fut = {**spread(legs=[leg("buy", 1300, 40), {**leg("sell", 1360, 15), "kind": "future", "strike": None,
                                                 "option_type": None}]), "exit_plan": {"options": PLAN}}
    assert strat.premium_plan(fut) is None


def test_tc43_the_public_trade_shows_the_plan_without_its_greek_rule():
    t = {**spread(), "exit_plan": {"options": {**PLAN, "greek_review": {"entry_delta_per_unit": 0.4}}}}
    pub = strat.public_strategy_trade(t, None)
    assert pub["premium_plan"] == {"kind": "debit", "entry_per_unit": 25.0, "stop_per_unit": 17.5, "t1_per_unit": 32.5,
                                   "t2_per_unit": 40.0, "unit_shares": 250.0, "version": "strategy-levels-v2",
                                   "source": "exit_plan.options"}


def test_tc44_the_greek_review_is_a_flag_and_an_event_never_an_exit(no_account):
    t = {**spread(), "exit_plan": {"options": {**PLAN, "planned_stop": 0.5, "greek_review": {"entry_delta_per_unit": 0.4, "view": "bullish"}}}}
    d1 = date(2026, 10, 14)
    # The underlying fell to 1,100: the 1300/1360 calls are far out of the money and the net delta collapses below
    # 30 % of the entry 0.4 (0.12); value 2.2 − 0.6 = 1.6 a unit is above the 0.5 premium stop, so nothing exits.
    sim = strat.simulate_strategy(t, [tb(d1, 1105, 1110, 1095, 1100)], [[row(d1, 2.2)], [row(d1, 0.6)]])
    assert sim["exit"] is None
    [flag] = [f for f in sim["flags"] if f["code"] == "greek_review"]
    assert flag["price"] < 0.12 and "not an exit" in flag["text"]
    d = strat.net_delta_per_unit(t["legs"], sim["legs"], 1100.0, d1, 250)
    assert 0 < d < 0.12

    async def close():
        coll = _Coll([{**copy.deepcopy(t), "status": "open"}])

        class Db:
            def __getitem__(self, name):
                return coll
        return await strat.close_strategy_trade(Db(), t, exit_reason="manual", exit_session=d1, exit_note=None, sim=sim)
    stored, mine = asyncio.run(close())
    assert mine and "greek_review" in [e["type"] for e in stored["events"]]


# ── TC-50: the AI Trader's paper trade carries the strategy's exits (N15) ──────────────────────────────────
def _ticket():
    return {"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
            "signal_date": "2026-10-05", "strategy_version": "v1"}


def test_tc50_the_ai_trader_body_carries_time_and_the_trail_and_the_desk_takes_it():
    body = execution.trade_body(_ticket(), rationale="MOCK", exit_spec={"stoploss_pct": 5, "target_rr": 2,
                                                                          "max_hold_days": 20, "trailing_atr_mult": 2})
    assert body["max_hold_sessions"] == 20 and body["exit_rules"] == {"trailing_atr": {"k": 2.0}}
    doc = svc.new_trade("user_a", body, NOW)                           # the contract: the desk validator accepts it
    assert doc["max_hold_sessions"] == 20
    assert doc["exit_rules"] == [{"code": "trailing_atr", "version": "trail-atr-v1", "params": {"k": 2.0, "atr_period": 14}}]


def test_tc50_a_hold_beyond_the_desk_maximum_is_capped_and_no_spec_changes_nothing():
    assert execution.trade_body(_ticket(), rationale="x", exit_spec={"max_hold_days": 300})["max_hold_sessions"] == 250
    plain = execution.trade_body(_ticket(), rationale="x")
    assert "max_hold_sessions" not in plain and "exit_rules" not in plain
    assert svc.new_trade("user_a", plain, NOW)["exit_rules"] == []


# ── TC-70 (contract): the bodies the screens now send, exactly as the e2e specs pin them, pass the desk validator ──
@pytest.mark.parametrize("body", [
    # Top 10 / AI watchlist / scanner tab (copilot-app-desk-top10, -ai-watchlist, -desk-scanner specs)
    {"symbol": "ICICIBANK", "quantity": 208, "entry_price": 1200, "stop_price": 1160, "target_price": 1280,
     "source": {"kind": "scanner", "bucket": "breakout_confirmed", "signal_date": "2026-10-05"}, "entry_rule": "at_once",
     "max_hold_sessions": 15},
    # risk desk (no entry rule)
    {"symbol": "FIXBRK", "quantity": 200, "entry_price": 505, "stop_price": 480, "target_price": 560,
     "source": {"kind": "scanner", "bucket": "breakout_confirmed", "signal_date": "2026-10-05"}, "max_hold_sessions": 20},
    # Strategy Builder cash candidate (plan horizon)
    {"symbol": "RELIANCE", "quantity": 208, "entry_price": 1200, "stop_price": 1160, "target_price": 1280,
     "source": {"kind": "strategy_plan", "bucket": "breakout_continuation", "signal_date": "2026-10-05"},
     "signal_at": "2026-10-05T03:00:00+00:00", "strategy_version": "strategy-rules.v1.5", "rationale": "Breakout continuation (long); plan p",
     "max_hold_sessions": 10},
], ids=["scanner", "risk-desk", "plan-cash"])
def test_tc70_the_screen_bodies_with_a_time_exit_are_accepted(body):
    doc = svc.new_trade("user_a", body, NOW)
    assert doc["max_hold_sessions"] == body["max_hold_sessions"] and doc["exit_rules"] == []
