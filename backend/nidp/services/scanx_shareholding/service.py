"""Quarterly shareholding history per stock from ScanX company pages.

Fills the hole in nidp.shareholding_pattern, where 1,316 of 2,137 symbols carry a single quarter
and therefore cannot be differenced at all. The company page gives ~24 quarters per stock of
Promoter / FII / DII / Public / Government / Others — the only source found that reports DII.

Three things this module is careful about, each required by migration 180:

  * the YEAR label is a REPORTING PERIOD, never a publication date, so nothing is derived from it
    and publication_provenance stays 'unknown';
  * FII is not comparable across the whole series — it was reported inside Others until a
    reclassification whose quarter differs per stock — so the break is DETECTED and flagged
    rather than assumed or smoothed;
  * the parser version is written to every row, so a field added later is never assumed present
    on rows written earlier.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Optional

import httpx

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

SERVICE_NAME = "scanx_shareholding"
INGEST_VERSION = "scanx-sh-v1"
BASE = "https://scanx.trade/company"
POLITE_GAP_S = 1.2

# A reclassification shows as FII collapsing to near zero while Others absorbs the same magnitude
# in the SAME quarter. Both legs are required: a stock whose FII genuinely fell would not show a
# matching jump in Others.
_BREAK_FII_DROP_PP = 10.0
_BREAK_OTHERS_JUMP_PP = 10.0

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Encoding": "identity",
}
_NG_STATE_RE = re.compile(r'<script id="ng-state" type="application/json">(.*?)</script>', re.S)


def _find_shareholding(state: Any) -> Optional[dict]:
    if isinstance(state, dict):
        if {"PROMOTER", "FII", "DII", "YEAR"} <= set(state.keys()):
            return state
        for v in state.values():
            got = _find_shareholding(v)
            if got:
                return got
    elif isinstance(state, list):
        for v in state:
            got = _find_shareholding(v)
            if got:
                return got
    return None


def _floats(raw: Any) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for p in str(raw or "").split("|"):
        p = p.strip()
        try:
            out.append(float(p))
        except ValueError:
            out.append(None)
    return out


def detect_break_index(fii: list[Optional[float]], others: list[Optional[float]]) -> Optional[int]:
    """Index from which rows are on the OLD basis (series is newest-first), or None.

    Walks newest to oldest looking for the step where FII falls away and Others absorbs it.
    """
    for i in range(len(fii) - 1):
        a, b = fii[i], fii[i + 1]
        oa, ob = (others[i] if i < len(others) else None,
                  others[i + 1] if i + 1 < len(others) else None)
        if None in (a, b, oa, ob):
            continue
        if (a - b) >= _BREAK_FII_DROP_PP and (ob - oa) >= _BREAK_OTHERS_JUMP_PP:
            return i + 1
    return None


def parse_shareholding(html: str, slug: str) -> list[dict]:
    m = _NG_STATE_RE.search(html)
    if not m:
        return []
    try:
        state = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    node = _find_shareholding(state)
    if not node:
        return []

    years = [y.strip() for y in str(node.get("YEAR") or "").split("|")]
    fii = _floats(node.get("FII"))
    others = _floats(node.get("OTHERS"))
    promoter = _floats(node.get("PROMOTER"))
    dii = _floats(node.get("DII"))
    public = _floats(node.get("PUBLIC"))
    govt = _floats(node.get("GOVERNMENT"))
    holders = [h.strip() for h in str(node.get("NO_OF_SHARE_HOLDERS") or "").split("|")]

    brk = detect_break_index(fii, others)
    if brk is not None:
        logger.info("%s[%s]: FII/Others reclassification detected at index %d (period %s)",
                    SERVICE_NAME, slug, brk, years[brk] if brk < len(years) else "?")

    def at(xs: list, i: int):
        return xs[i] if i < len(xs) else None

    rows: list[dict] = []
    for i, y in enumerate(years):
        if not re.fullmatch(r"\d{6}", y):
            continue
        try:
            period = date(int(y[:4]), int(y[4:6]), 1)
        except ValueError:
            continue
        try:
            nh = int(float(at(holders, i))) if at(holders, i) not in (None, "") else None
        except (TypeError, ValueError):
            nh = None
        rows.append({
            "company_slug": slug, "period": period,
            "promoter_pct": at(promoter, i), "fii_pct": at(fii, i), "dii_pct": at(dii, i),
            "public_pct": at(public, i), "government_pct": at(govt, i),
            "others_pct": at(others, i), "no_of_shareholders": nh,
            "fii_in_others": (brk is not None and i >= brk),
        })
    return rows


_UPSERT = """
INSERT INTO nidp.scanx_shareholding
    (company_slug, period, symbol, promoter_pct, fii_pct, dii_pct, public_pct, government_pct,
     others_pct, no_of_shareholders, fii_in_others, ingest_version, slug_source, source_run_id)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
ON CONFLICT (company_slug, period) DO UPDATE SET
    symbol = coalesce(EXCLUDED.symbol, nidp.scanx_shareholding.symbol),
    promoter_pct = EXCLUDED.promoter_pct, fii_pct = EXCLUDED.fii_pct, dii_pct = EXCLUDED.dii_pct,
    public_pct = EXCLUDED.public_pct, government_pct = EXCLUDED.government_pct,
    others_pct = EXCLUDED.others_pct, no_of_shareholders = EXCLUDED.no_of_shareholders,
    fii_in_others = EXCLUDED.fii_in_others, ingest_version = EXCLUDED.ingest_version,
    slug_source = EXCLUDED.slug_source, retrieved_at = now(),
    source_run_id = EXCLUDED.source_run_id
