"""Market-wide FII/DII flows from Sensibull's oxide endpoints -> nidp.fii_dii_flows.

Why this exists: NSE's /api/fiidiiTradeReact is rolling and its dated archive
(fii_stats_{YYYYMMDD}.xls) 404s on every date tried, so nidp.fii_dii_flows had only ~16 days and
could not be backfilled from the exchange. Sensibull serves the whole history and needs no login.

Two endpoints, both on oxide, both reachable with an ANONYMOUS platform token:

    GET /v1/pluto/auth/web/session/a/platform/identify   -> Set-Cookie: access_token=pa:<JWT>
    GET /v1/compute/cache/fii_dii_daily                  -> {year_month, key_list, data{date: rec}}
    GET /v1/compute/cache/fii_dii_daily?year_month=2026-September
    GET /v1/compute/cache/fii_dii_cash                   -> {YYYY-MM-01: monthly rec}  (no params)

Two traps, both of which make a working endpoint look dead:
  * `year_month` takes the month NAME. The numeric form (2026-09) returns
    "Internal Calculation Error: Compute server internal error".
  * Both data calls need `Origin: https://web.sensibull.com`. Without it: "access denied".
So the month list is read from the no-param call's `key_list` rather than constructed.

Depth, measured 2026-10-22: daily is a ~7-month rolling window (key_list 2026-April..2026-October);
monthly is 98 points, 2018-09-01..2026-10-01. Months outside key_list error, so monthly is the
deep history and daily is the recent detail.

Third trap, found by the row counts not adding up: the CURRENT month's key does not return a
calendar month. `2026-October` returned 21 sessions starting 2026-09-21, overlapping the
`2026-September` payload by 8 sessions. So the seven payloads carry 146 date-entries for 138
distinct dates. The upsert absorbs it (verified: a re-run changes 0 of 2,266 rows), but anything
that counts rows per month, or sums payloads without deduplicating, will double-count those 8
sessions.

Provenance: daily lands as source SENSIBULL, monthly as SENSIBULL_MONTHLY. They are deliberately
DIFFERENT sources, not one source at two granularities, so that no query can sum a monthly
observation together with daily ones by accident -- every read filters `source`. Existing
NSE_FII_DII rows are never overwritten; the overlap is a free daily reconciliation check.

What is deliberately NOT stored: the feed's net_view / net_view_strength / net_action strings, the
call/put long-short legs, and the `amount-wise` mirror of `quantity-wise`. Those are the vendor's
interpretation, and a warehouse should not keep another party's opinion as if it were an
observation.

Caveat: this is a public app's internal app-state endpoint, not a documented API, and the
anonymous token is an undocumented affordance. It can change shape without notice. Cadence here is
daily, and the requests are paced.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime
from typing import Any, Iterable, Optional

import httpx

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

SERVICE_NAME = "sensibull_fii_dii"

OXIDE = "https://oxide.sensibull.com"
_IDENTIFY = f"{OXIDE}/v1/pluto/auth/web/session/a/platform/identify"
_DAILY = f"{OXIDE}/v1/compute/cache/fii_dii_daily"
_MONTHLY = f"{OXIDE}/v1/compute/cache/fii_dii_cash"

SOURCE_DAILY = "SENSIBULL"
SOURCE_MONTHLY = "SENSIBULL_MONTHLY"
POLITE_GAP_S = 1.5

# Origin is not optional: the API answers "access denied" without it.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://web.sensibull.com",
    "Referer": "https://web.sensibull.com/",
}

# cash carries fii/dii only; future and option also carry pro/client.
_CASH_PARTIES = ("fii", "dii")
_FO_PARTIES = ("fii", "dii", "pro", "client")
# Per-index futures net OI lives under quantity-wise as "<index>_net_oi". segment carries the
# index name so index-level F&O needs no schema change. Two things measured, not assumed: the feed
# supplies these per-index fields for FII ONLY (dii/pro/client omit them, so those rows are
# skipped rather than written as nulls), and it gives a net figure with no outstanding-OI
# counterpart, so open_interest stays NULL on FUT_* rows by design.
_INDICES = ("nifty", "banknifty", "finnifty", "midcpnifty", "niftynxt50")

_UPSERT = """
INSERT INTO nidp.fii_dii_flows
    (as_of_date, category, segment, buy_value_cr, sell_value_cr, net_value_cr,
     buy_contracts, sell_contracts, net_contracts, open_interest, source, source_run_id)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
ON CONFLICT (as_of_date, category, segment, source) DO UPDATE SET
    buy_value_cr   = EXCLUDED.buy_value_cr,
    sell_value_cr  = EXCLUDED.sell_value_cr,
    net_value_cr   = EXCLUDED.net_value_cr,
    buy_contracts  = EXCLUDED.buy_contracts,
    sell_contracts = EXCLUDED.sell_contracts,
    net_contracts  = EXCLUDED.net_contracts,
    open_interest  = EXCLUDED.open_interest,
    ingested_at    = now(),
    source_run_id  = EXCLUDED.source_run_id
