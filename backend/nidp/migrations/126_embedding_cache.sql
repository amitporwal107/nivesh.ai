-- 126: embedding_cache — content-addressed memoization for chunk embeddings.
--
-- An embedding is a PURE FUNCTION of (normalized_text, model, dims), so this is
-- memoization with durable storage, not a cache that can go stale. Keying on the
-- content (never chunk_id/url/timestamp) is what makes it work: when the Ray
-- parser re-parses a source and produces the same chunk text again, it hits.
--
-- WHY (measured on staging 2026-07-19, 30-day scope):
--   289,628 unembedded chunks -> 208,437 unique texts = 81,191 duplicates (28.0%).
-- So more than a quarter of the backfill is re-embedding text we already paid for.
-- The same structure gives dedup, retry-safety, re-parse handling and cost saving
-- at once.
--
-- model+dims are baked INTO the hash by the writer, so a model or dimension change
-- simply stops hitting old rows — no invalidation logic, no stale vectors. They are
-- also stored as columns for observability/cleanup.
--
-- No HNSW index here: this table is only ever probed by primary key
-- (WHERE content_hash = ANY($1)), never searched by similarity.

BEGIN;
SET search_path TO nidp, public;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS nidp.embedding_cache (
    content_hash TEXT        PRIMARY KEY,   -- sha256(model:dims:normalized_text)
    embedding    vector(768) NOT NULL,
    model        TEXT        NOT NULL,
    dims         INT         NOT NULL,
    token_count  INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE nidp.embedding_cache IS
  'Content-addressed embedding memoization. Key = sha256(model:dims:normalized_text). '
  'Probed by PK only. 28% of the 30-day backfill was duplicate text (measured 2026-07-19).';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('126_embedding_cache.sql') ON CONFLICT DO NOTHING;
COMMIT;
