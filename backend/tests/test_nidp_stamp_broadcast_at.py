"""broadcast_at stamping from NSE's results listing -- real AHLWEST excerpt, filed 30-Jun-2024."""
import json
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.nse_financials.stamp_broadcast_at import earliest_broadcasts  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "nse_financial_results_listing.json")


def _records():
    with open(FIXTURE) as fh:
        return json.load(fh)


def test_takes_the_earliest_broadcast_across_both_bases():
    got = earliest_broadcasts(_records())
    # consolidated 14:21:49, standalone 14:19:21 -> the quarter was public at 14:19:21
    assert got[("AHLWEST", date(2022, 3, 31))] == datetime(2024, 6, 30, 14, 19, 21, tzinfo=IST)
    # consolidated 14:15:19, standalone 14:04:48
    assert got[("AHLWEST", date(2021, 3, 31))] == datetime(2024, 6, 30, 14, 4, 48, tzinfo=IST)


def test_keys_on_the_reported_period_not_the_filing_date():
    """Late filers must land on the quarter they report, not the day they filed."""
    assert set(earliest_broadcasts(_records())) == {("AHLWEST", date(2022, 3, 31)),
                                                    ("AHLWEST", date(2021, 3, 31))}


def test_a_later_revision_does_not_move_the_timestamp():
    recs = [
        {"symbol": "ABC", "toDate": "30-Jun-2025", "broadCastDate": "10-Aug-2025 16:00:00"},
        {"symbol": "ABC", "toDate": "30-Jun-2025", "broadCastDate": "02-Sep-2025 11:00:00"},
    ]
    assert earliest_broadcasts(recs)[("ABC", date(2025, 6, 30))].day == 10


def test_timestamps_are_ist_aware():
    ts = next(iter(earliest_broadcasts(_records()).values()))
    assert ts.utcoffset().total_seconds() == 5.5 * 3600


def test_incomplete_records_are_skipped():
    recs = [{"symbol": "", "toDate": "30-Jun-2025", "broadCastDate": "10-Aug-2025 16:00:00"},
            {"symbol": "A", "toDate": None, "broadCastDate": "10-Aug-2025 16:00:00"},
            {"symbol": "B", "toDate": "30-Jun-2025"},
            "not-a-dict"]
    assert earliest_broadcasts(recs) == {}


# ── Integrated Filing (SEBI's regime from Q1 2025) ───────────────────
from nidp.services.nse_financials.stamp_broadcast_at import (  # noqa: E402
    normalize_integrated,
    source_windows,
)

INTEGRATED = os.path.join(os.path.dirname(__file__), "fixtures", "nse_integrated_filing_results.json")


def _integrated():
    with open(INTEGRATED) as fh:
        return [n for n in (normalize_integrated(r) for r in json.load(fh)) if n]


def test_integrated_filing_takes_earliest_across_bases():
    got = earliest_broadcasts(_integrated())
    # KRIDHANINF: standalone 20:13:19, consolidated 20:14:59 (both 31-May-2025)
    assert got[("KRIDHANINF", date(2025, 3, 31))] == datetime(2025, 5, 31, 20, 13, 19, tzinfo=IST)


def test_uppercase_quarter_end_parses():
    """Integrated Filing sends qe_Date as '31-MAR-2025'."""
    assert ("KRIDHANINF", date(2025, 3, 31)) in earliest_broadcasts(_integrated())


def test_revision_without_broadcast_is_skipped_not_misdated():
    """SARVESHWAR's revision carries no broadcast_Date; only the original is when it went public."""
    assert not any(sym == "SARVESHWAR" for sym, _ in earliest_broadcasts(_integrated()))


def test_non_financial_integrated_filings_are_ignored():
    assert normalize_integrated({"type": "Integrated Filing- Governance", "symbol": "X",
                                 "qe_Date": "31-MAR-2025",
                                 "broadcast_Date": "01-May-2025 10:00:00"}) is None


def test_source_windows_split_at_the_integrated_filing_changeover():
    assert source_windows(date(2022, 1, 1), date(2026, 9, 13)) == [
        ("legacy", date(2022, 1, 1), date(2025, 3, 31)),
        ("integrated", date(2025, 1, 1), date(2026, 9, 13)),
    ]
    assert source_windows(date(2023, 1, 1), date(2023, 12, 31)) == [
        ("legacy", date(2023, 1, 1), date(2023, 12, 31))]
    assert source_windows(date(2026, 1, 1), date(2026, 6, 30)) == [
        ("integrated", date(2026, 1, 1), date(2026, 6, 30))]


