# Ten-Percent Days — complete plan after the Kite backfill

**Written 2026-09-19.** Governs all work from here. Every step is judged against `pattern_engine/SUCCESS_CRITERIA.md`
(five gates, three stages) and follows `pattern_engine/PAPER_TRADING_SPEC.md`. Evidence to date:
`RESEARCH_NOTES_2026-09-18_19.md`, `gapdown/G1_RESULT.md`.

**Objective (owner, 2026-09-19): detect early, confirm objectively, define risk before entry, and exit when the trade
thesis changes — not "find stocks likely to rise 5%".** Trades are executed **manually** by the owner, so the product is
an **Early Signal + Entry Zone + Exit Intelligence** system (Phase H), not an automated trading system.

## 0. Where we stand

| Asset | State |
|---|---|
| Kite daily candles, 2021-01-01 → 2026-09-18 | 2,895 symbols, 2,916,948 rows (+7 hyphenated symbols top-up) — `/app/research/kite_history/day_2021/` |
| Kite minute bars, gap-down sessions 2024–26 | 4,052 pairs (3,887 + 165), validated — `gapdown_minute_v2/` |
| Kite 5-minute bars, top-800 liquid, 2024-08 → | BACKFILL_RESULT_5MIN — `five_min_2024/` |
| Research panel 2024–26 (bhavcopy) | Durable copy; **phantom gaps** — use only with Kite-derived gaps (`/app/research/tpd3_panel/README.md`) |
| Paper Trade Engine v1 | Replay done (no edge); forward run of the v4 model counts from **Mon 2026-09-21** |
| Pattern registry | 19 hypothesis families tested on 2024–26 (`pattern_engine/REGISTRY_SEED.md`) |

**Candidates still standing (all exploratory, discovery data only):**
- **H-A** gap-down ≤ −3%, buy at the open, sell at the close, **liquid names (> Rs 5 cr)**: +0.697%/session, t 3.94.
- **H-B** gap-down **early-confirmation entry** (enter only if the first minutes hold up): suggested by the timing study.
- **H-C** gap-up 5-day continuation (−1.207% on day 1, +0.457% over 5 days, per stock-day): weakest, optional.

G1 with target/stop is **abandoned** (pre-registered condition 3). v4/v5 models, setups A–D, hourly signal and the
single-feature lifts have **failed**.

## 1. Rules that apply to every phase
1. **The 2021-01 → 2024-07 period is sealed.** No outcome from it is read until the hypothesis tested on it is
   pre-registered and committed. Counting events by their entry condition only (e.g. how many gaps) is allowed for sizing.
2. **Split the sealed period in two** (owner decision D1): a **validation** slice for Stage 2 and a **final-test** slice
   kept sealed for Stage 3. Recommended: validation 2021-01 → 2022-12, final test 2023-01 → 2024-07. Each slice is
   single-use per hypothesis family.
3. **Data checks are gate 1.** Every cross-source join is checked on two fields (same raw/Kite factor on open and close;
   minute 09:15 open = Kite daily open). Gaps and multi-day paths come from Kite's adjusted series. Extreme-decile
   audit before trusting any extreme-selection result.
4. **Economics decide.** Net return after a liquidity-dependent cost model, per-session statistics, whole-market-day
   resampling, year/liquidity/regime splits, outlier dependence. Accuracy/AUC never decides.
5. **Every test is logged** in the registry's multiple-testing count, failures included.
6. **Research environment only.** Nothing enters the product backend (whose builds run on the prod-shared app-vm)
   until a pattern reaches Stage 3.

## 2. Phases

### Phase A — Certify the backfill (today, after it completes)
| # | Task | Output / acceptance |
|---|---|---|
| A1 | Validate 5-minute bars: first bar open = Kite daily open; session max-high / min-low vs daily high/low; bars per session (75 expected); missing sessions; status errors | Check report with pass rates; exclusions listed |
| A2 | Confirm the 7-symbol daily top-up | Status rows OK |
| A3 | **Data manifest**: every dataset's range, rows, `fetched_at`, adjustment state (splits/bonuses/dividends), known gaps (survivorship: Kite lists today's names only) | `DATA_MANIFEST.md` |
| A4 | Turn the three join checks into **pytest tests** over the research datasets | Tests run in CI-style locally; a failing check blocks any study |

