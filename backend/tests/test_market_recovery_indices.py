"""Market Recovery › Nifty and Bank Nifty by expiry: TC-I1 … TC-I7 of docs/market_recovery/DESIGN.md §9.

Hand-made series and a hand-made chain (MOCK — not real data): spot 1,000, strikes 900–1,100 every 20, lot 50; option prices =
intrinsic value + 20·exp(−|K − 1,000| / 60), so the ATM straddle is 40 and its range 960–1,040."""
import copy
import math

import numpy as np
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from services.market_recovery import indices as I
from services.scan_builder import indicators as ind
from services.scan_builder.data import DataUnavailable


# ── TC-I1 technicals, pivots, streak ─────────────────────────────────────────────────────────────────────────────

def test_tc_i1_technicals_match_the_indicator_library():
    rng = np.random.default_rng(3)
    c = list(1000 * np.exp(np.cumsum(0.001 + 0.01 * rng.standard_normal(400))))
    h = [x * 1.005 for x in c]
    l = [x * 0.995 for x in c]
    t = I.technicals(c, h, l)
    col = lambda a: float(a[-1, 0])                                        # noqa: E731
    C, H, L = (np.array(v).reshape(-1, 1) for v in (c, h, l))
    assert t["ema200"] == round(col(ind.ema(C, 200)), 2) and t["rsi14"] == round(col(ind.rsi(C, 14)), 2)
    assert t["atr14"] == round(col(ind.atr(H, L, C, 14)), 2) and t["sessions"] == 400
    assert t["high20"] == round(max(h[-20:]), 2) and t["low52"] == round(min(l[-252:]), 2)
    assert t["vs_ema200_pct"] == pytest.approx(round(100 * (c[-1] / col(ind.ema(C, 200)) - 1), 2), abs=0.011)


def test_tc_i1_pivots_and_streak():
    p = I.pivots(110.0, 90.0, 100.0)
    assert p == {"p": 100.0, "r1": 110.0, "r2": 120.0, "r3": 130.0, "s1": 90.0, "s2": 80.0, "s3": 70.0}
    assert I.up_streak([1, 2, 3, 2, 3, 4, 5]) == 3 and I.up_streak([5, 4, 3, 2]) == -3 and I.up_streak([1, 1]) == 0


# ── TC-I2 futures build-up ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("p,o,label", [(1.0, 5, "long_buildup"), (1.0, -5, "short_covering"), (-1.0, 5, "short_buildup"),
                                       (-1.0, -5, "long_unwinding"), (0.0, 5, None), (None, 5, None)])
def test_tc_i2_buildup(p, o, label):
    assert I.buildup(p, o) == label


# ── TC-I3 expiry kinds and liquidity ─────────────────────────────────────────────────────────────────────────────

def test_tc_i3_kinds_and_liquidity():
    k = I.expiry_kinds(["2026-11-09", "2026-11-17", "2026-11-23", "2026-12-01", "2026-12-29"])
    assert k == {"2026-11-09": "weekly", "2026-11-17": "weekly", "2026-11-23": "monthly", "2026-12-01": "weekly",
                 "2026-12-29": "monthly"}
    assert I.expiry_kinds(["2026-11-23", "2026-12-29"], monthly_only=True) == {"2026-11-23": "monthly", "2026-12-29": "monthly"}
    # 3 Nov shapes: 9 Nov busiest; 23 Nov 20% of its volume; 17 Nov 5%; 1 Dec 0.2% volume and 0.7% OI
    assert I.liquidity(127, 1866, 127, 1866) == "active" and I.liquidity(25.4, 1165, 127, 1866) == "active"
    assert I.liquidity(6.6, 166, 127, 1866) == "thin" and I.liquidity(0.3, 13.8, 127, 1866) == "too_thin"
    assert I.liquidity(0.3, 665, 127, 1866) == "thin"                      # little volume but large OI: still read


# ── the hand-made chain ──────────────────────────────────────────────────────────────────────────────────────────

def tv(k):
    return 20 * math.exp(-abs(k - 1000) / 60)


def call(k):
    return round(max(1000 - k, 0) + tv(k), 2)


def put(k):
    return round(max(k - 1000, 0) + tv(k), 2)


CALL_OI = {1020: 100_000, 1040: 300_000, 1060: 900_000, 1080: 400_000}
PUT_OI = {960: 800_000, 980: 200_000, 940: 300_000}
CALL_ADD = {1060: 120_000, 1100: 90_000, 1020: -40_000}
PUT_ADD = {980: 150_000, 960: 70_000, 900: -20_000}


