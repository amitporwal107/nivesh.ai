-- 007_goal_planning.sql
-- Goal-Based Investment Planning Engine (GBIPE) schema.

CREATE TABLE IF NOT EXISTS user_financial_snapshots (
    user_id UUID PRIMARY KEY,
    age INT,
    marital_status TEXT,              -- single | married | divorced
    dependents INT DEFAULT 0,
    monthly_income_rs NUMERIC(14, 2),
    income_growth_pct NUMERIC(5, 2) DEFAULT 8.0,
    monthly_expenses_rs NUMERIC(14, 2),
    inflation_pct NUMERIC(5, 2) DEFAULT 6.0,
    current_corpus_rs NUMERIC(14, 2) DEFAULT 0,      -- liquid net-worth snapshot
    total_liabilities_rs NUMERIC(14, 2) DEFAULT 0,
    risk_profile TEXT,                               -- conservative | moderate | aggressive
    behavior_score NUMERIC(5, 2),                    -- optional: from behavioral engine
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS user_goals (
    goal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    goal_type TEXT NOT NULL,           -- retirement | education | home | wealth | custom
    goal_name TEXT NOT NULL,
    target_amount_rs NUMERIC(14, 2) NOT NULL,        -- in TODAY's rupees
    horizon_years NUMERIC(5, 2) NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',         -- high | medium | low
    inflation_pct NUMERIC(5, 2) DEFAULT 6.0,
    expected_return_pct NUMERIC(5, 2),               -- derived from allocation
    current_corpus_rs NUMERIC(14, 2) DEFAULT 0,      -- already earmarked for this goal
    monthly_sip_rs NUMERIC(14, 2) DEFAULT 0,         -- user's committed SIP
    allocation JSONB,                                -- {equity:60,debt:30,hybrid:10}
    selected_funds JSONB,                            -- {equity:[{instrument_id,name,weight_pct}],...}
    manual_fund_override BOOLEAN DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active',           -- active | achieved | abandoned | paused
    on_track_pct NUMERIC(5, 2),                      -- last computed success %
    last_simulated_at TIMESTAMPTZ,
    last_simulation JSONB,                           -- {base, bull, bear, stress, monte_carlo}
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_goals_user ON user_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_user_goals_status ON user_goals(user_id, status);
