-- Functional index backing the NSE/BSE identity bridge in daas_api documents.search.
-- A company's NSE filings carry ticker_symbol; its BSE filings carry only
-- scrip_code (ticker_symbol/isin NULL), and no populated key links them
-- (ref.security_master.bse_code is empty). documents.search therefore bridges the
-- two on a NORMALIZED company name. This index makes that resolution an indexed
-- lookup — MUST match routers/documents.py::_norm() byte-for-byte, since Postgres
-- matches functional indexes by expression equality.
--
-- The ANALYZE is REQUIRED, not optional: CREATE INDEX does not gather statistics
-- on the index expression, so without it the planner mis-estimates selectivity and
-- ignores the index — measured on staging 2026-07-20 as a 7s seq-scan of 94,942
-- scrip rows; after ANALYZE the same query is an index scan at 0.35ms.
SET search_path TO nidp, public;

CREATE INDEX IF NOT EXISTS idx_documents_norm_company
  ON nidp.documents (
    btrim(regexp_replace(regexp_replace(regexp_replace(
      lower(company_name),'[^a-z0-9]+',' ','g'),'\s+',' ','g'),
      '(\s+(limited|ltd|pvt|private|the|company))+\s*$','','g'))
  );

ANALYZE nidp.documents;
