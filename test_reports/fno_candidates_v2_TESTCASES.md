# F&O candidates v2: three separate scores, explicit coverage, research gate (2026-10-23): test cases, authored before implementation

Decisions (user, 2026-10-23, answering docs/FO_SMART_MONEY_PRD_GAP_ANALYSIS.md section 7):
- Candidate screen and the threshold research job are built in parallel; the research report is the release gate for any
  live-ranked claim. Every unvalidated setting is labelled with its status: `research_setting_not_validated`,
  `research_result`, `validated` or `insufficient_evidence`, with experiment id, data window and last-updated time.
- Three independent scores: Signal Strength, Tradeability, Strategy Quality. Stock Signal Strength weights (research settings,
  not validated): futures OI 30, futures price behaviour 20, volume / relative volume 15, options-chain confirmation 15,
  cash-market and delivery context 10, technical structure 10.
- Missing input: NEVER renormalise. The score keeps the 100-point denominator, the missing input and its weight are shown,
  `coverage` says how much weight was available (e.g. 0.85), the score is `incomplete`, and a configurable minimum coverage
  is required before a candidate is ranked or published.
- Fundamentals leave the score and become a separate Fundamental Quality / Risk Context panel.
- The NIFTY and BANKNIFTY view becomes two independent workspaces (selector), index-agnostic API.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | engine | Signal Strength weights are exactly 30/20/15/15/10/10 and sum to 100; read from `rules` | unit | weights |
| TC-2 | engine | all six inputs known: score is the weighted points out of 100, coverage 1.0, complete true | unit | worked example |
| TC-3 | engine | options-chain confirmation is unavailable for stocks: coverage 0.85, `incomplete`, the missing input and its 15 points are listed, score keeps the 100 denominator and is NOT scaled up | unit | score, coverage |
| TC-4 | engine | a second missing input lowers coverage further and the score never rises because an input went missing | unit | monotonic |
| TC-5 | engine | minimum coverage: a candidate below it is not ranked, is listed under `unranked` with its missing inputs, and counted in `excluded.insufficient_coverage` | unit | unranked |
| TC-6 | engine | tradeability is its own score with its own weights and coverage (liquidity, expiry distance, spread/depth unavailable); a thin-but-strong signal shows high strength and low tradeability, not one blended number | unit | two scores differ |
| TC-7 | engine | strategy quality is `unavailable` with reasons (no cost model or probability method yet), never a number | unit | state |
| TC-8 | engine | fundamentals are not an input of any score; they appear as `fundamental_context`; changing fundamentals alone changes no score | unit | scores equal |
| TC-9 | engine | ranking is by Signal Strength points then |OI change|, among candidates that meet the coverage gate; per limits the list | unit | order |
| TC-10 | engine | relative volume is cash volume over its 20-day average, scored 0 at 1.0x and 100 at 2.0x; absent inputs make it unknown, not 0 | unit | scores |
| TC-11 | engine | the response carries the research status block (status, threshold version, experiment id null until a report exists, data window, last updated) and every threshold is labelled research_setting_not_validated | unit | block |
| TC-12 | engine | entry viability and signal_state (candidate / confirmed / invalidated / unavailable) still work and are not part of any score | unit | states |
| TC-13 | api | route 200 with v2 shape; features unreachable degrades with lower coverage (candidates unranked, said plainly); 502 / 401 / 422 as before | api | shape |
| TC-14 | research | pure functions: regime labels, near-month contract choice, forward outcomes by horizon, cost application, time split, grid enumeration, baseline | unit | worked examples |
| TC-15 | research | the report is reproducible: same input rows and config give an identical report hash; every tested configuration is recorded; no configuration reads data after its decision day | unit | hash, count, no look-ahead |
| TC-16 | research | verdict logic: `validated` needs positive net out-of-sample expectancy and enough samples; too few samples is `insufficient_evidence`; never `validated` from in-sample alone | unit | verdict |
| TC-17 | research | a real run on the staging warehouse (read-only) produces a report with the honest verdict | real data | report |
| TC-18 | e2e | the candidate section shows three score bars per card with coverage and an incomplete marker, the research status chip with experiment id and window, and never a single blended score | e2e | cards |
| TC-19 | e2e | NIFTY / BANKNIFTY selector loads independent analysis per index; limitations (no historical constituents, intraday OI unavailable) are shown | e2e | workspace |
