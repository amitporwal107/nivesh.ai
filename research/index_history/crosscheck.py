"""Cross-check freshly fetched index closes against two pre-existing local files that
happen to overlap our fetch windows:

  - /app/research/model_v5/index_p4.csv (date,open,high,low,close,index — stacks
    NIFTY 500 / NIFTY 50 / INDIA VIX; overlaps 2019-07..2022-12)
  - /app/research/phase1/nifty500_index_daily.csv (date,close only, NIFTY 500;
    overlaps 2024-08..today)

A mismatch is reported, never silently resolved — this module only computes and
prints/returns differences, it does not "fix" either side.
"""
from __future__ import annotations

import csv
from pathlib import Path

INDEX_P4_PATH = Path("/app/research/model_v5/index_p4.csv")
PHASE1_NIFTY500_PATH = Path("/app/research/phase1/nifty500_index_daily.csv")


def _read_new_closes(csv_path: Path) -> dict[str, float]:
    """Our own fetched CSV: date,open,high,low,close,volume."""
    out: dict[str, float] = {}
    with open(csv_path, newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["date"]] = float(row["close"])
    return out


def read_index_p4_closes(index_name: str, path: Path = INDEX_P4_PATH) -> dict[str, float]:
    """date -> close for one `index` value out of the stacked index_p4.csv."""
    out: dict[str, float] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["index"] == index_name:
                out[row["date"][:10]] = float(row["close"])
    return out


def read_phase1_nifty500_closes(path: Path = PHASE1_NIFTY500_PATH) -> dict[str, float]:
    """date (first 10 chars, tz suffix dropped) -> close."""
    out: dict[str, float] = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["date"][:10]] = float(row["close"])
    return out


def diff_closes(a: dict[str, float], b: dict[str, float]) -> dict:
    """Compare two date->close maps on their overlapping dates only."""
    overlap = sorted(set(a) & set(b))
    if not overlap:
        return {"overlap_dates": 0, "max_abs_diff": None, "max_rel_diff": None, "at_date": None}
    max_abs, max_rel, at_date = 0.0, 0.0, None
    for d in overlap:
        abs_diff = abs(a[d] - b[d])
        rel_diff = abs_diff / abs(b[d]) if b[d] else float("inf")
        if abs_diff > max_abs:
            max_abs = abs_diff
            at_date = d
        max_rel = max(max_rel, rel_diff)
    return {"overlap_dates": len(overlap), "max_abs_diff": max_abs, "max_rel_diff": max_rel, "at_date": at_date}


def crosscheck_index(index_name: str, new_csv_path: Path) -> dict:
    """Run every applicable comparison for one index; returns {source_label: diff_dict}."""
    new_closes = _read_new_closes(new_csv_path)
    results: dict = {}

    if INDEX_P4_PATH.exists():
        p4 = read_index_p4_closes(index_name)
        if p4:
            results["model_v5/index_p4.csv"] = diff_closes(new_closes, p4)

    if index_name == "NIFTY 500" and PHASE1_NIFTY500_PATH.exists():
        p1 = read_phase1_nifty500_closes()
        results["phase1/nifty500_index_daily.csv"] = diff_closes(new_closes, p1)

    return results


def main(data_dir: Path, index_names: list[str] = ("NIFTY 50", "NIFTY 500", "INDIA VIX")) -> dict:
    report = {}
    for name in index_names:
        slug = name.strip().upper().replace(" ", "_")
        csv_path = data_dir / f"{slug}.csv"
        if not csv_path.exists():
            report[name] = {"error": f"{csv_path} not found — fetch it first"}
            continue
        report[name] = crosscheck_index(name, csv_path)
    return report


if __name__ == "__main__":
    import json
    import sys
    dd = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "data"
    print(json.dumps(main(dd), indent=2, default=str))
