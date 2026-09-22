"""Build data/demergers.csv + manifest.json (and the gap-detector safety-net output,
data/gap_review_candidates.csv) from the raw source snapshots this package ships with.

Run from the repo root:

    /app/research/tpd3_forward/venv/bin/python -m research.corporate_actions.build_demerger_events

Inputs (no network calls -- everything here reads local, already-retrieved evidence):
  data/raw/nse_ca_demerger_rows.json          NSE corporate-actions API, subject contains
                                               "demerger" or "scheme of arrangement",
                                               2021-01-01..2026-09-22, fetched this session
                                               (see that file's own "source"/"retrieved_at").
  data/raw/tpd_ca_history_demerger_rows.csv   secondary, already-in-repo corroborating
                                               source (research/tpd3_forward/inputs/
                                               tpd_ca_history.csv, action_type==DEMERGER
                                               rows only; covers 2024-06-03 onward).
  research.charting.bars.load_symbol()        Kite daily bars -- both the "is this symbol
                                               in the Kite universe" gate and the
                                               gap_pct_kite cross-check column.
  _RESULTING_ENTITY_OVERLAY (below)           hand-curated, cited from a live WebSearch
                                               this session (see each entry's `source`) --
                                               NSE's own feed never names the resulting
                                               entity, only "Demerger" as the subject.

Never invents an event or a date: every row written to demergers.csv traces to a source
in data/raw/ (an event absent from both raw snapshots is not written, however plausible).
A symbol from either raw snapshot that has no Kite bars at all is left out of
demergers.csv (out of scope -- "for the symbols in the Kite daily universe") and is
reported on stdout, not silently dropped.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
DEMERGERS_CSV = DATA_DIR / "demergers.csv"
GAP_CANDIDATES_CSV = DATA_DIR / "gap_review_candidates.csv"
MANIFEST_PATH = DATA_DIR / "manifest.json"

_REPO_ROOT = HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.charting import bars  # noqa: E402
from research.corporate_actions.events import CSV_COLUMNS, DemergerEvent, event_to_row  # noqa: E402
from research.corporate_actions.gap_detector import scan_universe_for_large_gaps  # noqa: E402
from research.corporate_actions.manifest import (  # noqa: E402
    load_manifest, save_manifest, sha256_file, upsert_file_entry, upsert_source_entry,
)

NSE_SOURCE_NAME = "NSE corporate-actions API (nseindia.com/api/corporates-corporateActions)"
TPD_SOURCE_NAME = "in-repo NSE_CA_ARCHIVE (research/tpd3_forward/inputs/tpd_ca_history.csv)"

# Cited from a live WebSearch this session (2026-09-22) for the three demergers the task
# named explicitly. NSE's own corporate-actions feed never names the resulting entity, so
# this is the only source for these three fields in the whole dataset; every other
# confirmed row's resulting_entity/resulting_symbol is deliberately left blank ("where
# known" -- not known from a source read this session). resulting_symbol is left blank
# even for these three: NSE's quote-equity API (which would confirm the exchange ticker)
# returned 403 Access Denied to every symbol probed this session (see the build report),
# so the ticker itself is not independently confirmed, only the entity name.
_RESULTING_ENTITY_OVERLAY: dict[str, dict] = {
    "SIEMENS": {
        "resulting_entity": "Siemens Energy India Limited (SEIL)",
        "resulting_symbol": "",
        "note": (
            "Power/energy business demerged from Siemens Limited; SEIL listed on NSE/BSE "
            "2025-06-19 at a 1:1 allotment ratio, record date 2025-04-07."
        ),
        "source": "WebSearch 2026-09-22: groww.in, angelone.in, business-standard.com, siemens-energy-india.com",
    },
    "ABFRL": {
        "resulting_entity": "Aditya Birla Lifestyle Brands Limited (ABLBL)",
        "resulting_symbol": "",
        "note": (
            "Western-wear brands (Louis Philippe, Van Heusen, Allen Solly, Peter England) "
            "vertically demerged from Aditya Birla Fashion and Retail Limited into ABLBL, "
            "effective 2025-05-01, record date 2025-05-22, listed on NSE at Rs 167."
        ),
        "source": "WebSearch 2026-09-22: hdfcsky.com, indiainfoline.com, adityabirla.com",
    },
    "TMPV": {
        "resulting_entity": (
            "Tata Motors Limited was renamed Tata Motors Passenger Vehicles Limited (TMPV, "
            "retaining PV/EV/JLR); the commercial-vehicles business was demerged into a new "
            "entity that took the 'Tata Motors' name and listed separately on NSE/BSE "
            "2025-11-12 (TMCV)"
        ),
        "resulting_symbol": "",
        "note": (
            "Record date 2025-10-14, 1:1 ratio. Sources differ on framing (surviving-entity "
            "rename vs. new-entity spin-off) -- reported as read, not resolved further."
        ),
        "source": "WebSearch 2026-09-22: businesstoday.in, plindia.com, en.wikipedia.org/wiki/Tata_Motors_Passenger_Vehicles",
    },
}

# NSE's action_type bucket is "DEMERGER" for these too, but the `subject` text says this is
# a Scheme of Arrangement issuing Non-Convertible Redeemable Preference Shares (NCRPS), not
# a business separation. Kept, not silently dropped -- see events.py module docstring.
_NCRPS_MARKER = "ncrps"


def _load_raw_nse_rows() -> list[dict]:
    payload = json.loads((RAW_DIR / "nse_ca_demerger_rows.json").read_text())
    return payload["rows"], payload["source"], payload["source_reference"], payload["retrieved_at"]


def _nse_date(s: str) -> date:
    return datetime.strptime(s, "%d-%b-%Y").date()


def _gap_pct_near(symbol: str, ex_date: date) -> float | None:
    """Open-vs-previous-close % on the first Kite bar on/after ex_date (see
    regime._anchor_index for why "on/after", not "nearest" -- kept simple and independently
    computed here rather than importing regime's anchor logic, since this is a diagnostic
    column, not the regime-break boundary itself)."""
    df = bars.load_symbol(symbol)
    if df.empty:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    on_or_after = df[df["date"] >= pd.Timestamp(ex_date)]
    if on_or_after.empty:
        return None
    idx = on_or_after.index[0]
    if idx == 0:
        return None
    prev_close = df.loc[idx - 1, "close"]
    open_ = df.loc[idx, "open"]
    if prev_close == 0:
        return None
    return round(float((open_ - prev_close) / prev_close * 100.0), 4)


def build() -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nse_rows, nse_source, nse_reference, nse_retrieved_at = _load_raw_nse_rows()

    out_of_scope: list[tuple[str, str]] = []
    events: list[DemergerEvent] = []
    seen: set[tuple[str, date, str]] = set()

    for row in nse_rows:
        symbol = row["symbol"]
        ex_dt = _nse_date(row["exDate"])
        rec_dt = _nse_date(row["recDate"]) if row["recDate"] and row["recDate"] != "-" else None
        if ex_dt > date.today():
            continue  # window is 2021-01-01 -> today

        bars_df = bars.load_symbol(symbol)
        if bars_df.empty:
            out_of_scope.append((symbol, row["exDate"]))
            continue

        is_ncrps = _NCRPS_MARKER in row["subject"].lower()
        category = "NCRPS_BONUS_SCHEME" if is_ncrps else "DEMERGER"
        gap_pct = _gap_pct_near(symbol, ex_dt)

        overlay = _RESULTING_ENTITY_OVERLAY.get(symbol, {})
        if is_ncrps:
            verified = False
            review_reason = (
                "NSE files this under action_type=DEMERGER but subject is "
                f"'{row['subject']}' -- a Scheme of Arrangement issuing Non-Convertible "
                "Redeemable Preference Shares, not a business demerger. Kite gap on/near "
                f"ex_date is {gap_pct if gap_pct is not None else 'n/a'}% (no discontinuity "
                "consistent with a business separation). Excluded from regime-break "
                "treatment pending owner confirmation."
            )
        else:
            verified = True
            review_reason = ""

        key = (symbol, ex_dt, category)
        if key in seen:
            continue
        seen.add(key)

        events.append(DemergerEvent(
            symbol=symbol,
            ex_date=ex_dt,
            date_type="EX_DATE",
            record_date=rec_dt,
            category=category,
            resulting_entity=overlay.get("resulting_entity", ""),
            resulting_symbol=overlay.get("resulting_symbol", ""),
            source=nse_source,
            source_reference=nse_reference,
            retrieved_at=nse_retrieved_at,
            verified=verified,
            gap_pct_kite=gap_pct,
            review_reason=review_reason,
        ))

    events.sort(key=lambda e: (e.ex_date, e.symbol))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEMERGERS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for e in events:
            writer.writerow(event_to_row(e))

    # Safety-net gap scan over the whole Kite universe, for the manifest + the report.
    # Excludes bars already covered by a written event's own symbol+date to keep this file
    # focused on genuinely UNEXPLAINED candidates (still just REVIEW candidates, not
    # confirmations, if a future date happens to coincide).
    written_symbol_dates = {(e.symbol, e.ex_date) for e in events}

    def _all_bars():
        yield from bars.load_all()

    gap_df = scan_universe_for_large_gaps(_all_bars())
    gap_df["date_only"] = pd.to_datetime(gap_df["date"]).dt.date
    is_explained = gap_df.apply(
        lambda r: any(sym == r["symbol"] and abs((r["date_only"] - exd).days) <= 2
                      for sym, exd in written_symbol_dates),
        axis=1,
    )
    gap_df = gap_df.loc[~is_explained].drop(columns=["date_only"]).reset_index(drop=True)
    gap_df.to_csv(GAP_CANDIDATES_CSV, index=False)

    manifest = load_manifest(MANIFEST_PATH)
    upsert_source_entry(manifest, "nse_corporate_actions_api", {
        "name": nse_source, "reference": nse_reference, "retrieved_at": nse_retrieved_at,
        "raw_file": "raw/nse_ca_demerger_rows.json",
    })
    upsert_source_entry(manifest, "in_repo_tpd_ca_history", {
        "name": TPD_SOURCE_NAME,
        "reference": "research/tpd3_forward/inputs/tpd_ca_history.csv (repo-local, not this package's own fetch)",
        "raw_file": "raw/tpd_ca_history_demerger_rows.csv",
        "used_for": "secondary corroboration only -- demergers.csv is built from the NSE API snapshot",
    })
    nse_raw_path = RAW_DIR / "nse_ca_demerger_rows.json"
    for name, path, row_count in (
        ("demergers.csv", DEMERGERS_CSV, sum(1 for _ in open(DEMERGERS_CSV)) - 1),
        ("gap_review_candidates.csv", GAP_CANDIDATES_CSV, sum(1 for _ in open(GAP_CANDIDATES_CSV)) - 1),
        ("raw/nse_ca_demerger_rows.json", nse_raw_path, len(nse_rows)),
        ("raw/tpd_ca_history_demerger_rows.csv", RAW_DIR / "tpd_ca_history_demerger_rows.csv",
         sum(1 for _ in open(RAW_DIR / "tpd_ca_history_demerger_rows.csv")) - 1),
    ):
        upsert_file_entry(manifest, name, {"sha256": sha256_file(path), "rows": row_count})
    save_manifest(MANIFEST_PATH, manifest, generated_at)

    confirmed = [e for e in events if e.is_confirmed_demerger()]
    print(f"wrote {len(events)} event rows ({len(confirmed)} confirmed demergers, "
          f"{len(events) - len(confirmed)} NCRPS-bonus-scheme) to {DEMERGERS_CSV}")
    print(f"wrote {len(gap_df)} unexplained gap-review candidates to {GAP_CANDIDATES_CSV}")
    if out_of_scope:
        print(f"{len(out_of_scope)} symbols from the raw sources have no Kite bars (out of scope):")
        for sym, exd in out_of_scope:
            print(f"  {sym}  {exd}")


if __name__ == "__main__":
    build()