### Phase B — Data foundation v2 (replace the phantom-prone panel)
| # | Task | Notes |
|---|---|---|
| B1 | Build the stock-day research table from **Kite adjusted daily 2021–26**: point-in-time features (only data ≤ t), turnover = volume × close, real gaps | Discovery rows (2024-08 →) usable immediately; sealed rows built but not analysed |
| B2 | Labels: movement (1d/5d touch), downside (−3/−5/−10%), **target-before-stop** (5d from daily with the conservative both-touched rule; 1d from 5-minute bars for the top 800), net return | Same code for discovery and sealed periods |
| B3 | **Liquidity-dependent cost model**: statutory charges (STT, exchange transaction charge, SEBI fee, stamp duty, GST, brokerage) + spread/slippage by turnover bucket | Versioned; assumptions stated. The one surviving effect lives in thin names, where a flat 0.25% is least realistic |
| B4 | **Survivorship**: try NSE bhavcopy archives 2021–24 through the app-vm proxy route to recover delisted names and raw prices; if impossible, quantify the bias | UNVERIFIED feasibility — NSE blocks this VM; the proxy route works for NSE APIs |
| B6 | **Delivery-data hole**: `deliv20` is present 100% in 2024 Q3–Q4, 63% in 2025 Q1, **~0% in 2025 Q2–Q4**, 33–40% in 2026 Q1–Q2. Kite has no delivery data. Recover from NSE delivery archives through the app-vm proxy route | UNVERIFIED feasibility. **Blocks the accumulation family** until fixed |
| B7 | **Announcement history**: `nidp.corporate_announcements` spans only **2026-01-19 → 2026-09-18** (213,637 rows, all with `broadcast_at`). Backfill 2021–2025 (NSE via proxy; BSE incl. `AttachHis/`) | UNVERIFIED feasibility. **Blocks the event/catalyst family** for discovery and validation |
| B8 | **Relative strength inputs**: Nifty and sector index candles from Kite (index history — to verify), and fill `sector_master` (61% UNKNOWN) | Needed for the relative-strength family |
| B5 | **Point-in-time audit** before any fundamental or event feature: the features-extended overwrite (memory 2026-09-16; migration 148 not applied), announcement publication timestamps, `sector_master` (61% UNKNOWN) | Until it passes, fundamentals and events stay out of every model |

### Phase C — Pre-register (before reading any sealed outcome)
Hypotheses to register (owner decision D2 chooses which spend the validation slice):

| ID | Family | Prior evidence | Data readiness |
|---|---|---|---|
| H-A | Gap-down, open → close, liquid names | +0.697%/session, t 3.94 (discovery) | Ready |
| H-B | Gap-down, early-confirmation entry | Timing study: drawdown by 10:00 predicts the close | Ready (2021–24 intraday needs one login) |
| H-D | **Continuation after controlled pullback** (owner) | Related breakout/momentum features moved but lost net (20-day high −0.80%, pivot breakout −0.54%). Only new if the **5-minute confirmation** is part of the rule | Daily ready; 5-minute for top 800 from 2024-08 |
| H-E | **Accumulation → confirmed range expansion** (owner) | Untested as a combined family | **Blocked by B6** (delivery hole) |
| H-F | **Event/catalyst reaction with defined risk** (owner) | Untested | **Blocked by B7** (8 months of announcements) |
| H-C | Gap-up 5-day continuation | Weak, descriptive only | Ready; optional |

For each registered hypothesis: exact entry/exit rule, **one primary endpoint**, abandon conditions (including
the liquidity split that ended G1), cost-model version, universe, sample-size floor, Bonferroni for secondaries, and
the registry entry. **H-B must fix one confirmation rule and its time before seeing sealed data, with returns measured
from the later entry price** (not the open). Commit with a timestamp before Phase D.

### Phase D — One-shot validation on the sealed slice (needs one Kite login)
| # | Task | Size (estimated from discovery rates, no sealed outcomes read) |
|---|---|---|
| D1 | Fetch intraday bars for validation-slice gap-down sessions | ≈ 7.5 pairs/session × ~495 sessions (2021–22) ≈ 3,700 minute-bar requests ≈ 35–40 min |
| D2 | (If H-B or 1-day labels need it) 5-minute bars, top-800, 2021–22 | ≈ 800 × 8 windows ≈ 6,400 requests ≈ 60 min |
| D3 | Run H-A / H-B / H-C exactly as registered; full success-criteria report | Pass → Stage 2 (validation candidate). Fail → registry, stop |
| D4 | Stage 3 later: the same, once, on the final-test slice (2023-01 → 2024-07) with realistic execution | Pass → production candidate → paper shadow |

