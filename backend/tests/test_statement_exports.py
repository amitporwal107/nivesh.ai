"""Unit tests for the uploaded-holdings parsers.

`helpers.parsing.parse_csv_holdings` / `parse_excel_holdings` delegate to
`helpers.statement_exports`, which reads broker holdings exports.

Every fixture here is SYNTHETIC: built in the test from the column names
WealthPulse documents for each broker, not from real broker downloads.
"""
import asyncio
import csv
import datetime
import io
import re
import struct
import zipfile

import openpyxl
import pytest
import xlrd
from fastapi import HTTPException

from helpers import holdings_reconcile
from helpers import statement_exports as se
from helpers.parsing import parse_csv_holdings, parse_excel_holdings
from helpers.statement_exports import parse_csv_statement, parse_excel_statement


def _csv(text: str, encoding: str = "utf-8") -> list:
    return asyncio.run(parse_csv_holdings(text.encode(encoding)))


def _xlsx_bytes(rows: list, extra_sheets: dict = None) -> bytes:
    """Build an .xlsx in memory; `rows` go on the active sheet."""
    wb = openpyxl.Workbook()
    for row in rows:
        wb.active.append(row)
    for title, sheet_rows in (extra_sheets or {}).items():
        ws = wb.create_sheet(title)
        for row in sheet_rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _xlsx(rows: list) -> list:
    return asyncio.run(parse_excel_holdings(_xlsx_bytes(rows)))


def _row(name, ticker="", asset_type="equity", quantity=0.0, buy_price=0.0,
         current_price=0.0, sector="Other", buy_date=""):
    return {
        "name": name, "ticker": ticker, "asset_type": asset_type, "quantity": quantity,
        "buy_price": buy_price, "current_price": current_price, "sector": sector,
        "buy_date": buy_date,
    }


# ── Backward compatibility ──────────────────────────────────────────────
# Written against the parsers as they were BEFORE statement_exports existed
# (header on row 1, the old column names) and passing on that code unchanged.

def test_legacy_csv_snake_case_template():
    rows = _csv(
        "name,ticker,asset_type,quantity,buy_price,current_price,sector,buy_date\n"
        "Reliance Industries,RELIANCE,equity,10,2400.50,2500,Energy,2024-01-15\n"
        "Parag Parikh Flexi Cap Fund,INF879O01019,Mutual_Fund,123.456,55.1,70.25,,\n"
        "HDFC Bank,,,5,,1600,,\n"
    )
    assert rows == [
        _row("Reliance Industries", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, "Energy", "2024-01-15"),
        _row("Parag Parikh Flexi Cap Fund", "INF879O01019", "mutual_fund", 123.456, 55.1, 70.25),
        _row("HDFC Bank", quantity=5.0, current_price=1600.0),
    ]


def test_legacy_csv_title_case_template():
    rows = _csv(
        "Name,Ticker,Type,Quantity,Buy Price,Current Price,Sector,Buy Date\n"
        "Infosys,INFY,Equity,7,1400,1500.5,IT,2023-06-01\n"
    )
    assert rows == [_row("Infosys", "INFY", "equity", 7.0, 1400.0, 1500.5, "IT", "2023-06-01")]


def test_legacy_csv_alternate_column_names():
    assert _csv(
        "STOCK,SYMBOL,QTY,Avg. Cost,ltp,Asset Type,Date\n"
        "Tata Motors,TATAMOTORS,20,600.25,950,equity,2022-03-10\n"
    ) == [_row("Tata Motors", "TATAMOTORS", "equity", 20.0, 600.25, 950.0, "Other", "2022-03-10")]

    # A mutual-fund sheet stays "equity" unless the file says otherwise: the
    # generic template never inferred the asset type from the ISIN.
    assert _csv(
        "Scheme Name,ISIN,Units,NAV,Current NAV\n"
        "Axis Bluechip Fund,INF846K01EW2,250.5,40,55.5\n"
    ) == [_row("Axis Bluechip Fund", "INF846K01EW2", "equity", 250.5, 40.0, 55.5)]

    assert _csv(
        "Fund,ISIN,type,Balance Units,cost,cmp\n"
        "SBI Small Cap Fund,INF200K01T51,mutual_fund,10,100,150\n"
    ) == [_row("SBI Small Cap Fund", "INF200K01T51", "mutual_fund", 10.0, 100.0, 150.0)]

    assert _csv(
        "scheme_name,symbol,qty,avg_price,Market Value\n"
        "Nippon India Growth Fund,NIPPON,3,2000,2500\n"
    ) == [_row("Nippon India Growth Fund", "NIPPON", "equity", 3.0, 2000.0, 2500.0)]

    assert _csv(
        "stock,ticker,units,cmp\n"
        "ITC,ITC,100,450\n"
    ) == [_row("ITC", "ITC", "equity", 100.0, 0.0, 450.0)]


def test_legacy_csv_trims_text_and_skips_rows_without_a_name():
    rows = _csv(
        "name,ticker,quantity,buy_price,current_price\n"
        "  Infosys  ,  INFY  ,7,1400,1500\n"
        ",ORPHAN,1,1,1\n"
        "   ,BLANKNAME,1,1,1\n"
        "\n"
        "Wipro,WIPRO,0,400,450\n"
    )
    # A zero-quantity row is kept, as it always was.
    assert rows == [
        _row("Infosys", "INFY", "equity", 7.0, 1400.0, 1500.0),
        _row("Wipro", "WIPRO", "equity", 0.0, 400.0, 450.0),
    ]


def test_legacy_csv_latin1_bytes():
    rows = _csv("name,quantity,buy_price\nNestlé India,2,20000\n", encoding="latin-1")
    assert rows == [_row("Nestlé India", quantity=2.0, buy_price=20000.0)]


def test_legacy_csv_column_priority_and_per_row_fallback():
    rows = _csv(
        "NAV,cost,ISIN,ticker,Scheme Name,name,quantity\n"
        "11,22,INE002A01018,RELIANCE,Scheme A,Name A,1\n"
        "33,,INE467B01029,,Scheme B,,2\n"
    )
    assert rows == [
        # name beats Scheme Name, ticker beats ISIN, cost beats NAV (CSV order)
        _row("Name A", "RELIANCE", "equity", 1.0, 22.0),
        # ...and a blank cell falls through to the next matching column
        _row("Scheme B", "INE467B01029", "equity", 2.0, 33.0),
    ]


