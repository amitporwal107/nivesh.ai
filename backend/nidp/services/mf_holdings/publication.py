"""Publication timestamps for mf_holdings: capture Last-Modified, derive published_at credibly.

Point-in-time correctness for this feed rests on one question: when could a user first have known
this portfolio? as_of_month cannot answer it (SEBI allows ten days after month end, and the
sources lag further), and ingested_at only says when WE wrote it. The source file's Last-Modified
is the only publication signal any of these AMCs expose.

Measured across all 118 stored AMC-month URLs on 2026-10-22: every source returns the header, but
90 are credible publication dates (lag from month end: min 5, median 9, max 51 days — a median of
9 matching SEBI's M+10 is what corroborates them), 14 are late re-uploads, and 13 are CDN cache
touches equal to our own fetch time (franklin rewrites it on 11 of 13 requests).

So the header is an UPPER BOUND, not publication. It is stored raw either way, and published_at is
derived only inside the credible window. Outside it we keep the weaker true statement — "we had
seen this by source_observed_at" — rather than a stronger false one.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

# A disclosure for month M cannot have been published before M ended, and one still being
# modified more than ~2 months later is a revision rather than the original release. 60 days is
# generous against the observed max of 51 while still excluding the October-2026 cache touches on
# months from 2025.
MAX_PUBLICATION_LAG_DAYS = 60

# A Last-Modified within this many days of our own fetch is treated as a cache touch, not a
# publication, regardless of the month it claims to describe.
CACHE_TOUCH_TOLERANCE_DAYS = 2

CLASS_PLAUSIBLE   = "plausible_publication"
CLASS_LATE        = "late_reupload"
CLASS_CACHE_TOUCH = "cache_touch"
CLASS_TOO_EARLY   = "before_month_end"
CLASS_UNPARSEABLE = "unparseable"
CLASS_ABSENT      = "absent"


def _month_end(as_of_month: date) -> date:
    return date(as_of_month.year, as_of_month.month,
                calendar.monthrange(as_of_month.year, as_of_month.month)[1])


def classify(
    last_modified: Optional[str | datetime],
    as_of_month: date,
    observed_at: Optional[datetime] = None,
) -> Tuple[Optional[datetime], str]:
    """(parsed_last_modified, class). Only CLASS_PLAUSIBLE may become published_at."""
    if last_modified is None or last_modified == "":
        return None, CLASS_ABSENT
    if isinstance(last_modified, datetime):
        lm = last_modified
    else:
        try:
            lm = parsedate_to_datetime(last_modified)
        except Exception:                                          # noqa: BLE001
            return None, CLASS_UNPARSEABLE
    if lm is None:
        return None, CLASS_UNPARSEABLE
    if lm.tzinfo is None:
        lm = lm.replace(tzinfo=timezone.utc)

    me = _month_end(as_of_month)
    lag = (lm.date() - me).days

    # Checked before the lag window: a CDN that rewrites the header on access can land inside the
    # window by coincidence for a recent month, and that value is still meaningless.
    obs = observed_at or datetime.now(timezone.utc)
    if abs((lm.date() - obs.date()).days) <= CACHE_TOUCH_TOLERANCE_DAYS:
        return lm, CLASS_CACHE_TOUCH
    if lag < 0:
        return lm, CLASS_TOO_EARLY
    if lag <= MAX_PUBLICATION_LAG_DAYS:
        return lm, CLASS_PLAUSIBLE
    return lm, CLASS_LATE


def published_at_from(
    last_modified: Optional[str | datetime],
    as_of_month: date,
    observed_at: Optional[datetime] = None,
) -> Tuple[Optional[datetime], Optional[datetime], str]:
    """(published_at | None, parsed_last_modified | None, class)."""
    lm, cls = classify(last_modified, as_of_month, observed_at)
    return (lm if cls == CLASS_PLAUSIBLE else None), lm, cls


async def fetch_last_modified(
    http: aiohttp.ClientSession, url: str
) -> Optional[str]:
    """HEAD the file for its Last-Modified, falling back to a ranged GET.

    One extra request per AMC-month, which is negligible against downloading a 25MB disclosure.
    Some CDNs refuse HEAD but answer a ranged GET, so both are tried. Never raises: a missing
    publication timestamp degrades provenance, it must not fail an otherwise good ingest.
    """
    try:
        async with http.head(url, allow_redirects=True) as r:
            lm = r.headers.get("Last-Modified")
            if lm:
                return lm
    except Exception as e:                                         # noqa: BLE001
        logger.debug("last-modified HEAD failed for %s: %s: %s", url, type(e).__name__, e)
    try:
        async with http.get(url, allow_redirects=True,
                            headers={"Range": "bytes=0-64"}) as r:
            return r.headers.get("Last-Modified")
    except Exception as e:                                         # noqa: BLE001
        logger.info("last-modified unavailable for %s: %s: %s", url, type(e).__name__, e)
        return None


# ── Backfill for AMC-months ingested before migration 171 ───────────────────────────────────────
#
# Usage:
#     python -m nidp.services.mf_holdings.publication            # only rows still missing it
#     python -m nidp.services.mf_holdings.publication --all      # re-check every AMC-month
#
# Holdings rows are matched by (as_of_month, source_url) rather than by an amc_id-to-source-prefix
# guess: the URL is stored on every row and is exact, whereas prefix matching on ids that
# themselves contain underscores would over-match under LIKE.

_SELECT_SQL = """
SELECT amc_id, as_of_month, source_url
  FROM nidp.mf_holdings_coverage
 WHERE status = 'OK' AND source_url IS NOT NULL
   AND ($1::bool OR source_last_modified IS NULL)
 ORDER BY as_of_month DESC, amc_id
