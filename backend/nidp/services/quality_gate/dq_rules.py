"""
nidp_expectations — the declarative DQ rules library the gate runs.

Each rule is a ``Rule``: a name, a taxonomy category (C1..C8 -> failure_class),
a default severity, a check function, and its kwargs. Rules are data: you can
list them, diff them in review, and the gate executes them uniformly. Every
check returns a ``CheckResult`` (from nidp_dq_primitives) so persistence and
verdict are uniform across the standard primitives and the special ones
(freshness / Q4-contamination / meta-guard).

Severity convention:
    "error" — the check could not evaluate (missing key column) -> abort suite
    "fail"  — bad data, high confidence
    "warn"  — suspicious or stylistic (e.g. non-canonical casing) — surfaced, not gated hard

The four schema-forced CORRECTIONS from the trio review are encoded here and in
nidp_suites; each has a regression test in test_nidp_dq.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

from .dq_primitives import (
    CheckResult, TradingCalendar,
    freshness_within_trading_days, detect_q4_annual_contamination,
)

# Standard ISIN: 2 alpha country + 9 alnum + 1 check digit
ISIN_REGEX = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"

# Word-boundary subtotal markers; \btotal\b matches "Total" / "Grand Total"
# but NOT "TotalEnergies" (no boundary between 'l' and 'E').
DEFAULT_SUBTOTAL_REGEX = r"(?i)\b(sub[\s-]*total|grand\s+total|total|net\s+assets?)\b"


# ---------------------------------------------------------------------------
# Rule abstraction
# ---------------------------------------------------------------------------
@dataclass
class Rule:
    name: str
    category: str               # C1..C8 or "meta"
    severity: str               # default severity on failure
    fn: Callable
    kwargs: dict = field(default_factory=dict)
    description: str = ""

    def run(self, df: pd.DataFrame) -> CheckResult:
        return self.fn(df, severity=self.severity, category=self.category,
                       name=self.name, **self.kwargs)


def _result(name, category, success, severity, message, *, actual=None,
            expected=None, violations=None) -> CheckResult:
    obs = {}
    if actual is not None:
        obs["actual"] = actual
    if expected is not None:
        obs["expected"] = expected
    return CheckResult(check=name, asset="", success=success,
                       severity=severity if not success else "warn",
                       category=category, message=message, observed=obs,
                       violations=violations or [])


def _missing_cols(df, cols):
    return [c for c in cols if c not in df.columns]


# ===========================================================================
# C1 — Completeness
# ===========================================================================
def not_null(*cols, severity="fail") -> Rule:
    return Rule(f"C1.not_null[{','.join(cols)}]", "C1", severity, _not_null,
                {"cols": list(cols)})

def _not_null(df, *, cols, severity, category, name):
    miss = _missing_cols(df, cols)
    if miss:
        return _result(name, "meta", False, "error",
                       f"key column(s) absent: {miss}", expected={"cols": cols})
    bad_mask = df[cols].isna().any(axis=1)
    n = int(bad_mask.sum())
    viols = df[bad_mask][cols].head(50).to_dict("records")
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) null in {cols}", actual=n,
                   expected={"not_null": cols}, violations=viols)


def compound_unique(*cols, severity="fail", note="") -> Rule:
    desc = note or f"unique on {list(cols)}"
    return Rule(f"C6.compound_unique[{','.join(cols)}]", "C6", severity,
                _compound_unique, {"cols": list(cols)}, description=desc)

def _compound_unique(df, *, cols, severity, category, name):
    miss = _missing_cols(df, cols)
    if miss:
        return _result(name, "meta", False, "error",
                       f"key column(s) absent: {miss} — uniqueness validates nothing",
                       expected={"unique_on": cols})
    dup_mask = df.duplicated(subset=cols, keep=False)
    dups = df[dup_mask]
    viols = []
    for keyvals, grp in dups.groupby(cols):
        kv = keyvals if isinstance(keyvals, tuple) else (keyvals,)
        viols.append({**dict(zip(cols, [str(x) for x in kv])), "row_count": int(len(grp))})
    n = int(dup_mask.sum())
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) in {len(viols)} duplicate group(s) on {cols}",
                   actual=n, expected={"unique_on": cols}, violations=viols[:50])


# ===========================================================================
# C2 — Validity / range / enum / regex
# ===========================================================================
def between(col, *, min=None, max=None, inclusive=True, severity="fail") -> Rule:
    return Rule(f"C2.between[{col}]", "C2", severity, _between,
                {"col": col, "min": min, "max": max, "inclusive": inclusive})

def _between(df, *, col, min, max, inclusive, severity, category, name):
    if col not in df.columns:
        return _result(name, "meta", False, "error", f"column absent: {col}")
    v = pd.to_numeric(df[col], errors="coerce")
    cond = pd.Series(True, index=df.index)
    if min is not None:
        cond &= (v >= min) if inclusive else (v > min)
    if max is not None:
        cond &= (v <= max) if inclusive else (v < max)
    cond |= v.isna()                       # nulls are a completeness concern, not range
    bad = df[~cond]
    n = len(bad)
    viols = [{col: float(x)} for x in pd.to_numeric(bad[col], errors="coerce").head(50)]
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) of {col} outside [{min},{max}]",
                   actual=n, expected={"min": min, "max": max}, violations=viols)


def in_set(col, allowed, *, allow_blank=False, case_insensitive=False, severity="fail") -> Rule:
    return Rule(f"C2.in_set[{col}]", "C2", severity, _in_set,
                {"col": col, "allowed": set(allowed), "allow_blank": allow_blank,
                 "case_insensitive": case_insensitive})

def _in_set(df, *, col, allowed, allow_blank, case_insensitive, severity, category, name):
    if col not in df.columns:
        return _result(name, "meta", False, "error", f"column absent: {col}")
    cmp = {str(a).lower() for a in allowed} if case_insensitive else {str(a) for a in allowed}

    def ok(raw):
        if pd.isna(raw) or str(raw).strip() == "":
            return allow_blank
        sv = str(raw)
        return (sv.lower() in cmp) if case_insensitive else (sv in cmp)

    mask_ok = df[col].map(ok)
    bad = df[~mask_ok]
    n = len(bad)
    offending = sorted({str(x) for x in bad[col].unique()})[:20]
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) of {col} outside allowed set; offending={offending}",
                   actual=n, expected={"allowed": sorted(map(str, allowed)),
                                       "allow_blank": allow_blank,
                                       "case_insensitive": case_insensitive},
                   violations=[{col: o} for o in offending])


def canonical_casing(col, *, canonical="lower", severity="warn") -> Rule:
    """Flags values that ARE valid but not in canonical casing (e.g. 'QUARTERLY').
    Default warn: failing half the table is indistinguishable from no signal."""
    return Rule(f"C2.canonical_casing[{col}]", "C2", severity, _canonical_casing,
                {"col": col, "canonical": canonical})

def _canonical_casing(df, *, col, canonical, severity, category, name):
    if col not in df.columns:
        return _result(name, "meta", False, "error", f"column absent: {col}")
    s = df[col].dropna().astype(str)
    s = s[s.str.strip() != ""]

    def canon(v):
        if canonical == "lower":
            return v.lower()
        if canonical == "upper":
            return v.upper()
        if isinstance(canonical, dict):
            return canonical.get(v.lower(), v)
        return v

    bad_mask = s != s.map(canon)
    offending = sorted(s[bad_mask].unique())[:20]
    n = int(bad_mask.sum())
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) of {col} non-canonical casing; offending={offending}",
                   actual=n, expected={"canonical": canonical},
                   violations=[{col: o} for o in offending])


def match_regex(col, pattern, *, allow_blank=False, severity="fail") -> Rule:
    return Rule(f"C2.match_regex[{col}]", "C2", severity, _match_regex,
                {"col": col, "pattern": pattern, "allow_blank": allow_blank})

def _match_regex(df, *, col, pattern, allow_blank, severity, category, name):
    if col not in df.columns:
        return _result(name, "meta", False, "error", f"column absent: {col}")
    rx = re.compile(pattern)

    def ok(raw):
        if pd.isna(raw) or str(raw).strip() == "":
            return allow_blank
        return bool(rx.match(str(raw)))

    bad = df[~df[col].map(ok)]
    n = len(bad)
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) of {col} fail /{pattern}/",
                   actual=n, expected={"pattern": pattern, "allow_blank": allow_blank},
                   violations=[{col: str(x)} for x in bad[col].head(50)])


def no_subtotal_rows(col, *, pattern=DEFAULT_SUBTOTAL_REGEX, severity="fail") -> Rule:
    return Rule(f"C2.no_subtotal[{col}]", "C2", severity, _no_subtotal,
                {"col": col, "pattern": pattern})

def _no_subtotal(df, *, col, pattern, severity, category, name):
    if col not in df.columns:
        return _result(name, "meta", False, "error", f"column absent: {col}")
    rx = re.compile(pattern)
    bad = df[df[col].astype(str).map(lambda v: bool(rx.search(v)))]
    n = len(bad)
    return _result(name, category, n == 0, severity,
                   f"{n} subtotal-like row(s) in {col}",
                   actual=n, expected={"forbidden_pattern": pattern},
                   violations=[{col: str(x)} for x in bad[col].head(50)])


# ===========================================================================
# C3 — Cross-field consistency
# ===========================================================================
def pair_a_lte_b(a, b, *, tol=0.0, severity="fail") -> Rule:
    return Rule(f"C3.a_lte_b[{a}<= {b}]", "C3", severity, _pair_a_lte_b,
                {"a": a, "b": b, "tol": tol})

def _pair_a_lte_b(df, *, a, b, tol, severity, category, name):
    if _missing_cols(df, [a, b]):
        return _result(name, "meta", False, "error", f"column(s) absent: {_missing_cols(df,[a,b])}")
    av = pd.to_numeric(df[a], errors="coerce")
    bv = pd.to_numeric(df[b], errors="coerce")
    both = av.notna() & bv.notna()
    bad = df[both & ((av - bv) > tol)]
    n = len(bad)
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) where {a} > {b}", actual=n,
                   expected={"constraint": f"{a} <= {b}", "tol": tol},
                   violations=bad[[a, b]].head(50).astype(str).to_dict("records"))


def same_sign(a, b, *, severity="fail") -> Rule:
    return Rule(f"C3.same_sign[{a},{b}]", "C3", severity, _same_sign, {"a": a, "b": b})

def _same_sign(df, *, a, b, severity, category, name):
    if _missing_cols(df, [a, b]):
        return _result(name, "meta", False, "error", f"column(s) absent: {_missing_cols(df,[a,b])}")
    av = pd.to_numeric(df[a], errors="coerce")
    bv = pd.to_numeric(df[b], errors="coerce")
    both = av.notna() & bv.notna() & (av != 0) & (bv != 0)
    bad = df[both & ((av > 0) != (bv > 0))]
    n = len(bad)
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) where sign({a}) != sign({b})", actual=n,
                   expected={"constraint": f"sign({a}) == sign({b})"},
                   violations=bad[[a, b]].head(50).astype(str).to_dict("records"))


def columns_sum_to(cols, *, target=100.0, tol=1.0, severity="warn") -> Rule:
    return Rule(f"C3.sum_to[{','.join(cols)}]", "C3", severity, _columns_sum_to,
                {"cols": list(cols), "target": target, "tol": tol})

def _columns_sum_to(df, *, cols, target, tol, severity, category, name):
    if _missing_cols(df, cols):
        return _result(name, "meta", False, "error", f"column(s) absent: {_missing_cols(df,cols)}")
    rowsum = df[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
    diff = (rowsum - target).abs()
    bad = df[diff > tol]
    n = len(bad)
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) where sum{cols} != {target}±{tol}", actual=n,
                   expected={"sum_of": cols, "target": target, "tol": tol},
                   violations=[{"row_sum": float(x)} for x in rowsum[diff > tol].head(50)])


# ===========================================================================
# C4 — Grouped / aggregate  (NIPPON weight-sum guard)
# ===========================================================================
def grouped_sum_between(group_cols, value_col, *, min, max, severity="fail") -> Rule:
    gc = group_cols if isinstance(group_cols, (list, tuple)) else [group_cols]
    return Rule(f"C4.grouped_sum[{value_col} by {','.join(gc)}]", "C4", severity,
                _grouped_sum_between,
                {"group_cols": list(gc), "value_col": value_col, "min": min, "max": max})

def _grouped_sum_between(df, *, group_cols, value_col, min, max, severity, category, name):
    if _missing_cols(df, group_cols + [value_col]):
        miss = _missing_cols(df, group_cols + [value_col])
        return _result(name, "meta", False, "error", f"column(s) absent: {miss}")
    g = df.groupby(group_cols)[value_col].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()).reset_index()
    bad = g[(g[value_col] < min) | (g[value_col] > max)]
    viols = []
    for _, r in bad.iterrows():
        viols.append({**{gc: str(r[gc]) for gc in group_cols},
                      "group_sum": round(float(r[value_col]), 4)})
    # IMPORTANT: "actual" counts offending GROUPS (schemes), not rows.
    bad_groups = [v[group_cols[0]] for v in viols] if len(group_cols) == 1 else None
    return _result(name, category, bad.empty, severity,
                   f"{len(bad)} group(s) with {value_col} sum outside [{min},{max}]"
                   + (f"; e.g. {bad_groups[:5]}" if bad_groups else ""),
                   actual=len(bad),
                   expected={"per_group_sum_between": [min, max], "grouped_by": group_cols},
                   violations=viols[:50])


# ===========================================================================
# C5 — Timeliness
# ===========================================================================
def not_in_future(col, *, asof=None, severity="fail") -> Rule:
    return Rule(f"C5.not_in_future[{col}]", "C5", severity, _not_in_future,
                {"col": col, "asof": asof})

def _not_in_future(df, *, col, asof, severity, category, name):
    if col not in df.columns:
        return _result(name, "meta", False, "error", f"column absent: {col}")
    asof = asof or date.today()
    d = pd.to_datetime(df[col], errors="coerce").dt.date
    bad = df[d.notna() & (d > asof)]
    n = len(bad)
    return _result(name, category, n == 0, severity,
                   f"{n} row(s) with {col} in the future (> {asof})",
                   actual=n, expected={"asof": str(asof)},
                   violations=[{col: str(x)} for x in bad[col].head(50)])


def freshness(date_col, calendar: TradingCalendar, *, max_lag_trading_days=1,
              settlement_lag=0, severity="fail") -> Rule:
    def _fn(df, *, severity, category, name, **_):
        if date_col not in df.columns:
            return _result(name, "meta", False, "error", f"column absent: {date_col}")
        max_date = pd.to_datetime(df[date_col], errors="coerce").max()
        if pd.isna(max_date):
            return _result(name, category, False, severity,
                           f"{date_col} has no valid dates (all null/empty)",
                           actual="no_dates", expected={"date_col": date_col})
        r = freshness_within_trading_days(
            asset="", max_date=max_date, calendar=calendar,
            max_lag_trading_days=max_lag_trading_days, settlement_lag=settlement_lag)
        r.check, r.category = name, category
        r.observed.setdefault("actual", r.observed.get("lag_trading_days"))
        r.observed["expected"] = {"max_lag_trading_days": max_lag_trading_days,
                                  "settlement_lag": settlement_lag}
        return r
    return Rule(f"C5.freshness[{date_col}]", "C5", severity, _fn, {})


# ===========================================================================
# C3 special — Q4-annual contamination (the doubled-PAT guard)
# ===========================================================================
def q4_annual_contamination(value_cols, *, severity="fail", **detect_kwargs) -> Rule:
    def _fn(df, *, severity, category, name, **_):
        r = detect_q4_annual_contamination(df, value_cols=value_cols, **detect_kwargs)
        r.check, r.category = name, category
        r.observed["actual"] = r.observed.get("violation_count", len(r.violations))
        r.observed["expected"] = {"flow_metrics": list(value_cols)}
        return r
    return Rule("C3.q4_annual_contamination", "C3", severity, _fn, {})
