"""Paper Trading v2 — GET /api/v1/paper/fno-structures (services/spt/fno_structures.py; TESTCASES PV2-B-24..26).
MOCK — not real data: the structures, the chain (prices, IVs, Greeks), the quotes and the margin are made up. The real
pricing path runs: services/positions/service.paper_groups → _price_leg → analytics (Black-76), on the MOCK chain."""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from services.paper_pnl import book as book_mod
from services.paper_pnl import prices
from services.positions import analytics
from services.positions import service as positions_service
from services.spt import fno_structures as fs
from tests.paper_v2_fakes import A, NOW, client, world  # noqa: F401 (fixtures)

EXP = "2026-11-24"
TODAY = date(2026, 11, 5)


def pub(legs, sid="s1", **over):
    """MOCK desk paper strategy trade, as services/desk_strategy_trades.public_strategy_trade shapes it."""
    p = {"id": sid, "kind": "strategy", "underlying": "NIFTY", "symbol": "NIFTY", "status": "open",
         "family": "bull_call_spread", "family_name": "Bull call spread", "summary_text": "MOCK", "direction": "bullish",
         "opened_at": "2026-11-04T05:00:00+00:00", "stop_underlying": None, "target_underlying": None, "legs": legs}
    p.update(over)
    return p


def leg(i, side, strike, entry, lots=1, otype="call"):
    return {"index": i, "kind": "option", "side": side, "lots": lots, "lot_size": 75, "entry_price": entry,
            "expiry": EXP, "strike": strike, "option_type": otype, "mark": None, "pnl_rs": None}


def side_row(settle, iv, delta, gamma, theta, vega):
    return {"settle": settle, "close": settle, "iv": iv, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega,
            "volume": 100, "oi": 1000}


def chain(iv_26200=13.5):
    """MOCK NSE chain for EXP (the shape routes/fno.chain answers)."""
    return {"as_of": "2026-11-04", "spot": 26000.0, "lot_size": 75, "futures": {}, "error": None,
            "chains": {EXP: {"lot_size": 75, "summary": {"forward": 26050.0, "days_to_expiry": 19, "spot": 26000.0,
                                                          "as_of": "2026-11-04"},
                             "strikes": [{"strike": 26000.0, "call": side_row(150.0, 14.0, 0.55, 0.0004, -8.0, 20.0)},
                                         {"strike": 26200.0, "call": side_row(70.0, iv_26200, 0.40 if iv_26200 else None,
                                                                              0.0003 if iv_26200 else None,
                                                                              -6.0 if iv_26200 else None,
                                                                              17.0 if iv_26200 else None)}]}}}


UQ = {"quotes": {"NIFTY": {"ltp": 26050.0}}, "source": "kite_live", "as_of": "2026-11-05T05:00:00+00:00"}


def group_for(p, monkeypatch, iv_26200=13.5):
    async def price_fno(request, underlying, expiries):
        return chain(iv_26200)
    monkeypatch.setattr(positions_service, "price_fno", price_fno)
    return asyncio.run(positions_service.paper_groups(None, [p], UQ))[0]


