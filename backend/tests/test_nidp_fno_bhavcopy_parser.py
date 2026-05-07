"""Tests for the F&O bhavcopy CSV parser."""
from __future__ import annotations

from nidp.services.fno_bhavcopy.parser import parse_fno_bhavcopy


_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,"
    "XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,"
    "OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,"
    "OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty"
)


def _row(**kw):
    cols = {
        "TradDt": "2026-05-07", "BizDt": "2026-05-07", "Sgmt": "FO", "Src": "NSE",
        "FinInstrmTp": "OPTIDX", "FinInstrmId": "12345", "ISIN": "INE000A00000",
        "TckrSymb": "NIFTY", "SctySrs": "",
        "XpryDt": "2026-05-29", "FininstrmActlXpryDt": "2026-05-29",
        "StrkPric": "22000.0", "OptnTp": "CE", "FinInstrmNm": "NIFTY 29MAY26 22000 CE",
        "OpnPric": "100.0", "HghPric": "120.0", "LwPric": "95.0", "ClsPric": "110.0",
        "LastPric": "111.0", "PrvsClsgPric": "98.0", "UndrlygPric": "22050.0",
        "SttlmPric": "110.5", "OpnIntrst": "1500000", "ChngInOpnIntrst": "50000",
        "TtlTradgVol": "200000", "TtlTrfVal": "22000000.0", "TtlNbOfTxsExctd": "5000",
        "SsnId": "F1", "NewBrdLotQty": "50",
    }
    cols.update(kw)
    return ",".join(cols[k] for k in [
        "TradDt","BizDt","Sgmt","Src","FinInstrmTp","FinInstrmId","ISIN","TckrSymb",
        "SctySrs","XpryDt","FininstrmActlXpryDt","StrkPric","OptnTp","FinInstrmNm",
        "OpnPric","HghPric","LwPric","ClsPric","LastPric","PrvsClsgPric","UndrlygPric",
        "SttlmPric","OpnIntrst","ChngInOpnIntrst","TtlTradgVol","TtlTrfVal",
        "TtlNbOfTxsExctd","SsnId","NewBrdLotQty",
    ])


def test_parses_index_option_row():
    csv = _HEADER + "\n" + _row() + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert len(rows) == 1
    r = rows[0]
    assert r["instrument_type"] == "OPTIDX"
    assert r["ticker_symbol"]   == "NIFTY"
    assert r["expiry_date"]     == "2026-05-29"
    assert r["strike_price"]    == 22000.0
    assert r["option_type"]     == "CE"
    assert r["close_price"]     == 110.0
    assert r["open_interest"]   == 1500000
    assert r["change_in_oi"]    == 50000
    assert r["underlying_price"] == 22050.0


def test_parses_stock_future_row():
    csv = _HEADER + "\n" + _row(
        FinInstrmTp="FUTSTK", TckrSymb="RELIANCE",
        StrkPric="", OptnTp="",
    ) + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert len(rows) == 1
    r = rows[0]
    assert r["instrument_type"] == "FUTSTK"
    assert r["ticker_symbol"]   == "RELIANCE"
    assert r["strike_price"]    is None
    assert r["option_type"]     is None


def test_filters_non_fo_segment():
    csv = _HEADER + "\n" + _row(Sgmt="CM") + "\n" + _row() + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0]["instrument_type"] == "OPTIDX"


def test_filters_unknown_instrument_types():
    """Spread / strategy rows that aren't in the canonical 4 types
    should be dropped."""
    csv = _HEADER + "\n" + _row(FinInstrmTp="FUTSPREAD") + "\n" + _row() + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert [r["instrument_type"] for r in rows] == ["OPTIDX"]


def test_handles_legacy_date_format():
    csv = _HEADER + "\n" + _row(TradDt="07-MAY-2026", XpryDt="29-MAY-2026") + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert rows[0]["as_of_date"]  == "2026-05-07"
    assert rows[0]["expiry_date"] == "2026-05-29"


def test_drops_rows_with_no_ticker():
    csv = _HEADER + "\n" + _row(TckrSymb="") + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert rows == []


def test_drops_rows_with_invalid_option_type():
    """Anything other than CE/PE for an option must be NULL'd out."""
    csv = _HEADER + "\n" + _row(OptnTp="XX") + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert rows[0]["option_type"] is None


def test_empty_input():
    assert parse_fno_bhavcopy(b"") == []


def test_handles_blank_numeric_fields():
    csv = _HEADER + "\n" + _row(OpnIntrst="", ChngInOpnIntrst="", UndrlygPric="") + "\n"
    rows = parse_fno_bhavcopy(csv.encode("utf-8"))
    assert rows[0]["open_interest"]    is None
    assert rows[0]["change_in_oi"]     is None
    assert rows[0]["underlying_price"] is None
