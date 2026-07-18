-- 125: document_chunks.embedding — OpenAI 1536-dim to self-hosted bge-base 768-dim.
--
-- WHY (measured on staging 2026-07-18)
-- ------------------------------------
-- 119 widened the (empty) VECTOR(384) column to 1536 for OpenAI
-- text-embedding-3-small. Two facts made 1536 the wrong answer:
--   1. IT NO LONGER FITS. The corpus reached 1.72M chunks. At float4 x dims:
--          768  -> ~5.0 GB      1536 -> ~9.9 GB
--      plus an HNSW index of comparable size, on top of the ~1.7 GB table,
--      against ~17 GB free on the NFS share that holds this database. 1536-dim
--      (~20 GB with its index) overflows it; this VM's known failure mode is a
--      disk-full crash-looping Postgres. 768-dim (~10 GB) fits with headroom.
--   2. OpenAI ran out of credit after ~208k chunks (~$2), twice. bge-base is
--      $0 and has no quota ceiling.
-- bge-base-en-v1.5 (768-dim) is ~on par with text-embedding-3-small on MTEB
-- retrieval, and PROVEN so on THIS corpus: a $0 head-to-head against the 216k
-- OpenAI vectors already in the DB showed 0.458 top-10 neighbour agreement and
-- correct retrieval on real filing queries.
--
-- The 216k OpenAI-1536 vectors are DISCARDED, not converted — there is no
-- projection from 1536-dim to 768-dim, and mixing spaces in one index returns
-- silently meaningless similarity. Re-embedding all chunks with bge-base costs
-- CPU (~1 day across parallel workers), not money.
--
-- Re-runnable: every step is guarded on current state.

BEGIN;

-- The `vector` type lives in public, not nidp. Without this the ADD below fails
-- with `type "vector" does not exist` — every migration in this tree opens the
-- same way (031, 119).
SET search_path TO nidp, public;
CREATE EXTENSION IF NOT EXISTS vector;

-- The postgres container runs with Docker's default 64MB /dev/shm; a parallel
-- worker on this ~1.7M-row table asked for a 2GB shared segment and an earlier
-- attempt died with a /dev/shm DiskFullError (NOT the disk). Nothing here needs
-- parallelism.
SET max_parallel_workers_per_gather = 0;
SET maintenance_work_mem = '256MB';

-- 1. Clear the OpenAI bookkeeping columns. The vectors themselves go with the
--    column in step 2.
UPDATE nidp.document_chunks
   SET embedding_model = NULL, embedded_at = NULL
 WHERE embedding_model IS NOT NULL;

-- 2. DROP + ADD, not ALTER ... TYPE. ALTER COLUMN TYPE forces a full table
--    rewrite (~1.7M rows / ~1.8GB over NFS) that blew the 600s per-statement
--    migration budget twice. And it is pointless: it would copy 1.8GB to retype
--    a column whose every value we discard on the line above. DROP COLUMN is
--    metadata-only; ADD COLUMN with no default is metadata-only on PG11+ — both
--    instant at any table size. DROP cascades to idx_chunk_embedding_hnsw, which
--    step 3 rebuilds. The column reappears at the end of the tuple; nothing
--    reads by ordinal (asyncpg returns rows by name), so that is cosmetic.
ALTER TABLE nidp.document_chunks DROP COLUMN IF EXISTS embedding;
ALTER TABLE nidp.document_chunks ADD  COLUMN embedding vector(768);

COMMENT ON COLUMN nidp.document_chunks.embedding IS
    'bge-base-en-v1.5 (768-dim), self-hosted ONNX on CPU. Populated by '
    'document_parser.embed_pending via nidp.shared.embeddings_local. No API key '
    'or quota. Vectors are L2-normalised (CLS pooling) for cosine.';

-- 3. Rebuild the vector index at the new dimension. Safe on an empty column;
--    HNSW grows incrementally as embed_pending fills rows.
CREATE INDEX IF NOT EXISTS idx_chunk_embedding_hnsw
    ON nidp.document_chunks
 USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- The FTS index (119) is dimension-independent and stays as is — it keeps the
-- corpus keyword-searchable while embeddings backfill.

INSERT INTO nidp.schema_migrations(filename)
VALUES ('125_document_chunks_embedding_bge_base.sql')
ON CONFLICT DO NOTHING;

COMMIT;
