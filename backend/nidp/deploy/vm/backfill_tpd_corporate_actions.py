"""One-off: NSE corporate-actions API archive -> CSV for nidp.tpd_corporate_actions_history (migration 148).

Reuses the production parser/classifier (services/corporate_actions/parser.py), so action types, ratios and
dividend amounts match the shared table's. Loads into the model-only table, never the shared
corporate_actions table (see migration 148 for why). backfill_tpd_corporate_actions.sql inserts the CSV.

Usage (from backend/):
    python nidp/deploy/vm/backfill_tpd_corporate_actions.py --archive-dir <nse_api/ca> --out <csv>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from nidp.services.corporate_actions.parser import parse_corporate_actions  # noqa: E402

SOURCE = "NSE_CA_ARCHIVE"
COLS = ["symbol", "series", "action_type", "action_subtype", "purpose", "ratio", "face_value_pre", "face_value_post",
        "dividend_amount", "record_date", "ex_date", "bc_start_date", "bc_end_date", "announcement_date", "source"]


ADJUSTMENT_TYPES = {"SPLIT", "BONUS"}


def _merge(key: tuple, a: dict, b: dict) -> dict:
    """Two distinct actions share one primary key (e.g. a final and an interim dividend on the same ex-date;
    the live writer keeps only the last). Dividends add up; other disagreeing fields become NULL rather than
    a guess; split/bonus ratios drive price adjustment, so a conflict there refuses."""
    if key[1] in ADJUSTMENT_TYPES:
        raise ValueError(f"conflicting rows for {key}: {a['purpose']!r} vs {b['purpose']!r}")
    merged = {}
    for c in COLS:
        x, y = a.get(c), b.get(c)
        if x == y:
            merged[c] = x
        elif c == "purpose":
            merged[c] = " + ".join(p for p in (x, y) if p)
        elif c == "dividend_amount" and x is not None and y is not None:
            merged[c] = round(float(x) + float(y), 4)
        else:
            merged[c] = None
    return merged


def build_rows(paths: Iterable[Path]) -> list[dict]:
    """Parse every monthly file, drop exact repeats, and merge distinct actions that share a primary key."""
    distinct: dict[tuple, list[dict]] = {}
    for path in sorted(paths):
        for r in parse_corporate_actions(Path(path).read_bytes()):
            row = {**{c: r.get(c) for c in COLS}, "source": SOURCE}
            rows = distinct.setdefault((row["symbol"], row["action_type"], row["ex_date"], SOURCE), [])
            if row not in rows:
                rows.append(row)
    out = []
    for key in sorted(distinct):
        merged = distinct[key][0]
        for row in distinct[key][1:]:
            merged = _merge(key, merged, row)
        out.append(merged)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--archive-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    files = sorted(args.archive_dir.glob("ca_*.json"))
    raw = sum(len(json.loads(f.read_text())) for f in files)
    rows = build_rows(files)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows({c: ("" if r[c] is None else r[c]) for c in COLS} for r in rows)
    ex = sorted(r["ex_date"] for r in rows)
    print(json.dumps({"files": len(files), "raw_records": raw, "rows": len(rows),
                      "ex_date_first": ex[0] if ex else None, "ex_date_last": ex[-1] if ex else None,
                      "action_types": dict(Counter(r["action_type"] for r in rows).most_common())}, indent=1))


if __name__ == "__main__":
    main()
