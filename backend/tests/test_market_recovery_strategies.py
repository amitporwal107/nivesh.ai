"""Market Recovery › strategies with downside protection: TC-S1 … TC-S6 of docs/market_recovery/DESIGN.md §8.

A hand-made option chain (MOCK — not real data): strikes 80–120 every 5, lot 100, close 100; the page's plan for the stock is
entry low 98, Stop loss 92, Target 1 112, Target 2 118. Every expected figure below is worked out by hand in its comment."""
import asyncio
import copy
from datetime import date

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from services.market_recovery import strategies as S

PLAN = {"close": 100.0, "entry_low": 98.0, "stop_loss": 92.0, "target_1": 112.0, "target_2": 118.0}
CALLS = {100: 4.0, 105: 2.0, 110: 1.0, 115: 0.5, 120: 0.2, 95: 6.5, 90: 10.5, 85: 15.2, 80: 20.1}
PUTS = {100: 3.5, 95: 1.8, 90: 0.9, 85: 0.4, 80: 0.2, 105: 6.0, 110: 10.2, 115: 15.1, 120: 20.0}


def side(price, oi=1000, vol=50, iv=0.3):
    return {"close": price, "settle": price, "oi": oi, "volume": vol, "iv": iv, "delta": 0.5}


def chain(calls=CALLS, puts=PUTS, lot=100, as_of="2026-11-03", over=None):
    rows = []
    for k in sorted(set(calls) | set(puts)):
        rows.append({"strike": float(k), "call": side(calls[k]) if k in calls else None, "put": side(puts[k]) if k in puts else None})
    for (k, sd), patch in (over or {}).items():
        r = next(x for x in rows if x["strike"] == k)
        r[sd] = {**r[sd], **patch}
    return {"summary": {"as_of": as_of, "spot": 100.0}, "lot_size": lot, "strikes": rows}


def by_key(out):
    return {s["key"]: s for s in out}


# ── TC-S1 strikes from the plan ──────────────────────────────────────────────────────────────────────────────────

def test_tc_s1_strikes_from_the_plan():
    ks = sorted(float(k) for k in PUTS)
    assert S.strikes_for("protective_put", ks, ks, PLAN)[0] == {"put": 100.0}
    assert S.strikes_for("bull_call_spread", ks, ks, PLAN)[0] == {"long_call": 100.0, "short_call": 110.0}   # nearest 112
    assert S.strikes_for("collar", ks, ks, PLAN)[0] == {"long_put": 90.0, "short_call": 110.0}               # nearest 92 / 112
    assert S.strikes_for("bull_put_spread", ks, ks, PLAN)[0] == {"short_put": 95.0, "long_put": 90.0}        # ≤ 98 / near 92
    assert S.strikes_for("put_ratio_backspread", ks, ks, PLAN)[0] == {"short_put": 100.0, "long_put": 90.0}


def test_tc_s1_fallbacks_when_the_level_sits_on_the_wrong_side():
    ks = [95.0, 100.0, 105.0]
    plan = dict(PLAN, stop_loss=99.0, target_1=101.0)          # nearest to the stop is 100 (≥ close), nearest to T1 is 100
    assert S.strikes_for("bull_call_spread", ks, ks, plan)[0] == {"long_call": 100.0, "short_call": 105.0}
    assert S.strikes_for("collar", ks, ks, plan)[0] == {"long_put": 95.0, "short_call": 105.0}
    k, why = S.strikes_for("bull_call_spread", [90.0, 100.0], [90.0, 100.0], plan)
    assert k is None and "No call strike above" in why


# ── TC-S2 payoff figures equal the hand-worked values ────────────────────────────────────────────────────────────

