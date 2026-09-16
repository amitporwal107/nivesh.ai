"""DaaS /v1/move-odds (test cases TC-1..TC-8 in test_reports/move_odds_research_20260916_2351.md). No live Postgres:
a fake connection answers each query by the table it reads, and the clock is injected."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
import re

import pytest
from fastapi.testclient import TestClient

IST = timezone(timedelta(hours=5, minutes=30))
BANNED = re.compile(r"\b(buy|sell|invest|hold|entry|stop|target_price|conviction|position_size|multibagger|best|top_?pick|rank)\b", re.I)


class _Conn:
    def __init__(self, db):
        self.db = db
        self.queries = []

    async def fetch(self, q, *a):
        self.queries.append(q)
        if "nidp.nse_holidays" in q: return self.db.get("holidays", [])
        if "nidp.tpd_run_estimates e" in q: return self.db.get("rows", [])
        if "nidp.tpd_band_record" in q: return self.db.get("bands", [])
        if "nidp.tpd_run_events" in q: return self.db.get("events", [])
        if "nidp.tpd_run_estimates" in q: return self.db.get("estimates", [])
        return []

    async def fetchrow(self, q, *a):
        self.queries.append(q)
        if "nidp.tpd_run_refusals" in q: return self.db.get("refusal")
        if "nidp.tpd_model_record" in q: return self.db.get("record")
        if "nidp.tpd_run_grades" in q: return self.db.get("live")
        if "nidp.tpd_run_stocks" in q: return self.db.get("stock")
        if "nidp.tpd_runs" in q: return self.db.get("run")
        return None

    async def fetchval(self, q, *a):
        return 1

    async def execute(self, q, *a):
        return "OK"


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn
        class _CM:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _CM()


RUN = {"run_id": 7, "model": "v4", "refit": "monthly", "status": "final", "data_as_of": date(2026, 9, 16), "target_session": date(2026, 9, 17),
       "frozen_at": datetime(2026, 9, 16, 20, 50, tzinfo=IST), "snapshot_sha256": "a" * 64, "git_sha": "0dc20f9243", "universe_size": 1000, "scored": 994,
       "input_count": 84, "train_rows": 366080, "train_end": date(2026, 8, 31), "skipped_holidays": [], "counts_toward_verdict": True}
ROWS = [{"symbol": "PNCINFRA", "company_name": "PNC Infratech Limited", "sector": "Construction", "p": 0.366, "p_opposite": 0.31, "p_base_rate": 0.0758, "events_on_record": 3},
        {"symbol": "ANTELOPUS", "company_name": "Antelopus Selan Energy Limited", "sector": "Oil Gas", "p": 0.325, "p_opposite": 0.402, "p_base_rate": 0.0758, "events_on_record": 1}]


def _db(**over):
    db = {"holidays": [], "run": RUN, "rows": ROWS, "refusal": None,
          "bands": [{"band_lo": 0.0, "band_hi": 0.05, "rows": 72715, "realised": 0.035}, {"band_lo": 0.3, "band_hi": 0.4, "rows": 1950, "realised": 0.275}],
          "record": {"window_label": "Jan–Aug 2025", "sessions": 165, "base_rate": 0.0812, "top10_hit_rate": 0.3103},
          "live": {"sessions": 0, "top10_hits": None, "touched": None, "graded_rows": None, "last_target": None, "last_top10_hits": None, "last_touched": None, "last_graded_rows": None},
          "stock": {"symbol": "PNCINFRA", "company_name": "PNC Infratech Limited", "sector": "Construction", "results_filed": False,
                    "inputs": '{"close_change_pct": {"v": -4.19, "date": "2026-09-16"}}'},
          "estimates": [{"head": h, "p": p} for h, p in (("p_up5_1d", 0.366), ("p_down5_1d", 0.31), ("p_up10_1d", 0.104), ("p_down10_1d", 0.025))],
          "events": [{"ord": 1, "event_time": datetime(2026, 9, 14, 21, 2, tzinfo=IST), "source_label": "NSE filing", "is_media": False, "event_type": "REGULATORY",
                      "event_subtype": "debarment", "direction": "negative", "title": "PNCINFRA: Action(s) taken or orders passed", "url": "https://nse/x.pdf", "method": "rules"},
                     {"ord": 2, "event_time": datetime(2026, 9, 15, 10, 13, tzinfo=IST), "source_label": "Economic Times", "is_media": True, "event_type": "REGULATORY",
                      "event_subtype": "debarment", "direction": "negative", "title": None, "url": "https://et/y", "method": "rules"}]}
    db.update(over)
    return db


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    import nidp.shared.storage.pg as pg_mod
    import nidp.services.daas_api.middleware as mw
    from nidp.services.daas_api.routers import move_odds

    def _make(db, plan="internal", now=datetime(2026, 9, 17, 9, 0, tzinfo=IST)):
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
        return TestClient(app), pool
    return _make


H = {"X-API-Key": "nvd_t_token"}


def test_expected_session_follows_the_clock_and_the_cm_calendar():
    from nidp.services.daas_api.routers.move_odds import expected_session

    hol = {date(2026, 10, 2)}
    assert expected_session(datetime(2026, 9, 17, 9, 0, tzinfo=IST), hol) == date(2026, 9, 17)     # morning of a session: today's estimates
    assert expected_session(datetime(2026, 9, 17, 15, 29, tzinfo=IST), hol) == date(2026, 9, 17)
    assert expected_session(datetime(2026, 9, 17, 15, 30, tzinfo=IST), hol) == date(2026, 9, 18)    # after the close: the next session's
    assert expected_session(datetime(2026, 9, 18, 21, 0, tzinfo=IST), hol) == date(2026, 9, 21)     # Friday night -> Monday
    assert expected_session(datetime(2026, 9, 19, 11, 0, tzinfo=IST), hol) == date(2026, 9, 21)     # Saturday
    assert expected_session(datetime(2026, 10, 1, 18, 0, tzinfo=IST), hol) == date(2026, 10, 5)     # Thu night, Fri holiday -> Monday


def test_tc1_latest_is_sorted_with_no_rank_and_carries_base_rate_provenance_and_record(make_client):
    c, pool = make_client(_db())
    r = c.get("/v1/move-odds/latest?head=p_up5_1d&model=v4", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "final" and d["head"] == "p_up5_1d" and d["base_rate"] == pytest.approx(0.0758)
    assert [x["symbol"] for x in d["rows"]] == ["PNCINFRA", "ANTELOPUS"] and "rank" not in d["rows"][0]
    assert d["run"]["target_session"] == "2026-09-17" and d["run"]["data_as_of"] == "2026-09-16" and d["run"]["scored"] == 994
    assert d["record"]["top10_hit_rate"] == pytest.approx(0.3103) and [b["band_lo"] for b in d["record"]["bands"]] == [0.0, 0.3]
    assert d["live_record"]["sessions"] == 0 and "intraday prices" in " ".join(d["limits"]["not_used"])
    assert d["rows"][0]["p_opposite"] == pytest.approx(0.31) and d["rows"][0]["events_on_record"] == 3
    keys = set()
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items(): keys.add(k); walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(d)
    assert not [k for k in keys if BANNED.search(k.replace("_", " "))]
    assert any("ORDER BY e.p DESC" in q for q in pool.conn.queries) and any("ORDER BY band_lo" in q for q in pool.conn.queries)


def test_tc2_unknown_head_and_unknown_model_are_rejected(make_client):
    c, _ = make_client(_db())                                         # the DaaS app maps validation errors to 400
    assert c.get("/v1/move-odds/latest?head=p_up20_1d", headers=H).status_code == 400
    assert c.get("/v1/move-odds/latest?head=p_up5_1d&model=v4d", headers=H).status_code == 400


def test_tc3_no_run_at_all_is_not_published(make_client):
    c, _ = make_client(_db(run=None))
    d = c.get("/v1/move-odds/latest?head=p_up5_1d", headers=H).json()["data"]
    assert d["status"] == "not_published" and d["rows"] == [] and d["expected_session"] == "2026-09-17" and d["last_published_for"] is None


def test_tc4_an_older_run_is_never_served_for_a_later_session(make_client):
    c, pool = make_client(_db(), now=datetime(2026, 9, 17, 18, 0, tzinfo=IST))     # after the close: tomorrow's run expected
    d = c.get("/v1/move-odds/latest?head=p_up5_1d", headers=H).json()["data"]
    assert d["status"] == "not_published" and d["rows"] == [] and d["expected_session"] == "2026-09-18" and d["last_published_for"] == "2026-09-17"
    assert not any("nidp.tpd_run_estimates e" in q for q in pool.conn.queries)


def test_tc5_a_refusal_for_the_expected_session_is_withheld_with_no_rows(make_client):
    refusal = {"reason": "stale_data", "detail": '{"rows": 812, "median": 2640}', "recorded_at": datetime(2026, 9, 16, 20, 51, tzinfo=IST)}
    # the 22:50 retry published a run for the same session: the run is served, the earlier refusal is not
    c, _ = make_client(_db(refusal=refusal))
    assert c.get("/v1/move-odds/latest?head=p_up5_1d", headers=H).json()["data"]["status"] == "final"
    # no run for that session (only yesterday's): withheld
    c, _ = make_client(_db(refusal=refusal, run={**RUN, "target_session": date(2026, 9, 16)}))
    r = c.get("/v1/move-odds/latest?head=p_up5_1d", headers=H)
    assert r.status_code == 503
    d = r.json()["data"]
    assert d["status"] == "withheld" and d["reason"] == "stale_data" and d["detail"] == {"rows": 812, "median": 2640} and "rows" not in d


def test_tc6_stock_detail_has_four_estimates_dated_inputs_and_events_with_media_titles_null(make_client):
    c, _ = make_client(_db())
    r = c.get("/v1/move-odds/stocks/pncinfra", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["symbol"] == "PNCINFRA" and set(d["estimates"]) == {"p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"}
    assert d["inputs"]["close_change_pct"] == {"v": -4.19, "date": "2026-09-16"} and d["run"]["target_session"] == "2026-09-17"
    assert d["events"][0]["title"].startswith("PNCINFRA") and d["events"][1]["is_media"] is True and d["events"][1]["title"] is None


def test_tc7_symbol_not_in_the_run_is_404(make_client):
    c, _ = make_client(_db(stock=None))
    assert c.get("/v1/move-odds/stocks/NOSUCH", headers=H).status_code == 404


def test_tc8_non_internal_key_plan_is_403(make_client):
    c, _ = make_client(_db(), plan="pro")
    assert c.get("/v1/move-odds/latest?head=p_up5_1d", headers=H).status_code == 403
    assert c.get("/v1/move-odds/stocks/PNCINFRA", headers=H).status_code == 403
