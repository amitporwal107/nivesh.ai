"""Daily NSE reference snapshot → nidp.security_reference_daily.

These three lists decide whether a large move is even possible: a stock in a
5% band cannot rise 10% in a day, F&O stocks have no fixed band, and ETFs
trade in the EQ series without being companies. Stored per day because bands
are revised by surveillance and today's band must never be read onto history.
"""
from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from nidp.shared.config import NSE_ARCHIVES, NSE_WWW
from nidp.shared.sources.nse_fetcher import fetch_text
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SEC_LIST_URL = f"{NSE_ARCHIVES}/content/equities/sec_list.csv"
FO_LOTS_URL = f"{NSE_ARCHIVES}/content/fo/fo_mktlots.csv"
ETF_LIST_URL = f"{NSE_ARCHIVES}/content/equities/eq_etfseclist.csv"

# A short or empty file (maintenance page, partial download) must fail the run
# rather than write a snapshot that says nothing has a band or F&O.
_MIN_SEC_LIST, _MIN_FNO, _MIN_ETF = 1000, 100, 100
_IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class SnapshotReport:
    as_of_date: date
    run_id: str
    symbols: int = 0
    banded: int = 0
    fno: int = 0
    etf: int = 0
    rows_written: int = 0


def _rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]


def parse_bands(text: str) -> dict[str, tuple[str, str, Optional[float]]]:
    """symbol → (series, band as published, band % or None for 'No Band').
    Where a symbol is listed under several series, the EQ row wins."""
    out: dict[str, tuple[str, str, Optional[float]]] = {}
    for r in _rows(text):
        sym, series, band = r.get("Symbol", ""), r.get("Series", ""), r.get("Band", "")
        if not sym:
            continue
        try:
            pct: Optional[float] = float(band)
        except ValueError:
            pct = None
        if sym not in out or series == "EQ":
            out[sym] = (series, band, pct)
    return out


def parse_fno(text: str) -> set[str]:
    """Symbols with F&O contracts. Index rows (NIFTY, BANKNIFTY…) are kept
    here and fall away at the join, because they are not in sec_list."""
    return {r["SYMBOL"] for r in _rows(text) if r.get("SYMBOL") and r["SYMBOL"] != "Symbol"}


def parse_etfs(text: str) -> set[str]:
    return {r["Symbol"] for r in _rows(text) if r.get("Symbol")}


def build_rows(bands: dict, fno: set[str], etfs: set[str]) -> list[tuple]:
    rows = []
    for sym in sorted(set(bands) | etfs):
        series, band_raw, pct = bands.get(sym, (None, None, None))
        rows.append((sym, series, pct, band_raw, sym in fno, sym in etfs))
    return rows


_UPSERT_SQL = """
INSERT INTO nidp.security_reference_daily
    (as_of_date, symbol, series, price_band_pct, band_raw, fno_eligible, is_etf, source_run_id)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (as_of_date, symbol) DO UPDATE SET
    series         = EXCLUDED.series,
    price_band_pct = EXCLUDED.price_band_pct,
    band_raw       = EXCLUDED.band_raw,
    fno_eligible   = EXCLUDED.fno_eligible,
    is_etf         = EXCLUDED.is_etf,
    source_run_id  = EXCLUDED.source_run_id,
    ingested_at    = NOW()
"""


async def run(target_date: Optional[date] = None) -> SnapshotReport:
    as_of = target_date or datetime.now(_IST).date()
    report = SnapshotReport(as_of_date=as_of, run_id=str(uuid.uuid4()))
    referer = f"{NSE_WWW}/all-reports"
    bands = parse_bands((await fetch_text(SEC_LIST_URL, referer=referer))[0])
    fno = parse_fno((await fetch_text(FO_LOTS_URL, referer=referer))[0])
    etfs = parse_etfs((await fetch_text(ETF_LIST_URL, referer=referer))[0])
    if len(bands) < _MIN_SEC_LIST or len(fno) < _MIN_FNO or len(etfs) < _MIN_ETF:
        raise ValueError(f"reference lists look truncated: sec_list={len(bands)} "
                         f"fo_mktlots={len(fno)} etf={len(etfs)}")

    rows = build_rows(bands, fno, etfs)
    report.symbols = len(rows)
    report.banded = sum(1 for r in rows if r[2] is not None)
    report.fno = sum(1 for r in rows if r[4])
    report.etf = sum(1 for r in rows if r[5])
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_UPSERT_SQL, [(as_of, *r, uuid.UUID(report.run_id)) for r in rows])
    report.rows_written = len(rows)
    logger.info("nse_reference_snapshot %s", report)
    return report
