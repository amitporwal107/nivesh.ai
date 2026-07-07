"""Source-schema contract — fail LOUD on column/format drift.

The silent failure this closes: a source renames/drops a column (NSE did
`ClsPric`→`ClsgPric` mid-2025) or serves a valid-looking but wrong-schema file.
A lenient parser then null-drops the affected rows → fewer/zero rows → the run
is marked SKIPPED (looks like a holiday) instead of FAILED. Avro only guards the
nullable OUTPUT shape, so it doesn't catch this. See HANDOFF-FEED-RELIABILITY.md
§D5.

`require_columns(present, required, feed=...)` raises `SchemaContractError` when
an expected column is missing — case- and whitespace-insensitive, extra columns
allowed. Parsers call it on the source header before mapping fields, so drift
fails at the door with a precise message instead of silently losing data.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence


class SchemaContractError(Exception):
    """A source's header is missing column(s) the parser requires."""

    def __init__(self, feed: str, missing: Sequence[str],
                 present: Sequence[str] | None = None, source: str = "") -> None:
        self.feed = feed
        self.missing = list(missing)
        self.present = list(present or [])
        src = f" ({source})" if source else ""
        shown = ", ".join(self.present) if self.present else "(none)"
        super().__init__(
            f"{feed}: source schema drift{src} — missing expected column(s): "
            f"{', '.join(self.missing)}. Present: {shown}"
        )


def _norm(c: str) -> str:
    return c.strip().lower()


def require_columns(
    present: Iterable[str],
    required: Sequence[str],
    *,
    feed: str,
    source: str = "",
) -> List[str]:
    """Assert every `required` column is in `present`. Returns the normalized
    present columns on success; raises SchemaContractError on any miss.

    Comparison is case-insensitive and whitespace-trimmed; extra present
    columns are fine (sources add columns without breaking parsers)."""
    present_list = list(present)
    present_norm = {_norm(c) for c in present_list}
    missing = [r for r in required if _norm(r) not in present_norm]
    if missing:
        raise SchemaContractError(feed, missing, present=present_list, source=source)
    return sorted(present_norm)
