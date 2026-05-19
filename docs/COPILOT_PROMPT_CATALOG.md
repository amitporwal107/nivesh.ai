# Copilot Prompt Catalog — Persona × Question × Category × Agent Mapping

**Status:** Draft for review (not yet wired into code).
**Source of truth for:** the `_PROMPT_TEMPLATES` array in [backend/routes/copilot_prompts.py](../backend/routes/copilot_prompts.py).
**Total entries:** 110 (10 personas × 10 questions + 10 universal). The 10 product-defined "starter chips" are a derived subset of the universal entries — see bottom of file.

## Conventions

**Categories** (the 5 product taxonomy buckets):
- `PH` — Portfolio Health
- `PA` — Performance Analysis
- `RD` — Risk & Diversification
- `TX` — Tax Optimization
- `GP` — Goal Planning

**Agents** (LangGraph specialist nodes, all under [backend/nidp/services/copilot_agent/nodes/](../backend/nidp/services/copilot_agent/nodes/)):
- `portfolio` — `portfolio_analyst`
- `mf` — `mf_analyst`
- `stock` — `stock_analyst`
- `risk` — `risk_analyst`
- `goal` — `goal_planner`
- `market` — `market_analyst`
- `recommendation` — `recommendation` (also runs "educator" sub-mode against knowledge_base.md in Phase 3)

**Tiering** (existing field, controls UI prominence):
- `primary` — single hero card (1 per response)
- `secondary` — compact cards (2–3 per response)
- `advanced` — collapsed chips

**Phase markers in Tools column:**
- (P1) — tool exists today, just needs wiring
- (P2) — new tool added in Phase 2 of the implementation plan
- (P3) — educator knowledge-base lookup (Phase 3)

---

## 1. Salaried Beginner Investor — persona: `salaried_beginner`

Framing: plain language, FD as the reference yardstick, avoid jargon, one action at a time.

### Portfolio Holdings Questions

| # | Cat | Tier | Label (chip) | Routes to | Tools |
|---|-----|------|--------------|-----------|-------|
| 1 | RD | primary | Is my portfolio well diversified? | portfolio | get_portfolio_summary, get_concentration_report (P1) |
| 2 | RD | secondary | Am I taking too much risk? | risk | get_risk_metrics (P1) |
| 3 | PA | secondary | Which mutual funds are underperforming? | mf | get_mf_performance, get_mf_scorecard (P1) |
| 4 | PH | secondary | Should I sell any of my stocks or funds? | portfolio | get_rebalance_plan, get_tax_harvest_candidates (P1) |
| 5 | PA | advanced | How much return am I making vs FD? | portfolio | get_portfolio_xirr (P1), compare_to_fd (P2) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | GP | secondary | How much should I invest every month? | goal | required_sip via goal_engine (P1) |
| 7 | PH | advanced | Which mutual funds are best for long-term wealth? | recommendation | get_top_funds (P1) |
| 8 | GP | advanced | Should I invest in stocks or mutual funds? | recommendation | educator (P3) |
| 9 | TX | advanced | How do I save tax under Section 80C? | recommendation | educator (P3) |
| 10 | GP | advanced | How much corpus do I need for retirement? | goal | required_lumpsum, monte_carlo_success (P1) |

---

## 2. Mutual Fund Focused Investor — persona: `mf_focused`

Framing: fund-level depth, overlap and expense-ratio focus.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | PH | primary | Do I have too many mutual funds? | portfolio | get_portfolio_summary, get_concentration_report (P1) |
| 2 | RD | secondary | Are any funds overlapping significantly? | mf | get_fund_overlap (P1) |
| 3 | PA | secondary | Which funds are dragging down performance? | mf | get_mf_performance (P1) |
| 4 | GP | secondary | Is my SIP allocation optimal? | mf | get_sip_performance, required_sip (P1) |
| 5 | TX | advanced | Should I switch to direct plans? | mf | get_mf_intelligence (expense_ratio_direct vs regular) (P1) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | PH | secondary | Which funds are best for SIP? | recommendation | get_top_funds (P1) |
| 7 | RD | advanced | Difference between large-cap, flexi-cap, mid-cap? | recommendation | educator (P3) |
| 8 | RD | advanced | How much equity allocation is suitable for my age? | goal | allocation_for_profile (P1) |
| 9 | GP | advanced | Should I continue investing during market corrections? | recommendation | educator (P3) |
| 10 | PA | advanced | How do expense ratios affect returns? | recommendation | educator (P3) |

---

## 3. Direct Equity Investor — persona: `direct_equity`

