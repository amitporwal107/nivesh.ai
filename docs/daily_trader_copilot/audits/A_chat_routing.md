# A — How the Copilot chat answers the owner's 15 trader questions today (origin/dev a4294830)

Audit date 2026-10-30. Read-only. Every ref is `path:line` on `origin/dev` (read with `git show origin/dev:<path>`).

**Method and limits.**
- Code reading.
- I also ran dev's own pure routing functions (`intent_patterns.match_agent`, `symbol_resolver.resolve_symbol`, `copilot_trade_idea.is_trade_question` / `direction_of` / `horizon_of`) on every question, in an isolated scratch copy. That run used no LLM, no network and no DB.
  - Script: `/tmp/claude-1002/-home-deploy-nivesh-ai/3d5d2da4-dd5c-4e4e-9753-e2b535562f89/scratchpad/q15/route_probe.py`
  - Inputs: `questions.txt` and `questions_phase.txt` in the same folder.
  - The routing columns below are that run's real output.
- **Not observed:**
  - which agent the LLM fallback classifier picks (marked "LLM-decided");
  - any live answer text;
  - whether the staging deploy equals dev.

---

## 0. How chat works today

### 0.1 Two chat surfaces, one endpoint
Both surfaces call `POST /api/chat/stream` (`backend/routes/chat.py:1519`).

| Surface | What it sends | Ref |
|---|---|---|
| **/app chat** (CopilotApp composer and home) | `persona = mode` ("investor" / "trader" / "advisor", the mode toggle). No `surface`. A broker F&O position row also sends `position`. | `frontend-v5/src/pages/CopilotApp/index.tsx:100-105`, `screens/desk/BrokerPositions.tsx:353` |
| **Trading-desk Copilot dock** | `persona` = desk wording switch ("trader" / "investor") **and** `surface: "trading_desk"`. Own thread in sessionStorage. | `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/CopilotDock.tsx:30-34`, `TradingDesk.tsx:414` |

The dock renders only the `trade_plan` card inline. Any other widget shows as "This answer has a result card — open the full thread ›" (`CopilotDock.tsx:97-123`).

### 0.2 `stream_chat`, step by step (`backend/routes/chat.py:1519-1890`)

1. **Advisor mode is off for persona "trader" / "investor"** (`chat.py:94-109`, `1528`). A trader therefore always takes the single-portfolio LangGraph path (`route_investor`, `chat.py:1541-1543`).
2. **Desk persona.** `desk_persona` is set only when `surface == "trading_desk"`; unknown values read as "trader" (`chat.py:112-126`, `1532`).
3. **Position card.** A question asked from a broker position row gets a `broker_contract_chart` card. The position facts are read live from the broker (P&L and breakeven are worked out) and passed to the engine as delimited data (`chat.py:152-240`, `243-300`, `1550-1553`).
4. **Trade-idea pre-step** (`chat.py:1554-1575`; `backend/services/copilot_trade_idea.py`):
   - `is_trade_question` is **True for every message when persona == "trader" or desk_persona == "trader"**. Otherwise it needs a trade word: trade, entry, stop-loss, target, breakout, setup, swing, intraday, spread… (`copilot_trade_idea.py:39-43`, `65-69`).
   - Then `symbol_for(message)` runs the stock resolver (`copilot_trade_idea.py:95-102`). Without a symbol there is no trade idea.
   - With a symbol, `build()` builds the desk's own StrategyPlan exactly like `POST /api/desk/strategy/plan` (`copilot_trade_idea.py:229-267`):
     - inputs from `normalise_inputs`;
     - ~20 sources from `collect_snapshots` (`services/strategy_plan/sources.py:380-410`): regime, sector returns, indicators, patterns, scan snapshot, features, financials, announcements, events, corporate actions, F&O buildup, futures, expiries, option chain with Black-76 IV/Greeks, calibration, AI-scanner bucket/picks, the user's holdings, shareholding, bulk/block deals, Chartink hits, optional broker quotes;
     - stores the TradePlans;
     - sizes the preferred plan through the risk service `risk_gate.plan_sizing.size_for` (`copilot_trade_idea.py:270-277`).
   - The card (`widget_type: "trade_plan"`) is sent **only when the plan status is `plan` or `wait` and a candidate carries a TradePlan** (`copilot_trade_idea.py:116-146`). The plan's facts go to the engine as a `TRADE_PLAN` data block either way (`chat.py:1695-1699`).
   - When a trade idea exists, **the engine is pinned to `stock_analyst`** whatever the router would say (`chat.py:1570-1575`).
5. **Graph:** `intent_node → one specialist node → compliance_node → END` (`backend/nidp/services/copilot_agent/graph.py:61-147`). The Mongo chat history (last 20 messages) is injected into LangGraph messages (`chat.py:1683-1701`).

### 0.3 Router (`nodes/intent.py`, `nodes/intent_patterns.py`)
- A pinned agent skips classification (`intent.py:159-170`). Otherwise the regex table runs, first match wins (`intent_patterns.py:456-500`):
  - **PRE:** backtest, strategy-lab, builder, screener, cap, fund-overlap, stock-ownership, regulatory, stocks-insights, policy;
  - then numeric-screen and the single-stock gate;
  - **POST:** risk, goal, portfolio, recommendation, MF, market, stock.
- No match → **LLM classifier** with a 9-agent list (`intent.py:85-139`). It defaults to `market_analyst` on any error.
- **Key routing defect.** `_P_STOCK` (`intent_patterns.py:67-76`) is compiled with `re.IGNORECASE`, so `(?:what|how|…)\s+(?:is\s+)?[A-Z]{2,10}` matches *any* "What are…", "How much…", "What did…", "What should…".
  - Generic trader questions therefore fall through to `stock_analyst`.
  - With no stock named, that node returns the fixed reply "Which stock would you like me to look at?…" (`nodes/stock.py:146-165`).
  - This hits Q6 (no name), Q7 (no name), Q12, Q13, Q14 and Q15.
