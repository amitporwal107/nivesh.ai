# PRD — Portfolio Concentration Analytics & Remediation

| | |
|---|---|
| **Product area** | Portfolio Risk / Insights |
| **Feature** | Multi-lens concentration analysis, overlap & redundancy detection, verdicts, and remediation engine |
| **Status** | Draft for review |
| **Version** | 1.1 |
| **Author** | Product |
| **Reviewers** | Engineering, Data, Risk, Design, Compliance |
| **Related** | Existing "Exposure" tab (AMC / Sector / Company / Group) + "Overlap" tab (Company / MF overlap) — this PRD specifies their rewrite |
| **Changelog** | v1.1 — added the Overlap & Redundancy module (§8.8), duplicate-plan and closet-index detection, and consolidation as highest-leverage remediation. |

---

## 1. TL;DR

We analyze a user's combined portfolio (direct equity + mutual-fund look-through) and tell them, in plain language, **how concentrated their money is**, **whether that is a problem**, and **exactly what to change to fix it.**

The current feature shows the right charts but fails at the things that matter: its narrative contradicts its own numbers, its verdicts are inconsistent and don't roll up into one story, its recommendations are vague or backwards, and — critically — it shows *overlap* (the same companies and near-identical funds held many times over) as a passive list, disconnected from any verdict or fix. This rewrite introduces a **single computation layer** (so no two elements can disagree), a **deterministic verdict engine** with two headline states — **Balanced** and **Over-concentrated** — plus a middle **Elevated** tier, an **Overlap & Redundancy engine** that explains *why* the portfolio is concentrated and detects duplicate plans and closet-index clusters, and a **remediation engine** that turns each problem into a ranked, concrete, simulated set of actions ("trim X by ₹N — moves you from Over-concentrated to Balanced").

Overlap is the causal layer. The exposure lenses say *what* the user is concentrated in; overlap says *why* — they own many funds that secretly hold the same stocks, sometimes literally the same fund in two plans. Because fixing overlap reduces fund count, fees, and concentration in a single move, **fund consolidation is the highest-leverage remediation we can offer**, and it is wired directly into the recommendation engine.

The unit of value is not the chart. It is the **verdict plus the fix.**

---

## 2. Background & problem statement

The portfolio is analyzed through four lenses — **Sector, Company, AMC, Group**. Each lens is individually useful, but the current implementation has structural defects:

1. **Copy drifts from data.** Headline narrative is generated separately from the numbers it describes, so it can claim "a third of your money is over the 35% cap" while the cards on the same screen show 14% and "0 sectors over cap." Trust dies on contradiction.
2. **Verdicts don't agree or aggregate.** Across the four tabs the user sees two greens, an amber, and a red, with no synthesis. The most important truth — *granular views look diversified, roll-up views are concentrated* — is never stated because no component looks across lenses.
3. **Verdicts aren't gated on data quality.** A lens is called "excellent diversification" while its largest bucket is literally *Unclassified* and a large share of the book is uncategorized.
4. **Banners under-report.** A lens flags only the single worst breach (e.g. one group) when several exceed the threshold.
5. **Recommendations are wrong or empty.** A "fix" instructs the user to "trim" a number while *raising* it, and there is no projection of what the fix achieves.
6. **Data is not normalized.** Weights don't always sum to 100% (a silent residual disappears); the same entity appears twice (e.g. an AMC under two names); financial exposure is fragmented across overlapping buckets; the count of items in a lens is inconsistent between views.
7. **Overlap is inert.** The overlap views are a passive list, disconnected from verdicts and fixes. They miss the most actionable findings entirely: (a) **duplicate Regular + Direct plans of the same fund** (a ~97–80% "overlap" that is really one portfolio held twice, with the Regular plan charging a higher expense ratio for identical holdings) are shown as ordinary overlap rather than flagged as fee waste; (b) **closet-index clusters** (several large-cap funds 50–68% similar to the index and each other) are not called out as redundant; and (c) the overlap metric itself is undefined — "top-25 stocks shared" and "25 pairs analysed" don't tell the user whether overlap is measured by weight or by name count, or over what universe.
8. **Hedged where it should be definitive.** Company-overlap copy says effective exposure "may be larger than any single fund line shows," when the Company lens already computes the exact aggregate. Hedging a number we hold undermines trust.

