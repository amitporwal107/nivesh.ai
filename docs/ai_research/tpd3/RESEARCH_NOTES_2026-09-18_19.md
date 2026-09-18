# Ten-Percent Days — research notes, 2026-09-18 to 2026-09-19

A single record of every analysis run in this working session: what was tested, the numbers, what was later found
to be wrong, and what is still open. Detailed evidence lives in the linked documents; this note is the index and the
honest summary.

**Status legend:** ✅ valid · ⚠️ valid with caveats · ❌ failed test · 🚫 retracted (the analysis itself was wrong) · ⏳ pending

---

## 1. Headline conclusions

Every result here is judged against the owner's success criteria (`pattern_engine/SUCCESS_CRITERIA.md`): no pattern is a
validated trading model without no-look-ahead simulation and positive out-of-sample net expectancy after costs.


1. **Our models predict movement, not profit.** Across every study, features that raise the chance of a big move do not
   raise the net return after costs. The Phase 1 base rates show it in one table: the chance of a +5% intraday move
   rises 40-fold from the calmest to the most volatile stocks, while the net open-to-close return stays flat (~−0.44%)
   and is worst in the most volatile bucket (−0.74%).
2. **The only consistently positive result is buying real gap-downs of 3% or more at the open and selling at the close
   (G1 close-only): +0.8909% per session, t 5.80, positive in 2024, 2025 and 2026.** This is on the heavily explored
   2024–26 data. It has not yet been tested on the untouched 2021–24 period, and the pre-registered target/stop version
   is still being run.
3. **Three data errors were found tonight, each of which had produced a confident wrong answer** (section 7). The rules
   they led to now apply to all future work.

---

## 2. Data sources (as established)

| Source | Use | Key facts |
|---|---|---|
| **NSE bhavcopy** (NIDP archives) | Official open/close; the research panel | `NSE_SEC_BHAVDATA` 2024-05-31..2024-12-31, `NSE_BHAVCOPY` 2025-01-01+. Raw (unadjusted) prices. |
| **Kite Connect** (Zerodha, app `nivesh`, user WVX837) | Intraday path, adjusted daily history | Not IP-blocked from nidp-stack-vm. Minute bars ≥ 5 years back. Historical data included in the Rs 500/month plan. Daily token needs the owner's login (~06:00 IST expiry). |
| **Yahoo Finance** | **Dropped** (owner, 2026-09-18) | 5-minute history hard-capped at 60 days (HTTP 422 beyond). Still used by the paper-trades page's live chart — owner decision pending (section 8). |
| **NSE APIs** | Not usable from this VM | 403 even with session cookies through the proxy. |
| **NIDP intraday tables** | None existed | Verified by schema inspection before building the Kite collector. |

**Kite data rules (verified):**
- Candles are **back-adjusted for splits, bonuses and dividends**. Evidence: raw/Kite = 2.000 (TDPOWERSYS split 2:1),
  1.500 (TRENT bonus 1:2), 3.000 (GOODLUCK bonus 2:1); dividend payers show the same factor 1.002–1.05 on open and close
  (COALINDIA ×1.027). → **Returns from Kite; rupee levels (pivots, circuit bands, price filters) from raw bhavcopy.**
- Kite's last minute candle is the last traded minute, not the 15:30–15:40 closing auction (RELIANCE 2026-09-17: 1245.0
  vs official 1243.9). Kite's **daily** close does match the official close (scaled). → Official close from bhavcopy or
  Kite daily, never from the last minute bar.
- The instrument list holds only names trading today: 153 of 1,647 (9.3%) 2024–26 gap-down symbols are missing.
- **Display restriction (owner-cited Zerodha policy):** Kite data may not be shown on other platforms. Internal research
  only; anything user-facing needs an exchange-authorised vendor.