Framing: valuation/fundamentals depth, sector views.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | PA | primary | Which stocks are overvalued? | stock | get_fundamental (P/E, P/B), stock_scoring exit_score (P1) |
| 2 | PH | secondary | Which stocks have weak fundamentals? | stock | stock_scoring quality_score (P1) |
| 3 | RD | secondary | What is the concentration risk in my portfolio? | portfolio | get_concentration_report (sector + company HHI) (P1) |
| 4 | PA | secondary | Which stocks contribute most to returns? | portfolio | get_portfolio_summary (per-position return) (P1) |
| 5 | PH | advanced | Should I rebalance my holdings? | portfolio | get_rebalance_plan (P1) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | PA | secondary | Which sectors are likely to outperform? | market | sector rotation via daas_client (P1) |
| 7 | RD | advanced | How do I identify undervalued stocks? | recommendation | educator (P3) |
| 8 | PA | advanced | What valuation metrics matter most? | recommendation | educator (P3) |
| 9 | GP | advanced | How do I build a long-term stock portfolio? | recommendation | educator (P3) |
| 10 | RD | advanced | How much cash should I keep? | goal | allocation_for_profile (cash bucket) (P1) |

---

## 4. High Net Worth Investor (HNI) — persona: `hni`

Framing: multi-asset, tax + estate + alternative-asset focus.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | RD | primary | Is my wealth allocation optimal across asset classes? | portfolio | get_portfolio_summary, target_allocator (P1) |
| 2 | RD | secondary | Where is concentration risk highest? | portfolio | get_concentration_report (AMC + sector + company) (P1) |
| 3 | TX | secondary | How tax-efficient is my portfolio? | portfolio | get_full_tax_report (P1) |
| 4 | PH | secondary | Which assets should be rebalanced? | portfolio | get_rebalance_plan, deviation_engine (P1) |
| 5 | RD | advanced | What is my portfolio's downside in a market crash? | risk | run_market_drop_scenario (P2) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | RD | secondary | How should I allocate across equity, debt, gold, international? | goal | allocation_for_profile + international_funds (P1) |
| 7 | TX | advanced | What are the best tax-saving strategies? | recommendation | educator (P3) |
| 8 | PH | advanced | Should I use PMS or AIFs? | recommendation | educator (P3) |
| 9 | GP | advanced | How can I preserve wealth across generations? | recommendation | educator (P3) |
| 10 | GP | advanced | How should I structure estate planning? | recommendation | educator (P3) |

---

## 5. Retirement Planner — persona: `retirement_planner`

Framing: income/withdrawal/inflation lens, downside emphasis.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | GP | primary | Will my current investments be sufficient for retirement? | goal | monte_carlo_success on retirement goal (P1) |
| 2 | RD | secondary | Is my debt allocation adequate? | portfolio | get_portfolio_summary (debt %) (P1) |
| 3 | GP | secondary | How much monthly income can this portfolio generate? | goal | new withdrawal-rate helper (4% rule applied) (P1) |
| 4 | GP | secondary | What is the probability of running out of money? | goal | monte_carlo_success (P1) |
| 5 | PH | advanced | Which assets should be shifted to safer investments? | portfolio | get_rebalance_plan biased to debt (P1) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | GP | secondary | How much corpus do I need? | goal | required_lumpsum (P1) |
| 7 | RD | advanced | How should retirees invest? | recommendation | educator (P3) |
| 8 | GP | advanced | What withdrawal rate is safe? | recommendation | educator (P3) |
| 9 | GP | advanced | How do I protect against inflation? | recommendation | educator (P3) |
| 10 | GP | advanced | Should I invest in annuities? | recommendation | educator (P3) |

---

## 6. Parents Planning for Children — persona: `parents_for_kids`

Framing: goal-progress lens, shortfall-first, insurance overlay.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | GP | primary | Is my child education corpus on track? | goal | goal-progress on linked education goal (P1) |
| 2 | GP | secondary | Are current SIPs sufficient? | goal | required_sip vs current SIP (P1) |
| 3 | GP | secondary | What return assumptions are realistic? | goal | scenario_matrix base/bull/bear (P1) |
| 4 | GP | secondary | How much shortfall exists? | goal | project_corpus_fixed vs target (P1) |
| 5 | PH | advanced | Which investments should be earmarked for education? | portfolio | new goal-asset tagging helper (P1) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | GP | secondary | How much will higher education cost? | recommendation | educator with cost data (P3) |
| 7 | GP | secondary | How much should I invest monthly? | goal | required_sip (P1) |
| 8 | GP | advanced | Should I use equity funds for education planning? | goal | allocation_for_profile (5y guardrail) (P1) |
| 9 | GP | advanced | What if my goal is only 5 years away? | goal | allocation_for_profile (short-horizon rule) (P1) |
| 10 | GP | advanced | How do I protect the goal with insurance? | recommendation | educator (P3) |

---

## 7. Tax-Conscious Investor — persona: `tax_conscious`

