"""NSE block-deals CSV parser. Same shape as bulk-deals — we re-export
the bulk parser with a writer-side override (`source` field changes
upstream)."""
from __future__ import annotations

from nidp.services.bulk_deals.parser import parse_bulk_deals as parse_block_deals  # noqa: F401
