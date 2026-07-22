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

FRESHNESS IS TRADING-TIME AWARE FOR MARKET-DRIVEN STAGES
--------------------------------------------------------
The ingesters run `*/10 9-23 * * 1-5` (nidp.cron) — weekdays only. Measured
against a wall clock, Friday 23:50 -> Monday 09:00 is a ~57h gap, so a 24h
budget painted Ingest/Classify/Discover red every single weekend. A monitor
that cries wolf two days in seven gets ignored on the day it is right.

So the three market-driven stages measure TRADING time, not wall time:
weekend and NSE-holiday hours are not counted. Parse/Chunk/Embed keep
wall-clock budgets — they grind through backlog seven days a week.

INGEST MEASURES filed_at, NOT ingested_at
-----------------------------------------
corporate_announcements/writer.py does `ON CONFLICT ... DO UPDATE SET
ingested_at = NOW()`, so ingested_at bumps on every RE-SEEN row. Keying the
Ingest tile off max(ingested_at) therefore reported "the cron touched a row",
not "new data arrived" — a feed weeks behind on filings read healthy forever.
That is the same class of lie as trusting a zero exit code, just one layer in.
max(filed_at) vs the last NSE close is the honest signal, and the query was
already selecting it.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Optional

from fastapi import APIRouter, Depends

from nidp.services.query_api.auth import require_bearer
from nidp.shared.storage.pg import get_pool
from nidp.shared.trading_day import default_target_date

router = APIRouter(prefix="", tags=["pipeline"], dependencies=[Depends(require_bearer)])

# The classifier's queue floor: announcement_classifier/db.py selects
# WHERE event_category IS NULL AND filed_at >= NOW() - INTERVAL '30 days'.
# Anything older that is unclassified is not "pending" — it is unreachable.
_CLASSIFY_WINDOW_DAYS = 30

# The backfill's operational window (ray_day_backfill --since-days). Documents
# filed outside it are NOT going to be parsed, so reporting them as "pending"
# claims a queue is draining when nothing will ever touch it — the same lie the
# classify tile avoids by splitting out 'unreachable'. Kept equal to the classify
# window on purpose: parsing a document whose announcement can never be
# classified produces a corpus row nothing can reason about.
_BACKFILL_WINDOW_DAYS = int(os.environ.get("NIDP_BACKFILL_WINDOW_DAYS", "30"))

# Freshness budgets, in hours, per stage. Deliberately generous: these catch
# "this stage is dead", not "this stage is a bit behind". For market-driven
# stages these are TRADING hours (see _trading_hours_between).
_LAG_WARN_H = 6.0
_LAG_BAD_H = 24.0

# Ingest is measured in whole trading days behind the last NSE close rather than
# in hours: filings arrive in bursts across a session, so an hours budget would
# flap. One full trading session with zero new filings is worth a warning; two
# means the feed is not running.
_FILED_WARN_D = 1
_FILED_BAD_D = 2

IST = timezone(timedelta(hours=5, minutes=30))

# Walking day-by-day past this is pointless: every threshold has long since
# tripped, and an unbounded loop on a garbage timestamp is a hang.
_WALK_CAP_DAYS = 400


def _age_h(ts: Optional[datetime], now: datetime) -> Optional[float]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return round((now - ts).total_seconds() / 3600.0, 2)


