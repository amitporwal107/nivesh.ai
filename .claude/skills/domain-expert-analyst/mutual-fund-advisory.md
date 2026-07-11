# Pillar 3 — Mutual-Fund Advisory

**Grounding first:** read the repo's real scoring before ranking or recommending a fund —
`backend/nidp/services/mf_analytics_engine/calculator.py`,
`backend/nidp/services/mf_category_ranking/{ranking,peer_set}.py` + `weights.yaml`,
`backend/services/{fund_performance,nav_analytics,debt_scoring}.py`, `v3_scoring.py`.
Pull NAV/return/AUM/expense actuals via DaaS (`copilot_tools/{mf,mf_intelligence,scheme_resolver}.py`)
and check the `amfi_nav` feed is fresh in `nidp.v_feed_status` before quoting a number.
**Any suitability output must carry the compliance framing** enforced by
`backend/nidp/services/copilot_agent/nodes/compliance.py` (see `sebi-compliance.md`).

## Category framework (SEBI scheme categorization)
SEBI's 2017–18 recategorization defines the buckets; the repo mirrors it in
`061_nidp_sebi_category_master.sql`. Always **compare a fund only within its own category**
(peer set), never across.
- **Equity:** Large / Large&Mid / Mid / Small / Multi / Flexi / Focused / ELSS / Value/Contra /
  Dividend Yield / Sectoral-Thematic. (Definitions hinge on the AMFI market-cap list — top 100 =
  large, 101–250 = mid, 251+ = small.)
- **Debt:** by duration/credit — Overnight, Liquid, Ultra-Short, Low, Short, Medium, Corporate
  Bond, Banking&PSU, Gilt, Credit Risk, Dynamic, etc.
- **Hybrid:** Aggressive, Conservative, Balanced Advantage/Dynamic AA, Multi-Asset, Equity Savings,
  Arbitrage. **Solution:** Retirement, Children's. **Other:** Index/ETF, FoF.

## Scheme selection — an advisor's checklist (not one number)
Score across, don't cherry-pick a single trailing return:
1. **Consistency > point return:** rolling returns and their *distribution* over 3/5/7y
   (`095_mf_rolling_returns.sql`), not just last-1y. How often did it beat its category/benchmark?
2. **Risk-adjusted:** Sharpe/Sortino, std dev, **downside/upside capture**, max drawdown,
   **R² / tracking error / information ratio** (`094`, `096_mf_active_share.sql`) — is
   outperformance skill or just higher risk / a benchmark-hugger charging active fees?
3. **Cost:** **TER**, and **direct vs regular** — the direct-plan TER gap compounds massively
   over a goal horizon; **exit load**; churn/turnover.
4. **Portfolio quality:** concentration (top-10 %), sector/stock overlap with the investor's
   existing funds (`fund_clusterer.py`), active share, capacity (is a small-cap too big for its
   mandate?). **AUM** — too small (viability) vs too large (agility) for the category.
5. **Stewardship:** fund-manager tenure & track record, AMC pedigree, mandate drift.
6. **Debt-specific:** credit quality profile, **YTM**, **modified duration**
   (`097_mf_holdings_duration.sql`), and rate view — read `debt_scoring.py` +
   `config/debt_scoring_model.yaml`. Duration risk and credit risk are different risks; name which.

## Suitability — the part that makes it advice
A fund is only "good" *for a specific investor*. Map: **goal** (horizon, amount) → **risk
profile** (`backend/services/risk_profile_chat.py`) → **asset allocation** → category → scheme.
- Horizon drives asset class: short-term goals ≠ equity; equity needs 5y+.
- Risk capacity vs tolerance vs need — reconcile all three; don't let a high tolerance override a
  short horizon.
- Goal math + fund selection: `goal_engine.py`, `goal_fund_picker.py`, `target_allocator.py`.
- SIP/STP/SWP mechanics (`copilot_tools/sip.py`) — SIP for rupee-cost averaging into equity, SWP
  for decumulation, STP to stagger a lump sum in.

## Taxation — state the framework, VERIFY the current rate
Tax rules and thresholds change with each Finance Act — **flag every rate as "verify against the
current Finance Act / CBDT circular"**, don't assert from memory:
- **Equity-oriented funds:** short-term (≤12m) vs long-term (>12m) capital gains, LTCG with an
  annual exemption threshold and a specified rate; STT applies.
- **Debt/other funds:** post-April-2023 purchases are taxed differently from legacy units
  (indexation treatment changed) — **explicitly verify current treatment before advising.**
- **Dividend (IDCW)** taxed at slab; TDS may apply. See the CG engine
  (`copilot_tools/cg.py`, capital-gains services) for how the product computes this.

## Category ranking & derived analytics (real anchors)
`mf_category_ranking/` (peer set + weights), `mf_analytics_engine/calculator.py`,
`mf_derived_refresh/`, `mf_category_enricher.py`, scorecard `052/100/101`, category rank `084/085`.
Read the weights before explaining *why* a fund ranks where it does — the explanation must match
the code, not a generic "good returns."

## Definition of Done for an MF recommendation
Compared within the correct SEBI category; scored on consistency + risk-adjusted + cost +
portfolio quality (real numbers pulled this turn, `amfi_nav` freshness checked); direct-vs-regular
and exit-load called out; mapped to the investor's goal + risk profile (suitability explicit);
tax framing flagged "verify current rate"; compliance disclaimer + no assured-return language;
no fabricated NAV/return/AUM.
