# AI Strategy Copilot PRD: what we reuse, what we change, what we build — inside the existing Strategy Lab

Date: 2026-10-28 · Input: `docs/Nivesh_AI_Strategy_Copilot_Complete_PRD_v1.0.docx` (v1.0) · Code: `origin/dev` @ `48556220`
(what staging runs) · Data: staging warehouse, read-only queries run this session.
Status: **review only. No product code has been changed.** "Exists" below means the code or data is there, not that it is
validated for this PRD.

Owner decision (2026-10-28, ~05:10 IST): **build this into the existing Trade Desk › Strategy Lab, not a new "Strategy
Studio" screen, and cause no regression.**

Evidence (file:line for every claim, SQL with real output) is in the three audit reports beside this file:
[A_definition_layer.md](A_definition_layer.md) (AI interpretation, config, validation, persistence, security),
[B_engine_layer.md](B_engine_layer.md) (backtest engines, options engine, results, jobs, template catalogue),
[C_data_coverage.md](C_data_coverage.md) (what the warehouse actually holds). The key claims were re-checked by hand
(section 9).

---

## 1. Verdict

You are right that most of the **backend parts** exist. What does not exist is the **AI front door** and the
**options backtest loop** that joins those parts.

| Layer | State | One line |
|---|---|---|
| Strategy store, versions, runs, audit | **Reuse + extend** | The Strategy Builder's PostgreSQL tables already have versions that runs point at, owner checks and an audit table. They allow STOCK/MF only. |
| Options legs, templates, payoff, Greeks, costs | **Reuse** | 13 leg templates, exact payoff, Black-76 Greeks and the desk cost card. A missing premium is refused, never guessed. |
| Multi-leg replay on real F&O prices | **Reuse** | `desk_strategy_trades.simulate_strategy` replays 1–4 legs on real bhavcopy prices. It handles stop-first, premium stop/target and expiry settlement. Today it only runs for open paper trades. |
| Equity backtest | **Reuse + fix** | Daily, adjusted prices, costs, slippage, stop-first, provenance. Long-only. It runs inside the web request. |
| Turning a prompt into a strategy (English/Hinglish), clarification, field status | **Build** | No code turns a prompt into a strategy. In chat, "build a strategy" opens a fixed seed. |
| Options/futures **historical** backtest | **Build from existing parts** | No engine backtests a 1–4-leg structure over history. The parts exist; the loop, contract lookup by date, storage and metrics adapter do not. |
| Async jobs (queue, status, cancel, retry, idempotency) | **Build** | Nothing exists. Every run is synchronous and is saved as `'OK'`. |
| Version diff, compare, clone, rename, list versions/runs | **Build (small)** | The data for a diff is already logged in `strategy_audit`. |
| Intraday (15-minute) rules | **Blocked by data** | There are no intraday bars in the warehouse (section 3). |

## 2. Two things to settle before any code

**2.1 A peer session is building Build a trade right now.** Branch `feat/desk-strategy-lab-wizard` (worktree
`/home/deploy/nivesh-desk-wizard`, 3 commits ahead of dev, last commit 28 Oct 04:54) adds:
- the template catalogue with intent and tags;
- `POST /api/desk/paper-trades/check`;
- **`desk_strategy_instances`**, a Mongo store of 1–4-leg structures with append-only versions and clone.

That third piece is the PRD's FR-03 and FR-09 for structures. The Strategy Builder's PostgreSQL `strategy_versions` table is the same idea for rule-based strategies. If both go ahead unchanged, Strategy Lab ends up with two version histories and two "my strategies" lists. A backtest run (PostgreSQL) also could not point at an instance version (Mongo).
**Recommendation:** one store. Make the PostgreSQL strategy tables the home of everything that can be backtested. The wizard's
"Save as new version / Clone" then writes there; the instance code's validation rules (1–4 legs, field allow-lists, caps) move
into the shared config v2 validator. The branch is not merged yet, so this is not a regression. This needs your yes and a
hand-off with that session (decision D1).

