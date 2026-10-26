"""The shared F&O risk gate (services/risk_gate): test_reports/fno_risk_foundation_TESTCASES.md RG-1 to RG-18 and
W-11 to W-13.

No network and no real database. Replaced, and by what:
  * the database            FakeDB below (equality filters, the update operators the code uses, failure injection)
  * the exchange reference  `reference.lookup` in the gate tests (the reference module has its own tests below,
                            with the Kite list and the data platform's answer faked instead)
  * the clock               `now=` passed to gate.check: 2026-10-21 05:00 UTC, a Wednesday, 10:30 IST

MOCK — not real data: every symbol, strike, premium and lot size below is made up. Worked by hand:
  bull call spread  buy 100 C @ 6, sell 110 C @ 2, 50 shares: debit 4 x 50 = Rs 200 maximum loss
  long straddle     buy 100 C @ 5, buy 100 P @ 4, 50 shares: both premiums, 9 x 50 = Rs 450 (not 0)
  iron condor       buy 90 P @ 1, sell 95 P @ 3, sell 105 C @ 3, buy 110 C @ 1: credit 4, wing 5, (5 - 4) x 50 = Rs 50
  hedged future     buy future @ 100, buy 95 P @ 2: (100 - 95 + 2) x 50 = Rs 350
"""
from __future__ import annotations

import asyncio
import copy
import inspect
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import feature_flags as ff
import feature_gate
from services import fno_margin
from services import risk_controls as rc
from services import risk_gate
from services.copilot_tools import daas_client
from services.risk_gate import gate, policy, reference
from services.risk_gate.contract import RiskRequest, inputs_hash

NOW = datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 21)
EXP = "2026-10-27"


# ── an in-memory Mongo stand-in, shared by the other risk test files ─────────
def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for key, cond in query.items():
        assert not isinstance(cond, dict), f"the fake collection does not know {cond}"
        if doc.get(key) != cond:
            return False
    return True


class _Result:
    def __init__(self, matched: int = 0, deleted: int = 0):
        self.matched_count = self.modified_count = matched
        self.deleted_count = deleted


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


class FakeCollection:
    def __init__(self, name: str, db: "FakeDB"):
        self.name, self.db = name, db
        self.docs: List[Dict[str, Any]] = []
        self.indexes: List[Any] = []
        self.update_filters: List[Dict[str, Any]] = []

    def _maybe_fail(self, op: str) -> None:
        err = self.db.fail.get((self.name, op))
        if err is not None:
            raise err

    async def create_index(self, keys, **kw):
        self._maybe_fail("create_index")
        self.indexes.append((tuple(keys), kw))

    async def find_one(self, query, projection=None):
        self._maybe_fail("find_one")
        doc = next((d for d in self.docs if _matches(d, query)), None)
        return copy.deepcopy(doc) if doc is not None else None

    def find(self, query, projection=None):
        self._maybe_fail("find")
        return _Cursor([copy.deepcopy(d) for d in self.docs if _matches(d, query)])

    async def count_documents(self, query):
        self._maybe_fail("count_documents")
        return sum(1 for d in self.docs if _matches(d, query))

    async def insert_one(self, doc):
        self._maybe_fail("insert_one")
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update, upsert=False):
        self._maybe_fail("update_one")
        self.update_filters.append(dict(query))
        assert set(update) <= {"$set", "$setOnInsert", "$push", "$inc"}, update
        for d in self.docs:
            if _matches(d, query):
                d.update(copy.deepcopy(update.get("$set") or {}))
                for key, value in (update.get("$push") or {}).items():
                    d.setdefault(key, []).append(copy.deepcopy(value))
                for key, delta in (update.get("$inc") or {}).items():
                    d[key] = (d.get(key) or 0) + delta
                return _Result(matched=1)
        if upsert:
            doc = copy.deepcopy(update.get("$setOnInsert") or {})
            doc.update(copy.deepcopy(update.get("$set") or {}))
            self.docs.append(doc)
        return _Result()

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if _matches(d, query):
                del self.docs[i]
                return _Result(deleted=1)
        return _Result()


