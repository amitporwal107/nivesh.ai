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
