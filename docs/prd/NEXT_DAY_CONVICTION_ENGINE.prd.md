# Next-Day Conviction Engine — PRD

**Status:** DRAFT (owner decisions in §12) · **Author:** Claude for Amit Porwal · **Date:** 7 Nov 2026
**Source:** the owner's pasted proposal "Nivesh Next-Day Conviction Engine" (cash 30 / delivery 20 / price-volume 25 /
F&O 25, top 5 bullish and bearish for the next session), which ends by asking for this PRD.

**Recommendation: BUILD the engine as a research job that runs in SHADOW, and DO NOT BUILD a user-facing "tomorrow's
top 5" list until the pre-registered study in §7.4 passes and compliance signs off.** The evidence we already hold says that
next-session moves are the hardest horizon to predict (§1.2). The trading cost of a one-day hold is 0.20–0.37 % (§1.3). An
edge big enough to clear that cost would be unusually large. The engine is still worth building, because every feature it
computes also feeds the 10–20-session positional scoring, where our data has shown an edge.

---

## 1. Problem

### 1.1 What the owner wants
Each evening, a short list of stocks with a high probability of a directional move in the next trading session. A stock
makes the list only when four independent sources tell the same story: cash-market participation, delivery behaviour,
price-volume trend, and futures-and-options positioning. The engine may return zero names. Bullish and bearish lists are
kept apart. A stock's directional signal is scored separately from the quality of the trade (entry, risk, room to move).

### 1.2 What our own data already says (read this before the design)

| Finding | Source (in the repo unless stated) |
|---|---|
| The desk's v1 score was **anti-predictive** at 5 sessions: rank IC −0.028 (t −2.8) vs 5-session excess return, May–Nov 2026. | `test_reports/autodesk_scoring_v2_20261105.md`; `backend/autodesk/scoring/registry.py` (v1 validation note) |
| In that replay, v1's volume/delivery dimension (IC −0.037 / −0.036) and its short-term relative-strength dimension (−0.029 / −0.035) had a negative sign in both universes (F&O / Nifty Total Market); trend and regime were positive. | 5 Nov 2026 session study, **not committed** |
| **At 5 sessions no daily signal beat the Nifty after costs** (all within ±0.6 %, win rates 40–48 %); edges appear only at 10–20 sessions and only for trend / relative-strength signals. | `docs/signal_intelligence/SIGNAL_TIER_HIERARCHY.md` §10 |
| **Signal-day price-volume strength did not add consistently**: relative volume ≥ 10× +0.46 → −0.33; close in the top 20 % of the range +0.01 → +0.44 (fit → test, 10 sessions). Delivery 50–60 % was slightly positive in both periods. | same, §10 |
| Stocks the positional v2 score rates Strong / Exceptional **lag the next day (about −0.3 %)**: short horizons revert. | same, §13 |
| No intraday entry signal tested (10× opening volume, opening-range breakout, VWAP reclaim) beat the average stock after costs. | same, §13 |
| After a +5 % / 3× volume / close-near-high day, Nifty 500 stocks closed higher the **next day 45.7 %** of the time (all stock-days 48.4 %); moves ≥ 8 % or volume ≥ 6× faded more. 2,099 cases, Apr 2024 – Nov 2026. | 5 Nov 2026 session study, **not committed** to the repo |
| Last-hour futures long build-up (price ≥ +0.3 %, OI ≥ +1.5 %): next day −0.17 % vs the day's median, 45 % beat it. Only 6 sessions, n = 55, too thin to conclude. | 5 Nov 2026 session study, **not committed** |
| Smart-money holdings + deal tilt: **INCONCLUSIVE**; a ≥ +1 pp increment was ruled out at 95 %. | `docs/prd/SMART_MONEY_GATE_DECISION_20261022.md` |

None of this proves that the combination in the proposal fails. The proposal's own premise is that *agreement* between
independent sources is what carries the information, and no study so far has tested that agreement at the next-session
horizon. It does set the prior: **the most likely outcome of the study is FAIL or INCONCLUSIVE at one session.** The
plan in §9 is built so that this outcome is cheap and still useful.

### 1.3 The bar a next-day signal must clear
Round-trip cost on a ₹1 lakh trade, from the repo's own cost card `desk-cost-v2` (`backend/services/desk_cost_card.py`,
computed 7 Nov 2026):

| Segment | Round trip | Main parts |
|---|---|---|
| Equity delivery (overnight hold) | **0.370 %** | STT 0.200 · slippage allowance 0.100 · brokerage ₹40 = 0.040 · stamp 0.015 |
| Stock futures | **0.204 %** | STT 0.050 · slippage allowance 0.100 · brokerage 0.040 · exchange, GST, stamp |
| Equity intraday | not in the card | the card has no intraday segment (gap, §12 Q1) |

The repo's measured paper-trading friction was higher still: 0.628 % (`daas_api/routers/movers.py`, `COST`).

The noise a next-day test faces, measured 7 Nov 2026 on the F&O universe. These figures come from returns only (no
signal), so they reveal nothing that could bias the study:
270 signal sessions (1 Oct 2025 – 5 Nov 2026), on average 209 F&O stocks per day; next-day close-to-close return relative
to the day's universe average has a cross-sectional SD of **1.65 %**; the equal-weight universe moved with a daily SD of
1.05 % and a mean of +0.019 %; 49.1 % of stock-days closed up.

So a 5-name basket has daily noise of about 1.65 / √5 ≈ **0.74 %** (more if the names move together). Over N sessions
the 95 % interval on its mean excess return is about ±1.96 × 0.74 / √N: **±0.19 % at 60 sessions, ±0.125 % at 135,
±0.075 % at 370.** To pass at 60 sessions on futures cost, the basket must therefore beat the universe by about **0.39 %
a day**. The study can detect an edge that would pay; the question is whether one exists.

---

## 2. Goals and non-goals

**Goals**
- G1. Compute the four pillars for every eligible stock after each session's close, exactly as specified in §7, from
  point-in-time data only.
- G2. Produce a directional score (0–100) per stock and direction, a separate trade-quality score, and a classification
  that removes stocks where the pillars disagree.
