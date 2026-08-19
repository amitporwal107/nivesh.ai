"""Validation rule contract.

Each rule is an async callable: `run(ctx) -> list[Finding]`.
Empty list = pass; non-empty = one or more failures.

Rules are SQL-driven (run against the just-persisted facts) so they
catch issues at the *table* level — what the parser saw can differ
from what made it through validate() and persist().
"""
from __future__ import annotations

from decimal import Decimal

import abc
import enum
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

import asyncpg


class Severity(str, enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class FailureClass(str, enum.Enum):
    RETRY = "RETRY"
    FIX = "FIX"
    BLOCK = "BLOCK"
    INFO = "INFO"


@dataclass
class Finding:
    rule_name: str
    severity: Severity
    failure_class: FailureClass
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    sample_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RuleContext:
    """Per-run context passed to every rule."""
    conn: asyncpg.Connection
    ingester: str
    target_date: Optional[date]
    job_run_id: uuid.UUID


class Rule(abc.ABC):
    """Subclass + implement `check`. `name` is used in alerts/dashboards
    so make it stable + grep-able."""
    name: str = ""
    severity: Severity = Severity.ERROR
    failure_class: FailureClass = FailureClass.FIX

    @abc.abstractmethod
    async def check(self, ctx: RuleContext) -> list[Finding]: ...


# ── Built-in rule helpers ────────────────────────────────────────────
class CountAtLeastRule(Rule):
    """Assert that a query returns >= `min_count` rows (or that a
    scalar count is >= `min_count`)."""

    def __init__(
        self,
        *,
        name: str,
        sql: str,
        min_count: int,
        severity: Severity = Severity.CRITICAL,
        failure_class: FailureClass = FailureClass.BLOCK,
    ) -> None:
        self.name = name
        self._sql = sql
        self._min = min_count
        self.severity = severity
        self.failure_class = failure_class

    async def check(self, ctx: RuleContext) -> list[Finding]:
        actual = await ctx.conn.fetchval(self._sql, ctx.target_date, ctx.job_run_id)
        actual_int = int(actual or 0)
        if actual_int >= self._min:
            return []
        return [Finding(
            rule_name=self.name,
            severity=self.severity,
            failure_class=self.failure_class,
            message=f"row count {actual_int} below minimum {self._min}",
            expected=f">= {self._min}",
            actual=str(actual_int),
        )]


class NoNullsRule(Rule):
    """Assert that the rows persisted by this run have no NULL in the
    listed columns. Returns up to 5 sample offending rows."""

    def __init__(
        self,
        *,
        name: str,
        table: str,
        columns: list[str],
        where: str = "TRUE",
        severity: Severity = Severity.ERROR,
        failure_class: FailureClass = FailureClass.FIX,
    ) -> None:
        self.name = name
        self._table = table
        self._columns = columns
        self._where = where
        self.severity = severity
        self.failure_class = failure_class

    async def check(self, ctx: RuleContext) -> list[Finding]:
        null_pred = " OR ".join(f"{c} IS NULL" for c in self._columns)
        sql = f"""
            SELECT count(*) FROM {self._table}
             WHERE source_run_id = $1
               AND ({null_pred})
               AND {self._where}
        """
        bad = int(await ctx.conn.fetchval(sql, ctx.job_run_id) or 0)
        if bad == 0:
            return []
        sample_sql = f"""
            SELECT * FROM {self._table}
             WHERE source_run_id = $1
               AND ({null_pred})
               AND {self._where}
             LIMIT 5
        """
        sample = [dict(r) for r in await ctx.conn.fetch(sample_sql, ctx.job_run_id)]
        return [Finding(
            rule_name=self.name,
            severity=self.severity,
            failure_class=self.failure_class,
            message=f"{bad} row(s) have NULL in {self._columns}",
            expected="0",
            actual=str(bad),
            sample_rows=sample,
        )]


class RangeRule(Rule):
    """Assert that a numeric column lies inside [lo, hi] for all rows
    in this run.

    The bounds are compared in exact decimal space, not binary floating
    point. `lo` and `hi` arrive as Python floats, and binding a float into
    a numeric comparison expands its *full* binary value — 0.0001 arrives as
        0.000100000000000000004792173602385929598312941379845142364501953125
    which is strictly greater than the decimal 0.0001 that a numeric(14,4)
    column stores. A value sitting exactly on an inclusive bound then reads
    as outside it: amfi_nav flagged a NAV of exactly 0.0001 as "below
    0.0001" on a run that was otherwise clean.

    Converting through repr() picks the shortest decimal that round-trips
    the float, so the bound binds as the 0.0001 the caller wrote.
    """

    def __init__(
        self,
        *,
        name: str,
        table: str,
        column: str,
        lo: float,
        hi: float,
        where: str = "TRUE",
        severity: Severity = Severity.ERROR,
        failure_class: FailureClass = FailureClass.FIX,
    ) -> None:
        self.name = name
        self._table = table
        self._col = column
        # repr() gives the shortest round-tripping decimal, so Decimal(repr(x))
        # binds the bound the caller meant rather than the float's full binary
        # expansion. See the class docstring.
        self._lo = Decimal(repr(lo))
        self._hi = Decimal(repr(hi))
        self._where = where
        self.severity = severity
        self.failure_class = failure_class

    async def check(self, ctx: RuleContext) -> list[Finding]:
        sql = f"""
            SELECT count(*) FROM {self._table}
             WHERE source_run_id = $1
               AND {self._col} IS NOT NULL
               AND ({self._col}::numeric < $2::numeric
                    OR {self._col}::numeric > $3::numeric)
               AND {self._where}
        """
        bad = int(await ctx.conn.fetchval(sql, ctx.job_run_id, self._lo, self._hi) or 0)
        if bad == 0:
            return []
        sample_sql = f"""
            SELECT * FROM {self._table}
             WHERE source_run_id = $1
               AND {self._col} IS NOT NULL
               AND ({self._col}::numeric < $2::numeric
                    OR {self._col}::numeric > $3::numeric)
               AND {self._where}
             LIMIT 5
        """
        sample = [dict(r) for r in await ctx.conn.fetch(sample_sql, ctx.job_run_id, self._lo, self._hi)]
        return [Finding(
            rule_name=self.name,
            severity=self.severity,
            failure_class=self.failure_class,
            message=f"{bad} row(s) outside [{self._lo}, {self._hi}] for {self._col}",
            expected=f"[{self._lo}, {self._hi}]",
            actual=str(bad),
            sample_rows=sample,
        )]


class CustomSQLRule(Rule):
    """Catch-all for cross-source / shape-specific assertions. The SQL
    must return either a single integer (count of failures) — pass
    when 0 — or a set of rows that are all considered failures."""

    def __init__(
        self,
        *,
        name: str,
        sql: str,
        message: str,
        severity: Severity = Severity.ERROR,
        failure_class: FailureClass = FailureClass.FIX,
        sample_sql: Optional[str] = None,
        params_fn: Optional[Callable[[RuleContext], list[Any]]] = None,
    ) -> None:
        self.name = name
        self._sql = sql
        self._sample_sql = sample_sql
        self._message = message
        self.severity = severity
        self.failure_class = failure_class
        self._params_fn = params_fn or (lambda c: [c.target_date, c.job_run_id])

    async def check(self, ctx: RuleContext) -> list[Finding]:
        params = self._params_fn(ctx)
        result = await ctx.conn.fetchval(self._sql, *params)
        if result in (None, 0, False):
            return []
        sample = []
        if self._sample_sql:
            sample = [dict(r) for r in await ctx.conn.fetch(self._sample_sql, *params)]
        return [Finding(
            rule_name=self.name,
            severity=self.severity,
            failure_class=self.failure_class,
            message=self._message,
            actual=str(result),
            sample_rows=sample,
        )]
