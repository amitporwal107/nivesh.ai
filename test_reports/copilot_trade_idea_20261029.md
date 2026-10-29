# Functionality Verification Report — Copilot: ask about a stock, get the trade idea when conditions favour it

- **Branch:** feat/copilot-trade-idea (from dev 783d7095), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-29
- **Author:** Claude (FULL_STACK_DEVELOPER + DOMAIN_EXPERT_ANALYST + QA_ENGINEER)
- **Environment:** backend tests in the staging backend image (`--network none`); mocked Playwright on a production build; staging after merge
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Owner, 29 Oct:
- "We will have top AI recommendations for each category top 10 stocks and F/O and trading plan as we have currently."
  The Top 10 lists and their plans stay exactly as they are. On screen they stay "ideas", per the owner's 25 Oct decision
  (SEBI wording).
- "User can ask any questions about a stocks and we can put idea how to trade if conditions are favourable and signals
  are recieved."

What changes, with no new screens:
- **When it triggers.** A Copilot question about a stock is a *trading question* when any of these holds: the Trader
  persona, the trading desk's Copilot panel, or words such as plan / entry / stop / trade / setup / breakout.
- **What the route builds.** The chat route builds the desk's own StrategyPlan for that stock, as the signed-in user,
  with `POST /api/desk/strategy/plan`'s code: same inputs, same sources, same rules, same risk-service sizing. It stores
  the TradePlans, exactly as the desk does.
- **Which plans get a card.**
  - Plan status `plan` (a setup) or `wait` (a setup whose entry waits for a confirmation): the answer starts with a
    **trade-plan card** that shows the desk's own DecisionCard for the plan. The card has "Open in Strategy Lab" (the
    plan's paper-trade ticket, `&tp=<plan_id>`) and a chip to plan the opposite direction.
  - `no_trade` / `insufficient_data`: no card.
- **What the AI says.** The stock analyst is given the plan's facts as data (the desk's `explain_plan_context`). For a
  card, it adds a section "How to trade it (an idea, not a recommendation)": why the setup exists, the entry trigger and
  that entry waits for it, the invalidation level, the capital at risk, the targets, and what to do next. With no card,
  it says why there is no setup and what would have to change. It quotes only the plan's figures and never invents a
  price.