The result is a feature that *looks* analytical but cannot be trusted or acted on.

### Why rewrite vs. patch
The defects are architectural, not cosmetic. They stem from (a) narrative and metrics being computed in different places, and (b) the absence of an entity-resolution / normalization layer. Patching copy strings will not stop drift. We need one source of truth and one verdict authority.

---

## 3. Goals & non-goals

### Goals
- **G1.** Every surface (headline, cards, bars, verdict, recommendation) is derived from one computation result. Internal contradiction becomes structurally impossible.
- **G2.** Each lens, and the portfolio overall, carries an unambiguous verdict: **Balanced / Elevated / Over-concentrated.**
- **G3.** For every concentration problem, the user gets ranked, concrete, **direction-correct** remediation actions with a **before → after** projection.
- **G4.** Cross-lens synthesis: surface the single most important concentration truth across all lenses (the "concentration ladder").
- **G5.** Data is normalized and trustworthy: entities resolved, weights sum to 100%, classification coverage measured and disclosed.
- **G6.** Overlap is made causal and actionable: detect multi-route holdings, fund-pair similarity, **duplicate Regular/Direct plans**, and closet-index clusters; feed them into the verdict and recommendation engines so consolidation surfaces as the highest-leverage fix.

### Non-goals
- **NG1.** Executing trades automatically. v1 is advisory; action is a deep-link/hand-off (see phasing).
- **NG2.** Forecasting returns or predicting market direction. We measure concentration risk, not expected performance.
- **NG3.** Personalized investment advice in the regulated sense. Output is **educational/illustrative**; see Compliance (§13).
- **NG4.** Optimizing for tax-loss harvesting or factor exposure. Out of scope for v1.

---

## 4. Success metrics

| Metric | Definition | Target (v1) |
|---|---|---|
| Verdict consistency | Automated checks finding a contradiction between any two surfaces | **0** (hard gate, QA) |
| Recommendation correctness | Recs that fail direction/projection validation | **0** (hard gate, QA) |
| Insight engagement | Users who open ≥1 lens detail | Baseline + uplift |
| Remediation engagement | Users who expand ≥1 recommendation | New metric |
| Action rate | Users who act on a recommendation (deep-link follow-through) | New metric |
| Realized de-concentration | Among actors, median reduction in the worst-lens HHI 30 days later | Positive |
| Duplicate-plan resolution | Users with a detected Regular/Direct duplicate who consolidate | New metric |
| Fund-count reduction | Among actors, median reduction in redundant funds held | New metric |
| Trust | "I understand my concentration risk" survey agreement | Uplift vs. control |

---

## 5. Users & primary use cases

**Persona — the unaware-concentrated investor.** Holds 8–15 mutual funds plus some direct stocks, believes they are diversified because they own "many funds," and is unaware that look-through reveals heavy overlap in a few names, sectors, AMCs, or promoter groups.

Use cases:
- **UC1.** "Am I too exposed to any one thing?" — wants a verdict, fast.
- **UC2.** "Where exactly is the risk?" — wants the offending lens and the offending names.
- **UC3.** "What do I do about it?" — wants concrete, ranked actions and the resulting improvement.
- **UC4.** "I think I'm diversified — prove me wrong." — the cross-lens ladder.
- **UC5.** "Why am I concentrated, and am I holding the same thing twice?" — overlap: multi-route holdings, near-identical funds, and duplicate Regular/Direct plans.
- **UC6.** "Which single change helps most?" — the highest-leverage consolidation, fixing several lenses at once.

---

## 6. Scope: lenses & modules

**Four concentration lenses** answer *what* the portfolio is concentrated in:

| Lens | Question it answers | Aggregation key | Default single-name threshold* |
|---|---|---|---|
| **Company** | Exposure to a single issuer across direct equity + fund look-through | Canonical issuer (ISIN/company ID) | single-name cap |
| **Sector** | Exposure to an economic sector after dissolving funds | Single sector taxonomy | sector cap |
| **AMC** | Exposure to a single fund house | Canonical AMC ID | AMC cap |
| **Group** | Exposure to a promoter / business group | Promoter-group mapping | group cap |

