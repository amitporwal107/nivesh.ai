-- 047_nidp_performance_layer.sql
-- Activates the performance optimisations that the earlier migrations
-- described in comments but never actually applied.
--
-- Sections
-- ────────
-- A. TimescaleDB compression policies   (hypertables age ≥ 90 days)
-- B. Covering indexes                   (avoid heap fetches on hot paths)
-- C. analytics.stock_card               (precomputed per-stock dashboard row)
-- D. analytics.sector_snapshot          (precomputed sector aggregates)
-- E. analytics.fund_category_rank       (precomputed MF category leaderboard)
-- F. Materialized views                 (top-momentum, delivery-surge, sector heatmap)
-- G. analytics.refresh_all()            (single function refreshes A–F after pipeline)
-- H. PostgreSQL tuning                  (ALTER SYSTEM, 8 GB VM profile)
--
-- All TimescaleDB blocks are guarded by extension presence so the
-- migration is safe on plain PG dev/test environments.

SET search_path TO nidp, public;


-- ═══════════════════════════════════════════════════════════════════
-- A. COMPRESSION POLICIES
-- ═══════════════════════════════════════════════════════════════════
-- Compress chunks older than 90 days.  Column ordering follows the
-- primary-key structure of each table (leading dimension = best
-- compression ratio for time-sorted data).
-- ───────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        RAISE NOTICE '047: timescaledb not present — skipping compression policies';
        RETURN;
    END IF;

    -- prices_eod  PK: (as_of_date, symbol, series, source)
    BEGIN
        PERFORM add_compression_policy('nidp.prices_eod', INTERVAL '90 days', if_not_exists => TRUE);
        ALTER TABLE nidp.prices_eod SET (
            timescaledb.compress,
            timescaledb.compress_orderby  = 'as_of_date DESC',
            timescaledb.compress_segmentby = 'symbol'
        );
    EXCEPTION WHEN others THEN
        RAISE NOTICE '047: prices_eod compression: %', SQLERRM;
    END;

    -- delivery_data  PK: (as_of_date, symbol, series, source)
    BEGIN
        PERFORM add_compression_policy('nidp.delivery_data', INTERVAL '90 days', if_not_exists => TRUE);
        ALTER TABLE nidp.delivery_data SET (
            timescaledb.compress,
            timescaledb.compress_orderby  = 'as_of_date DESC',
            timescaledb.compress_segmentby = 'symbol'
        );
    EXCEPTION WHEN others THEN
        RAISE NOTICE '047: delivery_data compression: %', SQLERRM;
    END;

    -- stock_features_daily  PK: (symbol, as_of_date, source)
    BEGIN
        PERFORM add_compression_policy('nidp.stock_features_daily', INTERVAL '90 days', if_not_exists => TRUE);
        ALTER TABLE nidp.stock_features_daily SET (
            timescaledb.compress,
            timescaledb.compress_orderby  = 'as_of_date DESC',
            timescaledb.compress_segmentby = 'symbol'
        );
    EXCEPTION WHEN others THEN
        RAISE NOTICE '047: stock_features_daily compression: %', SQLERRM;
    END;

    -- mf_nav_daily
    BEGIN
        PERFORM add_compression_policy('nidp.mf_nav_daily', INTERVAL '90 days', if_not_exists => TRUE);
        ALTER TABLE nidp.mf_nav_daily SET (
            timescaledb.compress,
            timescaledb.compress_orderby  = 'nav_date DESC',
            timescaledb.compress_segmentby = 'scheme_code'
        );
    EXCEPTION WHEN others THEN
        RAISE NOTICE '047: mf_nav_daily compression: %', SQLERRM;
    END;

    -- fno_bhavcopy
    BEGIN
        PERFORM add_compression_policy('nidp.fno_bhavcopy', INTERVAL '90 days', if_not_exists => TRUE);
        ALTER TABLE nidp.fno_bhavcopy SET (
            timescaledb.compress,
            timescaledb.compress_orderby  = 'expiry_date DESC',
            timescaledb.compress_segmentby = 'symbol'
        );
    EXCEPTION WHEN others THEN
        RAISE NOTICE '047: fno_bhavcopy compression: %', SQLERRM;
    END;

    -- rbi_yields
    BEGIN
        PERFORM add_compression_policy('nidp.rbi_yields', INTERVAL '180 days', if_not_exists => TRUE);
        ALTER TABLE nidp.rbi_yields SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'as_of_date DESC'
        );
    EXCEPTION WHEN others THEN
        RAISE NOTICE '047: rbi_yields compression: %', SQLERRM;
    END;

    RAISE NOTICE '047: compression policies applied';
