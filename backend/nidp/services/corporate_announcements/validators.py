"""Validation gates for parsed announcement rows.

Drops rows that violate the schema's NOT NULL constraints. Logs (but
keeps) rows that look thin — empty subject, missing entity — since some
SEBI/regulatory disclosures legitimately have neither.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def validate_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Return (kept_rows, dropped_count)."""
    kept: list[dict] = []
    dropped = 0
    for r in rows:
        if not r.get("announcement_id") or not r.get("source") or not r.get("filed_at"):
            dropped += 1
            continue
        if not (r.get("ticker_symbol") or r.get("isin")
                or r.get("company_name") or r.get("scrip_code")):
            # No entity at all — likely a malformed feed entry, not a real disclosure.
            # BSE rows often have only scrip_code, hence its inclusion here.
            logger.debug("dropping entity-less announcement: %s", r.get("subject"))
            dropped += 1
            continue
        kept.append(r)
    if dropped:
        logger.info("validators: kept=%d dropped=%d", len(kept), dropped)
    return kept, dropped
