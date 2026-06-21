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
