# E: Auto-Suggestions & Smart Queries Engine: what exists (origin/dev a4294830) vs the owner's spec

Read-only audit, 2026-10-30. Code is read from `origin/dev`. Staging was probed with read-only Mongo queries (aggregates only) and one in-process replay of the prompt scorers on synthetic contexts (pure functions, no DB access).

**Code parity, VERIFIED.** These seven files have identical sha256 on origin/dev and in the `nivesh-staging-app-backend` container:

- copilot_prompts.py
- copilot_prompt_catalog.py
- chat.py
- compliance.py
- query_suggestions.py
- insights.py
- desk_alerts.py

## 0. Bottom line

There is no suggestion engine. What exists is:

1. **A ranked prompt endpoint**, `GET /api/copilot/suggested-prompts`.
   - 109 templates.
   - Rule scorers that read the portfolio (personalized).
   - Pulled on every read: no events, no store, no feedback.
2. **Static per-agent follow-up chips** in the chat `done` frame. They are not generated from the answer.
3. **Scattered rule engines.** None of them feed suggestions:
   - portfolio insights;
   - plan signal detectors;
   - desk alerts.

None of the spec's tables exist: `suggestion_rules`, `suggestion_events`, `suggestion_instances`, `suggestion_feedback`, `query_templates`. There are no code references and no Mongo collections. No cron or job produces suggestions.

## 1. The prompt catalog and how it is ranked

**Endpoint.** `backend/routes/copilot_prompts.py:752` `GET /api/copilot/suggested-prompts?persona=&category=`.

**Universal templates (10).** `_PROMPT_TEMPLATES` at copilot_prompts.py:136-266. Each has a rule scorer (lines 37-131) over a portfolio context.

| id | intent_category | tier | badge (computed figure) |
|---|---|---|---|
| fix_portfolio | portfolio_health | primary | "{n} actions pending" |
| overlap | risk_diversification | secondary | "Top pair X% overlap" (only if max overlap ≥ 40) |
| risk_allocation | risk_diversification | secondary | "Equity X% · Debt Y%" or "Equity X%" |
| exit_lowest_tax | tax | secondary | "Tax-optimised exits available" (text, no figure) |
| where_to_invest | portfolio_health | secondary | "Debt gap — only X%" |
| performance | performance | advanced | "N underperformers" (from plan reason codes) |
| concentration | risk_diversification | advanced | "{AMC} X%" |
| what_if | portfolio_health | advanced | "Simulate N actions" |
| tax_optimize | tax | advanced | "Est. tax ₹X" |
| long_term | goal_planning | advanced | none |

**Persona catalog (99).** `backend/routes/copilot_prompt_catalog.py`, merged in at copilot_prompts.py:274-279.

- **Personas:** 10 personas with 10 prompts each; active_trader has 9.
  - beginner_investor, mutual_fund_investor, stock_investor, hni_investor, retirement_planner, parents_planning, tax_saver, conservative_investor, active_trader, nri_investor.
- **Categories:** risk_diversification 28, goal_planning 25, performance 17, tax 16, portfolio_health 13.
- **Tiers:** primary 10, secondary 41, advanced 48.
- **Scores are fixed by tier.** None of them reads a signal.
  - 49 are gated on holdings (`total_value > 0`): primary 90, secondary 55, advanced 30.
  - 50 are holdings-free, at a fixed 28.
- **No persona prompt ever carries a badge.**

**active_trader block** (catalog.py:558-609, 9 prompts).

- Holdings-gated:
  - "Which positions are doing best?"
  - "Where am I overexposed?"
  - "Realized vs unrealized P&L"
  - "Which trades are consistently losing?"
- General:
  - sector momentum
  - swing setup
  - risk management
  - position size
  - discipline
- The win-rate / risk-reward question (Q5) is hidden "until P3".
- **There is no separate feature flag.** The whole persona catalog sits behind `copilot_persona_prompts_enabled` (feature_flags.py:117-127, default "everyone"). It is shown only when `user_profiles.persona.persona == "active_trader"`.
- The "position" prompts are gated on portfolio value (CAS/MF holdings), not on broker positions.

