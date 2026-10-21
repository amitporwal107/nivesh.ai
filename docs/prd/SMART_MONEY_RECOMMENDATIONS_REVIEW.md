# Requirement Review — Smart Money Recommendations Addendum (§30–42)

- **Reviews:** `docs/prd/SMART_MONEY_RECOMMENDATIONS_ADDENDUM.md` (sections 30–42 of the updated
  "Nivesh Smart Money Intelligence" document, supplied 2026-10-22)
- **Date:** 2026-10-22
- **Reviewer:** Claude (PRODUCT_MANAGER + DOMAIN_EXPERT_ANALYST + FULL_STACK_DEVELOPER)
- **Method:** read the addendum in full; grounded every claim in a repo path or a read-only query
  against `nidp_staging`. Claims marked **[verified]** were re-checked directly for this document;
  claims marked **[reported]** come from the review pass and are labelled where not re-checked.

## Verdict

The §30–42 *philosophy* is sound, and it independently arrives at the same conclusions this
repo's own engineers already reached — separate the accumulation signal from entry readiness,
never let a score alone trigger a buy, never impute missing data as zero. Those are the right
instincts.

As a *requirement*, it is not yet buildable. Four things block it:

1. It re-derives a design written two days earlier with different numbers.
2. Its 25% headline pillar is unscoreable for most of the universe.
3. Its score bands collide with live production bands and are calibrated to a distribution the
   data does not have.
4. It carries no regulatory posture, while the repo's own compliance flag for exactly this
   output is switched **off** pending a registration decision.

None of these is a reason to abandon it. All four are reasons to resolve the requirement before
anyone writes code against it.

---

## 1. It duplicates an existing design

`docs/INTEGRATED_STOCK_ENGINE_DESIGN.md` — *"Status: IN PROGRESS. Design only; no implementation
yet. Source: product brief pasted 2026-10-20"* — already specifies the same engine. **[verified]**

| Concern | §30–42 | INTEGRATED_STOCK_ENGINE_DESIGN.md |
|---|---|---|
| Composite weights | SmartMoney 25 / Fundamental 25 / Technical 20 / Sector 15 / Valuation-Risk 15 | sector 20 / technical 25 / momentum 15 / fundamental 20 / catalyst 10 / valuation_risk 10 |
| Missing data | "must not count as zero" | "Unknown components are excluded… total re-normalised over known weights… carries `coverage_pct`"; below a coverage threshold a stock "cannot be ranked above watchlist" |
| Hard gates | §35, qualitative | pledge limit, interest cover < 1.5 or negative CFO, liquidity floor, invalidated setup → `excluded \| warning` |
| States | 5 states (§33) | `excluded \| avoid \| watchlist \| setup_forming \| trigger_ready \| confirmed` |
| Two-stage split | §33 prose: "keep accumulation and entry readiness separate" | explicit `opportunity_quality` / `trade_readiness` |
| Snapshot | §40.8 prose | `nidp.stock_opportunity_daily(… components jsonb, gates jsonb, status, config_version)` |
| Sector-appropriate fundamentals | §35 "valuation constraints where relevant" | "reuse sector_scoring profiles… no universal P/E or D/E threshold" |

The existing design is **more specific** on exactly the points §30–42 leaves open, and it also
settles API placement (existing `/api/positional` prefix rather than a new one), which §24/§30–42
does not address.

**Action: declare one canonical.** Building §30–42 as written yields a second, differently
weighted, differently named engine for the same job.

## 2. The Smart Money pillar is 25% of a score it cannot currently populate

Measured on staging, latest populated date 2026-10-21, 2,479 symbols.

| Input | State |
|---|---|
| MF holdings history | **13 months**, 2025-09 → 2026-09 (backfilled 2026-10-22) **[verified]** |
| `mf_holdings_deltas` | **1,071,308 rows**, real month-over-month deltas **[verified]** |
| ISIN → priced NSE equity | ~1,067 of 3,478 held ISINs map; **501/501 Nifty 500 covered** [reported] |
| FII/DII ownership QoQ deltas | `fii_pct_change_qoq` **147/2,479 (5.9%)**, dii 5.6% [reported] |
| Aggregate FII/DII flows | `nidp.fii_dii_flows` **16 rows** **[verified]** |
| Deal disclosures | `bulk_deals` 996, `block_deals` **12** **[verified]**; `insider_sast` empty [reported] |
| Market proxies (delivery %, vol z, accumulation_score) | **100% coverage** [reported] |

The direct-evidence half is thin-to-empty outside the MF holdings we just backfilled; the proxy
half is complete. So a "Smart Money" pillar computed today is **mostly delivery percentage and
volume z-scores** — which violates two of §32's own requirements: *"keep direct ownership evidence
separate from indirect price/volume proxies"* and *"do not let missing institutional data count as
a zero factor score."* If you renormalise (the existing engine's behaviour), the 25% silently
redistributes to fundamentals and technicals, and a score named for smart money contains none.

