-- 010_stock_morningstar.sql
-- Add Morningstar quantitative star rating to the stock_scores table.
-- One column addition; safe to re-run (IF NOT EXISTS guard).

ALTER TABLE stock_scores
    ADD COLUMN IF NOT EXISTS morningstar_rating INTEGER;

COMMENT ON COLUMN stock_scores.morningstar_rating IS
    'Morningstar quantitative star rating (1-5) sourced from apac-api.morningstar.com';
