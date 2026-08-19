"""Selection tests for the shareholding history backfill.

The fetching is verified against staging. What matters without a DB is which
quarters get requested: over-requesting turns a 30-minute job into a 5-hour one and
hammers an endpoint whose IP block we only just escaped, and under-requesting
silently leaves the series too short for the thing it was run for.

No DB, no network.
"""
from __future__ import annotations

from datetime import date

import pytest

from nidp.services.nse_shareholding import backfill_history as bf


def m(period_end, url="https://x/f.xml"):
    return {"period_end": period_end, "xbrl_url": url}


JUN26, MAR26, DEC25, SEP25, JUN25 = (
    date(2026, 6, 30), date(2026, 3, 31), date(2025, 12, 31),
    date(2025, 9, 30), date(2025, 6, 30),
)
ALL = [m(JUN25), m(JUN26), m(SEP25), m(MAR26), m(DEC25)]   # deliberately unordered


def test_returns_newest_first_regardless_of_input_order():
    got = bf.missing_quarters(ALL, have=[], want=3)
    assert [x["period_end"] for x in got] == [JUN26, MAR26, DEC25]


def test_quarters_already_stored_are_never_refetched():
    """This is the difference between a 30-minute job and a 5-hour one, and it is
    what lets an interrupted run resume instead of restart."""
    got = bf.missing_quarters(ALL, have=[JUN26, MAR26], want=2)
    assert [x["period_end"] for x in got] == [DEC25, SEP25]


def test_want_is_a_hard_cap():
    assert len(bf.missing_quarters(ALL, have=[], want=1)) == 1
    assert len(bf.missing_quarters(ALL, have=[], want=99)) == len(ALL)


def test_nothing_missing_means_no_requests():
    assert bf.missing_quarters(ALL, have=[JUN26, MAR26, DEC25, SEP25, JUN25],
                               want=4) == []


def test_a_filing_with_no_xbrl_url_is_skipped_not_counted():
    """Yielding it would burn a slot in `want` on something unfetchable, quietly
    leaving the series one quarter short."""
    got = bf.missing_quarters([m(JUN26, url=None), m(MAR26), m(DEC25)],
                              have=[], want=2)
    assert [x["period_end"] for x in got] == [MAR26, DEC25]


def test_a_filing_with_no_period_is_ignored():
    got = bf.missing_quarters([{"xbrl_url": "https://x/f.xml"}, m(JUN26)],
                              have=[], want=4)
    assert [x["period_end"] for x in got] == [JUN26]


def test_none_in_the_have_list_does_not_mask_a_real_quarter():
    got = bf.missing_quarters([m(JUN26)], have=[None], want=1)
    assert [x["period_end"] for x in got] == [JUN26]


# ── URL construction ────────────────────────────────────────────────────────

def test_symbol_url_appends_to_the_existing_query():
    """The base URL already carries ?index=equities, so the symbol must join with
    & — a ? here would produce a malformed URL that quietly returns the whole
    universe instead of one symbol's history."""
    url = bf.symbol_url("RELIANCE")
    assert url.count("?") == 1
    assert url.endswith("&symbol=RELIANCE")
    assert "index=equities" in url


# ── the type mismatch that made the first run a no-op ───────────────────────

def test_string_manifest_dates_match_date_objects_from_the_database():
    """parse_filing_list yields period_end as a STRING; asyncpg returns
    datetime.date. A direct `in` check between them is always False — it does not
    raise, it just stops excluding anything, so the backfill re-fetches the quarters
    it already had and deepens nothing.

    Observed on staging before the fix: 556 rows written across ~278 symbols, every
    one still holding exactly the same two quarters afterwards.
    """
    manifests = [{"period_end": "2026-06-30", "xbrl_url": "u"},
                 {"period_end": "2026-03-31", "xbrl_url": "u"},
                 {"period_end": "2025-12-31", "xbrl_url": "u"},
                 {"period_end": "2025-09-30", "xbrl_url": "u"}]
    have = [date(2026, 6, 30), date(2026, 3, 31)]      # as the DB returns them
    got = bf.missing_quarters(manifests, have=have, want=2)
    assert [x["period_end"] for x in got] == ["2025-12-31", "2025-09-30"]


def test_string_manifests_sort_newest_first():
    manifests = [{"period_end": "2025-09-30", "xbrl_url": "u"},
                 {"period_end": "2026-06-30", "xbrl_url": "u"},
                 {"period_end": "2025-12-31", "xbrl_url": "u"}]
    got = bf.missing_quarters(manifests, have=[], want=3)
    assert [x["period_end"] for x in got] == ["2026-06-30", "2025-12-31", "2025-09-30"]


def test_mixed_types_on_both_sides_still_match():
    manifests = [{"period_end": date(2026, 6, 30), "xbrl_url": "u"},
                 {"period_end": "2026-03-31", "xbrl_url": "u"}]
    assert bf.missing_quarters(manifests, have=["2026-06-30", date(2026, 3, 31)],
                               want=2) == []
