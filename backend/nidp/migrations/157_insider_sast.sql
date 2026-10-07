-- 157: insider & SAST disclosures (the dashboard's INSIDER / SAST lane).
--
-- Why a new table: nidp has no insider/SAST/pledge source. corporate_announcements carries the
-- PDF-level filing, not the parsed transaction, and shareholding_pattern is quarterly aggregate.
-- The Top Movers dashboard's `ins` lane needs per-transaction rows (who, which side, how much,
-- holding after) on a daily timeline, so it gets its own table.
--
-- Source is the Trendlyne ownership feed (get_ownership_deals_insider_sast, type='sast'), which
-- returns both SEBI PIT ("Insider Trading") and SAST reg-29 rows in one table. Loaded by
-- research/trendlyne/bin/insider_sast_to_pg.py. `source` is stored per row so a licence or
-- provenance question can be answered by query rather than by memory.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.insider_sast (
    id                BIGSERIAL PRIMARY KEY,
    symbol            TEXT        NOT NULL,
    report_date       DATE        NOT NULL,   -- "Reported to Exchange": the date the market could see it
    txn_start_date    DATE,                   -- when the dealing actually happened (can precede report_date)
    txn_end_date      DATE,
    client_name       TEXT        NOT NULL,
    client_category   TEXT,                   -- Promoter / Promoter Group / Other / ...
    action            TEXT,                   -- Acquisition / Disposal / Pledge / Revoke / Invoke / ...
    disclosure_type   TEXT,                   -- 'Insider Trading' (SEBI PIT) or 'SAST'
    regulation        TEXT,                   -- e.g. 29(2) on SAST rows
    security_type     TEXT,
    mode              TEXT,                   -- Market Sale / Off Market / Inter-se-Transfer / Offer For Sale
    quantity          BIGINT,
    holding_after     BIGINT,
    holding_after_pct NUMERIC(9,4),
    pct_traded        NUMERIC(12,6),
    average_price     NUMERIC(18,4),
    value_rupees      NUMERIC(22,2),
    source            TEXT        NOT NULL DEFAULT 'trendlyne',
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The feed's real action domain. Pledge is the single most common value (promoter share
    -- pledging under SAST reg 29) and is NOT a change of ownership — it changes encumbrance — so it
    -- is kept as its own action rather than folded into Acquisition/Disposal or nulled.
    CONSTRAINT insider_sast_action_chk
        CHECK (action IS NULL OR action IN (
            'Acquisition', 'Disposal', 'Pledge', 'Revoke', 'Invoke',
            'Non-Disposable Undertaking', 'Others'))
);

-- One row per (symbol, report date, party, side, quantity). Trendlyne legitimately returns several
-- rows for one party on one date (tranches at different prices / holdings), so average_price is
-- part of the key; without it a re-run would collapse distinct tranches into one.
CREATE UNIQUE INDEX IF NOT EXISTS insider_sast_uniq
    ON nidp.insider_sast (symbol, report_date, client_name, COALESCE(action, ''),
                          COALESCE(quantity, -1), COALESCE(average_price, -1));

-- The dashboard always queries "this symbol, this date window".
CREATE INDEX IF NOT EXISTS insider_sast_symbol_date_idx
    ON nidp.insider_sast (symbol, report_date DESC);

COMMENT ON TABLE nidp.insider_sast IS
    'Per-transaction insider (SEBI PIT) and SAST disclosures. Source: Trendlyne ownership feed. '
    'report_date is the exchange-reported date — use it, not txn_start_date, for event alignment.';
