# Functionality Verification Report — Copilot chat defects found in the 30 Oct Daily Trader audit (6 fixes)

- **Branch:** fix/copilot-chat-p0 (from origin/dev a4294830), worktree /home/deploy/nivesh-wt-dtc-p0
- **Date:** 2026-10-30
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** pytest in the backend image (no network); Playwright on a production build (mocked APIs);
  read-only in-process checks inside the running staging backend container
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The 30 Oct read-only audit of the Copilot chat (`A_chat_routing.md`, `E_suggestions.md`, `D_portfolio_hub.md`) found
six defects that give the user a wrong or missing answer today. Each is an independent fix, its own commit, with its
own tests authored before the change:

1. **Compliance never reached the user.** `stream_chat` streamed and saved the raw LLM tokens; the compliance node's
   edits (the advice-wording scrub, the grounding caveat, the 400-word cap) were applied only when nothing had
   streamed. Fix: the `done` frame's text, and the saved message, now carry the compliance-edited text (an empty
   edited text keeps the streamed draft). Prompts that used wording the scrub removes ("Verdict — BULLISH / BEARISH")
   were reworded instead of weakening the scrub.
2. **Generic trader questions routed to "Which stock?".** `_P_STOCK` matched case-insensitively, so "What are my open
   trades doing?", "How much should I risk?", "What did I learn…", "What should I avoid today?" all matched as a
   ticker question. Fix: the ticker-shaped token is case-sensitive, and the any-case form only routes to the stock
   analyst when the symbol resolver actually finds a stock in the message.
3. **Trading words read as stock symbols.** The resolver's pass-through step accepted any upper-case token, so in the
   Trader persona "F&O", "GIFT", "PCR", "P&L", "IV", "OI", "ATM", "VIX"… became "symbols", a trade plan was built for
   them, and the turn was pinned to the stock analyst. Fix: a stop-list of trading/index/market words, plus a check
   against the loaded NSE symbol master for anything else.
4. **Suggestions invented personal figures.** A user with no holdings was shown "Equity 0% · Debt 0%" and "Debt gap —
   only 0%" as fact cards. Fix: the allocation scorers give no badge without a real asset mix, and Home shows badged
   prompts as fact cards only with a portfolio.
5. **Home's insight cards were dead.** `GET /api/insights` answers a bare list; the v5 frontend contract expected
   `{insights: […]}` and threw. Fix: the v5 adapter reads the list the route (and the legacy app) actually returns.
6. **The scheduled jobs ran once per uvicorn worker.** Staging runs 4 workers, each starting its own scheduler, so
   the 17:30 broker sync (and every other job) ran ~4 times at once. Fix: an exclusive, non-blocking file lock elects
   one process to run the jobs; the others log and skip. `stop()` now releases that lock even if `AsyncIOScheduler
   .shutdown()` raises (its own event loop can already be gone), so a restarted worker can always take over.

## Test Cases
> Authored up front, alongside each fix (see each commit for its own test list).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-CP1 | 1 | The `done` frame's text after an answer that needed the scrub | e2e | The checked text, not the raw stream | PASS |
| TC-CP2 | 1 | An answer the scrub does not change | e2e | Stays exactly as streamed (no re-render jump) | PASS |
| — | 1 | `test_chat_compliance_delivery.py`: a real `compliance_node`, the `done` frame and the saved message | unit | Both carry the compliance output | PASS |
| — | 2 | `test_intent_routing.py`: the owner's generic questions ("What are my open trades doing?", "How much should I risk?", "What did I learn from today's trades?", "What should I avoid today?") | unit | Do not route to `stock_analyst` | PASS |
| — | 2 | Real stock questions (INFY, lower-case tcs, a company name) | unit | Still route to `stock_analyst` with the right symbol | PASS |
| R-1 | 2 | The fixed router + resolver run in-process against real staging data | api (read-only) | Same split, on the real NSE symbol master | PASS |
| — | 3 | `test_copilot_trade_idea.py` TI-13: twelve trading-word questions give no symbol; real stocks still resolve; a non-master symbol gets no plan; the Trader F&O question is not pinned | unit | As stated | PASS |
| TC-CP3 | 4 | Badged prompts with no portfolio | e2e | Not shown as fact cards | PASS |
| — | 4 | `test_copilot_prompt_badges.py`: every universal scorer on an empty context | unit | No badge; real figures on a real context unchanged | PASS |
| TC-CP4 | 5 | The first two saved insights on Home | e2e | Rendered as cards | PASS |
| — | 5 | `test_insights_list_contract.py`: the real `generate` + `GET` routes, compared with the shared fixture | api (in-process) | Contract matches | PASS |
| LS-1 | 6 | The first process to start | unit | Runs all 14 scheduled jobs | PASS |
| LS-2 | 6 | A second real process already holding the lock | unit (subprocess) | No jobs start here; `status()` says why | PASS |
| LS-3 | 6 | `stop()` | unit | Releases the lock for the next process | PASS |
| RG-1 | all | Full backend CI allowlist, branch vs `origin/dev` | regression | Identical failing-test set (no new failure) | PASS |
| RG-2 | all | `tsc --noEmit`, `copilot-app.spec.ts` | regression | Clean / all pass | PASS |