"""

_UPDATE_COVERAGE_SQL = """
UPDATE nidp.mf_holdings_coverage
   SET source_last_modified = $3, last_modified_class = $4
 WHERE amc_id = $1 AND as_of_month = $2
"""

_UPDATE_HOLDINGS_SQL = """
UPDATE nidp.mf_holdings_monthly
   SET source_last_modified = $3,
       published_at = coalesce($4, published_at),
       publication_provenance = CASE WHEN coalesce($4, published_at) IS NOT NULL
                                     THEN 'published_at_captured' ELSE publication_provenance END
 WHERE as_of_month = $1 AND source_url = $2
"""

POLITE_GAP_S = 0.4


async def backfill(*, recheck_all: bool = False) -> dict:
    """Populate source_last_modified / published_at for already-ingested AMC-months."""
    import asyncio

    from nidp.shared.config import DEFAULT_UA
    from nidp.shared.storage.pg import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        targets = await conn.fetch(_SELECT_SQL, recheck_all)

    logger.info("publication backfill: %d AMC-month(s) to check", len(targets))
    summary: dict = {"checked": 0, "rows_stamped": 0, "by_class": {}}

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout,
                                     headers={"User-Agent": DEFAULT_UA}) as http:
        for i, t in enumerate(targets, 1):
            amc, month, url = t["amc_id"], t["as_of_month"], t["source_url"]
            raw = await fetch_last_modified(http, url)
            pub, lm, cls = published_at_from(raw, month)
            async with pool.acquire() as conn:
                await conn.execute(_UPDATE_COVERAGE_SQL, amc, month, lm, cls)
                tag = await conn.execute(_UPDATE_HOLDINGS_SQL, month, url, lm, pub)
            n = int(tag.rsplit(" ", 1)[-1]) if tag.startswith("UPDATE") else 0
            summary["checked"] += 1
            summary["rows_stamped"] += n if pub else 0
            summary["by_class"][cls] = summary["by_class"].get(cls, 0) + 1
            logger.info("[%d/%d] %s %s class=%s published_at=%s rows=%d",
                        i, len(targets), amc, month, cls, pub, n)
            if i < len(targets):
                await asyncio.sleep(POLITE_GAP_S)

    logger.info("publication backfill done: %s", summary)
    return summary


def main() -> None:
    import argparse
    import asyncio

    from nidp.shared.logging_setup import setup_logging
    from nidp.shared.storage.pg import close_pool

    ap = argparse.ArgumentParser(
        description="Capture Last-Modified and derive published_at for ingested AMC-months")
    ap.add_argument("--all", dest="recheck_all", action="store_true",
                    help="re-check every AMC-month, not only those missing a Last-Modified")
    args = ap.parse_args()
    setup_logging(service="mf_holdings_publication")

    async def _go() -> None:
        try:
            await backfill(recheck_all=args.recheck_all)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
