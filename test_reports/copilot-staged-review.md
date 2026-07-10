# Functionality Verification — Copilot chat staged review (live, all 5 stages)

**Change:** Bring the six-stage investor copilot experience from the `/v5/copilot` tour
design into the real copilot chat (`/v5/chat`). All five stages render off REAL data:

- **INTAKE** — captures goal / risk comfort / time horizon (real user input) + real
  holdings count; "what I know so far" reflects the picks; the picks carry into Analysis.
  (Backend note: the remediation endpoint reads risk from Postgres and does NOT accept a
  client override, so intake selections frame copy — they don't fake a re-scored result.)
- **ANALYSIS** — score ring (health score) + grade + top-sector concentration + worst-pair
  overlap + cash % + holdings + asset-class allocation bars + derived flags, from live
  hooks. The mockup's "risk 6.4" is dropped (no real 0–10 score); overlap is worst-pair
  (no real average exists).
- **OPTIONS** — the real `compute_remediation` recs as choosable paths, each with its real
  ₹ impact + priority. The mock's RISK Δ / EFFORT / TIME columns are labeled "once the
  scenario engine lands", not faked.
- **RECOMMENDATION** — top actions ranked by ₹ impact with exit/retain fund names,
  capital-to-redeploy and annual saving (full parity with the AI Insights remediation card).
- **ACTION** — a **non-executable preview**: the top rec's real per-fund EXIT lines
  (`contributors[].name` + real `value_rs`), the redeploy note, real capital + annual
  saving. Est. cost / tax show **"not computed"** (they are computed nowhere). A loud line
  states **NO ORDERS ARE PLACED — broker links are read-only** (confirmed: there is no
  `place_order` anywhere in the backend; every broker integration is read-only). The CTAs
  route to the copilot / an advisor — nothing executes.

**Honesty:** no fabricated numbers — any metric without a real source is omitted or labeled;
loading → skeleton; empty portfolio → honest per-stage states. Impersonation-aware (hooks
send `X-Active-Profile`), so an advisor viewing a client sees the CLIENT's data; advisors at
their book root keep the workflow tiles.

**Files**
- `src/pages/Chat/CopilotReview.tsx` (new) — the 5-stage review component (scoped `.copilot-tour`).
- `src/pages/Chat/index.tsx` — investor empty-state renders `<CopilotReview>`; advisor keeps `<CopilotWorkflows>`.
- `e2e/tests/copilot-staged-review.spec.ts` (new) — the cases below.
- `e2e/tests/copilot-workflows.spec.ts` — trimmed to the advisor-only cases (investor coverage moved here).

## Test cases (authored before implementation)

| # | State | Expected |
|---|-------|----------|
| 1 | investor, empty chat | staged review renders, stage strip, INTAKE active |
| 2 | investor | INTAKE captures goal→risk→horizon; picks show in "what I know so far" and carry into ANALYSIS context |
| 3 | investor | ANALYSIS ring = mocked health score; grade tile; NO fabricated "risk 6.4" |
| 4 | investor | OPTIONS shows the real remediation recs as paths with real ₹ impact |
| 5 | investor | RECOMMEND top recs with exit/retain + ₹ impact; now→target from before_after |
| 6 | investor | RECOMMEND CTA POSTs `/api/chat/stream` with a real prompt |
| 7 | investor | ACTION preview shows real per-fund EXIT line (name + ₹value_rs); "NO ORDERS ARE PLACED"; est cost "not computed"; NO fabricated SELL/BUY |
| 8 | investor | empty portfolio → honest per-stage states, no crash |
| 9 | advisor at book root | advisor workflow tiles, NOT the review (regression) |
| 10 | advisor viewing a client | staged review (investor mode) |

## Real output — local production build (base /v5/), Playwright

```
$ npx tsc --noEmit                         # EXIT 0
$ VITE_BASE=/v5/ npx vite build            # ✓ built in 38.96s (EXIT 0)
$ PW_BASE_URL=http://localhost:5310 npx playwright test \
    e2e/tests/copilot-staged-review.spec.ts e2e/tests/copilot-workflows.spec.ts --config pw.copilot.config.ts

  ✓  1 investor empty-state renders the staged review, INTAKE active (2.0s)
  ✓  2 INTAKE captures goal → risk → horizon and carries into ANALYSIS (1.6s)
  ✓  3 ANALYSIS shows the live health score + grade, no fabricated risk (1.4s)
  ✓  4 OPTIONS shows the real remediation recs as paths with ₹ impact (1.6s)
  ✓  5 RECOMMEND shows top recs with exit/retain + ₹ impact + now→target (1.8s)
  ✓  6 RECOMMEND CTA routes a real question into the copilot (1.7s)
  ✓  7 ACTION is a non-executable preview of real EXIT lines — no orders placed (1.9s)
  ✓  8 empty portfolio → honest states across stages, no crash (2.3s)
  ✓  9 advisor at book root shows the advisor tiles, NOT the review (1.7s)
  ✓ 10 advisor viewing a client shows the staged review (investor) (1.5s)
  ✓ 11 [regression] advisor sees the book workflows, not investor ones (1.2s)
  ✓ 12 [regression] advisor row runs a book-level prompt (1.2s)

  12 passed (23.5s)
```

## Real output — LIVE STAGING (structure, mocked /api/auth/me — no token)
_(to be re-run after this push deploys — same suite against
`https://staging.niveshcopilot.com:8443`.)_

## Real output — LIVE STAGING, real data, BOTH modes (fresh session token)
_(REMAINING GATE per copilot-chat-verify-both-modes: with a valid session token, reproduce
the live stages on a real portfolio in investor AND advisor-viewing-client mode; the
Recommendation/Action numbers must match the AI Insights remediation card. Awaiting a valid
token — the one supplied was 37 chars and `/api/auth/me` returned nulls.)_

## Verdict: PENDING (local build + 12/12 Playwright PASS; live-staging both-mode real-data check outstanding)
