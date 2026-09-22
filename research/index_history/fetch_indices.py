"""Fetch daily index history from Kite Connect for the research charting engine.

Run for real (network call against the live Kite Connect API — never mocked/invented
data) from the repo root:

    /app/research/tpd3_forward/venv/bin/python -m research.index_history.fetch_indices

Writes one CSV per resolved index to data/<SLUG>.csv (date,open,high,low,close,volume;
ascending, unique dates) and records/updates each file's entry in manifest.json. Any
index that fails to resolve or fetch is reported, never substituted.
"""
from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
MANIFEST_PATH = HERE / "manifest.json"

# Repo root two levels up from research/index_history, so `python -m research....` and
# direct script execution both resolve `research.index_history....` imports the same way.
_REPO_ROOT = HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.index_history.kite_client import (  # noqa: E402
    connect, fetch_day_history, get_access_token, resolve,
)
from research.index_history.manifest import (  # noqa: E402
    INTERVAL, SEALED_WINDOW, SOURCE, assert_no_sealed_dates, load_manifest,
    save_manifest, sha256_file, upsert_entry,
)

CSV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]

# Two fetch windows only — the gap between them is the sealed out-of-sample research
# window and must never be requested.
FETCH_WINDOWS: list[tuple[date, date]] = [
    (date(2019, 7, 1), date(2022, 12, 31)),
    (date(2024, 8, 1), date.today()),
]

REQUIRED_INDICES = ["NIFTY 50", "NIFTY 500", "INDIA VIX"]
BEST_EFFORT_INDICES = [
    "NIFTY MIDCAP 150",
    "NIFTY SMLCAP 250",
    "NIFTY BANK",
    "NIFTY IT",
    "NIFTY AUTO",
    "NIFTY PHARMA",
    "NIFTY FMCG",
    "NIFTY METAL",
    "NIFTY REALTY",
    "NIFTY ENERGY",
    "NIFTY FIN SERVICE",
    "NIFTY MEDIA",
    "NIFTY PSU BANK",
    "NIFTY INFRA",
]
ALL_INDICES = REQUIRED_INDICES + BEST_EFFORT_INDICES


def slug_for(index_name: str) -> str:
    return index_name.strip().upper().replace(" ", "_")


def _candle_date_str(candle: dict) -> str:
    """kiteconnect returns a datetime (tz-aware, midnight) for day-interval candles;
    accept a plain date/string too so this stays testable without the SDK."""
    d = candle["date"]
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def dedupe_sort_candles(candles: list[dict]) -> list[dict]:
    """One row per date (first occurrence wins across overlapping chunk edges),
    ascending by date."""
    by_date: dict[str, dict] = {}
    for c in candles:
        ds = _candle_date_str(c)
        if ds not in by_date:
            by_date[ds] = {
                "date": ds,
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c.get("volume", 0),
            }
    return [by_date[d] for d in sorted(by_date)]


def write_index_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def fetch_one_index(kc, name: str, token: int) -> list[dict]:
    all_rows: list[dict] = []
    for start, end in FETCH_WINDOWS:
        all_rows.extend(fetch_day_history(kc, token, start, end))
    rows = dedupe_sort_candles(all_rows)
    assert_no_sealed_dates(r["date"] for r in rows)
    return rows


def run(indices: list[str] = ALL_INDICES) -> dict:
    """Fetch every index in `indices`; return a report dict (also used by tests with a
    stub `kc`/resolver via the lower-level functions above)."""
    report: dict = {"resolved": {}, "missing": [], "failed": {}, "results": {}}

    access_token = get_access_token()
    if not access_token:
        report["blocker"] = "no Kite access token at /root/.kite-access-token"
        return report

    kc = connect(access_token)
    found, missing = resolve(kc, indices)
    report["resolved"] = found
    report["missing"] = missing

    manifest = load_manifest(MANIFEST_PATH)

    for name, token in found.items():
        try:
            rows = fetch_one_index(kc, name, token)
        except Exception as exc:  # report, never fabricate a substitute
            report["failed"][name] = f"{type(exc).__name__}: {exc}"
            continue

        slug = slug_for(name)
        csv_path = DATA_DIR / f"{slug}.csv"
        write_index_csv(rows, csv_path)
        digest = sha256_file(csv_path)
        entry = {
            "index_name": name,
            "instrument_token": token,
            "rows": len(rows),
            "first_date": rows[0]["date"] if rows else None,
            "last_date": rows[-1]["date"] if rows else None,
            "sha256": digest,
            "source": SOURCE,
            "interval": INTERVAL,
            "excluded_window": list(SEALED_WINDOW),
        }
        manifest = upsert_entry(manifest, f"{slug}.csv", entry)
        report["results"][name] = entry

    save_manifest(MANIFEST_PATH, manifest, generated_at=datetime.now(timezone.utc).isoformat())
    return report


def _print_report(report: dict) -> None:
    if report.get("blocker"):
        print(f"BLOCKER: {report['blocker']}")
        return
    print(f"Resolved {len(report['resolved'])}/{len(report['resolved']) + len(report['missing'])} indices")
    if report["missing"]:
        print(f"Missing (not found in kc.instruments('NSE') INDICES segment): {report['missing']}")
    for name, entry in report["results"].items():
        print(f"  {name}: rows={entry['rows']} first={entry['first_date']} last={entry['last_date']} "
              f"token={entry['instrument_token']} sha256={entry['sha256'][:12]}...")
    if report["failed"]:
        print("Failed:")
        for name, err in report["failed"].items():
            print(f"  {name}: {err}")


def main() -> int:
    report = run()
    _print_report(report)
    return 1 if (report.get("blocker") or report["failed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