**2.2 Two existing behaviours are wrong and must change (they are PRD release blockers, §19.2):**
- **Another user's run can be read.** Any user may backtest a public template, and the run is stored under the
  template. `GET /api/strategy-builder/runs/{run_id}` then returns that run and its full trade ledger to **any**
  signed-in user who has the id. The route checks `strategy_owner` or `is_public_template` and nothing else
  (`backend/routes/strategy_builder.py:1057`). The fix: allow only the strategy's owner or the user who triggered the run
  (`triggered_by` is already stored), and answer 404 otherwise.
- **Failed runs look successful.** A window with no data is stored with status `'OK'` and `metrics.reason = no_data`
  (`backend/services/strategy_engine/backtest.py:342-345, 854`). A real failure leaves no run row at all.

These are the only deliberate behaviour changes in this plan.

## 3. What the data can honestly support (measured 2026-10-28)

| Data | Range | Fit |
|---|---|---|
| Equity daily, raw (`nidp.prices_eod`) | 2024-04-01 → 2026-10-27, 635 sessions; 2,215 symbols ≥12 months, 1,947 ≥24 months | Yes, as the calendar and for raw levels |
| Equity daily, adjusted (`prices_eod_adjusted`) | Same range, but only about 1,200 symbols per session before 2025-10-01; demergers and renames break series | 12 months for nearly all names; 24 months for about 1,230 |
| Index daily (`index_eod`): NIFTY 50, BANK, FIN, MIDCAP SELECT, VIX | 635 / 635 sessions, no gaps | Yes |
| F&O contracts EOD (`fno_bhavcopy`) | **2025-10-01 → 2026-10-27, 263 sessions**; 6 index and 232 stock underlyings; lot size per contract per day (NIFTY 75 → 65) | **About 13 months of options/futures backtests, end of day only** |
| Untraded option contracts | Only 32% of index-option rows and 39% of stock-option rows actually traded; an untraded row's close is yesterday's close carried forward | The engine **must** check that the contract traded before filling at that price |
| Bid/ask, historical Greeks per contract, historical margin | None | Fills are close ± slippage; Greeks are model-derived (Black-76); margin shows "not available" |
| Intraday bars | None (`nidp.intraday_bars` does not exist; collector not scheduled) | **15-minute rules cannot run** |
| Precomputed daily features (`stock_features_daily`) | **Only from 2025-12-29 (204 sessions)**; no rows for indices | The existing engine takes its signal dates from here. **A 12-month backtest, or any NIFTY/BANKNIFTY signal, needs indicators calculated from the price tables** |
| Charges | Code constants (`desk-cost-v2`), today's rates | Applied to history with a visible disclosure |

So the honest MVP is **daily (end-of-day) backtests**:
- **Equity:** from 2024-04-01.
- **Index signals:** from 2024-04-01.
- **Options and futures structures:** 2025-10-01 → today, traded-contract fills only, close ± slippage.

The PRD's own example ("15-minute RSI crosses above 55") gets a clear "intraday rules are not supported yet", plus the daily version as an alternative.

## 4. How the PRD maps onto the existing Strategy Lab (no new screen)

Your design for Strategy Lab already has a place for almost every PRD region:

| PRD region / state (§4.2, §13) | Where it goes in Strategy Lab | Change |
|---|---|---|
| Conversation, empty state with examples | **Build a trade › Step 1** gains a "Describe your strategy" box above the template cards, with examples for stocks, futures, options and mixed; the **Copilot dock** (already docked right on the desk) gets a strategy mode | New prompt box; dock calls the new interpret route |
| Clarification questions | Copilot dock, one question at a time, with editable chips | New |
| Draft / configuration | **Step 2 Configure + Step 3 Review & adjust**. These already have the leg editor, payoff, Net Greeks and Checks. Add a status badge on each field (stated / inferred / default / missing) and an **Entry & exit rules** panel | Additive panels |
| Validation state | Step 3 **Checks**, split into blocking / warning / info, each linked to its field; assumptions to acknowledge before a run | Extend Checks |
| Backtest state and results | **Step 4** summary (coverage badge, status, run id) + **Backtest & validation** view (equity vs baseline, drawdown, ledger, manifest, warnings) | Async status + charts + per-leg ledger |
| Saved strategies, versions, compare | Step 1 "Existing strategies · AI and yours"; Step 4 version list, Save as new version, Clone; compare and diff in Backtest & validation | Version list, diff, compare |