def test_legacy_csv_name_only_header_and_unknown_columns():
    assert _csv("name\nReliance\nTCS\n") == [_row("Reliance"), _row("TCS")]
    assert _csv("Folio,Name,Remarks,Quantity\nF1,HDFC Bank,keep,4\n") == [
        _row("HDFC Bank", quantity=4.0),
    ]


def test_legacy_csv_empty_inputs_return_no_rows():
    assert _csv("") == []
    assert _csv("\n\n") == []
    assert _csv("name,ticker,quantity,buy_price,current_price\n") == []


def test_legacy_xlsx_template():
    rows = _xlsx([
        ["Name", "Ticker", "Asset Type", "Quantity", "Buy Price", "Current Price", "Sector", "Buy Date"],
        ["Reliance Industries", "RELIANCE", "Equity", 10, 2400.5, 2500, "Energy", datetime.datetime(2024, 1, 15)],
        ["Parag Parikh Flexi Cap Fund", "INF879O01019", "mutual_fund", 123.456, 55.1, 70.25, None, None],
        ["HDFC Bank", None, None, "5", None, 1600, None, "2023-02-01"],
    ])
    assert rows == [
        _row("Reliance Industries", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, "Energy", "2024-01-15 00:00:00"),
        _row("Parag Parikh Flexi Cap Fund", "INF879O01019", "mutual_fund", 123.456, 55.1, 70.25),
        _row("HDFC Bank", quantity=5.0, current_price=1600.0, buy_date="2023-02-01"),
    ]


def test_legacy_xlsx_alternate_column_names():
    assert _xlsx([
        ["Scheme Name", "ISIN", "Type", "Units", "NAV", "Current NAV"],
        ["Axis Bluechip Fund", "INF846K01EW2", "Mutual_Fund", 250.5, 40, 55.5],
    ]) == [_row("Axis Bluechip Fund", "INF846K01EW2", "mutual_fund", 250.5, 40.0, 55.5)]

    assert _xlsx([
        ["Fund", "Symbol", "Qty", "Avg. Cost", "CMP"],
        ["SBI Small Cap Fund", "SBISMALL", 10, 100, 150],
    ]) == [_row("SBI Small Cap Fund", "SBISMALL", "equity", 10.0, 100.0, 150.0)]

    assert _xlsx([
        ["  STOCK ", "TICKER", "BALANCE UNITS", "COST", "MARKET VALUE", "ASSET_TYPE", "BUY_DATE"],
        ["ITC", "ITC", 100, 300, 450, "equity", "2021-05-05"],
    ]) == [_row("ITC", "ITC", "equity", 100.0, 300.0, 450.0, "Other", "2021-05-05")]

    assert _xlsx([
        ["Scheme", "isin", "units", "avg price", "ltp", "date"],
        ["Kotak Flexicap Fund", "INF174K01LS2", 12, 50, 60, "2020-01-01"],
    ]) == [_row("Kotak Flexicap Fund", "INF174K01LS2", "equity", 12.0, 50.0, 60.0, "Other", "2020-01-01")]


def test_legacy_xlsx_column_priority():
    rows = _xlsx([
        ["cost", "nav", "isin", "symbol", "stock", "name", "qty"],
        [22, 11, "INE002A01018", "RELIANCE", "Stock A", "Name A", 1],
    ])
    # name beats stock, symbol beats isin, nav beats cost (Excel order)
    assert rows == [_row("Name A", "RELIANCE", "equity", 1.0, 11.0)]


def test_legacy_xlsx_skips_rows_without_a_name_and_ignores_unknown_columns():
    rows = _xlsx([
        ["Folio", "Name", "Quantity", "Buy Price", "Current Price", "Remarks"],
        ["F1", "Infosys", 7, 1400, 1500, "keep"],
        ["F2", None, 1, 1, 1, "no name"],
        ["F3", "   ", 1, 1, 1, "blank name"],
        [None, None, None, None, None, None],
        ["F4", "Wipro", 0, 400, 450, None],
    ])
    assert rows == [
        _row("Infosys", quantity=7.0, buy_price=1400.0, current_price=1500.0),
        _row("Wipro", quantity=0.0, buy_price=400.0, current_price=450.0),
    ]


def test_legacy_xlsx_name_only_header():
    assert _xlsx([["Name"], ["Reliance"], ["TCS"]]) == [_row("Reliance"), _row("TCS")]


def test_legacy_xlsx_empty_inputs_return_no_rows():
    assert _xlsx([]) == []
    assert _xlsx([["Name", "Ticker", "Quantity", "Buy Price", "Current Price"]]) == []


# ── Broker exports ──────────────────────────────────────────────────────

def _export(name, ticker, asset_type="equity", quantity=0.0, buy_price=0.0, current_price=0.0,
            sector="Other", isin=None, broker=None):
    """Expected row of a broker / MF export: the generic shape plus `isin` when
    the file gave one, and `source` + `broker` when the broker was recognised."""
    row = _row(name, ticker, asset_type, quantity, buy_price, current_price, sector)
    if isin:
        row["isin"] = isin
    if broker:
        row.update(source="broker_export", broker=broker)
    return row


def _biff4_xls(rows: list) -> bytes:
    """A legacy .xls assembled by hand: one BIFF4 worksheet stream.

    No .xls writer (xlwt) is installed, so this is the only way to give xlrd
    real bytes. It is a pre-OLE2 workbook, NOT the OLE2 container Excel 97+
    and brokers write — that container is only covered by the stubbed test
    further down.
    """
    def record(opcode, payload=b""):
        return struct.pack("<HH", opcode, len(payload)) + payload

    out = record(0x0409, struct.pack("<HHH", 0, 0x0010, 0))   # BOF: BIFF4 worksheet
    out += record(0x0042, struct.pack("<H", 1252))            # CODEPAGE
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            if value is None:
                continue
            if isinstance(value, str):
                raw = value.encode("cp1252")
                out += record(0x0204, struct.pack("<HHHH", r, c, 0, len(raw)) + raw)   # LABEL
            else:
                out += record(0x0203, struct.pack("<HHHd", r, c, 0, float(value)))     # NUMBER
    return out + record(0x000A)                                # EOF


ZERODHA_HEADER = [None, "Symbol", "ISIN", "Sector", "Qty Available", "Qty Discrepant", "Qty Long Term",
                  "Qty Pledged(Margin)", "Qty Pledged(Loan)", "Average Price", "Previous Closing Price",
                  "Unrealized P&L", "Unrealized P&L Pct"]
