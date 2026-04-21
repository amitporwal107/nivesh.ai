-- V3 Engine: benchmark→proxy fund mapping for downside_capture computation.
ALTER TABLE benchmark_master
    ADD COLUMN IF NOT EXISTS proxy_instrument_id UUID REFERENCES instrument_master(instrument_id);

CREATE INDEX IF NOT EXISTS idx_benchmark_proxy ON benchmark_master(proxy_instrument_id);
