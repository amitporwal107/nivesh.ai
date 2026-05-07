"""nidp.fno_bhavcopy writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_FO_BHAV"

# Sentinel strike used in the PK when option_type is NULL (futures).
# Postgres treats NULL as not-equal-to-NULL in unique constraints, so
# a sentinel keeps futures rows distinct without ambiguity.
_FUTURES_STRIKE_SENTINEL = -1.0
_FUTURES_OPTION_TYPE_SENTINEL = "FUT"


async def upsert_fno_bhavcopy(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0

    args = []
    for r in rows:
        # Coerce NULLs in the PK columns to sentinels so ON CONFLICT works
        strike = r.get("strike_price")
        opt_type = r.get("option_type")
        if strike is None:
            strike = _FUTURES_STRIKE_SENTINEL
        if opt_type is None:
            opt_type = _FUTURES_OPTION_TYPE_SENTINEL

        args.append((
            to_date(r["as_of_date"]),
            to_date(r.get("biz_date")),
            r["instrument_type"],
            r["ticker_symbol"],
            r.get("isin"),
            r.get("series"),
            to_date(r["expiry_date"]),
            to_date(r.get("actual_expiry_date")),
            strike,
            opt_type,
            r.get("open_price"),
            r.get("high_price"),
            r.get("low_price"),
            r.get("close_price"),
            r.get("last_price"),
            r.get("prev_close_price"),
            r.get("settle_price"),
            r.get("underlying_price"),
            r.get("open_interest"),
            r.get("change_in_oi"),
            r.get("traded_volume"),
            r.get("traded_value"),
            r.get("num_trades"),
            r.get("new_board_lot_qty"),
            SOURCE_NAME,
            run_id,
        ))

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.fno_bhavcopy
                    (as_of_date, biz_date, instrument_type, ticker_symbol,
                     isin, series, expiry_date, actual_expiry_date,
                     strike_price, option_type,
                     open_price, high_price, low_price, close_price,
                     last_price, prev_close_price, settle_price, underlying_price,
                     open_interest, change_in_oi, traded_volume, traded_value,
                     num_trades, new_board_lot_qty,
                     source, source_run_id, ingested_at)
                VALUES ($1::date, $2::date, $3, $4,
                        $5, $6, $7::date, $8::date,
                        $9, $10,
                        $11, $12, $13, $14,
                        $15, $16, $17, $18,
                        $19, $20, $21, $22,
                        $23, $24,
                        $25, $26, NOW())
                ON CONFLICT (as_of_date, instrument_type, ticker_symbol,
                             expiry_date, strike_price, option_type, source)
                DO UPDATE SET
                    biz_date            = EXCLUDED.biz_date,
                    isin                = EXCLUDED.isin,
                    series              = EXCLUDED.series,
                    actual_expiry_date  = EXCLUDED.actual_expiry_date,
                    open_price          = EXCLUDED.open_price,
                    high_price          = EXCLUDED.high_price,
                    low_price           = EXCLUDED.low_price,
                    close_price         = EXCLUDED.close_price,
                    last_price          = EXCLUDED.last_price,
                    prev_close_price    = EXCLUDED.prev_close_price,
                    settle_price        = EXCLUDED.settle_price,
                    underlying_price    = EXCLUDED.underlying_price,
                    open_interest       = EXCLUDED.open_interest,
                    change_in_oi        = EXCLUDED.change_in_oi,
                    traded_volume       = EXCLUDED.traded_volume,
                    traded_value        = EXCLUDED.traded_value,
                    num_trades          = EXCLUDED.num_trades,
                    new_board_lot_qty   = EXCLUDED.new_board_lot_qty,
                    source_run_id       = EXCLUDED.source_run_id,
                    ingested_at         = NOW()
                """,
                args,
            )
    logger.info("fno_bhavcopy upserted %d rows", len(args))
    return len(args)