GROWW_HEADER = ["Stock Name", "ISIN", "Quantity", "Avg buy price", "Buy value", "Closing price",
                "Closing value", "Unrealised P&L"]
KOTAK_HEADER = ["Symbol", "ISIN", "Quantity", "Avg Price", "LTP", "Current Value", "P&L", "Change %"]


def test_zerodha_xlsx_preamble_blank_first_column_and_totals_row():
    st = parse_excel_statement(_xlsx_bytes([
        [None, "Client ID", "AB1234"],
        [None, "Equity Holdings Statement as on 2026-10-10"],
        [],
        [None, "Invested Value", 26357.5],
        [None, "Present Value", 28860],
        [],
        ZERODHA_HEADER,
        [None, "RELIANCE", "INE002A01018", "Energy", 10, 0, 10, 0, 0, 2400.5, 2500, 995, 4.14],
        [None, "NIFTYBEES", "INF204KB14I2", "ETF", 100, 0, 0, 0, 0, 250.25, 275.5, 2525, 10.09],
        [None, "TOTAL", "INE000T01011", None, 3, 0, 0, 0, 0, 100, 110, 30, 10],
        [None, "IDEA", "INE669E01016", "Telecom", 0, 0, 0, 0, 0, 12, 9, 0, 0],
        [None, "Total", None, None, None, None, None, None, None, None, None, 3550, None],
    ]))
    assert (st.layout, st.broker, st.broker_name, st.kind, st.header_row, st.skipped_rows) == (
        "zerodha", "zerodha", "Zerodha", "xlsx", 7, 1)
    assert st.holdings == [
        # ticker is the trading symbol; the ISIN travels in `isin`.
        _export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, "Energy", "INE002A01018", "zerodha"),
        # An INF ISIN is a mutual-fund scheme, an INE ISIN a company share.
        _export("NIFTYBEES", "NIFTYBEES", "mutual_fund", 100.0, 250.25, 275.5, "ETF", "INF204KB14I2", "zerodha"),
        # A share whose symbol happens to be TOTAL is kept: the row has an ISIN.
        _export("TOTAL", "TOTAL", "equity", 3.0, 100.0, 110.0, isin="INE000T01011", broker="zerodha"),
        # WealthPulse keeps zero-quantity rows for Zerodha, so do we.
        _export("IDEA", "IDEA", "equity", 0.0, 12.0, 9.0, "Telecom", "INE669E01016", "zerodha"),
    ]


def test_zerodha_quantity_available_spelling():
    st = parse_excel_statement(_xlsx_bytes([
        [None, "Symbol", "ISIN", "Sector", "Quantity Available", "Average Price", "Previous Closing Price"],
        [None, "TCS", "INE467B01029", "IT", 2, 3000, 3500],
    ]))
    assert st.holdings == [_export("TCS", "TCS", "equity", 2.0, 3000.0, 3500.0, "IT", "INE467B01029", "zerodha")]


def test_zerodha_kite_csv_is_not_taken_for_upstox():
    # Header as remembered from Kite's holdings download, not from WealthPulse.
    st = parse_csv_statement(
        b'"Instrument","Qty.","Avg. cost","LTP","Cur. val","P&L","Net chg.","Day chg."\n'
        b'"INFY",7,"1,400.00","1,500.50","10,503.50","703.50","7.18","0.52"\n')
    assert st.broker == "zerodha"
    assert st.holdings == [_export("INFY", "INFY", "equity", 7.0, 1400.0, 1500.5, broker="zerodha")]


def test_groww_xlsx_preamble_indian_numbers_totals_and_footer():
    st = parse_excel_statement(_xlsx_bytes([
        ["Holdings statement for stocks as on 10-10-2026"],
        ["Name", "Test User"],                  # a "Name" label above the table is not the header
        ["Unique Client Code", "1234567890"],
        [],
        GROWW_HEADER,
        ["HDFC Bank Limited", "INE040A01034", 5, 1500, 7500, 1600.5, 8002.5, 502.5],
        ["Tata Consultancy Services Limited", "ine467b01029", "1,200", "₹ 3,000.00", "36,00,000.00",
         "Rs. 3,500.00", "42,00,000.00", "6,00,000.00"],
        ["Sold Out Limited", "INE111A01011", 0, 0, 0, 0, 0, 0],
        ["Total", None, None, None, 3607500, None, 4208002.5, 600502.5],
        ["* Closing price is the previous trading day's close"],
    ]))
    assert (st.layout, st.broker, st.header_row, st.skipped_rows) == ("groww", "groww", 5, 2)
    assert st.holdings == [
        # A Groww export has no symbol column, so ticker falls back to the ISIN.
        _export("HDFC Bank Limited", "INE040A01034", "equity", 5.0, 1500.0, 1600.5,
                isin="INE040A01034", broker="groww"),
        _export("Tata Consultancy Services Limited", "INE467B01029", "equity", 1200.0, 3000.0, 3500.0,
                isin="INE467B01029", broker="groww"),
        # WealthPulse keeps zero-quantity rows for Groww, so do we.
        _export("Sold Out Limited", "INE111A01011", isin="INE111A01011", broker="groww"),
    ]


def test_groww_average_buy_price_spelling_and_price_derived_from_value():
    st = parse_excel_statement(_xlsx_bytes([
        ["Stock Name", "ISIN", "Quantity", "Average buy price", "Buy value", "Closing price", "Closing value"],
        ["Infosys Limited", "INE009A01021", 4, 1400, 5600, None, 6002],
    ]))
    assert st.holdings == [_export("Infosys Limited", "INE009A01021", "equity", 4.0, 1400.0, 1500.5,
                                   isin="INE009A01021", broker="groww")]


def test_upstox_csv_has_no_isin_and_drops_zero_quantity():
    st = parse_csv_statement(
        b"Instrument,Exchange,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.\n"
        b'NSE_EQ:RELIANCE,NSE,10,"2,400.50","2,500.00","25,000.00",995.00,4.14%\n'
        b'TATAMOTORS-EQ,NSE,"1,200",600.25,950.00,"11,40,000.00","4,19,700.00",58.27%\n'
        b"SOLDOUT,NSE,0,100,90,0,0,0%\n"
        b"NOQTY,NSE,,100,90,-,N/A,\n")
    assert (st.layout, st.broker, st.kind, st.skipped_rows) == ("upstox", "upstox", "csv", 2)
    assert st.holdings == [
        _export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, broker="upstox"),
        _export("TATAMOTORS", "TATAMOTORS", "equity", 1200.0, 600.25, 950.0, broker="upstox"),
    ]