class FakeDB:
    def __init__(self):
        self.cols: Dict[str, FakeCollection] = {}
        self.fail: Dict[tuple, Exception] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.cols:
            self.cols[name] = FakeCollection(name, self)
        return self.cols[name]

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── request builders ─────────────────────────────────────────────────────────
def opt(side: str, option_type: str, strike: float, price: float, lots: int = 1, lot_size: int = 50,
        expiry: str = EXP) -> Dict[str, Any]:
    return {"kind": "option", "side": side, "lots": lots, "lot_size": lot_size, "entry_price": price,
            "expiry": expiry, "strike": strike, "option_type": option_type}


def fut(side: str, price: float, lots: int = 1, lot_size: int = 50, expiry: str = EXP) -> Dict[str, Any]:
    return {"kind": "future", "side": side, "lots": lots, "lot_size": lot_size, "entry_price": price,
            "expiry": expiry, "strike": None, "option_type": None}


def spread(**over) -> List[Dict[str, Any]]:
    return [opt("buy", "call", 100, 6, **over), opt("sell", "call", 110, 2, **over)]


def struct(legs: List[Dict[str, Any]], **over) -> RiskRequest:
    fields = {"correlation_id": "cid-1", "user_id": "u1", "actor_id": "u1", "mode": "paper",
              "path": "desk_paper_trade", "action": "open", "instrument": "structure", "symbol": "MOCKU",
              "legs": legs}
    fields.update(over)
    return RiskRequest(**fields)


def cash(**over) -> RiskRequest:
    fields = {"correlation_id": "cid-1", "user_id": "u1", "actor_id": "u1", "mode": "paper",
              "path": "desk_paper_trade", "action": "open", "instrument": "cash", "symbol": "MOCKA",
              "quantity": 10, "capital_at_risk_rs": 1000.0}
    fields.update(over)
    return RiskRequest(**fields)


def listed(lot: Optional[int] = 50) -> Dict[str, Any]:
    return {"listed": True, "lot_size": lot, "source": reference.BHAVCOPY_SOURCE, "as_of": "2026-10-20",
            "error": None if lot else "the bhavcopy has no single lot size for that contract"}


@pytest.fixture
def world(monkeypatch):
    w = SimpleNamespace(db=FakeDB(), refs={EXP: listed()}, lookups=[])
    monkeypatch.setattr(rc, "_indexes_ready", False)

    async def lookup(underlying, expiries, today):
        w.lookups.append((underlying, sorted(expiries), today))
        return {e: w.refs.get(e, {"listed": False, "lot_size": None, "source": reference.BHAVCOPY_SOURCE,
                                  "as_of": "2026-10-20", "error": "no contract with that expiry"}) for e in expiries}

    monkeypatch.setattr(reference, "lookup", lookup)
    return w


def judge(w, req: RiskRequest):
    return run(gate.check(w.db, req, now=NOW))


def codes(decision) -> List[str]:
    return [r.code for r in decision.reasons]


# ── RG-1, RG-13, RG-17: an allowed structure, recorded, checks in order ──────
def test_a_verified_defined_risk_spread_is_allowed_and_recorded(world):
    d = judge(world, struct(spread()))
    assert d.outcome == "allow" and d.reasons == []
    assert [c.check for c in d.checks] == list(gate.CHECK_ORDER)
    assert [c.status for c in d.checks] == ["pass"] * len(gate.CHECK_ORDER)
    assert d.policy_version == policy.POLICY_VERSION == "fno-risk-v1"
    (row,) = world.db[rc.DECISIONS].docs
    assert row["_id"] == d.decision_id and row["outcome"] == "allowed" and row["source"] == "risk_gate"
    assert (row["correlation_id"], row["path"], row["mode"], row["inputs_hash"]) == (
        "cid-1", "desk_paper_trade", "paper", d.inputs_hash)
    assert row["reasons"] == [] and row["user_id"] == "u1" and row["actor_id"] == "u1"
    assert row["detail"]["capital_at_risk_rs"] == 200.0          # worked example: debit 4 x 50
    assert world.lookups == [("MOCKU", [EXP], TODAY)]


def test_every_decision_allow_or_block_is_recorded(world):
    judge(world, struct(spread()))
    judge(world, struct([fut("buy", 100)]))
    assert [r["outcome"] for r in world.db[rc.DECISIONS].docs] == ["allowed", "blocked"]


