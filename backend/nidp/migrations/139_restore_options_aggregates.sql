-- 139_restore_options_aggregates.sql
--
-- options_pcr / options_total_oi / options_oi_change_pct were 0% filled even
-- though nidp.fno_bhavcopy lands every session (34,088 rows on 2026-09-11).
-- Migrations 029, 053 and 070 computed them in a "pass 2" of
-- populate_stock_features_extended; 091 rewrote that function without the pass,
-- and nothing has written the columns since.
--
-- Restored as its own function with 070's SQL, so populate_stock_features_extended
-- stays exactly as 136 left it; fundamental_engine calls this right after it.
-- PCR = put OI / call OI at each underlying's nearest expiry; NULL when call OI is 0.
-- Re-runnable.

CREATE OR REPLACE FUNCTION nidp.populate_stock_options_features(p_target_date date)
  RETURNS integer
  LANGUAGE plpgsql
AS $function$
DECLARE v_rows INTEGER;
BEGIN
    UPDATE nidp.stock_features_daily f
       SET options_pcr           = opt.pcr,
           options_total_oi      = opt.total_oi,
           options_oi_change_pct = opt.oi_change_pct
      FROM (
        WITH nearest_exp AS (
            SELECT DISTINCT ON (ticker_symbol) ticker_symbol, expiry_date
              FROM nidp.fno_bhavcopy
             WHERE as_of_date = p_target_date
               AND option_type IN ('CE', 'PE')
               AND expiry_date >= p_target_date
             ORDER BY ticker_symbol, expiry_date ASC
        )
        SELECT f.ticker_symbol AS symbol,
               ROUND((SUM(CASE WHEN f.option_type = 'PE' THEN f.open_interest END)::NUMERIC
                    / NULLIF(SUM(CASE WHEN f.option_type = 'CE' THEN f.open_interest END), 0))::NUMERIC, 4) AS pcr,
               SUM(f.open_interest)::BIGINT AS total_oi,
               ROUND((SUM(f.change_in_oi)::NUMERIC
                    / NULLIF(SUM(f.open_interest) - SUM(f.change_in_oi), 0) * 100)::NUMERIC, 4) AS oi_change_pct
          FROM nidp.fno_bhavcopy f
          JOIN nearest_exp ne ON ne.ticker_symbol = f.ticker_symbol AND ne.expiry_date = f.expiry_date
         WHERE f.as_of_date = p_target_date
           AND f.option_type IN ('CE', 'PE')
         GROUP BY f.ticker_symbol
      ) opt
     WHERE f.symbol = opt.symbol
       AND f.as_of_date = p_target_date;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$function$;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('139_restore_options_aggregates.sql')
ON CONFLICT (filename) DO NOTHING;