**Advisor audience.** `_advisor_prompts()` (copilot_prompts.py:603-656) returns 7 curated cross-client prompts. It is used when the caller owns an ADVISORY workspace and is not impersonating (`_is_advisor_mode`). The only badge is a static "Daily brief".

**Dead code.** `_investor_prompts_curated()` (copilot_prompts.py:659) is never called.

**Trader mode has no audience of its own.** The v5 frontend never passes `persona` or `category` (use-copilot-prompts.ts:75; chat.adapter.ts:223). Trader mode therefore gets the same investor ranking. `STARTERS.trader` (Home.tsx:46-53) appears only when the backend returns nothing.

**Context.** `_build_context` (copilot_prompts.py:286) reads:

- `portfolio_intelligence` for total, allocation, pairwise overlap and AMC exposure;
- a fallback from holdings;
- the active `action_plans` for the action count, exit flag, tax and underperformer count.

It does **not** read:

- broker positions;
- watchlists;
- prices or technicals;
- the market calendar;
- data freshness (the CAS date or the last broker sync).

**Ranking** (copilot_prompts.py:799-879):

1. Score from the scorer.
2. Add 20 to fix_portfolio when the journey is `first_time`.
3. Add 35 to a template tagged with the user's persona.
4. Sort by score.
5. Fill the tiers: 1 primary, up to 3 secondary, up to 3 advanced.
6. Apply the persona floor: at least one persona prompt in secondary when the persona is not the default.
7. If there is no primary, promote the top secondary.

Ranking has none of the following:

- urgency;
- evidence quality;
- interests or preferences;
- a recency or dedup history;
- cooldowns;
- dismiss.

`journey` (first_time / post_action / returning) and the per-prompt `viz` (donut, bar or gauge; copilot_prompts.py:447) are returned, but **the v5 frontend uses neither**: no `viz` reference exists in frontend-v5/src.

**🔴 Bug: manufactured personal figures with no portfolio.** This is VERIFIED by replaying the real scorer code inside the staging container on an empty context. A user with no holdings is ranked:

- `risk_allocation`, badge **"Equity 0% · Debt 0%"**, score 90;
- `where_to_invest`, badge **"Debt gap — only 0%"**, score 75.

The cause is in the scorers: `_score_risk_alloc` fires on `debt_pct < 10`, and `_score_add` on `debt < 10`. Neither checks `total_value`.

Home.tsx:310-313 turns every badged prompt into a "Worth knowing today" card with a FACT line. That step is not gated on `hasPf`. It also suppresses the news fallback (line 317).

This violates the spec's "never manufacture a personal alert". The browser render is UNVERIFIED: it was read from code, not seen in Playwright.

## 2. Frontend surfaces

**`useCopilotPrompts`** (CopilotApp/lib/use-copilot-prompts.ts:67-104):

- keeps id, label, query, outcome, badge and category;
- drops tier, score, viz and journey;
- caches for 5 minutes per impersonation profile.

**Home** (CopilotApp/views/Home.tsx):

- **Greeting.** Line 328 shows the date and the market state ("Market open/closed") as an eyebrow. Line 330 shows "What would you like to *know*, {firstName}?". There is no time-of-day greeting.
- **MarketStrip** (80-108): NIFTY, breadth, VIX, FII/DII cash from `/api/markets/home`.
- **StatementBar** (116-155): "Last CAS {period}", Sync Gmail, Upload. After an import it invalidates `["copilot"]`, so prompts are re-ranked on the next read. This is the only "after import" hook, and it is client-side only.
- **"For your portfolio today" cards** (`usePortfolioCards`, 205-273):
  - health score (`/api/insights/analysis`);
  - pending plan actions (`/api/plans/active`);
  - an allocation-drift card, derived in the client from the risk profile;
  - up to 2 `/api/insights` signal cards.
