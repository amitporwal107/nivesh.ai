# Market Recovery — Market Desk view (recovery-radar-v1)

Owner ask, 3 Nov 2026: build the pasted "Market Recovery Stock Selection Engine" proposal as a page. Decisions (AskUserQuestion,
3 Nov): a new view under **03 Market Desk** named **Market Recovery**; per-stock plan words are the standard **Entry zone ·
Stop loss · Target 1 · Target 2** (an explicit exception to the 3 Nov wording rule, this page only).

URL: `/v5/app/trader/desk?tab=market&view=recovery`. Flag: `market_recovery` (allow-list, owner by default), like `scan_builder`.

The proposal's three stages map to the page's four parts:

| Part | Proposal | Question it answers |
|---|---|---|
| 1. Recovery check | §1 Market regime | Is the broad market actually recovering? |
| 2. Sector leaders | §2 Smart-money sectors | Which 3–5 sectors lead? |
| 3. Recovery candidates | §3–§7 Score, setups, acceleration, plan | Which Nifty 500 stocks, inside those sectors, recover best? |
| 4. Excluded | §8 False signals | Which high scorers were left out, and why? |

Everything is computed on request by the main backend from data it already reads (no new table, no job):

* daily bars: `services/scan_builder/data.py` panel — NSE end-of-day bars, split/bonus adjusted (`nidp.prices_eod_adjusted`),
  shared file cache, all symbols since 2024-04-01. The scan uses the **last end-of-day session** only (no intraday candle: a
  half-day candle would distort daily volume and averages). The page says "as of the close of <date>".
* Nifty 500 members and their NSE industry: DaaS `/v1/indices/Nifty 500/constituents`. Cap groups: Nifty 100 / Midcap 150 /
  Smallcap 250 members (scan-builder reference).
* index levels: DaaS `/v1/indices/{Nifty 50|Nifty 500|India VIX}/eod` (`nidp.index_eod`).
* features (delivery averages, fundamentals, FII change, accumulation score, market cap): DaaS `POST /v1/features/bulk`
  (`nidp.stock_features_daily`), last ~12 sessions.
* daily delivery %: DaaS `/v1/prices/eod?on=` (`nidp.prices_eod.deliv_pct`, one session behind prices).
* futures price/OI change: scan-builder `fno_fields()` (NSE F&O bhavcopy via DaaS `/v1/desk/fno-buildup`).

Stale-data rule (owner, 28 Oct): if the newest end-of-day session is more than 4 calendar days old the API answers
503 `stale_data` rather than scoring old prices.

## API

`GET /api/market-recovery` — signed-in, flag `market_recovery` (403 when off). One computation per end-of-day date per worker,
reused for 15 minutes. Errors: `{"detail": {"code", "message"}}` + top-level `status/error/code/message` (scan-builder style):
`data_unavailable` (503), `stale_data` (503).

```jsonc
{
  "method": "recovery-radar-v1",
  "as_of": "2026-11-03",                 // the end-of-day session scored
  "computed_at": "2026-11-03T16:40:02Z",
  "universe": {"name": "Nifty 500", "members": 501, "members_as_of": "2026-11-01", "scored": 470,
               "left_out": {"no_bar": 8, "liquidity": 12, "market_cap": 3, "history": 2}},
  "regime": {
    "status": "confirmed",               // confirmed | underway | early | fragile | none
    "label": "Recovery confirmed",
    "line": "Nifty 50 is above a rising 20-day average and 64% of Nifty 500 stocks are above theirs, up from 48% a week ago.",
    "passed": 4, "total": 5,
    "checks": [ {"id": "nifty_above_20dma", "label": "Nifty 50 above its 20-day average", "importance": "high",
                 "pass": true, "value": "25,812 vs 25,410 (+1.6%)"} ],   // 5 checks, below
    "nifty": {"index": "Nifty 50", "close": 25812.4, "sma20": 25410.2, "sma20_5ago": 25301.0, "pct_vs_sma20": 1.58},
    "breadth": {"counted": 493, "advancers_pct": 63.1, "advancers_pct_5d_avg": 56.0, "above20_pct": 64.2,
                "above20_pct_5ago": 48.3, "above50_pct": 51.0, "above50_pct_5ago": 44.9},
    "vix": {"close": 12.1, "close_5ago": 13.4, "change_pct": -9.7},      // null when unavailable
    "caps": [{"key": "large", "label": "Nifty 100", "members": 100, "above20_pct": 70.0, "above20_pct_5ago": 52.0,
              "above50_pct": 58.0}]                                       // large, mid (Midcap 150), small (Smallcap 250)
  },
  "breadth_series": [{"date": "2026-09-22", "above20_pct": 31.2, "above50_pct": 40.1, "advancers_pct": 44.0,
                      "nifty_close": 24990.1}],                           // 30 sessions, oldest first
  "sectors": [{"sector": "Capital Goods", "members": 34, "ret_5d": 3.1, "ret_10d": 5.0, "ret_20d": 7.9,
               "rs_5d": 1.2, "rs_10d": 2.0, "rs_20d": 3.4, "rs_20d_5ago": 1.1, "rs_change": 2.3,
               "above20_pct": 78.0, "above50_pct": 66.0, "delivery_up_pct": 55.0,
               "state": "leadership", "state_label": "Leadership", "rank": 1, "leader": true}],
  "leaders": ["Capital Goods", "Realty", "Financial Services"],          // the top 5 sectors (rank order)
  "candidates": [Candidate],             // up to 10, from the leader sectors, best score first
  "others": [Candidate],                 // up to 10, best scores outside the leader sectors
  "excluded": [{"symbol": "ABC", "name": "ABC Ltd", "sector": "Realty", "score": 81, "trap": "dead_cat",
                "label": "Dead-cat bounce", "reason": "Up 6.2% in 5 sessions but below a falling 50-day and its 200-day average."}],
  "thresholds": {"priority_score": 75, "min_traded_value_cr": 5, "min_market_cap_cr": 1000},
  "sources": [{"what": "Daily prices", "source": "NSE end-of-day bars (split/bonus adjusted), NIDP warehouse", "as_of": "2026-11-03"}],
  "notes": ["…method notes, incl. 'not back-tested yet'…"],
  "warnings": ["…universe-level data gaps…"]
}
```

