"""Self-hosted bge-small-en-v1.5 embeddings — ONNX on CPU, no API, no quota.

WHY LOCAL
---------
The OpenAI path failed three separate ways in one day, each silently:
  * a rotated key left a dead value in the env file (14 call sites 401'd all day)
  * the vision tier hit TPM rate limits and discarded whole batches
  * the account ran out of credit (insufficient_quota) and embed_pending kept
    returning embedded=0, which is indistinguishable from "nothing to embed"
A local model has none of those states. It is also what this schema originally
specified: 031_nidp_documents.sql shipped `embedding VECTOR(384)` commented
"bge-small-en-v1.5 (default model)" with an `embedding_model` column for
re-embedding bookkeeping. No embedder was ever built, so 119 widened the empty
column to 1536 for OpenAI. This restores the original design.

WHY bge-small AND NOT bge-base/large (measured on staging, 2026-07-17)
---------------------------------------------------------------------
  * 512-token cap costs nothing here: of 668,621 chunks, exactly 10 (0.0%)
    exceed ~2048 chars. The chunker already caps at ~2000.
  * Disk is the binding constraint, and 1536-dim does NOT fit. Vectors alone:
    384=981MB, 768=1961MB, 1024=2615MB, 1536=3923MB — against 8.5G free on the
    NFS share that holds Postgres, plus an HNSW index of comparable size, plus
    the existing 1.7GB table. This VM's known failure mode is a disk-full
    crash-looping Postgres.
  * 33M params fits a 4-core box already running prod Postgres, 13 containers
    and whisper. bge-base is 3x, bge-large 10x.
Retrieval quality is within ~1 MTEB point of text-embedding-3-small, so this is
not a quality-for-independence trade.

ONNX, NOT sentence-transformers: sentence-transformers pulls torch (multi-GB).
onnxruntime + tokenizers is ~50MB and has no torch dependency.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import List

logger = logging.getLogger(__name__)

# The bge-*-en-v1.5 family shares one ONNX/tokenizer shape (BERT, 512-token cap,
# CLS pooling); only the output dimension differs. Verified from each model's own
# 1_Pooling/config.json: small=384, base=768, large=1024, all cls=True/mean=False.
# base is the current choice: ~on par with OpenAI text-embedding-3-small on MTEB
# retrieval, and its 768-dim vectors fit the disk that OpenAI's 1536 no longer did
# (1.72M chunks: 768-dim ~5GB vs 1536-dim ~10GB, + a same-sized HNSW index each).
_DIM_BY_MODEL = {
    "bge-small-en-v1.5": 384,
    "bge-base-en-v1.5": 768,
    "bge-large-en-v1.5": 1024,
}
MODEL_NAME = os.environ.get("NIDP_EMBED_MODEL", "bge-base-en-v1.5")
if MODEL_NAME not in _DIM_BY_MODEL:
    # Fail loud rather than silently embed at the wrong dimension.
    raise ValueError(f"unsupported local embed model {MODEL_NAME!r}; "
                     f"known: {sorted(_DIM_BY_MODEL)}")
EMBED_DIM = _DIM_BY_MODEL[MODEL_NAME]     # matches the vector(N) column; asserted at load
_MAX_SEQ = 512                            # model_type=bert, max_position_embeddings=512
_MAX_BATCH = int(os.environ.get("NIDP_EMBED_BATCH", "32"))
_MODEL_DIR = os.environ.get("NIDP_EMBED_MODEL_DIR", f"/opt/nidp-staging/models/{MODEL_NAME}")

# The box runs prod Postgres + 13 containers + whisper and sits at load ~15.
# Left unbounded, onnxruntime grabs every core and starves them.
_THREADS = int(os.environ.get("NIDP_EMBED_THREADS", "2"))

# bge-v1.5 s2p retrieval: the instruction goes on the QUERY only, never on the
# passages. Applying it to passages would embed 668k chunks in the wrong space.
# v1.5 reduced the need for it, so it is overridable to "" for A/B.
QUERY_PREFIX = os.environ.get(
    "NIDP_EMBED_QUERY_PREFIX",
    "Represent this sentence for searching relevant passages: ",
)

_session = None
_tokenizer = None
_lock = threading.Lock()              # first call may race across parser workers


class LocalEmbeddingError(RuntimeError):
    """Local embedding unavailable (missing package or model files)."""


def is_available() -> bool:
    """True when the local backend can actually run. Mirrors ocr_available() /
    audio_available(): callers check and degrade rather than crash."""
    if not (os.path.exists(os.path.join(_MODEL_DIR, "model.onnx"))
            and os.path.exists(os.path.join(_MODEL_DIR, "tokenizer.json"))):
        return False
    try:
        import onnxruntime  # noqa: F401
        import tokenizers   # noqa: F401
    except ImportError:
        return False
    return True


def _load():
    """Build the session once per process. Never call under a hot loop lock."""
    global _session, _tokenizer
    if _session is not None:
        return
    with _lock:
        if _session is not None:                       # double-checked
            return
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as e:
            raise LocalEmbeddingError(f"onnxruntime/tokenizers not installed: {e}") from e

        model_path = os.path.join(_MODEL_DIR, "model.onnx")
        tok_path = os.path.join(_MODEL_DIR, "tokenizer.json")
        if not (os.path.exists(model_path) and os.path.exists(tok_path)):
            raise LocalEmbeddingError(f"model files missing under {_MODEL_DIR}")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = _THREADS
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])

        tok = Tokenizer.from_file(tok_path)
        tok.enable_truncation(max_length=_MAX_SEQ)     # the 10 over-length chunks clip here
        tok.enable_padding(length=None)                # pad to longest in batch

        _session, _tokenizer = sess, tok
        logger.info("bge-small loaded from %s (threads=%d, inputs=%s)",
                    _MODEL_DIR, _THREADS, [i.name for i in sess.get_inputs()])


def embed_texts_local(texts: List[str], *, is_query: bool = False) -> List[List[float]]:
    """Embed texts with bge-small. Returns L2-normalised 384-dim vectors.

    is_query=True applies the bge retrieval instruction — set it ONLY for search
    queries. Passages must be embedded without it; mixing the two puts queries
    and documents in different spaces and silently wrecks recall.
    """
    if not texts:
        return []
    _load()
    import numpy as np

    prepared = [
        (QUERY_PREFIX + (t.strip() or " ")) if is_query else (t.strip() or " ")
        for t in texts
    ]

    out: List[List[float]] = []
    input_names = {i.name for i in _session.get_inputs()}
    for start in range(0, len(prepared), _MAX_BATCH):
        batch = prepared[start:start + _MAX_BATCH]
        encs = _tokenizer.encode_batch(batch)
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        # Some BERT exports require token_type_ids; others omit it. Feed only
        # what this graph declares — an undeclared input is a hard ORT error.
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.zeros_like(ids)

        last_hidden = _session.run(None, feed)[0]      # (batch, seq, 384)
        # CLS pooling — 1_Pooling/config.json says pooling_mode_cls_token=true.
        # Mean pooling here would produce plausible-looking vectors in the wrong
        # space: no error, just quietly worse retrieval.
        cls = last_hidden[:, 0, :]
        norms = np.linalg.norm(cls, axis=1, keepdims=True)
        cls = cls / np.clip(norms, 1e-12, None)        # cosine index needs unit vectors
        out.extend(cls.astype(np.float32).tolist())

    if out and len(out[0]) != EMBED_DIM:
        raise LocalEmbeddingError(f"expected {EMBED_DIM}-dim, got {len(out[0])}")
    return out
