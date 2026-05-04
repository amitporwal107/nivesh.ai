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
    if "TckrSymb" in h and "ClsgPric" in h:
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
            "prev_close":  _f(get("PrvsClsgPric")),
            "open_price":  _f(get("OpnPric")),
            "high_price":  _f(get("HghPric")),
            "low_price":   _f(get("LwPric")),
            "close_price": _f(get("ClsgPric")),
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
