"""Today's price before the exchange's end-of-day file (services/kite_live_feed/day_quote.py), owner rule 29 Oct 2026:
live while the market is open, the saved Kite close after the close, the exchange's bars once they are in.
Test ids follow test_reports/kite_close_until_eod_TESTCASES.md (U1-U10)."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from services.kite_live_feed import day_quote as dq
from services.kite_live_feed import quote_cache as qc

IST = timezone(timedelta(hours=5, minutes=30))
SERIES = [["2026-10-27", 100.0, 102.0, 99.0, 101.0, 900.0], ["2026-10-28", 101.0, 103.0, 100.5, 102.0, 1000.0]]


def q(**k):
    base = {"symbol": "ABC", "ltp": 104.0, "open": 102.5, "high": 104.5, "low": 101.8, "close": 102.0, "volume": 5000.0,
            "exchange_ts": "2026-10-29T15:29:59+05:30", "received_at": "2026-10-29T15:31:02+05:30"}
    base.update(k)
    return base


class FakeFeed:
    def __init__(self, *, status=None, snap=None, close=None):
        self.status, self.snap, self.close, self.close_reads = status, snap, close or {}, []

    async def read_status(self):
        return self.status

    async def read_snapshot(self):
        return self.snap

    async def read_close(self, day=None):
        self.close_reads.append(day)
        return self.close.get(day)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    async def read_quotes(symbols):
        return None
    monkeypatch.setattr(qc, "read_quotes", read_quotes)


# ── join_bar (pure) ───────────────────────────────────────────────────────────

def test_u1_after_the_close_the_kite_bar_joins_the_series():
    bars, info = dq.join_bar(SERIES, q(), "2026-10-29", source="kite_close")
    assert bars[-1] == ["2026-10-29", 102.5, 104.5, 101.8, 104.0, 5000.0] and bars[:-1] == SERIES
    assert info["used"] and info["source"] == "kite_close" and info["provisional"] and info["price"] == 104.0
    assert "provisional until the exchange's end-of-day file" in info["text"]
    assert len(SERIES) == 2                                              # the caller's list is not changed


def test_u2_the_exchange_bar_wins_once_it_is_in():
    bars, info = dq.join_bar(SERIES, q(), "2026-10-28", source="kite_close")
    assert bars is SERIES and info == {"used": False, "why": "eod_in", "text": None}


@pytest.mark.parametrize("prev", [None, 17.0, 102.2])                     # missing, a 1:6 split, off by 0.2 %
def test_u3_a_kite_close_that_does_not_join_the_series_is_left_out(prev):
    bars, info = dq.join_bar(SERIES, q(close=prev), "2026-10-29", source="kite_close")
    assert bars is SERIES and info["why"] == "does_not_join"


def test_u3b_within_the_tolerance_it_joins():
    _, info = dq.join_bar(SERIES, q(close=102.04), "2026-10-29", source="kite_close")
    assert info["used"]


@pytest.mark.parametrize("bad", [{"volume": 0.0}, {"volume": None}, {"exchange_ts": "2026-10-28T15:29:59+05:30"}, {"ltp": 0}])
def test_u4_a_price_from_a_day_without_trades_is_not_a_bar(bad):
    bars, info = dq.join_bar(SERIES, q(**bad), "2026-10-29", source="kite_close")
    assert bars is SERIES and info["why"] == "not_traded_today"


def test_u5_a_weekday_between_needs_the_holiday_list():
    series = SERIES[:1]                                                  # ends 27 Oct; 28 Oct is a weekday in between
    _, info = dq.join_bar(series, q(close=101.0), "2026-10-29", source="kite_close")
    assert info["why"] == "gap_unchecked"
    _, info = dq.join_bar(series, q(close=101.0), "2026-10-29", source="kite_close", holidays=set())
    assert info["why"] == "gap_unchecked"                                # 28 Oct was not a holiday: a session is missing
    bars, info = dq.join_bar(series, q(close=101.0), "2026-10-29", source="kite_close", holidays={date(2026, 10, 28)})
    assert info["used"] and bars[-1][0] == "2026-10-29"
    fri = [["2026-10-23", 1, 1, 1, 102.0, 1]]                             # Friday -> Monday: no weekday between
    _, info = dq.join_bar(fri, q(exchange_ts="2026-10-26T15:29:59+05:30"), "2026-10-26", source="kite_close")
    assert info["used"]


def test_u6_the_range_takes_in_the_last_trade_and_an_open_is_required():
    bars, _ = dq.join_bar(SERIES, q(high=103.9, low=104.2), "2026-10-29", source="kite_live")
    assert bars[-1][2] == 104.0 and bars[-1][3] == 102.5                 # high >= close, low <= open
    bars, info = dq.join_bar(SERIES, q(open=None), "2026-10-29", source="kite_close")
    assert bars is SERIES and info["why"] == "bad_candle"
    _, info = dq.join_bar(SERIES, q(), "2026-10-29", source="kite_live")
    assert "still forming" in info["text"]


# ── day_quotes (reads) ────────────────────────────────────────────────────────

def _fresh_snap(now, **k):
    return {"data_at": (now - timedelta(seconds=10)).isoformat(), "quotes": [q(exchange_ts=None, **k)]}


def test_u7_in_the_session_a_fresh_live_quote_answers():
    now = datetime(2026, 10, 29, 11, 0, tzinfo=IST)
    feed = FakeFeed(status={"state": "live", "session": "open", "cadence_seconds": 30}, snap=_fresh_snap(now))
    got = run(dq.day_quotes(["abc"], now=now, feed=feed))
    assert got["source"] == "kite_live" and got["day"] == "2026-10-29" and got["quotes"]["ABC"]["ltp"] == 104.0
    assert feed.close_reads == []                                        # the session never reads a saved close


def test_u7b_redis_answers_when_it_is_newer(monkeypatch):
    now = datetime(2026, 10, 29, 11, 0, tzinfo=IST)

    async def read_quotes(symbols):
        return {"ABC": {"symbol": "ABC", "kind": "EQ", "ltp": 104.6, "ohlc": {"open": 102.5, "high": 104.6, "low": 101.8, "close": 102.0},
                        "volume": 6000.0, "received_at": "2026-10-29T11:00:01+05:30"}}
    monkeypatch.setattr(qc, "read_quotes", read_quotes)
    feed = FakeFeed(status={"state": "live", "session": "open", "cadence_seconds": 30}, snap=_fresh_snap(now, received_at="2026-10-29T10:59:50+05:30"))
    assert run(dq.day_quotes(["ABC"], now=now, feed=feed))["quotes"]["ABC"]["ltp"] == 104.6


@pytest.mark.parametrize("status", [{"state": "expired", "session": "open"}, {"state": "live", "session": "open", "cadence_seconds": 30}])
def test_u8_in_the_session_without_a_live_feed_nothing_is_today(status):
    now = datetime(2026, 10, 29, 11, 0, tzinfo=IST)
    old = {"data_at": (now - timedelta(minutes=20)).isoformat(), "quotes": [q()]}
    got = run(dq.day_quotes(["ABC"], now=now, feed=FakeFeed(status=status, snap=old)))
    assert got["source"] is None and got["quotes"] == {} and got["why"] == "feed_not_live"


def test_u9_after_the_close_the_saved_close_answers_and_without_it_nothing():
    now = datetime(2026, 10, 29, 17, 0, tzinfo=IST)
    feed = FakeFeed(close={"2026-10-29": {"date": "2026-10-29", "data_at": "2026-10-29T10:01:05+00:00", "quotes": [q(), q(symbol="XYZ", volume=0)]}})
    got = run(dq.day_quotes(["ABC", "XYZ"], now=now, feed=feed))
    assert got["source"] == "kite_close" and got["day"] == "2026-10-29" and list(got["quotes"]) == ["ABC"]   # XYZ did not trade
    got = run(dq.day_quotes(["ABC"], now=now, feed=FakeFeed()))
    assert got["source"] is None and got["why"] == "no_saved_close" and got["day"] == "2026-10-29"


@pytest.mark.parametrize("now,day", [
    (datetime(2026, 10, 29, 9, 0, tzinfo=IST), "2026-10-28"),           # before the open: yesterday's close
    (datetime(2026, 10, 31, 12, 0, tzinfo=IST), "2026-10-30"),          # Saturday: Friday's close
    (datetime(2026, 11, 2, 8, 0, tzinfo=IST), "2026-10-30"),            # Monday before the open: Friday's close
])
def test_u10_outside_the_session_the_day_is_the_last_close(now, day):
    feed = FakeFeed()
    got = run(dq.day_quotes(["ABC"], now=now, feed=feed))
    assert got["day"] == day and feed.close_reads == [day]


def test_a_read_failure_is_no_quote_not_an_error():
    class Broken(FakeFeed):
        async def read_close(self, day=None):
            raise RuntimeError("mongo down")
    got = run(dq.day_quotes(["ABC"], now=datetime(2026, 10, 29, 17, 0, tzinfo=IST), feed=Broken()))
    assert got["why"] == "unreadable" and got["quotes"] == {}


def test_extend_daily_reads_holidays_only_for_a_gap(monkeypatch):
    calls = []

    async def holidays_between(a, b):
        calls.append((a, b))
        return {date(2026, 10, 28)}
    monkeypatch.setattr(dq, "holidays_between", holidays_between)
    now = datetime(2026, 10, 29, 17, 0, tzinfo=IST)
    feed = FakeFeed(close={"2026-10-29": {"quotes": [q(close=101.0)]}})
    bars, info = run(dq.extend_daily(SERIES[:1], "ABC", now=now, feed=feed))
    assert info["used"] and calls == [("2026-10-27", "2026-10-29")]
    feed = FakeFeed(close={"2026-10-29": {"quotes": [q()]}})
    calls.clear()
    bars, info = run(dq.extend_daily(SERIES, "ABC", now=now, feed=feed))
    assert info["used"] and calls == []
