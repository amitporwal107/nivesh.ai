"""nidp.shareholding_pattern writer."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from nidp.shared._date_coerce import to_date
from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
SOURCE_NAME = "NSE_SHP"


async def upsert_shareholding(rows: list[dict[str, Any]], run_id: uuid.UUID) -> int:
    if not rows:
        return 0

    args = []
    for r in rows:
        args.append((
            r["symbol"],
            to_date(r["period_end"]),
            r.get("promoter_pct"),
            r.get("promoter_pledged_pct"),
            r.get("promoter_pledged_to_total_pct"),
            r.get("fii_pct"),
            r.get("dii_pct"),
            r.get("mf_pct"),
            r.get("insurance_pct"),
            r.get("bank_fi_pct"),
            r.get("govt_holding_pct"),
            r.get("public_pct"),
            r.get("individual_pct"),
            r.get("nri_pct"),
            r.get("bodies_corporate_pct"),
            r.get("total_shares"),
            r.get("promoter_shares"),
            r.get("public_shares"),
            r.get("pledged_shares"),
            r.get("filing_id"),
            r.get("xbrl_url"),
            _to_tstz(r.get("broadcast_at")),
            SOURCE_NAME,
            run_id,
        ))

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO nidp.shareholding_pattern
                    (symbol, period_end,
                     promoter_pct, promoter_pledged_pct, promoter_pledged_to_total_pct,
                     fii_pct, dii_pct, mf_pct, insurance_pct, bank_fi_pct, govt_holding_pct,
                     public_pct, individual_pct, nri_pct, bodies_corporate_pct,
                     total_shares, promoter_shares, public_shares, pledged_shares,
                     filing_id, xbrl_url, broadcast_at,
                     source, source_run_id, ingested_at)
                VALUES ($1, $2::date,
                        $3, $4, $5,
                        $6, $7, $8, $9, $10, $11,
                        $12, $13, $14, $15,
                        $16, $17, $18, $19,
                        $20, $21, $22::timestamptz,
                        $23, $24, NOW())
                ON CONFLICT (symbol, period_end, source) DO UPDATE SET
                    promoter_pct                  = COALESCE(EXCLUDED.promoter_pct,                  shareholding_pattern.promoter_pct),
                    promoter_pledged_pct          = COALESCE(EXCLUDED.promoter_pledged_pct,          shareholding_pattern.promoter_pledged_pct),
                    promoter_pledged_to_total_pct = COALESCE(EXCLUDED.promoter_pledged_to_total_pct, shareholding_pattern.promoter_pledged_to_total_pct),
                    fii_pct                       = COALESCE(EXCLUDED.fii_pct,                       shareholding_pattern.fii_pct),
                    dii_pct                       = COALESCE(EXCLUDED.dii_pct,                       shareholding_pattern.dii_pct),
                    mf_pct                        = COALESCE(EXCLUDED.mf_pct,                        shareholding_pattern.mf_pct),
                    insurance_pct                 = COALESCE(EXCLUDED.insurance_pct,                 shareholding_pattern.insurance_pct),
                    bank_fi_pct                   = COALESCE(EXCLUDED.bank_fi_pct,                   shareholding_pattern.bank_fi_pct),
                    govt_holding_pct              = COALESCE(EXCLUDED.govt_holding_pct,              shareholding_pattern.govt_holding_pct),
                    public_pct                    = COALESCE(EXCLUDED.public_pct,                    shareholding_pattern.public_pct),
                    individual_pct                = COALESCE(EXCLUDED.individual_pct,                shareholding_pattern.individual_pct),
                    nri_pct                       = COALESCE(EXCLUDED.nri_pct,                       shareholding_pattern.nri_pct),
                    bodies_corporate_pct          = COALESCE(EXCLUDED.bodies_corporate_pct,          shareholding_pattern.bodies_corporate_pct),
                    total_shares                  = COALESCE(EXCLUDED.total_shares,                  shareholding_pattern.total_shares),
                    promoter_shares               = COALESCE(EXCLUDED.promoter_shares,               shareholding_pattern.promoter_shares),
                    public_shares                 = COALESCE(EXCLUDED.public_shares,                 shareholding_pattern.public_shares),
                    pledged_shares                = COALESCE(EXCLUDED.pledged_shares,                shareholding_pattern.pledged_shares),
                    filing_id                     = EXCLUDED.filing_id,
                    xbrl_url                      = EXCLUDED.xbrl_url,
                    broadcast_at                  = EXCLUDED.broadcast_at,
                    source_run_id                 = EXCLUDED.source_run_id,
                    ingested_at                   = NOW()
                """,
                args,
            )

    # DII derivation: if ingester didn't set dii_pct directly, sum the
    # institutional sub-categories. Done as a follow-up UPDATE so the
    # ingester stays simple.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE nidp.shareholding_pattern
               SET dii_pct = ROUND(
                       COALESCE(mf_pct,0) + COALESCE(insurance_pct,0)
                     + COALESCE(bank_fi_pct,0)::numeric, 4)
             WHERE source_run_id = $1
               AND dii_pct IS NULL
               AND (mf_pct IS NOT NULL OR insurance_pct IS NOT NULL OR bank_fi_pct IS NOT NULL)
            """,
            run_id,
        )

    logger.info("shareholding_pattern upserted %d rows", len(args))
    return len(args)


def _to_tstz(s: Any):
    if s is None:
        return None
    if hasattr(s, "isoformat") and not isinstance(s, str):
        return s
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None
