"""Parser for the Trendlyne bulk/block payload.

This stands in for a blocked exchange feed, so a silent parse failure looks exactly like "no deals
today" — which is why the NSE-exclusion and the escaping cases below are tests rather than trust.
"""
import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "ingest_bse_deals",
    pathlib.Path(__file__).resolve().parents[1] / "bin" / "ingest_bse_deals.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def payload(*rows: str) -> str:
    return "stockHeaders:\n  x | y\nstockData:\n  Foo Ltd., FOO, 1\ntableData:\n  " + ", ".join(rows)


R_BSE_BUY = '["HDFC MUTUAL FUND","Bulk","Purchase","2026-09-30",1315.0,2300000,2.0,"BSE"]'
R_BSE_SELL = '["BUSINESS EXCELLENCE TRUST III","Bulk","Sell","2026-09-30",1315.01,2328996,2.02,"BSE"]'
R_NSE = '["JUNOMONETA FINSOL PRIVATE LIMITED","Bulk","Purchase","2026-09-16",1288.14,590709,0.51,"NSE"]'
R_BLOCK = '["SOME FUND","Block","Purchase","2026-09-30",100.5,5000,0.1,"BSE"]'


# ── the exclusion that prevents double-counting ────────────────────────────────────

def test_nse_rows_are_excluded():
    """`source` is part of the primary key, so ingesting Trendlyne's NSE rows too would store
    every NSE deal a second time under a different source. The exchange feed owns NSE."""
    rows = mod.parse("MOLBIO", payload(R_BSE_BUY, R_NSE))
    assert len(rows) == 1
    assert rows[0][2] == "HDFC MUTUAL FUND"


def test_bse_rows_are_kept_with_the_right_fields():
    (d, sym, client, side, qty, price, seq, remarks, kind), = mod.parse("MOLBIO", payload(R_BSE_BUY))
    assert (d, sym, client, side) == ("2026-09-30", "MOLBIO", "HDFC MUTUAL FUND", "BUY")
    assert (qty, price, seq, kind) == (2300000, 1315.0, 1, "bulk")
    assert "pct_stake=2.0" in remarks and "exchange=BSE" in remarks


@pytest.mark.parametrize("action, expected", [
    ("Purchase", "BUY"), ("purchase", "BUY"), ("Buy", "BUY"),
    ("Sell", "SELL"), ("SALE", "SELL"),
])
def test_action_maps_to_the_table_vocabulary(action, expected):
    row = f'["X","Bulk","{action}","2026-09-30",10.0,100,0.1,"BSE"]'
    assert mod.parse("FOO", payload(row))[0][3] == expected


def test_an_unknown_action_is_dropped_not_guessed():
    assert mod.parse("FOO", payload('["X","Bulk","TRANSFER","2026-09-30",10.0,100,0.1,"BSE"]')) == []


def test_block_and_bulk_are_routed_apart():
    rows = mod.parse("FOO", payload(R_BSE_BUY, R_BLOCK))
    assert sorted(r[8] for r in rows) == ["block", "bulk"]


# ── deal_seq: part of the primary key ──────────────────────────────────────────────

def test_repeat_client_same_side_same_day_increments_the_sequence():
    """(date, symbol, client, deal_type, deal_seq, source) is the PK — without an incrementing
    seq the second genuine deal of the day would be silently discarded by ON CONFLICT."""
    rows = mod.parse("FOO", payload(R_BSE_BUY, R_BSE_BUY))
    assert [r[6] for r in rows] == [1, 2]


def test_different_sides_each_start_at_one():
    rows = mod.parse("FOO", payload(R_BSE_BUY, R_BSE_SELL))
    assert [r[6] for r in rows] == [1, 1]


# ── malformed input must degrade, not crash ────────────────────────────────────────

@pytest.mark.parametrize("bad, why", [
    ('["X","Bulk","Purchase","not-a-date",10.0,100,0.1,"BSE"]', "unparseable date"),
    ('["X","Bulk","Purchase","2026-09-30",10.0,100]', "too few fields"),
    ('[]', "empty"),
])
def test_malformed_rows_are_skipped(bad, why):
    assert mod.parse("FOO", payload(bad)) == [], why


def test_a_payload_without_tabledata_yields_nothing():
    assert mod.parse("FOO", "stockHeaders:\n  a | b\nstockData:\n  Foo") == []


def test_good_rows_survive_a_bad_neighbour():
    rows = mod.parse("FOO", payload('["X","Bulk","Purchase","bad",1.0,1,0.1,"BSE"]', R_BSE_BUY))
    assert len(rows) == 1 and rows[0][2] == "HDFC MUTUAL FUND"


# ── SQL generation ─────────────────────────────────────────────────────────────────

def test_apostrophes_in_a_client_name_are_escaped():
    """Indian registrant names contain apostrophes. Unescaped, this is broken SQL at best."""
    rows = mod.parse("FOO", payload('["O\'BRIEN CAPITAL","Bulk","Purchase","2026-09-30",10.0,100,0.1,"BSE"]'))
    sql = mod.sql_for(rows, "3317ad80-f879-4d45-8269-a4b6a416ad87")
    assert "O''BRIEN CAPITAL" in sql
    assert sql.count("'O''BRIEN CAPITAL'") == 1


def test_sql_carries_the_run_id_and_is_idempotent():
    rows = mod.parse("FOO", payload(R_BSE_BUY))
    sql = mod.sql_for(rows, "3317ad80-f879-4d45-8269-a4b6a416ad87")
    assert "'3317ad80-f879-4d45-8269-a4b6a416ad87'::uuid" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "source_run_id" in sql


def test_each_table_gets_its_own_statement():
    sql = mod.sql_for(mod.parse("FOO", payload(R_BSE_BUY, R_BLOCK)), "0" * 8 + "-0000-0000-0000-" + "0" * 12)
    assert "nidp.bulk_deals" in sql and "nidp.block_deals" in sql
    assert sql.count("INSERT INTO") == 2


def test_no_rows_produces_no_sql():
    assert mod.sql_for([], "x") == ""
