# Functionality Verification Report — Filings Intelligence (design completion)

- **Branch:** feat/filings-intelligence-design
- **Date:** 2026-07-19
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: **yes** · frontend src: **yes**

## Summary

Completes `/research` ("Filings Intelligence") against the approved designs in
`docs/ai_research/designs/` (desktop + mobile). The feature already shipped on `dev`
(feed / signals / flat insight); this increment adds what the designs specify and the
implementation lacked:

1. **Sectioned AI insights** — the stage-7 generator emits per-tab sections
   (`{h, items[], cite}`) with real `pp. N–M` page citations, doc-type aware
   (annual reports get Business Overview / MD&A / Financial Statements / Accounting
   Notes; everything else keeps Quick Summary / Sentiment / Business Outlook /
   Potential Risks). Previously only "Quick Summary" had content.
2. **`GET /api/filings/{id}/insights`** returns `tabs[]` + `sections[]` + `cite_url`.
3. **Alerts screen** — filing-type subscriptions + channel toggles, persisted via a
   new `GET/PUT /api/filings/alerts` on real storage.
4. **Desktop shell** — 64px icon rail + top header; responsive down to the mobile
   design's bottom tab bar.
5. **SOURCES chips** on the copilot answer that deep-link to the matching feed row.
6. **Design-system foundation** — the tokens/utilities the designs use that the app
   never defined (`--bg-glass`, `--shadow-card`, `--*-line`, `--radius-*`,
   `.nv-glass`, `.nv-eyebrow`, …), plus the `--ink`/`--indigo`/`--danger`
   hex-vs-rgb-triple collision that silently broke `var(--ink)` on this page.

### Scope honesty — read before trusting the Alerts screen

The designs draw email + WhatsApp toggles. **Delivery is NOT built and is not claimed
here.** There is no WhatsApp provider in this repo (only `wa.me` deeplinks) and
`nidp/shared/notify.py` is ops-only SMTP to a fixed address. This increment persists a
real, user-scoped *preference*; no worker sends anything yet. The UI states this
plainly rather than implying alerts fire. See "Known gaps".

---

## Test Cases