- After those come the badged prompt cards (299-313), capped at 6 cards in total. The news fallback is used when there are no cards (316-317, 362-373).
- **"Try asking"** (379-398) lists the remaining ranked prompts, or `STARTERS[mode]` (37-62, static, no figures).
- **No tabs, no dismiss, no refresh, no "why am I seeing this".** The "why" is only the OUTCOME line plus the FACT badge.

**🔴 `/api/insights` cards are dead.** VERIFIED from code and staging data; not seen at runtime.

1. `GET /api/insights` (insights.py:316-322) returns a **bare list**. `insightsService.list()` parses `InsightsListRes = z.object({insights: [...]})` (insights.contract.ts:85-97) and throws contract drift.
2. Nothing in frontend-v5 calls `POST /api/insights/generate`. `useGenerateInsights` has no callers.
3. Staging has **no `ai_insights` collection** at all.

The rule engine behind it is `_deterministic_insights` (insights.py:466): sector > 25%, AMC concentration, category concentration, regular-plan cost, debt < 10%, overlap > 70%. It is real, deterministic and personalized. It is not wired.

**Composer**, the "Ask your own question" box (CopilotApp/shell/Composer.tsx):

- With an empty box it shows the top 5 ranked prompts, with outcome or badge as the "why" (94-98).
- While typing it combines:
  - `/api/chat/suggest-queries` (the question bank);
  - `/api/chat/instrument-search`;
  - stock completion at the cursor.
- A `Freshness()` note (41-60) reads "NSE live / delayed / closed" with an as-of time.

**Question bank.** `backend/data/nivesh_question_bank.json` holds 298 templates. Each has:

- section, category and subcategory;
- example_query;
- intent: lookup 151, analysis 63, personalized 25, …;
- data_source;
- live_static;
- needs_disclaimer;
- applicability.

It is ranked deterministically in `services/query_suggestions.py:116` (typeahead only, unauthenticated, chat.py:1066-1073). This is the nearest thing to `query_templates`. It does **not** map to an analytics or widget template; it only fills the text box.

**Desk dock chips.** `useDockChips` (TradingDesk.tsx:374-397) is static per desk location. The only dynamic input is the ticker in view or the desk scanner's top symbol. They are questions, with no figures, ranking or feedback.

## 3. Follow-ups after an answer

**Mechanism.** The `follow_ups: List[str]` schema field (copilot_agent/schemas.py:158-161) is filled by `compliance_node` (nodes/compliance.py:204-208). It uses static `_DEFAULT_FOLLOW_UPS` (compliance.py:30-66) for 7 agents:

- market_analyst
- stock_analyst
- mf_analyst
- portfolio_analyst
- risk_analyst
- goal_planner
- recommendation

Three chips each.

- **No agent node sets its own follow-ups.** No other `follow_ups` writer exists under copilot_agent/. So the chips are **neither LLM- nor data-generated**: the same 3 chips appear for every answer from a given agent.
- **Four agents get none:** backtest_analyst, stocks_insights, policy_analyst, advisor.
- **The advisor book path** (chat.py:1817-1830, the `else:` branch) and the error path send none.

**Transport.** chat.py:1652 / 1794-1796 / 1862-1863 adds `follow_ups` (at most 3) to the `done` frame. They are **not persisted** on the `chat_messages` doc. Staging has 0 of 64 assistant messages with `follow_ups`.

**UI.** Follow-ups are shown in CopilotApp/views/Thread.tsx:136-141 only on the last turn, and only in the session that streamed it. tool-templates.ts:1017 itself lists "follow-ups are not stored" as a gap.

**Widget-level chips.** These are also static:

- the market-pulse widget's `_SUGGESTIONS` (copilot_tools/market_research.py:38), rendered at ChatWidget.tsx:2804;
- `portfolio_result_transformer` `suggestions=[...]`.

**Gap.** Context-aware follow-ups, such as "compare alternatives", "show historical validation" or "calculate position size":

- built from the answer's entities, widget and tool results;
- persisted;
- shown for every agent.