- **Second defect: symbol pass-through.** `resolve_symbol` step 5 passes through **any upper-case token** that is not on a stop-list (`copilot_tools/symbol_resolver.py:197-200`).
  - In the Trader persona this turns "F&O", "GIFT", "PCR" and "P&L" into "symbols" (probe output below). `normalise_inputs` accepts them (`services/strategy_plan/plan.py:30`: `^[A-Za-z0-9&\-]{1,20}$`).
  - A plan is built for a non-stock, and `trade_idea` is truthy.
  - Result: the turn is **pinned to `stock_analyst`**, overriding a correct `market_analyst` / `portfolio_analyst` route (`chat.py:1574-1575`).
  - The unit tests mock `symbol_for` (`backend/tests/test_copilot_trade_idea.py:242`), so this path is untested.

### 0.4 Specialist nodes: data each one reads
No node binds LLM tools. Each node runs a fixed set of fetches, then makes one LLM call. A `grep` for `bind_tools` / `@tool` / `tool_choice` over the copilot code finds nothing.

| Node | Fixed fetches (function → source) | Widget |
|---|---|---|
| `market_node` (`nodes/market.py:66-117`) | `copilot_tools.market_research.get_market_research` (`market_research.py:559-614`). DaaS `/v1/snapshots/market` (indices, VIX, breadth, FII/DII cash, G-Sec), `/v1/market-pulse/movers?cap=large`, `/v1/desk/sector-returns`, `/v1/holidays`, `/v1/events/calendar` (next 5 sessions), `/v1/snapshots/market/recent` (5-session trend), `/v1/macro/rbi-yields`, `/v1/desk/fno-buildup`, `/v1/fno/{NIFTY,BANKNIFTY}/expiries` + `/chain` → `routes.fno.summarise_chain` (PCR, max pain, heaviest call/put OI strike, spot), Yahoo global snapshot via `positional_engine.nse_live.get_global_snapshot`. All **end of day** (`DATA_MODE`, `market_research.py:66`). | `market_detail` |
| `stock_node` (`nodes/stock.py:133-242`) | `technical.get_technical_analysis` (DaaS stock features: RSI, MACD, SMA, `vol_z20`, 52w distance, `pivot_breakout_flag`, `technical.py:115-149`), `fundamental.get_fundamental_analysis`, `company_financials.get_company_financials` + `get_shareholding_analysis`, `instrument_research.get_stock_research` | `instrument_detail` (suppressed when the trade card is sent, `chat.py:1724-1732`, `1792`) |
| `recommendation_node` (`nodes/recommendation.py:255-528`) | MF screener when the text has fund/sip words. Otherwise `stock_intelligence.nidp_stock_screener` → `/v1/stocks/screener`, with NL filters on ROE, PE, D/E, growth, RSI, momentum, cap, Nifty universe (`recommendation.py:41-150`). **No volume / breakout / 52w-low / buildup / RS filter.** | `stock_screener` / `fund_comparison` / strategy_lab / portfolio_builder seeds |
| `risk_node` (`nodes/risk.py`) | `copilot_tools.risk`: `get_portfolio_risk_pra`, `get_risk_suitability`, `get_portfolio_var`, `get_stress_scenarios`, over long-term holdings (`risk.py:84-143`) | `risk_assessment` / `stress_test` |
| `portfolio_node` (`nodes/portfolio.py`) | `copilot_tools.portfolio` over Mongo `holdings` / `portfolio_holdings` (CAS) (`copilot_tools/portfolio.py:56-66`): XIRR, rebalance, concentration, tax, overlap | `portfolio_overview` etc. |
| `stocks_insights_node` | Exchange filings + quarterly financials. **Hard no-advice rule:** refuses buy/sell/hold (`nodes/stocks_insights.py:77-82`) | `stock_insights` |

Nodes call the LLM with **system prompt + the latest user message only** (e.g. `stock.py:212-218`, `market.py:100-103`). The injected history is not passed to the specialist LLM. Symbol resolution reads only the current message (`stock.py:141-144`), so a follow-up "Is this stock a buy now?" does not inherit the stock.

### 0.5 Persona handling
- `state.persona` comes from Mongo `user_profiles.persona` (default `retail_investor`), **not** from the request's `persona` (`persona_loader.py:18-61`; `chat.py:1703-1720`).
  - The /app Trader toggle therefore does **not** change the framing. Framing is "Active Trader…" only if the stored product persona is `active_trader` / `swing_trader` / … (`persona_framing.py:36-52`).
- `desk_persona` (desk dock only) appends the desk PRD §9.4 answer structure (`persona_framing.py:102-118`, `126-141`):
  - direct answer, evidence with source, as-of, bull/bear factors, uncertainties, invalidation, sources, where to look on the desk;
  - "do not tell the user to buy or sell".
  - /app Trader mode does **not** get this structure.
- The request's `persona` drives two things only:
  - advisor-mode off (`chat.py:1528`);
  - "every message is a trade question" (`copilot_trade_idea.py:67`).
- The risk profile reaches nodes as a category string (`persona_loader.py:54-57`) and through the trade plan's risk-service sizing.
  - The chat route also builds a holdings block and a risk-profile line, but in the trader path **they are never used**. `portfolio_context` / `risk_context` at `chat.py:1623-1636` are consumed only by the advisor branch at `chat.py:1819-1825`.

### 0.6 Guardrails and SEBI wording
- **Prompt rules:**
  - `ANTI_HALLUCINATION_RULES` is in every node.
  - Stock node **TRADE PLAN RULES** (`stock.py:41-59`): "How to trade it (an idea, not a recommendation)"; quote only TRADE_PLAN figures; never "buy now"; no "recommend / pick / suggested trade".
  - The stock node's own style still demands **"Verdict — BULLISH / BEARISH / NEUTRAL"** (`stock.py:34`).
  - The recommendation prompt says "actionable investment ideas… Max 5 picks; bold the top pick" (`recommendation.py:20-33`). This conflicts with the owner's "ideas, not picks" wording rule.
- **Q6-style "should I buy X?".** In the investor persona `_P_STOCK_INSIGHTS` sends it to the filings node, which refuses with no advice (`intent_patterns.py:166-170`, `stocks_insights.py:77-82`). In the **Trader persona with a named stock**, the trade-idea pin overrides that and gives stock analysis plus a trade-plan card (probe P3a/Q6b).
- **`compliance_node`** (`nodes/compliance.py:169-221`) does several things:
  - trims to 400 words;
  - strips inline disclaimers;
  - scrubs advice words, including bare "bullish" / "bearish" and "you should buy/sell/book/exit" (`compliance.py:145-166`);
  - adds a grounding caveat;
  - supplies follow-ups.