Candidate:

```jsonc
{
  "rank": 1, "symbol": "ABB", "name": "ABB India Ltd", "sector": "Capital Goods", "sector_rank": 1,
  "sector_state": "leadership", "close": 5320.5,
  "score": 86.4, "meets_priority": true,
  "components": [                                  // always the 5, in this order
    {"key": "relative_strength", "label": "Relative strength", "points": 21.0, "max": 25, "rescaled": false,
     "parts": [{"label": "vs Nifty 500, 20 sessions", "points": 11.2, "max": 12.5, "value": "+9.0 pp", "ok": true}]}
  ],                                               // keys: relative_strength · technical · volume_delivery · fundamental · smart_money
  "acceleration": {"score": 78, "improving": 5, "of": 6,
    "rows": [{"key": "rs", "label": "Relative strength vs Nifty 500 (20D)", "unit": "pp", "then": -3.0, "now": 2.0, "improving": true}]},
  "setup": {"key": "breakout", "label": "Early breakout", "why": "Closed above its 20-session high on 1.8× its usual volume."},
  "plan": {"entry_low": 5260.0, "entry_high": 5320.5, "stop_loss": 5080.0, "target_1": 5620.0, "target_2": 5800.0,
           "rr_1": 1.2, "rr_2": 2.0, "risk_pct": 4.5, "basis": "recovery-plan-v1: …"},          // null when no ATR
  "metrics": {"rs_vs_index_20d": 9.0, "rs_vs_sector_20d": 2.1, "rsi14": 61.2, "volume_ratio": 1.8, "pct_vs_ema20": 3.1,
              "deliv_5d": 52.0, "deliv_20d": 47.0, "atr14": 120.4, "traded_value_cr_20d": 210.0, "market_cap_cr": 112000,
              "roce": 28.0, "roe": 21.0, "de": 0.0, "pat_growth": 18.0, "cfo_pat": 1.1, "fii_change_qoq": 0.4},
  "reasons": ["Outperformed Nifty 500 by 9.0 pp over 20 sessions"],
  "cautions": ["Results due in 6 days"],
  "gaps": ["Cash flow (CFO/PAT) not available"]
}
```

## Rules (recovery-radar-v1; weights are the proposal's, thresholds untuned — NOT back-tested)

Notation: all per-stock series are the adjusted daily bars; "5 sessions ago" = the value on the 6th-last session.
`ramp(x, lo, hi)` = 0 at or below lo, 1 at or above hi, linear between. EMA = scan-builder `ema` (SMA-seeded).

### Universe and gates
Nifty 500 members (latest constituent list) with a bar on the scored session and ≥ 60 sessions of history. Left out (counted
in `universe.left_out`): no bar that day; 20-session average traded value (close × volume) < ₹5 cr; market cap < ₹1,000 cr
(when known). Financials = NSE industry "Financial Services".

### 1. Recovery check (recovery-check-v1)
Five checks, the proposal's §1 table:

| id | Check | Importance |
|---|---|---|
| `nifty_above_20dma` | Nifty 50 close > its 20-session SMA | high |
| `nifty_20dma_rising` | Nifty 50 SMA20 today > SMA20 5 sessions ago | high |
| `advancers_60` | ≥ 60% of counted Nifty 500 stocks closed up on the session | high |
| `breadth_expanding` | % of Nifty 500 above their SMA20 is ≥ 5 pp higher than 5 sessions ago | very high |
| `vix_falling` | India VIX close < its close 5 sessions ago | medium (null when VIX missing) |

