"""AI Trader Phases 2-5 — `NiveshConfig` (PRD F2.1, spec §4.1/§6/§7) and the Risk Governor (PRD F3.1-F3.4).

No network, no database, no clock. Both modules under test are pure Python and run here exactly as they run in
production: **nothing is replaced, stubbed, patched or monkeypatched**. There is no fixture in this file that could
soften a verdict — every number below comes out of the real `evaluate()` / `validate()`.

MOCK - not real data: every symbol, price, capital figure, VIX level, sector and average-traded-value here is
invented. "MOCKCO", "OTHERCO", "ITCO" and the "P0..P9" fillers are not NSE symbols and no figure was read from a feed.

Worked examples (every expected number in this file can be checked by hand)
  size       capital ₹1,000,000 · risk limit 1 % → ₹10,000 of risk; entry 100, stop 90 → ₹10 of risk a share
             → 10,000 / 10 = 1,000 shares. Position limit 10 % → 100,000 / 100 = 1,000 shares. Both bind at exactly
             1,000, so 1,000 shares are approved whole and 1,001 are reduced to 1,000.
  risk cap   entry 100, stop 88 → ₹12 of risk a share → 10,000 / 12 = 833.33 → 833 shares (floored, never rounded up).
  sector cap ₹250,000 already held in IT · sector limit 30 % of 1,000,000 = ₹300,000 → ₹50,000 left → 500 shares at 100.
             ₹250,000 held with *no* sector gives the same 500: an unclassified holding could be in this sector, so
             it is counted against the allowance and an `info` reason reports how much was counted that way.
  net cap    ₹750,000 already held · net limit 80 % = ₹800,000 → ₹50,000 left → 500 shares at 100.
  liquidity  average traded value ₹600,000 · 5 % = ₹30,000 → at ₹97 a share, 30,000 / 97 = 309.27 → 309 shares;
             310 shares would cost ₹30,070, over the ₹30,000 allowance. A traded value of ₹0 leaves no 5 % to take,
             so the cap is 0 shares and the order is rejected; only `None` is unknown.
  below one  capital ₹10,000 · 1 % = ₹100 of risk; entry 5,000, stop 4,500 → ₹500 of risk a share → 0.2 shares → the
             action is **reject** (SIZE_BELOW_ONE_SHARE), never "approve 0". At capital ₹50,000 exactly one share
             fits (500 / 500 = 1.0 and 5,000 / 5,000 = 1.0) and is approved; at ₹49,999 it is rejected again.
  daily loss realised −₹30,000 on ₹1,000,000 = 3.00 % → the 3 % halt fires at the boundary.
  vix        25.0 halves size (1,000 → 500); 35.0 defers; BEAR halves again (0.5 × 0.5). A factor applies to the
             quantity the hard caps allow, not to the quantity asked for: a 2,000-share ask against a 1,000-share
             cap in a BEAR market at VIX 26 is 1,000 × 0.25 = 250, not 2,000 × 0.25 = 500.
  hedge      ₹650,000 held + 600 × 100 = ₹710,000 on ₹1,000,000 = 71.0 % ≥ the 70 % hedge line → action "hedge",
             the order still allowed at its full 600 shares.

No test here is skipped or xfailed, and nothing was papered over by weakening an assertion. The six defects this file
found (the `symbols` error wording, `validate()` missing the identifier rule, the identifier check running after a
`.startswith` on the key, a known-zero traded value read as unknown, the size-cap reasons carrying no limit, and
`symbols` entries never being type-checked) were fixed in the modules on 2026-10-21; every one of them is now an
ordinary passing assertion kept as its regression guard. `BEAR_REGIME` carrying no limit is deliberate — a regime is
a category, not a threshold — and is pinned as such in the reduce-reason partition test.

Two further defects, found in review and fixed on 2026-10-21, are covered by the tests named in the sections "a size
factor cuts what the limits allow, not what was asked for" and "a held position with no sector". Two expectations in
this file had encoded the wrong behaviour and were corrected with the fix, not around it: step 4 of the severity
ladder (500 → 250) and the `size_limits` oracle's sector rule.
"""
from __future__ import annotations

import ast
import itertools
import json
import math
import types
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from services.ai_trader import risk_governor as rg
from services.ai_trader.config import (AI_DEFAULTS, BUILTINS, CODE_WRITABLE, SCHEMA_VERSION, ConfigFrozenError,
                                       ConfigValidationError, NiveshConfig, resolve)

# ═════════════════════════════════════════════════════════════════════════════
# NiveshConfig  (spec §2 field reference, §6 edge cases, §7 test checklist; PRD F2.1)
# ═════════════════════════════════════════════════════════════════════════════
CLASS_DEFAULTS = {"initial_capital": 1_000_000.0, "commission_pct": 0.0, "pyramiding": 0, "short_margin_pct": 100.0}


def cfg(**kw) -> NiveshConfig:
    """A config with one field at a time overridden; everything else at the class default."""
    base = dict(symbols=["MOCKCO"], **CLASS_DEFAULTS)                      # MOCK - not real data
    base.update(kw)
    return NiveshConfig(**base)


# ── defaults ────────────────────────────────────────────────────────────────
def test_the_class_defaults_match_the_spec_field_reference():
    """Spec §2: capital 1,000,000, commission 0.0, pyramiding 0, short margin 100.0 when nothing is supplied."""
    c = NiveshConfig(["MOCKCO"])
    assert (c.initial_capital, c.commission_pct, c.pyramiding, c.short_margin_pct) == (1_000_000.0, 0.0, 0, 100.0)
    assert c.symbols == ("MOCKCO",)
    c.validate()                                                            # the bare defaults are a valid config


def test_resolve_applies_the_ai_defaults_when_bot_details_are_blank():
    """Spec §7 checklist 1 + PRD assumption B2: an AI strategy gets commission 0.05 %, pyramiding 0, margin 100 %."""
    assert AI_DEFAULTS == {"initial_capital": 1_000_000.0, "commission_pct": 0.05, "pyramiding": 0,
                           "short_margin_pct": 100.0}
    c = resolve(["MOCKCO"])
    assert {k: getattr(c, k) for k in AI_DEFAULTS} == AI_DEFAULTS
    # and the AI default commission is deliberately NOT the class default of 0.0 (spec §2 "proposed" vs B2)
    assert AI_DEFAULTS["commission_pct"] != CLASS_DEFAULTS["commission_pct"]


def test_ui_values_beat_the_ai_defaults():
    c = resolve(["MOCKCO"], ui={"commission_pct": 0.03, "pyramiding": 2, "short_margin_pct": 20.0,
                                "initial_capital": 250_000.0})
    assert (c.initial_capital, c.commission_pct, c.pyramiding, c.short_margin_pct) == (250_000.0, 0.03, 2, 20.0)
    # a partially filled form keeps the AI default for the rest
    c2 = resolve(["MOCKCO"], ui={"pyramiding": 1})
    assert (c2.pyramiding, c2.commission_pct) == (1, 0.05)


def test_a_missing_strategy_info_runs_with_the_ui_values_only():
    """Spec §6 row 1."""
    c = resolve(["MOCKCO"], ui={"initial_capital": 400_000.0}, strategy_info=None)
    assert c.initial_capital == 400_000.0 and c.to_dict()["custom"] == {}


# ── initial_capital is the one code-writable built-in ───────────────────────
def test_initial_capital_set_in_strategy_info_beats_the_ui_value_for_that_run():
    """Spec §7 checklist 2 + §4.4 help text: code wins over Bot details for that run only."""
    seen = []

    def strategy_info(config):
        seen.append(config.initial_capital)                                 # the UI value is visible first
        config.initial_capital = 100_000                                    # spec §3.1 example
        config.length = 14

    c = resolve(["MOCKCO"], ui={"initial_capital": 500_000.0}, strategy_info=strategy_info)
    assert seen == [500_000.0]                                              # strategy_info ran exactly once
    assert c.initial_capital == 100_000
    assert c.to_dict()["initial_capital"] == 100_000                         # and that is what is persisted with the run
    assert CODE_WRITABLE == {"initial_capital"}


@pytest.mark.parametrize("field, value", [("symbols", ["MOCKTWO"]), ("commission_pct", 0.1), ("pyramiding", 3),
                                          ("short_margin_pct", 50.0)])
def test_every_other_builtin_raises_config_frozen_error_on_a_write(field, value):
    """Spec §7 checklist 3 + §6 row 3 + PRD B2 Q1: only initial_capital is code-writable."""
    c = cfg()
    with pytest.raises(ConfigFrozenError) as e:
        setattr(c, field, value)
    assert field in str(e.value)
    assert getattr(c, field) in (("MOCKCO",), *CLASS_DEFAULTS.values())      # nothing was written
    assert isinstance(e.value, AttributeError)                              # spec §4.1: it is an AttributeError
    assert BUILTINS - CODE_WRITABLE == {"symbols", "commission_pct", "pyramiding", "short_margin_pct"}


def test_setting_symbols_points_the_author_at_the_symbol_picker():
    """Spec §6 row 2: `user sets config.symbols` → ConfigFrozenError *pointing to the symbol picker* (§4.4).
    The other read-only built-ins keep the platform / Bot details wording, which is where they are set."""
    with pytest.raises(ConfigFrozenError) as e:
        cfg().symbols = ["MOCKTWO"]
    assert str(e.value) == "'symbols' comes from the symbol picker, not from code"
    with pytest.raises(ConfigFrozenError) as other:
        cfg().commission_pct = 0.1
    assert str(other.value) == "'commission_pct' is set by the platform or in Bot details, not in code"
    assert "picker" not in str(other.value)


def test_any_write_after_freeze_raises_including_initial_capital_and_custom_keys():
    """Spec §6 row 5 + §7 checklist 4: the config is frozen before bar 1."""
    c = resolve(["MOCKCO"], strategy_info=lambda cf: setattr(cf, "fast", 9))
    for field, value in (("initial_capital", 1.0), ("fast", 5), ("brand_new", 1), ("commission_pct", 1.0)):
        with pytest.raises(ConfigFrozenError) as e:
            setattr(c, field, value)
        assert "read-only after strategy_info" in str(e.value) or field in str(e.value)
    assert (c.initial_capital, c.fast) == (1_000_000.0, 9)                   # spec §3.2: reads still work


