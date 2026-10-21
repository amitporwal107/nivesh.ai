-- 161_fund_category_rank_return_5y_rank.sql
-- mf_analytics_engine ranks funds on 5-year return and writes return_5y_rank, but no
-- migration ever created the column (it existed only on the old staging database, added
-- by hand). On a database built from migrations the ranking step failed with
--   column "return_5y_rank" of relation "fund_category_rank" does not exist
-- and the engine exited non-zero after computing the returns.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'analytics' AND table_name = 'fund_category_rank') THEN
        ALTER TABLE analytics.fund_category_rank ADD COLUMN IF NOT EXISTS return_5y_rank INTEGER;
    ELSE
        RAISE NOTICE '161 deferred: analytics.fund_category_rank not present (needs 047).';
    END IF;
END $$;