Status, first match: **confirmed** = nifty_above_20dma ∧ nifty_20dma_rising ∧ above20 ≥ 60% ∧ above50 ≥ 50%;
**underway** = nifty_above_20dma ∧ breadth_expanding; **early** = ¬nifty_above_20dma ∧ breadth_expanding;
**fragile** ("Narrow rally") = nifty_above_20dma ∧ above20 < 50%; otherwise **none** ("No recovery yet").
Breadth series: the same % above SMA20 / SMA50 and % advancers for the last 30 sessions (today's members — survivorship noted).

### 2. Sectors (NSE industry of the Nifty 500 members; ≥ 5 counted members)
`ret_n` = median member n-session return; `rs_n` = `ret_n` − Nifty 500 index n-session return (n = 5, 10, 20);
`rs_change` = rs_20d − rs_20d 5 sessions ago; `above20/50_pct`; `delivery_up_pct` = % of members whose 5-session delivery
average > their 20-session delivery average.
State: **leadership** = rs_20d > 0 ∧ above50 ≥ 60; **recovery** = rs_change > 0 ∧ above20 ≥ 60; **emerging** = rs_change > 0 ∧
above20 ≥ 40; **weak** ("Weak — avoid for now") = rs_20d < 0 ∧ above20 < 40; else **neutral**.
Rank by 0.4·pct-rank(rs_20d) + 0.3·pct-rank(rs_change) + 0.3·pct-rank(above20); leaders = top 5.

### 3. Stock score (100)
* **Relative strength 25**: vs Nifty 500 (20 sessions) 12.5·ramp(rs, 0, 10 pp); vs own sector median (20 sessions)
  12.5·ramp(rs, 0, 7.5 pp).
* **Technical recovery 25** (5 each): close > EMA20; close > EMA50; (EMA20−EMA50)/EMA50 higher than 5 sessions ago;
  RSI14 in 50–70 (2.5 if 45–50 or 70–75); higher lows = lowest low of the last 10 sessions > lowest low of the 10 before.
* **Volume & delivery 20**: volume ratio (5-session avg ÷ the 50 sessions before) 7·ramp(vr, 1.0, 1.5); up-day / down-day
  volume over 10 sessions 6·ramp(ud, 1.0, 1.5); delivery (5-session avg ÷ 20-session avg) 7·ramp(dr, 1.0, 1.2).
  **Low-base volume** (proposal §8.3): when the 50-session average volume is < 50% of the 250-session average, the volume-ratio
  part scores 0 and a caution says why.
* **Fundamental quality 20**, non-financials (5 each): ROCE ramp(10, 20)%; D/E 1 at ≤ 0.5 falling to 0 at 1.5; PAT growth
  YoY ramp(0, 15)%; CFO/PAT ramp(0.5, 1.0). Financials: ROE ramp(8, 16)% ×10, PAT growth ramp(0, 15)% ×10.
* **Smart money 10**: FII stake change QoQ 4·ramp(0, 1 pp); accumulation score (TI engine, 0–100) 3·(score/100);
  price-volume confirmation = up sessions on above-20-session-average volume in the last 5: 3·ramp(count, 0, 3).
* A part with no data is a **gap**: the component is rescaled over the parts that have data (`rescaled: true`) when at least
  half its max is measurable; otherwise it scores 0. Each gap is listed in `gaps`.
* `meets_priority` = score ≥ 75 (proposal §3).

### 4. Recovery acceleration (0–100)
Six 5-session changes: RS vs Nifty 500 (20D), RSI14, % distance from EMA20, volume ratio, delivery trend (TI engine
`deliv_trend10`, a 10-session slope), and the stock's sector rs_20d. Score = mean percentile rank of the available changes
across the scored universe × 100; `improving` = number of positive changes.

### 5. Setup (first match)
1. **breakout** "Early breakout": close > highest high of the previous 20 sessions ∧ session volume ≥ 1.5× its 20-session
   average ∧ RSI ≥ 50.
2. **ema_reclaim** "20-day average reclaim": close > EMA20 now ∧ close < EMA20 on one of the previous 5 sessions ∧ RSI ≥ 50.
3. **pullback** "Pullback in an uptrend": close > SMA50 ∧ higher lows ∧ rs_change(stock) > 0 ∧ down-day volume < up-day
   volume (10 sessions) ∧ close within 5% of EMA20.
4. **accumulation** "Accumulation": 20-session high/low range ≤ 12% ∧ delivery ratio > 1 ∧ up/down volume > 1.
5. else **relative_strength** "Relative strength".

### 6. Traps (proposal §8) — excluded from candidates, listed in `excluded`
* **dead_cat** "Dead-cat bounce": close < SMA50 ∧ close < SMA200 ∧ SMA50 lower than 10 sessions ago.
* **short_covering** "Short covering": F&O stock whose latest futures session shows price up > 1% with OI down > 3%, or price
  up with OI down by at least 1% on both of the last two sessions (a smaller OI change is noise: the first staging run
  flagged LT on −0.1%).
* **extended** "Extended": close > 10% above EMA20 (proposal "price-location check").

### 7. Plan (recovery-plan-v1; 5–20 session horizon; shown with the owner's standard words)
ATR = ATR14. **Entry zone** = max(EMA20, close − 0.5·ATR) … close. **Stop loss** = lowest low of the last 10 sessions − 0.25·ATR,
kept between 1·ATR and 3·ATR below the close (R = close − stop). **Target 1** = the highest high of the last 60 sessions when it
lies between close + 1R and close + 3R, else close + 2R. **Target 2** = max(close + 3R, Target 1 + 1R). rr_n = (Target n − close)
/ R; risk_pct = R / close.

## Test cases (authored before implementation)

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| TC-U1 | regime | crafted index + breadth hit each status path | unit | confirmed / underway / early / fragile / none |
| TC-U2 | breadth | % above SMA20/50 and % advancers on a small panel | unit | equals a hand count |
| TC-U3 | sectors | median-return RS, rs_change, state thresholds, rank, top-5 leaders | unit | as §2 |
| TC-U4 | score | crafted stock hits each part; total = sum ≤ 100; rescale on gaps; financials profile | unit | as §3 |
| TC-U5 | traps | dead-cat, short covering, extended excluded with reason; low-base zeroes the volume-ratio part | unit | as §6, §3 |
| TC-U6 | setups | breakout / ema_reclaim / pullback / accumulation / relative_strength series | unit | first match per §5 |
| TC-U7 | plan | 1 ≤ R/ATR ≤ 3; T1 rule both branches; T2 ≥ T1 + 1R; entry_low ≤ entry_high | unit | as §7 |
| TC-U8 | acceleration | deltas, improving count, score in 0–100 | unit | as §4 |
| TC-U9 | gates | ATV < ₹5 cr and mcap < ₹1,000 cr left out and counted | unit | as gates |
| TC-U10 | stale | panel 5+ days old → stale_data | unit | 503 stale_data |
| TC-R1 | route | flag off → 403; data unavailable → 503 typed body; ok → 200 | unit (TestClient) | as API |
| TC-A1 | real data | engine on staging DaaS (overlay in the backend container) | api | as_of = latest session, ≥ 400 scored, regime 5 checks, ≤ 10 candidates each with 5 components + plan |
| TC-A2 | data check | engine vs SQL on `nidp` | data | Nifty 50 close = index_eod; % above SMA20 within 2 pp of stock_features_daily; 3 candidates' RSI within 1.5 and 20D return within 0.5 pp of the feature store |
| TC-A3 | deployed | GET /api/market-recovery on staging | api | 200 with owner session; 401 without |
| TC-E1 | UI | view in Market Desk switcher (flag on); renders check, breadth chart, sectors, candidates | e2e | visible, data from mock |
| TC-E2 | UI | expand a candidate: components, acceleration table, plan (Entry zone · Stop loss · Target 1 · Target 2), reasons | e2e | visible |
| TC-E3 | UI | flag off → not in switcher; URL shows "not enabled" | e2e | as stated |
| TC-E4 | UI | 503 → error message; no candidates → empty state | e2e | as stated |
| TC-E5 | wording | lint the page; only the five plan labels are allowed | e2e | no other banned word |
| TC-E6 | UI | 390 px wide: no horizontal page overflow | e2e | scrollWidth ≤ width |

## 8. Strategies with downside protection (owner, 4 Nov ~01:30 IST)

Owner ask: "For each of the scored stocks please provide trading strategies, we need to hedge the risk as well", with five
strategies pasted: Protective Put, Bull Call Spread, Collar, Bull Put Credit Spread, Put Ratio Backspread. Decisions
(AskUserQuestion, 4 Nov): leg words **Buy / Sell** (a second exception on this page); **all five** shown, the ones failing a
check greyed with the reason; stocks **without stock options** get a **Nifty put hedge** sized by beta (Quick Hedge sizing);
premiums **end of day** (NSE F&O bhavcopy close, else settlement price), dated.

`GET /api/market-recovery/strategies/{symbol}` — same flag; any stock scored on the page (404 `not_scored` otherwise). Built on
request from the signed-in user's request through `routes/fno.py` (expiries + chain: current session only, unexpired series),
cached per symbol and chain date for 15 minutes. Errors: `not_scored` (404), `chain_unavailable` (503, the stock has options
but no current chain), `data_unavailable` (503).

Expiry: the nearest listed expiry with ≥ 14 calendar days left (the middle of the 5–20 session horizon) and ≤ 60; else the
nearest with ≥ 5 days (the builder's options minimum). One lot. Strikes come from the page's own plan for the stock:

| key | Strategy | Legs (1 lot) |
|---|---|---|
| `protective_put` | Protective Put | Buy shares (1 lot); Buy put at the highest strike ≤ the close (ATM / slightly OTM) |
| `bull_call_spread` | Bull Call Spread | Buy call at the ATM strike; Sell call at the strike nearest Target 1 (above the bought one) |
| `collar` | Collar | Hold shares (1 lot); Buy put at the strike nearest the Stop loss (below the close); Sell call at the strike nearest Target 1 (above the close) |
| `bull_put_spread` | Bull Put Credit Spread | Sell put at the highest strike ≤ the entry-zone low; Buy put at the strike nearest the Stop loss (below the sold one) |
| `put_ratio_backspread` | Put Ratio Backspread | Sell 1 put at the ATM strike; Buy 2 puts at the strike nearest the Stop loss (below) |

Figures at expiry, whole position, from `services/strategy_plan/payoff.py` (exact max profit / loss over all prices, breakevens,
the desk cost card desk-cost-v2 for costs): net premium (debit < 0, credit > 0), max profit (null + `profit_unbounded`), max
loss, max loss incl. costs (capital at risk), breakevens, reward : risk (max profit ÷ max loss; when profit is unbounded, the
P&L at Target 1 ÷ max loss; null for the put ratio backspread, whose "max profit" needs the stock to collapse), scenarios at the Stop loss, the close, Target 1 and Target 2 (and, for share strategies, the
same shares without the hedge), and 41 payoff points from 0.7× to 1.3× the close.

Checks (the Strategy Builder's own rules): `liquid` — every option leg has a premium, open interest and trades that day
(`candidates.leg_view` blockers; low OI / volume are flagged, not blocking); `reward_risk` — ≥ 1.5 (`rules.min_reward_risk`;
not applied to the put ratio backspread, a volatility hedge judged by its loss zone); `credit` — a credit spread takes in at
least a third of its strike width (the risk service's rule); `strikes` — the strikes the rule needs exist. A strategy passes
when every applicable check passes; otherwise it is shown greyed with the failing reasons. Not estimated: exchange margin
for sold options (credit spreads, collar call, backspread) — the page says so.

Stocks without stock options (`kind: "index_hedge"`): one Nifty put lot at the nearest Nifty expiry by the same rule; strike =
Quick Hedge `pick_put_strike` with fall = the stock's stop distance ÷ its beta (capped at 5%: on 3 Nov
real data a 10% cap picked a ~8% OTM put for SYNGENE that paid nothing at −5% and ~15% of the loss at −10%); hedged stock value = Nifty
close × lot ÷ beta (`beta_1y`, feature store); cost per lot and as % of that value; scenarios for a 5%, 10% and 15% Nifty fall (put
payoff vs the beta-implied stock loss). Caveat on screen: it covers a market-wide fall only, not a fall in the stock alone.

Response:
```jsonc
{"symbol": "LAURUSLABS", "kind": "options",            // or "index_hedge"
 "as_of": "2026-11-03", "expiry": "2026-11-23", "days_to_expiry": 20, "lot_size": 425, "spot": 2323.0,
 "plan": {"entry_low": 2285.27, "close": 2323.0, "stop_loss": 2096.64, "target_1": 2775.72, "target_2": 3002.08},
 "strategies": [{
   "key": "protective_put", "label": "Protective Put", "best_when": "…", "status": "passes",   // passes | fails | unavailable
   "why": null,                                          // text when fails / unavailable
   "legs": [{"action": "Buy", "instrument": "Shares", "strike": null, "lots": 1, "units": 425, "price": 2323.0,
             "price_basis": "close", "oi": null, "volume": null, "flags": []},
            {"action": "Buy", "instrument": "Put", "strike": 2300.0, "lots": 1, "units": 425, "price": 61.5,
             "price_basis": "close", "oi": 120000, "volume": 300, "flags": []}],
   "net_premium": -26137.5, "net_premium_per_share": -61.5, "outlay": -1013412.5,
   "max_profit": null, "profit_unbounded": true, "max_loss": -36912.5, "max_loss_with_costs": -38100.0,
   "breakevens": [2384.5], "reward_risk": 4.1, "costs_round_trip": 1180.0,
   "scenarios": [{"label": "At the Stop loss", "price": 2096.64, "pnl": -36912.5, "pnl_unhedged": -96203.0}],
   "checks": [{"id": "liquid", "label": "Every leg traded on 3 Nov", "pass": true, "detail": "…"}],
   "payoff": [[1626.1, -36912.5]]}],
 "index_hedge": null,                                    // {…} when kind = index_hedge
 "notes": ["…"], "sources": [{"what": "…", "source": "…", "as_of": "…"}], "warnings": []}
```
index_hedge: `{"index": "NIFTY", "expiry", "days_to_expiry", "lot_size", "spot", "beta", "put_strike", "premium", "price_basis",
"oi", "volume", "cost_per_lot", "hedged_value", "cost_pct", "fall_used_pct", "scenarios": [{"label": "Nifty −5%", "nifty_move_pct": -5,
"put_pnl", "stock_loss"}], "checks": [...], "caveat": "…"}`.

Test cases (§8): TC-S1 strikes per strategy from the plan (ATM, nearest-to-level, "above/below" fallbacks); TC-S2 payoff
figures for each structure equal hand-computed values (max loss, max profit or unbounded, breakevens); TC-S3 checks:
illiquid leg, R:R < 1.5, credit < ⅓ width, missing strike → fails/unavailable with reasons; TC-S4 expiry choice (≥ 14, else ≥ 5);
TC-S5 Nifty hedge sizing (hedged value, strike via pick_put_strike, scenarios); TC-S6 route: not scored → 404, chain down → 503;
TC-S7 real staging run for a stock with options and one without; TC-S8 UI: a candidate's detail loads the five strategies
(legs with Buy / Sell, figures, failing ones greyed) and the Nifty hedge for a stock without options; wording lint allows
only the plan labels and Buy / Sell in legs.

## 9. Nifty and Bank Nifty by expiry (owner, 4 Nov ~09:00 IST)

Owner: "Please also put this nifty analysis here in the dashboard", after the per-expiry Nifty / Bank Nifty analysis in chat
(and "We have nifty weekly and monthly expiry so nifty analysis should be done on each of the expiry dates"). A new part of
this page, after the Recovery check: **2 · Nifty and Bank Nifty** (the later parts renumber). Computed from our data every
day (never a pasted snapshot), end of day like the rest of the page.

`GET /api/market-recovery/indices` — same flag; one computation per end-of-day date per worker, reused 15 minutes. Reads:
index closes (DaaS /indices/{Nifty 50 | Nifty Bank | India VIX}/eod), option chains per live expiry and futures via
routes/fno (current session, unexpired series only), NSE FII/DII daily cash (DaaS market pulse). Errors: data_unavailable (503).

```jsonc
{"as_of": "2026-11-03",
 "indices": [{
   "symbol": "NIFTY", "name": "Nifty 50", "close": 23810.85, "change": 370.05, "change_pct": 1.58,
   "open": 23582.25, "high": 23810.85, "low": 23482.8, "up_streak": 4, "ret_5d": 4.66, "ret_20d": 5.56,
   "technicals": {"ema20", "ema50", "ema200", "vs_ema20_pct", "vs_ema50_pct", "vs_ema200_pct", "rsi14", "rsi14_5ago",
                  "macd", "macd_signal", "macd_hist", "macd_hist_prev", "atr14", "atr_pct", "high20", "low20",
                  "high52", "low52", "from_high52_pct", "from_low52_pct", "sessions"},
   "pivots": {"p", "r1", "r2", "r3", "s1", "s2", "s3"},              // classic floor pivots from the last H / L / C
   "futures": [{"expiry", "close", "change_pct", "oi", "oi_change", "oi_change_pct", "basis", "buildup"}],
              // buildup: long_buildup | short_covering | short_buildup | long_unwinding (price change × OI change)
   "levels": {"above": [{"level": 23907.99, "label": "200-day average (EMA)"}], "below": [{"level", "label"}]},  // ≤ 5 each, nearest first
   "expiries": [{
     "expiry": "2026-11-09", "days": 6, "kind": "weekly",              // weekly | monthly (monthly = the last listed expiry of its month)
     "liquidity": "active",                                            // active | thin | too_thin (volume vs the busiest expiry: ≥ 20% / ≥ 3%)
     "volume": 12700000, "pcr": 1.14, "call_oi": 87390000, "put_oi": 99220000, "max_pain": 23600,
     "atm": 23800, "atm_call": 149.9, "atm_put": 224.75, "straddle": 374.65, "move_pct": 1.57, "range_lo": 23436, "range_hi": 24186,
     "call_wall": 24000, "put_wall": 23700,                            // heaviest OI at/above and at/below the close (chain summary)
     "call_oi_top": [{"strike": 24000, "oi": 5820000}], "put_oi_top": [...],        // top 3 by OI
     "call_adds": [{"strike": 25000, "change": 2990000}], "put_adds": [...],        // top 3 OI additions
     "call_cuts": [{"strike": 23300, "change": -550000}], "put_cuts": [...],        // top 2 OI reductions
     "read": "…one sentence…"}],
   "setups": [{
     "expiry": "2026-11-09", "kind": "weekly", "key": "bull_call_spread",   // bull_call_spread | bear_put_spread | iron_condor | hedge_put_spread
     "label": "Bull Call Spread", "when": "If it rises toward 24,000", "lot_size": 65,
     "legs": [{"action": "Buy", "instrument": "Call", "strike": 23800, "lots": 1, "price": 149.9, "price_basis": "close",
               "oi": 0, "volume": 0, "flags": []}],
     "net_premium": -4494.75, "max_gain": 8505.25, "max_loss": -4494.75, "reward_risk": 1.89, "breakevens": [23869.15],
     "status": "passes", "why": null, "checks": [{"id", "label", "pass", "detail"}]}],
   "read": ["…rule-based bullets…"]}],
 "vix": {"close": 15.72, "change_pct": 1.42, "close_5ago": 16.4, "change_5d_pct": -4.15, "up_streak": 3},
 "relative": {"bank_minus_nifty_1d": -0.6, "bank_minus_nifty_5d": -1.76, "bank_minus_nifty_20d": -4.05},
 "flows": {"as_of": "2026-11-03", "days": [{"date", "fii", "dii"}], "fii_5d": 13478.0, "fii_buy_days_5": 4},
 "together": ["…Nifty across expiries…"],
 "notes": ["…"], "sources": [{"what", "source", "as_of"}], "warnings": []}
```

Rules: expiries = every live option expiry within 70 days (Nifty weeklies + monthlies; Bank Nifty monthlies), from the chain
route; a series expiring on the data day is never used. Technicals use the scan builder's conventions (SMA-seeded EMA, Wilder
RSI / ATR) on index closes. Setups per expiry (skipped for too_thin; 1 lot; legs Buy / Sell; figures at expiry via
strategy_plan.payoff; leg liquidity via candidates.leg_view):
* **bull_call_spread** — Buy the ATM call; Sell the call at the heaviest-OI strike above the ATM up to the straddle's upper bound
  (else the strike nearest that bound). "If it rises toward {short}". Check: reward : risk ≥ 1.5.
* **bear_put_spread** — Buy the ATM put; Sell the put at the heaviest-OI strike below the ATM down to the lower bound (else the
  strike nearest it). "If it breaks below {put_wall}". Check: reward : risk ≥ 1.5.
* **iron_condor** — Sell the call at the call wall and the put at the put wall; Buy wings ~1% of the close further out (nearest
  listed strikes). "If it stays {put_wall}–{call_wall}". Check: credit ≥ ⅓ of the wider wing. Skipped when a wall is the ATM.
* **hedge_put_spread** — Buy the put nearest 1% below the close; Sell the put nearest the straddle's lower bound. "To protect
  long stocks". No reward : risk check (a hedge).
Every setup also checks that each leg traded that day; a thin expiry adds a "use limit orders" note.
`together` (Nifty): the strike with the most put additions summed over the active / thin expiries ("common floor"), the
nearest active expiry's call wall ("near ceiling"), and the longest active monthly's max pain vs the close.

Test cases (§9): TC-I1 technicals and pivots on a hand-made series (EMA / RSI / ATR match the scan builder functions; pivots
by formula); TC-I2 futures build-up labels (4 quadrants); TC-I3 expiry kind (monthly = last of month), liquidity classes,
the expired-today series dropped; TC-I4 per-expiry figures from a hand-made chain (walls, adds / cuts, straddle range, read);
TC-I5 setups: strikes by rule, figures vs hand-worked values, checks (R:R, credit, illiquid leg), too_thin skipped; TC-I6
levels above / below sorted and capped; together lines; TC-I7 route 200 / 503 / flag; wording lint (Buy / Sell legs only);
TC-I8 real staging run vs nidp SQL (closes, PCR, max pain, walls for 9 Nov / 23 Nov equal the 4 Nov chat analysis);
TC-I9 UI: the section renders both indices, per-expiry table, setups with Buy / Sell legs, levels, futures, flows; 390 px.

## 10. Paper trading the recovery candidates, live (owner, 4 Nov ~08:55 IST)

Owner: "let's do a paper trading for the stocks … assume you have sufficient margin … keep track of the real time quotes and
create a real time p&l for each valid trade setup and the risk configuration already done we need to pick the best paper trade
strategy for each of the trade". Decisions (AskUserQuestion): paper capital raised to Rs 1 crore, % limits unchanged (done 4 Nov
08:58 IST: audited `paper_account.adjust`, key owner-capital-topup-20261104); the TOP 10 leading-sector candidates; best =
highest reward : risk after costs among the shares plan and the passing option strategies the risk gate approves (ties: lower
max loss); LIVE entry at Kite prices AND live exits (auto-close intraday on live stop / target touches) for these trades.
Reuses the desk's paper engine: POST /api/desk/paper-trades (risk gate, idempotency, duplicates, funds), its close functions,
the journal; Mongo `desk_paper_trades`.

**A. `GET /api/market-recovery/paper-plan`** (flag market_recovery; signed-in user; reads only):
```jsonc
{"as_of": "2026-11-03", "list_date": "2026-11-04",
 "market": {"live": true, "source": "kite_live", "why": null},       // live = Kite live quotes available now
 "capital": {"starting_capital_rs": 10000000, "equity_rs": 9990000, "available_rs": 9876112},
 "rule": "…", "notes": ["…"],
 "items": [{"rank": 1, "symbol": "LAURUSLABS", "name": "…", "sector": "…", "score": 82.8,
   "chosen": Candidate,                       // null when nothing qualifies
   "alternatives": [Candidate],               // the others, ranked, each with why it lost or was refused
   "skipped_reason": null,                    // text when chosen is null
   "open_trade": {"id": "…", "status": "open"} // a market_recovery trade already open for this stock (null otherwise)
 }]}
```
Candidate: `{"key": "shares" | "protective_put" | "bull_call_spread" | "collar" | "bull_put_spread" | "put_ratio_backspread",
"label", "reward_risk_net", "max_gain_rs", "max_loss_rs", "approved": {"outcome": "allow" | "reduce" | "block", "quantity" | "lots",
"reasons": [...]}, "prices": {"source": "kite_live" | "kite_close", "as_of"}, "body": {…exact POST /api/desk/paper-trades body…},
"idempotency_key": "mr-20261104-LAURUSLABS"}`. Shares: entry = live LTP, stop = the plan's Stop loss, target = Target 1 (the
desk stores one target; Target 2 is shown), quantity = the gate's approved quantity. Structures: legs re-priced at live option
quotes; lots = the gate's approved lots (≥ 1). Reward : risk after costs (desk cost card); a structure without live leg quotes
is not eligible ("no live option quote").

