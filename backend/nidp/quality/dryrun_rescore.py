"""Dry-run re-score: what the fixed rules and score say about past dates, written nowhere.

    python -m nidp.quality.dryrun_rescore --from 2026-10-12 --to 2026-10-27 [--domains equity,mf]

For each trading date and domain it runs every registered consistency rule and computes the quality score with the
CURRENT code, entirely inside a READ ONLY transaction: Postgres itself refuses any INSERT/UPDATE/DELETE, so a run
cannot change a quality score, a certification or a quarantine row. Beside each result it prints what is stored in
nidp.quality_scores today (the verdict the old code reached), so the change is visible date by date.

The gate outcome is worked out here with the gate's own decision matrix (nidp.shared.quality_gate), because the gate
class itself writes to the exception queue and quarantine log.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys

from nidp.shared.storage.pg import close_pool, get_pool
from nidp.shared.validation.consistency import get_consistency_rules
from nidp.shared.validation.consistency_rules import equity as _eq_rules  # noqa: F401  (registers the rules)
from nidp.shared.validation.consistency_rules import mf as _mf_rules      # noqa: F401
from nidp.shared.validation.quality_score import (ConsistencyInput, compute_quality_score, domain_ingesters)


def gate_outcome(q: float, k, blocks: int) -> tuple[str, str]:
    """The decision matrix of nidp.shared.quality_gate.QualityGate.evaluate, without its writes."""
    if blocks > 0:
        return "FAIL", f"{blocks} BLOCK finding(s)"
    if q < 95.0:
        return "FAIL", f"quality {q:.2f} < 95"
    if q < 98.0 or (k is not None and k < 90.0):
        return "REVIEW", f"quality {q:.2f}" + (f", confidence {k:.2f}" if k is not None else "")
    return "PASS", f"quality {q:.2f}"


async def rescore(start: dt.date, end: dt.date, domains: list[str]) -> list[dict]:
    pool = await get_pool()
    out: list[dict] = []
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            dates = [r["d"] for r in await conn.fetch(
                "SELECT DISTINCT as_of_date AS d FROM nidp.prices_eod WHERE as_of_date BETWEEN $1 AND $2 "
                "ORDER BY 1", start, end)]
            for d in dates:
                for domain in domains:
                    rules = get_consistency_rules(domain)
                    findings, crashed, errors = [], 0, []
                    for rule in rules:
                        try:
                            findings.extend(await rule.check(conn, d))
                        except Exception as exc:                                     # noqa: BLE001
                            crashed += 1
                            errors.append(f"{rule.name}: {type(exc).__name__}: {str(exc)[:120]}")
                    inp = ConsistencyInput.from_findings(len(rules), findings, crashed=crashed)
                    score = await compute_quality_score(conn, d, domain, consistency_input=inp)
                    val_blocks = int(await conn.fetchval(
                        "SELECT count(*) FROM nidp.validation_findings vf "
                        "JOIN nidp.validation_runs vr ON vr.job_run_id = vf.job_run_id "
                        "WHERE vr.target_date = $1 AND vf.failure_class = 'BLOCK' AND vf.ingester = ANY($2::text[])",
                        d, domain_ingesters(domain)) or 0)
                    cons_blocks = sum(1 for f in findings if f.failure_class.value == "BLOCK")
                    outcome, why = gate_outcome(score.overall, score.confidence, val_blocks + cons_blocks)
                    before = await conn.fetchrow(
                        "SELECT overall_score, certification, publish_decision FROM nidp.quality_scores "
                        "WHERE target_date = $1 AND domain = $2 ORDER BY computed_at DESC LIMIT 1", d, domain)
                    per_rule: dict[str, int] = {}
                    for f in findings:
                        per_rule[f.rule_name] = per_rule.get(f.rule_name, 0) + 1
                    out.append({
                        "date": d.isoformat(), "domain": domain,
                        "before": dict(before) if before else None,
                        "after": {"overall": score.overall, "accuracy": score.accuracy,
                                  "consistency": score.consistency, "completeness": score.completeness,
                                  "freshness": score.freshness, "auditability": score.auditability,
                                  "confidence": score.confidence, "certification": score.certification,
                                  "outcome": outcome, "why": why},
                        "fired": {name: {"worst": inp.fired.get(name), "findings": n} for name, n in per_rule.items()},
                        "samples": [f"{f.rule_name} {f.entity_id or ''}: {f.message[:140]}" for f in findings
                                    if f.rule_name in ("equity.prev_close_continuity",
                                                       "equity.price_temporal_change")][:6],
                        "crashed": errors,
                    })
    await close_pool()
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--domains", default="equity,mf")
    a = p.parse_args()
    rows = asyncio.run(rescore(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end),
                               [x.strip() for x in a.domains.split(",") if x.strip()]))
    for r in rows:
        b, af = r["before"] or {}, r["after"]
        print(f"{r['date']} {r['domain']:6s} before {b.get('overall_score', '-')!s:>7} "
              f"{b.get('certification', '-')!s:8s} {b.get('publish_decision', '-')!s:13s} | after "
              f"{af['overall']:7.3f} {af['certification']:8s} {af['outcome']:6s} "
              f"A={af['accuracy']:.1f} C={af['consistency']:.2f} P={af['completeness']:.1f} "
              f"F={af['freshness']:.1f} U={af['auditability']:.1f} fired={json.dumps(r['fired'])}")
        for s in r["samples"]:
            print(f"      {s}")
        for e in r["crashed"]:
            print(f"      CRASHED {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