- **The scrubbed text is not what the user sees on the normal streaming path** (code reading; not runtime-verified):
  - `stream_chat` builds the answer from streamed LLM tokens (`chat.py:1751-1761`).
  - It uses the compliance-edited `final_resp.text` only `if not prose` (`chat.py:1780-1781`, `1802-1809`). The comment at `1798-1801` confirms tokens normally stream.
  - So the advice scrub, the grounding caveat and the 400-word cap do not reach the streamed or saved answer. Only the follow-up chips do.
- **UI wording.** Trade card footer: "An idea to review, not a recommendation; nothing is sent to a broker" (`TradePlanChatCard.tsx:119-122`). Dock: "Educational research, not investment advice" (`CopilotDock.tsx:130`).

### 0.7 What chat cannot reach (grep over copilot_agent, copilot_tools, chat.py, copilot_trade_idea.py)
- **Paper trades:** `/api/desk/paper-trades`, `routes/desk_trading.py:591`; `/api/paper-trades/*`, `routes/paper_trades.py`.
- **AI scanner Top 10 / watchlist:** `/api/desk/ai-watchlist`, `/api/positional/watchlist|picks`. Reached only per symbol, inside the plan builder (`sources.py:246-265`).
- **Smart Money:** DaaS `routers/smart_money.py`.
- **Move-odds:** `/api/move-odds/*`.
- **Trade journal:** `/api/positional/journal`.
- **Idea scorecard:** `/api/desk/idea-scorecard`.
- **Risk-gate day state:** daily/weekly loss, open risk, sector, correlation checks (`services/risk_gate/service.py:34-54`). Reached only as the per-plan sizing on the card.
- **Chartink:** used only per symbol inside a plan.
- **Desk option-chain summary with `expected_move` and ATM IV:** `routes/fno.py:88-89`, `528`, `848`. The chat market node uses DaaS chain + `summarise_chain`, which has no expected move and no IV (`routes/fno.py:289-311`).

### 0.8 Tests that touch this
- `backend/tests/test_copilot_trade_idea.py`:
  - TI-1…TI-12 cover trade-question detection, direction, horizon, card/no-card, the stock-analyst rules, and that the Trader persona makes any stock question a trade question;
  - `symbol_for` is mocked.
- `backend/tests/test_desk_copilot_prompt.py`: desk surface → desk_persona → PRD §9.4 structure.
- `backend/nidp/services/copilot_agent/tests/*`: graph and e2e agents.
- **No test or e2e spec exercises any of the 15 questions as worded.** A grep for each phrase found none.
- No e2e covers the chat `trade_plan` card (no `tpc-*` testid in `frontend-v5/e2e/tests`).
- The e2e chat specs mock `/api/chat/stream` (e.g. `copilot-app-broker-paper.spec.ts:51`).

---

## Routing probe output (Trader persona; real output of dev's functions)

`agent` = regex result ("LLM-fallback" = no regex hit, LLM decides). `sym` = what `symbol_for` returns. `tradeQ` = `is_trade_question(msg, "trader", None)`.

```
Q1  market_analyst  POST:market 'market'             sym=None           tradeQ=True
Q2  LLM-fallback    —                                 sym=None           tradeQ=True
Q3  LLM-fallback    —                                 sym=None           tradeQ=True
Q4  LLM-fallback    —                                 sym=None           tradeQ=True
Q5  LLM-fallback    —                                 sym=None           tradeQ=True
Q6  stock_analyst   POST:stock 'this stock'           sym=None           tradeQ=True
Q6b "Is RELIANCE a buy now?"  stock_analyst 'buy now' sym=RELIANCE(ticker) dir=bullish(stated)
Q7  stock_analyst   POST:stock 'What is the'          sym=None           tradeword=entry
Q7b "…for INFY"     stock_analyst                     sym=INFY           dir=bullish(ASSUMED)
Q8  LLM-fallback    —                                 sym=None           tradeword=trade
Q9  stocks_insights PRE:insights 'Should I book'      sym=None
Q9b "…hold TCS?"    stocks_insights                   sym=TCS → trade idea → pinned stock_analyst, dir=bullish(ASSUMED)
Q10 LLM-fallback    —                                 sym=F&O (passthrough!) → trade idea for "F&O" → pinned stock_analyst
Q11 market_analyst  POST:market 'Nifty'               sym=None
Q12 stock_analyst   POST:stock 'How much'             sym=None
Q13 stock_analyst   POST:stock 'What are'             sym=None           tradeword=trades
Q14 stock_analyst   POST:stock 'What should'          sym=None
Q15 stock_analyst   POST:stock 'What did'             sym=None           tradeword=trades
```

---

## Q1 — "What is the market view today?" → Direction, breadth, volatility, key levels
- **Today:**
  - Regex `_P_MARKET` routes it to `market_node` (`intent_patterns.py:49-65`). No symbol, so no trade idea.
  - `get_market_research()` reads the full end-of-day snapshot (§0.4). The `market_detail` card is pushed early (`market.py:93-96`).
  - The LLM answers in ≤200 words of plain text with "a one-line market sentiment call (bullish/bearish/neutral), justified by breadth + VIX + flows" (`market.py:47-50`).
  - The desk dock adds the §9.4 structure.
- **Covers:**
  - direction: Nifty 50 close and % change, 5-session Nifty %, sentiment line;
  - breadth: advances / declines and their 5-session change;
  - volatility: India VIX and its tone;
  - sectors ranked by 1D / 1W / 1M; FII/DII cash; global cues; next-5-session calendar;
  - index F&O positioning: PCR, max pain, heaviest call/put OI strikes.
- **Gap:**
  - **Key levels** are only option-OI proxies (max pain, heaviest OI strikes). No Nifty/Bank Nifty technical support/resistance or pivots in TOOL_DATA. `summarise_chain` computes `put_wall` / `call_wall` (`routes/fno.py:308-309`), but `_fno_part` prints only the heaviest strikes (`market_research.py:424-425`).
  - All **end of day**; nothing intraday or live (`market_research.py:66`; the prompt forbids calling a figure live).
  - Bank Nifty has no % change (`market_research.py:264-265`).
  - In /app the sentiment line is not scrubbed (§0.6).
