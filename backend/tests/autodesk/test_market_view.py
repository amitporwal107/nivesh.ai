"""AD-10..AD-13, AD-15: the point-in-time market view (market/pit.py) over a FAKE data API (TEST DATA served by a
getter; the real API is covered by the staging run, AD-14) and the session calendar."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from autodesk.market import calendar
from autodesk.market.pit import PitMarketView
from autodesk.market.view import (IST, DataUnavailable, FnoContract, FrozenMarketView, LookAheadError, RestrictedView,
                                  ToolNotAllowed, chain_snapshot)
from tests.autodesk.conftest import run

D = date(2026, 11, 5)          # a Thursday
HOLIDAYS = {date(2026, 11, 10): "test holiday"}


@pytest.fixture(autouse=True)
def _calendar():
    calendar.set_holidays(2026, HOLIDAYS)
    calendar.set_holidays(2025, {date(2025, 12, 25): "Christmas"})
    yield


def at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST)


def sessions(back: int) -> list[date]:
    out, d = [], D
    while len(out) < back:
        if calendar.is_session(d):
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class FakeAPI:
    """TEST DOUBLE of the DaaS API: raw bars of XYZ around a 1:2 split with ex-date SPLIT; F&O rows on D."""
    def __init__(self, split: date, status: int = 200):
        self.split, self.status, self.calls = split, status, []

    async def __call__(self, path: str, params: dict):
        self.calls.append((path, dict(params)))
        if self.status != 200:
            return self.status, {"detail": "boom"}
        if path.startswith("/prices/eod/"):
            days = [d for d in sessions(40) + [date(2026, 11, 6), date(2026, 11, 9)]
                    if date.fromisoformat(params["start"]) <= d <= date.fromisoformat(params["end"])]
            rows = [{"as_of_date": d.isoformat(), "open_price": self._px(d), "high_price": self._px(d) + 2,
                     "low_price": self._px(d) - 2, "close_price": self._px(d), "volume": 1000, "turnover": "1000000"}
                    for d in days]
            return 200, {"data": sorted(rows, key=lambda r: r["as_of_date"], reverse=True)}
        if path.startswith("/prices/adjusted/"):
            # back-adjusted with every action known TODAY: bars before the ex-date carry factor 0.5
            days = [d for d in sessions(40) + [date(2026, 11, 6), date(2026, 11, 9)]
                    if date.fromisoformat(params["start"]) <= d <= date.fromisoformat(params["end"])]
            return 200, {"data": [{"as_of_date": d.isoformat(),
                                   "cumulative_adj_factor": "0.5" if d < self.split else "1"} for d in days]}
        if path.startswith("/fno/"):
            it = params.get("instrument_type")
            rows = []
            if it == "STF":
                rows = [{"as_of_date": D.isoformat(), "expiry_date": "2026-11-24", "option_type": None,
                         "close_price": "1005", "settle_price": "1005", "underlying_price": "1000",
                         "open_interest": 10, "traded_volume": 5, "new_board_lot_qty": 500, "traded_value": "2500000"}]
            elif it == "STO":
                rows = [{"as_of_date": D.isoformat(), "expiry_date": "2026-11-24", "option_type": "CE",
                         "strike_price": "1000", "close_price": "25", "traded_volume": 0, "new_board_lot_qty": 500}]
            return 200, {"data": rows}
        return 404, None

    def _px(self, d: date) -> float:
        return 2000.0 if d < self.split else 1000.0      # raw prices halve on the ex-date


def test_calendar_sessions_and_next_session():
    assert run(calendar.sessions_between(date(2026, 11, 6), date(2026, 11, 12))) == \
        [date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 11), date(2026, 11, 12)]
    assert run(calendar.next_session_for(at(D, "09:00"))) == D
    assert run(calendar.next_session_for(at(D, "16:00"))) == date(2026, 11, 6)
    assert run(calendar.next_session_for(at(date(2026, 11, 9), "18:00"))) == date(2026, 11, 11)   # skips the holiday
    calendar._HOLIDAYS.pop(2031, None)
    with pytest.raises(calendar.CalendarUnavailable):
        calendar.is_session(date(2031, 1, 2))


def test_ad10_publication_rule():
    api = FakeAPI(split=date(2026, 12, 1))
    v = PitMarketView(at(D, "08:45"), getter=api)
    assert v.latest_session("cash") == date(2026, 11, 4) and v.latest_session("fno") == date(2026, 11, 4)
    with pytest.raises(LookAheadError):
        run(v.day_snapshot(D))
    assert PitMarketView(at(D, "19:29"), getter=api).latest_session("cash") == date(2026, 11, 4)
    assert PitMarketView(at(D, "19:31"), getter=api).latest_session("cash") == D
    assert PitMarketView(at(D, "22:44"), getter=api).latest_session("fno") == date(2026, 11, 4)
    v = PitMarketView(at(D, "22:46"), getter=api)
    assert v.latest_session("fno") == D
    bars = run(v.daily_bars("XYZ", sessions=5))
    assert bars[-1].day == D and len(bars) == 5            # D+1 and D+2 rows in the API are never returned
    assert all(c.as_of == v.as_of for c in v.tool_calls())
    # a Monday-morning view sees Friday
    assert PitMarketView(at(date(2026, 11, 9), "08:45"), getter=api).latest_session("cash") == date(2026, 11, 6)


def test_ad11_split_adjusted_as_of_the_view():
    split = date(2026, 11, 2)
    api = FakeAPI(split=date(2026, 11, 20))                 # split AFTER the view's date
    bars = run(PitMarketView(at(D, "20:00"), getter=api).daily_bars("XYZ", sessions=10))
    assert {b.close for b in bars} == {Decimal("2000")}     # unadjusted: the later split does not leak in
    api = FakeAPI(split=split)                              # split inside the window
    bars = run(PitMarketView(at(D, "20:00"), getter=api).daily_bars("XYZ", sessions=10))
    before = [b for b in bars if b.day < split]
    after = [b for b in bars if b.day >= split]
    assert before and after
    assert {b.close for b in before} == {Decimal("1000.0")} and {b.close for b in after} == {Decimal("1000")}
    assert {b.volume for b in before} == {2000} and {b.adj_factor for b in before} == {Decimal("0.5")}


def test_fno_reads_and_lot_size():
    v = PitMarketView(at(D, "23:00"), getter=FakeAPI(split=date(2026, 12, 1)))
    [fut] = run(v.futures("ACME"))
    assert fut.kind == "FUT" and fut.lot_size == 500 and fut.traded_value_rs == Decimal("2500000")
    assert run(v.lot_size("ACME")) == 500 and run(v.expiries("ACME")) == [date(2026, 11, 24)]
    [ce] = run(v.options("ACME", date(2026, 11, 24)))
    assert ce.kind == "CE" and ce.strike == Decimal("1000")
    with pytest.raises(LookAheadError):
        run(v.futures("ACME", date(2026, 11, 6)))


def test_ad12_chain_snapshot_untraded_side():
    rows = [FnoContract(day=D, underlying="X", kind=k, expiry=date(2026, 11, 24), strike=Decimal("100"),
                        close=Decimal("5"), settle=None, underlying_price=Decimal("100"), open_interest=1,
                        change_in_oi=0, traded_volume=vol, lot_size=10) for k, vol in (("CE", 3), ("PE", 0))]
    ch = chain_snapshot(rows, spot=Decimal("100"))
    [row] = ch["strikes"]
    assert row["call"]["close"] == 5.0 and row["put"]["close"] is None and ch["as_of"] == D.isoformat()


def test_ad13_tool_allowlist():
    v = RestrictedView(FrozenMarketView(at(D, "20:00"), {"sessions": [D]}), {"daily_bars"}, "RISK_OPS")
    with pytest.raises(ToolNotAllowed):
        run(v.futures("ACME"))
    run(v.daily_bars("ACME", sessions=3))                   # allowed


def test_ad15_data_api_down_is_not_empty():
    for status in (500, 503, 404):
        v = PitMarketView(at(D, "20:00"), getter=FakeAPI(split=date(2026, 12, 1), status=status))
        with pytest.raises(DataUnavailable):
            run(v.daily_bars("XYZ", sessions=5))
        with pytest.raises(DataUnavailable):
            run(v.futures("ACME"))
    assert [c for c in v.tool_calls() if not c.ok]          # the failed read is recorded


def test_buildup_answered_for_another_day_is_refused():
    async def getter(path, params):
        return 200, {"as_of": "2026-11-03", "rows": [], "indices": []}
    v = PitMarketView(at(D, "20:00"), getter=getter)
    with pytest.raises(DataUnavailable):
        run(v.fno_buildup())


# ── desk fixes from the 5 Nov walk-through: AD-FX-01, 02, 09 ────────────────────────────────────────────────────────

def test_adfx01_published_times_follow_the_real_loads():
    """Cash 19:30 IST and F&O 22:45 IST: after the real loads (cash ~19:00, F&O ~22:15, nidp.v_feed_status)."""
    from datetime import time as dtime, timezone
    from autodesk.market import view as mv
    assert mv.CASH_EOD_PUBLISHED_IST == dtime(19, 30) and mv.FNO_EOD_PUBLISHED_IST == dtime(22, 45)
    assert mv.published_at(D, "cash") == at(D, "19:30").astimezone(timezone.utc) == \
        datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
    assert mv.published_at(D, "fno") == at(D, "22:45").astimezone(timezone.utc) == \
        datetime(2026, 11, 5, 17, 15, tzinfo=timezone.utc)


def test_adfx02_strict_point_in_time_at_the_new_instants():
    api = FakeAPI(split=date(2026, 12, 1))
    prev = date(2026, 11, 4)
    # the 18:50 IST walk-through case: 5 Nov cash is not published yet, so the view still sees 4 Nov
    assert PitMarketView(at(D, "18:50"), getter=api).latest_session("cash") == prev
    for hhmm, kind, want in (("19:29", "cash", prev), ("19:30", "cash", D), ("22:44", "fno", prev), ("22:45", "fno", D)):
        assert PitMarketView(at(D, hhmm), getter=api).latest_session(kind) == want, (hhmm, kind)
        assert FrozenMarketView(at(D, hhmm), {"sessions": [prev, D]}).latest_session(kind) == want, (hhmm, kind)
    # look-ahead stays an error until the instant, for both kinds, on both implementations
    early = PitMarketView(at(D, "19:29"), getter=api)
    with pytest.raises(LookAheadError):
        run(early.day_snapshot(D))
    with pytest.raises(LookAheadError):
        run(PitMarketView(at(D, "22:44"), getter=api).fno_universe(D))
    frozen = FrozenMarketView(at(D, "22:44"), {"sessions": [prev, D]})
    with pytest.raises(LookAheadError):
        run(frozen.fno_universe(D))
    # a Monday-morning view sees Friday for both kinds
    mon = at(date(2026, 11, 9), "08:45")
    assert PitMarketView(mon, getter=api).latest_session("fno") == date(2026, 11, 6)
    assert PitMarketView(mon, getter=api).latest_session("cash") == date(2026, 11, 6)


def test_adfx09_previous_session_is_calendar_only_and_skips_holidays():
    api = FakeAPI(split=date(2026, 12, 1))
    v = PitMarketView(at(D, "08:45"), getter=api)
    assert run(v.previous_session(date(2026, 11, 6))) == D
    assert run(v.previous_session(date(2026, 11, 9))) == date(2026, 11, 6)           # over the weekend
    assert run(v.previous_session(date(2026, 11, 11))) == date(2026, 11, 9)          # over the 10 Nov holiday
    assert run(v.previous_session(date(2026, 11, 14))) == date(2026, 11, 13)         # a Saturday asks for Friday
    calls = [c for c in v.tool_calls() if c.tool == "previous_session"]
    assert len(calls) == 4 and all(c.ok and c.rows == 1 and c.as_of == v.as_of for c in calls)
    assert api.calls == []                                                           # no data API read at all
    # Frozen view: from its own session list; none before the first session -> DataUnavailable (never a guess)
    f = FrozenMarketView(at(D, "08:45"), {"sessions": [date(2026, 11, 3), D]})
    assert run(f.previous_session(D)) == date(2026, 11, 3)
    with pytest.raises(DataUnavailable):
        run(f.previous_session(date(2026, 11, 3)))
