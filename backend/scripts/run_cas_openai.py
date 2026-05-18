"""One-shot test runner: parse priyanka_nsdl.pdf and varun_cdsl.pdf via
GPT-5 Vision, compare against expected ground-truth JSON, and print
latency + accuracy.

Reads OPENAI_API_KEY from stdin (so the value never appears in argv or
bash history). Stores it via helpers.secrets.set_override so the parser
picks it up without env-var pollution.

Run via:
    python3 scripts/run_cas_openai.py <<< "$OPENAI_API_KEY"

Or from a saved key file:
    python3 scripts/run_cas_openai.py < /path/to/keyfile
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Add backend root to path so `services.*` and `helpers.*` resolve
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from helpers import secrets
from services.openai_cas_parser import parse_with_openai_vision
from services.claude_cas_mapper import map_to_internal

TEST_DATA = BACKEND / "tests" / "test_data"
EXPECTED = TEST_DATA / "expected_outputs"

CASES = [
    ("NSDL", TEST_DATA / "nsdl" / "priyanka_nsdl.pdf",
            EXPECTED / "priyanka_nsdl.json"),
    ("CDSL", TEST_DATA / "cdsl" / "varun_cdsl.pdf",
            EXPECTED / "varun_cdsl.json"),
]


def _load_expected(p: Path) -> dict:
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _expected_isins(expected: dict) -> set:
    """Pull every ISIN from the ground-truth JSON, whatever its shape."""
    isins = set()
    if not expected:
        return isins
    # Likely shape: same as parser output {holdings: {...}} OR flat list
    def _walk(node):
        if isinstance(node, dict):
            v = node.get("isin")
            if isinstance(v, str) and len(v) == 12 and v.startswith("IN"):
                isins.add(v)
            for vv in node.values():
                _walk(vv)
        elif isinstance(node, list):
            for it in node:
                _walk(it)
    _walk(expected)
    return isins


def _parser_isins(holdings: list) -> set:
    out = set()
    for h in holdings or []:
        tk = (h.get("ticker") or "").strip()
        if len(tk) == 12 and tk.startswith("IN"):
            out.add(tk)
        meta = h.get("metadata") or {}
        isin = (meta.get("isin") or "").strip()
        if len(isin) == 12 and isin.startswith("IN"):
            out.add(isin)
    return out


async def main():
    # Key source priority: env var → stdin (for piped-in setups).
    # The parser itself reads from helpers.secrets (which falls back to
    # env), so an exported OPENAI_API_KEY is enough.
    import os
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and not sys.stdin.isatty():
        key = sys.stdin.read().strip()
    if not key or not key.startswith("sk-"):
        print("ERROR: no OpenAI key (set OPENAI_API_KEY env var, or pipe key to stdin)",
              file=sys.stderr)
        sys.exit(2)
    secrets.set_override("OPENAI_API_KEY", key)
    print(f"[setup] OPENAI_API_KEY loaded ({len(key)} chars, prefix {key[:7]}...)")
    print(f"[setup] CAS_OPENAI_MODEL = {secrets.get('CAS_OPENAI_MODEL') or 'gpt-5 (default)'}")
    print()

    for label, pdf_path, expected_path in CASES:
        if not pdf_path.exists():
            print(f"[{label}] SKIP — missing {pdf_path}")
            continue
        pdf_bytes = pdf_path.read_bytes()
        print(f"[{label}] {pdf_path.name}  ({len(pdf_bytes):,} bytes)")
        t0 = time.monotonic()
        try:
            raw = await parse_with_openai_vision(pdf_bytes, password="")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"[{label}]   FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
            print()
            continue
        elapsed = time.monotonic() - t0

        if raw is None:
            print(f"[{label}]   FAILED — parser returned None (parse error)  [{elapsed:.1f}s]")
            print()
            continue

        # Persist raw JSON so we can debug merge / mapper bugs separately
        dump_path = Path("/tmp") / f"cas_raw_{label.lower()}.json"
        dump_path.write_text(json.dumps(raw, indent=2, default=str))
        print(f"[{label}]   raw JSON saved to {dump_path}")
        raw_h = raw.get("holdings") or {}
        for k in ("equities", "preference_shares", "sovereign_gold_bonds",
                  "mutual_funds_demat", "mutual_fund_folios"):
            n = len(raw_h.get(k) or [])
            if n:
                print(f"[{label}]   raw.holdings.{k}: {n}")

        # Pull holdings via the same mapper the engine uses
        try:
            holdings, _norm = map_to_internal(raw)
        except Exception as exc:
            print(f"[{label}]   mapper FAILED: {exc}")
            print(f"[{label}]   raw holdings shape: {list((raw.get('holdings') or {}).keys())}")
            print()
            continue

        by_type: dict = {}
        for h in holdings:
            by_type[h.get("asset_type") or "unknown"] = by_type.get(h.get("asset_type") or "unknown", 0) + 1

        expected = _load_expected(expected_path)
        exp_isins = _expected_isins(expected)
        got_isins = _parser_isins(holdings)

        if exp_isins:
            tp = exp_isins & got_isins
            fn = exp_isins - got_isins
            fp = got_isins - exp_isins
            recall = len(tp) / len(exp_isins) if exp_isins else 0
            precision = len(tp) / len(got_isins) if got_isins else 0
            print(f"[{label}]   latency: {elapsed:.1f}s   holdings: {len(holdings)}   "
                  f"by_type: {by_type}")
            print(f"[{label}]   ISIN recall: {len(tp)}/{len(exp_isins)} = "
                  f"{recall*100:.1f}%   precision: {len(tp)}/{len(got_isins)} = "
                  f"{precision*100:.1f}%")
            if fn:
                print(f"[{label}]   missed ISINs ({len(fn)}): {sorted(fn)[:8]}"
                      f"{'...' if len(fn) > 8 else ''}")
            if fp:
                print(f"[{label}]   extra ISINs ({len(fp)}): {sorted(fp)[:8]}"
                      f"{'...' if len(fp) > 8 else ''}")
        else:
            print(f"[{label}]   latency: {elapsed:.1f}s   holdings: {len(holdings)}   "
                  f"by_type: {by_type}")
            print(f"[{label}]   (no ground-truth file at {expected_path} — accuracy not computed)")

        # Surface investor/statement info for sanity
        si = raw.get("statement_info") or {}
        ii = raw.get("investor_info") or {}
        print(f"[{label}]   depository: {si.get('depository')}   "
              f"investor: {ii.get('name')}   period: {si.get('period')}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
