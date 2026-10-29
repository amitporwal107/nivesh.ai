# Audit A: strategy definition, conversation, persistence and security layer

**PRD:** Nivesh AI Strategy Copilot v1.0 (28 Oct 2026). **Code audited:** a snapshot of `origin/dev` @ `4855622005368e8ea0d1da4127ec4b43f7c1256e` (the DEV_SHA file). Paths are relative to the snapshot root.
**Method:** I read the files and grepped them. I ran nothing against staging, so every runtime claim below is marked UNVERIFIED. I read no secrets.

Status legend:
- **REUSE**: works for the PRD as it stands.
- **MODIFY**: the code exists but needs changes.
- **PARTIAL**: some of the requirement exists.
- **MISSING**: nothing exists.

Size legend: S is 1 day or less, M is 2–4 days, L is a week or more.

---

## 1. Requirement-by-requirement map

### FR-01 Natural-language interpretation (P0)

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-01a | Parse an English prompt into underlying, asset class, template, direction, legs, indicators, entry/exit, timeframe, sizing, risk and dates | **MISSING** | No code path turns natural language into a strategy config. `validate_strategy` has only two non-test callers: `backend/routes/strategy_builder.py` and `backend/services/ai_trader/strategy.py:258,396`. In chat, "build a strategy" sends a fixed seed `{"universe": {"type":"index","ref":"NIFTY500"}}` and makes no LLM call (`backend/nidp/services/copilot_agent/nodes/recommendation.py:462-465`). The copilot "backtest" node uses regexes to parse an amount, periods and a basket for a lump-sum/SIP what-if (`backend/services/copilot_tools/backtest.py:92-134`). It does not parse rules. | Build `services/strategy_copilot/interpret.py`. It calls the LLM with a forced tool / JSON schema generated from the v2 config model (see FR-03a). The deterministic validator checks the output before anything is shown as runnable. Add a new intent to `nodes/intent_patterns.py` (or a standalone route) so chat can reach it. | L |
| FR-01b | Hinglish | **MISSING** | `backend/routes/copilot_prompt_catalog_hi.json` is a list of suggested prompts machine-translated into Devanagari. Its header says `"engine": "google"` and `"requires_review": true` (lines 3-4). No Python or frontend file loads it: grep for `catalog_hi` finds nothing. The intent regexes are English only (`intent_patterns.py:349-355`). | Handle Hinglish in the interpretation prompt, not with regexes. Build a curated Hinglish/romanised-Hindi eval set to measure the PRD §17.3 target of 80% correct interpretation. | M |
| FR-01c | Mark each field explicit / inferred / defaulted / missing | **MISSING** (precedent exists) | The backtest response already labels where each resolved value came from: `starting_capital_source: request\|strategy_config\|default` (`strategy_builder.py:1028-1038`). | Add a `field_status` map to the interpret output and persist it with the version. | S |
| FR-01d | Keep the original prompt | **MISSING** | `strategy_versions` has no prompt column (`backend/nidp/migrations/020_strategy_builder_core.sql:44-54`). Today the prompt lives only in Mongo `chat_messages` (`routes/chat.py:1567`), with nothing linking it to a strategy. | Add `source_prompt`, `conversation_ref` (chat `session_id` + message id) and `model_provenance` JSONB columns to `strategy_versions`. | S |

### §14.1 AI orchestration

**Requirement:** "OpenAI integration with configured fallback; structured outputs and schema validation."

**Status:** PARTIAL.

What exists:
- **One model factory, `make_chat_llm`** (`nidp/services/copilot_agent/_llm.py:161-203`).
  - It picks the provider in this order: Anthropic → Claude Code gateway → Groq → OpenAI. Environment variables decide which is used (`_llm.py:102-119`).
  - The default Anthropic model is `claude-opus-5-5` (`_llm.py:21`).
- **Copilot nodes ask for free text,** not structured output (`nodes/backtest.py:95-100`: `llm.ainvoke` then `text_of`).
- **A structured-output pattern exists,** but only for the OpenAI wire format (OpenAI or Groq): a forced function call followed by validation of the values (`nidp/services/announcement_classifier/classifier.py:116-140, 240-260`).
- **Safety pieces worth reusing:**
  - A PII guard wraps every SDK call and fails closed (`services/llm_guard.py`; installed at `server.py:175-176`).
  - `wrap_user_input` delimits user text and caps it at 8,000 characters (`services/llm_safety.py:28, 211-224`).
- **Do not reuse `services/copilot_agents.run_agent_oneshot`.** When the key is missing it returns a stub string that looks like an answer (`copilot_agents.py:259`). That is the "mock passed off as real" failure the PRD forbids.

**What to change:**
- Reuse `make_chat_llm` and use structured output (tool calling) on the active provider.
- Validate the output with pydantic / jsonschema. Both are already dependencies: `jsonschema==4.26.0` and `pydantic==2.12.5` (`requirements.txt:84,146`). No new dependency is needed.
- If no provider is configured, fail loudly.
- Store provider, model and prompt version with every interpretation.