The existing "Build a trade" ticket, the F&O builder, the equity Strategy Builder and its backtest panel keep working as they do now.

## 5. PRD requirement map (summary; details in A and B)

| PRD | Requirement | State | Reuse / change |
|---|---|---|---|
| FR-01 | Prompt → structured fields, Hinglish, field status, keep prompt | Build | Reuse `make_chat_llm` (one provider factory) + forced tool call (pattern in `announcement_classifier`); pydantic/jsonschema already installed. Do **not** reuse `copilot_agents.run_agent_oneshot` (returns a stub that looks like an answer when no key). |
| FR-02 | Capability-driven templates | Partial | Three catalogues disagree (6 DSL, 13 desk, 13 frontend). One server registry with an `enabled` flag per template |
| FR-03 | Typed config, schema version, immutable versions | Partial | Config v2 (legs 1–4 + rule tree) in `strategy_versions.definition`; v1 stays as is; add an immutability trigger. (Considered and not used as the rule base: `services/rules_dsl.py`, the advisor portfolio-rule evaluator. It checks string expressions against an allow-list over flat values, with no time series or crossovers. v2 uses JSON nodes the model can emit and the UI can edit, on the same allow-list principle.) |
| FR-04 | Clarify, never silently default | Build | Today capital ₹10 lakh, commission and max positions are filled in silently |
| FR-05 | Validation | Partial | Reuse strike-order rules, short-call coverage, defined-risk guard, lot check. Add: lot/expiry **as of each historical date**, indicator ranges, contradictions, a terminating exit, coverage preflight, one 4-leg limit (today 4 / 8 / 10 in three places) |
| FR-06 | Historical backtest | Equity: reuse; F&O: build from parts | B §4 design below |
| FR-07 | Metrics | Mostly reuse | Add gross/net/costs split, drawdown duration, largest win/loss, monthly returns, denominator label; profit factor already returns N/A on zero losses |
| FR-08 | Refine in chat, diff, new version | Build | Model returns a JSON patch; the server applies it, validates it and diffs it deterministically |
| FR-09 | Save, load, clone, rename, compare | Partial | Save/load/delete exist; add clone, rename, list versions, list runs |
| FR-10 | Async jobs | Build | Postgres run table + one worker process (`FOR UPDATE SKIP LOCKED`); no new dependency |
| FR-11 | Explain each trade | Partial | Exit reason, fills and stop history exist; persist the signal values and the rules that matched |
| FR-12 | Access control, rate limits, audit | Partial + one gap | Fix run access (2.2); add an interpret rate limit, audit on submit, clone and promote; log denials |
| FR-13/14 | Compare, sensitivity, out-of-sample | Partial | Slippage sweep exists; split helpers exist in `fno_backtest`; the AI Trader's "walk-forward" is fixed-spec folds and must not be labelled walk-forward |
| FR-15 | Paper trading | Exists | Your wizard's Step 4 already ends in a desk paper trade; only link the paper trade to the version |
| §6.2 | 51 templates | 14 reusable, 16 need a leg builder + tests (payoff already accepts them), 10 blocked by the defined-risk rule, 11 unsupported (calendars/diagonals, pairs, short stock, delta hedge) | Ship the defined-risk set first (B §3) |

