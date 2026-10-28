"""The v2 strategy document (Strategy Copilot Phase 1.1, the shared strategy store): validation, the derived checks, the
derived asset class and the version diff. Pure: no database, no network.

Covers TC-1 … TC-12 of test_reports/strategy_store_v2_20261028.md. The wizard's bodies come from the shared contract
fixture frontend-v5/e2e/fixtures/contract-strategy-store-v2.json (MOCK — not real data: invented prices and dates; the
shapes are the contract), so the browser and the validator are pinned to the same document.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from services import strategy_store as store
from services.strategy_limits import MAX_STRATEGY_LEGS

FIXTURE = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures" / "contract-strategy-store-v2.json"
assert FIXTURE.exists(), f"{FIXTURE} is the shared browser/route contract fixture and must be present"
CONTRACT = json.loads(FIXTURE.read_text(encoding="utf-8"))
BULL = CONTRACT["create_bull_call_spread"]["definition"]
COVERED = CONTRACT["create_covered_call_stock"]["definition"]
FUTURE = CONTRACT["create_long_future"]["definition"]


def d(base=BULL):
    return copy.deepcopy(base)


def problems(defn):
    return [(p["field"], p["code"]) for p in store.validate_definition(defn)]


def leg(leg_id, instrument, side, *, lots=1, lot_size=65, expiry="2026-11-25", strike=None, price=10.0):
    out = {"leg_id": leg_id, "instrument": instrument, "side": side, "lot_size_at_save": lot_size,
           "expiry": {"rule": "specific", "date": expiry} if expiry else None,
           "strike": {"rule": "fixed", "value": strike} if strike is not None else None,
           "entry_price_at_save": {"value": price, "source": "test"} if price is not None else None, "relationship": None}
    if instrument == "STOCK":
        out["shares"] = lots
    else:
        out["lots"] = lots
    return out


def with_legs(*legs, base=BULL):
    out = d(base)
    out["legs"] = list(legs)
    return out


# ── TC-1, TC-2: what the wizard sends validates and is kept as sent ──────────
@pytest.mark.parametrize("name", ["create_bull_call_spread", "create_covered_call_stock", "create_long_future"])
def test_tc1_tc2_the_wizard_bodies_validate(name):
    defn = CONTRACT[name]["definition"]
    assert store.is_v2(defn)
    assert store.validate_definition(defn) == []
    assert store.clean_definition(defn) == defn          # stored exactly as sent, nothing added or dropped


def test_v1_documents_are_not_v2():
    assert not store.is_v2({"version": "1", "asset_class": "STOCK"})
    assert not store.is_v2({"schema_version": 2})          # the number is not the string
    assert not store.is_v2(None) and not store.is_v2([])


# ── TC-3: the one leg limit ──────────────────────────────────────────────────
def test_tc3_more_legs_than_the_limit_is_refused():
    legs = [leg(f"L{i + 1}", "CALL", "BUY", strike=25000 + 100 * i) for i in range(MAX_STRATEGY_LEGS + 1)]
    assert ("legs", "too_many_legs") in problems(with_legs(*legs))
    assert problems(with_legs(*legs[:MAX_STRATEGY_LEGS])) == []
    assert ("legs", "no_legs") in problems(with_legs())


# ── TC-4: unknown fields are refused with their path, never dropped ──────────
def test_tc4_unknown_fields_are_refused_where_they_are():
    top = d(); top["notes"] = "x"
    in_leg = d(); in_leg["legs"][0]["delta"] = 0.5
    in_bc = d(); in_bc["build_constraints"]["margin_rs"] = 1
    in_rule = d(); in_rule["build_constraints"]["strike_rule"]["skew"] = 1
    assert ("notes", "unknown_field") in problems(top)
    assert ("legs[0].delta", "unknown_field") in problems(in_leg)
    assert ("build_constraints.margin_rs", "unknown_field") in problems(in_bc)
    assert ("build_constraints.strike_rule.skew", "unknown_field") in problems(in_rule)
    with pytest.raises(store.StoreInputError) as exc:
        store.clean_definition(top)
    assert exc.value.code == "invalid_definition" and exc.value.problems[0]["field"] == "notes"


# ── TC-5: build_constraints size cap ─────────────────────────────────────────
def test_tc5_build_constraints_over_4_kb_is_refused():
    big = d()
    big["build_constraints"]["chain_as_of"] = None
    big["build_constraints"]["strike_rule"]["rule"] = "manual"
    # Every field is typed, so the only way past 4 KB is a field that is not allowed; the cap is checked first and
    # reported on its own, so a client sees why.
    big["build_constraints"]["padding"] = "x" * store.BUILD_CONSTRAINTS_MAX_BYTES
    assert ("build_constraints", "build_constraints_too_large") in problems(big)


# ── TC-6: leg rules ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("mutate, expected", [
    (lambda x: x["legs"][0].pop("lots"), ("legs[0].lots", "lots_required")),
    (lambda x: x["legs"][0].update(lots=0), ("legs[0].lots", "invalid_lots")),
    (lambda x: x["legs"][0].update(lots=1.5), ("legs[0].lots", "invalid_lots")),
    (lambda x: x["legs"][0].update(lots=True), ("legs[0].lots", "invalid_lots")),
    (lambda x: x["legs"][0].update(lots="1"), ("legs[0].lots", "invalid_lots")),
    (lambda x: x["legs"][0].update(shares=10), ("legs[0].shares", "shares_only_for_stock")),
    (lambda x: x["legs"][0].update(expiry=None), ("legs[0].expiry", "expiry_required")),
    (lambda x: x["legs"][0].update(expiry={"rule": "specific", "date": "2026-02-30"}), ("legs[0].expiry.date", "invalid_date")),
    (lambda x: x["legs"][0].update(expiry={"rule": "same_as", "leg_id": "L9"}), ("legs[0].expiry.leg_id", "unknown_leg")),
    (lambda x: x["legs"][0].update(expiry={"rule": "same_as", "leg_id": "L1"}), ("legs[0].expiry.leg_id", "unknown_leg")),
    (lambda x: x["legs"][0].update(expiry={"rule": "fortnightly"}), ("legs[0].expiry.rule", "invalid_expiry_rule")),
    (lambda x: x["legs"][0].update(strike=None), ("legs[0].strike", "strike_required")),
    (lambda x: x["legs"][0].update(strike={"rule": "fixed", "value": -1}), ("legs[0].strike.value", "invalid_strike")),
    (lambda x: x["legs"][0].update(strike={"rule": "atm_offset_strikes", "value": 2.5}), ("legs[0].strike.value", "invalid_strike")),
    (lambda x: x["legs"][0].update(entry_price_at_save={"value": 0, "source": "x"}), ("legs[0].entry_price_at_save.value", "invalid_price")),
    (lambda x: x["legs"][0].update(entry_price_at_save={"value": 1, "source": "x" * 121}), ("legs[0].entry_price_at_save.source", "invalid_text")),
    (lambda x: x["legs"][0].update(lot_size_at_save=0), ("legs[0].lot_size_at_save", "invalid_lot_size")),
    (lambda x: x["legs"][0].update(side="buy"), ("legs[0].side", "invalid_side")),
    (lambda x: x["legs"][0].update(instrument="OPTION"), ("legs[0].instrument", "invalid_instrument")),
    (lambda x: x["legs"][1].update(leg_id="L1"), ("legs[1].leg_id", "duplicate_leg_id")),
    (lambda x: x["legs"][0].update(relationship={"covers": "L7"}), ("legs[0].relationship.covers", "unknown_leg")),
])
def test_tc6_leg_rules(mutate, expected):
    defn = d()
    mutate(defn)
    assert expected in problems(defn)


def test_tc6_stock_leg_rules():
    defn = d(COVERED)
    stock = defn["legs"][0]
    for change, expected in (
        ({"expiry": {"rule": "specific", "date": "2026-11-25"}}, ("legs[0].expiry", "expiry_not_allowed")),
        ({"strike": {"rule": "fixed", "value": 1}}, ("legs[0].strike", "strike_not_allowed")),
        ({"lots": 1}, ("legs[0].lots", "lots_not_allowed_for_stock")),
        ({"lot_size_at_save": 50}, ("legs[0].lot_size_at_save", "invalid_lot_size")),
    ):
        bad = d(COVERED)
        bad["legs"][0].update(change)
        assert expected in problems(bad), change
    no_shares = d(COVERED); no_shares["legs"][0].pop("shares")
    assert ("legs[0].shares", "shares_required") in problems(no_shares)
    on_index = d(COVERED); on_index["underlying"] = {"symbol": "NIFTY", "kind": "index"}
    assert ("legs[0].instrument", "stock_leg_on_index") in problems(on_index)
    assert stock["shares"] == 500                         # the fixture itself is untouched


def test_tc6_a_future_has_no_strike():
    bad = d(FUTURE)
    bad["legs"][0]["strike"] = {"rule": "fixed", "value": 54000}
    assert ("legs[0].strike", "strike_not_allowed") in problems(bad)


def test_top_level_rules():
    for change, expected in (
        ({"schema_version": "3"}, ("schema_version", "invalid_schema_version")),
        ({"market": "BSE"}, ("market", "invalid_market")),
        ({"timeframe": "15m"}, ("timeframe", "timeframe_not_supported")),
        ({"name": ""}, ("name", "invalid_text")),
        ({"name": "x" * 81}, ("name", "invalid_text")),
        ({"entry": {"type": "rule", "tree": {}}}, ("entry.type", "entry_type_not_supported")),
        ({"exit": {"profit_target_pct_of_net_debit": -5, "stop_loss_pct_of_net_debit": None,
                   "time_exit_sessions": None, "close_before_expiry_sessions": None}},
         ("exit.profit_target_pct_of_net_debit", "invalid_number")),
        ({"sizing": {"lots": 0}}, ("sizing.lots", "invalid_lots")),
    ):
        bad = d()
        bad.update(change)
        assert expected in problems(bad), change
    missing = d(); missing.pop("legs")
    assert ("legs", "required") in problems(missing)
    assert [p["code"] for p in store.validate_definition("not an object")] == ["invalid_definition"]


def test_a_cash_templates_sizing_is_shares():
    """The wizard's lots setting is shares for a cash template (Wizard.tsx stepper: max 100,000), sent as sizing.lots."""
    cash = with_legs(leg("L1", "STOCK", "BUY", lots=5000, lot_size=1, expiry=None), base=COVERED)
    cash["template_id"] = "cash_long"
    cash["sizing"] = {"lots": 5000}
    assert problems(cash) == []
    cash["sizing"] = {"lots": store.MAX_SHARES + 1}
    assert ("sizing.lots", "invalid_lots") in problems(cash)


