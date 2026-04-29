# CHANGELOG

## 2026-04-29 — NIVESH_CAS_PARSER (Google Document AI as 3rd parser provider)

### What's new
- **`services/nivesh_cas_parser.py`** — orchestrates: PyPDF2 decrypt → split into
  ≤12-page chunks → parallel Document AI calls (3 workers) → merge `{text, tables}`
  → run normalizer. Loads service-account credentials from `db.system_config`
  secrets (env-scoped) so a temp credentials file is never written to disk.
- **`services/nivesh_cas_normalizer.py`** — heuristic table classifier + row
  parsers that turn raw Document AI output into the same Claude/CAS-Connect
  schema (statement_info, investor_info, portfolio_summary, accounts, holdings,
  transactions). Validated on a real 18-page NSDL CAS:
  - 100% match on equities, preference shares, SGBs, MFs in demat
  - 95.3% match on MF folios (Document AI cell-merge artifacts)
  - **97.1% overall portfolio value match** (₹1.20Cr / ₹1.23Cr)
  - 110 holdings mapped, 32 SIP transactions, 2 folio buckets
- **3-way Admin toggle** — `cas_parser_provider` now accepts `casparser_api`,
  `claude_vision`, or `nivesh_cas_parser`. The dispatcher in `helpers/parsing.py`
  tries the active provider first and falls back to casparser_api on failure.
- **4 new known secrets** (category=parsing): `GOOGLE_DOCAI_CREDENTIALS_JSON`,
  `GOOGLE_DOCAI_PROJECT`, `GOOGLE_DOCAI_PROCESSOR`, `GOOGLE_DOCAI_LOCATION`.
- **Frontend**: `CasConfigSection.jsx` — third button "Nivesh Parser" with
  `data-testid="cas-provider-nivesh"`, configured-flag, and a tailored toast.
- **Dependencies**: `google-cloud-documentai==3.14.0`, `PyPDF2==3.0.1`.
- **Tested**: 11/11 backend pytest pass (testing agent iteration_54). End-to-end
  validated on the user's encrypted sample PDF (decrypts → 2 chunks → 110
  holdings via mapper).

### How to switch on
1. Admin → CAS Configuration → paste `key.json` content into
   `GOOGLE_DOCAI_CREDENTIALS_JSON` and set the other three GCP fields.
2. Click the **Nivesh Parser** card in the provider toggle.
3. Subsequent CAS PDF uploads route through Document AI automatically.

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
