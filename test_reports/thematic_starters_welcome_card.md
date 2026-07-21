# Functionality Verification Report — Curated thematic welcome card (/v5/research)

- **Branch:** feat/filings-intelligence-design (shipped to `dev`)
- **Date:** 2026-07-21
- **Author:** Claude (Design + Full-Stack + QA)
- **Environment:** staging (staging.niveshcopilot.com:8443 /v5/research · nivesh-staging-app-frontend-v5)
- **Changed areas:** frontend src: **yes** (data/thematicStarters.ts, pages/Research/index.tsx, pages/Chat/StockInsightsLanding.tsx) · backend: no

## Summary
Replaced the 3 flat ask-chips on the Research page (the thematic surface at /v5/research) with
a curated welcome card of 33 starter queries across 8 theme groups. Shows 5 by default with a
"Show 5 more" / "Show less" reveal; featured ("*") picks are starred; each item carries its
theme label; tapping runs it via the ask bar. The curated list is extracted to
data/thematicStarters.ts and shared with the Stocks-Insight landing (no duplication).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | build | tsc --noEmit on the 3 changed files | build | no type errors | PASS |
| TC-2 | deploy | new bundle served on staging (grep dist) | api | strings + testid present | PASS |
| TC-3 | render | /v5/research shows the curated card | e2e | 5 starters by default | PASS |
| TC-4 | content | item shows theme label + query | e2e | "GROWTH & ORDER MOMENTUM \| Biggest order wins…" | PASS |
| TC-5 | reveal | "Show 5 more" adds 5 | e2e | 5 → 10 | PASS |

## Build / Typecheck
- `node_modules/.bin/tsc --noEmit` → exit 0 (no errors in Research/index, StockInsightsLanding, thematicStarters)
- Frontend-v5 image rebuilt (Vite) + `nivesh-staging-app-frontend-v5` recreated @ dev 9a84c2f0
- Deployed dist contains `thematic-starters` testid + "Curated themes" (grep in served /usr/share/nginx/html/assets)

## Playwright (staging /v5/research, session_token cookie)
Real runner output (scratchpad/verify_starters.mjs, chromium headless):
```
starters shown by default: 5
first starter text: GROWTH & ORDER MOMENTUM | Biggest order wins this fortnight — by value, sector, and counterparty (govt/PSU/private)
"show more" button: Show 5 more · 28 left
starters shown after one 'show more': 10
VERDICT: PASS (5 by default)
```
Screenshot: scratchpad/research_starters.png

## Notes
- The `*` picks are rendered as "featured" (star). If that mapping is not intended, it's a
  one-line change in data/thematicStarters.ts.
- Some queries depend on data not yet in the corpus (USFDA scorecard, ASM/GSM surveillance,
  FII/DII shareholding deltas); the card presents them regardless and the thematic backend
  answers what it can — no card-side gating.
- All on `dev`/staging; prod frontend untouched.

## Verdict: PASS
