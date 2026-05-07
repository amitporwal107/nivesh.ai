"""Recursive character chunker.

Targets ~500 tokens/chunk with ~50-token overlap. We approximate token
count as char_count / 4 (cl100k roughly averages this for English).

Splits on a hierarchy: \\n\\n → \\n → '. ' → ' '. The first separator
that yields chunks under TARGET_CHARS wins; we never break a word.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TARGET_CHARS = 2000          # ≈500 tokens
OVERLAP_CHARS = 200          # ≈50 tokens
MIN_CHUNK_CHARS = 200        # below this we merge into the next chunk


@dataclass
class Chunk:
    index: int
    text: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    token_count: int          # approximation


def _approx_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def _char_to_page(char_offset: int, page_offsets: list[int]) -> int | None:
    """Map an absolute char offset back to a 1-based page number.

    page_offsets[i] = first char offset of page i+1 in full_text.
    """
    if not page_offsets:
        return None
    lo, hi = 0, len(page_offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if page_offsets[mid] <= char_offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def chunk_text(
    full_text: str,
    pages: list[str] | None = None,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[Chunk]:
    if not full_text.strip():
        return []

    # Page offsets for char→page lookup. We rebuild "joined" the same way
    # extract_text_from_pdf does: pages joined by "\n\n" with empty pages dropped.
    page_offsets: list[int] = []
    if pages:
        offset = 0
        for p in pages:
            if p.strip():
                page_offsets.append(offset)
                offset += len(p) + 2  # "\n\n" separator

    chunks: list[Chunk] = []
    n = len(full_text)
    cursor = 0
    idx = 0
    while cursor < n:
        end = min(cursor + target_chars, n)
        if end < n:
            # Prefer breaking at paragraph, then line, then sentence, then space.
            window = full_text[cursor:end]
            for sep in ("\n\n", "\n", ". ", " "):
                k = window.rfind(sep)
                if k > target_chars // 2:           # keep the chunk reasonably full
                    end = cursor + k + len(sep)
                    break

        chunk_text = full_text[cursor:end].strip()
        if chunk_text and (len(chunk_text) >= MIN_CHUNK_CHARS or not chunks):
            chunks.append(
                Chunk(
                    index=idx,
                    text=chunk_text,
                    char_start=cursor,
                    char_end=end,
                    page_start=_char_to_page(cursor, page_offsets) if page_offsets else None,
                    page_end=_char_to_page(end - 1, page_offsets) if page_offsets else None,
                    token_count=_approx_tokens(chunk_text),
                )
            )
            idx += 1
        elif chunks:
            # Tail too small — merge into the previous chunk.
            prev = chunks[-1]
            merged = (full_text[prev.char_start:end]).strip()
            chunks[-1] = Chunk(
                index=prev.index,
                text=merged,
                char_start=prev.char_start,
                char_end=end,
                page_start=prev.page_start,
                page_end=_char_to_page(end - 1, page_offsets) if page_offsets else prev.page_end,
                token_count=_approx_tokens(merged),
            )

        if end >= n:
            break
        cursor = max(end - overlap_chars, cursor + 1)

    return chunks
