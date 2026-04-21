#!/usr/bin/env python3
"""Daily AMFI NAV fetcher.

Pulls the EOD NAV dump from https://portal.amfiindia.com/spages/NAVAll.txt
and upserts into `mutual_fund_nav_history` keyed by (instrument_id, nav_date).

AMFI file format (pipe-delimited, with section headers):

    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

    Open Ended Schemes ( Equity Scheme - Large Cap Fund )
    Aditya Birla Sun Life AMC Limited
    101739;INF209KB11M4;INF209KB12M2;Aditya Birla Sun Life Frontline Equity Fund - Growth - Regular Plan;358.4817;20-Feb-2026
    ...

Design:
- Matches funds to `instrument_master` by ISIN first, then by fuzzy-normalised scheme name.
- Writes (instrument_id, nav_date, nav) idempotently via ON CONFLICT.
- Logs a summary row to `amfi_nav_fetch_log` for audit.
- Safe to re-run — NAV rows are idempotent by PK.

Usage:
    python -m scripts.fetch_amfi_navs          # run once
    python -m scripts.fetch_amfi_navs --dry-run
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime, date
from typing import Iterator, Optional, Tuple

import httpx
import asyncpg

# Allow `python scripts/fetch_amfi_navs.py` from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from services.pg_client import get_pool  # uses existing DB creds
except ImportError:
    # Standalone fallback — use env directly
    get_pool = None  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [amfi_navs] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"


def _normalise_name(s: str) -> str:
    """Same tokenising we use elsewhere so matches line up with scraper."""
    if not s:
        return ""
    s = re.sub(r"\([^)]*\)", " ", s.lower())
    s = s.replace(",", " ").replace("-", " ")
    s = re.sub(r"^\s*\b[a-z]{2,5}\b\s+(?=[a-z])", "", s)
    return " ".join(s.split())


def _parse_date(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d.strip(), "%d-%b-%Y").date()
    except Exception:
        return None


def iter_rows(text: str) -> Iterator[Tuple[str, str, str, float, date]]:
    """Yield (scheme_code, isin, name, nav, nav_date) from the AMFI dump.

    Skips header rows, blank lines, and section/AMC title lines.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("scheme code"):
            continue
        # Data rows have exactly 6 semicolon-delimited fields
        parts = line.split(";")
        if len(parts) != 6:
            continue
        scheme_code, isin_pay, isin_reinv, name, nav_str, date_str = parts
        if not scheme_code.strip().isdigit():
            continue
        try:
            nav = float(nav_str.strip())
        except ValueError:
            continue
        if nav <= 0:
            continue
        dt = _parse_date(date_str)
        if not dt:
            continue
        isin = (isin_pay or isin_reinv or "").strip() or None
        yield scheme_code.strip(), (isin or ""), name.strip(), nav, dt


async def _ensure_pool():
    if get_pool is not None:
        pool = await get_pool()
        if pool:
            return pool
    url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") \
        or "postgresql://postgres:postgres@localhost:5432/nivesh"
    return await asyncpg.create_pool(url, min_size=1, max_size=4)


async def resolve_instrument_id(
    conn: asyncpg.Connection, isin: str, name: str, scheme_code: str
) -> Optional[str]:
    """Find the instrument_id in instrument_master for this AMFI row.

    Resolution order: exact ISIN → scheme-code-in-metadata → normalised name.
    Returns None if no confident match.
    """
    if isin:
        r = await conn.fetchrow(
            "SELECT instrument_id FROM instrument_master WHERE isin = $1 AND instrument_type = 'MUTUAL_FUND' LIMIT 1",
            isin,
        )
        if r:
            return str(r["instrument_id"])

    if scheme_code:
        r = await conn.fetchrow(
            "SELECT instrument_id FROM mutual_fund_metadata WHERE amfi_scheme_code = $1 LIMIT 1",
            scheme_code,
        )
        if r:
            return str(r["instrument_id"])

    if name:
        norm = _normalise_name(name)
        r = await conn.fetchrow(
            """
            SELECT instrument_id FROM instrument_master
            WHERE instrument_type = 'MUTUAL_FUND'
              AND lower(instrument_name) = $1
            LIMIT 1
            """,
            norm,
        )
        if r:
            return str(r["instrument_id"])
        # pg_trgm similarity as a softer fallback (index already exists)
        r = await conn.fetchrow(
            """
            SELECT instrument_id, similarity(lower(instrument_name), $1) AS s
            FROM instrument_master
            WHERE instrument_type = 'MUTUAL_FUND'
              AND lower(instrument_name) % $1
            ORDER BY s DESC LIMIT 1
            """,
            norm,
        )
        if r and (r["s"] or 0) >= 0.55:
            return str(r["instrument_id"])

    return None


async def run(dry_run: bool = False) -> dict:
    t0 = time.time()
    log.info(f"Fetching {AMFI_URL}")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(AMFI_URL)
        resp.raise_for_status()
        body = resp.text
    log.info(f"Fetched {len(body):,} chars")

    pool = await _ensure_pool()
    async with pool.acquire() as conn:
        # Ensure pg_trgm is available for similarity search. Harmless if already
        # enabled by an earlier migration.
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:
            pass

        parsed = 0
        upserted = 0
        skipped_no_match = 0

        # Batch insert for throughput: collect 500 rows, flush.
        BATCH = 500
        buf: list[tuple] = []

        async def flush():
            nonlocal upserted
            if not buf:
                return
            if dry_run:
                upserted += len(buf)
                buf.clear()
                return
            await conn.executemany(
                """
                INSERT INTO mutual_fund_nav_history (instrument_id, nav_date, nav, source)
                VALUES ($1::uuid, $2, $3, 'amfi')
                ON CONFLICT (instrument_id, nav_date) DO UPDATE SET nav = EXCLUDED.nav
                """,
                buf,
            )
            upserted += len(buf)
            buf.clear()

        for scheme_code, isin, name, nav, nav_date in iter_rows(body):
            parsed += 1
            iid = await resolve_instrument_id(conn, isin, name, scheme_code)
            if not iid:
                skipped_no_match += 1
                continue
            buf.append((iid, nav_date, nav))
            if len(buf) >= BATCH:
                await flush()
            if parsed % 2000 == 0:
                log.info(f"  progress: parsed={parsed} upserted={upserted} skipped={skipped_no_match}")

        await flush()

        dur_ms = int((time.time() - t0) * 1000)
        log.info(
            f"Done. parsed={parsed:,} upserted={upserted:,} skipped_no_match={skipped_no_match:,} "
            f"duration_ms={dur_ms:,}"
        )

        if not dry_run:
            await conn.execute(
                """
                INSERT INTO amfi_nav_fetch_log (rows_parsed, rows_upserted, rows_skipped, duration_ms, status)
                VALUES ($1, $2, $3, $4, 'ok')
                """,
                parsed, upserted, skipped_no_match, dur_ms,
            )

    return {
        "parsed": parsed,
        "upserted": upserted,
        "skipped_no_match": skipped_no_match,
        "duration_ms": int((time.time() - t0) * 1000),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Parse but don't write to DB")
    args = ap.parse_args()
    try:
        result = asyncio.run(run(dry_run=args.dry_run))
        log.info(f"SUMMARY {result}")
        sys.exit(0)
    except Exception as e:
        log.exception(f"Fetch failed: {e}")
        # Best-effort failure log
        err_msg = str(e)[:500]
        try:
            async def _err():
                pool = await _ensure_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO amfi_nav_fetch_log (status, error_msg) VALUES ('failed', $1)",
                        err_msg,
                    )
            asyncio.run(_err())
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
