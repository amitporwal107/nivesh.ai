# Functionality Verification Report — Copilot tools wired to the existing APIs (round 3)

- **Branch:** `feat/copilot-one-screen` (tip `58631505`, 20 commits ahead of `dev` as fetched on 2026-10-13)
- **Date:** 2026-10-13
- **Author:** Claude (full-stack developer + QA; ten screen groups were built by parallel workers and reviewed here)
- **Environment:** production build of `frontend-v5` with mocked APIs; unit tests in the staging backend image; route handlers and read-only GETs against the real staging data. Nothing in this round is deployed, so nothing was run in a browser on staging.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

The one-screen Copilot (`/v5/app`) had 21 screens, many with blocks marked "not connected". This round wires those blocks to APIs the product already has, mounts the original v5 pages where they already do the job (Risk, Goals, Tax, advisor workspace, strategy builder, paper-trade record, simulation lab), adds two thin backend routes over existing data (`POST /api/screeners/run`, `GET /api/fno/{symbol}/expiries|chain|futures`), puts a company / fund-house / broker icon beside every name, and gives the tool builder a template per tool and a data source pool. Brokers are read-only everywhere: portfolio and positions, never orders.

What is verified: the code builds and typechecks from a clean checkout, 247 browser tests and 233 backend tests pass, the two new route handlers return correct figures on the real staging data, and every response shape the screens parse was compared with a real staging GET. What is not: the deployed app. The branch is not merged, so the new routes have not been called over HTTP on staging and no screen of this round has been opened there. **Every write on these screens was tested only against mocks.**

The gaps — everything that could not be wired, and why — are in the last section.

## Test Cases

> One row per case. The cases for each screen group were written with its design, before or alongside the implementation, in the spec file named in the Area column. Result is from the clean-checkout run of `58631505` shown under "UI / Playwright Tests". "MOCK" in the Type column means the API was answered by a fixture with synthetic values in the real response shape.