def test_angel_one_xlsx_and_csv():
    st = parse_excel_statement(_xlsx_bytes([
        ["Script", "ISIN", "Sector", "Qty", "Avg Cost", "LTP", "Current Value", "P&L", "% P&L"],
        ["NSE:INFY-EQ", "INE009A01021", "IT", 7, 1400, 1500.5, 10503.5, 703.5, 7.18],
        ["SBIN", "INE062A01020", "Banking", 0, 500, 600, 0, 0, 0],
    ]))
    assert (st.layout, st.broker, st.broker_name, st.skipped_rows) == ("angel", "angel", "Angel One", 1)
    assert st.holdings == [_export("INFY", "INFY", "equity", 7.0, 1400.0, 1500.5, "IT", "INE009A01021", "angel")]

    st = parse_csv_statement(
        b"Scrip Name,ISIN,Qty,Avg Price,LTP,Cur. Value,P&L,% Change\n"
        b'INFY-EQ,INE009A01021,7,1400.00,1500.50,"10,503.50",703.50,7.18\n')
    assert st.broker == "angel"
    assert st.holdings == [_export("INFY", "INFY", "equity", 7.0, 1400.0, 1500.5,
                                   isin="INE009A01021", broker="angel")]


def test_icici_direct_csv():
    st = parse_csv_statement(
        b"Stock Symbol,Company Name,ISIN,Qty,Buy Avg Price,LTP,Buy Value,Current Value,Profit/Loss,% Change\n"
        b"RELIND,Reliance Industries Ltd,INE002A01018,10,2400.50,2500.00,24005.00,25000.00,995.00,4.14\n"
        b"HDFBAN,HDFC Bank Ltd,,5,1500,1600,7500,8000,500,6.67\n")
    assert (st.layout, st.broker, st.broker_name) == ("icicidirect", "icicidirect", "ICICI Direct")
    assert st.holdings == [
        _export("Reliance Industries Ltd", "RELIND", "equity", 10.0, 2400.5, 2500.0,
                isin="INE002A01018", broker="icicidirect"),
        # No ISIN in this row: the key is left out, not sent empty.
        _export("HDFC Bank Ltd", "HDFBAN", "equity", 5.0, 1500.0, 1600.0, broker="icicidirect"),
    ]
    assert "isin" not in st.holdings[1]


def test_hdfc_securities_xlsx():
    st = parse_excel_statement(_xlsx_bytes([
        ["HDFC Securities - Holdings Report"],
        ["Stock Symbol", "Company Name", "ISIN", "Qty", "Buy Avg", "LTP", "Current Value", "P&L"],
        ["TCS", "Tata Consultancy Services Ltd", "INE467B01029", 2, 3000, 3500, 7000, 1000],
    ]))
    assert (st.layout, st.broker, st.broker_name, st.header_row) == ("hdfcsec", "hdfcsec", "HDFC Securities", 2)
    assert st.holdings == [_export("Tata Consultancy Services Ltd", "TCS", "equity", 2.0, 3000.0, 3500.0,
                                   isin="INE467B01029", broker="hdfcsec")]


def test_kotak_csv():
    st = parse_csv_statement(
        b"Symbol,ISIN,Quantity,Avg Price,LTP,Current Value,P&L,Change %\n"
        b"RELIANCE,INE002A01018,10,2400.5,2500,25000,995,4.14\n"
        b"GOLDBEES,INF204KB17I5,50,50,55,2750,250,10\n")
    assert (st.layout, st.broker, st.broker_name) == ("kotak", "kotak", "Kotak Securities")
    assert st.holdings == [
        _export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, isin="INE002A01018", broker="kotak"),
        _export("GOLDBEES", "GOLDBEES", "mutual_fund", 50.0, 50.0, 55.0, isin="INF204KB17I5", broker="kotak"),
    ]


def test_dhan_csv():
    st = parse_csv_statement(
        b"Trading Symbol,ISIN,Exchange,Segment,Qty,Avg. Cost Price,Close Price,Cur. Value,Day P&L,Overall P&L\n"
        b"NSE-RELIANCE,INE002A01018,NSE,EQ,10,2400.50,2500.00,25000.00,50.00,995.00\n")
    assert (st.layout, st.broker, st.broker_name) == ("dhan", "dhan", "Dhan")
    assert st.holdings == [_export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0,
                                   isin="INE002A01018", broker="dhan")]


def test_5paisa_xlsx():
    st = parse_excel_statement(_xlsx_bytes([
        ["Scrip Name", "Scrip Code", "ISIN", "Qty", "Avg Rate", "LTP", "Current Value", "Gain/Loss"],
        ["RELIANCE", 500325, "INE002A01018", 10, 2400.5, 2500, 25000, 995],
        ["ITC", 500875, None, 100, 300, 450, 45000, 15000],
        ["Hindustan Unilever Ltd", 500696, None, 3, 2500, 2600, 7800, 300],
    ]))
    assert (st.layout, st.broker, st.broker_name) == ("fivepaisa", "fivepaisa", "5paisa")
    assert st.holdings == [
        _export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, isin="INE002A01018", broker="fivepaisa"),
        _export("ITC", "ITC", "equity", 100.0, 300.0, 450.0, broker="fivepaisa"),
        # A company name is not a trading symbol; with no ISIN either, the scrip code is all there is.
        _export("Hindustan Unilever Ltd", "500696", "equity", 3.0, 2500.0, 2600.0, broker="fivepaisa"),
    ]


