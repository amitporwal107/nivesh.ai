"""Market Recovery (recovery-radar-v1): TC-U1 … TC-U10 and TC-R1 of docs/market_recovery/DESIGN.md.

Pure rule tests on hand-made scalars and small hand-made panels; every price below is invented (MOCK — not real data).
The real router and flag gate run in TC-R1, with the user resolver, flag store and service injected."""
import copy
from datetime import date, timedelta

import numpy as np
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from services.market_recovery import engine as E
from services.scan_builder.data import DataUnavailable


# ── TC-U1 recovery check status ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw,expected", [
    (dict(above_20dma=True, sma_rising=True, breadth_expanding=False, above20=64.0, above50=55.0), "confirmed"),
    (dict(above_20dma=True, sma_rising=False, breadth_expanding=True, above20=58.0, above50=40.0), "underway"),
    (dict(above_20dma=False, sma_rising=False, breadth_expanding=True, above20=45.0, above50=30.0), "early"),
    (dict(above_20dma=True, sma_rising=True, breadth_expanding=False, above20=42.0, above50=35.0), "fragile"),
    (dict(above_20dma=False, sma_rising=False, breadth_expanding=False, above20=30.0, above50=30.0), "none"),
    (dict(above_20dma=None, sma_rising=None, breadth_expanding=None, above20=None, above50=None), "none"),
])
def test_tc_u1_regime_status_paths(kw, expected):
    assert E.regime_status(**kw) == expected


# ── helpers: a hand-made panel ────────────────────────────────────────────────────────────────────────────────────

