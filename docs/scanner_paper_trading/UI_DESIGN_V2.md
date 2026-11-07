# Paper Trading v2: the owner's six-view design (5 Nov 2026)

Source: "Nivesh Paper Trading (standalone).html", sent by the owner on 5 Nov 2026 at ~07:50 IST. It was made in Claude
Design from the Scanner-to-Paper Trading PRD and the Workflow (docs/prd/). Every figure in it is illustrative sample data.
The HTML is not in the repo; this file records its structure, copy and behaviour so the build can follow it exactly.

## Owner decisions (5 Nov, ~08:00 IST)

- **Placement:** Trade Desk › Paper Trading.
- **Scope of the replacement:** the owner wrote "We need to completely replace the current paper trading dashboard".
  - The Paper Trading menu becomes exactly these six views, in this order.
  - Today's sub-views go: Live desk, Trade journal, P&L dashboard, Opportunities, Analytics, Settings.
  - The three Risk Desk SPT views go too: Trading overview, Capital allocation, Portfolio risk.
  - Their URLs redirect to the matching new view. No code is deleted in this release.
  - Actions that only those screens had move into the new ones; see §5.
- **F&O: "cash now, F&O next".**
  - The scanner pipeline paper-trades cash longs only.
  - F&O panels read the desk's existing paper F&O structures (desk_paper_trades strategy trades).
  - Scanner F&O ideas appear as TRACKED, with no approve.
  - Scanner-to-spread orders are the next build.
- **Wording:**
  - "Allocation changes · ranked by ₹ impact" replaces the design's "Recommended changes"; the rule bars recommend /
    pick / suggested.
  - Entry, Stop, T1, T2, "Approve paper trade", "Reject" and "Add to watchlist" are allowed on these paper screens.

## 1. Navigation (copy it exactly)

The design has a left "Trading" menu: 01 Overview · 02 Scanner opportunities · 03 Capital allocation · 04 Portfolio risk ·
05 Real-time P&L · 06 Strategy analytics.

- **In the app:** these are the Paper Trading sub-views, in that order and with those labels.
- **Keys:** `sub=` keys are `overview · opportunities · allocation · risk · pnl · analytics`. Use `pnl` for Real-time
  P&L so old P&L links keep working.
- **Default:** `overview`.
- **Old keys:**
  - `live`, `journal` → `pnl`
  - `settings` → `allocation`
  - Risk Desk `view=overview` → `tab=trade&view=paper&sub=overview`
  - Risk Desk `view=allocation` → `sub=allocation`
  - Risk Desk `view=portfolio` → `sub=risk`
- **Labels:** each number ("01".."06") is shown small and mono before its label, as in the design. The 06 Strategy
  analytics label is shortened to "Analytics" only if the chip row overflows at 390 px.
- **Opportunities badge:** the design shows a mono amber count = the number of opportunities awaiting the user. It is
  live from `/api/v1/proposals` (state AWAITING_USER_APPROVAL), and hidden at 0.
