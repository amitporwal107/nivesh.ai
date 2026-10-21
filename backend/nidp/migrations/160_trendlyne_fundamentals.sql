-- 160_trendlyne_fundamentals.sql
-- Staging for the Trendlyne MCP fundamentals loader (services/trendlyne_fundamentals).
--
-- Trendlyne serves each metric as a value relative to "now" ("Net Profit Qtr",
-- "Net Profit 3Qtr Ago") with no quarter date, 10 stocks x 10 parameters per call,
-- against a daily call cap. So the raw values are staged here exactly as received,
-- and dated quarterly rows are built from them in a separate, repeatable step.

CREATE TABLE IF NOT EXISTS nidp.trendlyne_param_labels (
    parameter    TEXT PRIMARY KEY,          -- the token sent to the tool, e.g. 'npqmq3'
    label        TEXT NOT NULL UNIQUE,      -- the label the tool answers with, e.g. 'Net Profit 3Q Ago'
    learned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nidp.trendlyne_param_values (
    symbol        TEXT        NOT NULL,
    parameter     TEXT        NOT NULL,
    value         NUMERIC,                  -- NULL = the provider had no value for this stock
    as_of_date    DATE        NOT NULL,     -- the date the provider stamps on the response
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_run_id UUID,
    PRIMARY KEY (symbol, parameter)
);

CREATE TABLE IF NOT EXISTS nidp.trendlyne_call_log (
    id         BIGSERIAL PRIMARY KEY,
    called_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tool       TEXT        NOT NULL,
    ok         BOOLEAN     NOT NULL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS trendlyne_call_log_called_at_idx ON nidp.trendlyne_call_log (called_at);
