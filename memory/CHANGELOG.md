# CHANGELOG

## 2026-04-28 — Claude Vision CAS Parser (alternative SDK)

### What's new
- **`services/claude_cas_parser.py`** — sends each PDF page as a base64 PNG to
  Anthropic Claude Sonnet 4.5 (via Emergent LLM key) and returns a single
  structured JSON describing the entire NSDL CAS (statement_info, investor_info,
  portfolio_summary, accounts, holdings, transactions). Auto-batches at 6 pages
  per request and merges sub-responses. Caps at 24 pages for cost control.
- **`services/claude_cas_mapper.py`** — converts Claude's JSON into the
  internal `holdings[]` list AND the normalized `{mutual_funds: [{schemes:
  [{transactions: [...]}]}]}` shape that `cas_transactions.extract_transactions`
  consumes. Equities, preference shares, SGBs, demat MFs, MF folios all
  supported.
- **Admin toggle**:
  - `GET /api/admin/cas-parser-provider`
  - `PUT /api/admin/cas-parser-provider {"provider": "claude_vision"|"casparser_api"}`
  - Stored in `db.system_config` keyed `cas_parser_provider`.
- **`helpers/parsing.parse_cas_pdf_with_data()`** + `parse_cas_pdf()` now read
  the active provider on every call and route to Claude Vision FIRST when
  selected. Falls back to casparser.in API → casparser library → OCR/AI on
  failure.
- **Frontend Admin UI**: `CasConfigSection.jsx` shows two side-by-side cards
  ("casparser.in" vs "Claude Vision") with one-click switching, configured-flag
  status, and the active model name.
- **`ClaudeCasUploadButton.jsx`** — drop-in alternative to `<CasConnectButton/>`.
  Same prop API (`onSuccess`, `label`, `testId`). Opens a modal with PDF
  picker + password field, posts to `/api/portfolio/upload-raw`, polls the
  task status, calls `onSuccess` when done.
- **`MfdOnboardingWizard.jsx`** — Step 3 now auto-detects the active provider
  and renders either CAS Connect or Claude Vision widget. No code change
  needed by the MFD when admin toggles the provider.

### Validation
- Tested end-to-end on a real 412KB Amit Porwal CAS PDF (4 pages):
  Claude Vision extracted 19 holdings (4 equities + 1 SGB + 14 demat MFs)
  with correct ISINs, units, NAVs, and asset_type classification.
- Admin toggle endpoint roundtrip verified (GET → PUT claude_vision → GET
  → PUT casparser_api → GET; invalid value returns 400).

### Cost note
Each CAS parse via Claude ≈ $0.05–$0.08 depending on page count. Result is
cached in `db.cas_parsed_responses` so re-views don't re-bill.

---

## 2026-04-27 — Real CAS Transactions (pivot from unit-delta)

- Removed unit-delta SIP estimation in `cas_snapshot_engine.py`.
- New `cas_parsed_responses` collection caches the full parsed CAS JSON
  per `file_id` so the UI can show "View Parsed Statement" without
  re-parsing the PDF.
- New endpoints:
  - `GET /api/mfd/cas-uploads/{file_id}/parsed-response`
  - `GET /api/mfd/cas-snapshots/{snapshot_date}/parsed-response`
  - `POST /api/portfolio/cas-transactions/backfill` (idempotent)
- `CasTimeMachine.jsx` shows "View parsed" button on each snapshot
  tile and a "Import from snapshots" backfill nudge when no transactions.
- Skip button on Step 3 of the MFD onboarding wizard (`skip-cas-import-btn`).
