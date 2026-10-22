"""AI Trader Phases 4 and 5: paper execution and assisted tickets (services/ai_trader/execution.py and the Phase 4/5
routes in routes/ai_trader.py). Covers the Phase 4, Phase 5, no-broker, ownership and journal bullets of section 5 of
docs/prd/AI_TRADER_PHASES_2_5.prd.md.

No network, no Mongo and no Postgres. Replaced, and by what:
  * `route.db`                an in-memory stand-in for the strategy, ticket and paper-trade collections (equality
                              filters only), the same approach as tests/test_desk_alerts.py
  * `route.get_current_user`  reads the test's `X-Test-User` header
  * `route._screen`           a fixed candidate list, because the real screen needs the NIDP Postgres
  * `route._market`           a fixed India VIX and regime, because the research index files stop in 2024
  * `route._evidence_for`     a fixed evidence list, and `strategy.propose` where a route calls Phase 2 code, so these
                              tests do not depend on another module's internals
  * the clock                 `execution.utcnow` and `desk.utcnow`, fixed at 2026-10-21 05:00 UTC (10:30 IST)

Everything else runs for real: the sizing and ticket logic, `risk_governor.evaluate`, `desk_trading.new_trade` (so the
paper trades asserted on are genuine desk documents), `calibration.calibration_report`, the ownership checks and the
route status codes.

MOCK - not real data: every symbol, close, strategy spec, paper trade and P&L below is made up.

Worked examples
  sizing   capital Rs 10,00,000 and the governor's 1% risk per trade give a Rs 10,000 risk budget. A close of 200.00
           with a 10% stop puts the stop at 180.00, so Rs 20 a share buys floor(10,000 / 20) = 500 shares, and a
           target_rr of 2 puts the target at 200 + 20 * 2 = 240.00. The 10% position limit allows 100,000 / 200 = 500
           as well, so the governor approves all 500.
  reduce   a close of 100.00 with a 6% stop risks Rs 6 a share, so the risk budget wants floor(10,000 / 6) = 1,666
           shares, but the 10% position limit allows only 100,000 / 100 = 1,000. The decision is reduce 1,000 and the
           paper trade is opened for 1,000, not 1,666.
  journal  two closed shadow trades, +5,000 and -2,000, against a stated confidence of 0.60: the pairs are
           (0.60, True) and (0.60, False), so Brier = (0.40^2 + 0.60^2) / 2 = 0.26 and the 0.6-0.7 bin observed 0.50
           against 0.60 stated, a calibration error of 0.10. Paper stats: expectancy Rs 1,500 and profit factor 2.5.
"""
from __future__ import annotations

import ast
import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from routes import ai_trader as route
from services import desk_trading as desk
from services.ai_trader import execution, strategy
from services.ai_trader.risk_governor import DEFAULT_LIMITS, Decision, Intent, Market, Portfolio, Reason, evaluate

BASE = "/api/ai-trader"
A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}
NOW = datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc)      # Wednesday 10:30 IST
AS_OF = "2026-10-20"                                          # Tuesday, the signal date used throughout
CAPITAL = 1_000_000.0


# ── the in-memory collections (equality filters, plus the one $in the routes use) ─────
def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, want in query.items():
        if isinstance(want, dict) and set(want) == {"$in"}:
            if doc.get(key) not in want["$in"]:
                return False
        elif doc.get(key) != want:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction):
        self._docs = sorted(self._docs, key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    async def to_list(self, length):
        return self._docs if length is None else self._docs[:length]


class _Res:
    def __init__(self, matched=0, deleted=0):
        self.matched_count = matched
        self.deleted_count = deleted


class Coll:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.writes = 0
        self.indexes: List[Any] = []

    async def create_index(self, keys, **kw):
        self.indexes.append((tuple(keys), kw))
        return None

    def find(self, q):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, q)])

    async def find_one(self, q):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, q)), None)

    async def count_documents(self, q):
        return sum(1 for d in self.docs if _matches(d, q))

    async def insert_one(self, doc):
        self.writes += 1
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, q, update):
        for d in self.docs:
            if _matches(d, q):
                self.writes += 1
                d.update(copy.deepcopy(update.get("$set") or {}))
                for key, value in (update.get("$push") or {}).items():
                    d.setdefault(key, []).append(copy.deepcopy(value))
                return _Res(matched=1)
        return _Res()


class Db:
    def __init__(self):
        self.cols: Dict[str, Coll] = {}

    def __getitem__(self, name) -> Coll:
        return self.cols.setdefault(name, Coll())

    @property
    def strategies(self) -> Coll:
        return self[execution.STRATEGIES]

    @property
    def tickets(self) -> Coll:
        return self[execution.TICKETS]

    @property
    def trades(self) -> Coll:
        return self[desk.TRADES]


# ── MOCK - not real data: the documents and rows the routes read ─────────────
def spec(stoploss_pct: float = 10.0, target_rr: float = 2.0) -> Dict[str, Any]:
    """MOCK - not real data: shaped like services/strategy_engine/templates/momentum_breakout.json."""
    return {
        "version": "1", "asset_class": "STOCK", "name": "Mock momentum",
        "universe": {"type": "index", "ref": "NIFTY500"},
        "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]},
        "exit": {"stoploss_pct": stoploss_pct, "target_rr": target_rr, "max_hold_days": 30},
        "ranking": {"by": "vol_z20", "limit": 10, "order": "desc"},
        "rebalance": "daily",
    }


def config(capital: float = CAPITAL) -> Dict[str, Any]:
    """MOCK - not real data: a NiveshConfig.to_dict() with the AI defaults."""
    return {"schema_version": 1, "symbols": ["MOCKA", "MOCKB"], "initial_capital": capital,
            "commission_pct": 0.05, "pyramiding": 0, "short_margin_pct": 100.0, "custom": {}}


def strategy_record(uid: str = "user_a", stage: str = "paper", *, stoploss_pct: float = 10.0,
                    target_rr: float = 2.0, capital: float = CAPITAL, win_rate: Optional[float] = 60.0,
                    sid: str = "strat-1") -> Dict[str, Any]:
    """MOCK - not real data: the document shape services/ai_trader/strategy.py's new_strategy writes."""
    runs = [{"run_id": "run-1", "ran_at": "2026-10-19T00:00:00+00:00", "strategy_version": "mockversion000001",
             "metrics": {"trade_count": 120, "win_rate": win_rate, "profit_factor": 1.6},
             "window": {"from_date": "2021-01-01", "to_date": "2022-12-31"}, "holdout": False,
             "walk_forward": []}] if win_rate is not None else []
    return {
        "_id": sid, "user_id": uid, "name": "Mock momentum", "created_by": "ai", "stage": stage,
        "version": "mockversion000001", "spec": spec(stoploss_pct, target_rr), "config": config(capital),
        "template": "momentum_breakout", "regime": "BULL", "provenance": {}, "runs": runs,
        "holdout_used": False, "paper_stats": None,
        "stage_history": [{"stage": stage, "at": "2026-10-19T00:00:00+00:00", "by": "ai", "from": None, "gates": []}],
        "created_at": "2026-10-19T00:00:00+00:00", "updated_at": "2026-10-19T00:00:00+00:00",
    }


def candidate(symbol: str, close: float, sector: str = "Mock Sector") -> Dict[str, Any]:
    """MOCK - not real data: a market-data provider screen() row."""
    return {"symbol": symbol, "as_of_date": AS_OF, "close": close, "adj_close": close, "adj_factor": 1.0,
            "atr14": round(close * 0.02, 2), "accumulation_score": 0.7, "sector": sector}


def held(uid: str, symbol: str, price: float = 10.0) -> Dict[str, Any]:
    """MOCK - not real data: an open desk paper trade, built by the real validator."""
    return desk.new_trade(uid, {"symbol": symbol, "quantity": 1, "entry_price": price,
                                "stop_price": round(price * 0.9, 2), "target_price": round(price * 1.3, 2)}, NOW)