**One diagnostic module** answers *why* — and feeds the others:

| Module | Question it answers | Unit |
|---|---|---|
| **Overlap & Redundancy** | Which holdings are duplicated across routes, which funds are near-identical, and which funds are redundant (duplicate plans, closet indexers)? | Holding × route; fund × fund |

The Overlap module is **not a peer lens** — it does not get a Balanced/Over-concentrated verdict of its own. It is the explanatory and remediation layer: it accounts for the Company lens's single-name exposures and supplies the recommendation engine with its highest-leverage consolidation actions (§8.8, §8.5).

\* All thresholds are **named, configurable parameters owned by Risk** (see §10.4). This PRD uses parameter names, not fixed numbers, per the brief.

---

## 7. Core concepts & definitions

- **Look-through:** every mutual fund is dissolved into its latest disclosed underlying holdings before any lens is computed. Direct equity is added at face value. All four lenses are computed on the *combined, dissolved* portfolio.
- **Weight (wᵢ):** an entity's share of total invested value, 0–1, normalized so that within each lens Σwᵢ = 1 (100%).
- **HHI (Herfindahl–Hirschman Index):** Σ wᵢ². Ranges from ~0 (perfectly spread) to 1 (everything in one). The headline dispersion metric.
- **Effective N:** 1 / HHI. "You hold X funds but are effectively concentrated in N." Human-readable companion to HHI.
- **Top-k share:** cumulative weight of the k largest entities. Catches "shoulder" concentration that a single-name cap misses.
- **Classification coverage:** share of the book successfully assigned to a *real* bucket (i.e. not "Unclassified"/"Other"/residual). Gates the verdict.
- **Concentration ladder:** Effective N computed for every lens, presented together, to reveal how diversification changes as holdings are aggregated upward.
- **Route:** a path through which the user holds a company — direct equity, or any fund whose look-through contains it. A multi-route holding is one reachable via 2+ routes.
- **Multi-route (hidden) overlap:** a single company's aggregate exposure assembled across all routes. The Company lens already computes this; overlap makes the *routes* visible.
- **Pairwise fund overlap:** similarity between two funds, defined precisely as the **sum of min(weightᵢ) across commonly-held holdings** (weight-based Jaccard-style overlap), computed over the **full disclosed holdings**, not a top-k subset.
- **Duplicate plan:** two holdings that are the **same underlying scheme** in different plans/options (Regular vs Direct, Growth vs IDCW). Overlap approaches 100% by construction; the difference is fee/structure, not portfolio. Detected by scheme identity, not by overlap score alone.
- **Closet index / redundant cluster:** a set of funds with mutually high overlap and high overlap to a benchmark index, such that holding all of them adds cost without adding diversification.
- **Redundancy:** the share of a fund's portfolio already obtained from cheaper or already-held sources; the basis for consolidation recommendations.

---

## 8. Functional requirements

Requirements are grouped by layer. The architecture is deliberately a pipeline: **Data → Normalization → Metrics → Verdict → Recommendation → Presentation.** Presentation never computes.

### 8.1 Data & look-through layer

- **FR-DATA-1.** Dissolve every mutual fund into its latest disclosed holdings; combine with direct equity into one holdings table. Record the **as-of date** of each fund's disclosure.
- **FR-DATA-2.** Where a fund's look-through is missing or stale beyond a configurable window, the system must **not** silently drop it. It is carried as an explicit "Look-through pending" residual and disclosed in the UI.
- **FR-DATA-3.** Output of this layer is an immutable, timestamped snapshot consumed by everything downstream. The same snapshot powers every surface.

### 8.2 Normalization & entity resolution

