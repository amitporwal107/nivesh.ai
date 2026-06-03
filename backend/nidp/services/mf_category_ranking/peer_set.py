"""Peer-set builder for mf_category_ranking.

Fetches schemes and NAV history from the NIDP DB, applies:
  1. Direct-Growth plan/option filter (ILIKE heuristic — NI-01 decision)
  2. Point-in-time NAV cutoff: nav_date <= rank_date  (AC-09)
  3. Minimum-history gate: >= min_history_bars observations (AC-11)

Returns funds grouped by sebi_category (raw scheme_category string),
each with its metric values ready for the ranking engine.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

import asyncpg
import numpy as np

from ..mf_analytics_engine.calculator import compute_returns, compute_risk_metrics

logger = logging.getLogger(__name__)

# NAV lookback: 5 years + buffer so 5y CAGR can be computed
_LOOKBACK_DAYS = 365 * 5 + 90

# Nifty 50 benchmark name in index_eod (used for Beta computation)
_BENCHMARK = "Nifty 50"


@dataclass
class FundMetrics:
    """All computed metric values for one fund, ready for ranking."""
    scheme_code: str
    scheme_name: str
    sebi_category: str          # raw mf_scheme_master.scheme_category
    expense_ratio: Optional[float]  # from disclosure snapshot (TER direct)
    aum_cr: Optional[float]

    # Computed from NAV series
    return_1y: Optional[float] = None
    return_3y: Optional[float] = None
    return_5y: Optional[float] = None
    sharpe_1y: Optional[float] = None
    sortino_1y: Optional[float] = None
    max_drawdown_1y: Optional[float] = None
    beta_1y: Optional[float] = None

    nav_count: int = 0
    data_as_of: Optional[date] = None

    def metrics_dict(self) -> Dict[str, Optional[float]]:
        """Return metric name → value mapping used by the ranking engine."""
        return {
            "return_1y":       self.return_1y,
            "return_3y":       self.return_3y,
            "return_5y":       self.return_5y,
            "sharpe_1y":       self.sharpe_1y,
            "sortino_1y":      self.sortino_1y,
            "max_drawdown_1y": self.max_drawdown_1y,
            "beta_1y":         self.beta_1y,
            "expense_ratio":   self.expense_ratio,
        }


async def fetch_peer_sets(
    conn: asyncpg.Connection,
    rank_date: date,
    min_history_bars: int = 252,
    batch_size: int = 150,
) -> tuple[Dict[str, List[FundMetrics]], int, int]:
    """Fetch and compute metrics for all Direct-Growth schemes.

    Returns:
        (peer_sets, total_input, dedupe_collapse_count)
        peer_sets: {sebi_category: [FundMetrics, ...]}
        total_input: schemes found before dedupe/history filter
        dedupe_collapse_count: Regular/IDCW schemes filtered out by heuristic
    """
    since = rank_date - timedelta(days=_LOOKBACK_DAYS)

    # Step 1: Fetch all active schemes with metadata
    all_schemes = await _fetch_schemes(conn)
    total_input = len(all_schemes)

    # Step 2: Apply Direct-Growth heuristic filter (NI-01 decision)
    direct_growth, collapsed = _filter_direct_growth(all_schemes)
    dedupe_collapse_count = collapsed

    if not direct_growth:
        return {}, total_input, dedupe_collapse_count

    # Step 3: Fetch Nifty 50 benchmark for Beta
    bench_navs = await _fetch_benchmark(conn, since, rank_date)
    if bench_navs is None:
        logger.warning("mf_category_ranking: no Nifty 50 benchmark data for beta computation")

    # Step 4: Fetch NAV history in batches and compute metrics
    codes = [s["scheme_code"] for s in direct_growth]
    meta_by_code = {s["scheme_code"]: s for s in direct_growth}

    peer_sets: Dict[str, List[FundMetrics]] = {}

    for i in range(0, len(codes), batch_size):
        batch = codes[i: i + batch_size]
        try:
            nav_data = await _fetch_nav_batch(conn, batch, since, rank_date)
        except Exception as exc:
            logger.error("mf_category_ranking: nav fetch error batch=%d %s", i, exc)
            # Mark batch schemes as having no data (they'll get insufficient_history)
            for code in batch:
                m = meta_by_code[code]
                fm = FundMetrics(
                    scheme_code=code,
                    scheme_name=m["scheme_name"] or "",
                    sebi_category=m["scheme_category"] or "Unknown",
                    expense_ratio=m.get("ter"),
                    aum_cr=m.get("aum_cr"),
                    nav_count=0,
                    data_as_of=rank_date,
                )
                peer_sets.setdefault(fm.sebi_category, []).append(fm)
            continue

        for code in batch:
            m = meta_by_code[code]
            nav_pair = nav_data.get(code)
            sebi_cat = m["scheme_category"] or "Unknown"

            if nav_pair is None or len(nav_pair[0]) < min_history_bars:
                fm = FundMetrics(
                    scheme_code=code,
                    scheme_name=m["scheme_name"] or "",
                    sebi_category=sebi_cat,
                    expense_ratio=m.get("ter"),
                    aum_cr=m.get("aum_cr"),
                    nav_count=len(nav_pair[0]) if nav_pair else 0,
                    data_as_of=rank_date,
                )
                peer_sets.setdefault(sebi_cat, []).append(fm)
                continue

            navs, nav_dates = nav_pair
            data_as_of = nav_dates[-1]

            rets = compute_returns(navs, rank_date)
            risk = compute_risk_metrics(
                navs, bench_navs, rets.get("return_1y"),
                window_bars=252,
            )

            fm = FundMetrics(
                scheme_code=code,
                scheme_name=m["scheme_name"] or "",
                sebi_category=sebi_cat,
                expense_ratio=m.get("ter"),
                aum_cr=m.get("aum_cr"),
                return_1y=rets.get("return_1y"),
                return_3y=rets.get("return_3y"),
                return_5y=rets.get("return_5y"),
                sharpe_1y=risk.get("sharpe_1y"),
                sortino_1y=risk.get("sortino_1y"),
                max_drawdown_1y=risk.get("max_drawdown_1y"),
                beta_1y=risk.get("beta_1y"),
                nav_count=len(navs),
                data_as_of=data_as_of,
            )
            peer_sets.setdefault(sebi_cat, []).append(fm)

    return peer_sets, total_input, dedupe_collapse_count


# ── DB helpers ─────────────────────────────────────────────────────────────

async def _fetch_schemes(conn: asyncpg.Connection) -> List[dict]:
    """All active schemes with metadata needed for ranking."""
    rows = await conn.fetch(
        """
        SELECT s.scheme_code,
               s.scheme_name,
               s.scheme_category,
               s.launch_date,
               d.ter_pct_direct   AS ter,
               d.aum_inr_crore    AS aum_cr
          FROM nidp.mf_scheme_master s
          LEFT JOIN LATERAL (
              SELECT ter_pct_direct, aum_inr_crore
                FROM nidp.mf_scheme_disclosure_snapshot
               WHERE scheme_code = s.scheme_code
               ORDER BY snapshot_date DESC
               LIMIT 1
          ) d ON TRUE
         WHERE s.status = 'active'
           AND s.scheme_category IS NOT NULL
         ORDER BY s.scheme_category, s.scheme_code
        """
    )
    return [dict(r) for r in rows]


def _filter_direct_growth(schemes: List[dict]) -> tuple[List[dict], int]:
    """Apply keyword heuristic to keep only Direct-Growth canonical schemes.

    NI-01 decision: name-parsing heuristic over adding plan_type column.

    Filter logic (all checks case-insensitive):
      - FILTER if name contains 'REGULAR' (explicit non-Direct plan)
      - FILTER if name contains 'IDCW' or 'DIVIDEND' (non-Growth option)
      - KEEP if name contains 'DIRECT' (explicit Direct plan) — regardless of option keyword
      - KEEP (ambiguous) if no plan/option keywords detected — fail-open

    Returns (filtered_list, collapse_count).
    """
    kept = []
    collapsed = 0
    ambiguous = 0

    for s in schemes:
        name = (s.get("scheme_name") or "").upper()
        has_regular  = "REGULAR" in name
        has_idcw     = "IDCW" in name or "DIVIDEND" in name
        has_direct   = "DIRECT" in name

        if has_regular or has_idcw:
            # Explicitly a Regular plan or a non-Growth (IDCW/Dividend) option
            collapsed += 1
        elif has_direct:
            # Explicitly Direct (any option that isn't IDCW/Dividend — growth or unspecified)
            kept.append(s)
        else:
            # No plan/option keywords — ambiguous, fail-open
            ambiguous += 1
            kept.append(s)

    if ambiguous:
        logger.info(
            "mf_category_ranking: %d ambiguous scheme names (no plan/option keyword) — included",
            ambiguous,
        )
    if collapsed:
        logger.info(
            "mf_category_ranking: deduped %d Regular/IDCW variants", collapsed
        )

    return kept, collapsed


async def _fetch_nav_batch(
    conn: asyncpg.Connection,
    scheme_codes: List[str],
    since: date,
    until: date,
) -> Dict[str, tuple[np.ndarray, List[date]]]:
    """Fetch NAV history for a batch.  Point-in-time: nav_date <= until (AC-09)."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (scheme_code, nav_date)
               scheme_code, nav_date, nav
          FROM nidp.mf_nav_daily
         WHERE scheme_code = ANY($1::text[])
           AND nav_date >= $2
           AND nav_date <= $3
           AND nav > 0
         ORDER BY scheme_code, nav_date, source
        """,
        scheme_codes, since, until,
    )

    grouped: Dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r["scheme_code"], []).append((r["nav_date"], float(r["nav"])))

    result: Dict[str, tuple] = {}
    for code, pairs in grouped.items():
        pairs.sort(key=lambda p: p[0])
        dates = [p[0] for p in pairs]
        navs = np.array([p[1] for p in pairs])
        result[code] = (navs, dates)
    return result


async def _fetch_benchmark(
    conn: asyncpg.Connection,
    since: date,
    until: date,
) -> Optional[np.ndarray]:
    """Fetch Nifty 50 close prices for Beta computation."""
    rows = await conn.fetch(
        """
        SELECT as_of_date, close_price
          FROM nidp.index_eod
         WHERE index_name = $1
           AND as_of_date >= $2
           AND as_of_date <= $3
           AND close_price > 0
         ORDER BY as_of_date
        """,
        _BENCHMARK, since, until,
    )
    if len(rows) < 30:
        return None
    return np.array([float(r["close_price"]) for r in rows])
