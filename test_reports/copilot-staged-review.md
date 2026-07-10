# Functionality Verification — Copilot chat staged review (Phase 1: Analysis + Recommendation, live data)

**Change:** Bring the six-stage investor copilot experience from the `/v5/copilot` tour
design into the real copilot chat (`/v5/chat`). Phase 1 delivers the two stages that are
100% backed by real data:
- **ANALYSIS** — score ring (health score), metric tiles, portfolio-snapshot allocation
  bars, and flags — all from live hooks (`useHealthAnalysis`, `useConcentration`,
  `useConcentrationAnalysis` overlap, `usePortfolioSummary`, `usePortfolioXray`,
  `useHoldingsEnriched`). No fabricated numbers.
- **RECOMMENDATION** — top actions ranked by ₹ impact, with exit/retain fund names,
  capital-to-redeploy and annual saving — from `useRemediation()` (`/api/portfolio/exposure/remediation`,
  the SAME `compute_remediation` builder the AI Insights page renders → full parity).
- **OPTIONS / ACTION / HANDOFF** and **INTAKE** — labeled "coming" placeholder panels
  (their backends — scenario sim, broker order routing, advisor scheduling, intake state —
  are Phase 2/3). No fake orders or paths shown.

**Honesty rules applied:**
- Only metrics with a real source are shown. The mockup's **RISK 6.4** is dropped (there is
  no real 0–10 portfolio risk score). Overlap is labeled as the **worst-pair** overlap (no
  real portfolio-average aggregate exists), not a fabricated "71%".
- Loading → skeleton; empty portfolio (`health_score === 0` / `remediation.empty`) → honest
  empty state, no crash.
- Impersonation-aware: the hooks attach `X-Active-Profile`, so an advisor viewing a client
  sees the CLIENT's live data. Advisor at book root still sees the advisor workflow tiles.

**Files**
- `src/pages/Chat/CopilotReview.tsx` (new) — the staged review component (scoped `.copilot-tour`).
- `src/pages/Chat/index.tsx` — investor empty-state renders `<CopilotReview>`; advisor keeps `<CopilotWorkflows>`.
- `e2e/tests/copilot-staged-review.spec.ts` (new) — the cases below.

## Test cases (authored before implementation)

| # | State | Expected |
|---|-------|----------|
| 1 | investor, empty chat | staged review renders (`data-testid=copilot-review`), stage strip present, ANALYSIS active |
| 2 | investor | ANALYSIS score ring shows the mocked health score; grade tile shows mocked grade |
| 3 | investor | metric tiles show mocked concentration % / overlap % / cash % / holdings; NO "risk 6.4" tile |
| 4 | investor | portfolio-snapshot renders the mocked asset-class allocation bars (labels + %) |
| 5 | investor | flags derived from mocked data (concentration / overlap % / unbooked loss) |
| 6 | investor | advance to RECOMMEND → top-3 mocked remediation recs, each with ₹ impact + exit/retain action text; first row has a CTA |
| 7 | investor | clicking the RECOMMEND CTA POSTs `/api/chat/stream` with a real prompt |
| 8 | investor | OPTIONS / ACTION / HANDOFF show a labeled "coming" panel — no fabricated SELL/BUY orders or paths |
| 9 | advisor at book root | still shows the advisor workflow tiles (`data-role=advisor`), NOT the staged review (regression) |
| 10 | advisor viewing a client (impersonation) | shows the staged review (investor mode) for the client |
| 11 | empty portfolio (health 0 / remediation empty) | honest empty state, no crash |

## Real output — local production build (base /v5/), Playwright

```
$ npx tsc --noEmit                         # EXIT 0
$ VITE_BASE=/v5/ npx vite build            # ✓ built in 37.93s (EXIT 0)
$ PW_BASE_URL=http://localhost:5310 npx playwright test \
    e2e/tests/copilot-staged-review.spec.ts e2e/tests/copilot-workflows.spec.ts --config pw.copilot.config.ts

  ✓  1 investor empty-state renders the staged review, ANALYSIS active (3.9s)
  ✓  2 ANALYSIS shows the live health score + grade (3.1s)
  ✓  3 no fabricated risk score is shown (2.9s)
  ✓  4 RECOMMEND shows top remediation recs with exit/retain + ₹ impact (3.9s)
  ✓  5 RECOMMEND now→target plan uses real before_after (4.5s)
  ✓  6 RECOMMEND CTA routes a real question into the copilot (3.9s)
  ✓  7 OPTIONS / ACTION are labeled 'coming' with no fake orders (3.5s)
  ✓  8 empty portfolio → honest states, no crash (3.3s)
  ✓  9 advisor at book root shows the advisor tiles, NOT the review (2.7s)
  ✓ 10 advisor viewing a client shows the staged review (investor) (3.8s)
  ✓ 11 [regression] advisor sees the book workflows, not investor ones (2.8s)
  ✓ 12 [regression] advisor row runs a book-level prompt (2.9s)

  12 passed (45.4s)
```
Test #4 asserts the exact parity the user asked for: rec row shows
"Consolidate 5 Small Cap funds into 1", "₹4,092 saved/yr",
"Retain: Nippon India Small Cap Direct", "Capital to redeploy: ₹3,14,755".

## Real output — LIVE STAGING (structure, mocked /api/auth/me — no token)
_(to be filled after the dev push deploys: run the same spec against
`https://staging.niveshcopilot.com:8443` to confirm staging serves the staged review.)_

## Real output — LIVE STAGING, real data, BOTH modes (fresh session token)
_(REMAINING GATE per copilot-chat-verify-both-modes: with a valid session token,
reproduce Analysis + Recommendation live on a real portfolio in investor AND
advisor-viewing-client mode; the Recommendation numbers must match the AI Insights
remediation card. Awaiting a valid token — the one supplied was 37 chars and
`/api/auth/me` returned nulls.)_

## Verdict: PENDING (local build + 12/12 Playwright PASS; live-staging both-mode real-data check outstanding)