## Tests run (real output, 2026-10-30)
- **Targeted suites:**
  `pytest tests/test_chat_compliance_delivery.py tests/test_intent_routing.py tests/test_copilot_trade_idea.py
  tests/test_copilot_prompt_badges.py tests/test_insights_list_contract.py tests/test_mf_scheduler_leader.py
  tests/test_desk_copilot_prompt.py` (backend image, no network) → `302 passed, 1 skipped in 8.64s`.
- **Full CI allowlist, this branch:** `pytest -q -p no:cacheprovider <282 allowlisted files>` (research/ mounted, as
  `test_rs63_readiness.py` needs it) → `17 failed, 7318 passed, 34 skipped in 223.22s`.
- **The same allowlist on an unmodified `origin/dev` checkout** (`/tmp/dev-baseline`, same command) → `17 failed, 7158
  passed, 33 skipped in 249.88s`.
- **Diff of the two FAILED lists → identical**, byte for byte:
  `test_cas_api_client.py::test_sandbox_parse_and_map/test_convenience_helper_returns_list`,
  `test_chartink_desk.py::test_cron_and_installer_files`, `test_decision_cards.py::test_be7c_…`,
  `test_desk_exit_job.py::test_ej13_…`, `test_desk_redesign_routes.py` ×5, `test_fno_forward.py::test_the_recorder_is_scheduled_after…`,
  `test_fno_iv_history.py::test_the_documented_schedule_runs_after…`, `test_move_odds_diagnostics.py::test_tc39_…`,
  `test_move_odds_filing_analysis.py::test_tc10_tc11_…`, `test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches`,
  `test_watchlist_fno_chain_expiry.py::test_c1_…`. **No new failure; 160 more tests pass** than the dev baseline (4 new
  suites plus new cases this branch adds to `test_intent_routing.py` and `test_copilot_trade_idea.py`).
- **CI allowlist file:** `.github/workflows/backend-tests.yml` updated with the 4 new suites
  (`test_chat_compliance_delivery.py`, `test_copilot_prompt_badges.py`, `test_insights_list_contract.py`,
  `test_mf_scheduler_leader.py`), so GitHub's own CI run covers them too.
- **Frontend:** `tsc --noEmit` → exit 0. `playwright test copilot-app.spec.ts` (production build, mocked APIs) →
  `28 passed (19.2s)`, including TC-CP1 … TC-CP4.
- **Real-data router check (R-1), read only:** the fixed `intent_patterns.match_agent` and `symbol_resolver
  .resolve_symbol`, loaded from this branch, run in-process inside `nivesh-staging-app-backend` against the real NSE
  symbol master, no DB write, overlay removed afterward:
  ```
  'How much should I risk?'                    -> agent=None   (was: stock_analyst, "Which stock?")
  'What are my open trades doing?'              -> agent=None   (was: stock_analyst, "Which stock?")
  'What should I avoid today?'                  -> agent=None   (was: stock_analyst, "Which stock?")
  "What did I learn from today's trades?"       -> agent=None   (was: stock_analyst, "Which stock?")
  'Which are today's top 5 opportunities?'      -> agent=None
  'Which F&O setups are attractive?'            -> agent=None   (F&O no longer resolves as a symbol)
  'What is INFY trading at?'                    -> agent=stock_analyst  symbol=INFY   (real stock, unaffected)
  'how is tcs doing'                            -> agent=stock_analyst  symbol=TCS    (lower-case ticker now resolves)
  'Plan a breakout trade for infosys'           -> agent=stock_analyst  symbol=INFY   (company name, unaffected)
  'Is this stock a buy now?'                    -> agent=stock_analyst  (unchanged: "this stock" still asks which one)
  ```
  `agent=None` means the regex router defers to the LLM classifier (the intended path for a generic question), not
  the hard-coded "Which stock?" reply.

## Not verified
- **A live, signed-in `/api/chat/stream` session on staging** for TC-CP1/TC-CP2/TC-CP3/TC-CP4 and for the trade-idea
  pin (fix 3) end to end through the real route. The Playwright specs cover the same frames with mocked APIs; the
  in-process checks cover the real data the fixes read. A live walk needs a staging session token.
- **The scheduler lock under the real staging deploy** (4 uvicorn workers, a real job tick). LS-1…LS-3 reproduce the
  concurrency with real separate OS processes and a real `fcntl` lock, which is the mechanism itself, not a staging
  rehearsal. After the merge and deploy, `nidp.job_log` (or the app's own job log) should show each scheduled job
  logged once per tick, not four times, at the next run.
- **The dead-insight-cards fix (5) on real saved insights.** The contract test proves the route and the adapter now
  agree; seeing real cards on Home needs a signed-in user with saved insights.

## Verdict: BLOCKED
