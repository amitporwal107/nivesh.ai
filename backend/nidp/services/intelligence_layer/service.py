from __future__ import annotations

from datetime import date

from nidp.shared.storage.pg import get_pool


def _rows_affected(tag: str) -> int:
    try:
        return int(tag.split()[-1])
    except Exception:
        return 0


async def run(target_date: date | None = None) -> dict[str, int | str]:
    """Materialize Phase-1 intelligence tables from existing NIDP core tables.

    Idempotent UPSERT/INSERT-only flow.
    """
    pool = await get_pool()
    as_of = target_date.isoformat() if target_date else "latest"

    async with pool.acquire() as conn:
        # ensure idempotent daily semantics
        # 1) Security master: equities from prices + index constituents.
        # Dedupe by symbol; null out ISIN when multiple symbols claim the same
        # ISIN (rare but happens in raw bhavcopy) so the unique index on isin
        # doesn't reject the batch.
        eq_rows = await conn.execute(
            """
            WITH per_symbol AS (
                SELECT DISTINCT ON (p.symbol) p.symbol, p.isin, p.as_of_date
                  FROM nidp.prices_eod p
                 WHERE ($1::date IS NULL OR p.as_of_date = $1::date)
                 ORDER BY p.symbol, p.as_of_date DESC
            ),
            cleaned AS (
                SELECT s.symbol,
                       CASE
                           WHEN s.isin IS NULL THEN NULL
                           WHEN COUNT(*) OVER (PARTITION BY s.isin) > 1 THEN NULL
                           ELSE s.isin
                       END AS isin
                  FROM per_symbol s
            )
            INSERT INTO ref.security_master (
                entity_type, asset_class, symbol, isin, nse_symbol,
                security_name, sector, industry, source_system
            )
            SELECT
                'EQUITY', 'EQUITY', d.symbol, d.isin, d.symbol,
                COALESCE(ic.company_name, d.symbol),
                NULL::text,
                ic.industry,
                'nidp.prices_eod'
            FROM cleaned d
            LEFT JOIN LATERAL (
                SELECT company_name, industry
                  FROM nidp.index_constituents x
                 WHERE x.symbol = d.symbol
                 ORDER BY x.as_of_date DESC
                 LIMIT 1
            ) ic ON TRUE
            ON CONFLICT (entity_type, symbol) WHERE symbol IS NOT NULL
            DO UPDATE SET
                isin          = COALESCE(EXCLUDED.isin, ref.security_master.isin),
                security_name = COALESCE(EXCLUDED.security_name, ref.security_master.security_name),
                industry      = COALESCE(EXCLUDED.industry, ref.security_master.industry),
                updated_at    = NOW()
            """,
            target_date,
        )

        # 2) Security master: mutual funds. Dedupe by scheme_code; null out
        # ISIN if it collides with an equity ISIN we just inserted, or if
        # multiple schemes share it (rare but seen in AMFI feeds).
        mf_rows = await conn.execute(
            """
            WITH per_scheme AS (
                SELECT DISTINCT ON (s.scheme_code)
                       s.scheme_code,
                       COALESCE(s.isin_growth, s.isin_idcw) AS isin,
                       s.scheme_name
                  FROM nidp.mf_scheme_master s
                 ORDER BY s.scheme_code
            ),
            cleaned AS (
                SELECT p.scheme_code, p.scheme_name,
                       CASE
                           WHEN p.isin IS NULL THEN NULL
                           WHEN COUNT(*) OVER (PARTITION BY p.isin) > 1 THEN NULL
                           WHEN EXISTS (
                               SELECT 1 FROM ref.security_master sm
                                WHERE sm.isin = p.isin
                                  AND NOT (sm.entity_type = 'MF_SCHEME'
                                           AND sm.symbol = p.scheme_code)
                           ) THEN NULL
                           ELSE p.isin
                       END AS isin
                  FROM per_scheme p
            )
            INSERT INTO ref.security_master (
                entity_type, asset_class, symbol, isin, amfi_scheme_code,
                security_name, source_system
            )
            SELECT
                'MF_SCHEME', 'MUTUAL_FUND', d.scheme_code,
                d.isin, d.scheme_code, d.scheme_name,
                'nidp.mf_scheme_master'
            FROM cleaned d
            ON CONFLICT (entity_type, symbol) WHERE symbol IS NOT NULL
            DO UPDATE SET
                isin          = COALESCE(EXCLUDED.isin, ref.security_master.isin),
                security_name = COALESCE(EXCLUDED.security_name, ref.security_master.security_name),
                updated_at    = NOW()
            """
        )

        # 3) Feature store mapping from existing nidp.stock_features_daily.
        feat_rows = await conn.execute(
            """
            INSERT INTO features.stock_features_daily (
                security_id, as_of_date, close_price,
                ret_5d, ret_20d, rsi_14, macd, macd_signal,
                sma_20, sma_50, atr_14, source_run_id
            )
            SELECT
                sm.security_id,
                f.as_of_date,
                f.close,
                f.return_5d_pct,
                f.return_20d_pct,
                f.rsi14,
                f.macd,
                f.macd_signal,
                f.sma20,
                f.sma50,
                f.atr14,
                f.source_run_id
            FROM nidp.stock_features_daily f
            JOIN ref.security_master sm
              ON sm.entity_type = 'EQUITY' AND sm.symbol = f.symbol
            WHERE ($1::date IS NULL OR f.as_of_date = $1::date)
            ON CONFLICT (security_id, as_of_date)
            DO UPDATE SET
                close_price = EXCLUDED.close_price,
                ret_5d      = EXCLUDED.ret_5d,
                ret_20d     = EXCLUDED.ret_20d,
                rsi_14      = EXCLUDED.rsi_14,
                macd        = EXCLUDED.macd,
                macd_signal = EXCLUDED.macd_signal,
                sma_20      = EXCLUDED.sma_20,
                sma_50      = EXCLUDED.sma_50,
                atr_14      = EXCLUDED.atr_14
            """,
            target_date,
            timeout=300,
        )

        # 4) Ownership links: fund holds stock from monthly holdings ISIN joins.
        link_rows = await conn.execute(
            """
            INSERT INTO graph.entity_links (
                as_of_date, left_security_id, right_security_id,
                relationship_type, weight_pct, metadata_json, source_system, valid_from
            )
            SELECT
                h.as_of_month,
                mf.security_id,
                eq.security_id,
                'FUND_HOLDS_STOCK',
                h.weight_pct,
                jsonb_build_object('security_name', h.security_name, 'source', h.source),
                'nidp.mf_holdings_monthly',
                h.as_of_month
            FROM nidp.mf_holdings_monthly h
            JOIN ref.security_master mf
              ON mf.entity_type = 'MF_SCHEME' AND mf.symbol = h.scheme_code
            JOIN ref.security_master eq
              ON eq.entity_type = 'EQUITY'
             AND h.security_isin IS NOT NULL
             AND eq.isin = h.security_isin
            WHERE ($1::date IS NULL OR h.as_of_month = date_trunc('month', $1::date)::date)
            ON CONFLICT DO NOTHING
            """,
            target_date,
            timeout=300,
        )


        # 5) Correlations: stock↔stock 90D from return_1d series (|corr| >= 0.7).
        # Constrained to symbols present in nidp.index_constituents to keep
        # the pairwise compute tractable; broaden later as universe grows.
        corr_rows = await conn.execute(
            """
            WITH latest AS (
                SELECT max(as_of_date) AS dt FROM nidp.prices_eod
            ),
            universe AS (
                SELECT DISTINCT symbol FROM nidp.index_constituents
            ),
            daily_ret AS (
                SELECT
                    p.symbol,
                    p.as_of_date,
                    ((p.close_price / NULLIF(lag(p.close_price) OVER (PARTITION BY p.symbol ORDER BY p.as_of_date), 0)) - 1.0)::double precision AS ret1d
                FROM nidp.prices_eod p
                JOIN universe u ON u.symbol = p.symbol
                WHERE p.source = 'NSE_BHAVCOPY'
                  AND p.as_of_date >= COALESCE($1::date, (SELECT dt FROM latest)) - INTERVAL '120 days'
                  AND p.as_of_date <= COALESCE($1::date, (SELECT dt FROM latest))
            ),
            pairs AS (
                SELECT
                    COALESCE($1::date, (SELECT dt FROM latest))::date AS as_of_date,
                    a.symbol AS left_symbol,
                    b.symbol AS right_symbol,
                    corr(a.ret1d, b.ret1d) AS c
                FROM daily_ret a
                JOIN daily_ret b ON a.as_of_date = b.as_of_date AND a.symbol < b.symbol
                WHERE a.ret1d IS NOT NULL AND b.ret1d IS NOT NULL
                GROUP BY 1,2,3
                HAVING count(*) >= 60 AND abs(corr(a.ret1d, b.ret1d)) >= 0.7
            )
            INSERT INTO graph.correlations (
                as_of_date, window_days, left_security_id, right_security_id,
                relationship_type, correlation_value, method
            )
            SELECT
                p.as_of_date,
                90,
                ls.security_id,
                rs.security_id,
                'STOCK_STOCK',
                p.c,
                'pearson'
            FROM pairs p
            JOIN ref.security_master ls ON ls.entity_type='EQUITY' AND ls.symbol = p.left_symbol
            JOIN ref.security_master rs ON rs.entity_type='EQUITY' AND rs.symbol = p.right_symbol
            ON CONFLICT (as_of_date, window_days, left_security_id, right_security_id, relationship_type, method)
            DO UPDATE SET correlation_value = EXCLUDED.correlation_value
            """,
            target_date,
            timeout=600,
        )

        # 6) DQ quality score snapshot for core datasets (simple deterministic scoring).
        dq_rows = await conn.execute(
            """
            WITH latest_day AS (
                SELECT COALESCE($1::date, max(as_of_date)) AS d FROM nidp.prices_eod
            ),
            metric AS (
                SELECT 'prices_eod'::text AS dataset_name,
                       (SELECT count(*) FROM nidp.prices_eod p, latest_day l WHERE p.as_of_date = l.d) AS row_count,
                       (SELECT count(*) FROM nidp.prices_eod p, latest_day l WHERE p.as_of_date = l.d AND p.close_price IS NOT NULL) AS valid_count
                UNION ALL
                SELECT 'stock_features_daily',
                       (SELECT count(*) FROM nidp.stock_features_daily f, latest_day l WHERE f.as_of_date = l.d),
                       (SELECT count(*) FROM nidp.stock_features_daily f, latest_day l WHERE f.as_of_date = l.d AND f.rsi14 IS NOT NULL)
            )
            INSERT INTO dq.quality_scores (
                target_date, dataset_name, freshness_score, accuracy_score, consistency_score, completeness_score, overall_score, quality_tier
            )
            SELECT
                l.d,
                m.dataset_name,
                100.0,
                CASE WHEN m.row_count = 0 THEN 0 ELSE round((m.valid_count::numeric / m.row_count) * 100.0, 3) END,
                100.0,
                CASE WHEN m.row_count = 0 THEN 0 ELSE round((m.valid_count::numeric / m.row_count) * 100.0, 3) END,
                CASE WHEN m.row_count = 0 THEN 0 ELSE round((m.valid_count::numeric / m.row_count) * 100.0, 3) END,
                CASE
                    WHEN m.row_count = 0 THEN 'REVIEW'
                    WHEN (m.valid_count::numeric / m.row_count) >= 0.99 THEN 'PLATINUM'
                    WHEN (m.valid_count::numeric / m.row_count) >= 0.95 THEN 'GOLD'
                    WHEN (m.valid_count::numeric / m.row_count) >= 0.90 THEN 'SILVER'
                    ELSE 'REVIEW'
                END
            FROM metric m
            CROSS JOIN latest_day l
            ON CONFLICT DO NOTHING
            """,
            target_date,
        )

        # 7) Daily market snapshot from index close + flows.
        snap_rows = await conn.execute(
            """
            WITH dayx AS (
                SELECT COALESCE($1::date, max(as_of_date)) AS d FROM nidp.index_eod
            ),
            idx AS (
                SELECT
                    max(close_price) FILTER (WHERE lower(index_name)='nifty 50')   AS nifty50_close,
                    max(close_price) FILTER (WHERE lower(index_name)='nifty bank') AS banknifty_close
                FROM nidp.index_eod i, dayx d
                WHERE i.as_of_date = d.d
            ),
            flows AS (
                SELECT
                    sum(net_value_cr) FILTER (WHERE category='FII') AS fii_net_cr,
                    sum(net_value_cr) FILTER (WHERE category='DII') AS dii_net_cr
                FROM nidp.fii_dii_flows f, dayx d
                WHERE f.as_of_date = d.d
            )
            INSERT INTO analytics.market_snapshot (
                as_of_date, fii_net_cr, dii_net_cr, nifty50_close, banknifty_close, market_regime, summary_json
            )
            SELECT
                d.d,
                fl.fii_net_cr,
                fl.dii_net_cr,
                i.nifty50_close,
                i.banknifty_close,
                CASE
                    WHEN fl.fii_net_cr > 0 AND i.nifty50_close IS NOT NULL THEN 'RISK_ON'
                    WHEN fl.fii_net_cr < 0 THEN 'RISK_OFF'
                    ELSE 'NEUTRAL'
                END,
                jsonb_build_object('source','intelligence_layer','as_of',d.d)
            FROM dayx d
            CROSS JOIN idx i
            CROSS JOIN flows fl
            ON CONFLICT (as_of_date)
            DO UPDATE SET
                fii_net_cr      = EXCLUDED.fii_net_cr,
                dii_net_cr      = EXCLUDED.dii_net_cr,
                nifty50_close   = EXCLUDED.nifty50_close,
                banknifty_close = EXCLUDED.banknifty_close,
                market_regime   = EXCLUDED.market_regime,
                summary_json    = EXCLUDED.summary_json
            """,
            target_date,
        )

        return {
            "as_of": as_of,
            "security_master_equity": _rows_affected(eq_rows),
            "security_master_mf":     _rows_affected(mf_rows),
            "feature_rows":           _rows_affected(feat_rows),
            "entity_links":           _rows_affected(link_rows),
            "correlations":           _rows_affected(corr_rows),
            "dq_scores":              _rows_affected(dq_rows),
            "market_snapshots":       _rows_affected(snap_rows),
        }