# ── Writes commit in batches (one 10,843-row transaction filled the disk) ──
import asyncio  # noqa: E402

from nidp.services.nse_financials import stamp_broadcast_at as sba  # noqa: E402


class _FakeConn:
    def __init__(self):
        self.transactions = []   # rows executed per committed transaction
        self._open = None

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                conn._open = []

            async def __aexit__(self, exc_type, *_):
                if exc_type is None:
                    conn.transactions.append(conn._open)
                conn._open = None
                return False

        return _Tx()

    async def execute(self, sql, symbol, period_end, ts):
        assert self._open is not None, "UPDATE ran outside a transaction"
        self._open.append(symbol)
        return "UPDATE 1"


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Acq:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *_):
                return False

        return _Acq()


def test_run_commits_in_batches(monkeypatch):
    records = [{"symbol": f"S{i:04d}", "toDate": "31-Mar-2025",
                "broadCastDate": "01-May-2025 10:00:00"} for i in range(1201)]
    conn = _FakeConn()

    async def fake_fetch(_start, _end):
        return records

    async def fake_pool():
        return _FakePool(conn)

    monkeypatch.setattr(sba, "fetch_integrated", fake_fetch)
    monkeypatch.setattr(sba, "get_pool", fake_pool)
    summary = asyncio.run(sba.run(date(2025, 1, 1), date(2025, 6, 30)))

    assert [len(t) for t in conn.transactions] == [500, 500, 201]
    assert summary["rows_stamped"] == 1201


def test_batched_splits_without_losing_items():
    assert sba.batched(list(range(7)), 3) == [[0, 1, 2], [3, 4, 5], [6]]
    assert sba.batched([], 3) == []


def test_periods_ending_before_the_window_are_not_stamped():
    """A 2018 filing that covers FY2017 is not when FY2017 went public -- that was pre-window."""
    got = sba.in_window({
        ("PETRONET", date(2017, 3, 31)): datetime(2018, 7, 2, 10, 0, tzinfo=IST),
        ("PETRONET", date(2018, 3, 31)): datetime(2018, 5, 20, 10, 0, tzinfo=IST),
    }, date(2018, 1, 1))
    assert list(got) == [("PETRONET", date(2018, 3, 31))]


def test_run_skips_pre_window_periods(monkeypatch):
    records = [{"symbol": "OLD", "toDate": "31-Mar-2020", "broadCastDate": "02-Jul-2021 10:00:00"},
               {"symbol": "NEW", "toDate": "31-Mar-2021", "broadCastDate": "20-May-2021 10:00:00"}]
    conn = _FakeConn()

    async def fake_fetch(_start, _end):
        return records

    async def fake_pool():
        return _FakePool(conn)

    monkeypatch.setattr(sba, "fetch_listing", fake_fetch)
    monkeypatch.setattr(sba, "get_pool", fake_pool)
    summary = asyncio.run(sba.run(date(2021, 1, 1), date(2021, 12, 31)))
    assert conn.transactions == [["NEW"]]
    assert summary["periods"] == 1


def test_legacy_listing_is_not_read_before_2020():
    """Pre-2020 legacy broadcast times are late refilings (TCS FY2018 stamped 36 days late)."""
    assert sba.source_windows(date(2018, 1, 1), date(2019, 12, 31)) == []
    assert sba.source_windows(date(2018, 1, 1), date(2021, 12, 31)) == [
        ("legacy", date(2020, 1, 1), date(2021, 12, 31))]


def test_run_from_before_2020_skips_periods_before_the_window_actually_read(monkeypatch):
    """--from 2018 reads from 2020, so FY2019 (first public in 2019) must not be stamped."""
    records = [{"symbol": "FY19", "toDate": "31-Mar-2019", "broadCastDate": "05-Jun-2020 10:00:00"},
               {"symbol": "FY20", "toDate": "31-Mar-2020", "broadCastDate": "16-Apr-2020 20:24:12"}]
    conn = _FakeConn()
    seen = []

    async def fake_fetch(start, end):
        seen.append((start, end))
        return records

    async def fake_pool():
        return _FakePool(conn)

    monkeypatch.setattr(sba, "fetch_listing", fake_fetch)
    monkeypatch.setattr(sba, "get_pool", fake_pool)
    asyncio.run(sba.run(date(2018, 1, 1), date(2021, 12, 31)))
    assert seen == [(date(2020, 1, 1), date(2021, 12, 31))]
    assert conn.transactions == [["FY20"]]
