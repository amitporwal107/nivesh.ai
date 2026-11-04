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
