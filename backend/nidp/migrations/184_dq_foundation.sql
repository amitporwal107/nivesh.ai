-- 184: DQ foundation — feed DQ status that is never empty, and Gate 1 floors that match the feed validators.
--
-- ── 1. v_feed_dq ignored every validation run ────────────────────────────────────────────────
-- Migration 111 added validation_runs.asset and built v_feed_dq from rows WHERE asset IS NOT NULL, but the per-ingest
-- validation runner never wrote an asset, so the view was empty and nidp.v_feed_status.last_dq_status read NONE for
-- all 59 feeds (measured 2026-10-28). The runner now writes asset = ingester; this view also reads the older rows with
-- no asset as the ingester's own asset, so the status is right immediately, not only after each feed's next run.
--
-- ── 2. Gate 1 used its hard-coded "something is deeply wrong" floors ─────────────────────────
-- dq.feed_sla had no gate_id = 1 rows (077 seeded gate 3 only), so Gate 1 checked bhavcopy against 1,000 rows and the
-- F&O bhavcopy against 100. These rows make the gate (which runs BEFORE the write) use the validators' floors. Each
-- floor was checked against every Gate 1 run on staging (dq.gate_verdicts, Apr 2024 – Oct 2026), and every real
-- session clears it:
--     bhavcopy      lowest 2,697 rows   floor 1,500
--     delivery      lowest 2,531        floor 1,500
--     fno_bhavcopy  lowest 29,088       floor 25,000 (post-expiry days; the old 30,000 validator floor is lowered too)
--     index_close   lowest 111          floor 20
-- A holiday's empty file is SKIPPED before the gate and never reaches it.
--
-- Re-runnable.

CREATE OR REPLACE VIEW nidp.v_feed_dq AS
WITH latest_per_asset AS (
    SELECT DISTINCT ON (ingester, COALESCE(asset, ingester))
        ingester, COALESCE(asset, ingester) AS asset, status, rules_failed, findings_count, started_at
    FROM nidp.validation_runs
    ORDER BY ingester, COALESCE(asset, ingester), started_at DESC
)
SELECT
    ingester,
    CASE max(CASE status WHEN 'ERROR'  THEN 4 WHEN 'FAILED'  THEN 3
                         WHEN 'PARTIAL' THEN 2 WHEN 'PASSED' THEN 1 ELSE 0 END)
        WHEN 4 THEN 'ERROR' WHEN 3 THEN 'FAILED' WHEN 2 THEN 'PARTIAL'
        WHEN 1 THEN 'PASSED' ELSE 'NONE' END  AS dq_status,   -- worst wins
    count(*)            AS dq_assets,
    sum(rules_failed)   AS dq_rules_failed,
    sum(findings_count) AS dq_findings,
    max(started_at)     AS dq_checked_at
FROM latest_per_asset
GROUP BY ingester;

INSERT INTO dq.feed_sla (feed, gate_id, row_count_min, notes)
VALUES
    ('bhavcopy',     1,  1500, 'Gate 1 floor = bhavcopy.row_count_min validator (EQ/BE/BZ/SM >= 1500)'),
    ('fno_bhavcopy', 1, 25000, 'Gate 1 floor = fno_bhavcopy.row_count_min validator (>= 25000); lowest real day 29,088'),
    ('delivery',     1,  1500, 'Gate 1 floor = delivery.row_count_min validator (>= 1500)'),
    ('index_close',  1,    20, 'Gate 1 floor = index_close.row_count_min validator (>= 20)')
ON CONFLICT (feed, gate_id) DO UPDATE
    SET row_count_min = EXCLUDED.row_count_min,
        notes         = EXCLUDED.notes,
        updated_at    = now();

INSERT INTO nidp.schema_migrations (filename)
VALUES ('184_dq_foundation.sql')
ON CONFLICT (filename) DO NOTHING;