END $$;


-- ═══════════════════════════════════════════════════════════════════
-- B. COVERING INDEXES
-- Avoid heap fetches for the hottest DaaS query shapes.
-- Each index includes all columns returned by the corresponding
-- API endpoint so the planner can do index-only scans.
-- ═══════════════════════════════════════════════════════════════════

-- Screener / signal queries: latest features for all symbols on a date
-- Query shape: WHERE as_of_date = $1 ORDER BY <score> LIMIT N
CREATE INDEX IF NOT EXISTS idx_sfd_date_covering
    ON nidp.stock_features_daily (as_of_date DESC, symbol)
    INCLUDE (close, rsi14, macd_hist, return_20d_pct, return_60d_pct,
             accumulation_score, pivot_breakout_flag, vol_z20,
             deliv_pct_avg_20, deliv_trend10);

-- Symbol time-series: one stock across date range
-- Query shape: WHERE symbol = $1 AND as_of_date BETWEEN $2 AND $3
CREATE INDEX IF NOT EXISTS idx_sfd_symbol_date_covering
    ON nidp.stock_features_daily (symbol, as_of_date DESC)
    INCLUDE (close, rsi14, macd, macd_hist, sma20, sma50,
             return_5d_pct, return_20d_pct, bb_pos, atr_pct);

-- Stock daily snapshot hot path: symbol lookup
CREATE INDEX IF NOT EXISTS idx_sds_symbol_date_covering
    ON nidp.stock_daily_snapshot (symbol, as_of_date DESC)
    INCLUDE (close_price, pct_change_1d, volume, deliv_pct,
             in_nifty50, in_nifty500, industry,
             bulk_deal_count, has_upcoming_ca);

-- Delivery screener: rank by delivery % on a date
CREATE INDEX IF NOT EXISTS idx_delivery_date_symbol
    ON nidp.delivery_data (as_of_date DESC, symbol)
    INCLUDE (deliv_qty, deliv_pct);

-- MF NAV time-series
CREATE INDEX IF NOT EXISTS idx_mf_nav_scheme_date
    ON nidp.mf_nav_daily (scheme_code, nav_date DESC)
    INCLUDE (nav);

-- Portfolio holdings: common dashboard query
CREATE INDEX IF NOT EXISTS idx_port_user_date_covering
    ON portfolio.user_holdings_snapshot (external_user_id, snapshot_date DESC)
    INCLUDE (asset_class, symbol, isin, amfi_scheme_code,
             market_value_inr, weight_pct, quantity);


