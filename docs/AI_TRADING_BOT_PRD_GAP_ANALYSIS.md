# F&O AI Trading Intelligence PRD v2.0 — Gap Analysis vs. the F&O Lab

| | |
|---|---|
| PRD reviewed | `docs/ai_research/Nivesh_FO_AI_Trading_Intelligence_PRD_v2.md` (879 lines, 22 sections) |
| PRD with this analysis folded in | `docs/ai_research/Nivesh_FO_AI_Trading_Intelligence_PRD_v2.1_Implementation_Gap_Integrated.md` (§23–27) |
| Code baseline | `origin/dev` at `307c2994` (merge of PR #332), 2026-10-24 |
| Execution direction | **Live strategy execution will use the Kite Connect API** when it is built (product decision, 2026-10-24) |
| Status | Code-and-data assessment. It is not a certification, and nothing here is claimed to be deployed or working beyond the checks in §0. |

Paths are relative to `backend/` unless they start with `frontend-v5/`, `docs/`, `deploy/` or `test_reports/`. A claim marked **†** was read by a review agent and not re-checked by the author. Everything else was re-checked by the author on a clean `origin/dev` tree, or comes from a test or query listed in §0. An earlier, truncated draft of the PRD (ai_trading_bot.md, which ends mid-word at §12.2) was not used and is not committed.

## Scope: what "the F&O Lab" means here

- **Trading Desk → F&O tab** (`frontend-v5/src/pages/CopilotApp/screens/tradingdesk/FnoTab.tsx:501-505`): OI build-up for F&O stocks, Candidates, NIFTY & BANKNIFTY, the option chain with Analyse, and Paper strategies (Builder and Rule-based ideas).
- **Options Lab** (`tool/optlab`, `frontend-v5/src/pages/CopilotApp/screens/OptionsLab.tsx`): a second strategy builder that computes in the browser.
- **Backend:**
  - Routes: `/api/fno/*` (`routes/fno.py`), `/api/desk/strategy/*` (`routes/strategy_plan.py`), `/api/desk/paper-trades` (`routes/desk_trading.py`) and `/api/risk/*` (`routes/risk_controls.py`).
  - The research services `services/fno_backtest`, `services/fno_candidates` and `services/fno_forward`.
  - The warehouse table `nidp.fno_bhavcopy` and the Kite live feed (`services/kite_live_feed`).

## 0. Evidence: checks run for this report

| # | Check | Result |
|---|---|---|
| 1 | Order calls: `grep -rnE "\.(place_order\|modify_order\|cancel_order)\("` over non-test backend code | No call sites. The only mention is a comment (`services/brokers/zerodha.py:4` †). |
| 2 | Execution modes | `services/ai_trader/execution.py:49`: `MODES = ("paper", "assisted")`. |
| 3 | Backend tests: 49 F&O, desk, paper, risk, AI-trader and live-feed test files, run on the clean tree in a throwaway container with no network † | **1,701 passed, 10 failed**, 0 collection errors. Eight failures are in `tests/test_copilot_backtest.py`: the image lacks `pytest-asyncio`, and with a shim all 28 of its tests pass. Two are in `tests/test_desk_paper_sim.py`: they pin the gap-fill rule that commit `cace6500` replaced, and `tests/test_honesty_safety_pass.py`, which pins the new rule, passes. |
| 4 | Component tests, re-run by the author on the same tree | `174 passed` (`test_option_pricing`, `test_risk_controls`, `test_fno_margin`, `test_paper_account`, `test_ai_trader_execution`). |
| 5 | Warehouse: read-only query on staging NIDP, run by the author | `nidp.fno_bhavcopy` holds 261 sessions, 2025-10-01 → 2026-10-23, 10,298,812 rows: index futures 4,065, index options 1,339,156, stock futures 162,744, stock options 8,792,847. Feed `NSE_FNO_BHAVCOPY` is `OK`, staleness 1 of 4 days, `last_dq_status NONE`. |
| 6 | App Mongo on staging: collection names and counts only † | `desk_paper_trades` 8, `paper_accounts` 1, `risk_controls` 1, `risk_control_audit` 8, `risk_decisions` 3, `ai_trader_tickets` 0, `kite_live_intraday` 0, `idempotency_keys` 0. `fno_forward_signals` and `desk_strategy_plans` do not exist. |
| 7 | Payoff engine run on mock legs (`compute_payoff`) † | Of 22 structures it rejects six: calendar, diagonal, short straddle, short strangle, naked short call and naked short put. Every valid result returns `margin: None`. |
| 8 | Security review (author) | Findings reported to the owner separately; not detailed in this public document (§18). |
| 9 | Frontend typecheck, and the repo's Playwright specs for the desk, F&O and strategy screens (mocked APIs, no network, built from the clean tree) † | `tsc --noEmit`: 0 errors. Playwright: **513 passed, 32 failed, 16 skipped** across 22 spec files; `copilot-app-desk-lab` passed 79 (2 skipped). Of the 32 failures, 31 are `copilot-app-desk-strategy-graphs`, which needs a test-only build flag (`VITE_STRATEGY_HARNESS=1`) set by a script that is not in the repo. Rebuilt with the flag, that spec gives 31 passed. One is a date-dependent assertion in `copilot-app-desk-smart-money` (TC-F3, no frozen clock), which passes with the clock fixed at 2026-10-22. |

## 1. Scorecard

| PRD § | Area | Status | In one line |
|---|---|---|---|
| 5 | Architecture and authority boundaries | Partial | Pricing and payoff are deterministic, and no LLM sits in a decision path. There is no schema-validator, authorization or certification service. |
| 6.1 | Market regime | Partial | A versioned, explainable five-regime rule. No realized-vs-implied, liquidity or event regime, and no transition history. |
| 6.2 | Futures intelligence | Partial | End-of-day build-up labels, with OI summed over all expiries. An intraday series is coded but not recording. |
| 6.3 | Options-chain intelligence | Partial | End-of-day chain with volume, OI and Black-76 IV/Greeks. No stored bid/ask and no intraday snapshots. |
| 6.4 | Expiry and term structure | Partial | Weekly/monthly selector and expected move. No term structure or skew. |
| 6.5 | Greeks and volatility | Partial | Calculated Greeks only, at a fixed 5.75% rate, with no IV history. |
| 7 | AI strategy agent | Missing | No agent and no proposal schema. The copilot narrates F&O data as free text. |
| 8 | Strategy library and builder | Partial (strongest) | Two builders, exact payoff, and broker margin and charges. No calendars or undefined-risk structures, and two contradictions on screen. |
| 9 | Strategy ranking | Partial | Two rule-based rankings that record each input's contribution. Research found no edge over simple baselines. |
| 10 | Backtesting | Partial for futures signals, missing for options | Pre-registered, point-in-time futures-signal studies. No options replay and no fill model. |
| 11 | Paper and shadow | Partial | End-of-day diagnostic paper, with defects in the F&O path. No shadow mode. |
| 12 | Live OMS | Absent by design | No order code. Kite Connect is the chosen adapter, and the Kite integration is read-only. |
| 13 | Risk engine and Risk Control Center | Partial for AI-trader cash, missing for F&O | The governor covers one path and fails open. The kill switch has no UI. |
| 14 | Certification | Missing | The equity AI Trader has stage gates and a sealed holdout; there is nothing for F&O. |
| 15 | UX and screens | Partial | Trust lines and paper labels exist. No replay, shadow, live, certification or risk-centre screens. |
| 16 | APIs | Partial | Equivalents exist for the chain, payoff, risk status and kill switch; the rest are absent. |
| 17 | Data model | Partial | Of 35 entities: 2 exist, 15 are partial, 18 are missing. |
| 18 | Security, reliability, observability | Partial | Broker tokens are encrypted. Further security and operations findings were reported to the owner separately. The data-quality rollup is blind for the F&O feed. |
| 19 | Acceptance criteria | 0 of 27 met | 16 partial, 9 missing, 2 absent by design (§2, "§19 Acceptance criteria"). |
| 21 | Live readiness gate | Missing | There is no order path on which to enforce the 12 conditions. |

## 2. Detail by section

### §5 Architecture and authority boundaries — Partial
- **Deterministic services exist:**
  - pricing (`services/option_pricing.py`, Black-76)
  - payoff (`services/strategy_plan/payoff.py`, `payoff-v1`)
  - broker margin (`services/fno_margin.py`)
- **No LLM in these services:** a grep for `openai|anthropic|llm|gpt|chat.completions|messages.create` in `services/strategy_plan` and `services/fno_candidates` returns nothing.
- **Missing PRD §5.2 services:** a separate strategy-schema validator, an authorization service, a certification service and a decision-audit service.
- **Other execution-capable integration:** the codebase contains an integration with a third-party trading platform that sits outside the risk engine and the kill switch (PRD §5.2, §13.1). Its details were reported to the owner separately.

### §6 Market intelligence — Partial
- **Data (§0 #5):** end-of-day NSE F&O bhavcopy only.
  - Rows carry prices, OI, change in OI, volume, lot size, and `source` / `source_run_id` / `ingested_at`.
  - There is no bid/ask, IV, Greeks, quote time or quality flag †.
  - `ingested_at` is load time: 253 sessions were bulk-loaded on 2026-10-12, and a reload overwrites the run id instead of keeping history †.
  - The DaaS F&O routes, the build-up scan, candidates and margin all serve the latest date without a freshness check (`nidp/services/daas_api/routers/fno.py:31,75` †).
- **§6.1 Regime:** `desk-regime-v1` (`services/macro_engine.py:826-846`, served by `routes/macro.py:159`) reads one end-of-day session, in this order:
  1. India VIX ≥ 20 → high volatility.
  2. Nifty 50 trend and market breadth disagree → mixed.
  3. Otherwise the Nifty close against its 50-session average → bullish, sideways or bearish.

  The thresholds are versioned and sent with every answer, as PRD §6.1 asks. Missing: a realized-vs-implied volatility regime, liquidity and spread quality, event-driven conditions, and stored transition history.
- **§6.2 Futures:** `GET /api/fno/scan/buildup` labels long build-up, short build-up, short covering and long unwinding.
  - Its docstring (`routes/fno.py:784-786`) takes the price change from the nearest expiry, while open interest and its change are "summed over all expiries". This is also noted in `docs/FO_SMART_MONEY_PRD_GAP_ANALYSIS.md:41`.
  - There is no confidence or conflicting-evidence field, and no basis-across-expiries or roll tracking.
  - A 5-minute intraday snapshot of near-month futures (price, OI, volume) into Mongo `kite_live_intraday` is coded (`services/kite_live_feed/feed.py:43-46`, `:475-500` †). Staging holds 0 documents for 2026-10-18 to 10-24 (§0 #6); the cause has not been established.
- **§6.3 Options chain:**
  - Present per strike: close, settle, OI, change in OI and volume (`routes/fno.py:216-220`, `:317-321`), plus Black-76 IV and Greeks (`:398-399`) and the lot size from the exchange file (`:613`). PCR, max pain and walls are also computed.
  - Missing: bid/ask, quote age, spread width and intraday snapshots. Option contracts are not on the live feed †.
  - Two live option reads exist, and neither is stored:
    - `POST /api/live/fno-quotes` reads up to 40 named legs on each screen request, with no bid/ask (`services/kite_live_feed/fno_quotes.py:29` †).
    - The plan engine can read bid/ask for its preferred candidate's legs through the user's own ICICI Direct session. This is opt-in and off by default (`services/strategy_plan/quotes.py:1-11` †).
- **§6.4 Expiry:** a weekly/monthly selector (`FnoTab.tsx:344-347`) and an ATM-straddle expected move. Missing: IV, OI and basis term structure, and tracking through the month.
- **§6.5 Greeks and IV:**
  - Greeks are calculated only, from end-of-day prices, with a fixed `RISK_FREE_RATE = 0.0575` (`services/option_pricing.py:66`).
  - There are no broker-provided Greeks and no provenance flag. There is no IV history, so no IV rank or percentile (`services/strategy_levels.py:147` returns null for both †). There is no skew and no stored Greeks.
  - Net strategy Greeks are shown in the Desk builder in pre-expiry mode † and in the Options Lab (`screens/trading/odds.ts`). Per-leg Greeks are computed by the backend (`services/strategy_plan/pre_expiry.py:112-119` †) but never rendered †.

### §7 AI strategy agent — Missing
- No agent proposes strategies, and there is no structured proposal schema (`proposal_id`, legs, `model_version`, `data_snapshot_id`).
- **What the copilot chat does today** (`POST /api/chat/stream`, `routes/chat.py:1496` †):
  - It is a LangGraph flow of fixed Python fetchers with one narrative LLM call per node. There is no LLM tool calling †.
  - It already narrates F&O positioning: build-up, PCR and max pain, read through DaaS (`services/copilot_tools/market_research.py:527-547` †).
  - It puts the user's broker F&O positions and live quote into the prompt (`routes/chat.py:150-238` †).
  - Its prompt forbids buy/sell advice, and a compliance node scrubs directional words (`nidp/services/copilot_agent/nodes/compliance.py:145-166` †).
  - It writes nothing to paper trades, plans, risk controls or orders. It can auto-create an equity/MF Plan Board plan (`routes/chat.py:421-446` †).
- **Deterministic analogue of §7.4:** the rule-based plan engine returns `plan`, `wait`, `no_trade` or `insufficient_data` (`services/strategy_plan/plan.py:7-12`; the logic is at `:399-413` †).

### §8 Strategy library and builder — Partial (strongest area)

Two builders exist:

| | Desk builder (`tradingdesk/FnoBuilder.tsx`) | Options Lab (`screens/OptionsLab.tsx`) |
|---|---|---|
| Payoff | Server: `POST /api/desk/strategy/payoff`, debounced 250 ms † | Browser: `screens/trading/payoff.ts` (exact, piecewise linear) |
| Templates | 13 tiles † | 16 structures (`payoff.ts:115-140`) |
| Greeks | Net, in pre-expiry mode only †; per-leg not shown † | Net (`odds.ts`) |
| Chance of profit | None | Risk-neutral lognormal at the ATM IV, with no skew, labelled a model estimate (`odds.ts:1-23`) |
| Costs | Slippage % plus flat brokerage. Taxes, STT, exchange and statutory charges are listed as excluded (`services/strategy_plan/payoff.py:14-19`). | None |
| Margin | Broker basket-margin strip (`POST /api/fno/margin`) † | Not connected (`OptionsLab.tsx` header) |

- **Template coverage (PRD §8.1)**, from the engine run (§0 #7 †):
  - Accepted: long call and long put; covered call (shares or future); protective put; bull and bear call and put spreads; long straddle and long strangle; iron condor; iron butterfly; call butterfly; a future with a protective option.
  - Rejected: calendar and diagonal spreads (`mixed_expiries_not_supported`, `services/strategy_plan/model.py:189-191` †), and short straddle, short strangle and naked shorts (`undefined_risk_not_supported`, `model.py:270-289` †).
  - The Desk builder offers option legs only, with no futures or share legs †. Its `sell_put` and `sell_call` tiles always come back rejected †.
  - Template permissions by role, account or mode do not exist.
- **Costs (§8.3):**
  - `services/fno_margin.py:75-91` † returns Zerodha's calculator charges: brokerage, STT, exchange, SEBI, stamp duty and GST.
  - The Desk margin strip shows the total with brokerage, STT, exchange and GST; SEBI and stamp duty are parsed but not shown †.
  - The payoff itself is not net of these charges.
- **Margin (§8.3):**
  - The payoff route always returns `margin: None`, with the reason "No margin source exists in this system…" (`services/strategy_plan/engine.py:15-17`, `:22`, `:79`).
  - The Desk screen shows that dash and reason under "Margin (estimate)" (`tradingdesk/strategy/PayoffSummary.tsx:57-60`), next to the working broker-margin strip.
  - `POST /api/fno/margin` needs the platform's daily Kite login and answers 503 without it (`routes/fno.py:675-679`).
  - A second margin path reads the user's own Zerodha session, for stock underlyings only, when live broker reads are switched on (`services/strategy_plan/margin.py` †).
  - There is no margin buffer or free-funds-after-trade view.
- **Builder (§8.2):**
  - Editable: legs (add, remove, modify), strike from the chain, side, type, lots and price †. Expiry comes from the chain selector.
  - There is no order-type field † and no compare-variants view.
  - Saving a plan is `POST /api/desk/strategy/plans` (`routes/strategy_plan.py:196`).
  - The Desk builder's "Record as paper trade" button is permanently disabled, with text saying the desk's paper trades "hold long shares only" (`FnoBuilder.tsx:247-250`). That text is stale: F&O structures are recorded as paper trades from the plan actions (`tradingdesk/strategy/PlanActions.tsx:72-81` → `routes/desk_trading.py:109-110`).

### §9 Ranking — Partial
- **Regime fit:** `services/strategy_plan/regime_fit.py` ranks priced structures by fit to the current regime: direction 40, volatility 30, breadth 15, positioning 15 (`:89` †).
  - It says it is "not a performance ranking" (`:8-9`, `:43-48` †).
  - It has no minimum fit score, so it never answers "no suitable candidate" while anything prices †.
- **F&O candidates (v2):** `fno_candidates` scores OI 30, price 20, volume 15, options 15, delivery 10, technical 10 (`services/fno_candidates/rules.py:40` †), with a minimum coverage of 80% (`:49` †).
  - Options confirmation is never computed, so coverage tops out at 85% (`services/fno_candidates/engine.py:235`, `:376` †).
  - Each candidate records per-input weight, score and points (`services/fno_candidates/engine.py:201-218` †). That partly meets the feature-contribution item in §9.2.
- **Research:** the production top five was compared against OI-only, price-only and whole-pool (random) picks. It found "no ordering skill beyond a random pick", and no threshold survived validation and test (`docs/FO_RANKING_BACKTEST_FINDINGS_20261023.md`, findings 1–2).
- **Missing:** expected return after costs, liquidity and fill probability, portfolio fit, drift tracking, a live baseline comparison, and walk-forward evidence.

### §10 Backtesting — Partial for futures signals, missing for options
- **What `services/fno_backtest` studies:** futures-signal outcomes, entered at the next session's open and exited at the close of day D+h.
  - Prices are split/bonus-adjusted **cash prices used as a proxy for the near-month future**; "basis and roll are not modelled" (`services/fno_backtest/study.py:5`, `:266`).
  - Costs are an assumed `research-cost-v0` round trip of 0.15% (stress 0.30%) (`services/fno_backtest/outcomes.py:13`).
- **Integrity controls:**
  - pre-registration (`docs/FO_STAGE_B_PREREGISTRATION.md`, `docs/FO_STAGE_B2_EXPIRY_CURVE_PREREGISTRATION.md`)
  - chronological discovery, validation and test splits
  - a poisoned-future-rows test (`tests/test_fno_backtest.py:144-148`)
  - a no-lookahead test (`tests/test_fno_expiry_study.py:147`)
- **Results:**
  - The ranking study covered 200 signal sessions, 29 Dec 2025 to 21 Oct 2026.
  - Stage B2 supported none of its hypotheses. The nearest miss, near-month short build-up, failed the permutation gate at p = 0.060 (`docs/FO_STAGE_B2_FINDINGS_20261023.md:5-7`).
- **Missing against §10.1–10.6:** any options or multi-leg replay; bid/ask or intraday data; a versioned instrument master and a roll model (daily lot sizes are stored per contract †); fill, partial-fill and latency simulation; walk-forward evaluation; and an AI-versus-rule ablation.
- The Stage B3 options/Greeks study is pre-registered (`docs/FO_STAGE_B3_OPTIONS_GREEKS_PREREGISTRATION.md`), but no code implements it.

### §11 Paper and shadow — Partial
- **Where F&O paper structures live:**
  - They are `kind: "strategy"` rows in `desk_paper_trades` (`services/desk_strategy_trades.py:3-4` †), created through `POST /api/desk/paper-trades` (`routes/desk_trading.py:109-110`) and listed on the Paper Desk (`PaperDesk.tsx:196-228` †).
  - Legs are immutable and hashed together with client-supplied rule and model versions (`desk_strategy_trades.py:268-272` †). No market snapshot is stored.
- **Fills:**
  - F&O entries are taken at the typed prices, with all legs filled at once (`:309-313`, `:356` †). Cash trades have an end-of-day fill model with gap-to-open fills.
  - In PRD terms this is diagnostic paper, but nothing labels it so. The AI Trader's paper → assisted promotion gate consumes end-of-day paper results (`services/ai_trader/strategy.py:87-90` †).
- **Defects found:**
  - **Closing an F&O structure never returns its reserved capital.** Creation reserves the capital at risk (`routes/desk_trading.py:123-128`) and releases it only if the insert fails (`:133`, `:139`). `close_strategy_trade` (`services/desk_strategy_trades.py:670-712`) has no release, unlike the cash close (`services/desk_trading.py:730-739`). The capital stays blocked and the P&L never reaches paper cash. No test covers this. It was found by reading the code and has not been reproduced.
  - **F&O exits run only when someone opens the paper-trade list** (`routes/desk_trading.py:171`). The evening job skips `kind == "strategy"` rows (`services/desk_trading.py:769-771`).
  - Desk paper trades have no duplicate protection: each POST gets a new id, and the indexes are not unique †. AI-trader tickets do have a unique index †.
  - A futures-only structure passes `check_defined_risk` as `defined_risk: True`, with an "unbounded" note (`services/desk_strategy_trades.py:203-208`).
  - The lot size is taken from the client without a check, and expiry is only checked as not in the past (`:152-153`, `:165-167` †).
- **Missing:**
  - pause, resume and reset of sessions
  - margin and Greeks tracking
  - an expected-vs-simulated fill comparison for F&O
  - shadow mode for F&O
- **Forward test:** `services/fno_forward` has never recorded anything. Its collection does not exist on staging (§0 #6), and the nightly job was never installed: it is not in `deploy/cloudpe/nidp/nidp-staging.cron` † (`test_reports/OVERRIDE_fno_forward_test.md:3`, `:11`).

### §12 OMS and live execution — Absent by design; Kite Connect is the chosen adapter
- **No order code exists** (§0 #1). The Kite integration is read-only by construction: the live ticker, the NFO instrument list and the basket-margin calculator.
  - `services/fno_margin.py:23` states "No order, GTT, position or holdings method is exposed".
  - `services/risk_controls.py:13-16` notes that the Kite wrapper has no order method.
- **What a Kite Connect execution adapter must add (from PRD §12):**
  - an order state machine mapped to Kite order statuses and order updates
  - idempotency: our own keys, plus Kite's order `tag` for correlation
  - retries that cannot double-submit
  - reconciliation of orders, trades, positions and funds
  - recovery from partial fills and later-leg failures (PRD §12.3: a multi-leg order must never be assumed atomic)
  - cancel/replace safety
  - separate paper and live state
- **Orders must run in the user's own Kite session.**
  - The platform Kite session that exists today is the platform's own, used for data and margins.
  - Per-user Zerodha sessions already exist in the broker hub for reads, with encrypted tokens (`services/brokers/sessions.py:321-325` †).
- **Retire or lock down the other trading-platform integration (§5),** so that the Kite adapter is the only execution route.

### §13 Risk engine, kill switch, Risk Control Center — Partial for AI-trader cash, missing for F&O

Which paths are governed (callers of `risk_governor.evaluate` and `risk_controls.assert_allowed`):

| Path | Kill switch | Governor |
|---|---|---|
| AI-trader signals and confirm (`routes/ai_trader.py:603`, `:776` †) | Indirect: the governor reads the controls and halts | Yes (`:655`, `:795` †) |
| Desk paper trade, cash and F&O (`routes/desk_trading.py:101`) | Yes | **No** |
| Journal create (`routes/positional_journal.py:168` †) | Yes | No |
| Journal ENTRY fill (`routes/positional_journal.py`, `add_fill`) | **No** | No |
| Save plan (`routes/strategy_plan.py:196`) | No | No |

- **Governor** (`services/ai_trader/risk_governor.py`, `LIMITS_VERSION = "gov-v1"`):
  - Covers long-only cash equity. It has no Greeks, margin, lot or expiry terms.
  - **Fails open:** an unknown input skips the rule with an `info` reason (`:7-10`). PRD §13.2 "reject if any required check is unavailable" is not met.
  - Limits are the constant `DEFAULT_LIMITS` at both call sites †.
  - The event-blackout rule is never fed †. The liquidity rule is always skipped, because average traded value is never supplied †.
  - Open F&O structures enter the governor's book but leave drawdown unknown (`routes/ai_trader.py:392-410`). **The drawdown halt therefore cannot fire while any F&O structure is open.**
- **Kill switch** (`routes/risk_controls.py`, `/api/risk/*`):
  - Present:
    - It is backend-enforced, per user, and a reason is required in both directions (`:54-83`).
    - The audit log is append-only by convention only: the code only inserts, and nothing in the database enforces it (`services/risk_controls.py:145` †). Failed decision-log writes are swallowed (`:243-248` †).
  - Against PRD §13.4:
    - It stops new paper risk on three paths only.
    - It cannot cancel orders, and it has no hold, hedge or flatten policy.
    - The same user resets it with no elevated authorization, although `docs/RISK_CONTROL_INVENTORY.md:89-90` † planned one.
    - **No screen calls `/api/risk/*`** (grep of `frontend-v5/src` and `frontend/src`), so it cannot be reached from the UI.
- **Risk Control Center (§13.5):**
  - `RiskDesk.tsx` is a one-stock sizing panel †. The Paper Desk shows P&L †.
  - Missing from the UI: certification state, drawdown, margin and funds, Greeks, limits used and remaining, alerts, the kill switch and an audit timeline.
- **Recorded decisions:** decisions are recorded only for the AI trader and for **blocked** desk trades (`GET /api/risk/decisions`, `routes/risk_controls.py:95-104`). Allowed desk trades write none †.

### §14 Certification — Missing
- `nidp/shared/certification.py:3-7` certifies data-lake dates into `nidp.certified_dates`. Nothing certifies an agent, a strategy or an adapter.
- **Equity building blocks to reuse:**
  - the AI Trader's stage ladder `draft → backtested → paper → assisted → retired`, with promotion gates (`services/ai_trader/strategy.py:6`, `:56`)
  - a sealed block, 2023-01-01 to 2024-07-31, that no gate reads (`:13`, `:20`, `:202-203`)
  - Brier and calibration reporting (`services/ai_trader/calibration.py:21-53`)

### §15 UX and screens — Partial
- **Present:**
  - The F&O tab views (`FnoTab.tsx:501-505`).
  - A trust line on module cards that states source, as-of, mode (live, delayed, end of day or historical) and maker (reported, rules, model or AI) (`tradingdesk/trust.tsx:1-40`). The chain, for example, shows "NSE F&O bhavcopy … end of day" (`FnoTab.tsx:549`).
  - Paper writes say "No order is placed" (`tradingdesk/ScannerTab.tsx:735`, `tradingdesk/RiskDesk.tsx:1039`).
  - The Options Lab shows SEBI's F&O loss statistic (`screens/trading/parts.tsx:10`).
  - Broker settings are read-only (`screens/Brokers.tsx:1-12`).
- **Missing screens from §15.1:**
  - Historical Replay Lab, Shadow Mode Monitor, Live Trading Desk, Risk Control Center and Agent Certification Center.
  - Audit and Decision Replay is only partly present: `screens/OpsAudit.tsx:1-13` shows the account's audit trail and states that the backend "keeps no run records to replay".
- **Missing behaviours from §15.2:** a visible kill switch, and plain-language reasons for a rejected structure (the payoff summary shows rejection codes †).

### §16 APIs — Partial

| PRD route | Nearest existing route |
|---|---|
| `GET /market/options-chain` | `GET /api/fno/{symbol}/chain` |
| `GET /market/futures-intelligence` | `GET /api/fno/scan/buildup`, `GET /api/fno/{symbol}/futures` |
| `GET /market/regime` | Desk regime, served by `routes/macro.py:159` |
| `POST /strategies/payoff` | `POST /api/desk/strategy/payoff` |
| `GET /risk/status` | `GET /api/risk/status` |
| `POST /risk/kill-switch` | `PUT /api/risk/kill-switch` (also `PUT /api/risk/halt`) |
| `GET /audit/decisions/{id}` | `GET /api/risk/decisions` (a list, covering the AI trader and blocked desk trades) |
| `/strategies/validate`, `/strategies/scenarios`, `/ai/proposals`, `/research/backtests`, `/paper/sessions`, `/shadow/sessions`, `/orders/authorize`, `/orders`, `/certification/*` | None (route grep over `routes/` and the DaaS routers) |

### §17 Data model — Partial (2 exist, 15 partial, 18 missing †)

| Status | PRD entities and where they live |
|---|---|
| Exists | `broker_account` → `broker_accounts`. `kill_switch_event` → `risk_control_audit` (append-only by convention). |
| Partial | **Market data and instruments:**<br>• `market_data_snapshot` → `kite_live_snapshot` (latest only, 72 h) and `kite_live_close` (one per day); no `data_snapshot_id` anywhere.<br>• `instrument_master_version` → daily lot size per contract in `fno_bhavcopy`, and the F&O-eligible flag per day in `security_reference_daily` (from 2026-10-12); the Kite NFO list is never stored.<br>• `options_chain_snapshot` and `futures_snapshot` → `fno_bhavcopy`, end of day only.<br>**Strategies and research:**<br>• `strategy_template` → in code (`strategy_plan/templates.py`).<br>• `strategy_definition` and `strategy_leg` → `desk_strategy_plans` and legs inside `desk_paper_trades`.<br>• `margin_estimate` → only inside a saved plan.<br>• `backtest_run` → JSON files for F&O, plus the equity `strategy_runs` table.<br>• `backtest_trade` → equity `strategy_trades` only.<br>**Positions, risk and audit:**<br>• `position_snapshot` → holdings history only; positions are read live and never stored.<br>• `risk_policy` → `risk_controls` plus `POLICY_VERSION`.<br>• `risk_decision` → `risk_decisions`, for the AI trader, kill-switch denials and the journal.<br>• `model_version` → non-F&O models only.<br>• `audit_event` → `audit_log`, which is a data-access log. |
| Missing | `market_regime_snapshot`, `strategy_proposal`, `pricing_result`, `greeks_snapshot`, `scenario_result`, `backtest_event`, `paper_session`, `paper_order`, `paper_fill`, `shadow_decision`, `live_order`, `live_fill`, `risk_event`, `agent_version`, `certification_record`, `certification_test_result`, `broker_adapter_version`, `incident_record` |

### §18 Security, reliability, observability — Partial
- **Secrets:** broker tokens are AES-256-GCM encrypted (`services/brokers/sessions.py:321-325` †).
- **Reported separately:** findings on secret storage, backup coverage, LLM input handling, endpoint authentication and authorization were reported to the owner separately, because this repository is public. PRD v2.1 tracks them as P0.6.
- **Roles:** the roles are user, advisor, support and admin (`deps.py:116-150` †). There are no risk-manager, approver or trader roles (PRD §4).
- **Idempotency:** `Idempotency-Key` is handled only for Plan Board plans and portfolio upload †. F&O and paper writes have none.
- **Observability:**
  - Present: feed status per source (`nidp.v_feed_status`), a Kite token alert, Grafana alert events † and Prometheus metrics †.
  - The data-quality rollup reads `NONE` for the F&O feed (§0 #5), because no validation run carries an `asset` †.
  - Three `row_count_min` BLOCK failures (2026-07-30, 08-27, 08-28) did not stop those sessions from being stored and served: no bhavcopy reader checks validation results, `certified_dates` or `v_publish_gate` †.
  - There are no alerts on kill-switch activations or risk rejections †.
  - Missing: agent proposal and rejection rates, OMS latency, slippage and drift.
- **Fail-closed behaviour:**
  - The plan engine blocks prices older than 4 days and marks a stale chain as not actionable (`services/strategy_plan/rules.py:23-24`, `plan.py:190-193` †).
  - The other F&O routes do not check freshness †, and the governor fails open (§13).

### §19 Acceptance criteria

| PRD §19 criterion | Status | Evidence |
|---|---|---|
| Critical data is timestamped and provenance is retained | Partial | Rows carry source, run id and load time, but a reload overwrites them †. The UI trust line shows source and as-of. |
| Stale or incomplete data blocks affected decisions | Partial | The plan engine blocks stale prices †. Three BLOCK-failed sessions are served †. The governor skips unknowns. |
| Historical instrument metadata is point-in-time correct | Partial | Daily lot size per contract †. Eligibility history only since 2026-10-12 †. No versioned instrument master. |
| Backtest replay is deterministic and reproducible | Partial | The futures-signal studies pin the code commit and frozen settings (`docs/FO_STAGE_B2_FINDINGS_20261023.md:3`). No options replay. |
| Lookahead and leakage tests pass | Partial | Poisoned-rows and no-lookahead tests exist for the futures studies, and the F&O test group passed (§0 #3). |
| Costs, spreads, slippage and partial fills are modeled | Missing | A flat assumed 0.15% round trip. The payoff uses slippage % plus flat brokerage. |
| OOS and walk-forward evaluation are available | Partial | Chronological discovery, validation and untouched test splits. No walk-forward for F&O. |
| Baseline and ablation comparisons are included | Partial | OI-only, price-only and random-pool baselines in the ranking study. No AI to ablate. |
| Every proposal conforms to the structured schema | Missing | No AI proposals exist. |
| Invalid legs, contracts and quantities are rejected | Partial | Mixed expiries and undefined risk are rejected †. The client's lot size is not checked †. |
| Payoff, max loss/profit, breakevens, Greeks and margin are independently calculated | Partial | Deterministic payoff and Black-76. Margin is in a separate route and missing from the payoff payload. |
| AI can return no-trade | Partial | The deterministic engine returns `no_trade`, `wait` and `insufficient_data` †. No AI. |
| AI cannot execute directly or change policy | Partial | No order code, and the copilot has no tool calling †. A third-party trading-platform integration sits outside the risk engine (§5). |
| Explanations are traceable to evidence | Partial | Evidence ledger and trust lines. The copilot's number check only warns †. |
| Risk engine governs every order path | Missing | The governor runs only on AI-trader signals and confirm. F&O paper and journal fills are not governed. |
| Drawdown, loss, margin, exposure and quantity limits are enforced | Partial | AI-trader cash only. Drawdown is unknown while F&O is open. No margin limits. |
| Kill switch is accessible and backend-enforced | Partial | Backend-enforced on three paper paths. No UI. |
| Duplicate submissions are prevented | Partial | AI-trader tickets have a unique index †. Desk paper trades do not †. |
| Partial fills, timeouts and unknown broker states are safely reconciled | Absent by design | No orders. |
| Multi-leg interim risk is controlled | Absent by design | No orders. |
| Audit trail captures decisions, approvals and order state changes | Partial | `risk_control_audit` and `risk_decisions` (blocked desk trades only †). No order states. |
| Certification is scoped and versioned | Missing | Data-date certification only. |
| Paper/shadow evidence meets preregistered criteria | Missing | No preregistered paper criteria for F&O. The forward test has never recorded. |
| Critical fault-injection tests pass | Missing | None for F&O. |
| Live authorization checks certification on the backend | Missing | No live authorization. |
| Any relevant version/scope mismatch blocks execution | Missing | No execution path. |
| Suspension and revocation are tested | Missing | No certification lifecycle for F&O. |

### §21 Live readiness gate — Missing
- No order path exists, so none of the 12 conditions is enforced on an order.
- Inputs that do exist:
  - per-feed data freshness (condition 6), which is not a gate
  - deterministic payoff and Greeks, and the broker margin calculator (condition 7)
  - the AI-trader governor's portfolio checks for cash (condition 8)
  - the per-user kill switch on the paper paths (condition 11)

## 3. Defects and contradictions found
These are fixable now and do not depend on the PRD roadmap.

1. **F&O paper close never releases reserved capital**, and P&L never reaches paper cash (§11).
2. **F&O paper exits run only when the paper-trade list is opened.** The evening job skips them (§11).
3. **Drawdown halt cannot fire while any F&O structure is open** (§13).
4. **The kill switch has no UI.** Journal ENTRY fills bypass it, and the governor fails open on unknown inputs (§13).
5. **A third-party trading-platform integration sits outside the risk engine** (§5, §12). Details were reported privately.
6. **Security and operations items** were reported privately (§18).
7. **Margin contradiction on the Desk builder:** "Margin (estimate) —, no margin source exists" sits beside the working broker-margin strip (§8).
8. **Stale "Record as paper trade" text** in the Desk builder, which says paper trades hold long shares only (§8).
9. **The forward test has never recorded**, because the nightly job was never installed (§11).
10. **Intraday futures snapshots are coded but empty on staging**; cause not established (§6.2).
11. **The data-quality rollup is blind** (`last_dq_status NONE`), and BLOCK-failed sessions are served (§18).
12. **Stale docstrings:**
    - `services/kite_live_feed/fno_quotes.py:4` and `routes/live_quotes.py:202` say no futures contract is subscribed; the feed subscribes near-month futures †.
    - The `services/desk_trading.py` docstring still describes the old gap-fill rule †.
13. **Tests:**
    - Two stale tests in `tests/test_desk_paper_sim.py`.
    - Eight tests that need `pytest-asyncio`.
    - An assertion that can never fail at `tests/test_risk_controls.py:172` (`action != "allow"`, where "allow" is not one of the governor's actions, `risk_governor.py:18`).
    - The strategy-graphs Playwright spec depends on a build flag set by a script that is not in the repo.
    - TC-F3 in the smart-money spec is date-dependent †.
    - `nidp/services/copilot_agent/tests/test_risk_tools.py` is order-dependent: it fails 42 tests when run in a group but passes all 44 alone †.
14. **Desk paper trades have no duplicate protection** †. A futures-only structure is labelled `defined_risk: True` (§11).

## 4. Strengths to keep
- Pre-registered research, with honest "no validated edge" findings published in the repo.
- Point-in-time tests that inject poisoned future rows. Every unvalidated threshold is labelled `research_setting_not_validated` †.
- Deterministic pricing and payoff, the broker margin and charges calculator, and an explicit `insufficient_data` / `no_trade` / `wait` vocabulary.
- An independence boundary: the governor imports no strategy or AI code, the broker adapters are read-only, and the copilot cannot call tools.
- Trust lines that say where every figure came from and how fresh it is.
- The AI Trader's stage ladder, sealed holdout and calibration reporting, ready to generalise into F&O certification.

## 5. What blocks the PRD, in order
1. **Intraday options data:** option contracts on the feed, stored bid/ask and timestamped chain snapshots (§6.3, §10, §11).
2. **IV history and a Greeks provenance store** (§6.5, §10).
3. **A snapshot and decision store** (`data_snapshot_id`, proposal, pricing result, risk decision, audit event) (§14, §17, §21).
4. **An F&O-aware, fail-closed risk engine on every write path**, plus a UI for the kill switch (§13).
5. **An options event-driven backtester with a fill and cost model** (§10, and the evidence for §9).
6. **Conservative paper and shadow mode**, with the forward-test job actually running (§11).
7. **An agent with a versioned proposal schema**, only after 1–6 (§7).
8. **Certification, then the Kite Connect order adapter with reconciliation**, then restricted live (§12, §14, §21).

## 6. Suggested sequencing (maps to PRD §20)
- **Now (not roadmap):** fix the defects in §3, starting with items 1–6.
- **Phase 0:** blockers 1, 3 and 4, and wire the data-quality status into the F&O readers.
- **Phase 1:**
  - Net charges into the payoff.
  - Show per-leg Greeks.
  - One builder engine: make the Options Lab call the server payoff, or keep both on the same tested arithmetic.
  - Margin buffer and free funds.
  - Calendars, if wanted.
- **Phase 2:** blocker 5, starting from the pre-registered Stage B3 study.
- **Phase 3:** blocker 6.
- **Phase 4 and later:** certification, then the Kite Connect adapter, then restricted live, after the regulatory and broker review in §7.

## 7. Regulatory and broker review (Kite Connect)
- **Execution through Kite Connect means automated or API order placement for retail users.** These need a compliance review before any order path is built, and are listed here to confirm, not as conclusions:
  - SEBI and exchange rules for retail algorithmic trading as they apply to API orders (algo registration and identification, order-rate thresholds, static-IP requirements).
  - Zerodha's requirements for a platform that places orders on users' behalf.
- **The repo's own docs already list these review items:** `docs/AI_TRADER_BUSINESS_REQUIREMENT.md:224`, `:229` †; brokers read-only by design (`docs/SECURITY_PRD.md:154` †); no order placement (`docs/RISK_CONTROL_INVENTORY.md:9-23` †).
- **Route it through the `domain-expert-analyst` role.** This report does not assess compliance.

## 8. Not covered / UNVERIFIED
- **Playwright scope:** the specs run against mocked APIs, so they show UI behaviour, not live data. The strategy-graph spec passes only with a build flag that the standard recipe does not set (§0 #9). The live spec `strategy-builder-live.spec.ts` (real staging, session cookie) was not run.
- **Runtime behaviour:**
  - Nothing was exercised against the staging API with a user session.
  - Whether staging runs exactly `origin/dev` was not checked.
  - Why `kite_live_intraday` is empty was not established.
- **Not reproduced by a test:** the F&O paper-reservation defect, the drawdown-halt defect and the journal-fill gap were found by reading the code.
- **Security items:** reported privately, with their own open questions.
- **Agent-read claims:** claims marked † were read by review agents and not re-checked by the author.
- **Policy, not code:** certification sample sizes (§14.5) and limit ranges (§13.3) are policy choices with no code-level answer yet.
