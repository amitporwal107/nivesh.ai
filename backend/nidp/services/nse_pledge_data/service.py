"""NSE pledge data ingester.

Fetches the bulk pledge data endpoint from NSE India:
    https://www.nseindia.com/api/corporate-pledgedata

This endpoint returns the latest Reg-7 SAST aggregate pledge position
for all listed companies (1500+), including:
  - Total shares pledged (numSharesPledged)
  - Pledged % of total issued shares (percSharesPledged)
  - Promoter holding % (percPromoterHolding)
  - Shareholding pattern date (shp)

The data is mapped to NIDP symbols via sector_master.company_name and
merged into shareholding_pattern (promoter_pledged_pct,
promoter_pledged_to_total_pct, pledged_shares).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date
from typing import Optional

from nidp.shared.config import NSE_WWW
from nidp.shared.metrics import SOURCE_FETCH, time_fetch
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.pg import get_pool

from .parser import parse_pledge_response

logger = logging.getLogger(__name__)

NSE_PLEDGE_URL = f"{NSE_WWW}/api/corporate-pledgedata"
NSE_PLEDGE_REFERER = f"{NSE_WWW}/companies-listing/corporate-filings-pledge-data"
SOURCE_NAME = "NSE_PLEDGE"


async def run(target_date: Optional[date] = None) -> dict:
    """Fetch NSE pledge data and merge into shareholding_pattern.

    Returns a summary dict with counts.
    """
    run_id = uuid.uuid4()
    logger.info("nse_pledge_data: starting run %s", run_id)

    # 1. Fetch bulk pledge endpoint
    with time_fetch(SOURCE_NAME):
        try:
            body, status = await fetch_bytes(
                NSE_PLEDGE_URL,
                referer=NSE_PLEDGE_REFERER,
                extra_headers={"Accept": "application/json"},
            )
            SOURCE_FETCH.labels(source=SOURCE_NAME, status=str(status)).inc()
        except Exception:
            SOURCE_FETCH.labels(source=SOURCE_NAME, status="error").inc()
            raise

    if status != 200 or not body:
        logger.error("nse_pledge_data: fetch failed (status=%s, bytes=%d)", status, len(body or b""))
        return {"status": "FAILED", "reason": f"HTTP {status}"}

    # 2. Parse JSON and build name→pledge map
    pledge_records = parse_pledge_response(body)
    logger.info("nse_pledge_data: parsed %d pledge records", len(pledge_records))

    if not pledge_records:
        return {"status": "SKIPPED", "reason": "no pledge records parsed"}

    # 3. Map company names to symbols via sector_master
    pool = await get_pool()
    async with pool.acquire() as conn:
        sm_rows = await conn.fetch(
            "SELECT symbol, company_name FROM nidp.sector_master WHERE company_name IS NOT NULL"
        )

    # Build name→symbol lookup (case-insensitive, strip whitespace)
    name_to_symbol: dict[str, str] = {}
    for row in sm_rows:
        name_to_symbol[row["company_name"].strip().lower()] = row["symbol"]

    # 4. Match and upsert
    matched = 0
    unmatched_names: list[str] = []
    upsert_args = []

    for rec in pledge_records:
        com_name = rec["company_name"].strip().lower()
        symbol = name_to_symbol.get(com_name)
        if not symbol:
            unmatched_names.append(rec["company_name"])
            continue
        matched += 1
        # Tuple layout: (symbol, period_end, pledged_pct_promoter, pledged_pct_total, pledged_shares, run_id)
        upsert_args.append((
            symbol,                               # $1
            rec["period_end"],                     # $2
            rec["promoter_pledged_pct"],           # $3 — pledged as % of promoter holding
            rec["promoter_pledged_to_total_pct"],  # $4 — pledged as % of total shares
            rec["pledged_shares"],                 # $5 — absolute share count
            run_id,                                # $6
        ))

    if not upsert_args:
        logger.warning("nse_pledge_data: no symbols matched")
        return {"status": "SKIPPED", "matched": 0, "unmatched": len(unmatched_names)}

    # 5. Upsert into shareholding_pattern
    #    - UPDATE existing rows where (symbol, period_end, source='NSE_SHP') exists
    #    - INSERT new rows for symbols that have no shareholding row at that period_end
    shp_updated = 0
    shp_inserted = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            # First, UPDATE existing rows
            # Args: $1=symbol, $2=period_end, $3=pledged_pct_promoter,
            #        $4=pledged_pct_total, $5=pledged_shares, $6=run_id
            await conn.executemany(
                """
                UPDATE nidp.shareholding_pattern
                   SET promoter_pledged_pct          = COALESCE($3::numeric,   promoter_pledged_pct),
                       promoter_pledged_to_total_pct = COALESCE($4::numeric,   promoter_pledged_to_total_pct),
                       pledged_shares                = COALESCE($5::bigint,    pledged_shares),
                       source_run_id                 = $6::uuid,
                       ingested_at                   = NOW()
                 WHERE symbol     = $1::text
                   AND period_end = $2::date
                   AND source     = 'NSE_SHP'
                """,
                upsert_args,
            )

            # Then, INSERT rows for symbols with no existing shareholding data
            # at this period_end. Uses ON CONFLICT to skip duplicates.
            await conn.executemany(
                """
                INSERT INTO nidp.shareholding_pattern
                    (symbol, period_end,
                     promoter_pledged_pct, promoter_pledged_to_total_pct, pledged_shares,
                     source, source_run_id, ingested_at)
                VALUES ($1::text, $2::date, $3::numeric, $4::numeric, $5::bigint,
                        'NSE_SHP', $6::uuid, NOW())
                ON CONFLICT (symbol, period_end, source) DO NOTHING
                """,
                upsert_args,
            )

    # 6. Propagate pledge data directly into stock_features_daily
    #    Use a temp table to hold the pledge values, then bulk-UPDATE.
    #    This bypasses the v_shareholding_latest view which may not have
    #    all stocks (shareholding_pattern needs promoter_pct to appear in
    #    the DISTINCT ON view).
    updated_sfd = 0
    async with pool.acquire() as conn:
        # Create temp mapping of symbol → pledge %
        await conn.execute("DROP TABLE IF EXISTS _pledge_update")
        await conn.execute("CREATE TEMP TABLE _pledge_update (symbol TEXT PRIMARY KEY, pct NUMERIC(8,4))")
        await conn.executemany(
            "INSERT INTO _pledge_update (symbol, pct) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            [(a[0], a[3]) for a in upsert_args if a[3] is not None],  # a[3] = pledged_pct_total
        )
        result = await conn.execute(
            """
            UPDATE nidp.stock_features_daily sfd
               SET promoter_pledged_pct = pu.pct
              FROM _pledge_update pu
             WHERE sfd.symbol     = pu.symbol
               AND sfd.as_of_date >= (CURRENT_DATE - INTERVAL '60 days')
               AND (sfd.promoter_pledged_pct IS NULL
                    OR sfd.promoter_pledged_pct != pu.pct)
            """,
        )
        updated_sfd = int(result.split()[-1]) if result else 0

    logger.info(
        "nse_pledge_data: done. matched=%d unmatched=%d sfd_updated=%d",
        matched, len(unmatched_names), updated_sfd,
    )

    if unmatched_names:
        logger.debug(
            "nse_pledge_data: unmatched names (first 20): %s",
            unmatched_names[:20],
        )

    return {
        "status": "OK",
        "run_id": str(run_id),
        "total_parsed": len(pledge_records),
        "matched": matched,
        "unmatched": len(unmatched_names),
        "sfd_updated": updated_sfd,
    }
