#!/usr/bin/env python3
"""Parse Trendlyne insider/SAST disclosures into a COPY-ready CSV for nidp.insider_sast.

The dashboard's INSIDER / SAST lane has no source in nidp (see migration 157). Trendlyne's
ownership feed carries it, but one call serves one stock against a ~1,000/day cap, so this reads
the append-only archive first (already-paid-for responses, zero calls) and only fetches symbols
that have never been fetched — and then through tl_cache, so a repeat inside the TTL is also free.

Columns are mapped by Trendlyne's `unique_name` header key, not by position: the response is a
generic table and a column order change would otherwise silently shift every value one place.

Usage:
    insider_sast_to_pg.py --archive-only                 # parse what is cached, fetch nothing
    insider_sast_to_pg.py --symbols-from <csv> --max 400  # top up, bounded by the daily cap
Output: ref/insider_sast.csv  (+ .skipped.csv for rows that failed validation, never dropped silently)
"""
from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import glob
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARCHIVE = os.environ.get("TL_ARCHIVE_DIR", f"{ROOT}/archive")
OUT = f"{ROOT}/ref/insider_sast.csv"
SKIPPED = f"{ROOT}/ref/insider_sast.skipped.csv"

# nidp.insider_sast column -> Trendlyne unique_name
FIELDS = [
    ("client_name", "actor"),
    ("client_category", "actor_category_text"),
    ("action", "transaction_type_text"),
    ("report_date", "report_date"),
    ("quantity", "holding_change"),
    ("holding_after", "holding_after"),
    ("holding_after_pct", "holdingP_after"),
    ("pct_traded", "holdingP_change"),
    ("average_price", "average_price"),
    ("txn_start_date", "start_date"),
    ("txn_end_date", "end_date"),
    ("disclosure_type", "get_sast_type_display"),
    ("regulation", "regulation_text"),
    ("security_type", "security_type_text"),
    ("mode", "mode"),
    ("value_rupees", "transaction_value"),
]
COLS = ["symbol"] + [c for c, _ in FIELDS] + ["source", "fetched_at"]
DATE_COLS = {"report_date", "txn_start_date", "txn_end_date"}
NUM_COLS = {"quantity", "holding_after", "holding_after_pct", "pct_traded",
            "average_price", "value_rupees"}
# The feed's action domain, canonicalised. Pledge/Revoke/Invoke are encumbrance events, not
# ownership changes, and are the majority of rows — they are preserved, never collapsed to NULL.
ACTIONS = {
    "acquisition": "Acquisition", "disposal": "Disposal", "pledge": "Pledge",
    "revoke": "Revoke", "invoke": "Invoke", "others": "Others",
    "non-disposable undertaking": "Non-Disposable Undertaking",
    "non disposal undertaking": "Non-Disposable Undertaking",
}


def header_keys(text: str) -> list[str]:
    """unique_name of each tableData column, in order, from the tableHeaders block."""
    m = re.search(r"^tableHeaders:\n((?:[ \t]+.*\n?)+)", text, re.M)
    if not m:
        return []
    keys = []
    for ln in m.group(1).splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) == 3 and parts[2] != "unique_name":
            keys.append(parts[2])
    return keys


def rows_of(text: str) -> list[list]:
    """tableData is a JSON-ish array-of-arrays with Python-incompatible `null`; parse leniently."""
    m = re.search(r"^tableData:\n[ \t]*(\[.*?\])\s*$", text, re.M | re.S)
    if not m:
        return []
    blob = m.group(1).strip()
    if not blob.startswith("["):
        return []
    try:
        return json.loads(f"[{blob}]" if not blob.startswith("[[") else blob)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(f"[{blob.replace('null', 'None')}]")
        except (ValueError, SyntaxError):
            return []


def _date(v) -> str | None:
    if not v or not isinstance(v, str):
        return None
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(v.strip(), f).date().isoformat()
        except ValueError:
            continue
    return None


def _num(v) -> str | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return repr(v)
    s = re.sub(r"[,\s₹%]", "", str(v))
    try:
        float(s)
    except ValueError:
        return None
    return s


