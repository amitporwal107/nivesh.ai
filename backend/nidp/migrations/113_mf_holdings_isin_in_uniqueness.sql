-- 113_mf_holdings_isin_in_uniqueness.sql
-- The mf_holdings_monthly PRIMARY KEY was (scheme_code, as_of_month,
-- security_name, source). Debt funds list several DISTINCT instruments under one
-- issuer NAME — e.g. SBI Liquid Fund holds 4 different Kotak Securities CPs (4
-- ISINs) all named "Kotak Securities Ltd." — so on upsert 3 of the 4 collapsed to
-- one PK row and the scheme's weight summed to <100 (26 SBI debt funds affected).
--
-- Re-key the uniqueness on security_isin as well. A PRIMARY KEY can't include the
-- nullable security_isin, so replace it with a UNIQUE constraint. NULLS NOT
-- DISTINCT (PG15+) keeps cash/TREPS/receivables lines (NULL ISIN) idempotent:
-- two NULL-ISIN rows with the same name still collapse, but two real instruments
-- with different ISINs are now kept.
--
-- Existing rows are unique on the old 4-tuple, so they trivially satisfy the wider
-- key — ADD CONSTRAINT cannot fail on current data. Table is NOT a hypertable.
-- Re-runnable.

ALTER TABLE nidp.mf_holdings_monthly
    DROP CONSTRAINT IF EXISTS mf_holdings_monthly_pkey;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nidp.mf_holdings_monthly'::regclass
          AND conname  = 'mf_holdings_monthly_uniq'
    ) THEN
        ALTER TABLE nidp.mf_holdings_monthly
            ADD CONSTRAINT mf_holdings_monthly_uniq
            UNIQUE NULLS NOT DISTINCT
            (scheme_code, as_of_month, security_name, security_isin, source);
    END IF;
END $$;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('113_mf_holdings_isin_in_uniqueness.sql')
ON CONFLICT (filename) DO NOTHING;
