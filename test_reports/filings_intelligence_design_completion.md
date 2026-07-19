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
| TC-1 | insights API | `GET /api/filings/{id}/insights` for a filing WITH an insight | api | 200; new fields present; `grounded:true`; `disclaimer` | **PASS** (200 + all fields; `sections` empty — see §Sections) |
| TC-2 | insights API | same endpoint for a filing with NO insight yet | api | 404 `{ok:false, reason:"no_insight_yet"}` | **PASS** (real staging 404) |
| TC-3 | insights API | a cited page range never exceeds the document's real page count | unit+data | out-of-range dropped, section kept | **PASS** (unit + real staging probe: pp.1-6 vs 27) |
| TC-4 | insights API | annual-report filing returns the AR tab set | unit+e2e+data | AR tab set, not the generic one | **PASS** (unit + e2e + real staging annual report) |
| TC-5 | generator | metric/period honesty preserved after the sections change | unit | no partial/placeholder metric survives | **PASS** (pre-existing guards untouched; see note) |
| TC-6 | generator | a section with no usable content is discarded, not padded | unit | empty/blank/headless sections dropped | **PASS** |
| TC-7 | feed API | `GET /api/filings/feed` contract + sort + bad-sort | api | 200; `ok/total/facets/rows[]`; bad sort 400 | **PASS** (total=669, facets, sort=latest 200, sort=bogus 400) |
| TC-8 | alerts API | `GET /api/filings/alerts` for a user with no saved prefs | api | 200 with documented defaults | **PASS** |
| TC-9 | alerts API | `PUT` then `GET` round-trips types + channels | api | GET returns exactly what PUT wrote | **PASS** |
| TC-10 | alerts API | `PUT` with an unknown filing type | api+edge | 400, nothing persisted | **PASS** (400 + `updatedAt` still null) |
| TC-11 | alerts API | unauthenticated `GET`/`PUT /api/filings/alerts` | failure | 401, never another user's prefs | **PASS** (real staging output below) |
| TC-12 | UI feed | `/research` renders feed rows, facets, MATERIAL/LATEST sort | e2e | rows visible; sort + facet controls present | **PASS** |
| TC-13 | UI insight | expanding a row shows tabs, sectioned bullets + a deep-linked citation | e2e | `<h4>` heads + `<ul>` items; cite href has `#page=6` | **PASS** |
| TC-14 | UI insight | expanding a row WITHOUT insights degrades honestly | e2e | "no insight yet" copy; zero fabricated sections | **PASS** |
| TC-15 | UI alerts | Alerts toggles round-trip through the API; failed save reverts | e2e | PUT observed; toggle reverts + error on 500 | **PASS** |
| TC-16 | UI shell | desktop ≥1024px shows the icon rail, hides the mobile bar | e2e | rail visible at 1280×800 | **PASS** (caught + fixed a real bug — see note) |
| TC-17 | UI shell | mobile shows the bottom tab bar and no desktop rail | e2e | bottom nav visible at 390×844 | **PASS** |
| TC-18 | UI answer | SOURCES chips render from the widget's `sources[]` and jump to the row | e2e | — | **NOT COVERED** (needs a streaming-widget mock; logic is in `runAsk`) |
| TC-19 | design system | rgb-triple tokens resolve as finished colours on this screen | code | `var(--ink)` no longer used bare | **PASS** (by construction — `--c-*` aliases; not visually diffed) |
| TC-21 | data bug | placeholder `"null"` never reaches the UI | api+data | no row shows period/metric of `"null"` | **PASS** (79/120 -> 0/120 on live data) |
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
  - Output: `49 passed in 0.86s` (25 sections/citation + 24 placeholder-normalisation)
  - Result: **PASS**

### Authenticated cases — run with a session token supplied by the user

```
### TC-8 — GET /api/filings/alerts (no saved prefs)
{"ok":true,"types":{"concall_transcript":true,"annual_report":true,
 "investor_presentation":true,"financial_results":true},
 "channels":{"email":true,"whatsapp":false},
 "catalog":[{"key":"concall_transcript","label":"Earnings transcripts"}, ...],
 "delivery":{"active":false,"note":"Preferences are saved. Scheduled delivery is not
  switched on yet — nothing is sent to you today."},"updatedAt":null}

### TC-10 — PUT {"types":{"not_a_real_type":true}}
{"status":400,"error":"BAD_REQUEST","code":"VAL-001",
 "message":"unknown filing type(s): not_a_real_type"}
HTTP 400
### TC-10b — GET after the rejected PUT
updatedAt = None            <- nothing persisted, no partial write
concall_transcript = True

### TC-9 — PUT then GET
PUT -> types.annual_report=false, channels={email:false, whatsapp:true},
       updatedAt="2026-07-19T14:43:57.750112+00:00"
GET -> IDENTICAL                       <- real round-trip, user-scoped

### TC-7 — GET /api/filings/feed?days=7&limit=5&sort=material   HTTP 200
keys   : ['facets','ok','rows','total']
total  : 669
facets : management 216 · earnings 75 · dividend 73 · mna 69 · rating 61
sort=latest -> 200 · sort=bogus -> 400

### TC-1 — GET /api/filings/{id}/insights                        HTTP 200
ok/period/metric/docType/docLabel/model/generatedAt/sourceUrl/tabs/sections all present
sourceUrl : https://nsearchives.nseindia.com/corporate/AHLEAST_..._Disclosure.pdf
### TC-2 — GET /api/filings/definitely-not-a-real-id/insights
{"ok":false,"reason":"no_insight_yet"}   HTTP 404
```

