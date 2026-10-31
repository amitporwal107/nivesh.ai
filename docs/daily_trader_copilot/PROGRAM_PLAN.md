# Daily Trader Copilot — program plan (30 Oct 2026)

Owner briefs of 30 Oct, read together:
1. **Daily Trader Copilot.** Six entry points (Market pulse, Find opportunities, My positions, F&O strategies, Manage
   risk, Daily review) and the 15 priority questions. Every answer produces a decision.
2. **Question-to-Visualization Engine.** Every answer is a visual decision dashboard from real data, through one
   response contract. Releases MVP 1 to MVP 3.
3. **Portfolio & Broker Hub.** Connect, upload or enter manually; My Portfolio vs Open Positions; holdings and position
   analytics; a portfolio-aware Copilot.
4. **Auto-suggestions & smart queries.** For You, Market, My Trades, F&O Lab; suggestions driven by data and rules;
   follow-ups after every answer.

The product goal, in the owner's words: *"Given what I already own and the positions I have open, what deserves my
attention today?"* Typed and suggested questions lead to the same visual-answer engine
([VISUAL_ANSWER_CONTRACT.md](VISUAL_ANSWER_CONTRACT.md)).

## Where we stand (read-only audits, 30 Oct, origin/dev a4294830 and staging)

| # | Question | Chat today | Data that exists (route / service) | Fresh on staging? | Release |
|---|---|---|---|---|---|
| 1 | Market view today | partial (end-of-day prose) | markets home, market snapshot, index closes, sector indices, F&O chain (OI walls, expected move) | yes (29 Oct); analytics layer frozen at 12 Oct (fix PR #414) | R1 |
| 2 | Where is smart money moving | partial | FII/DII cash, sector indices, F&O buildup, smart-money routes | cash yes; FII F&O flows stop at 21 Oct (Sensibull feed) | R1 |
| 3 | Top 5 opportunities | not covered | AI scanner Top 10 (ai_watchlist_days) + TradePlans, /api/desk/strategy/ideas | yes (29 Oct list) | R1 |
| 4 | Confirmed breakouts | not covered | positional watchlist `breakout_confirmed` (level, 3-vs-20 volume ≥1.5×, stop) | yes | R1 |
| 5 | Unusual volume | not covered | stock features rvol/vol_z20, delivery averages | yes; delivery is 1 day behind until ~10:30 | R1 |
| 6 | Is this stock a buy now | partial (named stock only) | the desk plan: plan / wait / no_trade with reasons | yes | R1 |
| 7 | Entry, target, stop-loss | partial (named stock only) | TradePlan: entry, stop, 3 targets, R:R, risk-service size | yes | R1 |
| 8 | Is my trade still valid | not covered | paper trades + lifecycle + plan versions; nothing re-checks an open trade | — | R2 |
| 9 | Book profits or hold | not covered | exit engine (ATR trail, EMA exit, opt-in); TradePlan trailing stop disabled | — | R2 |
| 10 | Attractive F&O setups | not covered | /api/desk/strategy/top: 7 defined-risk families, max loss, breakevens, Greeks | yes | R2 |
| 11 | Expected move in Nifty | partial (PCR, max pain only) | chain: ATM straddle expected move, ATM IV | yes (end of day); IV history stops at 26 Oct (cron not installed) | R1 |
| 12 | How much should I risk | not covered | risk profile defaults, plan_sizing.size_for, /paper-trades/check | yes | R2 |
| 13 | My open trades | not covered | /api/desk/paper-trades (P&L, MFE/MAE, end-of-day marks); broker positions read live | yes | R2 |
| 14 | What to avoid today | not covered | events/results calendar, scan risk flags, risk-gate limits; no unified list, no F&O ban list | results yes; macro calendar empty | R2 |
| 15 | What did I learn today | not covered | risk decision log; no post-trade review, rule adherence or live hit-rate | no live outcomes | R3 |

**Summary:** the chat fully answers none of the 15 today, and 3 only partly. Yet most of the data already exists
behind routes the desk uses. The work is mostly connecting it to one answer engine, plus a short list of true gaps.

## Fix first (wrong answers or broken data today)

| Defect | Effect | Status |
|---|---|---|
| Compliance edits never reach the user | The advice scrub, the evidence caveat and the 400-word cap act on a text the stream never sends | building (branch fix/copilot-chat-p0) |
| Generic trader questions routed to the stock analyst | "What are my open trades doing?", "How much should I risk?"… get "Which stock?" | building |
| Capital words read as stocks | "F&O", "PCR", "P&L", "GIFT" become symbols; a plan is built for them | building |
| Suggestions invent personal facts | A user with no holdings sees "Equity 0% · Debt 0%" as a fact card | building |
| Home's insight cards dead | /api/insights returns a list; the app expects {insights} | building |
| Scheduler runs once per worker | The 17:30 broker sync runs ~4 times at once and can race | building |
| Analytics layer frozen at 12 Oct | Market Overview movers, sector heatmap, delivery surge, stock cards are 12 Oct | **PR #414** |
| Data feeds needing the owner | Daily Kite login (live data); Sensibull FII F&O feed stale since 22 Oct; `record_iv_history` cron not installed; BSE announcements HTTP 403 since 13 Oct; no GIFT Nifty source; macro calendar empty | owner action / decision |

## Releases

### R1 — Daily Trader home and visual answers for market and opportunities (DONE, PR pending merge)
- **Trader home:** the owner's six entry points, a question box with stock autocomplete, and "Explore this question",
  plus matching tiles in the trading desk's Copilot dock empty state. `components/DailyTraderPanel.tsx`.
- **Visual-answer engine** (`backend/services/copilot_visual`), 7 intents, each built from existing desk services and
  verified on a real staging capture: `market_view` (Q1), `smart_money` (Q2), `top_opportunities` (Q3), `breakouts`
  (Q4), `unusual_volume` (Q5), `stock_decision` (Q6 and Q7), `expected_move` (Q11).
- **Rendering.** A chart registry: KPI strip, annotated candles with levels and bands, bars, heatmap, buildup
  quadrant, ranked table, trade-plan card, data-quality footer. Works in the chat thread and inline in the desk dock.
- **Follow-up questions** after every visual answer: rule-based, each one a supported question.
- **Six chat defects fixed** (found by the audit, so Release 1's own answers are not wrong on day one): compliance
  wording not reaching the user, generic questions mis-routed to "Which stock?", F&O/PCR/GIFT read as stock symbols,
  fake 0% suggestion badges, Home's dead insight cards, scheduled jobs running 4× (one per uvicorn worker).
- **Verification:** 380 backend tests, 108 frontend tests, tsc clean, full CI allowlist identical to `origin/dev`
  (no regression). A live signed-in session is still needed for the staging walk — see the OVERRIDE files.

### R2 — Positions, the Broker Hub, and the next 4 visual answers
Sized from the 30-Oct Hub audit (`audits/D_portfolio_hub.md`). The single biggest item is the Open Positions workspace.

- **5 more visual answers (DONE, branch `feat/dtc-r2-answers`, PR pending)**, reusing R1's contract and block
  registry — zero frontend code changes needed, since the block registry is keyed by block type, never by intent:
  - Q13 "What are my open trades doing?" (`open_trades`) — the paper book's own open trades, already exit-rule
    checked (`routes.desk_trading.list_paper_trades`).
  - Q10 "Which F&O setups are attractive?" (`fno_setups`) — `services.strategy_plan.regime_fit.build_top`, the same
    board `/api/desk/strategy/top` ranks; found and fixed a real bug in the process (its TradePlans were never
    stored, so the card's plan_id pointed nowhere — the route stores them after building, the reader didn't).
  - Q8 "Is my trade still valid?" (`trade_validity`) — today's fresh plan read against the newest plan stored
    earlier for the stock (Mongo `trade_plans`), with what changed (direction, stop) made explicit.
  - Q9 "Should I book profits or hold?" (`exit_options`) — the open trade's own levels and today's price, distance
    to stop and target; states plainly it does not tell the user to exit or hold.
  - Q12 "How much should I risk?" (`position_size`) — the account's own risk limits and today's usage
    (`services.risk_profile`, `services.risk_book`), plus a named stock's own size from the same sizing
    `stock_decision` shows.
  - Verified: 162 backend unit/chat tests, full CI allowlist (7426 passed, same 17 pre-existing failures as
    `origin/dev`, zero new), 29 frontend Playwright cases against a real 12-intent staging capture (all 12 R1+R2
    intents, not just R1's 7 — the spec's intent list was found not to cover the 5 new ones and was extended), 89
    passed on the broader desk/trade-idea/decision-card regression set, tsc clean. A compliance-wording bug was
    found this way (3 of the 5 builders generated a follow-up or row "ask" reading "Is X a buy now?" — the exact
    phrase the engine's own facts-block instruction forbids) and fixed (now "What's the setup for X?"), with a
    fresh real re-capture confirming the fix. Reports: `test_reports/dtc_r2_visual_backend_20261030.md`,
    `test_reports/dtc_r2_visual_frontend_20261030.md`.
  - Not yet built: Q14 "What to avoid today" (no unified list; see "Fix first" above) stays open, not part of this
    sub-item.
- **Open Positions workspace (L).** Today positions are read live from the broker and never stored (`db.holdings`
  has holdings; there is no positions/orders/trades model at all). Build:
  - a positions store with the broker's own as-of time (not Nivesh's read time);
  - grouping by underlying, with F&O contract normalisation (a canonical key, lot size; broker codes don't match
    NSE, e.g. ICICI's SONBLW = NSE's SONACOMS);
  - payoff, breakeven, Greeks and scenario P&L, reusing `option_pricing.py` and `strategy_plan/payoff.py` (already
    used by R1's visual answers and the desk);
  - distance to stop, combined exposure, daily realised P&L, risk-limit use;
  - stale-price / near-expiry / breach warnings.
- **Hub fixes (M):**
  - a real review step before an import commits (today the broker callback commits straight away);
  - one upload path with a preview, instead of three inconsistent ones (only the desk's Portfolio tab previews;
    Settings/Onboarding/Brokers post straight to the route);
  - F&O-position and trade-history import templates (today only holdings/MF layouts exist);
  - a manual-entry UI (the backend route exists; nothing in `/app` calls it);
  - a price-freshness stamp on stored rows (0 of 125 staging rows have one today) and transaction-based cost basis
    for broker rows (today only the CAS-delta estimate exists).
- **My Portfolio charts (M):** a treemap, an equity curve vs Nifty 50, DMA 20/50/200 health per holding (the data is
  already in Postgres `stock_technical_features`), a per-stock evidence panel.
- **Position-aware suggestions:** near stop, approaching expiry, stale price — blocked on the positions store above,
  since brokers give no stop price to compare against.

### R3 — Daily review and the real suggestion engine
Sized from the 30-Oct suggestions audit (`audits/E_suggestions.md`). The suggestion engine itself is sized L.

- **Q15 "What did I learn from today's trades?" (BUILT, branch `feat/dtc-r3-daily-review`, PR pending, stacked on
  #422)** — visual-answer intent `daily_review`: the paper book's closed trades for the day (or the ISO week), plan vs
  actual with the R achieved, how each exit happened (the plan's rules vs closed by you, gaps through the stop), what
  the risk checks refused, and a `₹` equity curve of cumulative net realised P&L. When nothing was recorded that day it
  reviews the latest day with activity and names both dates (stale notice when older than the previous session). It
  says plainly that there is no live signal hit-rate (`positional_outcomes` is empty; the idea scorecard is a static
  backtest). Staging has no closed paper trade yet, so the real capture shows the empty-trades branch with 3 refused
  entry requests; the populated branches are unit-tested on MOCK data. Reports:
  `test_reports/dtc_r3_daily_review_{backend,frontend}_20261031.md`.
- **The suggestion engine**, replacing today's static, scored prompt list:
  - the 5 stores from the brief: `suggestion_rules`, `suggestion_events`, `suggestion_instances`,
    `suggestion_feedback`, `query_templates` (today: nothing — no code, no collections);
  - scheduled + event-driven evaluation (reuse the desk-alerts cron pattern: dedup key, one-shot firing), with
    cooldowns;
  - ranking beyond today's score + persona boost: urgency, evidence quality, interest weights, dedup across
    surfaces;
  - dismiss / refresh / "Why am I seeing this?" (today: nothing tracks a prompt's feedback);
  - the 3-way split — informational / validated signal / actionable risk alert — as one field plus its own wording
    and SEBI-safe card treatment (today the vocabulary is scattered: prompt tier, insight severity, "fired");
  - the 4 tabs (For You / Market / My Trades / F&O Lab): a category/audience on every template, and Trader mode
    passing it (today the backend filter covers only 5 investor categories, and v5 never sends one);
  - `query_templates` actually used: a card's click already asks free text through the same LangGraph router R1's
    visual answers use; map each template to its intent/agent instead of relying on text matching alone.
- **Portfolio scenarios:** Nifty −2%, a sector-reduction "what if", reusing the risk service's existing stress-test
  tools (today: a flat percentage drop only, no beta or F&O weighting).

## Decisions for the owner
1. **Wording for "Is this stock a buy now?"** The decision label proposed is **Setup ready / Wait / Avoid / No setup
   yet**, with "an idea to review, not a recommendation". The alternative is the brief's Buy / Wait / Avoid. The plan
   service decides the status; the LLM never does.
2. **Live data each day** needs the admin Kite login after 06:00 IST. Without it, every answer says "end of day, 29 Oct".
3. **Feeds:**
   - Sensibull (FII F&O positioning): restore it, or drop it from answers;
   - IV history: install the cron;
   - BSE announcements: 403;
   - GIFT Nifty: no source today; choose one, or leave pre-open questions on global indices only.