-- ═══════════════════════════════════════════════════════════════════
-- C. analytics.stock_card
-- One flat row per (symbol, as_of_date).
-- Built nightly by analytics.refresh_all(); served directly by
-- the stock-screener and trader-signal API endpoints.
-- Target: < 100 ms for a single stock, < 500 ms for full Nifty-500 scan.
-- ═══════════════════════════════════════════════════════════════════

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.stock_card (
    symbol               TEXT    NOT NULL,
    as_of_date           DATE    NOT NULL,

    -- Identity
    company_name         TEXT,
    sector               TEXT,
    industry             TEXT,
    isin                 TEXT,
    in_nifty50           BOOLEAN NOT NULL DEFAULT FALSE,
    in_nifty500          BOOLEAN NOT NULL DEFAULT FALSE,

    -- Price
    close                NUMERIC(14,4),
    prev_close           NUMERIC(14,4),
    pct_change           NUMERIC(10,4),
    volume               BIGINT,
    avg_volume_20        BIGINT,
    vol_ratio            NUMERIC(10,4),      -- volume / avg_volume_20
    deliv_pct            NUMERIC(7,4),
    deliv_pct_avg_20     NUMERIC(7,4),
    deliv_surge_z        NUMERIC(10,4),      -- z-score of today's deliv_pct vs 20-day

    -- Trend
    sma20                NUMERIC(14,4),
    sma50                NUMERIC(14,4),
    dist_52w_high_pct    NUMERIC(10,4),
    dist_52w_low_pct     NUMERIC(10,4),

    -- Momentum / oscillators
    rsi14                NUMERIC(7,4),
    macd                 NUMERIC(14,6),
    macd_hist            NUMERIC(14,6),
    bb_pos               NUMERIC(10,6),
    return_5d_pct        NUMERIC(10,4),
    return_20d_pct       NUMERIC(10,4),
    return_60d_pct       NUMERIC(10,4),

    -- Intelligence
    accumulation_score   NUMERIC(7,4),
    pivot_breakout_flag  BOOLEAN,
    accumulation_signals TEXT[],

    -- Institutional flow (same-day bulk/block)
    bulk_buy_qty         BIGINT  NOT NULL DEFAULT 0,
    bulk_sell_qty        BIGINT  NOT NULL DEFAULT 0,
    block_deal_count     INTEGER NOT NULL DEFAULT 0,

    -- Corporate events
    has_upcoming_ca      BOOLEAN NOT NULL DEFAULT FALSE,
    upcoming_ca_types    TEXT[],

    -- Precomputed rankings within the date (lower = better rank)
    momentum_rank        INTEGER,    -- by return_20d_pct DESC
    delivery_rank        INTEGER,    -- by deliv_surge_z DESC
    accumulation_rank    INTEGER,    -- by accumulation_score DESC
    nifty500_rank        INTEGER,    -- momentum_rank restricted to in_nifty500

    -- Build provenance
    built_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_sc_date_momentum
    ON analytics.stock_card (as_of_date DESC, momentum_rank ASC)
    WHERE in_nifty500;

CREATE INDEX IF NOT EXISTS idx_sc_date_delivery
    ON analytics.stock_card (as_of_date DESC, delivery_rank ASC)
    WHERE in_nifty500;

CREATE INDEX IF NOT EXISTS idx_sc_date_breakout
    ON analytics.stock_card (as_of_date DESC, accumulation_rank ASC)
    WHERE pivot_breakout_flag;

CREATE INDEX IF NOT EXISTS idx_sc_sector_date
    ON analytics.stock_card (sector, as_of_date DESC);


-- ═══════════════════════════════════════════════════════════════════
-- D. analytics.sector_snapshot
-- One row per (sector, as_of_date).  Powers the sector heatmap and
-- the sector-rotation signal.
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS analytics.sector_snapshot (
    sector               TEXT    NOT NULL,
    as_of_date           DATE    NOT NULL,

    stock_count          INTEGER NOT NULL DEFAULT 0,
    advancing            INTEGER NOT NULL DEFAULT 0,
    declining            INTEGER NOT NULL DEFAULT 0,

    -- Aggregate returns (equal-weight)
    avg_return_1d        NUMERIC(10,4),
    avg_return_5d        NUMERIC(10,4),
    avg_return_20d       NUMERIC(10,4),
    median_rsi           NUMERIC(7,4),
    avg_accumulation     NUMERIC(7,4),
    breakout_count       INTEGER NOT NULL DEFAULT 0,   -- stocks with pivot_breakout_flag

    -- Delivery signal
    avg_deliv_surge_z    NUMERIC(10,4),

    -- Rank within date (1 = best performing sector)
    return_1d_rank       INTEGER,
    return_20d_rank      INTEGER,

    built_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (sector, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_ss_date_rank
    ON analytics.sector_snapshot (as_of_date DESC, return_20d_rank ASC);


-- ═══════════════════════════════════════════════════════════════════
-- E. analytics.fund_category_rank
-- One row per (scheme_code, rank_date).  Built from mf_nav_daily +
-- mf_scheme_master.  Powers MF category leaderboard and advisor
-- recommendations.
-- ═══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS analytics.fund_category_rank (
    scheme_code          TEXT    NOT NULL,
    rank_date            DATE    NOT NULL,   -- last trading day of the computation window

    -- Identity (denormalised for single-row dashboard reads)
    scheme_name          TEXT,
    category             TEXT,
    sub_category         TEXT,
    amc_code             TEXT,

    -- Returns (annualised %)
    return_1y            NUMERIC(10,4),
    return_3y            NUMERIC(10,4),
    return_5y            NUMERIC(10,4),
    return_ytd           NUMERIC(10,4),

    -- Risk
    volatility_1y        NUMERIC(10,4),     -- annualised std dev of daily returns
    sharpe_1y            NUMERIC(10,4),     -- (return_1y − risk_free) / volatility_1y
    max_drawdown_1y      NUMERIC(10,4),     -- max peak-to-trough %

    -- Expense
    ter                  NUMERIC(6,3),      -- total expense ratio %

    -- Within-category ranks (1 = best)
    return_1y_rank       INTEGER,
    return_3y_rank       INTEGER,
    sharpe_rank          INTEGER,
    ter_rank             INTEGER,           -- 1 = lowest TER
    composite_rank       INTEGER,           -- weighted blend

    built_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (scheme_code, rank_date)
);

CREATE INDEX IF NOT EXISTS idx_fcr_category_date_rank
    ON analytics.fund_category_rank (category, rank_date DESC, composite_rank ASC);

CREATE INDEX IF NOT EXISTS idx_fcr_date_rank
    ON analytics.fund_category_rank (rank_date DESC, composite_rank ASC);


-- ═══════════════════════════════════════════════════════════════════
-- F. MATERIALIZED VIEWS
-- Refreshed by analytics.refresh_all() after each pipeline run.
-- These power instant dashboard responses without any joins.
-- ═══════════════════════════════════════════════════════════════════

-- F1. Top-momentum stocks (Nifty 500, latest date)
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.mv_top_momentum AS
SELECT symbol, as_of_date, company_name, sector,
       close, pct_change, return_20d_pct, rsi14,
       accumulation_score, momentum_rank, nifty500_rank,
       pivot_breakout_flag, vol_ratio
  FROM analytics.stock_card
 WHERE as_of_date = (SELECT max(as_of_date) FROM analytics.stock_card)
   AND in_nifty500
 ORDER BY nifty500_rank ASC NULLS LAST
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_momentum_symbol
    ON analytics.mv_top_momentum (symbol);

CREATE INDEX IF NOT EXISTS idx_mv_momentum_rank
    ON analytics.mv_top_momentum (nifty500_rank ASC NULLS LAST);


-- F2. Delivery-surge leaders (Nifty 500, latest date)
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.mv_delivery_surge AS
SELECT symbol, as_of_date, company_name, sector,
       close, pct_change, deliv_pct, deliv_pct_avg_20, deliv_surge_z,
       delivery_rank, vol_ratio, accumulation_score
  FROM analytics.stock_card
 WHERE as_of_date = (SELECT max(as_of_date) FROM analytics.stock_card)
   AND in_nifty500
   AND deliv_surge_z IS NOT NULL
 ORDER BY delivery_rank ASC NULLS LAST
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_delivery_symbol
    ON analytics.mv_delivery_surge (symbol);


-- F3. Sector heatmap (latest date)
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.mv_sector_heatmap AS
SELECT sector, as_of_date,
       stock_count, advancing, declining,
       avg_return_1d, avg_return_5d, avg_return_20d,
       median_rsi, avg_accumulation, breakout_count,
       return_1d_rank, return_20d_rank
  FROM analytics.sector_snapshot
 WHERE as_of_date = (SELECT max(as_of_date) FROM analytics.sector_snapshot)
 ORDER BY return_20d_rank ASC NULLS LAST
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_sector_sector
    ON analytics.mv_sector_heatmap (sector);


-- F4. MF category leaderboard (latest rank_date, top 10 per category)
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.mv_fund_category_top10 AS
SELECT scheme_code, rank_date, scheme_name, category, sub_category, amc_code,
       return_1y, return_3y, return_5y, sharpe_1y, ter,
       return_1y_rank, sharpe_rank, composite_rank
  FROM analytics.fund_category_rank
 WHERE rank_date = (SELECT max(rank_date) FROM analytics.fund_category_rank)
   AND composite_rank <= 10
 ORDER BY category, composite_rank ASC
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_mv_fund_category
    ON analytics.mv_fund_category_top10 (category, composite_rank);


-- ═══════════════════════════════════════════════════════════════════
-- G. analytics.refresh_all(target_date)
-- Called by the analytics_refresh service after each pipeline run.
-- Populates stock_card, sector_snapshot, fund_category_rank,
-- then REFRESHes all four materialized views concurrently.
-- ═══════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION analytics.refresh_stock_card(p_date DATE)
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    inserted INTEGER;
BEGIN
    -- Delete existing rows for the date (idempotent rebuild)
    DELETE FROM analytics.stock_card WHERE as_of_date = p_date;

    INSERT INTO analytics.stock_card (
        symbol, as_of_date,
        company_name, sector, industry, isin,
        in_nifty50, in_nifty500,
        close, prev_close, pct_change, volume, avg_volume_20,
        vol_ratio, deliv_pct, deliv_pct_avg_20, deliv_surge_z,
        sma20, sma50, dist_52w_high_pct, dist_52w_low_pct,
        rsi14, macd, macd_hist, bb_pos,
        return_5d_pct, return_20d_pct, return_60d_pct,
        accumulation_score, pivot_breakout_flag, accumulation_signals,
        bulk_buy_qty, bulk_sell_qty, block_deal_count,
        has_upcoming_ca, upcoming_ca_types
    )
    SELECT
        sds.symbol,
        p_date,
        sm.company_name,
        COALESCE(sm.sector, sds.industry),
        sds.industry,
        sm.isin,
        sds.in_nifty50,
        sds.in_nifty500,
        sds.close_price,
        sds.prev_close,
        sds.pct_change_1d,
        sds.volume,
        sfd.avg_volume_20,
        CASE WHEN sfd.avg_volume_20 > 0
             THEN ROUND(sds.volume::NUMERIC / sfd.avg_volume_20, 4)
             ELSE NULL END,
        sds.deliv_pct,
        sfd.deliv_pct_avg_20,
        sfd.vol_z20,       -- reuse volume z-score as delivery surge proxy
        sfd.sma20,
        sfd.sma50,
        sfd.dist_52w_high_pct,
        sfd.dist_52w_low_pct,
        sfd.rsi14,
        sfd.macd,
        sfd.macd_hist,
        sfd.bb_pos,
        sfd.return_5d_pct,
        sfd.return_20d_pct,
        sfd.return_60d_pct,
        sfd.accumulation_score,
        sfd.pivot_breakout_flag,
        sfd.accumulation_signals,
        sds.bulk_buy_qty,
        sds.bulk_sell_qty,
        sds.block_deal_count,
        sds.has_upcoming_ca,
        sds.upcoming_ca_types
    FROM nidp.stock_daily_snapshot sds
    LEFT JOIN nidp.stock_features_daily sfd
           ON sfd.symbol = sds.symbol AND sfd.as_of_date = p_date
    LEFT JOIN nidp.sector_master sm
           ON sm.symbol = sds.symbol
    WHERE sds.as_of_date = p_date
      AND sds.series = 'EQ';

    GET DIAGNOSTICS inserted = ROW_COUNT;

    -- Compute rankings within this date
    UPDATE analytics.stock_card sc
       SET momentum_rank     = r.momentum_rank,
           delivery_rank     = r.delivery_rank,
           accumulation_rank = r.accumulation_rank,
           nifty500_rank     = r.nifty500_rank
      FROM (
          SELECT symbol,
                 ROW_NUMBER() OVER (ORDER BY return_20d_pct   DESC NULLS LAST) AS momentum_rank,
                 ROW_NUMBER() OVER (ORDER BY vol_z20          DESC NULLS LAST) AS delivery_rank,
                 ROW_NUMBER() OVER (ORDER BY accumulation_score DESC NULLS LAST) AS accumulation_rank,
                 ROW_NUMBER() OVER (
                     PARTITION BY CASE WHEN in_nifty500 THEN 1 ELSE NULL END
                     ORDER BY return_20d_pct DESC NULLS LAST
                 ) AS nifty500_rank
            FROM analytics.stock_card
           WHERE as_of_date = p_date
      ) r
     WHERE sc.symbol     = r.symbol
       AND sc.as_of_date = p_date;

    RETURN inserted;
END $$;


CREATE OR REPLACE FUNCTION analytics.refresh_sector_snapshot(p_date DATE)
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    inserted INTEGER;
BEGIN
    DELETE FROM analytics.sector_snapshot WHERE as_of_date = p_date;

    INSERT INTO analytics.sector_snapshot (
        sector, as_of_date,
        stock_count, advancing, declining,
        avg_return_1d, avg_return_5d, avg_return_20d,
        median_rsi, avg_accumulation, breakout_count,
        avg_deliv_surge_z,
        return_1d_rank, return_20d_rank
    )
    WITH base AS (
        SELECT sector, as_of_date,
               count(*)                                         AS stock_count,
               count(*) FILTER (WHERE pct_change > 0)          AS advancing,
               count(*) FILTER (WHERE pct_change < 0)          AS declining,
               avg(return_5d_pct)                               AS avg_return_5d,
               avg(return_20d_pct)                              AS avg_return_20d,
               avg(pct_change)                                  AS avg_return_1d,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY rsi14) AS median_rsi,
               avg(accumulation_score)                          AS avg_accumulation,
               count(*) FILTER (WHERE pivot_breakout_flag)      AS breakout_count,
               avg(deliv_surge_z)                               AS avg_deliv_surge_z
          FROM analytics.stock_card
         WHERE as_of_date = p_date
           AND sector IS NOT NULL
         GROUP BY sector, as_of_date
    )
    SELECT sector, as_of_date,
           stock_count, advancing, declining,
           avg_return_1d, avg_return_5d, avg_return_20d,
           median_rsi, avg_accumulation, breakout_count,
           avg_deliv_surge_z,
           ROW_NUMBER() OVER (ORDER BY avg_return_1d  DESC NULLS LAST) AS return_1d_rank,
           ROW_NUMBER() OVER (ORDER BY avg_return_20d DESC NULLS LAST) AS return_20d_rank
      FROM base;

    GET DIAGNOSTICS inserted = ROW_COUNT;
    RETURN inserted;
END $$;


CREATE OR REPLACE FUNCTION analytics.refresh_all(p_date DATE DEFAULT CURRENT_DATE)
RETURNS JSONB
LANGUAGE plpgsql AS $$
DECLARE
    sc_rows  INTEGER;
    ss_rows  INTEGER;
    t_start  TIMESTAMPTZ := clock_timestamp();
BEGIN
    sc_rows := analytics.refresh_stock_card(p_date);
    ss_rows := analytics.refresh_sector_snapshot(p_date);

    -- Materialized views — CONCURRENTLY requires a unique index (added above)
    -- Falls back to non-concurrent if table is empty (first run)
    BEGIN
        REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.mv_top_momentum;
        REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.mv_delivery_surge;
        REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.mv_sector_heatmap;
        REFRESH MATERIALIZED VIEW CONCURRENTLY analytics.mv_fund_category_top10;
    EXCEPTION WHEN others THEN
        -- First run: tables may be empty; fall back to non-concurrent refresh
        REFRESH MATERIALIZED VIEW analytics.mv_top_momentum;
        REFRESH MATERIALIZED VIEW analytics.mv_delivery_surge;
        REFRESH MATERIALIZED VIEW analytics.mv_sector_heatmap;
        REFRESH MATERIALIZED VIEW analytics.mv_fund_category_top10;
    END;

    RETURN jsonb_build_object(
        'date',          p_date,
        'stock_cards',   sc_rows,
        'sectors',       ss_rows,
        'duration_ms',   EXTRACT(MILLISECONDS FROM clock_timestamp() - t_start)::INTEGER
    );
END $$;


-- ═══════════════════════════════════════════════════════════════════
-- H. POSTGRESQL TUNING  (8 GB RAM, SSD, TimescaleDB VM profile)
-- Guarded: only runs if we can confirm we're on the NIDP VM
-- (NIDP_ENV=production or explicitly allowed).
-- ═══════════════════════════════════════════════════════════════════
DO $$
BEGIN
    -- Only apply on production; skip silently in dev/test
    IF current_setting('nidp.env', true) = 'production'
       OR current_setting('nidp.apply_tuning', true) = 'true' THEN

        -- Memory (8 GB VM: 2 GB shared_buffers, 6 GB effective_cache)
        EXECUTE 'ALTER SYSTEM SET shared_buffers           = ''2GB''';
        EXECUTE 'ALTER SYSTEM SET effective_cache_size     = ''6GB''';
        EXECUTE 'ALTER SYSTEM SET work_mem                 = ''64MB''';
        EXECUTE 'ALTER SYSTEM SET maintenance_work_mem     = ''512MB''';

        -- Parallelism (conservative for 8 GB)
        EXECUTE 'ALTER SYSTEM SET max_parallel_workers                 = 4';
        EXECUTE 'ALTER SYSTEM SET max_parallel_workers_per_gather      = 2';
        EXECUTE 'ALTER SYSTEM SET max_parallel_maintenance_workers     = 2';
        EXECUTE 'ALTER SYSTEM SET parallel_tuple_cost                  = 0.1';
        EXECUTE 'ALTER SYSTEM SET parallel_setup_cost                  = 500';

        -- SSD random access (no spinning-disk penalty)
        EXECUTE 'ALTER SYSTEM SET random_page_cost         = 1.1';
        EXECUTE 'ALTER SYSTEM SET effective_io_concurrency = 200';

        -- WAL / checkpoint (reduce I/O spikes during ingestion)
        EXECUTE 'ALTER SYSTEM SET checkpoint_completion_target = 0.9';
        EXECUTE 'ALTER SYSTEM SET wal_buffers                  = ''64MB''';
        EXECUTE 'ALTER SYSTEM SET min_wal_size                 = ''512MB''';
        EXECUTE 'ALTER SYSTEM SET max_wal_size                 = ''2GB''';

        -- Statistics target (better planner decisions on time-series columns)
        EXECUTE 'ALTER SYSTEM SET default_statistics_target  = 200';

        RAISE NOTICE '047: PostgreSQL system parameters updated — reload required (SELECT pg_reload_conf())';
    ELSE
        RAISE NOTICE '047: skipping ALTER SYSTEM (set nidp.apply_tuning=true to enable)';
    END IF;
END $$;


-- ═══════════════════════════════════════════════════════════════════
-- Routing guide comment (no DDL — for documentation only)
-- ═══════════════════════════════════════════════════════════════════
COMMENT ON TABLE analytics.stock_card IS
'Precomputed per-stock dashboard row. Rebuilt nightly by analytics.refresh_all().
Query routing:
  Single stock lookup     → analytics.stock_card             target < 100 ms
  Full screener (500 rows)→ analytics.stock_card             target < 500 ms
  Top-momentum widget     → analytics.mv_top_momentum        target < 50 ms
  Delivery surge widget   → analytics.mv_delivery_surge      target < 50 ms
  Sector heatmap          → analytics.mv_sector_heatmap      target < 50 ms
  MF leaderboard          → analytics.mv_fund_category_top10 target < 50 ms
  Historical time-series  → nidp.stock_features_daily        (hypertable, chunk pruning)
  Raw price drill-down    → nidp.prices_eod                  (hypertable)';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('047_nidp_performance_layer.sql')
ON CONFLICT (filename) DO NOTHING;
