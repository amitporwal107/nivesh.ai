# Functionality Verification Report — Compliance P0 (no SEBI-status claims, encrypted CAS secrets, no broker credentials)

- **Branch:** fix/compliance-p0 (from dev 33d266fd)
- **Date:** 2026-11-02
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER; DOMAIN_EXPERT_ANALYST for wording)
- **Environment:** unit + real MongoDB 7 (throwaway) + staging Mongo (read-only dry runs) + Playwright (local build)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
P0-1: removed every "SEBI-aligned" / "SEBI-COMPLIANT" claim from shipped pages (12 files: Homepage, Login,
About, Contact, Product, Security, Onboarding, marketing footer, 3 blog articles); Nivesh holds no SEBI
registration. ARN and risk-warning text kept. P0-2: the consumer PAN and the CAS statement password are now
stored AES-256-GCM encrypted (`services/cas_secrets.py`) on `user_profiles` and `gmail_tokens`; every write
removes the plaintext fields; reads fall back to plaintext until `scripts/encrypt_cas_secrets.py` has run.
P0-3: the 5paisa adapter refuses the password/TOTP sign-in it used to accept (it was unreachable from the UI).
Test cases: `test_reports/compliance_p0_TESTCASES.md` (written after `cas_secrets.py`, before every call site).
P0-4 (prod SSH key-only) was an ops change, verified separately in the session; not part of this branch.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | FE | 9 public pages render without a SEBI-status claim, keep ARN / risk text | e2e | no match | PASS |
| TC-2 | FE | onboarding footer "SEBI-COMPLIANT" → "READ-ONLY" | static grep | 0 claims left in src | PASS |
| TC-3 | FE | homepage trust badges (updated assertion) | e2e | pass | PASS |
| TC-4 | 5paisa | exchange_code with password/TOTP | unit | refuses, SDK untouched | PASS |
| TC-5 | 5paisa | not connectable even when configured | unit | connectable False | PASS |
| TC-6 | helper | encryption fields | unit | ciphertext, decrypts back | PASS |
| TC-7 | helper | unlock precedence | unit | custom > PAN, first row wins | PASS |
| TC-8 | helper | backfill update | unit | encrypt + unset, keep existing | PASS |
| TC-9 | POST /api/onboarding/pan | save PAN | unit | ciphertext only, both collections | PASS |
| TC-10 | POST /api/onboarding/cas-password | save statement password | unit | ciphertext only | PASS |
| TC-11 | POST /api/onboarding/upload-cas | inline PAN / custom secret | unit | stored encrypted, still unlocks | PASS |
| TC-12 | onboarding state | pan_on_file | unit + staging data | encrypted and legacy both true | PASS |
| TC-13 | daily sweep | selection before/after backfill | real Mongo + staging data | same users | PASS |
| TC-14 | Gmail status | auto_import_ready | unit | encrypted mirror counts | PASS |
| TC-15 | failure | no key outside dev | unit | raises, nothing stored | PASS |
| TC-16 | backfill | dry run / apply / idempotent | real Mongo | 0 plaintext, decrypts | PASS |
| TC-17 | backfill | staging dry run | staging data | counts only | PASS |
| TC-18 | regression | 11 existing suites | unit | same as dev | PASS |
| TC-19 | post-merge | `--apply` on staging + a real CAS unlock | data/e2e | 0 plaintext; import unlocks | POST-MERGE — not part of this verdict (needs deploy + a CAS PDF) |

