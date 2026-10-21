"""One AMC, one month — the unit of work shared by the daily run and the backfill.

Both callers need identical semantics (fetch, archive, write, record coverage), and the two
diverging was how the original gap went unnoticed: the daily path wrote every AMC's rows in a
single end-of-run batch, so one AMC's failure was indistinguishable from another's and a partial
month looked like a whole one. Writing per-AMC instead makes progress incremental and resumable
(a 13-month backfill is ~2M rows — one batch is not an option) and makes the coverage ledger
exact rather than inferred.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional

import aiohttp

from . import coverage
from .amc_dispatch import ADAPTERS
from .writer import upsert_holdings

logger = logging.getLogger(__name__)


@dataclass
class AmcIngestResult:
    amc_id: str
    as_of_month: date
    status: str                      # OK | EMPTY | ERROR  (mirrors mf_holdings_coverage)
    rows_written: int = 0
    schemes_written: int = 0
    source_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


async def ingest_amc(
    http: aiohttp.ClientSession,
    amc_id: str,
    as_of_month: date,
    run_id: uuid.UUID,
    *,
    archive: bool = True,
) -> AmcIngestResult:
    """Fetch + persist one AMC's portfolio for one month, and record coverage.

    Never raises for an adapter-level problem: the failure is captured in the returned result
    and in the ledger, so one bad AMC cannot abort a 13-month backfill. A genuine programming
    error (e.g. a missing adapter) still surfaces as an ERROR row with the exception text
    rather than being swallowed.
    """
    fn = ADAPTERS.get(amc_id)
    if fn is None:
        res = AmcIngestResult(amc_id, as_of_month, "ERROR",
                              error="no adapter registered for this amc_id")
        await coverage.record(amc_id, as_of_month, res.status, error=res.error)
        logger.warning("mf_holdings[%s %s]: no adapter registered", amc_id, as_of_month)
        return res

    try:
        rows = await fn(http, as_of_month)
    except Exception as e:                                            # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:500]
        res = AmcIngestResult(amc_id, as_of_month, "ERROR", error=err)
        await coverage.record(amc_id, as_of_month, res.status, error=err)
        logger.warning("mf_holdings[%s %s]: adapter raised: %s", amc_id, as_of_month, err)
        return res

    if not rows:
        res = AmcIngestResult(amc_id, as_of_month, "EMPTY",
                              error="adapter returned no rows (file not published/indexed yet?)")
        await coverage.record(amc_id, as_of_month, res.status, error=res.error)
        logger.info("mf_holdings[%s %s]: no rows", amc_id, as_of_month)
        return res

    # Archive the canonicalised rows. We don't hold the raw file here (each AMC site has its own
    # shape), so the parsed form is what ops can re-import without re-scraping. Archiving must
    # never cost us the write, hence the contained failure.
    if archive:
        try:
            from nidp.shared.archive import archive_raw
            archive_raw("mf_holdings", as_of_month, f"{amc_id}.parsed.json",
                        json.dumps(rows, default=str).encode("utf-8"))
        except Exception as e:                                        # noqa: BLE001
            logger.warning("mf_holdings[%s %s]: archive failed (continuing): %s: %s",
                           amc_id, as_of_month, type(e).__name__, e)

    source_url = next((r.get("source_url") for r in rows if r.get("source_url")), None)
    try:
        n = await upsert_holdings(rows, run_id)
    except Exception as e:                                            # noqa: BLE001
        err = f"upsert failed: {type(e).__name__}: {e}"[:500]
        res = AmcIngestResult(amc_id, as_of_month, "ERROR",
                              source_url=source_url, error=err)
        await coverage.record(amc_id, as_of_month, res.status,
                              source_url=source_url, error=err)
        logger.warning("mf_holdings[%s %s]: %s", amc_id, as_of_month, err)
        return res

    schemes = len({r["scheme_code"] for r in rows})
    res = AmcIngestResult(amc_id, as_of_month, "OK", rows_written=n,
                          schemes_written=schemes, source_url=source_url)
    await coverage.record(amc_id, as_of_month, "OK", rows_written=n,
                          schemes_written=schemes, source_url=source_url)
    logger.info("mf_holdings[%s %s]: wrote %d rows over %d schemes from %s",
                amc_id, as_of_month, n, schemes, source_url)
    return res
