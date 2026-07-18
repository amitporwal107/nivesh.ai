"""Embedding client for document-chunk semantic search — local bge or OpenAI.

Shared by the write side (document_parser fills nidp.document_chunks.embedding)
and the read side (feed_rag vector retriever + daas_api /documents/search embed
the user query). BOTH sides resolve NIDP_EMBED_MODEL through this module, which
is what makes switching backends safe: queries and passages can never end up in
different vector spaces because there is one switch, not two.

Default: bge-small-en-v1.5, self-hosted via ONNX on CPU (384-dim), matching the
document_chunks.embedding VECTOR(384) column (migration 125). Set
NIDP_EMBED_MODEL=text-embedding-3-small to route to OpenAI instead — but note
the column dimension must match the model, so switching models is a migration,
not just an env change.

Key handling mirrors the announcement classifier: OPENAI_API_KEY from env
(set in /opt/nidp/nidp.env on the VM; present on the API tier too). The openai
import is lazy so this module stays importable in envs without the package.

Vectors are passed to Postgres as a pgvector *string literal* cast with
`$n::vector` — this avoids registering an asyncpg codec for the `vector` type.
"""
from __future__ import annotations

import asyncio
import logging
import os
from nidp.shared.openai_key import get_openai_api_key, openai_configured
from typing import List, Optional

logger = logging.getLogger(__name__)

EMBED_MODEL = os.environ.get("NIDP_EMBED_MODEL", "text-embedding-3-small")

# Any bge-* model routes to the self-hosted ONNX backend; anything else is
# treated as an OpenAI model name. The dimension MUST match the
# document_chunks.embedding column or every insert fails on the cast — the
# column is vector(1536), so the OpenAI default (1536-dim) is the one that fits.
# The bge-small path (384-dim) is a dormant opt-in: switching to it needs a
# column migration + full re-embed, since 384 and 1536 cannot share one index.
_LOCAL_PREFIXES = ("bge-",)


def _use_local() -> bool:
    return EMBED_MODEL.startswith(_LOCAL_PREFIXES)


# Dimension MUST match the document_chunks.embedding vector(N) column, or every
# insert fails on the $n::vector cast. bge-base is the local default (768-dim,
# ~on par with OpenAI on retrieval, fits disk); OpenAI text-embedding-3-small is
# 1536. Keyed by model so small/base/large and OpenAI can't be confused.
_DIM_BY_MODEL = {
    "bge-small-en-v1.5": 384,
    "bge-base-en-v1.5": 768,
    "bge-large-en-v1.5": 1024,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}
EMBED_DIM = _DIM_BY_MODEL.get(EMBED_MODEL, 768 if _use_local() else 1536)
_MAX_BATCH = 128                 # inputs per embeddings.create call
_MAX_INPUT_CHARS = 24_000        # ~6k tokens; well under the 8191-token model limit

_client = None
_client_key: str | None = None                   # lazily constructed OpenAI() (or an injected fake in tests)


class EmbeddingError(RuntimeError):
    """Raised when embedding is unavailable (no key / package / API error)."""


def is_configured() -> bool:
    """True when an embedding call can be attempted.

    Local backend: needs the model files + onnxruntime on disk — no key, no
    quota, no network. OpenAI backend: resolves the key via GSM/admin/env, not
    os.environ alone, which is blind to a key rotated in Secret Manager.
    """
    if _use_local():
        from nidp.shared.embeddings_local import is_available
        return is_available()
    return openai_configured()


def _get_client():
    # Re-create when the key changes: a cached client pins the key it was built
    # with, so a GSM rotation would otherwise need a process restart to apply.
    global _client, _client_key
    if _client is not None and _client_key != get_openai_api_key():
        _client = None
    if _client is None:
        try:
            from openai import OpenAI
        except ImportError as e:                       # pragma: no cover - env-dependent
            raise EmbeddingError("openai package not installed") from e
        key = get_openai_api_key()
        if not key:
            raise EmbeddingError("OPENAI_API_KEY not set — required for chunk embeddings")
        # max_retries=5 (SDK default is 2): the SDK retries 429/408/409/5xx with
        # exponential backoff and honours Retry-After, so a transient rate-limit
        # blip during a 710k-chunk drain self-heals instead of dropping a batch.
        # Note this does NOT rescue insufficient_quota (also a 429): those retries
        # all fail, so the drain must hard-stop on them rather than spin.
        _client, _client_key = OpenAI(api_key=key, max_retries=5, timeout=60.0), key
    return _client


def _embed_sync(texts: List[str], *, is_query: bool = False) -> List[List[float]]:
    """Embed a list of texts in batches, preserving input order.

    Empty/blank inputs are sent as a single space so the API returns a vector
    for every position (callers rely on positional alignment with their rows).

    is_query only matters for the local bge backend, which prefixes queries with
    a retrieval instruction and passages with nothing. OpenAI has no such split.
    """
    if not texts:
        return []
    if _use_local():
        from nidp.shared.embeddings_local import LocalEmbeddingError, embed_texts_local
        try:
            return embed_texts_local(texts, is_query=is_query)
        except LocalEmbeddingError as e:
            # Same contract as the OpenAI path: callers catch EmbeddingError and
            # degrade to keyword search rather than failing the parse.
            raise EmbeddingError(f"local embedding failed: {e}") from e
    client = _get_client()
    out: List[List[float]] = []
    for start in range(0, len(texts), _MAX_BATCH):
        batch = [
            (t.strip()[:_MAX_INPUT_CHARS] if (t and t.strip()) else " ")
            for t in texts[start:start + _MAX_BATCH]
        ]
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
        except Exception as e:                          # noqa: BLE001 - surface as EmbeddingError
            raise EmbeddingError(f"embeddings.create failed: {e}") from e
        # Realign by .index in case the API reorders (it shouldn't, but be safe).
        for item in sorted(resp.data, key=lambda d: d.index):
            out.append(list(item.embedding))
    return out


async def embed_texts(texts: List[str]) -> List[List[float]]:
    """Async: embed many texts off-thread so the event loop isn't blocked."""
    return await asyncio.to_thread(_embed_sync, texts)


async def embed_query(text: str) -> Optional[List[float]]:
    """Async: embed a single SEARCH QUERY; None for empty input.

    Distinct from embed_texts() on purpose: bge is asymmetric. A query carries a
    retrieval instruction, a passage does not. Embedding a query as a passage
    (or vice versa) puts the two in different spaces — no error, just quietly
    broken recall — so the query/passage split must stay at this boundary.
    """
    if not text or not text.strip():
        return None
    vecs = await asyncio.to_thread(_embed_sync, [text], is_query=True)
    return vecs[0] if vecs else None


def to_pgvector_literal(vec: List[float]) -> str:
    """Render a float list as a pgvector literal '[0.1,0.2,...]' for `$n::vector`."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"
