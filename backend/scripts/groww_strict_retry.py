"""Strict Groww resolver + bulk retry.

For each fund name, try in order:
  1. Alias table (known SEBI renames)
  2. Groww search API — but REQUIRE the returned title to share the same AMC prefix
     (first 2-3 tokens) with the requested name. Reject otherwise.
  3. Report as "unresolved" with the top-3 candidates so user can choose.

Writes results to /tmp/groww_strict_retry_<ts>.json and persists successful
scrapes to Postgres via pg_writer.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from services import groww_client, pg_client, pg_writer  # noqa: E402
from helpers import secrets as _secrets  # noqa: E402

log = logging.getLogger("groww_retry")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SEMAPHORE = 3

# ── Known SEBI renames / Groww slug overrides ────────────────────────────
# Key = original user-provided name (case-insensitive), Value = explicit slug
# OR corrected search term Groww will resolve.
ALIASES: Dict[str, str] = {
    # Only keep proven-good explicit slugs discovered via manual probing.
    # (Empty for now — strict search handles the rest.)
}


def amc_prefix(name: str) -> str:
    """Extract the AMC name (first 2–3 tokens) from a scheme name."""
    toks = re.findall(r"[A-Za-z]+", name.lower())
    # Known multi-word AMCs
    joined = " ".join(toks)
    for amc in ["aditya birla sun life", "canara robeco", "parag parikh",
                "icici prudential", "hdfc", "sbi", "axis", "kotak",
                "nippon india", "mirae asset", "dsp", "uti", "tata",
                "motilal oswal", "franklin india", "edelweiss", "bandhan",
                "pgim india", "quant", "jm", "navi"]:
        if joined.startswith(amc):
            return amc
    return toks[0] if toks else ""


async def _strict_search(scheme_name: str) -> Tuple[Optional[str], List[Dict]]:
    """Search Groww; pick only candidates where title starts with same AMC.

    Returns (best_slug, top3_candidates) — top3 always returned for debugging.
    """
    amc = amc_prefix(scheme_name)
    url = "https://groww.in/v1/api/search/v3/query/global/st_query"
    params = {"q": scheme_name, "from": "0", "size": "10"}
    headers = {"User-Agent": groww_client.USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning(f"search failed for {scheme_name!r}: {e}")
        return None, []

    hits = [h for h in (data.get("data") or {}).get("content") or []
            if h.get("sub_entity_type") == "Scheme" and h.get("search_id")]
    top3 = [{"title": h.get("title"), "slug": h.get("search_id")} for h in hits[:3]]

    # Tokenise requested name
    req_tokens = set(re.findall(r"[a-z0-9]+", scheme_name.lower()))
    req_tokens -= {"fund", "plan", "growth", "direct", "regular"}

    best_slug, best_score = None, 0.0
    for h in hits:
        title = (h.get("title") or "").lower()
        if amc and not title.startswith(amc):
            continue
        # Token overlap on non-AMC portion
        title_tokens = set(re.findall(r"[a-z0-9]+", title))
        if not req_tokens:
            continue
        score = len(req_tokens & title_tokens) / len(req_tokens)
        if score > best_score:
            best_score = score
            best_slug = h.get("search_id")

    # Require decent overlap
    if best_slug and best_score >= 0.5:
        return best_slug, top3
    return None, top3


async def _resolve(scheme_name: str) -> Tuple[Optional[str], str, List[Dict]]:
    """Return (slug, reason, top3_candidates). reason ∈ {'alias','strict','unresolved'}."""
    key = scheme_name.lower().strip()
    if key in ALIASES:
        return ALIASES[key], "alias", []
    slug, top3 = await _strict_search(scheme_name)
    if slug:
        return slug, "strict", top3
    return None, "unresolved", top3


async def _process_one(sem, entry, results):
    async with sem:
        scheme = entry["scheme_name"]
        cat = entry["category"]
        t0 = time.perf_counter()
        out = {"category": cat, "scheme_name": scheme}
        try:
            slug, reason, top3 = await _resolve(scheme)
            out["resolution"] = reason
            out["top3_candidates"] = top3
            if not slug:
                out["status"] = "unresolved"
                log.warning(f"[{cat}] UNRESOLVED {scheme} · top3: "
                            + ", ".join(f'{c["title"]}→{c["slug"]}' for c in top3))
                results.append(out)
                return

            # Fetch with explicit slug → no search fallback
            scrape = await groww_client.fetch_fund_with_sibling(scheme, explicit_slug=slug)
            if not scrape:
                out["status"] = "fetch_failed"
                out["tried_slug"] = slug
                log.warning(f"[{cat}] FETCH-FAILED {scheme} · slug={slug}")
                results.append(out)
                return

            # Verify the *returned* scheme_name matches AMC to be safe
            returned = (scrape.get("scheme_name") or "").lower()
            amc = amc_prefix(scheme)
            if amc and amc not in returned:
                out["status"] = "amc_mismatch"
                out["tried_slug"] = slug
                out["returned_scheme_name"] = scrape.get("scheme_name")
                log.warning(f"[{cat}] AMC-MISMATCH {scheme} → returned {scrape.get('scheme_name')}")
                results.append(out)
                return

            mf_id = await pg_writer.persist_scrape(scrape)
            sibling = scrape.get("sibling")
            sib_id = await pg_writer.persist_scrape(sibling) if sibling else None

            meta = scrape.get("metadata") or {}
            v3 = scrape.get("v3_primitives") or {}
            out.update({
                "status": "ok",
                "slug": scrape.get("slug"),
                "sibling_slug": (sibling or {}).get("slug") if sibling else None,
                "mf_id": str(mf_id) if mf_id else None,
                "sibling_mf_id": str(sib_id) if sib_id else None,
                "primitives": {
                    "aum_cr": meta.get("aum_cr"),
                    "category": meta.get("category"),
                    "fund_age_years": v3.get("fund_age_years"),
                    "manager_tenure_years": v3.get("manager_tenure_years"),
                    "expense_ratio_direct": meta.get("expense_ratio_direct"),
                    "expense_ratio_regular": meta.get("expense_ratio_regular"),
                    "top10_concentration_pct": v3.get("top10_concentration_pct"),
                    "turnover_ratio": v3.get("turnover_ratio"),
                },
            })
            dt = (time.perf_counter() - t0) * 1000
            pb = []
            if out["primitives"].get("aum_cr") is not None:
                pb.append(f'AUM ₹{out["primitives"]["aum_cr"]:,.0f}Cr')
            if out["primitives"].get("fund_age_years") is not None:
                pb.append(f'age {out["primitives"]["fund_age_years"]:.1f}y')
            if out["primitives"].get("expense_ratio_direct") is not None:
                pb.append(f'ER-D {out["primitives"]["expense_ratio_direct"]:.2f}%')
            log.info(f"[{cat}] OK ({dt:.0f}ms · {reason}) {scheme} → {scrape.get('scheme_name')} · "
                     + " · ".join(pb) + (" +sibling" if sib_id else ""))
        except Exception as e:  # noqa: BLE001
            out["status"] = "error"
            out["error"] = f"{type(e).__name__}: {e}"
            log.error(f"[{cat}] ERROR {scheme} :: {e!r}")
        finally:
            results.append(out)


async def main(retry_list_path: str) -> None:
    # Hydrate secrets
    from motor.motor_asyncio import AsyncIOMotorClient
    import os
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    try:
        await _secrets.hydrate_from_db(mc[os.environ["DB_NAME"]])
    finally:
        mc.close()
    log.info(f"Secrets hydrated · env={_secrets.current_env()} · "
             f"POSTGRES_URL configured: {bool(_secrets.get('POSTGRES_URL'))}")

    retry_list = json.load(open(retry_list_path))
    log.info(f"Retry list: {len(retry_list)} funds · concurrency {SEMAPHORE}")

    sem = asyncio.Semaphore(SEMAPHORE)
    results: List[Dict] = []
    t0 = time.perf_counter()
    await asyncio.gather(*[_process_one(sem, e, results) for e in retry_list])
    dt = time.perf_counter() - t0

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = f"/tmp/groww_strict_retry_{ts}.json"
    with open(out_path, "w") as fh:
        json.dump({"elapsed_sec": round(dt, 1), "results": results}, fh, indent=2, default=str)

    ok = sum(1 for r in results if r.get("status") == "ok")
    ur = sum(1 for r in results if r.get("status") == "unresolved")
    am = sum(1 for r in results if r.get("status") == "amc_mismatch")
    ff = sum(1 for r in results if r.get("status") == "fetch_failed")
    er = sum(1 for r in results if r.get("status") == "error")
    log.info("=" * 70)
    log.info(f"DONE  total={len(results)}  ok={ok}  unresolved={ur}  "
             f"amc_mismatch={am}  fetch_failed={ff}  error={er}  · {dt:.1f}s")
    log.info(f"Report → {out_path}")

    for r in results:
        if r.get("status") not in ("ok",):
            log.warning(f"  · [{r['category']}] {r['scheme_name']} → {r['status']}"
                        + (f' (top3: {r.get("top3_candidates")})' if r.get("top3_candidates") else ''))

    await pg_client.close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--retry-list", default="/tmp/groww_retry_list.json")
    args = p.parse_args()
    asyncio.run(main(args.retry_list))