## 4. Alerts, notifications and signals that could feed the engine

**Desk alerts.** `POST/GET/DELETE /api/desk/alerts` (routes/desk_trading.py:973/998/1042). Rules are in services/desk_alerts.py.

- **8 conditions:**
  - above / below a price;
  - filing;
  - filing category or bulk/block deal;
  - volume × 20-day mean;
  - in the positional scanner picks;
  - sector index 1-day move;
  - ATR% risk.
- **User-set only.** Alerts are one-shot, deduplicated by `dedupe_key` (409 on a duplicate), and capped per user.
- **Evaluation.** On GET, and by the weekday cron `check_desk_alerts` at 20:45 and 22:45 IST. Staging job_runs: 6 runs, the last at 2026-10-29T17:15Z.
- **In-app only:** "nothing is sent anywhere".
- This is the best pattern to reuse (dedup, one-shot, firing reason, `check_errors` when data is unreadable). It is **not** a suggestion source: nothing turns a fired alert into a prompt or a card.

**Filing alerts.** `GET/PUT /api/filings/alerts` (filings.py:492/506) stores preferences only. Delivery is off: "nothing is sent to you today".

**There is no notification center and no bell in the CopilotApp shell.** A Bell icon exists only in the legacy Research page nav and AdvisorDashboard. `user.py:365` stores push/email notification preferences that nothing uses.

**Kite / staleness.** `GET /api/live/status` returns `login_needed`. `KiteLoginNotice.tsx` is **admin-only** and covers the platform token, not a user's broker connection. Prompts never consult it.

**Market inputs that exist.** None of them feeds prompts.

- `/api/markets/home`
- `/api/markets/daily-brief`: lazy on GET plus a POST generate; no cron. Staging has only 3 briefs, the latest dated 2026-10-21.
- `/api/markets/events-calendar` and `/macro-calendar`
- `/api/market/events`, `/events/tomorrow` and `/signals` (AI filing signals)
- `nidp/shared/trading_day.py` and `market_hours.py`

**Opportunity inputs that exist.** Nothing intersects a user's watchlist or holdings with these signals.

- The positional engine: a cron, 8 runs on staging.
- The AI watchlist Top-10 (`ai_watchlist_days`, cron, list_dates 2026-10-26 to 10-29).
- The research watchlist.
- Chartink.
- User watchlists (`/api/watchlists`).

**Position inputs that exist.**

- Broker positions and holdings: `/api/broker/positions`, `/holdings`, `/accounts` (broker_connect.py).
- The daily `broker_holdings_sync_daily` job at 17:30 IST (mf_scheduler.py).

**There is no near-stop or deteriorating-signal rule for real positions.** Paper-trade stops are checked only by the evening exit job.

**Other rule engines.**

- `services/signal_detector.py` (overlap, overexposure, quality; priority-sorted). It feeds action plans only.
- The prompt scorers.
- `_deterministic_insights`.

## 5. Feedback, dismiss and completion tracking

- **Prompts:** nothing (no impression, click, dismiss or feedback logging).
- **Insights:** `POST/DELETE /api/insights/{id}/complete` writes to `insight_completions` (insights.py:926-975). That collection is absent on staging.
- **Plan actions:** `PATCH /api/plans/{plan_id}/actions/{action_id}/feedback` takes useful plus a comment (plans.py:354).
- **Answers:** `POST /api/copilot/feedback` takes thumbs up/down into `copilot_feedback` (copilot_agents.py:113-137). **There is no frontend-v5 caller**, and the collection is absent on staging.
- **Desk alerts:** delete only.

## 6. Feature flags and staging data (aggregates only)

**Flag source.** `backend/feature_flags.py` (`KNOWN_FEATURES` defaults), hydrated from `system_config{key:"feature_flags"}`. The persisted doc was last updated 2026-10-24T23:08Z. Values on staging:

