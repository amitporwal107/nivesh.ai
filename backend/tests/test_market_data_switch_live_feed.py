"""Market-data switch, app side — MS-17 / MS-18 (test_reports/market_data_switch_TESTCASES.md).

The Kite live feed starts exactly as before at `current`, and does not start when the switch has TrueData serving
live quotes. Mongo, Kite and the feed loop are replaced with fakes; nothing connects anywhere.
"""
from __future__ import annotations

import asyncio

import pytest

from nidp.shared import market_data_source as mds
from services.kite_live_feed import feed as live

READY = {"TRUEDATA_USERNAME": "u", "TRUEDATA_PASSWORD": "p"}
TRUEDATA_SERVES = mds.resolve({"source": "truedata", "truedata_licence_confirmed": True}, READY, integrated=True)
CURRENT = mds.resolve({"source": "current"}, {}, integrated=True)


class FakeFeed:
    cadence = 60
    started = False

    async def run(self):
        FakeFeed.started = True
        await asyncio.sleep(0)


@pytest.fixture
def fakes(monkeypatch):
    async def no_indexes(db):
        return None

    monkeypatch.setattr(live, "ensure_indexes", no_indexes)
    monkeypatch.setattr(live.cfg, "enabled", lambda: True)
    monkeypatch.setattr(live, "get_feed", lambda db=None: FakeFeed())
    monkeypatch.setattr(live, "_task", None)
    FakeFeed.started = False
    yield
    live._task = None


def test_ms17_live_feed_does_not_start_when_truedata_serves(fakes, monkeypatch):
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: TRUEDATA_SERVES)

    async def go():
        return await live.start(db=object())

    assert asyncio.run(go()) is False
    assert live._task is None


def test_ms18_live_feed_starts_as_before_at_current(fakes, monkeypatch):
    monkeypatch.setattr(mds, "resolve", lambda *a, **k: CURRENT)

    async def go():
        started = await live.start(db=object())
        await live._task
        return started

    assert asyncio.run(go()) is True
    assert FakeFeed.started is True
