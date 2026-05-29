# PRD — Persona-Based Recommendation Rules Engine

**Product:** Financial Advisor Agent
**Component:** Recommendation engine (exit / add / consolidate / diversify)
**Status:** Draft for review
**Owner:** _TBD_

---

## 1. Summary

The agent already produces a **quality score and peer rank for every stock and mutual fund** a user holds. This component is the layer on top: it reads those scores plus the user's risk persona, goals, and tax state, and turns them into a ranked, explained set of actions — what to **exit**, what to **add**, what to **consolidate**, and where to **diversify**.

The core principle, carried over from the rebalancing design note: a recommendation is never "this fund scores low, sell it." It is "this fund is below your bar *and* its small-cap risk is above your moderate profile, so trim it and move the money to debt where your plan is underweight." Suitability and goals gate the score, never the other way round.

This PRD defines (a) the **master rules** that apply to every user, (b) the **per-persona rule sets** that calibrate every threshold, and (c) the output contract.

---

## 2. Scope and assumptions

**In scope:** the decision logic that converts existing scores + persona + goals into ranked recommendations, the master rules, the per-persona calibration tables, the recommendation output schema, severity/prioritisation, and tax-aware execution selection.

**Out of scope (already built or handled elsewhere):**
- The scoring and ranking model for stocks and funds — **assumed to exist** and treated as an input.
- Trade execution / broker integration.
- The risk-profiling questionnaire itself (we consume its output).
- Tax filing.

**Assumed scoring contract (input per holding):**

| Field | Meaning |
|---|---|
| `security_id`, `type` | Stock / MF / ETF |
| `category` | large-cap, mid-cap, small-cap, flexi, debt-by-duration, gold, sector, thematic |
| `score` | 0–100 quality score (already computed) |
| `percentile_rank` | rank within its peer category |
| `value`, `weight_pct` | holding value and % of portfolio |
| `overlap_group` | id grouping funds with substantially similar holdings/index |
| `unrealised_gain`, `holding_period`, `exit_load`, `lock_in` | for tax- and cost-aware execution |

The engine is a pure function: `recommend(holdings + scores/ranks, persona, goals, tax_state) → ranked recommendations`. All thresholds below are **configurable defaults**, not hardcoded constants — the numbers are illustrative and meant to be tuned.

> **Note:** Specific Indian capital-gains rules (equity vs. debt fund treatment, exemption limits, holding-period cutoffs) change frequently. The engine must read these from a live tax-rules service, not bake them into logic or copy.

---

## 3. The two persona dimensions

The product uses the word "persona" for two different things. The engine needs both, and they do different jobs.

**3.1 Risk persona (the primary axis).** Derived from the risk score (0–100) as `min(capacity, tolerance)`. One of five types. **This sets the target allocation and therefore every action threshold.**

`Conservative · Moderate · Balanced · Growth · Aggressive`

**3.2 Behavioural persona (the modifier).** Detected from portfolio composition and activity, with a confidence level — e.g. *Mutual Fund Investor (73%, medium)*. This does **not** change the target allocation; it changes **which instruments** the engine recommends and **how** it phrases and sequences actions.

`Mutual Fund Investor · Direct Equity Investor · Active Trader · Income / Dividend Seeker · New / First-time Investor`

**Governing rule:** risk persona decides *what* the portfolio should look like; behavioural persona decides *how* to get there and what to say. When behavioural-persona confidence is low (see §10), the engine softens — smaller moves, confirm before large sells.

---

## 4. Master rules (apply to every user, every persona)

These are the universal invariants. Per-persona tables only change the numbers; they never override these.

