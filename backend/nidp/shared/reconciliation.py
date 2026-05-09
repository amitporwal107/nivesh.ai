"""Reconciliation Engine.

After multiple ingesters have written facts for the same entity+field,
this engine:

  1. Collects all source values (ordered by source precedence).
  2. Applies the majority-vote + highest-priority-wins rule.
  3. Detects disagreements and records them as consistency findings.
  4. Returns the canonical (reconciled) value for downstream certification.

Source precedence registry maps field_name → ordered list of source labels.
The first source in the list is the golden source; others are cross-checks.

Usage:
    from nidp.shared.reconciliation import reconcile_field, FIELD_PRECEDENCE

    result = await reconcile_field(
        conn, field="nav", entity_id="119551", target_date=date.today()
    )
    # result.canonical_value — the value to publish
    # result.agreement      — True if all sources agreed within tolerance
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

# ── Source precedence registry ───────────────────────────────────────
# Maps field_name → [(source_label, SQL returning (entity_id, value))].
# First entry = golden source.  Add new fields here without touching
# the engine logic.

_FIELD_SOURCES: dict[str, list[tuple[str, str]]] = {
    "nav": [
        (
            "amfi_nav_daily",
            "SELECT scheme_code AS entity_id, nav::text AS value "
            "FROM nidp.mf_nav_daily WHERE nav_date = $1",
        ),
        (
            "scheme_master_cache",
            "SELECT scheme_code AS entity_id, latest_nav::text AS value "
            "FROM nidp.mf_scheme_master WHERE latest_nav_date = $1 AND latest_nav IS NOT NULL",
        ),
    ],
    "ter_pct": [
        (
            "disclosure_snapshot",
            "SELECT scheme_code AS entity_id, ter_pct::text AS value "
            "FROM nidp.mf_scheme_disclosure_snapshot WHERE snapshot_date = $1",
        ),
    ],
    "close_price": [
        (
            "bhavcopy",
            "SELECT symbol AS entity_id, close_price::text AS value "
            "FROM nidp.prices_eod WHERE as_of_date = $1 AND series = 'EQ'",
        ),
        (
            "bhavcopy_adj",
            "SELECT symbol AS entity_id, close_pr::text AS value "
            "FROM nidp.prices_eod_adjusted WHERE as_of_date = $1",
        ),
    ],
    "promoter_pct": [
        (
            "nse_shp",
            "SELECT symbol AS entity_id, promoter_pct::text AS value "
            "FROM nidp.shareholding_pattern "
            "WHERE period_end = (SELECT max(period_end) FROM nidp.shareholding_pattern "
            "                    WHERE period_end <= $1)",
        ),
    ],
}

# Per-field tolerance for "same value" comparison (absolute difference).
_FIELD_TOLERANCE: dict[str, float] = {
    "nav":         0.0001,   # 4 decimal places
    "ter_pct":     0.0001,
    "close_price": 0.01,
    "promoter_pct": 0.01,
}


def register_field_sources(
    field_name: str,
    sources: list[tuple[str, str]],
    tolerance: float = 0.001,
) -> None:
    """Register additional field sources at module load time."""
    _FIELD_SOURCES[field_name] = sources
    _FIELD_TOLERANCE[field_name] = tolerance


@dataclass
class ReconciliationResult:
    field_name:      str
    entity_id:       str
    target_date:     date
    golden_source:   str
    canonical_value: Optional[float]
    all_values:      dict[str, Optional[float]]     # source → value
    agreement:       bool                            # all present sources agree within tol
    disagreements:   list[dict[str, Any]] = field(default_factory=list)


async def reconcile_field(
    conn: asyncpg.Connection,
    field_name: str,
    entity_id: str,
    target_date: date,
) -> ReconciliationResult:
    """Fetch all source values for (field, entity, date) and reconcile."""
    sources = _FIELD_SOURCES.get(field_name, [])
    tol = _FIELD_TOLERANCE.get(field_name, 0.001)

    all_values: dict[str, Optional[float]] = {}
    for label, sql in sources:
        rows = await conn.fetch(sql, target_date)
        for r in rows:
            if str(r["entity_id"]) == entity_id and r["value"] is not None:
                try:
                    all_values[label] = float(r["value"])
                except (ValueError, TypeError):
                    all_values[label] = None
                break
        else:
            all_values[label] = None

    # Golden source = first registered
    golden_label   = sources[0][0] if sources else "unknown"
    canonical      = all_values.get(golden_label)
    disagreements: list[dict[str, Any]] = []

    if canonical is not None:
        for label, val in all_values.items():
            if label == golden_label or val is None:
                continue
            if abs(val - canonical) > tol:
                dev = abs(val - canonical) / max(abs(canonical), tol) * 100.0
                disagreements.append({
                    "source":       label,
                    "value":        val,
                    "golden_value": canonical,
                    "deviation_pct": round(dev, 4),
                })

    agreement = len(disagreements) == 0

    if not agreement:
        logger.warning(
            "reconcile[%s] entity=%s date=%s: %d source(s) disagree with golden=%s",
            field_name, entity_id, target_date, len(disagreements), golden_label,
        )

    return ReconciliationResult(
        field_name=field_name,
        entity_id=entity_id,
        target_date=target_date,
        golden_source=golden_label,
        canonical_value=canonical,
        all_values=all_values,
        agreement=agreement,
        disagreements=disagreements,
    )


async def reconcile_domain(
    conn: asyncpg.Connection,
    field_name: str,
    target_date: date,
) -> list[ReconciliationResult]:
    """Reconcile all entities for a field on a given date."""
    sources = _FIELD_SOURCES.get(field_name, [])
    if not sources:
        return []

    golden_label, golden_sql = sources[0]
    rows = await conn.fetch(golden_sql, target_date)
    entity_ids = [str(r["entity_id"]) for r in rows]

    results: list[ReconciliationResult] = []
    for eid in entity_ids:
        res = await reconcile_field(conn, field_name, eid, target_date)
        results.append(res)
    return results


def cross_source_agreement_pct(results: list[ReconciliationResult]) -> float:
    """Compute G (cross-source agreement %) over a set of reconciliation results."""
    if not results:
        return 100.0
    agreed = sum(1 for r in results if r.agreement)
    return round(100.0 * agreed / len(results), 3)