- **Evidence:** `market.py:21-117`; `market_research.py:252-318`, `400-428`, `559-614`.

## Q2 — "Where is smart money moving?" → FII/DII flows, sector rotation, buildup signals
- **Today:**
  - No regex hit ("smart money" is in no pattern), so the **LLM classifier** decides. Its prompt maps "FII/DII, sector performance" to `market_analyst` (`intent.py:88-90`); the actual pick is not observed.
  - If it goes to `market_node`, the TOOL_DATA described in Q1 is used.
- **Covers (if market_node):** FII/DII cash net for the day and the 5-session sum; sector ranking (rotation proxy); index futures buildup label and stock-futures buildup counts (long buildup / short covering … counts over the F&O universe).
- **Gap:**
  - No **Smart Money service** data: DaaS `routers/smart_money.py`, AMC/MF deployment, FII/DII history, sector flow attribution. Not referenced from chat.
  - No per-stock buildup lists, only counts.
  - No MF flow data.
  - Routing to market_node is not deterministic.
- **Evidence:** probe Q2; `intent.py:85-139`; `market_research.py:227-246`, `402-412`.

## Q3 — "Which are today's top 5 opportunities?" → Ranked stocks with evidence and risk
- **Today:** **LLM-decided** route (no regex hit). Candidates:
  - `recommendation` ("buy/invest recommendations, stock screener") would run `nidp_stock_screener` with no filters: top-60 by market cap from the feature store (`recommendation.py:340-360`). The prompt is "Max 5 picks; bold the top pick". `top_n=5` is parsed as a slot (`intent.py:42`, `75-77`), but the recommendation node does not read it (not found in the node).
  - `market_analyst` would give top movers.
- **Covers:** a fundamentals/technicals screener table (Symbol, Score/10, Signal, RSI, PE, Key Reason) at best.
- **Gap:**
  - The desk's real "today's ideas" (AI scanner Top 10 in `ai_watchlist_days`, positional picks, Chartink hits, move-odds) are **not reachable from chat**.
  - No per-idea entry, stop or risk; no trade cards for a list.
  - The prompt's "picks / top pick" wording conflicts with the owner's "ideas, not picks" rule.
- **Evidence:** probe Q3; `recommendation.py:20-33`, `255-445`; §0.7.

## Q4 — "Which breakouts are confirmed?" → Entry zone, volume confirmation, invalidation
- **Today:**
  - **LLM-decided** route ("breakouts" plural does not match `\bbreakout\b` in `_P_STOCK`).
  - In Trader persona `is_trade_question` is True, but there is no symbol, so no trade idea.
  - If routed to `stock_analyst` → the "Which stock?" clarification. If `recommendation` → the generic screener.
- **Covers:**
  - Nothing cross-sectional.
  - Per stock (only when named, e.g. "Is the INFY breakout confirmed?", probe P3b): the technical tool's `pivot_breakout_flag` and `vol_z20`, plus a trade-plan card (status `plan` or `wait`, reasons, "would change if", entry trigger, stop/invalidation).
- **Gap:**
  - No breakout list; the screener has no breakout or volume filter.
  - The desk scanner's breakout buckets are not reachable.
  - "Confirmed" is not a field. The plan's `wait` status ("waiting for its confirmation") is the closest, per stock only.
- **Evidence:** probe Q4/P3b; `technical.py:127-136`; `copilot_trade_idea.py:116-146`.

## Q5 — "Which stocks have unusual volume?" → Relative volume, price change, delivery data
- **Today:** **LLM-decided** route. If `market_analyst`: top 5 gainers/losers by % (large cap) only. If `recommendation`: generic screener.
- **Covers:** top movers by price change.
- **Gap:**
  - No relative-volume ranking: `vol_z20` exists per stock in features (`technical.py:127`) but there is no cross-sectional query in chat.
  - No delivery % data anywhere in the chat tools; "delivery %" exists only as a routing cue word (`intent_patterns.py:398`).
- **Evidence:** probe Q5; `market_research.py:288-297`; `recommendation.py:41-86` (no volume metric).

## Q6 — "Is this stock a buy now?" → Buy/wait/avoid assessment with rationale
- **Today:**
  - **As worded ("this stock"):** `_P_STOCK` → `stock_analyst` → no symbol → fixed "Which stock would you like me to look at?" (`stock.py:146-165`). The previous turn's stock is not inherited (§0.4).
  - **With a name**, e.g. "Is RELIANCE a buy now?":
    - Trader persona → trade idea (direction bullish, *stated* by "buy") → pinned `stock_analyst`.
    - The answer has Technical / Fundamental / Quarterly / Smart Money / **Verdict BULLISH/BEARISH/NEUTRAL**, plus "How to trade it (an idea, not a recommendation)" if TRADE_PLAN is present.
    - The `trade_plan` card shows "Setup found" / "Waiting for confirmation"; with no setup there is no card and the prose says why.
  - **Investor persona, "Should I buy X?":** stocks_insights refuses ("can't give investment advice", `stocks_insights.py:77-82`).
- **Covers:** a buy/wait/avoid-*like* outcome (plan / wait / no setup) with rationale and invalidation, for a named stock.
- **Gap:**
  - No explicit Buy / Wait / Avoid label; by design no buy/sell call.
  - "Avoid" reasons appear only as the no-setup prose or the card's warnings.
  - Behaviour differs by persona and wording (deflection vs. plan).
  - The Verdict line is unscrubbed in streamed text (§0.6).
- **Evidence:** probe Q6/Q6b/P3a; `chat.py:1561-1575`; `stock.py:22-59`; `TradePlanChatCard.tsx:72-81`.

## Q7 — "What is the entry, target and stop-loss?" → Trade plan with risk-reward
- **Today:**
  - No stock named → `stock_analyst` → clarification. Trade words are present, but there is no symbol, so no plan.
  - With a stock ("…for INFY"): trade idea → card plus prose quoting only TRADE_PLAN figures. Direction is **assumed long** when not said, and the answer must say so (`copilot_trade_idea.py:209-210`).