## API / Endpoint Tests
Branch code cannot be called through staging's HTTP API before merge (staging runs dev). The changed routes
were exercised as functions with a fake DB (pytest), and the changed queries were run on staging's REAL
Mongo through a read-only overlay (branch modules copied to the container's /tmp, removed after).

- **pytest (new):** `python -m pytest tests/test_compliance_p0.py -q` in `nivesh/backend:staging`
  - Output: `11 passed, 2 warnings in 8.40s`
  - Result: PASS
- **Mutation checks** (code broken on purpose in a scratch copy, new suite re-run):
  - save_pan also writes plaintext → `FAILED test_tc9_save_pan_stores_ciphertext_only` · `1 failed, 10 passed`
  - 5paisa accepts again → `FAILED test_tc4_fivepaisa_refuses_password_and_totp` · `1 failed, 10 passed`
  - unlock ignores custom password → `FAILED test_tc7…`, `FAILED test_tc11…[Custom-Pw-1…]` · `2 failed, 9 passed`
  - Result: PASS (each guard catches its regression)
- **Regression (TC-18):** test_cas_import_all, test_onboarding_state_sources, test_broker_native_routes,
  test_broker_sessions, test_broker_fenix_reader, test_statement_exports, test_order_path_guard,
  test_chat_compliance_delivery, test_gmail_autofetch, test_gmail_cas_flatten, test_llm_pii_guard
  - branch: `18 failed, 591 passed, 1 skipped` · plain dev 33d266fd: `18 failed, 591 passed, 1 skipped`
  - `diff` of the FAILED lists: `IDENTICAL failure sets` — all 18 in `tests/test_gmail_autofetch.py` (needs a live server; `--network none`)
  - Result: PASS

## UI / Playwright Tests
- **tsc:** `npx tsc --noEmit -p tsconfig.json` → `tsc exit=0` — PASS
- **Spec:** `e2e/tests/unauth-no-sebi-claims.spec.ts` (new, 9 pages) + `e2e/tests/homepage.spec.ts` (updated)
  - Command: `npx playwright test --project=unauthenticated e2e/tests/unauth-no-sebi-claims.spec.ts e2e/tests/homepage.spec.ts`
  - Output (branch): `3 failed · 17 passed (53.0s)`; failed: homepage.spec `renders nav bar with brand and CTA`,
    `'Check my portfolio free' CTA navigates to /login`, `'Watch the 90-second tour' does NOT navigate`
    (strict-mode: two buttons with the same name)
  - Baseline (plain dev, homepage.spec only): `3 failed · 8 passed (35.1s)` — the SAME three tests
  - All 9 new cases and the updated trust-badge case passed. Result: PASS (no new failure)

## Data Correctness
- **Real MongoDB 7 (throwaway container), `python tests/compliance_p0_mongo_check.py`:**
  ```
  PASS TC-13 sweep selects legacy-PAN and encrypted-PAN rows, skips disabled / no-PAN (before backfill)
  PASS TC-16 dry run finds 4 profile rows and 3 token rows with plaintext
  PASS TC-16 dry run writes nothing
  PASS TC-16 apply updates 4 + 3 rows and leaves 0 plaintext rows
  PASS TC-16 a direct Mongo count finds 0 plaintext fields in both collections
  PASS TC-16 no synthetic secret appears in clear text anywhere
  PASS TC-16 ciphertexts decrypt to the originals
  PASS TC-16 an existing encrypted value is kept over a stale plaintext copy
  PASS TC-16 unlock passwords after backfill: custom beats PAN, PAN otherwise
  PASS TC-13 sweep selection unchanged after backfill
  PASS TC-16 second apply is a no-op
  11/11 checks passed
  ```
- **Staging Mongo, read-only (TC-17, TC-12, TC-13):** `APP_ENV=staging`, `PII_ENCRYPTION_KEY: set in env`
  ```
  STAGING DRY RUN (nothing written):
    user_profiles: plaintext rows=1 left=1 updated=0
    gmail_tokens: plaintext rows=1 left=1 updated=0
  STAGING sweep selection: old filter=1 users, new filter=1 users, identical=True
  STAGING unlock password resolved for 1/1 swept users (values not printed)
  STAGING pan_on_file (new has_pan) true for 1/1 profiles holding a legacy PAN
  ```
- Result: PASS

## Not verified (and why)
- **Prod:** whether `PII_ENCRYPTION_KEY` resolves in the prod backend, and the prod plaintext row count. The read
  was refused by the session's permission classifier ("Production Reads"). If prod has no key, saving a PAN
  fails closed (500) after this deploys — confirm before merging to main.
- **TC-19** after merge: restart staging backend, run `python -m scripts.encrypt_cas_secrets --apply`, re-count,
  then one real CAS unlock (needs a CAS PDF from the owner).
- Advisor-side PAN (`users` / `profiles` `pan` + `pan_norm`) is NOT in this change (P1-4).

## Inputs required from user
- none for this verdict; a CAS PDF for TC-19 after merge.

## Verdict: PASS