1. **Mandatory gates.** No recommendation is generated until a risk persona *and* at least one goal exist. Missing either → prompt the user, don't guess.
2. **Suitability gates score.** A holding that doesn't fit the persona's allowed categories or a goal's horizon is exited or never added — *regardless of how high it scores*. Category-fit is checked before score.
3. **Goal-bucket first, portfolio second.** Recommendations are computed per goal bucket against that bucket's horizon and target, then aggregated. A 25-year retirement bucket and a 3-year house bucket get different verdicts on the same fund.
4. **Governing risk = lower of capacity and tolerance.** When they diverge, flag it; never silently take the higher.
5. **Least-disruptive lever first.** Preference order for closing any gap: redirect new money → trim → sell. Prefer the path that realises no tax.
6. **Every recommendation states its reason** in persona/goal terms, not score terms. ("Below your bar *and* above your risk band" — not "low score.")
7. **Materiality threshold.** Suppress any recommendation that doesn't move portfolio risk, a goal's success probability, or cost/overlap by a meaningful amount. Over-trading is a failure, not a feature.
8. **Severity ordering.** Present recommendations severe → minor (see §8). The top action is always the highest-severity one.
9. **Tax- and cost-aware execution.** Every sell recommendation carries its realised-gain and exit-load impact, and prefers harvesting / exemption-use / staggering where it changes the outcome.
10. **Confidence gating.** Low persona-detection confidence → propose, don't auto-apply; ask the user to confirm the persona before any large exit.
11. **Respect locks and loads.** ELSS lock-ins, exit-load windows, and notice periods are hard constraints — never recommend an action that violates them; defer or route through new money instead.

---

## 5. The four action types

Each action has a generic trigger here; §6 calibrates the thresholds per persona. Two supporting actions — **TRIM** (partial reduce) and **REDIRECT** (point new SIPs/lump sums) — are how most recommendations actually execute, and **HOLD/CONTINUE** is the explicit "no change, and here's why" verdict.

**EXIT — sell the position fully.** Triggered when any of:
- Score below the persona's exit threshold, *and* the holding isn't the best available in a category the persona still needs.
- Category is not allowed for the persona (e.g. small-cap in a Conservative book, any equity in a near-term goal bucket).
- Single-holding weight exceeds the persona cap and the position is low-ranked.
- It's a lower-ranked duplicate inside an `overlap_group` (the survivor is the top-ranked one).

**ADD / INCREASE — buy more, or open a new position.** Triggered when:
- A required category is underweight versus the persona target, *and*
- The candidate's score sits in the persona's add tier (top quartile/decile of its peer group).
- A goal's funding gap calls for more of a specific risk class.
- Executed as REDIRECT (new money) before any sell, per master rule 5.

**CONSOLIDATE — cut the number of holdings.** Triggered when:
- Holding count in a category exceeds the persona's recommended max, or
- Multiple `overlap_group` members duplicate exposure.
- Keep the top-ranked holding(s); trim/exit the rest. This is the dominant action for Mutual Fund Investors (the 111-holdings problem).

**DIVERSIFY — spread into missing categories/sectors.** Triggered when:
- Single sector / category / stock concentration exceeds the persona threshold, or
- A required asset class for the persona is absent (e.g. no debt, no gold).
- Resolved by ADD into the missing class, funded by REDIRECT or by the proceeds of an EXIT.

---

## 6. Per-persona rule sets

All values are **tunable defaults**. Allocation ranges are per goal bucket where goals exist; otherwise portfolio-level.

### 6.1 Target allocation and equity sub-mix

| Persona | Equity | Debt | Gold/Alt | Equity composition (caps) |
|---|---|---|---|---|
| Conservative | 25–35% | 55–65% | 5–10% | Large-cap / index only; mid ≤5%, small 0%, thematic 0% |
| Moderate | 40–50% | 40–50% | 5–10% | Large ≥65% of equity; mid ≤25%, small ≤10%, thematic ≤5% |
| Balanced | 55–65% | 25–35% | ~5% | Large ≥50%; mid ≤30%, small ≤15%, thematic ≤10% |
| Growth | 70–80% | 15–25% | 0–5% | Large ≥40%; mid ≤35%, small ≤25%, thematic ≤15% |
| Aggressive | 80–90% | 5–15% | 0–5% | Large ≥30%; mid ≤40%, small ≤35%, sector/thematic ≤25% |

### 6.2 Action-trigger calibration

| Persona | Exit if score < | Add if score ≥ | Max single holding | Max single sector | Target # holdings |
|---|---|---|---|---|---|
| Conservative | 60 | 75 | 5% | 20% | 8–12 |
| Moderate | 55 | 70 | 8% | 25% | 12–16 |
| Balanced | 50 | 65 | 10% | 30% | 15–20 |
| Growth | 45 | 60 | 12% | 35% | 18–22 |
| Aggressive | 40 | 55 | 15% | 40% | 20–25 |