def test_tc_s2_figures():
    out = by_key(S.build_options(PLAN, chain()))
    assert [s["key"] for s in out.values()] == list(S.ORDER)

    pp = out["protective_put"]                     # 100 shares @100 + 100 put @3.5
    assert pp["net_premium"] == -350.0 and pp["outlay"] == -10350.0 and pp["net_premium_per_share"] == -3.5
    assert pp["max_loss"] == -350.0 and pp["profit_unbounded"] and pp["max_profit"] is None
    assert pp["breakevens"] == [103.5]
    assert pp["reward_risk"] == pytest.approx(850 / 350, abs=0.01)          # P&L at Target 1 (112): (12 − 3.5) × 100
    stop = pp["scenarios"][0]
    assert stop["label"] == "At the Stop loss" and stop["pnl"] == -350.0 and stop["pnl_unhedged"] == -800.0
    assert [l["action"] for l in pp["legs"]] == ["Buy", "Buy"] and pp["legs"][0]["instrument"] == "Shares"

    bc = out["bull_call_spread"]                   # 100 call @4 bought, 110 call @1 written: debit 3
    assert bc["net_premium"] == -300.0 and bc["max_profit"] == 700.0 and bc["max_loss"] == -300.0
    assert bc["breakevens"] == [103.0] and bc["reward_risk"] == pytest.approx(2.33, abs=0.01)
    assert [l["action"] for l in bc["legs"]] == ["Buy", "Sell"]

    co = out["collar"]                             # shares + 90 put @0.9 bought + 110 call @1.0 written: credit 0.1
    assert co["net_premium"] == 10.0 and co["max_loss"] == -990.0 and co["max_profit"] == 1010.0
    assert co["breakevens"] == [99.9]

    bp = out["bull_put_spread"]                    # 95 put @1.8 written, 90 put @0.9 bought: credit 0.9
    assert bp["net_premium"] == 90.0 and bp["max_profit"] == 90.0 and bp["max_loss"] == -410.0
    assert bp["breakevens"] == [94.1]

    rb = out["put_ratio_backspread"]               # 1 × 100 put @3.5 written, 2 × 90 put @0.9 bought: credit 1.7
    assert rb["net_premium"] == 170.0 and rb["max_loss"] == -830.0          # at 90: −10 × 100 + 170
    assert rb["max_profit"] == 8170.0 and not rb["profit_unbounded"]        # at 0: −96.5×100 + 2×89.1×100
    assert rb["reward_risk"] is None                                       # not a ratio: profit needs a collapse
    assert rb["breakevens"] == [81.7, 98.3]
    assert [l["lots"] for l in rb["legs"]] == [1, 2]
    for s in out.values():
        assert len(s["payoff"]) == S.PAYOFF_POINTS and s["max_loss_with_costs"] <= s["max_loss"]


# ── TC-S3 checks ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_tc_s3_reward_risk_and_credit_checks():
    out = by_key(S.build_options(PLAN, chain()))
    assert out["protective_put"]["status"] == "passes" and out["bull_call_spread"]["status"] == "passes"
    co = out["collar"]                                                  # 1010 / 990 = 1.02 < 1.5
    assert co["status"] == "fails" and "Reward : risk" in co["why"]
    bp = {c["id"]: c for c in out["bull_put_spread"]["checks"]}
    assert bp["credit"]["pass"] is False and "credit ₹90 vs width ₹500" in bp["credit"]["detail"]
    assert bp["reward_risk"]["pass"] is False
    rb = {c["id"]: c for c in out["put_ratio_backspread"]["checks"]}
    assert rb["reward_risk"]["pass"] is None and out["put_ratio_backspread"]["status"] == "passes"


def test_tc_s3_illiquid_leg_fails_with_the_reason():
    out = by_key(S.build_options(PLAN, chain(over={(110.0, "call"): {"volume": 0}})))
    bc = out["bull_call_spread"]
    assert bc["status"] == "fails" and "Call 110: no trades today" in bc["why"]
    assert out["protective_put"]["status"] == "passes"                   # its legs are untouched


def test_tc_s3_missing_price_and_missing_strike_are_unavailable():
    out = by_key(S.build_options(PLAN, chain(over={(100.0, "put"): {"close": None, "settle": None}})))
    assert out["protective_put"]["status"] == "unavailable" and "Put 100 has no price" in out["protective_put"]["why"]
    calls = {k: v for k, v in CALLS.items() if k <= 100}
    out = by_key(S.build_options(PLAN, chain(calls=calls)))
    assert out["bull_call_spread"]["status"] == "unavailable"
    assert out["bull_call_spread"]["checks"][0]["id"] == "strikes"