"""


def _num(v: Any) -> Optional[float]:
    """A float, or None. Rejects bools and non-finite values rather than storing them."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _bigint(v: Any) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(round(f))


def _row(as_of: date, category: str, segment: str, *, buy: Any = None, sell: Any = None,
         net: Any = None, net_contracts: Any = None, oi: Any = None) -> tuple:
    return (as_of, category, segment, _num(buy), _num(sell), _num(net),
            None, None, _bigint(net_contracts), _bigint(oi))


def parse_daily(payload: dict) -> list[tuple]:
    """One Sensibull daily month -> fii_dii_flows tuples (without source/run_id)."""
    out: list[tuple] = []
    for ds, rec in (payload.get("data") or {}).items():
        if not isinstance(rec, dict):
            continue
        try:
            as_of = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            logger.info("%s: unparseable daily date %r, skipped", SERVICE_NAME, ds)
            continue

        cash = rec.get("cash") or {}
        for p in _CASH_PARTIES:
            v = cash.get(p)
            if isinstance(v, dict):
                out.append(_row(as_of, p.upper(), "EQUITY_CASH", buy=v.get("buy"),
                                sell=v.get("sell"), net=v.get("buy_sell_difference")))

        fut = rec.get("future") or {}
        for p in _FO_PARTIES:
            v = fut.get(p)
            if not isinstance(v, dict):
                continue
            q = v.get("quantity-wise") or {}
            if isinstance(q, dict):
                out.append(_row(as_of, p.upper(), "INDEX_FUTURES",
                                net_contracts=q.get("net_oi"), oi=q.get("outstanding_oi")))
                for idx in _INDICES:
                    n = q.get(f"{idx}_net_oi")
                    if n is not None:
                        out.append(_row(as_of, p.upper(), f"FUT_{idx.upper()}", net_contracts=n))

        opt = rec.get("option") or {}
        for p in _FO_PARTIES:
            v = opt.get(p)
            if isinstance(v, dict):
                out.append(_row(as_of, p.upper(), "INDEX_OPTIONS",
                                net_contracts=v.get("overall_net_oi_change"),
                                oi=v.get("overall_net_oi")))
    return out


def parse_monthly(payload: dict) -> list[tuple]:
    """The monthly cash series -> tuples. as_of_date is the 1st, as the feed keys it."""
    out: list[tuple] = []
    for ds, rec in (payload or {}).items():
        if not isinstance(rec, dict):
            continue
        try:
            as_of = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            continue
        for p in _CASH_PARTIES:
            out.append(_row(as_of, p.upper(), "EQUITY_CASH", buy=rec.get(f"{p}_buy"),
                            sell=rec.get(f"{p}_sell"), net=rec.get(f"{p}_net")))
    return out


async def _token(http: httpx.AsyncClient) -> str:
    """Mint the anonymous platform token. Aborts loudly rather than writing nothing silently."""
    r = await http.get(_IDENTIFY)
    r.raise_for_status()
    tok = r.cookies.get("access_token") or http.cookies.get("access_token")
    if not tok:
        raise RuntimeError(
            "Sensibull did not set an access_token cookie on the anonymous identify call — the "
            "auth shape has probably changed; refusing to proceed")
    return tok


async def _get_json(http: httpx.AsyncClient, url: str, **params: str) -> dict:
    r = await http.get(url, params=params or None)
    r.raise_for_status()
    body = r.json()
    if isinstance(body, dict) and body.get("success") is False:
        raise RuntimeError(f"{url} -> {body.get('errors')!r}")
    return body


async def coverage(pool, sources: Iterable[str]) -> list[dict]:
    """Per source: range, distinct dates, and trading sessions MISSING inside its own range.

    The calendar comes from prices_eod, which defines real sessions. Monthly sources are reported
    without a missing-session count, because a monthly observation is not a session.
    """
    rows = []
    async with pool.acquire() as conn:
        for src in sources:
            r = await conn.fetchrow(
                """
                WITH mine AS (
                    SELECT DISTINCT as_of_date FROM nidp.fii_dii_flows
                     WHERE source = $1 AND segment = 'EQUITY_CASH'
                ), span AS (SELECT min(as_of_date) lo, max(as_of_date) hi FROM mine),
                sess AS (
                    SELECT DISTINCT p.as_of_date FROM nidp.prices_eod p, span
                     WHERE p.as_of_date BETWEEN span.lo AND span.hi
                )
                SELECT (SELECT lo FROM span) AS first_date,
                       (SELECT hi FROM span) AS last_date,
                       (SELECT count(*) FROM mine) AS dates_held,
                       (SELECT count(*) FROM sess) AS sessions_in_span,
                       (SELECT count(*) FROM (SELECT as_of_date FROM sess
                                              EXCEPT SELECT as_of_date FROM mine) x)
                           AS sessions_missing
                """, src)
            d = dict(r or {})
            d["source"] = src
            if src.endswith("_MONTHLY"):
                # A monthly observation is not a trading session, so comparing it to the session
                # calendar would report every non-1st session as "missing" (239 of them).
                d["sessions_in_span"] = None
                d["sessions_missing"] = None
            rows.append(d)
    return rows