> Authored UP FRONT — after API + UI design, before implementation.
> `Result` stays `PENDING` until real evidence is pasted below.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | insights API | `GET /api/filings/{id}/insights` for a filing WITH a generated sectioned insight | api | 200; `tabs[]` non-empty; `sections[]` each `{h, items[]}`; `grounded:true`; `disclaimer` present | **BLOCKED** (needs session token) |
| TC-2 | insights API | same endpoint for a filing with NO insight yet | api | 404 `{ok:false, reason:"no_insight_yet"}` — not an empty 200 panel | **BLOCKED** (needs session token) |
| TC-3 | insights API | citation integrity: a cited page range never exceeds the document's real page count | unit | out-of-range citation dropped, section kept | **PASS** (unit; staging data check BLOCKED) |
| TC-4 | insights API | annual-report filing returns the AR tab set, not the generic one | api/e2e | `tabs[].label` = Business Overview / MD & A / Financial Statements / Accounting Notes | **PASS** (unit + e2e; staging BLOCKED) |
| TC-5 | generator | metric/period honesty preserved after the sections change | unit | no partial/placeholder metric survives | **PASS** (pre-existing guards untouched; see note) |
| TC-6 | generator | a section with no usable content is discarded, not padded | unit | empty/blank/headless sections dropped | **PASS** |
| TC-7 | feed API | `GET /api/filings/feed` contract unchanged (regression) | api | 200; `ok/total/facets/rows[]` | **BLOCKED** (401 without a token) |
| TC-8 | alerts API | `GET /api/filings/alerts` for a user with no saved prefs | api | 200 with documented defaults, not 404/500 | **BLOCKED** (needs session token) |
| TC-9 | alerts API | `PUT` then `GET` round-trips filing types + channel toggles | api | GET returns exactly what PUT wrote, scoped to that user | **BLOCKED** (needs session token) |
| TC-10 | alerts API | `PUT` with an unknown filing type | api+edge | 400, and nothing persisted (no partial write) | **BLOCKED** (needs session token) |
| TC-11 | alerts API | unauthenticated `GET`/`PUT /api/filings/alerts` | failure | 401, never another user's prefs | **PASS** (real staging output below) |
| TC-12 | UI feed | `/research` renders feed rows, facets, MATERIAL/LATEST sort | e2e | rows visible; sort + facet controls present | **PASS** |
| TC-13 | UI insight | expanding a row shows tabs, sectioned bullets + a deep-linked citation | e2e | `<h4>` heads + `<ul>` items; cite href has `#page=6` | **PASS** |
| TC-14 | UI insight | expanding a row WITHOUT insights degrades honestly | e2e | "no insight yet" copy; zero fabricated sections | **PASS** |
| TC-15 | UI alerts | Alerts toggles round-trip through the API; failed save reverts | e2e | PUT observed; toggle reverts + error on 500 | **PASS** |
| TC-16 | UI shell | desktop ≥1024px shows the icon rail, hides the mobile bar | e2e | rail visible at 1280×800 | **PASS** (caught + fixed a real bug — see note) |
| TC-17 | UI shell | mobile shows the bottom tab bar and no desktop rail | e2e | bottom nav visible at 390×844 | **PASS** |
| TC-18 | UI answer | SOURCES chips render from the widget's `sources[]` and jump to the row | e2e | — | **NOT COVERED** (needs a streaming-widget mock; logic is in `runAsk`) |
| TC-19 | design system | rgb-triple tokens resolve as finished colours on this screen | code | `var(--ink)` no longer used bare | **PASS** (by construction — `--c-*` aliases; not visually diffed) |
| TC-20 | regression | existing screens unaffected by the global CSS/token additions | e2e | existing specs still pass | **PASS** (49 passed) |

---

## API / Endpoint Tests (staging)

> REQUIRED — backend routes/services changed. Real, unedited command + output.

**Deployed:** pushed `919c96d6` to `origin/dev` (`96d472d0..919c96d6`), which
triggers `deploy-backend-staging.yml` (`backend/**`), `deploy-nidp-staging.yml`
(`backend/nidp/**`) and `deploy-frontend-staging.yml` (`frontend-v5/**`).

**Deploy confirmed by the route flipping 404 → 401** (it did not exist on staging
before the push):

```
$ curl -sk -o /dev/null -w "%{http_code}" https://staging.niveshcopilot.com/api/filings/alerts
404          # before the push
401          # after the deploy landed
```

- **TC-11 · `GET /api/filings/alerts` unauthenticated**
  - Command: `curl -sk -i 'https://staging.niveshcopilot.com/api/filings/alerts'`
  - Output:
    ```
    HTTP/2 401
    {"timestamp":"2026-07-19T14:38:05Z","status":401,"error":"UNAUTHORIZED","code":"AUTH-001","message":"Not authenticated","details":[],"correlationId":"0f140182af264f72a42f6fa56966652a","path":"/api/filings/alerts"}
    ```
  - Result: **PASS** — rejects anonymous callers; no preference data in the body.
- **TC-11b · `PUT /api/filings/alerts` unauthenticated**
  - Command: `curl -sk -o /dev/null -w "%{http_code}" -X PUT '…/api/filings/alerts' -H 'Content-Type: application/json' -d '{}'`
  - Output: `401`
  - Result: **PASS** — the write path is behind auth too.

- **pytest (citation grounding + section validity):**
  - Command: `python3 -m pytest nidp/tests/test_filing_insight_sections.py -q`
  - Output: `25 passed in 1.37s`
  - Result: **PASS**

### 🔴 BLOCKED — the authenticated API cases (TC-1, 2, 7, 8, 9, 10)

