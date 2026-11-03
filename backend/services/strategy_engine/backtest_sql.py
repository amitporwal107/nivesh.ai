"""Shared SQL constants for the strategy engine's SQL market-data backend.

Kept in its own module so both `backtest.py` and `market_data.py` can import
it without a circular dependency.
"""
from __future__ import annotations

# Exit bars from the corp-action-adjusted series (R1) so a split/bonus during
# the hold doesn't fabricate a gain or loss. adj_open/adj_high/adj_low/adj_close are on
# the same basis as the adjusted entry close. The open is what a gap through the stop
# fills at (services/exit_rules.py).
EXIT_BARS_SQL = """
SELECT p.symbol      AS symbol,
       p.adj_open    AS open,
       p.adj_close   AS close,
       p.adj_high    AS high,
       p.adj_low     AS low
  FROM nidp.prices_eod_adjusted p
 WHERE p.symbol = ANY($1::text[])
   AND p.as_of_date = $2
"""
