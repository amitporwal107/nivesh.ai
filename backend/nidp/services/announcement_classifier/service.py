"""Classifier loop — fetch unclassified rows, call the LLM, write back.

Designed for cron invocation (every 5–10 min). Crashes are safe: rows
stay unclassified until a future run picks them up. The `classified_at`
+ `classifier_version` pair lets us re-classify when the prompt changes.

Per-row failures are swallowed on purpose — one malformed filing must not stop
the batch. But a run where EVERY row failed is an outage, not a quiet no-op, so
it raises (see `run_once`). That distinction is load-bearing: between 2026-07-25
and 2026-08-10 the OpenAI account was credit-exhausted and every call 429'd, yet
each 30-min tick still recorded `status=OK, inserted=0`. `nidp.v_feed_status`
stayed green for 16 days while the /v5/research corporate-events feed silently
froze. Nothing alarmed because nothing ever reported failure.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Optional

from .classifier import HaikuClassifier
from .db import fetch_unclassified, store_classification

logger = logging.getLogger(__name__)


async def run_once(limit: int = 200, dry_run: bool = False) -> dict:
    rows = await fetch_unclassified(limit)
    if not rows:
        logger.info("no unclassified announcements; nothing to do")
        return {"processed": 0, "errors": 0}

    clf = HaikuClassifier()
    processed = 0
    errors = 0
    cat_counts: Counter[str] = Counter()
    impact_counts: Counter[str] = Counter()
    t0 = time.monotonic()

    for row in rows:
        try:
            result = clf.classify(row)
        except Exception as e:  # noqa: BLE001 — single-row failure shouldn't stop the run
            logger.warning("classify failed id=%s source=%s err=%s",
                           row["announcement_id"], row["source"], e)
            errors += 1
            continue

        cat_counts[result.event_category] += 1
        impact_counts[result.impact_score] += 1

        if dry_run:
            logger.info("[dry-run] %s/%s → %s/%s/%s   %s",
                        row["source"], row["announcement_id"][:10],
                        result.event_category, result.impact_score, result.sentiment,
                        (row["subject"] or "")[:60])
        else:
            await store_classification(
                row["announcement_id"], row["source"],
                event_category=result.event_category,
                impact_score=result.impact_score,
                sentiment=result.sentiment,
                classifier_version=result.classifier_version,
            )
        processed += 1

    duration = time.monotonic() - t0
    logger.info(
        "classifier done: processed=%d errors=%d duration=%.1fs categories=%s impact=%s",
        processed, errors, duration, dict(cat_counts), dict(impact_counts),
    )

    # Total failure is an outage — raise so run_with_job_log records FAILED and
    # v_feed_status turns red. Returning normally here is what let a 16-day
    # credit-exhaustion outage report OK on every tick (see module docstring).
    # A PARTIAL run (some rows classified) still returns OK: the batch made
    # progress and the failed rows stay NULL for the next tick to retry.
    if processed == 0 and errors > 0:
        raise RuntimeError(
            f"announcement_classifier: all {errors} row(s) failed to classify "
            f"(0 succeeded) — the preceding 'classify failed' warnings carry the "
            f"provider error. Failing the run so it is not recorded as OK."
        )
    return {
        "processed": processed,
        "errors": errors,
        "duration_s": round(duration, 1),
        "categories": dict(cat_counts),
        "impact": dict(impact_counts),
    }
