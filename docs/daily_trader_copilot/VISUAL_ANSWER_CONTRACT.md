# Visual answer contract — `visual-answer-v1`

The owner (30 Oct 2026) asked that the Copilot answer a trader's question with a visual decision dashboard (charts,
heatmaps, tables and a trade plan), not paragraphs. One engine does it for every question: the question is classified,
the data is fetched from the platform's own services, and the answer is a structured payload rendered by a fixed set
of chart templates. **The LLM never produces chart data, prices or signal states.** It writes the explanation from
the same facts the payload carries.

```
question ──► intent resolver ──► builder (real data, existing services) ──► visual_answer payload ──► chat widget
                                                     └──► facts block ──► LLM explanation (grounded in the payload)
```

## Where it runs

- **Backend:** `backend/services/copilot_visual/`. `resolve_intent(message, persona, surface, last_symbol)` returns an
  intent, or none. `build(intent, …)` returns the payload.
- **Chat:** `routes/chat.py stream_chat` runs it as a pre-step, as it already does for the trade idea:
  - it sends the payload as a widget frame, `widget_type: "visual_answer"`;
  - it passes the payload's facts to the specialist node as a delimited data block;
  - it pins the node that should explain (market_analyst, stock_analyst, …).
- **Frontend:**
  - `components/chat/visual/VisualAnswer.tsx` renders the payload with a registry of block components;
  - `ChatWidget` adds `case "visual_answer"`;
  - the trading-desk Copilot dock renders it inline, as it does the trade-plan card.

## Payload

```jsonc
{
  "schema": "visual-answer-v1",
  "intent": "market_view",               // one of the intents below
  "title": "Market view · Nifty and Bank Nifty",
  "as_of": "2026-10-29",                 // the session the data describes (IST trading day); null if unknown
  "generated_at": "2026-10-30T04:50:00+05:30",
  "mode": "eod",                         // "live" | "eod" | "mixed" — live only when every number shown is live
  "headline": { "text": "Nifty rose 1.05% to 22,936.75; 62% of stocks advanced; India VIX 15.12.", "tone": "up" },
  "decision": null,                      // see below; null for informational intents
  "blocks": [ /* Block, in display order */ ],
  "evidence": [ { "label": "FII cash", "value": "−₹943.60 Cr", "source": "NSE FII/DII", "as_of": "2026-10-29" } ],
  "data_quality": {
    "sources": [ { "name": "NSE bhavcopy", "as_of": "2026-10-29", "status": "fresh", "note": null } ],
    "stale": false,                      // true when any source behind a shown number is older than the latest session
    "missing": [ "GIFT Nifty: no source" ]
  },
  "follow_ups": [ { "label": "Where is smart money moving?", "query": "Where is smart money moving?" } ],
  "caveat": "Built from end-of-day data of 29 Oct 2026. Ideas to review, not recommendations; nothing is sent to a broker."
}
```

Rules for every builder:
- Every number comes from a platform service, table or route. **Nothing is invented, estimated or filled in.** If a
  number is unavailable, leave it out and say why in `data_quality.missing` or a `notice` block.
- `as_of` per source. A source older than the latest completed session is `stale`, and the payload says so with a
  `notice` block. Owner rule: only today's live data or the latest completed session (T-1) counts as current.
- Wording: ideas, not picks or recommendations. Never "buy now". The decision labels are fixed (below).
- Personal data (paper trades, risk profile, broker positions) only for the asking user.

### Decision (stock and plan intents)

```jsonc
{ "status": "setup_ready",          // "setup_ready" | "wait" | "avoid" | "no_setup" | "info"
  "label": "Setup ready",           // fixed per status: Setup ready · Wait · Avoid · No setup yet · For information
  "reason": "Close above the breakout level 1,195 on 2.1× average volume.",
  "conditions": [ { "text": "Close above ₹1,195", "met": true }, { "text": "Volume ≥ 1.5× its 20-day average", "met": true } ],
  "invalidation": "A close below ₹1,160",
  "plan_id": "tp_…" }               // the stored TradePlan, when there is one
```

`status` comes from the plan service (TradePlan eligibility: plan → setup_ready, wait → wait, rejected → avoid,
no_setup → no_setup), never from the LLM.