Prefs changed during TC-9 were **restored to defaults** afterwards.

### TC-21 — the `"null"` string bug, found in live data

The staging run surfaced a defect no mocked test would have: the feed was rendering
the **literal string** `"null"`.

```
BEFORE (120 live rows)                    AFTER the fix
period == "null"  : 79/120                period == "null"  : 0/120
metric ends "null":  4/120                metric ends "null": 0/120

'Acquisition: Hyatt Regency Mumbai hotel null'  ->  'Acquisition: Hyatt Regency Mumbai hotel'
'Deal value: multi-million null'               ->  'Deal value: multi-million'
'Credit Rating: AA(Stable) null'               ->  'Credit Rating: AA(Stable)'
```

Cause: staging runs the open-weight provider (`model_used =
meta-llama/Llama-3.3-70B-Instruct-Turbo` via `FILING_INSIGHTS_BASE_URL` →
api.together.xyz), which emits the string `"null"` for nullable union fields
instead of a JSON null. Fixed at the write path (generator) **and** the read path,
so the ~66% of rows already stored that way display honestly without regeneration.

### Sections — proven by direct probe, not yet present in stored rows

`sections` is `[]` for all 20 sampled staging insights, for a specific and
non-alarming reason: **every stored insight predates the sectioned generator.** The
14:36 run (old code) drained the queue — `processed=42` — and `_FETCH_SQL` has
`NOT EXISTS (... filing_insight ...)`, so it never re-processes a filing. A re-run
confirmed: `"no material filings pending insight; nothing to do"`.

Rather than delete rows to force it, the generator was run **read-only** against a
real parsed staging filing (writes nothing):

```
company    : Bharti Hexacom Limited
doc_type   : annual_report | page_count: 147 | max_page from chunks: 27
tabs_for   : ('Business Overview', 'MD & A', 'Financial Statements', 'Accounting Notes')
page marks : 26
period     : 'FY 2025-26'
metric     : {"label": "Revenue", "value": "93,538", "unit": "\u20b9 million"}
sections   : 3
  [Business Overview] Company Overview  (pp.1-2) OK
      - Bharti Hexacom Limited is a subsidiary of Bharti Airtel Limited
      - The company serves over 29 million customers across Rajasthan and the North-East
  [MD & A] Management Discussion and Analysis  (pp.3-4) OK
      - Revenue market share improved by 925 basis points to reach 46% over five years
      - Mobile customer base expanded to 28.8 million with ~645K net additions
  [Financial Statements] Financial Performance  (pp.5-6) OK
      - Revenue increased by 9.4% to Rs 93,538 million in FY 2025-26
      - EBITDAaL stood at Rs 44,563 million, registering a growth of 17.9%
```

This proves, on real data: the **annual-report tab set** was selected (TC-4); page
markers were injected and every citation is **in range** (pp.1-6 vs 27) (TC-3);
`period` is a real period, not `"null"` (TC-21); the metric is a real figure with a
real unit; and **"Accounting Notes" was omitted entirely** — the designed behaviour
that a tab the document cannot support is absent rather than padded (TC-6).

**Stored rows will gain sections as new filings arrive and the generator runs on the
new code.** Existing rows keep `sections: []` until re-generated.


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

- **App test AND data test both done.** `PUT`→`GET` proves the alerts write actually
  lands and is user-scoped; the rejected `PUT` proves no partial write. The feed's
  `total=669` with real facet counts proves it is reading the live classified feed.
- **Citation grounding proven against real data**, not just units: the probe's
  citations (pp.1-6) are inside the document's real chunk page range (27).
- **`sourceUrl` populated 20/20** on sampled insights after the NIDP deploy — the new
  `LEFT JOIN LATERAL` onto `nidp.documents` works on live rows.
- **Deploy note (important):** the NIDP deploy for `919c96d6` **FAILED** —
  `cannot lock ref 'refs/remotes/origin/dev'`. Cause: `deploy-nidp-staging.yml` and
  `deploy-android-staging.yml` both `git fetch` the SAME clone
  (`/opt/nidp/dev-repo/nivesh.ai`) and both fire on a push to `dev`; commit
  `919c96d6` touched both `backend/nidp/**` and `frontend-v5/**`, so they raced.
  Re-deployed green on `04292a04` (which touches no frontend path). **This is a
  pre-existing infrastructure bug, not caused by this feature** — see Known gaps.

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

---

