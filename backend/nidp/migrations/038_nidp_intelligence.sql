-- ── Event-Driven Market Intelligence ──────────────────────────────────
-- Extends corporate_event_signals with scoring + confirmation columns
-- and adds an intelligence_alerts log for sent Telegram/other messages.

-- Impact score + market confirmation on each signal row
ALTER TABLE nidp.corporate_event_signals
    ADD COLUMN IF NOT EXISTS impact_score         NUMERIC(5,2),   -- 0-100
    ADD COLUMN IF NOT EXISTS confirmation_json    JSONB,          -- volume/delivery/OI data
    ADD COLUMN IF NOT EXISTS breakout_score       NUMERIC(5,2),   -- 0-100
    ADD COLUMN IF NOT EXISTS breakout_confidence  TEXT,           -- HIGH | MEDIUM | LOW
    ADD COLUMN IF NOT EXISTS alert_sent           BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS alert_sent_at        TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_signals_impact_score
    ON nidp.corporate_event_signals(impact_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_signals_breakout
    ON nidp.corporate_event_signals(breakout_confidence, event_date DESC)
    WHERE alert_sent = FALSE;


-- Intelligence alerts log — one row per outbound notification
CREATE TABLE IF NOT EXISTS nidp.intelligence_alerts (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT REFERENCES nidp.corporate_event_signals(id),
    symbol          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    alert_type      TEXT NOT NULL,   -- 'breakout' | 'd1_prep' | 'event_day' | 'post_event'
    channel         TEXT NOT NULL,   -- 'telegram' | 'email'
    message_text    TEXT NOT NULL,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered       BOOLEAN NOT NULL DEFAULT FALSE,
    error_msg       TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol_date
    ON nidp.intelligence_alerts(symbol, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_type_date
    ON nidp.intelligence_alerts(alert_type, sent_at DESC);


INSERT INTO nidp.schema_migrations(filename)
    VALUES ('038_nidp_intelligence.sql')
    ON CONFLICT (filename) DO NOTHING;