- **FR-NORM-1.** **Entity resolution.** Resolve each holding to canonical IDs: issuer (ISIN), AMC, promoter group, and a single sector taxonomy. Duplicate or alias names must collapse to one canonical entity.
- **FR-NORM-2.** **Sum-to-100.** Within each lens, weights must total 100%. Any unassigned remainder is shown as an **explicit residual bucket**, never dropped.
- **FR-NORM-3.** **Classification coverage.** Compute, per lens, the % of the book in real buckets vs. residual/"Unclassified"/"Other." Persist this; the verdict engine consumes it.
- **FR-NORM-4.** **Consistent counts.** The count of entities in a lens is computed once from the snapshot and is identical everywhere it appears.
- **FR-NORM-5.** **Bucket consolidation policy.** Overlapping buckets that represent the same concept are merged under the canonical taxonomy.

### 8.3 Metrics engine

- **FR-METRIC-1.** For each lens compute: largest single weight, top-3 and top-5 share, HHI, Effective N, count, classification coverage, and the full ranked weight vector.
- **FR-METRIC-2.** Metrics are computed only from the normalized snapshot. No metric may be hand-entered or sourced from a separate path.
- **FR-METRIC-3.** **Determinism.** Same snapshot → identical metrics, bit-for-bit.
- **FR-METRIC-4.** **Cross-lens metric:** assemble Effective N for all lenses into the concentration-ladder dataset.

### 8.4 Verdict engine

Three tiers:

| Verdict | Meaning | Color |
|---|---|---|
| **Balanced** | No exposure exceeds its cap; dispersion is healthy; classification coverage is sufficient to certify. | Green |
| **Elevated** | Approaching a cap, *or* dispersion is mediocre, *or* coverage is too low to certify "Balanced." | Amber |
| **Over-concentrated** | One or more exposures breach a cap, or dispersion is poor. Action recommended. | Red |

- **FR-VERDICT-1.** Per-lens decision rule (deterministic, evaluated in order): (1) Over-concentrated if largest ≥ cap or HHI ≥ hhi_high or top-3 ≥ top3_cap or ≥2 entities ≥ soft_cap. (2) Elevated if approaching cap, HHI in mid band, or coverage < min_coverage. (3) Balanced.
- **FR-VERDICT-2.** Coverage gate: A lens may not return Balanced while coverage < min_coverage. At most Elevated, labeled "Diversified but unclassified."
- **FR-VERDICT-3.** Complete breach reporting: list every entity over threshold, not just the worst.
- **FR-VERDICT-4.** Portfolio-level verdict: most severe lens verdict, attributed to the driving lens(es).
- **FR-VERDICT-5.** Explainability: each verdict carries a machine-readable "reasons" array.
- **FR-VERDICT-6.** Thematic exemption (configurable).

### 8.5 Remediation engine

- **FR-REC-1.** Detect & rank problems by severity = (excess over target) × portfolio weight.
- **FR-REC-2.** Gap-to-target: minimum reduction needed to bring exposure inside the target band.
- **FR-REC-3.** Attribute the source: which holdings create the exposure.
- **FR-REC-4.** Direction-correctness validation (hard gate): every recommendation is verified to actually reduce concentration.
- **FR-REC-5.** Redeployment: recommend where freed capital goes.
- **FR-REC-6.** Multi-lens simulation: simulate post-action state across all four lenses.
- **FR-REC-7.** Leverage ranking: risk reduction per rupee moved.
- **FR-REC-8.** Before → after: show projected change to verdict, HHI, Effective N, and offending weight.
- **FR-REC-9.** Constraints: STCG/LTCG, exit loads, lock-ins, minimum lot sizes.
- **FR-REC-10.** Per-lens remediation playbooks (Company, Sector, AMC, Group, Fund redundancy).
- **FR-REC-11.** Consolidation is leverage-ranked alongside trims.
- **FR-REC-12.** Overlap-aware redeployment guard.
- **FR-REC-13.** "No action needed" state when all lenses Balanced.

### 8.6 Cross-lens synthesis

- **FR-SYN-1.** Concentration ladder: Effective N for all lenses, ordered.
- **FR-SYN-2.** Single cross-lens headline insight derived from comparing per-lens verdicts and Effective N.
- **FR-SYN-3.** Tie overlap to the ladder: where Company lens looks diversified but fund redundancy is high, synthesis must state this.

### 8.7 Presentation requirements

