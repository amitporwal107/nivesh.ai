# Functionality Verification Report — <FUNCTIONALITY NAME>

- **Branch:** <git branch>
- **Date:** <YYYY-MM-DD>
- **Author:** Claude (<role>)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: <yes/no> · frontend src: <yes/no>

## Summary
<One paragraph: what was built/changed and the exact scope verified here.>

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. One row per case.
> Mark each PASS only with real evidence below.

| ID | Area | Scenario | Type (unit/api/e2e/edge/failure) | Expected | Result |
|----|------|----------|----------------------------------|----------|--------|
| TC-1 | | | | | PASS/FAIL |
| TC-2 | | | | | PASS/FAIL |

## API / Endpoint Tests (staging)
> REQUIRED when backend routes/services changed. Paste REAL, unedited command + output.

- **Endpoint:** `METHOD /api/...`
  - Command: `curl -sk 'https://staging.niveshcopilot.com/api/...' -H 'Cookie: session_token=…'`
  - Output: `HTTP 200 …`  <!-- real output; not paraphrased -->
  - Result: PASS/FAIL
- **pytest:** `python3 -m pytest backend/tests/<...> -q`
  - Output: `N passed …`
  - Result: PASS/FAIL

## UI / Playwright Tests
> REQUIRED when frontend src changed. Paste REAL runner output.

- **Spec:** `frontend-v5/e2e/<name>.spec.ts`
  - Command: `npx playwright test <name>`
  - Output: `N passed …`
  - Result: PASS/FAIL

## Data Correctness (staging)
> App test AND data test. Query the real tables the feature reads/writes.

- Query: `<sql / api>`
- Result: PASS/FAIL — <what the data showed; freshness/row-count in band?>

## Inputs required from user
> Anything you had to request (session token, CAS PDF, credentials). If none, write "none".

- <none>

## Verdict: BLOCKED
<!-- Set the line above to EXACTLY "## Verdict: PASS" only when every test case passed with
     real evidence. Leave/keep BLOCKED or FAIL otherwise — the gate opens only on PASS. -->
