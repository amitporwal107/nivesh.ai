"""The universal risk-decision service (services/risk_gate/service.py), its estimate, the profile and the book's marks.

TESTCASES: test_reports/p1_universal_risk_TESTCASES.md (D = decisions and sizing, F = fail closed, P = profile).
`decide()` is pure over a snapshot, so most cases build the snapshot by hand: a calm market, a known sector, a fresh
last close and a flat book, then change the one input the case is about.

MOCK — not real data: FIXA / NIFTY / FIXE and every price here are made up; the PRD worked examples (A, E, F) are the
PRD's own hypothetical numbers (docs/NIVESH_AI_LAB_TRADING_DECISION_GUIDELINES.md §8).
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timezone

import pytest

from services import data_freshness as fresh
from services import desk_trading as desk
from services import risk_book
from services import risk_profile as rp
from services.risk_gate import estimate as est
from services.risk_gate import replay
from services.risk_gate import service as svc
from tests.test_risk_gate import FakeDB

NOW = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)        # Tuesday 10:30 IST
EXPIRY = "2026-11-26"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def book(equity=1_000_000.0, profile=None, **over):
    b = {"profile": profile or rp.default_state("u1"),
         "account": {"cash_rs": equity, "blocked_rs": 0.0, "available_rs": equity, "starting_capital_rs": 1e6},
         "equity": {"equity_rs": equity, "unknown_reasons": [], "marks_as_of": "2026-10-26"},
         "peak": {"peak_rs": equity}, "drawdown_pct": 0.0,
         "day": {"start": "2026-10-27", "pnl_rs": 0.0, "start_equity_rs": equity, "unknown_reasons": []},
         "week": {"start": "2026-10-26", "pnl_rs": 0.0, "start_equity_rs": equity, "unknown_reasons": []},
         "open": {"positions": 0, "risk_rs": 0.0, "exposure_rs": 0.0, "sector_rs": {}, "unclassified_exposure_rs": 0.0,
                  "legacy_risk_rs": 0.0, "legacy_exposure_rs": 0.0, "legacy_positions": 0, "legacy_risk_unknown": []},
         "positions": [], "reservations": []}
    b.update(over)
    return b


def snap(last_close=1005.0, equity=1_000_000.0, refs=None, **over):
    s = {"today": "2026-10-27", "controls": {"kill_switch": False, "halted": False}, "live_allowed": None,
         "book": book(equity), "book_error": None,
         "instrument": {"last_close": last_close, "last_close_as_of": "2026-10-26", "adv_rs": 5e9,
                        "last_close_freshness": {"ok": True, "as_of": "2026-10-26", "age_sessions": 0, "budget": 2}},
         "sector": {"sector": "Capital Goods"},
         "market": {"vix": 14.0, "regime": "BULL", "as_of": "2026-10-26", "freshness": {"ok": True}},
         "references": refs or {}, "open_structures": "n/a"}
    s.update(over)
    return s


def cash(**over):
    body = dict(correlation_id="c1", user_id="u1", actor_id="u1", mode="paper", path="desk_paper_trade", symbol="FIXA",
                quantity=85, entry_price=1005.0, stop_price=970.0, target_price=1110.0)
    body.update(over)
    return svc.EntryRequest(**body)


def call(side, strike, price, lots=1, lot=50):
    return {"kind": "option", "side": side, "lots": lots, "lot_size": lot, "entry_price": price, "expiry": EXPIRY,
            "strike": strike, "option_type": "call"}


def structure(legs, **over):
    body = dict(correlation_id="c1", user_id="u1", actor_id="u1", mode="paper", path="desk_paper_trade",
                instrument="structure", symbol="NIFTY", legs=legs, direction="bullish", reference_price=25010.0)
    body.update(over)
    return svc.EntryRequest(**body)


def listed(lot):
    return {EXPIRY: {"listed": True, "lot_size": lot, "source": "MOCK", "as_of": "2026-10-26"}}


def codes(d):
    return [r["code"] for r in d["reasons"]]


# ── D: the PRD's worked examples under the owner's 0.5% profile ─────────────
def test_d1_example_a_is_reduced_so_the_cost_and_gap_inclusive_risk_fits_rs_3000():
    """0.5% of Rs 6 lakh = Rs 3,000 (Example A's budget). At 85 shares the loss at the stop is Rs 2,975 gross but
    Rs 4,117.61 with costs and the 1% gap stress, so the service reduces; the approved size's estimate fits."""
    d = svc.decide(cash(), snap(equity=600_000.0))
    assert d["outcome"] == "reduce" and d["requested_qty"] == 85
    assert est.cash_risk(85, 1005, 970)["total"] > 3000
    assert d["approved_qty"] == min(est.max_cash_qty(3000, 1005, 970, 85), 59)          # 10% position cap = 59 shares
    assert d["estimated_risk_rs"]["total"] <= 3000 and "per_trade_risk_exceeded" in codes(d)
    assert d["budget"]["per_trade_budget_rs"] == 3000.0


@pytest.mark.parametrize("market", [{"vix": 14.0, "regime": "BEAR"}, {"vix": 26.0, "regime": "BULL"}])
@pytest.mark.parametrize("ask", [400, 85, 49, 20])
def test_d1b_a_reduced_size_sent_again_is_allowed_in_a_bear_or_high_vix_market(ask, market):
    """Found on staging 2026-10-27 (regime BEAR): INFY ×400 → reduce 42, then 42 → 21 → 10 → 5 → block, because the
    governor halved whatever size it was sent. The desk accepts only an allow, so no share paper trade could be
    recorded. Now the factor halves the limit: the most is half of min(per-trade fit, 10% position cap), and that
    size, sent again, is allowed unchanged."""
    m = {**market, "as_of": "2026-10-26", "freshness": {"ok": True}}
    first = svc.decide(cash(quantity=ask), snap(market=m))
    fit = est.max_cash_qty(5000.0, 1005.0, 970.0, 10 ** 9, desk.COST_MODEL)       # 0.5% of Rs 10 lakh
    ceiling = min(fit, 99) // 2                                                     # 10% position cap = 99 shares
    assert first["outcome"] in ("allow", "reduce") and first["approved_qty"] == min(ask, ceiling), codes(first)
    again = svc.decide(cash(quantity=first["approved_qty"]), snap(market=m))
    assert (again["outcome"], again["approved_qty"]) == ("allow", first["approved_qty"]), codes(again)


def test_d2_example_e_one_futures_lot_is_over_rs_2500_and_is_refused_not_rounded_up():
    fut = [{"kind": "future", "side": "buy", "lots": 1, "lot_size": 100, "entry_price": 1250.0, "expiry": EXPIRY,
            "strike": None, "option_type": None}]
    d = svc.decide(structure(fut, symbol="FIXE", reference_price=1250.0, stop_underlying=1225.0, target_underlying=1300.0),
                   snap(last_close=1250.0, equity=500_000.0, refs=listed(100)))
    assert d["outcome"] == "block" and "min_lot_exceeds_budget" in codes(d)
    r = next(r for r in d["reasons"] if r["code"] == "min_lot_exceeds_budget")
    assert r["limit"] == 2500.0 and r["value"] > 2500.0          # Rs 2,500 gross + costs + Rs 1,225 gap stress


def test_d3_example_f_the_spreads_maximum_loss_plus_costs_exceeds_rs_2500():
    legs = [call("buy", 25000, 220), call("sell", 25200, 130)]
    d = svc.decide(structure(legs), snap(last_close=25010.0, equity=500_000.0, refs=listed(50)))
    r = next(r for r in d["reasons"] if r["code"] == "min_lot_exceeds_budget")
    assert d["outcome"] == "block" and r["limit"] == 2500.0
    assert r["value"] == est.structure_risk(legs, direction="bullish", stop_underlying=None)[0]["total"]
    assert est.structure_risk(legs, direction="bullish", stop_underlying=None)[0]["gross"] == 4500.0   # PRD figure


def test_d4_the_estimate_is_gross_plus_desk_cost_card_costs_plus_the_gap_stress():
    e = est.cash_risk(85, 1005.0, 970.0)
    assert e["gross"] == 2975.0 and e["gap_stress"] == round(85 * 970 * est.GAP_STRESS_PCT / 100, 2)
    assert e["costs"] == desk.round_trip_cost(85, 1005.0, 970.0, desk.COST_MODEL)
    assert e["stop_based"] == round(e["gross"] + e["costs"], 2) and e["total"] == round(e["stop_based"] + e["gap_stress"], 2)
    assert e["version"] == est.ESTIMATE_VERSION and est.GAP_STRESS_PCT == 1.0


def test_d5_a_spread_over_budget_is_reduced_in_whole_lots():
    # Debit 60 = Rs 3,000 of maximum loss per lot, Rs 7,000 of maximum gain (reward:risk ~2.3; Example F's own 1.2 is
    # below the 1.5 minimum, so it cannot show the lot rounding). 0.5% of Rs 14 lakh = Rs 7,000: two lots fit, three not.
    legs = [call("buy", 25000, 150, lots=3), call("sell", 25200, 90, lots=3)]
    d = svc.decide(structure(legs), snap(last_close=25010.0, equity=1_400_000.0, refs=listed(50)))
    assert d["outcome"] == "reduce" and (d["requested_lots"], d["approved_lots"]) == (3, 2), codes(d)
    assert d["estimated_risk_rs"]["total"] <= 7_000


def test_d6_exposure_and_loss_at_stop_are_separate_limits():
    """A 1% stop on Rs 2 lakh risks ~Rs 4,300 (inside 0.5% of Rs 10 lakh) but is 20% of equity in one position."""
    d = svc.decide(cash(quantity=200, entry_price=1000.0, stop_price=990.0, target_price=1050.0), snap(last_close=1000.0))
    assert d["outcome"] == "reduce" and "POSITION_SIZE" in codes(d) and d["approved_qty"] == 100
    assert d["estimated_risk_rs"]["total"] < 5000


def test_d7_the_decision_carries_the_structured_result():
    d = svc.decide(cash(quantity=10), snap())
    assert d["outcome"] == "allow" and d["approved_qty"] == 10
    assert set(d["estimated_risk_rs"]) >= {"gross", "costs", "gap_stress", "total", "stop_based"}
    assert {"per_trade_budget_rs", "open_risk_cap_rs", "sector_cap_rs", "drawdown_pct", "funding_rs"} <= set(d["budget"])
    assert d["limits_version"].startswith("rp-0-") and [c["check"] for c in d["checks"]] == list(svc.CHECK_ORDER)
    assert all(set(r) == {"code", "check", "severity", "value", "limit", "message"} for r in d["reasons"])


def test_d8_a_stored_decision_replays_to_the_same_answer():
    req, s = cash(), snap(equity=600_000.0)
    s = svc.gate.bson_safe({**s, "request": req.model_dump()})
    body = svc.decide(req, s)
    row = {"_id": "d1", "source": "risk_service", "snapshot": s, "snapshot_version": svc.SNAPSHOT_VERSION,
           "snapshot_hash": svc.snapshot_hash(s), "inputs_hash": svc.inputs_hash(req), "policy_version": svc.POLICY_VERSION,
           "outcome": {"allow": "allowed", "reduce": "reduced", "block": "blocked"}[body["outcome"]],
           "reasons": body["reasons"], "checks": body["checks"], "approved_qty": body["approved_qty"],
           "approved_lots": body["approved_lots"]}
    out = replay.replay(row)
    assert out["replayable"] and out["match"], out["differences"]
    row["snapshot"]["book"]["equity"]["equity_rs"] = 9e9          # an edited snapshot no longer matches its hash
    assert replay.replay(row)["match"] is False


# ── F: every required input fails closed with its own reason ─────────────────
@pytest.mark.parametrize("name,mutate,code", [
    ("last close unknown", lambda s: s["instrument"].update(last_close=None, last_close_freshness={
        "ok": False, "age_sessions": None, "reason": "no value could be read"}), "last_close_unknown"),
    ("last close stale", lambda s: s["instrument"].update(last_close_freshness={
        "ok": False, "age_sessions": 5, "as_of": "2026-10-19", "budget": 2, "reason": "old"}), "last_close_stale"),
    ("sector unknown", lambda s: s.update(sector={"sector": None, "error": "not on the lists"}), "sector_unknown"),
    ("market unknown", lambda s: s.update(market={"vix": None, "regime": None, "freshness": {"ok": False}}),
     "market_state_unknown"),
    ("market stale", lambda s: s["market"].update(freshness={"ok": False, "age_sessions": 5, "budget": 2}),
     "market_state_stale"),
    ("liquidity unknown", lambda s: s["instrument"].update(adv_rs=None), "liquidity_unknown"),
    ("controls unreadable", lambda s: s.update(controls=None), "controls_unreadable"),
    ("account unreadable", lambda s: s.update(book=None, book_error="down"), "account_unreadable"),
    ("legacy risk unknown", lambda s: s["book"]["open"].update(legacy_risk_unknown=["OLD"]), "open_risk_unknown"),
])
def test_f_a_missing_or_stale_input_blocks_with_its_reason(name, mutate, code):
    s = snap()
    mutate(s)
    d = svc.decide(cash(quantity=10), s)
    assert d["outcome"] == "block" and code in codes(d), (name, codes(d))


def test_f7_unknown_equity_blocks_with_drawdown_unknown():
    s = snap()
    s["book"]["equity"] = {"equity_rs": None, "unknown_reasons": ["NIFTY structure has no F&O marks"]}
    s["book"]["drawdown_pct"] = None
    d = svc.decide(cash(quantity=10), s)
    assert d["outcome"] == "block" and {"equity_unknown", "drawdown_unknown"} <= set(codes(d))


@pytest.mark.parametrize("field,value,code", [("daily_loss_pct", None, "daily_loss_halt"),
                                              ("weekly_loss_pct", None, "weekly_loss_halt")])
def test_loss_halts_use_start_of_period_equity(field, value, code):
    s = snap()
    key = "day" if field.startswith("daily") else "week"
    s["book"][key] = {"start": "2026-10-26", "pnl_rs": -45_000.0, "start_equity_rs": 1_000_000.0, "unknown_reasons": []}
    assert code in codes(svc.decide(cash(quantity=10), s))


def test_the_drawdown_halt_and_its_unknown():
    s = snap()
    s["book"]["drawdown_pct"] = 12.0
    assert "drawdown_halt" in codes(svc.decide(cash(quantity=10), s))


def test_f12_options_are_marked_at_the_close_never_at_the_settle_price():
    """On an expiry day the bhavcopy's settle_price of an option is the UNDERLYING's price, not a premium. The book
    removes settle_price from option rows before simulate_strategy, so the close marks the leg."""
    doc = {"_id": "s1", "kind": "strategy", "underlying": "FIXU", "direction": "bullish", "status": "open",
           "opened_at": "2026-10-20T04:00:00+00:00", "cost_model": dict(desk.COST_MODEL),
           "legs": [{"kind": "option", "side": "buy", "lots": 1, "lot_size": 250, "entry_price": 40.0,
                     "expiry": "2026-10-29", "strike": 1300.0, "option_type": "call", "index": 0}]}
    bars = [{"date": date(2026, 10, 21), "open": 1240, "high": 1250, "low": 1230, "close": 1245, "volume": 1}]
    rows = [[{"as_of_date": "2026-10-21", "settle_price": 1245.0, "close_price": 12.0}]]       # settle = underlying
    value, day = risk_book.structure_value(doc, bars, rows)
    assert day == date(2026, 10, 21)
    gross = (12.0 - 40.0) * 250
    assert value is not None and value < gross < 0                  # the close (12), less costs; never 1245


# ── P: the per-account profile and its audited setter ────────────────────────
def test_p1_no_stored_profile_is_the_owner_defaults_said_explicitly():
    p = run(rp.read(FakeDB(), "u1"))
    assert p["stored"] is False and p["limits"] == rp.NAMED[rp.OWNER_DEFAULT]
    assert list(p["limits"].values()) == [0.5, 3.0, 10.0, 25.0, 2.0, 4.0, 10.0, 1.5]
    assert rp.NAMED[rp.ENGINEERING] == {"per_trade_risk_pct": 1.0, "max_open_risk_pct": 6.0, "max_position_pct": 10.0,
                                        "max_sector_pct": 30.0, "daily_loss_pct": 3.0, "weekly_loss_pct": 6.0,
                                        "max_drawdown_pct": 15.0, "min_reward_risk": 1.5}
    assert "simulation default" in p["starting_capital_label"] and p["starting_capital_rs"] == 1_000_000.0


def test_p2_to_p6_tighten_loosen_reason_and_concurrency():
    db = FakeDB()
    out = run(rp.set_limits(db, "u1", reason="smaller bets", actor="u1", actor_is_admin=False,
                            changes={"per_trade_risk_pct": 0.4}, now=NOW))
    assert out["limits"]["per_trade_risk_pct"] == 0.4 and out["version"] == 1 and out["stored"]
    (row,) = db[rp.AUDIT].docs
    assert (row["actor"], row["changes"], row["reason"], row["loosened"]) == (
        "u1", {"per_trade_risk_pct": {"before": 0.5, "after": 0.4}}, "smaller bets", [])
    assert row["effective_from"] == NOW.isoformat() and row["version_after"] == 1
    with pytest.raises(rp.ProfileError) as e:                     # loosening is an admin's
        run(rp.set_limits(db, "u1", reason="more", actor="u1", actor_is_admin=False, changes={"max_sector_pct": 30}))
    assert e.value.code == "admin_required" and len(db[rp.AUDIT].docs) == 1
    with pytest.raises(rp.ProfileError) as e:
        run(rp.set_limits(db, "u1", reason="", actor="u1", actor_is_admin=False, changes={"per_trade_risk_pct": 0.3}))
    assert e.value.code == "invalid_input"
    out = run(rp.set_limits(db, "u1", reason="comparison run", actor="adm", actor_is_admin=True, profile=rp.ENGINEERING))
    assert out["profile"] == rp.ENGINEERING and out["limits"] == rp.NAMED[rp.ENGINEERING]
    # Every limit the engineering profile loosens; it keeps the 10% position limit and the 1.5 reward:risk.
    assert sorted(db[rp.AUDIT].docs[-1]["loosened"]) == sorted(set(rp.FIELDS) - {"max_position_pct", "min_reward_risk"})
    db[rp.PROFILES].docs[0]["version"] = 99                        # another change landed between the read and the write
    real = db[rp.PROFILES].find_one

    async def stale(q):
        doc = await real(q)
        return {**doc, "version": 2}
    db[rp.PROFILES].find_one = stale
    with pytest.raises(rp.ProfileError) as e:
        run(rp.set_limits(db, "u1", reason="x", actor="adm", actor_is_admin=True, changes={"daily_loss_pct": 1.0}))
    assert e.value.code == "concurrent_change"


def test_profile_validation():
    with pytest.raises(rp.ProfileError):
        rp.plan_change(rp.NAMED[rp.OWNER_DEFAULT], changes={"per_trade_risk_pct": 9})
    with pytest.raises(rp.ProfileError):
        rp.plan_change(rp.NAMED[rp.OWNER_DEFAULT], changes={"max_open_risk_pct": 0.2})       # below per-trade
    with pytest.raises(rp.ProfileError):
        rp.plan_change(rp.NAMED[rp.OWNER_DEFAULT], changes={"bogus": 1})
    assert rp.is_looser("min_reward_risk", 1.5, 1.0) and not rp.is_looser("min_reward_risk", 1.5, 2.0)


# ── the freshness rule ───────────────────────────────────────────────────────
def test_freshness_counts_weekday_sessions_from_the_reference_session():
    assert fresh.reference_session(NOW) == date(2026, 10, 26)        # Tuesday -> Monday
    assert fresh.reference_session(datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc)) == date(2026, 10, 23)  # Mon -> Fri
    assert fresh.sessions_after(date(2026, 10, 23), date(2026, 10, 26)) == 1                 # the weekend is not a session
    ok = fresh.assess("x", "2026-10-23", budget_sessions=2, now=NOW)
    assert ok["ok"] and ok["age_sessions"] == 1
    old = fresh.assess("x", "2026-10-20", budget_sessions=2, now=NOW)
    assert not old["ok"] and old["age_sessions"] == 4 and "budget is 2" in old["reason"]
    assert not fresh.assess("x", None, budget_sessions=2, now=NOW)["ok"]
    assert fresh.known("x", "IT")["ok"] and not fresh.known("x", None)["ok"]