| flag | mode | persisted |
|---|---|---|
| copilot_persona_prompts_enabled | everyone | yes |
| copilot_engine_nidp | everyone | yes |
| chat_streaming | everyone | yes |
| broker_hub | everyone | yes |
| ai_copilot | allowlist (1 email) | yes |

No suggestion-specific flag exists beyond `copilot_persona_prompts_enabled`.

**Prompt-related collections: none.** There are no prompt or suggestion collections. These are also absent on staging: `ai_insights`, `insight_completions`, `copilot_feedback`, `portfolio_analysis`.

**Related staging collections:**

| collection | count | latest | detail |
|---|---|---|---|
| chat_sessions | 41 | 2026-10-29T22:44Z | 2 distinct users |
| chat_messages | 132 | 2026-10-29T22:46Z | 68 user / 64 assistant; 47 with a widget; **0 with follow_ups** |
| desk_price_alerts | 2 | 2026-10-23 | both `fired`, condition `filing` |
| market_daily_brief | 3 | date 2026-10-21 | |
| ai_watchlist_days | 4 | list_date 2026-10-29 | |
| action_plans | 3 | 2026-10-21 | 1 active, 2 archived |
| user_watchlists | 1 | | 12 symbols |
| broker_accounts | 2 | | |
| event_ai_analysis | 33,167 | | AI filing analysis |

**Users.** 4 users; 1 has holdings. Personas: 3 unset (so the default `retail_investor`, which has no persona templates), 1 `hni_investor`, **0 `active_trader`**.

**Staging crons installed** (/etc/cron.d on the app VM): ai-watchlist, cache-clear, db-snapshot, desk-alerts, positional-engine, research-watchlist. **None generates insights or suggestions.**

## 7. Spec item → exists → gap → size

