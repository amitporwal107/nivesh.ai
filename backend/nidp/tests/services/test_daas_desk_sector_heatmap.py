"""DaaS /v1/desk/sector-heatmap (nidp/services/daas_api/routers/desk_market.py).

Expected values are worked out here by hand from the fixture, with their own formulas, never read back from the code.
No live Postgres: a fake connection answers each query by the table it reads. MOCK — not real data: every symbol, price,
volume and market cap below is invented (A..F), except that the session count and the shape follow the staging tables.

Fixture (adjusted closes, newest session D0 first; D1 = 1 session back, D5 = 5 back, D21 = 21 back):
    A  Banks  110 / 100 / 100 / 50      d +10, w +10, m +120      mcap 600
    B  Banks   95 / 100 /  95 / 100     d  -5, w   0, m   -5      mcap 200
    C  IT     200 / 200 / 250 / 200     d   0, w -20, m    0      mcap 100
    D  IT     no bar on D0 (no price), older bars exist           mcap 100
    E  Auto   one bar, on D0 only (no history); no market cap
    F  Auto   a 1:2 split: raw 50 on D0, 100 before; adjusted 100 throughout   mcap 100
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}
D0 = date(2026, 10, 19)
DATES = [D0 - timedelta(days=i) for i in range(22)]        # 22 sessions, newest first (MOCK calendar)
LIST_DAY = date(2026, 10, 20)


def _bar(adj, raw=None, vol=None, raw_vol=None):
    return {"adj_close": Decimal(str(adj)), "raw_close": Decimal(str(raw if raw is not None else adj)),
            "adj_volume": vol, "raw_volume": raw_vol if raw_vol is not None else vol}


def _series(points, vol0=None, volrest=None, raw0=None):
    """points {session index: adj close}; volumes: vol0 on D0, volrest on D1..D20 when given."""
    out = {}
    for i, c in points.items():
        v = vol0 if i == 0 else (volrest if volrest is not None and 1 <= i <= 20 else None)
        out[DATES[i]] = _bar(c, raw=raw0 if (i == 0 and raw0 is not None) else None, vol=v)
    return out


def _all_sessions(close):
    return {i: close for i in range(22)}


BARS = {
    "A": _series({0: 110, 1: 100, 5: 100, 21: 50, **{i: 100 for i in range(2, 21) if i != 5}}, vol0=2_000_000, volrest=1_000_000),
    "B": _series({0: 95, 1: 100, 5: 95, 21: 100, **{i: 100 for i in range(2, 21) if i != 5}}, vol0=500_000, volrest=500_000),
    "C": _series({0: 200, 1: 200, 5: 250, 21: 200}),
    "D": _series({1: 10, 5: 10, 21: 10}),
    "E": _series({0: 30}),
    "F": {**{DATES[i]: _bar(100) for i in range(1, 22)}, DATES[0]: _bar(100, raw=50)},
}
del BARS["B"][DATES[7]]            # B has no volume bar on one of the 20 prior sessions -> rel_volume must be null
MCAP = {"A": 600.0, "B": 200.0, "C": 100.0, "D": 100.0, "F": 100.0}
MEMBERS = [
    ("A", "Alpha Bank", "Banks"), ("B", "Beta Bank", "Banks"), ("C", "Cee Tech", "IT"), ("D", "Dee Tech", "IT"),
    ("E", "Eee Motors", "Auto"), ("F", "Eff Motors", "Auto"),
]


def _members(weights=None):
    return [{"symbol": s, "company_name": n, "industry": ind, "weight_pct": (weights or {}).get(s)} for s, n, ind in MEMBERS]


def _ret(sym, n):
    a, b = BARS[sym].get(DATES[0]), BARS[sym].get(DATES[n])
    return None if not a or not b else float(a["adj_close"]) / float(b["adj_close"]) - 1


def _expected(horizon_n):
    """Hand model: end weights from market cap; start weight = end weight / (1 + r); contribution = start share x r."""
    tot = sum(MCAP.values())
    s = {k: (MCAP[k] / tot) / (1 + _ret(k, horizon_n)) for k in MCAP if _ret(k, horizon_n) is not None}
    S = sum(s.values())
    contrib = {k: 100 * s[k] * _ret(k, horizon_n) / S for k in s}
    return s, S, contrib


# ── fake pool ────────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, db):
        self.db, self.calls = db, []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        if "DISTINCT index_name" in q:
            return [{"index_name": n} for n in self.db.get("index_names", ["Nifty 50", "Nifty Bank", "Nifty 100"])]
        if "nidp.index_constituents" in q:
            return self.db.get("members", [])
        if "DISTINCT as_of_date" in q:
            return [{"as_of_date": d} for d in self.db.get("dates", DATES)]
        if "nidp.prices_eod_adjusted" in q:
            return [{"symbol": s, "as_of_date": d, **b} for s, ser in self.db.get("bars", {}).items() for d, b in ser.items()]
        if "nidp.stock_features_daily" in q:
            return [{"symbol": s, "market_cap_cr": Decimal(str(v)), "as_of_date": self.db.get("mcap_day", D0)}
                    for s, v in self.db.get("mcap", {}).items()]
        return []

    async def fetchval(self, q, *a):
        self.calls.append((q, a))
        if "nidp.index_constituents" in q:
            return LIST_DAY
        if "nidp.prices_eod_adjusted" in q:
            return self.db.get("as_of", D0)
        return None


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _CM()


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import desk_market

    def _make(db):
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(desk_market, "get_pool", _get_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh",
                             plan="internal", rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)

        async def _resolve(_t):
            return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)

        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                           daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _validation(_request, exc):
            return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

        from starlette.exceptions import HTTPException as SHE

        @app.exception_handler(SHE)
        async def _http(_request, exc):
            return JSONResponse(status_code=exc.status_code, content={"error": {"status": exc.status_code, "message": str(exc.detail)}})

        app.include_router(desk_market.router, prefix="/v1")
        return TestClient(app), pool
    return _make


def _db(**kw):
    base = {"members": _members(), "bars": BARS, "mcap": MCAP}
    base.update(kw)
    return base


def _get(make_client, q="", **kw):
    c, pool = make_client(_db(**kw))
    return c.get("/v1/desk/sector-heatmap" + q, headers=H), pool


# ── the payload ──────────────────────────────────────────────────────────────

def test_envelope_names_the_index_day_source_sessions_and_mode(make_client):
    r, _ = _get(make_client)
    assert r.status_code == 200
    d = r.json()
    assert d["as_of"] == "2026-10-19" and d["index"] == "Nifty 50" and d["mode"] == "end_of_day"
    assert d["sessions"] == {"d": 1, "w": 5, "m": 21}
    assert "nidp.prices_eod_adjusted" in d["source"] and "nidp.index_constituents" in d["source"]
    assert d["list_date"] == "2026-10-20"


def test_default_index_is_nifty_50_and_the_name_is_matched_loosely(make_client):
    for q in ("", "?index=NIFTY50", "?index=nifty%2050", "?index=Nifty-50"):
        r, pool = _get(make_client, q)
        assert r.status_code == 200 and r.json()["index"] == "Nifty 50", q
        assert any(a and a[0] == "Nifty 50" for _, a in pool.conn.calls if "nidp.index_constituents" in _), q
    r, _ = _get(make_client, "?index=nifty%20bank")
    assert r.json()["index"] == "Nifty Bank"


def test_stock_returns_use_the_session_grid_and_the_adjusted_close(make_client):
    d = _get(make_client)[0].json()
    st = {s["symbol"]: s for s in d["stocks"]}
    assert st["A"]["returns"] == {"d": 10.0, "w": 10.0, "m": 120.0}
    assert st["B"]["returns"] == {"d": -5.0, "w": 0.0, "m": -5.0}
    assert st["C"]["returns"] == {"d": 0.0, "w": -20.0, "m": 0.0}


def test_a_split_is_not_a_move_the_raw_close_halves_the_adjusted_does_not(make_client):
    st = {s["symbol"]: s for s in _get(make_client)[0].json()["stocks"]}
    assert st["F"]["returns"] == {"d": 0.0, "w": 0.0, "m": 0.0}
    assert st["F"]["close"] == 50.0           # the price that actually traded on D0, not the adjusted series


def test_a_stock_with_no_price_in_the_window_has_null_returns_never_zero(make_client):
    st = {s["symbol"]: s for s in _get(make_client)[0].json()["stocks"]}
    assert st["D"]["returns"] == {"d": None, "w": None, "m": None} and st["D"]["close"] is None
    assert st["D"]["index_impact_pct"]["d"] is None
    # E has a bar on D0 but none 1, 5 or 21 sessions back
    assert st["E"]["close"] == 30.0 and st["E"]["returns"] == {"d": None, "w": None, "m": None}


def test_weights_are_market_cap_shares_with_the_basis_stated_and_null_where_unknown(make_client):
    d = _get(make_client)[0].json()
    st = {s["symbol"]: s for s in d["stocks"]}
    tot = sum(MCAP.values())
    for k, v in MCAP.items():
        assert st[k]["weight_pct"] == pytest.approx(100 * v / tot, abs=0.005)
    assert st["E"]["weight_pct"] is None
    assert d["weight_basis"] == "market_cap"
    assert "free-float" in d["weight_note"].lower() or "free float" in d["weight_note"].lower()
    assert any(u["field"] == "weight_pct" and "E" in u["reason"] for u in d["unavailable"])


def test_the_index_list_weight_wins_when_every_member_has_one(make_client):
    w = {"A": 40.0, "B": 20.0, "C": 15.0, "D": 10.0, "E": 10.0, "F": 5.0}
    d = _get(make_client, members=_members(w))[0].json()
    assert d["weight_basis"] == "index_list"
    assert {s["symbol"]: s["weight_pct"] for s in d["stocks"]} == w
    assert not any(u["field"] == "weight_pct" for u in d["unavailable"])


def test_impact_and_the_weighted_change_follow_the_stated_rule(make_client):
    d = _get(make_client)[0].json()
    for key, n in (("d", 1), ("w", 5), ("m", 21)):
        _, _, contrib = _expected(n)
        assert d["weighted_change"][key] == pytest.approx(sum(contrib.values()), abs=0.006), key
    _, _, c1 = _expected(1)
    st = {s["symbol"]: s for s in d["stocks"]}
    for k, v in c1.items():
        assert st[k]["index_impact_pct"]["d"] == pytest.approx(v, abs=0.006), k
    # the day's change is the sum of the stock impacts
    assert sum(s["index_impact_pct"]["d"] or 0 for s in d["stocks"]) == pytest.approx(d["weighted_change"]["d"], abs=0.02)


def test_sector_returns_are_weight_weighted_and_contribution_is_the_sum_of_its_stocks(make_client):
    d = _get(make_client)[0].json()
    sec = {s["name"]: s for s in d["sectors"]}
    assert set(sec) == {"Banks", "IT", "Auto"}
    for key, n in (("d", 1), ("w", 5), ("m", 21)):
        s, _, contrib = _expected(n)
        banks = ("A", "B")
        exp = 100 * sum(s[k] * _ret(k, n) for k in banks) / sum(s[k] for k in banks)
        assert sec["Banks"]["returns"][key] == pytest.approx(exp, abs=0.006), key
        assert sec["Banks"]["contribution_pct"][key] == pytest.approx(sum(contrib[k] for k in banks), abs=0.006), key
    # IT: only C has a return; D has no price, so IT's return is C's alone
    assert sec["IT"]["returns"]["w"] == pytest.approx(-20.0, abs=0.006)
    assert sec["Banks"]["stocks"] == 2 and sec["IT"]["stocks"] == 2 and sec["Auto"]["stocks"] == 2
    tot = sum(MCAP.values())
    assert sec["Banks"]["weight_pct"] == pytest.approx(100 * 800 / tot, abs=0.01)
    assert sec["Auto"]["weight_pct"] == pytest.approx(100 * 100 / tot, abs=0.01)    # E has no weight, F has


def test_a_sector_with_no_priced_weighted_stock_has_null_returns(make_client):
    d = _get(make_client, mcap={"A": 600.0, "B": 200.0, "C": 100.0, "D": 100.0})[0].json()   # F loses its cap, E has none
    auto = {s["name"]: s for s in d["sectors"]}["Auto"]
    assert auto["returns"] == {"d": None, "w": None, "m": None}
    assert auto["contribution_pct"] == {"d": None, "w": None, "m": None} and auto["weight_pct"] is None


def test_breadth_counts_by_sector_and_overall_with_no_price_separate(make_client):
    d = _get(make_client)[0].json()
    sec = {s["name"]: s for s in d["sectors"]}
    assert sec["Banks"]["breadth"] == {"advances": 1, "declines": 1, "unchanged": 0, "no_price": 0}
    assert sec["IT"]["breadth"] == {"advances": 0, "declines": 0, "unchanged": 1, "no_price": 1}
    assert sec["Auto"]["breadth"] == {"advances": 0, "declines": 0, "unchanged": 1, "no_price": 1}
    assert d["breadth"]["advances"] == 1 and d["breadth"]["declines"] == 1 and d["breadth"]["unchanged"] == 2
    assert d["breadth"]["no_price"] == 2


def test_traded_value_and_relative_volume_are_computed_or_null(make_client):
    st = {s["symbol"]: s for s in _get(make_client)[0].json()["stocks"]}
    assert st["A"]["traded_value_cr"] == pytest.approx(110 * 2_000_000 / 1e7)       # 22.0 crore
    assert st["A"]["rel_volume"] == pytest.approx(2.0)                              # 2,000,000 vs twenty days of 1,000,000
    assert st["B"]["traded_value_cr"] == pytest.approx(95 * 500_000 / 1e7)
    assert st["B"]["rel_volume"] is None                                            # one of the 20 prior sessions has no volume
    assert st["C"]["traded_value_cr"] is None and st["C"]["rel_volume"] is None


def test_what_could_not_be_sourced_is_listed_with_a_reason(make_client):
    d = _get(make_client)[0].json()
    fields = {u["field"] for u in d["unavailable"]}
    assert {"weight_pct", "returns", "traded_value_cr", "rel_volume"} <= fields
    ret = next(u for u in d["unavailable"] if u["field"] == "returns")
    assert "D" in ret["reason"] and "no price" in ret["reason"]
    assert all(u["reason"] for u in d["unavailable"])


def test_the_rules_are_stated_in_the_payload(make_client):
    rules = _get(make_client)[0].json()["rules"]
    assert "adjusted" in rules["returns"] and "5" in rules["returns"] and "21" in rules["returns"]
    assert "sector" in rules["sector_return"].lower() and "weight" in rules["sector_return"].lower()
    assert "contribution" in rules["contribution"].lower()


def test_sessions_come_from_the_warehouse_calendar_not_from_calendar_days(make_client):
    # a 3-day gap between two sessions (a weekend) must not shift the 5-session base
    gapped = [D0, D0 - timedelta(days=3)] + [D0 - timedelta(days=3 + i) for i in range(1, 20)]
    bars = {"A": {gapped[0]: _bar(110), gapped[1]: _bar(100), gapped[5]: _bar(55), gapped[21 - 1]: _bar(1)}}
    d = _get(make_client, dates=gapped, bars=bars, mcap={"A": 1.0}, members=_members()[:1])[0].json()
    assert d["stocks"][0]["returns"]["w"] == 100.0           # 110 / 55 - 1
    assert d["stocks"][0]["returns"]["m"] is None            # only 21 sessions exist: the 21-back base is missing


def test_short_history_gives_null_month_not_zero(make_client):
    d = _get(make_client, dates=DATES[:10])[0].json()
    assert all(s["returns"]["m"] is None for s in d["stocks"])
    assert d["weighted_change"]["m"] is None and d["weighted_change"]["d"] is not None


def test_an_index_with_no_priced_stock_still_answers_200_with_nulls_and_why(make_client):
    r, _ = _get(make_client, as_of=None, bars={})
    d = r.json()
    assert r.status_code == 200 and d["as_of"] is None
    assert d["weighted_change"] == {"d": None, "w": None, "m": None}
    assert all(s["returns"]["d"] is None for s in d["stocks"])
    assert any(u["field"] == "returns" for u in d["unavailable"])


def test_an_empty_constituent_list_is_404_not_an_empty_heatmap(make_client):
    r, _ = _get(make_client, members=[])
    assert r.status_code == 404 and "no constituent list" in r.json()["error"]["message"]


def test_an_industry_less_stock_is_grouped_as_unclassified(make_client):
    m = _members()
    m[4]["industry"] = None
    d = _get(make_client, members=m)[0].json()
    assert "Unclassified" in {s["name"] for s in d["sectors"]}


# ── validation ───────────────────────────────────────────────────────────────

def test_an_unknown_index_is_a_typed_404_that_lists_the_valid_names(make_client):
    r, _ = _get(make_client, "?index=Nifty%20Imaginary")
    assert r.status_code == 404
    msg = r.json()["error"]["message"]
    assert msg.startswith("unknown_index") and "Nifty 50" in msg and "Nifty Bank" in msg


@pytest.mark.parametrize("q", ["?index=", "?index=ab", "?index=Nifty;drop", "?index=" + "x" * 61])
def test_a_malformed_index_is_a_400_before_any_query(make_client, q):
    r, pool = _get(make_client, q)
    assert r.status_code == 400 and pool.conn.calls == []


def test_the_route_needs_an_api_key(make_client):
    c, _ = make_client(_db())
    assert c.get("/v1/desk/sector-heatmap").status_code in (401, 403)