| ID | Area (spec file) | Scenario and expected behaviour | Type | Result |
|----|------------------|---------------------------------|------|--------|
| BUILD-1 | whole frontend | `tsc -b` then `vite build` from a clean checkout of the branch tip | build | PASS |
| API-1 | `backend/tests/test_fno_routes.py` | F&O routes: summary maths (spot, ATM, put-call ratio, max pain, heaviest strikes, basis) worked by hand in the file; strike window; expiry filtering; 404 / 502 / 401 / 422 paths; real-data shapes (IDF / STF rows, the data platform's error envelope, lot size) — 64 cases | unit, edge, failure | PASS |
| API-2 | `backend/tests/test_screeners_run.py` | Screener run route: each condition and bucket, coverage counts, unreachable source, the P/E-vs-sector alias — 40 cases | unit, edge, failure | PASS |
| API-3 | `GET /api/fno/*` handlers | Run on the real staging F&O data: NIFTY, BANKNIFTY, RELIANCE, M&M and an unknown symbol | api (real data, handler called directly) | PASS |
| API-4 | `POST /api/screeners/run` handler | Run on the real staging feature store: five screens, with coverage | api (real data, handler called directly) | PASS |
| API-5 | both new routes | Called over HTTP on staging with a real session | api (staging) | NOT RUN — not deployed |
| REG-1 | `lite-copilot.spec.ts` | The older chat screens still render (4 cases) | e2e MOCK | PASS |
| LIVE-1 | `copilot-app-live.spec.ts` | Every screen of this round opened on the deployed app against the real backend | e2e (staging) | NOT RUN — not deployed |
| TC-01 | shell `copilot-app.spec.ts:127` | Copilot app — desktop — shell renders: rail, greeting, ask box | e2e MOCK | PASS |
| TC-02 | shell `copilot-app.spec.ts:146` | Copilot app — desktop — rail lists saved threads and opens one | e2e MOCK | PASS |
| TC-03 | shell `copilot-app.spec.ts:174` | Copilot app — desktop — market strip shows /api/markets/home values, and nothing when it is empty | e2e MOCK | PASS |
| TC-04 | shell `copilot-app.spec.ts:194` | Copilot app — desktop — 'for your portfolio today' cards: health, plan and ranked prompts, each from its endpoint | e2e MOCK | PASS |
| TC-04c | shell `copilot-app.spec.ts:229` | Copilot app — desktop — the cards appear together: none is shown, and none can be clicked, while a source is still loading | e2e MOCK | PASS |
| TC-04b | shell `copilot-app.spec.ts:254` | Copilot app — desktop — the statement bar shows the last CAS and offers Gmail sync and upload, as the dashboard does | e2e MOCK | PASS |
| TC-08b | shell `copilot-app.spec.ts:276` | Copilot app — desktop — a statement on file with no holdings rows yet is not shown as 'no portfolio' | e2e MOCK | PASS |
| TC-05 | shell `copilot-app.spec.ts:289` | Copilot app — desktop — asking a question streams an answer with class, tool steps and follow-ups | e2e MOCK | PASS |
| TC-06 | shell `copilot-app.spec.ts:330` | Copilot app — desktop — an error frame shows a partial-result banner with a working retry | e2e MOCK | PASS |
| TC-07 | shell `copilot-app.spec.ts:347` | Copilot app — desktop — a failed stream request shows an error and leaves the ask box usable | e2e MOCK | PASS |
| TC-07c | shell `copilot-app.spec.ts:362` | Copilot app — desktop — a thread that cannot be started says so, and Retry sends the question | e2e MOCK | PASS |
| TC-07b | shell `copilot-app.spec.ts:388` | Copilot app — desktop — stopping an answer in flight keeps the question and offers a retry | e2e MOCK | PASS |
| TC-08 | shell `copilot-app.spec.ts:412` | Copilot app — desktop — an account with no holdings gets the connect banner and no zero values | e2e MOCK | PASS |
| TC-09 | shell `copilot-app.spec.ts:432` | Copilot app — desktop — evidence panel: context on home, tools and sources in a thread, and the toggle | e2e MOCK | PASS |
| TC-10 | shell `copilot-app.spec.ts:471` | Copilot app — desktop — ask-box suggestions: ranked prompts, completions, keyboard | e2e MOCK | PASS |
| TC-11 | shell `copilot-app.spec.ts:500` | Copilot app — desktop — mode pill swaps the tools; Advisor only for an advisory workspace | e2e MOCK | PASS |
| TC-11b | shell `copilot-app.spec.ts:538` | Copilot app — desktop — while an advisor has a client open, every screen says whose data it is and offers the way back | e2e MOCK | PASS |
| TC-12 | shell `copilot-app.spec.ts:564` | Copilot app — desktop — internal pages are for admins only | e2e MOCK | PASS |
| TC-13 | shell `copilot-app.spec.ts:585` | Copilot app — desktop — a signed-out visitor is sent to login | e2e MOCK | PASS |
| SHELL-20 | shell `copilot-app.spec.ts:592` | Copilot app — desktop — a user who has not finished onboarding lands on the onboarding screen | e2e MOCK | PASS |
| SHELL-21 | shell `copilot-app.spec.ts:601` | Copilot app — desktop — an unknown view falls back to home | e2e MOCK | PASS |
| TC-14 | shell `copilot-app.spec.ts:625` | Copilot app — phone (390×844) — no rail; the menu opens a drawer that navigates and closes | e2e MOCK | PASS |
| TC-15 | shell `copilot-app.spec.ts:652` | Copilot app — phone (390×844) — evidence opens as a bottom sheet and closes | e2e MOCK | PASS |
| TC-16 | shell `copilot-app.spec.ts:668` | Copilot app — phone (390×844) — the ask flow works and the ask box stays on screen | e2e MOCK | PASS |
| TC-17 | screens `copilot-app-screens.spec.ts:85` | Copilot app screens — desktop — every rail destination renders | e2e MOCK | PASS |
| TC-18 | screens `copilot-app-screens.spec.ts:93` | Copilot app screens — desktop — with empty API responses no screen shows the design's sample data | e2e MOCK | PASS |
| TC-17 | screens `copilot-app-screens.spec.ts:114` | Copilot app screens — phone (390×844) — every destination renders without sideways page scroll | e2e MOCK | PASS |
| SCREENS-04 | screens `copilot-app-screens.spec.ts:165` | TC-19 screens show their endpoint's data — desktop — Portfolio analysis ← holdings, concentration, overlap, remediation, performance (the old AI Insights and Performance data) | e2e MOCK | PASS |
| SCREENS-05 | screens `copilot-app-screens.spec.ts:218` | TC-19 screens show their endpoint's data — desktop — Portfolio ledger ← holdings-enriched | e2e MOCK | PASS |
| SCREENS-06 | screens `copilot-app-screens.spec.ts:230` | TC-19 screens show their endpoint's data — desktop — Recommendations and Action plan ← plans/active | e2e MOCK | PASS |
| SCREENS-07 | screens `copilot-app-screens.spec.ts:248` | TC-19 screens show their endpoint's data — desktop — Markets ← markets/home, and a mover row asks the Copilot | e2e MOCK | PASS |
| SCREENS-08 | screens `copilot-app-screens.spec.ts:263` | TC-19 screens show their endpoint's data — desktop — Research ← instrument search + company financials | e2e MOCK | PASS |
| SCREENS-09 | screens `copilot-app-screens.spec.ts:283` | TC-19 screens show their endpoint's data — desktop — Screener ← saved screeners; Open in Copilot asks the compiled rule (in-page runs: copilot-app-screener.spec.ts) | e2e MOCK | PASS |
| SCREENS-10 | screens `copilot-app-screens.spec.ts:297` | TC-19 screens show their endpoint's data — desktop — Watchlist ← the research watchlist, watchlists from saved screens, and filing alerts | e2e MOCK | PASS |
| SCREENS-11 | screens `copilot-app-screens.spec.ts:346` | TC-19 screens show their endpoint's data — desktop — Saved ← screeners + chat sessions; a thread opens | e2e MOCK | PASS |
| SCREENS-12 | screens `copilot-app-screens.spec.ts:358` | TC-19 screens show their endpoint's data — desktop — Trader desk ← journal, scanner, watch levels, broker accounts, markets/home | e2e MOCK | PASS |
| SCREENS-13 | screens `copilot-app-screens.spec.ts:389` | TC-19 screens show their endpoint's data — desktop — Options lab: payoff is computed from typed legs; with no F&O answer the chain and open interest show an error, not numbers | e2e MOCK | PASS |
| SCREENS-14 | screens `copilot-app-screens.spec.ts:418` | TC-19 screens show their endpoint's data — desktop — Options lab ← /api/fno: end-of-day chain, open interest, lot size and prefilled legs | e2e MOCK | PASS |
| SCREENS-15 | screens `copilot-app-screens.spec.ts:468` | TC-19 screens show their endpoint's data — desktop — Trader desk F&O card ← /api/fno: futures basis, put-call ratio, max pain and open-interest levels | e2e MOCK | PASS |
| SCREENS-16 | screens `copilot-app-screens.spec.ts:485` | TC-19 screens show their endpoint's data — desktop — Paper trades ← paper-trades portfolio, evaluation, live | e2e MOCK | PASS |
| SCREENS-17 | screens `copilot-app-screens.spec.ts:513` | TC-19 screens show their endpoint's data — desktop — Advisor ← client book + SIP board; opening a client lands in the Copilot | e2e MOCK | PASS |
| SCREENS-18 | screens `copilot-app-screens.spec.ts:544` | TC-19 screens show their endpoint's data — desktop — Advisor screen explains itself to a non-advisor account | e2e MOCK | PASS |
| SCREENS-19 | screens `copilot-app-screens.spec.ts:549` | TC-19 screens show their endpoint's data — desktop — Internal pages ← feeds, audit trail, admin stats, routing agents | e2e MOCK | PASS |
| SCREENS-20 | screens `copilot-app-screens.spec.ts:591` | TC-19 screens show their endpoint's data — desktop — Tool builder: the contract is derived from what is typed; saving is declared missing | e2e MOCK | PASS |
| SCREENS-21 | screens `copilot-app-screens.spec.ts:607` | TC-19 screens show their endpoint's data — desktop — the engineering 'needs' list on a not-connected block is shown to admins only | e2e MOCK | PASS |
| SCREENS-22 | screens `copilot-app-screens.spec.ts:641` | TC-19 account screens — desktop — Onboarding: skipping records completion and lands on home for good | e2e MOCK | PASS |
| SCREENS-23 | screens `copilot-app-screens.spec.ts:656` | TC-19 account screens — desktop — Onboarding: if recording completion fails the user still gets out, and is told | e2e MOCK | PASS |
| SCREENS-24 | screens `copilot-app-screens.spec.ts:666` | TC-19 account screens — desktop — Onboarding: the four steps in order, showing what is on file, then finish | e2e MOCK | PASS |
| SCREENS-25 | screens `copilot-app-screens.spec.ts:689` | TC-19 account screens — desktop — Broker connections ← broker accounts, statement on file, Gmail, import log | e2e MOCK | PASS |
| SCREENS-26 | screens `copilot-app-screens.spec.ts:713` | TC-19 account screens — desktop — Settings ← profile, risk, goals; mode and theme take effect | e2e MOCK | PASS |
| PORTFOLIO-01 | portfolio `copilot-app-portfolio.spec.ts:99` | Portfolio analysis — target mix and icons — the asset-class tab sets what is held against the target for the risk category | e2e MOCK | PASS |
| PORTFOLIO-02 | portfolio `copilot-app-portfolio.spec.ts:135` | Portfolio analysis — target mix and icons — target mix: no risk profile, an unknown category and a failed request each say so | e2e MOCK | PASS |
| PORTFOLIO-03 | portfolio `copilot-app-portfolio.spec.ts:158` | Portfolio analysis — target mix and icons — company rows carry the company icon and fund rows the fund house icon | e2e MOCK | PASS |
| PORTFOLIO-04 | portfolio `copilot-app-portfolio.spec.ts:222` | Recommendations — the original page's figures, step status, rebuild — filter counts, badges, tax breakdown, deferral, confidence tier and icons ← plans/active | e2e MOCK | PASS |
| PORTFOLIO-05 | portfolio `copilot-app-portfolio.spec.ts:277` | Recommendations — the original page's figures, step status, rebuild — marking a step done asks first, sends the status the backend accepts, and the list updates | e2e MOCK | PASS |
| PORTFOLIO-06 | portfolio `copilot-app-portfolio.spec.ts:310` | Recommendations — the original page's figures, step status, rebuild — a status change that fails says so and leaves the step where it was | e2e MOCK | PASS |
| PORTFOLIO-07 | portfolio `copilot-app-portfolio.spec.ts:320` | Recommendations — the original page's figures, step status, rebuild — rebuild asks first, then posts the refresh; a failure is reported | e2e MOCK | PASS |
| PORTFOLIO-08 | portfolio `copilot-app-portfolio.spec.ts:347` | Action plan — board, track record, expected and observed — board, summary and track record ← plans/active and plans/history | e2e MOCK | PASS |
| PORTFOLIO-09 | portfolio `copilot-app-portfolio.spec.ts:379` | Action plan — board, track record, expected and observed — deciding a step is one click and sends IN_PROGRESS for that step | e2e MOCK | PASS |
| PORTFOLIO-10 | portfolio `copilot-app-portfolio.spec.ts:392` | Action plan — board, track record, expected and observed — expected and observed ← portfolio/trend, health-projection and the plan's own figures | e2e MOCK | PASS |
| PORTFOLIO-11 | portfolio `copilot-app-portfolio.spec.ts:429` | Action plan — board, track record, expected and observed — observed: one record, no record and a failed request each say so; a plan without figures says so | e2e MOCK | PASS |
| PORTFOLIO-12 | portfolio `copilot-app-portfolio.spec.ts:475` | Portfolio ledger — holdings, what is on record, corrections — holdings: icons, source, type filter, search and order ← holdings-enriched + holdings | e2e MOCK | PASS |
| PORTFOLIO-13 | portfolio `copilot-app-portfolio.spec.ts:528` | Portfolio ledger — holdings, what is on record, corrections — allocation by type, gainers and losers, statements, transactions and SIPs | e2e MOCK | PASS |
| PORTFOLIO-14 | portfolio `copilot-app-portfolio.spec.ts:569` | Portfolio ledger — holdings, what is on record, corrections — nothing on record: statements, transactions and SIPs each say so | e2e MOCK | PASS |
| PORTFOLIO-15 | portfolio `copilot-app-portfolio.spec.ts:586` | Portfolio ledger — holdings, what is on record, corrections — failed requests: each block reports its own failure and the holdings stay listed | e2e MOCK | PASS |
| PORTFOLIO-16 | portfolio `copilot-app-portfolio.spec.ts:601` | Portfolio ledger — holdings, what is on record, corrections — a correction is reviewed, saved with only the changed field, and the figures are read again | e2e MOCK | PASS |
| PORTFOLIO-17 | portfolio `copilot-app-portfolio.spec.ts:656` | Portfolio ledger — holdings, what is on record, corrections — a correction that fails says nothing was changed | e2e MOCK | PASS |
| PORTFOLIO-18 | portfolio `copilot-app-portfolio.spec.ts:683` | Portfolio screens — phone (390×844) — the new blocks fit without sideways page scroll | e2e MOCK | PASS |
| MARKETS-01 | markets `copilot-app-markets.spec.ts:223` | Markets → Market — shows every block of the overview response, with icons and the as-of the response carried | e2e MOCK | PASS |
| MARKETS-02 | markets `copilot-app-markets.spec.ts:291` | Markets → Market — market lists are read when first opened | e2e MOCK | PASS |
| MARKETS-03 | markets `copilot-app-markets.spec.ts:317` | Markets → Market — empty and error states | e2e MOCK | PASS |
| MARKETS-04 | markets `copilot-app-markets.spec.ts:347` | Markets → Market — a failed market-list read says so | e2e MOCK | PASS |
| MARKETS-05 | markets `copilot-app-markets.spec.ts:355` | Markets → Market — a non-admin is not shown the source remark or the engineering notes | e2e MOCK | PASS |
| MARKETS-06 | markets `copilot-app-markets.spec.ts:366` | Markets → Sector Analysis — the table shows the endpoint's figures; a row opens the sector's companies and commentary | e2e MOCK | PASS |
| MARKETS-07 | markets `copilot-app-markets.spec.ts:404` | Markets → Sector Analysis — empty and error states | e2e MOCK | PASS |
| MARKETS-08 | markets `copilot-app-markets.spec.ts:440` | Markets → Earnings Tracker — summary growth, quarter-on-quarter columns and the company drill-down | e2e MOCK | PASS |
| MARKETS-09 | markets `copilot-app-markets.spec.ts:477` | Markets → Earnings Tracker — your holdings: result dates from the calendar and this quarter's results, direct stocks only | e2e MOCK | PASS |
| MARKETS-10 | markets `copilot-app-markets.spec.ts:522` | Markets → Earnings Tracker — your holdings: a calendar that cannot be read is declared, after one request | e2e MOCK | PASS |
| MARKETS-11 | markets `copilot-app-markets.spec.ts:540` | Markets → Earnings Tracker — your holdings: empty and error states | e2e MOCK | PASS |
| MARKETS-12 | markets `copilot-app-markets.spec.ts:574` | Markets → Earnings Tracker — empty and error states of the tracker | e2e MOCK | PASS |
| MARKETS-13 | markets `copilot-app-markets.spec.ts:588` | Markets → FII / DII — daily and monthly flows, every session on request, and holdings ranked three ways | e2e MOCK | PASS |
| MARKETS-14 | markets `copilot-app-markets.spec.ts:626` | Markets → FII / DII — empty and error states | e2e MOCK | PASS |
| MARKETS-15 | markets `copilot-app-markets.spec.ts:644` | Markets → Corporate Actions — the calendar, its filters, and the actions on stocks held directly | e2e MOCK | PASS |
| MARKETS-16 | markets `copilot-app-markets.spec.ts:684` | Markets → Corporate Actions — a calendar longer than one response says what was not checked | e2e MOCK | PASS |
| MARKETS-17 | markets `copilot-app-markets.spec.ts:692` | Markets → Corporate Actions — empty and error states | e2e MOCK | PASS |
| MARKETS-18 | markets `copilot-app-markets.spec.ts:710` | Markets → Articles — each card names its company with an icon and its feed; search reaches the endpoint | e2e MOCK | PASS |
| MARKETS-19 | markets `copilot-app-markets.spec.ts:740` | Markets → Articles — error state | e2e MOCK | PASS |
| MARKETS-20 | markets `copilot-app-markets.spec.ts:749` | Markets → Daily Iris Update — the stored brief: the backend's label as sent, sectors, movers, announcements and its stated sources | e2e MOCK | PASS |
| MARKETS-21 | markets `copilot-app-markets.spec.ts:777` | Markets → Daily Iris Update — empty and error states | e2e MOCK | PASS |
| MARKETS-22 | markets `copilot-app-markets.spec.ts:792` | Filings feed (Research → Filings) — each row has its company icon; AI insights opens the generated read under the row | e2e MOCK | PASS |
| MARKETS-23 | markets `copilot-app-markets.spec.ts:832` | Filings feed (Research → Filings) — empty and error states | e2e MOCK | PASS |
| MARKETS-24 | markets `copilot-app-markets.spec.ts:846` | Markets — phone (390×844) — no tab makes the page scroll sideways, with every block populated | e2e MOCK | PASS |
| RESEARCH-01 | research `copilot-app-research.spec.ts:118` | Research — stock — header: the company icon sits beside the name; search rows carry icons too | e2e MOCK | PASS |
| RESEARCH-02 | research `copilot-app-research.spec.ts:132` | Research — stock — price block ← daily bars: last close, day change, 52-week range, 200-day average and the chart | e2e MOCK | PASS |
| RESEARCH-03 | research `copilot-app-research.spec.ts:159` | Research — stock — price block: under a year of sessions is not called a 52-week range, and the 200-day average is not available | e2e MOCK | PASS |
| RESEARCH-04 | research `copilot-app-research.spec.ts:173` | Research — stock — price block: empty, switched-off and error states | e2e MOCK | PASS |
| RESEARCH-05 | research `copilot-app-research.spec.ts:191` | Research — stock — key figures: a figure the data does not carry reads “Not available”, never a dash or 0 | e2e MOCK | PASS |
| RESEARCH-06 | research `copilot-app-research.spec.ts:207` | Research — stock — scores and technicals ← the Copilot's research card, and the market backdrop | e2e MOCK | PASS |
| RESEARCH-07 | research `copilot-app-research.spec.ts:229` | Research — stock — scores and technicals: empty, switched-off and error states | e2e MOCK | PASS |
| RESEARCH-08 | research `copilot-app-research.spec.ts:253` | Research — filings — a material filing names its company with the company icon | e2e MOCK | PASS |
| RESEARCH-09 | research `copilot-app-research.spec.ts:272` | Research — mutual fund — overview ← lookup, factsheet and data-platform figures; the fund house icon sits beside the name | e2e MOCK | PASS |
| RESEARCH-10 | research `copilot-app-research.spec.ts:314` | Research — mutual fund — holdings and managers ← the factsheet | e2e MOCK | PASS |
| RESEARCH-11 | research `copilot-app-research.spec.ts:337` | Research — mutual fund — a factsheet for another plan only is named as such | e2e MOCK | PASS |
| RESEARCH-12 | research `copilot-app-research.spec.ts:347` | Research — mutual fund — empty states: no factsheet collected, and no figures on the data platform | e2e MOCK | PASS |
| RESEARCH-13 | research `copilot-app-research.spec.ts:370` | Research — mutual fund — empty state: a scheme the data platform cannot match has no returns block | e2e MOCK | PASS |
| RESEARCH-14 | research `copilot-app-research.spec.ts:378` | Research — mutual fund — error states: each block reports its own failed read | e2e MOCK | PASS |
| RESEARCH-15 | research `copilot-app-research.spec.ts:407` | Research — phone (390×844) — the stock and fund pages fit the phone without sideways page scroll | e2e MOCK | PASS |
| RESEARCH-16 | research `copilot-app-research.spec.ts:437` | Research shots — desktop — stock and fund pages desktop | e2e MOCK | SKIPPED (screenshot capture only) |
| RESEARCH-17 | research `copilot-app-research.spec.ts:437` | Research shots — phone — stock and fund pages phone | e2e MOCK | SKIPPED (screenshot capture only) |
| SCREENER-01 | screener `copilot-app-screener.spec.ts:59` | Screener results — desktop — a run shows the matches on the page; Open in Copilot still hands the sentence over | e2e MOCK | PASS |
| SCREENER-02 | screener `copilot-app-screener.spec.ts:97` | Screener results — desktop — a rule on a metric with no data says so, and names the metric | e2e MOCK | PASS |
| SCREENER-03 | screener `copilot-app-screener.spec.ts:116` | Screener results — desktop — rules that are only too strict say that instead | e2e MOCK | PASS |
| SCREENER-04 | screener `copilot-app-screener.spec.ts:130` | Screener results — desktop — a size universe the data has no labels for is named too | e2e MOCK | PASS |
| SCREENER-05 | screener `copilot-app-screener.spec.ts:145` | Screener results — desktop — 200 {} is an error state with a retry that works | e2e MOCK | PASS |
| SCREENER-06 | screener `copilot-app-screener.spec.ts:171` | Screener results — desktop — error state: HTTP 500 | e2e MOCK | PASS |
| SCREENER-07 | screener `copilot-app-screener.spec.ts:171` | Screener results — desktop — error state: a count with no rows | e2e MOCK | PASS |
| SCREENER-08 | screener `copilot-app-screener.spec.ts:171` | Screener results — desktop — error state: a half-shaped answer | e2e MOCK | PASS |
| SCREENER-09 | screener `copilot-app-screener.spec.ts:171` | Screener results — desktop — error state: rows that disagree with the count | e2e MOCK | PASS |
| SCREENER-10 | screener `copilot-app-screener.spec.ts:171` | Screener results — desktop — error state: the source did not answer (ok:false) | e2e MOCK | PASS |
| SCREENER-11 | screener `copilot-app-screener.spec.ts:185` | Screener results — desktop — Run on a saved row uses the same path and leaves the Copilot alone | e2e MOCK | PASS |
| SCREENER-12 | screener `copilot-app-screener.spec.ts:201` | Screener results — desktop — a template fills the rules; running it posts those rules | e2e MOCK | PASS |
| SCREENER-13 | screener `copilot-app-screener.spec.ts:221` | Screener results — desktop — while the run is in flight the section says so; every press of Run asks again | e2e MOCK | PASS |
| SCREENER-14 | screener `copilot-app-screener.spec.ts:246` | Screener results — desktop — more matches than rows sent is said plainly | e2e MOCK | PASS |
| SCREENER-15 | screener `copilot-app-screener.spec.ts:257` | Screener results — desktop — the table's own Ask button reaches the Copilot | e2e MOCK | PASS |
| SCREENER-16 | screener `copilot-app-screener.spec.ts:297` | Screener results — the minimal mocks from the report — two rows, rule on P/E | e2e MOCK | PASS |
| SCREENER-17 | screener `copilot-app-screener.spec.ts:317` | Screener results — the minimal mocks from the report — rule on ROE, which has no data | e2e MOCK | PASS |
| SCREENER-18 | screener `copilot-app-screener.spec.ts:343` | Screener results — phone (390×844) — matches fit the phone without sideways page scroll | e2e MOCK | PASS |
| SCREENER-19 | screener `copilot-app-screener.spec.ts:356` | Screener results — phone (390×844) — the no-data explanation fits the phone | e2e MOCK | PASS |
| SCREENER-20 | screener `copilot-app-screener.spec.ts:381` | Screener — ready-made strategy screens — a ready-made screen runs in place and lists its candidates; a row asks the Copilot | e2e MOCK | PASS |
| SCREENER-21 | screener `copilot-app-screener.spec.ts:417` | Screener — ready-made strategy screens — templates or a run that answer 200 {} show an error with retry, not a crash | e2e MOCK | PASS |
| WORKSPACE-01 | workspace `copilot-app-workspace.spec.ts:95` | Watchlist — the research watchlist — every stock has its icon, place, confidence, earlier-list badge, and a live or a stored price | e2e MOCK | PASS |
| WORKSPACE-02 | workspace `copilot-app-workspace.spec.ts:132` | Watchlist — the research watchlist — the confidence filter and the sort work on the list that came back | e2e MOCK | PASS |
| WORKSPACE-03 | workspace `copilot-app-workspace.spec.ts:155` | Watchlist — the research watchlist — a stock opens to the research behind it: the numbers that came back, the latest quarter and the notes | e2e MOCK | PASS |
| WORKSPACE-04 | workspace `copilot-app-workspace.spec.ts:193` | Watchlist — the research watchlist — an earlier list is read from the same endpoint by date, and says its prices are today's | e2e MOCK | PASS |
| WORKSPACE-05 | workspace `copilot-app-workspace.spec.ts:221` | Watchlist — the research watchlist — empty and error states: nothing published, a failed load with a retry that works, and a body that is not a list | e2e MOCK | PASS |
| WORKSPACE-06 | workspace `copilot-app-workspace.spec.ts:247` | Watchlist — your screens as watchlists — both kinds are listed from their own endpoints; opening one runs it and draws each stock with its icon | e2e MOCK | PASS |
| WORKSPACE-07 | workspace `copilot-app-workspace.spec.ts:282` | Watchlist — your screens as watchlists — empty states: nothing saved at all, one kind only, and a screen nothing passes today | e2e MOCK | PASS |
| WORKSPACE-08 | workspace `copilot-app-workspace.spec.ts:310` | Watchlist — your screens as watchlists — error states: a list that fails, a list in the wrong shape, and a run that fails | e2e MOCK | PASS |
| WORKSPACE-09 | workspace `copilot-app-workspace.spec.ts:333` | Watchlist — your screens as watchlists — deleting a saved screen asks first, removes it when the delete succeeds, and says so when it fails | e2e MOCK | PASS |
| WORKSPACE-10 | workspace `copilot-app-workspace.spec.ts:381` | Watchlist — price levels and filing alerts — the scanner's levels are listed with each stock's icon; none, and a failed load, say so | e2e MOCK | PASS |
| WORKSPACE-11 | workspace `copilot-app-workspace.spec.ts:409` | Watchlist — price levels and filing alerts — filing alerts: a switch saves the choice and moves only after the save; a failed save changes nothing | e2e MOCK | PASS |
| WORKSPACE-12 | workspace `copilot-app-workspace.spec.ts:453` | Watchlist — price levels and filing alerts — filing alerts: no types to show, and a failed load | e2e MOCK | PASS |
| WORKSPACE-13 | workspace `copilot-app-workspace.spec.ts:491` | Screener — save as a watchlist — a rule screen that was run is saved with its rules, and then shows on the Watchlist | e2e MOCK | PASS |
| WORKSPACE-14 | workspace `copilot-app-workspace.spec.ts:518` | Screener — save as a watchlist — a failed save says so and keeps the form; saving again works | e2e MOCK | PASS |
| WORKSPACE-15 | workspace `copilot-app-workspace.spec.ts:539` | Screener — save as a watchlist — a run that started from a saved screen is already a watchlist, and says where | e2e MOCK | PASS |
| WORKSPACE-16 | workspace `copilot-app-workspace.spec.ts:553` | Screener — save as a watchlist — a ready-made screen draws an icon on every row, is saved as a strategy, and then shows on the Watchlist | e2e MOCK | PASS |
| WORKSPACE-17 | workspace `copilot-app-workspace.spec.ts:586` | Screener — save as a watchlist — a ready-made screen that is refused says why; one with no stocks today can still be kept | e2e MOCK | PASS |
| WORKSPACE-18 | workspace `copilot-app-workspace.spec.ts:616` | Saved — both kinds of saved screen, starred questions and threads come from their endpoints | e2e MOCK | PASS |
| WORKSPACE-19 | workspace `copilot-app-workspace.spec.ts:642` | Saved — the holdings file downloads under the server's file name; no holdings, and a failure, are said plainly | e2e MOCK | PASS |
| WORKSPACE-20 | workspace `copilot-app-workspace.spec.ts:677` | Saved — a star is removed only when the server confirms it; a thread is deleted after asking twice | e2e MOCK | PASS |
| WORKSPACE-21 | workspace `copilot-app-workspace.spec.ts:723` | Saved — empty and error states for each group | e2e MOCK | PASS |
| WORKSPACE-22 | workspace `copilot-app-workspace.spec.ts:756` | Workspace screens — phone (390×844) — Watchlist, Saved and the Screener's save forms fit the phone without sideways page scroll | e2e MOCK | PASS |
| TRADER-01 | trader `copilot-app-trader.spec.ts:126` | Trader desk — broker block — holdings a broker read stored are listed with quantity, average, last price, P&L and as-of time | e2e MOCK | PASS |
| TRADER-02 | trader `copilot-app-trader.spec.ts:180` | Trader desk — broker block — no broker account: says so, links to Broker connections, and does not fetch holdings | e2e MOCK | PASS |
| TRADER-03 | trader `copilot-app-trader.spec.ts:194` | Trader desk — broker block — account connected but nothing read yet: empty state names the broker | e2e MOCK | PASS |
| TRADER-04 | trader `copilot-app-trader.spec.ts:206` | Trader desk — broker block — broker connections fail: the block reports the error | e2e MOCK | PASS |
| TRADER-05 | trader `copilot-app-trader.spec.ts:215` | Trader desk — broker block — holdings fail or come back in the wrong shape: error, never an empty list | e2e MOCK | PASS |
| TRADER-06 | trader `copilot-app-trader.spec.ts:230` | Trader desk — broker block — journal, watch-level and scanner rows carry the company icon; risk limits stay declared missing | e2e MOCK | PASS |
| TRADER-07 | trader `copilot-app-trader.spec.ts:255` | Paper trades — summary rows carry the company icon; the full record mounts the engine's own screen | e2e MOCK | PASS |
| TRADER-08 | trader `copilot-app-trader.spec.ts:284` | Paper trades — simulation lab view: offered only to accounts with the feature, and mounts the original lab screen | e2e MOCK | PASS |
| TRADER-09 | trader `copilot-app-trader.spec.ts:302` | Paper trades — nothing recorded yet: empty states, no figures | e2e MOCK | PASS |
| TRADER-10 | trader `copilot-app-trader.spec.ts:317` | Paper trades — the engine is unreachable: both blocks report the error | e2e MOCK | PASS |
| TRADER-11 | trader `copilot-app-trader.spec.ts:329` | Paper trades — an account without access sees only that | e2e MOCK | PASS |
| TRADER-12 | trader `copilot-app-trader.spec.ts:346` | Trader desk and Paper trades — phone (390×844) — the desk with broker holdings does not scroll sideways; the table scrolls inside itself | e2e MOCK | PASS |
| TRADER-13 | trader `copilot-app-trader.spec.ts:362` | Trader desk and Paper trades — phone (390×844) — paper trades, summary and full record, do not scroll sideways | e2e MOCK | PASS |
| TRADER-14 | trader `copilot-app-trader.spec.ts:392` | Strategy builder mounted in the shell — the original strategy builder renders inside the shell with its templates and universes | e2e MOCK | PASS |
| AD-01 | advisor `copilot-app-advisor.spec.ts:126` | Advisor · Client book — book figures, both ways into a client, and the two not-connected blocks | e2e MOCK | PASS |
| AD-02 | advisor `copilot-app-advisor.spec.ts:163` | Advisor · Client book — an admin sees what each not-connected block needs | e2e MOCK | PASS |
| AD-03 | advisor `copilot-app-advisor.spec.ts:170` | Advisor · Client book — a book with no clients: the way to add one stays inside the shell | e2e MOCK | PASS |
| AD-04 | advisor `copilot-app-advisor.spec.ts:191` | Advisor · Client book — the SIP tile prints no figure when its request fails or is not a SIP summary | e2e MOCK | PASS |
| AD-05 | advisor `copilot-app-advisor.spec.ts:213` | Advisor · Client book — an account that is not an advisor is told so, and is offered the workspace inside the shell | e2e MOCK | PASS |
| AD-06 | advisor `copilot-app-advisor.spec.ts:233` | Advisor · Client 360 — shows the chosen client's data in every block, with fund house and company icons | e2e MOCK | PASS |
| AD-07 | advisor `copilot-app-advisor.spec.ts:339` | Advisor · Client 360 — with no client named in the address, the first client in the book is shown | e2e MOCK | PASS |
| AD-08 | advisor `copilot-app-advisor.spec.ts:348` | Advisor · Client 360 — a client with nothing on file: every block has its own empty state | e2e MOCK | PASS |
| AD-09 | advisor `copilot-app-advisor.spec.ts:365` | Advisor · Client 360 — holdings without purchase dates: no short/long split and no tax figure are made up | e2e MOCK | PASS |
| AD-10 | advisor `copilot-app-advisor.spec.ts:386` | Advisor · Client 360 — each block says when its request failed; the page and the other blocks stay | e2e MOCK | PASS |
| AD-11 | advisor `copilot-app-advisor.spec.ts:423` | Advisor · Client 360 — an address that names someone outside the book says so and offers the book's clients | e2e MOCK | PASS |
| AD-12 | advisor `copilot-app-advisor.spec.ts:433` | Advisor · Client 360 — Open in Copilot switches to the client and stays in the shell | e2e MOCK | PASS |
| AD-13 | advisor `copilot-app-advisor.spec.ts:453` | Advisor · Client 360 — the action plan button opens the client on the shell's plan screen | e2e MOCK | PASS |
| AD-14 | advisor `copilot-app-advisor.spec.ts:463` | Advisor · Client 360 — holdings download: the file is saved; a client with no holdings is told so | e2e MOCK | PASS |
| AD-15 | advisor `copilot-app-advisor.spec.ts:486` | Advisor · Client 360 — the review prompt goes to the Copilot with the client's name | e2e MOCK | PASS |
| AD-16 | advisor `copilot-app-advisor.spec.ts:502` | Advisor · workspace (original page) — opening a client from the original page lands on shell screens, never the original app | e2e MOCK | PASS |
| AD-17 | advisor `copilot-app-advisor.spec.ts:533` | Advisor · workspace (original page) — the add-client dialog is the original one | e2e MOCK | PASS |
| AD-18 | advisor `copilot-app-advisor.spec.ts:553` | Advisor · SIP board — tiles and the four queues show the board's data; a row opens that client's 360 | e2e MOCK | PASS |
| AD-19 | advisor `copilot-app-advisor.spec.ts:587` | Advisor · SIP board — an empty board says nothing is recorded; a failed or malformed answer is an error, not an empty board | e2e MOCK | PASS |
| AD-20 | advisor `copilot-app-advisor.spec.ts:610` | Advisor · SIP board — the Client book's SIP tile links to the board | e2e MOCK | PASS |
| AD-21 | advisor `copilot-app-advisor.spec.ts:618` | Advisor · SIP board — Advisor mode lists the SIP board in the rail | e2e MOCK | PASS |
| AD-22 | advisor `copilot-app-advisor.spec.ts:636` | Advisor screens — phone (390×844) — with a full book, no advisor screen scrolls the page sideways | e2e MOCK | PASS |
| ACCOUNT-01 | account `copilot-app-account.spec.ts:87` | Broker connections — today's backend — connected accounts: broker icon, last synced, what is on file, and the read-only statement | e2e MOCK | PASS |
| ACCOUNT-02 | account `copilot-app-account.spec.ts:126` | Broker connections — today's backend — the broker list is shown, and no sign-in is offered because the server marks no broker connectable | e2e MOCK | PASS |
| ACCOUNT-03 | account `copilot-app-account.spec.ts:145` | Broker connections — today's backend — empty: no account and no broker listed; holdings are not requested | e2e MOCK | PASS |
| ACCOUNT-04 | account `copilot-app-account.spec.ts:159` | Broker connections — today's backend — errors: accounts, broker list and stored holdings each say they did not load, and retry | e2e MOCK | PASS |
| ACCOUNT-05 | account `copilot-app-account.spec.ts:187` | Broker connections — today's backend — a body that is not the documented shape is an error, not an empty list | e2e MOCK | PASS |
| ACCOUNT-06 | account `copilot-app-account.spec.ts:197` | Broker connections — today's backend — Sync now: the read succeeds and the account shows the new count | e2e MOCK | PASS |
| ACCOUNT-07 | account `copilot-app-account.spec.ts:220` | Broker connections — today's backend — Sync now: a failed read is shown in plain words; the server's wording goes to admins only | e2e MOCK | PASS |
| ACCOUNT-08 | account `copilot-app-account.spec.ts:247` | Broker connections — today's backend — Disconnect: asks first, then the account is gone | e2e MOCK | PASS |
| ACCOUNT-09 | account `copilot-app-account.spec.ts:270` | Broker connections — today's backend — Disconnect: a failure is shown and the account stays | e2e MOCK | PASS |
| ACCOUNT-10 | account `copilot-app-account.spec.ts:314` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — Connect is offered only where the server says connectable | e2e MOCK | PASS |
| ACCOUNT-11 | account `copilot-app-account.spec.ts:339` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — Connect leaves for the broker's own page with a path back to this screen | e2e MOCK | PASS |
| ACCOUNT-12 | account `copilot-app-account.spec.ts:358` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — “Not now” starts nothing | e2e MOCK | PASS |
| ACCOUNT-13 | account `copilot-app-account.spec.ts:370` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — a sign-in the server cannot start is said on the screen (503, 403, and today's 500) | e2e MOCK | PASS |
| ACCOUNT-14 | account `copilot-app-account.spec.ts:398` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — coming back: success is shown, the address is cleared, accounts are read again | e2e MOCK | PASS |
| ACCOUNT-15 | account `copilot-app-account.spec.ts:412` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — coming back: each failure code gets its own plain sentence | e2e MOCK | PASS |
| ACCOUNT-16 | account `copilot-app-account.spec.ts:434` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — an account signed in on the broker's page: who, until when, and what was read | e2e MOCK | PASS |
| ACCOUNT-17 | account `copilot-app-account.spec.ts:447` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — an expired session says so and offers Reconnect, which leaves for the broker | e2e MOCK | PASS |
| ACCOUNT-18 | account `copilot-app-account.spec.ts:459` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — Sync now reads a signed-in account, and each error code gets its own sentence | e2e MOCK | PASS |
| ACCOUNT-19 | account `copilot-app-account.spec.ts:497` | Broker connections — planned contract, not yet on staging — planned contract, not yet on staging — broker_hub switched off for the account: no Connect, no Reconnect, accounts still listed | e2e MOCK | PASS |
| ACCOUNT-20 | account `copilot-app-account.spec.ts:520` | Settings — Notifications: the saved choices, a change that saves, and what they do today | e2e MOCK | PASS |
| ACCOUNT-21 | account `copilot-app-account.spec.ts:544` | Settings — Notifications: a failed save is shown and the switch does not move | e2e MOCK | PASS |
| ACCOUNT-22 | account `copilot-app-account.spec.ts:554` | Settings — About you: the stored details, and a save that sends the whole row back | e2e MOCK | PASS |
| ACCOUNT-23 | account `copilot-app-account.spec.ts:591` | Settings — About you: nothing stored, a failed save, and a failed read | e2e MOCK | PASS |
| ACCOUNT-24 | account `copilot-app-account.spec.ts:612` | Settings — Privacy: consent choices on record are shown as recorded, with no switch | e2e MOCK | PASS |
| ACCOUNT-25 | account `copilot-app-account.spec.ts:624` | Settings — Privacy: no consent purposes, and a failed read | e2e MOCK | PASS |
| ACCOUNT-26 | account `copilot-app-account.spec.ts:634` | Settings — Privacy: delete all conversations asks first, then deletes | e2e MOCK | PASS |
| ACCOUNT-27 | account `copilot-app-account.spec.ts:656` | Settings — Privacy: a failed delete is shown and the conversations stay | e2e MOCK | PASS |
| ACCOUNT-28 | account `copilot-app-account.spec.ts:666` | Settings — Account activity: the trail in plain words, newest first; empty; failed read | e2e MOCK | PASS |
| ACCOUNT-29 | account `copilot-app-account.spec.ts:688` | Settings — Diagnostics: recording switches on through the server, and says when the server could not | e2e MOCK | PASS |
| ACCOUNT-30 | account `copilot-app-account.spec.ts:715` | Settings — what has no backend still says so | e2e MOCK | PASS |
| ACCOUNT-31 | account `copilot-app-account.spec.ts:742` | Get started — portfolio step — CSV or Excel: the file is uploaded and the number of holdings added is shown | e2e MOCK | PASS |
| ACCOUNT-32 | account `copilot-app-account.spec.ts:774` | Get started — portfolio step — CSV or Excel: a file with no holdings, a file the server refuses, and an .xls the server cannot open | e2e MOCK | PASS |
| ACCOUNT-33 | account `copilot-app-account.spec.ts:803` | Get started — portfolio step — Broker account, today's backend: the broker list and the read-only statement, with no sign-in offered | e2e MOCK | PASS |
| ACCOUNT-34 | account `copilot-app-account.spec.ts:815` | Get started — portfolio step — planned contract, not yet on staging — Broker account: Connect goes out with a path back to Get started, and coming back reopens this step | e2e MOCK | PASS |
| ACCOUNT-35 | account `copilot-app-account.spec.ts:849` | Get started — portfolio step — planned contract, not yet on staging — the last step shows the holdings and broker counts when the server sends them | e2e MOCK | PASS |
| ACCOUNT-36 | account `copilot-app-account.spec.ts:873` | Account screens — phone (390×844) — no sideways page scroll on Broker connections, Settings or the import step | e2e MOCK | PASS |
| OPS-01 | ops `copilot-app-ops.spec.ts:87` | Ops pages — Tool registry — shows the agents, answer models, insight-writer switch, prompts and feature switches the endpoints return | e2e MOCK | PASS |
| OPS-02 | ops `copilot-app-ops.spec.ts:126` | Ops pages — Tool registry — empty lists get an empty state; a closed switch reads as on | e2e MOCK | PASS |
| OPS-03 | ops `copilot-app-ops.spec.ts:142` | Ops pages — Tool registry — a failed request shows an error with a retry; a 429 says to wait and is not retried on its own | e2e MOCK | PASS |
| OPS-04 | ops `copilot-app-ops.spec.ts:181` | Ops pages — Feed health — sources: status, last run and the trailing week per feed; a row opens its run history | e2e MOCK | PASS |
| OPS-05 | ops `copilot-app-ops.spec.ts:227` | Ops pages — Feed health — run history: a feed with no runs, and a run history that fails to load | e2e MOCK | PASS |
| OPS-06 | ops `copilot-app-ops.spec.ts:239` | Ops pages — Feed health — checks: consistency runs, findings with the stock named, and validation per feed — read when the tab is opened | e2e MOCK | PASS |
| OPS-07 | ops `copilot-app-ops.spec.ts:271` | Ops pages — Feed health — tables and filings pipeline show row counts, date range and stage state | e2e MOCK | PASS |
| OPS-08 | ops `copilot-app-ops.spec.ts:291` | Ops pages — Feed health — checks, tables and pipeline: empty states | e2e MOCK | PASS |
| OPS-09 | ops `copilot-app-ops.spec.ts:307` | Ops pages — Feed health — checks with runs but no findings; a pipeline the data platform could not read | e2e MOCK | PASS |
| OPS-10 | ops `copilot-app-ops.spec.ts:321` | Ops pages — Feed health — checks, tables and pipeline: error states, with the status table still shown | e2e MOCK | PASS |
| OPS-11 | ops `copilot-app-ops.spec.ts:340` | Ops pages — Feed health — status request fails: the error is shown and the other sections stay reachable | e2e MOCK | PASS |
| OPS-12 | ops `copilot-app-ops.spec.ts:352` | Ops pages — Audit log — this account's trail, with the broker named; the platform-wide log stays not connected | e2e MOCK | PASS |
| OPS-13 | ops `copilot-app-ops.spec.ts:372` | Ops pages — Audit log — sign-ins by account: newest first, with how many sessions are still valid | e2e MOCK | PASS |
| OPS-14 | ops `copilot-app-ops.spec.ts:390` | Ops pages — Audit log — fund-data refreshes: each fund with its fund house icon and result | e2e MOCK | PASS |
| OPS-15 | ops `copilot-app-ops.spec.ts:410` | Ops pages — Audit log — empty and error states of the three lists | e2e MOCK | PASS |
| OPS-16 | ops `copilot-app-ops.spec.ts:436` | Ops pages — KPIs — every figure comes from an endpoint; sign-ins are counted only on request | e2e MOCK | PASS |
| OPS-17 | ops `copilot-app-ops.spec.ts:513` | Ops pages — KPIs — empty states | e2e MOCK | PASS |
| OPS-18 | ops `copilot-app-ops.spec.ts:535` | Ops pages — KPIs — error states: each block fails on its own, and a feature that is off for the account says so | e2e MOCK | PASS |
| OPS-19 | ops `copilot-app-ops.spec.ts:563` | Ops pages — access — a non-admin is sent home from all four pages and no admin endpoint is called | e2e MOCK | PASS |
| OPS-20 | ops `copilot-app-ops.spec.ts:577` | Ops pages — access — an admin moves between the four pages with the tab strip | e2e MOCK | PASS |
| OPS-21 | ops `copilot-app-ops.spec.ts:607` | Ops pages — phone (390×844) — no page scrolls sideways, with every section and an opened feed row | e2e MOCK | PASS |
| OPS-22 | ops `copilot-app-ops.spec.ts:658` | Ops pages — shots desktop — capture desktop | e2e MOCK | SKIPPED (screenshot capture only) |
| OPS-23 | ops `copilot-app-ops.spec.ts:658` | Ops pages — shots phone — capture phone | e2e MOCK | SKIPPED (screenshot capture only) |
| TC-B1 | builder `copilot-app-builder.spec.ts:37` | Tool builder — templates and data source pool — starts empty, with a template per tool and the whole pool | e2e MOCK | PASS |
| TC-B2 | builder `copilot-app-builder.spec.ts:78` | Tool builder — templates and data source pool — a template fills the draft, stays editable, and typed work is never replaced without asking | e2e MOCK | PASS |
| TC-B3 | builder `copilot-app-builder.spec.ts:156` | Tool builder — templates and data source pool — every template is complete and names only sources that are in the pool | e2e MOCK | PASS |
| TC-B4 | builder `copilot-app-builder.spec.ts:170` | Tool builder — templates and data source pool — phone (390×844): no sideways page scroll; the pool table scrolls inside its own box | e2e MOCK | PASS |

## API / Endpoint Tests (staging)

The two new routes are not on staging (branch not merged), so they could not be called there over HTTP. What was run instead:

- **pytest** (staging backend image, no network, source mounted read-only):
  - Command: `python -m pytest -q -p no:cacheprovider tests/test_fno_routes.py tests/test_screeners_run.py tests/test_screener_contract.py tests/test_daas_key_resolution.py tests/test_intent_routing.py tests/test_copilot_market_tool_paths.py tests/test_instrument_research_widget.py`
  - Output: `233 passed, 1 skipped, 9 warnings in 7.76s`
  - Result: PASS
- **`GET /api/fno/*` handlers on the real staging F&O data** (handlers called directly with sign-in stubbed; reads went to the staging data platform exactly as the deployed route would; read-only). Output, as printed (longer lines cut at the right):
  ```
  {"call": "NIFTY expiries", "as_of": "2026-10-12", "count": 18, "first3": [{"expiry": "2026-10-13", "days_to_expiry": 1}, {"expiry": "2026-10-19", "days_to_expiry": 7}, {"expiry": "2026-10-27", "days_to_expiry": 15}]}
  {"call": "NIFTY chain", "summary": {"as_of": "2026-10-12", "expiry": "2026-10-13", "spot": 22363.35, "atm_strike": 22350, "total_call_oi": 258704680, "total_put_oi": 152920755, "total_call_oi_change": 95812535, "total_put_oi_change": -55177980, "pcr": 0.5911, "max_pain": 22400, "max_call_oi": {"strike": 22600, "oi": 17681950}, "max_put_oi": {"strike": 22000, "oi": 12874355}}, "strike_count": 108, "strikes_returned": 21, …
  {"call": "NIFTY futures", "as_of": "2026-10-12", "spot": 22363.35, "count": 3, "futures": [{"expiry": "2026-10-27", "close": 22386.5, "settle": 22386.5, "oi": 18703750, "change_in_oi": -239200, "volume": 40671, "basis": 23.15}, …
  {"call": "RELIANCE futures", "as_of": "2026-10-12", "spot": 1158.9, "count": 3, "futures": [{"expiry": "2026-10-27", "close": 1160.2, "settle": 1160.2, "oi": 144250500, "change_in_oi": 695000, "volume": 15521, "basis": 1.3}, …
  {"call": "ZZZZNOTREAL expiries", "http": 404, "detail": "No F&O data for ZZZZNOTREAL"}
  {"call": "ZZZZNOTREAL chain", "http": 404, "detail": "No F&O data for ZZZZNOTREAL"}
  {"call": "ZZZZNOTREAL futures", "http": 404, "detail": "No F&O data for ZZZZNOTREAL"}
  ```
  - Result: PASS on real data. The first run of this check FAILED and is why three things were fixed: futures came back empty (the real rows are typed `IDF` / `STF` with `option_type` "FUT", not `FUTIDX` / `FUTSTK`), an unknown symbol's chain answered 502 (the data platform wraps errors as `{"error": {"message"}}`), and lot size was not passed through.
- **`POST /api/screeners/run` handler on the real staging feature store** (same method, earlier in the session):
  ```
  {"screen": "ROE over 20, debt to equity under 0.5", "ok": true, "as_of_date": "2026-10-12", "matched": 0, "rows_returned": 0, "universe_complete": true, "coverage": {"roe": {"filled": 0, "total": 2469}, "de": {"filled": 0, "total": 2469}}, "first": []}
  {"screen": "P/E under 15", "ok": true, "as_of_date": "2026-10-12", "matched": 485, "rows_returned": 200, "universe_complete": true, "coverage": {"pe": {"filled": 1671, "total": 2469}}, "first": [{"ticker": "20MICRONS", "pe": 10.3486}, {"ticker": "AAVAS", "pe": 13.7715}, {"ticker": "ACC", "pe": 11.0675}]}
  {"screen": "RSI under 30", "ok": true, "as_of_date": "2026-10-12", "matched": 250, "rows_returned": 200, "universe_complete": true, "coverage": {"rsi": {"filled": 2469, "total": 2469}}, …
  {"screen": "Large cap only", "ok": true, "as_of_date": "2026-10-12", "matched": 0, "rows_returned": 0, "universe_complete": true, "coverage": {"bucket": {"filled": 0, "total": 2469}}, "first": []}
  ```
  - Result: PASS on real data; the zero-match screens are the fundamentals gap (see Gaps), which the screen reports as "no data for this metric".
- **UNVERIFIED:** both routes over HTTP on staging with a real session (auth, rate limits, the proxy in front). Needs the merge, then `curl` with a session cookie.

## UI / Playwright Tests

- **Specs:** `frontend-v5/e2e/tests/copilot-app*.spec.ts` (twelve files; the live and screenshot specs are not part of this run)
  - Run from a clean checkout of `58631505` (`git worktree`, no local changes), in the Playwright container with no network:
    `npx tsc -b` → `npx vite build` → `npx vite preview --port 5174` → `npx playwright test --config pw.copilot-app.config.ts <the twelve spec files>`
  - Output:
    ```
    58631505 fix(v5): say whose data is on screen while an advisor has a client open
    tracked files changed in clean tree: 0
    tsc -b exit=0 (error lines: 0)
    ✓ built in 20.29s
    playwright exit=0
      4 skipped
      247 passed (2.8m)
    ```
  - Per file: account 36 · advisor 22 · builder 4 · markets 24 · ops 21 · portfolio 18 · research 15 · screener 21 · screens 26 · trader 14 · workspace 22 · shell 24. The 4 skipped are screenshot captures (2 in ops, 2 in research) that run only when a screenshot folder is set.
  - Result: PASS
- **Regression, the older chat screen:** `npx playwright test --config pw.copilot.config.ts e2e/tests/lite-copilot.spec.ts` → `4 passed (4.6s)`. Result: PASS
- **Found by these tests and fixed in this round:**
  - Home cards arrived one request at a time and moved, so a click could land on a different card (commit `92b2af9f`, new TC-04c).
  - The original strategy builder overflowed the phone layout; it now scrolls inside its own frame.
  - Outside the advisor screens nothing said an advisor was viewing a client, and there was no way back (commit `58631505`, new TC-11b).
- **UNVERIFIED:** any screen of this round in a browser against the real backend. `e2e/tests/copilot-app-live.spec.ts` does that on the deployed app and needs the merge plus a session token.

## Data Correctness (staging)

- **F&O bhavcopy** (`nidp.fno_bhavcopy`, read-only SQL on the staging warehouse): latest day 2026-10-12 has `IDF` 18 rows / 6 underlyings, `IDO` 5,773 rows, `STF` 635 rows / 213 underlyings, `STO` 30,725 rows; lot size filled on 37,151 of 37,151 rows (NIFTY 65, BANKNIFTY 30, RELIANCE 500, M&M 200). The NIFTY October future in the table (close 22386.50, underlying 22363.35, OI 18,703,750) equals the route's answer above. PASS.
- **Feature store** (`nidp.stock_features_daily`, 2026-10-12): 2,469 stocks; P/E filled on 1,671, RSI on 2,469, 1-year return on 2,468; ROE, ROCE, debt-to-equity, P/B, market cap and market-cap bucket filled on 0. The screener's coverage figures above match. PASS for the route; the empty columns are a data gap.
- **Response shapes on staging** (read-only GETs as the test account, by the worker that built each screen; counts and field names only were kept, and the raw responses were deleted from the scratch area): every endpoint a screen parses was compared with its real response. Differences that changed the build are listed under Gaps (for example `needs-attention` answering 500, `/api/market/events` failing, SIP board always empty).
- **Not checked:** whether figures are correct and fresh at source beyond the two tables above.

## Inputs required from user

- A staging session token was supplied earlier in the session and used for read-only GETs only. It is still in a 600-mode file in the session scratch area for the post-merge check, and will be deleted after it.
- Needed next: the merge to `dev`, so the deployed app can be tested.

## Gaps — what is still not connected, by persona

Status words: **no source** = no endpoint or store exists; **no data** = the endpoint works but staging returns nothing; **defect** = an existing endpoint or client is broken; **decision** = it can be built, but needs a product call first.

### Investor

| Tool | Connected now | Still missing | Kind · smallest change |
|---|---|---|---|
| Home | Last statement with Gmail sync and upload, health score, plan actions, drift, signals, ranked prompts | Home's drift card and Portfolio analysis quote different equity shares for the same account: Home (like the original dashboard) reads a split that files every ETF and gold under "hybrid" | defect · Home reads the composition split, or the enrichment classifies ETFs by category |
| Portfolio analysis | Concentration, overlap, what to fix, performance, value history, target mix | The target shown comes from the frontend's risk-category table, which is not the plan engine's target; the stored per-user target has no read route | decision + thin `GET /api/portfolio/allocation-deviation` over `compute_deviation()` |
| Recommendations, Action plan | Steps with tax line, confidence, deferral; mark / decline / reopen a step; rebuild the plan; expected vs observed health | A result per step after it is done; observed change is empty on staging (one snapshot on file); step tax is "not estimated" on all 6 staging steps | no source · no data (is the daily snapshot job running on staging?) |
| Portfolio ledger | Holdings with source, statements, transactions, SIPs, realised gains, corrections | A log of corrections and undo; corrections are overwritten by the next statement import; transactions, SIPs and realised gains are empty on staging; "vs index" is empty on all 117 rows | no source · no data |
| Risk, Goals, Tax | The original pages, unchanged | Tax's "Schedule harvest" button has no action (original page) | no source |
| Stock research | Price history and chart, key figures, scores and technicals, market backdrop, quarterly results, shareholding, corporate actions, filings | ROE, debt-to-equity, P/B, market cap (empty in the feature store), ROCE (not sent at all); annual statements; fair value vs own history; peers; bulk and block deals; intraday price. The scores card and price history are switched on per account (two allow-lists): other accounts see "not switched on" | no data · no source · decision on the allow-lists |
| Fund research | NAV, size, expense ratio, riskometer, returns vs category, risk tiles, holdings, sectors, managers | NAV chart; NAV date (null); returns vs benchmark and beyond 3 years; rank and peers (empty); fund score (the user route answers 404); exit load; overlap with funds held | no source · defect (`/api/funds/{isin}/v3-score`) |
| Screener | Rule screens run in the page; ready-made strategy screens; save either as a watchlist | Rules on ROE, ROCE, debt-to-equity, P/B, market cap and cap bucket match nothing: those columns are empty (Trendlyne's ratio and market-cap passes have not run). No icon inside the shared results widget | no data |
| Markets | Every tab at parity with the original pages; results and corporate actions for directly held stocks | Upcoming result dates fail on staging (`/api/market/events` queries `nidp.event_calendar` through the app's own database); movers, breadth, market verdict, sector market cap / P-E / ROE are empty; AI sector commentary is off (no model configured); stocks held through funds are not included | defect (serve it from the data platform's `/v1/events/calendar`) · no data |
| Watchlist & alerts | Research (multibagger) watchlist with full parity, saved screens of both kinds as watchlists, scanner levels, filing-alert switches | Hand-picked personal lists; price / volume / pledge alerts; an alert when a saved screen matches (tables exist, no code uses them); filing alerts are saved but nothing is sent (`_DELIVERY_ACTIVE = False`); scanner levels are empty on staging | no source · no data |
| Saved | Saved screens and strategies, starred questions, threads, holdings download | Saving an answer as a report; pinning or renaming a thread | no source |
| Settings, Onboarding | Profile, risk, goals, notifications, about you, consent records, delete conversations, activity, diagnostics, CSV / Excel upload | Answer depth; constraints / portfolio rules; memory; changing consent; deleting the account (the route does not delete — see defects); notification switches have no sender; column mapping and preview for an upload | no source |
| Statements (CAS) | Latest statement from Gmail or upload | "Import every statement not already stored, show the latest": not built — see decisions | decision |

### Trader

| Tool | Connected now | Still missing | Kind · smallest change |
|---|---|---|---|
| Trader desk | Journal, watch levels, scanner signals, broker accounts with the holdings a broker read stored, F&O card (future, basis, put-call ratio, max pain, OI levels) | Open positions, funds and day P&L from a broker (the routes arrived with the broker-hub backend, merged to `dev` after this work; the desk does not read them yet); risk limits; scanner and watch levels are empty on staging; no form to log a trade | follow-up · no source · no data |
| Options lab | Underlying and expiry pickers, option chain, open interest, put-call ratio, max pain, legs prefilled from the chain, payoff | Implied volatility, Greeks, chance of profit, margin; intraday chain; day change on the chain; lot size shows only after the data platform is redeployed with the lot column | no source (the exchange file has no IV) |
| Strategy builder | The original page, mounted | It is not laid out for a phone (scrolls inside its frame). Its own text says "broker order placement ships in a later phase", which contradicts the read-only rule | original page copy |
| Paper trades | Summary, the engine's full record, simulation lab (for accounts that have it) | Nothing is recorded on staging | no data |
| Not brought in | — | The original Pro Trader basket page (its banner reads "Deploy Aggressively / Stay Defensive", and its empty response breaks the page); the original charts, move-odds and movers screens | decision |

### Advisor

| Tool | Connected now | Still missing | Kind · smallest change |
|---|---|---|---|
| Client book | Book figures, queue, roster, links into each client | Approved model portfolios; client report drafts | no source |
| Advisor workspace | The original page; opening a client stays in the shell | Its client table is cramped at 1280 px and unreadable at 390 px (same in the original app) | original page |
| Client 360 | Scores, summary, value and recent purchases, unrealised gains, statement history, shared statements, notes, holdings download | "Needs attention" answers 500 on staging (a plan action's priority is sometimes a word, sometimes a number, and the comparison fails); saving a note; requesting a statement (the client's page exists only in the older app); logging a call; review pack (a stub: queues a task nothing works) | defect in `routes/advisor_v4.py` · no source |
| SIP board | Four queues and tiles | It can never have rows: it reads a collection nothing writes, while detected SIPs are stored elsewhere | defect · read `detected_sips` |
| Not brought in | — | Firm name / ARN form; the nine advisor workflow tiles from the original chat page | follow-up |

### Internal (admins)

| Tool | Connected now | Still missing | Kind |
|---|---|---|---|
| Tool builder | A template for each of the 21 tools; a pool of 38 data sources with status and which tools use each | Saving a definition, AI drafting, test prompts and review | no source |
| Tool registry | Routing agents, answer models, prompts, feature switches, insight-writer switch | A list of the Copilot's tools with usage, errors and latency (tool calls are not recorded anywhere) | no source |
| Feed health | Status, last run, week strip, run history, consistency checks, validation, table counts, filings pipeline | — | — |
| Audit log | This account's trail, sign-ins by account, fund-data refreshes | The platform-wide log (the service function exists, no route calls it) | thin route |
| KPIs | Platform counts, data quality score, statement corrections, app jobs, reported issues, setup study | Chat volume, active users, answer speed, feedback summary, model cost and tokens, cache hit rate, reconciliation accuracy | no source (not recorded) |

### Across the product

- **Logos.** The repo has no logo files and no API returns a logo URL. Every icon is a lettered tile; `lib/logo-manifest.ts` is where real files are registered. Decision: a licensed logo service, or an asset pack.
- **Data-source labels.** No markets response states its source, and nothing in the markets backend mentions Trendlyne (it reads the data platform and a live quote source), so the screens show a source only where a response states one.
- **Fundamentals.** ROE, ROCE, debt-to-equity, P/B and market cap are empty for all 2,469 stocks on staging. This one data gap is behind the empty Screener rules, the "Not available" key figures on Stock research and the empty sector medians on Markets.
- **Broker sign-in.** Built against the broker-hub contract and tested on mocks. That backend was merged to `dev` while this report was being written; another session is finishing the Settings and onboarding broker screens on a branch that includes these commits.

### Defects found in existing code (not changed in this round)

Security and privacy — these need an owner:

1. `GET /api/admin/grafana-alerts` has no sign-in or admin check.
2. `backend/routes/cas_snapshots.py` trusts the `profile_id` parameter: read from the code, any signed-in user who knows a profile id could read that client's snapshots. Not exercised.
3. PAN and the statement password are stored as entered (`user_profiles`, `gmail_tokens`), while the original onboarding page tells users they are "never stored in plain text".
4. A statement-parser API key is hard-coded in `backend/services/cas_api_client.py`, and session tokens are hard-coded in `backend/tests/conftest.py`.
5. `DELETE /api/compliance/account` does not delete the profile, PAN, Gmail token, goals, chats or broker accounts, and sign-in still works afterwards.
6. Every failed save shows the server's own error text to the user (`App.tsx` toast), which can name internals.

Functional:

7. `routes/advisor_v4.py` needs-attention: 500 when a plan action's priority is a word.
8. `/api/market/events` and `/api/market/signals`: fail on staging (wrong database).
9. The app's HTTP client re-sends any request once after a 5xx, POSTs included, so a create that succeeded before failing is saved twice.
10. Shared clients that do not match the backend: SIP list contract, plan step status (sends lower-case statuses the backend rejects), goals snapshot (reads the wrapper as the row), saved scenarios contract.
11. The market verdict text from the backend is directive ("keep cash, hedge longs, avoid new positions"); it is null on staging today.
12. The monthly Gmail sweep may re-import an email the onboarding route already imported, through the paid parser (read from code).

### Decisions needed from the owner

1. **Statements: import all, show the latest.** Not built. The existing snapshot engine, used as it is, lets an older statement overwrite a newer portfolio (reproduced against a stand-in database). It also turns out the Gmail scan returns only the newest statement per depository, so a history import needs its own scan. Questions: which statement counts as "the portfolio" when the newest is MF-only; how far back to scan; whether a paid vision call per older CDSL statement is acceptable; synchronous with a cap or a background job.
2. **Logo source** (above).
3. **Buy / Hold / Sell on the stock research card.** The card is shown unchanged, as the owner asked for the research pop-up on 2026-09-18; it now also appears on the new Research screen.
4. **Fund pages collect the factsheet on demand.** Opening a fund not in the cache makes the server collect its factsheet from Groww.
5. **Which target allocation is the real one** — the risk-category table the screens quote, or the plan engine's bands.
6. Still open from earlier rounds: the native Android / iOS build, whether `/app` becomes the landing page after sign-in, and the four test chat threads left on staging.

## Verdict: BLOCKED

Blocked on deployment, not on a failing test: the branch must be merged to `dev` before the two new routes can be called on staging and the screens opened against the real backend. Until then this is IN PROGRESS, not DONE.
