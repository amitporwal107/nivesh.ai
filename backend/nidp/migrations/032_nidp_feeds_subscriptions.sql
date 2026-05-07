-- 032_nidp_feeds_subscriptions.sql — Generic feed-subscription RAG layer.
--
-- Two tables + seed:
--   nidp.feeds                    — catalog of retrievable content feeds
--   nidp.user_feed_subscriptions  — N-to-N user → feed with per-user filter params
--
-- The copilot's content-RAG layer (backend/services/feed_rag/) reads
-- nidp.user_feed_subscriptions to know which retrievers to fan out to
-- on a given user query. Each retriever is identified by feed_id +
-- retrieval_kind (text | vector | structured). Subscription params are
-- merged into the retriever's WHERE clause as filters (e.g. tickers,
-- date range, impact_score floor).
--
-- This decouples *what content exists* (feeds catalog, ops-managed)
-- from *what content the user sees* (subscriptions, user-managed).
-- Adding a new feed = INSERT into nidp.feeds + new retriever class —
-- no copilot wiring change.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.feeds (
    feed_id           TEXT PRIMARY KEY,                 -- e.g. 'corporate_announcements'
    name              TEXT NOT NULL,                    -- 'Corporate Announcements (NSE+BSE)'
    description       TEXT,
    retrieval_kind    TEXT NOT NULL,                    -- 'text' | 'vector' | 'structured'
    source_table      TEXT,                             -- e.g. 'nidp.corporate_announcements'
    default_top_k     INTEGER NOT NULL DEFAULT 10,
    -- Tier gating: 'free' available to everyone; 'pro'/'institutional' require entitlement.
    tier              TEXT NOT NULL DEFAULT 'free',     -- 'free' | 'pro' | 'institutional'
    -- JSON schema fragment describing valid filter params on subscriptions.
    -- Example for corporate_announcements:
    --   {"tickers": {"type":"array","items":{"type":"string"}},
    --    "min_impact": {"enum":["low","medium","high"]}}
    params_schema     JSONB,
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (retrieval_kind IN ('text','vector','structured')),
    CHECK (tier IN ('free','pro','institutional'))
);

CREATE TABLE IF NOT EXISTS nidp.user_feed_subscriptions (
    user_id           TEXT NOT NULL,
    feed_id           TEXT NOT NULL REFERENCES nidp.feeds(feed_id) ON DELETE CASCADE,
    -- User-scoped filters merged into every retriever invocation. The
    -- retriever validates params against feeds.params_schema at insert time.
    params            JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Soft-pause: keep subscription metadata but stop including it in
    -- queries until paused_at IS NULL again.
    paused_at         TIMESTAMPTZ,
    subscribed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, feed_id)
);

CREATE INDEX IF NOT EXISTS idx_user_subs_user
    ON nidp.user_feed_subscriptions(user_id)
    WHERE paused_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_user_subs_feed
    ON nidp.user_feed_subscriptions(feed_id);


-- ── Seed: feeds available at launch ──────────────────────────────────
-- Idempotent — re-running the migration leaves user data alone but
-- refreshes the catalog metadata (name/description/tier).

INSERT INTO nidp.feeds (feed_id, name, description, retrieval_kind, source_table, tier, params_schema)
VALUES
  ('corporate_announcements',
   'Corporate Announcements (NSE+BSE)',
   'Real-time NSE + BSE corporate filings: orders, M&A, earnings, capex, regulatory. Classified by event category, impact, and sentiment.',
   'text',
   'nidp.corporate_announcements',
   'free',
   '{"tickers":{"type":"array","items":{"type":"string"}},"min_impact":{"enum":["low","medium","high"]},"event_category":{"type":"string"}}'::jsonb),

  ('filing_documents',
   'Filing Documents (annual reports, concall transcripts)',
   'Semantic search across PDF filings — annual reports, concall transcripts, investor presentations. Embedding-backed; hybrid keyword fallback while corpus warms up.',
   'vector',
   'nidp.document_chunks',
   'free',
   '{"tickers":{"type":"array","items":{"type":"string"}},"doc_types":{"type":"array","items":{"type":"string"}}}'::jsonb),

  ('financial_results',
   'Quarterly Financials',
   'Structured P&L / balance-sheet / cash-flow line items from NSE XBRL filings. Query by ticker + period.',
   'structured',
   'nidp.nse_financial_results',
   'free',
   '{"tickers":{"type":"array","items":{"type":"string"}},"periods":{"type":"array","items":{"type":"string"}}}'::jsonb),

  ('shareholding_pattern',
   'Shareholding Pattern',
   'Quarterly promoter / FII / DII / public shareholding splits per ticker, plus pledge ratios.',
   'structured',
   'nidp.nse_shareholding_pattern',
   'free',
   '{"tickers":{"type":"array","items":{"type":"string"}}}'::jsonb),

  ('bulk_block_deals',
   'Bulk + Block Deals',
   'Daily large-trade disclosures (bulk + block) with counterparty when available.',
   'structured',
   'nidp.bulk_deals',
   'free',
   '{"tickers":{"type":"array","items":{"type":"string"}},"min_value_inr":{"type":"number"}}'::jsonb)
ON CONFLICT (feed_id) DO UPDATE SET
    name           = EXCLUDED.name,
    description    = EXCLUDED.description,
    retrieval_kind = EXCLUDED.retrieval_kind,
    source_table   = EXCLUDED.source_table,
    tier           = EXCLUDED.tier,
    params_schema  = EXCLUDED.params_schema,
    updated_at     = NOW();


-- ── v_active_subscriptions ──────────────────────────────────────────
-- Drives the orchestrator's per-query fan-out. Joins subs to feeds so
-- a feed disabled at the catalog level (feeds.enabled=FALSE) is also
-- excluded — central kill switch without touching user rows.
CREATE OR REPLACE VIEW nidp.v_active_subscriptions AS
SELECT
    s.user_id,
    s.feed_id,
    f.name           AS feed_name,
    f.retrieval_kind,
    f.source_table,
    f.default_top_k,
    f.tier,
    s.params,
    s.subscribed_at
  FROM nidp.user_feed_subscriptions s
  JOIN nidp.feeds f USING (feed_id)
 WHERE s.paused_at IS NULL
   AND f.enabled = TRUE;

INSERT INTO nidp.schema_migrations(filename) VALUES ('032_nidp_feeds_subscriptions.sql')
ON CONFLICT DO NOTHING;
