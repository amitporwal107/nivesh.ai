"""NSE bhavcopy CSV parser — handles both legacy and post-2024 formats.

Two formats coexist in NSE archives:

A. Pre-Jul-2024 ("legacy"):
   SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,
   TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN

B. Post-Jul-2024 ("F&O-merged"):
   TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,
   XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,
   HghPric,LwPric,ClsgPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,
   OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,
   SsnId,NewBrdLotQty,Rmks,Rsvd1..4

We auto-detect by header presence. Equity rows in format-B are
filtered to FinInstrmTp ∈ {"STK","EQ"} and Sgmt = "CM" so F&O rows
don't slip through.

Pure function — no I/O. Easy to golden-file test.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _to_date_iso(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _f(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(s: Optional[str]) -> Optional[int]:
    f = _f(s)
    return int(f) if f is not None else None


def _detect_format(headers: list[str]) -> str:
    h = {x.strip() for x in headers}
    # Format B (post-2024 unified CM file). NSE renamed the close column
    # mid-2025 from `ClsgPric` → `ClsPric` (dropped the 'g') but kept
    # `PrvsClsgPric` for previous close — accept either.
    if "TckrSymb" in h and ({"ClsPric", "ClsgPric"} & h):
        return "B"
    if "SYMBOL" in h and "CLOSE" in h:
        return "A"
    raise ValueError(f"Unknown bhavcopy header: {headers!r}")


def _parse_legacy(rows: list[list[str]], headers: list[str]) -> list[dict[str, Any]]:
    idx = {h.strip(): i for i, h in enumerate(headers)}
    out: list[dict[str, Any]] = []
    for r in rows:
        if not r or all(not c.strip() for c in r):
            continue
        try:
            symbol = r[idx["SYMBOL"]].strip().upper()
            series = r[idx["SERIES"]].strip().upper()
        except (KeyError, IndexError):
            continue
        if not symbol or not series:
            continue
        out.append({
            "as_of_date":  _to_date_iso(r[idx.get("TIMESTAMP")]) if "TIMESTAMP" in idx else None,
            "symbol":      symbol,
            "series":      series,
            "isin":        r[idx["ISIN"]].strip() if "ISIN" in idx else None,
            "prev_close":  _f(r[idx.get("PREVCLOSE")] if "PREVCLOSE" in idx else None),
            "open_price":  _f(r[idx.get("OPEN")] if "OPEN" in idx else None),
            "high_price":  _f(r[idx.get("HIGH")] if "HIGH" in idx else None),
            "low_price":   _f(r[idx.get("LOW")] if "LOW" in idx else None),
            "close_price": _f(r[idx.get("CLOSE")] if "CLOSE" in idx else None),
            "last_price":  _f(r[idx.get("LAST")] if "LAST" in idx else None),
            "avg_price":   None,
            "volume":      _i(r[idx.get("TOTTRDQTY")] if "TOTTRDQTY" in idx else None),
            "turnover":    _f(r[idx.get("TOTTRDVAL")] if "TOTTRDVAL" in idx else None),
            "trades":      _i(r[idx.get("TOTALTRADES")] if "TOTALTRADES" in idx else None),
        })
    return out


def _parse_post2024(rows: list[list[str]], headers: list[str]) -> list[dict[str, Any]]:
    idx = {h.strip(): i for i, h in enumerate(headers)}

    def col(name: str) -> Optional[int]:
        return idx.get(name)

    out: list[dict[str, Any]] = []
    for r in rows:
        if not r or all(not c.strip() for c in r):
            continue
        try:
            sgmt = (r[col("Sgmt")] or "").strip().upper() if col("Sgmt") is not None else ""
            instr_tp = (r[col("FinInstrmTp")] or "").strip().upper() if col("FinInstrmTp") is not None else ""
        except IndexError:
            continue

        # Equity-only filter: Sgmt=CM, FinInstrmTp∈{STK,EQ,SHARES}.
        if sgmt and sgmt != "CM":
            continue
        if instr_tp and instr_tp not in ("STK", "EQ", "SHARES"):
            continue

        try:
            symbol = (r[col("TckrSymb")] or "").strip().upper()
            series = (r[col("SctySrs")] or "").strip().upper()
        except (TypeError, IndexError):
            continue
        if not symbol or not series:
            continue

        def get(name: str) -> Optional[str]:
            i = col(name)
            return r[i] if i is not None and i < len(r) else None

        out.append({
            "as_of_date":  _to_date_iso(get("TradDt")),
            "symbol":      symbol,
            "series":      series,
            "isin":        (get("ISIN") or "").strip() or None,
            "prev_close":  _f(get("PrvsClsgPric") or get("PrvsClsPric")),
            "open_price":  _f(get("OpnPric")),
            "high_price":  _f(get("HghPric")),
            "low_price":   _f(get("LwPric")),
            "close_price": _f(get("ClsPric") or get("ClsgPric")),
            "last_price":  _f(get("LastPric")),
            "avg_price":   None,
            "volume":      _i(get("TtlTradgVol")),
            "turnover":    _f(get("TtlTrfVal")),
            "trades":      _i(get("TtlNbOfTxsExctd")),
        })
    return out


def parse_bhavcopy(body: bytes) -> list[dict[str, Any]]:
    """Parse raw CSV bytes (already extracted from .zip) into rows.

    Auto-detects pre/post-Jul-2024 format by header.
    """
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []
    fmt = _detect_format(headers)
    body_rows = list(reader)
    if fmt == "A":
        return _parse_legacy(body_rows, headers)
    return _parse_post2024(body_rows, headers)


def parse_bse_scrip_isin(body: bytes) -> dict[str, str]:
    """Extract {BSE scrip code -> ISIN} from a BSE bhavcopy CSV.

    BSE's delivery file identifies rows by scrip code alone — no ISIN, no
    ticker — so it cannot be joined to nidp.delivery_data (keyed on NSE
    symbol) without a bridge. The BSE bhavcopy for the *same day* carries
    FinInstrmId (the scrip code) alongside ISIN, which makes it a
    self-consistent bridge with no extra source to maintain.

    Returns an empty dict if the file is not in the SEBI layout.
    """
    text = body.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {}
    h = {c.strip(): i for i, c in enumerate(header)}
    if "FinInstrmId" not in h or "ISIN" not in h:
        logger.warning("BSE bhavcopy: no FinInstrmId/ISIN columns; got %s",
                       list(h)[:12])
        return {}
    ci, ii = h["FinInstrmId"], h["ISIN"]
    out: dict[str, str] = {}
    for row in reader:
        if len(row) <= max(ci, ii):
            continue
        code = (row[ci] or "").strip()
        isin = (row[ii] or "").strip()
        if code and isin.startswith("IN"):
            out.setdefault(code, isin)
    return out


def parse_bse_scrip_master(body: bytes) -> list[dict[str, Any]]:
    """Full {scrip_code, isin, ticker, group, name} rows from a BSE bhavcopy.

    parse_bse_scrip_isin() above keeps only the scrip→ISIN pair, because that
    is all the delivery gap-fill bridge needs. Three more columns in the same
    file are worth persisting per day (migration 153):

      TckrSymb    BSE's own ticker — lets a filing resolve without an ISIN
      SctySrs     the trading/surveillance group ON THAT DAY (A, B, X, XT,
                  T, Z, M, …). X/XT/T/Z are trade-for-trade or restricted,
                  so this decides whether a fill was possible at all. It is
                  revised by surveillance and is NOT recoverable afterwards.
      FinInstrmNm the company name as filed that day, so renames are dated

    Returns [] if the file is not in the SEBI layout, matching
    parse_bse_scrip_isin()'s contract. Rows without a scrip code are skipped;
    a row with a missing or malformed ISIN is KEPT with isin=None, because the
    scrip still traded that day and its absence from a later file is the
    delisting signal.
    """
    text = body.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    h = {c.strip(): i for i, c in enumerate(header)}
    if "FinInstrmId" not in h or "ISIN" not in h:
        logger.warning("BSE scrip master: no FinInstrmId/ISIN columns; got %s",
                       list(h)[:12])
        return []

    def cell(row: list[str], name: str) -> Optional[str]:
        i = h.get(name)
        if i is None or len(row) <= i:
            return None
        v = (row[i] or "").strip()
        return v or None

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in reader:
        # Same equity filter as format B above — keep F&O rows out.
        tp = (cell(row, "FinInstrmTp") or "").upper()
        sgmt = (cell(row, "Sgmt") or "").upper()
        if tp and tp not in {"STK", "EQ"}:
            continue
        if sgmt and sgmt != "CM":
            continue
        code = cell(row, "FinInstrmId")
        if not code or code in seen:
            continue
        seen.add(code)
        isin = cell(row, "ISIN")
        out.append({
            "scrip_code": code,
            "isin": isin if (isin or "").startswith("IN") else None,
            "bse_ticker": cell(row, "TckrSymb"),
            "bse_group": cell(row, "SctySrs"),
            "company_name": cell(row, "FinInstrmNm"),
        })
    return out
