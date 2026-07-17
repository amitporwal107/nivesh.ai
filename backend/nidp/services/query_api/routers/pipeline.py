"""Per-stage health for the announcement -> RAG pipeline.

WHY THIS DOES NOT USE classify_feed()
-------------------------------------
helpers/nidp_feed_health.classify_feed only returns 'stale' for feeds whose
expected_freq is 'daily' or 'high-freq'. All four pipeline feeds are registered
expected_freq='event' (033_nidp_register_phase1b_s4_s5_ingesters.sql), so it can
NEVER call them stale: a feed that stopped ingesting days ago reads 'healthy' as
long as its last run exited OK. Measured 2026-07-17: BSE announcements were 8.4h
without an ingest and 2 days behind on filings while classify_feed said healthy.

So each stage carries its OWN freshness rule, derived from the data it writes
rather than from whether a cron exited zero. "The job ran" is not "the data moved".

COUNTS ARE FULL-TABLE ON PURPOSE
--------------------------------
Measured on staging (146k announcements / 144k documents / 524k chunks): ~1.7s
for the whole set, dominated by the chunk scans. That is too slow for the 6s poll
the Feeds Live panel uses, hence the panel polls this at 30s. Approximating from
pg_class.reltuples was rejected: it is an estimate that drifts after bulk loads,
and a dashboard whose whole purpose is catching silent drift must not itself
report a plausible-looking guess.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from nidp.services.query_api.auth import require_bearer
from nidp.shared.storage.pg import get_pool

router = APIRouter(prefix="", tags=["pipeline"], dependencies=[Depends(require_bearer)])

# The classifier's queue floor: announcement_classifier/db.py selects
# WHERE event_category IS NULL AND filed_at >= NOW() - INTERVAL '30 days'.
# Anything older that is unclassified is not "pending" — it is unreachable.
_CLASSIFY_WINDOW_DAYS = 30

# Freshness budgets, in hours, per stage. Deliberately generous: these catch
# "this stage is dead", not "this stage is a bit behind".
_LAG_WARN_H = 6.0
_LAG_BAD_H = 24.0


def _age_h(ts: Optional[datetime], now: datetime) -> Optional[float]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return round((now - ts).total_seconds() / 3600.0, 2)


def _state(age_h: Optional[float], *, has_backlog: bool) -> str:
    """Worst-first state for one stage.

    'never' is distinct from 'stale': never-run is a deployment fact, stale is a
    regression. Collapsing them hides which one you are looking at.
    """
    if age_h is None:
        return "never"
    if age_h >= _LAG_BAD_H:
        return "stale"
    if age_h >= _LAG_WARN_H:
        return "lagging"
    return "backlog" if has_backlog else "healthy"


@router.get("/pipeline/stages")
async def pipeline_stages() -> Dict[str, Any]:
    """Six stages of announcement -> RAG, each with counts + its own freshness.

    Never raises on a DB problem: returns db_error and whatever stages it got, so
    the panel degrades to a visible error instead of a blank page or a 500.
    """
    now = datetime.now(timezone.utc)
    stages: List[Dict[str, Any]] = []
    db_error: Optional[str] = None

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # ---- 1. INGEST -------------------------------------------------
            rows = await conn.fetch("""
                SELECT source, count(*) AS total,
                       max(filed_at)    AS latest_filed,
                       max(ingested_at) AS latest_ingest
                  FROM nidp.corporate_announcements
                 GROUP BY source ORDER BY source""")
            by_source = []
            ingest_total = 0
            newest_ingest: Optional[datetime] = None
            for r in rows:
                ingest_total += r["total"]
                if r["latest_ingest"] and (newest_ingest is None or r["latest_ingest"] > newest_ingest):
                    newest_ingest = r["latest_ingest"]
                by_source.append({
                    "source": r["source"],
                    "total": r["total"],
                    "latest_filed": r["latest_filed"].isoformat() if r["latest_filed"] else None,
                    "latest_at": r["latest_ingest"].isoformat() if r["latest_ingest"] else None,
                    "age_hours": _age_h(r["latest_ingest"], now),
                    # Per-source state: the whole reason this stage is split. A
                    # healthy NSE must not mask a dead BSE by averaging with it.
                    "state": _state(_age_h(r["latest_ingest"], now), has_backlog=False),
                })
            stages.append({
                "id": "ingest", "label": "Ingest", "order": 1,
                "table": "nidp.corporate_announcements",
                "total": ingest_total, "done": ingest_total, "pending": 0, "problem": 0,
                "latest_at": newest_ingest.isoformat() if newest_ingest else None,
                "age_hours": _age_h(newest_ingest, now),
                # Worst source wins — an aggregate that hides a dead feed is the bug.
                "state": _worst([s["state"] for s in by_source]),
                "breakdown": by_source,
                "note": "NSE and BSE are separate crons; the worst source sets the state.",
            })

            # ---- 2. CLASSIFY -----------------------------------------------
            r = await conn.fetchrow(f"""
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE event_category IS NOT NULL) AS classified,
                       count(*) FILTER (WHERE event_category IS NULL
                                          AND filed_at >= now() - interval '{_CLASSIFY_WINDOW_DAYS} days')
                            AS pending_reachable,
                       count(*) FILTER (WHERE event_category IS NULL
                                          AND filed_at <  now() - interval '{_CLASSIFY_WINDOW_DAYS} days')
                            AS unreachable,
                       max(classified_at) AS latest
                  FROM nidp.corporate_announcements""")
            stages.append({
                "id": "classify", "label": "Classify", "order": 2,
                "table": "nidp.corporate_announcements.event_category",
                "total": r["total"], "done": r["classified"],
                "pending": r["pending_reachable"], "problem": r["unreachable"],
                "latest_at": r["latest"].isoformat() if r["latest"] else None,
                "age_hours": _age_h(r["latest"], now),
                "state": _state(_age_h(r["latest"], now), has_backlog=r["pending_reachable"] > 0),
                "breakdown": [
                    {"label": "classified", "count": r["classified"], "tone": "ok"},
                    {"label": "pending", "count": r["pending_reachable"], "tone": "warn"},
                    # NOT pending. The classifier's queue has a 30-day floor, so
                    # nothing will ever pick these up. Counting them as "pending"
                    # would imply they are draining. They are not.
                    {"label": f"unreachable (>{_CLASSIFY_WINDOW_DAYS}d)",
                     "count": r["unreachable"], "tone": "bad"},
                ],
                "note": (f"The classifier only queues filed_at >= now()-{_CLASSIFY_WINDOW_DAYS}d. "
                         f"Older unclassified rows are unreachable, not pending — a backfill "
                         f"that ingests >30d of history strands them permanently."),
            })

            # ---- 3+4. DISCOVER / PARSE -------------------------------------
            r = await conn.fetchrow("""
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE parse_status='pending')          AS pending,
                       count(*) FILTER (WHERE parse_status='parsed')           AS parsed,
                       count(*) FILTER (WHERE parse_status='failed')           AS failed,
                       count(*) FILTER (WHERE parse_status='skipped_non_text') AS skipped,
                       count(*) FILTER (WHERE parse_status='failed'
                                          AND parse_attempts >= 5)             AS exhausted,
                       max(ingested_at) AS latest_discovered,
                       max(parsed_at)   AS latest_parsed
                  FROM nidp.documents""")
            stages.append({
                "id": "discover", "label": "Discover", "order": 3,
                "table": "nidp.documents",
                "total": r["total"], "done": r["total"], "pending": 0, "problem": 0,
                "latest_at": r["latest_discovered"].isoformat() if r["latest_discovered"] else None,
                "age_hours": _age_h(r["latest_discovered"], now),
                "state": _state(_age_h(r["latest_discovered"], now), has_backlog=False),
                "breakdown": [{"label": "documents registered", "count": r["total"], "tone": "ok"}],
                "note": "Attachment URLs discovered from announcements and queued for parse.",
            })
            stages.append({
                "id": "parse", "label": "Parse", "order": 4,
                "table": "nidp.documents.parse_status",
                "total": r["total"], "done": r["parsed"],
                "pending": r["pending"], "problem": r["exhausted"],
                "latest_at": r["latest_parsed"].isoformat() if r["latest_parsed"] else None,
                "age_hours": _age_h(r["latest_parsed"], now),
                "state": _state(_age_h(r["latest_parsed"], now), has_backlog=r["pending"] > 0),
                "breakdown": [
                    {"label": "parsed", "count": r["parsed"], "tone": "ok"},
                    {"label": "pending", "count": r["pending"], "tone": "warn"},
                    {"label": "failed (retrying)", "count": r["failed"] - r["exhausted"], "tone": "warn"},
                    # Burned the attempt cap: these will never be retried again.
                    {"label": "exhausted (>=5 tries)", "count": r["exhausted"], "tone": "bad"},
                    {"label": "skipped (no OCR)", "count": r["skipped"], "tone": "warn"},
                ],
                "note": "'failed' is retried while parse_attempts < 5; 'exhausted' never is.",
            })

            # ---- 5. CHUNK ---------------------------------------------------
            # LATERAL + LIMIT 1: existence, not a 524k-row join. Measured ~590ms.
            r = await conn.fetchrow("""
                SELECT count(*) FILTER (WHERE c.hit IS NOT NULL) AS chunked,
                       count(*) FILTER (WHERE c.hit IS NULL)     AS missing
                  FROM nidp.documents d
                  LEFT JOIN LATERAL (
                        SELECT 1 AS hit FROM nidp.document_chunks x
                         WHERE x.doc_id = d.doc_id LIMIT 1) c ON true
                 WHERE d.parse_status = 'parsed'""")
            rc = await conn.fetchrow("""
                SELECT count(*) AS chunks, max(ingested_at) AS latest
                  FROM nidp.document_chunks""")
            stages.append({
                "id": "chunk", "label": "Chunk", "order": 5,
                "table": "nidp.document_chunks",
                "total": r["chunked"] + r["missing"], "done": r["chunked"],
                "pending": 0, "problem": r["missing"],
                "latest_at": rc["latest"].isoformat() if rc["latest"] else None,
                "age_hours": _age_h(rc["latest"], now),
                "state": _state(_age_h(rc["latest"], now), has_backlog=r["missing"] > 0),
                "breakdown": [
                    {"label": "chunks", "count": rc["chunks"], "tone": "ok"},
                    {"label": "docs chunked", "count": r["chunked"], "tone": "ok"},
                    # A parsed doc with no chunks means the chunker silently
                    # produced nothing for text that extracted fine.
                    {"label": "parsed w/ 0 chunks", "count": r["missing"], "tone": "bad"},
                ],
                "note": "Chunks are written in the same transaction as parse_status='parsed'.",
            })

            # ---- 6. EMBED ---------------------------------------------------
            r = await conn.fetchrow("""
                SELECT count(*) AS chunks, count(embedding) AS embedded,
                       count(*) - count(embedding) AS unembedded,
                       max(embedded_at) AS latest
                  FROM nidp.document_chunks""")
            stages.append({
                "id": "embed", "label": "Embed", "order": 6,
                "table": "nidp.document_chunks.embedding",
                "total": r["chunks"], "done": r["embedded"],
                "pending": r["unembedded"], "problem": 0,
                "latest_at": r["latest"].isoformat() if r["latest"] else None,
                "age_hours": _age_h(r["latest"], now),
                "state": _state(_age_h(r["latest"], now), has_backlog=r["unembedded"] > 0),
                "breakdown": [
                    {"label": "embedded", "count": r["embedded"], "tone": "ok"},
                    {"label": "unembedded", "count": r["unembedded"], "tone": "warn"},
                ],
                # embed_pending() returns embedded:0 and logs a warning when the
                # key is missing or the API errors — it writes nothing either way.
                # So "outage" and "nothing to do" are identical in SQL, and the
                # only signal is unembedded staying flat while latest_embed ages.
                "note": ("An embedding outage looks identical to 'nothing to embed' in SQL — "
                         "embed_pending() swallows a missing key. Watch unembedded vs the "
                         "age of the last embed, not a success count."),
            })
    except Exception as e:  # noqa: BLE001 — a dashboard must degrade, not 500
        db_error = f"{type(e).__name__}: {e}"

    return {
        "generated_at": now.isoformat(),
        "stages": stages,
        "db_error": db_error,
        "summary": {
            "total": len(stages),
            "healthy": sum(1 for s in stages if s["state"] == "healthy"),
            "backlog": sum(1 for s in stages if s["state"] == "backlog"),
            "lagging": sum(1 for s in stages if s["state"] == "lagging"),
            "stale": sum(1 for s in stages if s["state"] == "stale"),
            "never": sum(1 for s in stages if s["state"] == "never"),
        },
    }


_ORDER = {"stale": 0, "never": 1, "lagging": 2, "backlog": 3, "healthy": 4}


def _worst(states: List[str]) -> str:
    if not states:
        return "never"
    return sorted(states, key=lambda s: _ORDER.get(s, 9))[0]