**Data now held (all on nidp-stack-vm's own disk, not the prod-shared app-vm):**
- `/app/research/kite_history/day_2021/` — daily candles 2021-01-01 → 2026-09-18, 2,895 symbols, 2,916,948 rows.
  **2021-01..2024-07 is the reserved, untouched validation period.**
- `/app/research/kite_history/gapdown_minute_v2/` — minute bars for the correct gap-down sessions (⏳ in progress).
- `/app/research/kite_history/five_min_2024/` — 5-minute bars, top-800 liquid names, 2024-08 → (⏳ queued).
- `/app/research/tpd3_panel/` — durable copy of the research panel (see its README for the phantom-gap flaw).
- `nidp.intraday_bars` (nidp_staging) — 1,396,641 minute bars from the first backfill. **These are the sessions BEFORE
  each gap-down** (section 7); real data, wrong days for the study.

---

## 3. Paper Trade Simulation Engine v1 ✅

- Engine (branch `feat/paper-trade-engine`, local): entry at the next official open, 6-session tracking, P5/P10
  portfolios, modes EOD-1/3/5, FIXED, TARGET_STOP. 19 unit tests. Traps fixed: Python-bool `~`, numpy-2 scalar repr in
  COPY, `str(None)` in JSON, empty corporate-action guard.
- Page on `dev` (`/v5/research/paper-trades`) with intraday session charts; Playwright suite 10 tests.
- Cron `/etc/cron.d/tpd-paper` (21:40 / 23:40 weekdays). First counted forward session: **Monday 2026-09-21.**
- Replay finding: **no edge** — the v4 model ranks movement, not direction; the 8% stop cap set almost every stop,
  making reward:risk 0.625 by construction.

---

## 4. Model studies (discovery period 2024–26)

| Study | Result | Status |
|---|---|---|
| Single-feature lift table (177,534 stock-days) | Circuit lock 6.9× lift / −0.89% net; new 20-day high 4.1× / −0.80%; pivot breakout 2.5× / −0.54% | ❌ movement only |
| Intraday drift | Overnight gap positive in 25 of 26 months; intraday negative in 21 | ✅ structural |
| Overnight-entry variant | t 18.4 in names under Rs 10 lakh turnover, t 0.56 in liquid names — bid-ask bounce | ❌ artefact |
| **v5 net-return model** (pre-registered, walk-forward) | 63 sessions: FAIL. 511 sessions: **−0.1944%/session, CI [−0.4203, +0.0315]**. Selection edge +0.2128pp (t 2.31) is mostly beta 1.48; alpha +0.41%/session (t 4.58) | ❌ |
| Resistance headroom | I first read it backwards; above-resistance performed best (62.5% vs 57.3%) | ✅ corrected |
| Owner's gap-up challenge | Owner was right: of +5% closers, gap 1.35% vs intraday 6.78%; 72% moved ≥5% intraday alone; 26% opened flat/down | ✅ |
| High-ATR cohort (ATR ≥ 5%) | **−0.5627%/session, t −9.21**, n 136,431 | ❌ |
| Inverse-ATR sizing | −0.5627% → −0.5508% | ❌ |
| Skip gap-ups > +2% / +3% | −0.56% → −0.4665% / −0.5119% | ⚠️ less bad, still negative |
| Intraday limit exits (high-ATR) | hold −0.465%; +5% limit −0.424%; +3% limit −0.391%. Days touching +5%: avg high +7.78%, close +4.77% (39% given back) | ⚠️ less bad, still negative |
| Model deciles | Worst decile hit +5% more often (12.44%) than the best (10.94%) | ❌ volatility, not direction |
| Stops (−1/−2/−3%, target/stop combos) | All negative; losses gap through | ❌ |

**Per-session returns, 511-session panel (reported 2026-09-18):** 2024 (86 sessions) mean −0.068%, std 1.130%, max
+2.406% (7 Oct), min −3.566% (21 Oct), skew −0.87; 2025 (249) mean −0.036%, std 1.220%, max +4.613% (9 May),
min −4.212% (4 Apr), skew −0.32; 2026 (176) mean +0.039%, std 1.279%, max +4.892%, min −4.314%. Up-day/down-day size
ratio 1.48× in 2024 narrowing to 1.03× by 2026. A Thursday effect (−0.364% in 2025) was flagged as probable noise.

---

## 5. Gap-down sleeve (G1)

**Pre-registration** (`gapdown/PREREGISTRATION.md`, commit `ea040cd6`, 2026-09-18 16:36:42Z, before any result):
gap = next open / adjusted previous close − 1 ≤ −3%; 20-day turnover ≥ Rs 50 lakh; top 20 deepest per session; EOD
model rank NOT used; ATR budget rejects rather than caps; grid CONSERVATIVE +2/−1.5, **MODERATE +3/−2 (primary)**,
EXTENDED +5/−3, ATR-based 0.75/0.50×ATR; success = mean > 0 and lower CI > 0.

| Run | Result | Status |
|---|---|---|
| Grid run 1 (panel, no intraday low) | MODERATE +0.6573%, t 13.72 — target credited from the high, stop checked only at the close | 🚫 look-ahead |
| Grid run 2 (Kite minute lows) | MODERATE −0.6531%, t −13.28, "all four FAIL" | 🚫 **wrong session** — bars were the day before each gap |
| Close-only on panel gaps | +0.4735%/session, CI [+0.2229, +0.7240], t 3.70; 2024 flat | ⚠️ diluted by phantom gaps |
| **Close-only on Kite real gaps** | **+0.8909%/session, CI [+0.5899, +1.1919], t 5.80** (3,588 pairs, 477 sessions). 2024 +0.9019% (t 2.73), 2025 +1.0734% (t 4.38), 2026 +0.6420% (t 2.86). Turnover Rs 50L–5cr +1.6040% (t 7.33); > Rs 5cr +0.6970% (t 3.94) | ⚠️ strongest result; discovery period only |
| Grid on validated correct-session minute bars | — | ⏳ refetch finishing, then run |
| Timing study (when the low is set, stop-then-recover, fills below the stop) | First version invalid (wrong session + mixed adjusted/raw prices) | 🚫 → ⏳ rerun on validated bars |

**Concentration caveat:** five market-wide gap days hold 36% of gap-down rows (the session after 2025-04-04 alone:
1,303 stocks gapped ≤ −3%, mean +4.96%). Per stock-day +1.61% vs per session +0.39% (panel gaps). The real sample is
far smaller than the row count; tests must resample whole market days, and it may be an index effect.

---

## 6. Pattern Discovery Engine

**Phase 1 — base rates** (discovery only; `pattern_engine/PHASE1_BASE_RATES.md`), 767,241 stock-days, 2,382 symbols:
- P(next-day high ≥ +5% from open) **7.02%**, +10% 1.14%; P(5-session high ≥ +5%) 31.31%, +10% 10.65%.
- Net open→close **−0.445%**, open→5th close −0.480% — negative in every ATR, liquidity, breadth, year and sector bucket.
- Real-gap buckets (Kite, per session): gap < −3% **+0.794%**; −3..−1% +0.447%; flat −0.425%; +1..+3% −1.231%;
  gap > +3% **−1.791%**.
- Downside/direction (Kite-validated, 729,435 rows): P(day-1 low ≤ −3%) 19.01%, ≤ −5% 5.18%; 5-session ≤ −5% 32.37%,
  ≤ −10% 7.28%. **+5% before −3% within 5 sessions: 24.43%** (ambiguous same-day 0.81%, neither 23.54%). A driftless
  random walk gives 37.5% of decided cases; every ATR bucket is below it; real gap-downs are above it (52.82%).
- Sector data: `nidp.sector_master` is 61% UNKNOWN, and the unknowns are the most volatile names.

**Registry seed** (`pattern_engine/REGISTRY_SEED.md`): 17 hypothesis families already tested on 2024–26, failures
included. A single t ≈ 2 on this data is expected by chance.

**Model design decisions (owner proposal reviewed 2026-09-19):**
- Four separate targets: movement, direction, target-before-stop, expected net return. Judge models on the net return of
  their top bucket after costs, not AUC.
- Event studies resample whole market days. Logistic baseline first; `HistGradientBoosting` (installed) before LightGBM.
- Target-before-stop as a session-by-session multinomial (discrete-time competing risks) on scikit-learn; survival
  curves (lifelines Aalen–Johansen) for the timing questions.
- **Verified in library source:** scikit-survival 0.28.0's predictive models do not support competing risks (only a
  descriptive cumulative-incidence function); hmmlearn 0.3.3 `predict_proba` uses the backward pass → smoothed,
  look-ahead unless filtered forward-only.
