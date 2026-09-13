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