- **What is assumed, and said.** A direction the user did not state is taken as long (the cash scanner's side) and
  labelled "assumed". Sizing is the account's saved risk profile (the risk service). Capital and risk-% overrides in
  words are for the ask-back step (next).

## Test Cases
> Authored UP FRONT (2026-10-29, before implementation). Files:
> - B = `backend/tests/test_copilot_trade_idea.py`
> - R = the same file, the stream route on the harness of `test_broker_contract_chart.py`
> - F = `frontend-v5/e2e/tests/copilot-app-trade-idea.spec.ts`

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TI-1 | B | Which questions are trading questions | unit | Trader persona or desk panel → yes. Investor persona: "Is Reliance a good long-term holding?" → no; "How should I trade TVSMOTOR?" / "entry and stop for TCS" / "trading plan" / "breakout" → yes || PASS |
| TI-2 | B | Direction from the words | unit | upside / long / bullish / breakout / buy → bullish (stated). fall / short / bearish / sell / put → bearish (stated). range / sideways → neutral (stated). Nothing said → bullish, **not stated** || PASS |
| TI-3 | B | Horizon from the words | unit | intraday / today → intraday (the builder answers insufficient_data: no intraday history); otherwise positional || PASS |
| TI-4 | B | Builder answers `plan` with 3 candidates | unit | Widget `trade_plan`: preferred plan first, at most 3 ids, symbol, status, direction + stated flag, horizon, data as-of, defaults applied. The candidates' TradePlans are stored. The context carries the plan facts, the assumed-direction note and the section rules || PASS |
| TI-5 | B | Builder answers `wait` | unit | Widget with status wait and the builder's reasons || PASS |
| TI-6 | B | Builder answers `no_trade` / `insufficient_data` | unit | No widget; the context carries the reasons, so the answer says why and what must change || PASS |
| TI-7 | B | The build raises or times out | unit | No widget; the context says no plan could be built now; never raises || PASS |
| TI-8 | B | The builder refuses the inputs | unit | None (nothing said about a plan) || PASS |
| TI-9 | R | A trading question naming a stock | api | The first widget frame is `trade_plan`, sent before any token. The engine's own card is dropped, and the saved turn's widget is `trade_plan`. The engine's last human message carries the wrapped `trade_plan` data block. The engine is pinned to the stock analyst || PASS |
| TI-10 | R | A question that is not a trading question | api | Unchanged: the engine's own card; the builder is never called || PASS |
| TI-11 | R | A question asked from a broker position | api | The position card wins; the builder is never called || PASS |
| TI-12 | B | The stock analyst's instructions | unit | Its system prompt holds the trade-plan rules: the section title, "an idea, not a recommendation", only TRADE_PLAN figures, entry waits for confirmation, invalidation, capital at risk, no card → why not || PASS |
| TI-13 | F | The `/app` thread shows the card | e2e | Header (symbol, "Setup found", "long · assumed"), the desk's DecisionCard read by id (entry / stop / targets), the alternatives, data as-of, caveat || PASS |
| TI-14 | F | "Open in Strategy Lab" | e2e | Goes to `/v5/app/trader/desk?tab=trade&view=lab&sub=build&tp=<plan_id>` || PASS |
| TI-15 | F | "Plan the opposite direction" chip | e2e | Asks "Plan a bearish trade for TVSMOTOR instead" || PASS |
| TI-16 | F | A `wait` card | e2e | "Waiting for confirmation" and the builder's reasons || PASS |
| TI-17 | F | The desk's Copilot panel | e2e | The card is shown inline in the panel (not only "open the full thread") || PASS |
| TI-18 | regression | CI allowlist backend dev vs branch; Copilot thread, dock and desk specs vs dev | unit+e2e | No new failure || PASS |
| TI-19 | staging | After merge: a real trading question on staging with a session | api+data | The card and the plan ids; TradePlans stored in Mongo `trade_plans` || PENDING (needs merge + a session) |

## Tests run (real output, 2026-10-29, branch feat/copilot-trade-idea)
Backend: image `nivesh/backend:staging`, tree read-only, `--network none`. Frontend: Playwright 1.60 on a production build
(`VITE_BASE=/v5/ vite build` + `vite preview`), `--network none`.
- **TI-1 … TI-12:** `pytest tests/test_copilot_trade_idea.py` → `35 passed, 2 warnings in 8.03s`. With the harness it
  borrows (`tests/test_broker_contract_chart.py`): `129 passed`.
- **TI-13 … TI-17:** `playwright test e2e/tests/copilot-app-trade-idea.spec.ts` → `5 passed (10.4s)`.
  - The first run failed TI-17 only: the desk docks the Copilot from 1400 px, and the test had not set that width.
  - Fixed in the test (`setViewportSize 1440×900`, as `copilot-app-desk.spec.ts` TC-4 does). No product change.
- **tsc:** `npx tsc --noEmit -p tsconfig.json` → exit 0.
  - The first run found `unknown` widget data rendered in JSX in CopilotDock; it is now typed as `TradeIdeaData`.
- **TI-18, backend regression (CI allowlist, same image):**
  - `dev` 783d7095 (265 files) → `3 failed, 6912 passed, 28 skipped`;
  - branch (266 files, + `test_copilot_trade_idea.py`) → `3 failed, 6947 passed, 28 skipped`;
  - the same 3 failures on both, which predate this branch (`test_cas_api_client` ×2, `test_nidp_stamp_broadcast_at` ×1);
  - +35 = the new suite. **No regression.**
- **TI-18, frontend regression:** every `/app` spec that renders the thread, the dock or the composer, plus the desk shell
  (advisor, contract-chart, broker-paper, desk-shell, desk-market-overview, desk, screens, copilot-app), with the new
  spec → `2 skipped, 189 passed (2.5m)`, **0 failed**. Not run: `copilot-app-live` and `copilot-app-shots`, which target
  staging and need a session and network.

## Inputs required from user
- The merge (per-PR approval). A session token for TI-19.

## Verdict: BLOCKED