def _days(n, end=date(2026, 11, 3)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def _panel(closes, vol=None):
    c = np.array(closes, dtype=float)
    h, l = c * 1.01, c * 0.99
    v = np.full(c.shape, 1e6) if vol is None else np.array(vol, dtype=float)
    return c, h, l, v


# ── TC-U2 breadth on a small panel equals a hand count ────────────────────────────────────────────────────────────

def test_tc_u2_breadth_hand_count():
    t = 60
    up = np.linspace(100, 160, t)          # above its SMA20 and SMA50, rose on the day
    down = np.linspace(160, 100, t)        # below both, fell on the day
    flat_then_jump = np.r_[np.full(t - 1, 100.0), 103.0]   # above both (jump), rose
    dip = np.r_[np.linspace(100, 130, t - 1), 110.0]       # below SMA20 (fell hard), above SMA50? check by hand below
    c, h, l, v = _panel(np.c_[up, down, flat_then_jump, dip])
    a = E.indicator_arrays(c, h, l, v)
    b = E.breadth_at(a, -1)
    sma20_dip = np.mean(c[-20:, 3])
    sma50_dip = np.mean(c[-50:, 3])
    exp20 = 100.0 * sum([True, False, True, 110.0 > sma20_dip]) / 4
    exp50 = 100.0 * sum([True, False, True, 110.0 > sma50_dip]) / 4
    assert b["above20_pct"] == pytest.approx(exp20)
    assert b["above50_pct"] == pytest.approx(exp50)
    assert b["advancers_pct"] == pytest.approx(50.0)       # up and the jump rose; down and the dip fell
    assert b["counted"] == 4


# ── TC-U3 sectors ─────────────────────────────────────────────────────────────────────────────────────────────────

def _member(sector, r20, r20_then, a20, a50, r5=1.0, r10=2.0, deliv_up=True):
    return {"sector": sector, "r5": r5, "r10": r10, "r20": r20, "r20_then": r20_then, "above20": a20, "above50": a50,
            "deliv_up": deliv_up}


def test_tc_u3_sector_rs_state_and_rank():
    stocks = {}
    for i, r in enumerate([5, 6, 7, 8, 9]):                        # median 7, then median 2: RS rising, all above
        stocks[f"CG{i}"] = _member("Capital Goods", r, 2.0, True, True)
    for i, r in enumerate([-6, -5, -4, -3, -2]):                   # median -4, then -1: falling, mostly below
        stocks[f"IT{i}"] = _member("Information Technology", r, -1.0, i == 4, False, deliv_up=False)
    for i in range(3):                                              # too few members: left out
        stocks[f"TX{i}"] = _member("Textiles", 1.0, 1.0, True, True)
    rows = E.sector_table(stocks, {"r5": 0.5, "r10": 1.0, "r20": 2.0, "r20_then": 1.0})
    by = {r["sector"]: r for r in rows}
    assert set(by) == {"Capital Goods", "Information Technology"}
    cg, it = by["Capital Goods"], by["Information Technology"]
    assert cg["ret_20d"] == 7.0 and cg["rs_20d"] == 5.0 and cg["rs_20d_5ago"] == 1.0 and cg["rs_change"] == 4.0
    assert cg["above20_pct"] == 100.0 and cg["state"] == "leadership" and cg["delivery_up_pct"] == 100.0
    assert it["rs_20d"] == -6.0 and it["above20_pct"] == 20.0 and it["state"] == "weak"
    assert it["state_label"] == "Weak — avoid for now"
    assert cg["rank"] == 1 and it["rank"] == 2 and cg["leader"] and it["leader"]       # top 5 = both


@pytest.mark.parametrize("args,state", [
    ((2.0, 1.0, 70.0, 65.0), "leadership"),
    ((-1.0, 1.0, 65.0, 40.0), "recovery"),
    ((-1.0, 1.0, 50.0, 40.0), "emerging"),
    ((-3.0, -1.0, 30.0, 20.0), "weak"),
    ((1.0, -1.0, 50.0, 50.0), "neutral"),
])
def test_tc_u3_sector_state(args, state):
    assert E.sector_state(*args) == state


# ── TC-U4 score ───────────────────────────────────────────────────────────────────────────────────────────────────

def _strong():
    return {"rs": 12.0, "rs_sector": 9.0, "close": 110.0, "ema20": 105.0, "ema50": 100.0, "ema20_then": 101.0,
            "ema50_then": 99.0, "rsi": 62.0, "higher_low": True, "vol_ratio": 1.8, "vol_base50": 1e6, "vol_avg250": 1e6,
            "ud10": 1.7, "deliv_ratio": 1.25, "deliv_5d": 55.0, "deliv_20d": 44.0, "upvol5": 3.0}


FULL_F = {"roce_pct": 25.0, "debt_to_equity": 0.2, "pat_growth_yoy_pct": 20.0, "cfo_pat_ratio": 1.1,
          "fii_pct_change_qoq": 1.5, "accumulation_score": 100.0}


def test_tc_u4_full_marks_and_components():
    res = E.score_stock(_strong(), FULL_F, {"financial": False})
    keys = [c["key"] for c in res["components"]]
    assert keys == ["relative_strength", "technical", "volume_delivery", "fundamental", "smart_money"]
    assert [c["max"] for c in res["components"]] == [25, 25, 20, 20, 10]
    assert res["score"] == 100.0 and res["gaps"] == [] and not res["low_base"]
    assert sum(c["points"] for c in res["components"]) == pytest.approx(res["score"])


def test_tc_u4_partial_points_follow_the_ramps():
    s = _strong() | {"rs": 5.0, "rsi": 47.0, "vol_ratio": 1.25}
    res = E.score_stock(s, FULL_F, {"financial": False})
    rs = res["components"][0]
    assert rs["parts"][0]["points"] == pytest.approx(6.25)          # 12.5 × 5/10
    tech = res["components"][1]
    assert tech["parts"][3]["points"] == 2.5                         # RSI 45–50
    vol = res["components"][2]
    assert vol["parts"][0]["points"] == pytest.approx(3.5)           # 7 × (1.25−1)/0.5


def test_tc_u4_missing_cash_flow_rescales_fundamentals():
    f = dict(FULL_F); f.pop("cfo_pat_ratio")
    res = E.score_stock(_strong(), f, {"financial": False})
    fund = res["components"][3]
    assert fund["rescaled"] and fund["points"] == pytest.approx(20.0)
    assert "Cash flow (CFO / PAT) not available" in res["gaps"]


def test_tc_u4_too_little_fundamental_data_scores_zero():
    res = E.score_stock(_strong(), {"roce_pct": 25.0}, {"financial": False})
    fund = res["components"][3]
    assert fund["points"] == 0.0 and not fund["rescaled"]           # 5 of 20 measurable: under half


def test_tc_u4_financials_profile():
    f = {"roe_pct": 16.0, "pat_growth_yoy_pct": 7.5, "debt_to_equity": 8.0}   # a bank's D/E must not count
    res = E.score_stock(_strong(), f | {"fii_pct_change_qoq": 1.0, "accumulation_score": 100}, {"financial": True})
    fund = res["components"][3]
    assert [p["label"] for p in fund["parts"]] == ["ROE (financials)", "Profit growth, year on year"]
    assert fund["points"] == pytest.approx(15.0)                    # 10 + 10 × 7.5/15


# ── TC-U5 traps and low-base volume ───────────────────────────────────────────────────────────────────────────────

def test_tc_u5_dead_cat():
    s = {"close": 90.0, "sma50": 100.0, "sma50_10ago": 104.0, "sma200": 120.0, "r5": 6.5, "ema20": 88.0}
    t = E.find_trap(s, None)
    assert t["trap"] == "dead_cat" and t["reason"].startswith("Up 6.5% in 5 sessions but below a falling 50-day")


def test_tc_u5_not_dead_cat_when_50dma_rising():
    s = {"close": 90.0, "sma50": 100.0, "sma50_10ago": 98.0, "sma200": 120.0, "r5": 6.5, "ema20": 88.0}
    assert E.find_trap(s, None) is None


@pytest.mark.parametrize("fno,hit", [
    ({"price_chg": 2.0, "oi_chg": -4.0}, True),
    ({"price_chg": 0.6, "oi_chg": -1.0, "prev_price_chg": 0.4, "prev_oi_chg": -1.2}, True),
    ({"price_chg": 0.4, "oi_chg": -0.1, "prev_price_chg": 0.4, "prev_oi_chg": -2.0}, False),   # OI noise (LT, 3 Nov)
    ({"price_chg": 2.0, "oi_chg": 3.0, "prev_price_chg": 1.0, "prev_oi_chg": 2.0}, False),   # long build-up
    ({"price_chg": 0.6, "oi_chg": -1.0, "prev_price_chg": -0.4, "prev_oi_chg": -0.5}, False),
])
def test_tc_u5_short_covering(fno, hit):
    s = {"close": 100.0, "ema20": 98.0}
    t = E.find_trap(s, fno)
    assert (t is not None and t["trap"] == "short_covering") is hit


def test_tc_u5_extended():
    t = E.find_trap({"close": 112.0, "ema20": 100.0}, None)
    assert t["trap"] == "extended" and "12.0% above" in t["reason"]


def test_tc_u5_low_base_volume_zeroes_the_ratio_part():
    s = _strong() | {"vol_base50": 4e5, "vol_avg250": 1e6, "vol_ratio": 3.0}
    res = E.score_stock(s, FULL_F, {"financial": False})
    assert res["low_base"] and res["components"][2]["parts"][0]["points"] == 0.0
    assert any(c.startswith("Low-base volume") for c in res["cautions"])


# ── TC-U6 setups ──────────────────────────────────────────────────────────────────────────────────────────────────

BASE = {"close": 105.0, "rsi": 58.0, "ema20": 101.0, "volume": 2e6, "vol_avg20_prev": 1e6, "high20_prev": 104.0,
        "closes_prev5": [101, 102, 103, 103, 104], "ema20_prev5": [99, 99, 99, 99, 99], "sma50": 98.0, "higher_low": True,
        "rs_change": 1.0, "ud10": 1.3, "high20": 106.0, "low20": 97.0, "deliv_ratio": 1.1}


@pytest.mark.parametrize("change,key", [
    ({}, "breakout"),
    ({"volume": 1.2e6, "closes_prev5": [98, 102, 103, 103, 104]}, "ema_reclaim"),
    ({"volume": 1.2e6}, "pullback"),
    ({"volume": 1.2e6, "rs_change": -1.0}, "accumulation"),
    ({"volume": 1.2e6, "rs_change": -1.0, "deliv_ratio": 0.9}, "relative_strength"),
])
def test_tc_u6_setup_first_match(change, key):
    assert E.classify_setup(BASE | change)["key"] == key


# ── TC-U7 plan ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("low10,h60,t1_is_h60", [
    (95.0, 112.0, True),      # stop 95 − 0.5 = 94.5 → R 5.5 (2.75 ATR); 60-session high 112 lies within 1–3R
    (99.5, 150.0, False),     # stop capped at 1 ATR (R 2); 150 is beyond 3R → T1 = 2R
    (80.0, 101.0, False),     # stop capped at 3 ATR (R 6); 101 below 1R → T1 = 2R
])
def test_tc_u7_plan_rules(low10, h60, t1_is_h60):
    s = {"close": 100.0, "atr": 2.0, "ema20": 98.0, "low10": low10, "high60": h60}
    p = E.trade_plan(s)
    risk = 100.0 - p["stop_loss"]
    assert 2.0 - 1e-9 <= risk <= 6.0 + 1e-9                        # 1–3 ATR
    assert p["entry_low"] <= p["entry_high"] == 100.0 and p["entry_low"] == 99.0   # max(EMA20 98, 100 − 1)
    assert (p["target_1"] == h60) is t1_is_h60
    if not t1_is_h60:
        assert p["target_1"] == pytest.approx(100.0 + 2 * risk)
    assert p["target_2"] >= p["target_1"] + risk - 1e-6 and p["target_2"] >= 100.0 + 3 * risk - 1e-6
    assert p["rr_1"] == pytest.approx((p["target_1"] - 100.0) / risk, abs=0.01)