def test_mf_central_xlsx_derives_unit_prices_and_keeps_folios_separate():
    header = ["Scheme Name", "AMC", "Category", "Sub Category", "Folio Number", "Source", "Units",
              "Invested Value", "Current Value", "Returns", "XIRR"]
    st = parse_excel_statement(_xlsx_bytes([
        ["Mutual Fund Holdings"],
        [],
        header,
        ["Parag Parikh Flexi Cap Fund - Direct Growth", "PPFAS", "Equity", "Flexi Cap", "123/45", "MFC",
         100, 5000, 7025, 2025, 15.2],
        ["Parag Parikh Flexi Cap Fund - Direct Growth", "PPFAS", "Equity", "Flexi Cap", "678/90", "MFC",
         50, "2,750.00", "3,512.50", 762.5, 14.1],
        ["Axis ELSS Tax Saver Fund", "Axis", "Equity", "ELSS", "555", "MFC", 0, 0, 0, 0, 0],
        ["Total", None, None, None, None, None, None, 7750, 10537.5, 2787.5, None],
    ]))
    assert (st.layout, st.broker, st.broker_name, st.header_row, st.skipped_rows) == (
        "mfcentral", "mfcentral", "MF Central", 3, 1)
    fund = "Parag Parikh Flexi Cap Fund - Direct Growth"
    assert st.holdings == [
        # No ISIN and no symbol column: ticker is empty and there is no `isin` key.
        _export(fund, "", "mutual_fund", 100.0, 50.0, 70.25, broker="mfcentral"),
        _export(fund, "", "mutual_fund", 50.0, 55.0, 70.25, broker="mfcentral"),
        # WealthPulse keeps zero-unit rows for mutual funds, so do we.
        _export("Axis ELSS Tax Saver Fund", "", "mutual_fund", broker="mfcentral"),
    ]

    # The same sheet with an ISIN column: it is carried in `isin` and used as the ticker.
    st = parse_excel_statement(_xlsx_bytes([
        header + ["ISIN"],
        [fund, "PPFAS", "Equity", "Flexi Cap", "123/45", "MFC", 100, 5000, 7025, 2025, 15.2, "INF879O01027"],
    ]))
    assert st.holdings == [_export(fund, "INF879O01027", "mutual_fund", 100.0, 50.0, 70.25,
                                   isin="INF879O01027", broker="mfcentral")]


# One header + one data row per broker, from the columns WealthPulse documents.
# The second field says whether that documented layout has an ISIN column.
_TCS = "INE467B01029"
BROKER_SAMPLES = [
    ("zerodha", True, ZERODHA_HEADER[1:], ["TCS", _TCS, "IT", 2, 0, 0, 0, 0, 3000, 3500, 1000, 16.6]),
    ("groww", True, GROWW_HEADER, ["Tata Consultancy Services Limited", _TCS, 2, 3000, 6000, 3500, 7000, 1000]),
    ("upstox", False, ["Instrument", "Exchange", "Qty.", "Avg. cost", "LTP", "Cur. val", "P&L", "Net chg."],
     ["TCS", "NSE", 2, 3000, 3500, 7000, 1000, 16.6]),
    ("angel", True, ["Script", "ISIN", "Sector", "Qty", "Avg Cost", "LTP", "Current Value", "P&L", "% P&L"],
     ["TCS", _TCS, "IT", 2, 3000, 3500, 7000, 1000, 16.6]),
    ("icicidirect", True, ["Stock Symbol", "Company Name", "ISIN", "Qty", "Buy Avg Price", "LTP", "Buy Value",
                           "Current Value", "Profit/Loss", "% Change"],
     ["TCS", "Tata Consultancy Services Ltd", _TCS, 2, 3000, 3500, 6000, 7000, 1000, 16.6]),
    ("hdfcsec", True, ["Stock Symbol", "Company Name", "ISIN", "Qty", "Buy Avg", "LTP", "Current Value", "P&L"],
     ["TCS", "Tata Consultancy Services Ltd", _TCS, 2, 3000, 3500, 7000, 1000]),
    ("kotak", True, KOTAK_HEADER, ["TCS", _TCS, 2, 3000, 3500, 7000, 1000, 16.6]),
    ("dhan", True, ["Trading Symbol", "ISIN", "Exchange", "Segment", "Qty", "Avg. Cost Price", "Close Price",
                    "Cur. Value", "Day P&L", "Overall P&L"],
     ["TCS", _TCS, "NSE", "EQ", 2, 3000, 3500, 7000, 10, 1000]),
    ("fivepaisa", True, ["Scrip Name", "Scrip Code", "ISIN", "Qty", "Avg Rate", "LTP", "Current Value", "Gain/Loss"],
     ["TCS", 532540, _TCS, 2, 3000, 3500, 7000, 1000]),
    ("mfcentral", False, ["Scheme Name", "AMC", "Category", "Sub Category", "Folio Number", "Source", "Units",
                          "Invested Value", "Current Value", "Returns", "XIRR"],
     ["Axis Bluechip Fund", "Axis", "Equity", "Large Cap", "123/45", "MFC", 2, 6000, 7000, 1000, 16.6]),
]


def test_broker_slugs_and_source_label_are_the_agreed_ones():
    assert [layout.id for layout in se._BROKERS] == [
        "zerodha", "groww", "upstox", "angel", "icicidirect", "hdfcsec", "kotak", "dhan", "fivepaisa", "mfcentral"]
    assert [sample[0] for sample in BROKER_SAMPLES] == [layout.id for layout in se._BROKERS]
    # save_holdings acts on this exact value.
    assert se._BROKER_EXPORT_SOURCE == holdings_reconcile.BROKER_EXPORT_SOURCE == "broker_export"


@pytest.mark.parametrize("kind", ["csv", "xlsx", "xls"])
@pytest.mark.parametrize("slug, has_isin, header, data", BROKER_SAMPLES, ids=[s[0] for s in BROKER_SAMPLES])
def test_every_broker_row_carries_source_broker_and_isin(slug, has_isin, header, data, kind):
    if kind == "csv":
        buf = io.StringIO()
        csv.writer(buf).writerows([header, data])
        st = parse_csv_statement(buf.getvalue().encode("utf-8"))
    elif kind == "xlsx":
        st = parse_excel_statement(_xlsx_bytes([header, data]))
    else:
        st = parse_excel_statement(_biff4_xls([header, data]))

    assert (st.layout, st.broker, st.kind) == (slug, slug, kind)
    (row,) = st.holdings
    assert (row["source"], row["broker"]) == ("broker_export", slug)
    assert row.get("isin") == (_TCS if has_isin else None)
    assert ("isin" in row) == has_isin
    # ticker: the trading symbol when the export has one, else the ISIN, else empty.
    assert row["ticker"] == {"groww": _TCS, "mfcentral": ""}.get(slug, "TCS")
    assert (row["quantity"], row["buy_price"], row["current_price"]) == (2.0, 3000.0, 3500.0)
    assert set(row) == set(_row("x")) | {"source", "broker"} | ({"isin"} if has_isin else set())


