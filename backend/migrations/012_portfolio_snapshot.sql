CREATE TABLE IF NOT EXISTS portfolio_snapshot_master (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    client_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,

    total_value NUMERIC(14,2),
    total_invested NUMERIC(14,2),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (client_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshot_holdings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    snapshot_id UUID REFERENCES portfolio_snapshot_master(id) ON DELETE CASCADE,

    instrument_id UUID NOT NULL,

    units NUMERIC(18,6),
    current_value NUMERIC(14,2),
    weight_pct NUMERIC(5,2),

    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE (snapshot_id, instrument_id)
);

-- 🔥 PERFORMANCE INDEXES
CREATE INDEX IF NOT EXISTS idx_pf_snapshot_client
ON portfolio_snapshot_master (client_id);

CREATE INDEX IF NOT EXISTS idx_pf_holdings_instrument
ON portfolio_snapshot_holdings (instrument_id);