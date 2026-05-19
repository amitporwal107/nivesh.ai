"""Demo runner: exercise the same code path the live `/api/portfolio/upload`
endpoint uses, and print the JSON the API would return when the polled
status flips to "completed".

This script calls `helpers.parsing.parse_cas_pdf_with_data` directly —
that is the exact function `_process_cas_background` (in
`routes/upload.py`) invokes after the API hands the PDF off for async
parsing. The output is the same `(holdings, normalized, raw_payload,
parser_source)` tuple that the background task writes into the
`upload_tasks` Mongo doc the frontend polls.

Run from /app/backend:
    export OPENAI_API_KEY='sk-proj-...'    # one-time, in your shell
    /root/.venv/bin/python3 scripts/run_cas_api_demo.py
"""
from __future__ import annotations

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
CASES = [
    ("NSDL", TEST_DATA / "nsdl" / "priyanka_nsdl.pdf"),
    ("CDSL", TEST_DATA / "cdsl" / "varun_cdsl.pdf"),
]


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
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key and key.startswith("sk-"):
        secrets.set_override("OPENAI_API_KEY", key)
        print(f"[setup] OPENAI_API_KEY loaded ({len(key)} chars, prefix {key[:7]}...)")
    else:
        print("[setup] OPENAI_API_KEY not set — chain will skip GPT-5 and "
              "fall through to casparser-lib + Docling")
    print()

    for label, pdf_path in CASES:
        if not pdf_path.exists():
            print(f"[{label}] SKIP — missing {pdf_path}")
            continue
        pdf_bytes = pdf_path.read_bytes()
        print(f"════════ [{label}] {pdf_path.name}  ({len(pdf_bytes):,} bytes) ════════")
        t0 = time.monotonic()
        try:
            holdings, normalized, raw_payload, parser_source = await parse_cas_pdf_with_data(
                pdf_bytes, password=""
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"  FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
            print()
            continue
        elapsed = time.monotonic() - t0

        api_resp = _api_response_for_task(holdings, parser_source, elapsed)

        # First, the API-equivalent response the frontend would see after polling
        # — truncated holdings for screen-friendliness; full list dumped below.
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

        # Save full output for inspection
        dump_path = Path("/tmp") / f"cas_api_{label.lower()}.json"
        dump_path.write_text(json.dumps(api_resp, indent=2, default=str))
        print(f"\n  Full response written to {dump_path} "
              f"({len(api_resp['holdings'])} holdings, parser={parser_source})")
        print()


if __name__ == "__main__":
    asyncio.run(main())
