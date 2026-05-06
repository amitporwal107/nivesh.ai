-- 023_nidp_market_session.sql — single source of truth for "what's
-- the last fully-closed NSE session?".
--
-- Why: ingesters that fire on a Cloud Scheduler cron need to know
-- which date they should pull. "today IST" is wrong before 18:30
-- (file not published yet); "yesterday IST" is wrong after market
-- close (we'd skip today's freshly-published file). Holidays and
-- weekends complicate both. Centralising the answer in the DB lets
-- every ingester ask the same question and get the same answer.
--
-- Layout:
--   nidp.market_session_state                  — denormalised row,
--     one per market (just NSE_EQ today).
--   nidp.compute_last_trading_day_ist(ts?)     — pure SQL function,
--     walks nse_holidays, applies 18:30 IST cutoff.
--   nidp.v_market_session                      — view that returns
--     the table value but auto-falls-back to the function if the
--     stored value is older than 24h (table not yet maintained).
--
-- Maintenance: BaseIngester (Python) refreshes the row after every
-- successful bhavcopy run, setting last_close_date = target_date.
-- The 24h stale-fallback in the view means even a totally
-- unmaintained table still gives correct answers.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.market_session_state (
    market                  TEXT PRIMARY KEY,           -- 'NSE_EQ', 'NSE_FNO', …
    last_close_date         DATE NOT NULL,              -- most recent closed session
    last_close_observed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes                   TEXT,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── SQL function: walk holidays + apply 18:30 IST cutoff ────────────
CREATE OR REPLACE FUNCTION nidp.compute_last_trading_day_ist(
    at_ist TIMESTAMPTZ DEFAULT NOW()
) RETURNS DATE AS $$
DECLARE
    ist_now   TIMESTAMP;
    boundary  DATE;
    candidate DATE;
BEGIN
    ist_now := at_ist AT TIME ZONE 'Asia/Kolkata';
    boundary := DATE(ist_now);

    -- Before 18:30 IST today, today's session isn't closed yet.
    IF ist_now < (DATE_TRUNC('day', ist_now) + INTERVAL '18 hours 30 minutes') THEN
        boundary := boundary - 1;
    END IF;

    candidate := boundary;
    -- Walk back up to 14 days through weekends + known holidays.
    FOR i IN 0..14 LOOP
        IF EXTRACT(ISODOW FROM candidate) NOT IN (6, 7)
           AND NOT EXISTS (
               SELECT 1 FROM nidp.nse_holidays WHERE holiday_date = candidate
           ) THEN
            RETURN candidate;
        END IF;
        candidate := candidate - 1;
    END LOOP;

    -- Fallback (shouldn't happen with current calendar): return the
    -- boundary even if it's a weekend/holiday — caller's ingester
    -- will fail loudly, which is the right behaviour.
    RETURN boundary;
END $$ LANGUAGE plpgsql STABLE;


-- ── View: stored value, auto-fallback to compute if stale ───────────
CREATE OR REPLACE VIEW nidp.v_market_session AS
SELECT
    s.market,
    CASE
        -- Stored value older than 24h — treat as stale; recompute.
        WHEN s.last_close_observed_at < NOW() - INTERVAL '24 hours'
            THEN nidp.compute_last_trading_day_ist()
        ELSE s.last_close_date
    END AS last_close_date,
    s.last_close_observed_at,
    s.notes
FROM nidp.market_session_state s;


-- ── Bootstrap NSE_EQ row ────────────────────────────────────────────
INSERT INTO nidp.market_session_state (market, last_close_date, notes)
VALUES (
    'NSE_EQ',
    nidp.compute_last_trading_day_ist(),
    'bootstrapped from compute_last_trading_day_ist() — nidp.nse_holidays must be populated'
)
ON CONFLICT (market) DO NOTHING;


COMMENT ON TABLE nidp.market_session_state IS
    'Denormalised "last NSE close" — read by ingesters that need a target date. '
    'Bumped after every successful bhavcopy ingestion (run.target_date). '
    'View nidp.v_market_session auto-recomputes if the row is stale.';
