-- 123_documents_doc_type_confidence.sql
-- Content-based doc_type classification (doc-type fix pack).
--
-- The document_parser now types each attachment from its OWN first-page content
-- at parse time (concall_transcript / investor_presentation / annual_report /
-- financial_results / press_release), instead of trusting BSE's self-reported
-- subcategory (companies tag inconsistently, and the subcategory sweep is not
-- scheduled). doc_type is already TEXT (031), so the new type VALUES need no
-- schema change — this migration only adds the classifier's confidence score.
--
-- Storing the score enables the cheap ongoing quality loop: eyeball the
-- below-threshold / borderline docs weekly to catch new document formats before
-- they silently mistype the RAG corpus. Additive + idempotent.

SET search_path TO nidp, public;

ALTER TABLE nidp.documents
    ADD COLUMN IF NOT EXISTS doc_type_confidence SMALLINT;

COMMENT ON COLUMN nidp.documents.doc_type_confidence IS
    'Content-classifier score behind doc_type (doctype.classify). NULL = typed before the classifier or at discover-time from subcategory; 0 = content gave no signal (doc_type came from subcategory/floor). Lower = weaker; review borderline cases.';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('123_documents_doc_type_confidence.sql')
ON CONFLICT DO NOTHING;
