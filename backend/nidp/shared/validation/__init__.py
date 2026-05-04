"""NIDP data-quality / validation framework.

Each ingester gets a list of `Rule` objects checked after persist.
Findings are classified by `failure_class`:

    RETRY   — transient (e.g. partial fetch); re-run will likely fix
    FIX     — deterministic parser or data issue; needs human attention
    BLOCK   — data bad enough that downstream snapshots must NOT consume
              this ingester run
    INFO    — recorded for audit, not actionable

The snapshot engine reads BLOCK findings before building a daily
snapshot — any BLOCK for a date and the snapshot refuses to build.

Rules are pure-data: they take a SQL connection + run context and
return zero or more `Finding`s. They do NOT mutate facts.
"""
from .rules import Finding, Rule, RuleContext, Severity, FailureClass
from .runner import run_validation
from .registry import REGISTRY, register, get_rules

__all__ = [
    "Finding", "Rule", "RuleContext", "Severity", "FailureClass",
    "run_validation",
    "REGISTRY", "register", "get_rules",
]
