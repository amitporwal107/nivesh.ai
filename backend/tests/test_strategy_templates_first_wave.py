"""The owner's first-wave templates (services/strategy_plan/templates.py): covered call, bull put and bear call credit
spreads, protective put, collar. TESTCASES T, P, R in test_reports/desk_templates_signal_record_TESTCASES.md.

MOCK — not real data: the chain is hand-made round numbers (the shape routes/fno.py sends), so every expected figure is
worked by hand in the comments. Spot 1215, lot 50, one lot unless stated:
    1100: call 130, put  5      1150: call 85, put 15      1250: call 14, put 40      1300: call 4, put 70
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route
from services import desk_strategy_trades as strat
from services.risk_gate import gate
from services.risk_gate import service as svc
from services.strategy_plan import compute_payoff
from services.strategy_plan import templates as tp
from tests.test_risk_service import EXPIRY, listed, snap, structure

TODAY = date(2026, 10, 27)
CHAIN = {"as_of": "2026-10-26", "strikes": [
    {"strike": 1100.0, "call": {"close": 130.0}, "put": {"close": 5.0}},
    {"strike": 1150.0, "call": {"close": 85.0}, "put": {"close": 15.0}},
    {"strike": 1250.0, "call": {"close": 14.0}, "put": {"close": 40.0}},
    {"strike": 1300.0, "call": {"close": 4.0}, "put": {"close": 70.0}},
    {"strike": 1350.0, "call": {"close": None}, "put": None},
]}
KW = dict(spot=1215.0, lot_size=50, expiry=EXPIRY, underlying="FIXA", today=TODAY)

#: (template, strikes, direction) — the strikes every case below builds.
FIRST_WAVE = [
    ("covered_call", {"call_strike": 1250.0}, "bullish"),
    ("bull_put_spread", {"long_strike": 1100.0, "short_strike": 1150.0}, "bullish"),
    ("bear_call_spread", {"short_strike": 1250.0, "long_strike": 1300.0}, "bearish"),
    ("protective_put", {"put_strike": 1150.0}, "bullish"),
    ("collar", {"put_strike": 1150.0, "call_strike": 1250.0}, "bullish"),
]


def build(name, strikes, **over):
    return getattr(tp, name)(CHAIN, **{**KW, **over}, **strikes)


def shape(t):
    return [(l["kind"], l["side"], l.get("option_type"), l.get("strike"), l["quantity"], l["lot_size"], l["entry_price"])
            for l in t["legs"]]


# ── T: legs, max loss / profit, breakevens ──────────────────────────────────

def test_t1_covered_call():
    # 50 shares at 1215 + sell 1250C at 14: max profit (1250 − 1215 + 14) × 50 = 2,450 above 1250;
    # max loss at a price of 0: −(1215 − 14) × 50 = −60,050; breakeven 1215 − 14 = 1201
    t = build("covered_call", {"call_strike": 1250.0})
    assert shape(t) == [("cash", "buy", None, None, 50, 1, 1215.0), ("option", "sell", "call", 1250.0, 1, 50, 14.0)]
    assert (t["max_profit"], t["max_loss"], t["breakevens"]) == (2450.0, -60050.0, [1201.0])
    assert not t["profit_unbounded"] and not t["loss_unbounded"] and t["net_premium"] == 700.0
    assert t["legs"][0]["price_source"] == "NSE F&O bhavcopy underlying price, 2026-10-26"
    assert t["legs"][1]["price_source"] == "NSE F&O bhavcopy close, 2026-10-26"
    # two lots: 100 shares cover 2 × 50 call units
    t2 = build("covered_call", {"call_strike": 1250.0}, lots=2)
    assert t2["legs"][0]["quantity"] == 100 and t2["max_profit"] == 4900.0


def test_t1b_covered_call_spot_source_from_the_chain():
    t = tp.covered_call({**CHAIN, "spot_source": "MOCK spot"}, call_strike=1250.0, **KW)
    assert t["legs"][0]["price_source"] == "MOCK spot"


def test_t2_covered_call_short_call_must_be_out_of_the_money():
    for k in (1150.0, 1100.0):
        with pytest.raises(tp.TemplateError) as e:
            build("covered_call", {"call_strike": k})
        assert e.value.code == "strike_not_otm"


def test_t3_bull_put_spread_is_a_credit():
    # buy 1100P at 5, sell 1150P at 15: credit 10 × 50 = 500; max loss (50 − 10) × 50 = 2,000; breakeven 1150 − 10
    t = build("bull_put_spread", {"long_strike": 1100.0, "short_strike": 1150.0})
    assert shape(t) == [("option", "buy", "put", 1100.0, 1, 50, 5.0), ("option", "sell", "put", 1150.0, 1, 50, 15.0)]
    assert (t["max_profit"], t["max_loss"], t["breakevens"], t["net_premium"]) == (500.0, -2000.0, [1140.0], 500.0)


def test_t4_bull_put_spread_strike_order():
    with pytest.raises(tp.TemplateError) as e:
        build("bull_put_spread", {"long_strike": 1150.0, "short_strike": 1100.0})
    assert e.value.code == "strike_order"


def test_t5_bear_call_spread_is_a_credit():
    # sell 1250C at 14, buy 1300C at 4: credit 10 × 50 = 500; max loss (50 − 10) × 50 = 2,000; breakeven 1250 + 10
    t = build("bear_call_spread", {"short_strike": 1250.0, "long_strike": 1300.0})
    assert shape(t) == [("option", "sell", "call", 1250.0, 1, 50, 14.0), ("option", "buy", "call", 1300.0, 1, 50, 4.0)]
    assert (t["max_profit"], t["max_loss"], t["breakevens"], t["net_premium"]) == (500.0, -2000.0, [1260.0], 500.0)


def test_t6_bear_call_spread_strike_order():
    with pytest.raises(tp.TemplateError) as e:
        build("bear_call_spread", {"short_strike": 1300.0, "long_strike": 1250.0})
    assert e.value.code == "strike_order"


def test_t7_protective_put():
    # 50 shares at 1215 + buy 1150P at 15: max loss (1215 − 1150 + 15) × 50 = 4,000; gain open; breakeven 1230
    t = build("protective_put", {"put_strike": 1150.0})
    assert shape(t) == [("cash", "buy", None, None, 50, 1, 1215.0), ("option", "buy", "put", 1150.0, 1, 50, 15.0)]
    assert t["max_loss"] == -4000.0 and t["profit_unbounded"] and t["max_profit"] is None
    assert t["breakevens"] == [1230.0] and t["net_premium"] == -750.0


def test_t8_collar():
    # shares at 1215 + buy 1150P at 15 + sell 1250C at 14: net debit 1. Max loss (1215 − 1150 + 1) × 50 = 3,300;
    # max profit (1250 − 1215 − 1) × 50 = 1,700; breakeven 1216
    t = build("collar", {"put_strike": 1150.0, "call_strike": 1250.0})
    assert shape(t) == [("cash", "buy", None, None, 50, 1, 1215.0), ("option", "buy", "put", 1150.0, 1, 50, 15.0),
                        ("option", "sell", "call", 1250.0, 1, 50, 14.0)]
    assert (t["max_profit"], t["max_loss"], t["breakevens"], t["net_premium"]) == (1700.0, -3300.0, [1216.0], -50.0)
    assert not t["profit_unbounded"] and not t["loss_unbounded"]


def test_t9_collar_strike_rules():
    with pytest.raises(tp.TemplateError) as e:
        build("collar", {"put_strike": 1250.0, "call_strike": 1250.0})
    assert e.value.code == "strike_order"
    with pytest.raises(tp.TemplateError) as e:
        build("collar", {"put_strike": 1100.0, "call_strike": 1150.0})
    assert e.value.code == "strike_not_otm"


@pytest.mark.parametrize("name, strikes, code", [
    ("covered_call", {"call_strike": 1350.0}, "no_premium"),
    ("covered_call", {"call_strike": 1275.0}, "no_strike"),
    ("bull_put_spread", {"long_strike": 1000.0, "short_strike": 1150.0}, "no_strike"),
    ("bear_call_spread", {"short_strike": 1250.0, "long_strike": 1350.0}, "no_premium"),
    ("protective_put", {"put_strike": 1350.0}, "no_premium"),
    ("collar", {"put_strike": 1150.0, "call_strike": 1350.0}, "no_premium"),
])
def test_t10_never_guesses_a_price(name, strikes, code):
    with pytest.raises(tp.TemplateError) as e:
        build(name, strikes)
    assert e.value.code == code


@pytest.mark.parametrize("spot", [None, 0, -5.0, True])
def test_t10b_no_spot_no_shares(spot):
    with pytest.raises(tp.TemplateError) as e:
        tp.protective_put(CHAIN, spot=spot, lot_size=50, expiry=EXPIRY, put_strike=1150.0, today=TODAY)
    assert e.value.code == "no_spot"


@pytest.mark.parametrize("name, strikes, direction", FIRST_WAVE)
def test_t11_template_numbers_are_the_payoff_engines_with_statutory_costs(name, strikes, direction):
    t = build(name, strikes)
    # the template's own grid (templates._result): capital at risk is evaluated up to the grid's top, where a short
    # call's exit costs keep growing with the price, so the same grid is needed for the same figure
    prices = [1215.0] + [l["strike"] for l in t["legs"] if l.get("strike")] + [l["entry_price"] for l in t["legs"] if l["kind"] != "option"]
    r = compute_payoff({"underlying": "FIXA", "reference_price": 1215.0, "legs": t["legs"], "as_of": "2026-10-26",
                        "grid": {"min": min(prices) * 0.5, "max": max(prices) * 1.5, "points": 400}}, TODAY)
    assert r["valid"] and r["calculation_version"] == "payoff-v2"
    e = r["expiry"]
    assert (t["max_profit"], t["max_loss"], t["breakevens"]) == (e["max_profit"], e["max_loss"], e["breakevens"])
    assert t["capital_at_risk"] == r["capital_at_risk"] > -t["max_loss"]          # costs on top of the gross loss
    assert r["costs"]["components"]["entry"]["stt"] > 0                           # statutory charges priced (payoff-v2)


# ── P: the payoff route and the paper-trade path accept them ────────────────

def _client(monkeypatch):
    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


@pytest.mark.parametrize("name, strikes, direction", FIRST_WAVE)
def test_p1_payoff_route_accepts_each(monkeypatch, name, strikes, direction):
    t = build(name, strikes)
    res = _client(monkeypatch).post("/api/desk/strategy/payoff", json={
        "underlying": "FIXA", "reference_price": 1215.0, "legs": t["legs"], "as_of": "2026-10-26"})
    assert res.status_code == 200
    b = res.json()
    assert b["valid"] is True and b["problems"] == [], b["problems"]
    assert b["expiry"]["max_loss"] == t["max_loss"] and b["sent_to_broker"] is False


@pytest.mark.parametrize("legs", [
    [{"kind": "cash", "side": "buy", "quantity": 49, "lot_size": 1, "entry_price": 1215.0},           # 49 shares < 50 call units
     {"kind": "option", "side": "sell", "quantity": 1, "lot_size": 50, "entry_price": 14.0, "expiry": EXPIRY,
      "strike": 1250.0, "option_type": "call"}],
    [{"kind": "option", "side": "sell", "quantity": 1, "lot_size": 50, "entry_price": 15.0, "expiry": EXPIRY,
      "strike": 1150.0, "option_type": "put"}],
])
def test_p2_naked_shorts_are_still_refused(monkeypatch, legs):
    b = _client(monkeypatch).post("/api/desk/strategy/payoff", json={
        "underlying": "FIXA", "reference_price": 1215.0, "legs": legs, "as_of": "2026-10-26"}).json()
    assert b["valid"] is False and [p["code"] for p in b["problems"]] == ["undefined_risk_not_supported"]


def paper_legs(t):
    """A template's legs in the paper-trade shape (routes/desk_trading.py strategy POST): `lots` is shares for cash."""
    out = []
    for l in t["legs"]:
        leg = {"kind": l["kind"], "side": l["side"], "lots": l["quantity"], "lot_size": l["lot_size"],
               "entry_price": l["entry_price"], "price_source": l["price_source"]}
        if l["kind"] != "cash":
            leg["expiry"] = l["expiry"]
        if l["kind"] == "option":
            leg.update(strike=l["strike"], option_type=l["option_type"])
        out.append(leg)
    return out


