"""Demo runner: exercise the same code path the live `/api/portfolio/upload`
endpoint uses, and print the JSON the API would return when the polled
status flips to "completed".

This script calls `helpers.parsing.parse_cas_pdf_with_data` directly —
that is the exact function `_process_cas_background` (in
`routes/upload.py`) invokes after the API hands the PDF off for async
parsing. The output is the same `(holdings, normalized, raw_payload,
parser_source)` tuple that the background task writes into the
`upload_tasks` Mongo doc the frontend polls.

Usage:
    export OPENAI_API_KEY='sk-proj-...'          # one-time, in your shell

    # default test PDFs (priyanka_nsdl, varun_cdsl):
    /root/.venv/bin/python3 scripts/run_cas_api_demo.py

    # arbitrary archived CAS PDFs:
    /root/.venv/bin/python3 scripts/run_cas_api_demo.py \
        /app/data/cas_uploads/<dir>/<file>.pdf \
        /app/data/gmail_cas/user_<hex>/<file>.pdf

    # with PAN password (for password-protected CAS PDFs):
    /root/.venv/bin/python3 scripts/run_cas_api_demo.py \
        --password ABCDE1234F /path/to/file.pdf

    # with a previously-parsed JSON for expected-vs-actual diff:
    /root/.venv/bin/python3 scripts/run_cas_api_demo.py \
        --expected /path/to/expected.json /path/to/file.pdf
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Backend imports require these env vars to construct the deps module;
# stub them locally so the script can import helpers.parsing without
# requiring a Mongo connection.
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/_demo")
os.environ.setdefault("DB_NAME", "_demo")
os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))

from helpers import secrets
from helpers.parsing import parse_cas_pdf_with_data

TEST_DATA = BACKEND / "tests" / "test_data"
DEFAULT_CASES = [
    ("NSDL", TEST_DATA / "nsdl" / "priyanka_nsdl.pdf"),
    ("CDSL", TEST_DATA / "cdsl" / "varun_cdsl.pdf"),
]


def _isins_from_holdings(holdings):
    """Pull every ISIN-like 12-char ticker out of a holdings list,
    regardless of whether it lives in `ticker` or `metadata.isin`."""
    s = set()
    for h in holdings or []:
        tk = (h.get("ticker") or "").strip()
        if len(tk) == 12 and tk.startswith("IN"):
            s.add(tk)
        meta = h.get("metadata") or {}
        isin = (meta.get("isin") or "").strip()
        if len(isin) == 12 and isin.startswith("IN"):
            s.add(isin)
    return s


def _isins_from_anywhere(node):
    """Recursive walk over an arbitrary JSON to collect every ISIN —
    works on raw parser output (`holdings.equities[].isin`), on the
    parser's normalized holdings list, and on hand-written expected
    JSON snippets."""
    out = set()
    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, str) and len(v) == 12 and v.startswith("IN") and k.lower() in ("isin", "ticker"):
                    out.add(v)
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)
    walk(node)
    return out


def _diff_against_expected(holdings, expected_path):
    """Compare actual holdings ISINs vs expected JSON. Returns a
    summary dict with recall/precision/missing/extra."""
    expected = json.loads(Path(expected_path).read_text())
    got_isins = _isins_from_holdings(holdings)
    exp_isins = _isins_from_anywhere(expected)
    if not exp_isins:
        return {"warning": "expected JSON contained no ISIN-like fields"}
    tp = got_isins & exp_isins
    return {
        "expected_count": len(exp_isins),
        "actual_count": len(got_isins),
        "recall_pct": round(100 * len(tp) / len(exp_isins), 1),
        "precision_pct": round(100 * len(tp) / max(len(got_isins), 1), 1),
        "missing_isins": sorted(exp_isins - got_isins)[:20],
        "extra_isins": sorted(got_isins - exp_isins)[:20],
    }


def _api_response_for_task(holdings, parser_source, latency_s):
    """Build the JSON shape the polling endpoint returns when the
    background task completes — mirrors what `_process_cas_background`
    writes into db.upload_tasks (count, holdings, status, message,
    parser_source)."""
    return {
        "status": "completed",
        "message": f"{len(holdings)} holdings imported from CAS PDF",
        "count": len(holdings),
        "parser_source": parser_source,
        "latency_seconds": round(latency_s, 2),
        "holdings": holdings,
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Run the production CAS parser chain on one or more PDFs "
                    "and optionally diff against expected output.",
    )
    parser.add_argument("pdfs", nargs="*", help="PDF file path(s) to test. "
                        "If omitted, uses tests/test_data/{nsdl,cdsl} defaults.")
    parser.add_argument("--password", default="",
                        help="CAS PDF password (PAN uppercase, e.g. ABCDE1234F)")
    parser.add_argument("--expected", default=None,
                        help="Path to expected JSON for ISIN recall/precision diff. "
                             "When multiple --pdfs are passed, the same expected file "
                             "is used for each (override per file by using a single "
                             "--pdf invocation).")
    args = parser.parse_args()

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key and key.startswith("sk-"):
        secrets.set_override("OPENAI_API_KEY", key)
        print(f"[setup] OPENAI_API_KEY loaded ({len(key)} chars, prefix {key[:7]}...)")
    else:
        print("[setup] OPENAI_API_KEY not set — chain will skip GPT-5 and "
              "fall through to casparser-lib + Docling")
    print()

    # Resolve cases
    if args.pdfs:
        cases = [(Path(p).stem, Path(p)) for p in args.pdfs]
    else:
        cases = DEFAULT_CASES

    for label, pdf_path in cases:
        if not pdf_path.exists():
            print(f"[{label}] SKIP — missing {pdf_path}")
            continue
        pdf_bytes = pdf_path.read_bytes()
        print(f"════════ [{label}] {pdf_path}  ({len(pdf_bytes):,} bytes) ════════")
        t0 = time.monotonic()
        try:
            holdings, normalized, raw_payload, parser_source = await parse_cas_pdf_with_data(
                pdf_bytes, password=args.password
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
            print()
            continue
        elapsed = time.monotonic() - t0

        api_resp = _api_response_for_task(holdings, parser_source, elapsed)

        # Compact preview — first 10 holdings, key fields only
        compact = {
            **api_resp,
            "holdings": [
                {
                    "ticker": h.get("ticker"),
                    "name": (h.get("name") or "")[:50],
                    "asset_type": h.get("asset_type"),
                    "quantity": h.get("quantity"),
                    "current_price": h.get("current_price"),
                    "current_value": h.get("current_value"),
                }
                for h in api_resp["holdings"][:10]
            ],
        }
        print("── API response (first 10 holdings shown) ──")
        print(json.dumps(compact, indent=2, default=str))

        # Diff against expected, if provided
        if args.expected:
            try:
                diff = _diff_against_expected(holdings, args.expected)
                print("\n── Expected-vs-actual diff (ISIN-level) ──")
                print(json.dumps(diff, indent=2, default=str))
            except FileNotFoundError:
                print(f"\n  WARN: expected file not found at {args.expected}")
            except json.JSONDecodeError as e:
                print(f"\n  WARN: expected file isn't valid JSON: {e}")

        # Persist full response for inspection
        dump_path = Path("/tmp") / f"cas_api_{label.lower()}.json"
        dump_path.write_text(json.dumps(api_resp, indent=2, default=str))
        print(f"\n  Full response written to {dump_path} "
              f"({len(api_resp['holdings'])} holdings, parser={parser_source})")
        print()


if __name__ == "__main__":
    asyncio.run(main())