class World:
    def __init__(self):
        self.db = Db()
        self.candidates: List[Dict[str, Any]] = [candidate("MOCKA", 200.0)]
        self.market = Market(vix=15.0, regime="BULL")
        self.screens = 0


@pytest.fixture
def world(monkeypatch) -> World:
    w = World()
    monkeypatch.setattr(route, "db", w.db)
    monkeypatch.setattr(route, "_indexes_ready", False)
    monkeypatch.setattr(execution, "utcnow", lambda: NOW)
    monkeypatch.setattr(desk, "utcnow", lambda: NOW)

    async def fake_screen(spec_, as_of):
        w.screens += 1
        return [dict(row) for row in w.candidates]

    monkeypatch.setattr(route, "_screen", fake_screen)
    monkeypatch.setattr(route, "_market", lambda as_of: w.market)
    monkeypatch.setattr(route, "_evidence_for", lambda as_of: ["MOCK evidence"])
    return w


@pytest.fixture
def api(world) -> TestClient:
    app = FastAPI()
    app.include_router(route.router)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    app.dependency_overrides[route.get_current_user] = fake_user
    return TestClient(app)


def signals(api, sid="strat-1", mode="paper", who=A, as_of=AS_OF, status=200):
    r = api.post(f"{BASE}/strategies/{sid}/signals", json={"as_of": as_of, "mode": mode}, headers=who)
    assert r.status_code == status, r.text
    return r.json()


# ── execution.py: sizing from the risk budget and the candidate's close ──────
def test_sizing_uses_the_candidate_close_the_stop_distance_and_the_risk_budget():
    intents = execution.intents_from_candidates(spec(), config(), [candidate("MOCKA", 200.0)], as_of=AS_OF)
    assert len(intents) == 1
    i = intents[0]
    assert (i.symbol, i.entry_price, i.stop_price, i.target_price) == ("MOCKA", 200.0, 180.0, 240.0)
    assert i.quantity == 500                              # floor(1% of 10,00,000 / 20)
    assert (i.sector, i.avg_daily_value) == ("Mock Sector", None)


def test_a_wider_stop_buys_fewer_shares_and_the_target_follows_the_reward_ratio():
    i = execution.intents_from_candidates(spec(6.0, 2.5), config(), [candidate("MOCKB", 100.0)], as_of=AS_OF)[0]
    assert (i.stop_price, i.target_price, i.quantity) == (94.0, 115.0, 1666)


def test_a_candidate_without_a_usable_close_is_refused_never_priced_from_something_else():
    for bad in (None, 0, -5, "200"):
        with pytest.raises(execution.ExecutionError):
            execution.intents_from_candidates(spec(), config(), [{"symbol": "MOCKA", "close": bad}], as_of=AS_OF)
    with pytest.raises(execution.ExecutionError):
        execution.intents_from_candidates(spec(), config(), [{"close": 200.0}], as_of=AS_OF)


@pytest.mark.parametrize("bad_spec, bad_config", [
    ({}, config()),
    ({"exit": {"target_rr": 2}}, config()),
    ({"exit": {"stoploss_pct": 0, "target_rr": 2}}, config()),
    ({"exit": {"stoploss_pct": 120, "target_rr": 2}}, config()),
    ({"exit": {"stoploss_pct": 10, "target_rr": 0}}, config()),
    (spec(), {"initial_capital": 0}),
    (spec(), {}),
])
def test_a_spec_or_config_that_cannot_size_an_order_is_refused(bad_spec, bad_config):
    with pytest.raises(execution.ExecutionError):
        execution.intents_from_candidates(bad_spec, bad_config, [candidate("MOCKA", 200.0)], as_of=AS_OF)


def test_a_risk_budget_too_small_for_one_share_gives_zero_and_the_governor_rejects_it():
    i = execution.intents_from_candidates(spec(), config(capital=1000.0), [candidate("MOCKA", 200.0)], as_of=AS_OF)[0]
    assert i.quantity == 0                                 # 1% of 1,000 is Rs 10, the stop is Rs 20 away
    decision = evaluate(i, Portfolio(capital=1000.0), Market(vix=15.0, regime="BULL"))
    assert decision.action == "reject" and decision.approved_qty == 0


# ── execution.py: tickets, text, expiry, the journal ─────────────────────────
def _decision(action="approve", requested=500, approved=500, codes=("DRAWDOWN_UNKNOWN",)):
    """MOCK - not real data: a governor decision, as risk_governor.evaluate would return it."""
    return Decision(action, requested, approved, [Reason(c, "mock reason", "info") for c in codes])


def test_a_paper_ticket_cleared_by_the_governor_carries_the_decision_and_waits_for_nothing():
    t = execution.new_ticket("user_a", strategy_record(), Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                             _decision(), as_of=AS_OF, mode="paper")
    assert (t["status"], t["governor_cleared"], t["expires_at"]) == ("confirmed", True, None)
    assert (t["quantity"], t["requested_quantity"], t["confidence"]) == (500, 500, 0.6)
    assert t["decision"]["action"] == "approve" and "DRAWDOWN_UNKNOWN" in t["reason_codes"]
    assert t["mode"] == "paper" and t["signal_date"] == AS_OF and t["trade_id"] is None


def test_an_assisted_ticket_waits_for_the_user_and_expires_at_the_next_session_end():
    t = execution.new_ticket("user_a", strategy_record(stage="assisted"), Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                             _decision(), as_of="2026-10-16", mode="assisted")       # a Friday
    assert t["status"] == "awaiting_confirmation"
    assert t["expires_at"] == "2026-10-19T10:00:00+00:00"       # Monday 15:30 IST, the weekend skipped
    assert execution.is_expired(t, datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)) is False
    assert execution.is_expired(t, datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc)) is True


@pytest.mark.parametrize("action, approved", [("reject", 0), ("defer", 0), ("halt", 0), ("approve", 0)])
def test_a_decision_worse_than_approve_or_reduce_is_stored_as_refused_in_either_mode(action, approved):
    for mode in ("paper", "assisted"):
        t = execution.new_ticket("user_a", strategy_record(), Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                                 _decision(action, 500, approved, codes=("MAX_POSITIONS",)), as_of=AS_OF, mode=mode)
        assert (t["status"], t["governor_cleared"], t["rejected_by"]) == ("rejected", False, "risk_governor")
        assert t["reject_reason"] == "MAX_POSITIONS" and t["trade_id"] is None


def test_a_hedge_decision_is_an_allowed_order_with_a_suggestion_not_a_refusal():
    """The governor's precedence puts hedge above reduce and a hedge decision carries the full approved size (PRD
    F3.2), so the ticket is actionable and the suggestion travels with it. Recording it as refused by the risk
    governor would state a refusal the risk layer never made."""
    assert execution.ACTIONABLE == ("approve", "reduce", "hedge")
    for mode, expected in (("paper", "confirmed"), ("assisted", "awaiting_confirmation")):
        t = execution.new_ticket("user_a", strategy_record(), Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                                 _decision("hedge", 500, 500, codes=("HEDGE_SUGGESTED",)), as_of=AS_OF, mode=mode)
        assert (t["status"], t["governor_cleared"]) == (expected, True)
        assert (t["rejected_by"], t["reject_reason"]) == (None, None)
        assert t["quantity"] == 500 and "HEDGE_SUGGESTED" in t["reason_codes"]


def test_a_ticket_keeps_the_average_traded_value_its_signal_was_judged_against():
    i = execution.intents_from_candidates(spec(), config(), [{**candidate("MOCKA", 200.0),
                                                              "avg_daily_value": 400_000.0}], as_of=AS_OF)[0]
    t = execution.new_ticket("user_a", strategy_record(), i, _decision(), as_of=AS_OF, mode="assisted")
    assert t["avg_daily_value"] == 400_000.0
    plain = execution.new_ticket("user_a", strategy_record(), Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                                 _decision(), as_of=AS_OF, mode="assisted")
    assert plain["avg_daily_value"] is None        # unknown stays unknown, so the governor still says it skipped