def test_every_problem_is_reported_not_just_the_first():
    bad = d()
    bad["legs"][0]["lots"] = 0
    bad["legs"][1]["side"] = "short"
    bad["timeframe"] = "1h"
    assert {p[0] for p in problems(bad)} >= {"legs[0].lots", "legs[1].side", "timeframe"}


# ── TC-7: the rule forms the Copilot will write ──────────────────────────────
def test_tc7_rule_based_legs_validate():
    defn = d()
    defn["template_id"] = None
    defn["legs"][0]["expiry"] = {"rule": "nearest_monthly"}
    defn["legs"][0]["strike"] = {"rule": "atm"}
    defn["legs"][0]["entry_price_at_save"] = None
    defn["legs"][1]["expiry"] = {"rule": "same_as", "leg_id": "L1"}
    defn["legs"][1]["strike"] = {"rule": "atm_offset_points", "value": 200}
    assert problems(defn) == []
    defn["legs"][1]["strike"] = {"rule": "atm_offset_strikes", "value": 2}
    assert problems(defn) == []


# ── TC-8: template and underlying ───────────────────────────────────────────
def test_tc8_template_and_underlying():
    bad_tpl = d(); bad_tpl["template_id"] = "jade_lizard"
    assert ("template_id", "invalid_template") in problems(bad_tpl)
    bad_sym = d(); bad_sym["underlying"]["symbol"] = "nifty 50!"
    assert ("underlying.symbol", "invalid_underlying") in problems(bad_sym)
    bad_kind = d(); bad_kind["underlying"]["kind"] = "etf"
    assert ("underlying.kind", "invalid_underlying_kind") in problems(bad_kind)


