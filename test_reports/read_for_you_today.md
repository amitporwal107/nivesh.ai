# Functionality Verification Report — "Read for you today" (Bloomberg + drawer + portfolio impact)

- **Branch:** feat/filings-intelligence-design (shipped to `dev`)
- **Date:** 2026-07-21
- **Environment:** staging (/v5/research :8443 · app-backend · nidp_staging)
- **Changed areas:** backend routes (filings.py) · frontend src (Research/index.tsx, filings.adapter.ts)

## Summary
Rebuilt the "Read for you today" surface per the scoped design: today-strict (IST) with an
honest empty state + "Show latest" toggle; editorial Bloomberg-style cards that are clickable
and open an **in-page detail drawer** (event + AI-insight sections with citations + source
PDF); and **portfolio impact** — an "In your portfolio" badge on any card whose stock the user
holds, plus a "You hold X — this filing may affect your position" callout in the drawer.
Backend: /api/filings/signals today-strict (+id/company); new /api/filings/portfolio-held.

## Test Cases
| ID | Scenario | Type | Expected | Result |
|----|----------|------|----------|--------|
| TC-1 | signals today_only=true | api | today=2026-07-21, honest (0 today) | PASS |
| TC-2 | signals today_only=false carry id+company | api | 3 with company names | PASS |
| TC-3 | /api/filings/portfolio-held | api | held names for the user | PASS |
| TC-4 | today-strict → empty state renders | e2e | "Markets quiet…" shown | PASS |
| TC-5 | "Show latest" toggle → cards | e2e | 3 cards appear | PASS |
| TC-6 | portfolio badge on held card | e2e | PUNJLLOYD shows "IN YOUR PORTFOLIO" | PASS |
| TC-7 | click card → in-page drawer | e2e | drawer opens | PASS |
| TC-8 | drawer AI-insight + portfolio callout + source | e2e | all present | PASS |
| TC-9 | tsc + vite build | build | exit 0 | PASS |

## API (staging) — real output
- `GET /api/filings/signals?today_only=true` → `{ today: "2026-07-21", signals: [] }` (today genuinely has 0 material filings yet — the honest empty case)
- `GET /api/filings/signals?today_only=false` → 3 signals, now carrying company (Punj Lloyd Limited, DPSC Limited, Marksans Pharma Limited) + id
- `GET /api/filings/portfolio-held` → returns the user's held companies (the test user holds Punj Lloyd, matched by canonical name)

## Playwright (staging /v5/research, session_token cookie) — real output
```
today-strict → empty-state: 1 | cards: 0
today-toggle label: Show latest
after 'Show latest' → cards: 3
first card: 01 | PUNJLLOYD | LITIGATION | Punj Lloyd Limited | IN YOUR PORTFOLIO | Punj Lloyd
  Limited announced the resignation of its cost auditor... | 20 Jul | Open →
DRAWER opened: PUNJLLOYD | LITIGATION | IN YOUR PORTFOLIO | Punj Lloyd Limited | 20 Jul |
  You hold PUNJLLOYD — this filing may affect your position. | [summary]...
drawer has 'AI insight' section: true
VERDICT: PASS
```
Screenshot: scratchpad/readfor.png — drawer shows the AI INSIGHT sections (Resignation of Cost
Auditor, Market Sentiment, Future Appointments, Risks) with page citations + Open source PDF.

## Build
- tsc --noEmit exit 0; vite build exit 0; frontend-v5 rebuilt + recreated @ dev 3a63f90b
- backend filings.py deployed @ dev b5839dfa

## Notes
- "Strictly today" is honestly empty when the market hasn't filed yet (weekend/early day);
  the "Show latest" toggle surfaces the most recent day on demand.
- Portfolio match is by canonical company name / ISIN / NSE symbol (holdings carry name+ISIN).
- prod untouched.

## Verdict: PASS
