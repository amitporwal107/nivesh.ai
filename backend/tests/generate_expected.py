"""Generate golden expected-output JSON files for CAS benchmark tests.

Run once after importing CAS PDFs via the Gmail UI for the test account:

    CAS_TEST_PASSWORD=ABCDE1234F python tests/generate_expected.py

This reads every PDF in tests/test_data/nsdl/ahaanporwal/, parses it with
the casparser fast-path, and writes the result to:
    tests/test_data/expected_outputs/ahaanporwal/<stem>.json

Commit both the PDF and the generated JSON so CI can verify regressions.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURE_DIR = Path(__file__).parent / "test_data" / "nsdl" / "ahaanporwal"
EXPECTED_DIR = Path(__file__).parent / "test_data" / "expected_outputs" / "ahaanporwal"
EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

PASSWORD = os.environ.get("CAS_TEST_PASSWORD", "")


def generate_for_pdf(pdf_path: Path) -> dict:
    from helpers.parsing import convert_casparser_to_holdings, _normalize_casparser_folios

    import casparser as _cp

    with open(pdf_path, "rb") as f:
        raw_bytes = f.read()

    raw = _cp.read_cas_pdf(io.BytesIO(raw_bytes), PASSWORD or "", output="dict")
    holdings = convert_casparser_to_holdings(raw)

    return {
        "source_file": pdf_path.name,
        "holdings_count": len(holdings),
        "holdings": holdings,
        "folios": _normalize_casparser_folios(raw).get("mutual_funds", []),
    }


def main():
    pdfs = sorted(FIXTURE_DIR.glob("*.PDF")) + sorted(FIXTURE_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {FIXTURE_DIR}")
        print("Import CAS PDFs via the Gmail Import UI first (use ahaanporwal16@gmail.com).")
        return

    for pdf in pdfs:
        out_path = EXPECTED_DIR / (pdf.stem + ".json")
        if out_path.exists():
            print(f"  SKIP  {pdf.name} (expected JSON already exists — delete to regenerate)")
            continue
        print(f"  PARSE {pdf.name} ...", end=" ", flush=True)
        try:
            result = generate_for_pdf(pdf)
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            print(f"OK  ({result['holdings_count']} holdings → {out_path.name})")
        except Exception as e:
            print(f"FAIL  ({e})")

    print("\nDone. Verify the JSON files and commit them alongside the PDFs.")


if __name__ == "__main__":
    main()
