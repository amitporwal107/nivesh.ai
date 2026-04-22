"""Tickertape fallback import for funds that Groww couldn't resolve.

Takes a hardcoded mapping of { fund_name: tickertape_url } (derived from
manual/search-based URL discovery) and scrapes Tickertape HTML via
`services.tickertape_client.fetch_fund_by_url()`, persisting the V3
primitives to Neon Postgres via `pg_writer.persist_scrape()`.

Run: cd /app/backend && python -m scripts.tickertape_fallback_import
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from services import tickertape_client, pg_client, pg_writer  # noqa: E402
from helpers import secrets as _secrets  # noqa: E402

log = logging.getLogger("tt_fallback")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Curated Tickertape URLs for funds that Groww search couldn't resolve or
# returned wrong results. Each tuple: (category, requested_name, tt_url).
# URLs verified via web search + manual check.
FALLBACK_URLS = [
    # Large Cap — renamed by SEBI
    ("large_cap", "SBI Bluechip Fund",
     "https://www.tickertape.in/mutualfunds/sbi-large-cap-fund-M_SBLH"),
    ("large_cap", "Axis Bluechip Fund",
     "https://www.tickertape.in/mutualfunds/axis-large-cap-fund-M_AXLB"),
    ("large_cap", "Canara Robeco Bluechip Equity Fund",
     "https://www.tickertape.in/mutualfunds/canara-rob-large-cap-fund-M_CANY"),
    ("large_cap", "Aditya Birla Sun Life Frontline Equity Fund",
     "https://www.tickertape.in/mutualfunds/aditya-birla-sl-large-cap-fund-M_ADTOR"),
    # Small Cap
    ("small_cap", "ICICI Prudential Smallcap Fund",
     "https://www.tickertape.in/mutualfunds/icici-pru-smallcap-fund-M_ICCDS"),
    # ELSS — renamed by SEBI
    ("elss", "Axis Long Term Equity Fund",
     "https://www.tickertape.in/mutualfunds/axis-elss-tax-saver-fund-M_AXLO"),
    ("elss", "SBI Long Term Equity Fund",
     "https://www.tickertape.in/mutualfunds/sbi-elss-tax-saver-fund-M_SBLO"),
]


async def _process_one(sem, entry, results):
    cat, name, url = entry
    async with sem:
        t0 = time.perf_counter()
        out = {"category": cat, "scheme_name": name, "url": url}
        try:
            scrape = await tickertape_client.fetch_fund_by_url(url)
            if not scrape:
                out["status"] = "fetch_failed"
                log.warning(f"[{cat}] FAIL {name} → {url}")
                results.append(out)
                return
            mf_id = await pg_writer.persist_scrape(scrape)
            meta = scrape["metadata"]
            v3 = scrape["v3_primitives"]
            out.update({
                "status": "ok" if mf_id else "persist_failed",
                "mf_id": str(mf_id) if mf_id else None,
                "returned_name": scrape["scheme_name"],
                "aum_cr": meta.get("aum_cr"),
                "fund_age_years": v3.get("fund_age_years"),
                "expense_ratio_direct": meta.get("expense_ratio_direct"),
                "manager_tenure_years": meta.get("manager_tenure_years"),
                "top10_concentration_pct": meta.get("top10_concentration_pct"),
            })
            dt = (time.perf_counter() - t0) * 1000
            log.info(f"[{cat}] OK ({dt:.0f}ms) {name} → {scrape['scheme_name']} · "
                     f"AUM ₹{(meta.get('aum_cr') or 0):,.0f}Cr · "
                     f"age {(v3.get('fund_age_years') or 0):.1f}y · "
                     f"ER-D {(meta.get('expense_ratio_direct') or 0):.2f}% · "
                     f"mgr {(meta.get('manager_tenure_years') or 0):.1f}y")
        except Exception as e:  # noqa: BLE001
            out["status"] = "error"
            out["error"] = f"{type(e).__name__}: {e}"
            log.error(f"[{cat}] ERROR {name} :: {e!r}")
        finally:
            results.append(out)


async def main() -> None:
    # Hydrate secrets
    from motor.motor_asyncio import AsyncIOMotorClient
    import os
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await _secrets.hydrate_from_db(mc[os.environ["DB_NAME"]])
    finally:
        mc.close()
    log.info(f"Secrets hydrated · POSTGRES_URL configured: {bool(_secrets.get('POSTGRES_URL'))}")

    sem = asyncio.Semaphore(1)
    results = []
    t0 = time.perf_counter()
    await asyncio.gather(*[_process_one(sem, e, results) for e in FALLBACK_URLS])
    dt = time.perf_counter() - t0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = f"/tmp/tickertape_fallback_{ts}.json"
    with open(out_path, "w") as fh:
        json.dump({"elapsed_sec": round(dt, 1), "results": results}, fh, indent=2, default=str)

    ok = sum(1 for r in results if r["status"] == "ok")
    log.info("=" * 70)
    log.info(f"DONE  ok={ok}/{len(results)}  · {dt:.1f}s")
    log.info(f"Report → {out_path}")
    for r in results:
        if r["status"] != "ok":
            log.warning(f"  · [{r['category']}] {r['scheme_name']} → {r['status']} {r.get('error','')}")

    # Trigger analytics sweep + V3 rescore so the new funds get scored immediately
    log.info("Running NAV analytics sweep + V3 rescore for freshly-imported funds...")
    from services.nav_analytics_sweep import run_analytics_sweep, run_v3_rescore
    s1 = await run_analytics_sweep()
    s2 = await run_v3_rescore()
    log.info(f"analytics_sweep: {s1}")
    log.info(f"v3_rescore:      {s2}")

    await pg_client.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