def test_a_cash_position_skips_the_contract_checks_and_says_why(world):
    d = judge(world, cash())
    assert d.outcome == "allow"
    by = {c.check: c for c in d.checks}
    assert by["lot_size"].status == by["expiry"].status == by["open_structures"].status == "skipped"
    assert by["defined_risk"].status == "pass" and world.lookups == []


# ── RG-2, RG-3: the controls ─────────────────────────────────────────────────
@pytest.mark.parametrize("field, code", [("kill_switch", "kill_switch_on"), ("halted", "trading_halted")])
def test_the_kill_switch_and_the_halt_block(world, field, code):
    run(rc.set_control(world.db, "u1", field=field, value=True, reason="gap risk", actor="u1"))
    d = judge(world, struct(spread()))
    assert d.outcome == "block" and codes(d) == [code] and "gap risk" in d.reasons[0].message


def test_unreadable_controls_block(world):
    world.db.fail[(rc.CONTROLS, "find_one")] = RuntimeError("mongo unreachable")
    d = judge(world, struct(spread()))
    assert d.outcome == "block" and codes(d) == ["controls_unreadable"]
    assert world.db[rc.DECISIONS].docs[0]["outcome"] == "blocked"


# ── RG-4: modes ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode, code", [("shadow", "mode_not_allowed"), ("live", "live_execution_unavailable"),
                                        ("nonsense", "mode_unknown")])
def test_shadow_live_and_unknown_modes_are_blocked(world, mode, code):
    d = judge(world, struct(spread(), mode=mode))
    assert d.outcome == "block" and codes(d) == [code]


def test_assisted_is_allowed(world):
    assert judge(world, struct(spread(), mode="assisted")).outcome == "allow"


def test_live_needs_the_build_and_a_grant_and_the_policy_still_refuses_it(world, monkeypatch):
    from services import execution_modes as modes
    monkeypatch.setattr(modes, "LIVE_EXECUTION_AVAILABLE", True)
    assert codes(judge(world, struct(spread(), mode="live"))) == ["live_not_authorized"]
    run(modes.set_live_authorization(world.db, "u1", True, "pilot", "admin1"))
    assert codes(judge(world, struct(spread(), mode="live"))) == ["mode_not_allowed"]


# ── RG-5: structure ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("req, code", [
    (struct([]), "no_legs"),
    (struct([dict(opt("buy", "call", 100, 6), kind="swap")]), "leg_kind_invalid"),
    (struct([dict(opt("buy", "call", 100, 6), lots=1.5)]), "leg_lots_invalid"),
    (struct([dict(opt("buy", "call", 100, 6), strike=None)]), "leg_strike_invalid"),
    (struct([dict(opt("buy", "call", 100, 6), expiry="27-10-2026")]), "leg_expiry_invalid"),
    (struct([dict(opt("buy", "call", 100, 6), entry_price=0)]), "leg_price_invalid"),
    (struct([{"kind": "cash", "side": "buy", "lots": 10, "lot_size": 1, "entry_price": 100}]), "no_derivative_leg"),
    (struct(spread(), path="somewhere"), "path_unknown"),
    (struct(spread(), action="close"), "action_unknown"),
    (struct(spread(), instrument="crypto"), "instrument_unknown"),
    (struct(spread(), symbol=" "), "symbol_missing"),
    (cash(quantity=2.5), "quantity_invalid"),
    (cash(legs=[fut("buy", 100)]), "cash_with_legs"),
])
def test_a_malformed_request_is_blocked_with_a_specific_code(world, req, code):
    d = judge(world, req)
    assert d.outcome == "block" and code in codes(d)
    by = {c.check: c.status for c in d.checks}
    assert by["structure"] == "fail"
    assert by["defined_risk"] == by["lot_size"] == by["expiry"] == by["caps"] == "skipped"
    assert world.lookups == []                                   # nothing is looked up for an unusable request