def test_generic_rows_carry_none_of_the_broker_keys():
    st = parse_csv_statement(b"name,ISIN,quantity\nReliance,INE002A01018,10\n", "zerodha_holdings.csv")
    assert (st.layout, st.broker, st.broker_name) == ("generic", None, None)
    xlsx = parse_excel_statement(_xlsx_bytes([["Name", "ISIN", "Quantity"], ["Reliance", "INE002A01018", 10]]))
    for holdings in (st.holdings, xlsx.holdings):
        assert holdings == [_row("Reliance", "INE002A01018", quantity=10.0)]
        assert not {"source", "broker", "isin"} & set(holdings[0])


def test_unidentified_table_is_read_but_not_attributed_to_a_broker():
    body = (b"Symbol,ISIN,Quantity,Avg Price,LTP,Current Value\n"
            b"RELIANCE,INE002A01018,10,2400.5,2500,25000\n"
            b"SOLD,INE111A01011,0,10,9,0\n")
    st = parse_csv_statement(body, "holdings.csv")
    assert (st.layout, st.broker, st.broker_name) == ("unidentified", None, None)
    assert st.holdings == [
        _export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0, isin="INE002A01018"),
        _export("SOLD", "SOLD", "equity", 0.0, 10.0, 9.0, isin="INE111A01011"),
    ]
    assert not any({"source", "broker"} & set(h) for h in st.holdings)

    # The file name is a secondary hint: it names a table the columns leave anonymous.
    hinted = parse_csv_statement(body, "kotak_holdings_oct.csv")
    assert (hinted.layout, hinted.broker) == ("kotak", "kotak")
    assert hinted.holdings == [_export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0,
                                       isin="INE002A01018", broker="kotak")]


def test_columns_beat_the_file_name():
    groww = _xlsx_bytes([GROWW_HEADER, ["HDFC Bank Limited", "INE040A01034", 5, 1500, 7500, 1600.5, 8002.5, 502.5]])
    assert parse_excel_statement(groww, "zerodha_holdings.xlsx").broker == "groww"


@pytest.mark.parametrize("filename, slug", [
    ("dhan_holdings.csv", "dhan"), ("dhananjay_holdings.csv", None), ("5paisa-holdings.xlsx", "fivepaisa"),
    ("icicidirect_2026.csv", "icicidirect"), ("hdfcsec_portfolio.xls", "hdfcsec"), ("kite_holdings.csv", "zerodha"),
    ("my mf holdings.xlsx", "mfcentral"), ("holdings.csv", None), ("", None),
])
def test_file_name_hint(filename, slug):
    layout = se._layout_from_filename(filename)
    assert (layout.id if layout else None) == slug


# ── Headers, numbers, text ──────────────────────────────────────────────

@pytest.mark.parametrize("header, key", [
    ("Qty.", "qty"), ("  AVG.  COST ", "avg cost"), ("avg_cost", "avg cost"), ("Cur. val", "cur val"),
    ("Net chg.", "net chg"), ("Unrealized P&L Pct", "unrealized p&l pct"), ("% P&L", "% p&l"),
    ("Scheme\xa0Name", "scheme name"), ("L.T.P.", "ltp"), (None, ""), (500325.0, "500325"),
])
def test_header_normalisation(header, key):
    assert se._norm(header) == key


def test_header_punctuation_and_case_do_not_matter():
    assert _csv("NAME,QTY.,Avg. Cost,L.T.P.\nReliance,10,2400.5,2500\n") == [
        _row("Reliance", quantity=10.0, buy_price=2400.5, current_price=2500.0)]


@pytest.mark.parametrize("cell, expected", [
    ("1,23,456.78", 123456.78), ("₹ 2,400.50", 2400.5), ("Rs. 500", 500.0), ("Rs.1,000", 1000.0),
    ("INR 75", 75.0), ("$12.5", 12.5), ("(1,200.00)", -1200.0), ("-45.5", -45.5), ("12.5%", 12.5),
    (" 10 ", 10.0), (10, 10.0), (2400.5, 2400.5),
    ("", None), ("   ", None), ("-", None), ("--", None), ("N/A", None), ("na", None), ("nil", None),
    (None, None), ("abc", None), ("nan", None), ("inf", None), (float("nan"), None), (True, None),
])
def test_number_cleaning(cell, expected):
    assert se._num(cell) == expected


@pytest.mark.parametrize("raw, symbol", [
    ("NSE:RELIANCE-EQ", "RELIANCE"), ("NSE_EQ:RELIANCE", "RELIANCE"), ("BSE-RELIANCE", "RELIANCE"),
    ("RELIANCE_EQ", "RELIANCE"), ("SILVERBEES-E", "SILVERBEES"), ("bajaj-auto", "BAJAJ-AUTO"),
    ("EMBASSY-RR", "EMBASSY-RR"), ("M&M", "M&M"),
])
def test_symbol_cleaning(raw, symbol):
    assert se._clean_symbol(raw) == symbol


@pytest.mark.parametrize("label, is_summary", [
    ("Total", True), ("Grand Total:", True), ("Sub-Total", True), ("Total Invested Value", True),
    ("Current Value", True), ("Net P&L", True),
    ("Total Transport Systems Ltd", False), ("Bajaj Holdings", False), ("HDFC Bank", False),
])
def test_summary_row_labels(label, is_summary):
    assert se._is_summary_label(label) is is_summary


def test_generic_template_below_preamble_rows_with_indian_numbers():
    rows = _csv(
        "My holdings\n"
        "as on 10-10-2026\n"
        "\n"
        "Name,Ticker,Quantity,Buy Price,Current Price\n"
        'Reliance,RELIANCE,"1,000","₹2,400.50",2500\n'
    )
    assert rows == [_row("Reliance", "RELIANCE", "equity", 1000.0, 2400.5, 2500.0)]


def test_generic_template_skips_totals_rows():
    # The one deliberate change for a sheet that imported before: "Total" is no longer a holding.
    assert _csv("name,quantity,current_price\nReliance,10,2500\nTotal,10,25000\nGrand Total:,,25000\n") == [
        _row("Reliance", quantity=10.0, current_price=2500.0)]


# ── CSV decoding ────────────────────────────────────────────────────────

