"""Bulk-fetch V3 primitives from Groww for a curated catalogue of funds.

For each fund name:
  1. `groww_client.fetch_fund_with_sibling()` → HTML scrape + auto-sibling
     (populates both Regular and Direct expense ratios).
  2. `pg_writer.persist_scrape()` → upsert instrument_master + mutual_fund_metadata
     + holdings + ratios.

Concurrency is capped via `SEMAPHORE_LIMIT` (default 6) to be polite to Groww.
Progress is logged to stdout and to `/tmp/groww_bulk_<timestamp>.log`.

Run:
    cd /app/backend && python -m scripts.bulk_import_groww_primitives
    cd /app/backend && python -m scripts.bulk_import_groww_primitives --category large_cap
    cd /app/backend && python -m scripts.bulk_import_groww_primitives --only "Parag Parikh Flexi Cap"
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import groww_client, pg_client, pg_writer  # noqa: E402
from helpers import secrets as _secrets  # noqa: E402

# Load backend/.env so MONGO_URL/DB_NAME and any env-side fallbacks are present.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass


async def _bootstrap_secrets() -> None:
    """Hydrate secrets from Mongo so pg_client/redis_client can see POSTGRES_URL etc."""
    import os
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        log.warning("MONGO_URL/DB_NAME missing — secrets will come from env only")
        return
    client = AsyncIOMotorClient(mongo_url)
    try:
        await _secrets.hydrate_from_db(client[db_name])
        log.info(f"Secrets hydrated from Mongo (env={_secrets.current_env()}) · "
                 f"POSTGRES_URL configured: {bool(_secrets.get('POSTGRES_URL'))}")
    finally:
        client.close()

log = logging.getLogger("bulk_groww")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

SEMAPHORE_LIMIT = 6

# ── Curated catalogue: (category_key, [scheme names]) ─────────────────────
CATALOGUE: Dict[str, List[str]] = {
    "large_cap": [
        "ICICI Prudential Bluechip Fund",
        "SBI Bluechip Fund",
        "Axis Bluechip Fund",
        "Mirae Asset Large Cap Fund",
        "HDFC Top 100 Fund",
        "Kotak Bluechip Fund",
        "Nippon India Large Cap Fund",
        "Canara Robeco Bluechip Equity Fund",
        "UTI Large Cap Fund",
        "Aditya Birla Sun Life Frontline Equity Fund",
    ],
    "flexi_cap": [
        "Parag Parikh Flexi Cap Fund",
        "UTI Flexi Cap Fund",
        "HDFC Flexi Cap Fund",
        "Kotak Flexi Cap Fund",
        "Franklin India Flexi Cap Fund",
        "Nippon India Multi Cap Fund",
        "SBI Flexicap Fund",
        "ICICI Prudential Flexicap Fund",
        "JM Flexicap Fund",
        "Quant Flexi Cap Fund",
    ],
    "mid_cap": [
        "Edelweiss Mid Cap Fund",
        "ICICI Prudential Midcap Fund",
        "Kotak Emerging Equity Fund",
        "HDFC Mid Cap Opportunities Fund",
        "Nippon India Growth Fund",
        "SBI Magnum Midcap Fund",
        "Axis Midcap Fund",
        "PGIM India Midcap Opportunities Fund",
        "Motilal Oswal Midcap Fund",
        "DSP Midcap Fund",
    ],
    "small_cap": [
        "Nippon India Small Cap Fund",
        "SBI Small Cap Fund",
        "Axis Small Cap Fund",
        "Kotak Small Cap Fund",
        "HDFC Small Cap Fund",
        "ICICI Prudential Smallcap Fund",
        "Quant Small Cap Fund",
        "DSP Small Cap Fund",
        "Canara Robeco Small Cap Fund",
        "Tata Small Cap Fund",
    ],
    "elss": [
        "SBI Long Term Equity Fund",
        "Mirae Asset Tax Saver Fund",
        "Axis Long Term Equity Fund",
        "DSP ELSS Tax Saver Fund",
        "Canara Robeco ELSS Tax Saver",
        "Kotak ELSS Tax Saver Fund",
        "Quant ELSS Tax Saver Fund",
        "Franklin India ELSS Tax Saver Fund",
        "ICICI Prudential ELSS Tax Saver Fund",
        "Bandhan ELSS Tax Saver Fund",
    ],
    "hybrid_aggressive": [
        "ICICI Prudential Equity & Debt Fund",
        "SBI Equity Hybrid Fund",
        "HDFC Hybrid Equity Fund",
        "Axis Aggressive Hybrid Fund",
        "Kotak Equity Hybrid Fund",
        "Mirae Asset Aggressive Hybrid Fund",
        "Canara Robeco Equity Hybrid Fund",
        "Quant Absolute Fund",
        "Edelweiss Aggressive Hybrid Fund",
        "DSP Aggressive Hybrid Fund",
    ],
    "debt_corporate_bond": [
        "ICICI Prudential Corporate Bond Fund",
        "HDFC Corporate Bond Fund",
        "SBI Corporate Bond Fund",
        "Kotak Corporate Bond Fund",
        "Axis Corporate Debt Fund",
        "Nippon India Corporate Bond Fund",
        "Aditya Birla Sun Life Corporate Bond Fund",
        "Bandhan Corporate Bond Fund",
        "UTI Corporate Bond Fund",
        "DSP Corporate Bond Fund",
    ],
    "debt_short_duration": [
        "HDFC Short Term Debt Fund",
        "ICICI Prudential Short Term Fund",
        "Axis Short Duration Fund",
        "SBI Magnum Low Duration Fund",
        "Kotak Bond Short Term Fund",
        "DSP Low Duration Fund",
        "Nippon India Low Duration Fund",
        "UTI Short Duration Fund",
        "Bandhan Low Duration Fund",
        "Aditya Birla Sun Life Short Term Fund",
    ],
    "liquid": [
        "ICICI Prudential Liquid Fund",
        "HDFC Liquid Fund",
        "SBI Liquid Fund",
        "Nippon India Liquid Fund",
        "Axis Liquid Fund",
        "Kotak Liquid Fund",
        "UTI Liquid Cash Plan",
        "Aditya Birla Sun Life Liquid Fund",
        "DSP Liquidity Fund",
        "Bandhan Cash Fund",
    ],
    "index": [
        "UTI Nifty 50 Index Fund",
        "HDFC Index Fund Nifty 50 Plan",
        "ICICI Prudential Nifty 50 Index Fund",
        "SBI Nifty Index Fund",
        "Nippon India Index Fund Nifty 50 Plan",
        "DSP Nifty 50 Index Fund",
        "Motilal Oswal Nifty 50 Index Fund",
        "Navi Nifty 50 Index Fund",
        "Tata Nifty 50 Index Fund",
        "Axis Nifty 100 Index Fund",
    ],
}


async def _process_one(
    sem: asyncio.Semaphore,
    scheme_name: str,
    category: str,
    results: List[Dict],
) -> None:
    async with sem:
        t0 = time.perf_counter()
        entry: Dict = {"category": category, "scheme_name": scheme_name}
        try:
            scrape = await groww_client.fetch_fund_with_sibling(scheme_name)
            if not scrape:
                entry["status"] = "not_found"
                log.warning(f"[{category}] NOT-FOUND  {scheme_name}")
                results.append(entry)
                return

            meta = (scrape.get("metadata") or {})
            v3 = (scrape.get("v3_primitives") or {})

            mf_id = await pg_writer.persist_scrape(scrape)
            sibling = scrape.get("sibling")
            sib_id = None
            if sibling:
                sib_id = await pg_writer.persist_scrape(sibling)

            entry["status"] = "ok" if mf_id else "persist_failed"
            entry["slug"] = scrape.get("slug")
            entry["mf_id"] = str(mf_id) if mf_id else None
            entry["sibling_slug"] = (sibling or {}).get("slug") if sibling else None
            entry["sibling_mf_id"] = str(sib_id) if sib_id else None
            entry["primitives"] = {
                "aum_cr": meta.get("aum_cr"),
                "category": meta.get("category"),
                "fund_age_years": v3.get("fund_age_years"),
                "manager_tenure_years": v3.get("manager_tenure_years"),
                "expense_ratio_direct": meta.get("expense_ratio_direct"),
                "expense_ratio_regular": meta.get("expense_ratio_regular"),
                "turnover_ratio": v3.get("turnover_ratio"),
                "top10_concentration_pct": v3.get("top10_concentration_pct"),
                "rating": meta.get("rating"),
            }
            dt_ms = (time.perf_counter() - t0) * 1000
            pb = []
            if entry["primitives"].get("aum_cr") is not None:
                pb.append(f'AUM ₹{entry["primitives"]["aum_cr"]:,.0f}Cr')
            if entry["primitives"].get("fund_age_years") is not None:
                pb.append(f'age {entry["primitives"]["fund_age_years"]:.1f}y')
            if entry["primitives"].get("manager_tenure_years") is not None:
                pb.append(f'mgr {entry["primitives"]["manager_tenure_years"]:.1f}y')
            if entry["primitives"].get("expense_ratio_direct") is not None:
                pb.append(f'ER-D {entry["primitives"]["expense_ratio_direct"]:.2f}%')
            log.info(f"[{category}] OK ({dt_ms:.0f}ms) {scheme_name} · " + " · ".join(pb)
                     + (f' +sibling' if sib_id else ''))
        except Exception as e:  # noqa: BLE001
            entry["status"] = "error"
            entry["error"] = f"{type(e).__name__}: {e}"
            log.error(f"[{category}] ERROR  {scheme_name} :: {e!r}")
        finally:
            results.append(entry)


async def _run(funds: List[Tuple[str, str]]) -> None:
    await _bootstrap_secrets()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = Path(f"/tmp/groww_bulk_{ts}.json")
    results: List[Dict] = []
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [
        _process_one(sem, scheme, cat, results)
        for cat, scheme in funds
    ]
    log.info(f"Starting bulk fetch: {len(tasks)} funds · concurrency {SEMAPHORE_LIMIT}")
    t0 = time.perf_counter()
    await asyncio.gather(*tasks)
    dt = time.perf_counter() - t0

    # Summary
    ok = sum(1 for r in results if r.get("status") == "ok")
    nf = sum(1 for r in results if r.get("status") == "not_found")
    er = sum(1 for r in results if r.get("status") == "error")
    pf = sum(1 for r in results if r.get("status") == "persist_failed")
    out_json.write_text(json.dumps({
        "started_at": ts,
        "duration_sec": round(dt, 1),
        "counts": {"ok": ok, "not_found": nf, "error": er, "persist_failed": pf,
                   "total": len(results)},
        "results": results,
    }, indent=2, default=str))
    log.info("=" * 70)
    log.info(f"DONE  total={len(results)}  ok={ok}  not_found={nf}  "
             f"error={er}  persist_failed={pf}  elapsed={dt:.1f}s")
    log.info(f"Report → {out_json}")

    # Print not-found + error buckets so user can see which slugs need manual mapping
    if nf:
        log.warning("NOT-FOUND funds (slug resolution failed — need explicit Groww URL):")
        for r in results:
            if r["status"] == "not_found":
                log.warning(f"  · [{r['category']}] {r['scheme_name']}")
    if er:
        log.warning("ERROR funds:")
        for r in results:
            if r["status"] == "error":
                log.warning(f"  · [{r['category']}] {r['scheme_name']} — {r.get('error')}")


def _select_funds(only: str, category: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for cat, names in CATALOGUE.items():
        if category and category != cat:
            continue
        for n in names:
            if only and only.lower() not in n.lower():
                continue
            pairs.append((cat, n))
    return pairs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--category", default="", help="Only fetch one category "
                   f"(one of: {', '.join(CATALOGUE.keys())})")
    p.add_argument("--only", default="", help="Substring-filter scheme names (case-insensitive)")
    args = p.parse_args()

    funds = _select_funds(args.only, args.category)
    if not funds:
        log.error("No funds matched the given filters.")
        return 1

    try:
        asyncio.run(_run(funds))
    finally:
        try:
            asyncio.run(pg_client.close_pool())
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
