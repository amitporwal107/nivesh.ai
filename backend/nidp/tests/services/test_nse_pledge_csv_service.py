"""Name-resolution tests for the SAST CSV ingester.

The write path is SQL and is verified against staging (see
test_reports/nse_pledge_csv_ingester.md). What is worth testing without a DB is the
part that decides WHICH symbol a company's pledge is attached to — getting that wrong
does not fail, it silently mislabels a real company.
"""
from __future__ import annotations

import pytest

from nidp.services.nse_pledge_csv.service import (
    _rowcount, build_name_index, resolve_symbols,
)


class _Row(dict):
    """asyncpg Records are read with ["col"]; a dict is the same shape."""


def _master(*pairs):
    return [_Row(symbol=s, company_name=n) for s, n in pairs]


# ── building the index ──────────────────────────────────────────────────────

def test_index_normalises_both_sides_of_the_join():
    index, collisions = build_name_index(_master(
        ("LAURUSLABS", "Laurus Labs Limited"),
        ("A2ZINFRA", "A2Z Infra Engineering Limited"),
    ))
    assert index["LAURUSLABSLIMITED"] == "LAURUSLABS"
    assert index["A2ZINFRAENGINEERINGLIMITED"] == "A2ZINFRA"
    assert collisions == []


def test_a_name_mapping_to_two_symbols_is_dropped_not_arbitrarily_picked():
    """Attaching one company's pledge to a different company's symbol is worse than
    reporting no pledge for either."""
    index, collisions = build_name_index(_master(
        ("AAA", "Ambiguous Holdings Limited"),
        ("BBB", "AMBIGUOUS HOLDINGS LIMITED"),
        ("CCC", "Clear Name Limited"),
    ))
    assert "AMBIGUOUSHOLDINGSLIMITED" not in index
    assert collisions == ["AMBIGUOUSHOLDINGSLIMITED"]
    assert index["CLEARNAMELIMITED"] == "CCC"


def test_the_same_symbol_listed_twice_is_not_a_collision():
    index, collisions = build_name_index(_master(
        ("DUP", "Dup Limited"), ("DUP", "DUP  LIMITED"),
    ))
    assert index["DUPLIMITED"] == "DUP"
    assert collisions == []


def test_rows_without_a_usable_name_are_skipped():
    index, _ = build_name_index(_master(("X", None), ("Y", "   "), ("Z", "!!!"),
                                        ("OK", "Real Limited")))
    assert index == {"REALLIMITED": "OK"}


# ── resolving ───────────────────────────────────────────────────────────────

def test_unresolved_names_are_returned_not_dropped_on_the_floor():
    """A company that did not resolve is a company whose pledge did not land. The
    CLI prints this to stderr; it must never be a silent omission."""
    rows = [
        {"company_name": "Laurus Labs Limited", "name_key": "LAURUSLABSLIMITED"},
        {"company_name": "Not In Master Limited", "name_key": "NOTINMASTERLIMITED"},
    ]
    resolved, unresolved = resolve_symbols(rows, {"LAURUSLABSLIMITED": "LAURUSLABS"})
    assert [r["symbol"] for r in resolved] == ["LAURUSLABS"]
    assert unresolved == ["Not In Master Limited"]


def test_resolution_preserves_every_parsed_field():
    rows = [{"company_name": "A2Z Infra Engineering Limited",
             "name_key": "A2ZINFRAENGINEERINGLIMITED",
             "promoter_pledged_pct": 99.68, "promoter_pledged_to_total_pct": 27.83,
             "pledged_shares": 49402301}]
    resolved, _ = resolve_symbols(rows, {"A2ZINFRAENGINEERINGLIMITED": "A2ZINFRA"})
    assert resolved[0]["promoter_pledged_pct"] == 99.68
    assert resolved[0]["promoter_pledged_to_total_pct"] == 27.83
    assert resolved[0]["pledged_shares"] == 49402301
    assert resolved[0]["symbol"] == "A2ZINFRA"


# ── command tags ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tag,expected", [
    ("UPDATE 2244", 2244), ("INSERT 0 17", 17), ("UPDATE 0", 0),
    ("", 0), (None, 0), ("SELECT", 0),
])
def test_rowcount_reads_the_command_tag(tag, expected):
    """The run is judged on how many rows were actually written, so the count comes
    from Postgres's own tag rather than from len(args)."""
    assert _rowcount(tag) == expected