### Phase E — Pattern Discovery Engine v1 (in parallel; discovery period only)
| # | Task |
|---|---|
| E1 | Install **statsmodels** in the research environment (clustered/HAC inference) |
| E2 | Univariate and interaction analysis of features vs the four targets, market-day clustered |
| E3 | Logistic baselines for movement, direction, target-before-stop, net return |
| E4 | `HistGradientBoosting` challenger; judged on **top-bucket net return after costs**, not AUC |
| E4b | **Entry Feature Engine** (owner): six families as *features, never standalone rules* — trend (EMA 20/50/200, ADX), momentum (RSI, ROC, MACD histogram), volume (relative volume, OBV, delivery trend), volatility (ATR, Bollinger width), relative strength (vs Nifty and sector), price action (support/resistance, VWAP, breakout structure). Most of trend/momentum/volume/volatility/price-action was already in v5, which failed on net return — the **new** ingredients to test are relative strength vs index/sector and 5-minute/VWAP confirmation |
| E4c | **Entry Readiness Score** (owner weights 25/20/20/15/10/10): registered as a **fixed baseline**, compared with a fitted (logistic) combination; weights are never tuned on discovery data and then called validated. Research feature until it shows better forward net returns out of sample |
| E5 | Rule-based regime classifier (index trend, breadth, volatility); HMM only as a forward-filtered challenger |
| E6 | Event studies (results, orders, approvals) — **only after B5 passes** |
| E7 | Registry and validation tables as a migration — drafted, applied only with owner approval |
Any new candidate from E goes through C → D. Because each sealed slice is single-use, new candidates found after D
may have to wait for forward paper data as their out-of-sample test.

### Phase F — Paper trading integration (per `PAPER_TRADING_SPEC.md`)
| # | Task |
|---|---|
| F1 | Extend the engine: `pattern_id` / `pattern_version`, per-signal feature snapshots, beside the existing immutable tables |
| F2 | Intraday execution on 5-minute bars (entry delay, spread assumption, achievable fills on gap-through) |
| F3 | **Shadow mode** for any pattern that passes D3 (frozen signals, no orders), then paper execution |
| F4 | Error analysis (reads `tpd_paper_universe_outcomes` for false negatives), then calibration once probabilities exist |
| F5 | Pattern-level dashboard breakdowns |
| F6 | Keep the v4 forward run as a **labelled control** (a known Stage 1 failure), never presented as an opportunity model |
Live 5-minute data needs a **daily Kite login** — without it, that day produces no intraday signals.

### Phase H — Manual signal engine (owner proposal, 2026-09-19)
Flow: **EOD model → next-day watchlist with entry zone, invalidation and target → 5-minute confirmation → manual entry →
exit intelligence.** The three states separate "a stock may move" from "a good trade is available now".

| # | Task | Notes |
|---|---|---|
| H1 | **Setup state machine**: Accumulation Watch → Trigger Watch → Confirmed Opportunity → Invalidated / Expired | Every transition written to the immutable signal ledger with its timestamp and feature snapshot, so each stage's incremental value can be measured (does Watch predict Trigger? does Trigger add value over Watch?) |
| H2 | **Target/stop outcome model**: P(target first), P(stop first), **P(neither)**, expected gross and net return, MFE, MAE — calibrated out of sample | EV = P_T·R_T − P_S·R_S **+ P_N·E[R \| timeout]** − C. The "neither" term is not optional: it is 23.5% of 5-session +5%/−3% outcomes overall and 66% in low-ATR names |
| H3 | **Stop and target intelligence**: structure, ATR, time, event and trailing stops chosen from the setup's historical behaviour, volatility and liquidity — never "the stop with the best backtest" | Timing evidence: on gap-down days 68% of lows are set by 10:00 (median 2 minutes after the open), so entering after a 15–30 minute confirmation places the stop after the noisiest window |
| H4 | **5-minute confirmation, tested separately**: first 15–30 minutes observed; predefined trigger with candle structure, volume, VWAP; reward/risk recomputed at the actual entry price; no entry on the gap alone | Its value is a hypothesis (H-B, H-D), not an assumption |
| H5 | **Manual-execution realism in every backtest and paper test**: entry at the next 5-minute bar after the trigger plus slippage (human latency), a cap on alerts per day (attention), stops placed manually vs exchange stop orders | Owner decision D8 sets the daily alert cap |
| H6 | **Manual signal dashboard**: Today's Opportunities (Early Watchlist / Trigger Watch / Confirmed counts), Open Positions (target proximity, stop risk, thesis deterioration). Each card: price and change, state, setup type, entry zone, stop and targets, reward/risk, probabilities, signal age, data freshness, three drivers and three risks, reason to enter / not to enter, **plus the setup's historical sample size and calibration** | Product code: staging verification gate applies, and any `dev` push needs ≥ 6 GB free on the app-vm |
| H7 | **Morning Kite login routine**: the owner logs in to trade anyway; the redirect to `/v5/kite-callback` (live on staging) supplies the day's token for the 5-minute feed | Replaces an unattended login |
| H8 | **Paper validation of manual signals**: every signal, entry timing, target/stop events, slippage and **missed opportunities** recorded (feeds F4 error analysis) | Signals from families that have passed Phase D only; others shown as research, clearly labelled |