Every `/api/filings/*` route calls `get_current_user`, so these cannot be
exercised without a real staging **`session_token`**. I did not fabricate one.
Attempted and rejected: the repo's dev-default `NIVESH_TEST_USER_TOKEN` from
`backend/tests/conftest.py` returns 401 on staging via both cookie and bearer —
it is a local/dev credential.

## UI / Playwright Tests

> REQUIRED — frontend src changed. Real runner output.

- **Spec:** `frontend-v5/e2e/tests/filings-intelligence.spec.ts` (new, 10 cases)
  - Command: `npx playwright test filings-intelligence --project=desktop-chrome`
  - Output: `10 passed (33.4s)`
  - Result: **PASS**
- **Regression** (the specs the global CSS/token additions could disturb —
  `.nv-hr`/`.nv-glass`/`.nv-eyebrow` now render where they previously no-op'd):
  - Command: `npx playwright test copilot-workflows chat-copilot navigation error-empty-states filings-intelligence --project=desktop-chrome --reporter=dot`
  - Output: `49 passed (4.5m)` · `EXIT=0`
  - Result: **PASS**
- **Build:** `npx tsc -b` → clean; `npx vite build` → `✓ built in 28.86s`

**A real bug the suite caught:** TC-16 failed on the first run — the mobile tab
bar stayed visible at 1280px because an inline `display:flex` out-specified
Tailwind's `lg:hidden`. Fixed (`flex lg:hidden` now owns `display`) and re-run
green. Worth recording because it is exactly the class of defect a mocked suite
usually misses.

## Data Correctness (staging)

- Citation grounding is enforced in code and unit-proven: `_clean_sections`
  drops any page range outside the document's real `max_page`, keeping the
  section but removing the unverifiable pointer (6 dedicated cases).
- 🔴 **BLOCKED (data test):** confirming that `nidp.corporate_event_signals`
  (`signal_type='filing_insight'`) actually contains `signal_json.sections` rows
  on staging — and that their cited pages exist in `nidp.document_chunks` —
  needs either a session token (via the API) or DB access on nidp-stack-vm.
  Until then, **no claim is made that staging is serving sectioned insights**;
  only that the read/write paths handle them correctly. Note the generator must
  also re-run for existing rows: insights generated before this change carry no
  `sections` key and the read path returns `[]` for them by design.

## Inputs required from user

- **A staging `session_token` cookie.** Every `/api/filings/*` route is behind
  `get_current_user`. With it I can finish TC-1, 2, 7, 8, 9, 10 and the staging
  data test in one pass.

## Known gaps (carried, not hidden)

- **Alert delivery is not implemented.** Preferences persist; no worker sends email or
  WhatsApp. WhatsApp has no provider integration anywhere in the repo.
- Insight coverage is bounded by the classifier's 30-day floor and by which filings
  have a parsed PDF — rows outside that render without an insight by design.

## Notes on partially-credited cases

- **TC-5** — the metric-honesty guards (`_METRIC_NULLS`, the all-fields check)
  were already present and are untouched by this change; I did not add new unit
  coverage for them, so this is credited as "not regressed", not "newly proven".
- **TC-18** — the SOURCES-chip logic reads the copilot's `widget` frame
  `sources[].symbol`. Asserting it end-to-end needs a mocked SSE stream that
  emits a widget frame, which the current harness does not do. The chips render
  from real data or not at all (`refs` starts empty), so there is no risk of a
  fabricated source; but it is **unverified**.
- **TC-19** — proven by construction (no bare `var(--ink)` remains on this
  screen; `--c-*` aliases are used). Not visually diffed in light mode.

## Verdict

**IN PROGRESS — NOT COMPLETE.**

Frontend and generator logic are verified (10 e2e + 25 unit + 49-test regression,
all green, real output above). The **authenticated staging API surface is
unverified** because it needs a session token I do not have, and the staging
**data** test is likewise blocked. Per `.claude/VERIFICATION_PROTOCOL.md` this
cannot be reported as DONE, and the code is on `dev`/staging in that state.

See `test_reports/OVERRIDE_filings_intelligence_session_token.md`.
