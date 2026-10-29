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

### R1 — Daily Trader home and visual answers for market and opportunities (in progress)
- **Trader home:** the owner's six entry points, a question box with stock autocomplete, and "Explore this question".
  Built on branch feat/daily-trader-copilot.
- **Visual-answer engine.** The contract, an intent resolver, and builders on existing services for these intents:
  - `market_view` (Q1)
  - `smart_money` (Q2)
  - `top_opportunities` (Q3)
  - `breakouts` (Q4)
  - `unusual_volume` (Q5)
  - `stock_decision` (Q6 and Q7)
  - `expected_move` (Q11)
- **Rendering.** A chart registry draws the answers: KPI strip, annotated candles with levels and bands, bars,
  heatmap, buildup quadrant, ranked table, trade-plan card, data-quality footer. It works in the chat and in the desk dock.
- **Follow-up questions** after every visual answer: rule-based, each one a supported question.

### R2 — Positions, F&O and risk
- **Questions:** Q8 (thesis check), Q9 (exit options), Q10 (F&O setups), Q12 (sizing), Q13 (open trades), Q14
  (avoid list).
- **Open Positions workspace:**
  - store broker position snapshots with the broker's as-of time;
  - group positions by underlying;
  - payoff and Greeks from the existing engines;
  - distance to stop;
  - risk-limit use.

  Today, positions are read live and never stored, and the open-positions view only lists rows.
- **Hub gaps:**
  - a review step before the import is committed;
  - one upload path, with preview and templates;
  - a manual-entry screen;
  - F&O contract normalisation (canonical key, lot size).
- **Position-aware suggestions:** near stop, approaching expiry, stale price.

### R3 — Review and validation
- **Q15:** equity curve, win/loss, plan versus actual, rule adherence.
- **Live signal outcomes:** `positional_outcomes` is empty today. Signal hit-rate by setup.
- **Suggestion engine:** rules, events, instances and feedback, with dismiss, "Why am I seeing this?" and cooldowns.
- **Portfolio scenarios:** Nifty −2%, sector reduction.

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
