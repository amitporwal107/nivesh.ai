"""Scheme-level MF holdings from ScanX insight pages -> nidp.scanx_mf_holdings.

The first source that is both scheme-level AND industry-wide: its directory lists 52 AMCs and
1,434 schemes, including HDFC and Mirae, whose own sites we cannot reach. Each scheme page
server-renders a 12-month series per holding, so ONE request covers the whole backfill window for
that scheme.

Shape of a page: an Angular `<script id="ng-state">` blob whose data node holds one list per asset
class ("Equity", "Arbitrage", "Certificate of Deposit", ...). Each row is a positional array; the
fields used are read by INDEX but validated by length first, and the asset class is taken from the
dict KEY rather than a field, because the per-row type field is inconsistent between equity
(index 12 = "EQUITY") and debt (index 13 = "Certificate of Deposit").

Deliberately polite: this is a public page, not an API, and the cadence is weekly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Iterable, Optional

import httpx

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

SERVICE_NAME = "scanx_mf_holdings"
BASE = "https://scanx.trade/insight/mf-holdings"
POLITE_GAP_S = 1.2
REFRESH_AFTER_DAYS = 6          # weekly cadence; a scheme fetched inside this window is skipped

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}

_NG_STATE_RE = re.compile(
    r'<script id="ng-state" type="application/json">(.*?)</script>', re.S)

# Positional fields in a holding row. Validated against both an equity and a debt row.
_F_SYMBOL, _F_NAME, _F_ISIN = 0, 1, 14
_F_SHARES, _F_WEIGHT, _F_MONTHS = 15, 16, 17
_F_SECTOR, _F_INDUSTRY = 18, 19
_MIN_ROW_LEN = 20


def _ng_state(html: str) -> Optional[dict]:
    m = _NG_STATE_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_directory(html: str) -> list[dict]:
    """[{amc, amc_id, scheme:[{plan_id, name, seo}]}] from the index page."""
    state = _ng_state(html)
    if not state:
        return []
    found: list[dict] = []

    def walk(o: Any) -> None:
        if found:
            return
        if isinstance(o, dict):
            data = o.get("data")
            if (isinstance(data, list) and data and isinstance(data[0], dict)
                    and "amc" in data[0] and "scheme" in data[0]):
                found.extend(data)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(state)
    return found


def parse_holdings(html: str, slug: str) -> list[dict]:
    """Flatten every asset class into (month, isin) rows."""
    state = _ng_state(html)
    if not state:
        return []

    buckets: dict[str, list] = {}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            data = o.get("data")
            if isinstance(data, dict):
                for k, v in data.items():
                    if (isinstance(v, list) and v and isinstance(v[0], list)
                            and len(v[0]) >= _MIN_ROW_LEN):
                        buckets.setdefault(k, []).extend(v)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(state)

    out: list[dict] = []
    for asset_class, rows in buckets.items():
        for r in rows:
            if len(r) < _MIN_ROW_LEN:
                continue
            isin = str(r[_F_ISIN] or "").strip()
            if not re.fullmatch(r"IN[EF][A-Z0-9]{9}", isin):
                continue
            months = str(r[_F_MONTHS] or "").split("|")
            shares = str(r[_F_SHARES] or "").split("|")
            weights = str(r[_F_WEIGHT] or "").split("|")
            if not months or len(months) != len(shares):
                continue
            for i, mon in enumerate(months):
                mon = mon.strip()
                if not re.fullmatch(r"\d{4}-\d{2}", mon):
                    continue
                try:
                    qty = float(shares[i])
                except (ValueError, IndexError):
                    continue
                try:
                    wt = float(weights[i]) if i < len(weights) else None
                except ValueError:
                    wt = None
                out.append({
                    "scheme_slug": slug,
                    "as_of_month": date(int(mon[:4]), int(mon[5:7]), 1),
                    "security_isin": isin,
                    "symbol": (str(r[_F_SYMBOL]).strip() or None),
                    "security_name": (str(r[_F_NAME]).strip() or None),
                    "shares": qty,
                    "weight_pct": wt,
                    "asset_class": asset_class,
                    "sector": (str(r[_F_SECTOR]).strip() or None) if len(r) > _F_SECTOR else None,
                    "industry": (str(r[_F_INDUSTRY]).strip() or None) if len(r) > _F_INDUSTRY else None,
                })
    return out


_UPSERT = """
INSERT INTO nidp.scanx_mf_holdings
    (scheme_slug, as_of_month, security_isin, symbol, security_name, shares, weight_pct,
     asset_class, sector, industry, amc, scheme_name, plan_id, source_run_id)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
