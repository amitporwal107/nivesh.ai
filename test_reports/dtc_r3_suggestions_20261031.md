# Functionality Verification Report — Auto-Suggestions & Smart Queries Engine (first release)

- **Branch:** feat/dtc-r3-suggestions (merged with origin/dev 82580088; PR base `dev`)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** unit/contract tests in `nivesh/backend:staging` (`--network none`); the engine run in-process inside
  `nivesh-staging-app-backend` on real staging data, every write refused; a throwaway `mongo:7` for the stores;
  production build served by `vite preview` in the Playwright image, every `/api` call mocked. Not deployed.
- **Changed areas:** backend routes/services: yes (`services/suggestions/`, `routes/suggestions.py`, one include in
  `server.py`) · frontend src: yes (`SuggestionsPanel.tsx`, `use-suggestions.ts`, one mount line in `Home.tsx`)

## Summary
The owner's brief #4 (30 Oct) as a first release: four tabs (For you, Market, My trades, F&O Lab) of cards, each a
question that opens the same visual answer as typing it; five Mongo stores; rules as data; one class per card
(informational / validated signal / risk alert) with its own wording; a freshness gate (a stale or missing source gives
no card, and a notice says so); ranking, dedupe across tabs, cooldowns, dismiss / useful / not relevant / refresh /
"Why am I seeing this?"; the owner's greeting. Scope of the audit's row 19 that is NOT here: rules over real broker
positions (the positions store belongs to another workstream), follow-up questions after every answer (row 9), an
installed cron or event hook, an admin view.

## Test Cases
> Authored up front from the owner's brief and the audit's row 19, before the implementation. IDs are the test names.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| SG-T1 | templates | every one of the 20 query templates, as trader and as investor | unit | `copilot_visual.resolve_intent` returns the template's declared intent (None for the portfolio analyst), with the symbol parameter | PASS (40 cases) |
| SG-T1b | templates | all 13 visual-answer intents incl. `daily_review` (day and week) | unit | each intent has a template; "How did I do this week?" resolves to period week | PASS |
| SG-T2/T3 | catalog | every rule has an evaluator, template, class, tab, known inputs; no wording says buy now / recommend / pick | unit | wired; clean | PASS |
| SG-E1 | market | one daily starter per current source, with the source's own date | unit | 5 cards, the FII/DII why-line carries the figures and the date | PASS |
| SG-E2 | freshness | a stale source and an unreadable source | unit | no card from either; one notice each naming the source, its date and the previous session / the error | PASS |
| SG-E3 | personal | no portfolio | unit | no personal rule fires; a "Connect" notice; only market questions remain | PASS |
| SG-E4 | portfolio | holdings 1 day old vs 12 days old | unit | cards from the portfolio rules vs none + "your holdings were last updated on 18 Oct 2026" | PASS |
| SG-E5 | opportunity | a held or watched stock on the AI scanner's list | unit | validated-signal card with rank, desk status and the scan date | PASS |
| SG-E6 | trades | near stop (long and short), near target, far, not entered, past exit, stale mark | unit | only the right trades alert; a stale mark gives no trade card and "Prices stale" | PASS |
| SG-E7 | limits | today's loss at 60% / 20% of the daily limit | unit | risk alert at 60%, nothing at 20% | PASS |
| SG-E8 | F&O | current list; a list whose chain data is stale | unit | validated-signal cards per instrument; none when `fno_staleness` is set | PASS |
| SG-E9/E10 | ranking | class urgency, audience, one card per (question, parameters, subject) across tabs | unit | risk first, then signal, then questions; no duplicate question | PASS |
| SG-E11 | feedback | dismiss; not relevant; after the cooldown | unit | hidden until the cooldown ends; the rule's score −40 for 7 days | PASS |
| SG-E12 | stores | instances and events written once | unit | events not repeated on re-evaluation | PASS |
| SG-E13..E18 | misc | disconnected broker, a failing rule, stored override and idempotent seed, text/date check on every card, memo, "none met the rule" starter | unit | as stated in each test | PASS |
| SG-I1..I4 | inputs | holdings as-of, user symbols, paper trades read without running the exit job, a failing market source not cached | unit | as stated | PASS |
| SG-R1..R6 | route | list contract, bad query → 422, refresh body (extra field → 422), feedback body for every action + bad action/empty/unknown id/other user, why contract, signed out → 401 | contract | every request body of every route is checked | PASS |
| SG-D1 | data | the engine on real staging data for three users, all writes refused | data | each card carries real dates; stale/missing sources are said | PASS |
| SG-D2 | stores | seed, upserts, dedupe, TTL, unique key, feedback, cooldown on a real MongoDB 7 | data | as below | PASS |
| SG-U1 | greeting | 9:00, 14:00, 20:00 | e2e | "Good morning / afternoon / evening! What would you like to explore?" + the owner's line | PASS |
| SG-U2/U3/U4 | tabs, cards | tab order and counts; Market tab from the REAL capture; click asks the card's question | e2e | as stated | PASS |
| SG-U5/U6 | classes, icon | three classes look different; stock icon beside a stock's name | e2e | accent bar on signal and risk only; icon on symbol cards only | PASS |
| SG-U7..U9 | feedback | dismiss, not relevant, useful bodies; a failing save | e2e | `{action}` sent; card removed / kept; error said | PASS |
| SG-U10/U11 | refresh, why | refresh body `{tab, mode}`; why panel | e2e | new list; rule, data used with dates, cooldown | PASS |
| SG-U12..U14 | notices | stale prices, no portfolio (→ onboarding), broker disconnected (→ brokers page) | e2e | said in words; no personal figure without a portfolio | PASS |
| SG-U15 | failure | backend 500 | e2e | "Suggestions are not available just now" + Try again; the rest of Home works | PASS |
| SG-U16/16b | mode | Investor and Trader request their audience | e2e | `mode=investor` / `mode=trader`; the trader panel is still there | PASS |
| SG-U17/U18 | layout, words | 390 px; no banned words on every card | e2e | no sideways scroll; clean | PASS |
| SG-U19 | visual | screenshots at 1280 and 390 px, read by eye | manual | legible, nothing clipped | PASS (below) |
| REG | regression | existing Home, trader, desk, visual-answer specs; full backend CI allowlist | e2e / unit | no new failures | PASS |
| LIVE | live | the Home tabs on staging with a signed-in session | live | cards from the user's own account | NOT RUN — see OVERRIDE |

