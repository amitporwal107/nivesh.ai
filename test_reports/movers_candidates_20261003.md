# Functionality Verification Report — Movers "Candidates" mode (events + bulk/block deals)

- **Branch:** `feat/movers-monday-candidates` (new worktree off `origin/dev` @ `83783215`, per owner's branch decision)
- **Date:** 2026-10-03
- **Author:** Claude (full-stack developer)
- **Environment:** mocked DB (backend pytest) + mocked API (frontend Playwright) + real staging DB (direct SQL)
  + real staging HTTP (deployed). See the update below — deployed and the route is live; an authenticated
  end-to-end check is the one piece still open.
- **Changed areas:** backend routes/services: yes (`backend/nidp/services/daas_api/routers/movers.py`,
  `backend/routes/movers.py`) · frontend src: yes (`movers.adapter.ts`, `MoversShell.tsx`, `MoversView.tsx`,
  `MoveOddsScreen.tsx`, `pages/Research/index.tsx`)

## Summary

Added `GET /movers/candidates` (DaaS) / `GET /api/movers/candidates` (app proxy): stocks with a material
filing (`impact_score = 'high'`) or a bulk/block deal on one session — no price-move filter, no odds-model
score. Added a third "CANDIDATES" mode to the existing (previously unmounted) Top Movers dashboard
(`MoversRail`/`MoversHero` in `MoversShell.tsx`, wired in `MoversView.tsx`), which reuses the already-built
`MoversChart` (candles + event lanes) and `MoversLog` (event/deal timeline) as-is, and deliberately hides the
odds-model-specific panels (sensitivity, Copilot attribution, technical score, flag-lift, model panel) for
this mode — the owner was explicit this is "purely on the basis of market events and bulk deals," not a
prediction. Added a "Candidates for the next session →" link on the `/v5/research` filings feed screen
(visible only when `features.move_odds` is on) that deep-links straight into it. `view`/`mode` now also read
from the URL once at mount so the link works as a real deep link.

## Test Cases

See `TESTCASES_movers_candidates.md`. TC-C01–C19 PASS with real output below; TC-C20–C22 BLOCKED.

## Backend tests (mocked DB connection — not real data)

Command:
```
cd backend && python -m pytest tests/test_movers_v4.py tests/test_movers_proxy.py -q
```
Output:
```
.....................................................................    [100%]
69 passed in 0.59s
```
69 = 62 pre-existing (unmodified, confirms no regression) + 7 new: `test_candidates_route_registered_before_symbol`,
`test_candidates_merges_signals_and_ranks_by_deal_value`, `test_candidates_drops_illiquid_and_priceless_symbols`,
`test_candidates_empty_day_still_carries_rule_and_disclaimer`, `test_candidates_404_when_no_session_on_record`,
`test_candidates_forwards_session_and_limit`, `test_candidates_omits_session_when_not_given`.

These mock the asyncpg connection (canned rows keyed by SQL substring, same idiom as the existing `_FwdConn`
for `/forward`) — they prove the merge/rank/liquidity-filter/route-order/forwarding logic is correct, **not**
that the real tables or real data behave this way.

## Frontend build + tests

```
cd frontend-v5 && npx tsc -b
```
Output: (empty — exit 0, clean compile)

```
cd frontend-v5 && npx playwright test e2e/tests/research-movers-candidates.spec.ts \
  e2e/tests/research-movers-v4.spec.ts e2e/tests/research-movers-v4-ui.spec.ts e2e/tests/research-movers.spec.ts \
  --reporter=list
```
Output (tail):
```
  ✓   2 … the feed screen shows a Candidates link that deep-links into Movers (3.3s)
  ✓   3 … candidates render with a signal badge and no odds-model framing (3.3s)
  ✓   4 … selecting BBB swaps the chart and timeline to its own event (2.8s)
  ✓   5 … the FILING / DEAL filter narrows the rail (2.6s)
  ✓   6 … an empty day shows the honest empty state, not a blank list (2.3s)
  … [42 pre-existing Movers v4/v1 cases, all ✓, unmodified]
  48 passed (2.0m)
```
Full untruncated run (first attempt) is in the session transcript; the figures above are the clean re-run
after a stale dev-server process (started before several of these edits landed, not picking them up — Vite's
file watcher did not fire in this sandbox) was killed and Playwright started a fresh one. The first run's 5
failures were a stale-server artifact, not a code defect — re-run with a fresh server, 0 failures.

Route mocks are fixtures shaped like the real endpoints (see `research-movers-candidates.spec.ts`) — these
prove the SCREEN (rail/hero/chart/log, mode switch, filters, absence of odds-model panels, verbatim
disclaimer text), **not** real data.

## API / Endpoint Tests (staging) — deployed 2026-10-03

Merged `origin/dev`'s concurrent `feat(movers): FORWARD tab beside MOVERS and FLAGGED` commits into this
branch by hand (both touched `MoversShell.tsx`/`MoversView.tsx` in the same places; resolved to a coherent
4-mode dashboard — MOVERS / FLAGGED / FORWARD / CANDIDATES — re-verified: 69 backend pytest, `tsc -b` clean,
49 Playwright including the pre-existing FORWARD-tab cases, 0 failures). Pushed to `dev`
(`32ee917d..10503c75`, fast-forward) and ran the staging redeploy script on `nivesh-app-vm`:

```
Image nivesh/backend:staging Built
Image nivesh/frontend:staging Built
Image nivesh/frontend-v5:staging Built
[redeploy-staging] Waiting for nivesh-staging-app-backend to report healthy...
[redeploy-staging] Healthy after 1 checks.
[redeploy-staging] Smoke check via nginx on 127.0.0.1:8443...
{"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
```

Then, from outside the VM:
```
curl -sk -o /dev/null -w "healthz: %{http_code}\n" https://staging.niveshcopilot.com/api/healthz
→ healthz: 200

curl -sk https://staging.niveshcopilot.com/api/movers/candidates
→ HTTP 401 {"status":401,"error":"UNAUTHORIZED","code":"AUTH-001","message":"Not authenticated", "path":"/api/movers/candidates"}
```
**Result: PASS for "is it deployed and wired correctly."** The route exists and answers (401, not 404/500) —
confirms the app's router registered it, matching `test_candidates_route_registered_before_symbol`. An
**authenticated** end-to-end call (what a logged-in, allowlisted user actually sees) is the one thing still
open — I have no session token and won't fabricate one. See "what's left" below.

## Data Correctness (staging) — 2026-10-03, after the GCP token was refreshed

Ran the real logic of `candidates()` directly against the real `nidp_staging` Postgres on `nidp-stack-vm`
(via `gcloud compute ssh --tunnel-through-iap`, `psql "$NIDP_POSTGRES_URL"`; connection string never printed).

```
-- latest EQ session on staging
SELECT max(as_of_date) FROM nidp.prices_eod WHERE series = 'EQ';
→ 2026-10-01

-- table existence
SELECT to_regclass('nidp.corporate_announcements'), to_regclass('nidp.bulk_deals'),
       to_regclass('nidp.block_deals'), to_regclass('nidp.prices_eod');
→ nidp.corporate_announcements|nidp.bulk_deals|nidp.block_deals|nidp.prices_eod   (all exist)

-- high-impact filings on 2026-10-01: 39 rows, e.g.
ADANIGREEN|Updates
BAJFINANCE|Qualified Institutional Placement
BAJFINANCE|Preferential issue
GODREJPROP|Action(s) initiated or orders passed
HEGAM|Bagging/Receiving of orders/contracts
… (39 total)

-- bulk/block deals on 2026-10-01, e.g.
BLOCK|NIRLON|NIHAR NANDAN NILEKANI|SELL|2325000|615.0000
BLOCK|EDELWEISS|PABRAI WAGONS ETF|BUY|14572000|142.7300
BULK|AONESTEELS|MARWADI CHANDARANA INTERMEDIARIES BROKERS PRIVATE LIMITED|BUY|573384|420.1800
… (several more)

-- full merge + liquidity-floor logic, same rule as candidates():
liquid_candidates | total_signal_symbols | no_price_row
               53 |                   69 |           13

-- top 10 by deal value (symbol | n_signals | deal_val | turnover)
EDELWEISS |4 |2079861560 |855635661.78
MONEYVIEW |14|1681099471 |36986973541.44
TARIL     |8 |914340253  |16552705437.75
NUVAMA    |2 |859994050  |1459795070.10
RATNAVEER |6 |657437144  |3964521718.65
HEROMOTORS|4 |550045257  |14311943018.94
ELEVATE   |1 |339713805  |5252678621.00
GKSL      |28|299854359  |6943525794.43
SSRETAIL  |2 |296273384  |5779218131.00
AONESTEELS|11|287147773  |6479215316.55
```
**Result: PASS.** Real tables, real data, the merge/rank/liquidity-floor logic behaves as implemented: 69
symbols had a signal on the real latest session, 53 pass the liquidity floor (13 correctly dropped for no EQ
price row that session — suspended/BE-BZ/untraded, not shown with an invented dash), and the ranking puts the
largest real bulk/block deals first. This is the same arithmetic as `candidates()`, run by hand over the real
tables it reads; it is not a run of the Python function itself (that still needs the branch deployed, or a
local process pointed at this DB — not done here, see below).

## A separate finding, now resolved: `move_odds` had an empty allowlist on staging

Checked `move_odds`'s live state the same way the code reads it: staging Mongo (`portfolio_ingestion` DB,
`system_config` collection) had **zero documents** — nobody had ever persisted a feature-flag override there.
`feature_flags.py`'s own default for `move_odds` is `mode: allowlist, allowlist: []` ("admins included" per
its own docstring — `is_admin` does not bypass this gate), so Movers (old modes and new) was unreachable for
every account, including the owner's. Not caused by this branch — a pre-existing condition surfaced while
checking the staging path.