ON CONFLICT (scheme_slug, as_of_month, security_isin) DO UPDATE SET
    symbol = EXCLUDED.symbol, security_name = EXCLUDED.security_name,
    shares = EXCLUDED.shares, weight_pct = EXCLUDED.weight_pct,
    asset_class = EXCLUDED.asset_class, sector = EXCLUDED.sector, industry = EXCLUDED.industry,
    amc = EXCLUDED.amc, scheme_name = EXCLUDED.scheme_name, plan_id = EXCLUDED.plan_id,
    retrieved_at = now(), source_run_id = EXCLUDED.source_run_id
"""


async def run(*, limit: Optional[int] = None, amc_filter: Optional[str] = None,
              refresh: bool = False) -> dict:
    bind_context(service=SERVICE_NAME)
    summary = {"schemes_attempted": 0, "schemes_with_rows": 0, "rows_written": 0, "errors": 0}
    pool = await get_pool()

    async with httpx.AsyncClient(timeout=90, follow_redirects=True, headers=_HEADERS) as http:
        idx = await http.get(BASE)
        idx.raise_for_status()
        directory = parse_directory(idx.text)
        if not directory:
            logger.error("%s: could not read the AMC directory from the index page — the page "
                         "shape has probably changed; refusing to proceed", SERVICE_NAME)
            return summary
        logger.info("%s: directory lists %d AMC(s), %d scheme(s)", SERVICE_NAME,
                    len(directory), sum(len(a.get("scheme", [])) for a in directory))

        targets: list[tuple[str, str, str, str]] = []   # slug, amc, scheme_name, plan_id
        for a in directory:
            if amc_filter and amc_filter.lower() not in a.get("amc", "").lower():
                continue
            for s in a.get("scheme", []):
                slug = (s.get("seo") or "").strip()
                if slug:
                    targets.append((slug, a.get("amc"), s.get("name"), str(s.get("plan_id") or "")))

        if not refresh:
            async with pool.acquire() as conn:
                done = {r["scheme_slug"] for r in await conn.fetch(
                    "SELECT DISTINCT scheme_slug FROM nidp.scanx_mf_holdings "
                    "WHERE retrieved_at > now() - ($1 || ' days')::interval",
                    str(REFRESH_AFTER_DAYS))}
            before = len(targets)
            targets = [t for t in targets if t[0] not in done]
            logger.info("%s: %d scheme(s) fetched within %d days are skipped; %d to go",
                        SERVICE_NAME, before - len(targets), REFRESH_AFTER_DAYS, len(targets))
        if limit:
            targets = targets[:limit]
        if not targets:
            return summary

        async with JobRun(ingester=SERVICE_NAME, target_date=date.today()) as job:
            bind_context(run_id=str(job.run_id))
            for i, (slug, amc, name, plan_id) in enumerate(targets, 1):
                try:
                    r = await http.get(f"{BASE}/{slug}-holdings")
                    if r.status_code != 200:
                        summary["errors"] += 1
                        logger.info("%s[%s]: HTTP %d", SERVICE_NAME, slug, r.status_code)
                        continue
                    rows = parse_holdings(r.text, slug)
                except Exception as e:                                  # noqa: BLE001
                    summary["errors"] += 1
                    logger.info("%s[%s]: %s: %s", SERVICE_NAME, slug, type(e).__name__, str(e)[:120])
                    continue
                summary["schemes_attempted"] += 1
                if rows:
                    args = [(d["scheme_slug"], d["as_of_month"], d["security_isin"], d["symbol"],
                             d["security_name"], d["shares"], d["weight_pct"], d["asset_class"],
                             d["sector"], d["industry"], amc, name, plan_id, job.run_id)
                            for d in rows]
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            await conn.executemany(_UPSERT, args, timeout=180)
                    summary["schemes_with_rows"] += 1
                    summary["rows_written"] += len(args)
                if i % 25 == 0:
                    logger.info("%s: %d/%d schemes, %d rows", SERVICE_NAME, i, len(targets),
                                summary["rows_written"])
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
    ap = argparse.ArgumentParser(description="Ingest scheme-level MF holdings from ScanX")
    ap.add_argument("--limit", type=int, default=None, help="cap the scheme count")
    ap.add_argument("--amc", default=None, help="only schemes whose AMC name contains this")
    ap.add_argument("--refresh", action="store_true",
                    help=f"re-fetch schemes already pulled within {REFRESH_AFTER_DAYS} days")
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    async def _go() -> None:
        try:
            await run(limit=args.limit, amc_filter=args.amc, refresh=args.refresh)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