**B. Live entry on the desk (fill-model change for tagged trades):** POST /api/desk/paper-trades accepts on a shares body
`"price_source": {"kind": "kite_live", "at": ISO}`: the at-once entry is then checked against TODAY's live day range (the live
quote's low / high, ±0.5%) instead of the last completed session's bars; refused when no live quote of today exists.
Structure legs keep `price_source` per leg ("Kite live HH:MM").

Tags: shares `source: {"kind": "market_recovery", "bucket": <key>, "signal_date": <as_of>}`; structures
`signal: {"rule_version": "recovery-plan-v1", "source_refs": [{"kind": "market_recovery", "ref": "<SYM>:<key>", "as_of"}], …}`.

**C. `GET /api/market-recovery/paper-trades/live`**: the user's market_recovery paper trades (open + closed today), marked at
live Kite prices (shares / underlyings via day_quote.day_quotes; option legs via the live F&O quote reader): per trade id,
symbol, kind, label, legs (entry, live), entry, live price, stop, target, quantity / lots, `pnl_rs`, `pnl_pct` (of capital at
risk), status, exit {reason, price, at}; totals {open_pnl_rs, realised_today_rs, open_count, closed_today_count}; market
{live, source, why, as_of}. Applies the live exits (D) on read.

**D. Live exits** — the same function, also run by an mf_scheduler job (leader-locked) every 60 s, 09:15–15:30 IST Mon–Fri:
shares: live LTP ≤ stop → close at LTP, reason `stop_live`; LTP ≥ target → `target_live`. Structures: the underlying's live
price ≤ stop_underlying → `stop_live`, ≥ target_underlying → `target_live`, every leg closed at its live price (not closed
when a leg has no live quote: flagged). Exit prices recorded with source kite_live. Without live quotes (no Kite login) nothing
is closed live; the desk's end-of-day exits still apply.

**E. UI** — part "5 · Paper trades (live)" of this page: the plan (stock, chosen structure, why, the gate's size, reward : risk,
max loss, alternatives on expand), a button "Open paper trades for the top 10" that POSTs each chosen body to
/api/desk/paper-trades with its Idempotency-Key and shows each result or refusal, and the live table (polled every 30 s in
market hours) with totals; "Kite login needed" when the market is open but quotes are not live.

Test cases (§10): TC-P1 picker ranks by net R:R, ties by max loss, refusals and missing live quotes excluded, shares fallback;
TC-P2 bodies match the desk's schemas (cash and strategy) with tags and idempotency keys; TC-P3 live-entry check (today's range,
refused without a live quote, unchanged without price_source); TC-P4 live marks and P&L for shares and a 2-leg structure;
TC-P5 live exits at stop / target (shares, structure), none without live quotes; TC-P6 scheduler job only in market hours;
TC-P7 routes 200 / flag / errors; TC-P8 real staging: plan for the top 10, open via the desk endpoint with the owner's session,
live P&L read; TC-P9 UI.
