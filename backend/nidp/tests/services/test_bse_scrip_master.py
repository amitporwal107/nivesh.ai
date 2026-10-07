"""Point-in-time BSE scrip master parsing (migration 153).

parse_bse_scrip_isin() already bridged scrip_code -> ISIN for the delivery
gap-fill. parse_bse_scrip_master() keeps three more columns from the same file
that only make sense dated: the BSE ticker, the trading/surveillance group on
that day, and the company name as filed.

These pin the parse against the same real 2026-08-17 BSE bhavcopy slice the
delivery-fallback tests use. The write path needs a live DB and is evidenced by
the staging run recorded in test_reports/bse_scrip_master.md.
"""
from __future__ import annotations

from pathlib import Path

from nidp.services.bhavcopy.parser import (parse_bse_scrip_isin,
                                           parse_bse_scrip_master)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "bse"
BHAV = (FIX / "bhavcopy_20260817_slice.csv").read_bytes()


def _by_scrip(rows, code):
    return next(r for r in rows if r["scrip_code"] == code)


# ── the three columns this function exists for ───────────────────────
def test_keeps_ticker_group_and_name():
    r = _by_scrip(parse_bse_scrip_master(BHAV), "500325")
    assert r["isin"] == "INE002A01018"
    assert r["bse_ticker"] == "RELIANCE"
    assert r["bse_group"] == "A"
    assert r["company_name"] == "RELIANCE INDUSTRIES LTD."


def test_every_row_carries_the_full_shape():
    """A missing key downstream would write NULL silently, so pin the shape."""
    want = {"scrip_code", "isin", "bse_ticker", "bse_group", "company_name"}
    rows = parse_bse_scrip_master(BHAV)
    assert rows
    assert all(set(r) == want for r in rows)


# ── regression guard against the existing bridge ─────────────────────
def test_is_a_strict_superset_of_the_isin_bridge():
    """The delivery gap-fill depends on parse_bse_scrip_isin. This must not
    drop a scrip it maps, nor disagree on an ISIN."""
    old = parse_bse_scrip_isin(BHAV)
    new = {r["scrip_code"]: r["isin"] for r in parse_bse_scrip_master(BHAV)}
    assert old, "fixture should map at least one scrip"
    assert set(old) <= set(new)
    assert all(new[c] == isin for c, isin in old.items())


# ── dedup, because the file repeats scrips ───────────────────────────
def test_deduplicates_repeated_scrip_codes():
    """The real file lists 500002 twice; the table PK is (date, scrip_code),
    so a duplicate would make executemany raise on conflict."""
    rows = parse_bse_scrip_master(BHAV)
    codes = [r["scrip_code"] for r in rows]
    assert len(codes) == len(set(codes))


# ── filters and degradation ──────────────────────────────────────────
def test_drops_fno_rows():
    header = (b"TradDt,Sgmt,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,FinInstrmNm\n")
    body = (header
            + b"2026-08-17,CM,STK,500325,INE002A01018,RELIANCE,A,RELIANCE INDUSTRIES LTD.\n"
            + b"2026-08-17,FO,FUTSTK,999999,INE002A01018,RELIANCE,A,RELIANCE FUT\n")
    rows = parse_bse_scrip_master(body)
    assert [r["scrip_code"] for r in rows] == ["500325"]


def test_keeps_a_row_whose_isin_is_missing():
    """The scrip still traded that day. Its later ABSENCE is the delisting
    signal, so dropping it here would fabricate an earlier delisting."""
    body = (b"TradDt,Sgmt,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,FinInstrmNm\n"
            b"2026-08-17,CM,STK,500325,,RELIANCE,A,RELIANCE INDUSTRIES LTD.\n")
    rows = parse_bse_scrip_master(body)
    assert len(rows) == 1
    assert rows[0]["isin"] is None
    assert rows[0]["bse_group"] == "A"


def test_empty_for_a_non_sebi_layout():
    """Parity with parse_bse_scrip_isin: a shape change degrades to 'nothing',
    never to wrong mappings."""
    assert parse_bse_scrip_master(b"SYMBOL,SERIES,CLOSE\nRELIANCE,EQ,1300\n") == []
    assert parse_bse_scrip_master(b"") == []


# ── BSE answers a holiday with HTML and HTTP 200, not a 404 ──────────
def test_holiday_html_is_not_a_parse_failure():
    """Observed on 2024-06-17: BSE served its landing page with HTTP 200 and
    14,287 bytes. Counting that as a failure would bury real failures among
    ~15 exchange holidays a year."""
    from nidp.services.bhavcopy.parser import looks_like_html
    assert looks_like_html(b'<!DOCTYPE html><html lang="en"><head>')
    assert looks_like_html(b'\n  <html>\n')
    assert not looks_like_html(BHAV)
    assert not looks_like_html(b"")
