# Functionality Verification — hide Pro Trader & Strategy Builder (+ dev→main merge auth)

Date: 2026-07-14
Branch: `hide/pro-trader-strategy-builder` off `origin/dev` (@ merge `954c92b7`)
Scope: two shipped changes on `dev`
1. **dev→main merge** (PR #80) — reconciled the diverged auth line; OTP kept **invite-only**.
2. **Hide Pro Trader & Strategy Builder** — removed from the sidebar nav and removed the
   Strategy Builder chat tool chip. Routes/pages kept (reachable by direct URL).

## Test Cases (authored up front)
| # | Case | Expected | Layer |
|---|------|----------|-------|
| TC-1 | Sidebar nav for a signed-in user | "Pro Trader" and "Strategy Builder" links absent; other links (Recommendations) still present | Playwright (mocked) |
| TC-2 | Chat composer tool row | `tool-strategy-builder` chip absent; sibling "Build a portfolio" chip still present | Playwright (mocked) |
| TC-3 | Routes preserved | `/pro-trader` and `/strategy-builder` still routed (hide ≠ remove) | code (routes.tsx) |
| TC-4 | Frontend compiles after removing now-unused icon imports | `tsc -b && vite build` exit 0, 0 TS errors | build |
| TC-5 | Merge OTP policy on staging | non-whitelisted email → 403 invite-gate (not self-registered) | real staging API |
| TC-6 | Merge OTP unit behavior | code gen/hash + email render pass | pytest |

## Evidence (real output)

### TC-4 — frontend build (exit 0, 0 TS errors)
```
$ npm run build   # tsc -b && vite build
✓ built in 34.43s
error TS count: 0
BUILD EXIT: 0
```

### TC-1 — sidebar hides both (Playwright, desktop-chrome, mocked local build)
```
$ npx playwright test navigation.spec.ts --project=desktop-chrome -g "hidden from the sidebar"
✓  1 [desktop-chrome] › navigation.spec.ts:53 › Pro Trader and Strategy Builder are hidden from the sidebar (11.6s)
1 passed (17.3s)
```
(asserts: Recommendations link visible; Pro Trader link count 0; Strategy Builder link count 0)

### TC-2 — chat chip hidden (Playwright, desktop-chrome, mocked local build)
```
$ npx playwright test chat-copilot.spec.ts --project=desktop-chrome -g "Strategy Builder tool chip is hidden"
✓  1 [desktop-chrome] › chat-copilot.spec.ts:22 › Strategy Builder tool chip is hidden (7.4s)
1 passed (11.9s)
```
(asserts: "Build a portfolio" chip visible; `getByTestId("tool-strategy-builder")` count 0)

### TC-3 — routes preserved (hide only)
```
frontend-v5/src/routes.tsx:148  <Route path="/pro-trader"       element={... <ProTraderPage/> ...} />
frontend-v5/src/routes.tsx:149  <Route path="/strategy-builder" element={... <StrategyBuilderPage/> ...} />
```

### TC-5 — merge OTP invite-gate LIVE on staging (real API)
```
$ curl -X POST https://staging.niveshcopilot.com:443/api/auth/otp/request \
       -d '{"email":"notwhitelisted.mergecheck@example.com"}'
HTTP_STATUS:403
{"status":403,"code":"AUTHZ-001","message":"This email isn't on the invite list yet. Request access first, then sign in."}
```
Confirms the merge is deployed AND OTP is invite-only (non-whitelisted email rejected, not self-registered).

### TC-6 — merge OTP unit test
```
$ pytest backend/tests/test_otp_email.py -q
4 passed in 0.12s
```

## Notes / limits
- Playwright ran against a LOCAL mocked build (project `desktop-chrome`, minimal storageState) —
  no staging session token needed for the nav/chip assertions. The behind-auth nav is
  rendered on every authed page, so the mocked render is representative.
- `@live` `strategy-builder-live.spec.ts` navigates to `/v5/strategy-builder` by URL and is
  unaffected (route kept).

## Verdict: PASS
