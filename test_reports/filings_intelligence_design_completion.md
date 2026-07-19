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
| TC-1 | insights API | `GET /api/filings/{id}/insights` for a filing WITH a generated sectioned insight | api | 200; `tabs[]` non-empty; `sections[]` each `{h, items[]}`; `grounded:true`; `disclaimer` present | PENDING |
| TC-2 | insights API | same endpoint for a filing with NO insight yet | api | 404 `{ok:false, reason:"no_insight_yet"}` — not an empty 200 panel | PENDING |
| TC-3 | insights API | citation integrity: every `sec.cite` that names pages maps to a real `document_chunks` page range for that doc | api+data | no citation references a page outside the doc's `page_count` | PENDING |
| TC-4 | insights API | annual-report filing returns the AR tab set, not the generic one | api | `tabs[].label` = Business Overview / MD & A / Financial Statements / Accounting Notes | PENDING |
| TC-5 | generator | metric/period honesty is preserved after the sections change | unit | filing stating no figure → `headline_metric` null; no "Not disclosed" in a value slot | PENDING |
| TC-6 | generator | sections are grounded — generator refuses to emit a section when the doc text is empty | unit | raises/skips rather than emitting invented bullets | PENDING |
| TC-7 | feed API | `GET /api/filings/feed` unchanged contract after the merge (regression) | api | 200; `ok/total/facets/rows[]`; `sort=material\|latest`; `days` capped at 30 | PENDING |
| TC-8 | alerts API | `GET /api/filings/alerts` for a user with no saved prefs | api | 200 with documented defaults, not 404/500 | PENDING |
| TC-9 | alerts API | `PUT` then `GET` round-trips filing types + channel toggles | api | GET returns exactly what PUT wrote, scoped to that user | PENDING |
| TC-10 | alerts API | `PUT` with an unknown filing type | api+edge | 400, and nothing persisted (no partial write) | PENDING |
| TC-11 | alerts API | unauthenticated `GET /api/filings/alerts` | failure | 401/403, never another user's prefs | PENDING |
| TC-12 | UI feed | `/research` renders real feed rows, facets, MATERIAL/LATEST sort, pagination | e2e | rows visible; sort toggle changes order; page 2 loads | PENDING |
| TC-13 | UI insight | expanding a row with insights shows tabs and sectioned bullets + citation | e2e | `<h4>` section heads + `<ul>` items render; cite chip shown | PENDING |
| TC-14 | UI insight | expanding a row WITHOUT insights degrades honestly | e2e | shows "no insight yet" copy; renders no fabricated one-liner/metric | PENDING |
| TC-15 | UI alerts | Alerts screen toggles persist across reload | e2e | toggle → reload → state retained (real API, not local state) | PENDING |
| TC-16 | UI shell | desktop ≥1024px shows the icon rail + top header | e2e | rail present at 1280×800 | PENDING |
| TC-17 | UI shell | mobile (Pixel 7) shows the bottom tab bar and no desktop rail | e2e | bottom nav present at 390×844; rail absent | PENDING |
| TC-18 | UI answer | SOURCES chips render on a copilot answer and scroll to the referenced row | e2e | chip click focuses/expands that row | PENDING |
| TC-19 | design system | `var(--ink)` / `--indigo` / `--danger` resolve correctly in both themes | e2e/visual | text is not transparent/black-on-black in light or dark | PENDING |
| TC-20 | regression | existing `/markets/articles` and copilot dock unaffected by the token changes | e2e | existing specs still pass | PENDING |

---

## API / Endpoint Tests (staging)

> REQUIRED — backend routes/services changed. Real, unedited command + output.

_PENDING — to be filled with real staging output._

## UI / Playwright Tests

> REQUIRED — frontend src changed. Real runner output.

_PENDING — to be filled with real `npx playwright test` output._

## Data Correctness (staging)

> App test AND data test.

_PENDING — will query `nidp.corporate_event_signals` (signal_type='filing_insight')
for sectioned rows, and the alerts store for round-tripped prefs._

## Inputs required from user

- A staging `session_token` cookie (every `/api/filings/*` route calls
  `get_current_user`, so all API cases are behind auth).

## Known gaps (carried, not hidden)

- **Alert delivery is not implemented.** Preferences persist; no worker sends email or
  WhatsApp. WhatsApp has no provider integration anywhere in the repo.
- Insight coverage is bounded by the classifier's 30-day floor and by which filings
  have a parsed PDF — rows outside that render without an insight by design.

## Verdict

_PENDING_