def test_tc_u7_no_plan_without_atr():
    assert E.trade_plan({"close": 100.0, "atr": None, "low10": 95.0}) is None


# ── TC-U8 / TC-U9 / TC-U10: the whole computation on a hand-made market ──────────────────────────────────────────

def _market(n_days=300):
    days = _days(n_days)
    rng = np.random.default_rng(7)
    syms, cols, vols, industry, feats = [], [], [], {}, {}
    sectors = ["Capital Goods", "Financial Services", "Information Technology"]
    for k, sec in enumerate(sectors):
        for i in range(6):
            sym = f"{sec[:2].upper()}{i}"
            drift = (0.002 if k == 0 else 0.0005 if k == 1 else -0.001) + 0.0002 * i
            path = 100 * np.exp(np.cumsum(drift + 0.01 * rng.standard_normal(n_days)))
            syms.append(sym); cols.append(path); vols.append(np.full(n_days, 2e6) * (1 + 0.5 * (i == 0)))
            industry[sym] = sec
            feats[sym] = {"as_of_date": days[-1].isoformat(), "market_cap_cr": 50000.0, "roce_pct": 18.0, "roe_pct": 15.0,
                          "debt_to_equity": 0.3, "pat_growth_yoy_pct": 10.0, "cfo_pat_ratio": 0.9, "fii_pct_change_qoq": 0.2,
                          "accumulation_score": 40.0, "deliv_pct_avg_20": 40.0, "deliv_trend10": 0.1}
    # gates: tiny traded value, small cap, no bar today, short history
    syms += ["TINY", "SMALLCAP", "NOBAR", "NEWLIST"]
    cols += [np.full(n_days, 10.0), np.linspace(50, 60, n_days), np.r_[np.linspace(50, 60, n_days - 1), np.nan],
             np.r_[np.full(n_days - 30, np.nan), np.linspace(50, 60, 30)]]
    vols += [np.full(n_days, 1000.0), np.full(n_days, 5e6), np.full(n_days, 5e6), np.full(n_days, 5e6)]
    for s in ("TINY", "SMALLCAP", "NOBAR", "NEWLIST"):
        industry[s] = "Textiles"
        feats[s] = {"market_cap_cr": 500.0 if s == "SMALLCAP" else 5000.0}
    c = np.c_[tuple(cols)]
    v = np.c_[tuple(vols)]
    n50 = [(d, 20000 * (1 + 0.0008) ** i) for i, d in enumerate(days)]
    n500 = [(d, 18000 * (1 + 0.0006) ** i) for i, d in enumerate(days)]
    vix = [(d, 15 - 0.01 * i) for i, d in enumerate(days)]
    return E.Inputs(
        as_of=days[-1], dates=np.array(days, dtype="datetime64[D]"), symbols=syms, close=c, high=c * 1.01, low=c * 0.99,
        volume=v, industry=industry, names={s: f"{s} Ltd" for s in syms},
        caps={"large": set(syms[:6]), "mid": set(syms[6:12]), "small": set(syms[12:18])},
        nifty50=n50, nifty500=n500, vix=vix, features_now=feats, features_then={s: {"deliv_trend10": 0.0} for s in syms},
        delivery={s: [44.0, 45.0, 46.0, 47.0, 48.0] for s in syms}, members_total=len(syms), members_as_of="2026-11-01")