- Libraries: statsmodels first; drop XGBoost (redundant, pulls a GPU library); SHAP only after an out-of-sample edge;
  Optuna trials counted as tests; reuse the paper engine's simulator instead of vectorbt/backtrader. **Research
  environment only**, not the product backend image.
- 1-day target-before-stop needs intraday bars → limited to the 800 names with 5-minute bars until a 2021–24 5-minute
  pull (≈ 2 hours on one login).

---

## 7. Data errors found tonight and the rules they produced

| Error | Effect | Rule |
|---|---|---|
| Backfill used `trade_day = as_of_date`; panel row t carries session t+1 | 1.4M minute bars were the pre-gap session; G1 "FAIL" and timing study invalid | Validate every bulk join on a shared field before computing anything |
| Research panel builds next-session prices by shifting each symbol's rows | **Phantom gaps**: 0.106% of all rows, but 11.5% of the G1 sleeve and 71% of its deepest decile (median panel gap −23.8%, real +0.1%) | Gaps and paths from Kite's adjusted daily series; audit the extreme decile before trusting an extreme-selection result |
| Kite adjusts for dividends as well as splits/bonuses | A "factor ≈ 1 or > 1.05" check wrongly rejected 31k valid rows | Join check = same raw/Kite factor on open and close (0.3%); minute 09:15 open = Kite daily open |
| Daily-pull filter dropped hyphenated stocks (BAJAJ-AUTO, NAM-INDIA; 7 total) | Missing large caps | Only 2-character suffixes mark non-EQ series; top-up queued |
| Process lookup matched my own shell wrapper | A chained pull started early and ran concurrently | Filter processes by name (`comm`), confirm the PID before waiting on or killing it |

