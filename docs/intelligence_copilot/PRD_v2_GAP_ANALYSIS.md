# PRD v2 gap analysis: the evidence-driven visual Copilot vs. what is built (31 Oct 2026)

**Requirement:** [PRD_v2_EVIDENCE_VISUAL_COPILOT.md](PRD_v2_EVIDENCE_VISUAL_COPILOT.md), saved verbatim.

**Baseline, i.e. what "built" means here:**
- `origin/dev` 4a9cdef7.
- The open Daily Trader Copilot PRs: #419 (Release 1) and #422 (Release 2). Neither is merged.
- Three branches in progress:
  - `feat/dtc-r3-daily-review`
  - `feat/dtc-r3-suggestions`
  - `feat/r2-open-positions`

**Evidence:**
- Code paths, as cited.
- Read-only aggregate queries on the staging warehouse, run 31 Oct (section 10).
- The 30 Oct audits A to E in `docs/daily_trader_copilot/audits/` on the DTC branches.

**Not verified:** nothing was run as a signed-in user, and no LLM answer was graded.

---

## 1. Bottom line

1. **The PRD's central architecture is already the architecture of the visual-answer engine.** The PRD's "critical recommendation" is: engines return structured facts, a composer picks supported components, React renders them, and every figure keeps its source. That is how `backend/services/copilot_visual` works (Releases 1 and 2), contract `visual-answer-v1`:
   - 12 intents, each built deterministically from existing desk services;
   - 9 typed block types, validated by `payload.validate()`;
   - rendering by block type only (`frontend-v5/src/components/chat/visual/blocks/registry.tsx`), with unknown or bad blocks degraded safely;
   - a per-source data-quality footer with a stale banner, evidence rows, and follow-ups;
   - the LLM explains a facts block it is handed and is told never to add a number.

   **Recommendation:** grow v1 into a v2 contract by adding fields. Do not start a parallel one.
2. **Coverage of the 18 prompt categories is thin and trader-shaped.** Releases 1 and 2 built the owner's 15 *trader* questions.
   - **Substantially covered as a visual answer:** Category 10 (Trading ideas and plan evaluation).
   - **Partly covered:** 11 (F&O), 12 (Risk), 16 (Daily briefing).
   - **Engines and data exist, but no blueprint or visual answer:** 1, 2, 3, 4, 13, 14, 18.
   - **Largely missing:** 5 (Macro), 6 (News, though its data is fresh), 7 (Regulatory), 8 (Legal), 9 (Strategy validation in chat), 15 (Scenarios), 17 (Education).
3. **The cross-cutting gaps are in the evidence framework, not the visuals:**
   - no evidence classification (Verified / Reported / Inference / Scenario / Unknown) and no source tier;
   - no link to the original document;
   - no answer blueprints stored as data;
   - no composition of several engines into one answer (§9);
   - no regenerate-or-block quality loop (§10);
   - no save, share or export of an answer;
   - no "challenge my thesis";
   - no adaptive density.
4. **A large evidence asset is under-used.** `nidp.documents` holds 110,520 exchange filings: 7,039 annual reports, 2,860 earnings-call transcripts, 13,068 results filings, 2,966 investor presentations and 4,538 press releases.
   - They are current to 30 Oct and split into 2,100,220 searchable chunks.
   - Their `source_url` points to the original filing, so citations can link to it.
   - A retrieval-evaluation harness exists (`backend/nidp/eval/rag_eval.py`: citation resolution, dangling citations, advice leakage, refusal when nothing is found).
   - Chat reaches the store only through `stocks_insights`.

   This is the natural Tier-1 backbone for business, management, results and forward-looking evidence.
5. **Phase 2 data is the long pole:**
   - `nidp.sebi_circulars` is **empty** on staging. The loader and its cron line exist, but the feed is not in `v_feed_status`.
   - `FRED_MACRO` has never succeeded, and there is no macro-indicator history store.
   - There is no court, NCLT, NCLAT, CCI or IBBI source.
   - BSE announcements have returned HTTP 403 since 13 Oct.
   - `insider_sast` is empty.
   - There are no consensus estimates, so "did earnings beat expectations?" cannot be answered.
6. **The PRD needs three corrections and one compliance decision before it is a build spec** (section 2).

---

## 2. Evaluation of the PRD itself

