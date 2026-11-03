# Compliance wording — no trading-call words in the Copilot app (owner, 3 Nov 2026)

Branch `fix/compliance-wording`, rebased on origin/dev `d8cfff7d` (checked again just before the push). Worktree
`/home/deploy/nivesh-wt-wording`. Test cases and the full pre-edit inventory: `test_reports/compliance_wording_TESTCASES.md`.

> "Please check compliance and do not use words like buy, stop loss, target" — owner, 3 Nov 2026. Approved vocabulary:
> Buy / Sell → Long / Short; Stop loss / SL / stop → Risk level; Target / T1 / T2 → Reward level (1 / 2); Entry →
> Reference price; "Loss at stop" → "Loss at risk level". Nivesh is not a SEBI-registered Research Analyst.

## Test Cases

| ID | Type | Case | Result |
|---|---|---|---|
| TC-1 | unit (backend, NEW) | every `copilot_visual` builder payload (18 core intents + every-read-failing + 5 research) through a banned-word lint | PASS (`test_compliance_wording_lint.py` WL-2) |
| TC-2 | unit (backend, NEW) | static strings of every `copilot_visual` module; `suggestions/catalog.py` templates; suggested-prompt chips; follow-up chips | PASS (WL-1, WL-3, WL-4, WL-5) |
| TC-3 | unit (backend, NEW) | vocabulary rule in every answer prompt; `wording_hits()` counts banned words (incl. bullish / bearish / undervalued / overvalued / cheap / expensive); the node rewrites nothing new | PASS (WL-5) |
| TC-4 | unit (backend) | named suites (copilot_visual, suggestions, copilot_agent, desk, positional, paper, strategy …) | PASS: identical failure set on dev and branch (see below) |
| TC-5 | contract | API field names / values unchanged | PASS (diff grep below) |
| TC-6 | e2e (Playwright, NEW) | every Trading Desk place rendered with mocked API, text + aria-label/title/placeholder linted | PASS on branch (3/3); FAILS on the dev build (224 hit lines) |
| TC-7 | e2e (Playwright) | all copilot-app specs, dev build vs branch build | PASS: no failure the dev build does not have (see "Playwright") |
| TC-8 | typecheck | `tsc --noEmit -p tsconfig.json` | PASS (exit 0) |
| TC-9 | edge | a contract code rendered raw (side buy/sell, BUY/SELL deal side, stance BUY/HOLD/SELL, plan direction) | PASS: display mappings, data unchanged |
| TC-10 | edge | non-trading senses (Stop generating, exit load, Suggested questions, Long build-up) | PASS: allow-listed in both guards |
| TC-11 | question routing | every sent chip / example question whose text changed | 9 of 24 identical; differences listed below |
| TC-12 | staging, read-only (now) | deployed staging endpoints, banned words in their strings | done: old words still served today (expected before merge) |
| TC-13 | staging (after merge + deploy) | same pages after deploy | UNVERIFIED: needs the merge, the frontend image rebuild and a backend restart |

## Backend

### CI allowlist (exact list of `.github/workflows/backend-tests.yml`), dev vs branch, same container

```
dev    d8cfff7d (313 files): 3 failed, 9130 passed, 51 skipped in 276.50s (0:04:36)
branch 1d463a23 (314 files): 3 failed, 9196 passed, 51 skipped in 284.38s (0:04:44)   (+66 = tests/test_compliance_wording_lint.py)
branch-only failures: (none)
dev-only failures:    (none)
both:
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches
```
These 3 need the network (the container runs `--network none`). GitHub's run on dev reports 6 pre-existing failures (MS-11,
SW-7, test_cas_api_client ×2, test_move_odds_filing_analysis TC-10/11, test_nidp_stamp_broadcast_at); MS-11, SW-7 and TC-10/11
pass in this container on both trees. The branch adds no failure on either side. The lint test is added to the allowlist.

### Named suites (copilot_visual, suggestions, copilot_agent, desk, positional, paper, strategy, ai_watchlist, open_book …)

```
dev 6d30a7f7           : 95 failed, 3210 passed, 20 skipped, 17 errors in 119.56s
branch (on 6d30a7f7)   : 95 failed, 3210 passed, 20 skipped, 17 errors in 118.29s
(the later rebase onto d8cfff7d brought only scan_builder backend files, none in these suites)
diff of the 112 failing/erroring test ids: branch-only = none, dev-only = none
```
(The 95 + 17 are pre-existing: copilot_agent graph/recommendation/tax tests that need services, and others not in the CI list.)