def test_an_unknown_mode_is_refused_and_live_is_not_a_mode():
    assert execution.MODES == ("paper", "assisted") and "live" not in execution.MODES
    with pytest.raises(execution.ExecutionError):
        execution.new_ticket("user_a", strategy_record(), Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                             _decision(), as_of=AS_OF, mode="live")


def test_the_ticket_text_names_every_number_and_says_nothing_was_sent():
    t = execution.new_ticket("user_a", strategy_record(), Intent("MOCKA", 1666, 100.0, 94.0, 115.0),
                             _decision("reduce", 1666, 1000), as_of=AS_OF, mode="assisted")
    text = execution.ticket_text(t)
    for part in ("MOCKA", "1000", "100.00", "94.00", "115.00", "cut from 1666", "reduce"):
        assert part in text, text
    assert "Place this order yourself at your broker; Nivesh sends nothing." in text
    assert text.splitlines()[-1] == execution.SELF_PLACE_LINE


def test_outcome_pairs_links_closed_trades_to_the_stated_confidence_and_a_win_is_positive_pnl():
    tickets = [
        {"trade_id": "t1", "confidence": 0.6},
        {"trade_id": "t2", "confidence": 0.6},
        {"trade_id": "t3", "confidence": 0.8},          # still open: no outcome yet
        {"trade_id": "t4", "confidence": None},         # nothing was stated: never scored against a guess
        {"trade_id": None, "confidence": 0.9},          # no trade at all
    ]
    trades = [                                           # MOCK - not real data
        {"_id": "t1", "status": "closed", "realized_pnl_rs": 5000.0},
        {"_id": "t2", "status": "closed", "realized_pnl_rs": -2000.0},
        {"_id": "t3", "status": "open", "realized_pnl_rs": None},
        {"_id": "t4", "status": "closed", "realized_pnl_rs": 100.0},
    ]
    assert execution.outcome_pairs(tickets, trades) == [(0.6, True), (0.6, False)]


def test_paper_stats_matches_the_hand_calculation_and_says_nothing_when_nothing_closed():
    stats = execution.paper_stats([{"_id": "t1", "status": "closed", "realized_pnl_rs": 5000.0},
                                   {"_id": "t2", "status": "closed", "realized_pnl_rs": -2000.0},
                                   {"_id": "t3", "status": "open", "realized_pnl_rs": None}])
    assert (stats["closed_trades"], stats["wins"], stats["losses"]) == (2, 1, 1)
    assert (stats["win_rate"], stats["expectancy"], stats["profit_factor"]) == (50.0, 1500.0, 2.5)
    empty = execution.paper_stats([])
    assert empty["closed_trades"] == 0 and empty["expectancy"] is None and empty["profit_factor"] is None
    # No loss means the ratio has no denominator; that is unknown, not a big number.
    assert execution.paper_stats([{"_id": "t", "status": "closed", "realized_pnl_rs": 10.0}])["profit_factor"] is None


def test_stated_confidence_prefers_the_paper_record_then_the_backtest_and_is_none_without_either():
    doc = strategy_record()
    assert execution.stated_confidence(doc) == 0.6
    doc["paper_stats"] = {"win_rate": 45.0}
    assert execution.stated_confidence(doc) == 0.45
    assert execution.stated_confidence(strategy_record(win_rate=None)) is None


def test_the_holdout_runs_win_rate_never_becomes_a_tickets_stated_confidence():
    """The holdout run is measured on the sealed block, so its win rate cannot be the number the system states and
    then scores itself against. The newest ordinary run is used instead, and a strategy with only a holdout run
    states nothing."""
    holdout_run = {"run_id": "run-h", "ran_at": "2026-10-20T00:00:00+00:00", "holdout": True,
                   "metrics": {"trade_count": 90, "win_rate": 90.0},            # MOCK - not real data
                   "window": {"from_date": "2023-01-01", "to_date": "2024-07-31"}, "walk_forward": []}
    doc = strategy_record()
    doc["runs"] = list(doc["runs"]) + [holdout_run]
    assert execution.stated_confidence(doc) == 0.6                 # the ordinary run, not the sealed one
    only_holdout = strategy_record(win_rate=None)
    only_holdout["runs"] = [holdout_run]
    assert execution.stated_confidence(only_holdout) is None
    t = execution.new_ticket("user_a", only_holdout, Intent("MOCKA", 500, 200.0, 180.0, 240.0),
                             _decision(), as_of=AS_OF, mode="paper")
    assert t["confidence"] is None
    # A ticket with no stated confidence is left out of the journal rather than scored against a guess.
    assert execution.outcome_pairs([t], [{"_id": t["trade_id"], "status": "closed",
                                          "realized_pnl_rs": 100.0}]) == []


# ── the no-broker guarantee ──────────────────────────────────────────────────
BACKEND = Path(__file__).resolve().parents[1]
# Any module path that could reach a broker or an order client. Checked against import paths, never against imported
# value names, so a constant like DEFAULT_BROKERAGE_INR cannot trip it (an alias is only treated as a module when it
# is all lowercase, the way module names are written).
FORBIDDEN = ("broker", "kite", "smartapi", "fyers", "upstox", "dhan", "angelone", "order_client", "place_order")


def _imported_paths(path: Path) -> List[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    paths: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            paths.append(base)
            paths += [f"{base}.{alias.name}" if base else alias.name
                      for alias in node.names if alias.name.islower()]
    return [p for p in paths if p]


def test_no_module_of_this_feature_imports_a_broker_or_an_order_client():
    files = sorted((BACKEND / "services" / "ai_trader").glob("*.py")) + [BACKEND / "routes" / "ai_trader.py"]
    scanned = {f.name for f in files}
    # A path typo must fail the test, not quietly scan nothing.
    assert {"execution.py", "risk_governor.py", "config.py", "ai_trader.py"} <= scanned and len(files) >= 6
    offences = []
    for f in files:
        for imported in _imported_paths(f):
            low = imported.lower()
            if any(token in low for token in FORBIDDEN) or low.startswith("services.brokers"):
                offences.append(f"{f.name}: {imported}")
    assert offences == []


def test_there_is_no_live_mode_anywhere_in_the_feature():
    assert "live" not in execution.MODES and "live" not in strategy.STAGES
    r = route.SignalsBody.model_json_schema()
    assert "live" not in str(r["properties"]["mode"])


# ── Phase 4 routes: paper execution ──────────────────────────────────────────
@pytest.mark.parametrize("stage", ["draft", "backtested"])
def test_a_strategy_that_has_not_reached_paper_cannot_signal(api, world, stage):
    world.db.strategies.docs.append(strategy_record(stage=stage))
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "paper"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "stage_cannot_signal")
    assert world.db.tickets.docs == [] and world.db.trades.docs == []


def test_live_mode_is_refused_and_stores_nothing(api, world):
    world.db.strategies.docs.append(strategy_record())
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "live"}, headers=A)
    assert r.status_code == 422
    assert world.db.tickets.docs == [] and world.db.trades.docs == []
    assert not any("live" in str(d) for d in world.db.tickets.docs)


def test_a_mode_that_is_not_the_strategys_stage_is_refused(api, world):
    world.db.strategies.docs.append(strategy_record(stage="paper"))
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "assisted"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "mode_not_allowed_for_stage")


def test_a_cleared_paper_intent_opens_exactly_one_trade_at_the_governors_quantity(api, world):
    world.db.strategies.docs.append(strategy_record())
    body = signals(api)
    assert (body["candidates"], body["created"], body["existing"]) == (1, 1, 0)
    ticket = body["tickets"][0]
    assert (ticket["status"], ticket["quantity"], ticket["requested_quantity"]) == ("executed_paper", 500, 500)
    assert ticket["decision"]["action"] == "approve" and ticket["trade_id"]

    assert len(world.db.trades.docs) == 1
    trade = world.db.trades.docs[0]
    assert (trade["_id"], trade["user_id"], trade["symbol"]) == (ticket["trade_id"], "user_a", "MOCKA")
    assert (trade["quantity"], trade["entry_price"], trade["stop_price"], trade["target_price"]) == \
        (500, 200.0, 180.0, 240.0)
    assert trade["source"] == {"kind": "ai_trader", "bucket": None, "signal_date": AS_OF}
    assert (trade["strategy_version"], trade["signal_at"], trade["status"]) == ("mockversion000001", AS_OF, "open")
    assert trade["rules_version"] == desk.RULES_VERSION and "risk governor approve" in trade["rationale"]
    assert ticket["text"] and execution.SELF_PLACE_LINE in ticket["text"]