Framing: tax-impact lens on every recommendation.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | TX | primary | What are my unrealized capital gains? | portfolio | get_full_tax_report (P1) |
| 2 | TX | secondary | Which holdings can be sold for tax harvesting? | portfolio | get_tax_harvest_candidates (P1) |
| 3 | TX | secondary | Which assets generate tax inefficiency? | portfolio | tax_engine classification breakdown (P1) |
| 4 | TX | secondary | How much tax will I pay if I rebalance? | portfolio | get_rebalance_plan + tax_impact (P1) |
| 5 | TX | advanced | Should I hold or sell before the financial year ends? | portfolio | tax-timing helper (LTCG threshold + 1.25L exemption) (P1) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | TX | secondary | How does capital gains tax work? | recommendation | educator (P3) |
| 7 | TX | advanced | What is tax-loss harvesting? | recommendation | educator (P3) |
| 8 | TX | advanced | Which investments are most tax efficient? | recommendation | educator (P3) |
| 9 | TX | advanced | Should I choose growth or IDCW? | recommendation | compare_idcw_vs_growth (P2) |
| 10 | TX | advanced | How do I minimize taxes legally? | recommendation | educator (P3) |

---

## 8. Conservative Investor — persona: `conservative`

Framing: downside-first, FD-comparable framing, debt focus.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | RD | primary | Is my portfolio too aggressive? | risk | get_risk_metrics + suitability check (P1) |
| 2 | RD | secondary | How much downside risk do I face? | risk | drawdown + scenario_matrix bear (P1) |
| 3 | RD | secondary | How much is allocated to debt and fixed income? | portfolio | get_portfolio_summary (debt %) (P1) |
| 4 | RD | secondary | Which holdings are volatile? | risk | volatility per holding (P1) |
| 5 | PA | advanced | Can I earn better returns than FD with low risk? | portfolio | compare_to_fd (P2) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | RD | secondary | What are safe investment options? | recommendation | educator (P3) |
| 7 | PH | advanced | Which debt funds are suitable? | recommendation | get_top_funds (debt category) (P1) |
| 8 | RD | advanced | How much equity should I own? | goal | allocation_for_profile (P1) |
| 9 | RD | advanced | Is gold a safe hedge? | recommendation | educator (P3) |
| 10 | GP | advanced | How do I preserve capital? | recommendation | educator (P3) |

---

## 9. Active Trader — persona: `active_trader`

Framing: realized P&L, momentum, sector rotation. (Win-rate / risk-reward deferred per scope decision; questions 5 + 9.5 surface a "coming soon" placeholder until Phase 3.)

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | PA | primary | Which positions are generating the best returns? | portfolio | get_portfolio_summary (per-position return ranked) (P1) |
| 2 | RD | secondary | Where am I overexposed? | portfolio | get_concentration_report (P1) |
| 3 | PA | secondary | What is my realized vs unrealized P&L? | portfolio | trading_metrics.realized_pnl via capital_gains_engine FIFO (P2) |
| 4 | PA | secondary | Which trades are consistently losing? | portfolio | per-position loss ranking from holdings (P1) |
| ~~5~~ | ~~PA~~ | — | ~~What is my win ratio and risk-reward?~~ | — | **Hidden until P3** — `trading_metrics` full primitives ship in Phase 3 |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | PA | secondary | Which sectors are showing momentum? | market | sector momentum via daas_client (P1) |
| 7 | PA | advanced | What is an effective swing trading setup? | recommendation | educator (P3) |
| 8 | RD | advanced | How do I manage risk? | recommendation | educator (P3) |
| 9 | RD | advanced | What position size should I use? | recommendation | educator (P3) |
| 10 | PA | advanced | How do I improve trading discipline? | recommendation | educator (P3) |

---

## 10. NRI / Global Investor — persona: `nri_global`

Framing: currency, geography mix, tax-treaty hints.

### Portfolio Holdings Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 1 | RD | primary | How much of my portfolio is India-focused? | portfolio | get_currency_exposure (P2) |
| 2 | RD | secondary | Do I have adequate global diversification? | portfolio | international_funds.classify (P1) |
| 3 | RD | secondary | What are my currency risks? | portfolio | get_currency_exposure (P2) |
| 4 | TX | secondary | Which investments are tax inefficient (NRI)? | portfolio | get_full_tax_report + NRI-rule overlay (P1) |
| 5 | PH | advanced | Should I rebalance between geographies? | portfolio | international_funds recommend + rebalance (P1) |

### General Questions

| # | Cat | Tier | Label | Routes to | Tools |
|---|-----|------|-------|-----------|-------|
| 6 | PA | secondary | Should I invest in India or abroad? | recommendation | educator (P3) |
| 7 | TX | advanced | How do tax treaties work? | recommendation | educator (P3) |
| 8 | PH | advanced | Which international ETFs are suitable? | recommendation | international_funds.recommend (P1) |
| 9 | PA | advanced | How do currency movements affect returns? | recommendation | educator (P3) |
| 10 | RD | advanced | What is the best allocation for global diversification? | recommendation | educator (P3) |

