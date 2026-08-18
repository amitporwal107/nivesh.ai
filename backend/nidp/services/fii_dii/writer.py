"""nidp.fii_dii_flows writer."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_FII_DII"


async def upsert_fii_dii(rows: list[dict[str, Any]], run_id: uuid.UUID,
                         source: str = SOURCE_NAME) -> int:
    """Upsert flow rows.

    `source` is part of the primary key (as_of_date, category, segment,
    source), so NSE's provisional figures and NSDL's custodian-confirmed
    figures coexist for the same day instead of overwriting each other —
    which is what makes a provisional-vs-confirmed comparison possible.
    A row may carry its own "source" to mix sources in one batch.
    """
    if not rows:
        return 0
    args = [
        (to_date(r["as_of_date"]), r["category"], r["segment"],
         r.get("buy_value_cr"), r.get("sell_value_cr"), r.get("net_value_cr"),
         r.get("buy_contracts"), r.get("sell_contracts"), r.get("net_contracts"),
         r.get("open_interest"),
         r.get("source") or source, run_id)
        for r in rows
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.fii_dii_flows
                    (as_of_date, category, segment,
                     buy_value_cr, sell_value_cr, net_value_cr,
                     buy_contracts, sell_contracts, net_contracts, open_interest,
                     source, source_run_id, ingested_at)
                VALUES ($1::date, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, NOW())
                ON CONFLICT (as_of_date, category, segment, source) DO UPDATE SET
                    buy_value_cr   = EXCLUDED.buy_value_cr,
                    sell_value_cr  = EXCLUDED.sell_value_cr,
                    net_value_cr   = EXCLUDED.net_value_cr,
                    buy_contracts  = EXCLUDED.buy_contracts,
                    sell_contracts = EXCLUDED.sell_contracts,
                    net_contracts  = EXCLUDED.net_contracts,
                    open_interest  = EXCLUDED.open_interest,
                    source_run_id  = EXCLUDED.source_run_id,
                    ingested_at    = NOW()
                """,
                args,
            )
    logger.info("fii_dii_flows upserted %d rows", len(args))
    return len(args)
