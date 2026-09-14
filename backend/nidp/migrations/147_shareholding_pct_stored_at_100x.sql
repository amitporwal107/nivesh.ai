-- 147_shareholding_pct_stored_at_100x.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Repair: shareholding percentages stored 100x too large.
--
-- The SHP v1.1 XBRL format carries every category in one tag
-- (ShareholdingAsAPercentageOfTotalNumberOfShares). nse_shareholding's parser assumed
-- decimal fractions (0.4504 = 45.04%) and multiplied by 100, but many filings for the
-- June-2025 quarter sent percentages (20.31) in that tag. Those were stored at 100x:
-- AWFIS promoter holding 2031, KPEL FII 63 (0.63%), IONEXCHANG promoter 2570. Found
-- 2026-09-14 while building 4-quarter ownership trends: 1,468 NSE_SHP rows, 1,364 of them
-- dated 2025-06-30, the rest Jul-Sep 2025, so every holding change spanning that quarter
-- was nonsense ("promoter -2,014pp over 4 quarters").
--
-- A percentage above 100 is impossible, and a filing uses one unit throughout, so any row
-- with a percentage above 100 is rescaled in full. The parser now detects the unit per
-- document and refuses impossible rows.
-- ─────────────────────────────────────────────────────────────────────────────
BEGIN;

UPDATE nidp.shareholding_pattern
   SET promoter_pct                  = promoter_pct / 100,
       promoter_pledged_pct          = promoter_pledged_pct / 100,
       promoter_pledged_to_total_pct = promoter_pledged_to_total_pct / 100,
       fii_pct                       = fii_pct / 100,
       dii_pct                       = dii_pct / 100,
       mf_pct                        = mf_pct / 100,
       insurance_pct                 = insurance_pct / 100,
       bank_fi_pct                   = bank_fi_pct / 100,
       govt_holding_pct              = govt_holding_pct / 100,
       public_pct                    = public_pct / 100,
       individual_pct                = individual_pct / 100,
       nri_pct                       = nri_pct / 100,
       bodies_corporate_pct          = bodies_corporate_pct / 100
 WHERE GREATEST(promoter_pct, promoter_pledged_pct, promoter_pledged_to_total_pct, fii_pct, dii_pct,
                mf_pct, insurance_pct, bank_fi_pct, govt_holding_pct, public_pct, individual_pct,
                nri_pct, bodies_corporate_pct) > 100;

DO $$
DECLARE v_left INT;
BEGIN
    SELECT count(*) INTO v_left FROM nidp.shareholding_pattern
     WHERE GREATEST(promoter_pct, fii_pct, dii_pct, mf_pct, public_pct) > 100;
    RAISE NOTICE '147: rows still above 100 after repair: %', v_left;
END $$;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('147_shareholding_pct_stored_at_100x.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
