-- 156_event_asof.sql — nidp.v_event_asof: the ONE as-of interface to event state.
--
-- Depends on: 154_announcement_security_resolution.sql (v_announcement_security),
--             155_corporate_transactions.sql (lifecycle), prices_eod, nse_holidays.
--
-- WHY
-- Chart/market and event signals are published independently (owner decision
-- 2026-09-25); correlations between them are computed afterwards. Both halves
-- must agree on WHEN the market could know an event. The rule used to live only
-- in research SQL (research/event_direction/event_panel.py); if each consumer
-- re-applies it they double-count or disagree. It is applied ONCE, here.
-- Consumers read this view and apply nothing on top.
--
-- THE AS-OF RULE (filed_at is true IST dissemination time, verified against the
-- NSE broadcast: RAYMOND 13:12:36 vs 13:12:35)
--   D = IST date of filed_at, T = IST time
--   timing_type        pre_market  (D is a session, T <  09:15)
--                      intraday    (D is a session, 09:15 <= T < 15:30)
--                      after_close (D is a session, T >= 15:30)
--                      non_session (weekend / exchange holiday)
--   known_at_open_session   first session whose OPEN can reflect it:
--                           D if pre_market, else the next session after D
--   known_by_close_session  first session whose CLOSE can reflect it:
--                           D if pre_market or intraday, else the next session
--   == the research rule "filed >= 15:30 -> next session".
--
-- SESSIONS come from the dates that actually traded (prices_eod, bhavcopy):
-- checked against an independent Kite NIFTY 50 series, 2024-08-01..2026-09-22,
-- 532 sessions, zero differences either way. Beyond the latest bhavcopy the next
-- session is PROJECTED (weekday, not an NSE CM holiday). Before prices_eod's
-- first date the calendar is unknown and the timing columns are NULL rather than
-- guessed. Special-session hours (Muhurat) are not modelled.
--
-- ONE ROW PER FILING PER EXCHANGE. NSE and BSE copies of one filing are
-- separate rows with no shared id, and their timestamps differ by minutes: on
-- 2026-09-01..22, of 7,136 BSE filings by NSE-listed companies, an NSE filing by
-- the same company existed within 2 min for 20%, within 10 min for 64%, same IST
-- day for 85%. A time-window merge would be both lossy and ambiguous, so rows are
-- not merged. primary_row marks the row to COUNT: every NSE row, and a BSE row
-- only when NSE has nothing from that company that IST day (BSE-only securities
-- and BSE-only days). Count events with WHERE primary_row.
--
-- LABELS ARE RAW. subject/subcategory are the exchange's own categories;
-- event_category/sentiment are the LLM classifier's (2026 only). None of them is
-- a direction: ~410 pre-registered tests (H#35-H#41) found no directional signal
-- in them. taxonomy_era records which exchange vocabulary produced `subject`,
-- because NSE changed it on 2024-09-21 (and in 2022; that history is not loaded
-- yet), so a step change in label density is not an event effect.
--
-- in_sealed_block: 2023-01-01..2024-07-31 is the sealed test period. Consumers
-- must exclude these rows unless running the pre-registered sealed test.

CREATE OR REPLACE FUNCTION nidp.nse_is_session(d date) RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN d IS NULL OR d < (SELECT min(as_of_date) FROM nidp.prices_eod) THEN NULL
        WHEN d <= (SELECT max(as_of_date) FROM nidp.prices_eod)
            THEN EXISTS (SELECT 1 FROM nidp.prices_eod WHERE as_of_date = d)
        ELSE extract(isodow FROM d) < 6
             AND NOT EXISTS (SELECT 1 FROM nidp.nse_holidays h
                             WHERE h.holiday_date = d AND h.segment = 'CM')
    END
$$;

COMMENT ON FUNCTION nidp.nse_is_session(date) IS
    'TRUE if NSE CM traded on d (from prices_eod); projected from weekday + CM holidays '
    'beyond the latest bhavcopy; NULL before prices_eod coverage.';

CREATE OR REPLACE FUNCTION nidp.nse_session_after(d date) RETURNS date
LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE
    lo date; hi date; s date;
BEGIN
    SELECT min(as_of_date), max(as_of_date) INTO lo, hi FROM nidp.prices_eod;
    IF d IS NULL OR d < lo THEN
        RETURN NULL;                     -- calendar unknown: never guess
    END IF;
    IF d < hi THEN
        SELECT min(as_of_date) INTO s FROM nidp.prices_eod WHERE as_of_date > d;
        RETURN s;
    END IF;
    s := d + 1;                          -- projected beyond the latest bhavcopy
    FOR i IN 1..15 LOOP
        IF extract(isodow FROM s) < 6 AND NOT EXISTS (
               SELECT 1 FROM nidp.nse_holidays h WHERE h.holiday_date = s AND h.segment = 'CM') THEN
            RETURN s;
        END IF;
        s := s + 1;
    END LOOP;
    RETURN NULL;
END
$$;

COMMENT ON FUNCTION nidp.nse_session_after(date) IS
    'First NSE CM session strictly after d. Real sessions from prices_eod; projected '
    'beyond the latest bhavcopy; NULL before prices_eod coverage.';

CREATE OR REPLACE VIEW nidp.v_event_asof AS
-- The calendar is built ONCE per query (prices_eod has 578 distinct dates; the
-- DISTINCT takes ~10 ms) and hash-joined on the IST date. Per-row function calls
-- scanned hypertable chunks for every filing and did not finish a full scan in
-- 10 minutes; the functions above remain for ad-hoc use.
WITH sess AS (
    SELECT DISTINCT as_of_date AS d FROM nidp.prices_eod
), bounds AS (
    SELECT min(d) AS lo, max(d) AS hi FROM sess
), projected AS (                       -- beyond the latest bhavcopy
    SELECT g::date AS d
    FROM bounds, generate_series(bounds.hi + 1, bounds.hi + 45, interval '1 day') g
    WHERE extract(isodow FROM g) < 6
      AND NOT EXISTS (SELECT 1 FROM nidp.nse_holidays h WHERE h.holiday_date = g::date AND h.segment = 'CM')
), all_sess AS (
    SELECT d FROM sess UNION ALL SELECT d FROM projected
), cal AS (                             -- one row per calendar day in coverage
    SELECT g::date AS cal_date,
           EXISTS (SELECT 1 FROM all_sess a WHERE a.d = g::date) AS is_session,
           (SELECT min(a.d) FROM all_sess a WHERE a.d > g::date) AS session_after
    FROM bounds, generate_series(bounds.lo, bounds.hi + 40, interval '1 day') g
), e AS (
    SELECT ca.announcement_id, ca.source, ca.filed_at,
           (ca.filed_at AT TIME ZONE 'Asia/Kolkata')::date AS d,
           (ca.filed_at AT TIME ZONE 'Asia/Kolkata')::time AS t,
           ca.subject, ca.subcategory, ca.description, ca.attachment_url,
           ca.event_category, ca.sentiment, ca.impact_score,
           coalesce(ca.raw_payload->>'via', 'api') AS via,
           s.nse_symbol, s.isin, s.scrip_code, s.resolution
    FROM nidp.corporate_announcements ca
    JOIN nidp.v_announcement_security s
      ON s.announcement_id = ca.announcement_id AND s.source = ca.source
), nse_days AS (                        -- (symbol, IST day) pairs NSE filed on
    SELECT DISTINCT ticker_symbol AS sym, (filed_at AT TIME ZONE 'Asia/Kolkata')::date AS d
    FROM nidp.corporate_announcements WHERE source = 'NSE_ANN' AND ticker_symbol IS NOT NULL
)
SELECT
    e.announcement_id, e.source, e.nse_symbol, e.isin, e.scrip_code, e.resolution,
    e.filed_at                                              AS event_ts,
    CASE WHEN e.via = 'cie_bse_rss' THEN 'submission' ELSE 'dissemination' END AS ts_basis,
    CASE WHEN c.cal_date IS NULL THEN NULL
         WHEN NOT c.is_session       THEN 'non_session'
         WHEN e.t < TIME '09:15'     THEN 'pre_market'
         WHEN e.t < TIME '15:30'     THEN 'intraday'
         ELSE 'after_close' END                             AS timing_type,
    CASE WHEN c.cal_date IS NULL THEN NULL
         WHEN c.is_session AND e.t < TIME '09:15' THEN e.d
         ELSE c.session_after END                           AS known_at_open_session,
    CASE WHEN c.cal_date IS NULL THEN NULL
         WHEN c.is_session AND e.t < TIME '15:30' THEN e.d
         ELSE c.session_after END                           AS known_by_close_session,
    (e.source = 'NSE_ANN' OR e.nse_symbol IS NULL OR nd.sym IS NULL) AS primary_row,
    CASE WHEN e.source = 'BSE_ANN' THEN 'bse_subcategory'
         WHEN e.d >= DATE '2024-09-21' THEN 'nse_granular'
         ELSE 'nse_legacy' END                              AS taxonomy_era,
    e.subject, e.subcategory, e.description, e.attachment_url,
    e.event_category, e.sentiment, e.impact_score,
    f.transaction_id, f.family AS lifecycle_family, f.stage AS lifecycle_stage, f.confounded,
    (e.d BETWEEN DATE '2023-01-01' AND DATE '2024-07-31')   AS in_sealed_block,
    e.via
FROM e
LEFT JOIN cal c        ON c.cal_date = e.d
LEFT JOIN nse_days nd  ON e.source = 'BSE_ANN' AND nd.sym = e.nse_symbol AND nd.d = e.d
LEFT JOIN nidp.corporate_transaction_filings f
       ON f.announcement_id = e.announcement_id AND f.source = e.source;

COMMENT ON VIEW nidp.v_event_asof IS
    'One row per exchange filing with the as-of timing applied once: timing_type, '
    'known_at_open_session, known_by_close_session. Count events WHERE primary_row. '
    'Labels are raw and carry no direction. Exclude in_sealed_block outside the sealed test.';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('156_event_asof.sql')
ON CONFLICT (filename) DO NOTHING;