- **Covers (named stock, status plan/wait):**
  - entry trigger and order type (stop-trigger / pullback / at-close) and validity in sessions;
  - stop with method and invalidation;
  - targets with R-multiples;
  - reward:risk gross/net per candidate (`plan.py:479-` `explain_plan_context`);
  - size and ₹ risk from the risk service; charges; payoff for options.
- **Gap:**
  - Needs the stock named in the same message.
  - No card when the status is not plan/wait; the prose then gives the reasons only.
  - Intraday horizon → `insufficient_data` (no intraday history, `copilot_trade_idea.py:17-19`).
- **Evidence:** probe Q7/Q7b; `copilot_trade_idea.py:153-199`; `DecisionCard.tsx:322-339`.

## Q8 — "Is my existing trade still valid?" → Thesis status and changing signals
- **Today:**
  - **LLM-decided** route (no regex hit). No symbol, so no trade idea.
  - Possible agents: `portfolio_analyst` (long-term holdings XIRR etc.) or `stock_analyst` (clarification).
- **Covers:** nothing about the user's open paper/desk trades.
- **Gap:**
  - Chat has **no read of paper trades** (`/api/desk/paper-trades`) or trade lifecycle status (eligible / triggered / open).
  - It has no thesis-vs-now comparison. The DecisionCard can show lifecycle status ("from your paper trades", `DecisionCard.tsx:318`), but only when a plan card is rendered for a *new* plan.
  - Broker F&O positions are reached only when the question is launched from a position row (`chat.py:152-240`). That gives live P&L and breakeven, then stock analysis of the underlying — not a thesis check.
- **Evidence:** probe Q8; §0.7.

## Q9 — "Should I book profits or hold?" → Exit conditions and trailing-stop options
- **Today:**
  - `_P_STOCK_INSIGHTS` advice clause ("should I book") → `stocks_insights` → no-advice refusal and redirect to filings (`intent_patterns.py:167`; `stocks_insights.py:77-82`).
  - With a named stock in Trader persona ("…hold TCS?"): trade idea → pinned stock_analyst → a **new entry plan**, direction *assumed long*. The question was about an existing position.
- **Covers:**
  - Refusal (no symbol).
  - With a symbol: the new plan's "How it ends" section on the full card (if wrong / if right / time limit / trailing "Protect gains" / trend exit, `DecisionCard.tsx:382-393`).
- **Gap:**
  - Not tied to the user's actual position: no entry price, no current P&L, no trailing-stop recompute, no "move to breakeven".
  - Paper trades and the journal are not reachable.
- **Evidence:** probe Q9/Q9b; §0.7.

## Q10 — "Which F&O setups are attractive?" → Strategy candidates and defined risk
- **Today:**
  - **LLM-decided** route. But in Trader persona the resolver passes "F&O" through as a symbol (`symbol_resolver.py:197-200`), and `normalise_inputs` accepts it (`plan.py:30`).
  - A plan is built for underlying "F&O". The likely outcome is the `unknown_symbol` gate, so no card (`plan.py:124-138`), but `trade_idea` is truthy.
  - So the turn is **pinned to stock_analyst for "F&O"** (`chat.py:1574-1575`), which fetches technicals/fundamentals for a non-stock. Code path from reading plus the probe; the live answer is not observed.
- **Covers:**
  - Nothing cross-sectional.
  - Per named F&O stock ("…for SBIN"): plan candidates across cash / futures / options families with legs, max profit/loss, breakevens, net R:R and payoff (`plan.py:479-` lines for legs, `max profit`, `reward:risk`). The full card shows option legs and the payoff (`DecisionCard.tsx:322-328`, `PlanPayoff`).
- **Gap:**
  - No ranked F&O setup list: the AI-watchlist F&O Top 10 and desk F&O strategies are not reachable.
  - Pass-through bug as described.
- **Evidence:** probe Q10; `chat.py:1561-1575`; `copilot_trade_idea.py:95-102`.

## Q11 — "What is the expected move in Nifty?" → Options-implied move and relevant levels
- **Today:**
  - `_P_MARKET` ("Nifty") → `market_node`. No symbol ("Nifty" is not in the curated equity list).
  - TOOL_DATA: NIFTY and BANKNIFTY nearest live expiry PCR, max pain, spot, heaviest call/put OI strikes; India VIX.
  - The prompt says "If a specific metric isn't in TOOL_DATA, say so".
- **Covers:** VIX, PCR, max pain, OI-heavy strikes as "relevant levels".
- **Gap:**
  - **No options-implied expected move and no ATM IV** in chat.
  - The desk's own chain summary computes both: `summary.expected_move` from the ATM straddle, and Black-76 IV (`routes/fno.py:88-89`, `528`, `848`). The market node uses DaaS chain + `summarise_chain`, which lacks them (`routes/fno.py:289-311`).
  - The put/call walls are computed but not printed.
  - If typed upper-case ("NIFTY"), the pass-through would build a trade plan for NIFTY and pin stock_analyst. Not probed; inferred from `symbol_resolver.py:197-200`.
- **Evidence:** probe Q11; `market_research.py:533-556`, `402-428`.

## Q12 — "How much should I risk?" → Position sizing and capital at risk
- **Today:** `_P_STOCK` ("How much") → `stock_analyst` → clarification "Which stock…?". (`_P_RISK` needs "how much risk", `intent_patterns.py:257`.)
- **Covers:** nothing as worded.
  - With a named stock and Trader persona, the card shows size, max loss (loss at exit + charges + gap allowance), "Your capital … up to ₹X at risk on one trade", binding limits, and room left in limits (`DecisionCard.tsx:340-360`), from `risk_gate.plan_sizing`.
  - "What position size should I take?" routes to `recommendation` via "position size" (`intent_patterns.py:324`) and runs the stock screener (probe P6b), a misroute.
- **Gap:**
  - No generic risk-budget answer: per-trade risk %, open-risk headroom and daily-loss room from the risk service are not exposed to chat except per plan.
  - The `risk_context` line built in chat.py is unused (§0.5).