- G3. Publish a next-session list, 0–5 names per direction, **to a shadow store** every trading evening, with the evidence
  for each name.
- G4. Prove or disprove the edge with a pre-registered, frozen study, against random, momentum-only and partial models,
  net of the repo's cost card.
- G5. Keep every feature reusable by the positional scoring (`backend/autodesk/scoring/`) and the Scan dashboard.

**Non-goals (this PRD)**
- No user-facing list, alert, notification or paper/live order from this engine until the gate in §11 passes.
- No intraday signals (§1.2: none passed). The engine runs on end-of-day data only.
- No new data vendor. Kite data is never mixed into OI figures (Kite end-of-day OI differs from NSE's bhavcopy by
  0.8–8.2 % on near-month futures; `fno_oi_reconcile.py`, 3 Nov 2026).
- No index options (Nifty / Bank Nifty need per-expiry analysis, a separate design).
- No weights fitted on the confirmation data. The proposal's weights are the hypothesis; they are not tuned to pass.

---

## 3. User stories
- As the **owner**, I want each evening's bullish and bearish candidates with the evidence from all four pillars, so that I
  can see where the cash and derivatives markets agree.
- As the **owner**, I want an honest verdict on whether the list beats random selection after costs before anyone else
  sees it, so that we never publish a list that does not work.
- As a **researcher** (Claude / an engineer), I want every score stored with its inputs and data cut-off, so that any
  list can be reproduced and audited later.
- As the **desk** (AI Trader, Scan dashboard), I want the pillar features as an API, so that positional scoring can test
  them at 10–20 sessions without recomputing them.

---

## 4. Requirements

### 4.1 Functional
- **F1 Universes.** Two, kept separate:
  - *F&O universe*: every underlying with a stock future (`fno_bhavcopy.instrument_type = 'STF'`) on session d (218
    names on each of the last six sessions to 6 Nov 2026). All four pillars apply.
  - *Cash universe*: the 500 most liquid EQ-series stocks on d by 20-session median traded value, with ≥ 60 sessions of
    history and a 20-session median traded value ≥ ₹10 crore. Cash, delivery and price-volume pillars apply. This replaces "Nifty 500
    membership", because the warehouse has no membership history (§5.2) and a liquidity universe built from each day's
    bhavcopy is free of survivorship bias.
- **F2 Exclusions** on d: BE / trade-for-trade series; a price band of 2 % or 5 % (from `security_reference_daily`, when
  that day has a row); F&O ban list (when the feed exists, §5.3); any one-day move > 25 % in the 60-session window that the
  adjustment factor does not explain (demerger trap: VEDL, HEG); results or board meeting on d+1 known by d 22:45
  (`event_calendar.first_seen_at`). Each exclusion is stored with its reason; nothing is dropped silently.
- **F3 Features** exactly as §7.1, one function per formula, unit-tested.
- **F4 Pillar points**, rubric v0, exactly as §7.2, scored separately for the bullish and the bearish direction.
- **F5 Classification**: pillar states, conflict detection and setup label as §7.3. A stock in conflict never enters a list.
- **F6 Selection**: per direction and universe, names with no conflict and score ≥ 75, ranked by score, then by
  trade-quality score, then by 20-session median traded value (never alphabetical). At most 5. Zero is a valid answer
  and is stored with the reason.
- **F7 Trade-quality score** (0–100) and reference levels as §7.5. It orders ties and is shown beside the
  name. It never changes the directional score.
- **F8 Next-session date**: the list is for the next NSE trading session after d (holidays from the NSE calendar the
  repo already uses). A Friday run is labelled "based on Friday's close, for Monday".
- **F9 Pre-open check** (d+1, 09:08 IST): when a Kite pre-open price is available, a gap of more than 1 % against the
  idea marks the name "invalidated at open". Evidence: in the 5 Nov desk replay (session study, not committed), an open
  gap of more than 1 % against the signal was followed by −0.67 % (F&O) and −0.31 % (wider universe) 5-session excess
  return. That is a 5-session figure; the study re-tests it at one session. Without a Kite login the name is marked
  "pre-open not checked", never "valid".
- **F10 Outcomes**: after d+1's bhavcopy, store each listed name's outcome on every horizon in §7.4, plus the outcome of
  the whole eligible universe, so that baselines use the same population.
- **F11 Study**: the frozen contract and evaluator of §7.4, producing PASS / FAIL / INCONCLUSIVE.

### 4.2 Non-functional
- **N1 Point in time.** No input dated after its visibility time: cash d from 19:30 IST, F&O d from 22:45 IST (the
  convention in `backend/autodesk/market/pit.py`); events by `first_seen_at`. Rupee levels are adjusted *as of* d
  (factor(day) ÷ factor(d)), never with corporate actions announced later.
- **N2 Freshness** (owner rule, 28 Oct 2026): a list is built only from session d's data. If a required input is
  missing, there is no list for that pillar or universe, with the reason. The job never falls back to d−1.
- **N3 Determinism.** Re-running a past date with the same inputs gives byte-identical scores.
- **N4 Runtime.** The nightly run finishes within 10 minutes of the F&O bhavcopy landing (≈ 2,500 stock-days of features).
- **N5 Audit.** Every run stores its input run ids (`source_run_id` of each feed), model version, rubric hash and code
  commit.
- **N6 Compliance.** While in shadow, lists are visible only to admin accounts. No user-visible string uses the words
  in the repo's wording rule (buy, sell, stop loss, target, entry, exit, recommend, pick …) unless the owner approves a
  vocabulary for this screen (§6, §12 Q5).

---

## 5. Data — what exists, what is missing

### 5.1 Available (checked on the staging warehouse, 7 Nov 2026)

