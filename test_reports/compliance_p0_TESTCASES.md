# Compliance P0 — test cases (authored before the call-site changes)

Branch `fix/compliance-p0` from dev 33d266fd. Scope: P0-1 (no SEBI-status claims), P0-2 (consumer PAN /
CAS PDF passwords encrypted at rest + backfill), P0-3 (backend refuses broker password/TOTP sign-in).
Order note: `services/cas_secrets.py` was written minutes before this file; every call site, the
backfill script, the frontend edits and all tests come after it.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | FE marketing | `/`, `/about`, `/contact`, `/product`, `/login`, 3 blog articles render | e2e | no text matches `/SEBI[- ]?(aligned\|compliant)/i`; ARN and "subject to market risk" still shown where they were |
| TC-2 | FE onboarding | onboarding CAS step footer | e2e/static | "SEBI-COMPLIANT" gone, replaced by a factual word |
| TC-3 | FE regression | `homepage.spec.ts` trust strip | e2e | updated assertion passes; no other homepage case regresses |
| TC-4 | 5paisa | `fivepaisa.exchange_code` with `{client_code,password,totp}` | unit | raises RuntimeError naming why; py5paisa SDK never imported/called |
| TC-5 | 5paisa | `/api/broker/native/supported` row | unit | 5paisa `connectable` stays False |
| TC-6 | helper | `pan_fields` / `pdf_password_fields` | unit | ciphertext ≠ plaintext and decrypts back; `pan_last4` only for PAN-shaped values; empty → ValueError |
| TC-7 | helper | `unlock_password` precedence | unit | custom password (encrypted or legacy) beats PAN; first doc wins within a kind; PAN upper-cased; "" when none |
| TC-8 | helper | `legacy_update` | unit | encrypts + unsets each plaintext field; keeps an existing encrypted value; None when nothing to do |
| TC-9 | POST /api/onboarding/pan | save PAN | unit (fake db) | `user_profiles` + `gmail_tokens` get `pan_encrypted`/`pan_last4`; `pan` and `cas_password` absent; decrypts to the PAN |
| TC-10 | POST /api/onboarding/cas-password | save statement password | unit (fake db) | `cas_pdf_password_encrypted` on both; plaintext absent |
| TC-11 | CAS upload with inline secret | PAN-shaped and custom secret | unit (fake db) | stored encrypted; the same request still unlocks with it |
| TC-12 | GET onboarding state | `pan_on_file` | unit | true for encrypted-only and legacy-only rows; false when none |
| TC-13 | daily sweep | `auto_import_all_users` selection + `auto_import_for_user` password | unit (fake db) | selects rows with encrypted or legacy PAN; unlocks with the decrypted value |
| TC-14 | Gmail status | `auto_import_ready` | unit | true with an encrypted PAN mirror |
| TC-15 | failure | no encryption key outside dev | unit | save PAN raises; nothing written in the clear |
| TC-16 | backfill (real Mongo) | `scripts/encrypt_cas_secrets.py` on a throwaway mongo:7 with synthetic rows | data | dry-run writes nothing; `--apply` leaves 0 plaintext fields, every ciphertext decrypts to the original; second run is a no-op |
| TC-17 | backfill (staging) | dry-run against staging Mongo | data | prints counts only (no values) |
| TC-18 | regression | existing suites: test_cas_import_all, test_onboarding_state_sources, broker suites | unit | same results as plain dev |
| TC-19 | post-merge | `--apply` on staging after the backend restart, then a real CAS unlock | data/e2e | 0 plaintext; import unlocks — needs a CAS PDF from the owner (UNVERIFIED until then) |
