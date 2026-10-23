"""Smart Money flows: continue the daily series with days newer than its last row (test_reports/fix_smart_money_flows_latest_TESTCASES.md)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import markets_smart_money as sm


def _client(monkeypatch, body, pulse, pulse_raises=False):
    async def fake_daas(path, params, list_key):
        return body

    async def fake_pulse(days=90):
        if pulse_raises:
            raise RuntimeError("boom")
        return pulse

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(sm, "_daas", fake_daas)
    monkeypatch.setattr(sm.daas_client, "get_market_pulse_fii_dii", fake_pulse)
    monkeypatch.setattr(sm, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(sm.router)
    return TestClient(app)


def _body(grain="daily"):
    return {"as_of": "2026-10-21", "window": "3M", "grain": grain, "count": 2, "total": 2,
            "rows": [{"date": "2026-10-19", "fii_net_cr": -1149.0, "dii_net_cr": 3201.0, "fii_cum_cr": -1000.0, "dii_cum_cr": 2000.0},
                     {"date": "2026-10-21", "fii_net_cr": 1022.32, "dii_net_cr": 1614.32, "fii_cum_cr": 22.32, "dii_cum_cr": 3614.32}]}


PULSE = {"as_of": "2026-10-23", "daily": [
    {"date": "2026-10-23", "fii_net": 887.65, "dii_net": 3235.36},
    {"date": "2026-10-22", "fii_net": -3458.7, "dii_net": 2891.32},
    {"date": "2026-10-21", "fii_net": 2044.64, "dii_net": 3228.64},      # doubled in the pulse (both sources): must NOT be used
    {"date": "2026-10-19", "fii_net": -2297.28, "dii_net": 6402.38},
]}


def test_tc1_tc2_newer_days_are_appended_with_a_continuing_cumulative_and_older_days_are_untouched(monkeypatch):
    d = _client(monkeypatch, _body(), PULSE).get("/api/markets/smart-money/flows?window=3M").json()
    assert [r["date"] for r in d["rows"]] == ["2026-10-19", "2026-10-21", "2026-10-22", "2026-10-23"]
    assert d["rows"][1]["fii_net_cr"] == 1022.32                       # the series' own 21 Oct, not the pulse's doubled 2044.64
    r22, r23 = d["rows"][2], d["rows"][3]
    assert r22["fii_net_cr"] == -3458.7 and r22["fii_cum_cr"] == round(22.32 - 3458.7, 4) and r22["dii_cum_cr"] == round(3614.32 + 2891.32, 4)
    assert r23["fii_cum_cr"] == round(22.32 - 3458.7 + 887.65, 4)
    assert d["as_of"] == "2026-10-23" and d["count"] == 4 and d["total"] == 4
    assert d["tail_days"] == ["2026-10-22", "2026-10-23"] and "NSE provisional" in d["tail_note"]


def test_tc3_monthly_grain_is_unchanged(monkeypatch):
    body = _body("monthly")
    assert _client(monkeypatch, body, PULSE).get("/api/markets/smart-money/flows?window=1Y").json() == body


def test_tc4_a_failed_or_empty_read_leaves_the_answer_as_sent(monkeypatch):
    body = _body()
    assert _client(monkeypatch, body, PULSE, pulse_raises=True).get("/api/markets/smart-money/flows?window=3M").json() == body
    assert _client(monkeypatch, body, None).get("/api/markets/smart-money/flows?window=3M").json() == body
    assert _client(monkeypatch, body, {"daily": []}).get("/api/markets/smart-money/flows?window=3M").json() == body


def test_tc5_a_day_with_a_missing_net_is_skipped_never_zero_filled(monkeypatch):
    pulse = {"daily": [{"date": "2026-10-23", "fii_net": None, "dii_net": 5.0}, {"date": "2026-10-22", "fii_net": 10.0, "dii_net": 20.0}]}
    d = _client(monkeypatch, _body(), pulse).get("/api/markets/smart-money/flows?window=3M").json()
    assert [r["date"] for r in d["rows"]][-1] == "2026-10-22" and d["as_of"] == "2026-10-22"