# ── RG-6, RG-7: defined risk ─────────────────────────────────────────────────
@pytest.mark.parametrize("legs, code", [
    ([opt("sell", "call", 110, 2)], "naked_short_call"),
    ([opt("buy", "call", 110, 2), opt("sell", "call", 105, 4, lots=2)], "naked_short_call"),
    ([opt("sell", "put", 95, 3)], "naked_short_put"),
    ([fut("buy", 100)], "futures_only"),
    ([fut("sell", 100)], "futures_only"),
    ([fut("buy", 100), opt("sell", "call", 110, 2)], "unhedged_future"),
    ([fut("sell", 100), opt("buy", "put", 95, 2)], "unhedged_future"),
    ([opt("buy", "call", 100, 6), opt("sell", "call", 110, 2, expiry="2026-11-24")], "mixed_expiries"),
])
def test_undefined_risk_is_blocked(world, legs, code):
    world.refs["2026-11-24"] = listed()
    d = judge(world, struct(legs))
    assert d.outcome == "block" and code in codes(d)
    assert {c.check: c.status for c in d.checks}["defined_risk"] == "fail"


def test_a_future_hedged_with_a_put_of_the_same_size_is_defined_risk(world):
    d = judge(world, struct([fut("buy", 100), opt("buy", "put", 95, 2)]))
    assert d.outcome == "allow", codes(d)
    assert world.db[rc.DECISIONS].docs[0]["detail"]["capital_at_risk_rs"] == 350.0      # (100 - 95 + 2) x 50


# ── RG-8, RG-9: the exchange lot and the listed expiry ───────────────────────
def test_an_unverifiable_lot_size_blocks(world):
    world.refs[EXP] = listed(lot=None)
    d = judge(world, struct(spread()))
    assert d.outcome == "block" and set(codes(d)) == {"lot_size_unverified"}
    assert "no single lot size" in d.reasons[0].message


def test_a_lot_size_that_is_not_the_exchange_lot_blocks(world):
    d = judge(world, struct(spread(lot_size=75)))
    assert codes(d) == ["lot_size_mismatch", "lot_size_mismatch"]


def test_an_unverifiable_expiry_blocks(world):
    world.refs[EXP] = {"listed": None, "lot_size": None, "source": None, "as_of": None,
                       "error": "the data platform could not be read"}
    d = judge(world, struct(spread()))
    assert {"lot_size_unverified", "expiry_unverified"} == set(codes(d))
    assert all("could not be read" in r.message for r in d.reasons)


def test_an_expiry_not_listed_blocks(world):
    world.refs.pop(EXP)
    assert "expiry_not_listed" in codes(judge(world, struct(spread())))


def test_a_past_expiry_blocks(world):
    world.refs["2026-10-20"] = listed()
    assert codes(judge(world, struct(spread(expiry="2026-10-20")))) == ["expiry_past"]