- **Evidence:** probe Q12/P6b; `services/risk_gate/service.py:34-54`; `plan_sizing.py:41`, `153-154`.

## Q13 — "What are my open trades doing?" → Live or latest available P&L and status
- **Today:** `_P_STOCK` ("What are") → `stock_analyst` → clarification. (`_P_PORTFOLIO` needs "my holdings/positions/portfolio", `intent_patterns.py:221-231`.)
- **Covers:** nothing as worded.
  - "my positions" phrasing would reach `portfolio_analyst`: CAS/long-term holdings, not trades.
  - A broker F&O position row ask gives live P&L for that one contract.
- **Gap:**
  - No chat access to desk paper trades, `paper-account`, `risk_book`, the trade journal, or the broker positions list.
  - No live-P&L tool for open trades.
- **Evidence:** probe Q13; §0.7; `chat.py:152-240`.

## Q14 — "What should I avoid today?" → Event risks, weak setups, overexposure
- **Today:** `_P_STOCK` ("What should") → `stock_analyst` → clarification.
- **Covers:** nothing as worded.
  - "What are the key market risks this week?", a desk dock chip (`TradingDesk.tsx:394`), would reach market_node. That node's prompt has a risk section built from calendar, flows, VIX, yields, global and F&O (`market.py:39-45`).
- **Gap:**
  - No "weak setups" list; the scanner's rejected/avoid buckets are not reachable.
  - No overexposure check against the user's open trades. The risk service's sector/correlation checks exist but only per plan.
  - Event risk only via market-wide calendar blocks.
- **Evidence:** probe Q14; `market.py:39-45`.

## Q15 — "What did I learn from today's trades?" → Performance, rule adherence, mistakes
- **Today:** `_P_STOCK` ("What did") → `stock_analyst` → clarification.
- **Covers:** nothing.
- **Gap:**
  - No chat access to closed paper trades or the journal (`/api/positional/journal`), and no idea scorecard (`/api/desk/idea-scorecard`, `desk_trading.py:1063`).
  - No rule-adherence comparison (plan vs. fills).
  - The trader prompt catalog notes "win ratio / risk-reward intentionally hidden until P3" (`routes/copilot_prompt_catalog.py:579`).
- **Evidence:** probe Q15; §0.7.

---

## Q16+ — the owner's full brief, by phase
Same rules. "Probe" = dev regex router + resolver output for the phrasing shown (Trader persona). The full table is in `questions_phase.txt` / the probe run.

### Phase 1 — Pre-market
| Ask | Probe route | What chat can return | Gap |
|---|---|---|---|
| Likely open: global cues, GIFT Nifty | market_analyst; **sym=GIFT (pass-through)** | Trader persona: plan built for "GIFT" → **pinned stock_analyst** (misroute). Otherwise market_node gives US/Europe/Asia indices, USD/INR, US10Y, Brent, gold (Yahoo, last daily close) | **GIFT Nifty is deliberately absent** ("no reliable free Yahoo feed", `positional_engine/nse_live.py:395-398`). No open forecast. Pass-through bug. |
| Sectors likely to outperform | LLM-decided | Sector 1D/1W/1M ranking (end of day) if market_node | Backward-looking only; no forward sector model in chat |
| Where FIIs / DIIs / MFs deploy | **mf_analyst** ("mutual funds") | Wrong node: the MF node answers about funds/schemes | FII/DII cash is in market_node only; MF/AMC deployment (Smart Money) is not reachable |
| Today's economic events & results | market_analyst ("economic events") | Next-5-session NSE calendar (results meetings, events, holidays, Nifty-50 reporters) | No macro-release calendar beyond what `/v1/events/calendar` holds |
| Trending / range-bound / volatile | LLM-decided | VIX tone, breadth, 5-session trend if market_node | No regime label in chat (the plan builder reads `macro_engine.classify_desk_regime`, `sources.py:45-52`, per stock only) |
| Nifty / Bank Nifty S/R | market_analyst | Max pain, heaviest OI strikes | No technical S/R or pivots; walls computed but not printed |

### Phase 2 — Scanning
| Ask | Probe route | Today | Gap |
|---|---|---|---|
| Highest-probability breakouts | LLM-decided | Clarification or screener | No breakout list. "Probability" is not offered; the persona text even says a scanner score is not a probability (`persona_framing.py:116`) |
| Up on volume but below resistance | stock_analyst ("resistance") | Clarification "Which stock?" | No cross-sectional volume + resistance scan |
| Fundamentally strong near 52-week lows | LLM-decided | If recommendation: fundamental screener (ROE, D/E…) | No 52w-low filter in the NL parser (`recommendation.py:41-86`); `dist_52w_low_pct` exists per stock only |
| Long buildup / short covering | LLM-decided | market_node gives buildup *counts* only | No per-stock buildup list (desk `/v1/desk/fno-buildup` has it; chat prints counts) |
| Relative strength vs Nifty | market_analyst ("Nifty") | Index-level data | No RS ranking |
| Could move 2% / 5%+ | LLM-decided | — | Move-odds model (`/api/move-odds/*`) not reachable from chat |
| Avoid: weak fundamentals / selling pressure | LLM-decided | Possibly screener | No avoid list; no selling-pressure metric |

### Phase 3 — Entry (stock named; Trader persona → trade-plan path)
- "Should I buy, sell or wait on X?" — the regex sends it to stocks_insights (refusal), **but the Trader pin overrides it**: stock analysis plus the plan card.
- "Is the X breakout confirmed or false?" — stock_analyst plus plan. "Confirmed" maps to plan status (`plan` vs `wait`) and the reasons.
- "Entry range" — entry is a single trigger price + order type + validity, not a range (`DecisionCard.tsx:51-66`, `322-329`).
- "Now or wait for a pullback" — order type `limit_pullback` / `stop_trigger` / `at_close` answers this per plan.
- "Is R:R attractive" — reward:risk gross/net per candidate (`plan.py` `explain_plan_context`); targets in R on the card. The risk service also has `min_reward_risk` (`risk_gate/service.py:38-44`).
- "Which confirmations are missing" — `status_reasons` + `would_change_if` when status is `wait` (`TradePlanChatCard.tsx:83-88`).
- "Overextended?" — only via technicals (RSI, distance from SMA) in prose. No explicit extension flag.
- "What invalidates" — stop + "Wrong if" / invalidation (`DecisionCard.tsx:330-334`).
- **Gaps:**
  - Several phrasings route LLM-decided, but the pin makes the route moot when a stock is named.
  - The direction is assumed long unless stated.
  - Intraday is unsupported.
  - Without a named stock, everything above becomes the clarification reply.