# ── reads ───────────────────────────────────────────────────────────────────
def test_reading_a_key_that_was_never_set_raises_attribute_error_naming_the_key():
    """Spec §6 row 4."""
    c = resolve(["MOCKCO"], strategy_info=lambda cf: setattr(cf, "length", 14))
    assert c.length == 14 and c.symbols == ("MOCKCO",)
    with pytest.raises(AttributeError) as e:
        c.quantity                                                          # spec §3.1: the key strategy_info forgot
    assert type(e.value) is AttributeError and not isinstance(e.value, ConfigFrozenError)
    assert "quantity" in str(e.value) and "strategy_info" in str(e.value)


# ── custom keys ─────────────────────────────────────────────────────────────
def test_custom_keys_are_accepted_exposed_flat_and_stored_under_custom():
    """Spec §3.3: custom keys live under `custom` in the stored form, flat on the object."""
    def strategy_info(config):
        config.initial_capital = 100_000
        config.length = 14
        config.quantity = 10
        config.use_shorts = False
        config.weights = {"a": 1, "b": [2, 3]}

    c = resolve(["MOCKCO"], strategy_info=strategy_info)
    assert (c.length, c.quantity, c.use_shorts, c.weights) == (14, 10, False, {"a": 1, "b": [2, 3]})
    d = c.to_dict()
    assert d["custom"] == {"length": 14, "quantity": 10, "use_shorts": False, "weights": {"a": 1, "b": [2, 3]}}
    assert "length" not in d and "quantity" not in d                        # flat on the object, nested when stored


def test_a_custom_key_with_a_leading_underscore_is_rejected():
    """Spec §2: no leading `_`."""
    c = cfg()
    with pytest.raises(ConfigValidationError) as e:
        setattr(c, "_private", 1)
    assert "cannot start with '_'" in str(e.value)
    # and the same key smuggled in through the stored `custom` blob is caught by validate()
    with pytest.raises(ConfigValidationError) as e2:
        cfg(custom={"_private": 1}).validate()
    assert "_private" in str(e2.value)


def test_a_custom_key_that_is_not_an_identifier_is_rejected():
    """Spec §2: must be a valid identifier."""
    c = cfg()
    for bad in ("my key", "2fast", "a-b", ""):
        with pytest.raises(ConfigValidationError) as e:
            setattr(c, bad, 1)
        assert "not a valid identifier" in str(e.value)


@pytest.mark.parametrize("key", ["my key", "2fast", "a-b", "", "class.attr", "ident ", " ident"])
def test_a_non_identifier_custom_key_from_the_stored_blob_is_rejected_by_validate(key):
    """Spec §2 "valid identifier" applies to a key that arrives through the constructor too — that is the path the
    stored `custom` blob of §4.3 takes on a re-run. A key like this could never be read back as config.<name>."""
    with pytest.raises(ConfigValidationError) as e:
        cfg(custom={key: 1}).validate()
    assert str(e.value) == f"custom keys must be valid identifiers: [{key!r}]"
    cfg(custom={"length": 14}).validate()                                    # a good key still validates


@pytest.mark.parametrize("key", [1, None, (1, 2), True])
def test_a_non_string_custom_key_is_rejected_as_a_validation_error(key):
    """A key that is not a string is unreadable for the same reason, and it must come back as a *validation* error:
    the identifier check runs before the shadow check, which would otherwise call `.startswith` on it and raise a
    bare AttributeError that the API's 422 path (ConfigValidationError / ValueError) would not catch."""
    with pytest.raises(ConfigValidationError) as e:
        cfg(custom={key: 1}).validate()
    assert str(e.value) == f"custom keys must be valid identifiers: [{key!r}]"
    assert not isinstance(e.value, AttributeError)
    # a leading underscore is still reported as the shadow/underscore rule, not as a bad identifier
    with pytest.raises(ConfigValidationError) as under:
        cfg(custom={"_private": 1}).validate()
    assert "start with '_'" in str(under.value)


def test_a_custom_key_that_shadows_a_builtin_is_rejected():
    """Spec §6 row 3: "rejected; only initial_capital is code-writable". Through __setattr__ a shadowing name is a
    ConfigFrozenError and never becomes a custom key; through the stored `custom` blob, validate() catches it."""
    for name in sorted(BUILTINS - CODE_WRITABLE):
        c = cfg()
        with pytest.raises(ConfigFrozenError):
            setattr(c, name, 1)
        assert c.to_dict()["custom"] == {}                                   # not quietly filed as a custom key
    c = cfg()
    c.initial_capital = 1                                                    # the one exception, and it is a built-in
    assert c.to_dict()["initial_capital"] == 1 and c.to_dict()["custom"] == {}
    for name in sorted(BUILTINS):
        with pytest.raises(ConfigValidationError) as e:
            cfg(custom={name: 1}).validate()
        assert name in str(e.value) and "shadow" in str(e.value)


@pytest.mark.parametrize("value, label", [({1, 2}, "a set"), (object(), "an object"), (lambda: 1, "a function"),
                                          ({"k": {1, 2}}, "a nested set")])
def test_a_non_serialisable_custom_value_fails_validation_before_bar_one(value, label):
    """Spec §6 row 6. `resolve` validates before it freezes, so the run never reaches bar 1."""
    with pytest.raises(ConfigValidationError) as e:
        resolve(["MOCKCO"], strategy_info=lambda c: setattr(c, "thing", value))
    assert "JSON-serialisable" in str(e.value), label


# ── ranges and types, at both ends of every allowed range ───────────────────
@pytest.mark.parametrize("field, value", [
    ("initial_capital", 0.01),       # just inside `> 0`
    ("initial_capital", 1),          # an int is a number
    ("initial_capital", 1e10),       # the spec §2 cap of 10,000,000,000 is inclusive
    ("commission_pct", 0),           # `0 <= x`
    ("commission_pct", 0.0),
    ("commission_pct", 5),           # `x <= 5`
    ("commission_pct", 5.0),
    ("pyramiding", 0),               # `>= 0`
    ("pyramiding", 1),
    ("pyramiding", 3),
    ("short_margin_pct", 0.01),      # just inside `> 0`
    ("short_margin_pct", 100),       # `x <= 100` is inclusive
    ("short_margin_pct", 100.0),
])
def test_a_value_at_the_edge_of_an_allowed_range_is_accepted(field, value):
    cfg(**{field: value}).validate()


@pytest.mark.parametrize("field, value, fragment", [
    ("initial_capital", "100000", "initial_capital must be a number"),      # spec §6 row 7: a string
    ("initial_capital", -1, "initial_capital out of range"),                # spec §6 row 7: negative
    ("initial_capital", -0.01, "initial_capital out of range"),
    ("initial_capital", 0, "initial_capital out of range"),                 # `> 0`, so 0 is out
    ("initial_capital", 0.0, "initial_capital out of range"),
    ("initial_capital", 1e10 + 1, "initial_capital out of range"),          # one rupee over the cap
    ("initial_capital", True, "initial_capital must be a number"),          # a bool is not a number here
    ("initial_capital", None, "initial_capital must be a number"),
    ("commission_pct", -0.01, "commission_pct out of range"),
    ("commission_pct", 5.01, "commission_pct out of range"),
    ("commission_pct", "0.05", "commission_pct must be a number"),
    ("commission_pct", True, "commission_pct must be a number"),
    ("pyramiding", -1, "pyramiding must be >= 0"),
    ("pyramiding", 1.5, "pyramiding must be an integer"),                   # a float is not an integer
    ("pyramiding", True, "pyramiding must be an integer"),
    ("pyramiding", "0", "pyramiding must be an integer"),
    ("short_margin_pct", 0, "short_margin_pct out of range"),               # `> 0`, so 0 is out
    ("short_margin_pct", -1, "short_margin_pct out of range"),
    ("short_margin_pct", 100.01, "short_margin_pct out of range"),
    ("short_margin_pct", False, "short_margin_pct must be a number"),
    ("symbols", [], "symbols is empty"),
    ("symbols", (), "symbols is empty"),
])
def test_a_value_outside_its_range_or_of_the_wrong_type_fails_with_the_field_named(field, value, fragment):
    """PRD §5: out-of-range values fail with the field named; spec §6 row 7 for initial_capital."""
    with pytest.raises(ConfigValidationError) as e:
        cfg(**{field: value}).validate()
    assert str(e.value).startswith(fragment), str(e.value)
    assert field in str(e.value)


@pytest.mark.parametrize("symbols, offenders", [
    ([1, 2], [1, 2]),
    ([None], [None]),
    (["MOCKCO", 7], [7]),                                                    # only the offending entry is listed
    ([b"MOCKCO"], [b"MOCKCO"]),
    ([["MOCKCO"]], [["MOCKCO"]]),
    (["  "], ["  "]),                                                        # whitespace only counts as empty
    ([""], [""]),
    (["MOCKCO", "", None], ["", None]),
])
def test_a_non_string_or_blank_entry_in_symbols_is_rejected(symbols, offenders):
    """Spec §2 types the field `list[str]`. Whether each symbol *exists* belongs to the picker and the instrument
    master (§4.4) and stays out of scope for this pure class, but the type is checkable from the value in hand —
    without it `to_dict()` would persist the junk with the run."""
    with pytest.raises(ConfigValidationError) as e:
        cfg(symbols=symbols).validate()
    assert str(e.value) == f"symbols must be non-empty strings: {offenders}"
    assert isinstance(e.value, ValueError)                                   # the route's 422 path catches this
    assert not isinstance(e.value, AttributeError)                           # and it is not the frozen-config error


def test_a_good_symbol_list_still_validates_and_an_empty_one_still_says_so():
    cfg(symbols=["MOCKCO", "INFY"]).validate()                               # MOCK - not real data
    assert resolve(["MOCKCO", "INFY"]).to_dict()["symbols"] == ["MOCKCO", "INFY"]
    for empty in ([], ()):
        with pytest.raises(ConfigValidationError) as e:
            cfg(symbols=empty).validate()
        assert str(e.value) == "symbols is empty"                            # the empty case keeps its own message


def test_an_invalid_value_written_in_strategy_info_stops_the_run_before_bar_one():
    """`resolve` validates after strategy_info and before freeze, so bar 1 is never reached."""
    with pytest.raises(ConfigValidationError) as e:
        resolve(["MOCKCO"], strategy_info=lambda c: setattr(c, "initial_capital", -5))
    assert "initial_capital out of range" in str(e.value)


