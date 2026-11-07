# Autonomous Trading Desk — design and phase plan (Phase 1 build)

Written 5 Nov 2026 for the owner and the engineers building the desk. Specs: `docs/prd/Nivesh_Autonomous_Trading_Desk_Complete_PRD_v2.0.md`
(PRD) and `docs/prd/Nivesh_Autonomous_Trading_Desk_Technical_Architecture_v1.0.md` (ARCH). Test cases: `TESTCASES.md`.
Code baseline: `origin/dev` 4391cd74.

## 1. Owner decisions (5 Nov 2026)

| # | Decision | Source |
|---|---|---|
| D1 | A **separate application**. It reuses the existing backend code; its UI layer is different and is built from the owner's screen designs. | "We need to create a separate application for this", "so you can use existing codebase", "but the UI layer need to different", "I will provide you the screen designs" |
| D2 | Its records live in an **own Postgres schema `autodesk`** in the staging app Postgres. It reads existing data (warehouse, Mongo) but never writes the existing paper-trading collections. | AskUserQuestion |
| D3 | **Cash + F&O together** in the first release. | AskUserQuestion |
| D4 | Now: docs + plan + **Phase 1 backend** (APIs only). UI waits for the designs. PR to `dev`; the owner merges. | AskUserQuestion |

Standing rules that still apply: brokers are read-only and nothing in this app can place a broker order; product wording
avoids research-advice words in generated text (§9); no stale market data; the AI proposes and code decides.

## 2. Shape of the application

```
backend/autodesk/                 ← its own package; imports backend/services/* (reuse), never the reverse
  main.py                         ← its own FastAPI app: uvicorn autodesk.main:app  (port 8010)
  contracts.py                    ← enums, event envelope, task contract, Signal / TradePlan / RiskAssessment / Approval / Policy
  config.py, store.py             ← settings; repositories (tenant-scoped reads, event appended in the same transaction)
  db/                             ← own asyncpg pool, migration runner, migrations/*.sql (schema autodesk)
  market/                         ← point-in-time market view (no future data), data API adapter
  agents/                         ← the five agents (pure: task + inputs + policy + market view → result)
  control/                        ← deterministic risk engine, sizing, policy evaluation
  orchestrator/                   ← workflows, task runtime (deadlines, retries, validation, handoffs), recovery
  simulator/                      ← simulations, clock, session schedule, results
  routers/                        ← /api/v1/... routes of the new app
backend/tests/autodesk/           ← unit + integration tests (throwaway Postgres)
frontend-autodesk/                ← LATER, from the owner's designs (not in Phase 1)
```

**Same image, different process.** The service runs from the existing backend image (`uvicorn autodesk.main:app`) so it
can import the backend's code; it has its own process, its own connection pool, its own schema and its own URL. Sign-in
reuses the Nivesh session (`deps.get_current_user`), so a user signed into Nivesh is signed into the desk; the tenant is
the Nivesh `user_id`. Deployment wiring (compose service + nginx path) is a separate, later change: an nginx upstream
that points at a container which does not exist yet would stop staging nginx from reloading.

## 3. Architecture choices against the ARCH baseline

The ARCH says "do not adopt every component on day one". Phase 1 choices:

| ARCH recommendation | Phase 1 choice | Why |
|---|---|---|
| Temporal / durable workflow engine | Workflow + task state in Postgres; the orchestrator resumes non-terminal workflows on start | No new infrastructure on a VM with 5.7 GB free disk; state is durable and replayable |
| Kafka / RabbitMQ | `autodesk.events` table = append-only audit log **and** transactional outbox; consumers keep a cursor (`event_cursors`) | Same transaction as the state change; at-least-once consumers come in Phase 2 (SSE, TLM) |
| LangGraph agent runtime | A small controlled runtime (`agents/base.py`, `orchestrator/runtime.py`) | Deterministic agents in Phase 1; LLM narration is a later, flag-gated add-on |
| PostgreSQL system of record | Yes (D2), NUMERIC money, append-only triggers | — |
| Redis | Not used in Phase 1 | Nothing needs it yet |
| TimescaleDB / ClickHouse | Not used; market data stays in the NIDP warehouse, read through its data API | Single source of truth |