| Pillar input | Table / columns | History | Lands (IST) |
|---|---|---|---|
| OHLC, volume, turnover, trades | `nidp.prices_eod` (`open_price … close_price, volume, turnover, trades, series`) | 2024-04-01 → 2026-11-06, 643 sessions | 19:00 |
| Split-adjusted OHLC and volume | `nidp.prices_eod_adjusted` (`adj_*`, `adj_volume`, `raw_*`, `cumulative_adj_factor`) | same | 19:00 |
| Delivery | `nidp.prices_eod.deliv_qty / deliv_pct` (EQ fully covered: 2,742 of 2,742 on 5 Nov; BE none) and `nidp.delivery_data` | same | 19:00 (prices_eod); 10:30 next day (delivery_data) |
| Futures and options, by contract | `nidp.fno_bhavcopy` (`instrument_type` STF/STO/IDF/IDO, `option_type` FUT/CE/PE, `close_price, prev_close_price, open_interest, change_in_oi, traded_volume, underlying_price`) | **2025-10-01 → 2026-11-06, 271 sessions** | 22:15 |
| Futures build-up, consolidated over expiries | DaaS `GET /v1/desk/fno-buildup?date=` (`daas_api/routers/desk_market.py`) | same as above | after 22:15 |
| Nifty and sector indices | `nidp.index_eod` (`index_name, close_price, pct_change`) | 643 sessions | — |
| Results / board meetings | `nidp.event_calendar` (`event_date, event_type, first_seen_at, intimated_at`) | event dates 2024-06-01 → 2026-12-05 | — |
| Market flows (context only) | `nidp.fii_dii_flows` | 243 dates since 2018-09 | — |

Stock options carry three monthly expiries (RELIANCE on 6 Nov 2026: 23 Nov, 29 Dec, 25 Jan; 100 / 99 / 52 strikes).

Split handling checked: KOTAKBANK's 5:1 split ex 14 Jan 2026 shows `adj_volume` 12,720,435 vs `raw_volume` 2,544,087
on 12 Jan (factor 0.2). **Delivery quantity is not adjusted**: features divide `deliv_qty` by the same factor.

### 5.2 Missing or too short, and what the engine does about it

| Gap | Effect | Handling |
|---|---|---|
| F&O history is 13 months (271 sessions), against the proposal's "2–3 years" | Only one F&O regime in the sample | Backfill 2024-04-01 → 2025-09-30 with the existing ingester (`python -m nidp.services.fno_bhavcopy --date …`; config holds both the post-8-Jul-2024 UDiFF URL and the legacy URL). **UNVERIFIED:** whether the parser reads the legacy pre-July-2024 format. Writes to the shared warehouse, so it needs owner approval (§12 Q2). |
| No implied volatility or Greeks history | The proposal's "ATM IV" and "PCR / IV confirmation" cannot be scored from stored data | v0 scores PCR only. Phase 3 may compute IV from each option's settlement price (stock options are European; Black-76 on the futures price). That is unreliable for illiquid strikes, so it stays off the score until it is validated. |
| No bid/ask, no trade side (buyer- or seller-initiated) | "Call writing" vs "call buying" cannot be observed | Inferred from premium change with OI change (§7.1 F4), labelled "inferred" wherever shown. |
| No index-membership history (`index_constituents`: 5 snapshots since 12 Oct 2026) | Nifty 500 backtests carry survivorship bias | Liquidity universe built from each day's bhavcopy (F1). Sector tags are today's, so sector results carry a caveat. |
| No price-band / surveillance history (`security_reference_daily`: 20 sessions since 12 Oct 2026); no ASM / GSM lists | Backtest cannot exclude surveillance stocks point in time | Backtest excludes BE / trade-for-trade series (available in `prices_eod.series`) as the proxy; the live engine also uses the band. ASM / GSM ingester: new work (§9). |
| No F&O ban list | Live list could name a stock in its ban period, where fresh positions are not allowed | New small ingester for NSE's daily ban list (§9). Until it exists, live lists carry "ban status not checked". |

### 5.3 Two breaks in the market's own rules inside the sample
- **Closing auction (from 3 Aug 2026):** for F&O stocks, cash continuous trading ends 15:15 and the official close is the
  auction price; futures trade to 15:40. Close-location and futures-basis features change meaning on that date. The study
  reports them before and after 3 Aug 2026 separately.
- **Expiry and roll days:** OI moves into the next series near each monthly expiry. OI change is consolidated over all
  expiries (the DaaS definition), and options positioning never reads a series that expires on d or d+1.

---

