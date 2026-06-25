"""
NIDP data-quality primitives — three high-leverage checks.

This module deliberately keeps the *detection logic* as pure functions over
pandas DataFrames (plus a small calendar helper). They return a uniform
``CheckResult`` that maps cleanly onto ``nidp.validation_findings`` and the
``v_feed_status`` verdict. GE-version-specific wrapping (turning these into
custom Expectations) is a thin adapter layer noted at each section; the logic
here does not depend on which GE release you run.

Three primitives, mapped to the gaps identified in the catalogue review:

  1. META-GUARD (the silent-no-op problem)
       - assert_columns_exist : a check bound to a non-existent column is an
         ERROR, not a green pass. Catches the original "validated nothing" bug.
       - expect_non_empty     : a batch of zero rows passes every expectation
         vacuously; make emptiness loud.
       - reconcile_executed_suites : did every suite that *should* run actually
         run today? The meta-version of the original bug.

  2. CALENDAR-AWARE FRESHNESS (replaces brittle freshness_max_date_equals)
       - TradingCalendar + freshness_within_trading_days : "<= N trading days
         behind, per nse_holidays", so weekends/holidays/settlement-lag don't
         false-positive.

  3. Q4-ANNUAL CONTAMINATION (the doubled-PAT bug)
       - detect_q4_annual_contamination : layered detection, flow-metrics only,
         consolidated/standalone kept separate, period_type case-normalised
         (which is itself the known bug).

Severity convention used throughout:
    "error" — the check could not meaningfully evaluate (misbound / empty).
              The runner should ABORT the suite, not record a pass.
    "fail"  — data is bad with high confidence.
    "warn"  — suspicious; likely-but-not-certain, low-cost to surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence, Optional, Any

import pandas as pd


# ---------------------------------------------------------------------------
# Uniform result type -> validation_findings sink
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    check: str                       # primitive name, e.g. "q4_annual_contamination"
    asset: str                       # table / feed name
    success: bool
    severity: str                    # "error" | "fail" | "warn"
    category: str = "meta"           # C1..C8 or "meta" -> validation_findings.failure_class
    message: str = ""
    observed: dict = field(default_factory=dict)     # summary numbers for the verdict
    violations: list[dict] = field(default_factory=list)  # offending rows -> failed_rows drill-down

    def to_finding(self, run_id: str | None = None) -> dict:
        """Shape for nidp.validation_findings (adjust column names to your schema)."""
        return {
            "run_id": run_id,
            "asset": self.asset,
            "check": self.check,
            "success": self.success,
            "severity": self.severity,
            "message": self.message,
            "observed": self.observed,
            "violation_count": len(self.violations),
            # Persist a bounded sample; full set can go to dq.failed_rows if desired.
            "violation_sample": self.violations[:50],
        }


# ===========================================================================
# 1. META-GUARD  —  defeats the "suite that validates nothing" failure mode
# ===========================================================================
#
# Wire these as the FIRST steps the runner performs for every asset, BEFORE the
# real suite executes. assert_columns_exist should run against the authoritative
# schema (information_schema.columns) so a misbound column is caught even when the
# fetched DataFrame happens not to contain it. If you only have the DataFrame,
# pass df.columns — still far better than nothing.

def assert_columns_exist(
    asset: str,
    expected_cols: Sequence[str],
    actual_cols: Iterable[str],
) -> CheckResult:
    """Every column a suite references must exist. A missing column means the
    expectation silently validates nothing -> treat as ERROR (abort the suite)."""
    actual = set(actual_cols)
    missing = [c for c in expected_cols if c not in actual]
    success = not missing
    return CheckResult(
        check="meta.columns_exist",
        asset=asset,
        success=success,
        severity="error" if missing else "warn",
        message=(
            f"{len(missing)} referenced column(s) absent: {missing}. "
            "Suite would validate nothing — aborting."
            if missing else "all referenced columns present"
        ),
        observed={"expected": list(expected_cols), "missing": missing},
        violations=[{"missing_column": c} for c in missing],
    )


def expect_non_empty(asset: str, df: pd.DataFrame, min_rows: int = 1) -> CheckResult:
    """An empty (or under-sized) batch passes every downstream expectation
    vacuously. Make it loud. Zero rows is an ERROR (the check could not run);
    below a configured floor is a FAIL."""
    n = len(df)
    if n == 0:
        sev, ok = "error", False
    elif n < min_rows:
        sev, ok = "fail", False
    else:
        sev, ok = "warn", True
    return CheckResult(
        check="meta.non_empty",
        asset=asset,
        success=ok,
        severity=sev,
        message=f"row_count={n} (floor={min_rows})",
        observed={"row_count": n, "min_rows": min_rows},
    )


def reconcile_executed_suites(
    expected_assets: Iterable[str],
    executed_assets: Iterable[str],
) -> CheckResult:
    """Orchestration-level coverage: a runner that silently stops running a suite
    is the meta-version of the original bug. Compare the registry of suites that
    *should* run against those that produced a run/finding this cycle."""
    expected = set(expected_assets)
    executed = set(executed_assets)
    missing = sorted(expected - executed)
    return CheckResult(
        check="meta.suite_coverage",
        asset="__runner__",
        success=not missing,
        severity="error" if missing else "warn",
        message=(
            f"{len(missing)} expected suite(s) did not execute: {missing}"
            if missing else "all expected suites executed"
        ),
        observed={"expected": len(expected), "executed": len(executed), "missing": missing},
        violations=[{"asset": a, "reason": "no run recorded this cycle"} for a in missing],
    )


# ===========================================================================
# 2. CALENDAR-AWARE FRESHNESS  —  replaces freshness_max_date_equals
# ===========================================================================
#
# Build the calendar once per run from nse_holidays:
#     cal = TradingCalendar(holidays={row.holiday_date for row in nse_holidays})
# Then per feed:
#     freshness_within_trading_days(asset, max_date, cal,
#                                   max_lag_trading_days=1, settlement_lag=0)
#
# settlement_lag handles "data for today's session only lands T+1": set =1 so the
# expected latest date is the *previous* trading day. For legitimately-lagging
# series (FRED) widen max_lag_trading_days or use a month-based check instead.

class TradingCalendar:
    """Weekends + explicit holiday set. Holidays are a set of datetime.date."""

    _SCAN_LIMIT = 60  # safety bound on backward scans

    def __init__(self, holidays: Iterable[date]):
        self.holidays = {self._as_date(d) for d in holidays}

    @staticmethod
    def _as_date(d: Any) -> date:
        # NOTE: pandas.Timestamp and datetime.datetime BOTH pass isinstance(d, date),
        # so we must convert them to a plain date rather than return as-is (a Timestamp
        # cannot be compared with a date and breaks the >= check downstream).
        if isinstance(d, pd.Timestamp):
            return d.date()
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
        return pd.Timestamp(d).date()

    def is_trading_day(self, d: date) -> bool:
        d = self._as_date(d)
        return d.weekday() < 5 and d not in self.holidays

    def latest_trading_day_on_or_before(self, d: date) -> date:
        cur = self._as_date(d)
        for _ in range(self._SCAN_LIMIT):
            if self.is_trading_day(cur):
                return cur
            cur -= timedelta(days=1)
        raise ValueError(f"no trading day within {self._SCAN_LIMIT}d before {d}")

    def previous_trading_day(self, d: date) -> date:
        cur = self._as_date(d) - timedelta(days=1)
        for _ in range(self._SCAN_LIMIT):
            if self.is_trading_day(cur):
                return cur
            cur -= timedelta(days=1)
        raise ValueError(f"no trading day within {self._SCAN_LIMIT}d before {d}")

    def trading_days_between(self, start: date, end: date) -> int:
        """Count trading days in the half-open interval (start, end]."""
        start, end = self._as_date(start), self._as_date(end)
        if end <= start:
            return 0
        cnt, cur = 0, start
        # bound the walk generously
        for _ in range((end - start).days + 1):
            cur += timedelta(days=1)
            if cur > end:
                break
            if self.is_trading_day(cur):
                cnt += 1
        return cnt


def freshness_within_trading_days(
    asset: str,
    max_date: Any,
    calendar: TradingCalendar,
    max_lag_trading_days: int = 1,
    settlement_lag: int = 0,
    asof: Optional[date] = None,
) -> CheckResult:
    """PASS iff the feed's latest date is within ``max_lag_trading_days`` trading
    sessions of the expected latest session (today, minus settlement_lag),
    accounting for weekends and the holiday calendar."""
    asof = asof or date.today()
    expected = calendar.latest_trading_day_on_or_before(asof)
    for _ in range(settlement_lag):
        expected = calendar.previous_trading_day(expected)

    md = TradingCalendar._as_date(max_date)
    lag = 0 if md >= expected else calendar.trading_days_between(md, expected)
    ok = lag <= max_lag_trading_days
    return CheckResult(
        check="freshness.trading_days",
        asset=asset,
        success=ok,
        severity="fail" if not ok else "warn",
        category="C5",
        message=(
            f"latest={md} expected≈{expected} lag={lag} trading day(s) "
            f"(max {max_lag_trading_days})"
        ),
        observed={
            "max_date": str(md),
            "expected_latest": str(expected),
            "lag_trading_days": lag,
            "max_lag_trading_days": max_lag_trading_days,
            "settlement_lag": settlement_lag,
        },
    )


# ===========================================================================
# 3. Q4-ANNUAL CONTAMINATION  —  the doubled-PAT bug
# ===========================================================================
#
# Symptom: a quarterly row carries the full-year figure (parser took the annual
# cumulative column and mislabelled it, classically as Q4). Q4 and the annual
# row share the same period_end (fiscal year-end), which is exactly why they get
# confused.
#
# Detection is LAYERED, and applied ONLY to flow metrics (revenue/PAT/EPS...),
# never to balance-sheet stocks (total assets/equity don't sum across quarters):
#
#   A) Quarter≈Annual smoking gun  [FAIL]
#        For a (symbol, fiscal_year, consolidated, metric), if an annual value A
#        exists and any *quarterly* row ≈ A within rel_tol -> that quarter is the
#        annual figure in disguise. A single quarter cannot equal the full year.
#
#   B) Sum-of-quarters reconciliation  [FAIL]
#        If all four quarters + the annual exist, sum(Q1..Q4) must ≈ annual. A
#        doubled quarter pushes the sum well past annual; flag the year and name
#        the quarter closest to the annual value as the suspect.
#
#   C) Self-relative magnitude  [WARN]  (fallback when no annual row is present)
#        Within a symbol's own quarterly history, a quarter that dwarfs both its
#        neighbours and the series median is suspicious. Higher false-positive
#        (genuine surges/seasonality) -> warn, not fail.
#
# Defaults assume Indian fiscal year (Apr–Mar). period_type is lower-cased before
# matching, so the check is robust to the known lowercase-period_type bug.

DEFAULT_FLOW_METRICS = (
    "revenue", "total_income", "net_sales", "operating_income",
    "pat", "net_profit", "profit_after_tax", "eps",
    "ebitda", "operating_profit", "pbt", "profit_before_tax",
    "interest_income", "other_income",
)

DEFAULT_ANNUAL_LABELS = ("annual", "fy", "yearly", "year", "a")
DEFAULT_QUARTER_LABELS = ("q1", "q2", "q3", "q4", "quarterly", "q")


def fiscal_year(period_end: Any) -> int:
    """Indian FY ends 31-Mar. period_end in Apr–Dec -> FY = year+1; Jan–Mar -> FY = year.
    e.g. 2023-06-30 -> FY2024 ; 2024-03-31 -> FY2024."""
    d = TradingCalendar._as_date(period_end)
    return d.year + 1 if d.month >= 4 else d.year


def _rel_close(a: float, b: float, rel_tol: float) -> bool:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return False
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom <= rel_tol


def detect_q4_annual_contamination(
    df: pd.DataFrame,
    *,
    value_cols: Sequence[str],
    symbol_col: str = "symbol",
    period_end_col: str = "period_end",
    period_type_col: str = "period_type",
    consolidated_col: str = "consolidated",
    annual_labels: Sequence[str] = DEFAULT_ANNUAL_LABELS,
    quarter_labels: Sequence[str] = DEFAULT_QUARTER_LABELS,
    flow_metrics: Sequence[str] = DEFAULT_FLOW_METRICS,
    rel_tol: float = 0.10,
    magnitude_factor: float = 3.0,
    asset: str = "nse_financials_quarterly",
) -> CheckResult:
    """Flag quarterly rows whose flow-metric values are actually annual figures.

    Returns a single CheckResult; ``violations`` lists each offending
    (symbol, fiscal_year, period_type, metric, value) with the rule that caught it.
    """
    flow_set = {m.lower() for m in flow_metrics}
    metrics = [c for c in value_cols if c.lower() in flow_set]
    skipped = [c for c in value_cols if c.lower() not in flow_set]

    work = df.copy()
    work["_ptype"] = work[period_type_col].astype(str).str.strip().str.lower()
    work["_fy"] = work[period_end_col].map(fiscal_year)
    is_annual = work["_ptype"].isin([s.lower() for s in annual_labels])
    is_quarter = work["_ptype"].isin([s.lower() for s in quarter_labels])

    consol_key = consolidated_col if consolidated_col in work.columns else None
    violations: list[dict] = []

    group_cols = ["_fy"] + ([consol_key] if consol_key else [])

    for sym, sym_df in work.groupby(symbol_col):
        for keys, grp in sym_df.groupby(group_cols):
            keys = keys if isinstance(keys, tuple) else (keys,)
            fy = keys[0]
            consol = keys[1] if consol_key else None
            ann = grp[is_annual.loc[grp.index]]
            qtrs = grp[is_quarter.loc[grp.index]]

            for metric in metrics:
                annual_val = (
                    pd.to_numeric(ann[metric], errors="coerce").dropna().iloc[0]
                    if not ann.empty and ann[metric].notna().any() else None
                )

                # ---- A) quarter ≈ annual smoking gun ----
                if annual_val is not None:
                    for idx, qrow in qtrs.iterrows():
                        qv = pd.to_numeric(pd.Series([qrow[metric]]), errors="coerce").iloc[0]
                        if pd.notna(qv) and _rel_close(qv, annual_val, rel_tol):
                            violations.append({
                                "rule": "A.quarter_equals_annual",
                                "severity": "fail",
                                "symbol": sym, "fiscal_year": int(fy),
                                "consolidated": consol,
                                "period_type": qrow["_ptype"],
                                "period_end": str(TradingCalendar._as_date(qrow[period_end_col])),
                                "metric": metric,
                                "value": float(qv), "annual_value": float(annual_val),
                            })

                # ---- B) sum-of-quarters reconciliation ----
                qvals = pd.to_numeric(qtrs[metric], errors="coerce").dropna()
                distinct_q = qtrs.loc[qvals.index, "_ptype"].isin(["q1", "q2", "q3", "q4"]).sum()
                if annual_val is not None and distinct_q >= 4:
                    qsum = float(qvals.sum())
                    if not _rel_close(qsum, annual_val, rel_tol):
                        # suspect = quarter closest to the annual figure
                        suspect_idx = (qvals - annual_val).abs().idxmin()
                        srow = qtrs.loc[suspect_idx]
                        violations.append({
                            "rule": "B.sum_quarters_neq_annual",
                            "severity": "fail",
                            "symbol": sym, "fiscal_year": int(fy),
                            "consolidated": consol, "metric": metric,
                            "sum_quarters": qsum, "annual_value": float(annual_val),
                            "suspect_period_type": srow["_ptype"],
                            "suspect_value": float(qvals.loc[suspect_idx]),
                        })

                # ---- C) self-relative magnitude (no annual to compare) ----
                if annual_val is None and len(qvals) >= 3:
                    med = float(qvals.median())
                    if med > 0:
                        for idx in qvals.index:
                            v = float(qvals.loc[idx])
                            others = qvals.drop(idx)
                            if v > magnitude_factor * med and v > magnitude_factor * others.max():
                                qrow = qtrs.loc[idx]
                                violations.append({
                                    "rule": "C.magnitude_outlier",
                                    "severity": "warn",
                                    "symbol": sym, "fiscal_year": int(fy),
                                    "consolidated": consol, "metric": metric,
                                    "period_type": qrow["_ptype"],
                                    "value": v, "series_median": med,
                                })

    has_fail = any(v["severity"] == "fail" for v in violations)
    severity = "fail" if has_fail else ("warn" if violations else "warn")
    return CheckResult(
        check="consistency.q4_annual_contamination",
        asset=asset,
        success=not violations,
        severity=severity,
        category="C3",
        message=(
            f"{len(violations)} contamination signal(s) across {len(metrics)} flow metric(s); "
            f"skipped non-flow cols {skipped}"
            if violations else
            f"clean across {len(metrics)} flow metric(s); skipped non-flow cols {skipped}"
        ),
        observed={"metrics_checked": metrics, "metrics_skipped": skipped,
                  "violation_count": len(violations)},
        violations=violations,
    )
