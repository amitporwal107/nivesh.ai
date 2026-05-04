"""NSE bulk-deals CSV parser.

NSE publishes a rolling CSV at /content/equities/bulk.csv with the
following columns (header row, comma-separated, latin-1 in places):

    Date, Symbol, Security Name, Client Name, Buy/Sell,
    Quantity Traded, Trade Price / Wght. Avg. Price, Remarks

Date format: DD-MMM-YYYY (e.g. "04-May-2026").

Multiple rows can exist for the same (date, symbol, client, side) when
a single client crosses the bulk threshold via several trades — we
assign a `deal_seq` 1..N to keep them distinct in the PK.

Pure function — takes raw bytes, returns list of dicts. No I/O.
Easily golden-file tested.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Tolerate header-name drift (NSE has shipped variants like
# "Buy/Sell Indicator", "QUANTITY TRADED", "Trade Price (Avg)" …).
HEADER_ALIASES: dict[str, list[str]] = {
    "as_of_date":   ["Date", "DATE", "Trade Date"],
    "symbol":       ["Symbol", "SYMBOL"],
    "client_name":  ["Client Name", "CLIENT NAME", "Client"],
    "deal_type":    ["Buy/Sell", "BUY/SELL", "Buy / Sell", "Buy/ Sell"],
    "quantity":     ["Quantity Traded", "QUANTITY TRADED", "Qty"],
    "avg_price":    [
        "Trade Price / Wght. Avg. Price",
        "Trade Price / Wght.Avg.Price",
        "Trade Price/Wght. Avg. Price",
        "Avg Price", "AVG PRICE", "Trade Price",
    ],
    "remarks":      ["Remarks", "REMARKS"],
}


def _resolve_columns(headers: list[str]) -> dict[str, int]:
    norm = [h.strip() for h in headers]
    out: dict[str, int] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                out[canonical] = norm.index(alias)
                break
    missing = {"as_of_date", "symbol", "client_name", "deal_type", "quantity", "avg_price"} - out.keys()
    if missing:
        raise ValueError(
            f"NSE bulk deals CSV missing required columns: {sorted(missing)} "
            f"(headers seen: {norm})"
        )
    return out


_DATE_FORMATS = ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y")


def _parse_date(s: str) -> str:
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unparseable bulk-deal date: {s!r}")


def _parse_qty(s: str) -> int:
    return int(re.sub(r"[,\s]", "", s))


def _parse_price(s: str) -> float:
    return float(re.sub(r"[,\s]", "", s))


def _parse_side(s: str) -> str:
    s = s.strip().upper()
    if s.startswith("B"):
        return "BUY"
    if s.startswith("S"):
        return "SELL"
    raise ValueError(f"Unknown deal side: {s!r}")


def parse_bulk_deals(body: bytes) -> list[dict[str, Any]]:
    """Parse raw NSE bulk.csv bytes into ingestion rows.

    Returns rows with `deal_seq` assigned to disambiguate same-key
    multi-row entries.
    """
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []
    cols = _resolve_columns(headers)

    rows: list[dict[str, Any]] = []
    seq_tracker: dict[tuple, int] = {}
    for raw in reader:
        if not raw or all(not c.strip() for c in raw):
            continue
        try:
            d = _parse_date(raw[cols["as_of_date"]])
            sym = raw[cols["symbol"]].strip().upper()
            client = raw[cols["client_name"]].strip()
            side = _parse_side(raw[cols["deal_type"]])
            qty = _parse_qty(raw[cols["quantity"]])
            price = _parse_price(raw[cols["avg_price"]])
        except (IndexError, ValueError) as e:
            logger.warning("skipping malformed bulk-deal row: %s (%s)", raw, e)
            continue

        key = (d, sym, client, side)
        seq_tracker[key] = seq_tracker.get(key, 0) + 1
        seq = seq_tracker[key]

        remarks_idx = cols.get("remarks")
        remarks_raw = raw[remarks_idx].strip() if remarks_idx is not None and remarks_idx < len(raw) else ""
        # NSE uses "-" as the empty-remarks sentinel.
        remarks = remarks_raw if remarks_raw and remarks_raw not in ("-", "—") else None

        rows.append({
            "as_of_date": d,
            "symbol": sym,
            "client_name": client,
            "deal_type": side,
            "quantity": qty,
            "avg_price": price,
            "deal_seq": seq,
            "remarks": remarks,
        })
    return rows
