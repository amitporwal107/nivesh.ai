"""
nidp_gate — runs a suite and maps results to the real plumbing schema.

Flow per asset (flag-only posture):
  1. META-GUARD first: columns-exist + non-empty. A missing column or empty batch
     ABORTS the suite with an ERROR verdict — never a silent pass.
  2. Run each rule -> CheckResult.
  3. Verdict for v_feed_status: any error/fail -> FAIL; any warn-failure -> WARN; else OK.
  4. Map failures -> nidp.validation_findings rows; header -> nidp.validation_runs.

Real validation_findings columns (from the schema pass):
  finding_id(uuid, generated), validation_id, job_run_id, ingester, target_date,
  rule_name <- rule.name, severity, failure_class <- category (C1..C8),
  message, expected <- kwargs json, actual <- unexpected_count/%,
  sample_rows(jsonb) <- partial_unexpected_list, detected_at(tstz).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd

from .dq_primitives import CheckResult, assert_columns_exist, expect_non_empty
from .dq_sink import severity_for, status_for, action_for, as_text


@dataclass
class RunContext:
    ingester: str
    target_date: date
    validation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_run_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SuiteRun:
    suite: object
    results: list
    verdict: str          # "OK" | "WARN" | "FAIL"
    aborted: bool = False

    @property
    def failures(self):
        return [r for r in self.results if not r.success]


def _verdict(results) -> str:
    fails = [r for r in results if not r.success]
    if any(r.severity in ("error", "fail") for r in fails):
        return "FAIL"
    if fails:                         # only warns
        return "WARN"
    return "OK"


def run_suite(suite, df: pd.DataFrame) -> SuiteRun:
    results: list[CheckResult] = []

    # --- META-GUARD: defeats the "validates nothing" failure mode ---
    cols = assert_columns_exist(suite.asset, suite.required_columns, df.columns)
    results.append(cols)
    if not cols.success:
        return SuiteRun(suite, results, "FAIL", aborted=True)

    nonempty = expect_non_empty(suite.asset, df)
    results.append(nonempty)
    if not nonempty.success:
        return SuiteRun(suite, results, "FAIL", aborted=True)

    # --- the reviewed rules ---
    for rule in suite.rules:
        try:
            r = rule.run(df)
        except Exception as exc:  # a crashing check is an ERROR, not a silent skip
            r = CheckResult(check=rule.name, asset=suite.asset, success=False,
                            severity="error", category=rule.category,
                            message=f"check raised: {exc!r}")
        r.asset = suite.asset
        results.append(r)

    return SuiteRun(suite, results, _verdict(results))


# ---------------------------------------------------------------------------
# Persistence mapping -> REAL nidp.validation_findings / validation_runs columns
# ---------------------------------------------------------------------------
# severity      -> {INFO, WARN, ERROR, CRITICAL}   (how bad)
# failure_class -> {RETRY, FIX, BLOCK, INFO}       (what action; NOT the C-taxonomy)
# status        -> {PASSED, FAILED, PARTIAL, ERROR}
# expected/actual are TEXT; partition key is job_run_id.
def finding_rows(run: SuiteRun, ctx: RunContext) -> list[dict]:
    rows = []
    detected = datetime.now(timezone.utc).isoformat()
    for res in run.failures:
        # keep the C-taxonomy visible in the message (it's not a column)
        msg = f"[{res.category}] {res.message}"
        rows.append({
            "finding_id": str(uuid.uuid4()),
            "validation_id": ctx.validation_id,
            "job_run_id": ctx.job_run_id,                       # partition/identity key
            "ingester": run.suite.ingester,
            "target_date": ctx.target_date.isoformat(),
            "rule_name": res.check,
            "severity": severity_for(res.severity),             # INFO/WARN/ERROR/CRITICAL
            "failure_class": action_for(res.check, res.category),  # RETRY/FIX/BLOCK/INFO
            "message": msg,
            "expected": as_text(res.observed.get("expected", {})),  # TEXT
            "actual": as_text(res.observed.get("actual")),          # TEXT
            "sample_rows": json.dumps(res.violations[:50], default=str),  # jsonb
            "detected_at": detected,
        })
    return rows


def run_header(run: SuiteRun, ctx: RunContext) -> dict:
    failed = run.failures
    # a meta-guard abort or a crashing check is a run-level ERROR, not just FAILED
    has_meta_error = any(r.category == "meta" and not r.success for r in run.results)
    status = "ERROR" if (run.aborted or has_meta_error) else status_for(run.verdict)
    return {
        "validation_id": ctx.validation_id,
        "job_run_id": ctx.job_run_id,
        "ingester": run.suite.ingester,
        "target_date": ctx.target_date.isoformat(),
        "status": status,                                       # PASSED/FAILED/PARTIAL/ERROR
        "rules_run": len(run.results),
        "rules_failed": len(failed),
        "findings_count": len(failed),
    }


# ---------------------------------------------------------------------------
# Demo: run the trio against deliberately dirty data
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from .dq_suites import build_suites

    suites = build_suites()

    # dirty mf_holdings: a NIPPON-style scheme summing to 224%, a subtotal row, a 412 corruption
    mf = pd.DataFrame([
        ("N1", date(2026, 5, 31), "INE001A01036", "Reliance Ltd", "", 60.0, "AMC"),
        ("N1", date(2026, 5, 31), "INE002A01018", "TCS Ltd",      "", 164.0, "AMC"),  # -> sum 224
        ("N2", date(2026, 5, 31), "INE003A01024", "HDFC Ltd",     "", 50.0, "AMC"),
        ("N2", date(2026, 5, 31), "INE004A01020", "Infosys Ltd",  "", 49.5, "AMC"),
        ("N2", date(2026, 5, 31), "",             "Grand Total",  "", 99.5, "AMC"),   # subtotal row
        ("N3", date(2026, 5, 31), "INE005A01011", "ITC Ltd",      "", 412.8, "AMC"),  # corruption
        ("N3", date(2026, 5, 31), "INE006A01017", "Wipro short",  "", -20.0, "AMC"),  # legit short
    ], columns=["scheme_code", "as_of_month", "security_isin", "security_name",
                "instrument_type", "weight_pct", "source"])

    ctx = RunContext(ingester="mf_holdings", target_date=date(2026, 5, 31))
    run = run_suite(suites["mf_holdings"], mf)
    print(f"VERDICT: {run.verdict}\n")
    print("HEADER:", json.dumps(run_header(run, ctx), indent=2))
    print("\nFINDINGS:")
    for f in finding_rows(run, ctx):
        print(f"  [{f['severity']:5}] {f['failure_class']:4} {f['rule_name']:40} "
              f"actual={f['actual']}  {f['message']}")
