# Functionality Verification Report — Hedge holdings sources, connect a broker, and "If Nifty falls 5%"

- **Branch:** feat/hedge-connect-broker (commits bb1f3cf6 + d9b2cfef on dev fb66b6d0; first verified as 47fa1c6e + 28c231c3 on dev 33d266fd)
- **Date:** 2026-11-01
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER)
- **Environment:** pre-merge. Unit tests and Playwright (production build, mocked API) ran in containers, and the changed backend service ran against **real staging data** from a throwaway `/tmp` overlay inside the staging backend container. Nothing was deployed; the overlay was removed afterwards.
- **Changed areas:** backend services: yes (`quick_hedge/inputs.py`, `quick_hedge/service.py`, `copilot_visual/builders.py`, `copilot_visual/intents.py`) · frontend src: yes (`HedgeView.tsx`, `hedge-data.ts`, `DailyTraderPanel.tsx`, `Onboarding.tsx`, new `components/NiftyFallCard.tsx`)

## Summary
This follows up the Quick Hedge release (PRs #440 and #444, both merged and live-verified). The owner asked for four things:
1. Say how the hedge finds the holdings.
2. Offer a way to connect the right broker.
3. Add a Manage-risk tool in the Copilot chat.
4. On onboarding, show what a 5% Nifty fall would do to the portfolio and how it can be hedged.

Built:
- The hedge (desk view and chat card) now names its holdings sources. For the CAS it gives the **statement date** from `user_profiles`; for brokers, the connections and whether their sessions have ended.
- When something needs attention, it offers Connect a broker / Sign in again / Update your CAS, which open the Brokers screen.
- The chat card opens with "If Nifty falls X%": the loss without a hedge, with the Balanced hedge, and the difference.
- The Manage-risk tile gets two questions that reach that card.
- The onboarding done step shows a `NiftyFallCard`.

Everything is behind the existing `portfolio_hedge` flag.

## Test cases (authored before the implementation)

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| B-1 | sources | stale CAS (over 35 days) and two ended broker sessions | unit | needs_attention; CAS age shown; each broker marked "ended" | PASS |
| B-2 | sources | fresh CAS and an active broker | unit | no alarm, no action | PASS |
| B-3 | sources | statement-date formats (31-Aug-2026, ISO, d-m-Y, d/m/Y, "31 Aug 2026", junk) | unit | parsed or left alone, never guessed | PASS |
| B-4 | sources | no holdings; no CAS on file | unit | needs attention; no claim about a CAS | PASS |
| B-5 | privacy | profile read | unit | projection is only cas_statement_date + cas_statement_period; **cas_password never read** | PASS |
| B-6 | sources | profile/broker read raises | unit | sources = None; the hedge still answers | PASS |
| B-7 | service | sources passed through to `data.portfolio.sources` | unit | present | PASS |
| B-8 | service | no holdings | unit | reason says to connect a broker or upload a CAS | PASS |
| B-9 | chat card | impact row + headline | unit | "If Nifty falls 5%" kpis first; hand-worked figures | PASS |
| B-10 | chat card | stale / fresh / no broker / no summary | unit | notice + actions as specified; no notice without a summary | PASS |
| B-11 | chat card | no holdings | unit | connect action, no impact figure | PASS |
| B-12 | intent | 3 Manage-risk phrasings incl. "goes down 5%" | unit | portfolio_hedge, fall 5 | PASS |
| B-13 | intent | "Will Nifty fall tomorrow?", "Why did the market fall today?" | unit | not taken as a hedge question | PASS |
| HG-12 | desk | stale sources | e2e | named; ended broker has a sign-in button; it opens Broker connections | PASS |
| HG-13 | desk | no equity-linked holdings | e2e | says so; connect/upload offered; no choices shown | PASS |
| HG-14 | desk | sources unreadable | e2e | card left out, not guessed | PASS |
| DT-3b | chat tile | Manage risk | e2e | Nifty-fall impact + hedge questions after the lead question | PASS |
| NF-1 | onboarding | done step with holdings | e2e | 5% fall impact + the first choice that pays at that fall (Maximum protection in this fixture), from the server's figures | PASS |
| NF-2 | onboarding | flag off | e2e | nothing shown, no request | PASS |
| NF-3 | onboarding | portfolio under one lot | e2e | simulated loss shown, says why no hedge | PASS |
| NF-4 | onboarding | no equity-linked holdings | e2e | says so, offers connect/upload | PASS |
| NF-5 | onboarding | stale sources | e2e | flagged, with a way to update | PASS |
| NF-6 | onboarding | 403 / server error | e2e | 403 hides the card; error says so quietly; step stays | PASS |
| NF-7 | onboarding | no holdings on file | e2e | no card, no request | PASS |
| NF-8 | layout | phone width | e2e | no sideways scroll | PASS |
| B-14 | chat card | the chosen hedge is not reached at the fall (fall lands on the strike) | unit | headline says where it starts paying ("21,850 (5.0% down)") and that it only adds its cost; names the choice that does pay; never "With the Balanced hedge it would be about" | PASS |
| B-15 | chat card | no choice pays at the fall | unit | says where Balanced starts; names no other choice | PASS |
| NF-9 | onboarding | no choice pays at a 5% fall | e2e | `data-pays="no"`; "starts paying only below Nifty 20,700 (10.0% down)"; the 15% row's figures; "choose a smaller tolerable loss"; no "would cut it to" | PASS |
| S-1 | real data | changed service on the staging account | data | sources block matches the account's real state | PASS |
| S-2 | real data | a user with no holdings | data | new message | PASS |
| S-3 | real data | chat card built for the staging account | data | contract check clean; impact row first; sources notice with actions | PASS |

## Results — REAL output from this session

**Backend, core files on the committed branch** (container `nivesh/backend:staging`, `--network none`):
```
$ git log --oneline -1   ->  47fa1c6e feat(hedge): show where holdings come from, connect a broker, and "what if Nifty falls 5%"
$ python -m pytest -q tests/test_quick_hedge_calc.py tests/test_quick_hedge_inputs.py tests/test_quick_hedge_service.py tests/test_quick_hedge_route.py tests/test_quick_hedge_chat.py tests/test_suggestions.py tests/test_copilot_visual.py tests/test_copilot_visual_chat.py
422 passed, 2 warnings in 9.85s
```

**Backend, wider selection, branch vs plain dev.** The selection is every test file that mentions copilot_visual, quick_hedge, portfolio_hedge, suggestions or feature_flags: 31 files. Two files that cannot be collected in this container were left out: `test_portfolio_intelligence.py` needs `/app/frontend/.env`, and `test_research_chart.py` imports `research/`, which is outside the sparse worktree.
```
branch:  54 failed, 1394 passed, 6 skipped, 4 warnings, 8 errors in 55.66s
dev 33d266fd failures: 62
only on branch:
only on dev:
(end)
```
All 62 failures are in suites that need a live server or other services:
- `test_groww_phase2_phase3.py`: 28
- `test_copilot_phase_ab_integration.py`: 22
- `test_v2_5_decision_engine.py`: 11
- `test_chartink_desk.py`: 1

Both trees have the same names; this branch adds none.

**Frontend** (container `mcr.microsoft.com/playwright:v1.47.0-jammy`, production build `VITE_USE_MOCK_API=false VITE_BASE=/v5/`, `vite preview`, `pw.copilot-app.config.ts`). Specs run: nifty-fall-card, desk-hedge, daily-trader, account, screens, desk-risk-controls, desk-risk-desk, desk-risk-phase1, risk-profile, suggestions, visual-answer.
```
TSC_EXIT=0
BUILD_EXIT=0
  4 skipped
  222 passed (2.5m)
PW_EXIT=0
```
The 4 skipped tests are opt-in by design: screenshot capture (`SHOT_DIR`, `SG_SHOTS`, `VA_SHOTS`), plus one conditional skip when the mocked data has no ranked row with a plan id. All new cases ran and passed: HG-12, HG-13, HG-14, NF-1 to NF-8, DT-3b.

Before the rebase, the whole `/v5/app` suite on this change was 1297 passed and 32 failed. The 32 are the same titles as the known pre-existing `copilot-app-desk-strategy-graphs` failures on plain dev.

**Real staging data, desk service** (overlay `/tmp/ov_hc`, read-only, removed afterwards; rupee figures left out of this report):
```
staging account: top-level keys ['confidence', 'data', 'disclosures', 'expiry', 'exposure', 'inputs', 'modes', 'policy_version', 'reasons', 'status', 'tenor'] | 4.3s
sources keys: ['brokers', 'cas', 'holdings', 'needs_attention']
  holdings: [('cas', 'CAS statement', '2026-11-01'), ('broker_native', 'Connected broker', '2026-10-31')]
  cas: {'statement_date': '31-Aug-2026', 'age_days': 62, 'older_than_a_month': True}
  brokers: [('zerodha', 'ended'), ('icicidirect', 'ended')] | needs_attention: True
user with no holdings: keys [...same...]
  reasons: [{'code': 'missing_portfolio', 'message': 'There are no equity-linked holdings to hedge. Connect a broker or upload a CAS statement so the hedge can see your holdings.'}]
intent: None <- Will Nifty fall tomorrow?
intent: None <- Why did the market fall today?
intent: ('portfolio_hedge', {'expected_fall_pct': 10.0}) <- Hedge my portfolio for a 10% crash
```
This shows the CAS mirror date (2026-11-01) differs from the statement date (31 Aug 2026), so the old "as of" label was misleading.

**Real staging data, chat card** (same overlay):
```
resolved: ('portfolio_hedge', {'expected_fall_pct': 5.0}) <- If Nifty goes down 5% what is the impact on my portfolio?
resolved: ('portfolio_hedge', {'expected_fall_pct': 5.0}) <- What happens to my portfolio if Nifty falls 5%?
resolved: ('portfolio_hedge', {'expected_fall_pct': 5.0}) <- How can I hedge my portfolio against a 5% fall?
contract problems: []
first block: impact | If Nifty falls 5% | [('Without a hedge', ...), ('With the Balanced hedge', ...), ('The hedge changes it by', ...)]
sources notice tone: warn
  actions: [{'kind': 'connect_broker', 'label': 'Sign in to Zerodha again'}, {'kind': 'connect_broker', 'label': 'Sign in to ICICI Direct again'}, {'kind': 'connect_broker', 'label': 'Connect a broker or update your CAS'}]
```
The rupee values were elided above.

## Defect found on that real-data run, and fixed (commit after 47fa1c6e)
On the staging account, the Balanced hedge's "with the hedge" loss at a 5% fall was *larger* than the unhedged loss, by about the premium. The put is struck about 7.6% below Nifty, so a 5% fall never reaches it.

The calculator is right: protection starts only after the tolerable loss. But two places implied the hedge helps:
- the onboarding card said the hedge "would cut it to about ₹…";
- the chat headline gave the hedged figure with no explanation.

The NF-1 fixture had the same shape (Balanced −₹7,855 at the 5% fall, Maximum +₹27,650), so NF-1 had been passing while checking the misleading wording.

Fix:
- **Onboarding card:** it shows the first choice that pays at the fall (Balanced, then Maximum, then Lowest cost). When none pays, it says where protection starts, what it does at the first deeper fall that pays, and that a smaller tolerable loss is needed to cover this fall.
- **Chat:** the headline says the chosen hedge "starts paying only below Nifty K (N% down), so at a 5% fall it pays nothing and only adds its cost", and names a choice that pays, if there is one. The "changes it by" tile says it pays nothing at this fall.

The figures themselves are unchanged.

**Backend after the fix** (core files; the wider 31-file comparison above was run on 47fa1c6e, before this change):
```
$ python -m pytest -q tests/test_quick_hedge_calc.py tests/test_quick_hedge_inputs.py tests/test_quick_hedge_service.py tests/test_quick_hedge_route.py tests/test_quick_hedge_chat.py tests/test_suggestions.py tests/test_copilot_visual.py tests/test_copilot_visual_chat.py
424 passed, 2 warnings in 10.67s
```
The new fixture `quick-hedge-fall5-inside.mock.json` was produced by the real service with invented data (tolerance 10% of ₹20 lakh):
```
status ok | spot 23000.0
maximum True [21850.0] | -5: (-100000, -7855, -107855) | -10: (-200000, 66714, -133286) | -15: (-300000, 141284, -158716)
balanced True [20700.0] | -5: (-100000, -3951, -103951) | -10: (-200000, -3951, -203951) | -15: (-300000, 70618, -229382)
lowest_cost False [] | -5: None | -10: None | -15: None
```

**Backend on the fix commit 28c231c3** (re-run on 2 Nov, after a session restart):
```
28c231c3 fix(hedge): never say the hedge cuts a loss it does not reach
424 passed, 2 warnings in 10.72s
```

**Frontend on the fix commit 28c231c3** (same container recipe, `--workers=2`, `NODE_OPTIONS=--max-old-space-size=4096`). Specs run: nifty-fall-card, desk-hedge, daily-trader, account, screens, visual-answer, suggestions.
```
TSC_EXIT=0
BUILD_EXIT=0
  4 skipped
  172 passed (3.2m)
PW_EXIT=0
```
NF-1 to NF-9, HG-12, HG-13, HG-14 and DT-3b all ran and passed. The 4 skipped tests are the same opt-in skips as above.

**After rebasing onto dev fb66b6d0** (2 Nov; dev had changed `copilot_visual/builders.py` and `intents.py`; commits bb1f3cf6 + d9b2cfef). Backend selection: the same 31 files, run on this branch and on a clean copy of dev.
```
branch: 54 failed, 1440 passed, 6 skipped, 4 warnings, 8 errors in 56.87s
dev:    54 failed, 1409 passed, 8 skipped, 4 warnings, 8 errors in 55.86s
only on branch:
only on dev:
(end)
```
Frontend: specs nifty-fall-card, desk-hedge, daily-trader, account, screens, visual-answer, suggestions, desk-risk-desk, risk-profile.
```
TSC_EXIT=0
BUILD_EXIT=0
  4 skipped
  199 passed (2.9m)
PW_EXIT=0
```
NF-1 to NF-9, HG-12, HG-13, HG-14 and DT-3b all ran. 0 failed.

An earlier attempt at the 28c231c3 run, with a 3 GB container memory cap, aborted the Vite build (exit 134, out of memory). It was discarded and re-run without the cap; that failure was the harness, not the code.

## Data correctness
- The holdings source of truth is the Mongo `holdings` collection: `source: cas` rows mirrored by `cas_snapshot_engine`, and `source: broker_native` rows from `hub_reads`. The CAS statement date comes from `user_profiles.cas_statement_date`. Broker session state comes from `broker_accounts.status`. On staging the summary matched those documents: both broker accounts `expired`, statement 31-Aug-2026.
- The reader takes only the fields it needs (B-5). It never reads the CAS password field.

## NOT verified (UNVERIFIED)
- **Deployed route and screens.** These need the PR merged, a backend restart and a frontend image rebuild. The app VM had **5.9 GB free** at 1 Nov ~15:40 IST, and a deploy needs 6 GB.
- **The model's prose under the card.** Separately, on staging 25 of 57 saved visual answers start with "Some figures ... could not be verified". The compliance node checks numbers only against `tool_results`, while the visual card's facts reach the model inside the user message. This is not caused by this branch; it is reported to the owner as its own finding.
- **Flag-off path live** (needs a second account), and a trading day with live prices (today is Sunday; option data is the 30 Oct close).
- **Onboarding overlap:** the unpushed `feat/generic-onboarding` removes the done step this card sits on. It must be carried into the new flow when either branch merges.

## Inputs required from user
- none for this pre-merge run. The post-deploy check uses the stored staging session token.

## Verdict: PASS