def test_a_reduced_decision_trades_the_approved_quantity_not_the_one_asked_for(api, world):
    world.db.strategies.docs.append(strategy_record(stoploss_pct=6.0, target_rr=2.5))
    world.candidates = [candidate("MOCKB", 100.0)]
    ticket = signals(api)["tickets"][0]
    assert (ticket["decision"]["action"], ticket["requested_quantity"], ticket["quantity"]) == ("reduce", 1666, 1000)
    assert "POSITION_SIZE" in ticket["reason_codes"]
    trade = world.db.trades.docs[0]
    assert (trade["quantity"], trade["stop_price"], trade["target_price"]) == (1000, 94.0, 115.0)


def test_a_refused_intent_is_still_stored_with_its_reasons_and_opens_no_trade(api, world):
    world.db.strategies.docs.append(strategy_record())
    world.db.trades.docs.append(held("user_a", "MOCKB"))          # already in the book, so the governor rejects it
    world.candidates = [candidate("MOCKA", 200.0), candidate("MOCKB", 150.0)]
    body = signals(api)
    by_symbol = {t["symbol"]: t for t in body["tickets"]}
    assert body["created"] == 2
    assert by_symbol["MOCKB"]["status"] == "rejected" and by_symbol["MOCKB"]["trade_id"] is None
    assert "ALREADY_HELD" in by_symbol["MOCKB"]["reason_codes"]
    assert by_symbol["MOCKB"]["rejected_by"] == "risk_governor" and by_symbol["MOCKB"]["text"] is None
    assert by_symbol["MOCKA"]["status"] == "executed_paper"
    # one new trade only: the held position was there before, the refused intent added nothing
    assert [t["symbol"] for t in world.db.trades.docs] == ["MOCKB", "MOCKA"]
    assert sum(1 for t in world.db.trades.docs if (t.get("source") or {}).get("kind") == "ai_trader") == 1


def test_asking_twice_for_the_same_day_creates_no_second_ticket_and_no_second_trade(api, world):
    world.db.strategies.docs.append(strategy_record())
    first = signals(api)
    writes = world.db.tickets.writes
    again = signals(api)
    assert (again["created"], again["existing"]) == (0, 1)
    assert [t["id"] for t in again["tickets"]] == [t["id"] for t in first["tickets"]]
    assert world.db.tickets.writes == writes and len(world.db.tickets.docs) == 1
    assert len(world.db.trades.docs) == 1


def test_the_signal_key_is_unique_in_the_database_and_a_race_opens_nothing(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record())
    signals(api)
    assert ((("user_id", 1), ("strategy_id", 1), ("signal_date", 1), ("symbol", 1)), {"unique": True}) \
        in world.db.tickets.indexes

    async def duplicate(doc):
        raise DuplicateKeyError("ai_trader_tickets")      # MOCK - not real data: another request got there first

    monkeypatch.setattr(world.db.tickets, "insert_one", duplicate)
    world.candidates = [candidate("MOCKZ", 300.0)]
    body = signals(api)
    assert body["created"] == 0
    assert len(world.db.trades.docs) == 1                 # only the first call's trade exists
    assert [t["symbol"] for t in world.db.tickets.docs] == ["MOCKA"]


def test_a_signal_date_in_the_future_is_refused(api, world):
    world.db.strategies.docs.append(strategy_record())
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": "2027-01-04", "mode": "paper"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "as_of_in_the_future")


def test_a_signal_date_inside_the_sealed_block_is_refused_before_anything_is_read(api, world):
    """The sealed 2023-01-01..2024-07-31 block is opened once per strategy by the holdout backtest and by nothing
    else, so the screen must never be run for a date inside it (PRD B4)."""
    world.db.strategies.docs.append(strategy_record())
    for sealed in ("2023-01-01", "2023-06-15", "2024-07-31"):
        r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": sealed, "mode": "paper"}, headers=A)
        assert (r.status_code, r.json()["detail"]) == (422, "sealed_window"), r.text
    assert world.screens == 0
    assert world.db.tickets.docs == [] and world.db.trades.docs == []


def test_a_signal_date_older_than_the_last_few_sessions_is_refused(api, world):
    """A signal is taken off the last session's close. A freely chosen past session lets the paper record that gates
    `assisted` be built out of hindsight, so it is refused."""
    world.db.strategies.docs.append(strategy_record())
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": "2026-09-01", "mode": "paper"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "as_of_too_old")
    assert world.screens == 0 and world.db.tickets.docs == []


def test_the_sector_of_a_position_opened_in_this_run_counts_towards_the_sector_limit(api, world):
    """Four candidates in one sector at Rs 1,00,000 each would be 40% of capital against a 30% sector limit. The
    position just opened carries the sector its ticket already records, so the fourth is refused."""
    world.db.strategies.docs.append(strategy_record())
    world.candidates = [candidate(s, 200.0, sector="IT") for s in ("MOCKA", "MOCKB", "MOCKC", "MOCKD")]
    by_symbol = {t["symbol"]: t for t in signals(api)["tickets"]}
    assert [by_symbol[s]["status"] for s in ("MOCKA", "MOCKB", "MOCKC")] == ["executed_paper"] * 3
    assert by_symbol["MOCKD"]["status"] == "rejected"
    assert "SECTOR_LIMIT" in by_symbol["MOCKD"]["reason_codes"]
    # The sector of every position in this book is known, so the refusal names the sector itself and not an unknown.
    assert "SECTOR_EXPOSURE_UNKNOWN" not in by_symbol["MOCKD"]["reason_codes"]
    assert sum(1 for t in world.db.trades.docs if (t.get("source") or {}).get("kind") == "ai_trader") == 3


def test_the_book_tells_the_governor_the_sector_of_every_position_it_can_resolve(api, world):
    """A position's sector comes from the ticket that opened it. A trade the user opened by hand has no ticket, so it
    has no sector, and the governor is told that rather than shown a zero."""
    world.db.strategies.docs.append(strategy_record())
    signals(api)
    world.db.trades.docs.append(held("user_a", "MANUAL", 100.0))        # opened on the desk, not by a strategy
    book = asyncio.run(route._portfolio("user_a", CAPITAL))
    assert {p.symbol: p.sector for p in book.positions} == {"MOCKA": "Mock Sector", "MANUAL": None}


def test_a_hand_opened_book_is_counted_as_unknown_sector_not_as_diversified(api, world):
    """The one path where the route's half of the sector limit and the governor's half meet: desk trades the user
    opened by hand have no ticket, so their sector cannot be resolved. The book is handed over with those sectors
    unknown, and the governor counts their value against the sector allowance and says it did (PRD B5, F3.3). A
    ticket stored with a blank sector is the same unknown, which is why nothing here normalises it."""
    world.db.strategies.docs.append(strategy_record())
    for i in range(3):                                    # MOCK - not real data: Rs 1,00,000 each, 30% of capital
        world.db.trades.docs.append(desk.new_trade("user_a", {
            "symbol": f"HAND{i}", "quantity": 1000, "entry_price": 100.0, "stop_price": 90.0,
            "target_price": 130.0}, NOW))
    world.db.tickets.docs.append({"_id": "t-blank", "user_id": "user_a", "strategy_id": "strat-0",
                                  "trade_id": world.db.trades.docs[0]["_id"], "sector": ""})
    book = asyncio.run(route._portfolio("user_a", CAPITAL))
    assert [p.sector for p in book.positions] == ["", None, None]

    ticket = signals(api)["tickets"][0]
    assert ticket["status"] == "rejected" and ticket["trade_id"] is None
    assert "SECTOR_EXPOSURE_UNKNOWN" in ticket["reason_codes"]
    assert "SECTOR_LIMIT" in ticket["reason_codes"]
    unknown = next(r for r in ticket["decision"]["reasons"] if r["code"] == "SECTOR_EXPOSURE_UNKNOWN")
    assert unknown["value"] == 300_000.0 and unknown["severity"] == "info"
    assert not any((t.get("source") or {}).get("kind") == "ai_trader" for t in world.db.trades.docs)