**Options backtest, smallest credible design (B §4):**
1. Daily signal on the underlying. Index indicators are calculated from `index_eod`; the alternative is calendar entries (e.g. N sessions before expiry).
2. Pick the expiry and strikes from **that day's** chain (`/v1/fno/{U}?on=D`, lot size included).
3. Build the legs with the existing templates. A missing premium or an untraded contract means the trade is skipped and counted, never filled.
4. Replay with `simulate_strategy`.
5. Apply costs with the existing cost breakdown.
6. Reuse the equity engine's metrics through an adapter.
7. Store runs, trades and **legs**.

Size: about 2 weeks, plus the job infrastructure.

## 6. Plan: one PR to dev per row, each gated on no regression

**Regression gate for every PR:**
- the 38-file backend baseline (**1,701 passed** on dev today, [baseline_backend_20261028.md](baseline_backend_20261028.md)) stays green;
- the Strategy Lab and desk Playwright specs stay green;
- new tests are added;
- real staging API checks are run after deploy.

New behaviour sits behind a `strategy_copilot` feature flag (allowlist first). The v1 equity DSL, the existing sync backtest route, desk plans, the AI Trader and the paper desk keep their behaviour; the only exceptions are the two fixes in 2.2.

| # | PR | What | Size |
|---|---|---|---|
| **Phase 0: foundation and safety** | | | |
| 0.1 | Run access fix | Owner or `triggered_by` only; 404 otherwise; log denials; test with two users | S |
| 0.2 | Failed runs are FAILED | Persist `FAILED` + reason for no-data and errors; the UI shows the failure, never metrics | S |
| 0.3 | One 4-leg limit | Shared constant enforced by the server on every Copilot/instance path; release-blocker test | S |
| 0.4 | Baselines | Frontend Strategy Lab spec baseline; golden equity backtest reproduced twice (the PRD's Phase 0 exit criterion) | S |
| **Phase 1: conversational builder** | | | |
| 1.1 | Config v2 + migration | Legs 1–4, allow-listed rule tree (compare, crosses above/below, and/or/not, indicator, price/volume field), field status, prompt, model provenance; widen `asset_class`; immutability trigger | L |
| 1.2 | Validator v2 + template registry | Reuse desk rules; as-of-date contract checks; coverage preflight; problems as `{field, code, message}` | M–L |
| 1.3 | Interpret / refine routes | `/api/strategy-copilot/interpret` and `/refine`; one question at a time; JSON patch + diff; Hinglish eval set (target ≥80% correct on curated prompts, PRD §17.3) | L |
| 1.4 | Strategy Lab UI | Describe box (Step 1), Copilot dock strategy mode, field badges and rules panel (Step 3), Checks split, versions/clone/diff | L (frontend) |
| **Phase 2: historical backtesting** | | | |
| 2.1 | Async runs | Status machine, idempotency, worker, cancel, per-user cap, timeout, progress = sessions done / total | L |
| 2.2 | Indicators from prices | RSI/EMA/SMA/ATR, with crossovers, calculated from `prices_eod_adjusted` and `index_eod` (lifts the 204-session limit; enables index signals) | M |
| 2.3 | Options EOD engine | Section 5 design; per-leg ledger; traded-contract check; provenance incl. contracts read and cost disclosure | L |
| 2.4 | Results UI | Step 4 summary with coverage badge; Backtest & validation charts, ledger with "why this trade", manifest, warnings; opens on the last run | M–L |
| **Phase 3: refinement and comparison** | | | |
| 3.1 | Compare + robustness | Compare runs/versions with differences shown; parameter sensitivity as child runs; in-sample/out-of-sample tags; repeated-tuning warning | M–L |

**Rough total:** about 8–10 weeks of single-developer effort. Parallel agents shorten the calendar time but not the review load. This is an estimate, not a commitment.

## 7. Decisions (owner answered D1–D3 and the Phase 0 start on 2026-10-28 ~05:50 IST, all as recommended)

**Answered:**
- **D1:** one PostgreSQL store; the wizard saves there before its branch merges.
- **D2:** unlimited-loss structures are blocked in MVP backtests.
- **D3:** reuse the app's current LLM provider setting.
- **Phase 0:** start now, including the two behaviour fixes in 2.2.

**Not asked; taken as the stated defaults until the owner says otherwise:** D4 and D5.

| # | Decision | Recommended default | Why |
|---|---|---|---|
| D1 | One strategy store for everything backtestable (PostgreSQL), including the wizard's saved structures | **Yes**: the wizard saves into it before its branch merges | One version history; runs can point at an immutable version (PRD FR-09, §14.4) |
| D2 | Naked short options, short straddle/strangle, ratios, futures-only shorts in **backtests** | **Blocked in MVP**, shown as "disabled: needs a margin model" | There is no historical margin, so these cannot be sized or given a return on capital; it also keeps backtest and paper desk consistent |
| D3 | LLM for interpretation: the PRD says OpenAI; staging chat is set to `COPILOT_LLM_PROVIDER=claude_code` | **Reuse the app's existing provider setting**, record provider and model on every version, fail loudly if none | No second integration; the same model the chat already uses. A code comment also records the OpenAI account as out of credit since 2026-09-18 (`services/event_ai_insight.py:4-5`; current state UNVERIFIED) |
| D4 | MVP scope | **Daily only; options window from 2025-10-01; no calendars/diagonals; return on starting capital (margin "not available"); today's cost card with a disclosure** | These are the data and engine limits in section 3 |
| D5 | Sealed AI Trader research window (2023-01-01..2024-07-31) | Does **not** bind Copilot runs; recorded in provenance | Not owner-critical; the warehouse holds no data before 2024-04-01 anyway |

## 8. Known gaps this plan does not close

- Intraday rules need an intraday bar store (migration 152 is not applied and the collector is not scheduled). That is a separate data project.
- Options history is about 13 months. NSE archives before 2025-10-01 would need a backfill, and the ingester can parse the older format.
- Historical margin, bid/ask fills, Greek-based rules (delta hedge) and pairs are out of scope.
- Corporate-action gaps in adjusted equity prices: demergers and renames break series (e.g. TATAMOTORS shows a false −40% on 2025-10-14).
- `docs/DATABASE_SCHEMA.md` does not describe the strategy tables, and `docs/STRATEGY_BUILDER_CONFIG_SPEC.md` (Python sandbox) contradicts the PRD's "no arbitrary code"; it should be marked superseded.
- `.claude/roles/*.md` role guides referenced by CONTEXT.md do not exist in this checkout.

## 9. What was verified this session, and how

- **Backend regression baseline:** 38 test files run on an `origin/dev` @ 48556220 snapshot in the staging backend image (`--network none`) — `1701 passed, 3 warnings in 96.93s` (re-run: `1701 passed … in 101.64s`).
- **Data (re-run by hand on staging):**
  - `fno_bhavcopy` 2025-10-01 → 2026-10-27, 263 sessions;
  - `prices_eod` 2024-04-01 → 2026-10-27, 635 sessions;
  - `to_regclass('nidp.intraday_bars')` is null;
  - NIFTY futures lot 75 (to 2025-12-30) → 65 (from 2025-10-29).
- **Code (read by hand):**
  - run access check at `routes/strategy_builder.py:1042-1067`;
  - status `'OK'` at `strategy_engine/backtest.py:854`;
  - synchronous `await bt.run_backtest` in the route;
  - `CHECK (asset_class IN ('STOCK','MF'))` at `nidp/migrations/020_strategy_builder_core.sql:31`;
  - `simulate_strategy` at `services/desk_strategy_trades.py:517`;
  - provider order at `nidp/services/copilot_agent/_llm.py:102-119`.
- **Staging backend env:** checked by variable name only, no values printed. `COPILOT_LLM_PROVIDER=claude_code`, `OPENAI_API_KEY` set, `ANTHROPIC_API_KEY` unset.
- **UNVERIFIED:**
  - whether the Claude Code gateway is reachable from staging;
  - whether `stock_features_daily` historical rows were ever rebuilt (look-ahead risk on fundamental columns, B §6);
  - the frontend Playwright baseline (not run yet);
  - whether the research VM holds intraday archives.
