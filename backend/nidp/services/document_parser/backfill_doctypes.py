#!/usr/bin/env python3
"""
backfill_doctypes.py — retype already-parsed documents still stuck on the generic
'announcement_attachment', using the SAME content classifier the live parser now
applies (doctype.classify). The content signal is the first chunks' text already
stored in nidp.document_chunks (so we do NOT re-download or re-parse any PDF),
plus the joined announcement subject + subcategory.

Idempotent: only rows that classify to a confident non-fallback type are changed,
so it is safe to re-run after classifier improvements. --dry-run prints the
reclassifications without writing.

Run (one-time / occasional, from backend/):
  python -m nidp.services.document_parser.backfill_doctypes --dry-run
  python -m nidp.services.document_parser.backfill_doctypes --limit 2000
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter

from nidp.shared.storage.pg import get_pool
from nidp.services.corporate_announcements.doctype import classify

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("backfill_doctypes")

# Pull the first two chunks' text as the content signal (chunk_index 0,1 ~ the
# opening pages). Space-joined — the classifier's regexes don't need newlines.
_SELECT_SQL = """
SELECT d.doc_id, ca.subject, ca.subcategory,
       (SELECT string_agg(dc.text, ' ' ORDER BY dc.chunk_index)
          FROM nidp.document_chunks dc
         WHERE dc.doc_id = d.doc_id AND dc.chunk_index < 2) AS head_text
  FROM nidp.documents d
  LEFT JOIN nidp.corporate_announcements ca
         ON ca.announcement_id = d.announcement_id
        AND ca.source          = d.announcement_source
 WHERE d.doc_type = 'announcement_attachment'
   AND d.parse_status = 'parsed'
 ORDER BY d.filed_at DESC NULLS LAST
 LIMIT $1
"""

_UPDATE_SQL = """
UPDATE nidp.documents
   SET doc_type = $2, doc_type_confidence = $3
 WHERE doc_id = $1
"""


async def _main(limit: int, dry_run: bool) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SELECT_SQL, limit)
    log.info("untyped 'announcement_attachment' candidates: %d (limit %d)", len(rows), limit)

    updates: list[tuple] = []
    changed: Counter = Counter()
    for r in rows:
        new_type, score, _ = classify(
            headline=r["subject"] or "",
            first_page_text=(r["head_text"] or "")[:6000],
            subcategory=r["subcategory"] or "",
        )
        if new_type == "announcement_attachment":
            continue
        changed[new_type] += 1
        updates.append((r["doc_id"], new_type, score))
        log.info("  [-> %-22s score %2d] %s", new_type, score, (r["subject"] or "")[:80])

    if updates and not dry_run:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for doc_id, new_type, score in updates:
                    await conn.execute(_UPDATE_SQL, doc_id, new_type, score)

    log.info("reclassified: %s %s",
             dict(changed) or "nothing", "(dry run — no writes)" if dry_run else "(written)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(_main(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