**Action: §32 must state what the pillar does when direct evidence is absent** — gate the stock
out of "smart money" eligibility, or rename the pillar. Renormalising silently makes the name false.

### Fundamental pillar: the distress half is missing
Populated: `roce_pct` 86%, `roe_pct` 84%, `piotroski_score` 84%, `debt_to_equity` 84%, `pe_ttm` 67%.
**Empty (0 rows):** `altman_z_score`, `interest_coverage`, `cfo_pat_ratio`, `ev_ebitda` — root cause
`NSE_FINANCIALS` at `effective_status = NEVER_SUCCEEDED` in `nidp.v_feed_status`. [reported]

Consequence: the distress hard gate the sister design specifies (*interest cover < 1.5 or negative
CFO*) **cannot fire at all today**, and §31 step 3 / §34.1's "cash generation and balance-sheet
quality" have no inputs.

### The other three pillars
- **Technical 20%** — fully scoreable, no objection.
- **Sector/Regime 15%** — index trend and VIX fine (167 indices, 259 sessions). But
  `nidp.sector_rotation_daily` is *designed and never created*, so "sector rotation" is unsourced;
  `sector` on `stock_features_daily` is 22% populated. [reported]
- **Valuation/Risk 15%** — mostly fine; `ev_ebitda` empty, event risk not aggregated per symbol.

## 3. The score bands are already taken, and mis-calibrated

`backend/nidp/services/sector_scoring/composer.py` **[verified]**:

```
if score < 35:  return AVOID
if score < 50:  return REDUCE
...  if score >= 80: return STRONG_BUY
     if score >= 65: return BUY
     return HOLD
```

§32 proposes the **same 80 / 65 / 50 boundaries** with different words ("High-priority candidate /
Watch / Developing / Low priority"). Two vocabularies on one number is a support and UI problem
that will ship as one.

Applied to live data (`nidp.v3_stock_scores_daily`, latest date, 2,480 rows) **[verified]**:

| §32 band | symbols | share |
|---|---|---|
| 80–100 "High-priority candidate" | **1** | 0.0% |
| 65–79 "Watch" | 60 | 2.4% |
| 50–64 "Developing" | 644 | 26.0% |
| <50 "Low priority" | **1,774** | **71.6%** |

min 21.9 · avg 45.2 · max 80.3. A new composite with a 94%-absent Smart Money pillar will be
*more* compressed, not less. **The bands describe an imagined distribution.** Use percentile bands,
or recalibrate to the real one.

Also **[verified]**: `v3_stock_scores_daily.status` and `.gate_failure_reason` exist but are
**NULL on all 2,480 rows** — whoever builds §35 inherits unpopulated columns with no agreed
semantics.

## 4. Regulatory posture is absent, and the relevant flag is off

The addendum contains **zero** occurrences of SEBI, disclaimer, advice, adviser or compliance.
For a document specifying entry levels, stop levels, position quantity and portfolio suitability
for retail users, that is the largest single omission.

`backend/config/allocation_policy.yaml` **[verified verbatim]**:

```yaml
# Regulatory flags - these change what the product may OUTPUT, not the maths.
# Confirm the active registration with Compliance before enabling stock output.
compliance:
  registration: "TBD"                 # one of: RIA | research_analyst | mf_distributor
  direct_stock_recommendations_enabled: false
  mf_recommendations_mode: "named_scheme"
  disclaimer_required: true
```

§30–42 is, in effect, a request to set `direct_stock_recommendations_enabled: true`. The file's own
comment says the registration must be confirmed first. Public disclosure shows **ARN-128459**, an
AMFI *distributor* number — not an RIA or research-analyst registration. [reported]

### Which clauses carry which exposure

| Clause | Exposure |
|---|---|
| §32 bands → "consider a recommendation" at 80–100 | A score-driven buy shortlist for retail is research-analyst output: disclosed methodology, record-keeping, research-report format |
| §33 "Confirmed-strength candidate → evaluate potential entry" | Entry-level output |
| §34.2 "entry conditions, invalidation, target/exit logic and position size" | A trade call with a target price |
| **§36 position sizing against the user's capital, horizon and holdings** | **Personalised — this is the investment-adviser line, not research-analyst. Suitability duties attach.** |
| §37 "expected-return / downside scenarios" | Return projections to retail |
| §40.9 "never present a score as a probability" | Correct. Keep it — it is the one compliance-shaped clause in the document |

§36 is the clause to look at hardest: it is the one that changes the *category* of regulated
activity, not just the content.

### Two standing decisions this contradicts [reported]
- `docs/charting.md`: entry/stop/target/quantity are *"visible only behind the owner allowlist
  until the SEBI RA/IA question (NI-1a) is answered."*
- `docs/charting.md`: *"the TPD composite score ordered trades the wrong way round (its top 5 sat
  at the 0.5th percentile of random)… the headline number goes. Any composite is a research
  object: pre-registered, tested, then shown."* §32 asks for a headline composite with fixed
  weights **before** validation — the reverse of a decision taken *because* a composite failed here.