def chain(as_of="2026-11-03", lot=50, vol=500, untraded=()):
    rows = []
    for k in range(900, 1101, 20):
        side = lambda price, oi, add, t: {"close": None if (k, t) in untraded else price, "settle": price, "oi": oi,  # noqa: E731
                                          "change_in_oi": add, "volume": 0 if (k, t) in untraded else vol, "iv": 0.2, "delta": 0.5}
        rows.append({"strike": float(k), "call": side(call(k), CALL_OI.get(k, 50_000), CALL_ADD.get(k, 0), "c"),
                     "put": side(put(k), PUT_OI.get(k, 50_000), PUT_ADD.get(k, 0), "p")})
    return {"summary": {"as_of": as_of, "spot": 1000.0, "atm_strike": 1000.0, "pcr": 1.2, "max_pain": 980.0,
                        "call_wall": {"strike": 1060.0, "oi": 900000},
                        "put_wall": {"strike": 960.0, "oi": 800000},     # the shape routes/fno summarise_chain sends
                        "total_call_oi": 2_000_000, "total_put_oi": 2_400_000},
            "lot_size": lot, "strikes": rows}


# ── TC-I4 one expiry ─────────────────────────────────────────────────────────────────────────────────────────────

def test_tc_i4_expiry_view():
    e = I.expiry_view(chain(), "2026-11-09", 6, "weekly", "active", 11000)
    assert e["straddle"] == 40.0 and e["range_lo"] == 960 and e["range_hi"] == 1040 and e["move_pct"] == 4.0
    assert e["call_oi_top"][0] == {"strike": 1060.0, "oi": 900000} and e["put_oi_top"][0] == {"strike": 960.0, "oi": 800000}
    assert [a["strike"] for a in e["call_adds"]] == [1060.0, 1100.0] and e["call_cuts"] == [{"strike": 1020.0, "change": -40000}]
    assert [a["strike"] for a in e["put_adds"]] == [980.0, 960.0] and e["put_cuts"] == [{"strike": 900.0, "change": -20000}]
    assert e["read"].startswith("Weekly 9 Nov: the ATM straddle prices 960–1,040 (±4.00%) by expiry; heaviest calls at 1,060")
    thin = I.expiry_view(chain(), "2026-11-17", 14, "weekly", "thin", 500)
    assert thin["read"].endswith("Thin series: use limit orders.")
    assert "too little open interest" in I.expiry_view(chain(), "2026-12-01", 28, "weekly", "too_thin", 1)["read"]


# ── TC-I5 setups ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_tc_i5_setups_by_rule_and_figures():
    ch = chain()
    e = I.expiry_view(ch, "2026-11-09", 6, "weekly", "active", 11000)
    s = {x["key"]: x for x in I.build_setups(e, ch, 1000.0)}
    assert list(s) == ["bull_call_spread", "bear_put_spread", "iron_condor", "hedge_put_spread"]
    bc = s["bull_call_spread"]                                   # Buy 1000 C, Sell the heaviest call in (1000, 1040] = 1040
    assert [(l["action"], l["instrument"], l["strike"]) for l in bc["legs"]] == [("Buy", "Call", 1000.0), ("Sell", "Call", 1040.0)]
    debit = call(1000) - call(1040)
    assert bc["net_premium"] == pytest.approx(-debit * 50, abs=0.01) and bc["max_gain"] == pytest.approx((40 - debit) * 50, abs=0.01)
    assert bc["reward_risk"] == pytest.approx((40 - debit) / debit, abs=0.01) and bc["breakevens"] == [pytest.approx(1000 + debit, abs=0.01)]
    assert bc["when"] == "If it rises toward 1,040" and bc["status"] == "passes"
    bp = s["bear_put_spread"]                                    # Buy 1000 P, Sell the heaviest put in [960, 1000) = 960
    assert [l["strike"] for l in bp["legs"]] == [1000.0, 960.0] and bp["when"] == "If it breaks below 960"
    ic = s["iron_condor"]                                        # walls 1060 / 960, wings ~1% (10) out → 1080 / 940
    assert [l["strike"] for l in ic["legs"]] == [960.0, 940.0, 1060.0, 1080.0]
    credit = put(960) - put(940) + call(1060) - call(1080)
    assert ic["net_premium"] == pytest.approx(credit * 50, abs=0.01)
    assert {c["id"]: c["pass"] for c in ic["checks"]}["credit"] is (credit >= 20 / 3)
    hp = s["hedge_put_spread"]                                   # Buy the put nearest 990 (980), Sell the put nearest 960
    assert [l["strike"] for l in hp["legs"]] == [980.0, 960.0] and hp["reward_risk"] is None


def test_tc_i5_wing_skips_untraded_strikes():
    ch = chain(untraded={(1080, "c")})                           # the 1%-out wing would be 1080: untraded → next liquid, 1100
    e = I.expiry_view(ch, "2026-11-09", 6, "weekly", "active", 11000)
    ic = next(x for x in I.build_setups(e, ch, 1000.0) if x["key"] == "iron_condor")
    assert [l["strike"] for l in ic["legs"]][3] == 1100.0