@pytest.mark.parametrize("name, strikes, direction", FIRST_WAVE)
def test_p3_paper_trade_path_accepts_each(name, strikes, direction):
    assert name in strat.FAMILIES
    legs = [strat.clean_leg(l, TODAY) for l in paper_legs(build(name, strikes))]
    verdict = strat.check_defined_risk(legs)
    assert verdict == {"defined_risk": True, "futures_exposure": False, "note": None}


# ── R: the universal risk service's verdict ─────────────────────────────────

DEFINED_RISK_CODES = {"naked_short_call", "naked_short_put", "unhedged_future", "futures_only", "mixed_expiries",
                      "unbounded_loss", "short_futures_not_supported"}


def decide(legs, direction, equity=1_000_000.0):
    return svc.decide(structure(legs, symbol="FIXA", reference_price=1215.0, direction=direction, fno_additional=True),
                      snap(last_close=1215.0, equity=equity, refs=listed(50), open_structures=0))


def status(d, check):
    return next(c["status"] for c in d["checks"] if c["check"] == check)


@pytest.mark.parametrize("name, strikes, direction", FIRST_WAVE)
def test_r1_r2_each_is_defined_risk_to_the_service_and_the_gate(name, strikes, direction):
    legs = paper_legs(build(name, strikes))
    d = decide(legs, direction)
    assert status(d, "defined_risk") == "pass" and status(d, "fno_additional") == "pass"
    assert not {r["code"] for r in d["reasons"]} & DEFINED_RISK_CODES
    typed, failures = gate.clean_legs(legs)
    assert failures == [] and gate.defined_risk_failures(typed) == []