---

## 8. Infrastructure work in this session

- **Kite collector** (`backend/nidp/services/kite_bars/`, migration 152 applied to nidp_staging, 12 unit tests),
  credentials read from `/app/.KITE.API.KEY` (never printed), daily token handshake CLI.
- **`/v5` query-string fix + `/v5/kite-callback` page** — verified on live staging (6/6 Playwright, redirect keeps
  `request_token`). Report: `test_reports/v5_kite_callback_redirect_20260919_0305.md`.
- 🔴 **Prod incident 2026-09-19 03:01–03:06 IST**: the `dev` push filled the prod-shared app-vm disk; prod mongo
  crash-looped (restarts 169 → 177). Recovered, 0 errors after restart, prod healthz 200. Cause and timeline in the report.
- **Disk guard cron** on nivesh-app-vm replaced: the old one never ran (a literal `%` truncated the line); the new one
  triggers below 1,500 MB free, every 15 minutes.
- HNSW index checked before deletion: it is used by document search → kept.

---

## 10. Reviews and decisions made together (owner ↔ Claude)

Chronological. "Outcome" records what was concluded or done, including where the owner corrected me.

| # | Topic | Owner's input | Outcome |
|---|---|---|---|
| 1 | Paper engine scope | Engine + full page; forward + labelled replay; ATR-based stop | Built as specified (section 3). |
| 2 | "Why did we miss today's top gainers?" | Top-gainers CSV | The movers declared themselves in the first 30–60 minutes; our end-of-day picks had not moved by 10:30. The first-hour tape is information the model has never seen. |
| 3 | Common indicators and events before +5%/+10% moves | Day/week/month/quarter analysis requested; Yahoo as fallback for gaps; add 1M/3M/1Y change, 20/50/200-DMA distance, RSI, delivery %, P/E, last-quarter YoY growth | Feature study (177,534 stock-days): features predict movement, not profit (section 4). |
| 4 | Redefine the model | Chose: net return after costs; backfill first; pre-register, then walk-forward | v5 pre-registered and tested: FAIL on 63 and 511 sessions. |
| 5 | Pivots, support/resistance, Fibonacci, Trendlyne indicators | "Every stock has pivot support and resistance — why not use it?" | Tested. I first misread resistance headroom; corrected (above-resistance performed best). Pivot breakout 2.5× lift but −0.54% net. Beta and pivot levels added as display columns. |
| 6 | Gap-up entry | "I do not agree that stocks open gap-up and you cannot enter… take a positional bet" | **Owner was right.** +5% closers gapped only 1.35% on average and made 6.78% intraday; 72% moved ≥5% intraday alone. My central claim was overturned. |
| 7 | Holding period and return threshold | Hold a week/fortnight/month; "+1.238% avg is too low — screen only stocks where average return exceeds 5%" | Longer holds and higher thresholds examined; no selection rule found that delivers a positive net return. |
| 8 | Intraday charts (POONAWALLA, ATGL) and TradingView | Offered a TradingView account for charts/indicators | **Declined on security grounds** (would breach TradingView's terms, risk the account, and put a password on a server). Built our own intraday session charts instead. |
| 9 | Historical data source | "We already have bhavcopy archives for the last few years" | **Owner was right.** I had queried only `NSE_BHAVCOPY` and missed `NSE_SEC_BHAVDATA`; the panel grew from 63 to 511 sessions. |
| 10 | Disk clean-up, compression, NFS | Delete old archives/images/temp files; compress; NFS access given | Space reclaimed; nightly then hourly prune cron installed. HNSW index checked before deleting — it is used, so kept. |
| 11 | Live charts with entry/exit/stop indicators | Chose: live signals with the evidence shown beside them; Yahoo 5-minute bars | Built on the paper-trades page. (Yahoo later dropped as a research source — row 16.) |
| 12 | Most profitable days 2024/2025 | Statistics requested | Section 4 per-session statistics. |
| 13 | How to improve selection, entry, exit and stop-loss | Open question | ATR cap, gap-down sleeve, first-hour features, intraday limit exits proposed — all tested on discovery data; only the gap-down sleeve was positive. |
| 14 | Trade execution framework | Two strategies (next-day portfolio + gap-down sleeve); reject candidates whose stop exceeds the risk budget; G1–G5 entry variants; target/stop grid; 10:30/11:30/14:30 exit matrix; database fields | Agreed. I argued the EOD rank should not be a gap-down selection input (opposing filters) — adopted in the pre-registration. G2–G5 blocked by Yahoo's 60-day cap at the time. |
| 15 | Priority order | 1 check NIDP tables, 2 validate intraday sources, 3 start the 5-minute collector, 4 build G1, 5 pre-register the grid; add `source_version` and auditable ingestion | Done in that order: no NIDP intraday tables; Yahoo capped; G1 and grid pre-registered (`ea040cd6`). |
| 16 | Source decision | "FORGET YAHOO" — connect Kite Connect | Kite collector built and verified; 5+ years of minute history; the 60-day blocker removed. |
| 17 | Kite login redirect | "No request token coming here" | Root cause: nginx `/v5` redirect dropped the query string. Fixed and verified on staging (the `dev` push caused the prod incident in section 8). |
| 18 | Response to the G1 "failure" | "This is a valuable failure… study the timing of adverse movement vs recovery before choosing a delay; compare against the unstopped baseline" | Agreed. **But that failure was later retracted (wrong session).** The timing study was re-scoped to validated bars; the design guidance stands. |
| 19 | Pattern Discovery Engine | Separate targets (movement, direction, target-before-stop, net); negative labels; five feature groups; supervised + clustering + event studies; registry schema; walk-forward; mixture of specialised models | Agreed. Phase 1 base rates and registry seed done (section 6). I flagged point-in-time gaps in fundamentals, the phantom-gap risk, and that 2024–26 is no longer out-of-sample. |
| 20 | Kite pricing, data and display policy | Rs 500/month includes historical; websocket gives ticks, not candles; Kite data cannot be displayed on other platforms | Corrected my "separate add-on" claim. For research, after-close historical pulls replace tick aggregation. Display restriction affects the paper-trades chart (decision pending). |
| 21 | Model combination | Event study + bootstrap, logistic, LightGBM, competing-risk survival, HMM, clustering, GARCH, walk-forward | Agreed on the four-target split. Changes: resample whole market days; fixed-horizon multinomial before survival; rule-based regime first; ATR/realised vol over per-stock GARCH; evaluate on net return, not AUC. |
| 22 | Python libraries | scikit-learn, LightGBM, XGBoost, scikit-survival, lifelines, statsmodels, PyMC, hmmlearn, arch, SHAP, Optuna, vectorbt | Checked against the installed environment and library source (section 6). statsmodels first; XGBoost dropped; scikit-survival not used for competing risks; research environment only. |
| 23 | Success criteria for pattern models | Six dimensions (predictive, trading, statistical, stability, execution, operational); three-stage lifecycle; five production gates — no look-ahead, positive out-of-sample net expectancy, calibration, stability, transparent reporting | Recorded as standing policy: `pattern_engine/SUCCESS_CRITERIA.md`, with where each candidate stands. G1 close-only is a Stage 1 research candidate; gate 2 awaits the 2021–24 test. |

---

## 9. Open items and owner decisions

**Pending runs (automatic, tonight):** correct-session minute refetch → 165 extra real-gap pairs → 5-minute pull
(top 800) → 7-symbol daily top-up. Then: G1 pre-registered grid and timing study on validated bars.

**Owner decisions needed:**
1. Paper-trades page intraday chart: keep Yahoo for that one chart, remove it, or use an authorised vendor (Kite data
   cannot be displayed).
2. Raise the staging deploy workflows' free-space floor from 2,000 MB to ≥ 5,000 MB, and resize the nivesh-app-vm disk.
3. Kite API secret: replace line 2 of `/app/.KITE.API.KEY` after regenerating (not before the pulls finish).
4. Kite redirect URL → `https://staging.niveshcopilot.com:8443/v5/kite-callback`.

**Next research steps:** G1 grid + timing study on validated bars → gap-down event study with market-day resampling →
delayed-stop pre-registration → four labels with logistic baselines → one-shot test on 2021–24 → forward paper trading.
