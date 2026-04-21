"""One-shot backfill of AMFI historical NAVs into mutual_fund_nav_history.

Uses AMFI's public DownloadNAVHistoryReport_Po endpoint (same format as the
daily `spages/NAVAll.txt` but filterable by date range). Reuses the daily
cron's parser + instrument resolver.

Usage:
    python -m scripts.backfill_amfi_nav_history --years 5
    python -m scripts.backfill_amfi_nav_history --from 2021-04-01 --to 2026-04-30
    python -m scripts.backfill_amfi_nav_history --months 3 --dry-run
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List, Tuple

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_amfi_navs import iter_rows, resolve_instrument_id, _ensure_pool, _parse_date as _amfi_parse_date  # noqa: E402
from typing import Iterator, Optional, Tuple as _Tuple
from datetime import date as _DATE

log = logging.getLogger("backfill_amfi_nav")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

AMFI_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
TIMEOUT_S = 90.0
CHUNK_DAYS = 30  # AMFI accepts ~3 months per call; 30d keeps each payload <15 MB


def _month_chunks(start: date, end: date, step_days: int = CHUNK_DAYS) -> List[Tuple[date, date]]:
    out: List[Tuple[date, date]] = []
    cur = start
    while cur <= end:
        ce = min(cur + timedelta(days=step_days - 1), end)
        out.append((cur, ce))
        cur = ce + timedelta(days=1)
    return out


async def _fetch_chunk(client: httpx.AsyncClient, frm: date, to: date) -> str:
    params = {
        "mf": "", "tp": "1",
        "frmdt": frm.strftime("%d-%b-%Y"),
        "todt": to.strftime("%d-%b-%Y"),
    }
    r = await client.get(AMFI_URL, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.text


def _iter_history_rows(text: str) -> Iterator[_Tuple[str, str, str, float, _DATE]]:
    """Parse the HISTORICAL AMFI dump. Shape (8 semicolon-delimited fields):

        Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date

    Yields (scheme_code, isin, name, nav, nav_date).
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("scheme code"):
            continue
        parts = line.split(";")
        if len(parts) != 8:
            continue
        scheme_code, name, isin_pay, isin_reinv, nav_str, _rp, _sp, date_str = parts
        if not scheme_code.strip().isdigit():
            continue
        # Skip dividend/payout variants — we only track Growth plans. These
        # share similar names and pollute fuzzy matching.
        low = name.lower()
        if any(kw in low for kw in ("idcw", "dividend", "payout", "reinvest",
                                    "bonus", "income distribution")):
            continue
        try:
            nav = float(nav_str.strip())
        except ValueError:
            continue
        if nav <= 0:
            continue
        dt = _amfi_parse_date(date_str)
        if not dt:
            continue
        isin = (isin_pay or isin_reinv or "").strip() or ""
        yield scheme_code.strip(), isin, name.strip(), nav, dt


async def _resolve_by_isin_only(conn, isin: str, scheme_code: str) -> Optional[str]:
    """Strict resolver for historical backfill: ISIN exact match first, then
    amfi_scheme_code. NO name fuzzy match — AMFI historical dumps have dozens
    of near-identical plan names (Growth / IDCW / Direct / Regular) that blow
    up pg_trgm similarity matching and pollute NAV history.
    """
    if isin:
        r = await conn.fetchrow(
            "SELECT instrument_id FROM instrument_master "
            "WHERE isin = $1 AND instrument_type = 'MUTUAL_FUND' LIMIT 1",
            isin,
        )
        if r:
            return str(r["instrument_id"])
    if scheme_code:
        r = await conn.fetchrow(
            "SELECT instrument_id FROM instrument_master "
            "WHERE symbol = $1 AND instrument_type = 'MUTUAL_FUND' LIMIT 1",
            scheme_code,
        )
        if r:
            return str(r["instrument_id"])
        r = await conn.fetchrow(
            "SELECT instrument_id FROM mutual_fund_metadata "
            "WHERE amfi_scheme_code = $1 LIMIT 1",
            scheme_code,
        )
        if r:
            return str(r["instrument_id"])
    return None