### Phase 4 — Open position
| Ask | Probe | Today | Gap |
|---|---|---|---|
| Hold / partial / exit my X position | LLM-decided; sym=X → Trader pin | A **new entry plan** for X (assumed long) | Not position-aware; no partial-booking logic tied to the position |
| Thesis weakened on my X trade | LLM-decided; pin | New plan + current technicals | No comparison to the plan the trade was opened on |
| Trail stop / move to breakeven | LLM-decided | — | No trailing recompute; the card only says "Protect gains: the exit price moves up as the price rises" |
| Losing momentum | LLM-decided | — | Per stock via RSI/MACD only if named |
| Add / average | LLM-decided | — | No pyramiding/averaging rules in chat |
| Realized / unrealized P&L | portfolio_analyst; **sym=P&L pass-through → Trader pin to stock_analyst** | Misroute in Trader persona; otherwise CAS holdings P&L (not trades) | Paper-trade and desk P&L not reachable |
| Overnight risk | stock_analyst ("What is my") | Clarification | No gap-risk-per-position; the plan has `costs.gap_risk` per plan only |

Broker F&O positions are reachable only via the position-row "ask" (live quote, P&L, breakeven).

### Phase 5 — F&O
- **Futures vs options vs cash for X** (named): the plan builds candidates across segments and picks a `preferred` one. The card lists "Also fits" links (`TradePlanChatCard.tsx:93-102`). Partial cover.
- **Buildup type for X**: stock_analyst + plan. The plan reads `/v1/desk/fno-buildup` per symbol (`sources.py:186-192`). Whether the prose states the label depends on the LLM quoting it.
- **PCR, max pain, ATM IV, expected move for NIFTY**: market_analyst, but **sym=PCR pass-through → Trader pin to stock_analyst** (misroute). Even when routed correctly: PCR and max pain only; no ATM IV, no expected move.
- **Call / put / debit spread on X**: regex says stocks_insights ("Should I buy"); the Trader pin wins → plan with option candidates (bull put/call words set the direction, `copilot_trade_idea.py:45-46`).
- **Strike and expiry**: plan legs (strike, expiry, lots) on the full card; the expiry choice is in `chain.expiry_why` (`sources.py:410-418`).
- **Max profit / max loss / breakeven**: in `explain_plan_context` and `PlanPayoff`. No stock named → stock_analyst clarification.
- **Margin**: stock_analyst clarification ("How much"). `services/strategy_plan/margin.py` exists. Whether the chat card shows margin was **not determined**: no "margin" text in the DecisionCard files besides a comment in `ways-forward.tsx:3`.
- **Reaction to price / time / volatility (Greeks)**: risk_analyst ("volatility") → portfolio risk. Wrong node. Greeks exist in the plan's chain (Black-76) and the card's "review when" (`DecisionCard.tsx:411`).
- **Close / roll / hedge**: LLM-decided. The desk has `/api/desk/paper-trades/{id}/roll` (`desk_trading.py:763-812`), but it is not reachable from chat.

### Phase 6 — Risk
| Ask | Probe | Today | Gap |
|---|---|---|---|
| Capital to risk | stock_analyst ("How much") | Clarification | Per-trade budget is visible only on a plan card ("up to ₹X at risk on one trade") |
| Position size | **recommendation** ("position size") | **Stock screener** (misroute) | Sizing exists in `risk_gate.plan_sizing`, per plan only |
| Daily loss limit used | stock_analyst | Clarification | The risk service checks `daily_loss` / `weekly_loss` / `drawdown` (`risk_gate/service.py:54`, `118-119`); not exposed to chat |
| Overexposed to sector / correlated | risk_analyst ("Am I overexposed") | Long-term holdings risk (PRA, VaR, suitability) | Not trading-book aware. Sector/correlation checks exist per plan (card "Things to watch: Too much in one place / Moves with what you hold", `DecisionCard.tsx:283`) |
| Too many trades today | LLM-decided | — | No trade-count read |
| Overlap with existing positions | portfolio_analyst ("overlap") | **MF overlap** (misroute) | Plan warnings `concentration` / `correlation` only |
| Stop after loss limit | LLM-decided | — | Risk-controls status `/api/risk/status` (`risk_controls.py:113`) not reachable |

### Phase 7 — End-of-day review
| Ask | Probe | Today | Gap |
|---|---|---|---|
| Which trades worked | LLM-decided | — | No closed-trade read |
| Entry / stop / exit rules followed | LLM-decided | — | No plan-vs-execution comparison |
| Which signals worked / failed | LLM-decided | — | Idea scorecard (`desk_trading.py:1063`) not reachable |
| What drove biggest gainers / losers | stock_analyst ("What drove") | Clarification | market_node has top movers but this phrasing does not reach it; no "why" attribution |
| Positions safe overnight under my rules | stock_analyst ("hold overnight") | Clarification | — |
| Tomorrow's setups and events | stock_analyst ("What are") | Clarification | Calendar is in market_node; setups (scanner) not reachable |
| Mistakes to avoid | stock_analyst ("What mistakes") | Clarification | — |

---

## Entry chips: the brief's six vs. what exists
The brief's six chips (**Market pulse, Find opportunities, My positions, F&O strategies, Manage risk, Daily review**) **do not exist** anywhere on dev. A grep for those labels in `frontend-v5/src` and `backend/routes` finds only unrelated "Market Pulse" page names.

What exists for a trader today:
1. **Desk Copilot dock chips**: context-dependent, defined in `useDockChips`, `frontend-v5/src/pages/CopilotApp/screens/TradingDesk.tsx:374-397`. Always ends with "What are the key market risks this week?".
   - Research/chart view with a symbol: "Explain the {sym} setup and what would invalidate it", "Size a trade in {sym} with 1% risk".
   - Smart Money view: "What does NIFTY option OI say about this expiry?", "Which F&O stocks show long build-up today?".
   - Portfolio tab: "What are the key risks in my portfolio this week?".
   - Intel: "Summarise today's most important filings".
   - Default: "Why does {top} rank first on the scanner?", "Which sectors are leading today and why?".