def test_tc_u8_u9_whole_page_shape_gates_and_acceleration():
    out = E.compute(_market(), today=date(2026, 11, 3), computed_at="2026-11-03T16:00:00Z")
    assert out["method"] == "recovery-radar-v1" and out["as_of"] == "2026-11-03"
    assert out["universe"]["left_out"] == {"no_bar": 1, "history": 1, "liquidity": 1, "market_cap": 1}
    assert out["universe"]["scored"] == 18
    reg = out["regime"]
    assert len(reg["checks"]) == 5 and reg["status"] in E.REGIME_LABEL and reg["label"] == E.REGIME_LABEL[reg["status"]]
    assert reg["vix"]["change_pct"] < 0 and [c for c in reg["checks"] if c["id"] == "vix_falling"][0]["pass"] is True
    assert [c["key"] for c in reg["caps"]] == ["large", "mid", "small"]
    assert len(out["breadth_series"]) == 30 and out["breadth_series"][-1]["date"] == "2026-11-03"
    assert {r["sector"] for r in out["sectors"]} == {"Capital Goods", "Financial Services", "Information Technology"}
    assert len(out["leaders"]) == 3                                     # every sector with ≥ 5 members (top 5 of 3)
    assert 0 < len(out["candidates"]) <= 10 and out["others"] == []
    for card in out["candidates"] + out["others"]:
        assert [c["key"] for c in card["components"]] == ["relative_strength", "technical", "volume_delivery",
                                                         "fundamental", "smart_money"]
        assert 0 <= card["score"] <= 100 and card["meets_priority"] == (card["score"] >= 75)
        acc = card["acceleration"]
        assert acc["score"] is None or 0 <= acc["score"] <= 100
        assert 0 <= acc["improving"] <= acc["of"] <= 6 and len(acc["rows"]) == 6
        assert card["setup"]["key"] in E.SETUP_LABEL
        assert card["plan"] is None or card["plan"]["stop_loss"] < card["close"] < card["plan"]["target_1"]
    scores = [c["score"] for c in out["candidates"]]
    assert scores == sorted(scores, reverse=True)
    trapped = {e["symbol"] for e in out["excluded"]}
    assert not trapped & {c["symbol"] for c in out["candidates"]}


