from __future__ import annotations

from datetime import date

from nidp.shared.storage.pg import get_pool


def _rows_affected(tag: str) -> int:
    try:
        return int(tag.split()[-1])
    except Exception:
        return 0


async def run(target_date: date | None = None) -> dict[str, int | str]:
    pool = await get_pool()
    as_of = target_date.isoformat() if target_date else "latest"

    async with pool.acquire() as conn:
        mapped = await conn.execute(
            """
            INSERT INTO portfolio.holding_security_map (snapshot_id, security_id, match_confidence, match_method)
            SELECT h.snapshot_id,
                   COALESCE(s_isin.security_id, s_amfi.security_id, s_sym.security_id) AS security_id,
                   CASE
                     WHEN s_isin.security_id IS NOT NULL THEN 100
                     WHEN s_amfi.security_id IS NOT NULL THEN 98
                     WHEN s_sym.security_id IS NOT NULL THEN 90
                     ELSE 0
                   END,
                   CASE
                     WHEN s_isin.security_id IS NOT NULL THEN 'isin'
                     WHEN s_amfi.security_id IS NOT NULL THEN 'amfi'
                     WHEN s_sym.security_id IS NOT NULL THEN 'symbol'
                     ELSE 'unmatched'
                   END
              FROM portfolio.user_holdings_snapshot h
              LEFT JOIN ref.security_master s_isin ON h.isin IS NOT NULL AND s_isin.isin = h.isin
              LEFT JOIN ref.security_master s_amfi ON h.amfi_scheme_code IS NOT NULL AND s_amfi.amfi_scheme_code = h.amfi_scheme_code
              LEFT JOIN ref.security_master s_sym  ON h.symbol IS NOT NULL AND s_sym.symbol = UPPER(h.symbol)
             WHERE ($1::date IS NULL OR h.snapshot_date = $1)
            ON CONFLICT (snapshot_id)
            DO UPDATE SET
              security_id = EXCLUDED.security_id,
              match_confidence = EXCLUDED.match_confidence,
              match_method = EXCLUDED.match_method,
              resolved_at = NOW()
            """,
            target_date,
        )

        intel = await conn.execute(
            """
            WITH d AS (
              SELECT COALESCE($1::date, max(snapshot_date)) AS snapshot_date
              FROM portfolio.user_holdings_snapshot
            ),
            base AS (
              SELECT h.external_user_id, h.snapshot_date, h.asset_class,
                     h.market_value_inr, h.weight_pct,
                     m.security_id
                FROM portfolio.user_holdings_snapshot h
                LEFT JOIN portfolio.holding_security_map m ON m.snapshot_id = h.snapshot_id
               WHERE h.snapshot_date = (SELECT snapshot_date FROM d)
            ),
            sec AS (
              SELECT b.*, sm.sector
                FROM base b
                LEFT JOIN ref.security_master sm ON sm.security_id = b.security_id
            ),
            feat AS (
              SELECT b.external_user_id, b.snapshot_date,
                     AVG(f.beta_90d) AS avg_beta_90d,
                     AVG(f.rsi_14) AS avg_rsi_14
                FROM base b
                JOIN features.stock_features_daily f ON f.security_id = b.security_id
               WHERE f.as_of_date = b.snapshot_date
               GROUP BY 1,2
            ),
            corr AS (
              SELECT b.external_user_id, b.snapshot_date,
                     count(*) FILTER (WHERE c.abs_correlation >= 0.8) AS high_corr_pairs
                FROM base b
                JOIN graph.correlations c
                  ON c.as_of_date = b.snapshot_date
                 AND (c.left_security_id = b.security_id OR c.right_security_id = b.security_id)
               GROUP BY 1,2
            ),
            agg AS (
              SELECT s.external_user_id,
                     s.snapshot_date,
                     sum(s.market_value_inr) AS total_market_value_inr,
                     100 * sum(s.market_value_inr) FILTER (WHERE s.asset_class = 'EQUITY') / NULLIF(sum(s.market_value_inr),0) AS equity_weight_pct,
                     100 * sum(s.market_value_inr) FILTER (WHERE s.asset_class IN ('MF','MUTUAL_FUND')) / NULLIF(sum(s.market_value_inr),0) AS mf_weight_pct,
                     100 * sum(s.market_value_inr) FILTER (WHERE s.security_id IS NULL) / NULLIF(sum(s.market_value_inr),0) AS unresolved_weight_pct,
                     100 * (
                       SELECT COALESCE(sum(x.market_value_inr),0)
                         FROM (
                           SELECT market_value_inr FROM sec t
                           WHERE t.external_user_id = s.external_user_id AND t.snapshot_date = s.snapshot_date
                           ORDER BY market_value_inr DESC LIMIT 5
                         ) x
                     ) / NULLIF(sum(s.market_value_inr),0) AS concentration_top5_pct
                FROM sec s
               GROUP BY s.external_user_id, s.snapshot_date
            ),
            top_sector AS (
              SELECT q.external_user_id, q.snapshot_date, q.sector AS top_sector,
                     100 * q.sector_mv / NULLIF(a.total_market_value_inr,0) AS top_sector_weight_pct
                FROM (
                  SELECT external_user_id, snapshot_date, sector,
                         sum(market_value_inr) AS sector_mv,
                         row_number() OVER (PARTITION BY external_user_id, snapshot_date ORDER BY sum(market_value_inr) DESC) AS rn
                    FROM sec
                   WHERE sector IS NOT NULL
                   GROUP BY 1,2,3
                ) q
                JOIN agg a ON a.external_user_id=q.external_user_id AND a.snapshot_date=q.snapshot_date
               WHERE q.rn = 1
            )
            INSERT INTO portfolio.user_intelligence_snapshot (
              external_user_id, snapshot_date, total_market_value_inr,
              equity_weight_pct, mf_weight_pct,
              top_sector, top_sector_weight_pct,
              concentration_top5_pct, unresolved_weight_pct,
              avg_beta_90d, avg_rsi_14, high_corr_pairs,
              quality_tier, summary_json
            )
            SELECT a.external_user_id, a.snapshot_date, a.total_market_value_inr,
                   a.equity_weight_pct, a.mf_weight_pct,
                   ts.top_sector, ts.top_sector_weight_pct,
                   a.concentration_top5_pct, a.unresolved_weight_pct,
                   f.avg_beta_90d, f.avg_rsi_14, COALESCE(c.high_corr_pairs,0),
                   CASE WHEN a.unresolved_weight_pct <= 5 THEN 'PLATINUM'
                        WHEN a.unresolved_weight_pct <= 15 THEN 'GOLD'
                        WHEN a.unresolved_weight_pct <= 30 THEN 'SILVER'
                        ELSE 'REVIEW' END,
                   jsonb_build_object('source','portfolio_intelligence_sync')
              FROM agg a
              LEFT JOIN top_sector ts ON ts.external_user_id=a.external_user_id AND ts.snapshot_date=a.snapshot_date
              LEFT JOIN feat f ON f.external_user_id=a.external_user_id AND f.snapshot_date=a.snapshot_date
              LEFT JOIN corr c ON c.external_user_id=a.external_user_id AND c.snapshot_date=a.snapshot_date
            ON CONFLICT (external_user_id, snapshot_date)
            DO UPDATE SET
              total_market_value_inr = EXCLUDED.total_market_value_inr,
              equity_weight_pct = EXCLUDED.equity_weight_pct,
              mf_weight_pct = EXCLUDED.mf_weight_pct,
              top_sector = EXCLUDED.top_sector,
              top_sector_weight_pct = EXCLUDED.top_sector_weight_pct,
              concentration_top5_pct = EXCLUDED.concentration_top5_pct,
              unresolved_weight_pct = EXCLUDED.unresolved_weight_pct,
              avg_beta_90d = EXCLUDED.avg_beta_90d,
              avg_rsi_14 = EXCLUDED.avg_rsi_14,
              high_corr_pairs = EXCLUDED.high_corr_pairs,
              quality_tier = EXCLUDED.quality_tier,
              summary_json = EXCLUDED.summary_json,
              computed_at = NOW()
            """,
            target_date,
        )

    return {"as_of": as_of, "mapped": _rows_affected(mapped), "intelligence_rows": _rows_affected(intel)}
