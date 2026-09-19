"""QA-06 manual spot-checks: fetch the BSE results PDF for 3 filings (direct, logged, stored as artifacts) and write its
text next to the archive for a human read. The READ itself is recorded by hand in manual_checks.json (performed by the
agent, pending owner confirmation) - this script never extracts or asserts a value from the PDF.

run: python3 manual_checks.py <analysis.json>
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/app/.claude/worktrees/paper-engine/backend")

from archive import Archive  # noqa: E402
from contracts import IST, iso  # noqa: E402
from nse_ground_truth import RequestLog  # noqa: E402

CHECKS = [("LICHSGFIN", "2024-09-30", "STANDALONE"), ("3MINDIA", "2026-06-30", "STANDALONE"),
          ("HINDUNILVR", "2025-12-31", "CONSOLIDATED")]
BASES = ["https://www.bseindia.com/xml-data/corpfiling/AttachLive/", "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"]
OUT = "/app/research/pit_audit/manual"


async def main(analysis_path: str):
    from nidp.shared.sources.bse_fetcher import fetch_bytes
    d = json.load(open(analysis_path))
    bse = Archive("/app/research/pit_audit/bse")
    rows = {r["raw_row"].get("NEWSID"): r["raw_row"] for r in bse.read("bse_announcements")}
    log = RequestLog(bse, "manual_checks")
    os.makedirs(OUT, exist_ok=True)
    for sym, pe, basis in CHECKS:
        a = next(a for a in d["availability"] if a["symbol"] == sym and a["period_end"] == pe
                 and a["filing_type"] == "RESULTS" and a["basis"] == basis and a["revision_flag"] != "REVISED")
        att = rows[a["bse_match"]["newsid"]]["ATTACHMENTNAME"]
        for base in BASES:
            t0, body, status, err = time.time(), None, None, None
            try:
                body, status = await fetch_bytes(base + att)
            except Exception as e:  # logged; the next base URL is tried, and a total failure is printed
                err = f"{type(e).__name__}: {str(e)[:200]}"
            log.record("results_pdf", base + att, False, status, body, t0, err, {"symbol": sym, "period_end": pe})
            if body is not None and status == 200 and body[:4] == b"%PDF":
                h, path = bse.store_artifact(body, ".pdf")
                txt = os.path.join(OUT, f"{sym}_{pe}.txt")
                subprocess.run(["pdftotext", "-layout", path, txt], check=True)
                print(sym, pe, basis, "pdf", h, "->", txt, "| NSE broadcast", a["broadcast_at"], "| BSE", a["bse_match"]["dissem_at"])
                break
        else:
            print(sym, pe, "PDF NOT RETRIEVED", err, status)
        await asyncio.sleep(1.0)
    bse.append("run_summaries", [dict({"step": "manual_checks", "finished_at": iso(dt.datetime.now(IST))}, **log.counts)])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