def test_tc_u8_pct_ranks():
    r = E.pct_ranks({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0, "e": None})
    assert r == {"a": 0.0, "b": pytest.approx(0.5), "c": pytest.approx(0.5), "d": 1.0}


def test_tc_u10_stale_prices_refused():
    with pytest.raises(E.StaleData):
        E.compute(_market(), today=date(2026, 11, 9))


# ── TC-R1 route: flag, typed errors, 200 ──────────────────────────────────────────────────────────────────────────

class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, proj=None):
        return next((copy.deepcopy(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)


class _DB:
    def __init__(self):
        self.system_config = _Coll([{"key": "feature_flags", "flags": {}}])
    def __getitem__(self, name): return getattr(self, name)


USERS = {"owner": {"user_id": "u1", "email": "aporwal107@gmail.com"}, "other": {"user_id": "u2", "email": "other@example.com"}}


@pytest.fixture
def client(monkeypatch):
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    import routes.market_recovery as rmr

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])

    db = _DB()
    gate = feature_gate.require_feature("market_recovery", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    app = FastAPI(); app.include_router(rmr.router)
    for route in app.routes:
        dep_ = getattr(route, "dependant", None)
        for dep in (dep_.dependencies if dep_ else []):
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    state = {"raise": None}

    class Stub:
        async def get(self):
            if state["raise"]:
                raise state["raise"]
            return {"method": "recovery-radar-v1", "as_of": "2026-11-03"}
    monkeypatch.setattr(rmr.service, "get_service", lambda: Stub())
    yield TestClient(app), state
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def test_tc_r1_flag_defaults_to_the_owner(client):
    c, _ = client
    meta = ff.KNOWN_FEATURES["market_recovery"]
    assert meta["default_mode"] == "allowlist" and meta["default_allowlist"] == ["aporwal107@gmail.com"]
    assert c.get("/api/market-recovery", headers={"X-Test-User": "other"}).status_code == 403
    r = c.get("/api/market-recovery", headers={"X-Test-User": "owner"})
    assert r.status_code == 200 and r.json()["as_of"] == "2026-11-03"


@pytest.mark.parametrize("exc,code", [(DataUnavailable("DaaS down"), "data_unavailable"), (E.StaleData("old"), "stale_data")])
def test_tc_r1_typed_503(client, exc, code):
    c, state = client
    state["raise"] = exc
    r = c.get("/api/market-recovery", headers={"X-Test-User": "owner"})
    body = r.json()
    assert r.status_code == 503 and body["code"] == code and body["detail"]["code"] == code and body["message"]


# ── wording: every string the API returns passes the 3 Nov lint, except the owner's plan words (this page only) ──────

PLAN_WORDS = __import__("re").compile(r"\b(?:entry zone|stop loss|target 1|target 2)\b", __import__("re").I)


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def test_wording_lint_outside_the_owner_plan_words():
    from tests.test_compliance_wording_lint import hits
    out = E.compute(_market(), today=date(2026, 11, 3))
    trap_reasons = [E.find_trap({"close": 90.0, "sma50": 100.0, "sma50_10ago": 104.0, "sma200": 120.0, "r5": 6.5}, None),
                    E.find_trap({"close": 100.0, "ema20": 98.0}, {"price_chg": 2.0, "oi_chg": -4.0}),
                    E.find_trap({"close": 100.0, "ema20": 98.0}, {"price_chg": 0.6, "oi_chg": -1.2, "prev_price_chg": 0.4,
                                                                   "prev_oi_chg": -1.5}),
                    E.find_trap({"close": 112.0, "ema20": 100.0}, None)]
    setups = [E.classify_setup(BASE | c) for c, _ in [({}, 0), ({"volume": 1.2e6, "closes_prev5": [98, 102, 103, 103, 104]}, 0),
                                                       ({"volume": 1.2e6}, 0), ({"volume": 1.2e6, "rs_change": -1.0}, 0),
                                                       ({"volume": 1.2e6, "rs_change": -1.0, "deliv_ratio": 0.9}, 0)]]
    low_base = E.score_stock(_strong() | {"vol_base50": 4e5, "vol_avg250": 1e6, "vol_ratio": 3.0}, FULL_F, {"financial": False})
    bad = [(s, hits(PLAN_WORDS.sub(" ", s))) for s in _strings([out, trap_reasons, setups, low_base, E.NOTES, E.REGIME_LABEL,
                                                                 E.SECTOR_LABEL, E.SETUP_LABEL, E.TRAP_LABEL])]
    assert [b for b in bad if b[1]] == []