Owner's implementation order within H: feature engine (E4b) → state machine (H1) → target/stop model (H2) →
dashboard (H6) → paper validation (H8). Gap-down stays a **separate research strategy** until it passes Phase D.

### Phase G — Production (only after Stage 3)
Liquidity and risk exclusions, drift monitoring, limited deployment. SEBI RA/IA question before any wider allowlist
(memory: ten-percent-days-3-plan).

## 3. Sequence and dependencies
```
A (today) ──► B1–B3 ──► C ──► D (login) ──► F3 shadow ──► D4 final test ──► G
                 │                 ▲                │
                 ├── B4–B8 ────────┘                └──► H1–H2 ──► H6 dashboard ──► H8 manual paper validation
                 │   (B6 gates H-E, B7 gates H-F, B5 gates E6)
                 └── E1–E5, E4b–E4c (parallel, discovery only) ──► new candidates ──► C
```
Critical path: **A → B1–B3 → C → D.** Rough estimate: A and B1–B3 in 2–3 working sessions; C in one; D in one session
plus one login. E runs alongside. F1–F2 after D3 has a result worth shadowing.

## 4. Kite logins needed
| When | Purpose |
|---|---|
| Phase D | Sealed-slice intraday bars (≈ 1.5 h of requests on one token) |
| D4 | Final-test-slice intraday bars |
| Each trading day in F3+ | Live 5-minute collection for shadow/paper signals |
| After a new split/bonus in a studied symbol | Re-pull that symbol (Kite history is rewritten by adjustments) |

## 5. Owner decisions and inputs
| # | Decision |
|---|---|
| D1 | Split of the sealed period (recommended: validate 2021–22, final test 2023-01 → 2024-07) |
| D2 | Which hypotheses spend the validation slice (recommended: H-A and H-B; H-C optional) |
| D3 | Daily Kite login routine for live paper data (or EOD-only paper until decided); check Zerodha's terms before automating |
| D4 | Paper-trades page chart: keep Yahoo for that chart, remove it, or an authorised vendor (Kite data cannot be displayed) |
| D5 | Staging deploy free-space floor ≥ 5,000 MB and the nivesh-app-vm disk resize |
| D6 | Kite secret rotation (line 2 of `/app/.KITE.API.KEY`) and redirect URL → `/v5/kite-callback` |
| D7 | **Personal use vs sharing signals**: entry/stop/target for specific stocks shown to anyone other than the owner is SEBI research-analyst territory; Kite data may not be displayed to others |
| D8 | Maximum confirmed alerts per day (manual attention budget), used in backtests and paper tests |
| D9 | Entry Readiness Score: keep the owner weights as the registered baseline (recommended), with a fitted model as the challenger |

## 6. Risks
- **The surviving effect may be execution, not edge.** It concentrates in thin names; B3's cost model may erase it.
- **Survivorship in 2021–24** is larger than in 2024–26 (Kite lists today's names only); B4 may not be able to fix it.
- **Market-day clustering**: a few market-wide gap days can dominate; always resample whole days.
- **Single-use holdout**: every hypothesis spent on the sealed slices reduces what is left for later discoveries.
- **Two of the three owner-recommended families are data-blocked** (delivery hole, 8 months of announcements); fixing
  B6/B7 may take longer than the modelling itself.
- **The indicator families largely overlap the v5 features that already failed on net return**; only the increments
  (relative strength, 5-minute confirmation) are new evidence.
- **Operational**: the daily Kite login; the prod-shared app-vm disk (three prod-mongo incidents from staging deploys).