def test_csv_utf8_bom():
    st = parse_csv_statement(("﻿" + ",".join(KOTAK_HEADER) + "\n"
                              "RELIANCE,INE002A01018,10,2400.5,2500,25000,995,4.14\n").encode("utf-8"))
    assert (st.broker, len(st.holdings)) == ("kotak", 1)
    assert _csv("﻿name,quantity\r\nReliance,10\r\n") == [_row("Reliance", quantity=10.0)]


def test_csv_cp1252_then_latin1():
    assert _csv("name,quantity\nNestlé India – A,2\n", encoding="cp1252") == [
        _row("Nestlé India – A", quantity=2.0)]
    # 0x81 is undefined in cp1252, so these bytes fall through to latin-1.
    assert asyncio.run(parse_csv_holdings(b"name,quantity\nCaf\xe9 \x81 Ltd,3\n")) == [
        _row("Café \x81 Ltd", quantity=3.0)]


# ── Empty, header-only and unrecognised files ───────────────────────────

def test_empty_file_gives_no_rows_and_no_layout():
    for st in (parse_csv_statement(b""), parse_csv_statement(b" \n\n"), parse_excel_statement(_xlsx_bytes([]))):
        assert (st.holdings, st.layout, st.broker, st.header_row) == ([], None, None, 0)


def test_recognised_export_without_rows_is_empty_not_an_error():
    st = parse_excel_statement(_xlsx_bytes([["Equity holdings"], ZERODHA_HEADER]))
    assert (st.holdings, st.layout, st.broker, st.header_row) == ([], "zerodha", "zerodha", 2)
    st = parse_excel_statement(_xlsx_bytes([ZERODHA_HEADER, [None, "Total", None, None, None]]))
    assert (st.holdings, st.skipped_rows) == ([], 1)


@pytest.mark.parametrize("parse, content", [
    (parse_csv_statement, b"foo,bar\n1,2\n"),
    (parse_csv_statement, b"Dear customer, please find your statement attached.\n"),
    # A tradebook has a symbol and a quantity but no holdings price / value column.
    (parse_csv_statement, b"symbol,isin,trade_date,trade_type,quantity,price\n"
                          b"INFY,INE009A01021,2026-10-01,buy,5,1500\n"),
    (parse_excel_statement, _xlsx_bytes([["Report"], ["foo", "bar"], [1, 2]])),
    (parse_excel_statement, _biff4_xls([["Report"], ["foo", "bar"], [1, 2]])),
], ids=["csv-other-columns", "csv-prose", "csv-tradebook", "xlsx-other-columns", "xls-other-columns"])
def test_unrecognised_layout_is_a_400_naming_the_columns_looked_for(parse, content):
    with pytest.raises(HTTPException) as err:
        parse(content)
    assert err.value.status_code == 400
    detail = err.value.detail
    assert detail.startswith("Could not find a holdings table in this file.")
    for column in ("symbol", "scheme name", "quantity", "units", "average price", "current value"):
        assert column in detail


# ── Excel reading ───────────────────────────────────────────────────────

def test_xlsx_header_on_a_sheet_other_than_the_active_one():
    content = _xlsx_bytes(
        [["Portfolio summary"], ["Generated on", "2026-10-10"]],
        extra_sheets={"Equity": [ZERODHA_HEADER, [None, "TCS", "INE467B01029", "IT", 2, 0, 0, 0, 0, 3000, 3500, 1000, 16.6]]},
    )
    st = parse_excel_statement(content)
    assert (st.broker, [h["ticker"] for h in st.holdings]) == ("zerodha", ["TCS"])


def test_xlsx_with_a_wrong_dimension_tag_is_read_in_full():
    good = _xlsx_bytes([KOTAK_HEADER,
                        ["RELIANCE", "INE002A01018", 10, 2400.5, 2500, 25000, 995, 4.14],
                        ["TCS", "INE467B01029", 2, 3000, 3500, 7000, 1000, 16.6]])
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                # Some exporters declare the sheet as a single cell; openpyxl's read-only
                # mode then yields only A1 unless the dimensions are reset.
                data, replaced = re.subn(rb'<dimension ref="[^"]*"', b'<dimension ref="A1"', data)
                assert replaced == 1
            dst.writestr(item, data)
    st = parse_excel_statement(out.getvalue())
    assert [h["ticker"] for h in st.holdings] == ["RELIANCE", "TCS"]


def test_xls_is_read_through_xlrd():
    content = _biff4_xls([
        ["Holdings as on 10-10-2026"],
        [],
        KOTAK_HEADER,
        ["RELIANCE", "INE002A01018", 10, 2400.5, 2500, 25000, 995, 4.14],
        ["Total", None, None, None, None, 25000, 995, None],
    ])
    st = parse_excel_statement(content, "holdings.xls")
    assert (st.kind, st.broker, st.header_row, st.skipped_rows) == ("xls", "kotak", 3, 1)
    assert st.holdings == [_export("RELIANCE", "RELIANCE", "equity", 10.0, 2400.5, 2500.0,
                                   isin="INE002A01018", broker="kotak")]
    # The old entry point takes the same bytes (it used to hand them to openpyxl and crash).
    assert asyncio.run(parse_excel_holdings(content)) == st.holdings

    generic = _biff4_xls([["Name", "Ticker", "Quantity", "Buy Price"], ["Infosys", "INFY", 7, 1400]])
    assert asyncio.run(parse_excel_holdings(generic)) == [_row("Infosys", "INFY", "equity", 7.0, 1400.0)]


def test_ole2_xls_bytes_are_dispatched_to_xlrd(monkeypatch):
    # STUB — not a real workbook. No .xls writer is installed, so an OLE2 file
    # cannot be built here; xlrd.open_workbook is replaced to prove the dispatch
    # and the cell-type handling. It does NOT prove xlrd opens a real broker .xls.
    cell = xlrd.sheet.Cell

    class FakeSheet:
        nrows = 3
        rows = [
            [cell(xlrd.XL_CELL_TEXT, "Name"), cell(xlrd.XL_CELL_TEXT, "Quantity"),
             cell(xlrd.XL_CELL_TEXT, "Buy Price"), cell(xlrd.XL_CELL_TEXT, "Buy Date")],
            [cell(xlrd.XL_CELL_TEXT, "Infosys"), cell(xlrd.XL_CELL_NUMBER, 7.0),
             cell(xlrd.XL_CELL_ERROR, 42), cell(xlrd.XL_CELL_DATE, 45306.0)],
            [cell(xlrd.XL_CELL_EMPTY, ""), cell(xlrd.XL_CELL_BLANK, ""),
             cell(xlrd.XL_CELL_EMPTY, ""), cell(xlrd.XL_CELL_EMPTY, "")],
        ]

        def row(self, r):
            return self.rows[r]

    class FakeBook:
        datemode = 0

        def sheets(self):
            return [FakeSheet()]

    seen = {}

    def fake_open_workbook(file_contents=None, **kwargs):
        seen["content"] = file_contents
        return FakeBook()

    monkeypatch.setattr(xlrd, "open_workbook", fake_open_workbook)
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    st = parse_excel_statement(ole2)
    assert seen["content"] == ole2
    assert (st.kind, st.layout) == ("xls", "generic")
    # The error cell reads as blank (not as its error code 42) and the date cell as a date.
    assert st.holdings == [_row("Infosys", quantity=7.0, buy_date="2024-01-15 00:00:00")]


