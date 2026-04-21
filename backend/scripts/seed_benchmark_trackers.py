"""Seed NIFTY index-tracker funds as benchmark proxies for V3 downside_capture.

Pipeline:
  1. For each tracker, scrape via Groww → populates instrument_master + metadata
  2. Backfill 5y AMFI NAV history for each (ISIN-only matching already in place)
  3. Wire benchmark_master.proxy_instrument_id for every category
  4. (Caller runs analytics sweep to recompute downside_capture)

Chosen trackers (high-AUM, long-history, tight-TE, Direct plans):
  - UTI Nifty 50 Index Fund                           → NIFTY 50 TRI  (Hybrid / Index / misc defaults)
  - UTI Nifty Next 50 Index Fund                      → NIFTY Next 50 TRI
  - HDFC Nifty 100 Index Fund                         → NIFTY 100 TRI (Large Cap)
  - Motilal Oswal Nifty Midcap 150 Index Fund         → NIFTY Midcap 150 TRI (Mid Cap)
  - Motilal Oswal Nifty Smallcap 250 Index Fund       → NIFTY Smallcap 250 TRI (Small Cap)
  - HDFC Nifty 500 Index Fund                         → NIFTY 500 TRI (Flexi / Focused / Multi / Value / ELSS / Contra)

Run: `python -m scripts.seed_benchmark_trackers`
"""
from __future__ import annotations
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import pg_client, groww_client  # noqa: E402
from services.pg_writer import persist_scrape  # noqa: E402

log = logging.getLogger("seed_benchmarks")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# scheme_name → {slug, benchmark_category_matches}
TRACKERS = [
    {
        "scheme": "UTI Nifty 50 Index Fund Direct Growth",
        "slug": "uti-nifty-50-index-fund-direct-growth",
        "covers": ["NIFTY 50 TRI"],
    },
    {
        "scheme": "UTI Nifty Next 50 Index Fund Direct Growth",
        "slug": "uti-nifty-next-50-index-fund-direct-growth",
        "covers": ["NIFTY Next 50 TRI"],
    },
    {
        "scheme": "HDFC Nifty 100 Index Fund Direct Growth",
        "slug": "hdfc-nifty-100-index-fund-direct-growth",
        "covers": ["NIFTY 100 TRI"],
    },
    {
        "scheme": "Motilal Oswal Nifty Midcap 150 Index Fund Direct Growth",
        "slug": "motilal-oswal-nifty-midcap-150-index-fund-direct-growth",
        "covers": ["NIFTY Midcap 150 TRI"],
    },
    {
        "scheme": "Motilal Oswal Nifty Smallcap 250 Index Fund Direct Growth",
        "slug": "motilal-oswal-nifty-smallcap-250-index-fund-direct-growth",
        "covers": ["NIFTY Smallcap 250 TRI"],
    },
    {
        "scheme": "HDFC Nifty 500 Index Fund Direct Growth",
        "slug": "hdfc-nifty-500-index-fund-direct-growth",
        "covers": ["NIFTY 500 TRI", "NIFTY LargeMidcap 250 TRI",
                   "NIFTY 500 Multicap 50:25:25 TRI"],
    },
]


async def _scrape_one(tracker: dict) -> dict:
    """Scrape via Groww, persist to PG, return {scheme, instrument_id, isin}."""
    name = tracker["scheme"]
    try:
        data = await groww_client.fetch_fund_with_sibling(name, explicit_slug=tracker["slug"])
        if not data:
            # Fall back to name-based resolution if slug is stale
            data = await groww_client.fetch_fund_with_sibling(name)
        if not data:
            log.warning(f"SCRAPE FAILED: {name}")
            return {"scheme": name, "ok": False}
        mf_id = await persist_scrape(data)
        meta = data.get("metadata") or {}
        log.info(
            f"Scraped {name!r} → instrument_id={mf_id} isin={meta.get('isin','?')} "
            f"aum={meta.get('aum_cr','?')}Cr"
        )
        return {"scheme": name, "ok": True, "instrument_id": mf_id}
    except Exception as e:  # noqa: BLE001
        log.error(f"SCRAPE ERROR for {name}: {e}")
        return {"scheme": name, "ok": False, "error": str(e)}


async def _wire_benchmark_proxies(scraped: list) -> dict:
    """For every (tracker, covered-benchmark-name), UPDATE benchmark_master
    rows whose benchmark_name matches. Returns {benchmark_name → fund_name}."""
    pool = await pg_client.get_pool()
    if pool is None:
        log.error("No PG pool — aborting proxy wiring")
        return {}
    wired: dict = {}
    async with pool.acquire() as conn:
        for entry in scraped:
            if not entry.get("ok"):
                continue
            iid = entry["instrument_id"]
            # Re-lookup covers from TRACKERS since `scraped` doesn't carry it
            tracker = next((t for t in TRACKERS if t["scheme"] == entry["scheme"]), None)
            if not tracker:
                continue
            for bm_name in tracker["covers"]:
                rows = await conn.execute(
                    """
                    UPDATE benchmark_master
                    SET proxy_instrument_id = $1::uuid
                    WHERE benchmark_name = $2
                    """,
                    iid, bm_name,
                )
                # `rows` is a status string like "UPDATE 3"
                count = int(rows.split()[-1]) if rows.startswith("UPDATE") else 0
                if count:
                    wired[bm_name] = (entry["scheme"], count)
                    log.info(f"  proxy wired: {bm_name} → {entry['scheme']} ({count} categories)")
    return wired


async def main():
    # 1. Scrape all trackers (parallel, bounded 3 at a time — polite to Groww)
    sem = asyncio.Semaphore(3)
    async def work(t):
        async with sem:
            return await _scrape_one(t)
    scraped = await asyncio.gather(*[work(t) for t in TRACKERS])

    ok_count = sum(1 for s in scraped if s.get("ok"))
    log.info(f"Scraped {ok_count}/{len(TRACKERS)} trackers successfully")

    # 2. Wire benchmark mappings
    wired = await _wire_benchmark_proxies(scraped)
    log.info(f"Wired {len(wired)} benchmark→proxy mappings")

    # 3. Print a final summary
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT bm.category, bm.benchmark_name, im.instrument_name AS proxy_fund
            FROM benchmark_master bm
            LEFT JOIN instrument_master im ON bm.proxy_instrument_id = im.instrument_id
            ORDER BY bm.category
            """
        )
    log.info("=== Benchmark → Proxy Mapping ===")
    for r in rows:
        proxy = r["proxy_fund"] or "—"
        log.info(f"  {r['category']:<18} → {r['benchmark_name']:<40} via {proxy}")

    log.info(
        "\nNext step: trigger analytics_sweep so downside_capture recomputes "
        "for every fund whose benchmark now has a proxy."
    )


if __name__ == "__main__":
    asyncio.run(main())