# ── the stored form ─────────────────────────────────────────────────────────
def test_to_dict_carries_the_schema_version_and_a_list_of_symbols():
    """Spec §3.3 stored form, byte for byte (with mock symbols); PRD F2.1 requires schema_version."""
    def strategy_info(config):
        config.length = 14
        config.quantity = 10

    c = resolve(["MOCKCO"], ui={"initial_capital": 100_000, "commission_pct": 0.03, "pyramiding": 0,
                                "short_margin_pct": 20}, strategy_info=strategy_info)
    d = c.to_dict()
    assert d == {"schema_version": 1, "symbols": ["MOCKCO"], "initial_capital": 100000,
                 "commission_pct": 0.03, "pyramiding": 0, "short_margin_pct": 20,
                 "custom": {"length": 14, "quantity": 10}}
    assert d["schema_version"] == SCHEMA_VERSION
    assert type(d["symbols"]) is list and not isinstance(d["symbols"], tuple)   # a tuple is not JSON and not the spec
    assert json.loads(json.dumps(d)) == d                                       # persistable as it stands
    d["symbols"].append("MUTATED")
    d["custom"]["length"] = 99
    assert c.symbols == ("MOCKCO",) and c.length == 14                          # to_dict handed out copies


def test_to_dict_of_a_multi_symbol_config_keeps_the_picker_order():
    c = resolve(["MOCKCO", "OTHERCO", "ITCO"])
    assert c.to_dict()["symbols"] == ["MOCKCO", "OTHERCO", "ITCO"]


# ═════════════════════════════════════════════════════════════════════════════
# Risk Governor  (PRD F3.1-F3.4, assumption B5)
# ═════════════════════════════════════════════════════════════════════════════
CAPITAL = 1_000_000.0                                                       # MOCK - not real data
L = rg.DEFAULT_LIMITS


def intent(**kw) -> rg.Intent:
    """Entry 100, stop 90 (10 % away, ₹10 of risk a share), target 130 (reward:risk 3.0), 1,000 shares."""
    base = dict(symbol="MOCKCO", quantity=1000, entry_price=100.0, stop_price=90.0, target_price=130.0,
                sector="IT", avg_daily_value=200_000_000.0, event_blackout=False)
    base.update(kw)
    return rg.Intent(**base)


def portfolio(**kw) -> rg.Portfolio:
    base = dict(capital=CAPITAL, positions=[], realized_pnl_today=0.0, drawdown_pct=2.0, kill_switch=False,
                halted=False)
    base.update(kw)
    return rg.Portfolio(**base)


def market(**kw) -> rg.Market:
    base = dict(vix=15.0, regime="BULL")
    base.update(kw)
    return rg.Market(**base)