"""


def derive_slug(name: str) -> list[str]:
    """Ordered candidate slugs for a company name.

    ScanX slugs carry the registered suffix even where the display name drops it — "3M India" is
    served at /company/3m-india-ltd, "HDFC Bank" at /company/hdfc-bank-ltd. A single derived guess
    therefore 404s for most names (measured: 8 of 8), so candidates are TRIED IN ORDER at fetch
    time rather than chosen upfront. Harvested slugs skip this entirely and are always preferred.
    """
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    n = re.sub(r"\s+", " ", n).strip()
    if not n:
        return []
    full = n.replace(" ", "-")
    cands = [full]
    bare = re.sub(r"-(ltd|limited)$", "", full)
    if bare != full:
        cands.append(bare)
    else:
        cands += [f"{full}-ltd", f"{full}-limited"]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def _targets(limit: Optional[int]) -> list[tuple[str, str, str]]:
    """(slug, symbol, slug_source) — harvested slugs preferred, derived only as a fallback."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, company_slug, security_name
              FROM nidp.scanx_mf_holdings
             WHERE symbol IS NOT NULL AND symbol <> '' AND asset_class = 'Equity'
             ORDER BY symbol, company_slug NULLS LAST
            """)
        done = {r["company_slug"] for r in await conn.fetch(
            "SELECT DISTINCT company_slug FROM nidp.scanx_shareholding "
            "WHERE retrieved_at > now() - interval '6 days'")}

    out: list[tuple[str, str, str]] = []
    for r in rows:
        if r["company_slug"]:
            if r["company_slug"] not in done:
                out.append((r["company_slug"], r["symbol"], "harvested"))
            continue
        cands = [c for c in derive_slug(r["security_name"] or "") if c not in done]
        if cands:
            out.append(("|".join(cands), r["symbol"], "derived"))
    logger.info("%s: %d target(s); %d already fetched within 6 days",
                SERVICE_NAME, len(out), len(done))
    return out[:limit] if limit else out


async def run(*, limit: Optional[int] = None) -> dict:
    bind_context(service=SERVICE_NAME)
    summary = {"attempted": 0, "with_rows": 0, "rows_written": 0, "breaks_detected": 0,
               "not_found": 0, "errors": 0, "ingest_version": INGEST_VERSION}
    targets = await _targets(limit)
    if not targets:
        return summary

    pool = await get_pool()
    async with httpx.AsyncClient(timeout=90, follow_redirects=True, headers=_HEADERS) as http:
        async with JobRun(ingester=SERVICE_NAME, target_date=date.today()) as job:
            bind_context(run_id=str(job.run_id))
            for i, (slug, symbol, slug_source) in enumerate(targets, 1):
                # A derived target carries its ordered candidates; a harvested one has exactly
                # one. Try each until a page answers, so a wrong suffix guess costs a request
                # rather than the whole stock.
                candidates = slug.split("|")
                resolved, html = None, None
                try:
                    for cand in candidates:
                        r = await http.get(f"{BASE}/{cand}")
                        if r.status_code == 200:
                            resolved, html = cand, r.text
                            break
                        if r.status_code != 404:
                            summary["errors"] += 1
                            break
                        if cand != candidates[-1]:
                            await asyncio.sleep(POLITE_GAP_S)
                    if resolved is None:
                        summary["not_found"] += 1
                        continue
                    slug = resolved
                    rows = parse_shareholding(html, slug)
                except Exception as e:                                  # noqa: BLE001
                    summary["errors"] += 1
                    logger.info("%s[%s]: %s: %s", SERVICE_NAME, slug, type(e).__name__, str(e)[:110])
                    continue
                summary["attempted"] += 1
                if rows:
                    if any(x["fii_in_others"] for x in rows):
                        summary["breaks_detected"] += 1
                    args = [(d["company_slug"], d["period"], symbol, d["promoter_pct"],
                             d["fii_pct"], d["dii_pct"], d["public_pct"], d["government_pct"],
                             d["others_pct"], d["no_of_shareholders"], d["fii_in_others"],
                             INGEST_VERSION, slug_source, job.run_id) for d in rows]
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            await conn.executemany(_UPSERT, args, timeout=120)
                    summary["with_rows"] += 1
                    summary["rows_written"] += len(args)
                if i % 25 == 0:
                    logger.info("%s: %d/%d, %d rows, %d breaks", SERVICE_NAME, i, len(targets),
                                summary["rows_written"], summary["breaks_detected"])
                if i < len(targets):
                    await asyncio.sleep(POLITE_GAP_S)

            job.rows_fetched = summary["rows_written"]
            job.rows_inserted = summary["rows_written"]
            job.metadata.update(summary)
            await job.finalize("OK" if summary["rows_written"] else "FAILED",
                               error_message=None if summary["rows_written"] else "no rows")
    logger.info("%s done: %s", SERVICE_NAME, summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest quarterly shareholding history from ScanX")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    async def _go() -> None:
        try:
            await run(limit=args.limit)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
