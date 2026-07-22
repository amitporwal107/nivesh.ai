-- 118_ann_subcategory.sql — BSE subcategory (SUBCATNAME) on corporate announcements.
--
-- Source:   BSE AnnSubCategoryGetData/w feed (subcategory taxonomy sweep — adopted
--           from the BSE Announcements API suite). The subcategory is the finer
--           Phase-1 filing type ("Award of Order / Receipt of Order",
--           "Earnings Call Transcript", "Presentation", ...) beneath the
--           coarse raw_category (CATEGORYNAME).
-- Why:      Drives (a) doc_type tagging of attachments (transcripts/presentations
--           become first-class corpus docs, not generic announcement_attachment)
--           and (b) precise order-win / M&A detection. NSE rows leave it NULL.
--
-- Additive + idempotent — a nullable column, safe on the live feed.

SET search_path TO nidp, public;

ALTER TABLE nidp.corporate_announcements
    ADD COLUMN IF NOT EXISTS subcategory TEXT;          -- BSE SUBCATNAME (NULL for NSE / older rows)

-- Filter/browse by subcategory (e.g. all "Earnings Call Transcript" filings).
CREATE INDEX IF NOT EXISTS idx_corp_ann_subcategory
    ON nidp.corporate_announcements (subcategory)
    WHERE subcategory IS NOT NULL;

-- Recreate the discoverer view so its `a.*` re-expands to include the new
-- `subcategory` column (Postgres freezes *-expansion at view-creation time, so
-- the ADD COLUMN above is invisible to the view until it is replaced). The
-- document_parser reads subcategory from this view to pick each attachment's
-- doc_type (concall_transcript / investor_presentation / announcement_attachment).
CREATE OR REPLACE VIEW nidp.v_announcements_needing_documents AS
SELECT a.*
  FROM nidp.corporate_announcements a
  LEFT JOIN nidp.documents d
         ON d.announcement_id = a.announcement_id
        AND d.announcement_source = a.source
 WHERE a.attachment_url IS NOT NULL
   AND d.doc_id IS NULL
   AND a.filed_at >= NOW() - INTERVAL '30 days';
