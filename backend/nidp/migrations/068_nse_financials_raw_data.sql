-- 068_nse_financials_raw_data.sql
--
-- Add raw_data JSONB column to nidp.nse_financials_quarterly.
--
-- Stores the full structured payload from the source (Screener.in table,
-- NSE XBRL JSON, LLM response, etc.) so future financial metrics can be
-- extracted without re-scraping.
--
-- Schema: { "source": "screener_in", "quarters": ["Mar 2025", ...],
--            "data": { "sales": [val, ...], "expenses": [...], ... } }

SET search_path TO nidp, public;

ALTER TABLE nidp.nse_financials_quarterly
    ADD COLUMN IF NOT EXISTS raw_data JSONB;

COMMENT ON COLUMN nidp.nse_financials_quarterly.raw_data IS
    'Full structured payload from source. '
    'Screener.in: { quarters: [...], data: { metric: [vals...] } }. '
    'LLM: raw extracted JSON dict.';

INSERT INTO nidp.schema_migrations(filename)
    VALUES ('068_nse_financials_raw_data.sql')
    ON CONFLICT (filename) DO NOTHING;
