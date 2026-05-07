-- 030_nidp_corporate_announcements.sql — NSE/BSE corporate announcement feed.
--
-- Source:   NSE corporate-announcements API (BSE + RBI/SEBI/PIB to follow)
-- Cadence:  Poll every 10 min during market hours; idempotent upsert by PK
-- Output:   nidp.corporate_announcements
--
-- One row per announcement. Classification fields (event_category, impact_score,
-- sentiment) are NULLable and populated asynchronously by the classifier service
-- (Week 2 — Haiku-based). The crawler ships the raw record; the classifier
-- enriches it. This decoupling means a classifier outage doesn't lose feeds.
--
-- Rationale: this is the foundation for event-aware copilot, advisor outreach
-- triggers, and the alert layer in S4. Also the discovery feed for S5 document
-- intelligence ingestion — most concall transcripts and earnings PDFs come as
-- attachments to announcements.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.corporate_announcements (
    -- Identity (synthetic — NSE/BSE IDs aren't stable across re-fetches)
    announcement_id     TEXT NOT NULL,                  -- sha1(source|symbol|filed_at|subject)
    source              TEXT NOT NULL,                  -- 'NSE_ANN' | 'BSE_ANN' | 'RBI' | 'SEBI' | 'PIB'

    -- Entity
    ticker_symbol       TEXT,                           -- NSE symbol when available
    isin                TEXT,
    scrip_code          TEXT,                           -- BSE code when source='BSE_ANN'
    company_name        TEXT,

    -- Filing
    filed_at            TIMESTAMPTZ NOT NULL,           -- exchange dissemination time
    broadcast_at        TIMESTAMPTZ,                    -- NSE an_dt (filing time, may differ from dissem)
    subject             TEXT,                           -- one-line title
    description         TEXT,                           -- body text where available (often empty for NSE)
    raw_category        TEXT,                           -- exchange's own category string (free text)
    attachment_url      TEXT,                           -- PDF if any — fed to S5 document ingestion

    -- Classification (filled async by classifier service — NULL until then)
    event_category      TEXT,                           -- 'orders'|'mna'|'earnings'|'capex'|'regulatory'|'management'|'dividend'|'buyback'|'qip'|'rating'|'other'
    impact_score        TEXT,                           -- 'high'|'medium'|'low'
    sentiment           TEXT,                           -- 'positive'|'neutral'|'negative'
    classifier_version  TEXT,                           -- model+prompt hash for reproducibility
    classified_at       TIMESTAMPTZ,

    -- Provenance
    source_run_id       UUID NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload         JSONB,                          -- full upstream record for replay/debug

    PRIMARY KEY (announcement_id, source)
);

CREATE INDEX IF NOT EXISTS idx_ann_filed_at
    ON nidp.corporate_announcements(filed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ann_ticker_filed
    ON nidp.corporate_announcements(ticker_symbol, filed_at DESC)
    WHERE ticker_symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ann_unclassified
    ON nidp.corporate_announcements(filed_at DESC)
    WHERE event_category IS NULL;
CREATE INDEX IF NOT EXISTS idx_ann_high_impact
    ON nidp.corporate_announcements(filed_at DESC)
    WHERE impact_score = 'high';
CREATE INDEX IF NOT EXISTS idx_ann_attachments
    ON nidp.corporate_announcements(filed_at DESC)
    WHERE attachment_url IS NOT NULL;

-- ── v_announcements_recent ──────────────────────────────────────────
-- Last 7 days of announcements joined to the equity master so consumers
-- get a canonical ticker/sector even when the feed reports only ISIN.
CREATE OR REPLACE VIEW nidp.v_announcements_recent AS
SELECT
    a.announcement_id,
    a.source,
    COALESCE(a.ticker_symbol, em.ticker_symbol) AS ticker_symbol,
    a.isin,
    a.company_name,
    a.filed_at,
    a.subject,
    a.raw_category,
    a.event_category,
    a.impact_score,
    a.sentiment,
    a.attachment_url
FROM nidp.corporate_announcements a
LEFT JOIN nidp.nse_equity_master em
       ON em.isin = a.isin
WHERE a.filed_at >= NOW() - INTERVAL '7 days'
ORDER BY a.filed_at DESC;

-- ── v_announcements_high_impact_today ───────────────────────────────
-- Drives the alert/copilot proactive trigger surface.
CREATE OR REPLACE VIEW nidp.v_announcements_high_impact_today AS
SELECT *
  FROM nidp.corporate_announcements
 WHERE impact_score = 'high'
   AND filed_at >= CURRENT_DATE
 ORDER BY filed_at DESC;

INSERT INTO nidp.schema_migrations(filename) VALUES ('030_nidp_corporate_announcements.sql')
ON CONFLICT DO NOTHING;
