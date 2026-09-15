-- 135_source_registry_dedupe_and_staleness.sql
--
-- Two defects, one table. Both make v_feed_status report health it cannot know.
--
-- (1) DUPLICATE ROWS. nidp.source_registry is keyed on source_name, but
--     job_log.finalize() upserts with `VALUES ($1, $1, ...) ON CONFLICT
--     (source_name)` where $1 is the INGESTER name. For every feed seeded by
--     migration 022/033 under a curated source_name ('NSE_BHAVCOPY', ingester
--     'bhavcopy'), that conflict target can never match — so on 2026-06-01 the
--     writer inserted a SECOND row per feed ('bhavcopy') and has updated only
--     that one ever since. The curated row froze on 2026-05-27 still reading
--     last_run_status = 'OK', because nothing has run to mark it otherwise.
--     20 feeds are split this way. NSE_FINANCIALS is the expensive one: it
--     reads OK while having produced nothing since May, which is why nobody
--     noticed fundamentals were capped at ~700 of 2,168 symbols.
--
--     The two rows are not interchangeable. The curated row holds the real
--     source_url_pattern, source_class, confidence and schedule_cron; the
--     auto-created stub has an empty URL, source_class 'derived' and a
--     hardcoded confidence of 1.00 — a value no consumer should trust, since
--     it is asserted rather than assessed. So this merges rather than deletes:
--     curated metadata is kept, live counters are carried over from the stub,
--     the stub is dropped, and a UNIQUE (ingester) constraint plus the matching
--     ON CONFLICT target in job_log.py stop the split recurring.
--
-- (2) NO FRESHNESS RULE. last_run_status records the outcome of the last run
--     that HAPPENED. A feed that stops running keeps its last verdict forever,
--     so silence reads as success. v_feed_status gains staleness_days and an
--     effective_status that returns STALE when a feed is overdue against its
--     own expected_freq. That is the part that generalises: it catches the
--     next feed to stop quietly, not just these twenty.
--
-- Re-runnable.

BEGIN;

-- ── 1. Merge each split pair into its curated row ────────────────────────
-- Carry the stub's activity onto the curated row. Counters are summed because
-- both rows counted real runs of the same ingester. Timestamps take the later
-- of the two. The last_run_* fields are taken as a set from whichever row ran
-- most recently, so status/id/duration stay consistent with each other rather
-- than being mixed across two different runs.
WITH pairs AS (
    SELECT curated.source_name AS keep_name,
           stub.source_name    AS drop_name,
           stub.last_run_at    AS stub_run_at,
           stub.last_run_id, stub.last_run_status, stub.last_run_duration_ms,
           stub.success_count, stub.partial_count, stub.failure_count,
           stub.consecutive_failures,
           stub.last_success_at, stub.last_failure_at
      FROM nidp.source_registry curated
      JOIN nidp.source_registry stub
        ON stub.ingester = curated.ingester
       AND stub.source_name = stub.ingester      -- the auto-created stub
       AND curated.source_name <> curated.ingester -- the curated seed
)
UPDATE nidp.source_registry r
   SET success_count        = r.success_count + p.success_count,
       partial_count        = r.partial_count + p.partial_count,
       failure_count        = r.failure_count + p.failure_count,
       last_success_at      = GREATEST(r.last_success_at, p.last_success_at),
       last_failure_at      = GREATEST(r.last_failure_at, p.last_failure_at),
       -- Take the whole last-run tuple from the row that ran last.
       last_run_at          = GREATEST(r.last_run_at, p.stub_run_at),
       last_run_id          = CASE WHEN p.stub_run_at >= COALESCE(r.last_run_at, '-infinity')
                                   THEN p.last_run_id ELSE r.last_run_id END,
       last_run_status      = CASE WHEN p.stub_run_at >= COALESCE(r.last_run_at, '-infinity')
                                   THEN p.last_run_status ELSE r.last_run_status END,
       last_run_duration_ms = CASE WHEN p.stub_run_at >= COALESCE(r.last_run_at, '-infinity')
                                   THEN p.last_run_duration_ms ELSE r.last_run_duration_ms END,
       consecutive_failures = CASE WHEN p.stub_run_at >= COALESCE(r.last_run_at, '-infinity')
                                   THEN p.consecutive_failures ELSE r.consecutive_failures END,
       updated_at           = now()
  FROM pairs p
 WHERE r.source_name = p.keep_name;

DELETE FROM nidp.source_registry stub
 USING nidp.source_registry curated
 WHERE stub.ingester = curated.ingester
   AND stub.source_name = stub.ingester
   AND curated.source_name <> curated.ingester;