## 6. UX / design notes
The owner designs this screen (standing rule: build the owner's structure exactly). This PRD fixes only the content
and the states, and nothing is user-facing before §11's gate.

- **Content per name:** symbol, universe, direction, score and band, setup label (e.g. "long build-up · delivery
  accumulation"), the four pillar sub-scores with each feature's value, the conflicts checked, the trade-quality score and
  the reference levels, pre-open status, data date ("based on 6 Nov close").
- **List-level content:** run time, inputs used (with their dates), names excluded and why, and the **band-level**
  historical results from the study (hit rate, mean excess, n, period). A per-stock "historical hit rate" is not shown:
  per-stock samples are tiny, and the figure would read as a performance claim (§10).
- **States:** loading; list built; zero names ("no stock met the bar tonight", with the count that came closest); input
  missing ("F&O data for 6 Nov has not arrived; no F&O list tonight"); stale is impossible by N2; shadow-only banner.
- **Vocabulary (owner decision, §12 Q5):** proposed neutral words are *idea*, *reference level*, *invalidation level*,
  *room to resistance* and *reward-to-risk*. "Very high conviction" becomes band labels A–E. The illustrative "Stock Radar" in the
  proposal used "opportunities" and stop-loss wording, which the 3 Nov rule does not allow outside the Scan dashboard.

---

## 7. Technical design

### 7.1 Features (exact formulas)
Notation: session d is the last completed session; t−k is k sessions before d. Prices are adjusted as of d. V = adjusted
volume, TV = turnover (₹), N = number of trades, DQ = delivery quantity ÷ adjustment factor, DP = delivery %. Nifty =
`index_eod` "Nifty 50". Medians and means exclude d unless stated.

**Cash**
- Return: r = C_d / C_{d−1} − 1
- Traded-value ratio: TVR = TV_d / mean(TV_{d−20..d−1})  *(replaces both "volume ratio" and "traded value ratio": their
  ratio is the day's price ratio, so they are the same signal counted twice)*
- Close location: CLV = (C_d − L_d) / (H_d − L_d); undefined (no points) when H_d = L_d
- Average trade size ratio: ATS = (TV_d / N_d) / median(TV/N over d−20..d−1)  *(the proposal's "cash market
  participation", made measurable with the `trades` column: larger average trades are the usual sign of institutional
  participation)*

**Delivery**
- Delivery expansion: DE = DQ_d / median(DQ_{d−20..d−1})
- Delivery participation change: DPC = DP_d − median(DP_{d−20..d−1}), in percentage points
- Three-session quadrant: ΔP3 = C_d / C_{d−3} − 1; ΔD3 = mean(DQ_{d−2..d}) / median(DQ_{d−22..d−3}) − 1
- Consistency: K3 = number of sessions in d−2..d with DQ above its 20-session median **and** a close in the scored direction
- *Delivery value (DQ × price) is not a separate feature: its ratio equals DE times the price ratio.*

**Price-volume**
- RS5 = (C_d / C_{d−5} − 1) − (Nifty_d / Nifty_{d−5} − 1); RS20 likewise over 20 sessions
- EMA20, EMA50 of adjusted closes, computed as in `nidp/services/technical_indicator_engine/calculator.py`; EMA50 slope =
  EMA50_d − EMA50_{d−5}
- Breakout: C_d > max(H_{d−20..d−1}) (20-day), C_d > max(H_{d−5..d−1}) (5-day); bearish mirrors use the lows
- ROC5 = C_d / C_{d−5} − 1
- Up-volume share: U10 = Σ V on sessions in d−9..d that closed up ÷ Σ V over d−9..d
- ATR14 (Wilder) — trade quality only

**Futures (F&O universe)**
- Price change: near-expiry future's close_price vs its prev_close_price (the expiry with the nearest `expiry_date` > d)
- OI and OI change: Σ open_interest and Σ change_in_oi over every STF contract of the underlying on d; OIchg% = Σchange ÷
  (ΣOI − Σchange) × 100, the DaaS `fno-buildup` definition (parity is a test, §8 AC-6)
- Build-up label, with materiality: |price change| ≥ 0.3 % **and** |OIchg%| ≥ 1.0 %, otherwise neutral; then
  up/up long build-up · down/up short build-up · up/down short covering · down/down long unwinding
- OI percentile: rank of ΣOI_d among ΣOI over d−19..d
- OI acceleration: OIchg%_d > OIchg%_{d−1} > OIchg%_{d−2} > 0 (bullish side; mirror for falling)
- Futures volume ratio: Σ traded_volume_d / mean over d−20..d−1 (contracts, all expiries)
- Annualised basis: b = (F_near − S) / S × 365 / calendar days to expiry; Δb = b_d − mean(b_{d−5..d−1}). S is the cash close,
  which since 3 Aug 2026 is the auction price at about 15:35, while F trades to 15:40 (noise, §5.3)

**Options (F&O universe)**
- Series: the nearest STO expiry with expiry_date > d + 1 trading session (never a series that expires on d or d+1)
- ATM = the listed strike nearest `underlying_price`; window = ATM−2 … ATM+2 listed strikes
- Only contracts with traded_volume > 0 on d count (a zero-volume row has no price that day)
- Put-writing inference: Σ put change_in_oi over ATM−2..ATM > 0 **and** the OI-weighted put premium change over those strikes < 0
- Call-unwinding: Σ call change_in_oi over ATM..ATM+2 < 0
- Bearish mirrors: call-writing inference above ATM (call ΔOI > 0, premium down); put unwinding at/below ATM (put ΔOI < 0)
- OI-PCR of the series = Σ put OI ÷ Σ call OI (all strikes); ΔPCR5 = PCR_d − PCR_{d−5}; PCR percentile among its own
  last 20 sessions (never a universal threshold)

### 7.2 Pillar points — rubric v0 (the frozen hypothesis)
Bullish points shown; the bearish rubric is the mirror (signs, lows for highs, distribution for accumulation). A
direction-free feature (TVR, ATS, DE, DPC, futures volume) earns points only for the direction of the day's move r.

| Pillar (max) | Sub-criterion | Points |
|---|---|---|
| **Cash (30)** | C1 TVR: 1.3–1.5 → 4 · 1.5–2 → 8 · 2–5 → 12 · ≥ 5 → 8 *(≥ 5× fades more, §1.2)* | 12 |
| | C2 r: 0–1 % → 2 · 1–3 % → 4 · 3–5 % → 6 · ≥ 5 % → 3 *(fade evidence)* | 6 |
| | C3 CLV: ≥ 0.75 → 6 · 0.50–0.75 → 3 | 6 |
| | C4 ATS: ≥ 1.5 → 6 · 1.2–1.5 → 3 | 6 |
| **Delivery (20)** | D1 DE: ≥ 2 → 7 · 1.5–2 → 5 · 1.2–1.5 → 2 | 7 |
| | D2 DPC: ≥ +10 pp → 5 · +5..+10 → 3 · 0..+5 → 1 | 5 |
| | D3 quadrant: ΔP3 > 0 and ΔD3 > 0 (accumulation) → 4; any other quadrant → 0 *(bearish: ΔP3 < 0, ΔD3 > 0 = distribution → 4)* | 4 |
| | D4 K3: 3 → 4 · 2 → 2 | 4 |
| **Price-volume (25)** | P1 RS5 > 0 and RS20 > 0 → 8 · RS20 > 0 only → 5 · RS5 > 0 only → 3 | 8 |
| | P2 C > EMA20 → 3 · EMA20 > EMA50 → 3 · EMA50 rising → 2 *(above a rising EMA50 helped in both periods, §1.2)* | 8 |
| | P3 close above 20-day high → 5, else above 5-day high → 3 | 5 |
| | P4 ROC5 > 0 → 2 · U10 ≥ 0.60 → 2 | 4 |
| **F&O (25)** | F1 long build-up → 8 · short covering → 6 *(bearish: short build-up 8 · long unwinding 6)* | 8 |
| | F2 OI percentile ≥ 80 → 2 · OI acceleration → 3 (only when F1 scored) | 5 |
| | F3 futures volume ratio ≥ 1.5 → 2 · Δb > 0 → 1 | 3 |
| | F4 put-writing inference → 3 · call unwinding → 2 | 5 |
| | F5 ΔPCR5 > 0 with r > 0 → 2 · PCR percentile ≥ 60 → 2 *(bearish: ΔPCR5 < 0 with r < 0, percentile ≤ 40)* | 4 |
| **Total** | | **100** |

Changes from the proposal's table, and why:
- Relative strength appeared in both cash (6) and price-volume (8). It is now scored only in price-volume.
- "Delivery value expansion" duplicated delivery expansion. Its points moved to the price–delivery quadrant, which is
  the proposal's own §3 accumulation / distribution table.
- "ATR-adjusted setup quality" describes the trade, not the direction. It moved to the trade-quality score, as the
  proposal itself recommends.
- "PCR / IV confirmation" is PCR only until IV exists (§5.2).
- Cash-universe score = (cash + delivery + price-volume) × 100 / 75.
- The ≥ 5 % and ≥ 5× tapers are hypotheses taken from §1.2. The study tests them like everything else.

### 7.3 Classification
- **Pillar state** for a direction: *supporting* when that direction earns ≥ 50 % of the pillar's maximum and the
  opposite direction earns < 25 %; *opposing* when the reverse holds; otherwise *neutral*.
- **Conflict**: at least one pillar supports the bullish side and at least one supports the bearish side → class
  "Conflict"; the stock appears in neither list. (This covers the proposal's §7 matrix row "Strong · Strong · Long
  build-up · Bearish = positioning conflict".)
- **Aligned**: no opposing pillar, and ≥ 3 of 4 supporting (F&O universe) or 3 of 3 (cash universe).
- **Setup label** = futures label (F&O universe) + delivery quadrant name, e.g. "Short covering · accumulation". The
  proposal's "possible reversal" (weak cash, strong delivery, short covering, bullish options) is the label "Short
  covering · accumulation" with cash neutral.
- **Bands** (proposal's thresholds, stored as codes): A 85–100 · B 75–84 · C 65–74 · D 50–64 · E < 50. Lists draw from
  A and B among Aligned names only.

### 7.4 Validation study (pre-registered; nothing reaches users without it)
**Study id** `NIDP-ND-VALIDATION-001`, following the Smart Money pattern. The contract is frozen as JSON, hashed with
SHA-256 and stored in an immutable row *before* any confirmatory data is scored; a hash mismatch aborts the run
(`nidp/migrations/175_smart_money_study_contract.sql`, `nidp/services/smart_money_study/evaluator.py`).

**Primary hypothesis H1.** On the F&O universe, the bullish list (rubric v0, §7.2–7.3) beats the equal-weight eligible
universe from the next session's open to its close by more than the futures round-trip cost.
- e_t = mean over listed names of (C_{d+1}/O_{d+1} − 1) − mean over all eligible names of the same; days with no names
  are recorded as no-trade days.
- κ = 0.204 % (desk-cost-v2, futures, ₹1 lakh), or 0.370 % if the owner chooses cash delivery (§12 Q1).
- **PASS**: the 95 % CI of mean(e_t) − κ has its lower bound > 0, **and** the paired difference vs the momentum-only model
  (M1) has its lower bound > 0, **and** at least 40 % of sessions have ≥ 1 listed name.
- **FAIL**: the upper bound of mean(e_t)'s CI < κ (the list cannot pay its costs).
- **INCONCLUSIVE**: anything else, including thin coverage.
- CI: moving-block bootstrap over sessions, block length 5, 5,000 resamples, fixed seed recorded in the contract.

**H2 (bearish list)** is a separate hypothesis on the same rule, using the short-side return, futures only (a retail
investor cannot hold a cash short overnight). Earlier evidence on bearish signals points both ways: they beat bullish
signals on the 5-session desk replay (5 Nov session study, not committed), but lost when shorted at 10–20 sessions
(`SIGNAL_TIER_HIERARCHY.md` §10). Until H2 passes, bearish names appear
only as risk warnings, the same rule the owner set for v2 on 5 Nov.

**Models compared** (each ranks the same eligible names on the same days, top 5 by its own score):
M0 random (1,000 draws of 5 names per day; the model's percentile is reported) · M1 momentum only (RS20) · M2 cash ·
M3 cash + delivery · M4 cash + price-volume · M5 cash + futures (F1–F3) · M6 cash + options (F4–F5) · M7 all four
(ranking only) · **M7-rule** all four with the conflict filter and score ≥ 75 (the product rule; H1's subject).

**Outcomes stored** per name and for the universe: open→close d+1 (primary); open d+1 → open d+2 (overnight hold);
close d → close d+1 (reference only: the close-to-open gap is not tradable from an evening list); d+1 high and low from
the open (MFE, MAE, touched +2 / +3 / +5 %); open d+1 → close d+5.

**Secondary reporting** (never used to claim PASS; Holm-adjusted p-values): hit rate; touch rates; MFE / MAE; each ablation
model vs M0 and M1; regimes (Nifty above / below its 50-day average × 20-session Nifty return in terciles); size buckets
(terciles of 20-session median traded value); sector (today's tags, caveated); before / after 3 Aug 2026; expiry weeks.

**Periods.**
- *Exploratory* 1 Oct 2025 → freeze date: build, debug and inspect freely. **This is not evidence.** Parts of it were
  already studied (desk replay May–Nov 2026), so it cannot be a clean test.
- *Retrospective confirmatory* 1 Jul 2024 → 30 Sep 2025, only if the F&O backfill (§12 Q2) is approved, loaded **after**
  the freeze, and scored once. The F&O pillars have never been seen on this period. The cash features were used to fit
  10–20-session positional signals on Apr 2024 – Sep 2025; that is a different horizon, but some contamination remains
  and is stated in the report.
- *Prospective confirmatory*: the first 60 trading sessions after the freeze (≈ 3 months), from the nightly shadow run.
  This is the cleanest test. PASS needs both confirmatory periods to pass where both exist.

**Costs and caveats in every report:** cost card version; survivorship (none for the bhavcopy universes; sector tags
are today's); one market history; the auction-close break; no IV; inferred option writing.

**If H1 fails:** no next-day list is published. The features and pillar scores still run nightly. They are offered to
the positional version registry as candidates at 10–20 sessions, through the normal walk-forward process in
`SIGNAL_TIER_HIERARCHY.md` §8.

### 7.5 Trade-quality score and reference levels (separate from direction)
| Component | Points |
|---|---|
| ATR14 as % of close: 1–4 % → 30 · 4–6 % → 15 · otherwise 0 | 30 |
| Room to resistance: (highest high of the last 60 sessions above C_d − C_d) ÷ ATR14: ≥ 2 → 30 · 1–2 → 15 · < 1 → 0; none above → 30 | 30 |
| Liquidity: 20-session median traded value ≥ ₹50 crore → 20 · ₹10–50 crore → 10 | 20 |
| No results or board meeting on d+1 or d+2 → 20 | 20 |

Reference level = C_d; invalidation level = C_d − 1 × ATR14 for bullish, + 1 × ATR14 for bearish (next-session horizon);
reward-to-risk = room ÷ 1 ATR. These are display and study fields (MAE vs invalidation is reported). They are not orders.

### 7.6 Components (Python)
Follows the NIDP service layout (`smart_money_scores` is the model).

```
backend/nidp/services/next_day_engine/
  __main__.py        python -m nidp.services.next_day_engine [--date D] [--dry-run] [--skip-if-done]
                                                             [--backfill-from D --backfill-to D]
  inputs.py          point-in-time reads (SQL in §7.7) + input gate (N2): each feed has d's rows, row counts within
                     ±10 % of their 20-session median, ≥ 200 STF names, EQ delivery coverage ≥ 95 %
  features.py        one pure function per formula in §7.1
  pillars.py         rubric v0 → bullish and bearish points; RUBRIC dict hashed into the run row
  classify.py        pillar states, conflict, setup label, band
  trade_quality.py   §7.5
  service.py         nightly run: inputs → features → pillars → classify → lists → writer
  writer.py          upserts by (as_of_date, symbol, model_version)
backend/nidp/services/next_day_study/
  outcomes.py        fills nidp.nd_outcomes after d+1's bhavcopy (19:45 IST)
  evaluator.py       H1 / H2, models M0–M7-rule, block bootstrap, PASS / FAIL / INCONCLUSIVE
backend/nidp/studies/NIDP-ND-VALIDATION-001.json      the frozen contract
backend/nidp/services/daas_api/routers/next_day.py    read-only routes (§7.9)
backend/routes/next_day.py                            app route, admin-only while in shadow
```

The F&O consolidation reuses the DaaS `fno-buildup` arithmetic, and a parity test (AC-6) keeps the two from drifting
apart. RSI, EMA and ATR come from the repo's indicator calculator, not new code.

### 7.7 SQL data requirements (read-only inputs)
```sql
-- (a) cash + delivery window for one session d (60 sessions back), EQ series, adjusted as of d
WITH s AS (SELECT as_of_date FROM nidp.prices_eod WHERE as_of_date <= :d
           GROUP BY 1 ORDER BY 1 DESC LIMIT 61),
f AS (SELECT symbol, cumulative_adj_factor AS f_d FROM nidp.prices_eod_adjusted WHERE as_of_date = :d)
SELECT p.as_of_date, p.symbol, p.series,
       a.raw_open  * a.cumulative_adj_factor / f.f_d AS o,      -- as-of-d adjustment (pit.py rule): RAW bar
       a.raw_high  * a.cumulative_adj_factor / f.f_d AS h,      -- × factor(day) ÷ factor(d). The stored adj_* are
       a.raw_low   * a.cumulative_adj_factor / f.f_d AS l,      -- back-adjusted with LATER actions too, so never
       a.raw_close * a.cumulative_adj_factor / f.f_d AS c,      -- use them for a past d
       a.raw_volume * f.f_d / a.cumulative_adj_factor AS v,
       p.turnover AS tv, p.trades AS n,
       p.deliv_qty / a.cumulative_adj_factor * f.f_d AS dq,     -- delivery is stored unadjusted
       p.deliv_pct AS dp
FROM nidp.prices_eod p
JOIN s USING (as_of_date)
JOIN nidp.prices_eod_adjusted a ON a.symbol = p.symbol AND a.as_of_date = p.as_of_date
JOIN f ON f.symbol = p.symbol
WHERE p.series = 'EQ';

-- (b) futures, consolidated per underlying for session d (the DaaS fno-buildup definition)
SELECT ticker_symbol AS symbol,
       sum(open_interest) AS oi, sum(change_in_oi) AS oi_chg, sum(traded_volume) AS fut_vol,
       (array_agg(close_price      ORDER BY expiry_date))[1] AS near_close,
       (array_agg(prev_close_price ORDER BY expiry_date))[1] AS near_prev,
       min(expiry_date) AS near_expiry
FROM nidp.fno_bhavcopy
WHERE as_of_date = :d AND instrument_type = 'STF'
GROUP BY 1;

-- (c) options window: nearest stock-option series that does not expire on d or d+1
SELECT ticker_symbol AS symbol, expiry_date, strike_price, option_type,
       close_price, prev_close_price, open_interest, change_in_oi, traded_volume, underlying_price
FROM nidp.fno_bhavcopy
WHERE as_of_date = :d AND instrument_type = 'STO'
  AND expiry_date > :next_session;          -- then keep the min(expiry_date) per symbol in Python

-- (d) Nifty for relative strength
SELECT as_of_date, close_price FROM nidp.index_eod WHERE index_name = 'Nifty 50' AND as_of_date <= :d;

-- (e) events known by the run time
SELECT symbol, event_type, event_date FROM nidp.event_calendar
WHERE event_date BETWEEN :next_session AND :session_after AND first_seen_at <= :run_cutoff;
```
Checked on the staging warehouse, 7 Nov 2026, with d = 6 Nov: all five queries run. (a) returns 157,001 rows (61
sessions), (b) 218 underlyings, (c) 33,179 option rows before the nearest-series step, (d) 643 rows (so `'Nifty 50'` is
the right `index_name`), (e) 31 events on 9–10 Nov known by the cut-off. Query (a) checked on the KOTAKBANK 5:1 split
(ex 14 Jan 2026): as of 13 Jan, the 12 Jan bar stays raw (₹2,133.30, volume 2,544,087), so the later split does not
leak in. As of 20 Jan, the same bar reads ₹426.66 with volume 12,720,435 and delivery ×5, matching the post-split
₹421.00. In a backfill, a universe member's history comes from that day's bhavcopy, never from today's lists.

### 7.8 New tables (NIDP migration, additive)
```sql
CREATE TABLE nidp.nd_scores_daily (
  as_of_date date, symbol text, universe text,            -- 'FNO' | 'CASH'
  model_version text, rubric_sha256 text,
  eligible boolean, ineligible_reason text,
  features jsonb,                                          -- every §7.1 value, null where undefined
  bull_points jsonb, bear_points jsonb,                    -- per sub-criterion
  bull_score numeric(5,1), bear_score numeric(5,1),
  pillar_states jsonb, classification text, setup_label text, band text,
  trade_quality numeric(5,1), ref_level numeric, invalidation_bull numeric, invalidation_bear numeric,
  inputs jsonb,                                            -- source_run_id per feed, data cut-off times
  run_id uuid, computed_at timestamptz,
  PRIMARY KEY (as_of_date, symbol, universe, model_version));

CREATE TABLE nidp.nd_lists (
  as_of_date date, list_date date, universe text, direction text, model_version text,
  rank smallint, symbol text, score numeric(5,1), status text,   -- 'shadow' | 'published'
  preopen_status text,                                            -- 'valid' | 'invalidated_at_open' | 'not_checked'
  reason_if_empty text, run_id uuid,
  PRIMARY KEY (as_of_date, universe, direction, model_version, rank));

CREATE TABLE nidp.nd_outcomes (
  as_of_date date, symbol text, universe text,
  ret_oc_d1 numeric, ret_oo_d2 numeric, ret_cc_d1 numeric, ret_oc_d5 numeric,
  mfe_d1 numeric, mae_d1 numeric, filled_at timestamptz,
  PRIMARY KEY (as_of_date, symbol, universe));
```
`nd_outcomes` covers every eligible name, not only listed ones, so baselines are scored on the same population. The
study contract uses the immutable-config pattern of migration 175: either reuse `smart_money_study_config` if its
columns fit, or create a sibling table. That choice is made at build time and stated in the build PR.

### 7.9 APIs
DaaS (API key, read-only):
- `GET /v1/next-day/lists?date=D&universe=FNO|CASH` → `{as_of_date, list_date, status, inputs:{feed:{date, run_id}},
  bullish:[{rank, symbol, score, band, setup_label, pillars:{cash,delivery,price_volume,fno}, trade_quality, levels,
  preopen_status}], bearish:[…], empty_reasons:{…}, excluded_counts:{reason:n}}`
- `GET /v1/next-day/stock/{symbol}?date=D` → the full `nd_scores_daily` row: every feature, points, states, conflicts.
- `GET /v1/next-day/study/NIDP-ND-VALIDATION-001` → contract hash, periods, n, statistics, verdict.
- Errors: `404` no run for that date; `409` with `{"missing": ["fno_bhavcopy"]}` when the inputs gate failed; never a
  list from another date.

App (signed-in): `GET /api/next-day/lists?date=` proxies DaaS through `daas_client`. It returns `403` to non-admins while
the status is shadow.

### 7.10 Daily workflow (IST, NSE trading days)
| Time | Step |
|---|---|
| d 19:00 | `prices_eod` + delivery land; visible from 19:30 |
| d 19:45 | outcomes for the previous list (its d+1 is today) |
| d 22:15 | `fno_bhavcopy` lands |
| d 22:45 | engine run: inputs gate → features → scores → lists (shadow); `--skip-if-done` |
| d 23:30 | retry if the gate failed; after that the day is stored as "no list: <input> missing" |
| d+1 09:08 | pre-open check against Kite pre-open prices (needs the day's admin Kite login) |
| Friday | the 22:45 run lists for Monday (or the next session after a holiday), labelled as such |

Cron goes in the NIDP cron set next to the 22:45 jobs. Installing it is a change to shared infrastructure and needs the
owner's go-ahead.

---

## 8. Acceptance criteria (the QA contract)
- [ ] **AC-1** Given all inputs for d, when the 22:45 run completes, then `nd_scores_daily` has one row per symbol of
  both universes (eligible or not, with reason), and `nd_lists` has 0–5 rows per direction and universe with `list_date`
  = the next NSE session.
- [ ] **AC-2** Given `fno_bhavcopy` has no rows for d at 22:45, then no F&O list is written, the 23:30 retry runs, and if
  still missing the day reads `reason_if_empty = 'fno_bhavcopy missing for d'`. No row uses d−1 F&O data.
- [ ] **AC-3** Formula unit tests: TVR, CLV (H = L → null, 0 points), ATS, DE, DPC, ΔP3 / ΔD3, K3, RS5 / RS20, U10, OIchg%,
  basis, PCR — each against hand-computed fixtures.
- [ ] **AC-4** Split: for KOTAKBANK across 14 Jan 2026, DE and TVR on 15–20 Jan compare like with like (delivery divided by the
  factor); without the adjustment the test fails.
- [ ] **AC-5** Look-ahead: re-running a past d with every input row ingested after d+1 00:00 IST removed gives identical
  scores; an event whose `first_seen_at` is after the cut-off does not exclude the stock.
- [ ] **AC-6** Parity: for 15 random underlyings on 3 sessions, the engine's OI, OI change, OIchg% and label equal DaaS
  `/v1/desk/fno-buildup` (label equal wherever both clear the materiality rule).
- [ ] **AC-7** Options: on a d where a stock series expires on d+1, the options pillar reads the next series; contracts with
  zero traded volume are ignored.
- [ ] **AC-8** Conflict: a stock whose futures pillar supports bearish while cash supports bullish is classified "Conflict"
  and is in neither list.
- [ ] **AC-9** Zero names: when no aligned name scores ≥ 75, the list is empty and states the reason and the closest score.
- [ ] **AC-10** Ties are broken by trade quality, then liquidity, never alphabetically (fixture with equal scores).
- [ ] **AC-11** Universe: a symbol that stopped trading in 2025 appears in backfilled universes on the dates it traded.
- [ ] **AC-12** Exclusions: BE series, 2 % / 5 % band, results on d+1 known by the cut-off, and a > 25 % unexplained move are
  each excluded with their reason.
- [ ] **AC-13** Determinism: two runs of the same d produce identical `nd_scores_daily` rows (except `run_id`, `computed_at`).
- [ ] **AC-14** Study contract: altering one byte of the stored config makes the evaluator abort with a hash mismatch.
- [ ] **AC-15** Evaluator: on synthetic data with a planted +0.6 %/day edge it returns PASS; with no edge, FAIL or INCONCLUSIVE;
  with 30 % coverage, INCONCLUSIVE.
- [ ] **AC-16** Random baseline M0 uses the same eligible set per day as M7-rule (checked by count per day).
- [ ] **AC-17** Access: a non-admin session gets 403 from `/api/next-day/lists` while status is shadow.
- [ ] **AC-18** Wording: an output lint finds none of the restricted words in any user-visible string or LLM explanation
  prompt of this feature (reuse the PR #458 lint).
- [ ] **AC-19** Runtime: the 22:45 run on staging finishes within 10 minutes (log timestamps).
- [ ] **AC-20** Weekend: a Friday run writes `list_date` = Monday, or the next session when Monday is a holiday.

The verification protocol applies: test cases are authored in `test_reports/` before implementation, and backend
results are shown from staging.

---

## 9. Dependencies and sequencing
| Phase | Work | Depends on | Exit |
|---|---|---|---|
| **P0** | This PRD; owner answers §12 | — | PRD APPROVED |
| **P1** | Engine (features, pillars, classify, trade quality, writer, DaaS + app read routes) computed over the 271 F&O sessions and 643 cash sessions; exploratory report | P0 | AC-1…13, 17–20 pass on staging; exploratory report committed |
| **P2** | Freeze `NIDP-ND-VALIDATION-001` (hash stored); F&O backfill Apr 2024 – Sep 2025 if approved (legacy-format parser check first); retrospective confirmatory run; nightly cron in shadow | P1, owner Q2/Q3 | AC-14…16; retrospective verdict |
| **P3** | 60 prospective sessions in shadow; F&O ban-list and ASM / GSM ingesters; optional computed IV (validated before scoring) | P2 | prospective verdict report |
| **P4** | Only on PASS + compliance sign-off: owner-designed screen behind an allowlist flag, then everyone | P3 PASS, §12 Q5/Q6 | §11 rollout |

On FAIL or INCONCLUSIVE at P3 the project stops at P3. The features and pillar scores go to the positional registry as
candidate inputs (§7.4).

---

## 10. Risks
| Risk | Mitigation |
|---|---|
| No next-session edge exists (the likely outcome, §1.2) | Shadow first; a cheap, honest stop at P3; features reused at 10–20 sessions |
| Overfitting: 20 sub-criteria with thresholds | Rubric frozen before the confirmatory periods; one primary hypothesis; Holm on secondary results |
| Only 13 months of F&O history | Backfill + a 60-session prospective test; both reported |
| Survivorship and today's sector tags | Universes from each day's bhavcopy; sector results caveated |
| Option writing is inferred, not observed | Labelled "inferred"; 5 of 100 points |
| Closing-auction break (3 Aug 2026) | Before / after split in every report |
| SEBI: a named next-day list with levels is research-analyst activity | Shadow and admin-only until legal sign-off; neutral wording; band-level (not per-stock) performance (§12 Q6) |
| Kite pre-open needs a daily admin login | "Not checked" state; never assumed valid |
| Inputs late (22:15 F&O) or missing | Inputs gate + retry + explicit "no list"; no stale fallback |
| Disk / cron changes on shared VMs | Owner go-ahead before installing the cron or running the backfill |

---

## 11. Success metric and rollout
- **Measure:** the study verdict. PASS on H1 (and H2 for the bearish list) in every confirmatory period run is the only
  route to users. After launch, the same evaluator runs monthly on new sessions. A verdict that turns to FAIL on a
  rolling 60 sessions hides the list again.
- **Rollout:** shadow (admin only) → allowlist flag → everyone. Rollback = flag off, with the trigger above.
- Engineering measure from P1: nightly run success rate and runtime, and the share of days with a list.

---

## 12. Open questions (owner)
1. **Q1 Instrument and cost.** Which round trip should H1 use: futures 0.204 %, cash delivery overnight 0.370 %, or cash
   intraday, which the cost card does not have yet? The proposed default is futures, because it is the cheapest
   realistic route for F&O names.
2. **Q2 F&O backfill.** May the existing F&O bhavcopy ingester load 1 Apr 2024 – 30 Sep 2025 into the staging warehouse
   (about 370 sessions, written to the shared NIDP database)?
3. **Q3 Shadow period.** Do you accept 60 prospective sessions (about 3 months) in shadow before any user-facing list?
   And should shadow lists be visible to admin accounts only?
4. **Q4 Bearish list.** Keep bearish names as risk warnings until H2 passes (the 5 Nov rule for v2)?
5. **Q5 Wording.** On this screen, use the neutral vocabulary in §6, or the standard trading words you allowed on the
   Scan dashboard?
6. **Q6 SEBI.** Publishing a named next-session list with levels to users reads as research-analyst activity. A
   compliance or legal view on registration, disclosures and past-performance claims is needed before P4 (verify
   against the current SEBI RA regulations and master circular).
7. **Q7 Screen.** You design the screen. Where should it live: Trading Desk, Scan dashboard or Market Desk?
8. **Q8 Universes.** Run both the F&O and cash universes from P1, or F&O only first, as the proposal's four-pillar case?
