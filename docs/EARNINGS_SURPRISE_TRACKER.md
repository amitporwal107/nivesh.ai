# Earnings Surprise & Guidance Tracker ("Results week"): spec, API contract, test cases

**Status:** Phase 1 IN PROGRESS (2026-10-27): backend on `feat/earnings-surprise-tracker`. Paper / research only. Nothing here places an order.
**Wording:** "ideas", "ordered for review", "vs historical trend". Never "picks", "recommended", "beat the Street" (SEBI; no
consensus is held).

## 0. Why (owner, 27 Oct 2026, IST)
From ~17:20 IST, in this order:
- ten stocks with strong Q2 results on 26 Oct (MANKIND, APLAPOLLO, SONACOMS, ATHERENERG, TATACONSUM, …) jumped on
  27 Oct; none was in the AI Scanner. Findings (staging, read-only):
  - the scanner's score is price-only (trend 25 %, structure 20 %, accumulation 20 %, momentum 15 %, sector 10 %, risk 10 %);
    no results, filings or OI input. 9 of the 10 were below their 50-day average before results;
  - most filed after the close on 26 Oct (17:54–20:59 IST); the move came on 27 Oct, after the 26 Oct scan;
  - our own filing analysis (Mongo `event_ai_analysis`) rated 8 of the 10 "moderately positive" by ~19:30 IST on 26 Oct,
    and the warehouse held their Q2 figures by ~20:32 IST: the evidence was there the night before; nothing used it;
  - the main scanner's Chartink step has no scans configured (0 hits ever). The owner's dashboard 247498 is imported in
    the desk's Chartink section (`desk_chartink_sources`) but runs only on a manual Refresh (20, 21, 27 Oct).
- "create a watchlist for this week's results … technical and fundamental analysis and OI build-up … rank them …
  early signals of positive movement … put it in our scanner".
- "a market update dashboard with this week's results … did they beat expectations or not".
- "also capture the core market data and macro events".
- the owner's framework: build an **Earnings Surprise + Management Guidance Tracker**, then validate whether its
  verdicts explain post-results stock performance; keep the verdict separate from any price prediction; where no reliable
  consensus exists show "Above / In line / Below **historical trend**".

## 1. Owner decisions
| When | Decision |
|---|---|
| 27 Oct (evening) | The ranked list goes on screen now, labelled **not yet tested**; a pre-registered validation runs alongside, and weights change only by its written rule. |
| 27 Oct (evening) | **Two lists:** F&O names (with OI and option chain) and all results names (technicals + fundamentals only). |
| 27 Oct (evening) | **Chartink dashboard 247498: confirmation column only.** Run its scans nightly; show which scans each stock hit; scores do not change. Fix the main scanner so Chartink hits are ADDED to its universe instead of replacing it. |
| 27 Oct (evening) | Build it as the Earnings Surprise + Guidance Tracker (framework above). |
| 27 Oct (evening) | Defaults taken (the owner rejected the question and asked to proceed): expectation = our **historical-trend baseline**; a consensus source is investigated separately. Placement = desk **Events tab** (dashboard) + **Scanner tab** (ranked list); both move with the desk redesign (`docs/desk_redesign_20261027/PLAN.md`: Market Desk › Market Intelligence and Market Overview › Top AI ideas). |

## 2. Phases
- **P1 (now):** surprise engine vs historical trend, operating trend, filing-analysis outlook, earnings-quality flags, market
  reaction vs Nifty, OI build-up, technicals, Chartink confirmation; the dashboard; the ranked lists; a nightly point-in-time
  snapshot; the validation study.
- **P2:** management guidance tracker: extract dated guidance statements from concall transcripts (2,231 parsed), investor
  presentations (2,293) and press releases (3,722) into an **append-only** store (statement, date, target period, revision,
  eventual outcome); raised / maintained / cut / delayed / withdrawn; a delivery record. Needs the owner's OK on model, cost
  and prompt. Replaces P1's outlook proxy.