async def run(*, month: Optional[str] = None, skip_monthly: bool = False,
              dry_run: bool = False) -> dict:
    summary: dict[str, Any] = {"months_available": 0, "months_fetched": 0, "months_failed": 0,
                               "daily_rows": 0, "monthly_rows": 0, "rows_written": 0}
    pool = await get_pool()

    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
        await _token(http)
        logger.info("%s: anonymous platform token minted", SERVICE_NAME)

        head = await _get_json(http, _DAILY)
        key_list = [k for k in (head.get("key_list") or []) if isinstance(k, str)]
        if not key_list:
            logger.error("%s: the daily endpoint returned no key_list — shape changed; refusing "
                         "to guess month names", SERVICE_NAME)
            return summary
        summary["months_available"] = len(key_list)
        months = [month] if month else key_list
        if month and month not in key_list:
            logger.warning("%s: %s is not in key_list %s — fetching anyway, it will probably "
                           "error", SERVICE_NAME, month, key_list)
        logger.info("%s: key_list %s; fetching %d month(s)", SERVICE_NAME, key_list, len(months))

        async with JobRun(ingester=SERVICE_NAME, target_date=date.today()) as job:
            bind_context(run_id=str(job.run_id))
            batches: list[tuple[str, list[tuple]]] = []

            for i, ym in enumerate(months, 1):
                try:
                    payload = head if (not month and ym == head.get("year_month")) else \
                        await _get_json(http, _DAILY, year_month=ym)
                    rows = parse_daily(payload)
                except Exception as e:                                  # noqa: BLE001
                    summary["months_failed"] += 1
                    logger.warning("%s[%s]: %s: %s", SERVICE_NAME, ym, type(e).__name__,
                                   str(e)[:160])
                    continue
                summary["months_fetched"] += 1
                summary["daily_rows"] += len(rows)
                batches.append((SOURCE_DAILY, rows))
                logger.info("%s[%s]: %d rows", SERVICE_NAME, ym, len(rows))
                if i < len(months):
                    await asyncio.sleep(POLITE_GAP_S)

            if not skip_monthly:
                try:
                    mrows = parse_monthly(await _get_json(http, _MONTHLY))
                    summary["monthly_rows"] = len(mrows)
                    batches.append((SOURCE_MONTHLY, mrows))
                    logger.info("%s: monthly series %d rows", SERVICE_NAME, len(mrows))
                except Exception as e:                                  # noqa: BLE001
                    logger.warning("%s[monthly]: %s: %s", SERVICE_NAME, type(e).__name__,
                                   str(e)[:160])

            if dry_run:
                logger.info("%s: --dry-run, nothing written. %s", SERVICE_NAME, summary)
                await job.finalize("SKIPPED", error_message="dry run")
                return summary

            for src, rows in batches:
                if not rows:
                    continue
                args = [r + (src, job.run_id) for r in rows]
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.executemany(_UPSERT, args, timeout=300)
                summary["rows_written"] += len(args)

            job.rows_fetched = summary["daily_rows"] + summary["monthly_rows"]
            job.rows_inserted = summary["rows_written"]
            job.metadata.update(summary)
            await job.finalize("OK" if summary["rows_written"] else "FAILED",
                               error_message=None if summary["rows_written"] else "no rows")

    cov = await coverage(pool, (SOURCE_DAILY, SOURCE_MONTHLY, "NSE_FII_DII"))
    summary["coverage"] = cov
    for c in cov:
        miss = c.get("sessions_missing")
        span = c.get("sessions_in_span")
        logger.info("%s coverage[%s]: %s..%s  %s date(s) held, %s, %s",
                    SERVICE_NAME, c.get("source"), c.get("first_date"), c.get("last_date"),
                    c.get("dates_held"),
                    "monthly series" if span is None else f"{span} session(s) in span",
                    "no session gaps expected" if miss is None else f"{miss} MISSING")
    logger.info("%s done: %s", SERVICE_NAME,
                {k: v for k, v in summary.items() if k != "coverage"})
    print(json.dumps(summary, indent=2, default=str))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest market-wide FII/DII flows from Sensibull")
    ap.add_argument("--month", default=None,
                    help="one month, in the feed's own format, e.g. 2026-September")
    ap.add_argument("--skip-monthly", action="store_true",
                    help="skip the 98-point monthly history (daily only)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and parse, write nothing")
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    async def _go() -> None:
        try:
            await run(month=args.month, skip_monthly=args.skip_monthly, dry_run=args.dry_run)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