# ── index underlyings (found by the staging probe, 2026-10-27) ───────────────
def test_an_index_underlying_reads_its_nse_index_close_and_a_named_sector(monkeypatch):
    """nidp.prices_eod has no BANKNIFTY / NIFTY rows on staging, so the last close comes from the NSE index's own
    end-of-day closes, and the sector from inputs.INDEX_SECTORS. MOCK rows shaped like /v1/indices/{index}/eod."""
    import importlib
    from services.copilot_tools import daas_client
    from services.risk_gate import inputs as real_inputs
    inputs = importlib.reload(real_inputs)
    asked = []

    async def fake_get(path, params=None, timeout=10.0, *, creds=None):
        asked.append(path)
        return {"data": [{"as_of_date": "2026-10-26", "close_price": 54366.7, "high_price": 54500.0, "low_price": 54100.0},
                         {"as_of_date": "2026-10-23", "close_price": 54287.35}]}
    monkeypatch.setattr(daas_client, "_get", fake_get)
    out = run(inputs.instrument("BANKNIFTY", date(2026, 10, 27)))
    assert (out["last_close"], out["last_close_as_of"], out["adv_rs"]) == (54366.7, "2026-10-26", None)
    assert asked == ["/indices/Nifty%20Bank/eod"] and [b["date"].isoformat() for b in out["bars"]] == ["2026-10-23", "2026-10-26"]
    assert run(inputs.sector_of("BANKNIFTY"))["sector"] == "Financial Services"
    assert run(inputs.sector_of("NIFTY"))["sector"] == "Broad market index"