## API / Endpoint Tests
There is no staging deploy of this branch, so the routes are exercised through FastAPI's TestClient (SG-R*) and the
engine in-process on staging data (SG-D1). A signed-in HTTP check needs the deploy: see the OVERRIDE.

- **pytest (this feature):** `python -m pytest tests/test_suggestions.py -q` → `72 passed`.
  With the visual-answer suites after merging dev: `tests/test_suggestions.py tests/test_copilot_visual.py tests/test_copilot_visual_chat.py` → `200 passed, 1 skipped`.
- **pytest (full CI allowlist, 286 files), branch vs a clean `origin/dev` checkout, same mounts:**
  - branch: `20 failed, 7556 passed, 34 skipped in 204.39s`
  - origin/dev: `20 failed, 7484 passed, 34 skipped in 207.93s`
  - `comm` of the sorted FAILED names: nothing only on the branch, nothing only on dev. The 20 are the same
    pre-existing failures (cron/installer file checks, desk-redesign result-file fixtures, the TrueData/market-data
    shadow tests, CAS client, move-odds snapshots). +72 passes = this feature's tests.
- **Real-MongoDB check of the stores (`mongo:7`, throwaway container, removed):**
```
seed: {'rules': 22, 'templates': 20} | again: {'rules': 0, 'templates': 0}
cards shown: 20 | instances stored: 20 | events stored: 9
re-evaluated: instances 20 events 9 (unchanged = deduped)
indexes: {'suggestion_rules': 2, 'suggestion_events': 3, 'suggestion_instances': 4, 'suggestion_feedback': 3, 'query_templates': 2}
TTL index: 0 | expires_at type: datetime
feedback state: dismissed | instance state: dismissed
dismissed card hidden after 1h: True | suppressed: 1
back after cooldown (state active again): True active
unique (user_id, dedupe_key) enforced: DuplicateKeyError
```
  The inputs are the unit tests' MOCK fixtures; what this proves is the stores' behaviour on a real database.

## Data Correctness (staging, read-only)
The engine ran in-process in `nivesh-staging-app-backend` (overlay `/tmp/ov_r3suggest`, removed afterwards) for three
runs (two users, one of them in both modes), with every Mongo and Redis write refused by a read-only proxy (`refused writes (stubbed)`: 48 instance and
19 event upserts, the index creations and one Redis cache write: nothing was written). Output is aggregate: personal
card text is withheld, market-tab text is shown. Window: today 31 Oct, previous session 30 Oct.

