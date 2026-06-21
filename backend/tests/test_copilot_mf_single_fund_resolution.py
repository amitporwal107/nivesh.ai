"""Single-fund resolution gating for the Copilot MF node.

Regression cover for the bug where asking about a fund by name without a
trigger phrase — e.g. "HDFC Balanced Advantage Fund" or "How is HDFC Balanced
Advantage Fund?" — returned a "data unavailable" answer with only
portfolio-overlap data and NO MF scorecard tile.

Root cause: the intent node only extracts 6-digit AMFI codes, so a fund named
in prose carried no scheme_code. `mf_node` only resolved a name → code when the
message matched `_SINGLE_FUND_Q` ("tell me about", "good fund", a view word).
A bare name matched neither that nor a portfolio question, so it fell through to
the portfolio-overlap catch-all instead of building the MF_DETAIL tile.

`_should_resolve_scheme` now lets a successful resolution promote a bare fund
name to a single-fund card, while still skipping portfolio, leaderboard, and
generic/educational MF questions so those keep their own paths.

These are deterministic unit tests over the predicate — no DB / DaaS.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("langchain_core")  # the node module imports langchain

from nidp.services.copilot_agent.nodes.mf import (  # noqa: E402
    _CAP_Q,
    _COUNT_Q,
    _FIX_Q,
    _SEVERITY_Q,
    _SINGLE_FUND_Q,
    _detect_mf_view,
    _should_resolve_scheme,
)


def _gate(text: str) -> bool:
    """Reproduce mf_node's gating: would we attempt name → scheme resolution?"""
    is_port = bool(
        _COUNT_Q.search(text)
        or _FIX_Q.search(text)
        or _SEVERITY_Q.search(text)
        or _CAP_Q.search(text)
    )
    is_single = (not is_port) and bool(
        _detect_mf_view(text) or _SINGLE_FUND_Q.search(text)
    )
    return _should_resolve_scheme(
        text,
        is_single_fund=is_single,
        is_portfolio_q=is_port,
        has_scheme_code=False,
    )


# --- the exact reported failure + sibling fund-name cases ---------------------

@pytest.mark.parametrize(
    "text",
    [
        "HDFC Balanced Advantage Fund",            # the reported bug (bare name)
        "How is HDFC Balanced Advantage Fund?",    # bare name, question form
        "tell me about HDFC Balanced Advantage Fund",  # explicit single-fund
        "is HDFC Balanced Advantage Fund a good fund",
        "HDFC Balanced Advantage Fund returns",    # view word
        "Parag Parikh Flexi Cap",                  # bare name, different AMC
    ],
)
def test_named_fund_attempts_resolution(text):
    assert _gate(text) is True, f"{text!r} should attempt scheme resolution"


# --- queries that must NOT be resolved to a single scheme --------------------

@pytest.mark.parametrize(
    "text",
    [
        "best large cap funds",       # leaderboard
        "top funds to invest",        # leaderboard
        "large cap funds",            # category leaderboard
        "which category should I pick",  # category question
        "what is NAV",                # generic / educational
        "how do mutual funds work",   # generic
        "explain SIP",                # generic
        "do I have too many funds",   # portfolio (count)
        "fix the overlap in my funds",   # portfolio (fix)
        "are my funds overlapping significantly",  # portfolio (severity)
        "large cap vs flexi cap",     # cap education
    ],
)
def test_non_single_fund_skips_resolution(text):
    assert _gate(text) is False, f"{text!r} should NOT attempt scheme resolution"


# --- an explicit 6-digit code is already resolved upstream -------------------

def test_existing_scheme_code_short_circuits():
    assert (
        _should_resolve_scheme(
            "119551",
            is_single_fund=True,
            is_portfolio_q=False,
            has_scheme_code=True,
        )
        is False
    )
