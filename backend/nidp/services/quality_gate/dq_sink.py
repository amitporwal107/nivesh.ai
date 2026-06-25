"""
nidp_sink — maps internal check results onto the REAL plumbing enums.

The schema pass (reading the live writers in services/quality_gate/) established
that there is ONE sink, nidp.validation_findings + nidp.validation_runs, and that
its columns use enums that are NOT the OK/WARN/FAIL literals the gate computes
internally. Two distinct axes the internal model conflated:

  severity      ∈ {INFO, WARN, ERROR, CRITICAL}     — "how bad"
  failure_class ∈ {RETRY, FIX, BLOCK, INFO}         — "what action"  (NOT C1..C8!)

C1..C8 is the *taxonomy* of the check (completeness/validity/...) and belongs in
the rule metadata / message, not in failure_class. failure_class is the operator
action: a stale feed is RETRY, a range violation is FIX, a contamination that
must not propagate is BLOCK (even under flag-only, BLOCK marks "do not trust"),
informational drift is INFO.

Run-level:
  validation_runs.status ∈ {PASSED, FAILED, PARTIAL, ERROR}
  expected / actual are TEXT columns (a boolean writes 'True'/'False').
  identity/partition key is job_run_id.
"""

from __future__ import annotations

# Internal check severity -> real per-finding severity enum
SEVERITY_MAP = {
    "warn": "WARN",
    "fail": "ERROR",
    "error": "CRITICAL",   # the check itself could not evaluate -> most severe
    "info": "INFO",
}

# Internal verdict -> real run status enum
STATUS_MAP = {
    "OK": "PASSED",
    "WARN": "PARTIAL",
    "FAIL": "FAILED",
    "ERROR": "ERROR",       # run-level exception (meta-guard abort, crash)
}

# Per-category default ACTION class. failure_class answers "what should the
# operator do", which is orthogonal to the C-taxonomy. These are defaults; a
# rule can override via Rule.action.
CATEGORY_ACTION = {
    "C1": "FIX",     # completeness — missing required data
    "C2": "FIX",     # validity/range/enum — bad values
    "C3": "FIX",     # cross-field consistency
    "C4": "BLOCK",   # grouped/aggregate (weight-sum corruption) — don't trust the group
    "C5": "RETRY",   # timeliness — stale, re-pull
    "C6": "FIX",     # uniqueness/golden-source
    "C7": "FIX",     # cross-source reconciliation
    "C8": "INFO",    # volume/distribution drift — informational by default
    "meta": "BLOCK", # misbound/empty/crash — suite couldn't validate -> don't trust
}

# A few checks warrant a non-default action regardless of category.
RULE_ACTION_OVERRIDES = {
    "C3.q4_annual_contamination": "BLOCK",   # contamination must not propagate to scoring
    "C5.freshness": "RETRY",
}


def severity_for(internal_severity: str) -> str:
    return SEVERITY_MAP.get(internal_severity, "ERROR")


def status_for(verdict: str) -> str:
    return STATUS_MAP.get(verdict, "ERROR")


def action_for(rule_name: str, category: str) -> str:
    for prefix, action in RULE_ACTION_OVERRIDES.items():
        if rule_name.startswith(prefix):
            return action
    return CATEGORY_ACTION.get(category, "FIX")


def as_text(value) -> str | None:
    """expected/actual are TEXT columns — render scalars/bools/dicts as text."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, default=str)
    return str(value)
