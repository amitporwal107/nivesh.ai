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
| `bars` | `unit: "₹"\|"₹ Cr"\|"%"\|"×"\|"count"`, `orientation: "h"\|"v"`, `items: [{label, value, tone?, sub?}]`, `baseline?: number` | horizontal or vertical bars, signed colours; `"₹"` prints a signed rupee amount (`+₹1,234.50`, Release 3's equity curve) |
| `heatmap` | `unit: "%"`, `cells: [{label, value, group?, sub?}]` | a grid of tiles coloured by value |
| `quadrant` | `x: {label, unit}`, `y: {label, unit}`, `quadrants: {tr, tl, br, bl}` (names), `points: [{label, x, y, quadrant}]` | a 2×2 scatter, e.g. price change vs OI change (long buildup …) |
| `ranked` | `columns: [{key, label, align?: "left"\|"right", format?: "price"\|"pct"\|"x"\|"int"\|"text"}]`, `rows: [{symbol?, cells: {key: value}, tone?, plan_id?, ask?}]` | a ranked table; a row with `ask` asks that follow-up; a row with `plan_id` opens its plan |
| `trade_plan` | `plan_id` | the existing compact decision card (DecisionCardById) |
| `list` | `items: [{text, tone?, sub?}]` | a short list (warnings, events, reasons) |
| `notice` | `tone: "warn"\|"info"`, `text` | a callout for stale or missing data |

Formats: prices in ₹ with two decimals (a negative one with a true minus before the sign, `−₹14,406.00`); percentages with a sign and two decimals; ratios as `1.8×`; dates as
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

Release 2 added `open_trades`, `trade_validity`, `exit_options`, `fno_setups` and `position_size` with the blocks above
(no new block type). Release 3:

| intent | Trader asks (examples) | blocks (smallest useful set) | sources (existing) |
|---|---|---|---|
| `daily_review` | What did I learn from today's trades? How did I do this week? My mistakes today? | kpis (closed, wins / losses, win rate, net realised P&L, average R) · ranked plan vs actual (planned entry, fill, stop, target, exit, R, net P&L) · list how the trades ended (plan's rules vs closed by you, gaps through the stop) · list what the risk checks refused · bars `₹` equity curve (cumulative net realised P&L per session) · notice: no live signal hit-rate | the paper book's closed trades (`desk_paper_trades`, read directly, not through the GET route that runs the exit rule) and the risk decisions log (`risk_decisions`) |

Sector view (31 Oct 2026):

| intent | Trader asks (examples) | blocks | sources (existing) |
|---|---|---|---|
| `sector_rotation` | Which sectors are leading and lagging? Show sector rotation today. Sector heatmap. | kpis (leading, lagging, sectors up today) · heatmap sectors (1-week return, best first; 1-day and 1-month in `sub`), each cell carrying `members`: its five strongest stocks by the day's move with index weight and an `ask` | desk sector returns · desk sector constituents (NSE index lists with bhavcopy closes) |

A heatmap cell may carry `members: [{label, value, sub?, ask?}]`, shown when the tile is selected. `sector rotation` is no longer a
`smart_money` phrase: FII/DII flows, buildup and smart money stay there; the sector questions have their own answer.

Block fields added on 31 Oct 2026 (all optional; a payload without them is unchanged):

| block | field | meaning |
|---|---|---|
| `ranked` row | `alternatives: [row]` | the row's other structures, one level deep, same columns; the table shows "+N more ›" (the F&O board folds an underlying's alternatives under its lead) |
| `ranked` row | `badge: text` | a tag by the symbol: `Live`, or the close the row was priced at (`30 Oct close`) |
| `ranked` row | `tips: {cellKey: text}` | a tooltip on a cell (a bought put's theoretical to-zero profit is only here) |
| `ranked`, `quadrant` | `detail: "fno"` | a row or point with a stock opens that stock's option chain and futures build-up (inside the app shell), with "Open in Chart Analysis ›" |
| `heatmap` cell | `members: [{label, value, sub?, ask?}]` | the stocks behind a tile, shown when it is selected |
| `notice` | `actions: [{kind, label}]` | `kite_login` (admins), `connect_broker`, `set_risk_profile` |

A saved setting (a risk profile) is a source with status `fresh` whatever its date: the freshness rule is for prices and flows.

`daily_review` reviews the day asked about (or the ISO week when the question names the week). When nothing was
recorded then, it reviews the latest day (week) that has activity and names both dates; its `as_of` is that day, so a
day older than the previous session carries the stale notice. `avoid_today` (Q14) is not built.


## Open trades on the broker book, and answers that keep themselves current (31 Oct 2026)

`open_trades` shows the user's own broker positions beside the paper trades, labelled, by the user's broker configuration:

| state | what the answer has |
|---|---|
| no broker connected | a `notice` (id `no-broker`) with the `connect_broker` action; the paper trades as before |
| broker hub off for the user | a `notice` (id `no-hub`), no action |
| session ended | a `notice` (id `ended-<account>`) with a `connect_broker` action ("Sign in to <broker> again"); the account's LAST STORED read (rows badged `As of <date time>`, the notice names the time, a read older than the previous session also carries the stale banner); funds "Not available" |
| a read failed | a `notice` (id `failed-<account>`), the last stored read if any; the other accounts are unaffected |
| signed in | blocks `book` (kpis), `positions` (ranked, one row per broker position), `levels` (ranked, one row per underlying), `accounts` (ranked), `commentary` (list), then the paper blocks `summary` and `trades` |

Figures: quantity, average, price and P&L are the broker's own (a share's price and P&L move with Kite's live price while the market is open;
a future or option keeps the broker's price of its last read, said on hover). A row the broker sent no P&L for (ICICI Direct sends null for
futures and options) is marked at the last price and says so. Stop and target are the user's own levels, else the plan they recorded when it
points the same way as the position; the loss at the stop is never the price falling to zero; margin is Zerodha's calculator for the F&O legs
(shares are paid in full), else "Needs Kite login" with the `kite_login` / `connect_broker` actions; available cash, collateral and used margin
are each broker's own funds figures, read only while its session is live. `commentary` holds the deterministic checks (distance to the stop,
loss at the stop, expiry, the plan's direction against the position, margin as a share of the account's cash); the written commentary explains
them and adds no figure.

Envelope field `refresh` (optional): `{path, interval_s, block_ids}`. The page asks `path` (an `/api/` route, authenticated as the user) every
`interval_s` seconds (at least 5) while the tab is visible, the answer is on screen and it was built today, and swaps in the blocks the response
names by `id`. The response is `{generated_at, mode, blocks: [...], refresh: {active, interval_s, why}}`; `active: false` tells the page to stop
(the market closed, no live session). A failed ask keeps the blocks shown, the page says "Live feed lost" with the time of the last good read, backs
off, and stops after three failures. `GET /api/positions/book/live` serves the open-trades answer. The server never calls a broker more than once
per 15 s per account however many pages ask (see services/positions/book.py).