# ── PV2-B-24 shape and figures ───────────────────────────────────────────────
def test_pv2_b_24_bull_call_spread_figures(monkeypatch):
    p = pub([leg(0, "buy", 26000.0, 150.0), leg(1, "sell", 26200.0, 70.0)])
    g = group_for(p, monkeypatch)
    s = fs.structure(p, group=g, leg_ltp={"s1:0": 160.0, "s1:1": 75.0}, margin=(12345.0, None), limit_rs=6500.0,
                     today=TODAY)
    assert set(s) >= {"id", "name", "underlying", "underlying_ltp", "expiry", "days_to_expiry", "lots", "lot_size", "status",
                      "hedged", "max_loss_rs", "max_profit_rs", "breakevens", "net", "margin_rs", "pnl_rs", "legs",
                      "scenarios"}
    assert (s["status"], s["hedged"], s["underlying_ltp"], s["expiry"], s["days_to_expiry"], s["lots"], s["lot_size"]) == \
        ("filled", True, 26050.0, EXP, 19, 1, 75)
    assert s["max_loss_rs"] == 6000.0                  # net debit (150 − 70) × 75
    assert s["max_profit_rs"] == 9000.0                # (200 − 80) × 75
    assert s["breakevens"] == [26080.0]
    assert s["net"] == {"delta": 11.25, "gamma": 0.0075, "theta_rs_day": -150.0, "vega_rs_pt": 225.0}   # 75 × (a − b)
    assert s["pnl_rs"] == 375.0                        # 75 × (160 − 150) − 75 × (75 − 70)
    assert [(l["side"], l["entry"], l["ltp"], l["filled_qty"], l["qty"], l["pnl_rs"], l["pending"]) for l in s["legs"]] == [
        ("BUY", 150.0, 160.0, 75, 75, 750.0, False), ("SELL", 70.0, 75.0, 75, 75, -375.0, False)]
    assert s["legs"][0]["contract"] == "NIFTY 24 Nov 2026 26000 CE"
    assert (s["margin_rs"], s["max_loss_used_pct"], s["max_loss_flag"]) == (12345.0, 92.31, "NEAR_LIMIT")
    sc = {x["name"]: x for x in s["scenarios"]}
    assert list(sc) == ["und_down_2", "und_down_1", "und_up_1", "und_up_2", "iv_up_5", "iv_down_5", "theta_1d",
                        "expiry_at_level"]
    assert sc["und_up_1"]["pnl_rs"] > 0 > sc["und_down_2"]["pnl_rs"] and sc["theta_1d"]["pnl_rs"] < 0
    now_v = analytics.today_pnl(g["_legs"], 26050.0, 26050.0)
    # held to expiry at 26,050: (50 − 150) × 75 + (70 − 0) × 75 = −2,250, less the model value now
    assert sc["expiry_at_level"]["pnl_rs"] == round(-2250.0 - now_v, 2)
    assert sc["expiry_at_level"]["label"] == "Expiry at 26,050"
    assert s["stress"]["iv_up_10_rs"] is not None


def test_pv2_b_24b_body_totals_and_limits(monkeypatch):
    p = pub([leg(0, "buy", 26000.0, 150.0), leg(1, "sell", 26200.0, 70.0)])
    s = fs.structure(p, group=group_for(p, monkeypatch), leg_ltp={"s1:0": 160.0, "s1:1": 75.0}, margin=(12345.0, None),
                     limit_rs=6500.0, today=TODAY)
    b = fs.body([s, dict(s, id="s2")], equity=1_000_000.0, limits={"fno_max_loss_pct": 0.35, "margin_util_pct": 70.0},
                notes=[], as_of="t")
    assert b["totals"]["margin_rs"] == 24690.0 and b["totals"]["max_loss_rs"] == 12000.0 and b["totals"]["count"] == 2
    assert b["totals"]["net"]["delta"] == 22.5 and b["totals"]["margin_util_used_pct"] == 2.469
    assert b["limits"] == {"fno_max_loss_pct": 0.35, "margin_util_pct": 70.0, "fno_max_loss_rs": 3500.0,
                           "margin_limit_rs": 700000.0, "equity_rs": 1_000_000.0}
    assert b["scenario_note"] == "Scenarios are assumptions, not forecasts."


# ── PV2-B-25 fill state ──────────────────────────────────────────────────────
def test_pv2_b_25_pending_protective_leg_is_partial_and_unhedged(monkeypatch):
    p = pub([leg(0, "sell", 26000.0, 150.0), leg(1, "buy", 26200.0, None)], family="bear_call_spread")
    g = group_for(p, monkeypatch)
    s = fs.structure(p, group=g, leg_ltp={"s1:0": 140.0, "s1:1": 60.0}, margin=(None, "MOCK"), limit_rs=6500.0, today=TODAY)
    assert (s["status"], s["hedged"]) == ("partial", False)
    assert s["max_loss_rs"] is None and "unbounded" in s["max_loss_reason"]
    pending = s["legs"][1]
    assert (pending["pending"], pending["filled_qty"], pending["pnl_rs"], pending["qty"]) == (True, 0, None, 75)
    assert s["pnl_rs"] == 750.0                       # only the filled short: −75 × (140 − 150)
    assert s["net"]["delta"] == -41.25                # the filled short alone: −75 × 0.55
    assert any("Partly filled" in n and "unhedged" in n for n in s["notes"])