## Blocks

Each block is `{ "type": …, "id": "…", "title": "…", "note": "…" | null, …data }`.

| type | data | renders as |
|---|---|---|
| `kpis` | `items: [{label, value, sub?, tone?: up\|down\|neutral\|warn}]` | a strip of figures |
| `candles` | `symbol, bars: [{d, o, h, l, c, v}]`, `overlays?: {ema20?, ema50?, ema200?}` (series aligned to bars), `levels?: [{kind: support\|resistance\|entry\|stop\|target\|wall_call\|wall_put\|max_pain, price, label}]`, `band?: {low, high, label}` | the desk's CandleChart with dashed level lines and a shaded band |
| `bars` | `unit: "₹ Cr"\|"%"\|"×"\|"count"`, `orientation: "h"\|"v"`, `items: [{label, value, tone?, sub?}]`, `baseline?: number` | horizontal or vertical bars, signed colours |
| `heatmap` | `unit: "%"`, `cells: [{label, value, group?, sub?}]` | a grid of tiles coloured by value |
| `quadrant` | `x: {label, unit}`, `y: {label, unit}`, `quadrants: {tr, tl, br, bl}` (names), `points: [{label, x, y, quadrant}]` | a 2×2 scatter, e.g. price change vs OI change (long buildup …) |
| `ranked` | `columns: [{key, label, align?: "left"\|"right", format?: "price"\|"pct"\|"x"\|"int"\|"text"}]`, `rows: [{symbol?, cells: {key: value}, tone?, plan_id?, ask?}]` | a ranked table; a row with `ask` asks that follow-up; a row with `plan_id` opens its plan |
| `trade_plan` | `plan_id` | the existing compact decision card (DecisionCardById) |
| `list` | `items: [{text, tone?, sub?}]` | a short list (warnings, events, reasons) |
| `notice` | `tone: "warn"\|"info"`, `text` | a callout for stale or missing data |

Formats: prices in ₹ with two decimals; percentages with a sign and two decimals; ratios as `1.8×`; dates as
`29 Oct 2026`.

## Intents (Release 1)

| intent | Trader asks (examples) | blocks (smallest useful set) | sources (existing) |
|---|---|---|---|
| `market_view` | What is the market view today (for Nifty and Bank Nifty)? Is the market trending? | kpis (Nifty, Bank Nifty, VIX, breadth, FII/DII cash) · candles NIFTY (60 sessions, EMA 20/50, call/put OI walls, expected-move band) · heatmap sectors (day %) | market snapshot / markets home, index closes, sector indices, F&O chain summary |
| `smart_money` | Where is smart money moving? | bars FII and DII cash (last 10 sessions) · heatmap sector rotation · quadrant F&O buildup (price % vs OI %) · ranked strongest long buildup / short covering | FII/DII flows, sector indices, F&O buildup |
| `top_opportunities` | Today's top 5 opportunities (with entry, stop-loss and targets) | ranked (rank, symbol, setup, entry, stop, target, reward:risk, score) · trade_plan for the first | AI scanner watchlist day (Top 10) and its TradePlans |
| `breakouts` | Which breakouts are confirmed? | ranked (symbol, breakout level, close, volume ×, stop) · candles of the first with the level · bars volume × | positional watchlist `breakout_confirmed` |
| `unusual_volume` | Which stocks have unusual volume? | bars relative volume (top 10) · ranked (symbol, price %, volume ×, delivery %) | stock features (rvol / vol_z20, delivery avg), bhavcopy |
| `stock_decision` | Is X a buy now? Entry, target and stop-loss for X? | decision · candles X with entry/stop/targets · kpis (R:R, size, max loss) · trade_plan | the desk plan (copilot_trade_idea.build) and its TradePlan |
| `expected_move` | What is the expected move in Nifty? | kpis (ATM IV, expected move ±, PCR, max pain, expiry) · candles NIFTY with the band and the OI walls | F&O chain summary (end of day) |

Releases 2 and 3 add `open_trades`, `trade_validity`, `exit_options`, `fno_setups`, `position_size`, `avoid_today` and
`daily_review`, with their own blocks (payoff, exposure, gauge, equity curve). They follow this contract.