-- One row per ingester from here on. This is what makes the ON CONFLICT
-- (ingester) target in shared/storage/job_log.py legal, and it is the
-- constraint that actually prevents a recurrence.
CREATE UNIQUE INDEX IF NOT EXISTS source_registry_ingester_key
    ON nidp.source_registry (ingester);

-- ── 2. Staleness on the view ────────────────────────────────────────────
CREATE OR REPLACE VIEW nidp.v_feed_status_base AS
 WITH last_run AS (
         SELECT DISTINCT ON (job_log.ingester) job_log.ingester,
            job_log.run_id AS last_run_id,
            job_log.target_date AS last_target_date,
            job_log.status AS last_status,
            job_log.started_at AS last_started_at,
            job_log.finished_at AS last_finished_at,
            job_log.duration_ms AS last_duration_ms,
            job_log.rows_fetched AS last_rows_fetched,
            job_log.rows_inserted AS last_rows_inserted,
            job_log.rows_skipped AS last_rows_skipped,
            job_log.error_message AS last_error_message,
            job_log.artifact_path AS last_artifact_path
           FROM nidp.job_log
          ORDER BY job_log.ingester, job_log.started_at DESC
        ), last_snapshot AS (
         SELECT DISTINCT ON (feed_snapshot.ingester) feed_snapshot.ingester,
            feed_snapshot.snapshot_date AS last_snapshot_date,
            feed_snapshot.row_count AS last_snapshot_rows,
            feed_snapshot.captured_at AS last_snapshot_at
           FROM nidp.feed_snapshot
          ORDER BY feed_snapshot.ingester, feed_snapshot.snapshot_date DESC
        )
 SELECT s.source_name, s.ingester, s.source_class, s.confidence, s.expected_freq,
    s.schedule_cron, s.is_primary, s.last_success_at, s.last_failure_at,
    s.consecutive_failures, s.success_count, s.failure_count, s.partial_count,
    s.last_run_at, s.next_run_at, s.last_run_status, s.last_run_duration_ms,
    lr.last_run_id, lr.last_target_date, lr.last_started_at, lr.last_finished_at,
    lr.last_rows_fetched, lr.last_rows_inserted, lr.last_rows_skipped,
    lr.last_error_message, lr.last_artifact_path,
    ls.last_snapshot_date, ls.last_snapshot_rows, ls.last_snapshot_at,

    -- Whole days since this feed last produced anything. NULL when it has
    -- never succeeded, which is a different condition from "stale" and must
    -- not be flattened into one.
    (EXTRACT(EPOCH FROM (now() - s.last_success_at)) / 86400)::int
        AS staleness_days,

    -- How long this feed may go quiet before silence means something is
    -- wrong. Generous against each cadence — a daily feed is allowed a long
    -- weekend plus a holiday, a monthly one a late publication — because a
    -- false STALE trains people to ignore the column.
    CASE s.expected_freq
        WHEN 'high-freq' THEN 1
        WHEN 'daily'     THEN 4
        WHEN 'weekly'    THEN 10
        WHEN 'monthly'   THEN 45
        WHEN 'quarterly' THEN 120
        ELSE NULL                      -- 'manual'/'event': silence is normal
    END AS staleness_budget_days,

    -- The status a human should act on. last_run_status answers "how did the
    -- last run go"; this answers "is this feed working", and they diverge
    -- precisely when a feed stops being invoked at all.
    CASE
        WHEN s.expected_freq IN ('manual', 'event') THEN COALESCE(s.last_run_status, 'IDLE')
        WHEN s.last_success_at IS NULL THEN 'NEVER_SUCCEEDED'
        WHEN (EXTRACT(EPOCH FROM (now() - s.last_success_at)) / 86400)::int >
             CASE s.expected_freq
                 WHEN 'high-freq' THEN 1
                 WHEN 'daily'     THEN 4
                 WHEN 'weekly'    THEN 10
                 WHEN 'monthly'   THEN 45
                 WHEN 'quarterly' THEN 120
             END THEN 'STALE'
        ELSE COALESCE(s.last_run_status, 'UNKNOWN')
    END AS effective_status
   FROM nidp.source_registry s
     LEFT JOIN last_run lr USING (ingester)
     LEFT JOIN last_snapshot ls USING (ingester);

CREATE OR REPLACE VIEW nidp.v_feed_status AS
 SELECT fs.*,
    COALESCE(dq.dq_status, 'NONE')      AS last_dq_status,
    COALESCE(dq.dq_rules_failed, 0)::int AS last_dq_rules_failed,
    COALESCE(dq.dq_findings, 0)::int     AS last_dq_findings,
    dq.dq_checked_at                    AS last_dq_checked_at
   FROM nidp.v_feed_status_base fs
     LEFT JOIN nidp.v_feed_dq dq ON dq.ingester = fs.ingester;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('135_source_registry_dedupe_and_staleness.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
