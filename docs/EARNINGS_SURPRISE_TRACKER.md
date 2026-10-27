# Earnings Surprise & Guidance Tracker ("Results week"): spec, API contract, test cases

**Status:** Phase 1 IN PROGRESS (2026-10-27). Paper / research only. Nothing here places an order.
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
| Filing analysis (outlook proxy) | Mongo `event_ai_analysis` (`event_type: RESULTS`, `mode: single_full`): `net_impact_score` −100..100, `net_band`, `confidence_score`, `materiality_score`, `analysis.sum` | covers a subset (32 results docs since 26 Oct) → missing = "not analysed", never neutral |
| Past results reactions | DaaS `GET /v1/desk/events-calendar/history?symbol&type=RESULTS` | event_day / d1 / w1 % |
| Price reaction now | app DB `stock_ohlcv` (+ Nifty from DaaS index EOD) | after-close filings react next session |
| Futures OI build-up (all stocks, one date) | DaaS `GET /v1/desk/fno-buildup?date=` (used by `routes/fno.py`) | F&O bhavcopy lands 22:15 IST |
| Technicals | app DB `stock_technical_features` (AI scanner, nightly 19:45 IST) | |
| Chartink confirmation | Mongo `desk_chartink_hits` (the desk's Chartink section, `services/chartink_desk/*`) | per user; nightly refresh added in P1 |
| Market strip, macro | DaaS `/desk/sector-returns`, `/market-pulse/fii-dii`, index EOD, `/desk/macro-calendar` | existing |

## 4. Scoring (P1). Every threshold is a provisional hypothesis; the validation study (§7) tests it.
### 4a. Earnings verdict "vs historical trend" (per declared result with figures)
Per metric m in {pat, revenue} with a reliable baseline: `z = (filed − mid) / (high − mid)` if filed ≥ mid, else
`(filed − mid) / (mid − low)`.
- metric verdict: `z > 1` above · `−1 ≤ z ≤ 1` in line · `z < −1` below; intensity `z ≥ 2` "outstanding", `z ≤ −2` "well below".
- component score `S = clamp(50 + 25·z, 0, 100)`; surprise score = 0.6·S_pat + 0.4·S_revenue (PAT only when revenue is
  null, e.g. banks; revenue only when PAT is unreliable).
- No reliable baseline → verdict `null` with the API's reason ("not rated: no reliable baseline").

### 4b. Earnings Intelligence Score (0–100; owner framework weights, renormalised over the components present)
| Component | Weight | P1 source |
|---|---|---|
| Surprise vs historical trend (framework: vs consensus) | 35 | §4a |
| Operating trend: YoY & QoQ revenue, EBITDA, PAT growth; EBITDA-margin change | 25 | quarterly history |
| Outlook | 25 | P1: filing analysis `net_impact_score` → `(score + 100) / 2`, labelled "filing analysis, not a guidance tracker" |
| Earnings quality & risk flags | 15 | 100 minus flags: exceptional items > 20 % of PBT; other income > 30 % of PBT; tax rate < 10 % or > 40 % with PBT > 0; PAT growth > 2× revenue growth with other income rising; cash flow "not checked" |
`coverage` lists components present and missing. Bands 70–100 above · 45–69 in line / mixed · 0–44 below (provisional).
The headline verdict is the §4a verdict; the composite is shown beside it.

### 4c. Early-signal order (Scanner "Results week ideas"); labelled **not yet tested**
- **Declared** (filed in the last 3 sessions): earnings score 40 · reaction 20 (excess return vs Nifty on the first session,
  volume ×) · OI build-up 20 (long build-up / short covering positive; short build-up / long unwinding negative) · technical 20.
- **Upcoming** (meeting in the next 5 sessions): technical 40 · OI build-up 30 · past results reactions 15 · operating trend 15.
- **All list:** no OI; its weight is spread pro rata. **F&O list:** F&O names only. Ties: higher earnings score, then symbol.
- Chartink hits are shown, never scored.

## 5. API contract (P1)
`GET /api/desk/results-week?date=YYYY-MM-DD` (signed-in; 401 otherwise; default today IST; past dates answer from the
stored snapshot, today is built live and cached ≤ 10 min)
```
{ "date", "as_of", "week": {"from","to"}, "basis": "historical_trend", "consensus_available": false,
  "label": "vs historical trend (the company's own past quarters), not analyst consensus",
  "counts": {"declared","declared_pending","upcoming","above","in_line","below","not_rated"},
  "market": {...strip...} | null, "macro": [ ... ] ,
  "results": [ { "symbol","name","sector","event_date","status","fno","period_label","basis",
      "verdict": {"label": "above|in_line|below|null","intensity": "outstanding|well_below|null","reason"},
      "score": {"value": 0-100|null, "band": "above|in_line|below|null", "coverage": {"present":[],"missing":[]}},
      "components": { "surprise": {...metrics with filed, expected, vs_mid_pct, z, verdict}, "trend": {...}, "outlook": {...}, "quality": {"flags":[],"not_checked":[]} },
      "reaction": {...} | null, "fno_buildup": {...} | null, "technical": {...} | null, "chartink": {"scans": [], "scan_date"} | null,
      "evidence": [ {"label","url"} ], "gaps": [] } ],
  "ideas": { "fno": [ {"rank","symbol","phase","signal","parts","why"} ], "all": [ ... ],
             "note": "Ordered for review, not a prediction. This ordering has not been tested yet." },
  "sources": {...}, "gaps": [ ... ] }
```
Nightly job `scripts/build_results_week.py` (`--date`, `--dry-run`, `--skip-if-done`) stores the day in Mongo
`results_week_days` (`_id` = date, insert-once), after the F&O bhavcopy: cron 22:45 + 23:30 IST (installing it needs the
owner's go-ahead). The same job refreshes each imported desk Chartink source once (reusing `services/chartink_desk/refresh`).
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

**Staging (real API + data test)**
- TC-S1 `GET /api/desk/results-week?date=2026-10-27` 200; counts agree with DaaS expectations for the same windows.
- TC-S2 data test: MANKIND, APLAPOLLO, SONACOMS YoY PAT growth equals a hand calculation from
  `nidp.nse_financials_quarterly`.
- TC-S3 401 without a session.

**Frontend (Playwright: mocked API for layout, one real staging smoke)**
- TC-F1 Events › Results week shows the basis label and counts.
- TC-F2 a declared row shows its verdict pill, PAT surprise and reaction; a pending row says figures are not filed yet.
- TC-F3 an upcoming row shows the expected range, or "no reliable baseline".
- TC-F4 Scanner shows Results week ideas with the F&O | All toggle and the "not yet tested" note.
- TC-F5 loading, empty and error states.
- TC-F6 390 px width: no horizontal page scroll.