def test_damaged_workbooks_are_a_400_not_a_crash():
    for content in (b"PK\x03\x04" + b"not really a zip" * 10,
                    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600):
        with pytest.raises(HTTPException) as err:
            parse_excel_statement(content)
        assert err.value.status_code == 400
        assert err.value.detail.startswith("Could not read this Excel file.")


# ── Routes ──────────────────────────────────────────────────────────────

@pytest.fixture
def upload_client(monkeypatch):
    """The two upload routes on a bare app, with real upload validation and parsing.

    STUBS — not the real system: the session lookup, save_holdings and the
    dashboard-cache invalidation are replaced, so nothing here touches MongoDB
    or Redis and nothing is persisted. `saved` records what the route handed
    to save_holdings.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.upload as upload

    saved = []

    async def fake_user(request):
        return {"user_id": "user_test"}

    async def fake_save_holdings(user_id, parsed, file_type, task_id=None, portfolio_id=""):
        saved.append({"user_id": user_id, "rows": parsed, "file_type": file_type, "portfolio_id": portfolio_id})
        return [{"holding_id": f"hold_{i}", "name": h["name"], "asset_type": h["asset_type"],
                 "quantity": h["quantity"]} for i, h in enumerate(parsed)]

    async def fake_invalidate(user_id):
        return None

    monkeypatch.setattr(upload, "get_current_user", fake_user)
    monkeypatch.setattr(upload, "save_holdings", fake_save_holdings)
    monkeypatch.setattr(upload.dashboard_cache, "invalidate", fake_invalidate)
    app = FastAPI()
    app.include_router(upload.router)
    return TestClient(app), saved


def test_upload_route_reports_the_broker_slug_and_keeps_existing_keys(upload_client):
    client, saved = upload_client
    content = _xlsx_bytes([["Equity holdings"], ZERODHA_HEADER,
                           [None, "TCS", "INE467B01029", "IT", 2, 0, 0, 0, 0, 3000, 3500, 1000, 16.6]])
    res = client.post("/api/portfolio/upload", files={"file": ("Holdings.XLSX", content, "application/octet-stream")})
    assert res.status_code == 200, res.text
    assert res.json() == {
        "message": "1 holdings imported from Excel",
        "count": 1,
        "holdings": [{"holding_id": "hold_0", "name": "TCS", "asset_type": "equity", "quantity": 2.0}],
        "broker": "zerodha",
        "broker_name": "Zerodha",
        "format": "zerodha",
    }
    assert saved == [{"user_id": "user_test", "file_type": "Excel", "portfolio_id": "", "rows": [
        _export("TCS", "TCS", "equity", 2.0, 3000.0, 3500.0, "IT", "INE467B01029", "zerodha")]}]


def test_upload_raw_route_generic_csv(upload_client):
    client, saved = upload_client
    res = client.post(
        "/api/portfolio/upload-raw",
        content=b"name,ticker,quantity,buy_price,current_price\nReliance,RELIANCE,10,2400.5,2500\n",
        headers={"X-Filename": "My Portfolio.csv", "X-Portfolio-Id": "pf_1"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {
        "message": "1 holdings imported from CSV",
        "count": 1,
        "holdings": [{"holding_id": "hold_0", "name": "Reliance", "asset_type": "equity", "quantity": 10.0}],
        "broker": None,
        "broker_name": None,
        "format": "generic",
    }
    # Same rows the old parser produced: no source / broker / isin.
    assert saved == [{"user_id": "user_test", "file_type": "CSV", "portfolio_id": "pf_1", "rows": [
        _row("Reliance", "RELIANCE", "equity", 10.0, 2400.5, 2500.0)]}]


def test_upload_routes_answer_400_for_an_unrecognised_file(upload_client):
    client, saved = upload_client
    body = b"foo,bar\n1,2\n"
    for res in (
        client.post("/api/portfolio/upload", files={"file": ("notes.csv", body, "text/csv")}),
        client.post("/api/portfolio/upload-raw", content=body, headers={"X-Filename": "notes.csv"}),
    ):
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert detail.startswith("Could not find a holdings table in this file.")
        assert "quantity" in detail and "symbol" in detail
    assert saved == []


def test_upload_routes_keep_the_no_holdings_response_for_a_recognised_empty_file(upload_client):
    client, saved = upload_client
    header_only = (",".join(KOTAK_HEADER) + "\n").encode("utf-8")
    detected = {"broker": "kotak", "broker_name": "Kotak Securities", "format": "kotak"}

    res = client.post("/api/portfolio/upload", files={"file": ("kotak.csv", header_only, "text/csv")})
    assert res.status_code == 200
    assert res.json() == {"message": "No holdings found in the uploaded file", "count": 0, "holdings": [], **detected}

    res = client.post("/api/portfolio/upload-raw", content=header_only, headers={"X-Filename": "kotak.csv"})
    assert res.status_code == 200
    assert res.json() == {"message": "No holdings found", "count": 0, "holdings": [], **detected}
    assert saved == []


def test_upload_route_hands_an_xls_to_the_xls_reader(upload_client):
    client, saved = upload_client
    # Passes the .xls magic-byte check in upload_validation but is not a workbook,
    # so the answer comes from the xlrd reader: a 400, where it used to be an
    # unhandled openpyxl BadZipFile.
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    res = client.post("/api/portfolio/upload", files={"file": ("holdings.xls", ole2, "application/vnd.ms-excel")})
    assert res.status_code == 400
    assert res.json()["detail"].startswith("Could not read this Excel file.")
    assert saved == []
