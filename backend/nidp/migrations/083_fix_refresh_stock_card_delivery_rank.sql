-- Migration 083: Fix analytics.refresh_stock_card — delivery_rank subquery
-- referenced vol_z20 from analytics.stock_card (does not exist there);
-- the correct column name in analytics.stock_card is deliv_surge_z.

CREATE OR REPLACE FUNCTION analytics.refresh_stock_card(p_date date)
RETURNS integer
LANGUAGE plpgsql
AS $function$
DECLARE
    inserted INTEGER;
BEGIN
    DELETE FROM analytics.stock_card WHERE as_of_date = p_date;

    INSERT INTO analytics.stock_card (
        symbol, as_of_date,
        company_name, sector, industry, isin,
        in_nifty50, in_nifty500,
        close, prev_close, pct_change, volume, avg_volume_20,
        vol_ratio, deliv_pct, deliv_pct_avg_20, deliv_surge_z,
        sma20, sma50, dist_52w_high_pct, dist_52w_low_pct,
        rsi14, macd, macd_hist, bb_pos,
        return_5d_pct, return_20d_pct, return_60d_pct,
        accumulation_score, pivot_breakout_flag, accumulation_signals,
        bulk_buy_qty, bulk_sell_qty, block_deal_count,
        has_upcoming_ca, upcoming_ca_types
    )
    SELECT
        sds.symbol,
        p_date,
        sm.company_name,
        COALESCE(sm.sector, sds.industry),
        sds.industry,
        sm.isin,
        sds.in_nifty50,
        sds.in_nifty500,
        sds.close_price,
        sds.prev_close,
        sds.return_1d_pct,
        sds.volume,
        sfd.avg_volume_20,
        CASE WHEN sfd.avg_volume_20 > 0
             THEN ROUND(sds.volume::NUMERIC / sfd.avg_volume_20, 4)
             ELSE NULL END,
        sds.deliv_pct,
        sfd.deliv_pct_avg_20,
        sfd.vol_z20,
        sfd.sma20,
        sfd.sma50,
        sfd.dist_52w_high_pct,
        sfd.dist_52w_low_pct,
        sfd.rsi14,
        sfd.macd,
        sfd.macd_hist,
        sfd.bb_pos,
        sfd.return_5d_pct,
        sfd.return_20d_pct,
        sfd.return_60d_pct,
        sfd.accumulation_score,
        sfd.pivot_breakout_flag,
        sfd.accumulation_signals,
        sds.bulk_buy_qty,
        sds.bulk_sell_qty,
        sds.block_deal_count,
        sds.has_upcoming_ca,
        sds.upcoming_ca_types
    FROM nidp.stock_daily_snapshot sds
    LEFT JOIN nidp.stock_features_daily sfd
           ON sfd.symbol = sds.symbol AND sfd.as_of_date = p_date
    LEFT JOIN nidp.sector_master sm
           ON sm.symbol = sds.symbol
    WHERE sds.as_of_date = p_date
      AND sds.series = 'EQ';

    GET DIAGNOSTICS inserted = ROW_COUNT;

    UPDATE analytics.stock_card sc
       SET momentum_rank     = r.momentum_rank,
           delivery_rank     = r.delivery_rank,
           accumulation_rank = r.accumulation_rank,
           nifty500_rank     = r.nifty500_rank
      FROM (
          SELECT symbol,
                 ROW_NUMBER() OVER (ORDER BY return_20d_pct    DESC NULLS LAST) AS momentum_rank,
                 ROW_NUMBER() OVER (ORDER BY deliv_surge_z     DESC NULLS LAST) AS delivery_rank,
                 ROW_NUMBER() OVER (ORDER BY accumulation_score DESC NULLS LAST) AS accumulation_rank,
                 ROW_NUMBER() OVER (
                     PARTITION BY CASE WHEN in_nifty500 THEN 1 ELSE NULL END
                     ORDER BY return_20d_pct DESC NULLS LAST
                 ) AS nifty500_rank
            FROM analytics.stock_card
           WHERE as_of_date = p_date
      ) r
     WHERE sc.symbol     = r.symbol
       AND sc.as_of_date = p_date;

    RETURN inserted;
END $function$;