def test_r3_a_covered_call_on_a_long_future_is_refused_by_the_gate_so_the_template_uses_shares():
    legs = [{"kind": "future", "side": "buy", "lots": 1, "lot_size": 50, "entry_price": 1215.0, "expiry": EXPIRY},
            {"kind": "option", "side": "sell", "lots": 1, "lot_size": 50, "entry_price": 14.0, "expiry": EXPIRY,
             "strike": 1250.0, "option_type": "call"}]
    typed, _ = gate.clean_legs(legs)
    assert [c for c, _ in gate.defined_risk_failures(typed)] == ["unhedged_future"]
    d = decide(legs, "bullish")
    assert "unhedged_future" in {r["code"] for r in d["reasons"] if r["check"] == "fno_additional"}


@pytest.mark.parametrize("legs, code", [
    ([{"kind": "option", "side": "sell", "lots": 1, "lot_size": 50, "entry_price": 14.0, "expiry": EXPIRY,
       "strike": 1250.0, "option_type": "call"}], "unbounded_loss"),
    ([{"kind": "option", "side": "sell", "lots": 1, "lot_size": 50, "entry_price": 15.0, "expiry": EXPIRY,
       "strike": 1150.0, "option_type": "put"}], "naked_short_put"),
    ([{"kind": "cash", "side": "buy", "lots": 49, "lot_size": 1, "entry_price": 1215.0},          # 49 shares < 50 units
      {"kind": "option", "side": "sell", "lots": 1, "lot_size": 50, "entry_price": 14.0, "expiry": EXPIRY,
       "strike": 1250.0, "option_type": "call"}], "unbounded_loss"),
])
def test_r4_naked_shorts_still_fail_defined_risk(legs, code):
    d = decide(legs, "bullish")
    assert status(d, "defined_risk") == "fail" and code in {r["code"] for r in d["reasons"] if r["check"] == "defined_risk"}