def test_a_ticket_the_desk_refuses_is_recorded_and_the_run_still_finishes(api, world, monkeypatch):
    """The desk's validator has limits of its own (its quantity ceiling, its symbol rule). A ticket it refuses is a
    finished ticket with a reason, not a request that dies half way with trades already written."""
    world.db.strategies.docs.append(strategy_record())
    world.candidates = [candidate("MOCKA", 200.0), candidate("MOCKB", 250.0)]
    real_new_trade = desk.new_trade

    def refuse_the_first(uid, body, *a, **kw):
        if body["symbol"] == "MOCKA":
            raise desk.DeskInputError("invalid_quantity")     # MOCK - not real data: the desk's own ceiling
        return real_new_trade(uid, body, *a, **kw)

    monkeypatch.setattr(desk, "new_trade", refuse_the_first)
    body = signals(api)
    by_symbol = {t["symbol"]: t for t in body["tickets"]}
    assert body["created"] == 2
    assert (by_symbol["MOCKA"]["status"], by_symbol["MOCKA"]["rejected_by"]) == ("rejected", "desk")
    assert by_symbol["MOCKA"]["reject_reason"] == "invalid_quantity"
    assert by_symbol["MOCKA"]["trade_id"] is None and by_symbol["MOCKA"]["text"] is None
    assert by_symbol["MOCKB"]["status"] == "executed_paper"               # the loop finished
    stored = {t["symbol"]: t for t in world.db.tickets.docs}
    assert stored["MOCKA"]["status"] == "rejected"                        # not left in the transient "confirmed"
    assert [t["symbol"] for t in world.db.trades.docs] == ["MOCKB"]


def test_signals_refuse_to_write_a_ticket_while_the_idempotence_index_is_missing(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record())

    async def no_index(keys, **kw):
        if kw.get("unique"):
            raise RuntimeError("not authorised to build an index")        # MOCK - not real data
        return None

    monkeypatch.setattr(world.db.tickets, "create_index", no_index)
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "paper"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (503, "idempotence_index_unavailable")
    assert world.db.tickets.docs == [] and world.db.trades.docs == []


def test_when_the_screen_cannot_be_read_nothing_is_invented(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record())

    async def boom(spec_, as_of):
        raise RuntimeError("no Postgres here")                     # MOCK - not real data

    monkeypatch.setattr(route, "_screen", boom)
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "paper"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (503, "market_data_unavailable")
    assert world.db.tickets.docs == []


# ── Phase 5 routes: assisted tickets ─────────────────────────────────────────
def assisted_ticket(api, world, uid="user_a", capital=CAPITAL):
    world.db.strategies.docs.append(strategy_record(uid, stage="assisted", capital=capital))
    body = signals(api, mode="assisted", who={"X-Test-User": uid})
    assert body["created"] == 1
    return body["tickets"][0]


def test_an_assisted_signal_waits_for_the_user_and_records_no_trade_yet(api, world):
    ticket = assisted_ticket(api, world)
    assert (ticket["status"], ticket["quantity"], ticket["trade_id"]) == ("awaiting_confirmation", 500, None)
    assert ticket["expires_at"] == "2026-10-21T10:00:00+00:00"     # the next session's close, 15:30 IST
    assert world.db.trades.docs == []
    assert ticket["text"] and execution.SELF_PLACE_LINE in ticket["text"]


def test_confirming_re_runs_the_governor_then_records_a_shadow_trade_and_returns_the_order_text(api, world):
    ticket = assisted_ticket(api, world)
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticket"]["status"] == "executed_paper" and body["ticket"]["quantity"] == 500
    assert body["trade"]["quantity"] == 500 and body["trade"]["symbol"] == "MOCKA"
    assert body["trade"]["source"]["kind"] == "ai_trader"
    for part in ("MOCKA", "500", "200.00", "180.00", "240.00"):
        assert part in body["text"], body["text"]
    assert execution.SELF_PLACE_LINE in body["text"]
    assert len(world.db.trades.docs) == 1
    # confirming again changes nothing
    r2 = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert (r2.status_code, r2.json()["detail"]) == (409, "ticket_not_awaiting_confirmation")
    assert len(world.db.trades.docs) == 1


def test_confirming_never_approves_more_than_the_governor_allowed_on_the_signal_date(api, world):
    """The confirm re-run may lower the size or refuse it, never raise it. An elevated VIX halved the size when the
    ticket was made; the same index row is not there yet when the user confirms the next morning, and that unknown
    must not hand back the shares the volatility rule took away (PRD F5.2, B5)."""
    world.market = Market(vix=28.0, regime="BULL")
    ticket = assisted_ticket(api, world)
    assert (ticket["quantity"], ticket["requested_quantity"]) == (250, 500)
    assert "VIX_REDUCE" in ticket["reason_codes"]

    world.market = Market()                 # MOCK - not real data: today's VIX row has not landed yet
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticket"]["quantity"] == 250
    assert body["ticket"]["decision"]["action"] == "reduce"
    assert "SIZE_CAPPED_AT_SIGNAL" in body["ticket"]["reason_codes"]
    assert body["trade"]["quantity"] == 250
    assert "250 share(s)" in body["text"], body["text"]
    assert world.db.tickets.docs[0]["quantity"] == 250


def test_confirming_is_refused_with_the_new_reasons_when_the_book_now_breaches_a_limit(api, world):
    ticket = assisted_ticket(api, world)
    for i in range(DEFAULT_LIMITS.max_open_positions):
        world.db.trades.docs.append(held("user_a", f"MOCKH{i}"))
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "risk_refused" and "MAX_POSITIONS" in detail["reason_codes"]
    assert detail["decision"]["action"] == "reject" and detail["decision"]["approved_qty"] == 0
    stored = world.db.tickets.docs[0]
    assert stored["status"] == "awaiting_confirmation" and stored["trade_id"] is None
    assert "MAX_POSITIONS" in [r_["code"] for r_ in stored["last_decision"]["reasons"]]
    assert not any((t.get("source") or {}).get("kind") == "ai_trader" for t in world.db.trades.docs)
    # The ticket still waits for the book to free up, but it must not read like an order the governor cleared.
    listed = api.get(f"{BASE}/tickets", headers=A).json()["tickets"]
    assert [t["status"] for t in listed] == ["awaiting_confirmation"] and listed[0]["text"] is None


def test_a_confirm_the_desk_refuses_leaves_the_ticket_answerable(api, world, monkeypatch):
    """"confirmed" is a transient status no route can answer. A paper trade that cannot be written must put the
    ticket back where the user can confirm it again or let it expire, not strand it there."""
    ticket = assisted_ticket(api, world)
    real_new_trade = desk.new_trade

    def refuse(uid, body, *a, **kw):
        raise desk.DeskInputError("invalid_quantity")        # MOCK - not real data: the desk's own ceiling

    monkeypatch.setattr(desk, "new_trade", refuse)
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_quantity"), r.text
    stored = world.db.tickets.docs[0]
    assert (stored["status"], stored["quantity"], stored["trade_id"]) == ("awaiting_confirmation", 500, None)
    assert world.db.trades.docs == []

    monkeypatch.setattr(desk, "new_trade", real_new_trade)
    again = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert again.status_code == 200, again.text
    assert again.json()["ticket"]["status"] == "executed_paper"