async def _ingest_chunk(conn, body: str, dry_run: bool) -> Tuple[int, int, int]:
    """Parse one AMFI historical dump, upsert matched rows. Returns (parsed, upserted, skipped)."""
    parsed = upserted = skipped = 0
    BATCH = 1000
    buf: list[tuple] = []

    async def flush():
        nonlocal upserted
        if not buf:
            return
        if dry_run:
            upserted += len(buf); buf.clear(); return
        await conn.executemany(
            """
            INSERT INTO mutual_fund_nav_history (instrument_id, nav_date, nav, source)
            VALUES ($1::uuid, $2, $3, 'amfi-backfill')
            ON CONFLICT (instrument_id, nav_date) DO UPDATE SET nav = EXCLUDED.nav
            """,
            buf,
        )
        upserted += len(buf); buf.clear()

    cache: dict = {}
    for scheme_code, isin, name, nav, nav_date in _iter_history_rows(body):
        parsed += 1
        key = (isin, scheme_code)
        if key in cache:
            iid = cache[key]
        else:
            iid = await _resolve_by_isin_only(conn, isin, scheme_code)
            cache[key] = iid
        if not iid:
            skipped += 1
            continue
        buf.append((iid, nav_date, nav))
        if len(buf) >= BATCH:
            await flush()
    await flush()
    return parsed, upserted, skipped


async def run(start: date, end: date, step_days: int = CHUNK_DAYS, dry_run: bool = False) -> dict:
    chunks = _month_chunks(start, end, step_days)
    log.info(f"Backfill {start} → {end}: {len(chunks)} chunks × {step_days}d each")

    pool = await _ensure_pool()
    if pool is None:
        log.error("No PG pool — aborting")
        return {"status": "failed", "reason": "no_pg"}

    tot_parsed = tot_upserted = tot_skipped = 0
    t_start = time.time()

    async with httpx.AsyncClient() as client:
        for i, (frm, to) in enumerate(chunks, 1):
            t0 = time.time()
            # Retry once on transient failures
            for attempt in (1, 2):
                try:
                    body = await _fetch_chunk(client, frm, to)
                    break
                except httpx.HTTPError as e:
                    if attempt == 2:
                        log.error(f"[{i}/{len(chunks)}] {frm}→{to}: SKIPPED ({e})")
                        body = None
                    else:
                        log.warning(f"[{i}/{len(chunks)}] {frm}→{to}: fetch {e}; retrying in 5s")
                        await asyncio.sleep(5)
            if not body:
                continue

            async with pool.acquire() as conn:
                p, u, s = await _ingest_chunk(conn, body, dry_run)
            tot_parsed += p; tot_upserted += u; tot_skipped += s
            log.info(
                f"[{i}/{len(chunks)}] {frm}→{to}: parsed={p:,} upserted={u:,} skipped={s:,} "
                f"({int((time.time() - t0) * 1000)}ms)"
            )
            await asyncio.sleep(1.0)  # gentle pacing for AMFI

    dur = int(time.time() - t_start)
    log.info(f"DONE. parsed={tot_parsed:,} upserted={tot_upserted:,} skipped={tot_skipped:,} in {dur}s")
    return {
        "status": "ok",
        "chunks": len(chunks),
        "rows_parsed": tot_parsed,
        "rows_upserted": tot_upserted,
        "rows_skipped": tot_skipped,
        "duration_s": dur,
    }


def _args():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--years", type=float)
    g.add_argument("--months", type=int)
    ap.add_argument("--from", dest="frm", type=str)
    ap.add_argument("--to", dest="to", type=str)
    ap.add_argument("--chunk-days", type=int, default=CHUNK_DAYS)
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main():
    a = _args()
    today = date.today()
    if a.frm:
        start = date.fromisoformat(a.frm); end = date.fromisoformat(a.to) if a.to else today
    elif a.years:
        start = today - timedelta(days=int(a.years * 365)); end = today
    elif a.months:
        start = today - timedelta(days=a.months * 30); end = today
    else:
        start = today - timedelta(days=365 * 5); end = today
    res = asyncio.run(run(start, end, step_days=a.chunk_days, dry_run=a.dry_run))
    log.info(f"Result: {res}")


if __name__ == "__main__":
    main()
