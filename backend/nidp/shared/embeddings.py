"""OpenAI embedding client for document-chunk semantic search.

Shared by the write side (document_parser fills nidp.document_chunks.embedding)
and the read side (feed_rag vector retriever + daas_api /documents/search embed
the user query). Model: text-embedding-3-small (1536-dim), matching the
nidp.document_chunks.embedding VECTOR(1536) column (migration 119).

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
EMBED_DIM = 1536                 # text-embedding-3-small native dimension
_MAX_BATCH = 128                 # inputs per embeddings.create call
_MAX_INPUT_CHARS = 24_000        # ~6k tokens; well under the 8191-token model limit

_client = None
_client_key: str | None = None                   # lazily constructed OpenAI() (or an injected fake in tests)


class EmbeddingError(RuntimeError):
    """Raised when embedding is unavailable (no key / package / API error)."""


def is_configured() -> bool:
    """True when an embedding call can be attempted (key resolvable).

    Resolves via GSM/admin/env — not os.environ alone, which is blind to a key
    rotated in Secret Manager.
    """
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
        _client, _client_key = OpenAI(api_key=key), key
    return _client


def _embed_sync(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts in batches, preserving input order.

    Empty/blank inputs are sent as a single space so the API returns a vector
    for every position (callers rely on positional alignment with their rows).
    """
    if not texts:
        return []
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
    """Async: embed a single query string; None for empty input."""
    if not text or not text.strip():
        return None
    vecs = await asyncio.to_thread(_embed_sync, [text])
    return vecs[0] if vecs else None


def to_pgvector_literal(vec: List[float]) -> str:
    """Render a float list as a pgvector literal '[0.1,0.2,...]' for `$n::vector`."""
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"
