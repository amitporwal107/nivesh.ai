"""NIDP Postgres connection.

Owns its own asyncpg pool so NIDP does not import the existing
backend.services.pg_client. Same DB host (NIDP_POSTGRES_URL or, as
fallback, POSTGRES_URL) but a separate pool — lets us tear down NIDP
cleanly without disturbing live services.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def _resolve_url() -> Optional[str]:
    return (
        os.environ.get("NIDP_POSTGRES_URL")
        or os.environ.get("POSTGRES_URL")
        or "postgresql://postgres:postgres@localhost:5432/nivesh"
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    url = _resolve_url()
    _pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=4,
        command_timeout=30,
        statement_cache_size=0,
        server_settings={"search_path": "nidp,public"},
    )
    logger.info("NIDP pg pool initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    # Close the shared NSE HTTP session — always torn down together at process
    # exit; skipping it causes asyncio "Unclosed client session" ERROR noise.
    try:
        from nidp.shared.sources import nse_fetcher
        await nse_fetcher.close()
    except Exception:  # noqa: BLE001
        pass


# pgvector HNSW GUCs for FILTERED vector search.
#
# An HNSW scan walks the graph collecting ef_search (default 40) candidates and
# only THEN applies the query's WHERE clause. When the filter is selective — one
# ticker out of ~2,000 — none of those 40 survive and the vector leg returns ZERO
# rows. It does not error. Measured on staging 2026-07-19 against 311,868 embedded
# chunks: a company-scoped AI query returned 0 rows for both TCS (195 embedded
# chunks) and HCLTech (299) at the default, and 3 correct rows with iterative_scan.
#
# This is especially dangerous in the hybrid RRF queries here: the FTS leg still
# returns results, so the endpoint looks healthy while semantic search silently
# contributes nothing. Symptom is "search got worse", not "search broke".
#
# iterative_scan lets the scan resume through the graph until the filter is
# satisfied. relaxed_order is used over strict_order because the row_number()
# window re-sorts by distance anyway, so relaxed only affects WHICH candidates
# come back (better recall), not their ranking. max_scan_tuples bounds the cost.
# Measured: TCS 176ms -> 181ms with iterative_scan, vs 1092ms for ef_search=1000
# (same 3 rows) — ~6x cheaper than brute-forcing the candidate pool.
#
# Requires pgvector >= 0.8.0 (staging runs 0.8.1). On older builds the GUC does
# not exist and SET raises; we swallow it so search degrades to the old behaviour
# rather than failing the request.
async def prepare_vector_search(conn) -> bool:
    """Configure `conn` for filtered HNSW search. True if applied.

    Call before any query that ORDERs BY an `<=>` distance AND filters on a
    column the vector index does not cover. Session-scoped on a pooled
    connection, which is safe: these GUCs only affect vector index scans.
    """
    try:
        await conn.execute("SET hnsw.iterative_scan = relaxed_order")
        await conn.execute("SET hnsw.max_scan_tuples = 20000")
        return True
    except Exception as e:  # noqa: BLE001 — pgvector < 0.8: keep serving results
        logger.debug("pgvector iterative_scan unavailable (%s); "
                     "filtered vector search may under-return", e)
        return False
