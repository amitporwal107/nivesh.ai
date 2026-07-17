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
--   1. IT DOES NOT FIT. Vectors alone, at float4 x dims x ~695,000 rows:
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

-- The `vector` type lives in public, not nidp. Without this the ALTER below
-- fails with `type "vector" does not exist` even though the column is already a
-- vector — every migration in this tree opens the same way (see 031, 119).
SET search_path TO nidp, public;
CREATE EXTENSION IF NOT EXISTS vector;

-- The postgres container runs with Docker's default 64MB /dev/shm. A parallel
-- worker on this 696k-row table asked for a 2GB shared segment and the
-- migration died with:
--     DiskFullError: could not resize shared memory segment ... to 2094047776
--     bytes: No space left on device
-- That is /dev/shm, NOT the disk (nfs had 23G free at the time) — an easy error
-- to misread. Nothing below benefits from parallelism, so force it serial.
-- The durable fix is shm_size on the postgres service in
-- docker-compose.staging.yml; that needs a DB restart, so it is deliberately
-- not bundled into a migration.
SET max_parallel_workers_per_gather = 0;
SET maintenance_work_mem = '256MB';

-- 1. Clear the OpenAI bookkeeping. The vectors themselves go with the column
--    in step 2; this is just the metadata columns that survive it.
UPDATE nidp.document_chunks
   SET embedding_model = NULL, embedded_at = NULL
 WHERE embedding_model IS NOT NULL;

-- 2. DROP + ADD, not ALTER ... TYPE.
--    ALTER COLUMN TYPE forces a full table rewrite — 694k rows / 1.8GB over NFS.
--    Measured: it blew past the 600s per-statement migration budget (cli.py
--    MIGRATION_TIMEOUT_SEC) and rolled back, twice. And the rewrite is pointless:
--    it would copy 1.8GB to retype a column whose every value we are discarding.
--    DROP COLUMN is metadata-only; ADD COLUMN with no default is metadata-only on
--    PG11+. Both are instant regardless of table size.
--    DROP cascades to idx_chunk_embedding_hnsw, which step 3 rebuilds. The
--    column reappears at the end of the tuple — nothing here reads by ordinal
--    (asyncpg returns rows by name), so that is cosmetic.
ALTER TABLE nidp.document_chunks DROP COLUMN IF EXISTS embedding;
ALTER TABLE nidp.document_chunks ADD  COLUMN embedding vector(384);

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
