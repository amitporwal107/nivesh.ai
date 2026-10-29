# Chart Analysis v2 (new chart interface) + Strategy Lab removed — design, contracts, test cases (2026-10-29)

Owner, 29 Oct (evening): pasted the "Nivesh Chart (standalone)" design (TVSMOTOR F&O chart) — "Please make changes here",
"We need new chart interface", then "We can remove strategy lab" — "completely".

Branch `feat/chart-analysis-v2` (from feat/live-chart-comprehensive = PR #409 + comprehensive-chart docs + futures bars /
options intraday + chart events). Screen: Trade Desk › Chart Analysis › Live chart (`?tab=trade&view=chart&sub=live&sym=`).
The design's numbers are placeholders; the build uses real data only. A figure the data does not give is "—" with why.
Nothing here is sent to a broker; paper only. The design's VIEW (desktop/mobile) and DARK/LIGHT buttons are canvas
controls, not product features: the app's own theme and width apply.

## Layout (the design, top to bottom; built as drawn)

Left card (full width when the basket is closed; with the basket panel on the right from 1000 px, stacked below that):
1. Header: SYMBOL · state badge · `NSE · CASH · DAILY|15M · SIGNAL <date> R<rev>` · LAST <price> · <date> · <source> · `+ PAPER TRADE`.
2. Stats row (6 tiles; 2 columns on a phone): PCR · FUT OI Δ (+ %) · MAX PAIN (vs spot) · ATM IV · IV PCTILE · EXP. MOVE.
3. SIGNALS ON CHART chips: Build-up · OI walls · Max pain · Pattern · Confirmation · RVOL · Events (Events is an addition:
   the owner asked for market events on the chart earlier on 29 Oct; the design is silent).
4. Readout line: bar time · O H L C · Vol · FUT OI · Δ (%) — follows the hovered bar (keyboard ← → too), else the last bar.
5. Chart (one SVG): price pane (candles, EMA 20, call wall / put wall / max pain dashed lines with tags, WATCH / READY
   markers on top, RVOL marker, CONFIRMED ✓ under the bar, trade lines ENTRY / STOP / TGT, last-price tag), FUTURES OI line,
   OI Δ PER BAR bars, BUILD-UP row (LB SB SC LU per 4-bar window), STRIKE LADDER on the right aligned to the price axis
   (put bars left, call bars right, OI-Δ ticks, P / C wall tags, click selects the strike), legend line under it.
   Click on the price pane sets the future's (else cash's) entry in the basket; drag STOP / TGT lines to move them.
6. OPTION CHAIN · <expiry> with OI | GREEKS: call columns (OI, OI Δ%) or (IV, VEGA, GAMMA, THETA, DELTA), LTP, B, S,
   STRIKE, B, S, LTP, put columns mirrored. Phone: OI Δ% only / THETA + DELTA only. ATM row and the selected row marked.
7. EXPIRY pills Current · Next · Far · Consolidated (with dates) and LADDER OI | OI Δ | VOLUME.
8. Summary lines: build-up badge + sentence; CALL WALL; PUT WALL; STRIKE <selected> (call OI, Δ, put OI, Δ, PCR at strike).
9. RECOMMENDED STRATEGIES · SYMBOL · EXPIRY: up to 3 cards (name, tag, legs, why, max profit, max loss, R:R, breakeven,
   net debit/credit, ADD TO BASKET).
10. Footer: snapshot time · chain end of day <date> · EDUCATIONAL · PAPER ONLY.

Right: PAPER TRADE basket (open by + PAPER TRADE, by a B / S, by ADD TO BASKET): Basket N legs; ADD Cash / Future;
STRATEGY presets (Long straddle, Bull call spread, Bear put spread, Short strangle, Iron condor); legs (side flip, name,
price, lots −/+, ×); STOP / TARGET on the underlying; net debit/credit; risk / reward; VIEW LEGS, PAYOFF AND GREEKS ↓;
hint; PLACE PAPER BASKET; the route's answer.