def test_the_liquidity_limit_is_re_applied_on_confirm_from_the_value_the_ticket_stored(api, world):
    world.candidates = [{**candidate("MOCKA", 200.0), "avg_daily_value": 400_000.0}]
    ticket = assisted_ticket(api, world)
    assert (ticket["quantity"], ticket["avg_daily_value"]) == (100, 400_000.0)   # 5% of Rs 4,00,000 at Rs 200
    assert "LIQUIDITY" in ticket["reason_codes"]
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert r.status_code == 200, r.text
    codes = r.json()["ticket"]["reason_codes"]
    assert "LIQUIDITY" in codes and "LIQUIDITY_UNKNOWN" not in codes
    assert r.json()["trade"]["quantity"] == 100


def test_an_expired_ticket_is_shown_as_expired_and_can_neither_be_confirmed_nor_rejected(api, world):
    ticket = assisted_ticket(api, world)
    world.db.tickets.docs[0]["expires_at"] = "2026-10-20T10:00:00+00:00"    # MOCK - not real data: yesterday's close
    listed = api.get(f"{BASE}/tickets", headers=A).json()["tickets"]
    assert [t["status"] for t in listed] == ["expired"]
    for path in ("confirm", "reject"):
        r = api.post(f"{BASE}/tickets/{ticket['id']}/{path}", json={}, headers=A)
        assert (r.status_code, r.json()["detail"]) == (409, "ticket_expired")
    assert world.db.trades.docs == []


def test_rejecting_a_ticket_stores_the_reason(api, world):
    ticket = assisted_ticket(api, world)
    r = api.post(f"{BASE}/tickets/{ticket['id']}/reject", json={"reason": "I do not want this stock"}, headers=A)
    assert r.status_code == 200, r.text
    assert r.json()["ticket"]["status"] == "rejected"
    stored = world.db.tickets.docs[0]
    assert (stored["status"], stored["rejected_by"], stored["reject_reason"]) == \
        ("rejected", "user", "I do not want this stock")
    assert world.db.trades.docs == []
    again = api.post(f"{BASE}/tickets/{ticket['id']}/reject", json={}, headers=A)
    assert (again.status_code, again.json()["detail"]) == (409, "ticket_not_awaiting_confirmation")