- **FR-UI-1.** Four lenses + Overlap, switchable; each showing verdict banner, KPI triplet, ranked bars with threshold marker, and residual bucket.
- **FR-UI-2.** Tab indicators reflect each lens's verdict color.
- **FR-UI-3.** Persistent cross-lens summary (ladder + headline insight) above the lens detail.
- **FR-UI-4.** Remediation panel: ranked recommendations, each expandable with contributors, before→after, and constraints. Highest-leverage action pinned first.
- **FR-UI-5.** Every number and verdict is traceable to a "why" affordance.
- **FR-UI-6.** The UI must not compute, reformat, or re-derive any number or verdict. It renders engine output only.
- **FR-UI-7.** Disclose data freshness and classification coverage on each lens.
- **FR-UI-8.** Overlap surfaces: Company overlap (multi-route) + Fund overlap (pairwise). Duplicate plans and redundant clusters visually distinguished with badge, each linking to consolidation recommendation.

### 8.8 Overlap & Redundancy engine

- **FR-OVL-1.** Multi-route (company) overlap: enumerate every route, compute definitive aggregate weight. Must equal Company lens weight.
- **FR-OVL-2.** Pairwise fund overlap: weight-based overlap over full disclosed holdings (Σ min(wᵢ_A, wᵢ_B)). Legacy "top-25 names" definition deprecated.
- **FR-OVL-3.** Duplicate-plan detection: same scheme in different plan/option by scheme identity, not overlap score. Output discrete `duplicate_plan` finding with cheaper plan identified and expense-ratio differential.
- **FR-OVL-4.** Redundant-cluster / closet-index detection: mutual overlap ≥ cluster_overlap and/or overlap to benchmark ≥ index_overlap.
- **FR-OVL-5.** Redundancy contribution: estimate share of fund's portfolio already available from cheaper/already-held sources.
- **FR-OVL-6.** Feeds, doesn't decide: outputs consumed by recommendation engine and synthesis layer.
- **FR-OVL-7.** Determinism & freshness: same snapshot → identical findings; findings carry disclosure as-of dates.

---

## 9. Detailed walkthrough (illustrative)

1. Engine ingests snapshot → normalizes → computes per-lens metrics.
2. Verdict engine evaluates each lens: Company = Balanced, Sector = Elevated (coverage gate), AMC = Over-concentrated, Group = Over-concentrated.
3. Portfolio verdict = Over-concentrated, attributed to AMC + Group.
4. Ladder shows Effective N falling from Company (high) to AMC/Group (low).
5. Remediation engine ranks problems → finds one action reducing AMC, Group, and Sector simultaneously → pins as highest-leverage.
6. Overlap engine reports duplicate Regular/Direct plan and redundant large-cap cluster → both enter leverage ranking and may outrank the trims.
7. Each recommendation renders with before→after verdict change, redeployment suggestion, and tax/load/lock-in caveats.

---

## 10. Data & configuration requirements

### 10.4 Configurable thresholds (owned by Risk)

| Parameter | Per-lens | Purpose |
|---|---|---|
| `single_name_cap` | ✓ | Hard cap on a single entity's weight |
| `warn_band` | ✓ | Lower edge of "approaching cap" |
| `soft_cap` | ✓ | Multiple-breach trigger |
| `top3_cap` | ✓ | Shoulder-concentration cap |
| `hhi_mid`, `hhi_high` | ✓ | Dispersion bands |
| `min_coverage` | ✓ | Minimum classification coverage to certify Balanced |
| `target_buffer` | ✓ | How far inside the cap a fix should land |
| `staleness_window` | global | Max age of fund disclosure before flagging |
| `cluster_overlap` | global | Mutual fund-pair overlap to flag a redundant cluster |
| `index_overlap` | global | Overlap to a benchmark index to flag closet indexing |
| `max_dest_overlap` | global | Max overlap a recommended destination fund may have with current holdings |

---

## 11. Edge cases