**Where it agrees with how Nivesh already works (keep as written):**
- "Evidence Before Intelligence."
- Deterministic calculations, with the LLM only explaining (§11.3).
- Deterministic risk controls are authoritative (FR-09). This is `services/risk_gate`, the universal risk service.
- Confidence is never a probability of profit (§10.3).
- Never show an allegation as a finding (FR-06).
- Charts only from retrieved data (§7.1).
- A typed schema, and no model-generated code (§13).
- "Don't force every section into every answer" (§6.4).
- Idea, not recommendation (Category 10). This matches the owner's standing rule: "ideas to review", never "buy now / recommend / pick".

**Needs correcting or deciding:**

| PRD § | Issue | Proposed resolution |
|---|---|---|
| 11.4 | "Database: PostgreSQL" | Nivesh runs **two** stores: Postgres (app DB + NIDP warehouse) and **MongoDB**. Mongo holds chat messages, trade plans, paper trades, risk decisions, `event_ai_analysis` and `ai_watchlist_days`. The data model in §12 must say which store each entity lives in. |
| 11.4 | "AI providers: OpenAI with Google Generative AI fallback" | Not what runs. `backend/nidp/services/copilot_agent/_llm.py` selects OpenAI-wire providers by environment: `openai` (default), `groq` (an open model), and a Claude gateway on the app VM. There is no Google fallback. |
| 11.4 | "Charts: Recharts" | The visual answers use their own SVG components (the desk `CandleChart` and the visual blocks). `recharts` 2.12 and `lightweight-charts` 5.2 are also installed. Keep the house components so chat and desk charts match. |
| 7.2A, 8.2 | The Executive Insight Card's "Overall assessment / Fundamental quality: Strong", and "Is the current valuation justified?" | A per-stock overall rating or valuation verdict reads as a research recommendation under SEBI's Research Analyst rules. Today's wording rules forbid it. **Owner decision** (section 8): either a methodology-labelled score band with no verdict, or Nivesh's registration covers it. |
| 13 | A new response shape, separate from what is shipped | Add §13's fields to `visual-answer-v1`, and keep v1's block-type tolerance. A parallel contract would split the renderer and the tests. |
| FR-03 | New sector weights (20/20/15/15/10/10/10) | `backend/nidp/services/sector_scoring/composer.py` already composes V3 sector-aware scores (fundamental, technical, cycle, event overlay, red-flag penalty). §11.4 itself says not to build duplicate engines. Reconcile the two first. "Earnings momentum" needs estimate revisions, which do not exist. |
| FR-06, Cat. 8 | Court and tribunal portals as sources | These portals have no APIs. Their terms and the work of matching cases to companies make this an L+ effort. Exchange-disclosed litigation is already classified (`announcement_classifier` has category `litigation`: NCLT/IBC/CIRP/court orders) and is a Tier-1 start. |
| 10.1 | Quality weights | These need a graded evaluation set and a judge. `rag_eval.py` covers citation and leakage checks; nothing grades depth or accuracy yet. Size the judge's LLM cost before adopting the 25/20/15/15/10/10/5 weights. |
| 15, 9 | "Turn this into a paper-trading idea" | The paper-trade path exists: the desk decision cards and risk service. Strategy Lab was **removed by the owner on 29 Oct**, so the strategy-validation dashboard (§7.2J) needs a home: chat only, or Chart Analysis. **Owner decision.** |

---

## 3. Foundations the PRD can build on