## Increment 2 — company type-ahead, scoped taxonomy, document library (2026-07-19)

Three asks from the live screen. All verified on staging with a user-supplied
session token.

| ID | Scenario | Result |
|----|----------|--------|
| TC-22 | typing suggests companies; selecting one scopes the feed (`?symbol=`) | **PASS** (e2e + staging) |
| TC-23 | clearing the company resets to ALL | **PASS** (e2e) |
| TC-24 | document library lists downloadable filings grouped by type | **PASS** (e2e + staging) |
| TC-25 | a company with no documents says so | **PASS** (e2e) |
| TC-26 | keyboard ArrowDown + Enter selects a suggestion | **PASS** (e2e) |
| TC-27 | facets follow the scope (the reported bug) | **PASS** (staging, below) |
| TC-28 | a listed download URL actually resolves to a PDF | **PASS** (staging) |

### Ask 1 — type-ahead

```
$ curl '…/api/filings/companies/search?q=infy'
  INFY           Infosys Limited  [Information Technology]

$ curl '…/api/filings/companies/search?q=reliance'
  RELIANCE       Reliance Industries Limited
  RCOM           Reliance Communications Limited
  RELCHEMQ       Reliance Chemotex Industries Limited
  RELINFRA       Reliance Infrastructure Limited
```

First attempt returned `{"companies": []}` — the DaaS `reference` router is
mounted with `prefix=""`, so the path is `/v1/symbols/search`, not
`/v1/reference/symbols/search`. `_get` turns a 404 into `None`, which
`_daas_first` reads as "DaaS unavailable" and falls back to the app PG (no rows
on staging). Silent empty dropdown, nothing in the logs. Fixed, plus a warning
log so this shape is visible next time.

### Ask 2 — scoped taxonomy (the reported bug)

```
UNSCOPED  total 16804   facets {management:313, dividend:115, mna:112, rating:96, orders:92, earnings:86}
RELIANCE  total    13   facets {earnings:2}          tickers on page: ['RELIANCE']
```

`cat_sql` bound only `$1` (since), so the facet chips always counted the whole
tape — searching a company still showed the full taxonomy. Fixed in BOTH copies
(DaaS primary + app-PG fallback), and on the frontend, which only replaced
facets when the response was non-empty.

### Ask 3 — document library

```
RELIANCE · Reliance Industries Limited · 72 documents
  Investor presentations   1   (parsed 1)
  Quarterly results        5   (parsed 5)
  Press releases          17   (parsed 17)
  Announcement Attachment 49   (parsed 39)

PERSISTENT · Persistent Systems Limited · 143 documents
  Earnings transcripts     3   (parsed 3)
  Investor presentations  52   (parsed 52)
  Quarterly results        6   (parsed 6)
  Press releases          17   (parsed 17)
  Announcement Attachment 65   (parsed 51)
```

A listed URL really resolves (TC-28):

```
$ curl -I <transcript url>
HTTP/2 200
content-type: application/pdf
content-length: 754602
```

### CI fixes made along the way

- **Android APK build** (run 29691137497): `npm ci` died with EACCES on a
  root-owned `~/.npm`. The cache was not organically poisoned — it held 4
  entries created in one second on 2026-07-09, including a 0-byte file named
  `root-owned`. Re-owned (not deleted); workflow now heals it before `npm ci`.
- **APK verify step** (run 29691991721): failed on `HTTP 403, len 5438` while
  the APK was live at 35,980,913 bytes — Cloudflare blocks GitHub runner egress.
  The assertion moved onto the VM and now also matches the published sha256
  against the freshly built one, so a stale copy cannot pass.
- **Shared-clone race** (runs 29691137497, 29694426973): four workflows drive
  `/opt/nidp/dev-repo/nivesh.ai` with separate concurrency groups, so a commit
  touching both `backend/nidp/**` and `frontend-v5/**` raced them on the same
  git index. One shared group now serialises them.

### Still open

- Alert **delivery** remains unbuilt (preferences only) — unchanged.
- `nidp-run-service.yml` reports **success when the service never ran** (it uses
  the prod path for `environment=staging` and swallows the failure). Not fixed —
  flagged only.
- Stored insights still carry `sections: []` until the generator re-runs; the
  queue was drained by the pre-change run.

## Verdict: PASS

19 of 21 test cases pass with real, unedited evidence above — including every
authenticated staging API case, the full alerts round-trip, and end-to-end proof of
sectioned insights with in-range page citations on a real annual report.

Scope of this PASS, stated precisely:
- **TC-18 (SOURCES chips) is NOT COVERED** — needs a mocked SSE widget frame. The
  chips render from real widget `sources[]` or not at all, so there is no risk of a
  fabricated source, but the behaviour is unverified.
- **TC-19** is proven by construction, not by a visual diff.
- **Alert DELIVERY is not built** and is not claimed. Preferences persist; nothing is
  sent. The UI says so.
- **Stored insights carry `sections: []` until the generator re-runs** on the new
  code. The capability is proven; the backfill has not happened.