Owner confirmed (AskUserQuestion): add `aporwal107@gmail.com`. Wrote it directly (`docker exec
nivesh-staging-mongo mongosh`, read back to confirm, credentials never printed):
```
db.system_config.updateOne(
  {key: "feature_flags"},
  {$set: {"flags.move_odds": {mode: "allowlist", allowlist: ["aporwal107@gmail.com"]}, updated_at: ..., updated_by: ...}},
  {upsert: true}
)
→ {
    flags: { move_odds: { mode: 'allowlist', allowlist: [ 'aporwal107@gmail.com' ] } },
    updated_at: '2026-10-03T12:23:44.514Z',
    updated_by: 'claude-session-aporwal107-request'
  }
```
Backend workers refresh feature flags from this document every 30s (`feature_gate.REFRESH_SECONDS`), so this
takes effect without a restart.

## What's left

Everything that was within reach without a human-provided secret is done: merged, deployed, flag enabled,
route confirmed live (401, not 404/500). The one remaining gap is a session-authenticated pass — opening
`https://staging.niveshcopilot.com/v5/research` as `aporwal107@gmail.com`, clicking "Candidates for the next
session →", and confirming the rail/chart/timeline render with real data. That needs either the owner to look
themselves (the account is now entitled) or a session token handed to this session — not fabricated either
way, per this repo's rule.

## Verdict: BLOCKED
<!-- TC-C01-19, TC-C20 (deployed + route confirmed live) and TC-C22 (real staging data) are real PASSes with
     real command output above. TC-C21 (an authenticated live pass through the actual UI) is the one thing
     still open, and only because it needs a human session, not a credential or deploy blocker any more. -->
