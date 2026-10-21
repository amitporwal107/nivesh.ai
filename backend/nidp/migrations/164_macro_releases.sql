-- 164_macro_releases.sql
-- Scheduled macro-economic releases (India and US) for the trading desk's Events calendar, Macro half.
--
-- Loaded by services/macro_calendar from FREE sources only:
--   US     FRED API (release dates; first-release values from the ALFRED vintage matrix) and the Fed's FOMC calendar page
--   India  MoSPI "Advance Release Calendar" PDF (CPI, IIP, GDP, PLFS dates), RBI's MPC 2026-27 press release (meeting
--          dates) and the policy repo rate shown on rbi.org.in
--
--   release_date    the release's date in the SOURCE's own calendar (US date for US releases, IST date for India)
--   release_time    'HH:MM' local to release_tz; time_is_typical says it is the agency's usual time (editorial), not a
--                   time read from the calendar
--   impact          'H' | 'M' | 'L': OUR editorial rating (nothing in the free sources rates impact)
--   previous        the previous period's figure as known on the release date; actual NULL until released
--   estimate        ALWAYS NULL: no free source publishes consensus forecasts. The column exists so a licensed feed can
--                   fill it later without a migration
--   period          label of the reference period ('Sep 2026', 'Q3 2026 (advance)', 'Week ending 17 Oct')
--   source_url      the official page the date or value was read from
--
-- One row per indicator per release date. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.macro_releases (
    indicator_code  TEXT        NOT NULL,
    release_date    DATE        NOT NULL,
    country         TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    short_name      TEXT        NOT NULL,
    release_time    TEXT,
    release_tz      TEXT,
    time_is_typical BOOLEAN     NOT NULL DEFAULT TRUE,
    period          TEXT,
    previous        NUMERIC(18,4),
    estimate        NUMERIC(18,4),
    actual          NUMERIC(18,4),
    unit            TEXT,
    impact          CHAR(1)     NOT NULL,
    source          TEXT        NOT NULL,
    source_url      TEXT,
    source_run_id   UUID,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (indicator_code, release_date),
    CONSTRAINT macro_releases_impact_chk  CHECK (impact IN ('H', 'M', 'L')),
    CONSTRAINT macro_releases_country_chk CHECK (country IN ('IN', 'US'))
);

CREATE INDEX IF NOT EXISTS idx_macro_releases_date
    ON nidp.macro_releases (release_date, country);

COMMENT ON TABLE nidp.macro_releases IS
  'Scheduled India / US macro releases from free sources (FRED, Fed, MoSPI, RBI). estimate is always NULL; impact is editorial.';

INSERT INTO nidp.schema_migrations (filename) VALUES ('164_macro_releases.sql')
    ON CONFLICT (filename) DO NOTHING;