---

## Universal — persona: `*` (shown to all, default for unprofiled users)

| # | Cat | Tier | Label | Routes to | Tools | Starter chip? |
|---|-----|------|-------|-----------|-------|---------------|
| U1 | PH | primary | Is my portfolio healthy? | portfolio | get_portfolio_summary, v3_scoring portfolio_score (P1) | **Analyze My Portfolio** |
| U2 | RD | secondary | Am I properly diversified? | portfolio | get_concentration_report (P1) | **Check Diversification** |
| U3 | PH | secondary | Which investments should I sell? | portfolio | get_rebalance_plan + get_tax_harvest_candidates (P1) | — |
| U4 | PA | secondary | What is my expected long-term return? | goal | solve_required_return + project_corpus_fixed (P1) | — |
| U5 | RD | secondary | How much risk am I taking? | risk | get_risk_metrics (P1) | — |
| U6 | RD | advanced | What happens if markets fall 20%? | risk | run_market_drop_scenario (P2) | **Stress Test My Portfolio** |
| U7 | TX | advanced | How can I reduce taxes? | portfolio | get_full_tax_report + tax_harvest (P1) | **Tax Optimization** |
| U8 | PH | advanced | What should I buy next? | recommendation | get_top_funds + sector-gap (P1) | **What Should I Do Next?** |
| U9 | GP | advanced | Am I on track to meet my goals? | goal | goal-progress (P1) | **Goal Progress** |
| U10 | RD | advanced | How do I compare with recommended allocations? | portfolio | deviation_engine + target_allocator (P1) | **Compare Against Ideal Allocation** |

### 10 Starter Chips (derived)

The product spec lists 10 starter chips. 7 map directly to universal entries above (marked in the **Starter chip?** column). The remaining 3 are:

| Chip | Sourced from | Notes |
|------|--------------|-------|
| **Find Underperformers** | Persona 1 Q3 / Persona 2 Q3 | Add `starter: true` flag on `mf_performance` template; shown as chip when `underperformer_count >= 1` |
| **Identify Overlap** | Persona 2 Q2 / existing `overlap` template | Already in catalog; just gets `starter: true` flag |
| **Rebalance Suggestions** | U3 variant | Re-uses `get_rebalance_plan`; chip label `"Rebalance Suggestions"` is just a UI alias |

---

## Catalog Stats

**By category (110 entries total):**

| Category | Count | Notes |
|----------|-------|-------|
| Portfolio Health (PH) | 19 | |
| Performance Analysis (PA) | 21 | |
| Risk & Diversification (RD) | 32 | Largest bucket — diversification questions span most personas |
| Tax Optimization (TX) | 17 | |
| Goal Planning (GP) | 21 | |

**By agent routing:**

| Agent | Count | Notes |
|-------|-------|-------|
| portfolio_analyst | 31 | |
| mf_analyst | 5 | Concentrated in MF-Focused persona |
| stock_analyst | 2 | Direct-Equity persona |
| risk_analyst | 8 | |
| goal_planner | 21 | |
| market_analyst | 3 | Sector momentum, sector rotation |
| recommendation (incl. educator) | 40 | The educator mode (P3) covers 32 of these — these are the "general" questions per persona |

**By phase blocker:**

| Phase | Entries gated on it | Phase work needed |
|-------|---------------------|-------------------|
| P1 only | 70 | Just persona wiring + catalog + intent regex |
| Needs P2 | 8 | `compare_to_fd`, `run_market_drop_scenario`, `compare_idcw_vs_growth`, `get_currency_exposure`, realized P&L block |
| Needs P3 | 32 | Educator knowledge-base markdown (~30 short entries) |

---

## Resolved Decisions

1. **Persona codes** — `PersonaType` enum will be **extended** to add `parents_for_kids` and `conservative` (today only a risk-profile category, now also a distinct persona) so enum values align with the 10 product-spec personas exactly. Existing enum values that already map cleanly (`hni_investor` → `hni`, `nri_investor` → `nri_global`, etc.) are aliased.
2. **`active_trader` Q5 (win ratio / risk-reward)** — **hidden** from the prompt list until Phase 3 ships the underlying primitive. Persona 9 portfolio-holdings questions are 4 entries (not 5) until then. Total catalog is **109 entries** during P1/P2, becoming 110 in P3.
3. **Tier balance** — kept as-is: 1 primary + 3–4 secondary + 5–6 advanced per persona.
4. **Educator entries (P3)** — knowledge-base topic list deferred until P3 work starts.
