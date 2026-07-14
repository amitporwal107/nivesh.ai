"""Scheme-name → AMFI scheme_code resolution for the MF holdings ingester.

The HDFC adapter used to carry a bespoke `_resolve_codes` (lower()/strip() +
"split at first '(' or '-'" + a `[:1]` last-resort pick) that dropped merged /
"&" funds — notably HDFC Balanced Advantage Fund (erstwhile HDFC Prudence Fund),
whose holdings then never landed under the plan codes the copilot resolves to, so
the chat showed no holdings. The adapter now uses the shared, precision-tiered
`_resolve_scheme_codes` (erstwhile-aware, "&"→"and", identity-based). These tests
pin that the shared resolver maps HDFC Balanced Advantage to ALL its plan codes
across the tricky name forms, and doesn't bleed across funds.

Pure functions (no network/DB) — run everywhere.
"""
from __future__ import annotations

from nidp.services.mf_holdings.amc_dispatch import _build_scheme_index, _resolve_scheme_codes

# Synthetic AMFI master rows (shape: scheme_code, scheme_name).
_DB = [
    {"scheme_code": "BAF-RG", "scheme_name": "HDFC Balanced Advantage Fund - Regular Plan - Growth Option"},
    {"scheme_code": "BAF-DG", "scheme_name": "HDFC Balanced Advantage Fund - Direct Plan - Growth Option"},
    {"scheme_code": "BAF-RI", "scheme_name": "HDFC Balanced Advantage Fund - Regular Plan - IDCW Option"},
    {"scheme_code": "BAF-DI", "scheme_name": "HDFC Balanced Advantage Fund - Direct Plan - IDCW Option"},
    {"scheme_code": "FLEXI-RG", "scheme_name": "HDFC Flexi Cap Fund - Regular Plan - Growth"},
    {"scheme_code": "BFS-RG", "scheme_name": "HDFC Banking & Financial Services Fund - Regular Plan - Growth"},
    {"scheme_code": "BFS-DG", "scheme_name": "HDFC Banking & Financial Services Fund - Direct Plan - Growth"},
]
_BAF = {"BAF-RG", "BAF-DG", "BAF-RI", "BAF-DI"}


def _resolve(name):
    return set(_resolve_scheme_codes(name, _build_scheme_index(_DB)))


def test_balanced_advantage_resolves_to_all_plan_codes():
    # The bare fund name (as Excel publishes it) → every plan variant's code.
    assert _resolve("HDFC Balanced Advantage Fund") == _BAF


def test_erstwhile_descriptor_is_stripped():
    assert _resolve("HDFC Balanced Advantage Fund (Erstwhile HDFC Prudence Fund)") == _BAF


def test_ampersand_vs_and_mismatch_resolves():
    # Excel "and" vs master "&" (or vice-versa) — the bespoke base-split missed
    # this; the shared resolver normalises both to "and".
    assert _resolve("HDFC Banking and Financial Services Fund") == {"BFS-RG", "BFS-DG"}
    assert _resolve("HDFC Banking & Financial Services Fund") == {"BFS-RG", "BFS-DG"}


def test_does_not_bleed_across_funds():
    assert _resolve("HDFC Flexi Cap Fund") == {"FLEXI-RG"}
    # Balanced Advantage must not pull in Flexi Cap or Banking funds.
    assert _resolve("HDFC Balanced Advantage Fund") & {"FLEXI-RG", "BFS-RG", "BFS-DG"} == set()


def test_unknown_fund_resolves_to_nothing():
    assert _resolve("Some Fund That Does Not Exist") == set()
