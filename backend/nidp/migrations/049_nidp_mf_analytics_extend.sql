-- 049_nidp_mf_analytics_extend.sql
-- Extends analytics.fund_category_rank with shorter return periods and
-- additional risk metrics not present in migration 047.
--
-- Adds:
--   return_1m, return_3m, return_6m, return_2y   (point-to-point returns %)
--   return_since_launch_cagr                      (CAGR from launch date)
--   sortino_1y                                    (Sortino ratio, 1-year window)
--   alpha_1y                                      (Jensen's Alpha vs benchmark)
--   beta_1y                                       (systematic risk vs benchmark)
--   scheme_launch_date                            (denormalised from scheme_master)
--   data_since_date                               (earliest NAV in our DB)
--   nav_count                                     (number of NAV observations available)
-- ──────────────────────────────────────────────────────────────────────────────

SET search_path TO analytics, nidp, public;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'analytics' AND table_name = 'fund_category_rank'
    ) THEN
        RAISE NOTICE '049 deferred: analytics.fund_category_rank not present (needs 047).';
        RETURN;
    END IF;

    EXECUTE $ddl$
        ALTER TABLE analytics.fund_category_rank
            ADD COLUMN IF NOT EXISTS return_1m               NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS return_3m               NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS return_6m               NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS return_2y               NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS return_since_launch_cagr NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS sortino_1y              NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS alpha_1y                NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS beta_1y                 NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS scheme_launch_date      DATE,
            ADD COLUMN IF NOT EXISTS data_since_date         DATE,
            ADD COLUMN IF NOT EXISTS nav_count               INTEGER,
            ADD COLUMN IF NOT EXISTS sortino_rank            INTEGER,
            ADD COLUMN IF NOT EXISTS alpha_rank              INTEGER
    $ddl$;

    -- Covering index for copilot category screener
    -- Query shape: category='...' AND rank_date=latest ORDER BY composite_rank
    EXECUTE $ddl$
        CREATE INDEX IF NOT EXISTS idx_fcr_category_rank_covering
            ON analytics.fund_category_rank (category, rank_date DESC, composite_rank ASC)
            INCLUDE (scheme_name, amc_code, return_1y, return_3y, return_5y,
                     sharpe_1y, max_drawdown_1y, ter, return_1m, return_3m)
    $ddl$;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('049_nidp_mf_analytics_extend.sql')
    ON CONFLICT (filename) DO NOTHING;
