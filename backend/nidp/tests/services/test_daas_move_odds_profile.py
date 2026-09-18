"""DaaS /v1/move-odds/profile (test cases TC-80..TC-87 in test_reports/move_odds_v7_ratings_filters_20260918_1130.md).
No live Postgres: a fake connection answers each query by the table it reads, and the clock is injected. The real-DB
run of the same handler is recorded in the report (TC-99/TC-100)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

IST = timezone(timedelta(hours=5, minutes=30))
BANNED = re.compile(r"\b(buy|sell|invest|hold|entry|stop|target_price|conviction|position_size|multibagger|best|top_?pick|rank)\b", re.I)

RUN = {"run_id": 3, "model": "v4", "refit": "monthly", "status": "final", "data_as_of": date(2026, 9, 17), "target_session": date(2026, 9, 18),
       "frozen_at": datetime(2026, 9, 17, 20, 50, tzinfo=IST), "snapshot_sha256": "a" * 64, "git_sha": "4d90472abc", "universe_size": 1000,
       "scored": 997, "input_count": 84, "train_rows": 366080, "train_end": date(2026, 8, 31), "skipped_holidays": [], "counts_toward_verdict": True}
D = date(2026, 9, 16)
STOCKS = [{"symbol": s, "sector": sec} for s, sec in (("AAA", "Construction"), ("BBB", "Construction"), ("CCC", "Finance"), ("DDD", "Finance"))]
SCORES = [  # AAA: A, full coverage · BBB: B partial · CCC: C · DDD: no score row at all
    {"symbol": "AAA", "as_of_date": D, "sector": "Construction", "market_cap_bucket": "LARGE_CAP", "quality_score": 70.0, "quality_coverage_pct": 92.0,
     "fundamental_score": 81.26, "technical_score": 55.0},
    {"symbol": "BBB", "as_of_date": D, "sector": "Construction", "market_cap_bucket": "MICRO_CAP", "quality_score": 69.96, "quality_coverage_pct": 62.5,
     "fundamental_score": 70.0, "technical_score": 69.9},
    {"symbol": "CCC", "as_of_date": D, "sector": "Finance", "market_cap_bucket": None, "quality_score": 49.99, "quality_coverage_pct": 80.0,
     "fundamental_score": None, "technical_score": 20.0},
]
SECTOR_ROWS = [  # the whole scored table on the score date: sector medians use coverage >= 80 only
    {"sector": "Construction", "quality_score": 70.0, "quality_coverage_pct": 92.0},
    {"sector": "Construction", "quality_score": 69.96, "quality_coverage_pct": 62.5},     # partial: left out of the median
    {"sector": "Construction", "quality_score": 30.0, "quality_coverage_pct": 85.0},
    {"sector": "Construction", "quality_score": 40.0, "quality_coverage_pct": 99.0},
    {"sector": "Finance", "quality_score": 49.99, "quality_coverage_pct": 80.0},
    {"sector": "Media", "quality_score": 55.0, "quality_coverage_pct": 40.0},             # no stock at coverage >= 80
]


def _feat(sym, **kw):
    base = {c: None for c in ("close", "current_ratio", "cfo_pat_ratio", "debt_to_equity", "dividend_yield_pct", "enterprise_value_cr", "eps_growth_yoy_pct",
                              "ev_ebitda", "interest_coverage", "market_cap_cr", "operating_margin_pct", "pat_growth_yoy_pct", "pb", "pe_ttm",
                              "profit_margin_pct", "promoter_pct", "promoter_pct_change_qoq", "promoter_pledged_pct", "return_20d_pct", "return_60d_pct",
                              "revenue_growth_yoy_pct", "roce_pct", "roe_pct")}
    base.update(symbol=sym, as_of_date=D, **kw)
    return base


FEATS = [
    _feat("AAA", market_cap_cr=12000.456, pe_ttm=20.0, roe_pct=15.0, dividend_yield_pct=0.0, roce_pct=18.0, promoter_pledged_pct=0.0),
    _feat("BBB", market_cap_cr=800.0, pe_ttm=None, roe_pct=8.0, dividend_yield_pct=1.2, roce_pct=None, promoter_pledged_pct=0.0),
    _feat("CCC", market_cap_cr=5000.0, pe_ttm=35.5, roe_pct=None, dividend_yield_pct=0.0, roce_pct=9.0, promoter_pledged_pct=0.0),
    _feat("DDD", market_cap_cr=None, pe_ttm=12.0, roe_pct=20.0, dividend_yield_pct=0.0, roce_pct=11.0, promoter_pledged_pct=0.0),
]
SESSIONS = [{"as_of_date": date(2026, 9, 17) - timedelta(days=i)} for i in range(260)]      # 260 sessions; index 252 is the 1-year base
D0, D252 = SESSIONS[0]["as_of_date"], SESSIONS[252]["as_of_date"]
CLOSES = [{"symbol": "AAA", "as_of_date": D0, "adj_close": 150.0}, {"symbol": "AAA", "as_of_date": D252, "adj_close": 100.0},
          {"symbol": "BBB", "as_of_date": D0, "adj_close": 50.0},                               # BBB listed later: no base close
          {"symbol": "CCC", "as_of_date": D0, "adj_close": 90.0}, {"symbol": "CCC", "as_of_date": D252, "adj_close": 100.0}]
EVENTS = [
    {"symbol": "AAA", "event_time": datetime(2026, 9, 15, 10, 0, tzinfo=IST), "event_type": "CONTRACT", "event_subtype": "order_win", "direction": "positive"},
    {"symbol": "AAA", "event_time": datetime(2026, 9, 16, 18, 0, tzinfo=IST), "event_type": "CORPORATE", "event_subtype": "update", "direction": "neutral"},
    {"symbol": "AAA", "event_time": datetime(2026, 9, 14, 9, 0, tzinfo=IST), "event_type": "GOVERNMENT", "event_subtype": "tender", "direction": "mixed"},
    {"symbol": "CCC", "event_time": datetime(2026, 9, 13, 9, 0, tzinfo=IST), "event_type": "CAPITAL", "event_subtype": "fund_raise", "direction": "negative"},
]


class _Conn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, q, *a):
        if "nidp.nse_holidays" in q: return []
        if "FROM nidp.tpd_run_stocks" in q: return self.db["stocks"]
        if "DISTINCT ON (symbol) symbol, as_of_date, sector, market_cap_bucket" in q: return self.db["scores"]
        if "FROM nidp.v3_stock_scores_daily WHERE as_of_date" in q: return self.db["sector_rows"]
        if "FROM nidp.stock_features_daily" in q: return self.db["feats"]
        if "GROUP BY as_of_date HAVING" in q: return self.db["sessions"]
        if "adj_close FROM nidp.prices_eod_adjusted" in q: return self.db["closes"]
        if "FROM nidp.tpd_run_events" in q: return self.db["events"]
        return []

    async def fetchrow(self, q, *a):
        if "nidp.tpd_run_refusals" in q: return self.db.get("refusal")
        if "nidp.tpd_runs" in q: return self.db.get("run")
        return None


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn
        class _CM:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _CM()


def _db(**over):
    db = {"run": RUN, "refusal": None, "stocks": STOCKS, "scores": SCORES, "sector_rows": SECTOR_ROWS, "feats": FEATS,
          "sessions": SESSIONS, "closes": CLOSES, "events": EVENTS}
    db.update(over)
    return db


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    import nidp.shared.storage.pg as pg_mod
    import nidp.services.daas_api.middleware as mw
    from nidp.services.daas_api.routers import move_odds

    def _make(db, plan="internal", now=datetime(2026, 9, 18, 9, 0, tzinfo=IST)):
        pool = _Pool(db)
        async def _get_pool(): return pool
        async def _close_pool(): return None
        monkeypatch.setattr(pg_mod, "get_pool", _get_pool); monkeypatch.setattr(pg_mod, "close_pool", _close_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh", plan=plan,
                             rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)
        async def _resolve(_t): return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)
        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60, daily_quota=daily_quota,
                                           daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        monkeypatch.setattr(move_odds, "_now", lambda: now)
        mw._LOG_REQUESTS = False
        from nidp.services.daas_api.app import app
        return TestClient(app)
    return _make


H = {"X-API-Key": "nvd_t_token"}


def _get(client):
    r = client.get("/v1/move-odds/profile", headers=H)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# TC-80 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc80_profile_is_only_served_for_the_session_the_page_shows(make_client):
    older = dict(RUN, target_session=date(2026, 9, 17))
    d = make_client(_db(run=older)).get("/v1/move-odds/profile", headers=H).json()["data"]
    assert d["status"] == "not_published" and d["rows"] == {} and d["expected_session"] == "2026-09-18"

    refusal = {"reason": "prices_incomplete", "detail": json.dumps({"missing": 12}), "recorded_at": datetime(2026, 9, 17, 21, 0, tzinfo=IST)}
    r = make_client(_db(run=older, refusal=refusal)).get("/v1/move-odds/profile", headers=H)
    assert r.status_code == 503 and r.json()["data"]["status"] == "withheld" and "rows" not in r.json()["data"]

    r = make_client(_db(), plan="public").get("/v1/move-odds/profile", headers=H)
    assert r.status_code == 403


# TC-81 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc81_grade_bands_partial_flag_and_no_default_for_a_missing_score(make_client):
    from nidp.services.daas_api import move_odds_profile as prof
    assert [prof.grade(x) for x in (70.0, 69.99, 50.0, 49.99, None)] == ["A", "B", "B", "C", None]

    d = _get(make_client(_db()))
    a, b, c, dd = (d["rows"][s]["quality"] for s in ("AAA", "BBB", "CCC", "DDD"))
    assert a == {"score": 70.0, "grade": "A", "coverage": 92.0, "partial": False, "fundamental": 81.3, "technical": 55.0, "as_of": "2026-09-16"}
    assert b["grade"] == "A" and b["score"] == 70.0 and b["partial"] is True          # 69.96 shows as 70.0, so it grades A: letter and number agree
    assert c["grade"] == "B" and c["score"] == 50.0 and c["partial"] is False and c["fundamental"] is None   # 49.99 → 50.0 → B; coverage 80 is full; a missing composite stays null
    assert dd is None                                                                  # no V3 row → no rating, never a default
    assert d["grade_bands"] == {"A": 70.0, "B": 50.0} and d["coverage_min"] == 80.0 and d["scores_as_of"] == "2026-09-16"


# TC-82 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc82_sector_rating_is_the_median_of_full_coverage_scores_with_its_count(make_client):
    d = _get(make_client(_db()))
    assert d["sectors"]["Construction"] == {"median": 40.0, "grade": "C", "n": 3, "n_scored": 4}   # 70, 30, 40 → 40; the partial 69.96 is out
    assert d["sectors"]["Finance"] == {"median": 50.0, "grade": "B", "n": 1, "n_scored": 1}        # 49.99 shows as 50.0 and grades B
    assert d["sectors"]["Media"] == {"median": None, "grade": None, "n": 0, "n_scored": 1}
    assert d["rows"]["DDD"]["sector"] == "Finance"                                                 # no score row: the run's sector is used


def test_tc82b_sector_grade_uses_the_rounded_median_consistently():
    from nidp.services.daas_api import move_odds_profile as prof
    out = prof.sector_ratings([{"sector": "X", "quality_score": 49.99, "quality_coverage_pct": 90}])
    assert out["X"]["median"] == 50.0 and out["X"]["grade"] == "B"      # the grade matches the number shown beside it


# TC-83 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc83_cap_buckets(make_client):
    d = _get(make_client(_db()))
    assert [d["rows"][s]["cap"] for s in ("AAA", "BBB", "CCC", "DDD")] == ["Large", "Micro", None, None]
    from nidp.services.daas_api import move_odds_profile as prof
    assert [prof.cap_label(x) for x in ("LARGE_CAP", "MID_CAP", "SMALL_CAP", "MICRO_CAP", None, "")] == ["Large", "Mid", "Small", "Micro", None, None]


# TC-84 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc84_ratio_catalogue_offers_only_what_the_universe_has(make_client):
    d = _get(make_client(_db()))
    cat = {c["key"]: c for c in d["catalogue"]}
    assert cat["mcap"]["available"] and cat["mcap"]["n"] == 3
    assert cat["pledge"]["available"] is False and cat["pledge"]["reason"] == "Every reading is identical"   # all 0.0: not a ratio
    assert cat["npm"]["available"] is False and cat["npm"]["n"] == 0 and "0.0% of these stocks" in cat["npm"]["reason"]
    assert cat["sales_ttm"]["available"] is False and cat["sales_ttm"]["reason"]
    assert cat["divy"]["available"] and "0 can mean none or no data" in cat["divy"]["note"]
    assert all(c["group"] in d["groups"] and c["column"] in ("recent", "preceding", "historical") for c in d["catalogue"])
    keys = d["ratio_keys"]
    assert keys == [c["key"] for c in d["catalogue"] if c["available"]]
    row = dict(zip(keys, d["rows"]["BBB"]["ratios"]))
    assert row["pe"] is None and row["roce"] is None and row["mcap"] == 800.0      # missing stays null, never 0
    assert dict(zip(keys, d["rows"]["AAA"]["ratios"]))["mcap"] == 12000.46
    assert all(len(r["ratios"]) == len(keys) for r in d["rows"].values())
    assert d["rows"]["AAA"]["ratios_as_of"] == "2026-09-16" and d["features_as_of"] == "2026-09-16"


# TC-85 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc85_one_year_return_is_computed_252_sessions_apart_or_null(make_client):
    d = _get(make_client(_db()))
    keys = d["ratio_keys"]
    assert "r1y" in keys
    r1y = {s: dict(zip(keys, d["rows"][s]["ratios"]))["r1y"] for s in ("AAA", "BBB", "CCC")}
    assert r1y == {"AAA": 50.0, "BBB": None, "CCC": -10.0}                         # BBB: no close 252 sessions back → null
    assert d["return_1y_window"] == {"from": D252.isoformat(), "to": D0.isoformat()}

    short = _get(make_client(_db(sessions=SESSIONS[:200])))                          # under 253 sessions on record: nothing is served
    assert short["return_1y_window"] is None
    assert next(c for c in short["catalogue"] if c["key"] == "r1y")["available"] is False


# TC-86 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
PUBLISHED_PAIRS = {  # every (type, subtype) in nidp.tpd_run_events on 2026-09-18 and the category it must land in
    ("CAPITAL", "dividend"): "dividend", ("CAPITAL", "fund_raise"): "qip", ("CAPITAL", "buyback"): "buyback", ("CAPITAL", "bonus_split"): "other",
    ("CONTRACT", "order_win"): "orders",
    ("CORPORATE", "update"): "other", ("CORPORATE", "director_change"): "management", ("CORPORATE", "resignation"): "management",
    ("CORPORATE", "disruption"): "other", ("CORPORATE", "management_change"): "management", ("CORPORATE", "appointment"): "management",
    ("CORPORATE", "capacity"): "capex", ("CORPORATE", "divestment"): "mna", ("CORPORATE", "acquisition"): "mna",
    ("CORPORATE", "restructuring"): "mna", ("CORPORATE", "product_launch"): "other",
    ("FINANCIAL", "rating_watch"): "rating", ("FINANCIAL", "rating_upgrade"): "rating", ("FINANCIAL", "rating_downgrade"): "rating",
    ("GOVERNMENT", "subsidy"): "regulatory", ("GOVERNMENT", "circular"): "regulatory", ("GOVERNMENT", "policy"): "regulatory",
    ("GOVERNMENT", "tender"): "orders", ("GOVERNMENT", "project"): "orders", ("GOVERNMENT", "procurement"): "orders", ("GOVERNMENT", "tariff"): "regulatory",
    ("INSTITUTION", "partnership"): "other", ("INSTITUTION", "appointment"): "management", ("INSTITUTION", "press_release"): "other",
    ("LEGAL", "litigation"): "litigation", ("LEGAL", "arbitration"): "litigation",
    ("M&A", "acquisition"): "mna", ("M&A", "open_offer"): "mna", ("M&A", "merger"): "mna", ("M&A", "demerger"): "mna", ("M&A", "stake_sale"): "mna",
    ("PHARMA", "fda_approval"): "regulatory", ("PHARMA", "inspection"): "regulatory",
    ("REGULATORY", "approval"): "regulatory", ("REGULATORY", "penalty"): "regulatory", ("REGULATORY", "regulatory_order"): "regulatory",
    ("REGULATORY", "ban"): "regulatory", ("REGULATORY", "rejection"): "regulatory", ("REGULATORY", "forced_listing"): "regulatory",
    ("REGULATORY", "debarment"): "regulatory", ("REGULATORY", "licence_granted"): "regulatory",
    ("RESULTS", "board_outcome"): "earnings", ("RESULTS", "quarterly"): "earnings",
}


def test_tc86_event_categories_material_and_latest(make_client):
    from nidp.services.daas_api import move_odds_profile as prof
    from nidp.services.daas_api import metric_registry as reg
    for (t, s), want in PUBLISHED_PAIRS.items():
        assert prof.event_category(t, s) == want, (t, s)
    assert set(prof.EVENT_LABELS) == set(reg.EVENT_CATEGORIES)                      # one vocabulary with the classifier

    d = _get(make_client(_db()))
    a = d["rows"]["AAA"]["events"]
    assert a["n"] == 3 and a["material"] == 2                                       # neutral is not material
    assert a["latest"] == "2026-09-16T18:00:00+05:30"
    assert a["categories"] == ["orders", "other"]                                   # orders twice (order_win, tender), then other
    assert d["rows"]["CCC"]["events"] == {"n": 1, "material": 1, "latest": "2026-09-13T09:00:00+05:30", "categories": ["qip"]}
    assert d["rows"]["BBB"]["events"] == {"n": 0, "material": 0, "latest": None, "categories": []}
    assert {"key": "qip", "label": "Fund raise"} in d["event_categories"]


# TC-87 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_tc87_payload_passes_the_vocabulary_scan(make_client):
    text = json.dumps(_get(make_client(_db())))
    assert BANNED.search(text) is None, BANNED.search(text)