def test_r5_what_the_service_decides_today_on_the_default_profile():
    """Recorded as found, rules unchanged (reported to the owner): every first-wave structure passes defined risk, but
    with the default profile (0.5% per trade, min reward:risk 1.5) the sizing checks still decide —
      * covered call: its maximum loss is the shares to zero, so `min_lot_exceeds_budget` even at Rs 1 crore equity;
      * credit spreads: net credit after costs below 1/3 of the strike width, `credit_too_small` (risk policy v2, PR
        #382: the credit rule replaces the 1.5 reward:risk minimum for credit structures);
      * the collar: reward:risk below 1.5, `reward_risk_too_low`;
      * protective put: allowed."""
    expect = {"covered_call": ("block", "min_lot_exceeds_budget"), "bull_put_spread": ("block", "credit_too_small"),
              "bear_call_spread": ("block", "credit_too_small"), "collar": ("block", "reward_risk_too_low"),
              "protective_put": ("allow", None)}
    for name, strikes, direction in FIRST_WAVE:
        d = decide(paper_legs(build(name, strikes)), direction, equity=10_000_000.0)
        outcome, code = expect[name]
        assert d["outcome"] == outcome, (name, d["reasons"])
        assert [r["code"] for r in d["reasons"]] == ([code] if code else []), (name, d["reasons"])
