-- ── Feature Flags + D-1 Prep signal type ──────────────────────────────
-- 1. Add signal_type column to corporate_event_signals so D-1 prep
--    briefings coexist with post-event analysis for the same event.
-- 2. Create nidp.feature_flags for runtime on/off toggles without
--    requiring a redeploy. Env var NIDP_FEATURE_<FLAG>=0 overrides DB.

ALTER TABLE nidp.corporate_event_signals
    ADD COLUMN IF NOT EXISTS signal_type TEXT NOT NULL DEFAULT 'post_event';
-- signal_type: 'post_event' | 'd1_prep'

-- Widen the unique constraint to allow both d1_prep and post_event
-- for the same (symbol, event_type, event_date, period).
DO $$
BEGIN
    -- Drop old 4-column constraint if it still exists
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'nidp.corporate_event_signals'::regclass
           AND conname = 'corporate_event_signals_symbol_event_type_event_date_period_key'
    ) THEN
        ALTER TABLE nidp.corporate_event_signals
            DROP CONSTRAINT corporate_event_signals_symbol_event_type_event_date_period_key;
    END IF;
END $$;

ALTER TABLE nidp.corporate_event_signals
    DROP CONSTRAINT IF EXISTS corporate_event_signals_symbol_event_type_event_date_period_signal_type_key;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'corporate_event_signals_uniq'
          AND conrelid = 'nidp.corporate_event_signals'::regclass
    ) THEN
        ALTER TABLE nidp.corporate_event_signals
            ADD CONSTRAINT corporate_event_signals_uniq
            UNIQUE (symbol, event_type, event_date, period, signal_type);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_signals_signal_type
    ON nidp.corporate_event_signals(signal_type, event_date DESC);


-- ── Feature flags table ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.feature_flags (
    flag_name   TEXT PRIMARY KEY,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    notes       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO nidp.feature_flags (flag_name, enabled, notes) VALUES
    ('event_processing',  true,  'Master switch: turns off event_analyzer + d1_prep together'),
    ('d1_prep',           true,  'D-1 evening briefing generation via Claude'),
    ('event_day_polling', true,  'Event-day result polling for companies reporting today'),
    ('telegram_alerts',   false, 'Telegram alert bot — set true once NIDP_TELEGRAM_BOT_TOKEN is configured')
ON CONFLICT (flag_name) DO NOTHING;


INSERT INTO nidp.schema_migrations(filename)
    VALUES ('037_nidp_feature_flags.sql')
    ON CONFLICT (filename) DO NOTHING;