2. **/app home "Try asking" starters, Trader mode** (`frontend-v5/src/pages/CopilotApp/views/Home.tsx:37-53`). Used **only when the backend returns no ranked prompts** (`Home.tsx:383`):
   - "Which sectors are leading the market this month?"
   - "Screen for stocks near their 52-week high with rising volume"
   - "What are FIIs and DIIs doing this week?"
   - "Backtest a 20-day breakout on Nifty 500 stocks"
   - "Which stocks reported results this week?"
   - "Explain how position sizing with 1% risk works"
3. **Ranked suggested prompts**, `GET /api/copilot/suggested-prompts` (`backend/routes/copilot_prompts.py:752-`; catalog `backend/routes/copilot_prompt_catalog.py:558-609`, persona `active_trader`):
   - The nine entries: "Which positions are doing best?", "Where am I overexposed?", "What is my realized vs unrealized P&L?", "Which trades are consistently losing?", "Which sectors show momentum?", "Effective swing trading setup?", "How do I manage risk?", "What position size should I use?", "How to improve trading discipline?".
   - Keyed to the **stored product persona** behind a feature flag (`copilot_prompts.py:778-779`), **not** the /app Trader toggle. The composer and home call the endpoint without a persona/mode param (`use-copilot-prompts.ts`, `Composer.tsx:89-97`).
   - These prompts answer from CAS/long-term holdings, not trades.
4. **Market node follow-up chips** (`market_research.py:37-44`) and **compliance default follow-ups** per agent (`compliance.py:30-66`). The recommendation follow-ups include "Compare the top 3 picks" ("picks" wording).

---

## Today's chat trade-plan card vs. the brief's "required answer fields"
The card is `TradePlanChatCard` (`frontend-v5/src/components/chat/TradePlanChatCard.tsx`).
- It renders the desk `DecisionCardById` row; "Full card ›" expands it (`DecisionCard.tsx:291-393`).
- It is shown only for a named stock whose plan status is `plan` or `wait`.
- The prose comes from the stock analyst's "How to trade it" section (`stock.py:41-59`).

| Brief field | Today | Where | Gap |
|---|---|---|---|
| **Market context and evidence** | Partly. "Why this idea": per-evidence-key verdict (ok / not checked) (`DecisionCard.tsx:366-372`). Raw evidence text and as-of dates are in the collapsed audit (`DecisionCard.tsx:394-403`). The prose gets evidence lines (`copilot_trade_idea.py:177-179`). | Regime and sector snapshots are inputs (`sources.py:45-60`) | No explicit market/regime line on the card; card evidence shows a direction word, not the figure |
| **Entry trigger and confirmation** | Yes. "When to enter": trigger price + order type in words, "waits up to N trading days", last close (`DecisionCard.tsx:322-329`). `wait` status lists reasons and "Would change if" (`TradePlanChatCard.tsx:83-88`) | | Single price, not a zone; confirmation is status-level, not a checklist |
| **Stop, targets and risk-reward** | Yes. "When the idea is wrong" (exit price, why there, wrong-if) and "Targets" with R multiples (`DecisionCard.tsx:330-339`). The prose gets "risk per unit" and target R (`copilot_trade_idea.py:166-172`); net/gross R:R in plan context | | No single headline R:R number on the compact row (targets in R instead) |
| **Size from the risk budget** | Yes. Size, max loss (loss + charges + gap allowance), "Your capital … up to ₹X at risk on one trade", binding limits, "Room left in your limits", limits check badge (`DecisionCard.tsx:340-360`, `37-42`). Prose: `sizing_lines` (`copilot_trade_idea.py:186-199`) | `risk_gate.plan_sizing` | Sized on paper equity by risk profile; the card notes "assuming no other open trades" (`DecisionCard.tsx:445`) |
| **Reasons to avoid** | Partly. "Things to watch" warnings: upcoming event, liquidity, concentration, correlation (`DecisionCard.tsx:283`, `373-381`); `rejected` → "Why not". With **no setup there is no card**; the reasons appear only in prose (`copilot_trade_idea.py:212-213`) | | No "avoid" verdict; the no-setup case has no structured card |
| **Conditions to hold, modify or exit** | Partly. "How it ends": if wrong, if right, time limit, trailing "Protect gains", trend exit, option exit levels (`DecisionCard.tsx:382-393`); exit rules in the audit (`DecisionCard.tsx:411`) | | Plan-time rules only; no live re-evaluation of an open position (hold / modify) |

---

## Defects found while tracing (code reading + probe; not runtime-verified)
1. **Generic questions fall into `stock_analyst`.** The case-insensitive `_P_STOCK` (`intent_patterns.py:67-76`) catches "What are / How much / What did / What should", and the user gets "Which stock…?" (Q6, Q7, Q12-Q15; P4g, P5f, P5g, P6a, P6c, P7d-g).
2. **Trader persona pins any upper-case token to `stock_analyst`.** "F&O", "GIFT", "PCR", "P&L" become symbols (`symbol_resolver.py:197-200`); a plan is built for them; the turn is pinned (`chat.py:1561-1575`). This overrides the market and portfolio routes (Q10, P1a, P4f, P5c).
3. **Compliance edits are dropped on the streamed path.** The advice scrub, grounding caveat and 400-word cap are applied to `final_resp`, but the streamed tokens are what the user sees and what is saved (`chat.py:1751-1809`; `compliance.py:169-221`). The stock node's "Verdict BULLISH/BEARISH" and the recommendation node's "picks" wording reach the user unscrubbed.
4. **Holdings and risk-profile context are built but unused** in the trader path (`chat.py:1623-1636`).
5. **The /app Trader toggle does not change the LLM framing or the suggested prompts.** Both key off the stored `user_profiles.persona`. Only the desk dock gets the PRD §9.4 answer structure.
6. **Specialist LLM calls get only the latest message.** No multi-turn context, so "this stock" and "my trade" follow-ups fail.
