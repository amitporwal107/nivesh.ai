-- 031_nidp_documents.sql — Document intelligence ingestion (S5 Week 1).
--
-- Two tables and pgvector:
--   nidp.documents        — one row per ingested PDF (announcement attachment,
--                           annual report, concall transcript, investor deck)
--   nidp.document_chunks  — text chunks ready for embedding + retrieval
--
-- The embedder service (next sprint) populates document_chunks.embedding;
-- this migration leaves it NULLable so the parser can ship rows without
-- waiting on the embedding pipeline.
--
-- Cross-link to S4: documents.announcement_id + announcement_source point
-- back to nidp.corporate_announcements when the document arrived as a
-- filing attachment (~95% of inputs initially). Standalone documents
-- (manually curated annual reports, concall PDFs from IR sites) leave
-- those NULL.

SET search_path TO nidp, public;

-- pgvector ships in Cloud SQL Postgres ≥15 with the `vector` extension flag
-- enabled. If this CREATE fails, enable the flag in Cloud SQL → Flags.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS nidp.documents (
    doc_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source
    source_url          TEXT NOT NULL,                  -- canonical PDF URL
    doc_type            TEXT NOT NULL,                  -- 'announcement_attachment' | 'annual_report' | 'concall_transcript' | 'investor_presentation'

    -- Cross-link to S4 (NULL for non-announcement documents)
    announcement_id     TEXT,
    announcement_source TEXT,                           -- 'NSE_ANN' | 'BSE_ANN' — composite FK target

    -- Entity (denormalised from announcement for fast filter)
    ticker_symbol       TEXT,
    isin                TEXT,
    scrip_code          TEXT,
    company_name        TEXT,
    filed_at            TIMESTAMPTZ,                    -- when the document was published, not ingested

    -- Raw + parsed state
    raw_sha256          TEXT,                           -- bytes hash of the downloaded PDF
    raw_size_bytes      BIGINT,
    text_size_chars     INTEGER,
    page_count          INTEGER,
    parse_status        TEXT NOT NULL DEFAULT 'pending',-- 'pending' | 'parsed' | 'failed' | 'skipped_non_text'
    parse_error         TEXT,
    parsed_at           TIMESTAMPTZ,

    -- Provenance
    source_run_id       UUID NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (source_url),
    FOREIGN KEY (announcement_id, announcement_source)
        REFERENCES nidp.corporate_announcements(announcement_id, source)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_doc_filed_at
    ON nidp.documents(filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_doc_ticker
    ON nidp.documents(ticker_symbol, filed_at DESC)
    WHERE ticker_symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doc_scrip
    ON nidp.documents(scrip_code, filed_at DESC)
    WHERE scrip_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doc_pending
    ON nidp.documents(ingested_at)
    WHERE parse_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_doc_type_filed
    ON nidp.documents(doc_type, filed_at DESC);


CREATE TABLE IF NOT EXISTS nidp.document_chunks (
    chunk_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES nidp.documents(doc_id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,                   -- 0-based ordinal within doc
    text            TEXT NOT NULL,
    char_start      INTEGER,                            -- byte offset in source text
    char_end        INTEGER,
    page_start      INTEGER,                            -- 1-based; NULL if cross-page
    page_end        INTEGER,
    token_count     INTEGER,                            -- approx; cl100k tokenizer at parse time

    -- Embedding (populated by separate embedder service)
    embedding       VECTOR(384),                        -- bge-small-en-v1.5 (default model)
    embedding_model TEXT,                               -- 'bge-small-en-v1.5' etc — for re-embedding bookkeeping
    embedded_at     TIMESTAMPTZ,

    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (doc_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunk_doc
    ON nidp.document_chunks(doc_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunk_unembedded
    ON nidp.document_chunks(ingested_at)
    WHERE embedding IS NULL;

-- HNSW index for cosine-similarity vector search. Built lazily once we
-- have a meaningful corpus; CREATE INDEX CONCURRENTLY in a follow-up
-- migration when chunk count > 50K to avoid a long lock here.
-- CREATE INDEX idx_chunk_embedding_hnsw ON nidp.document_chunks
--     USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);


-- ── v_documents_pending ─────────────────────────────────────────────
-- Drives the parser worker: announcement_attachments awaiting parse,
-- newest first.
CREATE OR REPLACE VIEW nidp.v_documents_pending AS
SELECT *
  FROM nidp.documents
 WHERE parse_status = 'pending'
 ORDER BY ingested_at DESC;

-- ── v_announcements_needing_documents ───────────────────────────────
-- Drives the document discoverer: announcements with PDFs that haven't
-- been registered as documents yet.
CREATE OR REPLACE VIEW nidp.v_announcements_needing_documents AS
SELECT a.*
  FROM nidp.corporate_announcements a
  LEFT JOIN nidp.documents d
         ON d.announcement_id = a.announcement_id
        AND d.announcement_source = a.source
 WHERE a.attachment_url IS NOT NULL
   AND d.doc_id IS NULL
   AND a.filed_at >= NOW() - INTERVAL '30 days';

INSERT INTO nidp.schema_migrations(filename) VALUES ('031_nidp_documents.sql')
ON CONFLICT DO NOTHING;