### New guard: `backend/tests/test_compliance_wording_lint.py` — `66 passed in 8.02s`

### Contract proof (TC-5)
`git diff origin/dev...HEAD -- backend frontend-v5/src` changes string literals, labels and display mappings only. No dict
key, request/response field, enum value, route path, data-testid or comparison changed. Display mappings added where a code
was shown raw: side `buy/sell` → Long/Short (StructureCard, OptionChain L/S, Journal, FnoLevels, DecisionCard legs), deal
side BUY/SELL → "Client · purchase / sale", stance BUY/HOLD/SELL → STRONG/NEUTRAL/WEAK (chat card), plan direction
bullish/bearish → long/short (broker review facts, chat "Plan a … trade instead"). The stored values are unchanged.

## Playwright

All copilot-app specs (`pw.copilot-app.config.ts`), production builds served by `vite preview` (VITE_BASE=/v5/), `--network none`,
same container image and browser volume, final rebase base dev `d8cfff7d`:

```
dev    d8cfff7d  build assets/index-DBJa62RU.js : 1450 tests — 32 failed, 51 skipped, 1367 passed (15.0m)
branch 1d463a23  build assets/index-DUUw09GT.js : 1453 tests — 62 failed, 51 skipped, 1340 passed (16.1m)
```
Branch-vs-dev failure diff (keyed by spec + title):
- 32 fail on BOTH: all `copilot-app-desk-strategy-graphs.spec.ts` (needs a `VITE_STRATEGY_HARNESS=1` build; pre-existing).
- 30 fail on the branch run only, every one a SCREENSHOT WRITE: the branch run mounted a read-only snapshot of `e2e/`
  (`EROFS: read-only file system, open 'e2e/.shots/…'` and `ENOENT … 'e2e/screenshots/…'`). Re-run of those 8 spec files
  on the branch with a writable `e2e/` (chart-analysis-basket, desk-chart-analysis, desk-events, desk-expectation,
  desk-macro, desk-results-today, desk-scanner, desk-symbol-search):
  ```
  assets/index-DUUw09GT.js
    181 passed (1.8m)
  ```
- Fail on dev only: none. Branch failures excluding the screenshot writes = exactly dev's 32 (`same set as dev: True`).
- +3 tests on the branch = the new guard `copilot-app-compliance-wording.spec.ts`.

New guard (TC-6), the same spec file against each build:
```
branch build assets/index-BLYqyVO0.js:  CW-1 ✓  CW-2 ✓  CW-3 ✓   3 passed (25.3s)
dev build    assets/index-CWpMJVef.js:  CW-1 ✓  CW-2 ✘  CW-3 ✘   2 failed, 1 passed (25.4s)
  dev hit lines: 224 across all 18 desk places, e.g. "Recommendations", "END OF DAY · IDEAS FOR REVIEW, NOT RECOMMENDATIONS",
  "Find today's top 5 trading opportunities with entry, stop-loss and targets", "TO TARGET"
```
`research-move-odds.spec.ts` (chat stock card; not a copilot-app spec, temporary config): dev `49 passed (44.0s)`,
branch `49 passed (45.0s)`.

An earlier full pair (dev `6d30a7f7` 1317 passed / 79 failed / 51 skipped in 4.2 h under load average 84 on 4 CPUs;
branch 1330 / 69 / 51) is superseded: that dev run imported the worktree's branch `src` in three pure-logic specs and
timed out under load; a clean re-run of those files on dev gave `73 passed`.

## Typecheck
`npx tsc --noEmit -p tsconfig.json` on the final branch `1d463a23`: `tsc exit 0`.

## Question routing (TC-11)
Each changed chip / example question, old vs new, through `copilot_visual.resolve_intent` (trader / investor, with and
without a thread stock) and `copilot_agent.match_agent`: 9 of 24 identical. Differences:
- Removed mis-routes (old text sent a portfolio or review question to the stock trade plan `stock_decision` when a stock was
  in the thread): "target allocation" ×4, "entry, stop-loss and exit rules" ×2.
- Agent now deterministic where it was the LLM classifier: "Why are these steps in my portfolio plan?" → portfolio_analyst;
  "Which of my holdings carry losses …" → portfolio_analyst; "institutional flows" → market_analyst (and smart_money, no
  longer ownership_trend, with a thread stock); "How would a trailing risk level work on my X?" → risk_analyst.