| PRD element | Existing implementation | State |
|---|---|---|
| Unified chat (4.1, AC-1) | `/v5/app` one-screen Copilot; `routes/chat.py stream_chat` (SSE); desk dock | Live on staging |
| Routing (FR-01, AC-2) | Deterministic visual-answer intents (`copilot_visual/intents.py`, 12 intents) ahead of the LangGraph router (`copilot_agent/nodes/intent.py`), with specialist nodes stock, market, mf, portfolio, risk, recommendation, backtest, goal, policy, stocks_insights | Single-engine only; no composition (§9) |
| Typed visual contract (§13, §14) | `visual-answer-v1`: kpis, candles, bars, heatmap, quadrant, ranked, trade_plan, list, notice; `validate()`; registry by type | PRs #419, #422 |
| Data quality (7.2I, AC-7) | Per-source fresh/stale/missing with as-of and a stale banner (`VisualAnswer.tsx`); owner's no-stale rule | Built; lacks completeness, conflicts, historical coverage |
| Evidence panel (7.2H) | Shell `Evidence.tsx` (tool steps, routing, source tags) + visual-answer `evidence[]` rows | Partial: no classification, original-source link, retrieval time or verification status |
| Deterministic calcs (§11.3) | `option_pricing.py` (Black-76, IV, Greeks), `strategy_plan/payoff.py`, risk service sizing, `copilot_tools/technical.py`, the AI Trader DSL backtester with walk-forward folds and holdout (`routes/ai_trader.py:444`), `copilot_tools/backtest.py` (lump-sum and SIP) | Built |
| Prompt library (§8) | `GET /api/copilot/suggested-prompts` (109 templates), `data/nivesh_question_bank.json` (298), suggestion engine on `feat/dtc-r3-suggestions` (`query_templates`) | No blueprint per category |
| Curated, non-LLM mapping (7.2G) | `copilot_agent/nodes/policy.py`: policy → sector rules, versioned in code, with companies from the screener; never inferred by an LLM | Pattern to reuse for macro transmission maps |
| Financials and ownership (FR-02) | `copilot_tools/company_financials.py` (DaaS financials, shareholding, features); warehouse `nse_financials_quarterly` 2,208 symbols, about 10.7 quarters each, to Sep-26; `shareholding_pattern` 2,411 symbols, Sep-26 | Data present; no visual blueprint |
| Filings as evidence | `nidp.documents` / `document_chunks` (above); `stocks_insights` quotes passages; `rag_eval.py` | Under-used |
| Regulation | `nidp/services/sebi_circulars` + migration 163 + cron line; `policy.py` curated rules | Table **empty** on staging |

---

## 4. Gaps by functional requirement

