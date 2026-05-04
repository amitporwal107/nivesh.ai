"""Chartink scan-result loader.

Chartink lets you export scan results as CSV with a 'Symbol' column (and
typically: Stock Name, Symbol, Links, % Chg, Price, Volume). Drop the CSV
into the loader and it persists rows into chartink_scan_hits.

Two paths:
  1. Per-scan CSV upload (preferred — explicit scan_name passed in).
  2. Programmatic ingest from a list of {symbol, ...} dicts.

We intentionally do NOT scrape Chartink (their dashboards are JS-rendered
behind auth and TOS-restricted). Export → upload → ingest.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date
from typing import Iterable, List, Optional

from services import pg_client

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────
def _norm_symbol(raw: str) -> str:
    """Chartink CSVs sometimes include suffixes like '.NS' or extra whitespace."""
    s = raw.strip().upper()
    if s.endswith(".NS"):
        s = s[:-3]
    if s.endswith(".BO"):
        s = s[:-3]
    return s


def parse_csv(blob: str) -> List[dict]:
    """Return a list of {symbol, extra} from a Chartink CSV blob.

    Tolerant of column variations: tries Symbol → NSE Code → Code → Stock.
    Unknown rows are skipped.
    """
    reader = csv.DictReader(io.StringIO(blob))
    out: List[dict] = []
    sym_keys = ("Symbol", "Symbol ", "NSE Code", "Code", "Stock", "stock", "symbol")
    for row in reader:
        sym_raw = None
        for k in sym_keys:
            if k in row and row[k]:
                sym_raw = row[k]
                break
        if not sym_raw:
            continue
        out.append({
            "symbol": _norm_symbol(sym_raw),
            "extra": {k: v for k, v in row.items() if v and k not in sym_keys},
        })
    return out


# ── DB writers ───────────────────────────────────────────────────────────
async def upsert_scan_hits(scan_date: date,
                           scan_name: str,
                           rows: Iterable[dict]) -> int:
    """Upsert (date, scan_name, symbol) rows. Returns count inserted/updated."""
    pool = await pg_client.get_pool()
    if pool is None:
        logger.warning("upsert_scan_hits: no pg pool")
        return 0
    payload = [(scan_date, scan_name, r["symbol"], json.dumps(r.get("extra") or {}))
               for r in rows if r.get("symbol")]
    if not payload:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO chartink_scan_hits (scan_date, scan_name, nse_symbol, extra)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (scan_date, scan_name, nse_symbol)
            DO UPDATE SET extra = EXCLUDED.extra, ingested_at = NOW()
            """,
            payload,
        )
    return len(payload)


async def get_scans_for(scan_date: date, symbol: str) -> List[str]:
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT scan_name FROM chartink_scan_hits "
            "WHERE scan_date = $1 AND nse_symbol = $2",
            scan_date, symbol,
        )
    return [r["scan_name"] for r in rows]


async def list_universe_for(scan_date: date) -> List[str]:
    """All symbols that hit ANY scan on `scan_date` — the daily universe."""
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT nse_symbol FROM chartink_scan_hits WHERE scan_date = $1",
            scan_date,
        )
    return [r["nse_symbol"] for r in rows]