- **P3:** analyst consensus captured **before** each announcement (source and licence to be confirmed; `nidp.earnings_estimates`
  is empty today). Adds the consensus verdict beside, never instead of, the historical-trend verdict.

## 3. Data map (all exist; checked on staging 27 Oct)
| Need | Source | Note |
|---|---|---|
| This week's results meetings, F&O flag, sector | DaaS `GET /v1/desk/events-calendar/expectations?from&to&universe=all` (≤ 3-day window) | 496 meetings 26–31 Oct; status declared / pending / upcoming |
| Baseline expectation + band, filed figure | same (`metrics[]`: revenue, pat, eps; `expected{low,mid,high}`, `filed`, `vs_mid_pct`, `within_band`, `reliable`) | PAT reliable for ~51 %; band = 10th–90th pct of measured errors, so ~80 % land "in band" by construction |
| Quarterly history (QoQ, YoY, EBITDA, margins, other income, exceptional items, tax) | DaaS `GET /v1/financials/{symbol}?period_type=quarterly` (`daas_client.get_quarterly_financials`) | 8 quarters (Dec 2024 on); cash flow empty on staging → "not checked" |
| Filing analysis (outlook proxy) | Mongo `event_ai_analysis` (`event_type` containing RESULT, case-insensitive: the model writes RESULTS, QUARTERLY RESULTS, RESULTS AND DIVIDEND, …; `mode` single_full or *_compact; tools off, isolated): `net_impact_score` −100..100, `net_band`, `confidence_score`, `materiality_score`, `analysis.sum` | covers a subset (32 results docs since 26 Oct) → missing = "not analysed", never neutral; a store that cannot be read is a gap, not "not analysed" |
| Past results reactions | DaaS `GET /v1/desk/events-calendar/history?symbol&type=RESULTS` | event_day / d1 / w1 % |
| Price reaction now | app DB `stock_ohlcv` (+ Nifty from DaaS index EOD) | after-close filings react next session |
| Futures OI build-up (all stocks, one date) | DaaS `GET /v1/desk/fno-buildup?date=` (used by `routes/fno.py`): total OI over every expiry, near-month price, cash close | F&O bhavcopy lands 22:15 IST |
| OI across the coming months (per F&O stock) | DaaS `GET /v1/fno/{symbol}?on=&instrument_type=STF` (futures, every expiry), `…&instrument_type=STO&expiry=` (one options expiry), `/v1/fno/{symbol}/expiries` | expiries are read from the data, never computed (November 2026's is 23 Nov) |
| Technicals | app DB `stock_technical_features` (AI scanner, nightly 19:45 IST) | |
| Chartink confirmation | Mongo `desk_chartink_hits` (the desk's Chartink section, `services/chartink_desk/*`) | per user; nightly refresh added in P1 |
| Market strip, macro | DaaS `/desk/sector-returns`, `/market-pulse/fii-dii`, index EOD, `/desk/macro-calendar` | existing; composed by the screen from the desk's existing routes, not part of `/api/desk/results-week` |

## 4. Scoring (P1). Every threshold is a provisional hypothesis; the validation study (§7) tests it.
Code: `backend/services/results_week/scoring.py` (pure functions; every constant named there with a comment).

### 4a. Earnings verdict "vs historical trend" (per declared result with figures)
Per metric m in {pat, revenue} with a reliable AND informative baseline: `z = (filed − mid) / (high − mid)` if filed ≥ mid,
else `(filed − mid) / (mid − low)`.
- **Too wide → not rated** (coordinator, 27 Oct; provisional): relative half-width `(high − low) / (2·mid)` above **0.35 for
  PAT** or **0.20 for revenue** → "not rated: baseline too uncertain" (e.g. BAJAJ-AUTO PAT 1848–3687–7200 = 0.73, ITCHOTELS
  PAT 110–172–281 = 0.50; ITCHOTELS revenue 894–978–1174 = 0.14 is rated). On staging 27 Oct no declared PAT band passed
  0.35, so verdicts rest on revenue where it is rated.
- metric verdict: `z > 1` above · `−1 ≤ z ≤ 1` in line · `z < −1` below; intensity `z ≥ 2` "outstanding", `z ≤ −2` "well below".
- component score `S = clamp(50 + 25·z, 0, 100)`; surprise score = 0.6·S_pat + 0.4·S_revenue over the RATED metrics (PAT only
  when revenue is not rated, e.g. banks; revenue only when PAT is not rated).
- **Headline verdict** = the same thresholds applied to the same weighted z (0.6·z_pat + 0.4·z_rev, or the one rated metric's z).
- Nothing rated → verdict `null` with the reason: "not rated: baseline too uncertain" when a band was too wide, else
  "not rated: no reliable baseline"; never "in line". Counted under `not_rated`. Figures pending → "not rated: figures pending
  (the outcome is filed; the figures are not in the stored results yet)", counted under `declared_pending`.

### 4b. Earnings Intelligence Score (0–100; owner framework weights, renormalised over the components present)
| Component | Weight | P1 source and rule |
|---|---|---|
| Surprise vs historical trend (framework: vs consensus) | 35 | §4a surprise score |
| Operating trend | 25 | the declared quarter (upcoming: the latest stored quarter): each YoY / QoQ growth g % of revenue, EBITDA, PAT scores clamp(50 + g); the EBITDA-margin change YoY (pp) scores clamp(50 + 10·pp); weights YoY 2, QoQ 1, margin 2. Growth off a non-positive base is not computed |
| Outlook | 25 | filing analysis `net_impact_score` → `(score + 100) / 2`, labelled "filing analysis, not a guidance tracker"; the most material analysis of the meeting known by the build (event_ts from the meeting − 1 day to + 4 days) |
| Earnings quality & risk flags | 15 | 100 − 25 per flag over the checks the stored figures allow: exceptional items > 20 % of PBT; other income > 30 % of PBT; tax rate < 10 % or > 40 % (PBT > 0); PAT growth > 2× revenue growth (PAT growing) with other income rising. A figure not stored → that check in `not_checked`; cash flow always "not checked" (not stored). No check possible → component missing |
`coverage` lists components present and missing; no surprise AND no trend → score `null`. Bands 70–100 above · 45–69 in line /
mixed · 0–44 below (provisional). The headline verdict is the §4a verdict; the composite is shown beside it. Declared rows only.

### 4c. Early-signal order (Scanner "Results week ideas"); labelled **not yet tested**
- **Declared** (figures stored, meeting in the last 3 sessions up to the date): earnings score (the §4b composite) 40 ·
  reaction 20 · OI build-up 20 · technical 20.
- **Upcoming** (meeting on the date or in the next 5 sessions): technical 40 · OI build-up 30 · past results reactions 15 ·
  operating trend 15.
- The look-back / look-ahead reach outside the week (extra DaaS windows); those meetings are ordered but not listed in
  `results` or `counts`. Pending results are not ordered (`left_out.pending`).
- Missing parts renormalise; a declared name needs its earnings score; any name needs parts carrying ≥ 50 % of its list's
  weight. On the filing evening (filed after the close) the reaction is missing, so a declared name is ordered on earnings /
  OI / technical renormalised to 50 / 25 / 25.
- Reaction part: first-session excess return vs Nifty (filed at or after 15:30 IST → the next session), close to close;
  score clamp(50 + 10·excess·w), w = volume × (first-session volume ÷ mean of up to 20 earlier sessions, ≥ 5 needed) clamped
  to [0.5, 2]. Technical part: the AI scanner's `final_score` × 100 (latest row within a week). Past results reactions: mean
  two-session move (event day compounded with the next) over the stock's past results, ≥ 2 occurrences, clamp(50 + 10·mean).
- OI part = §4e's headline `total.state`: long build-up 100 · short covering 75 (mildly positive) · no clear signal 50 · long
  unwinding 25 · short build-up 0. **Expiry week** (coordinator, 27 Oct): in the 5 sessions up to and including a monthly
  expiry (`EXPIRY_WINDOW_SESSIONS = 5`, expiry from the data), total futures OI falls routinely as contracts are closed rather
  than rolled, so short covering and long unwinding there score 50, keep their text and add "expiry week: open interest falls
  as contracts close" (26 Oct: IEX +2.2 % / OI −8.2 %, CDSL +0.6 % / −8.8 %, LODHA +1.8 % / −9.0 %). Rising-OI states keep
  their scores. The ranking rule (`ideas.rule`) says so.
- **All list:** no OI part; its weight is spread pro rata. **F&O list:** F&O names only. One entry per symbol (declared over
  upcoming, then the later meeting). Ties: higher earnings score, then symbol.
- Chartink hits are shown, never scored.

### 4d. Results signal in the AI scanner (owner, 27 Oct evening: "show extra strength signal for strong-results candidate stocks in the AI scanner")
Applied at READ time by `GET /api/positional/picks` and `/api/positional/watchlist` (code `services/results_week/signal.py`);
the engine's stored scores (`positional_signals`, `stock_technical_features`) stay purely technical. Each row gains
`results_signal` = `{strength: "strong"|"weak", points, basis: "figures"|"filing_analysis", reasons: [...], filed_at,
sessions_since}` or `null`, and `base_final_score`; `final_score` = clamp(base + points / 100, 0, 1), applied BEFORE each
route's sort, min_score filter and limit (the top rows by base score plus every signalled stock are read, adjusted, then
filtered, sorted and cut), so a boosted stock just outside the base top N can enter and a weak one can leave. Stage and
actionability are unchanged. Every merge that ranks by `final_score` (desk-data.ts mergeSetups, selection.merge_setups) uses
it unchanged; `selection.SELECTION_RULE` and `ideas.RANKING_NOTE` say "Strong results add up to +10 points, weak results
subtract up to 10; this adjustment has not been tested yet." Both responses carry `results_signal: {rule, tested: false,
signals, applied, gap, source}`.
- Window: a results meeting declared within the last 5 sessions; only filings broadcast before now. `sessions_since` counts
  from the FIRST REACTION SESSION (the §4c reaction rule: broadcast before 15:30 IST on a session day → that session = 0;
  after 15:30 or on a non-session day → the next session = 0). MANKIND, filed 20:59 IST on 26 Oct, gets +10 on 27 Oct, 8 on
  28 Oct, … 0 from the 5th session after 27 Oct.
- STRONG on figures (+10): the quarter's figures stored and ≥ 2 of: PAT YoY ≥ +20 % (loss → profit counts as met); revenue
  YoY ≥ +10 %; EBITDA margin YoY ≥ +50 bps; a rated §4a metric verdict "above" — and no red flag (exceptional items > 20 % of
  PBT, other income > 30 % of PBT), no rated below, and **PAT not down YoY** (any fall blocks "strong"; a loss turning into
  a profit is not a fall).
- STRONG on the filing analysis (+5, figures pending): `event_ai_analysis` results band moderately positive or better at
  confidence ≥ 75.
- WEAK (−10; −5 on the filing analysis): PAT YoY ≤ −10 % with revenue YoY < +5 %, or a rated verdict below / well below
  WITHOUT a strong PAT rise (PAT YoY ≥ +20 % or loss → profit), or (figures pending) band moderately negative or worse at
  confidence ≥ 75. Weak is checked first. A rated below together with a strong PAT rise is mixed: no adjustment.
- Decay: points × (1 − sessions_since / 5). Cached ≤ 10 min; bounded by 25 s; any source failure → no adjustment and a gap.
- Reasons are factual, from the data, e.g. "Q2 FY27 PAT +40.0 % YoY, revenue +17.3 %, EBITDA margin +207 bps (filed 26 Oct)",
  "Filing analysis: moderately positive, confidence 80 % (figures not filed yet)".
- Changed 27 Oct (coordinator, before merge) after the staging dry run showed "strong" on a profit fall (WESTLIFE PAT −107 %,
  MGEL −48 %, via revenue + margin) and "weak" on a profit jump (GAEL PAT +247 % with a rated revenue below): the PAT-not-down
  condition and the "below without a strong PAT rise" condition above. Still as designed: a red flag vetoes a strong quarter
  (ATHERENERG: loss → profit, revenue +63 %, margin +1552 bps, but other income ≈ 50× a barely positive PBT, so the profit
  rests on other income).

### 4e. OI build-up across the coming months (owner, 27 Oct evening), F&O names only
- `total` (headline): total futures OI across every expiry against the spot (cash close) over the last session (`*_1s`, the
  day's own change in DaaS `/desk/fno-buildup`) and 3 sessions (`*_3s`, vs that scan 3 sessions back) → state when |price| ≥
  0.5 % and |OI| ≥ 2 %, else "no clear signal" (never a state from the sign alone). This separates fresh positions from the
  roll: MANKIND 26 Oct total OI +9.60 % with spot +4.49 % reads long build-up while its expiring October contract lost 60 %.
- `by_expiry`: near / next / far futures, each price %, OI %, basis % vs spot, state (same thresholds).
- `rollover`: in the 5 sessions before a monthly expiry (and on expiry day): % of futures OI in later months and the
  next-month premium %, beside the same readings on the stock's own last 5 expiries at the same number of sessions before
  each (`past`, `past_range`, `position` below / within / above, `past_premium_range`, `premium_position`).
- `options_next_expiry`: the first expiry more than 7 calendar days after the date (a contract in its expiry week is
  distorted): PCR (put OI ÷ call OI) and its change vs the previous session (from the day's own OI minus its change), put and
  call OI added, the max put-OI and max call-OI strikes, the strikes with the most put / call OI added. Label: "open interest
  cannot tell buyers from writers".
- `scan`: the DaaS build-up row's own label, risk flags and turnover, for reference.

## 5. API contract (P1)
`GET /api/desk/results-week?date=YYYY-MM-DD` — signed in (401 otherwise). `date` omitted → today (IST), built live and cached
≤ 10 min; a build longer than 45 s answers with the previous build, or **503** `{code: "building", retry_after_s}` (header
Retry-After) before the first one. A past date answers from the stored snapshot, **404** `{code: "not_stored"}` when none. A
malformed or future date → **422** `{code: "invalid_date"}`. The results calendar failing entirely → **502**
`upstream_unavailable` (never an empty week); any other failing source nulls its block and is named in `gaps`.

**Contract change (coordinator, 27 Oct):** the market strip and the macro calendar are NOT in this response: the screen
composes them from the desk's existing routes and components.
```
{ "schema": "results-week-v1", "date", "as_of", "mode": "live|snapshot", "week": {"from","to"}, "basis": "historical_trend",
  "consensus_available": false, "label": "vs historical trend (the company's own past quarters), not analyst consensus",
  "counts": {"declared","declared_pending","upcoming","above","in_line","below","not_rated"}, "counts_partial": bool,
  "results": [ { "id", "symbol","name","sector","event_date",
      "status": "declared|pending|upcoming",     // declared = figures stored; pending = outcome filed, figures not stored yet
      "fno", "period_label", "basis": "consolidated|standalone" (the figures' reporting basis), "filed_at",
      "verdict": {"label": "above|in_line|below|null","intensity": "outstanding|well_below|null","reason"},
      "score": {"value": 0-100|null, "band": "above|in_line|below|null", "coverage": {"present":[],"missing":[]}, "weights"},
      "components": {
        "surprise": {"value", "used": [...], "weights", "z", "metrics": {"pat"|"revenue": {"filed","expected":{low,mid,high},
                     "vs_mid_pct","within_band","reliable","half_width","z","verdict","intensity","score","reason","unit","note"}}},
        "trend": {"value","quarter","yoy_pct":{revenue,ebitda,pat},"qoq_pct":{...},"ebitda_margin_pct","ebitda_margin_change_pp","missing","basis"},
        "outlook": {"value","label","analysed": true|false|null,"net_impact_score","net_band","confidence_score","materiality_score","summary","event_ts","analyzed_at","reason"},
        "quality": {"value","flags":[{code,text,value_pct}],"checked":[],"not_checked":[],"quarter"},
        "past_reactions": {"n","mean_two_session_pct","score","stats"} | null      // upcoming rows only
      },
      "reaction": {"filed_at","filed_after_close","first_session","previous_session","close","previous_close",
                   "stock_return_pct","nifty_return_pct","excess_pct","volume_x","score"} | null,
      "fno_buildup": {"as_of","state","text","signal","score","expiry_window","sessions_to_expiry","note",
                      "total": {"oi","price_basis","oi_chg_pct_1s","price_chg_pct_1s","state_1s","oi_chg_pct_3s","price_chg_pct_3s","state_3s","since_3s","state"},
                      "by_expiry": [{"leg": "near|next|far","expiry","close","price_chg_pct","oi","oi_chg_pct","basis_pct","state"}],
                      "rollover": {...§4e} | null, "options_next_expiry": {...§4e} | null, "scan": {...} | null} | null,   // F&O names only
      "technical": {"as_of","stage","final_score","score"} | null,
      "chartink": {"scans": [names], "scan_date"} | null,     // the signed-in user's hits on the date; [] = not hit; null = none stored
      "evidence": [ {"label","url"} ], "gaps": [] } ],
  "ideas": { "fno": [ {"rank","symbol","name","phase": "declared|upcoming","event_date","signal","parts": {name: {"value","weight"}},"missing","why"} ],
             "all": [ ... ], "note": "Ordered for review, not a prediction. This ordering has not been tested yet.",
             "tested": false, "weights", "left_out", "rule" },
  "rules": {...}, "sources": {...per source: source, ok, …; chartink: {connected, scan_date, symbols, note}}, "gaps": [ ... ], "read_only": true }
```
Scanner rows (`GET /api/positional/picks`, `/watchlist`): `results_signal` and `base_final_score` per row, `final_score`
adjusted (§4d); each response carries `results_signal: {rule, tested, signals, applied, gap, source}`.

Nightly job `scripts/build_results_week.py` (`--date`, `--dry-run`, `--skip-if-done`; `--symbols`, `--signals`, `--live` for
dry runs) stores the day in Mongo `results_week_days` (`_id` = date, insert-once; the per-user Chartink column is joined at read
time), after the F&O bhavcopy: cron 22:45 + 23:30 IST Mon–Fri (`deploy/nivesh-staging/results-week.cron`; installing it needs the
owner's go-ahead). Only the date itself is stored (point-in-time); its F&O build-up and stock prices must be the date's (exit
4 otherwise; a later run builds the day). The same job refreshes each imported desk Chartink source once
(`services/chartink_desk/refresh.refresh_all`). Exit codes: 0 stored / nothing to do / dry run; 1 failed or not today; 2 not a
session; 3 stored meanwhile; 4 inputs not loaded; 5 results calendar unreadable.
Main scanner: `services/positional_engine/pipeline.universe_for` returns the UNION of Chartink hits and every stock with
fresh bars (equity filter applied), never the hits alone.

## 6. Screens (P1)
- **Events tab › "Results week" view** (`data-testid="results-week"`): basis label; counts; market strip; macro this week;
  Declared table (verdict pill, PAT/revenue vs baseline mid %, YoY/QoQ, outlook band, quality flags, reaction vs Nifty,
  Chartink chips); Pending ("figures not filed yet"); Upcoming (date, expected range or "no reliable baseline", past
  reactions, OI state, stage). Row → drawer with components, evidence links, gaps.
- **Scanner tab › "Results week ideas"** beside the Top 10 (`data-testid="results-week-ideas"`): F&O | All toggle; rank,
  symbol, declared/upcoming, signal, parts, why; footer note.

## 7. Validation (pre-registered before any run; `docs/ai_research/EARNINGS_SURPRISE_PREREGISTRATION.md`)
Seasons with F&O and price history: Oct–Nov 2025, Jan–Feb 2026, Apr–May 2026, Jul–Aug 2026. Point-in-time: a figure is
known at its `broadcast_at`; the baseline uses only quarters known before the target filing.
- H1: "above trend" results have a higher mean first-session and 5-session excess return vs Nifty than "below trend".
- H2: the composite score's rank IC with 5-session excess return is > 0.
- H3: the pre-results early-signal order's rank IC with the post-results 5-session excess return is > 0.
Report every result, including nulls; weights change only by the registered rule.

## 8. Test cases (authored before implementation)
**Backend unit (pytest; fixtures labelled MOCK unless copied from staging with a date)**
- TC-B1 z and verdict at band edges (z = 1 in line, z = 1.01 above, z = −2 well below).
- TC-B2 unreliable / missing baseline → verdict null with the API's reason; never "in line".
- TC-B3 bank (revenue null) → PAT-only surprise; revenue-only when PAT unreliable.
- TC-B4 missing components renormalise; `coverage` names them; no surprise and no trend → score null.
- TC-B5 quality flags fire at their thresholds; cash flow listed as not checked.
- TC-B6 reaction: filed after 15:30 IST → first session is the next one; excess vs Nifty hand-checked.
- TC-B7 OI build-up: four states map correctly; non-F&O → null.
- TC-B8 ideas: F&O list holds only F&O names; All list has no OI part; deterministic ties; the note is present.
- TC-B9 wording: no "beat the Street", "recommend", "pick" anywhere in the response; label says historical trend.
- TC-B10 route: 401 without a session; 422 on a bad date.
- TC-B11 job: `--dry-run` writes nothing; `--skip-if-done` is a no-op; a stored day is never rewritten.
- TC-B12 `universe_for`: Chartink hits + bars → union (filtered); no hits → bars (unchanged behaviour).
- TC-B13 a failed source (DaaS 5xx, Mongo error) → that block null with a gap; the rest still answers.
- TC-B14 a baseline band wider than 0.35 (PAT) / 0.20 (revenue) relative half-width → "not rated: baseline too uncertain"; the verdict uses the rated metric; none rated → null, counted under not_rated (BAJAJ-AUTO / ITCHOTELS bands copied from staging).
- TC-B15 results signal (§4d): thresholds at their edges; loss → profit; decay from the first reaction session (after-close filing → next session = 0); figures-pending path; weak path; red-flag veto; routes order by the adjusted final_score; the adjustment is applied before the limit (base rank 31 + 10 enters the top 30); a failed source → no adjustment + gap.
- TC-B16 OI across the coming months (§4e): the four states and their thresholds; total OI vs the near month on the roll (MANKIND 26 Oct); rollover vs the stock's past expiries; options PCR and its change; non-F&O → null.
- TC-B17 expiry week: a short-covering day 2 sessions before expiry scores 50 with the note; 8 sessions before, 75.

**Staging (real API + data test)**
- TC-S1 `GET /api/desk/results-week?date=2026-10-27` 200; counts agree with DaaS expectations for the same windows.
- TC-S2 data test: MANKIND, APLAPOLLO, SONACOMS YoY PAT growth equals a hand calculation from
  `nidp.nse_financials_quarterly`.
- TC-S4 data test: total OI and spot on 26 Oct (MANKIND +9.6 % / +4.47 %, APLAPOLLO +2.7 % / +2.18 %, SONACOMS −1.2 % / +3.86 %), rollover and Nov PCR match the coordinator's warehouse query.
- TC-S3 401 without a session.

**Frontend (Playwright: mocked API for layout, one real staging smoke)**
- TC-F1 Events › Results week shows the basis label and counts.
- TC-F2 a declared row shows its verdict pill, PAT surprise and reaction; a pending row says figures are not filed yet.
- TC-F3 an upcoming row shows the expected range, or "no reliable baseline".
- TC-F4 Scanner shows Results week ideas with the F&O | All toggle and the "not yet tested" note.
- TC-F5 loading, empty and error states.
- TC-F6 390 px width: no horizontal page scroll.
