# VERIFICATION_PROTOCOL.md — verify-before-complete (ENFORCED)

This protocol turns the QA staging checklist (`.claude/roles/QA_ENGINEER.md`) into a
**hard, unskippable gate**. It is enforced by hooks (see "Enforcement" below), not by
memory. It exists so that "functionality complete" always means *tested on staging with
real output*, never "I wrote the code."

Applies to every session that edits **product functionality**:
- **Backend** — files under `backend/routes/`, `backend/services/`, or `.../routers/`.
- **Frontend** — files under `frontend-v5/src/` or `frontend/src/`.

Not gated: docs, `*.md`, migrations/seeds/`*.sql`, config (`*.json/*.yml/*.yaml/lock`),
tests/e2e/mocks, images, and `.claude/`.

---

## The lifecycle (do these in order — no skipping)

### 1. Design → then TEST CASES UP FRONT (before implementation)
After the API contract and UI are designed and **before** you write implementation code,
author the test cases for the functionality. List them in the report's **Test Cases**
table: unit · integration · **api** (endpoint) · **e2e** (Playwright) · edge
(empty/max/wrong-type/unauthorized) · failure (network/DB down/partial feed).
Reuse existing tests where they already cover a case; create the ones that don't exist yet.
- Backend tests live in `backend/tests/` (`pytest`).
- Frontend E2E lives in `frontend-v5/e2e/` and `frontend/tests/e2e/` (`@playwright/test`).

### 2. Implement
Build the smallest change that satisfies the spec and makes the test cases pass.

### 3. Verify on STAGING (real output, app AND data)
- **Backend edited → API endpoint tests are REQUIRED.** Hit each new/modified endpoint on
  staging and paste the real, unedited command + output. This repo reaches staging over SSH;
  see the allowed patterns in `.claude/settings.local.json` and the curls in
  `docs/BUILD_AND_DEPLOYMENT.md` (`staging.niveshcopilot.com` /
  `data.staging.niveshcopilot.com`). Also run the relevant `pytest`.
- **Frontend edited → Playwright is REQUIRED.** Run `npx playwright test <spec>` (from
  `frontend-v5/`) against the changed screens and paste the real runner output. `agent-browser`
  may be used for exploratory checks, but the recorded proof is the Playwright run.
- **Data test, not just app test.** Query the real tables the feature reads/writes
  (`nidp.v_feed_status`, `nidp.validation_findings`, `nidp.job_log`, `v3_scored_at`, …) and
  confirm the data is real, fresh, and in-band. "200 OK" is not "the data is right."

### 4. Need something from the user? ASK — do not fake it.
If a test needs a **session token**, a **CAS document**, credentials, or any other input
you don't have, STOP and ask the user for it explicitly (`NEEDS-INPUT: …`). If you cannot
get it (or staging is down), you are blocked — take the OVERRIDE path (below), don't fake a
result and don't silently narrow the scope.

### 5. Write the report → THEN it's complete
Copy `test_reports/_TEMPLATE_functionality.md` to
`test_reports/<slug>_<YYYYMMDD_HHMM>.md`, fill every required section with the **real**
output, and set the final line to exactly `## Verdict: PASS` (only when every test case
passed). The gate opens on that report; only now may you say the functionality is COMPLETE.

---

## The gate (what the hooks enforce)

- `mark-functionality.sh` (PostToolUse) arms a per-session marker when you edit gated
  backend/frontend code.
- `require-functionality-verification.sh` (Stop) **blocks the turn from ending** while a
  marker is armed and there is no *fresh* passing report (nor a fresh override). "Fresh" =
  the report file is newer than your last gated edit — edit again after testing and you must
  re-verify.
- The gate is satisfied by a report whose:
  - body contains a **Test Cases** section,
  - contains staging **API/endpoint** evidence (if backend was edited),
  - contains **Playwright** evidence (if frontend was edited),
  - ends with a line exactly `## Verdict: PASS`.

## The only sanctioned skip — LOUD OVERRIDE
When genuinely blocked (staging unavailable, or a required user-provided secret you don't
have), write `test_reports/OVERRIDE_<slug>.md` containing a line:

```
REASON: <why verification is deferred, and what is needed to finish it>
```

This lets the turn end, records the debt loudly, and is surfaced to the user. It is **not**
a pass — resolve it before merge. There is no silent skip.

## Verify commands recognized by the baseline gate
`npx playwright test` · `pytest` · `yarn build` · `make verify` · staging health curls.
(See `.claude/hooks/clear-if-verified.sh`.) The baseline gate only proves "some check ran";
this protocol's report is the stronger, functionality-scoped proof.