def parse(symbol: str, text: str, fetched_at: str) -> tuple[list[dict], list[dict]]:
    keys = header_keys(text)
    good: list[dict] = []
    bad: list[dict] = []
    for raw in rows_of(text):
        if not isinstance(raw, list):
            continue
        # Positional fallback is refused: without headers we cannot tell which column is which,
        # and a mis-mapped holding% is worse than a missing row.
        if len(keys) != len(raw):
            bad.append({"symbol": symbol, "reason": f"header/row width {len(keys)}!={len(raw)}",
                        "raw": json.dumps(raw, default=str)[:300]})
            continue
        d = dict(zip(keys, raw))
        rec: dict = {"symbol": symbol, "source": "trendlyne", "fetched_at": fetched_at}
        for col, key in FIELDS:
            v = d.get(key)
            rec[col] = _date(v) if col in DATE_COLS else _num(v) if col in NUM_COLS else (
                str(v).strip() if v not in (None, "") else None)
        if rec["action"]:
            a = rec["action"].strip()
            mapped = ACTIONS.get(a.lower())
            if mapped is None:
                # An unseen action is reported, not silently nulled: the CHECK in migration 157
                # would reject it on load, and a dropped value here would hide why.
                bad.append({"symbol": symbol, "reason": f"unmapped action {a!r}",
                            "raw": json.dumps(raw, default=str)[:300]})
                continue
            rec["action"] = mapped
        if not rec["report_date"] or not rec["client_name"]:
            bad.append({"symbol": symbol, "reason": "missing report_date or client_name",
                        "raw": json.dumps(raw, default=str)[:300]})
            continue
        good.append(rec)
    return good, bad


def from_archive() -> tuple[list[dict], list[dict], set[str]]:
    good: list[dict] = []
    bad: list[dict] = []
    seen: set[str] = set()
    for p in sorted(glob.glob(f"{ARCHIVE}/*/tool_responses.jsonl.gz")):
        with gzip.open(p, "rt") as f:
            for ln in f:
                try:
                    j = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if j.get("tool") != "get_ownership_deals_insider_sast":
                    continue
                a = j.get("args") or {}
                if a.get("type") != "sast" or not j.get("text"):
                    continue
                sym = a.get("stock_code")
                if not sym:
                    continue
                seen.add(sym)
                g, b = parse(sym, j["text"], j.get("fetched_at") or "")
                good += g
                bad += b
    return good, bad, seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive-only", action="store_true")
    ap.add_argument("--symbols-from", help="CSV with a `symbol` column: the top-up universe")
    ap.add_argument("--max", type=int, default=0, help="max symbols to fetch (0 = none)")
    args = ap.parse_args()

    good, bad, seen = from_archive()
    print(f"archive: {len(seen)} symbols fetched before, {len(good)} rows parsed, {len(bad)} skipped")

    if not args.archive_only and args.symbols_from and args.max > 0:
        sys.path.insert(0, HERE)
        from tl_cache import TLCache  # noqa: PLC0415  (optional dependency of the top-up path)
        import pandas as pd  # noqa: PLC0415

        want = [s for s in dict.fromkeys(pd.read_csv(args.symbols_from).symbol.astype(str))
                if s not in seen][: args.max]
        print(f"top-up: {len(want)} symbols")
        c = TLCache()
        for i, sym in enumerate(want, 1):
            try:
                r = c.call("get_ownership_deals_insider_sast", {"stock_code": sym, "type": "sast"})
            except Exception as e:  # noqa: BLE001 — one bad symbol must not lose the batch
                print(f"  [{i}/{len(want)}] {sym}: {type(e).__name__}: {e}", flush=True)
                if "budget" in str(e).lower() or "BudgetExceeded" in type(e).__name__:
                    print("  daily cap reached — stopping")
                    break
                continue
            txt = r if isinstance(r, str) else (r or {}).get("text", "")
            g, b = parse(sym, txt, dt.datetime.now(dt.timezone.utc).isoformat())
            good += g
            bad += b
            print(f"  [{i}/{len(want)}] {sym}: {len(g)} rows", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # De-duplicate on the same key the unique index uses, so a reload is a no-op not a conflict.
    uniq: dict[tuple, dict] = {}
    for r in good:
        uniq[(r["symbol"], r["report_date"], r["client_name"], r["action"] or "",
              r["quantity"] or "", r["average_price"] or "")] = r
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(uniq.values())
    with open(SKIPPED, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "reason", "raw"])
        w.writeheader()
        w.writerows(bad)
    print(f"wrote {len(uniq)} unique rows -> {OUT}")
    print(f"wrote {len(bad)} skipped rows -> {SKIPPED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