def held(symbol: str, value: float, sector: str, price: float = 100.0) -> rg.Position:
    """A position worth `value` rupees at `price` a share."""
    assert value % price == 0
    return rg.Position(symbol, int(value // price), price, sector)


def blank(symbol: str, value: float, price: float = 100.0) -> rg.Position:
    """A position worth `value` rupees whose sector is not known — the shape `routes._portfolio` builds from the
    desk's paper trades, which store no sector."""
    assert value % price == 0
    return rg.Position(symbol, int(value // price), price)


def go(i=None, p=None, m=None, limits=None) -> rg.Decision:
    return rg.evaluate(i or intent(), p or portfolio(), m or market(), limits or L)


def codes(d: rg.Decision):
    return [r.code for r in d.reasons]


def reason(d: rg.Decision, code: str) -> rg.Reason:
    hits = [r for r in d.reasons if r.code == code]
    assert len(hits) == 1, f"{code} appears {len(hits)} times in {codes(d)}"
    return hits[0]


def severities(d: rg.Decision):
    return {r.severity for r in d.reasons}


GOV_SOURCE = Path(rg.__file__).read_text(encoding="utf-8")
GOV_TREE = ast.parse(GOV_SOURCE)


def _codes_in_the_module() -> set:
    """Every reason code the module can emit: the literal first argument of a `Reason(...)` call, plus the
    `caps["..."]` keys, which are passed to `Reason` as a variable."""
    found = set()
    for node in ast.walk(GOV_TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Reason":
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "caps"
                and isinstance(node.slice, ast.Constant)):
            found.add(node.slice.value)
    return found


TEN_OTHER_POSITIONS = [rg.Position(f"P{i}", 1, 1.0, "BANK") for i in range(10)]   # MOCK - not real data

# One row per reason code: (code, severity, action, approved_qty, intent kwargs, portfolio kwargs, market kwargs).
# The arithmetic for every approved_qty is in the module docstring.
CASES = [
    ("KILL_SWITCH", "halt", "halt", 0, {}, {"kill_switch": True}, {}),
    ("HALTED", "halt", "halt", 0, {}, {"halted": True}, {}),
    ("DRAWDOWN_UNKNOWN", "info", "approve", 1000, {}, {"drawdown_pct": None}, {}),
    ("DRAWDOWN_HALT", "halt", "halt", 0, {}, {"drawdown_pct": 15.0}, {}),            # the 15 % limit, at the boundary
    ("DAILY_LOSS_HALT", "halt", "halt", 0, {}, {"realized_pnl_today": -30_000.0}, {}),   # 30,000/1,000,000 = 3.00 %
    ("NO_CAPITAL", "reject", "reject", 0, {}, {"capital": 0.0}, {}),
    ("INVALID_ORDER", "reject", "reject", 0, {"quantity": 0}, {}, {}),
    ("STOP_REQUIRED", "reject", "reject", 0, {"stop_price": None}, {}, {}),
    ("STOP_INVALID", "reject", "reject", 0, {"stop_price": 110.0}, {}, {}),          # above a long's entry
    ("STOP_TOO_WIDE", "reject", "reject", 0, {"stop_price": 80.0}, {}, {}),          # 20 % away, limit 15 %
    ("TARGET_REQUIRED", "reject", "reject", 0, {"target_price": None}, {}, {}),
    ("TARGET_INVALID", "reject", "reject", 0, {"target_price": 100.0}, {}, {}),       # not above the entry
    ("RR_TOO_LOW", "reject", "reject", 0, {"target_price": 114.0}, {}, {}),          # 14/10 = 1.4, minimum 1.5
    ("MAX_POSITIONS", "reject", "reject", 0, {}, {"positions": TEN_OTHER_POSITIONS}, {}),
    ("ALREADY_HELD", "reject", "reject", 0, {}, {"positions": [held("MOCKCO", 1_000.0, "IT")]}, {}),
    ("VIX_UNKNOWN", "info", "approve", 1000, {}, {}, {"vix": None}),
    ("VIX_DEFER", "defer", "defer", 0, {}, {}, {"vix": 35.0}),                        # the defer line, at the boundary
    ("EVENT_BLACKOUT", "defer", "defer", 0, {"event_blackout": True}, {}, {}),
    ("VIX_REDUCE", "reduce", "reduce", 500, {}, {}, {"vix": 25.0}),                   # 1,000 × 0.5
    ("BEAR_REGIME", "reduce", "reduce", 500, {}, {}, {"regime": "BEAR"}),             # 1,000 × 0.5
    ("REGIME_UNKNOWN", "info", "approve", 1000, {}, {}, {"regime": None}),
    ("SECTOR_UNKNOWN", "info", "approve", 1000, {"sector": None}, {}, {}),
    # ₹100,000 held with no sector: counted against the IT allowance, which still leaves 2,000 shares of room
    ("SECTOR_EXPOSURE_UNKNOWN", "info", "approve", 1000, {}, {"positions": [blank("NOSEC", 100_000.0)]}, {}),
    ("LIQUIDITY_UNKNOWN", "info", "approve", 1000, {"avg_daily_value": None}, {}, {}),
    # 10,000 of risk / 12 a share = 833.33 → 833
    ("RISK_PER_TRADE", "reduce", "reduce", 833, {"stop_price": 88.0}, {}, {}),
    # risk allows 10,000/5 = 2,000; the 10 % position limit allows 100,000/100 = 1,000
    ("POSITION_SIZE", "reduce", "reduce", 1000, {"quantity": 2000, "stop_price": 95.0}, {}, {}),
    # 750,000 already held → 800,000 − 750,000 = 50,000 left → 500 shares at 100
    ("NET_EXPOSURE", "reduce", "reduce", 500, {"quantity": 2000, "stop_price": 95.0},
     {"positions": [held("OTHERCO", 750_000.0, "BANK")]}, {}),
    # 250,000 already held in IT → 300,000 − 250,000 = 50,000 left → 500 shares at 100
    ("SECTOR_LIMIT", "reduce", "reduce", 500, {"quantity": 600, "stop_price": 95.0},
     {"positions": [held("ITCO", 250_000.0, "IT")]}, {}),
    # 5 % of an average traded value of 1,000,000 = 50,000 → 500 shares at 100
    ("LIQUIDITY", "reduce", "reduce", 500, {"quantity": 600, "stop_price": 95.0, "avg_daily_value": 1_000_000.0},
     {}, {}),
    # capital 10,000: 1 % = 100 of risk / 500 a share = 0.2 shares, and 10 % = 1,000 / 5,000 = 0.2 shares
    ("SIZE_BELOW_ONE_SHARE", "reject", "reject", 0,
     {"quantity": 1, "entry_price": 5_000.0, "stop_price": 4_500.0, "target_price": 5_750.0},
     {"capital": 10_000.0}, {}),
    # 650,000 held + 600 × 100 = 710,000 = 71.0 % of capital, over the 70 % hedge line
    ("HEDGE_SUGGESTED", "hedge", "hedge", 600, {"quantity": 600, "stop_price": 95.0},
     {"positions": [held("OTHERCO", 650_000.0, "BANK")]}, {}),
]


def test_the_case_table_covers_every_reason_code_the_module_can_emit():
    """PRD §5: one test per reason code — and every code the module contains must be reachable."""
    covered = {c[0] for c in CASES}
    in_module = _codes_in_the_module()
    assert len(CASES) == len(covered) == 31           # 30 + SECTOR_EXPOSURE_UNKNOWN, added 2026-10-21
    assert in_module - covered == set(), f"unreachable / untested codes: {sorted(in_module - covered)}"
    assert covered - in_module == set(), f"codes tested that the module cannot emit: {sorted(covered - in_module)}"


@pytest.mark.parametrize("code, severity, action, approved, i_kw, p_kw, m_kw", CASES,
                         ids=[c[0] for c in CASES])
def test_each_reason_code_is_reachable_with_its_severity_and_action(code, severity, action, approved, i_kw, p_kw, m_kw):
    d = go(intent(**i_kw), portfolio(**p_kw), market(**m_kw))
    assert code in codes(d), f"{code} not emitted; got {codes(d)}"
    assert reason(d, code).severity == severity
    assert (d.action, d.approved_qty) == (action, approved)
    assert d.requested_qty == i_kw.get("quantity", 1000)
    assert d.action in rg.ACTIONS and d.limits_version == rg.LIMITS_VERSION == "gov-v1"
    assert d.to_dict()["reasons"][codes(d).index(code)]["code"] == code     # the code survives serialisation


@pytest.mark.parametrize("code, i_kw, p_kw, m_kw, value, limit", [
    # PRD F3.2: a reason carries the value that fired it and the limit it was compared against.
    ("DRAWDOWN_HALT", {}, {"drawdown_pct": 15.0}, {}, 15.0, 15.0),
    ("DAILY_LOSS_HALT", {}, {"realized_pnl_today": -30_000.0}, {}, 3.0, 3.0),
    ("STOP_TOO_WIDE", {"stop_price": 80.0}, {}, {}, 20.0, 15.0),            # (100−80)/100 = 20 %
    ("RR_TOO_LOW", {"target_price": 114.0}, {}, {}, 1.4, 1.5),              # (114−100)/(100−90) = 1.4
    ("VIX_DEFER", {}, {}, {"vix": 35.0}, 35.0, 35.0),
    ("VIX_REDUCE", {}, {}, {"vix": 25.0}, 25.0, 25.0),
    ("MAX_POSITIONS", {}, {"positions": TEN_OTHER_POSITIONS}, {}, 10, 10),
    ("STOP_INVALID", {"stop_price": 110.0}, {}, {}, 110.0, 100.0),
    ("TARGET_INVALID", {"target_price": 100.0}, {}, {}, 100.0, 100.0),
    ("NO_CAPITAL", {}, {"capital": 0.0}, {}, 0.0, None),
    ("ALREADY_HELD", {}, {"positions": [held("MOCKCO", 1_000.0, "IT")]}, {}, "MOCKCO", None),
    ("BEAR_REGIME", {}, {}, {"regime": "BEAR"}, "BEAR", None),
    ("SIZE_BELOW_ONE_SHARE", {"quantity": 1, "entry_price": 5_000.0, "stop_price": 4_500.0, "target_price": 5_750.0},
     {"capital": 10_000.0}, {}, 0, None),
    # 650,000 held + 600 × 100 = 710,000 on 1,000,000 → 71.0 %
    ("HEDGE_SUGGESTED", {"quantity": 600, "stop_price": 95.0}, {"positions": [held("OTHERCO", 650_000.0, "BANK")]},
     {}, 71.0, 70.0),
    ("INVALID_ORDER", {"quantity": 0}, {}, {}, {"qty": 0, "entry": 100.0}, None),
    # the value is the rupee exposure that could not be classified; the limit is the sector limit it was counted into
    ("SECTOR_EXPOSURE_UNKNOWN", {}, {"positions": [blank("NOSEC", 100_000.0)]}, {}, 100_000.0, 30.0),
])
def test_a_reason_carries_the_value_that_fired_it_and_the_limit(code, i_kw, p_kw, m_kw, value, limit):
    r = reason(go(intent(**i_kw), portfolio(**p_kw), market(**m_kw)), code)
    assert (r.value, r.limit) == (value, limit)
    assert r.text and r.text[0].isupper() and r.text.endswith(".")           # a sentence a person can read


@pytest.mark.parametrize("code, configured, i_kw, p_kw", [
    # PRD F3.2: a size-cap reason names the configured percentage behind it, and its value is the cap in shares.
    ("RISK_PER_TRADE", "max_risk_per_trade_pct", {"stop_price": 88.0}, {}),
    ("POSITION_SIZE", "max_position_pct", {"quantity": 2000, "stop_price": 95.0}, {}),
    ("NET_EXPOSURE", "max_net_exposure_pct", {"quantity": 2000, "stop_price": 95.0},
     {"positions": [held("OTHERCO", 750_000.0, "BANK")]}),
    ("SECTOR_LIMIT", "max_sector_pct", {"quantity": 600, "stop_price": 95.0},
     {"positions": [held("ITCO", 250_000.0, "IT")]}),
    ("LIQUIDITY", "max_adv_pct", {"quantity": 600, "stop_price": 95.0, "avg_daily_value": 1_000_000.0}, {}),
])
def test_a_size_cap_reason_names_the_configured_limit_it_came_from(code, configured, i_kw, p_kw):
    d = go(intent(**i_kw), portfolio(**p_kw))
    r = reason(d, code)
    assert (r.severity, r.limit) == ("reduce", getattr(L, configured))
    assert isinstance(r.value, int) and r.value >= d.approved_qty            # the cap in shares, not a percentage
    # a person-set limit is what gets reported, not the default
    tight = rg.Limits(**{configured: getattr(L, configured) / 2})
    assert reason(rg.evaluate(intent(**i_kw), portfolio(**p_kw), market(), tight), code).limit == \
        getattr(L, configured) / 2


def test_every_reduce_reason_names_a_numeric_limit_except_the_one_that_has_none():
    """Guards PRD F3.2 against a return of the `limit=None` size caps. Over the whole input sweep, the only
    reduce-severity code that carries no numeric limit is BEAR_REGIME, which has no threshold to name: the regime is
    a category, and the 0.5 it applies is `bear_regime_size_factor`, a factor rather than a limit. Pinned both ways —
    if a size cap loses its limit, or BEAR_REGIME gains one, this test fails and has to be looked at."""
    without, with_limit = set(), {}
    for vix, regime, stop, adv, pos in itertools.product(
            [None, 15.0, 25.0, 30.0], [None, "BULL", "BEAR"], [88.0, 95.0, 99.0], [None, 1_000_000.0, 2e8],
            [[], [held("OTHERCO", 750_000.0, "BANK")], [held("ITCO", 250_000.0, "IT")]]):
        d = rg.evaluate(intent(quantity=5000, stop_price=stop, avg_daily_value=adv),
                        portfolio(positions=pos), rg.Market(vix=vix, regime=regime))
        for r in d.reasons:
            if r.severity == "reduce":
                (without.add(r.code) if r.limit is None else with_limit.setdefault(r.code, r.limit))
    assert without == {"BEAR_REGIME"}, sorted(without)
    assert with_limit == {"RISK_PER_TRADE": L.max_risk_per_trade_pct, "POSITION_SIZE": L.max_position_pct,
                          "NET_EXPOSURE": L.max_net_exposure_pct, "SECTOR_LIMIT": L.max_sector_pct,
                          "LIQUIDITY": L.max_adv_pct, "VIX_REDUCE": L.vix_reduce_at}


def test_a_clean_order_is_approved_whole_with_no_reasons_at_all():
    """Capital 1,000,000: risk 1 % / ₹10 a share = 1,000 shares; position 10 % / ₹100 = 1,000 shares. 1,000 fits both."""
    d = go()
    assert (d.action, d.approved_qty, d.requested_qty, d.reasons) == ("approve", 1000, 1000, [])


def test_one_share_more_than_the_limits_allow_is_reduced_to_the_limit():
    d = go(intent(quantity=1001))
    assert (d.action, d.approved_qty) == ("reduce", 1000)
    assert codes(d) == ["RISK_PER_TRADE"]                                    # risk and position tie at 1,000
    assert reason(d, "RISK_PER_TRADE").value == 1000


# ── precedence: halt > reject > defer > reduce > hedge > approve ────────────
@pytest.mark.parametrize("winner, loser, action, i_kw, p_kw, m_kw", [
    # a halt alongside a reject
    ("KILL_SWITCH", "INVALID_ORDER", "halt", {"quantity": 0}, {"kill_switch": True}, {}),
    # a halt alongside a defer
    ("DRAWDOWN_HALT", "EVENT_BLACKOUT", "halt", {"event_blackout": True}, {"drawdown_pct": 20.0}, {}),
    # a halt alongside a reduce
    ("DAILY_LOSS_HALT", "BEAR_REGIME", "halt", {}, {"realized_pnl_today": -40_000.0}, {"regime": "BEAR"}),
    # a reject alongside a defer
    ("STOP_REQUIRED", "EVENT_BLACKOUT", "reject", {"stop_price": None, "event_blackout": True}, {}, {}),
    # a reject alongside a reduce
    ("RR_TOO_LOW", "BEAR_REGIME", "reject", {"target_price": 114.0}, {}, {"regime": "BEAR"}),
    # a defer alongside a reduce
    ("VIX_DEFER", "BEAR_REGIME", "defer", {}, {}, {"vix": 36.0, "regime": "BEAR"}),
    # a reduce alongside a hedge: 750,000 held → 50,000 of net exposure left → 500 shares, and 80 % exposure after
    ("NET_EXPOSURE", "HEDGE_SUGGESTED", "reduce", {"quantity": 2000, "stop_price": 95.0},
     {"positions": [held("OTHERCO", 750_000.0, "BANK")]}, {}),
    # a hedge alongside an otherwise clean approve
    ("HEDGE_SUGGESTED", None, "hedge", {"quantity": 600, "stop_price": 95.0},
     {"positions": [held("OTHERCO", 650_000.0, "BANK")]}, {}),
])
def test_the_strictest_action_wins_and_the_losing_reasons_are_still_reported(winner, loser, action, i_kw, p_kw, m_kw):
    """PRD F3.2. The losing rule is never dropped — the decision has to explain itself completely."""
    d = go(intent(**i_kw), portfolio(**p_kw), market(**m_kw))
    assert d.action == action
    assert winner in codes(d)
    if loser is not None:
        assert loser in codes(d), f"the losing reason {loser} was dropped; got {codes(d)}"
    assert d.approved_qty == 0 if action in ("halt", "reject", "defer") else d.approved_qty > 0


def test_every_severity_that_can_coexist_resolves_to_halt_and_every_reason_survives():
    """Four severities at once. The fifth, `hedge`, is deliberately absent: the ₹700,000 already held is past the
    70 % line, but this order is halted, rejected *and* deferred, so it was never going to add anything to hedge."""
    i = intent(quantity=0, stop_price=None, event_blackout=True)
    p = portfolio(capital=CAPITAL, positions=[held("OTHERCO", 700_000.0, "BANK")], realized_pnl_today=-30_000.0,
                  drawdown_pct=20.0, kill_switch=True, halted=True)
    d = go(i, p, market(vix=36.0, regime="BEAR"))
    assert d.action == "halt" and d.approved_qty == 0
    assert severities(d) == {"halt", "reject", "defer", "reduce"}
    assert set(codes(d)) >= {"KILL_SWITCH", "HALTED", "DRAWDOWN_HALT", "DAILY_LOSS_HALT",     # halt
                             "INVALID_ORDER", "STOP_REQUIRED",                               # reject
                             "VIX_DEFER", "EVENT_BLACKOUT",                                  # defer
                             "BEAR_REGIME"}                                                   # reduce
    assert "HEDGE_SUGGESTED" not in codes(d)
    # the exposure really is hedge-worthy: 700,000 of 1,000,000 is 70.0 %, the line itself
    assert sum(x.quantity * x.price for x in p.positions) / p.capital * 100 == L.hedge_at_exposure_pct


def test_relaxing_the_top_severity_hands_the_decision_to_the_next_one_down():
    """The whole ladder, one rung at a time, on the same portfolio (700,000 held in BANK, capital 1,000,000)."""
    pos = [held("OTHERCO", 700_000.0, "BANK")]
    # 1. halt
    d = go(intent(quantity=0, stop_price=None, event_blackout=True),
           portfolio(positions=pos, realized_pnl_today=-30_000.0, drawdown_pct=20.0, kill_switch=True),
           market(vix=36.0, regime="BEAR"))
    assert d.action == "halt"
    # 2. the halts cleared → the rejects decide
    d = go(intent(quantity=0, stop_price=None, event_blackout=True), portfolio(positions=pos),
           market(vix=36.0, regime="BEAR"))
    assert (d.action, d.approved_qty) == ("reject", 0) and {"INVALID_ORDER", "STOP_REQUIRED"} <= set(codes(d))
    # 3. a well-formed order → the defers decide
    d = go(intent(quantity=2000, stop_price=95.0, event_blackout=True), portfolio(positions=pos),
           market(vix=36.0, regime="BEAR"))
    assert (d.action, d.approved_qty) == ("defer", 0) and {"VIX_DEFER", "EVENT_BLACKOUT"} <= set(codes(d))
    # 4. no event and VIX back under 35 → the reduces decide. The limits allow 1,000 shares (the 10 % position cap,
    #    and the net-exposure room of (800,000 − 700,000) / 100 is the same 1,000); VIX 26 halves that allowance and
    #    BEAR halves it again → 250. This expectation was 500 until 2026-10-21, when it was corrected: it had
    #    encoded the defect of halving the *request* (2,000 × 0.25), which left the approved size identical to the
    #    calm-market one whenever a cap was already below half the ask, while the ticket claimed the size was cut.
    d = go(intent(quantity=2000, stop_price=95.0), portfolio(positions=pos), market(vix=26.0, regime="BEAR"))
    assert (d.action, d.approved_qty) == ("reduce", 250) and {"VIX_REDUCE", "BEAR_REGIME"} <= set(codes(d))
    assert "POSITION_SIZE" in codes(d)                                       # the cap that set the allowance is named
    # 5. a calm market and an ask inside every limit → the hedge suggestion decides. 700,000 + 600 × 100 = 76 %.
    d = go(intent(quantity=600, stop_price=95.0), portfolio(positions=pos), market())
    assert (d.action, d.approved_qty) == ("hedge", 600) and codes(d) == ["HEDGE_SUGGESTED"]
    assert reason(d, "HEDGE_SUGGESTED").value == 76.0
    # 6. nothing held → approve
    d = go(intent(quantity=600, stop_price=95.0), portfolio(), market())
    assert (d.action, d.approved_qty, d.reasons) == ("approve", 600, [])


# ── the hedge suggestion is only for an order that could still be placed ───
# ₹700,000 held across seven names = 70.0 % of ₹1,000,000, so any order on top of it is past the hedge line.
HEAVY = [held(f"OTHER{n}", 100_000.0, "BANK") for n in range(7)]             # MOCK - not real data
TEN_HEAVY = [held(f"OTHER{n}", 70_000.0, "BANK") for n in range(10)]         # same ₹700,000, at the position limit


def heavy(**kw) -> rg.Portfolio:
    base = dict(positions=HEAVY)
    base.update(kw)
    return portfolio(**base)


def cleared(**kw) -> rg.Intent:
    """50 shares at ₹100, stop 95, target 120 (reward:risk 4.0): nothing about it is refusable."""
    base = dict(quantity=50, stop_price=95.0, target_price=120.0)
    base.update(kw)
    return intent(**base)


def test_a_cleared_order_on_a_heavy_book_carries_the_hedge_suggestion():
    """700,000 held + 50 × 100 = ₹705,000 of ₹1,000,000 = 70.5 %, over the 70 % line. The order is still allowed."""
    d = go(cleared(), heavy())
    assert (d.action, d.approved_qty, codes(d)) == ("hedge", 50, ["HEDGE_SUGGESTED"])
    assert (reason(d, "HEDGE_SUGGESTED").value, reason(d, "HEDGE_SUGGESTED").limit) == (70.5, 70.0)


@pytest.mark.parametrize("label, action, code, i_kw, p_kw, m_kw", [
    ("kill switch", "halt", "KILL_SWITCH", {}, {"kill_switch": True}, {}),
    ("halted", "halt", "HALTED", {}, {"halted": True}, {}),
    ("drawdown", "halt", "DRAWDOWN_HALT", {}, {"drawdown_pct": 20.0}, {}),
    ("daily loss", "halt", "DAILY_LOSS_HALT", {}, {"realized_pnl_today": -30_000.0}, {}),
    ("no stop", "reject", "STOP_REQUIRED", {"stop_price": None}, {}, {}),
    ("stop above entry", "reject", "STOP_INVALID", {"stop_price": 110.0}, {}, {}),
    ("no target", "reject", "TARGET_REQUIRED", {"target_price": None}, {}, {}),
    ("already held", "reject", "ALREADY_HELD", {"symbol": "OTHER0"}, {}, {}),
    ("at the position count", "reject", "MAX_POSITIONS", {}, {"positions": TEN_HEAVY}, {}),
    # a traded value of zero leaves a liquidity cap of 0 shares, so no whole share fits
    ("below one share", "reject", "SIZE_BELOW_ONE_SHARE", {"avg_daily_value": 0.0}, {}, {}),
    ("event blackout", "defer", "EVENT_BLACKOUT", {"event_blackout": True}, {}, {}),
    ("vix too high", "defer", "VIX_DEFER", {}, {}, {"vix": 36.0}),
], ids=lambda v: v if isinstance(v, str) else "")
def test_a_refused_order_never_suggests_hedging_an_exposure_it_was_not_going_to_add(label, action, code, i_kw, p_kw,
                                                                                    m_kw):
    """The same hedge-worthy book, refused for one reason at a time: every blocking severity suppresses the
    suggestion, and the blocking reason itself is still reported."""
    d = go(cleared(**i_kw), heavy(**p_kw), market(**m_kw))
    assert (d.action, d.approved_qty) == (action, 0), label
    assert code in codes(d), label
    assert "HEDGE_SUGGESTED" not in codes(d), f"{label}: a refused order suggested a hedge"
    assert "hedge" not in severities(d), label


@pytest.mark.parametrize("label, approved, i_kw, m_kw", [
    # 10 % of capital is 1,000 shares, so 2,000 is cut to 1,000 → (700,000 + 100,000) / 1,000,000 = 80 %
    ("a size limit", 1000, {"quantity": 2000}, {}),
    # BEAR halves 50 to 25 → (700,000 + 2,500) / 1,000,000 = 70.25 %
    ("a size factor", 25, {}, {"regime": "BEAR"}),
])
def test_a_reduced_order_still_carries_the_hedge_suggestion(label, approved, i_kw, m_kw):
    """`reduce` is not a blocking severity: the order is still going to be placed, just smaller, so the exposure it
    adds is real and the suggestion belongs on the ticket. Precedence still hands the action to `reduce`."""
    d = go(cleared(**i_kw), heavy(), market(**m_kw))
    assert (d.action, d.approved_qty) == ("reduce", approved), label
    assert "HEDGE_SUGGESTED" in codes(d), label
    assert severities(d) == {"reduce", "hedge"}
    assert reason(d, "HEDGE_SUGGESTED").value == round((700_000 + approved * 100) / CAPITAL * 100, 2)


# ── a reduced size satisfies every limit at once ────────────────────────────
def size_limits(i: rg.Intent, p: rg.Portfolio, lim: rg.Limits = L):
    """Every size limit recomputed from the inputs, in shares, independently of the module under test."""
    out = {}
    if i.stop_price is not None and 0 < i.stop_price < i.entry_price:
        out["RISK_PER_TRADE"] = p.capital * lim.max_risk_per_trade_pct / 100 / (i.entry_price - i.stop_price)
    out["POSITION_SIZE"] = p.capital * lim.max_position_pct / 100 / i.entry_price
    gross = sum(x.quantity * x.price for x in p.positions)
    out["NET_EXPOSURE"] = (p.capital * lim.max_net_exposure_pct / 100 - gross) / i.entry_price
    if i.sector:
        # A held position with no sector could be in this one, so it is counted against the allowance: an unknown
        # must not be able to buy more room than a known other sector would.
        in_sector = sum(x.quantity * x.price for x in p.positions if x.sector == i.sector or not x.sector)
        out["SECTOR_LIMIT"] = (p.capital * lim.max_sector_pct / 100 - in_sector) / i.entry_price
    if i.avg_daily_value is not None:                                        # only None is unknown; 0 is a fact
        out["LIQUIDITY"] = max(0.0, i.avg_daily_value) * lim.max_adv_pct / 100 / i.entry_price
    return out


# (label, intent kwargs, portfolio kwargs, approved, the limit that binds)
CAP_BOUND = [
    # 10,000 of risk / 12 a share = 833.33 → 833
    ("risk per trade", {"stop_price": 88.0}, {}, 833, "RISK_PER_TRADE"),
    # 100,000 / 100 = 1,000 shares
    ("position size", {"quantity": 2000, "stop_price": 95.0}, {}, 1000, "POSITION_SIZE"),
    # (800,000 − 750,000) / 100 = 500
    ("net exposure", {"quantity": 2000, "stop_price": 95.0}, {"positions": [held("OTHERCO", 750_000.0, "BANK")]},
     500, "NET_EXPOSURE"),
    # (300,000 − 250,000) / 100 = 500
    ("sector limit", {"quantity": 600, "stop_price": 95.0}, {"positions": [held("ITCO", 250_000.0, "IT")]},
     500, "SECTOR_LIMIT"),
    # 5 % of 600,000 = 30,000 / 97 = 309.27 → 309
    ("liquidity", {"quantity": 5000, "entry_price": 97.0, "stop_price": 90.0, "target_price": 120.0,
                   "avg_daily_value": 600_000.0}, {"positions": [held("OTHERCO", 500_000.0, "BANK")]},
     309, "LIQUIDITY"),
    # risk and position tie at 1,000; one share more than that is what is being asked for
    ("the tie at 1,000", {"quantity": 1001}, {}, 1000, "RISK_PER_TRADE"),
]


@pytest.mark.parametrize("label, i_kw, p_kw, approved, binding", CAP_BOUND, ids=[c[0] for c in CAP_BOUND])
def test_a_reduced_quantity_satisfies_every_size_limit_and_one_more_share_would_not(label, i_kw, p_kw, approved,
                                                                                   binding):
    """PRD §5: the reduce quantity satisfies every limit at once. Each limit is recomputed here from the inputs."""
    i, p = intent(**i_kw), portfolio(**p_kw)
    d = go(i, p)
    assert (d.action, d.approved_qty) == ("reduce", approved)
    lims = size_limits(i, p)
    assert len(lims) == 5, lims                                              # every rule had the facts it needed
    for code, shares in lims.items():
        assert d.approved_qty <= math.floor(shares + 1e-9), f"{label}: {d.approved_qty} breaches {code} ({shares})"
    breached = [code for code, shares in lims.items() if d.approved_qty + 1 > shares]
    assert breached, f"{label}: {d.approved_qty + 1} shares would breach nothing, so the cut was not a limit"
    assert binding in breached
    assert binding in codes(d)                                               # and the binding limit is named


def test_a_cut_that_comes_only_from_a_size_factor_is_not_a_limit_breach():
    """VIX 25 halves a 1,000-share ask to 500. 501 shares would still be inside every limit (both caps are 1,000);
    the cut is the volatility factor, not a limit, and the reason code says exactly that."""
    i, p = intent(), portfolio()
    d = go(i, p, market(vix=25.0))
    assert (d.action, d.approved_qty, codes(d)) == ("reduce", 500, ["VIX_REDUCE"])
    assert all(d.approved_qty + 1 <= math.floor(s + 1e-9) for s in size_limits(i, p).values())


# ── a size factor cuts what the limits allow, not what was asked for ───────
def test_a_size_factor_applies_to_what_the_limits_allow_not_to_the_request():
    """B5 lists "India VIX >=25 halves size" and "BEAR market regime halves size" among the risk limits, so the
    halving has to shrink the exposure that is actually going on the book. Applied to the *request* it does nothing
    whenever a hard cap was already below half the ask — exactly the large positions it exists to shrink.

    Ask 2,000 at ₹100 with a ₹5 stop: risk allows 10,000/5 = 2,000, the 10 % position limit allows 1,000. The
    allowance is 1,000, so VIX halves it to 500, BEAR halves it to 500, and both together quarter it to 250."""
    i, p = intent(quantity=2000, stop_price=95.0), portfolio()
    calm = go(i, p, market())
    assert (calm.action, calm.approved_qty) == ("reduce", 1000) and "POSITION_SIZE" in codes(calm)
    for m_kw, approved in (({"vix": 26.0}, 500), ({"regime": "BEAR"}, 500), ({"vix": 26.0, "regime": "BEAR"}, 250)):
        d = go(i, p, market(**m_kw))
        assert (d.action, d.approved_qty) == ("reduce", approved), (m_kw, codes(d))
        # the cap that set the allowance is still named: it is half the story of the approved quantity
        assert "POSITION_SIZE" in codes(d), m_kw
        assert (reason(d, "POSITION_SIZE").value, reason(d, "POSITION_SIZE").limit) == (1000, L.max_position_pct)
        assert d.approved_qty < calm.approved_qty, m_kw


def test_a_claimed_size_cut_is_always_a_real_cut():
    """The honesty half of the same defect: a `reduce` reason reading "size is cut" must mean the approved quantity
    is smaller than the same order would get in a calm BULL market. Checked against every combination of ask, stop
    and book below, not just the one where no cap binds."""
    for qty, stop, pos in itertools.product([600, 1000, 2000, 10_000], [88.0, 95.0, 99.0],
                                            [[], [held("OTHERCO", 750_000.0, "BANK")]]):
        i, p = intent(quantity=qty, stop_price=stop), portfolio(positions=pos)
        calm = rg.evaluate(i, p, rg.Market(vix=15.0, regime="BULL"))
        assert calm.approved_qty >= 1, (qty, stop, calm.action)
        for m in (rg.Market(vix=26.0, regime="BULL"), rg.Market(vix=15.0, regime="BEAR"),
                  rg.Market(vix=26.0, regime="BEAR")):
            d = rg.evaluate(i, p, m)
            claimed = [r.code for r in d.reasons if r.code in ("VIX_REDUCE", "BEAR_REGIME")]
            assert claimed, (m, codes(d))
            assert d.approved_qty < calm.approved_qty, (qty, stop, len(pos), m, claimed, d.approved_qty)
            # and the cut size still satisfies every limit it was measured against
            for code, shares in size_limits(i, p).items():
                assert d.approved_qty <= math.floor(shares + 1e-9), (code, shares, d.approved_qty)


# ── a held position with no sector ─────────────────────────────────────────
def test_a_held_position_with_no_sector_is_counted_against_the_sector_allowance_and_reported():
    """A book whose sectors are unknown must not read as perfectly diversified. ₹285,000 is held with no sector at
    all; the order is for ₹95,000 of BANK. Counting the unclassified value against the 30 % allowance leaves
    (300,000 − 285,000) / 100 = 150 shares, and an `info` reason says how much was counted that way, so the
    conservative assumption is never silent.

    This is the honest direction of the two: if an unclassified position counted as zero, a caller could raise the
    sector limit simply by not supplying a sector, which PRD F3.3 forbids."""
    i = intent(quantity=950, stop_price=96.0, target_price=112.0, sector="BANK")
    p = portfolio(positions=[blank(f"NOSEC{n}", 95_000.0) for n in range(3)])
    d = go(i, p)
    assert (d.action, d.approved_qty) == ("reduce", 150), codes(d)
    assert "SECTOR_LIMIT" in codes(d)
    r = reason(d, "SECTOR_EXPOSURE_UNKNOWN")
    assert (r.severity, r.value, r.limit) == ("info", 285_000.0, L.max_sector_pct)
    assert "sector" in r.text
    # the approved size keeps the worst case inside the limit: 285,000 + 150 × 100 = 30.0 % of capital
    assert (285_000.0 + d.approved_qty * i.entry_price) / p.capital * 100 == L.max_sector_pct
    # and the two halves compose: once the route supplies the sectors, the same book decides the same way, with
    # nothing left unknown to report
    known = go(i, portfolio(positions=[held(f"BANK{n}", 95_000.0, "BANK") for n in range(3)]))
    assert (known.action, known.approved_qty) == (d.action, d.approved_qty)
    assert "SECTOR_EXPOSURE_UNKNOWN" not in codes(known) and "SECTOR_LIMIT" in codes(known)
    # The consequence, stated rather than discovered: once the unclassified value is past the allowance on its own,
    # no room is left and the order is refused by PRD F3.4 — loudly, with the unknown named. That is the deliberate
    # direction for a risk layer, and it goes away for every position the desk can supply a sector for.
    full = go(i, portfolio(positions=[blank("NOSEC", 350_000.0)]))
    assert (full.action, full.approved_qty) == ("reject", 0)
    assert {"SECTOR_EXPOSURE_UNKNOWN", "SECTOR_LIMIT", "SIZE_BELOW_ONE_SHARE"} <= set(codes(full))


def test_an_unclassified_position_is_counted_on_top_of_the_sectors_that_are_known():
    """The mixed book the route fix leaves behind while some trades predate it: ₹200,000 of known IT plus ₹50,000
    with no sector, against a ₹300,000 IT allowance → ₹50,000 of room → 500 shares."""
    p = portfolio(positions=[held("ITCO", 200_000.0, "IT"), blank("NOSEC", 50_000.0)])
    d = go(intent(quantity=1000, stop_price=95.0), p)
    assert (d.action, d.approved_qty) == ("reduce", 500), codes(d)
    assert "SECTOR_LIMIT" in codes(d)
    assert reason(d, "SECTOR_EXPOSURE_UNKNOWN").value == 50_000.0
    # a position in a *known* other sector is not unclassified and nothing is reported about it
    other = go(intent(quantity=1000, stop_price=95.0), portfolio(positions=[held("BANKCO", 250_000.0, "BANK")]))
    assert "SECTOR_EXPOSURE_UNKNOWN" not in codes(other)


@pytest.mark.parametrize("missing", [None, ""])
def test_a_blank_sector_on_a_held_position_counts_as_unknown_not_as_a_sector_of_its_own(missing):
    """`None` and `""` both mean the desk stored no sector. An empty string must not read as some sector this order
    is not in, which would hand ₹250,000 a free pass through the IT allowance."""
    p = portfolio(positions=[rg.Position("NOSEC", 2500, 100.0, missing)])    # MOCK - not real data: ₹250,000
    d = go(intent(quantity=5000, stop_price=95.0), p)                        # the order is in IT
    assert (d.action, d.approved_qty) == ("reduce", 500), codes(d)
    assert reason(d, "SECTOR_EXPOSURE_UNKNOWN").value == 250_000.0


def test_dropping_the_sector_on_a_held_position_cannot_raise_the_sector_limit():
    """PRD F3.3 from the portfolio side: ₹250,000 held in IT and ₹250,000 held with no sector have to allow the same
    size for an IT order, never more."""
    i = intent(quantity=5000, stop_price=95.0)                               # sector IT
    with_sector = go(i, portfolio(positions=[held("ITCO", 250_000.0, "IT")]))
    without = go(i, portfolio(positions=[blank("ITCO2", 250_000.0)]))
    assert without.approved_qty <= with_sector.approved_qty
    assert (without.action, without.approved_qty) == ("reduce", 500)
    assert "SECTOR_EXPOSURE_UNKNOWN" in codes(without)
    assert "SECTOR_EXPOSURE_UNKNOWN" not in codes(with_sector)
    # an unknown on the order's own side is a different thing: the whole rule is skipped and SECTOR_UNKNOWN says so
    skipped = go(intent(quantity=5000, stop_price=95.0, sector=None), portfolio(positions=[blank("X", 250_000.0)]))
    assert "SECTOR_UNKNOWN" in codes(skipped) and "SECTOR_EXPOSURE_UNKNOWN" not in codes(skipped)
    assert "SECTOR_LIMIT" not in codes(skipped)


def test_when_less_than_one_whole_share_fits_the_action_is_reject_not_approve_of_zero():
    """PRD F3.4. Capital 10,000, entry 5,000, stop 4,500: 1 % of capital is 100 and one share risks 500."""
    i = intent(quantity=1, entry_price=5_000.0, stop_price=4_500.0, target_price=5_750.0)
    d = go(i, portfolio(capital=10_000.0))
    assert (d.action, d.approved_qty) == ("reject", 0)
    assert reason(d, "SIZE_BELOW_ONE_SHARE").severity == "reject" and reason(d, "SIZE_BELOW_ONE_SHARE").value == 0
    assert size_limits(i, portfolio(capital=10_000.0))["RISK_PER_TRADE"] == 0.2
    # the boundary: 50,000 of capital is exactly one share by both rules (500/500 = 1.0 and 5,000/5,000 = 1.0)
    assert go(i, portfolio(capital=50_000.0)).action == "approve"
    assert go(i, portfolio(capital=50_000.0)).approved_qty == 1
    just_under = go(i, portfolio(capital=49_999.0))
    assert (just_under.action, just_under.approved_qty) == ("reject", 0)
    assert "SIZE_BELOW_ONE_SHARE" in codes(just_under)


def test_no_decision_ever_approves_a_quantity_of_zero():
    """A sweep of 10,368 inputs: `approve`, `reduce` and `hedge` always carry at least one share, and the three
    blocking actions always carry none.

    The third book — ₹450,000 of known BANK plus ₹250,000 with no sector — is a dimension added on 2026-10-21 so
    that the sweep's limit check covers a book whose sector exposure is only partly known. It is the same ₹700,000
    of gross exposure as the second, so the net-exposure arithmetic is unchanged and only the sector rule differs."""
    seen_actions = set()
    cases = 0
    for capital, qty, stop, vix, regime, pos, adv, dd in itertools.product(
            [0.0, 10_000.0, CAPITAL],
            [0, 1, 1000, 10_000],
            [None, 90.0, 99.0, 110.0],
            [None, 20.0, 25.0, 40.0],
            [None, "BULL", "BEAR"],
            [[], [held("OTHERCO", 700_000.0, "BANK")],
             [held("OTHERCO", 450_000.0, "BANK"), blank("NOSEC", 250_000.0)]],
            [None, 0.0, 1_000_000.0],
            [2.0, 20.0]):
        cases += 1
        i = intent(quantity=qty, stop_price=stop, avg_daily_value=adv)
        p = portfolio(capital=capital, positions=pos, drawdown_pct=dd)
        d = rg.evaluate(i, p, rg.Market(vix=vix, regime=regime))
        seen_actions.add(d.action)
        assert d.requested_qty == qty
        assert d.action in rg.ACTIONS
        assert 0 <= d.approved_qty <= max(0, qty), (d.action, d.approved_qty, qty)
        if d.action in ("halt", "reject", "defer"):
            assert d.approved_qty == 0
        else:
            assert d.approved_qty >= 1, (d.action, qty, capital, stop)
        if d.action != "approve":
            assert d.reasons, d.action
        else:
            assert severities(d) <= {"info"}                                 # an approve carries nothing but notes
        if d.approved_qty > 0:
            for code, shares in size_limits(i, p).items():
                assert d.approved_qty <= math.floor(shares + 1e-9), (code, shares, d.approved_qty)
    assert cases == 10368
    assert seen_actions == set(rg.ACTIONS), sorted(seen_actions)              # the sweep exercised all six actions


# ── determinism ─────────────────────────────────────────────────────────────
def test_the_same_inputs_give_an_identical_decision():
    """PRD §5: the governor is deterministic — no clock, no randomness, no ordering surprise."""
    i_kw = dict(quantity=2000, stop_price=95.0, avg_daily_value=1_200_000.0)
    p_kw = dict(positions=[held("OTHERCO", 400_000.0, "BANK"), held("ITCO", 200_000.0, "IT")],
                realized_pnl_today=-5_000.0, drawdown_pct=9.0)
    first = go(intent(**i_kw), portfolio(**p_kw), market(vix=26.0, regime="BEAR"))
    second = go(intent(**i_kw), portfolio(**p_kw), market(vix=26.0, regime="BEAR"))
    assert first == second
    assert first.to_dict() == second.to_dict()
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    assert codes(first) == codes(second)                                     # including the order of the reasons
    # the same objects evaluated twice, and the inputs are unchanged by the call
    i, p, m = intent(**i_kw), portfolio(**p_kw), market(vix=26.0, regime="BEAR")
    before = (asdict(i), asdict(p), asdict(m))
    assert rg.evaluate(i, p, m) == rg.evaluate(i, p, m) == first
    assert (asdict(i), asdict(p), asdict(m)) == before


# ── unknown facts ───────────────────────────────────────────────────────────
UNKNOWN_CODES = {"VIX_UNKNOWN", "REGIME_UNKNOWN", "SECTOR_UNKNOWN", "LIQUIDITY_UNKNOWN", "DRAWDOWN_UNKNOWN"}


def test_an_unknown_fact_is_reported_and_neither_passes_nor_fails_its_rule_silently():
    """Module contract: where a fact is unknown the rule is skipped and an `info` reason says so."""
    known = go()
    blind = go(intent(sector=None, avg_daily_value=None), portfolio(drawdown_pct=None),
               rg.Market(vix=None, regime=None))
    assert set(codes(blind)) == UNKNOWN_CODES                                # all five said out loud
    assert severities(blind) == {"info"}                                     # none of them blocks or shrinks
    assert (blind.action, blind.approved_qty) == (known.action, known.approved_qty) == ("approve", 1000)
    assert known.reasons == []                                               # the same order with the facts supplied
    # not silently unsafe either: the limits that *can* be checked still bind
    tight = go(intent(quantity=5000, sector=None, avg_daily_value=None), portfolio(drawdown_pct=None),
               rg.Market(vix=None, regime=None))
    assert (tight.action, tight.approved_qty) == ("reduce", 1000)
    assert "RISK_PER_TRADE" in codes(tight) and UNKNOWN_CODES <= set(codes(tight))


@pytest.mark.parametrize("code, i_kw, p_kw, m_kw, skipped", [
    ("VIX_UNKNOWN", {}, {}, {"vix": None}, ("VIX_REDUCE", "VIX_DEFER")),
    ("REGIME_UNKNOWN", {}, {}, {"regime": None}, ("BEAR_REGIME",)),
    ("SECTOR_UNKNOWN", {"sector": None}, {}, {}, ("SECTOR_LIMIT",)),
    ("LIQUIDITY_UNKNOWN", {"avg_daily_value": None}, {}, {}, ("LIQUIDITY",)),
    ("DRAWDOWN_UNKNOWN", {}, {"drawdown_pct": None}, {}, ("DRAWDOWN_HALT",)),
])
def test_each_unknown_names_the_rule_it_skipped(code, i_kw, p_kw, m_kw, skipped):
    d = go(intent(**i_kw), portfolio(**p_kw), market(**m_kw))
    r = reason(d, code)
    assert r.severity == "info" and ("not supplied" in r.text or "was not supplied" in r.text)
    assert "skipped" in r.text or "could not be checked" in r.text
    for gone in skipped:
        assert gone not in codes(d)


def test_an_unknown_drawdown_does_not_mask_a_halt_that_is_known():
    d = go(intent(), portfolio(drawdown_pct=None, kill_switch=True))
    assert d.action == "halt" and {"DRAWDOWN_UNKNOWN", "KILL_SWITCH"} <= set(codes(d))


@pytest.mark.parametrize("adv", [0.0, -1.0, -1e9])
def test_a_known_zero_average_traded_value_is_a_fact_not_an_unknown(adv):
    """A stock that traded nothing leaves no 5 % to take: the liquidity cap is 0 shares, so the order is rejected
    rather than approved whole. Only `None` means "not supplied"."""
    d = go(intent(avg_daily_value=adv))
    assert (d.action, d.approved_qty) == ("reject", 0), f"{d.action} {d.approved_qty} on an ADV of {adv}"
    assert codes(d) == ["LIQUIDITY", "SIZE_BELOW_ONE_SHARE"]
    assert (reason(d, "LIQUIDITY").value, reason(d, "LIQUIDITY").limit) == (0, L.max_adv_pct)
    assert "LIQUIDITY_UNKNOWN" not in codes(d)                               # a known zero is not an unknown
    # a traded value that leaves exactly one share is the other side of that boundary: 5 % of ₹2,000 = ₹100 at ₹100
    one = go(intent(quantity=1, avg_daily_value=2_000.0))
    assert (one.action, one.approved_qty) == ("approve", 1)
    # and None still skips the rule, loudly
    unknown = go(intent(avg_daily_value=None))
    assert (unknown.action, unknown.approved_qty, codes(unknown)) == ("approve", 1000, ["LIQUIDITY_UNKNOWN"])
    assert reason(unknown, "LIQUIDITY_UNKNOWN").severity == "info"


# ── limits can only come from the configured Limits ────────────────────────
def test_the_limits_object_cannot_be_written_to_at_all():
    """PRD F3.3: limits come from configuration a person sets."""
    for field in ("max_risk_per_trade_pct", "max_position_pct", "max_open_positions", "vix_defer_at"):
        with pytest.raises(FrozenInstanceError):
            setattr(rg.DEFAULT_LIMITS, field, 999)
    assert asdict(rg.DEFAULT_LIMITS) == asdict(rg.Limits())                  # unchanged by every test above


def test_nothing_in_the_intent_or_the_portfolio_can_raise_a_limit():
    """PRD F3.3. Every tweak below is an attempt by the caller to buy more than the configured percentages allow."""
    tweaks = [
        {},                                                                  # ask for 10,000× the allowance
        {"avg_daily_value": 1e15},                                           # claim unlimited liquidity
        {"avg_daily_value": None},                                           # or no liquidity data at all
        {"sector": None},                                                    # drop the sector so the rule is skipped
        {"sector": "NOT_A_SECTOR"},                                          # or claim a sector nothing is held in
        {"target_price": 1e9},                                               # a fantastic reward:risk
        {"event_blackout": False},
        {"symbol": "RISK_PER_TRADE"},                                        # a symbol named after a rule
        {"stop_price": 99.99},                                               # a hair-thin stop to inflate the risk cap
    ]
    for tweak in tweaks:
        i = intent(quantity=10_000_000, **tweak)
        for p in (portfolio(), portfolio(capital=1e9), portfolio(positions=[held("ITCO", 100_000.0, "IT")])):
            d = rg.evaluate(i, p, market(), L)
            risk_money = d.approved_qty * (i.entry_price - i.stop_price)
            position_money = d.approved_qty * i.entry_price
            assert risk_money <= p.capital * L.max_risk_per_trade_pct / 100 + 1e-6, (tweak, d.approved_qty)
            assert position_money <= p.capital * L.max_position_pct / 100 + 1e-6, (tweak, d.approved_qty)
            assert d.approved_qty <= i.quantity
            assert d.limits_version == rg.LIMITS_VERSION
    # A bigger capital moves the rupee allowance but not the percentage. At capital 1,000,000,000 risk and position
    # both allow 1,000,000 shares (1 % of 1e9 / ₹10 of risk, and 10 % of 1e9 / ₹100), so the binding limit becomes
    # liquidity: 5 % of the ₹200,000,000 average traded value = ₹10,000,000 / ₹100 = 100,000 shares.
    big = rg.evaluate(intent(quantity=10_000_000), portfolio(capital=1e9), market(), L)
    assert (big.action, big.approved_qty) == ("reduce", 100_000) and "LIQUIDITY" in codes(big)
    # with liquidity out of the way the percentages are what bind, and they bind exactly
    deep = rg.evaluate(intent(quantity=10_000_000, avg_daily_value=1e12), portfolio(capital=1e9), market(), L)
    assert (deep.action, deep.approved_qty) == ("reduce", 1_000_000)
    assert deep.approved_qty * (100.0 - 90.0) == 1e9 * L.max_risk_per_trade_pct / 100   # ₹10,000,000 of risk
    assert deep.approved_qty * 100.0 == 1e9 * L.max_position_pct / 100                  # ₹100,000,000 of exposure


def test_a_tighter_person_set_limit_is_honoured_and_cannot_be_argued_back_up():
    """A 1 % position limit on 1,000,000 of capital is 10,000 rupees → 100 shares at 100, whatever is asked for."""
    tight = rg.Limits(max_position_pct=1.0)
    for i_kw in ({"quantity": 10_000_000}, {"quantity": 1000, "avg_daily_value": 1e15},
                 {"quantity": 1000, "sector": None}, {"quantity": 1000, "target_price": 1e6}):
        d = rg.evaluate(intent(**i_kw), portfolio(), market(), tight)
        assert (d.action, d.approved_qty) == ("reduce", 100), (i_kw, d.action, d.approved_qty)
        assert "POSITION_SIZE" in codes(d)
    assert asdict(tight) != asdict(rg.DEFAULT_LIMITS) and tight.max_risk_per_trade_pct == 1.0


def test_evaluate_does_not_mutate_the_limits_it_was_given():
    lim = rg.Limits(max_position_pct=3.0, vix_reduce_at=18.0)
    before = asdict(lim)
    rg.evaluate(intent(quantity=5000), portfolio(positions=[held("ITCO", 100_000.0, "IT")]),
                market(vix=19.0, regime="BEAR"), lim)
    assert asdict(lim) == before


# ── independence (PRD Phase 3 heading / §5 AST criterion) ──────────────────
FORBIDDEN_IN_AN_IMPORT = ("strategy", "evidence", "context", "validation", "calibration", "llm", "openai",
                          "anthropic", "claude", "gpt", "gemini", "broker", "kite", "trendlyne", "zerodha",
                          "execution", "routes", "server", "daas", "pg_client", "motor", "pymongo", "requests",
                          "httpx", "aiohttp", "fastapi", "desk_", "sector", "timeframes", "_research")


def test_the_governor_imports_nothing_from_the_strategy_evidence_or_ai_side():
    """PRD §5 AST criterion for Phase 3: `risk_governor.py` is independent by construction."""
    imported = set()
    for node in ast.walk(GOV_TREE):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))             # a relative import names a sibling
    assert imported == {"__future__", "math", "dataclasses", "typing"}, sorted(imported)
    for name in sorted(imported):
        low = name.lower()
        assert not name.startswith("."), f"relative import of a sibling module: {name}"
        assert not any(bad in low for bad in FORBIDDEN_IN_AN_IMPORT), name
    # nothing is pulled in dynamically either
    called = {n.func.id for n in ast.walk(GOV_TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attrs = {n.attr for n in ast.walk(GOV_TREE) if isinstance(n, ast.Attribute)}
    assert "__import__" not in called and "eval" not in called and "exec" not in called
    assert "import_module" not in attrs and "load_module" not in attrs
    # and at runtime the only module object the governor holds is the standard library's math
    assert {k for k, v in vars(rg).items() if isinstance(v, types.ModuleType)} == {"math"}


def test_the_governor_reads_nothing_but_its_four_arguments():
    """No clock, no environment, no file and no global state: a function of its arguments only."""
    names = {n.id for n in ast.walk(GOV_TREE) if isinstance(n, ast.Name)}
    for forbidden in ("datetime", "time", "random", "os", "open", "getenv", "environ", "uuid", "requests"):
        assert forbidden not in names, forbidden
    attrs = {n.attr for n in ast.walk(GOV_TREE) if isinstance(n, ast.Attribute)}
    assert {"now", "utcnow", "today", "random", "shuffle", "choice", "getenv"} & attrs == set()
    # math is used for one thing only: flooring a share count down
    assert {n.attr for n in ast.walk(GOV_TREE)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "math"} == {"floor"}


def test_the_limits_in_the_module_are_the_prd_assumption_b5_numbers():
    """PRD B5: the defaults are an owner-reviewable assumption, so they are pinned here."""
    assert asdict(rg.DEFAULT_LIMITS) == {
        "max_risk_per_trade_pct": 1.0, "max_position_pct": 10.0, "max_open_positions": 10, "max_sector_pct": 30.0,
        "max_net_exposure_pct": 80.0, "hedge_at_exposure_pct": 70.0, "max_daily_loss_pct": 3.0,
        "max_drawdown_pct": 15.0, "min_reward_risk": 1.5, "max_stop_distance_pct": 15.0, "vix_reduce_at": 25.0,
        "vix_defer_at": 35.0, "max_adv_pct": 5.0, "bear_regime_size_factor": 0.5, "vix_size_factor": 0.5}
    assert rg.ACTIONS == ("approve", "reduce", "hedge", "defer", "reject", "halt")   # F3.1, in precedence order


@pytest.mark.parametrize("field, ok, breached, i_kw, p_kw, m_kw, code", [
    # both ends of every threshold B5 states: the value at the limit passes, a hair past it fires.
    ("max_stop_distance_pct", 85.0, 84.99, {}, {}, {}, "STOP_TOO_WIDE"),            # 15.00 % vs 15.01 % away
    ("min_reward_risk", 115.0, 114.99, {}, {}, {}, "RR_TOO_LOW"),                   # 1.5 vs 1.499
    ("max_drawdown_pct", 14.99, 15.0, {}, {}, {}, "DRAWDOWN_HALT"),
    ("max_daily_loss_pct", -29_999.0, -30_000.0, {}, {}, {}, "DAILY_LOSS_HALT"),    # 2.9999 % vs 3.0000 %
    ("vix_defer_at", 34.99, 35.0, {}, {}, {}, "VIX_DEFER"),
    ("vix_reduce_at", 24.99, 25.0, {}, {}, {}, "VIX_REDUCE"),
    # 698,000 + 10 × 100 = 69.9 % after the order; 699,000 + 1,000 = 70.0 % exactly, and the line is inclusive
    ("hedge_at_exposure_pct", 698_000.0, 699_000.0, {}, {}, {}, "HEDGE_SUGGESTED"),
    ("max_open_positions", 9, 10, {}, {}, {}, "MAX_POSITIONS"),
])
def test_both_ends_of_every_threshold(field, ok, breached, i_kw, p_kw, m_kw, code):
    def build(v):
        i, p, m = dict(i_kw), dict(p_kw), dict(m_kw)
        if field == "max_stop_distance_pct":
            i["stop_price"] = v
            i["target_price"] = 1000.0                                       # keep reward:risk out of the way
        elif field == "min_reward_risk":
            i["target_price"] = v
        elif field == "max_drawdown_pct":
            p["drawdown_pct"] = v
        elif field == "max_daily_loss_pct":
            p["realized_pnl_today"] = v
        elif field in ("vix_defer_at", "vix_reduce_at"):
            m["vix"] = v
        elif field == "hedge_at_exposure_pct":
            i["quantity"] = 10                                               # 10 × 100 = 1,000 on top of what is held
            i["stop_price"] = 95.0
            p["positions"] = [held("OTHERCO", v, "BANK")]
        elif field == "max_open_positions":
            p["positions"] = TEN_OTHER_POSITIONS[:v]
        return go(intent(**i), portfolio(**p), market(**m))

    assert code not in codes(build(ok)), f"{code} fired at the allowed end of {field}"
    assert code in codes(build(breached)), f"{code} did not fire one step past {field}"