# ── TC-9, TC-10: the derived checks (owner decision D2) ──────────────────────
def codes(defn):
    return {c["code"]: c for c in store.checks(defn)}


@pytest.mark.parametrize("legs, code", [
    ([leg("L1", "CALL", "SELL", strike=25500)], "unbounded_loss"),
    ([leg("L1", "CALL", "SELL", strike=25500), leg("L2", "PUT", "SELL", strike=25500)], "unbounded_loss"),
    ([leg("L1", "PUT", "SELL", strike=25000)], "naked_short_put"),
    ([leg("L1", "FUTURE", "SELL", lot_size=65)], "short_futures_not_supported"),
    ([leg("L1", "CALL", "BUY", strike=25500), leg("L2", "CALL", "SELL", strike=25700, expiry="2026-12-30")],
     "mixed_option_expiries"),
])
def test_tc9_not_defined_risk_is_saved_but_blocked_for_backtest_and_paper(legs, code):
    defn = with_legs(*legs)
    defn["template_id"] = None
    assert problems(defn) == []                            # a draft can be stored …
    c = codes(defn)[code]                                  # … and says what it cannot do
    assert c["severity"] == "blocking" and c["blocking_for"] == ["backtest", "paper"] and c["message"]


def test_tc9_mixed_expiry_rules_are_a_calendar_too():
    defn = d()
    defn["legs"][0]["expiry"] = {"rule": "nearest_weekly"}
    defn["legs"][1]["expiry"] = {"rule": "nearest_monthly"}
    assert codes(defn)["mixed_option_expiries"]["severity"] == "blocking"
    same = d()
    same["legs"][0]["expiry"] = {"rule": "nearest_monthly"}
    same["legs"][1]["expiry"] = {"rule": "same_as", "leg_id": "L1"}
    assert "mixed_option_expiries" not in codes(same)


