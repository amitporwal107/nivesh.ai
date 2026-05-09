"""Parser for NSE F&O EOD bhavcopy (post-Jul-2024 unified format).

NSE column headers (canonical):
    TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId, ISIN, TckrSymb,
    SctySrs, XpryDt, FininstrmActlXpryDt, StrkPric, OptnTp, FinInstrmNm,
    OpnPric, HghPric, LwPric, ClsPric, LastPric, PrvsClsgPric,
    UndrlygPric, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTradgVol,
    TtlTrfVal, TtlNbOfTxsExctd, SsnId, NewBrdLotQty, Rmks, Rsvd1..Rsvd4
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Filter to the F&O segment. Sgmt='FO' on the unified post-2024 file.
_FO_SEGMENT = "FO"

# NSE renamed instrument type codes in the unified post-2024 bhavcopy format.
# Accept both old and new codes for backward compatibility with archived files.
# Old → New: FUTIDX→IDF, FUTSTK→STF, OPTIDX→IDO, OPTSTK→STO
_VALID_INSTRUMENT_TYPES = {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK", "IDF", "STF", "IDO", "STO"}


def parse_fno_bhavcopy(csv_bytes: bytes) -> List[Dict[str, Any]]:
    if not csv_bytes:
        return []

    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    out: List[Dict[str, Any]] = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}

        # Filter to F&O segment + valid instrument types
        if row.get("Sgmt") and row["Sgmt"] != _FO_SEGMENT:
            continue
        instrument_type = row.get("FinInstrmTp") or ""
        if instrument_type not in _VALID_INSTRUMENT_TYPES:
            continue

        ticker = row.get("TckrSymb")
        expiry = _parse_date(row.get("XpryDt"))
        if not ticker or not expiry:
            continue

        trad_dt = _parse_date(row.get("TradDt"))
        if not trad_dt:
            continue

        option_type = row.get("OptnTp") or None
        if option_type and option_type not in ("CE", "PE"):
            option_type = None

        out.append({
            "as_of_date":          trad_dt,
            "biz_date":            _parse_date(row.get("BizDt")),
            "instrument_type":     instrument_type,
            "ticker_symbol":       ticker,
            "isin":                row.get("ISIN") or None,
            "series":              row.get("SctySrs") or None,
            "expiry_date":         expiry,
            "actual_expiry_date":  _parse_date(row.get("FininstrmActlXpryDt")),
            "strike_price":        _to_float(row.get("StrkPric")),
            "option_type":         option_type,
            "open_price":          _to_float(row.get("OpnPric")),
            "high_price":          _to_float(row.get("HghPric")),
            "low_price":           _to_float(row.get("LwPric")),
            "close_price":         _to_float(row.get("ClsPric")),
            "last_price":          _to_float(row.get("LastPric")),
            "prev_close_price":    _to_float(row.get("PrvsClsgPric")),
            "settle_price":        _to_float(row.get("SttlmPric")),
            "underlying_price":    _to_float(row.get("UndrlygPric")),
            "open_interest":       _to_int(row.get("OpnIntrst")),
            "change_in_oi":        _to_int(row.get("ChngInOpnIntrst")),
            "traded_volume":       _to_int(row.get("TtlTradgVol")),
            "traded_value":        _to_float(row.get("TtlTrfVal")),
            "num_trades":          _to_int(row.get("TtlNbOfTxsExctd")),
            "new_board_lot_qty":   _to_int(row.get("NewBrdLotQty")),
        })
    return out


def _parse_date(s: Optional[str]) -> Optional[str]:
    """Parse NSE date formats. Returns ISO string or None.

    Post-2024 bhavcopy uses YYYY-MM-DD. Legacy used DD-Mon-YYYY.
    """
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        v = float(s.replace(",", ""))
        # NSE encodes "no value" as -1.0 or 999999 sentinels in some
        # legacy files; treat 0 settle prices as legitimate.
        return v
    except ValueError:
        return None


def _to_int(s: Optional[str]) -> Optional[int]:
    if s is None or s == "":
        return None
    try:
        return int(float(s.replace(",", "")))
    except ValueError:
        return None
