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
        if "WITH ranked AS" in q: return self.db.get("hist_rows", [])            # history: top-N per run with its price window
        if "FROM nidp.tpd_runs WHERE model" in q: return self.db.get("runs", [])  # history: the published sessions
        if "graded_rows, touched, top10_hits" in q: return self.db.get("grades", [])
        if "nidp.tpd_run_estimates e" in q: return self.db.get("rows", [])
        if "nidp.tpd_band_record" in q: return self.db.get("bands", [])
        if "nidp.tpd_run_events" in q: return self.db.get("events", [])
        if "nidp.tpd_run_estimates" in q: return self.db.get("estimates", [])
        return []

    async def fetchrow(self, q, *a):
        self.queries.append(q)
        if "SELECT p_base_rate" in q: return self.db.get("base")
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


# ── History (TC-50..TC-55 in test_reports/move_odds_history_20260918_0820.md) ────────────────────────────────────────

def _hrun(run_id, target, scored=994):
    return {"run_id": run_id, "target_session": target, "data_as_of": target - timedelta(days=1),
            "frozen_at": datetime(target.year, target.month, target.day - 1, 20, 50, tzinfo=IST), "scored": scored, "universe_size": 1000}


def _hrow(run_id, symbol, p, rk, *, prev_close=100.0, d_high=None, d_low=None, h3=None, l3=None, n3=3, h5=None, l5=None, n5=5):
    return {"run_id": run_id, "symbol": symbol, "p": p, "rk": rk, "company_name": f"{symbol} Ltd", "sector": "Test",
            "prev_close": prev_close, "d_high": d_high, "d_low": d_low, "h3": h3, "l3": l3, "n3": n3, "h5": h5, "l5": l5, "n5": n5}


def _hist_db(**over):
    """Two sessions. 18 Sep: ALPHA touched +5% on the day, BETA did not but got there within 5.
    17 Sep: ALPHA and GAMMA. So on 18 Sep, BETA is new and ALPHA is not."""
    db = _db(
        runs=[_hrun(3, date(2026, 9, 18)), _hrun(1, date(2026, 9, 17))],
        hist_rows=[
            _hrow(3, "ALPHA", 0.30, 1, prev_close=100.0, d_high=106.0, d_low=99.0, h3=106.0, l3=98.0, h5=106.0, l5=98.0),
            _hrow(3, "BETA",  0.25, 2, prev_close=200.0, d_high=203.0, d_low=198.0, h3=205.0, l3=196.0, h5=212.0, l5=196.0),
            _hrow(1, "ALPHA", 0.28, 1, prev_close=95.0, d_high=99.0, d_low=94.0, h3=99.0, l3=94.0, h5=101.0, l5=94.0),
            _hrow(1, "GAMMA", 0.22, 2, prev_close=50.0, d_high=53.0, d_low=49.0, h3=53.0, l3=49.0, h5=53.0, l5=49.0),
        ],
        grades=[{"run_id": 1, "graded_rows": 994, "touched": 86, "top10_hits": 3}],
        base={"p_base_rate": 0.0758},
    )
    db.update(over)
    return db


def test_tc50_history_lists_sessions_newest_first_with_ranked_rows(make_client):
    c, _ = make_client(_hist_db())
    r = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["head"] == "p_up5_1d" and d["top_n"] == 2
    assert [s["target_session"] for s in d["sessions"]] == ["2026-09-18", "2026-09-17"]
    first = d["sessions"][0]
    assert [row["rank"] for row in first["rows"]] == [1, 2]
    assert [row["symbol"] for row in first["rows"]] == ["ALPHA", "BETA"]
    assert first["rows"][0]["p"] == 0.30 and first["scored"] == 994
    assert first["base_rate"] == 0.0758