def test_pv2_b_25b_long_future_alone_has_no_to_zero_max_loss(monkeypatch):
    p = pub([{"index": 0, "kind": "future", "side": "buy", "lots": 1, "lot_size": 75, "entry_price": 26000.0,
              "expiry": EXP, "strike": None, "option_type": None}], family="long_future", stop_underlying=25800.0)
    s = fs.structure(p, group=None, leg_ltp={}, margin=(None, "MOCK"), limit_rs=6500.0, today=TODAY)
    assert s["max_loss_rs"] is None and "owner rule" in s["max_loss_reason"] and s["hedged"] is False
    assert s["loss_at_stop_rs"] == 15000.0            # 75 × (26,000 − 25,800)
    assert s["pnl_rs"] is None and any("no price now" in n for n in s["notes"])


# ── PV2-B-26 unpriced ────────────────────────────────────────────────────────
def test_pv2_b_26_no_iv_means_null_greeks_and_scenarios(monkeypatch):
    p = pub([leg(0, "buy", 26000.0, 150.0), leg(1, "sell", 26200.0, 70.0)])
    g = group_for(p, monkeypatch, iv_26200=None)
    s = fs.structure(p, group=g, leg_ltp={"s1:0": 160.0, "s1:1": 75.0}, margin=(None, "MOCK: no Kite session"),
                     limit_rs=6500.0, today=TODAY)
    assert s["net"] == {"delta": None, "gamma": None, "theta_rs_day": None, "vega_rs_pt": None}
    assert all(x["pnl_rs"] is None for x in s["scenarios"])
    assert any("implied volatility" in n for n in s["notes"])
    assert s["max_loss_rs"] == 6000.0                 # the payoff needs no IV
    assert (s["margin_rs"], s["margin_reason"]) == (None, "MOCK: no Kite session")


# ── over HTTP ────────────────────────────────────────────────────────────────
def test_pv2_b_24c_route(client, monkeypatch):
    p = pub([leg(0, "buy", 26000.0, 150.0), leg(1, "sell", 26200.0, 70.0)])

    async def read_book(db, uid, **kw):
        return book_mod.Book(open=[book_mod.strategy_item(p)])

    async def resolve(legs, now=None, feed=None):
        return {"s1:0": SimpleNamespace(ltp=160.0), "s1:1": SimpleNamespace(ltp=75.0)}, {"notes": []}

    async def und(symbols):
        return UQ

    async def price_fno(request, underlying, expiries):
        return chain()

    async def margin(db, underlying, legs, key):
        assert legs == [{"side": "buy", "option_type": "call", "expiry": EXP, "strike": 26000.0, "lots": 1},
                        {"side": "sell", "option_type": "call", "expiry": EXP, "strike": 26200.0, "lots": 1}]
        return 12345.0, None

    monkeypatch.setattr(book_mod, "read_book", read_book)
    monkeypatch.setattr(prices, "resolve", resolve)
    monkeypatch.setattr(positions_service, "underlying_quotes", und)
    monkeypatch.setattr(positions_service, "price_fno", price_fno)
    monkeypatch.setattr(fs, "zerodha_margin", margin)
    r = client.get("/api/v1/paper/fno-structures", headers=A)
    assert r.status_code == 200, r.text
    b = r.json()
    assert set(b) >= {"structures", "totals", "limits", "basis", "notes"}
    s = b["structures"][0]
    # the default limit: 0.7 × 0.5 % = 0.35 % of ₹10L = ₹3,500; the spread's ₹6,000 max loss is 171.43 % of it
    assert (s["id"], s["max_loss_rs"], s["margin_rs"], s["pnl_rs"], s["max_loss_flag"], s["max_loss_used_pct"]) == \
        ("s1", 6000.0, 12345.0, 375.0, "BREACH", 171.43)
    assert b["limits"]["fno_max_loss_pct"] == 0.35 and b["limits"]["fno_max_loss_rs"] == 3500.0
    assert b["totals"]["margin_rs"] == 12345.0


def test_pv2_b_24d_route_with_no_structure(client):
    b = client.get("/api/v1/paper/fno-structures", headers=A).json()
    assert b["structures"] == [] and b["totals"]["count"] == 0 and "No open desk paper F&O structure." in b["notes"]