```
user a5530afb31 (with holdings), investor:  for_you 7 cards + 2 notices, market 4, my_trades 3, fno_lab 4
user a5530afb31 (open paper trades), trader: same inputs, all as_of 2026-10-30; notices: Zerodha / ICICI Direct "disconnected"
user fb08dca0c0 (no portfolio, no trades), investor: for_you 1 card + 1 notice (no_portfolio), market 4, my_trades 2, fno_lab 5
  input holdings empty | paper_trades empty | risk_book empty | ai_watchlist ok as_of 2026-10-30 | fii_dii ok 2026-10-30 ...
  [informational] smart_money_daily | Where smart money is moving — FII cash +₹3,598.54 Cr, DII cash −₹817.51 Cr on 30 Oct 2026. → 'Where is smart money moving?' (smart_money)
  [validated_signal] fno_top_signals | PERSISTENT: Bear put spread 5800/6000 fits today's regime — Rank 1 on the AI scanner's F&O list of 30 Oct 2026; regime fit 100. → "What's the setup for PERSISTENT?" (stock_decision)
```
- The no-portfolio user got no personal card and a connect notice, never "Equity 0% · Debt 0%" (the audit's bug).
- The first run found 0 confirmed breakouts on 30 Oct and still suggested "Which breakouts are confirmed?". Fixed
  (`min_count`): the second run, after merging dev, has no breakouts card. Market tab: 5 → 4 cards.
- The user with two broker accounts (Zerodha, ICICI Direct) has both sessions ended: the notices say the connection has ended.
- Result: PASS for what it covers. NOT covered: the paper-trade near-stop and loss-limit cards did not fire for the
  real users (no trade is near a level today), so those rules are verified on MOCK data only.

## UI / Playwright Tests
Production build (`VITE_USE_MOCK_API=false VITE_BASE=/v5/ vite build`), `vite preview` :5174, `--network none`,
`pw.copilot-app.config.ts`. The Market and F&O Lab tabs use `e2e/fixtures/contract-suggestions.json`, the real capture;
For you and My trades cards are labelled MOCK in the spec.
- `tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`; `vite build` → `BUILD_EXIT=0`, `✓ built in 25.69s`.
- **Spec + regression, on the merged tree:** `copilot-app-suggestions.spec.ts copilot-app.spec.ts copilot-app-daily-trader.spec.ts copilot-app-desk.spec.ts copilot-app-visual-answer.spec.ts` → `95 passed (1.0m)`, 1 skipped (screenshots, opt-in).
- After the final styling change (cards align to the top): the same specs without visual-answer → `63 passed (32.1s)`, 1 skipped.
- The first run of the new spec had one failure (SG-U5 expected a 0 px border on the plain card; it has the app's 1 px
  card border). The test was wrong, not the product; fixed to assert the accent bar is absent.
- **Visual review (SG-U19):** screenshots at 1280 and 390 px, read by eye: legible, cards fit, the class chip, the why
  panel and the notices read well. Two things seen: an open "Why" panel stretched its neighbour card (fixed: cards align
  to the top); at 390 px the F&O Lab tab sits past the right edge of the tab row and is reached by swiping the row (the
  row scrolls; SG-U17 clicks it). Light theme not looked at.

## Inputs required from user
- A live signed-in session on staging after the deploy (see `OVERRIDE_dtc_r3_suggestions.md`).

## Not verified / known limits
- Not deployed: nothing was checked on staging over HTTP, and no suggestion was ever written to the staging database.
- Advisor mode returns no panel (by code); not covered by an e2e case.
- The personal rules (near stop / target, loss limit, portfolio rules, overlap, opportunity-on-holdings) were run on
  MOCK inputs; on real data only the portfolio rules fired.
- In-process memo (60 s per user and mode) is per uvicorn worker; instances are deterministic ids in Mongo, so workers agree.
- The reads for a tab are done for all four tabs together on each evaluation (about 1–3 s on staging, cached 10 min for
  market sources); no timing budget was measured under load.

## Owner decisions
1. **Placement:** the tabs sit above the existing "For your portfolio today" cards and "Try asking", which are
   unchanged (their tests pass). Some overlap (plan, health). Replace the old cards with the tabs, or keep both?
2. **Headline:** the screen's own headline stays ("What would you like to know…"; existing tests assert it); the owner's
   greeting is the panel's heading. Make it the screen headline?
3. **Scheduling:** `python -m services.suggestions.admin pass` and `engine.scheduled_pass` exist; no cron or event hook
   is installed. Pre-open and post-close slots, and a hook after a broker sync / CAS import, are your call.
4. **Seed:** `python -m services.suggestions.admin seed` writes the rules and templates to Mongo for tuning without a
   deploy. The engine works without it (catalog defaults). Not run on staging.
5. **Thresholds** (all in `catalog.py`, tunable in `suggestion_rules`): a trade 70% of the way to its stop (80% to
   its target), loss limit 50% used, fund overlap 40%, holdings fresh within 7 days.
6. **Class names on screen:** "To explore", "Rule-based signal", "Risk check".

## Verdict: PASS
Scope: the backend engine, routes and stores (unit, contract, real-MongoDB and read-only staging data tests), and the
Home tabs on a production build with mocked APIs (Market and F&O Lab on a real capture). The full CI allowlist has the
same 20 failures as `origin/dev` and no new one. The live walk is open (OVERRIDE).