## 4. What is reused (and what must never be called)

Read from two code surveys of `origin/dev` (5 Nov). Paths under `backend/services/`.

| Need | Reused | Notes |
|---|---|---|
| Option leg construction, max profit/loss, breakevens, capital at risk | `strategy_plan/templates.py` (long call/put, bull/bear call/put spreads, iron condor, covered call, protective put, collar, futures, cash long) + `strategy_plan/engine.compute_payoff` (`payoff-v2`) | Templates take a bhavcopy chain snapshot; a missing premium raises, never guesses. **No iron butterfly, calendar or diagonal** anywhere in the codebase |
| Greeks / IV | `option_pricing.py` (Black-76: `implied_vol`, `greeks`) | Carried-spot forward ignores dividends |
| Risk estimates | `risk_gate/estimate.py` (`cash_risk`, `structure_risk`, `credit_terms`), `risk_gate/gate.py` (`clean_legs`, `defined_risk_failures`, `structure_capital_at_risk`) | Pure |
| Defined-risk rules | `desk_strategy_trades.check_defined_risk` | Pure |
| Costs | `desk_cost_card.py` (`desk-cost-v2`: equity delivery / futures / options) | No intraday segment |
| Default limits | `risk_profile.OWNER_DEFAULT` (0.5 / 3 / 10 / 25 / 2 / 4 / 10 / 1.5) | Policy defaults (D: SPT decision 2) |
| Regime | `macro_engine.classify_desk_regime` (`desk-regime-v1`) | Pure; inputs computed point-in-time |
| OI build-up labels | data API `GET /v1/desk/fno-buildup?date=` + `fno_oi_windows.buildup_label` | Date-parameterised (point-in-time) |
| Market data | `copilot_tools/daas_client` (`_get`, `strategy_creds`) → NIDP data API | The app VM cannot reach the warehouse by SQL |
| Exit rules (Phase 3) | `exit_rules.py` (`trail-atr-v1`, `trend-ema-v1`) | End-of-day bars only; stop wins a same-bar tie |
| Paper fills (Phase 2) | `spt/paper/execution.simulate` | Equity delivery only; needs lot rounding + options |

**Never called from autodesk** (they write existing paper data): `risk_gate.service.enter/gather/enforce`,
`risk_book.read` (writes `paper_accounts.equity_peak_rs`), `plan_sizing.size_for`, `spt.allocation.account_state`,
anything writing `paper_accounts`, `paper_account_ledger`, `desk_paper_trades`, `risk_decisions`, `spt_*`.
Test AD-91 enforces this statically. The existing universal risk service's `decide()` is pure but needs a hand-built
21-key snapshot and hard-codes the 80% exposure / 10 positions governor and the existing PATHS, so the desk has its own
risk engine built on the pure helpers above, with the same check names where they mean the same thing.

**Order-path guard.** `tests/test_order_path_guard.py` fails on any call named `place_order` / `modify_order` /
`cancel_order` (and the GTT variants) outside `services/oms/adapters/`. The Phase 2 execution gateway therefore uses
`submit` / `amend` / `withdraw` names and has only paper and shadow adapters. `LIVE_EXECUTION_AVAILABLE` stays False.

## 5. Market data facts that shape the desk

- Cash end-of-day (`nidp.prices_eod`, raw bhavcopy): 2024-04-01 → today. F&O bhavcopy: 2025-10-01 → today (≈261 sessions).
- `prices_eod_adjusted` is **back-adjusted** (later splits rewrite earlier bars): look-ahead in a replay. The desk reads raw
  bars and adjusts as of the view's date (factor ratio anchored at or before as-of).
- Index membership has 4 snapshots (Oct 2026): using it for 2025 is survivorship bias. **Default universe = F&O stocks
  traded the previous session** (point-in-time). Index lists are allowed with a survivorship caveat in the results.
- F&O eligibility history (`security_reference_daily`) starts 2026-10-12; before that, the stock futures present in the
  bhavcopy that day define eligibility. Lot size = the bhavcopy's `new_board_lot_qty` that day.
