-- 173: let the point-in-time and reporting-date Smart Money series coexist.
--
-- WHY
-- nidp.smart_money_scores_daily was keyed (as_of_date, symbol), so recomputing a date in
-- point-in-time mode would OVERWRITE the reporting-date row. The two are different measurements
-- of the same date and the interesting question is how far apart they are: the gap IS the
-- look-ahead that a naive historical run would have smuggled into a backtest. Keeping both makes
-- that measurable instead of asserted.
--
-- Existing rows are reporting-date (point_in_time = false): they were computed before the
-- knowledge dates from migrations 171/172 existed.
--
-- Idempotent: safe to re-run.

ALTER TABLE nidp.smart_money_scores_daily
    ADD COLUMN IF NOT EXISTS point_in_time BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN nidp.smart_money_scores_daily.point_in_time IS
  'true = only changes knowable by as_of_date, with a real publication timestamp on both compared '
  'months. false = reporting-date mode, which sees disclosures before they were released and is '
  'therefore valid for stability analysis only, never for a backtest.';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
                WHERE conname = 'smart_money_scores_daily_pkey'
                  AND conrelid = 'nidp.smart_money_scores_daily'::regclass
                  AND array_length(conkey, 1) = 2) THEN
        ALTER TABLE nidp.smart_money_scores_daily
            DROP CONSTRAINT smart_money_scores_daily_pkey;
        ALTER TABLE nidp.smart_money_scores_daily
            ADD CONSTRAINT smart_money_scores_daily_pkey
            PRIMARY KEY (as_of_date, symbol, point_in_time);
    END IF;
END $$;

-- How much a reporting-date run differs from the honest one on the same date. A large gap means a
-- backtest built the naive way would have been reading the future.
CREATE OR REPLACE VIEW nidp.v_smart_money_lookahead_gap AS
SELECT r.as_of_date,
       count(*)                                                        AS common_symbols,
       (SELECT count(*) FROM nidp.smart_money_scores_daily z
         WHERE z.as_of_date = r.as_of_date AND NOT z.point_in_time)     AS reporting_date_symbols,
       (SELECT count(*) FROM nidp.smart_money_scores_daily z
         WHERE z.as_of_date = r.as_of_date AND z.point_in_time)         AS point_in_time_symbols,
       round(corr(r.accumulation_score, p.accumulation_score)::numeric, 3) AS score_corr,
       round(avg(abs(r.accumulation_score - p.accumulation_score))::numeric, 2) AS mean_abs_diff
  FROM nidp.smart_money_scores_daily r
  JOIN nidp.smart_money_scores_daily p
    ON p.as_of_date = r.as_of_date AND p.symbol = r.symbol
   AND p.point_in_time AND NOT r.point_in_time
 GROUP BY r.as_of_date;

COMMENT ON VIEW nidp.v_smart_money_lookahead_gap IS
  'Reporting-date vs point-in-time Smart Money scores on the same date. The difference is the '
  'look-ahead a naive historical run would introduce; coverage shrinks under point-in-time '
  'because undateable AMCs (axis, franklin) drop out.';
