"""Cross-source, temporal, internal, API, and point-in-time consistency rules.

Five dimensions defined in NIDP Data Quality Rules:
  CROSS_SOURCE   — same field compared across multiple ingester tables
  INTERNAL       — related fields within one table (weights sum, OHLC, accounting eq)
  TEMPORAL       — change vs prior period exceeds threshold
  API            — same field matches across /api/... endpoints (SQL cross-check)
  POINT_IN_TIME  — historical snapshot integrity; as-of queries remain reproducible

Rule contract: async check(conn, target_date) -> list[ConsistencyFinding]
Empty list = pass.

Registry maps domain -> list[ConsistencyRule].  Domain values: 'mf' | 'equity' | 'all'.
"""
from __future__ import annotations

import abc
import enum
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

import asyncpg

from .rules import FailureClass, Severity


class ConsistencyDimension(str, enum.Enum):
    CROSS_SOURCE   = "CROSS_SOURCE"
    INTERNAL       = "INTERNAL"
    TEMPORAL       = "TEMPORAL"
    API            = "API"
    POINT_IN_TIME  = "POINT_IN_TIME"


@dataclass
class ConsistencyFinding:
    rule_name:    str
    dimension:    ConsistencyDimension
    severity:     Severity
    failure_class: FailureClass
    message:      str
    entity_type:  Optional[str] = None   # 'scheme' | 'symbol' | 'portfolio'
    entity_id:    Optional[str] = None   # scheme_code, NSE symbol, etc.
    field_name:   Optional[str] = None
    source_a:     Optional[str] = None
    value_a:      Optional[str] = None
    source_b:     Optional[str] = None
    value_b:      Optional[str] = None
    deviation_pct: Optional[float] = None
    sample_rows:  list[dict[str, Any]] = field(default_factory=list)


class ConsistencyRule(abc.ABC):
    """Subclass and implement `check`.  `name` must be stable and grep-able."""
    name:       str = ""
    dimension:  ConsistencyDimension = ConsistencyDimension.CROSS_SOURCE
    severity:   Severity = Severity.ERROR
    failure_class: FailureClass = FailureClass.FIX

    @abc.abstractmethod
    async def check(
        self,
        conn: asyncpg.Connection,
        target_date: date,
    ) -> list[ConsistencyFinding]: ...


# ── Built-in rule helpers ────────────────────────────────────────────

class CrossSourceRule(ConsistencyRule):
    """Compare the same numeric field from two SQL queries (golden vs published).

    Each query must return rows of (entity_id, value).  For each entity present
    in both, compute accuracy = 100 × (1 − |a − b| / max(|b|, epsilon)) and
    emit a finding when accuracy drops below `min_accuracy`.
    """
    dimension = ConsistencyDimension.CROSS_SOURCE

    def __init__(
        self,
        *,
        name: str,
        field_name: str,
        entity_type: str,
        source_a_label: str,
        source_a_sql: str,      # returns (entity_id TEXT, value NUMERIC)
        source_b_label: str,
        source_b_sql: str,
        min_accuracy: float = 99.9,
        epsilon: float = 1e-6,
        severity: Severity = Severity.ERROR,
        failure_class: FailureClass = FailureClass.FIX,
    ) -> None:
        self.name          = name
        self._field        = field_name
        self._entity_type  = entity_type
        self._label_a      = source_a_label
        self._sql_a        = source_a_sql
        self._label_b      = source_b_label
        self._sql_b        = source_b_sql
        self._min_acc      = min_accuracy
        self._eps          = epsilon
        self.severity      = severity
        self.failure_class = failure_class

    async def check(self, conn: asyncpg.Connection, target_date: date) -> list[ConsistencyFinding]:
        rows_a = {r["entity_id"]: float(r["value"]) for r in await conn.fetch(self._sql_a, target_date) if r["value"] is not None}
        rows_b = {r["entity_id"]: float(r["value"]) for r in await conn.fetch(self._sql_b, target_date) if r["value"] is not None}

        findings: list[ConsistencyFinding] = []
        for eid in rows_a.keys() & rows_b.keys():
            va, vb = rows_a[eid], rows_b[eid]
            denom = max(abs(vb), self._eps)
            accuracy = 100.0 * (1.0 - abs(va - vb) / denom)
            if accuracy < self._min_acc:
                dev = abs(va - vb) / denom * 100.0
                findings.append(ConsistencyFinding(
                    rule_name=self.name,
                    dimension=self.dimension,
                    severity=self.severity,
                    failure_class=self.failure_class,
                    message=(
                        f"{self._field} mismatch for {eid}: "
                        f"{self._label_a}={va} vs {self._label_b}={vb} "
                        f"(deviation {dev:.4f}%, accuracy {accuracy:.2f}%)"
                    ),
                    entity_type=self._entity_type,
                    entity_id=eid,
                    field_name=self._field,
                    source_a=self._label_a,
                    value_a=str(va),
                    source_b=self._label_b,
                    value_b=str(vb),
                    deviation_pct=round(dev, 4),
                ))
        return findings


