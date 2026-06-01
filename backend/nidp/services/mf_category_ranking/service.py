"""MF Category Ranking Service — main entry point.

Fixes the defective rank-averaging in mf_analytics_engine by implementing
the canonical algorithm:
  1. Build per-category peer sets (Direct-Growth schemes, point-in-time NAV)
  2. Percentile-normalise each metric within the category
  3. Compute weighted composite with re-normalised denominator for nulls
  4. Rank composite once with deterministic tie-breaks
  5. Persist to nidp.mf_category_rank_daily

Usage:
  python -m nidp.services.mf_category_ranking
  python -m nidp.services.mf_category_ranking --date 2026-05-31
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import asyncpg

from .config import ConfigurationError, RankingConfig, family_for_category, load_config
from .peer_set import fetch_peer_sets
from .persistence import upsert_ranked_funds
from .ranking import rank_category

logger = logging.getLogger(__name__)


@dataclass
class MfRankingRunReport:
    rank_date: date
    run_id: str
    categories_processed: int = 0
    funds_ranked: int = 0
    funds_insufficient_history: int = 0
    funds_insufficient_coverage: int = 0
    funds_low_confidence: int = 0
    rows_upserted: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: int = 0

    def log(self) -> None:
        logger.info(
            "mf_ranking_complete date=%s run=%s categories=%d ranked=%d "
            "insuf_history=%d insuf_coverage=%d low_conf=%d upserted=%d errors=%d duration_ms=%d",
            self.rank_date, self.run_id, self.categories_processed,
            self.funds_ranked, self.funds_insufficient_history,
            self.funds_insufficient_coverage, self.funds_low_confidence,
            self.rows_upserted, len(self.errors), self.duration_ms,
        )

    def as_dict(self) -> dict:
        return {
            "rank_date": str(self.rank_date),
            "run_id": self.run_id,
            "categories_processed": self.categories_processed,
            "funds_ranked": self.funds_ranked,
            "funds_insufficient_history": self.funds_insufficient_history,
            "funds_insufficient_coverage": self.funds_insufficient_coverage,
            "funds_low_confidence": self.funds_low_confidence,
            "rows_upserted": self.rows_upserted,
            "errors": self.errors[:20],
            "duration_ms": self.duration_ms,
        }


async def create_pool(url: str) -> asyncpg.Pool:
    """Create asyncpg connection pool."""
    return await asyncpg.create_pool(url, min_size=2, max_size=8)


async def run(
    pool: asyncpg.Pool,
    rank_date: date,
    *,
    config: Optional[RankingConfig] = None,
) -> MfRankingRunReport:
    """Run the full ranking pipeline for rank_date.

    Args:
        pool:      asyncpg connection pool
        rank_date: the 'as of' date for NAV and category membership
        config:    override config (default: loads weights.yaml)

    Raises:
        ConfigurationError: if weights config is invalid at startup
    """
    if config is None:
        config = load_config()   # raises ConfigurationError if weights invalid

    t0 = time.monotonic()
    run_id = str(uuid.uuid4())
    report = MfRankingRunReport(rank_date=rank_date, run_id=run_id)

    logger.info(
        "mf_category_ranking_start date=%s run=%s families=%s",
        rank_date, run_id, list(config.families.keys()),
    )

    async with pool.acquire() as conn:
        # Fetch all peer sets + compute metrics
        try:
            peer_sets, total_input, dedupe_collapse = await fetch_peer_sets(
                conn, rank_date,
                min_history_bars=config.min_history_bars,
            )
        except Exception as exc:
            logger.error("mf_category_ranking: peer_set fetch failed: %s", exc)
            report.errors.append(f"peer_set_fetch: {exc}")
            report.duration_ms = int((time.monotonic() - t0) * 1000)
            return report

        logger.info(
            "mf_category_ranking: fetched %d categories %d total_input %d deduped",
            len(peer_sets), total_input, dedupe_collapse,
        )

        # Rank each category and collect all output
        all_ranked = []
        for sebi_category, funds in peer_sets.items():
            if not funds:
                continue
            try:
                family_cfg = family_for_category(sebi_category, config)
                ranked = rank_category(funds, family_cfg, config, rank_date)
                all_ranked.extend(ranked)
                report.categories_processed += 1

                for r in ranked:
                    if r.status == "ranked":
                        report.funds_ranked += 1
                    elif r.status == "insufficient_history":
                        report.funds_insufficient_history += 1
                    elif r.status == "insufficient_coverage":
                        report.funds_insufficient_coverage += 1
                    elif r.status == "low_confidence":
                        report.funds_low_confidence += 1

            except Exception as exc:
                logger.error(
                    "mf_category_ranking: error ranking category=%r: %s",
                    sebi_category, exc,
                )
                report.errors.append(f"rank_{sebi_category}: {exc}")

        # Persist
        if all_ranked:
            try:
                upserted = await upsert_ranked_funds(
                    conn, all_ranked, rank_date, run_id, dedupe_collapse
                )
                report.rows_upserted = upserted
            except Exception as exc:
                logger.error("mf_category_ranking: upsert failed: %s", exc)
                report.errors.append(f"upsert: {exc}")

    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.log()
    return report
