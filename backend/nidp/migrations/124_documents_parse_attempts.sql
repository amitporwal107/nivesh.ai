-- 124_documents_parse_attempts.sql
-- Make document download/parse failures RETRYABLE with a bounded attempt count.
--
-- Root cause this fixes: document_parser's _parse_one marked ANY download failure
-- parse_status='failed', and fetch_pending_docs only re-queued 'pending' (plus
-- 'skipped_non_text' once OCR exists) — NEVER 'failed'. So a single transient blip
-- (NSE-archive slowness, a VM incident, a BSE rate-limit 403) permanently killed the
-- document. Measured on staging 2026-07-16: 18,574 of 18,579 documents stuck 'failed'
-- (16,482 nsearchives timeouts + 2,103 bseindia 403s) while 30/30 sampled failed URLs
-- still returned HTTP 200 — i.e. the whole RAG corpus was recoverable but never retried.
--
-- With this column the parser re-queues 'failed' docs until parse_attempts hits the cap
-- (NIDP_MAX_PARSE_ATTEMPTS, default 5): transient failures self-heal, while genuinely
-- gone URLs (BSE purges old AttachLive files -> 404) stop after the cap instead of
-- looping forever. Existing rows default to 0, so the current backlog becomes eligible
-- immediately and drains gradually across the */15 cron ticks. Additive + idempotent.

SET search_path TO nidp, public;

ALTER TABLE nidp.documents
    ADD COLUMN IF NOT EXISTS parse_attempts SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN nidp.documents.parse_attempts IS
    'Download/parse attempts made. fetch_pending_docs re-queues parse_status=''failed'' rows until this reaches NIDP_MAX_PARSE_ATTEMPTS (default 5), so transient failures self-heal and permanently-gone URLs stop retrying.';

-- Supports the retry sweep (failed docs still under the cap).
CREATE INDEX IF NOT EXISTS idx_doc_retryable
    ON nidp.documents(ingested_at)
    WHERE parse_status = 'failed';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('124_documents_parse_attempts.sql')
ON CONFLICT DO NOTHING;