- Changed answer: the research lens chip "Should I buy X?" → "How does X score today?" now gets the stock analyst, not the
  trade-plan card (`stock_decision`) for a trader. "Is this stock a buy now?" → "What does the setup look like…" now also
  reaches `stock_decision` for an investor. "Should I book profits or hold?" → "Where does my trade stand: close it or hold?"
  keeps `exit_options` with a thread stock; without one the agent is the LLM classifier (was stocks_insights).
- "What is each idea based on?" (internal Tool builder sample only) → no deterministic agent (was recommendation).
- Trade-card flip chip "Plan a bearish/bullish trade for X instead" → "Plan a short/long trade for X instead": kept on
  stock_analyst by an ADDITIVE pattern `\b(?:long|short)\s+(?:trade|plan)\b` in intent_patterns (bullish/bearish still
  recognised; "my short trades" is not captured).

## Staging, read-only today (TC-12)
Signed-in GETs on https://staging.niveshcopilot.com (token from file, never printed); strings with a banned word:
```
/api/copilot/suggested-prompts?mode=investor   4 (2 unique: "…which to exit with lowest tax hit", "…follow your recommended actions…")
/api/copilot/suggested-prompts?mode=trader     2 (1 unique: "Entry zone, volume confirmation, invalidation")
/api/desk/ai-watchlist                         249 (51 unique: "2 x the stop distance", "A stop is a level, not a guaranteed price…")
/api/desk/exit-job-status                      1 ("Exits were checked after the 2026-11-02 close.")
/api/risk/policy, /api/positional/watchlist, /api/positional/picks, /api/desk/strategy/templates, /api/desk/strategy/plans,
/api/research/chart/live/RELIANCE/patterns     0
```
The branch rewords the three prompt sources (routes/copilot_prompts.py) and the exit-job message; the AI-watchlist strings
come from day lists STORED in Mongo `ai_watchlist_days` before this change, so they keep the old words until new lists are
built after deploy. `GET /api/desk/paper-trades` and `GET /api/suggestions` were not called (they write).

## Changes per area (git diff origin/dev...HEAD)

| Area | Files | Lines changed (+) |
|---|---:|---:|
| Backend · copilot_agent prompts + compliance node | 11 | 90 |
| Backend · copilot_visual builders | 7 | 137 |
| Backend · desk / idea / level / risk-gate services | 36 | 221 |
| Backend · routes (desk, prompts, research chart …) | 8 | 79 |
| Backend · suggestions catalog | 1 | 8 |
| Backend · tests (asserted texts + new lint) | 24 | 393 |
| CI allowlist | 1 | 1 |
| Frontend · Playwright specs (asserted texts + new guard) | 34 | 367 |
| Frontend · Trading Desk (screens/tradingdesk, trading, positions, desk, fnolab) | 71 | 521 |
| Frontend · chat components (incl. trade_plan card) | 8 | 29 |
| Frontend · e2e fixtures (strings only) | 4 | 558 |
| Frontend · rest of the Copilot app (portfolio, workspace, markets, Daily Trader, shell …) | 37 | 169 |
| Test cases / report | 1 | 2119 |

Candidate strings (TypeScript-compiler / Python-ast extraction, comments excluded): frontend scope 805 user-visible candidates on dev → 48 left, all non-trading senses (Stop generating, exit load, Suggested questions, endpoint paths); backend scope 469 hits → 257 left, all identifiers, question regexes, SQL / OpenAPI text or prompt lines that forbid the words.

## Wordings without a clean equivalent (for the owner)

