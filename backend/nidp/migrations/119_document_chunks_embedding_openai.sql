-- 119_document_chunks_embedding_openai.sql
-- Activate the semantic layer for document RAG.
--
-- Decision: embeddings are produced by OpenAI text-embedding-3-small (1536-dim),
-- reusing the existing OPENAI_API_KEY already on the VM (announcement classifier
-- uses it). The document_chunks.embedding column shipped as VECTOR(384) (a
-- planned bge-small default) but was NEVER populated — no embedder ran — so we
-- can safely widen it to 1536 while it is entirely NULL.
--
-- Also builds the two indexes hybrid retrieval needs:
--   * HNSW cosine index on the embedding (vector top-k)
--   * GIN full-text index on chunk text, 'english' config (keyword top-k)
--
-- Re-runnable: the ALTER is a no-op once the column is already vector(1536),
-- and both indexes are IF NOT EXISTS.

SET search_path TO nidp, public;

CREATE EXTENSION IF NOT EXISTS vector;

-- Widen the (empty) embedding column 384 -> 1536. All values are NULL today,
-- so the type change is a metadata-only operation.
DO $$
DECLARE
    n_embedded bigint;
BEGIN
    SELECT count(*) INTO n_embedded
      FROM nidp.document_chunks
     WHERE embedding IS NOT NULL;

    IF n_embedded > 0 THEN
        -- Guard: if some rows are already embedded at a different dim, do NOT
        -- silently truncate/break them — surface it loudly instead.
        RAISE NOTICE '119: % rows already embedded; leaving embedding column dim unchanged', n_embedded;
    ELSE
        ALTER TABLE nidp.document_chunks
            ALTER COLUMN embedding TYPE vector(1536);
    END IF;
END $$;

COMMENT ON COLUMN nidp.document_chunks.embedding IS
    'OpenAI text-embedding-3-small (1536-dim). Populated by document_parser.embed_pending.';

-- Vector top-k (cosine). Safe to build on an empty/partly-filled table; HNSW
-- grows incrementally as rows are embedded.
CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw
    ON nidp.document_chunks
 USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Keyword top-k for the hybrid retriever (matches the 'english' tsvector used
-- by feed_rag.retrievers.vector and the daas hybrid search).
CREATE INDEX IF NOT EXISTS idx_chunk_text_fts
    ON nidp.document_chunks
 USING gin (to_tsvector('english', text));

INSERT INTO nidp.schema_migrations(filename)
VALUES ('119_document_chunks_embedding_openai.sql')
ON CONFLICT DO NOTHING;
