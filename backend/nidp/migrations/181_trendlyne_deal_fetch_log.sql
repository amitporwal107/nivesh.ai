-- 181: durable per-symbol attempt log for the bulk/block deal ingest.
--
-- WHY
-- The deal ingest is ONE API call per stock against an account allowance of about 1,000 calls a
-- day that every NIDP Trendlyne job shares, so a run is budget-capped and always stops part-way.
-- Until now "where did we get to" was inferred from the FACT table: deals.py ordered its
-- candidates ORDER BY 1 (alphabetical) and skipped symbols whose nidp.trendlyne_deals rows
-- carried retrieved_at::date = current_date. Two faults combine, both measured 2026-10-22:
--
--   1. The marker is DAY-SCOPED. On a new day the skip-set is empty, so the alphabetical walk
--      restarts at 'A' and the same prefix is re-paid for every day. Three runs spent 341 calls
--      and reached candidate 338 of 984; nidp.trendlyne_deals held 19,787 legs over 328 symbols
--      and NOT ONE outside 0-9/A-G (max symbol 'GSPLTRANS'). 643 of 984 candidates were never
--      queried once (656 hold no deal row), and the study consuming this feed could see 1,910 of
--      6,873 eligible symbol-dates (27.8%) — "never asked", not "no institutional interest".
--
--   2. The marker only recorded symbols that PRODUCED ROWS. A symbol queried with no deals wrote
--      nothing, so it was re-queried on every run forever: 341 attempts yielded 328 symbols,
--      i.e. 13 symbols permanently re-paid for out of a shared budget.
--
-- An ATTEMPT is therefore recorded here, separately from the facts, whatever its outcome. deals.py
-- then orders candidates least-recently-attempted first, so coverage self-levels across runs and
-- a budget break can no longer bias the universe alphabetically. No positional cursor is stored:
-- a candidate list that changes between runs needs no reconciliation, because a symbol that is
-- new to the list simply has no row here and therefore sorts first.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.trendlyne_deal_fetch_log (
    symbol          TEXT        PRIMARY KEY,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_status     TEXT        NOT NULL,     -- 'OK' (rows parsed) | 'EMPTY' (none) | 'ERROR'
    last_success_at TIMESTAMPTZ,              -- last non-ERROR attempt
    attempts        INTEGER     NOT NULL DEFAULT 1,
    deal_rows       INTEGER,                  -- rows parsed on the last successful attempt
    last_run_id     UUID
);

-- The ingest's ordering key: least-recently-attempted first.
CREATE INDEX IF NOT EXISTS idx_tl_deal_fetch_log_attempt
    ON nidp.trendlyne_deal_fetch_log (last_attempt_at);

COMMENT ON TABLE nidp.trendlyne_deal_fetch_log IS
  'One row per symbol the bulk/block deal ingest has ASKED Trendlyne about, including symbols '
  'that legitimately returned no deals. Separate from nidp.trendlyne_deals because absence of a '
  'deal row must be distinguishable from absence of a question: conflating the two truncated the '
  'feed to 0-9/A-G (see migration header). Ordering by last_attempt_at is what makes a '
  'budget-capped run resumable across days.';

-- Seed from the history already on disk, so the first run after this migration does NOT re-walk
-- the symbols already fetched before reaching the ones never queried. Without this seed every
-- candidate looks never-attempted and the tie-break would start at 'A' all over again.
-- Symbols attempted before this migration that returned NO deals cannot be recovered (that is
-- exactly fault 2 above) and will be re-attempted once; after that they are recorded.
INSERT INTO nidp.trendlyne_deal_fetch_log
    (symbol, last_attempt_at, last_status, last_success_at, attempts, deal_rows)
SELECT symbol, max(retrieved_at), 'OK', max(retrieved_at), 1, count(*)
  FROM nidp.trendlyne_deals
 GROUP BY symbol
ON CONFLICT (symbol) DO NOTHING;