def test_tc_s3_settlement_price_when_untraded():
    out = by_key(S.build_options(PLAN, chain(over={(100.0, "put"): {"close": None, "settle": 3.6, "volume": 0}})))
    pp = out["protective_put"]
    assert pp["legs"][1]["price"] == 3.6 and pp["legs"][1]["price_basis"] == "settlement" and pp["status"] == "fails"


# ── TC-S4 expiry ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rows,expected", [
    ([("2026-11-10", 6), ("2026-11-24", 20), ("2026-12-29", 55)], ("2026-11-24", 20)),
    ([("2026-11-10", 6), ("2027-01-26", 83)], ("2026-11-10", 6)),
    ([("2026-11-05", 3)], None),
])
def test_tc_s4_expiry_choice(rows, expected):
    assert S.pick_expiry(rows) == expected


# ── TC-S5 Nifty put hedge ────────────────────────────────────────────────────────────────────────────────────────

def nifty_chain(prem=None, oi=2000):
    prem = prem or {23000: 60.0, 23200: 85.0, 23400: 120.0, 23600: 170.0, 23800: 240.0, 24000: 330.0}
    return {"summary": {"as_of": "2026-11-03", "spot": 24000.0}, "lot_size": 75,
            "strikes": [{"strike": float(k), "call": None, "put": side(p, oi=oi, vol=900)} for k, p in prem.items()]}


def test_tc_s5_fall_is_capped_at_5pct():
    h = S.build_index_hedge(dict(PLAN, stop_loss=80.0), 1.0, nifty_chain(), "2026-11-24", 21, "X")
    assert h["fall_used_pct"] == 5.0 and h["put_strike"] == 23000.0       # 20% stop distance, capped at 5%


def test_tc_s5_index_hedge_sizing():
    h = S.build_index_hedge(PLAN, 1.6, nifty_chain(), "2026-11-24", 21, "SYNGENE")
    # stop distance 8% ÷ beta 1.6 = 5% → lowest strike in [22,800, 24,000] = 23,000
    assert h["status"] == "passes" and h["put_strike"] == 23000.0 and h["fall_used_pct"] == 5.0
    assert h["premium"] == 60.0 and h["cost_per_lot"] == 4500.0
    assert h["hedged_value"] == 1125000.0 and h["cost_pct"] == pytest.approx(0.4)
    m5, m10, m15 = h["scenarios"]
    assert m5["nifty_move_pct"] == -5 and m5["put_pnl"] == (200 - 60) * 75 and m5["stock_loss"] == -90000.0
    assert m10["put_pnl"] == (1400 - 60) * 75 and m15["nifty_move_pct"] == -15
    assert "market-wide fall only" in h["caveat"]


def test_tc_s5_index_hedge_without_beta_or_liquidity():
    assert S.build_index_hedge(PLAN, None, nifty_chain(), "2026-11-24", 21, "X")["status"] == "unavailable"
    h = S.build_index_hedge(PLAN, 1.6, nifty_chain(oi=100), "2026-11-24", 21, "X")
    assert h["status"] == "fails" and h["checks"][0]["pass"] is False


# ── service: chain reads and caching ─────────────────────────────────────────────────────────────────────────────

def _ctx():
    return {"close": 100.0, "plan": {"entry_low": 98.0, "stop_loss": 92.0, "target_1": 112.0, "target_2": 118.0}, "beta": 1.6}


def test_service_options_and_index_paths_and_cache():
    asyncio.run(_service_paths())


async def _service_paths():
    calls = []

    async def expiries(request, sym):
        calls.append(("exp", sym))
        return {"as_of": "2026-11-03", "expiries": [{"expiry": "2026-11-10"}, {"expiry": "2026-11-24"}]}

    async def read(request, sym, expiry):
        calls.append(("chain", sym, expiry.isoformat()))
        return nifty_chain() if sym == "NIFTY" else chain()
    svc = S.StrategyService(expiries=expiries, chain=read, clock=lambda: 0.0)
    out = await svc.for_stock(None, "ABC", _ctx(), True, "2026-11-03")
    assert out["kind"] == "options" and out["expiry"] == "2026-11-24" and out["days_to_expiry"] == 21
    assert len(out["strategies"]) == 5 and out["index_hedge"] is None and out["lot_size"] == 100
    again = await svc.for_stock(None, "ABC", _ctx(), True, "2026-11-03")
    assert again is out and calls.count(("chain", "ABC", "2026-11-24")) == 1
    idx = await svc.for_stock(None, "XYZ", _ctx(), False, "2026-11-03")
    assert idx["kind"] == "index_hedge" and idx["strategies"] == [] and idx["index_hedge"]["put_strike"] == 23000.0


