"""Persistence layer for mf_category_ranking.

Upserts RankedFund rows to nidp.mf_category_rank_daily and writes
per-category run metrics to nidp.mf_ranking_run_metrics.

Uses ON CONFLICT DO UPDATE (upsert) — safe to re-run for the same rank_date.
"""
from __future__ import annotations

import json
import decimal as _decimal


class _DecimalEncoder(json.JSONEncoder):
    """Handle Decimal values that asyncpg returns from FDW numeric columns."""
    def default(self, obj):
        if isinstance(obj, _decimal.Decimal):
            return float(obj)
        return super().default(obj)
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List

import asyncpg

from .ranking import RankedFund

logger = logging.getLogger(__name__)

_UPSERT_SQL = """
INSERT INTO nidp.mf_category_rank_daily (
    scheme_code, rank_date,
    sebi_category,
    composite, category_rank, category_pct, category_size,
    metric_contributions,
    status,
    last_ranked_at, data_as_of
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (scheme_code, rank_date) DO UPDATE SET
    sebi_category           = EXCLUDED.sebi_category,
    composite               = EXCLUDED.composite,
    category_rank           = EXCLUDED.category_rank,
    category_pct            = EXCLUDED.category_pct,
    category_size           = EXCLUDED.category_size,
    metric_contributions    = EXCLUDED.metric_contributions,
    status                  = EXCLUDED.status,
    last_ranked_at          = EXCLUDED.last_ranked_at,
    data_as_of              = EXCLUDED.data_as_of
"""

_RUN_METRICS_SQL = """
INSERT INTO nidp.mf_ranking_run_metrics (
    run_id, sebi_category, rank_date,
    ranked_count, insufficient_history_count, insufficient_coverage_count,
    low_confidence_count, total_input_count, dedupe_collapse_count,
    null_counts_per_metric
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (run_id, sebi_category) DO NOTHING
"""


@dataclass
class CategoryRunMetrics:
    sebi_category: str
    ranked_count: int = 0
    insufficient_history_count: int = 0
    insufficient_coverage_count: int = 0
    low_confidence_count: int = 0
    total_input_count: int = 0
    dedupe_collapse_count: int = 0
    null_counts_per_metric: Dict[str, int] = field(default_factory=dict)

    def log(self) -> None:
        logger.info(
            "mf_category_ranking category=%r ranked=%d insuf_history=%d "
            "insuf_coverage=%d low_conf=%d total=%d",
            self.sebi_category,
            self.ranked_count,
            self.insufficient_history_count,
            self.insufficient_coverage_count,
            self.low_confidence_count,
            self.total_input_count,
        )


async def upsert_ranked_funds(
    conn: asyncpg.Connection,
    ranked: List[RankedFund],
    rank_date: date,
    run_id: str,
    dedupe_collapse_count: int = 0,
) -> int:
    """Upsert all ranked funds and emit per-category run metrics.

    Returns count of rows upserted.
    """
    if not ranked:
        return 0

    # Build upsert rows
    rows = []
    for r in ranked:
        rows.append((
            r.scheme_code,
            rank_date,
            r.sebi_category,
            r.composite,
            r.category_rank,
            r.category_pct,
            r.category_size,
            json.dumps(r.metric_contributions, cls=_DecimalEncoder),
            r.status,
            r.last_ranked_at,
            r.data_as_of,
        ))

    await conn.executemany(_UPSERT_SQL, rows)

    # Compute per-category run metrics (AC-12)
    metrics_by_cat: Dict[str, CategoryRunMetrics] = {}
    for r in ranked:
        m = metrics_by_cat.setdefault(
            r.sebi_category,
            CategoryRunMetrics(
                sebi_category=r.sebi_category,
                dedupe_collapse_count=dedupe_collapse_count,
            ),
        )
        m.total_input_count += 1
        if r.status == "ranked":
            m.ranked_count += 1
        elif r.status == "insufficient_history":
            m.insufficient_history_count += 1
        elif r.status == "insufficient_coverage":
            m.insufficient_coverage_count += 1
        elif r.status == "low_confidence":
            m.low_confidence_count += 1

        # Count null metrics
        for metric_name, contrib in r.metric_contributions.items():
            if contrib.get("value") is None:
                m.null_counts_per_metric[metric_name] = (
                    m.null_counts_per_metric.get(metric_name, 0) + 1
                )

    # Persist run metrics and log
    run_metric_rows = []
    for m in metrics_by_cat.values():
        m.log()
        run_metric_rows.append((
            run_id,
            m.sebi_category,
            rank_date,
            m.ranked_count,
            m.insufficient_history_count,
            m.insufficient_coverage_count,
            m.low_confidence_count,
            m.total_input_count,
            m.dedupe_collapse_count,
            json.dumps(m.null_counts_per_metric, cls=_DecimalEncoder),
        ))

    if run_metric_rows:
        try:
            await conn.executemany(_RUN_METRICS_SQL, run_metric_rows)
        except Exception as exc:
            # Run metrics are observability — never let them block the main upsert
            logger.warning("mf_category_ranking: run metrics insert error: %s", exc)

    return len(rows)