def test_tc_i5_checks_and_too_thin():
    ch = chain(untraded={(1040, "c")})
    e = I.expiry_view(ch, "2026-11-09", 6, "weekly", "active", 11000)
    bc = next(x for x in I.build_setups(e, ch, 1000.0) if x["key"] == "bull_call_spread")
    assert bc["status"] == "fails" and "Call 1,040: missing premium, no trades today" in bc["why"]   # no traded close: blocked
    thin = I.expiry_view(chain(), "2026-11-17", 14, "weekly", "thin", 500)
    assert all(any(c["id"] == "thin" for c in x["checks"]) for x in I.build_setups(thin, chain(), 1000.0))
    too = I.expiry_view(chain(), "2026-12-01", 28, "weekly", "too_thin", 1)
    assert I.build_setups(too, chain(), 1000.0) == []


# ── TC-I6 levels and together ────────────────────────────────────────────────────────────────────────────────────

def test_tc_i6_levels_sorted_merged_capped():
    tech = {"ema20": 990.0, "ema50": 1005.0, "ema200": 1030.0, "high20": 1040.0, "low20": 900.0}
    piv = {"p": 995.0, "r1": 1010.0, "r2": 1030.2, "s1": 980.0, "s2": 960.0}
    e = I.expiry_view(chain(), "2026-11-09", 6, "weekly", "active", 11000)
    lv = I.levels(1000.0, tech, piv, [e])
    assert [x["level"] for x in lv["above"]] == sorted(x["level"] for x in lv["above"]) and len(lv["above"]) <= 5
    assert [x["level"] for x in lv["below"]] == sorted((x["level"] for x in lv["below"]), reverse=True)
    merged = next(x for x in lv["above"] if x["level"] == 1030.0)
    assert "200-day average (EMA)" in merged["label"] and "pivot R2" in merged["label"]           # within 0.05%: one row
    assert lv["below"][0]["level"] == 995.0


def test_tc_i6_together():
    a = I.expiry_view(chain(), "2026-11-09", 6, "weekly", "active", 11000)
    b = I.expiry_view(chain(), "2026-11-23", 20, "monthly", "active", 9000)
    t = I.together([a, b], 1000.0)
    assert t[0].startswith("Common floor: 980 — put writers added there in 2 of 2 series")
    assert t[1] == "Near ceiling: 1,060, the heaviest call strike of the weekly 9 Nov."
    assert t[2] == "The 23 Nov monthly's max pain is 980, below the close."


# ── TC-I7 route and wording ──────────────────────────────────────────────────────────────────────────────────────

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

    class Svc:
        async def get(self, request):
            if state["raise"]:
                raise state["raise"]
            return {"as_of": "2026-11-03", "indices": []}
    monkeypatch.setattr(rmr.indices, "get_service", lambda: Svc())
    yield TestClient(app), state
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def test_tc_i7_route(client):
    c, state = client
    r = c.get("/api/market-recovery/indices")
    assert r.status_code == 200 and r.json() == {"as_of": "2026-11-03", "indices": []}
    state["raise"] = DataUnavailable("index closes down")
    r = c.get("/api/market-recovery/indices")
    assert r.status_code == 503 and r.json()["code"] == "data_unavailable"


def test_tc_i7_wording():
    import re
    from tests.test_compliance_wording_lint import hits
    ch = chain()
    exps = [I.expiry_view(ch, "2026-11-09", 6, "weekly", "active", 11000), I.expiry_view(ch, "2026-11-17", 14, "weekly", "thin", 500),
            I.expiry_view(ch, "2026-12-01", 28, "weekly", "too_thin", 1)]
    fut = [{"expiry": "2026-11-23", "buildup": "short_covering", "change_pct": 1.6, "oi_change_pct": -8.6}]
    tech = I.technicals([1000.0 + i for i in range(300)], [1001.0 + i for i in range(300)], [999.0 + i for i in range(300)])
    payload = {"exps": exps, "setups": [s for e in exps for s in I.build_setups(e, ch, 1000.0)],
               "read": I.index_read("Nifty 50", 1000.0, 1.5, 4, tech, fut), "together": I.together(exps, 1000.0),
               "levels": I.levels(1000.0, tech, I.pivots(1010, 990, 1000), exps), "notes": I.NOTES, "labels": I.LABEL}

    def strings(x, key=None):
        if isinstance(x, str):
            if key != "action":
                yield x
        elif isinstance(x, dict):
            for k, v in x.items():
                yield from strings(v, k)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v, key)
    bad = [(s, hits(s)) for s in strings(payload)]
    assert [b for b in bad if b[1]] == []
