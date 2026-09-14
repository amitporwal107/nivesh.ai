"""One-off backfill: older NSE sec_bhavdata_full archive files -> CSVs for nidp.prices_eod and nidp.delivery_data.

Ten-Percent Days 3.0 (W1) needs bars from 2024-05-31, but prices_eod starts 2025-01-01 and delivery_data
starts 2025-02-01. The archive (research/tpd_run/data/secbhav, mirrored to
gs://nidp-raw-niveshdataintelligence/research/tpd_run/) holds sec_bhavdata_full for every session.

Why not run the bhavcopy/delivery services with --date: they re-fetch from NSE, fall back to BSE rows on a
fetch failure, bump market_session_state, and the delivery writer UPDATEs existing prices_eod rows. This
script only builds CSVs; backfill_sec_bhavdata_archive.sql inserts rows strictly older than the existing
data with ON CONFLICT DO NOTHING, so no existing row changes.

On 2025 dates, where both sources exist, the archive matched nidp.prices_eod (NSE_BHAVCOPY) on
open/high/low/close/prev/last/avg/volume/trades for 11,065 of 11,065 EQ rows; turnover differs only by
the file's 2-decimal lakh rounding (max Rs 499.90). Rows are labelled NSE_SEC_BHAVDATA, the delivery
service's name for this file, not NSE_BHAVCOPY.

Usage (from backend/):
    python nidp/deploy/vm/backfill_sec_bhavdata_archive.py --archive-dir <secbhav> --out-dir <dir> \
        --prices-before 2025-01-01 --delivery-before 2025-02-01
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from nidp.services.delivery.parser import parse_delivery  # noqa: E402

SOURCE = "NSE_SEC_BHAVDATA"
PRICE_COLS = ["as_of_date", "symbol", "series", "isin", "prev_close", "open_price", "high_price", "low_price",
              "close_price", "last_price", "avg_price", "volume", "turnover", "trades", "deliv_qty", "deliv_pct",
              "source"]
DELIVERY_COLS = ["as_of_date", "symbol", "series", "traded_qty", "deliverable_qty", "deliverable_pct", "source"]
_FIELDS = ["PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE",
           "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER"]


def _dec(s: str) -> Optional[Decimal]:
    s = s.strip().replace(",", "")
    return None if s in ("", "-") else Decimal(s)


def _int(s: str) -> Optional[int]:
    d = _dec(s)
    return None if d is None else int(d)


def read_archive(paths: Iterable[Path]) -> dict[tuple[date, str, str], dict[str, str]]:
    """Key every row by its own DATE1 (holiday URLs serve the prior session's file) and collapse
    identical duplicates; refuse when two files disagree about the same bar."""
    out: dict[tuple[date, str, str], dict[str, str]] = {}
    for path in sorted(paths):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            idx = {h.strip(): i for i, h in enumerate(next(reader))}
            for raw in reader:
                if not raw or all(not c.strip() for c in raw):
                    continue
                cells = [c.strip() for c in raw]
                key = (datetime.strptime(cells[idx["DATE1"]], "%d-%b-%Y").date(),
                       cells[idx["SYMBOL"]].upper(), cells[idx["SERIES"]].upper())
                values = {f: cells[idx[f]] for f in _FIELDS}
                if key in out and out[key] != values:
                    raise ValueError(f"conflicting rows for {key} (second seen in {path.name})")
                out[key] = values
    return out


def price_rows(records: dict[tuple[date, str, str], dict[str, str]], before: date) -> list[dict]:
    rows = []
    for (d, symbol, series), v in sorted(records.items()):
        if d >= before:
            continue
        lacs = _dec(v["TURNOVER_LACS"])
        rows.append({
            "as_of_date": d.isoformat(), "symbol": symbol, "series": series, "isin": None,
            "prev_close": _dec(v["PREV_CLOSE"]), "open_price": _dec(v["OPEN_PRICE"]),
            "high_price": _dec(v["HIGH_PRICE"]), "low_price": _dec(v["LOW_PRICE"]),
            "close_price": _dec(v["CLOSE_PRICE"]), "last_price": _dec(v["LAST_PRICE"]),
            "avg_price": _dec(v["AVG_PRICE"]), "volume": _int(v["TTL_TRD_QNTY"]),
            "turnover": None if lacs is None else lacs * 100000, "trades": _int(v["NO_OF_TRADES"]),
            "deliv_qty": _int(v["DELIV_QTY"]), "deliv_pct": _dec(v["DELIV_PER"]), "source": SOURCE,
        })
    return rows


def delivery_rows(paths: Iterable[Path], before: date) -> list[dict]:
    seen: dict[tuple[str, str, str], dict] = {}
    for path in sorted(paths):
        for r in parse_delivery(Path(path).read_bytes()):
            if date.fromisoformat(r["as_of_date"]) < before:
                seen[(r["as_of_date"], r["symbol"], r["series"])] = {**r, "source": SOURCE}
    return [seen[k] for k in sorted(seen)]


def _write(rows: list[dict], cols: list[str], path: Path) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows({c: ("" if r[c] is None else r[c]) for c in cols} for r in rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--archive-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--prices-before", type=date.fromisoformat, required=True)
    ap.add_argument("--delivery-before", type=date.fromisoformat, required=True)
    args = ap.parse_args()

    files = sorted(args.archive_dir.glob("sec_bhavdata_full_*.csv"))
    records = read_archive(files)
    prices = price_rows(records, args.prices_before)
    delivery = delivery_rows(files, args.delivery_before)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write(prices, PRICE_COLS, args.out_dir / "prices_eod.csv")
    _write(delivery, DELIVERY_COLS, args.out_dir / "delivery_data.csv")

    def span(rows):
        ds = sorted({r["as_of_date"] for r in rows})
        return {"rows": len(rows), "sessions": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None}

    print(json.dumps({
        "files": len(files), "archive_sessions": len({k[0] for k in records}),
        "prices_eod": span(prices), "prices_eod_eq": span([r for r in prices if r["series"] == "EQ"]),
        "delivery_data": span(delivery),
    }, indent=1))


if __name__ == "__main__":
    main()
