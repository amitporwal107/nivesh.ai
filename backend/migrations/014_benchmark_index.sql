-- 014_benchmark_index.sql
--
-- Benchmark Index Data Service tables (per PRD shared 2026-04-30).
-- Three tables:
--   * market_index_data   — daily OHLCV per index
--   * index_metrics       — derived metrics (1D/1Y/3Y/5Y returns, vol, drawdown)
--   * fund_benchmark_map  — maps fund category → benchmark index
--
-- Seeded with the standard NSE indices and the default
-- category-to-benchmark mapping the MF + equity engines will consume.

CREATE TABLE IF NOT EXISTS market_index_data (
    id          BIGSERIAL PRIMARY KEY,
    index_name  VARCHAR(64)   NOT NULL,
    date        DATE          NOT NULL,
    open        NUMERIC(18,4),
    high        NUMERIC(18,4),
    low         NUMERIC(18,4),
    close       NUMERIC(18,4) NOT NULL,
    volume      BIGINT,
    source      VARCHAR(32)   DEFAULT 'yfinance',
    created_at  TIMESTAMPTZ   DEFAULT NOW(),
    updated_at  TIMESTAMPTZ   DEFAULT NOW(),
    UNIQUE(index_name, date)
);
CREATE INDEX IF NOT EXISTS idx_market_index_data_name_date
    ON market_index_data(index_name, date DESC);


CREATE TABLE IF NOT EXISTS index_metrics (
    index_name   VARCHAR(64)   NOT NULL,
    date         DATE          NOT NULL,
    return_1d    NUMERIC(10,6),
    return_1m    NUMERIC(10,6),
    return_3m    NUMERIC(10,6),
    return_6m    NUMERIC(10,6),
    return_1y    NUMERIC(10,6),
    return_3y    NUMERIC(10,6),
    return_5y    NUMERIC(10,6),
    volatility   NUMERIC(10,6),       -- annualised σ of daily log returns
    drawdown     NUMERIC(10,6),       -- current drawdown from rolling peak
    max_drawdown NUMERIC(10,6),       -- worst observed in trailing 5y
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (index_name, date)
);


CREATE TABLE IF NOT EXISTS fund_benchmark_map (
    fund_category    VARCHAR(80)  PRIMARY KEY,
    benchmark_index  VARCHAR(64)  NOT NULL,
    notes            TEXT,
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
);


-- ── PRD-pinned core mapping (DO NOT change without product sign-off) ──
-- These 4 are the canonical fund-category → benchmark pairings. The
-- daily refresh job checks all 4 land successfully every run.
--   Large Cap   → Nifty 50
--   Mid Cap     → Nifty Midcap 150
--   Small Cap   → Nifty Smallcap 250
--   Flexicap    → Nifty 500
--
-- Default category → benchmark mapping. Mirrors AMFI's typical
-- benchmark assignments. New categories or rebalances overwrite via
-- ON CONFLICT.
INSERT INTO fund_benchmark_map (fund_category, benchmark_index, notes) VALUES
    -- PRD-pinned core 4
    ('Large Cap',        'NIFTY_50',           'PRD core: top-50 by market cap'),
    ('Mid Cap',          'NIFTY_MIDCAP_150',   'PRD core: top 150 mid-caps'),
    ('Small Cap',        'NIFTY_SMALLCAP_250', 'PRD core: top 250 small-caps'),
    ('Flexi Cap',        'NIFTY_500',          'PRD core: broad 500 universe'),
    ('Flexicap',         'NIFTY_500',          'PRD core: broad 500 universe (alias)'),
    -- Adjacent / legacy categories
    ('Large & Mid Cap',  'NIFTY_LARGEMIDCAP_250', 'Combined large + mid cap universe'),
    ('Multi Cap',        'NIFTY_500',          'Broad-based 500 universe'),
    ('Focused',          'NIFTY_500',          'Concentrated portfolio fund'),
    ('Value',            'NIFTY_500',          'Value-oriented diversified'),
    ('Contra',           'NIFTY_500',          'Contrarian-style diversified'),
    ('Dividend Yield',   'NIFTY_DIV_OPPS_50',  'High dividend yield basket'),
    ('Equity Linked Savings Scheme', 'NIFTY_500', 'ELSS / tax-saver'),
    ('ELSS',             'NIFTY_500',          'ELSS / tax-saver'),
    ('Index',            'NIFTY_50',           'Default index for index funds'),
    ('Balanced Advantage','NIFTY_50_HYBRID',   'Dynamic asset allocation'),
    ('Hybrid Aggressive','NIFTY_50_HYBRID',    'Aggressive hybrid'),
    ('Hybrid Conservative','NIFTY_DEBT_HYBRID','Conservative hybrid'),
    ('Conservative Hybrid','NIFTY_DEBT_HYBRID','Conservative hybrid'),
    ('Arbitrage',        'NIFTY_ARBITRAGE',    'Arbitrage funds'),
    ('Liquid',           'CRISIL_LIQUID_DEBT', 'Liquid / overnight'),
    ('Ultra Short',      'CRISIL_LIQUID_DEBT', 'Ultra-short duration'),
    ('Short Term',       'CRISIL_SHORT_TERM',  'Short-term debt'),
    ('Corporate Bond',   'CRISIL_CORP_BOND',   'Corporate bond debt'),
    ('Gilt',             'CRISIL_GILT_INDEX',  'Government securities'),
    ('International',    'MSCI_WORLD',         'International equity'),
    ('Sectoral',         'NIFTY_500',          'Sectoral / thematic — placeholder until per-sector index is mapped')
ON CONFLICT (fund_category) DO UPDATE
    SET benchmark_index = EXCLUDED.benchmark_index,
        notes = EXCLUDED.notes,
        updated_at = NOW();