Reading the table: lower-risk personas demand **higher quality to hold** (higher exit bar) and **tighter concentration**, because they have less risk budget to absorb a misstep. Higher-risk personas tolerate lower-scored, more concentrated, more numerous speculative positions — but still cap them.

### 6.3 Per-persona action posture (plain-language summary)

- **Conservative** — protect capital. Exit anything below large-cap quality or above the volatility band. Consolidate aggressively. Diversify mainly into debt and gold. New money almost always to debt.
- **Moderate** — balance growth and stability. Trim the small/mid tilt back into band, keep top-ranked large/flexi, fund the debt underweight via new SIPs. *(This is the screenshot user's target.)*
- **Balanced** — let equity work but keep a real debt cushion. Mid-cap allowed in moderation; small-cap capped. Consolidate overlap, diversify across sectors.
- **Growth** — equity-led. Wider caps and higher concentration tolerated; debt is a shock absorber, not a core. Exit only clear laggards; add high-conviction top-ranked names.
- **Aggressive** — maximise long-horizon return. Small/mid/thematic actively allowed within caps. Focus shifts to *quality within risk* — exit low-ranked names, consolidate redundant bets, diversify enough to avoid single-name blowups.

---

## 7. Behavioural-persona modifiers

Applied on top of the risk-persona rules above. They change instruments and tone, not targets.

| Behavioural persona | What changes |
|---|---|
| Mutual Fund Investor | Speak in fund terms. **Consolidation is the headline action.** Don't recommend direct stocks unless the user opts in. |
| Direct Equity Investor | Stock-level exit/add by rank; position sizing and sector diversification lead. Flag single-stock concentration hard. |
| Active Trader | Surface STCG cost prominently; warn on churn; prefer holding past the long-term cutoff where it changes tax materially. |
| Income / Dividend Seeker | Favour dividend and debt instruments; frame in yield and stability rather than growth. |
| New / First-time | Fewer, simpler recommendations; education-first; avoid large restructuring in one step. |

---

## 8. Severity and prioritisation

Every recommendation is assigned a severity, which drives ordering and UI treatment:

| Severity | Condition | Treatment |
|---|---|---|
| Aligned | Within the persona band | Quiet confirmation, no action |
| Minor drift | Inside band but trending to edge | Subtle note |
| Mismatch | One band over target, or a meaningful underweight | Amber, "action needed" |
| Severe | Two+ bands over, **or a short-horizon goal in high-risk assets**, or single-name >2× cap | Red, pinned to top |

Within a severity tier, order by impact (risk-band change > goal-probability change > cost/overlap saving).

---

## 9. Tax- and cost-aware execution

For each action the engine selects the *how*, in this preference order:

1. **Redirect new money** — fund the underweight from incoming SIPs/lump sums. Zero realised tax. Always tried first.
2. **Harvest** — pair a sale with offsetting losses where available.
3. **Stagger** — spread sells across periods to stay within annual gain exemptions and across holding-period cutoffs.
4. **Sell now** — only when the risk is urgent (e.g. a near-term goal badly over-exposed) and the tax cost is the lesser evil.

Each sell recommendation must surface: realised gain, short- vs long-term classification, exit load, and lock-in status — all computed against the live tax-rules service.

---

## 10. Confidence and guardrails

- **Persona confidence tiers.** High → engine may present recommendations as ready-to-apply. Medium (e.g. the 73% case) → present as a *proposed plan* and ask the user to confirm the persona before any EXIT above a value threshold. Low → confirm the persona first; restrict to safe, reversible suggestions (consolidation, new-money redirection) until confirmed.
- **No over-trading.** Materiality threshold (master rule 7) plus a cap on number of sell recommendations per cycle.
- **Explainability is mandatory.** A recommendation the user can't understand won't be acted on — and is more likely to be abandoned in the next market scare.
- **Reversibility preference.** When two paths reach the same target, prefer the one that's cheaper to undo.

---

## 11. Conflict resolution (precedence)

When rules point in different directions, resolve top-down:

1. Locks, loads, and regulatory/suitability hard stops.
2. Short-horizon goal protection (de-risk a near-term goal beats any growth argument).
3. Risk-mismatch correction (bring the portfolio into the persona band).
4. Tax efficiency.
5. Score optimisation (upgrade low-ranked to high-ranked within a category).
6. Cost/overlap consolidation.

---

## 12. Recommendation output schema

Each recommendation the engine emits:

| Field | Description |
|---|---|
| `id` | unique |
| `action` | EXIT / ADD / CONSOLIDATE / DIVERSIFY / TRIM / REDIRECT / HOLD |
| `target` | security_id, category, or goal bucket |
| `magnitude` | % and/or ₹ amount |
| `reason` | one sentence in persona/goal terms |
| `severity` | aligned / minor / mismatch / severe |
| `execution` | redirect / harvest / stagger / sell-now |
| `tax_impact` | realised gain, ST/LT, exit load, lock-in flag |
| `confidence` | inherited from persona detection + data quality |
| `expected_effect` | risk-band Δ, score Δ, funding-probability Δ |
| `requires_confirmation` | boolean (from §10) |

The **rebalancing engine output** must read in goal terms, not mechanical terms — *"Reduce small-cap by 8%; your retirement goal is 5 years out and current volatility exceeds your moderate band,"* never *"sell 10% equity, buy debt."*

---

## 13. Worked example — the screenshot user

**Inputs:** risk persona target = **Moderate (3/5)**; detected behavioural persona = **Mutual Fund Investor (73%, medium)**; portfolio ₹1.2 Cr; **111 holdings**; **0% one-year return**; current risk = **Aggressive**; health 68.24.

**Engine output (illustrative, ordered by severity):**

1. **DIVERSIFY / TRIM — Mismatch (amber).** Equity is one band above the Moderate target. Trim small/mid-cap ~8% to bring volatility into band. *Reason: more downside than your plan allows, and the extra risk returned 0% last year.*
2. **CONSOLIDATE — high-value.** 111 → ~15 holdings. Keep the top-ranked fund in each `overlap_group`, exit the duplicates. *Reason: you're paying for overlap, not diversification.*
3. **EXIT.** Funds scoring < 55 (Moderate exit bar) that aren't the best in a needed category, plus small-cap exposure beyond the 10% sub-cap.
4. **ADD via REDIRECT — Mismatch.** Debt is underweight (target 40–50%, currently ~15%). Point new SIPs to short-duration debt + one top-ranked large-cap. *No realised tax.*
5. **Confidence gate.** Detection is *medium* → present as a proposed plan; confirm the Moderate persona before executing the large EXIT in step 3. Steps 2 and 4 (consolidation, new-money) are safe to proceed.

**Expected effect:** risk band Aggressive → Moderate (aligned); holdings 111 → ~15; debt brought toward target; most of the move achieved with little or no realised tax.

---

## 14. Success metrics

- % of accounts whose risk band is **aligned** with their profile (primary).
- Average **health-score lift** after recommendations applied.
- **Recommendation acceptance rate** (and rate by action type).
- **Realised tax per rebalance** (lower is better, for equal alignment).
- **Over-trading rate** — sells per account per cycle (guardrail; should stay low).
- Goal **success-probability lift** for funded goals.

---

## 15. Non-goals and open questions

**Non-goals:** redefining the scoring model; executing trades; tax filing; making registered-advice claims.

**Compliance dependency (not legal advice):** positioning of these outputs (guidance/education vs. personalised investment advice) has regulatory implications under India's investment-adviser framework. Confirm framing, disclaimers, and any registration requirement with compliance before launch.

**Open questions:**
- Confidence threshold for auto-apply vs. confirm — exact cutoffs.
- Re-evaluation cadence — on schedule, on market move, on score change, or all three.
- Materiality threshold values per action type.
- Handling of partially locked instruments (ELSS still in lock-in) within a consolidation.
- Whether to expose the per-persona parameter tables to advanced users for override.

---

*Last updated: 2026-05-29*
