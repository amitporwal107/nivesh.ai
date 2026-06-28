"""Fund-name phrase extraction for the Copilot MF scheme resolver.

Regression cover for the bug where "Tell me about the mutual fund HDFC Balanced
Advantage Fund" returned a "data unavailable" answer with only portfolio-overlap
data and no MF scorecard tile. `_LEAD` stripped the command verb ("tell me
about") but left the generic "the mutual fund" filler in front of the name, so
the DaaS substring search ran on "the mutual fund HDFC Balanced Advantage Fund"
— which matches no canonical scheme name — resolution returned None, no
scheme_code was set, and the node fell through to portfolio overlap.

`extract_scheme_query` now strips leading "(the) mutual fund / fund / scheme"
filler. Pure / no network — runs everywhere.
"""
from __future__ import annotations

import pytest

from services.copilot_tools.scheme_resolver import extract_scheme_query


@pytest.mark.parametrize(
    "text,expected",
    [
        # the exact reported failure
        ("Tell me about the mutual fund HDFC Balanced Advantage Fund",
         "HDFC Balanced Advantage Fund"),
        # filler variants
        ("Tell me about the fund HDFC Balanced Advantage Fund",
         "HDFC Balanced Advantage Fund"),
        ("mutual fund Parag Parikh Flexi Cap", "Parag Parikh Flexi Cap"),
        ("the scheme SBI Bluechip", "SBI Bluechip"),
        ("tell me about the mutual fund scheme HDFC Balanced Advantage Fund",
         "HDFC Balanced Advantage Fund"),
        # already-clean inputs must be unchanged (trailing "Fund" preserved)
        ("HDFC Balanced Advantage Fund", "HDFC Balanced Advantage Fund"),
        ("tell me about HDFC Balanced Advantage Fund",
         "HDFC Balanced Advantage Fund"),
        ("Show the holdings of HDFC Balanced Advantage Fund",
         "HDFC Balanced Advantage Fund"),
    ],
)
def test_extract_strips_generic_fund_filler(text, expected):
    assert extract_scheme_query(text) == expected


# A view/metric clause TRAILING the fund name ("{fund} top holdings", "{fund}
# latest NAV") must be stripped too. The MF node resolves on the whole user
# message, so "hdfc balanced advantage fund top holdings" left a stray "top" in
# the DaaS search → no or wrong scheme → live "top holdings: data unavailable".
@pytest.mark.parametrize(
    "text,expected",
    [
        # the reported failure
        ("hdfc balanced advantage fund top holdings", "hdfc balanced advantage fund"),
        ("HDFC Balanced Advantage Fund top holdings", "HDFC Balanced Advantage Fund"),
        # other trailing view/metric clauses
        ("Parag Parikh Flexi Cap Fund latest NAV", "Parag Parikh Flexi Cap Fund"),
        ("SBI Small Cap Fund returns", "SBI Small Cap Fund"),
        ("Axis Bluechip Fund expense ratio", "Axis Bluechip Fund"),
        ("Mirae Asset Large Cap Fund sector allocation", "Mirae Asset Large Cap Fund"),
        ("Quant Active Fund sharpe", "Quant Active Fund"),
        ("ICICI Prudential Bluechip Fund 5 year returns", "ICICI Prudential Bluechip Fund"),
        # alias shortcut still wins even with a trailing clause
        ("hdfc baf top holdings", "HDFC Balanced Advantage"),
    ],
)
def test_extract_strips_trailing_view_clause(text, expected):
    assert extract_scheme_query(text) == expected


# Real scheme names that contain view-like / qualifier words must NOT be truncated.
@pytest.mark.parametrize(
    "text,expected",
    [
        ("HDFC Top 100 Fund", "HDFC Top 100 Fund"),
        ("Kotak Emerging Equity Fund", "Kotak Emerging Equity Fund"),
        ("HDFC Top 100 Fund returns", "HDFC Top 100 Fund"),
    ],
)
def test_extract_does_not_truncate_real_names(text, expected):
    assert extract_scheme_query(text) == expected
