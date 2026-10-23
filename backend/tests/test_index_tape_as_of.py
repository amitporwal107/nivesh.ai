"""Index tape tiles carry the date of their own latest daily bar (test_reports/fix_index_tape_eod_day_TESTCASES.md TC-1, TC-2)."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import markets
from services.positional_engine import nse_live


def test_each_tile_has_the_date_of_its_last_daily_bar(monkeypatch):
    hist = {
        "^NSEI": ([22600.0, 22687.65], "2026-10-23"),
        "^BSESN": ([73248.35, 73123.83], "2026-10-22"),      # Yahoo one day behind for this ticker
        "^INDIAVIX": ([15.76, 16.86], "2026-10-23"),
    }
    monkeypatch.setattr(nse_live, "_fetch_index_history", lambda: hist)
    nse_live._SPARK_CACHE.update({"ts": 0.0, "data": None})
    tape = {t["name"]: t for t in asyncio.run(nse_live.get_index_tape())}
    nse_live._SPARK_CACHE.update({"ts": 0.0, "data": None})
    assert tape["Nifty 50"]["as_of"] == "2026-10-23" and tape["Nifty 50"]["value"] == 22687.65
    assert tape["Sensex"]["as_of"] == "2026-10-22"
    assert tape["India VIX"]["as_of"] == "2026-10-23"
    # a ticker with no history has no value and no date, never a made-up one
    assert tape["Nifty 500"]["value"] is None and tape["Nifty 500"]["as_of"] is None and tape["Nifty 500"]["spark"] == []


def test_home_passes_the_tile_date_through_and_clears_it_when_the_live_snapshot_replaced_the_value(monkeypatch):
    from services.positional_engine import market_dashboard as md

    async def build():
        return {"as_of_date": "2026-10-19", "breadth": {}}

    async def live_snapshot():
        return {"nifty50": {"close": 22700.0, "change_pct": 0.5}, "fetched_at": "2026-10-23T10:00:00+00:00"}

    async def nothing():
        return {}

    async def tape():
        return [
            {"name": "Nifty 50", "value": 22600.0, "change_pct": -0.39, "is_vix": False, "trend": None, "spark": [1.0], "as_of": "2026-10-22"},
            {"name": "Nifty Midcap 50", "value": 15000.0, "change_pct": 0.1, "is_vix": False, "trend": None, "spark": [1.0], "as_of": "2026-10-23"},
        ]

    async def movers():
        return {"as_of": None, "gainers": [], "losers": []}

    async def none():
        return None

    async def no_news():
        return []

    async def fake_user(request: Request):
        return {"user_id": "u1"}

    monkeypatch.setattr(md, "build", build)
    monkeypatch.setattr(nse_live, "get_live_snapshot", live_snapshot)
    monkeypatch.setattr(nse_live, "get_global_snapshot", nothing)
    monkeypatch.setattr(nse_live, "get_index_tape", tape)
    monkeypatch.setattr(markets, "_top_movers", movers)
    monkeypatch.setattr(markets, "_fii_dii", none)
    monkeypatch.setattr(markets, "_news", no_news)
    monkeypatch.setattr(markets, "get_current_user", fake_user)
    markets._CACHE.update({"ts": 0.0, "data": None})
    app = FastAPI()
    app.include_router(markets.router)
    d = TestClient(app).get("/api/markets/home").json()
    markets._CACHE.update({"ts": 0.0, "data": None})
    by = {i["name"]: i for i in d["indices"]}
    assert d["as_of"] == "2026-10-19"                          # the dashboard's own day is unchanged
    assert by["Nifty Midcap 50"]["as_of"] == "2026-10-23"      # the tile's own bar day, not the dashboard's
    assert by["Nifty 50"]["as_of"] is None and by["Nifty 50"]["value"] == 22700.0   # replaced by the live snapshot
