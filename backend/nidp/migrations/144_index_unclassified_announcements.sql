-- 144_index_unclassified_announcements.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- The announcement classifier reads the OLDEST unclassified rows:
--     WHERE event_category IS NULL [AND filed_at >= ...] ORDER BY filed_at ASC LIMIT n
-- Until now a fixed 30-day window kept that scan small while permanently stranding 42,359
-- older rows. With the window configurable (0 = any age) the same query has to sort the whole
-- unclassified backlog, so give it a partial index: it covers only rows still unclassified,
-- which is a small slice of corporate_announcements, and shrinks as the backlog drains.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_corp_ann_unclassified_filed_at
    ON nidp.corporate_announcements (filed_at)
 WHERE event_category IS NULL;

COMMENT ON INDEX nidp.idx_corp_ann_unclassified_filed_at IS
'Serves announcement_classifier''s oldest-first backlog scan (event_category IS NULL).';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('144_index_unclassified_announcements.sql')
ON CONFLICT (filename) DO NOTHING;
