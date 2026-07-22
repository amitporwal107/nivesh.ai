"""filing_insights loop — select material filings with parsed text, generate one
grounded insight each, upsert into nidp.corporate_event_signals.

Cron-invoked (every ~30 min). Crash-safe and idempotent: a filing with no
insight row is picked up next run; the partial unique index makes re-runs
update-in-place rather than duplicate. Single-row failures never stop the batch.
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from typing import Optional

from .db import fetch_material_pending, fetch_doc_text, store_insight
from .generator import InsightGenerator, MODEL, _model_version

logger = logging.getLogger(__name__)

# Bound the chunks pulled per doc — matches generator.MAX_TEXT_CHARS budget.
_MAX_CHUNKS = 60


def _signal_json(*, insight, row) -> str:
    """The stored payload. `summary` is the key the feed reads into row.one
    (FILINGS_HOME_SPEC §3.1). Everything grounded in the filing, nothing else."""
    return json.dumps({
        "summary":         insight.one_liner,
        "period":          insight.period,
        "headline_metric": insight.headline_metric,   # {label,value,unit} or null
        "sentiment":       insight.sentiment,
        "confidence":      insight.confidence,
        # Expanded-panel tabs. Page citations here are already validated against
        # the document's real page count, so the read path can render them as-is.
        "sections":        insight.sections,
        "event_category":  row["event_category"],
        "doc_type":        row["doc_type"],
        "generated_by":    "filing_insights",
        "model":           MODEL,
    })


async def run_once(limit: int = 100, dry_run: bool = False) -> dict:
    rows = await fetch_material_pending(limit)
    if not rows:
        logger.info("no material filings pending insight; nothing to do")
        return {"processed": 0, "errors": 0}

    gen = InsightGenerator()
    processed = 0
    errors = 0
    with_metric = 0
    with_sections = 0
    empty_text = 0
    sent_counts: Counter[str] = Counter()
    t0 = time.monotonic()

    for row in rows:
        try:
            text, max_page = await fetch_doc_text(row["doc_id"], _MAX_CHUNKS)
            if not text.strip():
                # Parsed doc exists but has no usable chunk text (e.g. a scanned
                # cover letter). Skip honestly rather than prompt on nothing.
                empty_text += 1
                continue
            insight = gen.generate(
                company=row["company_name"] or "",
                ticker=row["ticker_symbol"] or "",
                event_category=row["event_category"],
                doc_type=row["doc_type"],
                subject=row["subject"] or "",
                text=text,
                max_page=max_page,
            )
        except Exception as e:  # noqa: BLE001 — one filing must not kill the batch
            logger.warning("insight failed id=%s source=%s err=%s",
                           row["announcement_id"], row["source"], e)
            errors += 1
            continue

        sent_counts[insight.sentiment] += 1
        if insight.headline_metric:
            with_metric += 1
        if insight.sections:
            with_sections += 1

        if dry_run:
            m = insight.headline_metric
            logger.info("[dry-run] %s/%s %s conf=%.0f metric=%s :: %s",
                        row["source"], row["announcement_id"][:10],
                        row["event_category"], insight.confidence,
                        (f"{m['label']} {m['value']} {m['unit']}" if m else "—"),
                        insight.one_liner[:110])
        else:
            await store_insight(
                symbol=row["ticker_symbol"] or row["company_name"] or "UNKNOWN",
                event_type=row["event_category"],
                event_date=row["filed_at"].date(),
                period=insight.period,
                sentiment=insight.sentiment,
                confidence=insight.confidence,
                signal_json=_signal_json(insight=insight, row=row),
                announcement_ref=row["announcement_id"],
                announcement_source=row["source"],
                model_used=MODEL,
            )
        processed += 1

    duration = time.monotonic() - t0
    logger.info(
        "filing_insights done: processed=%d errors=%d empty_text=%d with_metric=%d "
        "with_sections=%d duration=%.1fs model=%s sentiment=%s",
        processed, errors, empty_text, with_metric, with_sections, duration,
        _model_version(), dict(sent_counts),
    )
    return {
        "processed": processed,
        "errors": errors,
        "empty_text": empty_text,
        "with_metric": with_metric,
        "with_sections": with_sections,
        "duration_s": round(duration, 1),
        "sentiment": dict(sent_counts),
    }


# CLI entrypoint alias (nidp.cli `ingest filing_insights` calls module.run).
async def run(limit: int = 100, dry_run: bool = False) -> dict:
    return await run_once(limit=limit, dry_run=dry_run)