def _is_trading_day(d: date, holidays: FrozenSet[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def _trading_hours_between(
    start: Optional[datetime], end: datetime, holidays: FrozenSet[date]
) -> Optional[float]:
    """Hours between `start` and `end` that fall on an NSE trading day (IST).

    Weekend and holiday time is not counted, so a stage that legitimately had
    nothing to do over a weekend does not age into 'stale'. Returns wall-clock
    hours beyond _WALK_CAP_DAYS — past that every budget has tripped anyway and
    the exact figure is noise.
    """
    if start is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end <= start:
        return 0.0
    if (end - start).days > _WALK_CAP_DAYS:
        return round((end - start).total_seconds() / 3600.0, 2)

    s, e = start.astimezone(IST), end.astimezone(IST)
    total = 0.0
    day = s.date()
    while day <= e.date():
        if _is_trading_day(day, holidays):
            day_start = datetime.combine(day, time.min, tzinfo=IST)
            lo, hi = max(s, day_start), min(e, day_start + timedelta(days=1))
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600.0
        day += timedelta(days=1)
    return round(total, 2)


def _trading_days_behind(
    latest_filed: Optional[datetime], last_close: date, holidays: FrozenSet[date]
) -> Optional[int]:
    """Trading sessions that closed after `latest_filed` without a new filing.

    Counts trading days strictly after latest_filed's IST date through
    `last_close` inclusive. 0 means the feed has everything the market has
    produced — which is the correct reading on a Sunday, when the last close is
    Friday and Friday's filings are in.
    """
    if latest_filed is None:
        return None
    if latest_filed.tzinfo is None:
        latest_filed = latest_filed.replace(tzinfo=timezone.utc)
    filed_day = latest_filed.astimezone(IST).date()
    if filed_day >= last_close:
        return 0
    if (last_close - filed_day).days > _WALK_CAP_DAYS:
        return _WALK_CAP_DAYS
    return sum(
        1
        for i in range((last_close - filed_day).days)
        if _is_trading_day(filed_day + timedelta(days=i + 1), holidays)
    )


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


def _filed_state(days_behind: Optional[int]) -> str:
    """State for a stage measured in trading days behind the last close."""
    if days_behind is None:
        return "never"
    if days_behind >= _FILED_BAD_D:
        return "stale"
    if days_behind >= _FILED_WARN_D:
        return "lagging"
    return "healthy"


async def _market_calendar(conn) -> tuple:
    """(last_close_date, holidays) from the DB, with a degraded fallback.

    A missing/empty nidp.nse_holidays must not blank the whole panel, so this
    falls back to the weekday-only calendar (default_target_date + no holidays).
    That is strictly better than the wall-clock behaviour it replaces: it still
    discounts weekends, it just cannot see a Diwali.
    """
    try:
        last_close = await conn.fetchval(
            "SELECT nidp.compute_last_trading_day_ist()")
        rows = await conn.fetch(
            "SELECT holiday_date FROM nidp.nse_holidays "
            " WHERE holiday_date >= current_date - $1::int", _WALK_CAP_DAYS)
        return last_close or default_target_date(), frozenset(
            r["holiday_date"] for r in rows)
    except Exception:  # noqa: BLE001 — degrade, never blank the panel
        return default_target_date(), frozenset()


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
            last_close, holidays = await _market_calendar(conn)

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
            newest_filed: Optional[datetime] = None
            for r in rows:
                ingest_total += r["total"]
                if r["latest_ingest"] and (newest_ingest is None or r["latest_ingest"] > newest_ingest):
                    newest_ingest = r["latest_ingest"]
                if r["latest_filed"] and (newest_filed is None or r["latest_filed"] > newest_filed):
                    newest_filed = r["latest_filed"]
                behind = _trading_days_behind(r["latest_filed"], last_close, holidays)
                by_source.append({
                    "source": r["source"],
                    "total": r["total"],
                    "latest_filed": r["latest_filed"].isoformat() if r["latest_filed"] else None,
                    "latest_at": r["latest_ingest"].isoformat() if r["latest_ingest"] else None,
                    # Wall-clock, for display only — "2d ago" is what an operator
                    # reads. State comes from trading_days_behind.
                    "age_hours": _age_h(r["latest_ingest"], now),
                    "trading_days_behind": behind,
                    # Per-source state: the whole reason this stage is split. A
                    # healthy NSE must not mask a dead BSE by averaging with it.
                    "state": _filed_state(behind),
                })
            ingest_behind = _trading_days_behind(newest_filed, last_close, holidays)
            stages.append({
                "id": "ingest", "label": "Ingest", "order": 1,
                "table": "nidp.corporate_announcements",
                "total": ingest_total, "done": ingest_total, "pending": 0, "problem": 0,
                "latest_at": newest_ingest.isoformat() if newest_ingest else None,
                "latest_filed": newest_filed.isoformat() if newest_filed else None,
                "age_hours": _age_h(newest_ingest, now),
                "trading_days_behind": ingest_behind,
                "last_close": last_close.isoformat() if last_close else None,
                # Worst source wins — an aggregate that hides a dead feed is the bug.
                "state": _worst([s["state"] for s in by_source]),
                "breakdown": by_source,
                "note": ("NSE and BSE are separate crons; the worst source sets the state. "
                         "Measured as trading days between the newest filed_at and the last "
                         "NSE close — NOT time since the last ingest run, because the writer "
                         "bumps ingested_at on every re-seen row, so that clock stays fresh "
                         "even when no new filing has arrived in weeks."),
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
                "trading_age_hours": _trading_hours_between(r["latest"], now, holidays),
                # Trading hours, not wall hours: the classifier runs */30 all week
                # but is fed by a weekday-only ingester, so an idle weekend is not
                # a regression.
                "state": _state(_trading_hours_between(r["latest"], now, holidays),
                                has_backlog=r["pending_reachable"] > 0),
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
            r = await conn.fetchrow(f"""
                WITH w AS (SELECT now() - interval '{_BACKFILL_WINDOW_DAYS} days' AS floor)
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE parse_status='pending')          AS pending,
                       count(*) FILTER (WHERE parse_status='parsed')           AS parsed,
                       count(*) FILTER (WHERE parse_status='failed')           AS failed,
                       count(*) FILTER (WHERE parse_status='skipped_non_text') AS skipped,
                       count(*) FILTER (WHERE parse_status='failed'
                                          AND parse_attempts >= 5)             AS exhausted,
                       -- In the backfill's window = actually queued to be parsed.
                       count(*) FILTER (WHERE parse_status='pending'
                                          AND filed_at >= (SELECT floor FROM w)) AS pending_in_window,
                       -- Outside it = nothing will ever pick these up under the
                       -- current --since-days cap. Not pending. Out of scope.
                       count(*) FILTER (WHERE parse_status='pending'
                                          AND filed_at <  (SELECT floor FROM w)) AS pending_out_of_scope,
                       max(ingested_at) AS latest_discovered,
                       max(parsed_at)   AS latest_parsed
                  FROM nidp.documents""")
            stages.append({
                "id": "discover", "label": "Discover", "order": 3,
                "table": "nidp.documents",
                "total": r["total"], "done": r["total"], "pending": 0, "problem": 0,
                "latest_at": r["latest_discovered"].isoformat() if r["latest_discovered"] else None,
                "age_hours": _age_h(r["latest_discovered"], now),
                "trading_age_hours": _trading_hours_between(r["latest_discovered"], now, holidays),
                # Discovery reads announcements, so it inherits their weekday-only
                # cadence — same trading-time treatment as Classify.
                "state": _state(_trading_hours_between(r["latest_discovered"], now, holidays),
                                has_backlog=False),
                "breakdown": [{"label": "documents registered", "count": r["total"], "tone": "ok"}],
                "note": "Attachment URLs discovered from announcements and queued for parse.",
            })
            stages.append({
                "id": "parse", "label": "Parse", "order": 4,
                "table": "nidp.documents.parse_status",
                "total": r["total"], "done": r["parsed"],
                # 'pending' is the IN-WINDOW queue only — the work that will
                # actually happen. Reporting the raw pending count here would
                # imply 84k docs are draining when the cap means they are not.
                "pending": r["pending_in_window"],
                "problem": r["exhausted"],
                "latest_at": r["latest_parsed"].isoformat() if r["latest_parsed"] else None,
                "age_hours": _age_h(r["latest_parsed"], now),
                "state": _state(_age_h(r["latest_parsed"], now),
                                has_backlog=r["pending_in_window"] > 0),
                "breakdown": [
                    {"label": "parsed", "count": r["parsed"], "tone": "ok"},
                    {"label": f"pending (last {_BACKFILL_WINDOW_DAYS}d)",
                     "count": r["pending_in_window"], "tone": "warn"},
                    {"label": f"out of scope (>{_BACKFILL_WINDOW_DAYS}d)",
                     "count": r["pending_out_of_scope"], "tone": "bad"},
                    {"label": "failed (retrying)", "count": r["failed"] - r["exhausted"], "tone": "warn"},
                    # Burned the attempt cap: these will never be retried again.
                    {"label": "exhausted (>=5 tries)", "count": r["exhausted"], "tone": "bad"},
                    {"label": "skipped (no OCR)", "count": r["skipped"], "tone": "warn"},
                ],
                "note": (f"Backfill is capped at --since-days {_BACKFILL_WINDOW_DAYS}, matching the "
                         f"classifier window. 'out of scope' docs are NOT queued — nothing will "
                         f"parse them while the cap holds. 'failed' retries while parse_attempts "
                         f"< 5; 'exhausted' never does."),
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