**Size:** M.

### FR-02 Template selection (P0)

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-02a, §6.2 | Canonical template catalogue, enabled only when data and engine support it | **PARTIAL** | There are three separate catalogues and none carries capability flags. (1) 6 stock DSL "factor" templates in `services/strategy_engine/templates/*.json`, served raw by `strategy_builder.py:155-174`. (2) 13 desk leg templates (long call/put, 4 verticals, iron condor, covered call, protective put, collar, long/short future, cash long), each with legs, risk text, params and a `calculation_version` (`services/strategy_plan/templates.py:194-257`; GET `/api/desk/strategy/templates` at `routes/strategy_plan.py:74-82`). (3) A frontend-only list of 13 that includes straddle, strangle, butterfly, short call and short put, which the backend catalogue lacks (`frontend-v5/src/pages/CopilotApp/screens/tradingdesk/FnoBuilder.tsx:39`). About 25 PRD templates are missing: straddle/strangle on the backend, calendars, diagonals, synthetics, cash-and-carry, pairs, butterflies, ratios, ladders, strap/strip, iron butterfly, box, double calendar and the mixed portfolios. | Build one server-side registry. Each entry holds canonical legs, strike/expiry constraints, the capabilities it needs (option-chain history, multi-leg engine) and an `enabled` flag computed from those capabilities. Seed it from the desk `CATALOG`. Make the frontend read it. | M (registry), L (full §6.2 list) |
| FR-02b | Map a prompt to a template | **MISSING** | AI Trader picks a template from the market regime only (`services/ai_trader/strategy.py:60, 236-246`). | Part of FR-01a. | — |
| FR-02c | Unsupported requests must not compile to executable rules | **PARTIAL** | The DSL validator gives a pass to things that later fail at run time. It accepts the unwired namespaces fundamental, shareholding, institutional and mf (`dsl.py:71-74, 301-305`), which the evaluator then refuses (`evaluator.py:66-67`). It does not check `compare_to` (`tests/test_strategy_engine.py:177`). It ignores unknown top-level keys instead of refusing them (`dsl.py:145-199` reads only named keys), so a `legs` array of any length is saved and silently ignored. | Tighten validation: refuse unknown keys (additionalProperties false), unwired namespaces and unknown `compare_to` fields. | S |

### FR-03 Structured configuration (P0)

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-03a, §8 | Typed, machine-readable config independent of the UI | **PARTIAL** | DSL v1 (`services/strategy_engine/dsl.py:8-28`) covers STOCK and MF only, daily bars only, with no legs, timeframe or instrument type. The database enforces `CHECK (asset_class IN ('STOCK','MF'))` (`020_...sql:31`) and the route repeats it with pattern `^(STOCK\|MF)$` (`strategy_builder.py:68`). A typed leg model exists separately (`services/strategy_plan/model.py:64-113`), but its legs are concrete: a fixed expiry date, strike and entry price, not rules. | Define config v2 to match PRD §8: pydantic models for strategy-level fields, `legs[1..4]` and an entry/exit expression tree. Keep DSL v1 as the compile target for stock-only strategies. Add a migration that widens `asset_class` (FNO / MIXED). | L |
| FR-03b | Schema versioning | **PARTIAL** | The document's `version` must equal `"1"` (`dsl.py:63, 155-159`). A `dsl_version` column exists (`020:49`). Migration shims are only planned, per a docstring (`dsl.py:51-52`). | Add `schema_version` "2". Upcast v1 documents on read. | S |
| FR-03c | Immutable versions | **PARTIAL** (core is reusable) | Every PATCH inserts `version_no+1` and flips `is_active` (`strategy_builder.py:535-553`). Runs carry a foreign key to `version_id` (`020:88`). But immutability is a convention: no trigger stops an UPDATE. The Bot-details `strategy_config` (capital, commission, pyramiding, short margin) is a mutable per-strategy row outside the versions (`backend/migrations/024_strategy_config.sql:44-61`; upsert at `strategy_builder.py:845-859`). Each run does record `starting_capital` and its cost model in `metrics` (`services/strategy_engine/backtest.py:577-578, 611, 743`). | Add a trigger that forbids UPDATE of `definition` and `created_by` on `strategy_versions`. In v2, fold capital, cost and sizing into the version. | S |

### FR-04 Clarification (P0)

**Status:** MISSING.

**Evidence:** There is no clarification loop anywhere. Existing code also fills in values silently in exactly the places the PRD forbids:
- capital ₹10,00,000 and commission 0.05% (`services/ai_trader/config.py:17`)
- `max_positions` 10 (`strategy_builder.py:61`)
- the screen bridge attaches "sensible default exit/ranking/rebalance" (`services/strategy_engine/screen_bridge.py:9-10`)

**What to change:** Keep a policy table of material fields: expiry rule, quantity, exit semantics, fill model, capital and cost model. Each must be explicit or a default the user has acknowledged. `interpret` returns `questions[]` (one at a time) and `assumptions[]`. A backtest submission is refused until every assumption is acknowledged.