### Pre-existing exposure found while reviewing — independent of this addendum
**`/pro-trader` renders entry price, stop-loss, target and R:R to any logged-in user, with no
admin gate and no disclaimer. [verified]** `frontend-v5/src/routes.tsx:176` is the only route in
its block not wrapped in `RequireAdmin` (contrast `:174-175`, `:179-181`);
`pages/ProTrader/BasketRow.tsx:71-86` renders the columns; no disclaimer/SEBI/advice string exists
anywhere under `pages/ProTrader/`. This already contradicts the owner-allowlist decision above and
is worth fixing regardless of what happens to §30–42.

## 5. Things already built that §30–42 re-specifies

| §30–42 asks for | Already exists |
|---|---|
| §36 `quantity = floor(risk_budget / abs(entry − stop))` | `backend/routes/positional.py` — `min(qty by risk, qty by allocation, max qty)`, lot rounding, **and it reports which constraint bound**. The addendum's formula is a strict subset [reported] |
| §37 "recommendation card" | Live `/recommendations` route, `components/shared/RecommendationCard.tsx`, `types/recommendation.ts` [reported] |
| §32 "Accumulation Score" | `accumulation_score` exists **twice on different scales**: 0–100 in `nidp.stock_features_daily`, NUMERIC(5,4) i.e. 0–1 in `stock_technical_features`. A third meaning would be the worst outcome — namespace it `smart_money_accumulation_score` [reported] |
| §34.2 "positional / 5–30 sessions" | The shipped Positional Engine's exact scope and product name |
| §40.8 reproducible snapshot | `backend/migrations/023_portfolio_proposal_audit.sql` and `nidp/migrations/151_tpd_paper_trades.sql` (rules hash, model_version, immutability trigger) are the templates to copy [reported] |

## 6. Underspecification that blocks implementation

1. **Gate ordering is contradictory.** §32's band table implies score-then-gate; §31 and §35 imply
   gate-then-rank; §40.3 says gates "override". Three orderings. This decides whether a gated stock
   gets a score at all, and therefore what `status` means.
2. **Not one §35 threshold is a number.** Meanwhile committed numbers exist and are not cited —
   a ₹10 Cr/day 20-session ADTV liquidity floor and 8 named universe gates in
   `docs/SMART_TRADING_DESK_FUNCTIONALITY.md`. §35 will become a fifth gate system with different
   numbers unless it points at those. [reported]
3. **"Don't impute zero" vs "minimum data completeness" are unreconciled** — two different answers
   to the same problem, both requested, with no statement of which wins or what the floor is.
4. **§36's inputs are never sourced.** `risk_budget_per_trade` has no origin; risk profile is
   *optional* at onboarding and persisted best-effort, and a risk *category* ("moderate") is not a
   rupee budget. So §36 correctly yields **no position size for most users** — which §37's card
   layout does not anticipate. `invalidation level` is required in three places and never defined;
   no reward:risk floor is set (the shipped planner rejects RR < 1.5). [reported]
5. **§39/§40.8 point-in-time is not satisfiable from the current schema.** Four blockers:
   - **No publication date on `mf_holdings_monthly`** — only `as_of_month` and `ingested_at`
     **[verified]**. §39's "do not treat a holding as known before it was published" cannot be
     enforced for the pillar the product is named after.
   - `shareholding_pattern.broadcast_at` populated on ~34% of rows. [reported]
   - **`index_constituents` has 3 distinct `as_of_date` values** — "historical universe membership"
     is impossible; survivorship bias is unavoidable and must be disclosed. [reported]
   - History depth: ~13 months of prices, ~10 of features, 13 of holdings, **one market regime**.
     §39 asks for results by sector, market cap and regime with confidence intervals. The sample
     does not exist.
6. **§33's five states have no machine predicates** — "improving market proxies", "acceptable
   fundamentals" are undefined; and they are a *fifth* state vocabulary in this codebase. [reported]
7. **§32's own anti-correlation rule is already violated by its own design**: promoter %, FII % and
   DII % sit inside the existing fundamental/governance pillar, so promoting them to a separate 25%
   Smart Money pillar double-counts them. [reported]

## 7. Sequencing — §41 Phase 1 against reality

