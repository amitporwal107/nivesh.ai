#!/usr/bin/env python3
"""run_fno_expiry_study.py: Stage B2 expiry-curve study on exported warehouse CSVs. READ ONLY; writes only the report.

    python3 -m scripts.run_fno_expiry_study --stf stf.csv --adj adj.csv --industry ind.csv --baseline <report.json> --out report.json --code-version <sha>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _f(x):
    return None if x in ("", None) else float(x)


def load(stf, adj, industry):
    rows = [{"day": r["as_of_date"], "sym": r["sym"].upper(), "exp": r["exp"], "c": _f(r["c"]), "pc": _f(r["pc"]), "oi": _f(r["oi"]), "coi": _f(r["coi"]), "vol": _f(r["vol"])}
            for r in csv.DictReader(open(stf))]
    adjusted = {}
    for r in csv.DictReader(open(adj)):
        adjusted.setdefault(r["symbol"].upper(), []).append({"day": r["as_of_date"], "o": _f(r["o"]), "c": _f(r["c"])})
    ind = {r["symbol"].upper(): r["industry"] for r in csv.DictReader(open(industry))}
    return {"stf": rows, "adjusted": adjusted, "industry": ind}


def main() -> None:
    from services.fno_backtest import expiry_study as es
    ap = argparse.ArgumentParser()
    for a in ("stf", "adj", "industry", "baseline", "out"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--code-version", default="")
    ap.add_argument("--perms", type=int, default=es.N_PERM)
    a = ap.parse_args()
    base = json.loads(Path(a.baseline).read_text())
    if base.get("report_hash") != es.FROZEN_BASELINE_HASH:
        raise SystemExit(f"baseline hash {base.get('report_hash')} is not the frozen {es.FROZEN_BASELINE_HASH}: refusing to run")
    frozen = {c: [(f["config"]["price_pct"], f["config"]["oi_pct"], f["config"]["rvol"]) for f in base["threshold_study"]["categories"][c]["frozen"]] for c in es.CATEGORIES}
    if any(len(v) != 5 for v in frozen.values()):
        raise SystemExit("each category must have 5 frozen settings")
    rep = es.run(load(a.stf, a.adj, a.industry), frozen, code_version=a.code_version, generated_at=datetime.now(timezone.utc).isoformat(), n_perm=a.perms)
    Path(a.out).write_text(json.dumps(rep, indent=1, default=str))
    print("experiment", rep["experiment_id"], "hash", rep["report_hash"][:16], "configs tested", rep["tested_configurations"])


if __name__ == "__main__":
    main()
