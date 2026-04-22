#!/usr/bin/env python3
"""Bulk-import Moneycontrol primitives for Debt mutual funds.

For every fund in `mutual_fund_metadata` classified as `debt` (via v3_weights
classifier), resolve the Moneycontrol imid via autosuggest, fetch the fund
page's `__NEXT_DATA__` JSON, and persist:
  - credit_quality_score (0-10, from "High/Medium/Low Quality")
  - duration_risk_score  (0-10, from "Limited/Moderate/Extensive Sensitivity")
  - ytm, modified_duration (when MC exposes them)
  - investment_style, moneycontrol_imid
  - + metadata fallbacks (aum, expense_ratio, manager_name, launch_date ...)

After persistence, triggers a V3 rescore so the category-aware Debt model
produces updated Quality/Health scores.

Usage:
    python -m scripts.bulk_import_moneycontrol_debt [--limit N] [--dry-run]
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

log = logging.getLogger("mc_debt_import")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def _hydrate_secrets() -> None:
    from motor.motor_asyncio import AsyncIOMotorClient
    from helpers import secrets as _s
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await _s.hydrate_from_db(mc[os.environ["DB_NAME"]])
    finally:
        mc.close()
    pg_url = _s.get("POSTGRES_URL")
    if not pg_url:
        raise RuntimeError("POSTGRES_URL missing from hydrated secrets")
    os.environ["POSTGRES_URL"] = pg_url


async def _debt_funds(limit: int = 0) -> list:
    from services import pg_client, v3_weights
    pool = await pg_client.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT im.instrument_id, im.instrument_name AS scheme_name, im.isin,
                   mfm.category, mfm.sub_category, mfm.moneycontrol_imid
            FROM mutual_fund_metadata mfm
            JOIN instrument_master im ON im.instrument_id = mfm.instrument_id
            WHERE im.is_active = TRUE
            ORDER BY im.instrument_name
            """
        )
    debt = [
        dict(r) for r in rows
        if v3_weights.classify_fund_category({
            "category": r["category"],
            "sub_category": r["sub_category"],
            "scheme_name": r["scheme_name"],
        }) == "debt"
    ]
    return debt[:limit] if limit else debt


async def _process_one(fund: dict, dry_run: bool) -> dict:
    """Resolve → fetch → persist a single debt fund. Returns a result dict."""
    from services import moneycontrol_client, pg_writer
    scheme = fund["scheme_name"]
    imid = fund.get("moneycontrol_imid")
    status: dict = {"scheme_name": scheme, "imid": imid, "outcome": "pending"}

    try:
        payload = None
        if imid:
            # We already know the imid from a previous run — but we don't know
            # the slug, so go through search to get the canonical URL.
            hit = await moneycontrol_client.search_fund(scheme)
            url = hit["url"] if hit and hit["imid"] == imid else None
            if url:
                payload = await moneycontrol_client.fetch_by_url(url)

        if payload is None:
            hit = await moneycontrol_client.search_fund(scheme)
            if not hit:
                status["outcome"] = "imid_not_found"
                return status
            status["imid"] = hit["imid"]
            payload = await moneycontrol_client.fetch_by_url(hit["url"])

        if not payload:
            status["outcome"] = "fetch_failed"
            return status

        status["credit_quality_score"] = payload.get("credit_quality_score")
        status["duration_risk_score"] = payload.get("duration_risk_score")
        status["investment_style"] = payload.get("investment_style")

        # Fill ISIN from instrument_master so persist can match existing row
        if fund.get("isin") and not payload.get("isin"):
            payload["isin"] = fund["isin"]
        # Always force scheme_name to the one we know is in PG, so the name-
        # match fallback works when ISIN doesn't exist.
        payload["scheme_name"] = scheme

        if dry_run:
            status["outcome"] = "dry_run"
            return status

        mf_id = await pg_writer.persist_moneycontrol_scrape(payload)
        status["outcome"] = "persisted" if mf_id else "persist_skipped"
    except Exception as e:  # noqa: BLE001
        status["outcome"] = "error"
        status["error"] = str(e)[:200]
    return status


async def _rescore_all() -> int:
    """Invalidate the Redis V3 score cache + trigger a baseline rescore."""
    try:
        from services import v3_score_cache
        from services.nav_analytics_sweep import run_v3_rescore
        n_invalidated = await v3_score_cache.invalidate_all()
        log.info(f"V3 cache invalidated: {n_invalidated} keys")
        res = await run_v3_rescore()
        log.info(f"V3 rescore complete: {res}")
        return res.get("rescored", 0) if isinstance(res, dict) else 0
    except Exception as e:  # noqa: BLE001
        log.warning(f"V3 rescore failed (non-fatal): {e}")
        return 0


async def main(limit: int, dry_run: bool, concurrency: int) -> None:
    await _hydrate_secrets()
    funds = await _debt_funds(limit=limit)
    log.info(f"Debt funds to process: {len(funds)}")

    sem = asyncio.Semaphore(concurrency)

    async def _guarded(f):
        async with sem:
            return await _process_one(f, dry_run)

    t0 = time.perf_counter()
    results = await asyncio.gather(*[_guarded(f) for f in funds])
    elapsed = time.perf_counter() - t0

    # Tally
    tally: dict = {}
    for r in results:
        tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1
    log.info(f"Outcome summary ({elapsed:.1f}s): {tally}")

    # Print a compact table for operator visibility
    print("\n─── Moneycontrol debt import report ───")
    for r in results[:50]:
        print(
            f"  {r['outcome']:15s} "
            f"cq={str(r.get('credit_quality_score')):<4} "
            f"dr={str(r.get('duration_risk_score')):<4} "
            f"style={r.get('investment_style') or '-':<40} "
            f"{r['scheme_name'][:60]}"
        )
    if len(results) > 50:
        print(f"  ... {len(results) - 50} more")

    if not dry_run:
        await _rescore_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max funds to process (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape + parse only, skip writes")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.dry_run, args.concurrency))