- The bhavcopy carries the previous close forward for contracts that did not trade: a leg needs `traded_volume > 0`.
- Minute history: ~10 days in Mongo `kite_live_minute`, indices/futures/ATM index options only, no cash stocks. So the
  Phase 1 replay is **daily** (decisions before the open on the previous session's data). Intraday replay waits for
  stored intraday history.
- `index_eod` is dense only from 2026-02-06 (relative strength and regime inputs are "unavailable" before that, never
  zero-filled into a positive score).

**Publication rule (no future data).** Cash EOD for session d is visible from d 19:30 IST, F&O EOD from d 22:45 IST (after the real loads: cash about 19:00,
F&O about 22:15 IST; changed from 18:30 / 19:30 on 7 Nov after a cycle at 18:50 IST found no cash file yet).
A read for a later session raises `LookAheadError`. Every read is recorded on the task (tool calls), so AD-72 can prove
it from the stored evidence.

## 6. Phase 1 scope (PRD Phase 1 + simulator S1)

PRD Phase 1 exit: "Agents collaborate on a signal-to-proposal workflow with traceable outputs and no order execution;
a simulation run can be created and replayed at workflow level." Phase 1 here goes one step further, to the Middle
Office decision (simulator S1 exit: "a traceable strategy proposal and approval workflow"). **No orders, no fills, no
positions, no capital reservation** — those are Phase 2.

### 6.1 Agents (all deterministic in Phase 1; versions pinned per task and per simulation)

| Agent | Task types | Phase 1 behaviour | Tools (market view methods) |
|---|---|---|---|
| Tech Support `autodesk-ts-v1` | PREMARKET_HEALTH_CHECK | Checks the previous session's cash and F&O data exist and are fresh, the data API answers, the desk DB answers. "Fresh" = the data is for the session immediately before the one being prepared (`previous_session`). READY / DEGRADED (F&O missing, too few, or not for that session → cash only) / BLOCKED (no cash data, or cash older than that session → no new risk) | latest_session, previous_session, day_snapshot, fno_universe, vix |
| AI Trader `autodesk-ait-v1` | SCAN_MARKET | Scans the universe on the previous session's data: breakout / breakdown, trend continuation, momentum, unusual volume and delivery, OI build-up (long/short build-up, short covering, long unwinding), Nifty/Bank Nifty trend or range. Scores 0–100 on the PRD's 8 dimensions with versioned weights; missing inputs earn 0 and are listed; a score is not a probability (`calibrated_probability` stays null). Dedupes. | all read tools |
| Trading Assistant `autodesk-ta-v1` | GENERATE_STRATEGY, REVISE_STRATEGY | Builds cash / futures / option alternatives from the existing templates on the previous session's chain, ranks them (reward:risk, loss within budget, liquidity), returns the top as a 19-field plan or NO_TRADE with reasons. Revises on risk violations (smaller size, then the next alternative). | daily_bars, futures, options, expiries, lot_size, vix, sector |
| Risk & Operations `autodesk-risk-v1` | ASSESS_RISK | Runs the deterministic risk engine (§6.2) on the exact plan version against the account book. | daily_bars, lot_size, sector |
| Middle Office `autodesk-mo-v1` | REVIEW_FOR_APPROVAL | Applies the approval policy: needs a PASS assessment of the exact version; ASSISTED → needs a person; AUTONOMOUS_PAPER → approves inside the autonomy rules, else needs a person. Binds scope (tenant, account, trade, version, instrument, strategy, max lots/notional/risk, mode, actions) and expiry (session close). | none |

### 6.2 Risk engine checks (`autodesk-risk-v1`)

inputs_fresh · account_active · strategy_allowed · segment_allowed · legs_valid (≤ 4 legs, lot multiples, lots/leg cap) ·
defined_risk (hard: no naked short option, no unbounded loss except futures with a stop) · expiry (≥ min days, never
same-day) · liquidity (ADV ≥ ₹1 cr; traded legs) · per_trade_risk (loss at invalidation incl. costs ≤ 0.5% equity) ·
reward_risk (directional ≥ 1.5) · credit_terms (credit structures: net credit after costs ≥ width/3) · position (notional
or margin ≤ 10% equity) · open_risk (with this plan + other APPROVED, unexpired plans ≤ 3%) · sector (≤ 25%) ·
margin_utilization (estimated margin incl. pending ≤ 25%) · daily_loss / weekly_loss / drawdown (SKIPPED until Phase 2
has P&L). Verdict PASS / REDUCE (smaller size passes; the allowed lots are returned) / FAIL. Every check, input
snapshot, policy version and engine version is stored.

Loss figures: cash and futures use the **loss at the invalidation level** (owner rule 30 Oct: never "stock to zero"),
plus costs and the existing 1% gap stress; futures are marked `loss_defined = false`. Option structures use the exact
payoff maximum loss plus costs. Margin for futures is an **estimate** (policy `futures_margin_pct`, labelled), not SPAN.

### 6.3 Workflows

- **SESSION_CYCLE** (per account per session): PREMARKET_CHECK → if BLOCKED stop (no new risk) → MARKET_SCAN → for the
  top N signals (policy `max_proposals_per_session`, score ≥ `min_signal_score`, one per instrument) a child
  TRADE_PROPOSAL.
  A desk cycle that ended BLOCKED before any scan produced nothing, so it does not use up the session: a new request
  opens `…:cycle:attempt-2`, `:attempt-3`, … and the earlier workflows stay for the audit. COMPLETED, RUNNING and
  FAILED cycles, and every simulation cycle, stay idempotent.
- **TRADE_PROPOSAL**: GENERATE_STRATEGY → ASSESS_RISK → (FAIL/REDUCE: REVISE_STRATEGY → ASSESS_RISK, at most 2
  revisions) → RESEARCH mode: plan RESEARCH_ONLY, end · otherwise REVIEW_FOR_APPROVAL → APPROVED (Phase 1 outcome
  `APPROVED_NO_EXECUTION`) / NEEDS_HUMAN_APPROVAL (workflow WAITING_HUMAN until `POST /approvals/{id}/decision`) /
  REJECTED. An unresolved disagreement ends in NO_TRADE; a hard FAIL is never voted away.
- Every task is persisted before dispatch, moves CREATED → ASSIGNED → ACCEPTED → RUNNING → RESULT_READY → VALIDATED →
  COMPLETED, has a deadline and bounded retries (timeout / invalid output → RETRY_PENDING; exhausted → ESCALATED), and
  each downstream task records a handoff in the same workflow.

### 6.4 Simulator (S1)

`POST /simulations` creates a simulation and its own SIMULATION account (isolated by `simulation_id`; desk lists never
show simulated rows). The clock steps through each session's schedule — PREMARKET 08:30, SCAN 08:45, PROPOSALS 09:00,
OPEN 09:15, CLOSE 15:30, EOD 18:00 IST — and runs the workflows due at each step with a market view bound to the sim
time. Controls: start, step (one phase / one session), run to the end (accelerated), pause, resume, stop. EOD expires
unused signals and unanswered approvals. Results state data coverage, versions and limitations (daily data, no fills
in Phase 1, survivorship caveat for index universes). Modes in Phase 1: HISTORICAL_REPLAY and ACCELERATED_REPLAY.
SCENARIO is Phase 3; LIVE_SHADOW is Phase 4.

### 6.5 Phase 1 APIs (`/api/v1`, all signed in, all tenant-scoped)

`GET desk/status` · `POST|GET accounts`, `GET accounts/{id}`, `POST accounts/{id}/mode` · `GET policies`,
`GET policies/{id}`, `POST policies/{id}/versions` (a user may tighten; loosening past the defaults needs an admin) ·
`GET agents`, `GET agents/{key}/activity` · `POST desk/workflows` (SESSION_CYCLE | TRADE_PROPOSAL), `GET desk/workflows`,
`GET desk/workflows/{id}` (tasks + handoffs; the list returns the newest first) · `GET signals`, `GET signals/{id}` · `GET trade-plans`,
`GET trade-plans/{id}` (`?version=`), `GET trade-plans/{id}/versions`, `POST trade-plans/{id}/validate` ·
`POST risk/assessments`, `GET risk/assessments/{id}`, `GET risk/portfolio/{account_id}` · `GET approvals` (`?pending=1`),
`GET approvals/{id}`, `POST approvals/{id}/decision` · `GET events` (timeline; `after_seq` is a cursor read oldest-first from it, without it the newest rows) · `POST|GET simulations`,
`GET simulations/{id}`, `POST simulations/{id}/{start|step|run|pause|resume|stop}`,
`GET simulations/{id}/{timeline|workflows|agents|results}`.

Not in Phase 1 (later phases): execution intents, orders, lifecycle, reconciliation, capital reservations, scenarios,
speed, restart-from-checkpoint, compare, SSE stream.

## 7. Phase plan after Phase 1 (each phase = its own PR)

| Phase | Adds | Reuses | Exit |
|---|---|---|---|
| 2 Risk-to-paper | capital ledger + atomic reservation (row lock), execution intents, gateway (`submit/amend/withdraw`), paper adapter (bid/ask from close ± spread proxy on daily data, partial fills by volume share, latency, rejections, desk-cost-v2 charges), order/fill ledger, journal | `spt/paper/execution` model, `desk_cost_card` | an approved plan fills in an isolated simulation with correct reservation and audit |
| 3 Lifecycle + full day | TLM (activate on fills only; stop/target/trailing; partial exits; multi-leg legs), daily P&L, daily/weekly loss + drawdown checks live, scenarios (gap, vol spike, partial fill, leg rejected, stale data, agent timeout), checkpoints, run comparison | `exit_rules`, `trade_lifecycle` ideas, `option_pricing` | five agents through simulated days with injected failures, reconciled closure |
| 4 Live shadow | live view from the Kite feed (`kite_live_feed`), hypothetical book, outcome comparison | `routes/live_quotes`, `day_quote` | shadow runs with no order capability |
| UI | the owner's screens in `frontend-autodesk/` | — | per the designs |

Live broker execution is out of scope (owner rule: brokers read-only).

## 8. Verification plan

- Unit + integration tests in `backend/tests/autodesk/` against a throwaway Postgres container (never the shared one).
- Real-data run on staging: the service code runs inside the staging backend container (real data API, real Mongo
  sessions) with its records in a **throwaway** Postgres attached to the staging network, then the container is removed.
  This proves the APIs on real market data without writing anything shared. Creating the `autodesk` schema in the shared
  staging Postgres happens only after the owner merges (the service applies it on start).
- Report: `test_reports/autodesk_phase1_<ts>.md`.

## 9. Words

API field names follow the PRD (entry, stop, targets). Generated narrative text (thesis, rationale, risk warnings,
task summaries, reasons) uses neutral words — "plan level", "invalidation level", "upper level", "long/short leg",
"open / close the position" — and never: buy, sell, stop loss, SL, target, entry, exit, accumulate, book profit,
upside, price target, recommend, pick (owner rule 3 Nov). AD-92 lints agent outputs. The owner allowed the standard
words on the paper-trading screens; whether this app's screens may use them is an open question (§10, Q5).

## 10. Open decisions for the owner (PRD §26 and new)

1. PRD §26 Q9 — first-release F&O strategies. Default here: long equity, long futures, long call/put, bull/bear debit
   spreads, bull put / bear call credit spreads, iron condor. Short futures off (as in the existing risk gate). Covered
   call / collar / protective put need holdings (none in a simulation account). Iron butterfly, calendar, diagonal: no
   code exists yet.
2. PRD §26 Q10 — which actions run autonomously. Default: AUTONOMOUS_PAPER auto-approves plans ≤ 0.5% equity risk,
   signal score ≥ 70, from the autonomy strategy list; anything else waits for a person.
3. PRD §26 Q3 — default limits: the risk-profile defaults above, margin utilisation 25%.
4. LLM use by the agents (thesis narration, natural-language objectives): which provider? The staging gateway shares
   the dev Claude login (5-hour limit). Phase 1 makes no LLM call.
5. Screen wording for this app: standard words (entry / stop / target) as on paper trading, or neutral words?
6. URL for the app: a path on staging (`/autodesk/`, shares the sign-in cookie) or a subdomain?
