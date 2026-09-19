"""Audit sample manifest (OPS-01): 30 fixed-seed random current Nifty 500 members + 10 restatement / calendar-risk names."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random

N500 = "/app/research/screener/ref/ind_nifty500list.csv"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "sample_manifest.json")
SEED = 20260919
RISK = {  # symbol -> reason (all verified present in the Nifty 500 list on 2026-09-19)
    "ITC": "ITC Hotels demerger (Jan 2025): discontinued operations",
    "HINDUNILVR": "ice-cream (Kwality Wall's) demerger 2025",
    "SIEMENS": "Siemens Energy demerger 2025",
    "ULTRACEMCO": "Kesoram cement scheme",
    "IDFCFIRSTB": "IDFC Ltd merger (Oct 2024)",
    "TMPV": "Tata Motors demerger + symbol rename (earlier filings under TATAMOTORS)",
    "ABCAPITAL": "ABFL amalgamation",
    "VEDL": "demerger scheme",
    "CASTROLIND": "December fiscal year-end",
    "ABB": "December fiscal year-end",
}
ALIASES = {"TMPV": ["TATAMOTORS"]}
QUARTERS = ["2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


def build() -> dict:
    raw = open(N500, "rb").read()
    members = sorted(r["Symbol"] for r in csv.DictReader(open(N500)))
    missing = [s for s in RISK if s not in members]
    if missing:
        raise SystemExit(f"risk names not in the Nifty 500 list: {missing}")
    pool = [s for s in members if s not in RISK]
    rnd = random.Random(SEED).sample(pool, 30)
    return {"seed": SEED, "universe_file": N500, "universe_sha256": hashlib.sha256(raw).hexdigest(),
            "universe_size": len(members), "random": sorted(rnd), "risk": RISK, "aliases": ALIASES,
            "quarters": QUARTERS, "symbols": sorted(rnd) + sorted(RISK)}


if __name__ == "__main__":
    m = build()
    if os.path.exists(OUT):
        old = json.load(open(OUT))
        if old["symbols"] != m["symbols"]:
            raise SystemExit("sample manifest exists and differs — refusing to overwrite a frozen sample")
    else:
        json.dump(m, open(OUT, "w"), indent=1)
    print(len(m["symbols"]), "symbols;", "random:", ", ".join(m["random"]))
