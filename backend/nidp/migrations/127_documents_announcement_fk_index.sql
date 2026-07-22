-- 127_documents_announcement_fk_index.sql
-- Index the documents → corporate_announcements foreign-key columns.
--
-- documents has a composite FK (announcement_id, announcement_source) but Postgres
-- does not auto-index the referencing side. Every "given an announcement, find its
-- parsed document" lookup therefore SEQ-SCANS all ~144k documents. The filing_insights
-- generator's LATERAL join did exactly this once per material announcement (655 loops
-- × 144k rows) and took 107s — blowing the 30s asyncpg command_timeout.
--
-- This index turns that probe into an index scan. It also speeds the existing
-- document_parser back-reference and any future announcement→doc join. Additive.

SET search_path TO nidp, public;

CREATE INDEX IF NOT EXISTS idx_documents_announcement
    ON nidp.documents (announcement_id, announcement_source);

INSERT INTO nidp.schema_migrations(filename)
VALUES ('127_documents_announcement_fk_index.sql')
ON CONFLICT DO NOTHING;