| # | Spec item | Exists (where, origin/dev) | Gap | Size |
|---|---|---|---|---|
| 1 | Greeting | Home.tsx:328-331: date, market-state eyebrow, "What would you like to know, {name}?" | Time-of-day greeting copy ("Good morning! What would you like to explore?") | S |
| 2 | Tabs: For You / Market / My Trades / F&O Lab | None. The backend `category` filter covers 5 *investor* intents (copilot_prompts.py:707, 756), and v5 never passes it | Tab taxonomy; an audience/category on each template for market, trades and F&O; the tab UI; Trader mode passing its audience | M |
| 3 | Smart query cards (title + one-line why) | TodayCard title + FACT (badge) + OUTCOME (Home.tsx:170-199, 299-313). "Review my portfolio" ≈ fix_portfolio; "Sector exposure / overlap" ≈ concentration + overlap | "Check my open positions" (near stop / deteriorating) and "Find today's opportunities" (setups, triggers, R:R) cards; the why should come from the triggering rule, not static outcome text | M |
| 4 | Ask-your-own box | Composer.tsx: ranked prompts when empty; question-bank typeahead (298); instruments; stock completion; freshness note | None functionally | — |
| 5 | Daily suggestions (start of day, key levels) | Market strip; news fallback cards; daily-brief endpoint (lazy, stale on staging: last 2026-10-21); calendars; trading_day.py; AI watchlist (daily cron) | A daily-starter generator keyed to the trading calendar and to which data is fresh today (holiday/pre-open/close aware); key-levels card | M |
| 6 | Portfolio-aware (after import or refresh) | Prompt scorers on portfolio_intelligence + plan (personalized, rule-based); `_deterministic_insights` rules; client invalidates `["copilot"]` after Gmail import | Event on CAS import / broker sync (17:30 job) to evaluate rules; technical-weakness rules on holdings; fix `/api/insights` (bare list vs `{insights}` contract; generate never called; no data on staging) | M |
| 7 | Position-aware (near stop / risk) | Desk alerts `above/below/risk` (user-set; checked on read and at 20:45/22:45 IST); paper-trade stops via the evening exit job; broker positions API | Rules over real broker positions (distance to stop or ATR, P&L drawdown, deteriorating signal); intraday evaluation; a stop-level source for broker positions (brokers give no stop) | L |
| 8 | Opportunity-aware (validated signal meets criteria) | Positional engine + AI watchlist Top-10 + Chartink + desk `scanner` alert condition (per symbol, user-set); dock chips name the top scanner symbol | Join of user watchlist/holdings × validated signals (with the validation evidence) → suggestion instance | M |
| 9 | Follow-ups after every answer | Static per-agent `_DEFAULT_FOLLOW_UPS` (compliance.py:30-66, 204-208) → `done.follow_ups` (chat.py:1862) → Thread.tsx:136 (last turn only) | Context-aware generation (entities, widget, tools); cover the 4 agents plus the advisor path; persist on chat_messages; spec chips (compare alternatives, historical validation, position size) | M |
| 10 | Engine inputs | All sources exist separately: holdings/PI, broker positions, watchlists, live status, markets home, calendars, prefs, persona | A single context builder for the engine (`_build_context` covers only portfolio + plan); freshness of each input | M |
| 11 | Rules + event detection (risk, technical, market events, freshness, relevance) | Scattered: prompt scorers, insights rules, signal_detector, desk_alerts (8 conditions, dedup, one-shot, check_errors) | `suggestion_rules` as data, not code; event detection; **freshness gating** (no badge from stale or empty data; say "broker disconnected / prices stale") | M |
| 12 | Ranking (relevance, urgency, evidence, interests, dedup) | score + persona boost (+35) + first-time boost (+20) + tier shaping + persona floor | Urgency, evidence-quality and interest weights; dedup across surfaces; cooldowns; per-user suppression | M |
| 13 | Card → preselected analysis → chart → evidence → follow-ups | Click = `ask(query)` free text (Home.tsx:307) → LangGraph intent → widget (33 WidgetTypes) → Evidence panel. Chat accepts an `agent` pin (chat.py:1531), unused by prompts; per-prompt `viz` computed but unused | `query_templates` mapping prompt → agent/tool/widget, passed with the ask; render `viz` previews or drop them | M |
| 14 | Tables: suggestion_rules / events / instances / feedback, query_templates | None (no code refs, no collections). Nearest: the question-bank JSON (298, intent + data_source) and the catalogs in code | Create all 5 stores + indexes + an admin view; move the catalog into `query_templates` | L |
| 15 | Scheduled + event-driven evaluation, dedup, cooldowns | Patterns to copy: desk-alerts cron + `job_runs` heartbeat; `dedupe_key`; mf_scheduler jobs (broker sync 17:30, snapshot 23:30) | Suggestion jobs (pre-open daily, post-close, after sync) + event hooks + cooldown store | M |
| 16 | Dismiss / refresh / "Why am I seeing this?" | Nothing for prompts. Insight complete/uncomplete; plan-action useful/comment; `/api/copilot/feedback` thumbs (no v5 caller) | `suggestion_feedback` (dismissed / useful / not relevant / completed) API + UI; refresh; a why panel showing the rule, inputs and as-of | M |
| 17 | Split: informational / validated signal / actionable risk alert | Separate surfaces with their own vocab: prompt tier; insight severity fix/watch/info/good; desk alert "fired" + reason; desk "ideas, not picks" wording | One `class` field on every suggestion instance + distinct card treatment + SEBI wording per class | S |
| 18 | Never manufacture a personal alert; say when stale or disconnected | Composer freshness note; StatementBar "Last CAS"; KiteLoginNotice (admin, platform token only) | **Bug:** no-holdings users get "Equity 0% · Debt 0%" and "Debt gap — only 0%" badges, shown as Home FACT cards (scorers at copilot_prompts.py:60-86; Home.tsx:310-313 not gated on hasPf). Prompts ignore broker or CAS staleness | S |
| 19 | First release: 4 categories, daily starters, portfolio-aware after connect, chart-template click, follow-ups, dismiss/refresh/why, the 3-way split | Partial pieces listed above | The new work: rows 2, 5, 6 (event), 9, 13, 14 (minimal), 16, 17, 18 | L overall |