- Desk: "Ref price" / "C REF PRICE" / "F REF PRICE" / "REWARD 1" chart pills (space); "Long above" (plain chart word); "Pending openings" / "1 opening pending"; Journal "Opening" row, "when opened"; "Reference-price rule" / trader "Opening rule" (was Entry rule); investor "Closed at the raised risk level" (was Locked-in exit); "At the current price" (was Buy now); DecisionCard "Ready for a paper trade"; "a close at the risk level may fill well beyond it"; "evening check" (was exit check); "Short-side idea: no new longs in this view" (was "Avoid new longs").
- Flows / deals: "How easy to turn into cash" (was days to sell), "Client · purchase / sale", "acquired / disposed of", "Who is raising and cutting holdings".
- Portfolio: plan verbs "Close out", "Lower holding in", "Lower weight in", "Raise weight in", "Invest in" (pills CLOSE OUT / LOWER / RAISE / INVEST), "All at once" (was Sell now), "Engine flag: close" (was Exit signal), "Planned mix" / "Above / Below plan" / "no planned share" (was target mix), "Purchase price", "realised lots", "Closed at", "Portfolio ideas" (was Recommendations), "Holding scores", "Own a home" (was Buy a home).
- Research / chat: "Score reading" with STRONG / NEUTRAL / WEAK (was the BUY / HOLD / SELL stance), score rationales "Fundamentals score N/100: the strong band" (was "suitable to accumulate"), lens chips "Scores today" / "How does it score today?" (was "Worth buying now?" / "Should I buy?") and "How is it valued?" (was "Cheap or pricey?"), event "Positive tone" / "Negative tone" (was Bullish / Bearish), "Selection rules" / "screened portfolio" (Strategy Lab), MF "FITS / REVIEW / DOES NOT FIT" (was CONTINUE / REVIEW / EXIT recommendation), "Illustrative SIP allocation".
- Kept for the owner to decide: "Accumulation" / "Distribution" category names; Bullish / Bearish as the user's own market view and setup direction; "Suggest a hedge" chip.

## Deliberately kept
- API fields / values (`stop_loss`, `target`, `entry`, `side: "BUY"`, `exit_reason` codes, `max_loss_at`, stance values),
  data-testids, keys, comparisons, literal types, file / component names (`TargetMix`).
- Question-recognition regexes; one ADDITIVE pattern for the "Plan a long/short trade … instead" chip (see routing).
- Non-trading senses: Stop generating / Stopped, exit load, Suggested questions / Suggestions, Add (UI verb), Long / Short
  build-up, Buyback, CSV import headers "Buy price" / "Buy date", the model picker's "recommended" tier, broker tariff
  quotes in `services/desk_cost_card.py`, the suggestions engine's "Nothing is suggested" notices.
- "Suggest a hedge" follow-up chip: rewording it re-routes it (recommendation → portfolio_hedge).
- The pre-existing `_ADVICE_RE` scrub (unchanged); no new hard filter on LLM output (owner decision, per the coordinator).

## Rebase and concurrency
Rebased on dev twice (6d30a7f7, then d8cfff7d with #468 / #467). One conflict, resolved: `ChartAnalysis.tsx` legend (dev's new
legend kept, the one string change applied). PR #460 (merged) also edits `copilot_agent/nodes/stock.py`; this branch's
edits there are in the general `_SYSTEM` prompt, outside its research-card block. New dev code from #468 (Scan dashboard
strategy ideas) already follows the rule (its own `BARRED` lint). Two layout widths changed for longer labels (FnoBuilder
side button 44→58 px, BasketPanel level label 90→112 px).

## Out of scope (older non-Copilot v5 pages; not changed) — 515 candidate strings
pages/Research 116, pages/Learn 95, pages/Blog 67, pages/Copilot 58, pages/Chat 25, pages/Dashboard 23, pages/FlowLedger 13,
components/shared 11, pages/StrategyBuilder 11, components/marketing 9, pages/AdvisorDashboard 7, pages/Concentration 7,
pages/Markets 7, components/admin 6, pages/Recommendations 6, pages/Performance 5, and ≤ 4 each in 23 more folders.

## UNVERIFIED
- TC-13: nothing is verified on staging. Needs the merge to dev, the frontend image rebuild and a backend process restart.
- Stored documents keep the wording they were saved with: `ai_watchlist_days`, stored trade plans, paper-trade records,
  decision logs. Only documents built after deploy carry the new wording.
- Trade-plan ids are content hashes that include the plan's texts, so the same setup gets a NEW plan id after deploy.
  Stored plans still validate against their own content (`trade_plan.validate`).
- LLM answers: the vocabulary rule is a prompt rule only (owner decision pending on a hard filter). `wording_hits()` logs
  a count per answer; no live LLM answer was checked.
- `copilot_prompt_catalog_hi.json` (Hindi): 6 "बेच…" (sell), 1 "खरीद/बिक्री" (buy/sell), 1 "अनुशंसित" (recommended),
  3 "सुझाव" (suggest) — not changed (Hindi rewording needs the owner or a translator).

## Verdict
All local checks are green (backend CI allowlist and named suites add no failure; new lint 66/66; tsc 0; guard spec 3/3 on
the branch and failing on dev; Playwright adds no failure). The live staging check (TC-13) needs the merge and deploy.

## Verdict: BLOCKED — the live staging check (TC-13) needs the merge to dev and the deploy (frontend rebuild + backend restart)