**Size:** M.

### FR-05 Validation (P0)

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-05 schema | Schema validation | **PARTIAL** | A pure validator returns path + message pairs (`dsl.py:145-199, 377-378`). The `config-schema` endpoint covers only the four Bot fields (`strategy_builder.py:712-763`). | Generate JSON Schema for v2 from pydantic. Return problems as `{field, code, message}`, the desk's shape (`strategy_plan/model.py:25-26`; `routes/strategy_plan.py:101-103`), so each issue links to a field (PRD §13.3). | S |
| FR-05 operators, §8.3 | Allow-listed, typed expression tree | **PARTIAL** | Reusable: allow-listed numeric and set operators plus a whitelist of feature columns (`dsl.py:76-77, 89-120`), a pure evaluator (`evaluator.py:26-111`), and a SQL compiler that only ever inlines whitelisted identifiers and parameterises every value (`compiler_stock.py:21-25`). Missing: the tree is only flat `all_of` + `any_of` (`evaluator.py:104-111`); there is no nesting, NOT, crossover, previous-bar value, session/time node or timeframe. No raw `high` or `prev_high` feature exists, so PRD example 1 ("closes above yesterday's high") cannot be expressed. | Typed node set: compare, cross_above/below (needs the t-1 value), and/or/not, indicator(ref, params), price/volume field, session/time, risk event. Extend the evaluator and compiler. Which indicators are available depends on the feature store (other audit). | M–L |
| FR-05 indicator ranges | Indicator parameter and value ranges | **MISSING** | `_validate_predicate` checks only that `value` is numeric (`dsl.py:287-299`), so `rsi14 > 150` passes. | A domain table per feature (RSI 0–100, percentage fields, and so on). | S |
| FR-05 rule conflicts, §9.1 | Contradictory or non-terminating logic | **MISSING** (exits partly covered) | Nothing detects contradictions such as `rsi14 > 70 AND rsi14 < 30`. Stock strategies must have a stop, target or max hold (`dsl.py:347-349`). | Intersect value intervals per feature across `all_of`. Require a terminating exit (time or expiry) on every strategy. | S–M |
| FR-05 leg count, §22 | At most 4 legs, enforced server-side | **PARTIAL** | 4 is enforced for desk paper trades (`services/desk_strategy_trades.py:97, 390-392`) and in the risk-gate policy (`services/risk_gate/policy.py:18`; `gate.py:315-316`). But the payoff model allows 8 (`strategy_plan/model.py:15, 178-179`), the margin calculator 10 (`services/fno_margin.py:10`), and the DSL has no notion of legs (and ignores a `legs` key; see FR-02c). | v2 schema `legs` with min 1, max 4. Repeat the check in the validator and at backtest submission. Add a release-blocker test (PRD §19.2). | S |
| FR-05 contract eligibility, strike/expiry | Contracts exist; strikes and expiries are consistent | **PARTIAL** | Reusable rules: strike order per template (`templates.py:92-93, 99-100, 107-108, 116-117, 124-125, 145-147`), short call must be out of the money (`templates.py:57-59`), expiry not in the past (`model.py:192-195`), listed-expiry check (`risk_gate/gate.py:277-294`). Live-chain resolvers: nearest eligible expiry `pick_expiry` (`strategy_plan/candidates.py:573`), ATM/spread strike selection (`candidates.py:629, 683`). Problems: every lookup is for **today** (`risk_gate/reference.py:100-106`; the bhavcopy may be at most 7 days old, `reference.py:28, 88-90`). Mixed expiries are refused (`model.py:188-191`; `desk_strategy_trades.py:248-249`), which blocks every calendar and diagonal in §6.2. | Give the reference lookup an as-of date (each backtest entry date, from `nidp.fno_bhavcopy`). Move the strike-order rules into the template registry. Allow several expiries only for calendar templates, once the engine supports them. | M |
| FR-05 lot size | Lot size matches the exchange | **PARTIAL** (reuse for live) | `check_exchange_lots` fails closed: an unverifiable lot blocks the trade (`desk_strategy_trades.py:276-308`; `gate._lot_size` at `gate.py:256-274`). It checks today's lot only. | Use the same as-of lookup on the bhavcopy's `new_board_lot_qty` (`reference.py:91-94`). | (in the row above) |
| FR-05 coverage, quantity relationships | Short calls covered; quantities consistent | **REUSE** | The covered call builds lots × lot size in shares (`templates.py:49-54, 130-134`). The undefined-risk guard nets short calls against long calls, futures and shares, and short puts against long puts (`model.py:270-289`; `desk_strategy_trades.py:218-262`; `gate.defined_risk_failures` at `gate.py:181`). | Call these from the v2 validator. Make "block or warn" a policy setting (see Conflicts #5). | S |
| FR-05 data coverage | Enough history for the period and legs | **MISSING** at validation time | The engine only finds out after running: `no_data` (`services/ai_trader/strategy.py:70`). | Add a coverage preflight in the validator. The data-coverage audit specifies the check. | — |
| FR-05 margin | Margin limits | **PARTIAL** | The only margin source is Zerodha's calculator through a live Kite session (`services/fno_margin.py:1-3`; `strategy_plan/margin.py:1-11`). Index contracts are not attempted (`margin.py:71`). There is no historical margin. | For backtests, either a clearly labelled margin estimate or capital at risk (`gate.structure_capital_at_risk`, `gate.py:223`) as the budget. | M |
| FR-05 risk limits | Risk limits enforced | **PARTIAL** (pure pieces reusable) | Policy `fno-risk-v1`: 4 legs, 10 lots per leg, ₹2 lakh capital at risk, defined risk required (`policy.py:12-26`; caps check `gate.py:308-330`). It was built for paper entries, not backtests. | Add a "backtest risk policy" object (the user's capital and maximum loss) that reuses the pure checks. | S |

### FR-08 and §12 Refinement

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-08, §12 | Conversational refinement: new version, before/after diff, revalidate | **MISSING** (the data for a diff exists) | There is no natural-language edit path. Every UPDATE writes `prev_definition` and `new_definition` to `strategy_audit` (`strategy_builder.py:554-561`; `020:212-221`). The config PUT writes "field a → b" notes (`strategy_builder.py:842-843`). Chat history is cut to 500 characters per message (`routes/chat.py:1602-1610`), so the current config must be sent alongside the chat history, not inside it. | `POST …/versions` from an interpret call that is given the current version. The LLM returns a JSON-Patch; the server applies it, validates it, computes the field-level diff deterministically, and stores `change_summary` and `parent_version_id`. | M |
| §12 | Never reuse old results; a changed config needs a new run | **PARTIAL** | Runs reference a `version_id` (`020:88`; `backtest.py:833-866`). The backtest always runs the active version (`strategy_builder.py:971-974`). There is no endpoint to list runs and no "stale" flag. | `GET …/strategies/{id}/runs` returning `version_no` and `is_current_version`. | S |

### FR-09 Persistence and versioning (P0)

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-09 save/load | Save and load | **REUSE** | `strategy_builder.py:373-412, 472-489, 492-512` | — | — |
| FR-09 clone | Clone | **MISSING** | No route. | `POST …/strategies/{id}/clone` (owner, or a public template), with an audit row `CLONE`. | S |
| FR-09 rename | Rename | **MISSING** | `StrategyUpdate` accepts only `definition` (`strategy_builder.py:72-73`). The name is stored twice, in `strategies.name` and in `definition.name` (which the DSL requires, `dsl.py:167-172`), and the two can drift apart. | PATCH name and description on `strategies` without creating a version. | S |
| FR-09 version history | List versions | **MISSING** | Only the active version is ever returned (`strategy_builder.py:505-508`). | `GET …/strategies/{id}/versions`. | S |
| FR-09 delete | Delete | **REUSE** (soft delete) | Archive with an audit row (`strategy_builder.py:565-584`). | The confirmation dialog is frontend work. | — |
| FR-09 separation | Definitions stored separately from runs | **REUSE** | `strategies`/`strategy_versions` and `strategy_runs`/`strategy_trades` are separate tables (`020:21-157`). | — | — |

### FR-12 and §15 Access control and security

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| FR-12 authentication | Every endpoint authenticated | **REUSE** | Every `strategy_builder` route calls `get_current_user` (cookie or Bearer session, `deps.py:71-123`). | — | — |
| FR-12, §15, App. A | Owner/tenant isolation; deny and log cross-user access | **PARTIAL**, with one real gap | Owner checks exist on get, patch, archive, config and backtest (`strategy_builder.py:503-504, 533-534, 574-575, 702-709, 969-970`) and are tested (`tests/test_strategy_config.py:434`). **Gap: another user's run can be read.** Any user may backtest a public template (`strategy_builder.py:969`), and the run is stored under the template's `strategy_id`. `GET /runs/{run_id}` then lets any user read any run of a public template (`strategy_builder.py:1057`), so user C can read user B's run and trade ledger given its id (a UUID, so it has to be known, not guessed). Also: (1) the routes answer 403, not 404, which reveals that a strategy exists, unlike desk plans (`routes/strategy_plan.py:263-267`) and AI Trader (`routes/ai_trader.py:253-258`); (2) path ids reach asyncpg's UUID parameter without validation, so the status a malformed id gets is UNVERIFIED (not run); (3) `_user_id` prefers a user's `id` field over `user_id` (`strategy_builder.py:144-151`), while desk, AI Trader and chat key on `user["user_id"]`. Current user inserts write no `id` field (`routes/auth.py:151-158`), so they agree today; legacy documents are UNVERIFIED. No denial is logged. | Allow a run only when the strategy's owner or `triggered_by` is the caller. Answer 404 for anything not owned. Validate UUIDs. Key on `user["user_id"]`. Log denials with `audit.record(outcome="denied")`. | S |
| FR-12 rate limits, §15 concurrency | Per-user rate and concurrency limits | **PARTIAL** | An in-memory sliding window per process, keyed by session cookie and path category (`middleware.py:25-145`). Strategy routes fall into "default", 200 per minute (`middleware.py:101-102`). There is no per-user backtest concurrency cap and no LLM budget. With several workers the limit multiplies; the worker count is UNVERIFIED. | Add a category for `…/interpret` (for example 20 per minute). Cap each user's running jobs when a run is submitted. | S |
| FR-12 audit trail, §15 | Audit material changes and run execution | **PARTIAL** | `strategy_audit` gets CREATE, UPDATE, ARCHIVE and CONFIG_UPDATE rows (`strategy_builder.py:403-408, 554-561, 580-583, 874-877`). Promote writes none (`strategy_builder.py:1075-1084`), and nothing records run submission or denied access. `services/audit.record` exists and supports `outcome="denied"` (`services/audit.py:58`) but these routes don't call it. | Audit run submit/cancel, version creation, clone and promote. Log authorisation denials. | S |
| FR-12 feature gating | Release behind a flag | **REUSE** | `require_feature` is a fail-closed dependency (`feature_gate.py:44`). The strategy routes are not gated today. | Add a `strategy_copilot` allowlist flag. | S |
| §15 broker secrets | No broker secrets in definitions or prompts | **PARTIAL** | `llm_guard` redacts PII (PAN, Aadhaar, mobile, address, date of birth) and fails closed (`services/llm_guard.py:1-20`). It does not look for broker tokens or keys. | Scan prompts for token and key shapes and refuse them. With v2's `extra=forbid`, no arbitrary key can be stored. | S |
| §15 input size | Validate input size | **PARTIAL** | JSON bodies are capped at 1 MB (`middleware.py:341`). Names are capped at 100 characters (`strategy_builder.py:66`). LLM user input is capped at 8,000 characters (`llm_safety.py:28`). | Cap the number of rules and nodes in the v2 schema. | S |
| §14.2 | Never execute code the model writes | **REUSE** | No `eval`/`exec`/`subprocess` in `services/strategy_engine`, `services/strategy_plan`, `services/ai_trader`, `nidp/services/copilot_agent` or the three strategy routes (grep). The compiler's whitelist is the security boundary (`compiler_stock.py:21-25`). | — | — |
| §15 idempotency | Idempotent submission, safe retries | **MISSING** on strategy routes; the pattern exists | Desk paper trades take an `Idempotency-Key` header (`routes/desk_trading.py:53, 261-266, 316-324`). Two identical `POST /strategies` calls create two strategies. | Reuse the header on version creation and on backtest submission. | S |

### FR-13 Comparison (P1)

**Status:** MISSING.

**Evidence:** No comparison endpoint exists. `FnoCompare.tsx:1-6` puts option structures side by side in the browser for one underlying and expiry. It does not compare runs or versions.

**What to change:** `POST …/comparisons` returning the config diff (the same differ as FR-08), run metrics side by side, and flags when periods, costs or assumptions differ.

**Size:** M.

### §6.1 Instrument types

| PRD ref | Requirement | Status | Evidence | What to change | Size |
|---|---|---|---|---|---|
| §6.1 stock long | Long stock | **REUSE** | The DSL backtester is long-only (`strategy_builder.py:594-597`). | A single-symbol universe (Conflicts #3). | S |
| §6.1 stock short | Short stock where permitted | **MISSING** | The engine is long-only, and the desk refuses short cash legs (`desk_strategy_trades.py:191-192`). | Owner decision (Q4). | — |
| §6.1 futures | Long and short futures | **PARTIAL** | The leg model and templates support futures (`model.py:20, 88-91`; `templates.py:153-164`). The desk refuses short futures-only structures (`desk_strategy_trades.py:242-246`, owner decision D2 of 2026-10-27). The risk policy requires defined risk (`policy.py:23`). | Owner decision (Q3). | — |
| §6.1 options | Calls and puts, bought or sold | **PARTIAL** | The leg model can be reused. Short legs are limited by the undefined-risk guard (`model.py:270-289`). | Q3. | — |
| §6.1 mixed | Stock + futures + options | **PARTIAL** | Cash + option templates exist (`templates.py:130-150`). No stock + futures hedge + option template exists. | Add templates; exposure math belongs to the engine audit. | M |

---

## 2. Which existing strategy store should be the base

| | **A. Strategy Builder (DSL)** | **B. AI Trader strategies** | **C. Desk strategy plans** |
|---|---|---|---|
| Storage | PostgreSQL `public.strategies`, `strategy_versions`, `strategy_runs`, `strategy_trades`, `strategy_audit`, `user_universes` (`nidp/migrations/020`, user ids widened to TEXT in `115`), plus `strategy_config` (`backend/migrations/024`) | Mongo `ai_trader_strategies` (`services/ai_trader/execution.py:54`), one document per strategy | Mongo `desk_strategy_plans` (`routes/strategy_plan.py:45`); candidate TradePlans in Mongo `trade_plans` (`services/strategy_plan/trade_plan.py`) |
| Schema | DSL v1: universe + flat entry predicates + exit (stop %, target R:R, max hold) + ranking (top N, 1–100) + rebalance (`dsl.py:8-28`) | DSL v1 spec copied from a regime-chosen template, plus a frozen NiveshConfig (`ai_trader/strategy.py:236-286`) | Plan schema: inputs + source snapshots + candidates with concrete legs (`strategy_plan/plan.py`, `model.py`) |
| Versioning | Append-only `version_no` rows, one active; runs point at `version_id`; immutable by convention only (`strategy_builder.py:535-553`) | One 16-character content hash (`strategy.py:289-293`); the document is changed in place (runs pushed, stage moved, `routes/ai_trader.py:493-526`), so there is no version history | `plan_id` = hash of inputs + snapshots + rules (`routes/strategy_plan.py:227-229`); the saved copy is immutable and has no update route (`:10`); `trade_plans` has `supersedes` lineage |
| Multi-leg / options | None. `asset_class` CHECK allows STOCK and MF only | None | Yes: cash, future and option legs; payoff; defined-risk guard. Up to 8 legs in the payoff model; one expiry |
| Rules (entry/exit signals) | Yes, the only one of the three (feature predicates) | Same as A | No. Point-in-time levels (underlying stop/target, premium levels) |
| Ownership | `owner_id` TEXT; 403 for non-owners; public templates readable; one run-access gap (§1 FR-12) | `user_id` filter, 404 | `user_id` filter, 404; at most 200 saved |
| Audit | `strategy_audit` | `stage_history` in the document | log lines only |
| UI that uses it (frontend-v5) | `pages/StrategyBuilder/StrategyBuilderPage.tsx`, the chat `components/chat/StrategyLabWidget.tsx`, CopilotApp `workspace/strategies.ts`, `Saved.tsx`, `markets/StrategyScreens.tsx`, and the backtest panel in `tradingdesk/tabs/trade-desk/NewTrade.tsx` | **None.** The only frontend matches are comments (grep for `ai-trader` / `ai_trader`) | `tradingdesk/strategy/*`, `FnoBuilder.tsx`, `FnoCompare.tsx`, `ScannerTop10.tsx`, `NewTrade.tsx` |

**Recommendation: make A (the Strategy Builder's PostgreSQL tables) the base, with a thin unifying layer.**

Why A:
- It is the only store that already has what PRD §14.1 and §14.4 describe: PostgreSQL, a version table, runs that reference an immutable version, per-trade rows, an audit table, owner checks, and run provenance (`backtest.run_provenance`, `backtest.py:245-296`).
- It already has users and UI.

What the unifying layer is:
- Config v2 lives in `strategy_versions.definition`, with `schema_version` "2".
- The leg validation is imported from C, not rebuilt: `strategy_plan/model.py` `_parse_leg`, the template registry, and the pure risk-gate checks.
- A stock-only v2 config compiles to DSL v1 and runs on the existing engine. An options config goes to the options engine (other audit).

What happens to B and C:
- **C stays as it is:** it holds system-built idea snapshots. Add `POST …/strategies/from-plan`, on the model of `from-screen` (`strategy_builder.py:415-469`), so a saved plan can seed a draft strategy.
- **B stays as it is for now:** it is AI Trader's promotion ladder (draft → backtested → paper → assisted). Later it could point at A's version ids (Q2).

Migrations needed on A:
- Widen the `asset_class` CHECK.
- Add to `strategy_versions`: `schema_version`, `source_prompt`, `conversation_ref`, `model_provenance`, `change_summary`, `parent_version_id`, `field_status`, `validation_snapshot`, and an immutability trigger.
- Add `strategy_validations` and `strategy_comparisons` tables.
- Run status, idempotency and per-leg trade rows belong to the engine audit's slice.

---

## 3. §14.3 API map

| Proposed (PRD) | Existing route | Gap |
|---|---|---|
| POST /api/strategy-copilot/interpret | **none, build** | Everything (FR-01, FR-04). |
| POST /api/strategies | `POST /api/strategy-builder/strategies` (`strategy_builder.py:373`); also `/from-screen` (`:415`) | Accepts DSL v1 only; no prompt or provenance; no idempotency key. |
| GET /api/strategies | `GET /api/strategy-builder/strategies` (`:472`) | No search or paging; the list omits version count and last run. |
| GET /api/strategies/{id} | `GET /api/strategy-builder/strategies/{id}` (`:492`) | Returns the active version only. |
| POST /api/strategies/{id}/versions | `PATCH /api/strategy-builder/strategies/{id}` (`:515`) creates `version_no+1` | Rename it or add a POST alias; add `parent_version_id`, `change_summary`, diff; add `GET …/versions`. |
| POST /api/strategies/{id}/validate | `POST /api/strategy-builder/validate` (`:178`) validates a posted document, not a stored id; `/screen` (`:884`) is a dry run on the latest snapshot | Add id-based validation that persists the result; v2 validator. |
| POST /api/backtests | `POST /api/strategy-builder/strategies/{id}/backtest` (`:953`), synchronous, at most 5 years | Async job, idempotency (engine audit). |
| GET /api/backtests/{run_id} | `GET /api/strategy-builder/runs/{run_id}` (`:1042`) returns run + provenance + **all** trades | Run-access gap (§1 FR-12); split the response. |
| GET /api/backtests/{run_id}/metrics | inside `runs/{id}` (`run.metrics` JSONB) | A separate route is optional. |
| GET /api/backtests/{run_id}/trades | inside `runs/{id}`, not paginated | Pagination. |
| POST /api/strategy-comparisons | **none, build** | FR-13. |
| (not in the PRD, needed) | — | `GET …/strategies/{id}/runs`, `…/versions`, `POST …/clone`, PATCH name, `…/from-plan` |

**Naming notes:**
- The codebase names routes by module: `/api/strategy-builder/*`, `/api/desk/strategy/*`, `/api/ai-trader/*`. No bare `/api/strategies` exists. `/api/ai-trader/strategies` and `/api/desk/strategy/plans` already use "strategy" for other things.
- So I recommend keeping `/api/strategy-builder/...` for CRUD, versions and runs, and adding only `/api/strategy-copilot/interpret` (and `/refine`). Bare `/api/strategies` and `/api/backtests` would add a fourth namespace.
- Error shapes differ today. The DSL routes answer `400 {message, errors:[str]}`. The desk routes answer `422 {code, problems:[{field, code, message}]}`. PRD §13.3 (link each issue to its field) fits the desk shape; use it for v2.

---

## 4. §14.4 Entity map

| Entity | Existing table / collection | Migration | Gap |
|---|---|---|---|
| strategy | `public.strategies` | `backend/nidp/migrations/020_strategy_builder_core.sql:21`; owner TEXT in `115_strategy_userid_text.sql:17` | No `template_id` or status beyond `is_archived` / `is_public_template`; `asset_class` limited to STOCK/MF. |
| strategy_version | `public.strategy_versions` | `020:44` (+`115:18`) | No prompt, schema version, change metadata, model provenance or parent; immutability not enforced. |
| strategy_template | **none as a table.** DSL JSON files `services/strategy_engine/templates/*.json`; code catalogue `services/strategy_plan/templates.py:194`; public-template rows (`strategies.is_public_template`); a frontend list `FnoBuilder.tsx:39` | — | No capability flags; three catalogues that disagree. |
| strategy_validation | **none** (validation is never persisted) | — | Build it. |
| backtest_run | `public.strategy_runs` | `020:85` | Status only RUNNING/OK/FAILED; no queue, cancel or idempotency (engine audit). Provenance is kept in `metrics.provenance` (`backtest.py:605-611`). |
| backtest_metrics | the `strategy_runs.metrics` JSONB column | `020:97` | No separate table (acceptable). |
| backtest_trade | `public.strategy_trades` | `020:123` | One row per symbol and trade; no per-leg rows (engine audit). |
| strategy_conversation | Mongo `chat_sessions` / `chat_messages` (`routes/chat.py:1076-1086, 1281, 1567`) | — (Mongo) | No link to a strategy or version. Add `strategy_id` / `version_id` to messages, or keep `conversation_ref` on the version. |
| strategy_comparison | **none** | — | Build it. |
| (related) | `strategy_audit` (`020:212`), `strategy_config` (`backend/migrations/024`), `user_universes` (`020:65`), `strategy_signals` / `strategy_alerts` (`020:165, 195`); Mongo `ai_trader_strategies`, `desk_strategy_plans`, `trade_plans`, `desk_paper_trades` | | Two migration runners: `nidp/migrations` creates the public strategy tables and `backend/migrations/024` depends on them (`024:11-17`). New migrations must respect that order. |

The canonical docs do not describe any of the Strategy Builder tables. `docs/DATABASE_SCHEMA.md` has no entry for `strategies` or `strategy_versions` (grep). That is a gap in the docs.

---

## 5. Conflicts between the PRD, the code and the owner's decisions

1. **LLM provider.**
   - The PRD says "OpenAI integration with configured fallback".
   - The copilot picks **Anthropic first** when a key is available, then the Claude Code gateway, then Groq, then OpenAI (`_llm.py:102-119`, default `claude-opus-5-5` at `:21`).
   - Two older paths also exist. `routes/copilot.py:54-72` is OpenAI-only, and its `"claude"` alias actually maps to `gpt-4o` (`:69`). `services/copilot_agents.py` goes through `emergentintegrations` and falls back to a stub.
   - Which provider staging uses is UNVERIFIED: it is set by environment and I did not read secrets.
2. **Persistence.** The PRD wants PostgreSQL. Desk plans, AI Trader strategies, chat conversations and paper trades are in Mongo. Recommendation: strategies, versions and runs in PostgreSQL (store A); conversations stay in Mongo, linked by id.
3. **Two different strategy models.**
   - A DSL strategy is a screener: rank a universe and hold the top N (`ranking.limit` 1–100, `dsl.py:353-368`; `max_positions` 10).
   - The PRD's strategy is one underlying with up to 4 legs.
   - A single-stock strategy today needs a stored `user_universes` id. AI Trader's own notes record this gap (`ai_trader/strategy.py:252-257`).
   - v2 needs an explicit `underlying`.
4. **Inconsistent leg limits:** 4 (desk and risk gate), 8 (payoff model), 10 (margin), none (DSL). PRD §22 wants 4 enforced by the backend everywhere.
5. **Risk policy versus PRD warnings.**
   - The risk gate and desk block naked short options, short futures-only structures (owner decision D2, 2026-10-27) and short cash (`policy.py:23`; `desk_strategy_trades.py:191-192, 242-246`).
   - The PRD lists short call, short put and short futures templates, and treats naked option exposure as a **warning** (§9.2); coverage blocks only "where coverage is required" (§9.1).
6. **Calendars and diagonals.** The PRD's calendars, diagonals and double calendars are blocked by the single-expiry rule (`model.py:188-191`; `desk_strategy_trades.py:248-249`).
7. **Timeframe.** The PRD's examples use 15-minute RSI. The DSL is daily only, and the owner chose positional (daily) first. MVP prompts asking for intraday timeframes must get a clarification or a clear "not supported".
8. **Same-bar stop and target: consistent.** `services/exit_rules.py:11-14` already takes the stop when both are touched in one bar. That matches the owner's decision and PRD §10.2's "documented conservative assumption". No conflict.
9. **Python sandbox versus no arbitrary code.**
   - `docs/STRATEGY_BUILDER_CONFIG_SPEC.md` (a Code screen, `strategy_info` in Python) and the AI Trader requirement doc (lines 225 and 233, decision OPEN) both describe a Python sandbox.
   - PRD §2.3 and §8.3 rule out arbitrary code, which effectively settles that open decision in favour of a DSL / expression tree.
   - The spec doc should be marked superseded.
10. **Templates are defined in the frontend.** `FnoBuilder.tsx:39` keeps its own template list (including short call and short put); the backend catalogue has 13 different ones. The PRD wants capability-driven templates owned by the server.
11. **Placement and the owner's 4-step wizard.**
    - PRD §4.1 places a new "Strategy Studio → AI Strategy Copilot".
    - The owner's 4-step "Build a trade" wizard is **not in `frontend-v5/src` at this commit**: grep for "Choose template" and "Review & adjust" finds nothing. Today "Build a trade" is the ticket, the F&O builder, the Strategy Builder and a backtest panel (`NewTrade.tsx:1-16`; nav at `tradingdesk/desk-nav.ts:78`).
12. **Paper trading.** The owner's wizard ends with "Validate & paper-trade". The PRD defers paper trading to Phase 4 (FR-15, P1/later). Desk paper trades for structures already exist (`desk_strategy_trades.py`).
13. **Mutable Bot config.** `strategy_config` is a per-strategy row edited in place, outside the versions. That conflicts with "each run references an immutable version" (FR-09). Runs do record their capital and cost model, so stored results stay traceable.

---

## 6. Questions only the owner can answer

1. **LLM for interpretation.** The PRD says OpenAI with fallback; the copilot today prefers Anthropic.
   *Default:* reuse the copilot's `make_chat_llm` provider order, use structured tool-call output on whichever provider is active, configure OpenAI as the fallback, and record the provider and model with every version.
2. **Base store.** Make the Strategy Builder's PostgreSQL tables the single home for copilot strategies (config v2), with desk plans importable as drafts and AI Trader left alone for now?
   *Default:* yes.
3. **Undefined-risk structures in backtests** (naked short call/put, short futures-only): block them as the risk gate and desk do, or allow them with warnings as PRD §9.2 implies?
   *Default:* allow in backtest only, with a loud warning and a labelled margin estimate; keep the paper-trade block.
4. **MVP template list.** Include calendars, diagonals, short stock and short futures in v1?
   *Default:* no. List them as disabled with the reason ("multi-expiry engine / historical data not verified"), and enable them through the capability registry later.
5. **Placement.** A new "Strategy Studio" nav item (PRD §4.1), or the chat front door of Trade Desk › Strategy Lab › Build a trade, reusing the wizard's Configure / Review steps as the config pane?
   *Default:* inside Strategy Lab › Build a trade; no new nav item.
6. **Paper trading at the end of the flow.** Keep the wizard's "Validate & paper-trade" step (the desk paper-trade route already exists), or hold paper trading to PRD Phase 4?
   *Default:* keep the step for option structures through the existing desk route, behind the existing risk gate; PRD Phase 4 then covers only automated, signal-driven paper runs.
