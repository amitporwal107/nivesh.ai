-- 125: document_chunks.embedding — OpenAI 1536-dim back to self-hosted bge-small 384-dim.
--
-- WHY REVERT 119
-- --------------
-- 119 widened the (then-empty) VECTOR(384) column to 1536 for OpenAI
-- text-embedding-3-small. Its own header records the reason honestly: the column
-- "shipped as VECTOR(384) (a planned bge-small default) but was NEVER populated
-- — no embedder ran". OpenAI was the expedient substitute for an embedder nobody
-- had built. Two things measured on 2026-07-17 make 1536 the wrong answer here:
--
--   1. IT DOES NOT FIT. Vectors alone, at float4 x dims x 669,470 rows:
--          384 -> 981MB      1536 -> 3923MB
--      plus an HNSW index of comparable size, on top of the existing 1.7GB
--      table, against 8.5G free on the NFS share that holds this database. This
--      VM's documented failure mode is a disk-full crash-looping Postgres.
--      The 384-dim column is the only one with headroom.
--
--   2. NOTHING IS LOST. The 512-token cap of bge-small clips exactly 10 of
--      668,621 chunks (0.0%) — the chunker already caps at ~2000 chars — and
--      bge-small scores within ~1 MTEB retrieval point of text-embedding-3-small.
--
-- The 8,000 rows embedded by OpenAI are DISCARDED, not converted. There is no
-- projection from a 1536-dim space to a 384-dim one: the vectors are not
-- compatible, and leaving both in one index would return silently meaningless
-- similarity scores. Re-embedding all 669k chunks locally costs CPU, not money.
--
-- Re-runnable: every step is guarded on current state.

BEGIN;

-- 1. Drop the HNSW index BEFORE the type change. Altering a column type under a
--    live vector index is what corrupts it; rebuilding after is cheap because
--    the column is empty at that point anyway.
DROP INDEX IF EXISTS nidp.idx_chunk_embedding_hnsw;

-- 2. Clear the OpenAI vectors. This is the step that makes the ALTER legal (and
--    is exactly the precondition 119 relied on in the other direction).
UPDATE nidp.document_chunks
   SET embedding = NULL, embedding_model = NULL, embedded_at = NULL
 WHERE embedding IS NOT NULL;

-- 3. Narrow 1536 -> 384. Guarded so a re-run on an already-384 column is a no-op.
-- format_type() renders the declared type as 'vector(1536)' / 'vector(384)' —
-- the only portable way to read a pgvector dimension from the catalog. (Do not
-- reach for information_schema.character_maximum_length: it is NULL for vector.)
DO $$
BEGIN
    IF (SELECT format_type(a.atttypid, a.atttypmod)
          FROM pg_attribute a
         WHERE a.attrelid = 'nidp.document_chunks'::regclass
           AND a.attname  = 'embedding'
           AND NOT a.attisdropped) IS DISTINCT FROM 'vector(384)' THEN
        ALTER TABLE nidp.document_chunks
            ALTER COLUMN embedding TYPE vector(384);
    END IF;
END $$;

COMMENT ON COLUMN nidp.document_chunks.embedding IS
    'bge-small-en-v1.5 (384-dim), self-hosted ONNX on CPU. Populated by '
    'document_parser.embed_pending via nidp.shared.embeddings_local. No API key '
    'or quota involved. Vectors are L2-normalised (CLS pooling) for cosine.';

-- 4. Rebuild the vector index at the new dimension. Safe on an empty table;
--    HNSW grows incrementally as embed_pending fills rows.
CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw
    ON nidp.document_chunks
 USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- The FTS index is dimension-independent and stays as 119 built it — it is what
-- keeps the corpus keyword-searchable while embeddings backfill.

INSERT INTO nidp.schema_migrations(filename)
VALUES ('125_document_chunks_embedding_bge_small.sql')
ON CONFLICT DO NOTHING;

COMMIT;