def test_a_reject_that_writes_nothing_says_so_instead_of_reporting_the_ticket_declined(api, world, monkeypatch):
    """A confirm that lands between this request's read and its write owns the ticket. The reject then matches no
    document, and reporting "rejected" would be a status the database does not hold."""
    ticket = assisted_ticket(api, world)
    snapshot = copy.deepcopy(world.db.tickets.docs[0])

    async def read_before_the_confirm(uid, ticket_id):
        return copy.deepcopy(snapshot)          # MOCK - not real data: the state the reject request read

    api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert world.db.tickets.docs[0]["status"] == "executed_paper"
    monkeypatch.setattr(route, "_own_ticket", read_before_the_confirm)
    r = api.post(f"{BASE}/tickets/{ticket['id']}/reject", json={"reason": "too late"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "ticket_not_awaiting_confirmation"), r.text
    assert world.db.tickets.docs[0]["status"] == "executed_paper"


def test_the_ticket_list_filters_by_status_and_strategy(api, world):
    ticket = assisted_ticket(api, world)
    assert len(api.get(f"{BASE}/tickets", params={"status": "awaiting_confirmation"}, headers=A).json()["tickets"]) == 1
    assert api.get(f"{BASE}/tickets", params={"status": "rejected"}, headers=A).json()["tickets"] == []
    assert len(api.get(f"{BASE}/tickets", params={"strategy_id": "strat-1"}, headers=A).json()["tickets"]) == 1
    assert api.get(f"{BASE}/tickets", params={"strategy_id": "nope"}, headers=A).json()["tickets"] == []
    r = api.get(f"{BASE}/tickets", params={"status": "whatever"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_status")
    assert ticket["id"]


# ── ownership and auth ───────────────────────────────────────────────────────
def test_another_users_strategy_and_ticket_are_404_and_never_listed(api, world):
    ticket = assisted_ticket(api, world)
    for method, path in [("get", f"{BASE}/strategies/strat-1"), ("get", f"{BASE}/strategies/strat-1/journal")]:
        assert getattr(api, method)(path, headers=B).status_code == 404
    assert api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "assisted"},
                    headers=B).status_code == 404
    assert api.post(f"{BASE}/strategies/strat-1/promote", json={"target_stage": "retired"},
                    headers=B).status_code == 404
    assert api.post(f"{BASE}/strategies/strat-1/backtest",
                    json={"from_date": "2021-01-01", "to_date": "2021-12-31"}, headers=B).status_code == 404
    for path in (f"{BASE}/tickets/{ticket['id']}/confirm", f"{BASE}/tickets/{ticket['id']}/reject"):
        r = api.post(path, json={}, headers=B)
        assert (r.status_code, r.json()["detail"]) == (404, "ticket_not_found")
    assert api.get(f"{BASE}/tickets", headers=B).json()["tickets"] == []
    assert api.get(f"{BASE}/strategies", headers=B).json()["strategies"] == []
    assert world.db.trades.docs == []


def test_every_new_route_needs_a_signed_in_user():
    app = FastAPI()
    app.include_router(route.router)
    c = TestClient(app)
    assert c.get(f"{BASE}/strategies").status_code == 401
    assert c.post(f"{BASE}/strategies", json={"symbols": ["MOCKA"], "as_of": AS_OF}).status_code == 401
    assert c.get(f"{BASE}/strategies/strat-1").status_code == 401
    assert c.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": AS_OF, "mode": "paper"}).status_code == 401
    assert c.get(f"{BASE}/tickets").status_code == 401
    assert c.post(f"{BASE}/tickets/t1/confirm").status_code == 401
    assert c.post(f"{BASE}/tickets/t1/reject", json={}).status_code == 401
    assert c.get(f"{BASE}/strategies/strat-1/journal").status_code == 401


@pytest.mark.parametrize("path, body", [
    ("/strategies", {}),
    ("/strategies", {"symbols": [], "as_of": AS_OF}),
    ("/strategies", {"symbols": ["MOCKA"], "as_of": "not-a-date"}),
    ("/strategies", {"symbols": ["MOCKA"], "as_of": AS_OF, "extra": 1}),
    ("/strategies/strat-1/signals", {"as_of": AS_OF}),
    ("/strategies/strat-1/signals", {"as_of": AS_OF, "mode": "paper", "extra": 1}),
    ("/strategies/strat-1/backtest", {"from_date": "2021-01-01"}),
    ("/strategies/strat-1/promote", {}),
])
def test_a_bad_body_is_422(api, world, path, body):
    world.db.strategies.docs.append(strategy_record())
    assert api.post(f"{BASE}{path}", json=body, headers=A).status_code == 422


def test_a_symbol_or_a_ui_config_field_the_platform_does_not_set_is_refused(api, world):
    r = api.post(f"{BASE}/strategies", json={"symbols": ["bad symbol!"], "as_of": AS_OF}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_symbol")
    r = api.post(f"{BASE}/strategies", json={"symbols": ["MOCKA"], "as_of": AS_OF,
                                             "ui_config": {"max_positions": 20}}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "unknown_ui_config_field")
    assert world.db.strategies.docs == []


# ── the strategy routes this file also owns (Phase 2 code is monkeypatched) ──
def test_a_strategy_is_proposed_stored_at_draft_and_listed_for_its_owner_only(api, world, monkeypatch):
    proposal = {"spec": spec(), "config": config(), "template": "momentum_breakout", "regime": "BULL",
                "provenance": {"as_of": AS_OF}}                          # MOCK - not real data
    monkeypatch.setattr(strategy, "propose", lambda evidence, **kw: copy.deepcopy(proposal))
    r = api.post(f"{BASE}/strategies", json={"symbols": ["MOCKA"], "as_of": AS_OF, "name": "My mock"}, headers=A)
    assert r.status_code == 201, r.text
    doc = r.json()["strategy"]
    assert (doc["stage"], doc["created_by"], doc["name"]) == ("draft", "ai", "My mock")
    assert doc["version"] and doc["spec"]["exit"]["stoploss_pct"] == 10.0
    assert [s["id"] for s in api.get(f"{BASE}/strategies", headers=A).json()["strategies"]] == [doc["id"]]
    assert api.get(f"{BASE}/strategies", headers=B).json()["strategies"] == []


def test_no_strategy_is_proposed_without_a_readable_market_regime(api, world, monkeypatch):
    def refuse(evidence, **kw):
        raise strategy.StrategyError("regime_unavailable")

    monkeypatch.setattr(strategy, "propose", refuse)
    r = api.post(f"{BASE}/strategies", json={"symbols": ["MOCKA"], "as_of": "2023-06-01"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "regime_unavailable")
    assert world.db.strategies.docs == []


def test_the_backtest_route_reports_the_sealed_window_and_a_used_holdout(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record(stage="draft"))

    async def pool():
        return object()                                             # MOCK - not real data: stands in for asyncpg

    monkeypatch.setattr(route.pg_client, "get_pool", pool)

    async def sealed(doc, **kw):
        raise strategy.SealedWindowRefused("2023-01-01..2023-02-01 overlaps the sealed block")

    monkeypatch.setattr(strategy, "run_backtest_for", sealed)
    r = api.post(f"{BASE}/strategies/strat-1/backtest",
                 json={"from_date": "2023-01-01", "to_date": "2023-02-01"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "sealed_window")

    async def used(doc, **kw):
        raise strategy.HoldoutUsed("already opened")

    monkeypatch.setattr(strategy, "run_backtest_for", used)
    r = api.post(f"{BASE}/strategies/strat-1/backtest",
                 json={"from_date": "2023-01-01", "to_date": "2023-02-01", "holdout": True}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "holdout_used")


def test_the_backtest_route_stores_the_run_on_the_strategy(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record(stage="draft", win_rate=None))

    async def pool():
        return object()

    monkeypatch.setattr(route.pg_client, "get_pool", pool)
    run = {"run_id": "run-x", "metrics": {"trade_count": 120}, "walk_forward": [], "holdout": False,
           "window": {"from_date": "2021-01-01", "to_date": "2021-12-31"}}      # MOCK - not real data

    async def fake_run(doc, **kw):
        doc.setdefault("runs", []).append(run)
        doc["updated_at"] = "2026-10-21T05:00:00+00:00"
        return run

    monkeypatch.setattr(strategy, "run_backtest_for", fake_run)
    r = api.post(f"{BASE}/strategies/strat-1/backtest",
                 json={"from_date": "2021-01-01", "to_date": "2021-12-31"}, headers=A)
    assert r.status_code == 200, r.text
    assert r.json()["run"]["run_id"] == "run-x"
    assert [x["run_id"] for x in world.db.strategies.docs[0]["runs"]] == ["run-x"]


def _sealed_backtest(api, world, monkeypatch, runner):
    """The real `run_backtest_for` over the whole sealed block, with only the backtester itself replaced."""
    world.db.strategies.docs.append(strategy_record(stage="draft"))

    async def pool():
        return object()                                   # MOCK - not real data: stands in for asyncpg

    monkeypatch.setattr(route.pg_client, "get_pool", pool)
    monkeypatch.setattr(route, "run_backtest", runner)
    return {"from_date": "2023-01-01", "to_date": "2024-07-31", "holdout": True}


def test_a_backtest_appends_its_run_instead_of_rewriting_the_list_from_its_own_snapshot(api, world, monkeypatch):
    """Two backtests of one strategy overlap by construction: the runner is awaited five times between the read and
    the write. The run is appended, so the one that finishes second does not erase the first."""
    world.db.strategies.docs.append(strategy_record(stage="draft", win_rate=None))

    async def pool():
        return object()                                   # MOCK - not real data: stands in for asyncpg

    monkeypatch.setattr(route.pg_client, "get_pool", pool)
    stale = copy.deepcopy(world.db.strategies.docs[0])    # the snapshot the second request read
    made = iter(["run-a", "run-b"])

    async def fake_run(doc, **kw):
        run = {"run_id": next(made), "metrics": {"trade_count": 120}, "walk_forward": [], "holdout": False,
               "window": {"from_date": "2021-01-01", "to_date": "2021-12-31"}}     # MOCK - not real data
        doc.setdefault("runs", []).append(run)
        doc["updated_at"] = "2026-10-21T05:00:00+00:00"
        return run

    monkeypatch.setattr(strategy, "run_backtest_for", fake_run)
    window = {"from_date": "2021-01-01", "to_date": "2021-12-31"}
    assert api.post(f"{BASE}/strategies/strat-1/backtest", json=window, headers=A).status_code == 200

    async def read_the_stale_snapshot(uid, sid):
        return copy.deepcopy(stale)

    monkeypatch.setattr(route, "_own_strategy", read_the_stale_snapshot)
    assert api.post(f"{BASE}/strategies/strat-1/backtest", json=window, headers=A).status_code == 200
    assert [x["run_id"] for x in world.db.strategies.docs[0]["runs"]] == ["run-a", "run-b"]


def test_the_seal_is_not_spent_on_a_strategy_that_has_no_ordinary_run_yet(api, world, monkeypatch):
    """The holdout confirms a strategy that already has a record. Spent as the first run it buys nothing and cannot
    be given back, so it is refused while no ordinary run exists."""
    reads: List[Any] = []

    async def boom(pool_, spec_, **kw):
        reads.append(kw)
        raise RuntimeError("this must never be reached")             # MOCK - not real data

    body = _sealed_backtest(api, world, monkeypatch, boom)
    world.db.strategies.docs[0]["runs"] = []
    r = api.post(f"{BASE}/strategies/strat-1/backtest", json=body, headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "holdout_before_backtest"), r.text
    assert reads == [] and world.db.strategies.docs[0]["holdout_used"] is False


def test_a_holdout_run_that_fails_half_way_still_spends_the_seal(api, world, monkeypatch):
    """The sealed block is read the moment the window is handed to the backtester, so a run that fails after that
    must leave the block recorded as opened: a retry may not read it a second time (PRD B4)."""
    reads: List[Any] = []

    async def boom(pool_, spec_, **kw):
        reads.append(kw)
        raise RuntimeError("the feature store timed out")           # MOCK - not real data

    body = _sealed_backtest(api, world, monkeypatch, boom)
    r = api.post(f"{BASE}/strategies/strat-1/backtest", json=body, headers=A)
    assert (r.status_code, r.json()["detail"]) == (503, "market_data_unavailable"), r.text
    stored = world.db.strategies.docs[0]
    assert stored["holdout_used"] is True
    assert stored["holdout_window"] == {"from_date": "2023-01-01", "to_date": "2024-07-31"}
    again = api.post(f"{BASE}/strategies/strat-1/backtest", json=body, headers=A)
    assert (again.status_code, again.json()["detail"]) == (409, "holdout_used"), again.text
    assert len(reads) == 1                         # the sealed window was handed over once, not once per attempt


def test_the_seal_is_claimed_in_the_database_before_the_block_is_handed_over(api, world, monkeypatch):
    """Two requests that both read the strategy while holdout_used was false must not both open the block: the claim
    is a conditional write, not a read-then-act check on the snapshot each request holds."""
    run = {"run_id": "run-h", "metrics": {"trade_count": 120}, "walk_forward": [], "holdout": True,
           "window": {"from_date": "2023-01-01", "to_date": "2024-07-31"}}      # MOCK - not real data
    reads: List[Any] = []

    async def stale_run(doc, **kw):
        """MOCK - not real data: a runner that reads the block and keeps no record of its own, the way a second
        request holding an older snapshot of the strategy would behave."""
        reads.append(kw)
        doc.setdefault("runs", []).append(run)
        doc["updated_at"] = "2026-10-21T05:00:00+00:00"
        return run

    body = _sealed_backtest(api, world, monkeypatch, None)
    monkeypatch.setattr(strategy, "run_backtest_for", stale_run)
    first = api.post(f"{BASE}/strategies/strat-1/backtest", json=body, headers=A)
    assert first.status_code == 200, first.text
    assert first.json()["strategy"]["holdout_used"] is True
    second = api.post(f"{BASE}/strategies/strat-1/backtest", json=body, headers=A)
    assert (second.status_code, second.json()["detail"]) == (409, "holdout_used"), second.text
    assert len(reads) == 1
    # The run is appended to the stored list, so the run the strategy already had is still there.
    assert [x["run_id"] for x in world.db.strategies.docs[0]["runs"]] == ["run-1", "run-h"]


def test_a_failing_gate_answers_409_with_the_unmet_criteria_and_live_is_not_a_stage(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record(stage="backtested"))
    unmet = [{"code": "trade_count", "label": "Backtest trades", "value": 12, "threshold": 100, "passed": False}]

    def refuse(doc, target_stage, **kw):
        raise strategy.GateNotMet(target_stage, unmet)

    monkeypatch.setattr(strategy, "promote", refuse)
    r = api.post(f"{BASE}/strategies/strat-1/promote", json={"target_stage": "paper"}, headers=A)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"code": "gate_not_met", "target_stage": "paper", "unmet": unmet}
    assert world.db.strategies.docs[0]["stage"] == "backtested"
    r = api.post(f"{BASE}/strategies/strat-1/promote", json={"target_stage": "live"}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_stage")


def test_a_promotion_that_passes_is_stored_with_the_paper_tally_the_gate_read(api, world, monkeypatch):
    world.db.strategies.docs.append(strategy_record(stage="paper"))
    seen: Dict[str, Any] = {}

    def allow(doc, target_stage, **kw):
        seen.update(kw)
        return {**doc, "stage": target_stage, "stage_history": list(doc["stage_history"]) + [{"stage": target_stage}],
                "updated_at": "2026-10-21T05:00:00+00:00"}

    monkeypatch.setattr(strategy, "promote", allow)
    r = api.post(f"{BASE}/strategies/strat-1/promote", json={"target_stage": "assisted"}, headers=A)
    assert r.status_code == 200, r.text
    assert r.json()["strategy"]["stage"] == "assisted"
    assert world.db.strategies.docs[0]["stage"] == "assisted"
    assert seen["paper_stats"]["closed_trades"] == 0        # nothing has closed yet, and that is what the gate reads


# ── what the governor is handed: the book and the market ─────────────────────
def test_the_book_handed_to_the_governor_is_the_users_own_open_trades_and_todays_pnl(world):
    world.db.trades.docs.append(held("user_a", "MOCKA", 100.0))
    world.db.trades.docs.append(held("user_b", "MOCKB", 100.0))              # another user's book
    closed = held("user_a", "MOCKC", 50.0)
    closed.update({"status": "closed", "closed_at": "2026-10-21T04:00:00+00:00", "realized_pnl_rs": -1200.0})
    world.db.trades.docs.append(closed)
    stale = held("user_a", "MOCKD", 50.0)
    stale.update({"status": "closed", "closed_at": "2026-10-19T04:00:00+00:00", "realized_pnl_rs": -9999.0})
    world.db.trades.docs.append(stale)                                        # closed on an earlier session

    book = asyncio.run(route._portfolio("user_a", CAPITAL))
    assert book.capital == CAPITAL
    assert [(p.symbol, p.quantity, p.price) for p in book.positions] == [("MOCKA", 1, 100.0)]
    assert book.realized_pnl_today == -1200.0
    assert book.drawdown_pct is None and book.kill_switch is False


def test_the_market_handed_to_the_governor_is_read_from_the_evidence_and_unknowns_stay_unknown(monkeypatch):
    from services.ai_trader import evidence as ev

    def made_up(as_of):
        """MOCK - not real data: shaped like services/ai_trader/context.py's market_context output."""
        base = dict(skill="market_intelligence", symbol=None, as_of=as_of, horizon="market",
                    interpretation="mock", confidence=0.5, decision_impact="neutral")
        return [ev.Evidence(observation="regime", data={"regime": {"value": "BEAR", "status": "OK", "reason": None}},
                            **base),
                ev.Evidence(observation="vix", data={"india_vix": 28.5}, **base),
                ev.unavailable("market_intelligence", None, as_of, "market", "breadth", "NO_DATA_FOR_DATE")]

    monkeypatch.setattr(route, "market_context", made_up)
    market = route._market(AS_OF)
    assert (market.vix, market.regime) == (28.5, "BEAR")

    def unavailable_engine(as_of):
        raise route._research.ResearchUnavailable("the research package is not on this host")

    monkeypatch.setattr(route, "market_context", unavailable_engine)
    blind = route._market(AS_OF)
    assert blind.vix is None and blind.regime is None          # never filled in, so the governor says it skipped


# ── the outcome journal ──────────────────────────────────────────────────────
def test_the_journal_scores_closed_shadow_trades_against_the_stated_confidence(api, world):
    world.db.strategies.docs.append(strategy_record())
    world.candidates = [candidate("MOCKA", 200.0), candidate("MOCKB", 250.0)]
    body = signals(api)
    assert body["created"] == 2
    # MOCK - not real data: close the two shadow trades, one winner and one loser
    for trade, pnl in zip(world.db.trades.docs, (5000.0, -2000.0)):
        trade.update({"status": "closed", "closed_at": "2026-10-21T05:00:00+00:00", "exit_reason": "target",
                      "exit_price": trade["target_price"], "realized_pnl_rs": pnl})
    r = api.get(f"{BASE}/strategies/strat-1/journal", headers=A)
    assert r.status_code == 200, r.text
    journal = r.json()
    assert journal["calibration"]["n"] == 2
    assert journal["calibration"]["brier"] == pytest.approx(0.26)
    assert journal["calibration"]["calibration_error"] == pytest.approx(0.1)
    bin_60 = next(b for b in journal["calibration"]["bins"] if b["low"] == 0.6)
    assert (bin_60["n"], bin_60["observed_rate"], bin_60["mean_confidence"]) == (2, 0.5, pytest.approx(0.6))
    assert journal["paper_stats"]["closed_trades"] == 2
    assert (journal["paper_stats"]["win_rate"], journal["paper_stats"]["expectancy"]) == (50.0, 1500.0)
    assert journal["paper_stats"]["profit_factor"] == 2.5
    assert journal["tickets"]["executed_paper"] == 2


def test_the_paper_record_is_every_closed_trade_of_the_strategy_not_the_newest_page_of_the_desk(api, world,
                                                                                               monkeypatch):
    """The strategy's closed trades are selected by the ids its tickets recorded. Reading the desk's newest-first
    page first and filtering afterwards would drop this strategy's older trades once the desk holds more than the
    page, and the gate would be scored on a slice presented as the whole record."""
    world.db.strategies.docs.append(strategy_record())
    world.candidates = [candidate("MOCKA", 200.0), candidate("MOCKB", 250.0)]
    signals(api)
    for trade, closed_at, pnl in zip(world.db.trades.docs, ("2026-10-20T05:00:00+00:00",
                                                            "2026-10-21T05:00:00+00:00"), (5000.0, -2000.0)):
        trade.update({"status": "closed", "closed_at": closed_at, "exit_reason": "target",
                      "exit_price": trade["target_price"], "realized_pnl_rs": pnl})
    monkeypatch.setattr(desk, "MAX_CLOSED_LISTED", 1)      # MOCK - not real data: a desk with a longer history
    journal = api.get(f"{BASE}/strategies/strat-1/journal", headers=A).json()
    assert journal["paper_stats"]["closed_trades"] == 2
    assert journal["calibration"]["n"] == 2


def test_the_journal_scores_nothing_before_a_trade_closes(api, world):
    world.db.strategies.docs.append(strategy_record())
    signals(api)
    journal = api.get(f"{BASE}/strategies/strat-1/journal", headers=A).json()
    assert journal["calibration"]["n"] == 0 and journal["calibration"]["brier"] is None
    assert journal["paper_stats"]["closed_trades"] == 0 and journal["paper_stats"]["expectancy"] is None