| FR | What exists | Gap | Size |
|---|---|---|---|
| 01 Conversational Copilot | Intents, specialist nodes, follow-ups, thread symbol carry-over, compliance scrub | Composing several engines into one answer; asking a clarifying question when an entity is missing (today "Which stock?" or no answer); fact / interpretation / projection tags on text | L |
| 02 360° stock | Financials (multi-quarter), shareholding, V3 scores, technicals, desk plan, filings retrieval | A `stock_360` blueprint (executive card, financial-trend line, peer table, ownership trend, events timeline, scenarios with stated assumptions); peers need an industry map (`sector_master` is sparse; use `index_constituents` industry) | M–L |
| 03 Sector ranking | NSE sector indices (heatmap in `smart_money`), V3 sector composer, app `sector_macro_scores` (21 rows, fresh), MF holdings by sector | The ranking itself with the PRD factors; earnings momentum (no estimates); `analytics.sector_snapshot` frozen since 12 Oct (PR #414); `fpi_sector_auc` stale | M |
| 04 Macro | `macro_releases` calendar (375 rows, PARTIAL); Yahoo global snapshot (crude, INR, US10Y; not stored); RBI yield files in `data/nidp_raw`; desk regime | An indicator-history store (repo, CPI, WPI, IIP, PMI, GDP, INR, G-sec, commodities); `FRED_MACRO` never succeeded; a transmission map (curated, like `policy.py`) | L |
| 05 Regulatory | SEBI loader, empty table; `policy.py` (6 policy rule sets) | Run and register the SEBI feed; parse circular PDFs into what changed / effective date / who is affected; RBI, MCA, ministries, Gazette | M (SEBI) + L (others) |
| 06 Legal | `announcement_classifier` `litigation` category on exchange filings | A legal-event store with the status taxonomy (allegation … settlement); court and tribunal sources; party-to-company matching | L |
| 07 News and events | `corporate_announcements` 196,864 rows (NSE fresh to 30 Oct), `event_ai_analysis` (Mongo, about 577 events a day), classifier with sentiment | BSE 403 since 13 Oct; no industry, macro or geopolitical news source (Tier 3); `corporate_event_signals` empty (Market Overview headlines blank); no news visual answer (timeline, price reaction, materiality) | M |
| 08 Strategy validator | AI Trader DSL backtester (walk-forward, holdout), `strategies`/`strategy_runs` tables, `desk_expectation` out-of-sample checks | Plain English → rules in chat; regime-wise and parameter-sensitivity reports; the validation dashboard; a UI home after Strategy Lab's removal | M–L |
| 09 Risk | Risk service (authoritative, logged in `risk_decisions`), `position_size` answer, desk 10 risk checks, open positions (in progress) | Psychology (overtrading, early exits) needs a trade journal (`trade_journal` empty); Q15 review is in progress | M |
| 10 Portfolio | `portfolio_analyst`, holdings-enriched, concentration, overlap, flat-% stress, XIRR | A portfolio visual blueprint (allocation, exposure cards, stress chart); beta- or macro-driven stress; event and regulatory exposure | M |
| 11 Daily intelligence | `market_view` answer, Closing Bell video (5 languages, live), AI watchlist | Pre-market briefing (GIFT Nifty absent; Asian bars lack a date); intraday event alerts; personalised impact; `market_daily_brief` stale since 21 Oct | M |
| 12 Learning | Question-bank look-ups | A learning blueprint (concept, example, formula, diagram); context-aware education inside other answers | M |

---

## 5. Gaps by prompt category (§8)

Status key: **Built** = a visual answer exists; **Partial** = data and engine exist, no blueprint or visual answer; **Missing** = data or engine absent too.

| # | Category | Status | Today | Main gap |
|---|---|---|---|---|
| 1 | Discovery and screening | Partial | `top_opportunities`, `breakouts`, `unusual_volume`; `POST /api/screeners/run`; `stock_features_daily` (52-week, relative volume, delivery) | Plain-English criteria → screen → ranked visual answer; fundamental factors with trends (ROCE trend needs balance sheets); sector distribution |
| 2 | Complete stock analysis | Partial | Stock node + financials, shareholding and V3 tools; `stock_decision` (plan and chart) | `stock_360` blueprint; peer table; scenarios with stated assumptions; SEBI wording of the "assessment" |
| 3 | Technical | Partial | `stock_decision` candles (EMA 20/50/200, levels); Chart Analysis v2; `stock_technical_features` (RSI, ATR, support) | Indicator panels (needs a `line` block); volume and delivery confirmation; invalidating levels as a block |
| 4 | Sector | Partial | `smart_money` sector heatmap and flows | Ranking table with factors; relative-strength line; earnings momentum (no data) |
| 5 | Macro | Missing | Policy node (curated, 6 rule sets); global snapshot (not stored) | Indicator history, transmission map, scenario block |
| 6 | News and events | Partial (data) | Announcements and `event_ai_analysis` fresh | News blueprint: timeline (event / publication / effective dates), affected entities, price reaction |
| 7 | Regulatory | Missing (data) | SEBI loader, empty table | Feed running; circular parsing; timeline and before/after |
| 8 | Legal and governance | Missing | Litigation tag on filings | Legal-event store and status taxonomy; case timeline |
| 9 | Strategy validation | Partial (engine) | AI Trader backtester | Chat blueprint and dashboard (equity curve, drawdown, regime table) |
| 10 | Trading ideas | **Built** | `stock_decision`, `trade_validity`, `exit_options`, `fno_setups`; TradePlan pipeline; decision cards; risk sizing | Outcome tracking: `positional_outcomes` is empty, so there is no live hit rate |
| 11 | F&O and options | Partial | `expected_move`, `fno_setups`; chain (PCR, max pain, walls); payoff and Greeks services; Kite margin (PR #415) | Payoff-graph and option-chain blocks in chat; Greeks cards; IV history (`record_iv_history` cron not installed) |
| 12 | Risk and psychology | Partial | `position_size`, `open_trades`, risk service; Q15 in progress | Behaviour analytics (needs the journal); loss-scenario block |
| 13 | Portfolio | Partial | Portfolio node and tools; Open Positions in progress | Visual blueprint; stress chart; holdings technicals (DMA) |
| 14 | Earnings and results | Partial | Results filings, call transcripts, quarterly financials, event calendar; earnings-surprise tracker | Results blueprint; "beat expectations" cannot be answered (no consensus) and must say so |
| 15 | Future prospects | Missing | Filings retrieval only | Scenario methodology with stated assumptions; no LLM-made numbers |
| 16 | Daily briefing | Partial | `market_view` (index, breadth, VIX, sectors), Closing Bell | Movers (frozen `analytics`, PR #414), event calendar block, next-session watchlist, global block with bar dates |
| 17 | Education | Missing | Question-bank look-ups | Blueprint, diagrams, calculators |
| 18 | Peer comparison | Missing | Building blocks only | Compare intent; side-by-side table; normalised price chart; evidence matrix; contradiction detection |

---

## 6. Cross-cutting gaps

**Evidence framework (§6)**
- Evidence classification per claim: none.
- Source tier per source: none.
- Original-source link: none in chat, although `documents.source_url` exists.
- Retrieval time per claim: none.
- Verification status: none.
- Size: S–M, by adding fields to `evidence[]` and `data_quality.sources[]`.

**Visual components (§7.2 A–J) against today's block types**

| Component | Status | Today / gap |
|---|---|---|
| A Executive card | none | `headline` + `decision` are the nearest; SEBI decision pending |
| B Metric cards | partial | `kpis` (label, value, sub, tone); add unit, period, benchmark and source per metric |
| C Charts | partial | `candles` (EMA overlays, levels, band) and `bars`. Missing: `line` (RSI/MACD, relative strength, equity, valuation, ownership), payoff, drawdown, timeframe switching |
| D Comparison | partial | `ranked`; no side-by-side compare block |
| E Scenarios | none | — |
| F Event timeline | none | `list` only |
| G Macro impact map | none | — |
| H Evidence panel | partial | See the evidence framework above |
| I Data quality | **largely built** | Add completeness, conflicts and historical coverage |
| J Strategy dashboard | none | — |

**Rest of the cross-cutting work**
- **Adaptive density (§7.4):** none. Every intent has one fixed density, and "explain simply / go deeper / show more evidence" are not handled. Size M.
- **Quality governance (§10):**
  - Built: the compliance scrub, the facts block ("never adds a number"), `validate()`, and `rag_eval` checkers.
  - Missing:
    - a numeric-grounding check, so that a number in the text that is not in the payload blocks the answer (S);
    - a check for stale data presented as current inside the text (S);
    - a regenerate-or-block loop (M);
    - a store for quality evaluations (S);
    - graded evaluation sets per category (M).
- **Response contract (§13)** — fields missing from v1:
  - `query.entities` and `query.time_horizon`;
  - answer sections (`key_findings`, `contradictions`, `scenarios`, `risks`, `invalidation_conditions`, `monitor_next`);
  - per-visualization `source_refs`;
  - `limitations`;
  - `confidence {level, reason}`;
  - `methodology {model_version, calculation_version, data_snapshot}`.

  Size M, done by adding fields.
- **Interactions (§15):**
  - "What changed" exists only for trade plans (`trade_validity`).
  - "Show me the evidence" is partly there (Evidence panel).
  - "Challenge my thesis", "What could go wrong", "Compare with peers", "Simplify" and "What data is missing" (as a question) are not built.
  - Size M.
- **Save / share / export (4.2, §14):**
  - There is nothing for a chat answer (only advisor PDFs and CSVs exist).
  - Owner decision on public links versus private ones. Size S–M.
- **Data model (§12):** map onto existing stores before creating any.

| PRD entity | Existing equivalent |
|---|---|
| `copilot_conversations` / `copilot_messages` / `copilot_response_components` | Mongo `chat_sessions` / `chat_messages` (the widget is stored on the message) |
| `copilot_prompt_templates` | `query_templates` (suggestions branch), `copilot_prompts.py`, the question bank |
| `macro_events` | `nidp.macro_releases` |
| `regulatory_events` | `nidp.sebi_circulars` |
| `news_events` | `corporate_announcements` + `event_ai_analysis` |
| `strategy_validation_runs` | `strategy_runs` + AI Trader runs (Mongo) |
| `evidence_registry` (partly) | `nidp.documents` |

  **Absent:** `macro_indicators`, `legal_events`, `entity_relationships`, `event_impact_assessments`, `sector_intelligence_daily`, `strategy_forward_runs`, `intelligence_reports`, `copilot_answer_blueprints`, `copilot_source_citations`, `copilot_quality_evaluations`.
- **NFRs (§16):**
  - Streaming, visible freshness and mobile are met for visual answers.
  - Auditability is partial: a payload does not record model, prompt or calculation versions, nor a data-snapshot id.

---

## 7. Data blockers (operations; each needs a fix or an owner action)

| Blocker | Evidence (31 Oct unless noted) | Blocks |
|---|---|---|
| SEBI circulars table empty; feed not registered | `count(*) = 0`; no `v_feed_status` row | Category 7, FR-05 |
| No macro indicator history | `FRED_MACRO` NEVER_SUCCEEDED; `fred_macro` 0 rows; `macro_calendar` PARTIAL | Category 5, FR-04 |
| BSE announcements HTTP 403 | Since 13 Oct (audit C) | Category 6 completeness |
| No consensus estimates | `earnings_estimates` empty (audit C) | Category 14 "beat or miss", FR-03 earnings momentum |
| Insider and SAST empty | `insider_sast` 0 rows | FR-02 ownership, governance |
| Analytics layer frozen at 12 Oct | Audit C; fix in PR #414 | Category 16 movers, sector snapshot |
| IV history stops at 26 Oct | `record_iv_history` cron not installed (audit C) | Category 11 IV changes |
| Trendlyne ownership and deals stale | STALE since 22 Oct | Ownership trends |
| `NSE_FINANCIALS` shows NEVER_SUCCEEDED, yet the table holds 2,208 symbols | Feed status vs. table | Which loader is canonical is unclear; needed for reproducibility (§16) |
| No live outcome tracking | `positional_outcomes` 0 rows (audit C) | Category 10 step 9, §18 |

---

## 8. Owner decisions needed

1. **SEBI posture** for the Executive Insight Card and valuation verdicts (Categories 2, 15, 18). Options: a methodology-labelled score band with no verdict word, or confirmation that Nivesh's registration covers ratings.
2. **Contract path:** extend `visual-answer-v1` to v2 by adding fields (recommended), or adopt §13's shape as a replacement.
3. **Legal intelligence scope:** start from exchange-disclosed litigation (Tier 1, available now), or invest in court and tribunal sources (licensing, effort).
4. **Paid Tier-2 data:**
   - consensus estimates (needed for beat or miss);
   - a news wire (industry and geopolitical news);
   - macro history (RBI DBIE and MoSPI are free Tier 1, but need loaders).
5. **Strategy-validation home** after Strategy Lab's removal on 29 Oct: chat dashboard only, or also Chart Analysis.
6. **Save and share:** private saved reports only, or shareable links (privacy of portfolio-linked answers).
7. **Quality budget:** an LLM-judge per answer (cost) versus deterministic checks plus a weekly human-graded sample.

---

## 9. Recommended sequence (PRD phases on top of the current release stack)

1. **Finish what is open:**
   - merge #419 and #422;
   - complete Q15, the suggestion engine and Open Positions (branches above).
2. **Phase 1 foundation, small steps that unblock everything:**
   - extend `visual-answer-v1` to v2 by adding fields: evidence class, source tier, `source_url`, retrieval time, `methodology`, per-block `source_refs`;
   - new block types `line`, `timeline`, `scenario`, `payoff`, `compare`;
   - a numeric-grounding check;
   - answer blueprints as data, starting from the 13 built intents.
3. **Phase 1 blueprints on data that already exists:**
   - `stock_360` (financials, ownership, filings retrieval with links, technicals, peers);
   - Technical (indicator lines);
   - Results (saying plainly that no consensus exists);
   - Peer compare;
   - Portfolio visual;
   - Options chain and payoff;
   - Pre-market briefing.
4. **Data work in parallel** (operations, then owner): SEBI feed running and registered, macro indicator loaders, BSE 403, IV cron, PR #414.
5. **Phase 2:**
   - news and regulatory timelines;
   - macro history plus a curated transmission map (the `policy.py` pattern, never LLM-inferred);
   - legal events from exchange disclosures.
6. **Phase 3:** a strategy-validation dashboard on the AI Trader backtester (walk-forward and holdout already exist).
7. **Phase 5:**
   - a store for quality evaluations;
   - graded evaluation sets per category (extending `rag_eval.py`);
   - live outcome tracking for ideas.

---

## 10. Queries run (31 Oct 2026, staging warehouse, read-only, aggregates only)

| Read | Result |
|---|---|
| `nidp.sebi_circulars` | 0 rows |
| `nidp.macro_releases` | 375 rows, furthest release 2027-12-08 |
| `nidp.fred_macro` | 0 rows |
| `nidp.nse_financials_quarterly` | 2,208 symbols, latest period 2026-09-30, max 29 / mean 10.66 quarters per symbol |
| `nidp.corporate_announcements` | 196,864 rows, last ingested 2026-10-30 23:50 IST |
| `nidp.insider_sast` | 0 rows |
| `nidp.shareholding_pattern` | 2,411 symbols, period 2026-09-30 |
| `nidp.documents` by type | announcement_attachment 80,049; financial_results 13,068; annual_report 7,039; press_release 4,538; investor_presentation 2,966; concall_transcript 2,860 (all to 2026-10-30) |
| `nidp.document_chunks` | 2,100,220 |
| Absent tables | `legal_events`, `court_orders`, `regulatory_events`, `news_events`, `macro_indicators`, `stock_fundamentals`, `sector_scores_daily` |
| `v_feed_status` | FRED_MACRO NEVER_SUCCEEDED; NSE_FINANCIALS NEVER_SUCCEEDED; macro_calendar PARTIAL (31 Oct); NIDP_DOCUMENT_PARSER OK (31 Oct); trendlyne_deals and trendlyne_ownership STALE (22 Oct); no SEBI row |