def test_tc51_outcome_uses_the_heads_own_rule_against_the_reference_close(make_client):
    c, _ = make_client(_hist_db())
    d = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).json()["data"]
    alpha, beta = d["sessions"][0]["rows"]
    assert alpha["outcome"]["touched"] is True                       # 106 >= 100 x 1.05
    assert alpha["outcome"]["reference_close"] == 100.0
    assert alpha["outcome"]["move_pct"] == pytest.approx(0.06)
    assert beta["outcome"]["touched"] is False                       # 203 < 200 x 1.05 on the day
    assert beta["outcome"]["within5"] is True                        # but 212 >= 210 within five sessions
    assert beta["outcome"]["within3"] is False                       # 205 < 210 within three
    # the down head reads the low against the same reference, not the high
    dn = c.get("/v1/move-odds/history?head=p_down5_1d&top=2", headers=H).json()["data"]
    a_dn = dn["sessions"][0]["rows"][0]
    assert a_dn["outcome"]["touched"] is False                       # low 99 > 100 x 0.95
    assert a_dn["outcome"]["move_pct"] == pytest.approx(-0.01)


def test_tc51b_published_session_summary_comes_from_the_official_grade(make_client):
    c, _ = make_client(_hist_db())
    d = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).json()["data"]
    sep17 = d["sessions"][1]
    assert sep17["summary"]["touched"] == 86 and sep17["summary"]["graded_rows"] == 994
    assert sep17["summary"]["top10_touched"] == 3
    assert sep17["summary"]["touch_rate"] == pytest.approx(86 / 994)


def test_tc52_a_session_with_no_prices_yet_is_pending_and_invents_no_outcome(make_client):
    db = _hist_db(hist_rows=[_hrow(3, "ALPHA", 0.30, 1, prev_close=None, d_high=None, d_low=None, n3=0, n5=0)], grades=[])
    c, _ = make_client(db)
    d = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).json()["data"]
    row = d["sessions"][0]["rows"][0]
    assert d["sessions"][0]["state"] == "pending"
    assert row["outcome"] == {"state": "pending", "touched": None, "move_pct": None, "reference_close": None,
                              "within3": None, "within5": None, "sessions_available": 0}
    assert d["sessions"][0]["summary"]["touched"] is None and d["sessions"][0]["summary"]["top_n_touched"] is None


def test_tc53_new_entries_are_flagged_against_the_previous_session_only(make_client):
    c, _ = make_client(_hist_db())
    d = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).json()["data"]
    newest = {row["symbol"]: row["is_new"] for row in d["sessions"][0]["rows"]}
    assert newest == {"ALPHA": False, "BETA": True}                  # ALPHA was in 17 Sep's top 2, BETA was not
    oldest = {row["symbol"]: row["is_new"] for row in d["sessions"][1]["rows"]}
    assert oldest == {"ALPHA": None, "GAMMA": None}                  # nothing before it: unknowable, never "new"


def test_tc54_an_incomplete_forward_window_stays_null_rather_than_reading_as_a_miss(make_client):
    db = _hist_db(hist_rows=[_hrow(3, "ALPHA", 0.30, 1, prev_close=100.0, d_high=101.0, d_low=99.0,
                                   h3=101.0, l3=99.0, n3=2, h5=101.0, l5=99.0, n5=2)])
    c, _ = make_client(db)
    d = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).json()["data"]
    o = d["sessions"][0]["rows"][0]["outcome"]
    assert o["touched"] is False and o["within3"] is None and o["within5"] is None and o["sessions_available"] == 2


def test_tc55_history_is_internal_plan_only_and_validates_the_head(make_client):
    c, _ = make_client(_hist_db(), plan="pro")
    assert c.get("/v1/move-odds/history", headers=H).status_code == 403
    c2, _ = make_client(_hist_db())
    # the DaaS app's validation handler answers 400, not FastAPI's default 422
    assert c2.get("/v1/move-odds/history?head=p_up20_1d", headers=H).status_code == 400
    assert c2.get("/v1/move-odds/history?top=500", headers=H).status_code == 400


def test_history_carries_no_recommendation_vocabulary(make_client):
    c, _ = make_client(_hist_db())
    body = c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).text
    keys = set()
    def walk(o):
        if isinstance(o, list):
            for v in o: walk(v)
        if isinstance(o, dict):
            for k, v in o.items(): keys.add(k); walk(v)
    walk(c.get("/v1/move-odds/history?head=p_up5_1d&top=2", headers=H).json())
    banned = re.compile(r"\b(buy|sell|invest|hold|stop|target_price|conviction|position_size|multibagger|best|top_?pick)\b", re.I)
    assert not [k for k in keys if banned.search(k.replace("_", " "))], [k for k in keys if banned.search(k.replace("_", " "))]
    assert "recommend" not in body.lower()
