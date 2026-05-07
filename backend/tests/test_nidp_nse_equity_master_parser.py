"""Tests for the NSE EQUITY_L.csv parser.

The CSV is small but the parser is the gate — header drift, numeric
formatting, date format variants. These tests pin the contract.
"""
from __future__ import annotations

from nidp.services.nse_equity_master.parser import parse_equity_master


_CSV = (
    "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
    "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
    "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
    "INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5\n"
)


def test_parser_extracts_required_columns():
    rows = parse_equity_master(_CSV.encode("utf-8"))
    assert len(rows) == 3
    rel = next(r for r in rows if r["symbol"] == "RELIANCE")
    assert rel["company_name"] == "Reliance Industries Limited"
    assert rel["series"]       == "EQ"
    assert rel["isin"]         == "INE002A01018"
    assert rel["face_value"]   == 10.0
    assert rel["listing_date"] == "1995-11-29"


def test_parser_handles_bom_prefix():
    """NSE CSVs sometimes ship with a BOM. utf-8-sig must strip it
    without mangling the SYMBOL column header."""
    body = ("﻿" + _CSV).encode("utf-8")
    rows = parse_equity_master(body)
    assert {r["symbol"] for r in rows} == {"RELIANCE", "TCS", "INFY"}


def test_parser_numeric_coercion_handles_commas():
    csv = (
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        "ABC,Big Co,EQ,01-JAN-2020,\"1,000\",100,INE000A00000,10\n"
    )
    rows = parse_equity_master(csv.encode("utf-8"))
    assert rows[0]["paid_up_value"] == 1000.0
    assert rows[0]["market_lot"]    == 100


def test_parser_handles_unparseable_date_gracefully():
    csv = (
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        "XYZ,Test,EQ,not-a-date,10,1,INE111A11111,10\n"
    )
    rows = parse_equity_master(csv.encode("utf-8"))
    assert rows[0]["listing_date"] is None
    assert rows[0]["symbol"] == "XYZ"


def test_parser_ignores_blank_symbol_rows():
    csv = (
        "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE\n"
        ",,,,,,,\n"
        "ABC,Test Co,EQ,01-JAN-2020,10,1,INE000A00000,10\n"
    )
    rows = parse_equity_master(csv.encode("utf-8"))
    assert [r["symbol"] for r in rows] == ["ABC"]


def test_parser_empty_input():
    assert parse_equity_master(b"") == []


def test_parser_normalises_whitespace_in_headers():
    """NSE has occasionally shipped headers with trailing spaces.
    Our header normalisation must still find SYMBOL et al."""
    csv = (
        "SYMBOL ,NAME OF COMPANY,SERIES, DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE \n"
        "ABC,Test Co,EQ,01-JAN-2020,10,1,INE000A00000,10\n"
    )
    rows = parse_equity_master(csv.encode("utf-8"))
    assert rows and rows[0]["symbol"] == "ABC"
    assert rows[0]["listing_date"] == "2020-01-01"