Below (when the basket has legs): Strategy · N legs · EXPIRY · DTE: legs table (Action, Underlying, Strike, Right, Expiry,
Lots, Entry, LTP, IV, Delta, Gamma, Theta, Vega, ×) + position total; EST. MARGIN REQUIRED + HEDGE BENEFIT; RESET, PLACE;
P&L payoff (range ±5 / 10 / 15 %): at expiry + today lines, max loss / profit, breakeven; scenario table at 11 spot levels
(Underlying, Payoff · expiry, P&L · today, Delta, Gamma, Theta, Vega).

## Data source per element (existing unless marked NEW)

| element | source |
|---|---|
| candles, EMA 20, RVOL, levels, markers, signal, LAST | GET /api/desk/live-chart/{sym} (15m with the Kite login, else daily; Kite close until EOD) |
| futures OI line, OI Δ per bar, build-up windows | GET /api/fno/{sym}/futures/oi-buildup: intraday `bars` (contract A); daily: NEW `daily_bars` (BE-1) |
| PCR, max pain, walls, ATM IV, expected move, chain rows, Greeks, lot size | GET /api/fno/{sym}/chain?expiry= (EOD bhavcopy, model Greeks) |
| expiry list | GET /api/fno/{sym}/expiries |
| Consolidated ladder / chain OI / PCR / max pain / walls | NEW GET /api/fno/{sym}/chain/consolidated (BE-2) |
| IV percentile | GET /api/fno/{sym}/iv-history (null + reason until 252 recorded sessions) |
| option LTP in the session | GET /api/live/fno-quotes (else the chain close, labelled) |
| recommended strategies | POST /api/desk/strategy/plan {underlying, direction} (existing engine; candidates ranked) |
| payoff, today curve, Greeks per leg / position | POST /api/desk/strategy/payoff (+ NEW pre_expiry.scenarios Greeks, BE-3) |
| margin + hedge benefit | POST /api/fno/margin (Zerodha calculator through the platform Kite session; 503 → "needs the Kite login") |
| place | POST /api/desk/paper-trades: options / futures (+ cash) → kind "strategy" (≤ 4 legs, defined risk, no short future, no short cash); cash only → the share trade |
| events | GET /api/desk/chart-events/{sym} |

## NEW backend contracts

BE-1 `GET /api/fno/{symbol}/futures/oi-buildup?...&daily=N` (0 = off, default 0, max 250): every contract slot and
`consolidated` gain `daily_bars: [[day, close, volume, oi, oi_change, expiry]]` for the last N sessions from the NSE F&O
bhavcopy, oldest first. Slot per day: current = nearest unexpired expiry that day, next = 2nd, far = 3rd (continuous;
`expiry` names the contract so a roll is visible). oi_change = that contract's OI − its own OI the previous session (null
when it had no row). Consolidated: close = the current slot's, volume and OI summed over the expiries listed that day,
oi_change vs the previous session's sum. Any mode (intraday or end_of_day).

BE-2 `GET /api/fno/{symbol}/chain/consolidated?around=N`: `{symbol, as_of, expiries[], spot, strikes:[{strike,
call:{oi, change_in_oi, volume}|null, put:{...}|null}], summary:{atm_strike, pcr, max_pain, put_wall, call_wall,
total_call_oi, total_put_oi, total_call_oi_change, total_put_oi_change}, basis: "summed over the listed expiries",
read_only: true}`. No prices or Greeks (expiries differ). 404 when the symbol has no options.

BE-3 `POST /api/desk/strategy/payoff`: when the request has `pre_expiry` and `scenarios`, `pre_expiry.scenarios =
[{name, underlying_price, gross, net, greeks:{delta,gamma,theta,vega,rho}|null}]`, priced with the same model and
assumptions as the pre-expiry curve at that underlying price; null with the reason in `unavailable` when a leg cannot be
priced. Nothing else in the answer changes.

