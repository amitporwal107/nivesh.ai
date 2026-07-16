-- 120_widen_document_ingest_window.sql
-- Widen the document_parser discovery window 30d -> 180d so historical concall
-- transcripts / investor presentations (the last ~2 quarters of results seasons)
-- enter the RAG corpus, not just the trailing month. This is the R2 coverage-gap
-- fix: single-company deep-dive + thematic questions need transcripts that are
-- often older than 30 days.
--
-- document_parser stays bounded per run (discover_limit=500, parse_limit=50), so
-- this backfills gradually across cron ticks rather than in one burst. Re-runnable.

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_announcements_needing_documents AS
SELECT a.*
  FROM nidp.corporate_announcements a
  LEFT JOIN nidp.documents d
         ON d.announcement_id = a.announcement_id
        AND d.announcement_source = a.source
 WHERE a.attachment_url IS NOT NULL
   AND d.doc_id IS NULL
   AND a.filed_at >= NOW() - INTERVAL '180 days';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('120_widen_document_ingest_window.sql')
ON CONFLICT DO NOTHING;
