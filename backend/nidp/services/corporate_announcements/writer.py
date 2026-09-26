"""Postgres writer for nidp.corporate_announcements.

Upsert on (announcement_id, source). Re-fetches of the same window are
no-ops on the row body but bump ingested_at + source_run_id so we can
trace which run last touched a record.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable
from uuid import UUID

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

SOURCE_NAME = "NSE_ANN"

_UPSERT_SQL = """
INSERT INTO nidp.corporate_announcements (
    announcement_id, source, ticker_symbol, isin, scrip_code, company_name,
    filed_at, broadcast_at, subject, description, raw_category, subcategory, attachment_url,
    source_run_id, raw_payload
) VALUES (
    $1,$2,$3,$4,$5,$6,
    $7,$8,$9,$10,$11,$12,$13,
    $14,$15::jsonb
)
ON CONFLICT (announcement_id, source) DO UPDATE SET
    ticker_symbol  = EXCLUDED.ticker_symbol,
    isin           = EXCLUDED.isin,
    scrip_code     = EXCLUDED.scrip_code,
    company_name   = EXCLUDED.company_name,
    broadcast_at   = EXCLUDED.broadcast_at,
    subject        = EXCLUDED.subject,
    description    = COALESCE(EXCLUDED.description, nidp.corporate_announcements.description),
    raw_category   = EXCLUDED.raw_category,
    -- keep an existing (subcategory-sweep) value if a later coarse sweep re-upserts NULL
    subcategory    = COALESCE(EXCLUDED.subcategory, nidp.corporate_announcements.subcategory),
    attachment_url = EXCLUDED.attachment_url,
    source_run_id  = EXCLUDED.source_run_id,
    raw_payload    = EXCLUDED.raw_payload,
    ingested_at    = NOW();
"""


# BSE filings written from the www RSS during the api.bseindia.com outage
# (backfill_bse_from_cie.py, raw_payload->>'via' = 'cie_bse_rss') carry no NEWSID,
# so their announcement_id can never equal the API's and ON CONFLICT cannot merge
# the two. When the API version of such a filing is written — by the live sweep,
# the feed_reconciler re-running its 7-day lookback, or an off-VM replay — the RSS
# row is retired in the same transaction. Same filing = same scrip and either the
# same attachment within a day, or (BSE's attachment-less notices) no attachment
# and API dissemination 0-182 s after the RSS submission time. The 1-day bound also
# stops a later re-filing of the same PDF from retiring an earlier, different filing.
RSS_VIA = "cie_bse_rss"

# r = the RSS row; a = its API twin, or (dry run) a replayed row not yet written.
_TWIN_MATCH = """
       r.source = 'BSE_ANN'
   AND r.raw_payload->>'via' = 'cie_bse_rss'
   AND r.scrip_code = a.scrip_code
   AND r.filed_at BETWEEN a.filed_at - interval '1 day' AND a.filed_at + interval '1 day'
   AND (r.attachment_url = a.attachment_url
        OR (r.attachment_url IS NULL AND a.attachment_url IS NULL
            AND a.filed_at BETWEEN r.filed_at - interval '1 second'
                               AND r.filed_at + interval '182 seconds'))"""
_API_TWIN = ("a.source = 'BSE_ANN' AND coalesce(a.raw_payload->>'NEWSID', '') <> '' "
             "AND r.announcement_id <> a.announcement_id AND")

# Per written batch. The batch's own time span bounds r as CONSTANTS ($2, $3), so the
# planner reads r through idx_ann_filed_at instead of every BSE row on every sweep.
_SUPERSEDE_FOR_BATCH = (
    "DELETE FROM nidp.corporate_announcements r USING nidp.corporate_announcements a "
    "WHERE a.announcement_id = ANY($1::text[]) AND " + _API_TWIN +
    " r.filed_at BETWEEN $2::timestamptz - interval '1 day' AND $3::timestamptz + interval '1 day' AND"
    + _TWIN_MATCH + " RETURNING r.announcement_id")
# Whole table: API rows written before the writer did this (bse_offvm_replay --supersede-rss).
SUPERSEDE_RSS_SQL = ("DELETE FROM nidp.corporate_announcements r USING nidp.corporate_announcements a "
                     "WHERE " + _API_TWIN + _TWIN_MATCH + " RETURNING r.announcement_id")
COUNT_RSS_TWINS_SQL = ("SELECT count(DISTINCT r.announcement_id) FROM nidp.corporate_announcements r, "
                       "nidp.corporate_announcements a WHERE " + _API_TWIN + _TWIN_MATCH)
# Dry run of a replay: RSS rows that rows NOT YET WRITTEN would retire, passed as arrays.
COUNT_TWINS_OF_ROWS_SQL = (
    "SELECT count(DISTINCT r.announcement_id) FROM "
    "unnest($1::text[], $2::timestamptz[], $3::text[]) AS a(scrip_code, filed_at, attachment_url), "
    "nidp.corporate_announcements r WHERE" + _TWIN_MATCH)

# No foreign key protects these, so a retired RSS id must be removed from them too;
# event_lifecycle and filing_insights rebuild from the API row on their next run.
_DEPENDANTS = (
    "DELETE FROM nidp.corporate_transaction_filings WHERE source = 'BSE_ANN' AND announcement_id = ANY($1::text[])",
    "DELETE FROM nidp.corporate_event_signals WHERE announcement_source = 'BSE_ANN' AND announcement_ref = ANY($1::text[])",
)


async def retire_rss_rows(conn, sql: str, *args) -> int:
    """Run a SUPERSEDE statement and remove the retired ids' dependants. Caller owns the transaction."""
    gone = [r["announcement_id"] for r in await conn.fetch(sql, *args)]
    if gone:
        for dep in _DEPENDANTS:
            await conn.execute(dep, gone)
    return len(gone)


async def upsert_announcements(rows: Iterable[dict], source_run_id: UUID) -> int:
    rows = list(rows)
    if not rows:
        return 0
    pool = await get_pool()
    n = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r in rows:
                await conn.execute(
                    _UPSERT_SQL,
                    r["announcement_id"],
                    r["source"],
                    r.get("ticker_symbol"),
                    r.get("isin"),
                    r.get("scrip_code"),
                    r.get("company_name"),
                    r["filed_at"],
                    r.get("broadcast_at"),
                    r.get("subject"),
                    r.get("description"),
                    r.get("raw_category"),
                    r.get("subcategory"),
                    r.get("attachment_url"),
                    source_run_id,
                    json.dumps(r.get("raw_payload") or {}, default=str),
                )
                n += 1
            api = [r for r in rows if r["source"] == "BSE_ANN" and (r.get("raw_payload") or {}).get("NEWSID")]
            if api:
                ts = [r["filed_at"] for r in api]
                gone = await retire_rss_rows(conn, _SUPERSEDE_FOR_BATCH,
                                             [r["announcement_id"] for r in api], min(ts), max(ts))
                if gone:
                    logger.info("writer: %d %s row(s) superseded by their API twins", gone, RSS_VIA)
    logger.info("writer: upserted %d announcements (run=%s)", n, source_run_id)
    return n