## Strategy Lab removed (owner, 29 Oct "completely")

Trade Desk sections become AI Scanner · Chart Analysis · Paper Trading · Watchlists. Every Strategy Lab URL
(`view=lab`, `sub=build|backtest`, `/pro-trader`, `/strategy-builder`, the retired `prog / replay / shadow`, old
`view=new`, `lab=strategies`, `view=strategy`) opens Chart Analysis › Live chart, keeping `sym` and `tp`. Every button that
opened the lab (Open in Strategy Lab, Build a strategy, Open the full Strategy Builder, New trade, an idea's strategy)
opens the chart with its symbol and plan. Its screens (Build a trade wizard, Backtest & validation, "From an idea" Strategy
Builder) and their specs are deleted; components the chart still uses stay. Backend routes stay (paper trades, payoff,
plan, ideas, the strategy store are still called).

## Test cases

### Backend (pytest, fakes)
| id | case | expected |
|---|---|---|
| D1 | daily=60: per-slot continuous series, expiry per bar, roll day keeps the new contract's own OI change | values, expiry |
| D2 | consolidated daily: sums over that day's listed expiries; a missing day is absent, never filled | sums |
| D3 | daily=0 → no daily_bars; daily>250 → 422 | shape |
| K1 | consolidated chain sums OI/Δ/volume per strike over 3 expiries; pcr/max pain/walls over the sums | numbers |
| K2 | a strike listed in one expiry only still sums what exists; no options → 404 | values / 404 |
| G1 | payoff with pre_expiry + scenarios → per-scenario greeks equal the curve model at that price | equal |
| G2 | an unpriceable leg → scenario greeks null, reason listed; expiry payoff unchanged | null |

### Staging (real data, read only)
| id | case | expected |
|---|---|---|
| S1 | TVSMOTOR oi-buildup daily=60: current-slot OI on the latest day = the bhavcopy near-month OI | equal |
| S2 | TVSMOTOR chain/consolidated: one strike's OI = sum of the 3 expiries' chain OI at that strike | equal |
| S3 | payoff of a TVSMOTOR bull call spread with 11 scenarios: scenario greeks at spot = pre_expiry.greeks | equal |
| S4 | deployed: Chart Analysis renders TVSMOTOR with real chain numbers (PCR = chain route's) | screenshot + values |

### UI (Playwright, mocked API — MOCK, not real data)
| id | case | expected |
|---|---|---|
| U1 | header, stats row values come from the mocked routes (PCR, max pain, ATM IV, expected move, IV pctile "not recorded") | text |
| U2 | toggles hide/show walls, max pain, build-up, pattern, confirmation, RVOL, events | element counts |
| U3 | ladder: modes OI / OI Δ / VOLUME change bar widths; click selects the strike (summary + chain row) | attrs |
| U4 | expiry pills switch the chain expiry and the futures slot; Consolidated shows summed OI, B/S disabled with why | requests, text |
| U5 | chain OI / GREEKS toggle; B adds a buy leg, same B again removes it, S switches side | basket legs |
| U6 | presets fill the basket with real strikes around ATM; ADD TO BASKET from a reco card | legs |
| U7 | strategy panel: legs table, payoff chart, scenario table from the mocked payoff answer; range buttons re-request | values |
| U8 | margin: mocked Zerodha answer → required + hedge benefit; 503 → "needs today's Kite login" | text |
| U9 | place: options basket posts kind "strategy" with the legs; cash only posts the share trade; route refusal shown | request body |
| U10 | drag STOP / TGT lines changes the levels; chart click sets the entry | values |
| U11 | 390 px: no sideways page scroll; chain and strategy tables scroll inside their boxes | layout |
| U12 | Strategy Lab gone: nav has 4 Trade Desk sections; every old lab URL lands on the chart with sym/tp | URL, text |
| U13 | non-F&O stock: chart + cash basket only; F&O parts say the stock is not in F&O | text |
