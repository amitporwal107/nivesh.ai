# CHANGELOG

## 2026-04-29 — Provider-agnostic CAS upload + per-user reset admin tool

### What changed (UX)
- **One button, one modal everywhere.** Replaced 5 different upload widgets
  (`CasConnectButton`, `ClaudeCasUploadButton`, plus three provider-branched
  renders) with a single generic `<CasUploadButton/>`. Label: "Import CAS PDF"
  on dashboards, "Upload CAS PDF" on Client 360 / wizard. No mention of
  "Nivesh", "Claude", "CAS Connect" anywhere in user-facing UI.
- Default CAS parser provider is now **`nivesh_cas_parser`** (Google
  Document AI). New deployments and missing-config reads default here.

### What changed (server)
- `helpers/parsing.parse_cas_pdf*` — true **auto-fallback chain**: tries the
  admin-selected primary, then the others in order. The chain is
  `[active_provider, nivesh, claude, casparser]` (deduped). First non-empty
  result wins. Casparser.in still respects sandbox-mode admin toggle.
- `BudgetExceededError` (Claude budget hit) is captured and only re-raised
  if NO downstream provider succeeds — so a Claude budget cap no longer
  blocks the full flow.

### New: per-user admin reset
- `POST /api/admin/users/{user_id}/reset-portfolio` — wipes 21
  user-scoped collections (holdings, portfolios, snapshots, action_plans,
  pending_actions, ai_insights, cas_parsed_responses, cas_transactions,
  detected_sips, saved_scenarios, scenario_simulations, upload_tasks,
  chat_sessions, chat_messages, copilot_cache, allocation_analysis_cache,
  fund_performance_cache, mfd_profile_signal_cache, gmail_imports,
  portfolio_analysis, portfolio_analysis_deep), clears Redis caches
  (snap:*, score:user:*, v3:user:*, actionplan:*, copilot:*), resets
  onboarding flags on `user_profiles`, and unsets `cas_view_state` on the
  user. Audit-logged.
- `UserManagementSection.jsx` — searchable user table with per-row reset,
  toggle-admin, and force-logout actions. Reset is gated by an
  email-confirmation modal that lists exactly what will be wiped.
- Bugfix: `admin_users_router` was imported but never `include_router`'d
  — now properly mounted.

### Files
- New: `services/nivesh_cas_parser.py`, `services/nivesh_cas_normalizer.py`,
  `frontend/components/CasUploadButton.jsx`, `frontend/components/admin/UserManagementSection.jsx`.
- Refactored: `helpers/parsing.py`, 5 upload-callsite components.
- Retired (no longer imported anywhere): `CasConnectButton.js`,
  `ClaudeCasUploadButton.jsx` (kept on disk for now to avoid breaking
  any hot-reload state).

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
