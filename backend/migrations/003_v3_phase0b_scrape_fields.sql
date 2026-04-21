-- V3 Engine Phase 0b: fields scraped natively from Groww __NEXT_DATA__.
-- All fields feed the Quality/Health/Portfolio-Fit composite scores.
-- Applied additively. Safe to re-run.

-- ── Fund identity / age
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS allotment_date DATE;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS fund_age_years NUMERIC(4, 1);

-- ── Fund manager (primary + full roster snapshot)
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS manager_since DATE;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS manager_education TEXT;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS manager_funds_count INTEGER;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS fund_managers JSONB;

-- ── Expense history / trend
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS expense_ratio_3y_ago NUMERIC(5, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS expense_trend_delta NUMERIC(5, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS historic_expense_json JSONB;

-- ── Turnover (Groww exposes this in historic_fund_expense rows)
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS turnover_ratio NUMERIC(6, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS turnover_as_of DATE;

-- ── Category peer averages & rank (Groww "stats" array)
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS category_avg_1y NUMERIC(6, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS category_avg_3y NUMERIC(6, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS category_avg_5y NUMERIC(6, 2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS rank_within_category_1y INTEGER;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS rank_within_category_3y INTEGER;
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS rank_within_category_5y INTEGER;

-- ── Portfolio concentration (top-10 weight)
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS top10_concentration_pct NUMERIC(5, 2);

-- ── Sibling plan (regular ⇄ direct) for expense-parity lookup
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS sibling_slug TEXT;

-- ── Analysis (Groww PROS/CONS bullets with qualitative rating)
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS analysis_json JSONB;