def test_tc10_defined_risk_futures_and_cash_only():
    assert [c for c in store.checks(BULL) if c["severity"] == "blocking"] == []
    fut = codes(FUTURE)["futures_exposure"]
    assert fut["severity"] == "warning" and fut["blocking_for"] == []
    cash = with_legs(leg("L1", "STOCK", "BUY", lots=100, lot_size=1, expiry=None), base=COVERED)
    cash["template_id"] = None
    info = codes(cash)["cash_only"]
    assert info["severity"] == "info" and info["blocking_for"] == []
    assert [c for c in store.checks(COVERED) if c["severity"] == "blocking"] == []   # covered call is covered


# ── TC-11: asset class from the legs ─────────────────────────────────────────
def test_tc11_asset_class_is_derived_from_the_legs():
    assert store.asset_class_of(BULL) == "FNO"
    assert store.asset_class_of(FUTURE) == "FNO"
    assert store.asset_class_of(COVERED) == "MIXED"
    cash = with_legs(leg("L1", "STOCK", "BUY", lots=100, lot_size=1, expiry=None), base=COVERED)
    assert store.asset_class_of(cash) == "STOCK"


# ── TC-12: the diff a new version answers with ───────────────────────────────
def test_tc12_diff_paths_are_stable_and_keyed_by_leg_id():
    after = d()
    after["name"] = "NIFTY bull call spread, wider"
    after["legs"][1]["strike"]["value"] = 25800
    after["legs"].append(leg("L3", "PUT", "BUY", strike=25000))
    diff = store.diff(BULL, after)
    assert diff == [
        {"path": "legs[L2].strike.value", "before": 25700, "after": 25800},
        {"path": "legs[L3]", "before": None, "after": after["legs"][2]},
        {"path": "name", "before": "NIFTY bull call spread", "after": "NIFTY bull call spread, wider"},
    ]
    removed = d(); removed["legs"] = removed["legs"][:1]
    assert store.diff(BULL, removed) == [{"path": "legs[L2]", "before": BULL["legs"][1], "after": None}]
    assert store.diff(BULL, d()) == []
    assert store.diff(BULL, after) == store.diff(BULL, copy.deepcopy(after))   # deterministic


def test_fingerprint_ignores_key_order_only():
    a = {"definition": d(), "name": "x"}
    b = {"name": "x", "definition": d()}
    assert store.fingerprint(a) == store.fingerprint(b)
    b["name"] = "y"
    assert store.fingerprint(a) != store.fingerprint(b)
