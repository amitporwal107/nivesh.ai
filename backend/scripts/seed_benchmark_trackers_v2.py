"""Seed NIFTY index-tracker funds as benchmark proxies for V3 downside_capture.

Skips Groww entirely — inserts directly into `instrument_master` using verified
AMFI scheme codes + ISINs, then triggers the AMFI NAV backfill which uses strict
ISIN-only matching to pull 5y of historical NAVs for these new funds.

Tracker picks are the oldest / highest-AUM fund per benchmark so 5y NAV history
is available for every mapping.

Run: `python -m scripts.seed_benchmark_trackers_v2 --backfill`
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import pg_client  # noqa: E402

log = logging.getLogger("seed_benchmarks")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Verified against AMFI NAVAll.txt (2026-04-21).
# Each tuple: (amfi_code, isin, scheme_name, covers_benchmark_names[])
TRACKERS = [
    ("120716", "INF789F01XA0",
     "UTI Nifty 50 Index Fund - Direct Plan - Growth",
     ["NIFTY 50 TRI"]),
    ("143341", "INF789FC12T1",
     "UTI Nifty Next 50 Index Fund - Direct Plan - Growth",
     ["NIFTY Next 50 TRI"]),
    ("149868", "INF179KC1BY3",
     "HDFC NIFTY 100 Index Fund - Direct Plan - Growth",
     ["NIFTY 100 TRI"]),
    ("148726", "INF204KB18Z7",
     "Nippon India Nifty Midcap 150 Index Fund - Direct Plan - Growth",
     ["NIFTY Midcap 150 TRI", "NIFTY LargeMidcap 250 TRI"]),
    ("148519", "INF204KB15W0",
     "Nippon India Nifty Smallcap 250 Index Fund - Direct Plan - Growth",
     ["NIFTY Smallcap 250 TRI"]),
    ("153161", "INF109KC16Y3",
     "ICICI Prudential Nifty 500 Index Fund - Direct Plan - Growth",
     ["NIFTY 500 TRI", "NIFTY 500 Multicap 50:25:25 TRI"]),
]


async def _upsert_instrument(conn, amfi_code: str, isin: str, name: str) -> str:
    """Idempotently insert/lookup an instrument, returning its UUID."""
    # Check by ISIN first (strongest key)
    r = await conn.fetchrow(
        "SELECT instrument_id::text FROM instrument_master WHERE isin = $1", isin
    )
    if r:
        # Just update symbol if missing
        await conn.execute(
            "UPDATE instrument_master SET symbol = $1 "
            "WHERE instrument_id = $2::uuid AND (symbol IS NULL OR symbol = '')",
            amfi_code, r["instrument_id"],
        )
        return r["instrument_id"]
    # Insert new
    r = await conn.fetchrow(
        """
        INSERT INTO instrument_master (instrument_name, instrument_type, isin, symbol)
        VALUES ($1, 'MUTUAL_FUND', $2, $3)
        RETURNING instrument_id::text
        """,
        name, isin, amfi_code,
    )
    return r["instrument_id"]


async def _ensure_metadata_row(conn, iid: str, category: str) -> None:
    """Make sure mutual_fund_metadata has a row so the scoring layer reads work."""
    await conn.execute(
        """
        INSERT INTO mutual_fund_metadata (instrument_id, category, sub_category, last_scraped_at, updated_at)
        VALUES ($1::uuid, $2, $2, NOW(), NOW())
        ON CONFLICT (instrument_id) DO NOTHING
        """,
        iid, category,
    )


async def _wire_proxies(conn, mappings: dict[str, str]) -> int:
    """mappings: {benchmark_name: proxy_iid}. Returns #rows updated."""
    total = 0
    for bm_name, iid in mappings.items():
        result = await conn.execute(
            "UPDATE benchmark_master SET proxy_instrument_id = $1::uuid WHERE benchmark_name = $2",
            iid, bm_name,
        )
        count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
        total += count
        if count:
            log.info(f"  proxy → {bm_name:<40} ({count} categories)")
    return total


async def run_seed() -> dict:
    pool = await pg_client.get_pool()
    if pool is None:
        log.error("No PG pool — abort")
        return {"ok": False}

    mappings: dict[str, str] = {}
    inserted = 0
    async with pool.acquire() as conn:
        for amfi, isin, name, covers in TRACKERS:
            iid = await _upsert_instrument(conn, amfi, isin, name)
            await _ensure_metadata_row(conn, iid, "Index")
            inserted += 1
            log.info(f"[seeded] {name[:60]}  isin={isin}  iid={iid[:8]}…")
            for bm in covers:
                mappings[bm] = iid
        wired = await _wire_proxies(conn, mappings)

    return {"ok": True, "seeded": inserted, "proxies_wired": wired}


async def run_backfill(years: float = 5.0) -> dict:
    """Re-run the 5y historical NAV backfill so our new tracker ISINs get NAV rows."""
    from scripts.backfill_amfi_nav_history import run as _bf_run
    end = date.today()
    start = end - timedelta(days=int(years * 365))
    log.info(f"[backfill] {start} → {end}")
    return await _bf_run(start, end)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true",
                    help="Also run 5y NAV backfill after seeding (takes ~6 min)")
    args = ap.parse_args()

    seed_res = await run_seed()
    log.info(f"Seed result: {seed_res}")

    if args.backfill:
        bf_res = await run_backfill()
        log.info(f"Backfill result: {bf_res}")

    # Print final mapping
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT bm.category, bm.benchmark_name, im.instrument_name AS proxy
            FROM benchmark_master bm
            LEFT JOIN instrument_master im ON bm.proxy_instrument_id = im.instrument_id
            ORDER BY bm.category
            """
        )
        nav_counts = await conn.fetch(
            """
            SELECT im.instrument_name,
                   COUNT(h.nav_date) AS nav_rows,
                   MIN(h.nav_date) AS first_nav, MAX(h.nav_date) AS last_nav
            FROM instrument_master im
            LEFT JOIN mutual_fund_nav_history h USING (instrument_id)
            WHERE im.isin = ANY($1::text[])
            GROUP BY im.instrument_name
            ORDER BY im.instrument_name
            """,
            [t[1] for t in TRACKERS],
        )

    log.info("\n=== Benchmark → Proxy Mapping ===")
    for r in rows:
        log.info(f"  {r['category']:<24} → {r['benchmark_name']:<42} via {r['proxy'] or '—'}")
    log.info("\n=== NAV coverage on new trackers ===")
    for r in nav_counts:
        log.info(f"  {r['instrument_name'][:65]:<65} navs={r['nav_rows']:<5}  "
                 f"{r['first_nav']} → {r['last_nav']}")


if __name__ == "__main__":
    asyncio.run(main())
