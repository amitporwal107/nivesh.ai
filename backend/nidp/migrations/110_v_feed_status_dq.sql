-- 110_v_feed_status_dq.sql
-- Surface the flag-only DQ verdict (decision #1: non-blocking) on v_feed_status.
-- The canonical DQ runner (nidp.services.quality_gate.dq_runner) writes a per-suite row
-- to nidp.validation_runs; this exposes the latest one per ingester as three columns on
-- the feed-status view. Ingest is unchanged — bad data still lands, now visibly flagged.
--
-- Mechanism: extract the current v_feed_status body into v_feed_status_base (verbatim),
-- then CREATE OR REPLACE v_feed_status as a thin wrapper that appends the DQ columns.
-- Re-runnable.

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
    ls.last_snapshot_date, ls.last_snapshot_rows, ls.last_snapshot_at
   FROM nidp.source_registry s
     LEFT JOIN last_run lr USING (ingester)
     LEFT JOIN last_snapshot ls USING (ingester);

-- Uses the per-ingester rollup nidp.v_feed_dq (migration 111) so feeds whose ingester
-- produces multiple assets (e.g. v3_scores_engine -> v3_stock + v3_mf) show the WORST
-- asset's verdict, not whichever suite ran last.
CREATE OR REPLACE VIEW nidp.v_feed_status AS
 SELECT fs.*,
    COALESCE(dq.dq_status, 'NONE')      AS last_dq_status,
    COALESCE(dq.dq_rules_failed, 0)::int AS last_dq_rules_failed,
    COALESCE(dq.dq_findings, 0)::int     AS last_dq_findings,
    dq.dq_checked_at                    AS last_dq_checked_at
   FROM nidp.v_feed_status_base fs
     LEFT JOIN nidp.v_feed_dq dq ON dq.ingester = fs.ingester;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('110_v_feed_status_dq.sql')
ON CONFLICT (filename) DO NOTHING;