def test_service_chain_404_becomes_chain_unavailable():
    asyncio.run(_service_404())


async def _service_404():
    async def expiries(request, sym):
        raise HTTPException(status_code=404, detail=f"{sym}: no F&O data on the latest session")

    svc = S.StrategyService(expiries=expiries, chain=None, clock=lambda: 0.0)
    with pytest.raises(S.ChainUnavailable) as e:
        await svc.for_stock(None, "ABC", _ctx(), True, "2026-11-03")
    assert "no F&O data" in e.value.message


# ── TC-S6 route ──────────────────────────────────────────────────────────────────────────────────────────────────

class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, proj=None):
        return next((copy.deepcopy(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)


class _DB:
    def __init__(self): self.system_config = _Coll([{"key": "feature_flags", "flags": {}}])
    def __getitem__(self, name): return getattr(self, name)


@pytest.fixture
def client(monkeypatch):
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    import routes.market_recovery as rmr

    async def resolve(request: Request):
        return {"user_id": "u1", "email": "aporwal107@gmail.com"}
    db = _DB()
    gate = feature_gate.require_feature("market_recovery", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    app = FastAPI(); app.include_router(rmr.router)
    for route in app.routes:
        dep_ = getattr(route, "dependant", None)
        for dep in (dep_.dependencies if dep_ else []):
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    state = {"raise": None}

    class Page:
        async def get(self): return {"as_of": "2026-11-03"}
        async def stock_context(self, sym): return _ctx() if sym == "ABC" else None

    class Ref:
        fno = {"ABC"}

    class Data:
        async def reference(self): return Ref()

    class Strat:
        async def for_stock(self, request, sym, ctx, has_options, eod):
            if state["raise"]:
                raise state["raise"]
            return {"symbol": sym, "kind": "options" if has_options else "index_hedge", "as_of": eod}
    monkeypatch.setattr(rmr.service, "get_service", lambda: Page())
    monkeypatch.setattr(rmr.strategies, "get_service", lambda: Strat())
    monkeypatch.setattr(rmr, "get_data", lambda: Data())
    yield TestClient(app), state
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def test_tc_s6_route(client):
    c, state = client
    r = c.get("/api/market-recovery/strategies/abc")
    assert r.status_code == 200 and r.json() == {"symbol": "ABC", "kind": "options", "as_of": "2026-11-03"}
    r = c.get("/api/market-recovery/strategies/NOPE")
    assert r.status_code == 404 and r.json()["code"] == "not_scored"
    state["raise"] = S.ChainUnavailable("ABC: no current chain")
    r = c.get("/api/market-recovery/strategies/ABC")
    assert r.status_code == 503 and r.json()["code"] == "chain_unavailable" and r.json()["message"] == "ABC: no current chain"
    assert c.get("/api/market-recovery/strategies/a;b").status_code == 422


# ── wording: Buy / Sell only as leg actions; the plan words; nothing else ────────────────────────────────────────

def test_wording_lint_strategies():
    import re
    from tests.test_compliance_wording_lint import hits
    plan_words = re.compile(r"\b(?:entry zone|stop loss|target 1|target 2)\b", re.I)
    payload = {"strategies": S.build_options(PLAN, chain()), "index": S.build_index_hedge(PLAN, 1.6, nifty_chain(), "2026-11-24", 21, "X"),
               "labels": S.LABEL, "best": S.BEST_WHEN, "notes": S.NOTES}

    def strings(x, key=None):
        if isinstance(x, str):
            if key != "action":                                       # the owner's Buy / Sell, legs only
                yield x
        elif isinstance(x, dict):
            for k, v in x.items():
                yield from strings(v, k)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v, key)
    bad = [(s, hits(plan_words.sub(" ", s))) for s in strings(payload)]
    assert [b for b in bad if b[1]] == []
