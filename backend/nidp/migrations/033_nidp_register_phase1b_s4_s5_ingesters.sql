-- 033_nidp_register_phase1b_s4_s5_ingesters.sql
--
-- Seeds nidp.source_registry rows for the 9 ingesters added in Phase
-- 1B and S4/S5 (announcements + classifier + parser). These services
-- were deployed to Cloud Run but their registry rows were never
-- seeded — meaning the UPDATE in nidp.shared.storage.job_log
-- (which expects the row to already exist) silently affected zero rows
-- on every run, leaving them invisible in v_feed_status / the NIDP
-- Console feeds list.
--
-- Symptom this fixes: Cloud Run shows 22 jobs running successfully,
-- but the NIDP Console "Feeds" tab shows only 13 entries.
--
-- Idempotent — INSERT ... ON CONFLICT DO NOTHING preserves any rows
-- the UPDATE may have already created (none expected, but cheap to
-- guard).
--
-- After this migration runs, trigger each of the 9 ingesters once
-- (or wait for the next scheduled run) so their dashboard counters
-- (last_run_at, success_count, etc.) populate.

SET search_path TO nidp, public;

INSERT INTO nidp.source_registry
    (source_name, ingester, source_url_pattern,
     source_class, confidence, is_primary, expected_freq, notes)
VALUES
    -- ── Phase 1B ─────────────────────────────────────────────────
    ('NSE_FINANCIALS',
     'nse_financials',
     'https://www.nseindia.com/api/corporates-financial-results',
     'A', 0.95, TRUE, 'quarterly',
     'Quarterly company financials (P&L + balance sheet) via XBRL filings'),

    ('NSE_SHAREHOLDING',
     'nse_shareholding',
     'https://www.nseindia.com/api/corporates-shareholding-pattern',
     'A', 0.95, TRUE, 'quarterly',
     'Quarterly shareholding patterns — promoter/FII/DII/MF % + pledge'),

    ('NIDP_PRICE_ADJUSTER',
     'price_adjuster',
     'derived://nidp.prices_eod+nidp.corporate_actions',
     'A', 1.00, TRUE, 'event',
     'Derived feed — applies splits/bonuses/dividends to produce prices_eod_adjusted'),

    ('NSE_EQUITY_MASTER',
     'nse_equity_master',
     'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',
     'A', 0.95, TRUE, 'monthly',
     'NSE listed equities master — symbol → ISIN → company name mapping'),

    ('NSE_FNO_BHAVCOPY',
     'fno_bhavcopy',
     'https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_${YYYYMMDD}_F_0000.csv',
     'A', 0.95, TRUE, 'daily',
     'F&O bhavcopy — per-contract OHLC, OI, contracts traded'),

    -- ── S4 — corporate announcements ─────────────────────────────
    ('NSE_CORPORATE_ANNOUNCEMENTS',
     'corporate_announcements_nse',
     'https://www.nseindia.com/api/corporate-announcements',
     'A', 0.95, TRUE, 'event',
     'Real-time NSE corporate filings (5-min cadence)'),

    ('BSE_CORPORATE_ANNOUNCEMENTS',
     'corporate_announcements_bse',
     'https://api.bseindia.com/BseIndiaAPI/api/AnnGetData',
     'A', 0.95, TRUE, 'event',
     'Real-time BSE corporate filings (5-min cadence)'),

    -- ── S5 — classifier + document pipeline ──────────────────────
    ('NIDP_ANNOUNCEMENT_CLASSIFIER',
     'announcement_classifier',
     'derived://nidp.corporate_announcements',
     'A', 1.00, TRUE, 'event',
     'Haiku-based impact tier classifier for corporate_announcements'),

    ('NIDP_DOCUMENT_PARSER',
     'document_parser',
     'derived://nidp.corporate_announcements (PDF attachments)',
     'A', 1.00, TRUE, 'event',
     'Downloads + parses + chunks + embeds PDF attachments referenced by announcements')

ON CONFLICT (source_name) DO NOTHING;


INSERT INTO nidp.schema_migrations(filename)
    VALUES ('033_nidp_register_phase1b_s4_s5_ingesters.sql')
    ON CONFLICT (filename) DO NOTHING;
