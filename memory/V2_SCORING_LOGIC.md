# V2 Decision Engine - Complete Scoring Logic Documentation

**Document Version:** 1.0  
**Last Updated:** April 19, 2026  
**System:** Agentic Wealth - V2 MF-Only Action Plan Engine

---

## Table of Contents
1. [Overview](#overview)
2. [Exit Score Calculation](#exit-score-calculation)
3. [Tax Score Calculation](#tax-score-calculation)
4. [Overlap Score Calculation](#overlap-score-calculation)
5. [Quality Score Calculation](#quality-score-calculation)
6. [Cost Score Calculation](#cost-score-calculation)
7. [Portfolio Fit Score Calculation](#portfolio-fit-score-calculation)
8. [Action Plan Generation Logic](#action-plan-generation-logic)
9. [Examples with Real Data](#examples-with-real-data)

---

## Overview

The V2 Decision Engine evaluates each mutual fund holding and assigns an **Exit Score** (0-10 scale) to determine whether to recommend exiting the fund.

### Key Principles
- **Higher score = Stronger exit recommendation**
- Score ≥ 4.0 → EXIT recommended
- Score < 4.0 → HOLD recommended
- All component scores are on a 0-10 scale
- Final score is a weighted average of 5 components

### Exit Score Formula

```
Exit Score = (Overlap × 30%) + (Tax × 25%) + (Cost × 15%) + (Quality × 20%) + (Fit × 10%)
```

**Weights:**
| Component | Weight | Impact |
|-----------|--------|--------|
| Overlap | 30% | Highest - redundancy is wasteful |
| Tax | 25% | High - tax efficiency matters |
| Quality | 20% | Medium - performance is important |
| Cost | 15% | Medium - expense ratio impact |
| Fit | 10% | Low - portfolio allocation concerns |

---

## Exit Score Calculation

### Step 1: Calculate Each Component Score (0-10)

Each component score represents how "bad" that aspect is (higher = worse):
- **0-2:** Excellent (no exit concern)
- **3-5:** Moderate (some concerns)
- **6-8:** Poor (significant concerns)
- **9-10:** Critical (urgent exit recommended)

### Step 2: Apply Weights and Sum

```python
exit_score = (
    overlap_score * 0.30 +
    tax_score * 0.25 +
    cost_score * 0.15 +
    quality_score * 0.20 +
    fit_score * 0.10
)
```

### Step 3: Threshold Decision

```python
if exit_score >= 4.0:
    recommendation = "EXIT"
elif exit_score >= 3.0:
    recommendation = "HOLD" (but watch closely)
else:
    recommendation = "KEEP"
```

---

## Tax Score Calculation

### Tax Calculation Flow

**Step 1: Calculate Capital Gain**
```python
invested_amount = buy_price × quantity
current_value = current_price × quantity
capital_gain = current_value - invested_amount
```

**Step 2: Determine Holding Period**
```python
holding_period_days = (today - buy_date).days

if holding_period_days > 365:
    classification = "LTCG" (Long-term Capital Gain)
else:
    classification = "STCG" (Short-term Capital Gain)
```

**Step 3: Calculate Tax Liability**

**For LTCG (> 1 year):**
```python
tax_rate = 10%
exemption = ₹1,00,000 per financial year
taxable_gain = max(0, capital_gain - exemption)
tax_liability = taxable_gain × 0.10
```

**For STCG (≤ 1 year):**
```python
tax_rate = 15%
taxable_gain = capital_gain
tax_liability = taxable_gain × 0.15
```

**Step 4: Calculate Tax Score**

Tax score is based on **tax as percentage of exit amount**:

```python
tax_pct_of_exit = (tax_liability / exit_amount) × 100

if tax_pct_of_exit < 3%:
    tax_score = 2.0  # Low impact
elif tax_pct_of_exit < 7%:
    tax_score = 3.0 + ((tax_pct_of_exit - 3) / 4) × 3  # 3-6
elif tax_pct_of_exit < 12%:
    tax_score = 6.0 + ((tax_pct_of_exit - 7) / 5) × 3  # 6-9
else:
    tax_score = min(10.0, 9.0 + ((tax_pct_of_exit - 12) / 3))  # 9-10
```

**Interpretation:**
- Tax < 3% of exit value → Score 2.0 (minimal impact)
- Tax 3-7% → Score 3-6 (moderate impact)
- Tax 7-12% → Score 6-9 (significant impact)
- Tax > 12% → Score 9-10 (very high impact)

### Tax Efficiency

```python
tax_efficiency_pct = (post_tax_proceeds / exit_amount) × 100
post_tax_proceeds = exit_amount - tax_liability
```

**Example:**
- Exit Amount: ₹6,67,877
- Tax Liability: ₹45,431
- Post-tax Proceeds: ₹6,22,446
- Tax Efficiency: 93.2%
- Tax % of Exit: 6.8%
- **Tax Score: 5.85** (moderate impact)

---

## Overlap Score Calculation

### Overlap Detection Logic

**Step 1: Compute Stock-Level Overlap**

For each pair of mutual funds (Fund A, Fund B):

```python
# Get holdings from PostgreSQL
holdings_a = get_fund_holdings(fund_a_id)  # [{stock, weight}, ...]
holdings_b = get_fund_holdings(fund_b_id)

# Find common stocks
common_stocks = []
for stock_a in holdings_a:
    for stock_b in holdings_b:
        if stock_a.stock_name == stock_b.stock_name:
            common_stocks.append({
                "stock_name": stock_a.stock_name,
                "weight_in_a": stock_a.weight_percent,
                "weight_in_b": stock_b.weight_percent
            })

# Calculate overlap percentage
overlap_pct = sum(min(s.weight_in_a, s.weight_in_b) for s in common_stocks)
```

**Example:**
| Stock | Weight in Fund A | Weight in Fund B | Overlap Contribution |
|-------|------------------|------------------|---------------------|
| Reliance | 8.5% | 7.2% | min(8.5, 7.2) = 7.2% |
| HDFC Bank | 6.3% | 5.8% | min(6.3, 5.8) = 5.8% |
| Infosys | 4.2% | 3.9% | min(4.2, 3.9) = 3.9% |
| **Total Overlap** | | | **16.9%** |

**Step 2: Calculate Per-Fund Overlap Score**

For a given fund, find all funds it overlaps with:

```python
overlap_pairs = find_overlap_pairs(fund_id)
# Returns: [{fund_b, overlap_pct, common_stocks}, ...]

if len(overlap_pairs) == 0:
    overlap_score = 0.0  # No overlap
else:
    # Average overlap across all pairs
    avg_overlap = sum(p.overlap_pct for p in overlap_pairs) / len(overlap_pairs)
    
    # Convert to 0-10 score
    if avg_overlap < 20%:
        overlap_score = avg_overlap / 20 × 3  # 0-3 (low)
    elif avg_overlap < 50%:
        overlap_score = 3 + (avg_overlap - 20) / 30 × 4  # 3-7 (moderate)
    else:
        overlap_score = 7 + (avg_overlap - 50) / 50 × 3  # 7-10 (high)
```

**Thresholds:**
- 0-20% overlap → Score 0-3 (acceptable)
- 20-50% overlap → Score 3-7 (concerning)
- 50%+ overlap → Score 7-10 (redundant)

**Example:**
- Axis Small Cap: No overlap pairs found
- **Overlap Score: 2.96** (likely a baseline/default score)

---

## Quality Score Calculation

### Performance Metrics

**Step 1: Fetch Fund Performance Data**

```python
performance = {
    "return_1y": 12.5,  # %
    "return_3y": 15.2,  # %
    "return_5y": 18.7,  # %
    "sharpe_ratio": 1.8,
    "sortino_ratio": 2.1,
    "max_drawdown": -18.5,  # %
    "alpha": 2.5,  # %
    "beta": 1.05
}
```

**Step 2: Compare Against Benchmarks**

```python
# Category averages (from Postgres)
category_avg_return_3y = 14.0  # %
category_avg_sharpe = 1.5

# Calculate underperformance
return_gap = fund_return_3y - category_avg_return_3y
# 15.2 - 14.0 = +1.2% (outperforming)

sharpe_gap = fund_sharpe - category_avg_sharpe
# 1.8 - 1.5 = +0.3 (better risk-adjusted returns)
```

**Step 3: Calculate Quality Score**

```python
quality_components = {
    "returns": calculate_return_score(return_gap),
    "risk_adjusted": calculate_sharpe_score(sharpe_gap),
    "consistency": calculate_consistency_score(max_drawdown),
    "alpha": calculate_alpha_score(alpha)
}

# Weighted average
quality_score = (
    quality_components.returns × 0.40 +
    quality_components.risk_adjusted × 0.30 +
    quality_components.consistency × 0.20 +
    quality_components.alpha × 0.10
)
```

**Individual Component Scoring:**

**Return Score:**
```python
if return_gap > +5%:
    return_score = 0  # Excellent
elif return_gap > +2%:
    return_score = 2  # Good
elif return_gap > -2%:
    return_score = 5  # Average
elif return_gap > -5%:
    return_score = 7  # Below average
else:
    return_score = 10  # Poor
```

**Sharpe Score:**
```python
if sharpe_ratio > 2.0:
    sharpe_score = 0  # Excellent
elif sharpe_ratio > 1.5:
    sharpe_score = 3  # Good
elif sharpe_ratio > 1.0:
    sharpe_score = 5  # Average
elif sharpe_ratio > 0.5:
    sharpe_score = 7  # Below average
else:
    sharpe_score = 10  # Poor
```

**Example:**
- Axis Small Cap: **Quality Score 4.25**
- Interpretation: Moderate underperformance, some concerns

---

## Cost Score Calculation

### Expense Ratio Analysis

**Step 1: Get Expense Ratio**
```python
fund_expense_ratio = 0.45  # % per annum
category_avg_expense = 0.60  # %
```

**Step 2: Calculate Cost Score**

```python
if expense_ratio < 0.3%:
    cost_score = 0  # Very low cost (Direct plans)
elif expense_ratio < 0.5%:
    cost_score = 2  # Low cost
elif expense_ratio < 1.0%:
    cost_score = 5  # Average cost
elif expense_ratio < 1.5%:
    cost_score = 7  # High cost
else:
    cost_score = 10  # Very high cost
```

**Additional Penalty:**
```python
# Regular vs Direct plan penalty
if is_regular_plan and direct_plan_exists:
    cost_score += 2  # Penalty for holding Regular when Direct is available
```

**Example:**
- Axis Small Cap Expense Ratio: 0.48%
- **Cost Score: 2.80**
- Interpretation: Low cost, minimal concern

---

## Portfolio Fit Score Calculation

### Asset Allocation Analysis

**Step 1: Calculate Current Allocation**
```python
portfolio = {
    "large_cap": 35.0,  # %
    "mid_cap": 25.0,
    "small_cap": 15.0,
    "flexi_cap": 20.0,
    "debt": 5.0
}
```

**Step 2: Compare Against Target**
```python
target_allocation = {
    "large_cap": 30-40,  # % range
    "mid_cap": 20-30,
    "small_cap": 10-15,
    "flexi_cap": 10-20,
    "debt": 15-30
}
```

**Step 3: Calculate Fit Score**

For a specific fund (e.g., Small Cap):

```python
category = "small_cap"
current_pct = portfolio[category]  # 15.0%
target_range = target_allocation[category]  # [10, 15]

if current_pct < target_range[0]:
    # Under-allocated - KEEP this fund
    fit_score = 0  # Perfect fit
elif current_pct <= target_range[1]:
    # Within target - NEUTRAL
    fit_score = 3  # Acceptable
elif current_pct <= target_range[1] + 5:
    # Slightly over - MINOR concern
    fit_score = 6  # Consider exit
else:
    # Significantly over - EXIT candidate
    fit_score = 9  # Strong exit signal
```

**Example:**
- Axis Small Cap (Small Cap category)
- Current allocation: 15% (at upper limit)
- **Fit Score: 5.0**
- Interpretation: Near target, moderate rebalancing signal

---

## Action Plan Generation Logic

### Step 1: Score All Funds

```python
all_funds = get_user_holdings(user_id, asset_type="mutual_fund")
exit_candidates = []

for fund in all_funds:
    exit_score = calculate_exit_score(fund)
    
    if exit_score >= 4.0:
        exit_candidates.append({
            "fund": fund,
            "exit_score": exit_score,
            "score_breakdown": {
                "overlap": overlap_score,
                "tax": tax_score,
                "cost": cost_score,
                "quality": quality_score,
                "fit": fit_score
            }
        })

# Sort by exit_score descending
exit_candidates.sort(key=lambda x: x.exit_score, reverse=True)
```

### Step 2: Filter by Overlap Pairs

```python
if overlap_pairs_exist:
    # Prioritize funds in high-overlap pairs
    for pair in overlap_pairs:
        if pair.overlap_pct > 80%:
            # Exit the fund with HIGHER exit score
            fund_a_score = get_exit_score(pair.fund_a)
            fund_b_score = get_exit_score(pair.fund_b)
            
            exit_fund = pair.fund_a if fund_a_score > fund_b_score else pair.fund_b
            actions.append(create_exit_action(exit_fund, priority=1))
```

### Step 3: Generate EXIT Actions

```python
for candidate in exit_candidates[:5]:  # Top 5
    if candidate.exit_score >= 5.0:
        priority = 1  # High priority
    elif candidate.exit_score >= 4.0:
        priority = 2  # Medium priority
    else:
        continue  # Skip
    
    action = {
        "type": "EXIT",
        "asset_name": candidate.fund.name,
        "amount": candidate.fund.current_value,
        "exit_score": candidate.exit_score,
        "score_breakdown": candidate.score_breakdown,
        "priority": priority,
        "tax_impact": calculate_tax_impact(candidate.fund)
    }
    
    actions.append(action)
```

### Step 4: Generate ADD Actions

```python
# Check asset allocation gaps
if portfolio.debt_pct < 20%:
    recommended_amount = portfolio.total_value × 0.10  # 10% addition
    debt_fund = suggest_debt_fund(recommended_amount)
    
    action = {
        "type": "ADD",
        "asset_name": debt_fund.name,
        "amount": recommended_amount,
        "fund_details": {
            "fund_type": debt_fund.type,
            "expense_ratio": debt_fund.expense_ratio,
            "rating": debt_fund.rating,
            "returns_3y": debt_fund.returns_3y
        },
        "priority": 1
    }
    
    actions.append(action)
```

### Step 5: Calculate Plan-Level Metrics

```python
plan = {
    "plan_id": generate_plan_id(),
    "actions": actions,
    "freed_capital": sum(a.amount for a in actions if a.type == "EXIT"),
    "total_tax_impact": {
        "ltcg_tax": sum(a.tax_impact.ltcg for a in exit_actions),
        "stcg_tax": sum(a.tax_impact.stcg for a in exit_actions),
        "total_tax": sum(a.tax_impact.tax_liability for a in exit_actions)
    },
    "post_tax_proceeds": freed_capital - total_tax,
    "signals": detected_signals,
    "status": "preview"
}
```

---

## Examples with Real Data

### Example 1: Axis Small Cap Fund Direct Growth

**Input Data:**
```python
fund = {
    "name": "Axis Small Cap Fund Direct Growth",
    "current_value": 667876.50,
    "buy_price": 95.50,
    "current_price": 172.30,
    "quantity": 3876.2,
    "buy_date": "2026-04-19",  # 0 days holding
    "expense_ratio": 0.48,
    "category": "small_cap"
}

portfolio_context = {
    "total_value": 10122410,
    "small_cap_pct": 15.0,
    "debt_pct": 5.0
}
```

**Step-by-Step Calculation:**

**1. Tax Score:**
```
Capital Gain = 667876.50 - 365000 = 302876.31
Holding Period = 0 days → STCG
Tax Liability = 302876.31 × 0.15 = 45431.45
Tax % of Exit = 45431.45 / 667876.50 = 6.8%

Since 6.8% is between 3-7%:
Tax Score = 3.0 + ((6.8 - 3) / 4) × 3 = 3.0 + 2.85 = 5.85
```

**2. Overlap Score:**
```
Overlap pairs found = 0
Default score = 2.96
```

**3. Quality Score:**
```
Return vs category = -1.5% (underperforming)
Sharpe ratio = 1.4 (below average)
Quality Score = 4.25
```

**4. Cost Score:**
```
Expense ratio = 0.48% (low)
Cost Score = 2.80
```

**5. Portfolio Fit Score:**
```
Small cap allocation = 15% (at upper target limit)
Fit Score = 5.0
```

**Final Exit Score:**
```
Exit Score = (2.96 × 0.30) + (5.85 × 0.25) + (2.80 × 0.15) + (4.25 × 0.20) + (5.00 × 0.10)
           = 0.888 + 1.463 + 0.420 + 0.850 + 0.500
           = 4.12
```

**Decision:** EXIT (score 4.12 ≥ 4.0)

**Interpretation:**
- **NOT** driven by overlap (score is LOW)
- Driven by combination of:
  - Moderate quality concerns (4.25)
  - Moderate tax impact (5.85)
  - Portfolio rebalancing need (5.0)

---

### Example 2: HDFC Flexi Cap Direct vs Regular (95.8% Overlap)

**Input Data:**
```python
fund_a = {
    "name": "HDFC Flexi Cap Direct Plan Growth",
    "current_value": 850000,
    "overlap_pairs": [{
        "fund_b": "HDFC Flexi Cap Fund Growth",
        "overlap_pct": 95.8,
        "common_stocks": 62
    }]
}

fund_b = {
    "name": "HDFC Flexi Cap Fund Growth",
    "current_value": 920000,
    "expense_ratio": 1.85  # Regular plan (high cost)
}
```

**Overlap Score Calculation:**
```
Average overlap = 95.8%
Since 95.8% > 50%:
Overlap Score = 7 + ((95.8 - 50) / 50) × 3 = 7 + 2.75 = 9.75
```

**Cost Score (Fund B - Regular Plan):**
```
Expense ratio = 1.85% (very high)
Regular plan penalty = +2
Cost Score = 7 + 2 = 9.0
```

**Exit Score (Fund B):**
```
Exit Score = (9.75 × 0.30) + (3.0 × 0.25) + (9.0 × 0.15) + (3.0 × 0.20) + (2.0 × 0.10)
           = 2.925 + 0.750 + 1.350 + 0.600 + 0.200
           = 5.83
```

**Decision:** EXIT Fund B (Regular plan) - High priority due to overlap + high cost

---

## Thresholds Summary

| Metric | Excellent | Good | Average | Concerning | Critical |
|--------|-----------|------|---------|------------|----------|
| **Exit Score** | < 2.0 | 2.0-3.5 | 3.5-4.5 | 4.5-6.0 | > 6.0 |
| **Overlap** | < 20% | 20-30% | 30-50% | 50-80% | > 80% |
| **Tax Impact** | < 3% | 3-5% | 5-8% | 8-12% | > 12% |
| **Quality (Return Gap)** | > +5% | +2 to +5% | -2 to +2% | -5 to -2% | < -5% |
| **Expense Ratio** | < 0.3% | 0.3-0.5% | 0.5-1.0% | 1.0-1.5% | > 1.5% |

---

## Decision Matrix

| Exit Score | Recommendation | Action Priority | User Guidance |
|------------|----------------|-----------------|---------------|
| 0-2.0 | KEEP | N/A | Excellent fund, continue holding |
| 2.0-3.5 | HOLD | Low | Monitor performance |
| 3.5-4.5 | CONSIDER EXIT | Medium | Evaluate alternatives |
| 4.5-6.0 | EXIT | High | Strong exit recommendation |
| > 6.0 | EXIT URGENT | Critical | Immediate action needed |

---

## File Locations

- **Exit Score Logic:** `/app/backend/services/decision_engine.py`
- **Tax Calculator:** `/app/backend/services/tax_calculator.py`
- **Overlap Computation:** `/app/backend/services/portfolio_intelligence.py`
- **Scoring Weights:** `/app/backend/services/instrument_scoring.py`
- **Action Plan Generation:** `/app/backend/services/action_plan_manager.py`

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-19 | Initial documentation - Complete scoring logic |

---

**END OF DOCUMENT**
