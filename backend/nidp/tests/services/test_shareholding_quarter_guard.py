"""nidp.shareholding_pattern must stay on a quarterly grain.

Screener labels a shareholding table by publication month, so it also
surfaces interim month-end filings (2026-07-31, 2026-04-30, ...). Those
rows carry real but non-quarter figures. Admitted into
shareholding_pattern they make "latest quarter" resolve to 2026-07-31 for
a handful of symbols and 2026-06-30 for everyone else, and they break
quarter-over-quarter deltas.
"""
from __future__ import annotations

from datetime import date

import pytest

from nidp.services.nse_financials.writer import _quarter_end_on_or_before


QUARTER_ENDS = ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31",
                "2023-03-31", "2025-12-31"]
INTERIM = {
    "2026-07-31": "2026-06-30",   # the ADANIENT / SUVEN / GOLDIAM case
    "2026-04-30": "2026-03-31",   # JIOFIN / 5PAISA / STEELXIND
    "2026-05-31": "2026-03-31",   # CENTRALBK / GRADIENTE
    "2023-04-30": "2023-03-31",   # TARACHAND
    "2026-01-31": "2025-12-31",   # year boundary
    "2026-02-28": "2025-12-31",
    "2026-10-15": "2026-09-30",   # mid-quarter, not a month end
}


@pytest.mark.parametrize("d", QUARTER_ENDS)
def test_quarter_ends_are_identified_as_quarter_ends(d):
    """The predicate must leave a genuine quarter end untouched."""
    dt = date.fromisoformat(d)
    assert _quarter_end_on_or_before(dt) == dt


@pytest.mark.parametrize("raw,expected", sorted(INTERIM.items()))
def test_interim_dates_are_not_quarter_ends(raw, expected):
    """An interim month end must be recognised as NOT a quarter end...

    ...and must resolve to the preceding quarter, so the skip log names
    the right period.
    """
    dt = date.fromisoformat(raw)
    snapped = _quarter_end_on_or_before(dt)
    assert snapped != dt, f"{raw} was wrongly treated as a quarter end"
    assert snapped == date.fromisoformat(expected)


def test_2024_leap_february_quarter_boundary():
    """Feb 29 in a leap year still belongs to the prior December quarter."""
    assert _quarter_end_on_or_before(date(2024, 2, 29)) == date(2023, 12, 31)