class InternalConsistencyRule(ConsistencyRule):
    """Assert an internal consistency invariant via SQL.

    SQL must return a count of violating rows (int scalar).  When > 0,
    `sample_sql` is run to attach example rows.
    """
    dimension = ConsistencyDimension.INTERNAL

    def __init__(
        self,
        *,
        name: str,
        sql: str,
        message: str,
        sample_sql: Optional[str] = None,
        field_name: Optional[str] = None,
        entity_type: Optional[str] = None,
        severity: Severity = Severity.ERROR,
        failure_class: FailureClass = FailureClass.FIX,
        params_fn: Optional[Callable[[date], list[Any]]] = None,
    ) -> None:
        self.name          = name
        self._sql          = sql
        self._sample_sql   = sample_sql
        self._message      = message
        self._field        = field_name
        self._entity_type  = entity_type
        self.severity      = severity
        self.failure_class = failure_class
        self._params_fn    = params_fn or (lambda d: [d])

    async def check(self, conn: asyncpg.Connection, target_date: date) -> list[ConsistencyFinding]:
        params = self._params_fn(target_date)
        bad = int(await conn.fetchval(self._sql, *params) or 0)
        if bad == 0:
            return []
        sample: list[dict[str, Any]] = []
        if self._sample_sql:
            sample = [dict(r) for r in await conn.fetch(self._sample_sql, *params)]
        return [ConsistencyFinding(
            rule_name=self.name,
            dimension=self.dimension,
            severity=self.severity,
            failure_class=self.failure_class,
            message=f"{self._message} ({bad} violating row(s))",
            field_name=self._field,
            entity_type=self._entity_type,
            actual=str(bad),
            sample_rows=sample,
        )]


class TemporalConsistencyRule(ConsistencyRule):
    """Flag entities whose field value changed > `threshold_pct` vs the prior period.

    SQL must return rows of (entity_id, current_val, prior_val).
    Only rows where abs(change) > threshold_pct are returned.
    """
    dimension = ConsistencyDimension.TEMPORAL

    def __init__(
        self,
        *,
        name: str,
        field_name: str,
        entity_type: str,
        sql: str,               # returns (entity_id, current_val, prior_val, change_pct)
        threshold_pct: float,
        severity: Severity = Severity.WARN,
        failure_class: FailureClass = FailureClass.FIX,
        params_fn: Optional[Callable[[date], list[Any]]] = None,
    ) -> None:
        self.name          = name
        self._field        = field_name
        self._entity_type  = entity_type
        self._sql          = sql
        self._threshold    = threshold_pct
        self.severity      = severity
        self.failure_class = failure_class
        self._params_fn    = params_fn or (lambda d: [d])

    async def check(self, conn: asyncpg.Connection, target_date: date) -> list[ConsistencyFinding]:
        params = self._params_fn(target_date)
        rows = await conn.fetch(self._sql, *params)
        findings: list[ConsistencyFinding] = []
        for r in rows:
            eid   = str(r["entity_id"])
            cur   = float(r["current_val"]) if r["current_val"] is not None else None
            prior = float(r["prior_val"])   if r["prior_val"]   is not None else None
            chg   = float(r["change_pct"])  if r["change_pct"]  is not None else None
            if chg is None or abs(chg) <= self._threshold:
                continue
            findings.append(ConsistencyFinding(
                rule_name=self.name,
                dimension=self.dimension,
                severity=self.severity,
                failure_class=self.failure_class,
                message=(
                    f"{self._field} changed {chg:+.2f}% for {eid} "
                    f"(threshold ±{self._threshold}%): {prior} → {cur}"
                ),
                entity_type=self._entity_type,
                entity_id=eid,
                field_name=self._field,
                source_a="prior_period",
                value_a=str(prior),
                source_b="current_period",
                value_b=str(cur),
                deviation_pct=round(abs(chg), 4),
            ))
        return findings


# ── Consistency rule registry ────────────────────────────────────────

_CONSISTENCY_REGISTRY: dict[str, list[ConsistencyRule]] = {}


def register_consistency(domain: str, rules: list[ConsistencyRule]) -> None:
    _CONSISTENCY_REGISTRY.setdefault(domain, []).extend(rules)


def get_consistency_rules(domain: str) -> list[ConsistencyRule]:
    if domain == "all":
        combined: list[ConsistencyRule] = []
        for rules in _CONSISTENCY_REGISTRY.values():
            combined.extend(rules)
        return combined
    return list(_CONSISTENCY_REGISTRY.get(domain, []))


def consistency_domains() -> list[str]:
    return sorted(_CONSISTENCY_REGISTRY.keys())