- Single-holding / tiny portfolio: HHI naturally high; explain expected vs. alarm.
- 100% one fund or all cash: "begin diversifying," not "trim."
- Thematic/sector fund: concentrated by design; apply thematic-exemption policy.
- Missing/stale look-through: routed to residual, disclosed; never inflates/deflates silently.
- Debt / gold / international sleeves: classified into own buckets.
- Index funds overlapping by design: flag as redundant (fee efficiency tone, not danger).
- Regular vs Direct of the same scheme: always a `duplicate_plan` finding.
- Different schemes from one AMC family: redundant cluster only if clears `cluster_overlap`.

---

## 12. Non-functional requirements

- **NFR-1.** Single source of truth: one computation service produces payload consumed by all clients.
- **NFR-2.** Determinism & reproducibility: identical inputs → identical outputs.
- **NFR-3.** Explainability: every verdict and number traceable to inputs and the rule that produced it.
- **NFR-4.** Performance: full analysis within load budget; heavy look-through cached on snapshot.
- **NFR-5.** Accuracy gates (CI): fail build if any lens ≠ 100%, duplicate entity survives, surface contradicts engine, recommendation fails direction/projection validation.
- **NFR-6.** Accessibility: color is never the sole carrier of verdict (icon + label too); Indian numbering; screen-reader labels.
- **NFR-7.** Observability: telemetry on verdict shown, lens viewed, recommendation shown/expanded/dismissed/acted.

---

## 13. Compliance & risk

- Advisory framing: recommendations are educational/illustrative, not personalized investment advice.
- Over-trading risk: weigh tax and exit-load drag; prefer low-cost paths.
- Data-staleness risk: disclosed as-of dates; stale funds flagged.
- Misinterpretation risk: plain language with "why" affordance; coverage gate prevents false comfort.

---

## 14. Phasing

- **Phase 1 — Trustworthy insight.** Data + normalization + metrics + verdict engine + cross-lens ladder + Overlap engine (multi-route + pairwise overlap + duplicate-plan detection). Kills all contradictions and surfaces the duplicate-plan finding.
- **Phase 2 — Remediation (advisory).** Recommendation engine with gap-to-target, contributors, before→after, constraints, leverage ranking, and consolidation actions.
- **Phase 3 — What-if & action.** Interactive simulation, one-tap hand-off to trade/rebalance/switch flow, cross-lens optimizer.

---

## 15. Open questions

1. Final threshold values and bands per lens — owned by Risk.
2. Thematic-exemption policy: opt-in by user intent, or always surface with adapted tone?
3. Group taxonomy source of truth and update cadence.
4. Advisory licensing path — Phase 2 ship as education-only, or under advisory?
5. Redeployment suggestions: curated destination universe vs. full market.
6. Pairwise overlap definition: confirm weight-based full-holdings metric; settle index-overlap benchmark set.
7. Duplicate-plan consolidation: education only, or guided switch?

---

## Appendix A — Formulas

- **HHI** = Σ (wᵢ)², wᵢ as fraction of total invested value, Σwᵢ = 1.
- **Effective N** = 1 / HHI.
- **Top-k share** = Σ of the k largest wᵢ.
- **Classification coverage** = 1 − (residual + Unclassified + Other weight).
- **Problem severity** = (current weight − target weight) × current weight.
- **Recommendation leverage** = total cross-lens risk reduction ÷ rupees moved.
- **Pairwise fund overlap** = Σ min(wᵢ_A, wᵢ_B) over holdings i common to funds A and B, on full disclosed holdings (0–1).
- **Route count** = number of distinct paths through which a company is held.

## Appendix B — Glossary

**Look-through** — dissolving a fund into its underlying holdings. **Residual bucket** — explicit catch-all for cash/uncategorized/pending so lenses sum to 100%. **Coverage gate** — rule that blocks a "Balanced" verdict when too much of the book is unclassified. **Concentration ladder** — Effective N across all lenses shown together. **Contributor** — a specific holding adding to a sector/group/AMC exposure. **Route** — a path (direct or via a fund) through which a company is held. **Multi-route / hidden overlap** — a company reachable via 2+ routes. **Duplicate plan** — the same scheme held in two plans/options. **Redundant cluster / closet index** — funds that largely replicate each other and/or an index. **Consolidation** — merging redundant/duplicate funds into the cheapest, most tax-efficient holding.