Phase 1 is *"use disclosed institutional holdings and market proxies to generate a candidate
universe."* The proxy half works now. The disclosed half is thin outside MF holdings. A Phase-1
candidate list built today is **a delivery-and-volume screen wearing an institutional label** —
precisely what §42 says not to ship.

**Ordered by "cannot be repaired later" first:**

1. **Snapshot `index_constituents` daily, starting now.** 3 dates exist. Every day not captured is
   permanently unbacktestable. This is the only item that *worsens with delay*.
2. **Add a publication-date column to `mf_holdings_monthly`** while the backfill tooling is fresh,
   not after. Without it the Smart Money pillar can never be used point-in-time.
3. **Specify the per-recommendation audit record** (model version, config version, feature snapshot
   ref, gate decisions, rejected-with-reasons) *before* anything reaches a user — §40.8 and the
   record-keeping duty are both retro-unfixable. Templates named in §5 above.
4. Backfill `shareholding_pattern.broadcast_at`.
5. Fix `NSE_FINANCIALS` (`NEVER_SUCCEEDED`) — unblocks interest cover, CFO/PAT, Altman Z, EV/EBITDA,
   i.e. half the Fundamental pillar and the distress gate.
6. Create `nidp.sector_rotation_daily` — the Sector/Regime pillar beyond index trend depends on it.
7. Fix `fii_dii_flows` (16 rows) and `fpi_sector_auc` (stale) for the aggregate flow context that
   §31 step 2 and §32 both name.

**Phase 4 is the real schedule risk.** §41 gates production on §39's thresholds, but §39's sample
cannot be assembled from this history, and `docs/charting.md` records that *every real study to
date found no edge*. Either define Phase 4's thresholds as achievable on this sample, or the
project discovers in Phase 4 that it ships nothing.

---

## Recommended decisions

### Must resolve before building
1. **Declare one canonical document** — §30–42 or `INTEGRATED_STOCK_ENGINE_DESIGN.md`.
2. **Answer the SEBI RA/IA question, or scope §30–42 behind the existing allowlist.** Add a
   regulatory-posture section naming the registration assumed, the disclaimer surface, the
   record-keeping table, and acknowledging that §36 crosses into advisory territory.
3. **Do not ship a headline 0–100 composite before validation** — or overrule
   `docs/charting.md`'s decision in writing, with the reason.
4. **Decide: extend `final_score` / `v3_stock_scores_daily`, or create a fourth score** — and if
   new, say how it relates to the live, user-visible `final_score` and `band`.
5. **Recalibrate or inherit the bands.** 80/65/50 are already `STRONG_BUY/BUY/HOLD` in production,
   and on real data put 1 stock in the top band.
6. **Resolve gate-vs-score ordering and put numbers on every §35 gate**, reconciled with the
   shipped liquidity floor and universe gates.
7. **Replace §36's formula with a reference to the shipped implementation.**
8. **State what the Smart Money pillar does when direct evidence is missing** — gate, or rename.

### Should clarify
9. Namespace new score fields (`smart_money_accumulation_score`).
10. §34.2 "positional" collides with a shipped engine name — reuse or rename.
11. Map §33's five states onto one existing vocabulary; give each a machine predicate.
12. Say whether §37's card is a new surface or an extension of the live one.
13. Resolve promoter/FII/DII double-counting between the new pillar and the existing one.
14. Define `risk_budget_per_trade`'s source; accept that §36 yields no size for most users.
15. Define the invalidation level and a reward:risk floor, or adopt the shipped planner's.
16. Set §39's minimum sample and confidence thresholds against the ≤13-month reality, and state the
    survivorship-bias disclosure (the Strategy Builder UI already carries one).

### Fix regardless of this addendum
17. **`/pro-trader` is ungated and undisclaimed** while showing entry/stop/target/R:R.

---

## Caveats on this review
- Claims marked **[reported]** come from the review pass; the ones marked **[verified]** were
  re-checked directly for this document. Specifically re-verified: the compliance block verbatim,
  `composer.py` band cut-points, `INTEGRATED_STOCK_ENGINE_DESIGN.md` existence/date/weights/states,
  `/pro-trader` route guarding and rendered fields, the live score distribution, the NULL
  `status`/`gate_failure_reason` columns, `mf_holdings_monthly` column list, and the MF
  holdings/delta counts.
- Staging row counts were a moving target: the MF backfill was writing during the review.
- `backend/services/setup_rules.py`, `backend/services/ai_trader/` and
  `frontend-v5/src/pages/CopilotApp/` are **not in this working tree**; claims about them come from
  docs describing `origin/dev`, not from code.
- `docs/Nivesh_PRD_v2.docx` and `docs/Nivesh_Rule_Book_Elaborated.docx` were not opened (binary)
  and may hold the authoritative regulatory position.
- No production system was touched; all queries were read-only `SELECT`s against staging.