- **Account card** (the design's sidebar card "Account · Mode / Positional Paper · INR 10L / [● Approval mode]"):
  - Shown on every view, at the top right of the Paper Trading header strip.
  - Shows the paper account, its capital and the SPT mode pill.
  - Clicking the mode pill opens the mode chooser (off / tracking / approval / auto; Auto asks to confirm). This is the
    only mode control; the old Settings screen is gone.
- **Top status strip**, as in the design, on every view:
  - `● Live · paper` (mint)
  - `Market open · HH:MM IST`, from the live feed status
  - `Data fresh · 1.2s`: last tick age; amber over 10 s, red when the feed is down
  - `Policy vN`: the combined policy version, §3
  - Right-aligned `Kill switch · ACTIVE` (mint pill when entries are allowed) or `Trading halted` (danger pill)
- **Theme:** the app's existing dark/light theme. There is no separate toggle.

**Visual language** is the V5 tokens the design uses (frontend-v5/design/nivesh-tokens.css; the app's `--cp-*` /
mint/amber/indigo/danger variables).
- **Type:** serif display for headlines and big metrics (`nv-synthesis` 32px, `nv-h1` 28px, `nv-metric` 32px tabular).
  Mono 10px uppercase eyebrows. Inter for body.
- **Containers:** cards are `bg-1` + hairline + radius 14; inner tiles are `bg-2` radius 10–12.
- **Pills:** mono 10px uppercase, tinted (mint = good, amber = caution, indigo = info/capital, danger = breach).
- **Bars:** 6–8px rounded on a `bg-3` track, coloured by level: mint ≤ 80% of limit, amber > 80%, danger > 100%.
- **Numbers:** tabular everywhere.

## 2. The six views

### 01 Overview

- **Header** (eyebrow "Trading overview"):
  - **Synthesis headline:** one sentence built from data, never an LLM. Pattern: "{n} setups cleared the risk engine
    today — but {worst concentration} already carry {x}% of open risk."
    - If there is no concentration warning: "{n} setups cleared the risk engine today."
    - Highlighted span in amber.
  - **Prose line:** "{signals} scanner signals consolidated into {opps} opportunities. {blocked} is blocked by … and
    {reduced} is reduced to fit the risk budget."
- **KPI tiles** (auto-fit, min 170px), six tiles:

  | Tile | Value | Sub-line |
  |---|---|---|
  | Account equity | value | "start ₹X" |
  | Daily P&L | mint/danger | "limit -X% · used Y%" |
  | Capital deployed | value | "N% · cash ₹" |
  | Open planned risk | amber when > 80% of the budget | "of X% budget" |
  | Drawdown | value | "warning at X%" |
  | Positions | "n / max" | "k pending orders" |

- **Two cards** (1.3fr / 1fr):
  - **"Today's pipeline · signal → position":**
    - Rows, each a label, a bar and a count: Scanner signals → Opportunities → Qualified → Risk approved → Orders filled
      → Open positions.
    - Bar width is relative to scanner signals. Colours: ink-3, indigo, indigo, mint, mint, mint.
    - Footnote: "A scanner signal is not a trade. Each stage can reject, expire or reduce."
  - **"Risk warnings":** a dot-coloured list with a title and a mono meta line ("RISK_REJECTED · 11:02").
    - Sources: risk-engine refusals today, near-limit warnings (> 80%), stop-approaching positions (exit watch),
      data/feed health.
    - Ends with a mint "All feeds healthy" line when that is true.

### 02 Scanner opportunities

- **Header:** eyebrow "Scanner opportunities"; h1 "Consolidated setups, ranked after the risk engine has spoken."
- **Layout:** two columns (1.5fr / 1fr), aligned at the top.
- **Left card, the table** (min-width 640):

  | Column | Content |
  |---|---|
  | Symbol | name + mono "LONG · EQ" |
  | Signals | "N sources" |
  | Opp score | serif 22px |
  | Entry | value |
  | R:R | "2.0:1" |
  | Risk ₹ | value |
  | Decision | pill |

  - **Decision pills:**
    - APPROVE: mint
    - APPROVE REDUCED: amber
    - CONDITIONAL: indigo
    - BLOCKED: danger
    - WATCHLIST: plain
    - TRACKED: plain; F&O ideas, cash-now decision
    - After a user action the pill shows the action (ORDER CREATED / USER REJECTED / WATCHLISTED) in mint.
  - The selected row is highlighted with `bg-3`.
  - Footnote: "Opportunity score rates setup quality. It is not a probability of profit and scanner scores are never
    summed."
- **Right card, the detail** (sticky top 20):
  - **Header:** mono eyebrow "{id} · {status}"; status is AWAITING USER APPROVAL / ORDER CREATED / NO ORDER.
    - Serif 30px symbol, company name under it.
    - Decision pill on the right.
  - **Reason sentence:** 14.5px.
  - **"Supporting signals · N":** tiles of scanner name · time · score.
  - **"Strategy plan":** 4 tiles.
    - Entry: bg-2
    - Stop: danger-soft, red eyebrow
    - T1 and T2: mint-soft, mint eyebrow
  - **Sizing row:** 3 columns, divided by hairlines top and bottom.
    - Quantity (serif 24) with a note: "full size" / "reduced from N" / "would be N".
    - Capital.
    - Planned risk.
  - **"Risk engine checks":** rows of glyph + check + value.
    - Glyphs: ✓ mint pass, ! amber warn, × danger fail.
    - Every check from the proposal's risk record (`checks[]`), not only the failed ones.
  - **Buttons:**
    - "Approve paper trade" (primary). For CONDITIONAL it reads "Arm conditional order"; after an action it reads
      "Done · order created".
    - "Add to watchlist": the desk's existing watchlists API, default list.
    - "Reject": asks for a one-line reason, as today.
    - Approve is disabled (opacity .35) for BLOCKED, WATCHLIST and TRACKED, and after an action.
  - **Footnote:**
    - When the item is hard-refused: "The risk engine has the final say. User approval cannot override a hard limit."
    - Otherwise: "Approval expires if price leaves the entry range, data goes stale or policy changes."

### 03 Capital allocation

- **Header:** eyebrow "Capital allocation".
  - **Synthesis:** "₹{deployed} is deployed. {bucket} uses {cap%} of it but carries {risk%} of open risk." Built from
    data; amber span.
  - **Prose:** "Capital and risk are allocated separately. F&O capital is measured by margin and F&O risk by strategy
    max loss, so a small margin can still carry large risk."
- **KPI tiles** (min 200):
  - Account equity ("cash ₹")
  - Deployed ("N% of equity")
  - Reserved · pending ("n orders")
  - Risk budget left ("₹ of X%")
- **Card "Configure · allocation policy"** (§3):
  - **Sub-line:** "Per-trade risk of ₹X per trade on ₹10L equity. Bucket targets always total 100%."
  - **Right side:** policy-version pill (mint "Policy vN · saved" / amber "Policy vN+1 · draft"), then Defaults,
    Discard and "Save policy". Discard and Save are dimmed when nothing has changed.
  - **Fields:** each row has a label, a number box with its unit, and a slider under it.
    - Equity positional %
    - Equity intraday %
    - F&O strategies %
    - Risk per trade %
    - Max open positions
  - **Bucket rule:** each bucket is capped so the three never exceed 100.
  - **"Unallocated reserve"** = 100 − the three, read-only. Amber under 5%. Note: "Derived: 100% minus the three buckets.
    Keep at least 5%."
- **Grid** (1.4fr / 1fr):
  - **Left, "Capital vs risk · by strategy bucket":**
    - Legend: indigo dot "CAPITAL USED", amber dot "RISK USED".
    - Per bucket: name + "TARGET n%". Two bars: capital used against the bucket target (indigo, danger if over), and risk
      used against the bucket's share of max open risk (levelled colours). Each bar has a % value.
    - Last row: Unallocated reserve.
  - **Right column, stacked:**
    - **"Sector exposure · % equity":** bars against the max-sector limit, indigo with amber/danger levels. Note: "Bars
      show use of the configured sector limit."
    - **"F&O allocation · margin vs max loss":**
      - Indigo pill "Margin ₹X" (total).
      - Per structure: name, margin (indigo), max loss (amber), and a bar of max loss against the per-strategy limit.
      - Note: "Indigo is margin (capital). Amber is max loss (risk). Bar shows max loss against the per-strategy limit set
        in Portfolio risk."
      - Data: the desk's open paper F&O structures.
    - **"Allocation changes · ranked by ₹ impact":** numbered rows (01, 02 …), a sentence, and the ₹ impact (mint when it
      lowers risk or frees cash, danger when blocked).
      - From `/api/v1/allocation/recommendations/{id}` plus reduction, block and lapse events.
      - Wording: describe the change; never "should", "recommend" or "suggest".

### 04 Portfolio risk

- **Header:** eyebrow "Portfolio risk".
  - **Synthesis:** "Within every limit, with {nearest} the nearest to a breach." When something is breached: "{n} limits
    breached: {names}."
- **Card "Configure · risk limits"** (§3):
  - **Sub-line:** "Risk budget left X% (₹Y). The risk engine enforces these as hard limits."
  - **Fields:** Max total open risk %, Daily loss limit %, Weekly loss limit %, Drawdown restricted at %, Trading halt at
    %, Max single stock %, Max sector exposure %, Max margin utilization %, F&O max loss per strategy %.
  - **Warning:** "Halt threshold must sit above the restricted threshold." when halt ≤ restricted. Save is refused then.
- **Grid** (1fr / 1fr):
  - **Left, "Limit utilization":**
    - Rows: name, an optional mono status (NEAR LIMIT amber / BREACH danger), "value / limit", and a levelled bar.
    - Rows: open planned risk, stressed portfolio loss, daily loss, weekly loss, drawdown, max single stock, margin
      utilization, open positions, and the largest F&O strategy's max loss.
  - **Right, stacked:**
    - **"Correlation · 60d returns" / "≥0.70 = concentrated":** a matrix of the open positions plus the selected
      candidate (up to 6).
      - Indigo cell tint by |ρ|; danger tint and text when ρ ≥ 0.70; the diagonal is bg-3.
      - Row labels on the left, column labels on top.
    - **"Stress scenarios · portfolio ₹ loss":** rows of name, danger bar and ₹.
      - Scenarios: Nifty −2%, the largest sector gaps −3%, correlated stops hit, gap beyond stops +25%, IV +10 pts (F&O).
- **Card "F&O · N strategies · net Greeks":**
  - Indigo pill "Sum of max loss · ₹X".
  - Greek tiles: Net delta (with the per-structure split), Net gamma, Net theta "₹ / day", Net vega "₹ / IV pt", Margin.
  - Below, two columns:
    - "Max loss by strategy · vs per-strategy limit": a row and bar per structure, a mono amber NEAR LIMIT / BREACH flag,
      and a note (amber "Unhedged · hedge leg pending" for partly filled ones).
    - "F&O scenario P&L · all strategies": underlying ±1/±2%, IV ±5 pts, 1-day theta, and expiry at a level. Mint or danger
      values. Note "Scenarios are assumptions, not forecasts."
- **Card "F&O structure caps (additional checks)":**
  - Collapsible with a chevron.
  - Right-side pill toggles the gate: "GATE ON FOR YOUR ACCOUNT" (mint) / "GATE OFF FOR YOUR ACCOUNT" (amber).
  - Note when off: "The policy gate does not check your paper writes, so these limits are not applied to them. The kill
    switch and the halt still apply." When on: "The policy gate checks your paper writes against these limits before an
    order is created. The kill switch and the halt also apply."
  - Table: Limit | Allowed (editable) | Used | Remaining.
    - Rows: Legs per structure, Lots per leg, Open structures, Capital at risk (₹ prefix), Defined risk only (Yes/No
      toggle).
    - Remaining is "—" when the gate is off.
  - Footer: mono "RISK CONTROLS · RULES-BASED · FNO-RISK-V1".
  - This is the existing risk-controls feature (services/risk_controls; Risk Desk › Policy & runtime). Reuse its API and
    behaviour; only the layout is new.

### 05 Real-time P&L

- **Header row:**
  - Left: eyebrow "Real-time paper P&L"; a serif 64px total (mint/danger) and a mono "+x.xx% of equity".
  - Right: pill "● Streaming · N ticks" while the SSE stream is live, else "Polling · every 3 s".
- **KPI tiles:**
  - Unrealized ("n equity · k F&O strategies")
  - Realized ("n closed today · net of costs")
  - Open risk remaining ("x% of equity")
  - Daily loss used ("of X% limit")
- **Grid** (1.6fr / 1fr):
  - **"Intraday equity · net of costs":** an SVG area + line chart from `/api/desk/pnl/timeseries`. Dashed zero line.
    Mono axis "09:15 · HH:MM NOW · 15:30".
  - **"P&L by strategy":** rows of strategy name, "n positions" and a coloured ₹. Grouped by the opportunity's setup type,
    and F&O spreads as one row.
- **Card "Open positions · N":** table (min-width 860).

  | Column | Content |
  |---|---|
  | Instrument | name + mono setup · LONG |
  | Avg entry | value |
  | LTP | value |
  | Qty | value |
  | Stop → Target | value |
  | Position in plan | a 6px track from danger-soft to bg-3 to mint-soft, with a 3px marker at (LTP−stop)/(target−stop), animated |
  | R | value |
  | Unrealized | right-aligned, coloured |

  - Footnote: "P&L uses executable bid-side prices with modeled costs. A stop trigger is not a guaranteed fill at the
    stop."
- **"F&O strategy positions · N":** note "Risk is measured by strategy max loss, not margin." One card per structure:
  - **Header:** name; mono "underlying · EXP date · lots"; status pill ("FILLED · HEDGED" mint / "PARTIALLY FILLED ·
    UNHEDGED" amber); serif 30px P&L.
  - **Tiles:** Max loss (danger-soft), Max profit (mint-soft), Breakeven, Net delta, Net theta, Margin.
  - **Two bars:** "LOSS USED OF MAX" (danger) and "PROFIT CAPTURED OF MAX" (mint).
  - **Legs table:** Leg (BUY mint / SELL rose) | Contract | Entry | LTP | Filled "n/n" (amber when unfilled) | Leg P&L
    ("PENDING" amber for an unfilled leg).
  - **Partial fills:** an amber note box explaining the unhedged exposure and that new risk-increasing orders are blocked.
- **Rows come from `/api/desk/pnl`:** desk share trades, scanner positions (source "scanner") and desk paper F&O
  structures.

### 06 Strategy analytics

- **Header:** eyebrow "Strategy analytics · last 90 days".
  - **Synthesis:** "{best} earn the edge. {weakest} lack sample size to scale." Built from data.
- **KPI tiles** (min 150):
  - Trades ("closed")
  - Win rate ("avg win xR")
  - Expectancy ("+0.31R net of costs")
  - Profit factor
  - Max drawdown ("peak to trough")
  - Sharpe / Sortino
- **Grid** (1.5fr / 1fr):
  - **Left, "Scanner attribution · signal outcome, not trade outcome":** a table of Scanner | Signals | T+5 | T+20 |
    MFE / MAE | Evidence.
    - Evidence pill: Sufficient (mint, n ≥ 30) / Building (amber) / Low sample (danger, n < 15).
    - Data: `/api/v1/analytics/scanners`.
  - **Right, stacked:**
    - **"Certification · {setup}":** rows of glyph, criterion and value.
      - Criteria: minimum 50 completed trades; positive net expectancy; profit factor ≥ 1.3; out-of-sample validated;
        two or more market regimes.
      - Note: "Risk allocation increases only after every criterion passes. A winning streak alone does not qualify."
      - Criteria that cannot be measured yet show "not measured" with an amber "!". Out-of-sample is not measured until a
        walk-forward split exists.
    - **"Expectancy by market regime":** Uptrend / Sideways / Downtrend rows with a bar and "+0.52R". The regime is the
      validation's market regime at entry.

## 3. Policy configuration (Allocation + Risk)

- **One draft, one version:** both panels edit ONE policy draft. "Save policy" writes it as one new version; the pill
  shows "Policy vN · saved" or "Policy vN+1 · draft".
- **Field → store:**

  | Field | Store |
  |---|---|
  | Risk per trade | risk_profile `per_trade_risk_pct` |
  | Max total open risk | `max_open_risk_pct` |
  | Daily loss limit | `daily_loss_pct` |
  | Weekly loss limit | `weekly_loss_pct` |
  | Trading halt at | `max_drawdown_pct` |
  | Max single stock | `max_position_pct` |
  | Max sector | `max_sector_pct` |
  | Bucket targets | SPT extras `allocation_buckets_pct` (reserve = 100 − the three) |
  | Max open positions | SPT extras (positions cap) |
  | Drawdown restricted at | SPT extras `drawdown_ladder.restrict_at_pct` |
  | Max margin utilization | new SPT extra, F&O |
  | F&O max loss per strategy | new SPT extra |

- **Permissions** are the existing ones: the user may tighten; loosening needs an admin. A 403 `admin_required` names
  the field.
- **Validation:** buckets total ≤ 100 and reserve ≥ 0; halt > restricted; every value within its range.
- **Buttons:** Defaults returns to the profile-derived defaults (null overrides). Discard returns to the saved version.
  - Live preview: limit bars and bucket bars recompute from the draft before saving, as in the design.

## 4. Backend gaps (new; keep each small and pure where possible)

1. **`GET /api/v1/paper/overview`:**
   - KPIs (from risk/account).
   - Today's pipeline counts: signals (spt_signal_events of the IST day), opportunities, qualified, risk-approved
     proposals, filled orders, open positions.
   - Warnings list `[{level, title, code, at}]`.
   - Status strip data: feed state and age, kill switch, policy version.
2. **`GET/PUT /api/v1/paper/accounts/{id}/policy`:**
   - The combined view and write of §3, with `expected_version`.
   - Writes go through the existing risk_profile and SPT config services and their permission rules. If one write is
     refused, nothing is written.
   - Admin variant: under `/api/admin/spt/{user_id}/policy`.
3. **`GET /api/v1/risk/correlation/{id}`:** 60-day daily-return Pearson correlations for the open positions and an
   optional `?with=SYMBOL`. Prices from the same EOD source as validation; bonus/split-adjusted. If a series is too short
   the cell is null, with a reason.
4. **Stress test:** add the scenarios named in §2.04, keeping the current ones and labelling each assumption.
5. **`GET /api/v1/analytics/account/{id}?days=90`:**
   - Trades, win rate, avg win R, expectancy R net, profit factor, max drawdown.
   - Sharpe/Sortino from the daily P&L curve; null with a reason when there are fewer than 20 days.
   - By setup type, and by regime at entry.
   - The certification checklist per setup type.
6. **F&O summary** for the allocation and risk panels:
   - Per open desk paper F&O structure: margin, max loss, max profit, breakeven, net Greeks, fill state, scenario P&L.
   - Use the existing payoff/Greeks code.
   - Expose it as `GET /api/v1/paper/fno-structures`, or reuse `/api/desk/pnl` if it already has the fields.

## 5. Actions that must survive the replacement

- **From the P&L dashboard:**
  - Modify risk (paper share trades) and Simulate exit (desk close / scanner exit route).
  - Exit-watch alerts (live book stop/exit alerts). These go to Overview's Risk warnings and a row action in Real-time
    P&L.
  - Read-only Live (broker) rows. Real-time P&L gets a small "Paper / Live" switch, since the design shows paper only.
    This is the one addition; Live stays read-only.
- **From the Live desk and Trade journal:** closed trades and the journal of the desk's own paper trades. These become
  a "Closed trades" section at the bottom of Real-time P&L.
- **From Settings:** mode (account card) and admin edits (policy panel, for admins: a user-id picker in the policy card).

## 6. Rules

- **Data:** real data only. The design's sample figures must never ship. Every empty state says what is missing.
- **Test cases first:** test_reports/paper_v2_*_TESTCASES.md. Playwright on mocked bodies (labelled MOCK), plus a
  real-body render (SPT_REAL_DIR pattern, copilot-app-desk-spt-real.spec.ts).
- **Wording:** compliance lint (no recommend / pick / suggest) on every new view.
- **Layout:** 390 px with no sideways scroll; tables scroll in their own card.

## 7. API contract for the new endpoints (frontend and backend build against this)

Money is in rupees (₹, float, 2 dp); percentages are % of current paper equity unless named otherwise. Times are ISO-8601
UTC. A value that cannot be computed is `null`, with the reason in `notes` or in a sibling `*_reason` field. A
computed-looking default is never sent.

```text
GET /api/v1/paper/overview  → 200
{ account_id, as_of,
  status: { feed_state: "live"|"stale"|"down"|"closed", last_tick_age_s, session: "open"|"closed", kill_switch: {state, entries_blocked, text},
            policy_version, mode },
  kpis: { equity_rs, start_equity_rs, day_pnl_rs, day_loss_limit_pct, day_loss_used_pct, deployed_rs, deployed_pct, cash_rs,
          open_risk_pct, open_risk_limit_pct, drawdown_pct, drawdown_warn_pct, positions_open, positions_max, orders_pending },
  pipeline: [ {stage: "signals"|"opportunities"|"qualified"|"risk_approved"|"orders_filled"|"open_positions", label, count} ],
  warnings: [ {level: "danger"|"amber"|"mint", title, code, at, symbol?} ],
  headline: { setups_cleared, worst_concentration: {name, pct_of_open_risk}|null, signals, opportunities, blocked, reduced } }

GET /api/v1/paper/accounts/{id}/policy  → 200
{ account_id, version, saved_at, saved_by,
  fields: { <key>: { value, default, min, max, step, unit: "%"|""|"₹", store: "risk_profile"|"spt", overridden: bool,
                     loosen_needs_admin: bool, label } },
  derived: { reserve_pct, risk_budget_left_pct, risk_budget_left_rs, per_trade_risk_rs } }
  keys: per_trade_risk_pct, max_open_risk_pct, daily_loss_pct, weekly_loss_pct, restrict_at_pct, halt_at_pct,
        max_position_pct, max_sector_pct, margin_util_pct, fno_max_loss_pct, bucket_positional_pct, bucket_intraday_pct,
        bucket_fno_pct, max_positions
PUT  same path  body { expected_version, values: {<key>: number|null}, reason? }
     → 200 {policy}; 403 {detail:{code:"admin_required", loosened:[keys]}}; 409 {detail:{code:"version_conflict"}};
       422 {detail:{code, field, message}}
PUT  /api/admin/spt/{user_id}/policy  (admin; same body; reason required)

GET /api/v1/risk/correlation/{id}?with=SYMBOL&days=60  → 200
{ symbols: [..], matrix: [[number|null,..],..], days, threshold: 0.7, basis, notes: [..] }

GET /api/v1/risk/stress-test/{id}   (existing; add these named scenarios)
  scenarios[] gains: {name:"index_down", label:"Nifty -2%", loss_rs, assumption}, {name:"sector_gap", label:"<Sector> gap -3%", ...},
  {name:"correlated_stops", ...}, {name:"gap_beyond_stops", label:"Gap beyond stops +25%", ...}, {name:"iv_up", label:"IV +10 pts (F&O)", ...}

GET /api/v1/analytics/account/{id}?days=90  → 200
{ days, trades, wins, losses, win_rate_pct, avg_win_r, avg_loss_r, expectancy_r, profit_factor, max_drawdown_pct,
  sharpe, sortino, ratio_reason?, by_setup: [ {setup, trades, expectancy_r, profit_factor, win_rate_pct} ],
  by_regime: [ {regime: "uptrend"|"sideways"|"downtrend"|"unknown", trades, expectancy_r} ],
  certification: [ {setup, criteria: [ {key, label, status: "pass"|"warn"|"fail"|"not_measured", value} ], certified: bool} ],
  basis, notes: [..] }

GET /api/v1/paper/fno-structures  → 200
{ structures: [ { id, name, underlying, underlying_ltp, expiry, days_to_expiry, lots, lot_size, status: "filled"|"partial",
     hedged: bool, max_loss_rs, max_profit_rs|null, breakevens: [..], net: {delta, gamma, theta_rs_day, vega_rs_pt}, margin_rs,
     pnl_rs, legs: [ {side:"BUY"|"SELL", contract, entry, ltp|null, filled_qty, qty, pnl_rs|null, pending: bool} ],
     scenarios: [ {name, label, pnl_rs} ] } ],
  totals: { margin_rs, max_loss_rs, net: {...} }, limits: { fno_max_loss_pct, margin_util_pct }, basis, notes }

### §7 amendments by the backend build (5 Nov 2026)

Every shape above is built as written; the notes below are what changed or was added, and why. Added keys are additive
(a client that ignores them is unaffected). Tests: `backend/tests/test_paper_v2_*.py`; cases:
`test_reports/paper_v2_backend_TESTCASES.md`.

- **Policy version** = risk profile `version` + SPT config `version` (no new store). A mode change (PUT …/config) also
  moves it. A failed write that was rolled back moves it by 2 (the profile's write + its restore) with the values unchanged.
- **Policy PUT:**
  - `expected_version` is REQUIRED (422 `invalid_number`, field `expected_version`, when missing).
  - A value equal to the one in force is not a change: it is dropped, never pins an SPT override (a draft may send every
    field; e.g. `restrict_at_pct` keeps following ⅔ of the halt unless set to a different value).
  - 403 detail = `{code: "admin_required", field: null, message, loosened: [keys]}`; a bucket rise that lowers the
    reserve is a loosening, named by the bucket key(s) that rose.
  - 409 detail = `{code: "version_conflict", field: null, message, current_version}`.
  - 422 codes: `invalid_body`, `unknown_field`, `invalid_number`, `out_of_range`, `reserve_negative`,
    `halt_not_above_restricted`, `ladder_not_ascending`, `open_risk_below_per_trade`, `weekly_below_daily`, `no_change`,
    `reason_required`, `reason_too_long`.
  - The two stores are written one after the other (no multi-document transaction on staging Mongo). When the second
    write fails, the first is restored and the answer is the second store's refusal (409 `version_conflict`, its 403 /
    422 code) or NEW 500 `policy_write_failed`, each with `rolled_back: true` (nothing changed). NEW 500
    `policy_rollback_failed` `{rolled_back: false, written: [fields]}` when the restore failed too.
  - A restricted level above ⅔ of a halt lowered in the same save (and under ⅓ of the old halt) is judged against the new
    halt's default by the SPT store: 403 `admin_required` for the holder (the rest is put back).
  - The holder's PUT may omit `reason` for a tightening; the stored reason is then "Paper Trading › policy panel (no
    reason entered)" (the risk profile requires one on every change).
- **Policy GET additions:** per field `looser_when` ("higher" | "lower" | "reserve_falls") and `path`; top level
  `version_basis`, `stores {risk_profile, spt}`, `defaults_source`, `notes`, `view_version`; `derived.equity_rs` and
  `derived.reason` (why the rupee figures are null).
- **New SPT extras' defaults** (corrected 5 Nov: the first build used 0.65, a figure from the design's SAMPLE data, which
  must never ship):
  - `fno_max_loss_pct` = the risk profile's `per_trade_risk_pct` × 0.7, the same derivation as `risk_pct.fno` (owner rule
    5 Nov: defaults come from the user's risk profile; PRD §9.4 / §26 "F&O strategy risk 0.35 %"). 0.35 for the
    owner-default profile; it follows a later profile change unless overridden. Range 0.01–5.
  - `margin_util_pct` = 70, `defaults_source` "owner's Paper Trading v2 design (5 Nov); PRD has no figure; configurable".
- **Overview additions:** `status.feed_mode`, `status.kill_switch.code/reason`; warnings may carry `decision`;
  `headline.worst_concentration` adds `exposure_rs`, `pct_of_sector_limit` (reported only above 80 % of the max-sector
  limit); `basis`, `notes`. `kpis` is exactly the §7 list. When the account cannot be read every KPI is null and a danger
  warning `ACCOUNT_UNREADABLE` says why.
- **Correlation additions:** `cells` (each null off-diagonal cell with its reason), `concentrated_pairs`, `series`, `with`,
  `min_overlap`, `version`, `account_id`. `days` must be 20–250 (422 otherwise); a bad `with` → 422 `invalid_symbol`. At
  most 6 symbols (largest exposure first, `with` last); the rest are named in `notes`. A one-day move ≥ 18 % nulls that
  series (possible unadjusted bonus/split: the validation's EOD source is raw prices).
- **Stress test:** the five named rows are `{name, label, loss_rs, pnl_rs, assumption}` plus, where they apply,
  `reason` (why `loss_rs` is null), `shares_pnl_rs`, `fno_pnl_rs`, `sector`, `symbols`. The three existing rows keep their
  old shapes (they have no `loss_rs`). A `named` block gives the book counts and the unpriced rows. The named rows read
  the wider paper book (SPT + desk share trades + desk F&O); the old three read the SPT entries only.
- **Analytics:** closed SPT positions only (desk paper trades have no setup type or regime at entry). Additions:
  `profit_factor_reason`, `net_rs`, `daily_points`, `start_capital_rs`, `thresholds`, `version`, `account_id`;
  `by_setup[].net_rs`; `by_regime[].desk_regimes`. `ratio_reason` is always present (null when both ratios are worked
  out). Certification uses `warn` for a passing figure on fewer than 30 trades; out-of-sample is always `not_measured`, so
  no setup is `certified` until a walk-forward split exists.
- **F&O structures:**
  - `pnl_rs` and leg `pnl_rs` are GROSS of charges (`pnl_basis`); scenario `pnl_rs` is the CHANGE from the structure's
    model value now (not P&L since entry); each scenario row has an `assumption`.
  - `max_loss_rs` is null (with `max_loss_reason`) for an unbounded loss or a long future / shares without a long put
    (owner rule, 30 Oct); `loss_at_stop_rs` then gives the loss at the structure's stop when it has one.
  - `margin_rs` is Zerodha's calculator figure; null with `margin_reason` when the platform has no Kite session.
  - `status: "partial"` / pending legs cannot occur for desk paper structures today (every leg is recorded at once); the
    detection is built and tested on synthetic legs. Nothing blocks new orders on a partial structure, so the note says
    only that the filled legs carry unhedged risk.
  - Additions per structure: `family`, `summary`, `underlying_source`, `profit_unbounded`, `max_loss_limit_rs`,
    `max_loss_used_pct`, `max_loss_flag` (NEAR_LIMIT > 80 %, BREACH > 100 % of the per-strategy limit), `opened_at`,
    `notes`, `stress.iv_up_10_rs`; per leg `kind`, `expiry`, `strike`, `option_type`; `totals.count / pnl_rs / scenarios /
    partial / unhedged / margin_util_used_pct`; `limits.fno_max_loss_rs / margin_limit_rs / equity_rs`; `scenario_note`,
    `version`.
