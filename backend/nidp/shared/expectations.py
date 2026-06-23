"""Lightweight Great-Expectations-compatible expectation engine.

Why a hand-rolled implementation rather than the full `great_expectations`
PyPI package?
  * NIDP runs on a small VM venv — the real GE adds ~350 MB and pulls
    pandas/altair/jinja2/marshmallow/etc.
  * We only need ~12 expectation primitives, defined in
    NIDP_Sample_Feed_Expectation_Rules.docx.
  * We want every expectation to write directly into the existing
    `nidp.validation_findings` table so the admin console's Quality
    panel automatically shows them. The real GE library writes to its
    own data-docs HTML reports — overkill.

Suite usage:

    from nidp.shared.expectations import Suite, expect

    suite = Suite("amfi_nav.daily")
    suite.add(
        expect.column_values_to_match_regex(
            column="Scheme Code", regex=r"^\\d+$"))
    suite.add(
        expect.compound_columns_to_be_unique(["Scheme Code", "Date"]))
    result = suite.run(rows)        # list[dict]
    print(result.success, result.success_pct, result.findings)

Each expectation is a callable `(rows) -> ExpectationResult`. Results
include unexpected_count, unexpected_percent, sample bad values, and a
human-readable message — everything the GE spec requires for ops triage.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Callable, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────

@dataclass
class ExpectationResult:
    expectation_type: str
    column: Optional[str]
    columns: Optional[List[str]]
    kwargs: dict
    success: bool
    element_count: int
    unexpected_count: int
    unexpected_percent: float
    partial_unexpected_list: List[Any]
    message: str = ""


@dataclass
class SuiteResult:
    suite_name: str
    feed: Optional[str]
    target_date: Optional[str]
    success: bool
    success_pct: float
    expectation_count: int
    successful_count: int
    failed_count: int
    findings: List[ExpectationResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "suite_name":        self.suite_name,
            "feed":              self.feed,
            "target_date":       self.target_date,
            "success":           self.success,
            "success_pct":       round(self.success_pct, 3),
            "expectation_count": self.expectation_count,
            "successful_count":  self.successful_count,
            "failed_count":      self.failed_count,
            "started_at":        self.started_at,
            "finished_at":       self.finished_at,
            "findings": [
                {
                    "expectation_type":      f.expectation_type,
                    "column":                f.column,
                    "columns":               f.columns,
                    "kwargs":                f.kwargs,
                    "success":               f.success,
                    "element_count":         f.element_count,
                    "unexpected_count":      f.unexpected_count,
                    "unexpected_percent":    round(f.unexpected_percent, 3),
                    "partial_unexpected_list": f.partial_unexpected_list[:10],
                    "message":               f.message,
                }
                for f in self.findings
            ],
        }


# ─────────────────────────────────────────────────────────────────
# Suite
# ─────────────────────────────────────────────────────────────────

class Suite:
    def __init__(self, name: str, feed: Optional[str] = None) -> None:
        self.name = name
        self.feed = feed or name
        self._expectations: List[Callable[[List[dict]], ExpectationResult]] = []

    def add(self, expectation: Callable[[List[dict]], ExpectationResult]) -> "Suite":
        self._expectations.append(expectation)
        return self

    def extend(self, expectations: Iterable[Callable[[List[dict]], ExpectationResult]]) -> "Suite":
        for e in expectations:
            self._expectations.append(e)
        return self

    def __len__(self) -> int:
        return len(self._expectations)

    def run(self, rows: List[dict], target_date: Optional[str] = None) -> SuiteResult:
        started = datetime.utcnow().isoformat() + "Z"
        findings: List[ExpectationResult] = []
        for fn in self._expectations:
            try:
                findings.append(fn(rows))
            except Exception as e:                                # noqa: BLE001
                # An expectation that ITSELF crashes is treated as a
                # failed expectation (don't blow up the whole suite).
                logger.exception("expectation crashed in suite %s", self.name)
                findings.append(ExpectationResult(
                    expectation_type="<runner_error>",
                    column=None, columns=None,
                    kwargs={"error": f"{type(e).__name__}: {e}"},
                    success=False,
                    element_count=len(rows),
                    unexpected_count=len(rows),
                    unexpected_percent=100.0,
                    partial_unexpected_list=[],
                    message=str(e)[:200],
                ))
        finished = datetime.utcnow().isoformat() + "Z"
        successes = sum(1 for f in findings if f.success)
        total     = len(findings) or 1
        return SuiteResult(
            suite_name        = self.name,
            feed              = self.feed,
            target_date       = target_date,
            success           = all(f.success for f in findings),
            success_pct       = (successes / total) * 100.0,
            expectation_count = len(findings),
            successful_count  = successes,
            failed_count      = len(findings) - successes,
            findings          = findings,
            started_at        = started,
            finished_at       = finished,
        )


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _col(rows: List[dict], col: str) -> List[Any]:
    return [r.get(col) for r in rows]


def _pct(unexpected: int, total: int) -> float:
    return 0.0 if total == 0 else (unexpected / total) * 100.0


def _result(
    *, expectation_type: str, column: Optional[str], rows: List[dict],
    failed_indexes: List[int], failed_values: List[Any],
    kwargs: dict, message: str, columns: Optional[List[str]] = None,
) -> ExpectationResult:
    total = len(rows)
    n     = len(failed_indexes)
    succ  = n == 0
    if succ:
        msg = f"PASS · {expectation_type}({column or columns or ''}) on {total} rows"
    else:
        msg = (f"FAIL · {expectation_type}({column or columns or ''}): "
               f"{n}/{total} rows ({_pct(n, total):.2f}%) failed — {message}")
    return ExpectationResult(
        expectation_type        = expectation_type,
        column                  = column,
        columns                 = columns,
        kwargs                  = kwargs,
        success                 = succ,
        element_count           = total,
        unexpected_count        = n,
        unexpected_percent      = _pct(n, total),
        partial_unexpected_list = failed_values[:10],
        message                 = msg,
    )


# ─────────────────────────────────────────────────────────────────
# Expectation primitives
# ─────────────────────────────────────────────────────────────────

class expect:                                                 # noqa: N801 — match GE naming
    """Namespace of expectation factories. Each returns a callable
    `(rows) -> ExpectationResult` so suites can compose them lazily."""

    @staticmethod
    def column_values_to_be_not_null(column: str):
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx = [i for i, v in enumerate(_col(rows, column))
                          if v is None or (isinstance(v, str) and not v.strip())]
            failed_v   = [(i, "NULL") for i in failed_idx]
            return _result(
                expectation_type="expect_column_values_to_be_not_null",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column}, message="found null/empty",
            )
        return fn

    @staticmethod
    def column_values_to_match_regex(column: str, regex: str):
        pat = re.compile(regex)
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, v in enumerate(_col(rows, column)):
                if v is None: continue                                  # nulls handled by other rule
                if not pat.match(str(v)):
                    failed_idx.append(i)
                    failed_v.append(v)
            return _result(
                expectation_type="expect_column_values_to_match_regex",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column, "regex": regex},
                message=f"didn't match {regex}",
            )
        return fn

    @staticmethod
    def column_values_to_be_in_set(column: str, value_set: Sequence[Any]):
        vs = set(value_set)
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, v in enumerate(_col(rows, column)):
                if v is None: continue
                if v not in vs:
                    failed_idx.append(i); failed_v.append(v)
            return _result(
                expectation_type="expect_column_values_to_be_in_set",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column, "value_set": list(vs)},
                message=f"value not in {sorted(vs)[:6]}…",
            )
        return fn

    @staticmethod
    def column_values_to_be_between(
        column: str, min_value: Optional[float] = None,
        max_value: Optional[float] = None, strict: bool = False,
    ):
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, v in enumerate(_col(rows, column)):
                if v is None: continue
                try: x = float(v)
                except (TypeError, ValueError):
                    failed_idx.append(i); failed_v.append(v); continue
                if min_value is not None:
                    if (strict and x <= min_value) or (not strict and x < min_value):
                        failed_idx.append(i); failed_v.append(v); continue
                if max_value is not None:
                    if (strict and x >= max_value) or (not strict and x > max_value):
                        failed_idx.append(i); failed_v.append(v); continue
            return _result(
                expectation_type="expect_column_values_to_be_between",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column, "min_value": min_value,
                        "max_value": max_value, "strict": strict},
                message=f"outside [{min_value},{max_value}] (strict={strict})",
            )
        return fn

    @staticmethod
    def column_values_to_be_greater_than_or_equal_to_column(col_a: str, col_b: str):
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                a, b = r.get(col_a), r.get(col_b)
                if a is None or b is None: continue
                try:
                    if float(a) < float(b):
                        failed_idx.append(i); failed_v.append((a, b))
                except (TypeError, ValueError):
                    failed_idx.append(i); failed_v.append((a, b))
            return _result(
                expectation_type="expect_column_values_to_be_greater_than_or_equal_to_column",
                column=col_a, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"col_a": col_a, "col_b": col_b}, columns=[col_a, col_b],
                message=f"{col_a} < {col_b}",
            )
        return fn

    @staticmethod
    def column_values_to_be_less_than_or_equal_to_column(col_a: str, col_b: str):
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                a, b = r.get(col_a), r.get(col_b)
                if a is None or b is None: continue
                try:
                    if float(a) > float(b):
                        failed_idx.append(i); failed_v.append((a, b))
                except (TypeError, ValueError):
                    failed_idx.append(i); failed_v.append((a, b))
            return _result(
                expectation_type="expect_column_values_to_be_less_than_or_equal_to_column",
                column=col_a, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"col_a": col_a, "col_b": col_b}, columns=[col_a, col_b],
                message=f"{col_a} > {col_b}",
            )
        return fn

    @staticmethod
    def column_values_to_parse_as_date(column: str, format_string: str):
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, v in enumerate(_col(rows, column)):
                if v is None: continue
                if isinstance(v, (date, datetime)): continue
                try: datetime.strptime(str(v), format_string)
                except (TypeError, ValueError):
                    failed_idx.append(i); failed_v.append(v)
            return _result(
                expectation_type="expect_column_values_to_parse_as_date",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column, "format_string": format_string},
                message=f"didn't parse as {format_string}",
            )
        return fn

    @staticmethod
    def column_values_to_be_not_in_future(column: str):
        def fn(rows: List[dict]) -> ExpectationResult:
            today = date.today()
            failed_idx, failed_v = [], []
            for i, v in enumerate(_col(rows, column)):
                if v is None: continue
                try:
                    if isinstance(v, datetime): d = v.date()
                    elif isinstance(v, date):   d = v
                    else: d = datetime.fromisoformat(str(v)).date()
                except (TypeError, ValueError):
                    failed_idx.append(i); failed_v.append(v); continue
                if d > today:
                    failed_idx.append(i); failed_v.append(v)
            return _result(
                expectation_type="expect_column_values_to_be_not_in_future",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column},
                message=f"date in future (today={today})",
            )
        return fn

    @staticmethod
    def compound_columns_to_be_unique(columns: Sequence[str]):
        cols = list(columns)
        def fn(rows: List[dict]) -> ExpectationResult:
            seen, failed_idx, failed_v = {}, [], []
            for i, r in enumerate(rows):
                key = tuple(r.get(c) for c in cols)
                if key in seen:
                    failed_idx.append(i); failed_v.append(key)
                else:
                    seen[key] = i
            return _result(
                expectation_type="expect_compound_columns_to_be_unique",
                column=None, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"columns": cols}, columns=cols,
                message=f"duplicate keys on {cols}",
            )
        return fn

    @staticmethod
    def column_pair_diff_equals_column(
        a: str, b: str, c: str, tolerance: float = 0.01,
    ):
        """Custom per-row check: row[c] ≈ row[a] - row[b]. Used for
        FII/DII netValue == buyValue - sellValue."""
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                va, vb, vc = r.get(a), r.get(b), r.get(c)
                if va is None or vb is None or vc is None: continue
                try:
                    if abs(float(vc) - (float(va) - float(vb))) > tolerance:
                        failed_idx.append(i); failed_v.append((va, vb, vc))
                except (TypeError, ValueError):
                    failed_idx.append(i); failed_v.append((va, vb, vc))
            return _result(
                expectation_type="expect_column_pair_diff_equals_column",
                column=c, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"a": a, "b": b, "c": c, "tolerance": tolerance},
                columns=[a, b, c],
                message=f"|{c} - ({a} - {b})| > {tolerance}",
            )
        return fn

    @staticmethod
    def freshness_max_date_equals(column: str, expected_date: str):
        def fn(rows: List[dict]) -> ExpectationResult:
            if not rows:
                return _result(
                    expectation_type="expect_freshness_max_date_equals",
                    column=column, rows=rows,
                    failed_indexes=[0], failed_values=[None],
                    kwargs={"column": column, "expected_date": expected_date},
                    message="no rows",
                )
            ds = []
            for v in _col(rows, column):
                if v is None: continue
                try:
                    if isinstance(v, datetime): ds.append(v.date().isoformat())
                    elif isinstance(v, date):   ds.append(v.isoformat())
                    else: ds.append(datetime.fromisoformat(str(v)[:10]).date().isoformat())
                except (TypeError, ValueError):
                    pass
            max_d = max(ds) if ds else None
            ok    = (max_d == expected_date)
            return _result(
                expectation_type="expect_freshness_max_date_equals",
                column=column, rows=rows,
                failed_indexes=[] if ok else [0],
                failed_values=[] if ok else [{"max_date_found": max_d}],
                kwargs={"column": column, "expected_date": expected_date},
                message=f"max({column})={max_d} expected={expected_date}",
            )
        return fn

    # ─────────────────────────────────────────────────────────────────
    # Extended expectations (EXTENDED_QUALITY_GATE.md §10)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def columns_sum_to_value(
        columns: Sequence[str],
        target_value: float,
        tolerance: float = 0.0,
        mostly: float = 1.0,
    ):
        """G1-SHR-001 / G3-INT-001: sum of specified columns ≈ target ± tolerance.

        Example: promoter_pct + fii_pct + dii_pct + public_pct + others_pct ≈ 100 ± 0.5
        """
        cols = list(columns)
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                try:
                    total = sum(float(r.get(c) or 0) for c in cols)
                    if abs(total - target_value) > tolerance:
                        failed_idx.append(i)
                        failed_v.append({"sum": round(total, 4), "row": i})
                except (TypeError, ValueError):
                    failed_idx.append(i)
                    failed_v.append({"error": "non-numeric", "row": i})
            n       = len(failed_idx)
            allowed = int((1.0 - mostly) * len(rows)) if rows else 0
            ok      = n <= allowed
            return ExpectationResult(
                expectation_type="expect_columns_sum_to_value",
                column=None,
                columns=cols,
                kwargs={"columns": cols, "target_value": target_value,
                        "tolerance": tolerance, "mostly": mostly},
                success=ok,
                element_count=len(rows),
                unexpected_count=n,
                unexpected_percent=_pct(n, len(rows)),
                partial_unexpected_list=failed_v[:10],
                message=(
                    f"PASS · columns {cols} sum to {target_value} ±{tolerance}"
                    if ok
                    else f"FAIL · {n}/{len(rows)} rows: columns {cols} "
                         f"don't sum to {target_value} ±{tolerance}"
                ),
            )
        return fn

    @staticmethod
    def column_pair_a_lte_b(col_a: str, col_b: str):
        """G1-SHR-003: promoter_pledged ≤ promoter_total."""
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                a, b = r.get(col_a), r.get(col_b)
                if a is None or b is None:
                    continue
                try:
                    if float(a) > float(b):
                        failed_idx.append(i)
                        failed_v.append({col_a: a, col_b: b})
                except (TypeError, ValueError):
                    failed_idx.append(i)
                    failed_v.append({col_a: a, col_b: b})
            return _result(
                expectation_type="expect_column_pair_a_lte_b",
                column=col_a, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"col_a": col_a, "col_b": col_b}, columns=[col_a, col_b],
                message=f"{col_a} > {col_b}",
            )
        return fn

    @staticmethod
    def column_grouped_sum_to_be_between(
        value_col: str,
        group_cols: Sequence[str],
        min_value: float,
        max_value: float,
        mostly: float = 0.95,
    ):
        """Per-group sum of value_col must fall in [min_value, max_value].

        Catches the MF-holdings corruption found 2026-06-23: a parser that ingests
        subtotal / grand-total rows as holdings pushes a scheme's weight_pct sum well
        past 100 (NIPPON summed to ~224%). Group by (scheme, month); expect ~100.
        """
        gcols = list(group_cols)

        def fn(rows: List[dict]) -> ExpectationResult:
            groups: Dict[tuple, float] = {}
            for r in rows:
                key = tuple(r.get(c) for c in gcols)
                try:
                    groups[key] = groups.get(key, 0.0) + float(r.get(value_col) or 0)
                except (TypeError, ValueError):
                    groups.setdefault(key, 0.0)
            bad = [(k, v) for k, v in groups.items() if not (min_value <= v <= max_value)]
            total = len(groups)
            allowed = int((1.0 - mostly) * total) if total else 0
            ok = len(bad) <= allowed
            return ExpectationResult(
                expectation_type="expect_column_grouped_sum_to_be_between",
                column=value_col,
                columns=gcols,
                kwargs={"value_col": value_col, "group_cols": gcols,
                        "min_value": min_value, "max_value": max_value, "mostly": mostly},
                success=ok,
                element_count=total,
                unexpected_count=len(bad),
                unexpected_percent=_pct(len(bad), total),
                partial_unexpected_list=[{"group": list(k), "sum": round(v, 2)} for k, v in bad[:10]],
                message=(
                    f"PASS · {value_col} per {gcols} in [{min_value},{max_value}]"
                    if ok else
                    f"FAIL · {len(bad)}/{total} groups: sum({value_col}) outside "
                    f"[{min_value},{max_value}] (e.g. {[round(v,1) for _, v in bad[:3]]})"
                ),
            )
        return fn

    @staticmethod
    def column_pair_same_sign(col_a: str, col_b: str):
        """col_a and col_b must share the same sign where both are non-null and non-zero.

        Catches the EPS/PAT mismatch found 2026-06-23 (a Screener parse read the EPS
        column wrong → PAT +67 with EPS −1.66, impossible).
        """
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                a, b = r.get(col_a), r.get(col_b)
                if a is None or b is None:
                    continue
                try:
                    fa, fb = float(a), float(b)
                    if fa != 0 and fb != 0 and (fa > 0) != (fb > 0):
                        failed_idx.append(i)
                        failed_v.append({col_a: a, col_b: b})
                except (TypeError, ValueError):
                    failed_idx.append(i)
                    failed_v.append({col_a: a, col_b: b})
            return _result(
                expectation_type="expect_column_pair_same_sign",
                column=col_a, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"col_a": col_a, "col_b": col_b}, columns=[col_a, col_b],
                message=f"{col_a} and {col_b} have opposite signs",
            )
        return fn

    @staticmethod
    def nav_change_within_category_band(
        nav_col: str,
        prev_nav_col: str,
        category_col: str,
        category_bands: Optional[dict] = None,
    ):
        """G1-NAV-003: daily NAV change within category-specific bounds.

        Requires rows to have a `previous_nav` column (populated by the
        ingester by joining today's nav with yesterday's nav before validation).
        Skips rows where prev_nav is None.

        Default bands: EQUITY ±10%, DEBT ±2%, LIQUID ±0.1%, HYBRID ±5%.
        """
        _bands = category_bands or {
            "EQUITY": 0.10, "DEBT": 0.02, "LIQUID": 0.001, "HYBRID": 0.05,
        }
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                nav       = r.get(nav_col)
                prev_nav  = r.get(prev_nav_col)
                category  = str(r.get(category_col) or "").upper()
                if nav is None or prev_nav is None:
                    continue  # skip: no historical data available
                try:
                    nav_f, prev_f = float(nav), float(prev_nav)
                    if prev_f == 0:
                        continue
                    change_pct = abs(nav_f - prev_f) / prev_f
                    band       = _bands.get(category, 0.10)
                    if change_pct > band:
                        failed_idx.append(i)
                        failed_v.append({
                            "nav": nav_f, "prev_nav": prev_f,
                            "change_pct": round(change_pct, 4),
                            "band": band, "category": category,
                        })
                except (TypeError, ValueError):
                    pass
            return _result(
                expectation_type="expect_nav_change_within_category_band",
                column=nav_col, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"nav_col": nav_col, "prev_nav_col": prev_nav_col,
                        "category_col": category_col, "bands": _bands},
                columns=[nav_col, prev_nav_col, category_col],
                message="NAV change exceeds category band",
            )
        return fn

    @staticmethod
    def row_count_within_pct_of_reference(
        expected_count: int,
        tolerance_pct: float = 2.0,
    ):
        """G1-NAV-004: row count ≥ (1 - tolerance_pct/100) × expected_count.

        Caller passes expected_count from the previous day's row count (or a
        known baseline). Rows list is just checked for len().
        """
        def fn(rows: List[dict]) -> ExpectationResult:
            actual    = len(rows)
            threshold = expected_count * (1.0 - tolerance_pct / 100.0)
            ok        = actual >= threshold
            return ExpectationResult(
                expectation_type="expect_row_count_within_pct_of_reference",
                column=None,
                columns=None,
                kwargs={"expected_count": expected_count, "tolerance_pct": tolerance_pct},
                success=ok,
                element_count=actual,
                unexpected_count=0 if ok else 1,
                unexpected_percent=0.0 if ok else 100.0,
                partial_unexpected_list=[] if ok else [{"actual": actual, "min": threshold}],
                message=(
                    f"PASS · row count {actual} >= {threshold:.0f} "
                    f"({100-tolerance_pct:.0f}% of {expected_count})"
                    if ok
                    else f"FAIL · row count {actual} < {threshold:.0f} "
                         f"({100-tolerance_pct:.0f}% of {expected_count})"
                ),
            )
        return fn

    @staticmethod
    def eps_reconciles_with_pat(
        eps_col: str,
        pat_col: str,
        shares_col: str,
        tolerance_pct: float = 5.0,
    ):
        """G1-FIN-005: EPS ≈ PAT / shares_outstanding within tolerance_pct.

        Requires all three columns. Skips rows where any is None.
        PAT expected in absolute units (crores); shares in crores.
        """
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                eps    = r.get(eps_col)
                pat    = r.get(pat_col)
                shares = r.get(shares_col)
                if eps is None or pat is None or shares is None:
                    continue
                try:
                    eps_f, pat_f, shares_f = float(eps), float(pat), float(shares)
                    if shares_f == 0:
                        continue
                    computed_eps = pat_f / shares_f
                    if abs(eps_f) < 1e-6:
                        continue  # near-zero EPS — skip reconciliation
                    pct_diff = abs(eps_f - computed_eps) / abs(eps_f) * 100
                    if pct_diff > tolerance_pct:
                        failed_idx.append(i)
                        failed_v.append({
                            "eps": eps_f, "computed_eps": round(computed_eps, 4),
                            "pct_diff": round(pct_diff, 2),
                        })
                except (TypeError, ValueError):
                    pass
            return _result(
                expectation_type="expect_eps_to_reconcile",
                column=eps_col, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"eps_col": eps_col, "pat_col": pat_col,
                        "shares_col": shares_col, "tolerance_pct": tolerance_pct},
                columns=[eps_col, pat_col, shares_col],
                message=f"EPS vs PAT/shares mismatch > {tolerance_pct}%",
            )
        return fn

    @staticmethod
    def ohlc_sanity(
        open_col: str = "open_price",
        high_col: str = "high_price",
        low_col: str  = "low_price",
        close_col: str = "close_price",
    ):
        """G1-BHV-004: low ≤ open,close ≤ high (composite OHLC sanity check)."""
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                o, h, l, c = (r.get(open_col), r.get(high_col),
                              r.get(low_col),  r.get(close_col))
                if any(v is None for v in (o, h, l, c)):
                    continue
                try:
                    o_f, h_f, l_f, c_f = float(o), float(h), float(l), float(c)
                    if not (l_f <= o_f <= h_f and l_f <= c_f <= h_f):
                        failed_idx.append(i)
                        failed_v.append({"O": o_f, "H": h_f, "L": l_f, "C": c_f})
                except (TypeError, ValueError):
                    failed_idx.append(i)
                    failed_v.append({"O": o, "H": h, "L": l, "C": c})
            return _result(
                expectation_type="expect_ohlc_sanity",
                column=None, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"open": open_col, "high": high_col,
                        "low": low_col, "close": close_col},
                columns=[open_col, high_col, low_col, close_col],
                message=f"OHLC invariant violated (L≤O,C≤H)",
            )
        return fn

    @staticmethod
    def delivery_qty_lte_traded(
        deliv_col: str = "deliverable_quantity",
        traded_col: str = "traded_quantity",
    ):
        """G1-DLV-003: delivery_qty ≤ traded_qty."""
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                d, t = r.get(deliv_col), r.get(traded_col)
                if d is None or t is None:
                    continue
                try:
                    if float(d) > float(t):
                        failed_idx.append(i)
                        failed_v.append({deliv_col: float(d), traded_col: float(t)})
                except (TypeError, ValueError):
                    failed_idx.append(i)
            return _result(
                expectation_type="expect_delivery_qty_lte_traded",
                column=deliv_col, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={deliv_col: deliv_col, traded_col: traded_col},
                columns=[deliv_col, traded_col],
                message=f"{deliv_col} > {traded_col}",
            )
        return fn

    @staticmethod
    def fii_flow_magnitude_plausible(
        buy_col: str  = "buy_value",
        sell_col: str = "sell_value",
        max_crore: float = 50_000.0,
    ):
        """G1-FII-001: FII/DII flow magnitudes < ₹50,000 crore (implausibility guard)."""
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                for col in (buy_col, sell_col):
                    v = r.get(col)
                    if v is None:
                        continue
                    try:
                        if abs(float(v)) > max_crore:
                            failed_idx.append(i)
                            failed_v.append({col: float(v), "max": max_crore})
                    except (TypeError, ValueError):
                        pass
            return _result(
                expectation_type="expect_fii_flow_magnitude_plausible",
                column=None, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"buy_col": buy_col, "sell_col": sell_col, "max_crore": max_crore},
                columns=[buy_col, sell_col],
                message=f"flow magnitude > ₹{max_crore:,.0f} cr",
            )
        return fn

    @staticmethod
    def symbol_cardinality_within_pct(
        symbol_col: str = "symbol",
        reference_count: Optional[int] = None,
        tolerance_pct: float = 2.0,
    ):
        """G1-BHV-007: symbol cardinality drift < tolerance_pct vs reference_count.

        If reference_count is None, the check always passes (no baseline available).
        """
        def fn(rows: List[dict]) -> ExpectationResult:
            unique = len(set(r.get(symbol_col) for r in rows if r.get(symbol_col)))
            if reference_count is None:
                return ExpectationResult(
                    expectation_type="expect_symbol_cardinality_within_pct",
                    column=symbol_col, columns=None,
                    kwargs={"reference_count": None, "tolerance_pct": tolerance_pct},
                    success=True,
                    element_count=unique, unexpected_count=0, unexpected_percent=0.0,
                    partial_unexpected_list=[],
                    message=f"PASS (no baseline) · unique {symbol_col}={unique}",
                )
            threshold = reference_count * (tolerance_pct / 100.0)
            drift     = abs(unique - reference_count)
            ok        = drift <= threshold
            return ExpectationResult(
                expectation_type="expect_symbol_cardinality_within_pct",
                column=symbol_col, columns=None,
                kwargs={"reference_count": reference_count, "tolerance_pct": tolerance_pct},
                success=ok,
                element_count=unique,
                unexpected_count=0 if ok else 1,
                unexpected_percent=0.0 if ok else 100.0,
                partial_unexpected_list=[] if ok else [{"unique": unique, "ref": reference_count, "drift": drift}],
                message=(
                    f"PASS · unique {symbol_col}={unique} (drift {drift} <= {threshold:.0f})"
                    if ok
                    else f"FAIL · unique {symbol_col}={unique} vs ref={reference_count} drift={drift} > {threshold:.0f}"
                ),
            )
        return fn

    @staticmethod
    def timestamps_monotonic(timestamp_col: str, partition_col: Optional[str] = None):
        """G2-U-002: timestamps monotonic per partition (or globally if no partition col).

        Applies to batches of rows already sorted by the caller.
        """
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            # Build partitions
            parts: dict[Any, list] = {}
            for i, r in enumerate(rows):
                key = r.get(partition_col) if partition_col else "__all__"
                parts.setdefault(key, []).append((i, r))
            for _key, items in parts.items():
                prev_ts = None
                for i, r in items:
                    ts = r.get(timestamp_col)
                    if ts is None:
                        continue
                    ts_cmp: Any
                    if isinstance(ts, (date, datetime)):
                        ts_cmp = ts
                    else:
                        try:
                            ts_cmp = datetime.fromisoformat(str(ts))
                        except (TypeError, ValueError):
                            continue
                    if prev_ts is not None and ts_cmp < prev_ts:
                        failed_idx.append(i)
                        failed_v.append({"ts": str(ts), "prev_ts": str(prev_ts)})
                    prev_ts = ts_cmp
            return _result(
                expectation_type="expect_timestamps_monotonic",
                column=timestamp_col, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"timestamp_col": timestamp_col, "partition_col": partition_col},
                columns=[c for c in [timestamp_col, partition_col] if c],
                message=f"non-monotonic {timestamp_col}",
            )
        return fn

    @staticmethod
    def quarter_end_is_valid(column: str = "period_end"):
        """G1-FIN-004: quarter_end date must fall on 03-31, 06-30, 09-30, or 12-31."""
        import re as _re
        _QUARTER_ENDS = _re.compile(r"-(03-31|06-30|09-30|12-31)$")
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, v in enumerate(_col(rows, column)):
                if v is None:
                    continue
                s = str(v)[:10] if not isinstance(v, str) else v[:10]
                if not _QUARTER_ENDS.search(s):
                    failed_idx.append(i)
                    failed_v.append(v)
            return _result(
                expectation_type="expect_quarter_end_is_valid",
                column=column, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"column": column},
                message="quarter_end not on 03-31/06-30/09-30/12-31",
            )
        return fn

    @staticmethod
    def index_weight_sum_per_index(
        index_col: str = "index_name",
        weight_col: str = "weight_pct",
        target: float = 100.0,
        tolerance: float = 2.0,
    ):
        """G1-IDX-001: weight_pct sums to ≈100 per index_name."""
        def fn(rows: List[dict]) -> ExpectationResult:
            from collections import defaultdict
            sums: dict[str, float] = defaultdict(float)
            for r in rows:
                idx = r.get(index_col)
                w   = r.get(weight_col)
                if idx is None or w is None:
                    continue
                try:
                    sums[str(idx)] += float(w)
                except (TypeError, ValueError):
                    pass
            bad = {k: v for k, v in sums.items() if abs(v - target) > tolerance}
            ok  = len(bad) == 0
            return ExpectationResult(
                expectation_type="expect_index_weight_sum_per_index",
                column=weight_col, columns=[index_col, weight_col],
                kwargs={"index_col": index_col, "weight_col": weight_col,
                        "target": target, "tolerance": tolerance},
                success=ok,
                element_count=len(sums),
                unexpected_count=len(bad),
                unexpected_percent=_pct(len(bad), len(sums)) if sums else 0.0,
                partial_unexpected_list=list(bad.items())[:10],
                message=(
                    f"PASS · all {len(sums)} indices weight-sum ≈{target}±{tolerance}"
                    if ok
                    else f"FAIL · {len(bad)} indices weight-sum outside ±{tolerance} of {target}: {list(bad.keys())[:5]}"
                ),
            )
        return fn

    @staticmethod
    def bulk_deal_value_plausible(
        qty_col: str = "quantity",
        price_col: str = "avg_price",
        max_value_crore: float = 10_000.0,
    ):
        """G1-BLK-001: qty × price < max_value_crore (feasibility guard)."""
        max_value = max_value_crore * 1e7  # crores to absolute
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                q, p = r.get(qty_col), r.get(price_col)
                if q is None or p is None:
                    continue
                try:
                    val = float(q) * float(p)
                    if val > max_value:
                        failed_idx.append(i)
                        failed_v.append({"qty": float(q), "price": float(p), "value": val})
                except (TypeError, ValueError):
                    pass
            return _result(
                expectation_type="expect_bulk_deal_value_plausible",
                column=None, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"qty_col": qty_col, "price_col": price_col,
                        "max_value_crore": max_value_crore},
                columns=[qty_col, price_col],
                message=f"deal value > ₹{max_value_crore:,.0f} cr",
            )
        return fn

    @staticmethod
    def corporate_action_ex_date_after_announcement(
        ex_date_col: str = "ex_date",
        announce_col: str = "announcement_date",
    ):
        """G1-CA-001: ex_date ≥ announcement_date."""
        def fn(rows: List[dict]) -> ExpectationResult:
            failed_idx, failed_v = [], []
            for i, r in enumerate(rows):
                ex   = r.get(ex_date_col)
                ann  = r.get(announce_col)
                if ex is None or ann is None:
                    continue
                try:
                    ex_d  = ex.date()  if isinstance(ex, datetime)  else (ex  if isinstance(ex, date)  else datetime.fromisoformat(str(ex)).date())
                    ann_d = ann.date() if isinstance(ann, datetime) else (ann if isinstance(ann, date) else datetime.fromisoformat(str(ann)).date())
                    if ex_d < ann_d:
                        failed_idx.append(i)
                        failed_v.append({"ex_date": str(ex_d), "ann_date": str(ann_d)})
                except (TypeError, ValueError):
                    pass
            return _result(
                expectation_type="expect_corporate_action_ex_date_after_announcement",
                column=ex_date_col, rows=rows,
                failed_indexes=failed_idx, failed_values=failed_v,
                kwargs={"ex_date_col": ex_date_col, "announce_col": announce_col},
                columns=[ex_date_col, announce_col],
                message=f"{ex_date_col} < {announce_col}",
            )
        return fn

    @staticmethod
    def table_freshness_within_hours(
        timestamp_col: str,
        max_age_hours: float = 24.0,
    ):
        """G3-PRES-006 / expect_table_to_have_freshness_within:
        max timestamp in rows ≤ max_age_hours ago."""
        def fn(rows: List[dict]) -> ExpectationResult:
            if not rows:
                return ExpectationResult(
                    expectation_type="expect_table_freshness_within_hours",
                    column=timestamp_col, columns=None,
                    kwargs={"timestamp_col": timestamp_col, "max_age_hours": max_age_hours},
                    success=False, element_count=0, unexpected_count=1,
                    unexpected_percent=100.0, partial_unexpected_list=[],
                    message="FAIL · no rows — table appears empty",
                )
            from datetime import timezone as _tz
            now    = datetime.now(_tz.utc)
            max_ts = None
            for v in _col(rows, timestamp_col):
                if v is None:
                    continue
                try:
                    if isinstance(v, datetime):
                        ts = v if v.tzinfo else v.replace(tzinfo=_tz.utc)
                    else:
                        ts = datetime.fromisoformat(str(v))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=_tz.utc)
                    if max_ts is None or ts > max_ts:
                        max_ts = ts
                except (TypeError, ValueError):
                    pass
            if max_ts is None:
                return ExpectationResult(
                    expectation_type="expect_table_freshness_within_hours",
                    column=timestamp_col, columns=None,
                    kwargs={"timestamp_col": timestamp_col, "max_age_hours": max_age_hours},
                    success=False, element_count=len(rows), unexpected_count=1,
                    unexpected_percent=100.0, partial_unexpected_list=[],
                    message=f"FAIL · no parseable timestamps in {timestamp_col}",
                )
            age_hours = (now - max_ts).total_seconds() / 3600
            ok = age_hours <= max_age_hours
            return ExpectationResult(
                expectation_type="expect_table_freshness_within_hours",
                column=timestamp_col, columns=None,
                kwargs={"timestamp_col": timestamp_col, "max_age_hours": max_age_hours},
                success=ok, element_count=len(rows),
                unexpected_count=0 if ok else 1,
                unexpected_percent=0.0 if ok else 100.0,
                partial_unexpected_list=[] if ok else [{"age_hours": round(age_hours, 2)}],
                message=(
                    f"PASS · {timestamp_col} max={max_ts.isoformat()[:19]} "
                    f"age={age_hours:.1f}h ≤ {max_age_hours}h"
                    if ok
                    else f"FAIL · {timestamp_col} max={max_ts.isoformat()[:19]} "
                         f"age={age_hours:.1f}h > {max_age_hours}h"
                ),
            )
        return fn
