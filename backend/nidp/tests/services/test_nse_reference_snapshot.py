"""Parsing of NSE's price-band, F&O and ETF lists (formats as published 2026-09-11)."""
from datetime import date

from nidp.services.event_calendar.backfill import LIVE_SINCE, split_by_live_coverage
from nidp.services.nse_reference_snapshot.service import build_rows, parse_bands, parse_etfs, parse_fno

SEC_LIST = ('Symbol,Series,Security Name,Band,Remarks\n'
            '21STCENMGM,EQ,21ST CENTURY MANAGEMENT SERVICES LIMITED,2,"-"\n'
            'RELIANCE,EQ,RELIANCE INDUSTRIES LIMITED,No Band,"-"\n'
            'SMALLCO,BE,SMALL CO LIMITED,5,"-"\n'
            'SMALLCO,EQ,SMALL CO LIMITED,10,"-"\n')
FO_LOTS = ('UNDERLYING                          ,SYMBOL    ,SEP-26     ,OCT-26     \n'
           'NIFTY 50                            ,NIFTY     ,65         ,65         \n'
           'Derivatives on Individual Securities,Symbol    ,           ,           \n'
           'RELIANCE INDUSTRIES LTD             ,RELIANCE  ,500        ,500        \n')
ETFS = ('Symbol,Underlying Asset,SecurityName,DateofListing,MarketLot,ISINNumber,FaceValue\n'
        'NIFTYBEES,Nifty 50,NIPINDETFNIFTYBEES,08-Jan-02,1,INF204KB14I2,1\n')


def test_bands_numeric_no_band_and_eq_preferred():
    b = parse_bands(SEC_LIST)
    assert b["21STCENMGM"] == ("EQ", "2", 2.0)
    assert b["RELIANCE"] == ("EQ", "No Band", None)
    assert b["SMALLCO"] == ("EQ", "10", 10.0)            # EQ row wins over BE


def test_fno_strips_padding_and_drops_section_header():
    f = parse_fno(FO_LOTS)
    assert "RELIANCE" in f and "Symbol" not in f and "NIFTY" in f


def test_rows_join_the_three_lists():
    rows = {r[0]: r for r in build_rows(parse_bands(SEC_LIST), parse_fno(FO_LOTS), parse_etfs(ETFS))}
    assert rows["RELIANCE"][4] is True and rows["RELIANCE"][2] is None   # F&O, no band
    assert rows["NIFTYBEES"][5] is True                                   # ETF kept even if not in sec_list
    assert "NIFTY" not in rows                                            # index never becomes a symbol row


def test_backfill_inserts_history_and_only_stamps_the_live_era():
    evs = [{"symbol": "A", "event_date": date(2026, 5, 18)}, {"symbol": "A", "event_date": LIVE_SINCE}]
    history, live_era = split_by_live_coverage(evs)
    assert [e["event_date"] for e in history] == [date(2026, 5, 18)]
    assert [e["event_date"] for e in live_era] == [LIVE_SINCE]