def test_a_failing_reference_lookup_blocks_as_unverified(world, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("bug")
    monkeypatch.setattr(reference, "lookup", boom)
    d = judge(world, struct(spread()))
    assert {"lot_size_unverified", "expiry_unverified"} == set(codes(d))


# ── RG-10, RG-11: caps and the open book ─────────────────────────────────────
def test_more_legs_than_the_policy_allows_blocks(world):
    legs = [opt("buy", "put", 90, 1), opt("sell", "put", 95, 3), opt("sell", "call", 105, 3),
            opt("buy", "call", 110, 1), opt("buy", "call", 120, 0.5)]
    assert "too_many_legs" in codes(judge(world, struct(legs)))


def test_more_lots_per_leg_than_the_policy_allows_blocks(world):
    assert codes(judge(world, struct(spread(lots=11)))) == ["lots_per_leg_exceeded", "lots_per_leg_exceeded"]


def test_capital_at_risk_above_the_cap_blocks(world):
    # A long call: 10 lots x 50 x Rs 500 premium = Rs 2,50,000 at risk, above the Rs 2,00,000 cap.
    d = judge(world, struct([opt("buy", "call", 100, 500, lots=10)]))
    assert codes(d) == ["capital_at_risk_exceeded"] and "250,000.00" in d.reasons[0].message
    assert codes(judge(world, cash(capital_at_risk_rs=200_000.01))) == ["capital_at_risk_exceeded"]
    assert judge(world, cash(capital_at_risk_rs=200_000)).outcome == "allow"


def test_a_cash_request_without_a_capital_figure_blocks(world):
    assert codes(judge(world, cash(capital_at_risk_rs=None))) == ["capital_at_risk_unknown"]


def test_a_caller_figure_above_the_computed_one_is_the_one_capped(world):
    assert codes(judge(world, struct(spread(), capital_at_risk_rs=300_000))) == ["capital_at_risk_exceeded"]


def test_the_open_structure_cap_blocks_a_new_structure(world):
    world.db["desk_paper_trades"].docs = [{"_id": f"t{i}", "user_id": "u1", "kind": "strategy", "status": "open"}
                                          for i in range(policy.LIMITS.max_open_structures)]
    world.db["desk_paper_trades"].docs.append({"_id": "other", "user_id": "u2", "kind": "strategy", "status": "open"})
    assert codes(judge(world, struct(spread()))) == ["open_structures_exceeded"]
    world.db["desk_paper_trades"].docs.pop(0)
    assert judge(world, struct(spread())).outcome == "allow"


def test_an_unreadable_open_book_blocks(world):
    world.db.fail[("desk_paper_trades", "count_documents")] = RuntimeError("timeout")
    assert codes(judge(world, struct(spread()))) == ["open_structures_unverified"]


# ── RG-12: the decision must be recorded ─────────────────────────────────────
def test_a_decision_that_cannot_be_recorded_raises_and_is_never_returned(world):
    world.db.fail[(rc.DECISIONS, "insert_one")] = RuntimeError("write concern")
    with pytest.raises(gate.DecisionUnrecorded):
        judge(world, struct(spread()))


def test_failing_indexes_do_not_block_a_decision(world):
    world.db.fail[(rc.CONTROLS, "create_index")] = RuntimeError("no privilege")
    assert judge(world, struct(spread())).outcome == "allow"
    assert rc._indexes_ready is False


# ── RG-14: capital at risk, worked by hand ───────────────────────────────────
@pytest.mark.parametrize("legs, expected", [
    (spread(), 200.0),
    ([opt("buy", "call", 100, 5), opt("buy", "put", 100, 4)], 450.0),
    ([opt("buy", "put", 90, 1), opt("sell", "put", 95, 3), opt("sell", "call", 105, 3), opt("buy", "call", 110, 1)],
     50.0),
    ([fut("buy", 100), opt("buy", "put", 95, 2)], 350.0),
    ([{"kind": "cash", "side": "buy", "lots": 50, "lot_size": 1, "entry_price": 100}, opt("sell", "call", 110, 2)],
     4900.0),
])
def test_capital_at_risk_is_the_maximum_loss_at_expiry(legs, expected):
    clean, failures = gate.clean_legs(legs)
    assert failures == [] and gate.structure_capital_at_risk(clean) == expected


def test_capital_at_risk_is_unknown_when_unbounded_or_across_expiries():
    naked, _ = gate.clean_legs([opt("sell", "call", 110, 2)])
    mixed, _ = gate.clean_legs([opt("buy", "call", 100, 6), opt("sell", "call", 110, 2, expiry="2026-11-24")])
    assert gate.structure_capital_at_risk(naked) is None and gate.structure_capital_at_risk(mixed) is None


# ── RG-15: inputs hash ───────────────────────────────────────────────────────
def test_the_inputs_hash_ignores_the_correlation_id_and_follows_every_input():
    a, b = struct(spread()), struct(spread(), correlation_id="another")
    assert inputs_hash(a) == inputs_hash(b)
    assert inputs_hash(a) != inputs_hash(struct(spread(lots=2)))
    assert inputs_hash(a) != inputs_hash(struct(spread(), mode="assisted"))


# ── RG-16: the exchange reference ────────────────────────────────────────────
KITE_ROWS = [  # MOCK — not real data: the shape of kiteconnect instruments("NFO") rows
    {"name": "MOCKU", "expiry": date(2026, 10, 27), "lot_size": 50, "instrument_type": "CE", "strike": 100.0},
    {"name": "MOCKU", "expiry": date(2026, 10, 27), "lot_size": 50, "instrument_type": "FUT", "strike": 0.0},
    {"name": "OTHER", "expiry": date(2026, 10, 27), "lot_size": 75, "instrument_type": "CE", "strike": 100.0},
]


def test_the_in_process_instrument_list_is_used_without_any_network_call(monkeypatch):
    monkeypatch.setattr(fno_margin, "cached_instruments", lambda today=None: KITE_ROWS)

    async def no_network(*a, **kw):
        raise AssertionError("the data platform must not be read when the instrument list is loaded")
    monkeypatch.setattr(daas_client, "get_raw", no_network)
    out = run(reference.lookup("MOCKU", {EXP, "2026-11-24"}, TODAY))
    assert out[EXP] == {"listed": True, "lot_size": 50, "source": reference.KITE_SOURCE, "as_of": "2026-10-21",
                        "error": None}
    assert out["2026-11-24"]["listed"] is False and out["2026-11-24"]["lot_size"] is None


def test_the_instrument_cache_is_read_only_for_today():
    fno_margin._INSTRUMENTS.update(day="2026-10-20", rows=KITE_ROWS)
    try:
        assert fno_margin.cached_instruments(date(2026, 10, 21)) is None
        assert fno_margin.cached_instruments(date(2026, 10, 20)) is KITE_ROWS
    finally:
        fno_margin._INSTRUMENTS.update(day=None, rows=None)


@pytest.fixture
def bhav(monkeypatch):
    state = SimpleNamespace(answer=None, calls=[], configured=True)
    monkeypatch.setattr(fno_margin, "cached_instruments", lambda today=None: None)
    monkeypatch.setattr(daas_client, "is_configured", lambda: state.configured)

    async def get_raw(path, params=None, timeout=10.0):
        state.calls.append((path, dict(params or {})))
        if isinstance(state.answer, Exception):
            raise state.answer
        return state.answer
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    return state


def _bhav_row(lot):
    return {"as_of_date": "2026-10-20", "ticker_symbol": "MOCKU", "expiry_date": EXP, "new_board_lot_qty": lot}


def test_the_bhavcopy_gives_the_lot_and_the_listing(bhav):
    bhav.answer = (200, {"data": [_bhav_row(50), _bhav_row(50)], "as_of": "2026-10-20", "symbol": "MOCKU"})
    out = run(reference.lookup("MOCKU", [EXP], TODAY))[EXP]
    assert out == {"listed": True, "lot_size": 50, "source": reference.BHAVCOPY_SOURCE, "as_of": "2026-10-20",
                   "error": None}
    assert bhav.calls == [("/fno/MOCKU", {"expiry": EXP, "limit": 20})]


@pytest.mark.parametrize("answer, listed_, error_part", [
    ((200, {"data": [], "as_of": "2026-10-20"}), False, "no contract with that expiry"),
    ((200, {"data": [_bhav_row(None)], "as_of": "2026-10-20"}), True, "no single lot size"),
    ((200, {"data": [_bhav_row(50), _bhav_row(25)], "as_of": "2026-10-20"}), True, "no single lot size"),
    ((200, {"data": [_bhav_row(50)], "as_of": "2026-10-10"}), None, "older than 7 days"),
    ((200, {"data": [], "as_of": None}), None, "no F&O rows"),
    ((502, None), None, "HTTP 502"),
    (daas_client.DaasError("timed out"), None, "could not be read"),
])
def test_an_unusable_bhavcopy_answer_is_never_a_lot_size(bhav, answer, listed_, error_part):
    bhav.answer = answer
    out = run(reference.lookup("MOCKU", [EXP], TODAY))[EXP]
    assert out["lot_size"] is None and out["listed"] is listed_ and error_part in out["error"]


def test_an_unconfigured_data_platform_is_unverifiable(bhav):
    bhav.configured = False
    out = run(reference.lookup("MOCKU", [EXP], TODAY))[EXP]
    assert out["listed"] is None and bhav.calls == []


# ── RG-18: the legacy decision log is unchanged ──────────────────────────────
def test_record_decision_keeps_its_signature_and_still_fails_open():
    params = list(inspect.signature(rc.record_decision).parameters)
    # `path` (keyword, optional) was added so desk and journal refusals carry the gate's path names; every older
    # caller is unchanged.
    assert params == ["db", "user_id", "action", "outcome", "symbol", "requested_qty", "approved_qty", "reasons",
                      "limits_version", "correlation_id", "detail", "path", "now"]
    db = FakeDB()
    db.fail[(rc.DECISIONS, "insert_one")] = RuntimeError("down")
    assert run(rc.record_decision(db, "u1", action="x", outcome="allowed")) is None


# ── usage, for GET /api/risk/policy ──────────────────────────────────────────
def test_usage_counts_open_structures_and_never_counts_an_unknown_as_zero():
    db = FakeDB()
    trades = db["desk_paper_trades"]
    trades.docs = [{"_id": "a", "user_id": "u1", "kind": "strategy", "status": "open", "legs": spread()},
                   {"_id": "b", "user_id": "u1", "kind": "strategy", "status": "closed", "legs": spread()},
                   {"_id": "c", "user_id": "u1", "status": "open", "symbol": "MOCKA"}]
    assert run(gate.usage(db, "u1")) == {"open_structures": 1, "capital_at_risk_rs": 200.0,
                                         "capital_at_risk_unknown": 0}
    trades.docs.append({"_id": "d", "user_id": "u1", "kind": "strategy", "status": "open",
                        "legs": [opt("sell", "call", 110, 2)]})
    assert run(gate.usage(db, "u1")) == {"open_structures": 2, "capital_at_risk_rs": None,
                                         "capital_at_risk_unknown": 1}


# ── W-11, W-12, W-13: the flag and the correlation id ────────────────────────
def test_the_flag_is_known_off_by_default_with_three_modes():
    meta = ff.KNOWN_FEATURES[risk_gate.FLAG]
    assert risk_gate.FLAG == "fno_risk_gate" and meta["default_mode"] == "off"
    assert meta["allowed_modes"] == ["off", "allowlist", "everyone"]


@pytest.fixture
def flags(monkeypatch):
    monkeypatch.setattr(ff, "_flags", {})
    monkeypatch.setitem(feature_gate._state, "at", float("-inf"))
    db = FakeDB()
    db["system_config"].docs.append({"key": "feature_flags", "flags": {
        "fno_risk_gate": {"mode": "allowlist", "allowlist": ["adv@example.com"]}}})
    db["users"].docs.append({"user_id": "adv", "email": "adv@example.com"})
    return db


def test_the_gate_is_on_per_user_from_the_persisted_allowlist(flags):
    assert run(risk_gate.enabled_for(flags, {"user_id": "adv", "email": "adv@example.com"})) is True
    assert run(risk_gate.enabled_for(flags, {"user_id": "u2", "email": "two@example.com"})) is False


def test_under_impersonation_the_signed_in_person_decides(flags):
    acting = {"user_id": "client", "email": "client@example.com", "_session_user_id": "adv"}
    assert run(risk_gate.enabled_for(flags, acting)) is True
    other = {"user_id": "adv", "email": "adv@example.com", "_session_user_id": "someone"}
    assert run(risk_gate.enabled_for(flags, other)) is False


def test_a_failed_flag_refresh_keeps_this_workers_copy(monkeypatch):
    async def unreadable(db, now=None):
        raise RuntimeError("mongo unavailable")
    monkeypatch.setattr(feature_gate, "refresh_if_stale", unreadable)
    ff._ensure_defaults()
    monkeypatch.setitem(ff._flags, "fno_risk_gate", {"mode": "everyone", "allowlist": []})
    assert run(risk_gate.enabled_for(FakeDB(), {"user_id": "u1"})) is True
    monkeypatch.setitem(ff._flags, "fno_risk_gate", {"mode": "off", "allowlist": []})
    assert run(risk_gate.enabled_for(FakeDB(), {"user_id": "u1"})) is False


def test_the_correlation_id_is_the_requests_or_a_fresh_one():
    def req(cid=None):
        state = SimpleNamespace() if cid is None else SimpleNamespace(correlation_id=cid)
        return SimpleNamespace(state=state)
    fresh = risk_gate.correlation_id(req())
    assert len(fresh) == 32 and int(fresh, 16) >= 0
    assert risk_gate.correlation_id(req("abc-123.x")) == "abc-123.x"
    junk = risk_gate.correlation_id(req("x" * 200))
    assert junk != "x" * 200 and len(junk) == 32
