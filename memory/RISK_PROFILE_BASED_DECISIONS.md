# Risk-Profile-Based Action Plan Framework

**Document:** Personalized Exit Decisions Based on Risk Tolerance  
**Date:** April 19, 2026  
**Principle:** Align investment actions with user's risk profile and time horizon

---

## Risk Profile Definitions

### 1. Conservative (Low Risk)
**Characteristics:**
- Age: Typically 50+ or nearing retirement
- Time Horizon: 3-5 years
- Priority: Capital preservation > Growth
- Tax Sensitivity: HIGH (avoid large tax hits)

**Decision Criteria:**
- Only exit if break-even ≤ 3 years
- Avoid exits with >5% tax impact on exit value
- Prefer certainty over optimization
- Willing to pay higher expense ratios to avoid tax

---

### 2. Moderate (Balanced)
**Characteristics:**
- Age: Typically 35-50
- Time Horizon: 5-10 years
- Priority: Balanced growth + stability
- Tax Sensitivity: MEDIUM (accept reasonable tax for long-term benefit)

**Decision Criteria:**
- Exit if break-even ≤ 5 years
- Accept tax up to 8% of exit value if net benefit is positive
- Balance immediate cost vs long-term savings
- Focus on portfolio optimization

---

### 3. Aggressive (High Risk)
**Characteristics:**
- Age: Typically 20-40
- Time Horizon: 10+ years
- Priority: Maximum growth + optimization
- Tax Sensitivity: LOW (willing to pay tax for future savings)

**Decision Criteria:**
- Exit if break-even ≤ 10 years
- Accept tax up to 15% of exit value for long-term optimization
- Prioritize future savings over immediate costs
- Focus on portfolio simplification and efficiency

---

## Decision Matrix: Direct vs Regular Exit

### Your 3 Overlap Pairs:

| Fund | Break-even | Tax % | 5Y Net | Conservative | Moderate | Aggressive |
|------|------------|-------|--------|--------------|----------|------------|
| **HDFC Flexi Cap Reg** | 4.0 years | 5.2% | +₹2,730 | ✅ EXIT | ✅ EXIT | ✅ EXIT |
| **Parag Parikh Flexi Reg** | 5.8 years | 5.8% | +₹319 | ⚠️ DEFER | ✅ EXIT | ✅ EXIT |
| **HDFC Small Cap Reg** | 7.7 years | 15.0% | -₹5,145 | ❌ KEEP | ⚠️ DEFER | ✅ EXIT |

---

## Conservative Profile Recommendations

### Exit Immediately:
✅ **HDFC Flexi Cap Regular** (₹2.18L)
- Break-even: 4 years (acceptable)
- Tax: 5.2% (low)
- Clear net benefit: ₹2,730

### Defer/Keep:
⏳ **Parag Parikh Flexi Cap Regular** (₹85K)
- Break-even: 5.8 years (borderline)
- Small amount, consider deferring until LTCG

❌ **HDFC Small Cap Regular** (₹98K)
- Break-even: 7.7 years (too long)
- Tax: 15% (high)
- **Keep for now**, revisit when LTCG

**Total Action:** Exit 1 fund (₹2.18L), Keep 2

**Rationale:**
- Minimize tax impact
- Only take actions with clear short-term benefit
- Preserve capital, avoid long break-even periods

---

## Moderate Profile Recommendations

### Exit Immediately:
✅ **HDFC Flexi Cap Regular** (₹2.18L)
- Clear winner, 4-year break-even

✅ **Parag Parikh Flexi Cap Regular** (₹85K)
- 5.8-year break-even is acceptable
- Small positive net benefit

### Defer:
⏳ **HDFC Small Cap Regular** (₹98K)
- Break-even too long (7.7 years)
- Wait for LTCG (365 days) to reduce tax
- Re-evaluate once tax drops

**Total Action:** Exit 2 funds (₹3.03L), Defer 1

**Rationale:**
- Balance immediate tax vs long-term savings
- Accept 5-6 year break-evens
- Defer edge cases with negative 5-year net

---

## Aggressive Profile Recommendations

### Exit All 3 Immediately:
✅ **HDFC Flexi Cap Regular** (₹2.18L)
✅ **Parag Parikh Flexi Cap Regular** (₹85K)
✅ **HDFC Small Cap Regular** (₹98K)

**Total Action:** Exit all 3 funds (₹4.01L)

**Rationale:**
- Long-term optimization (8+ year horizon)
- Small Cap has very high expense ratio (1.95% - wasteful)
- Portfolio simplification is valuable
- Even 7.7-year break-even becomes positive eventually
- Small amount (₹98K) limits downside risk

---

## Additional Factors to Consider

### 1. Investment Horizon

**Short Horizon (<5 years):**
- Conservative approach
- Only exit if break-even ≤ 3 years

**Medium Horizon (5-10 years):**
- Moderate approach
- Exit if break-even ≤ 6 years

**Long Horizon (>10 years):**
- Aggressive approach
- Exit if break-even ≤ 10 years

---

### 2. Tax Planning

**Current Financial Year:**
- If nearing year-end and high income, defer exits to next FY
- Spread tax liability across multiple years

**Capital Loss Harvesting:**
- If you have capital losses elsewhere, can offset with these gains
- Makes exits more attractive (lower net tax)

---

### 3. Age-Based Guidelines

| Age Group | Risk Profile | Recommended Action |
|-----------|--------------|-------------------|
| **20-35** | Aggressive | Exit all 3 |
| **35-45** | Moderate-Aggressive | Exit 2-3 (based on comfort) |
| **45-55** | Moderate | Exit 2 (defer edge cases) |
| **55+** | Conservative | Exit 1 (only clear winners) |

---

### 4. Portfolio Size Context

**Large Portfolio (>₹1 Cr):**
- Small amounts like ₹98K are negligible
- Prioritize simplification over optimization
- Exit all duplicates

**Medium Portfolio (₹25L-₹1 Cr):**
- Balance optimization with tax efficiency
- Moderate approach

**Small Portfolio (<₹25L):**
- Every rupee counts
- Conservative approach, minimize tax

**Your Portfolio: ₹1.01 Cr**
- Medium-Large size
- ₹98K is <1% of portfolio
- Simplification benefit outweighs edge case concerns

---

## Implementation in Code

### Risk-Aware Exit Score Adjustment

```python
def adjust_exit_score_for_risk_profile(
    exit_score: float,
    break_even_years: float,
    tax_pct_of_exit: float,
    net_benefit_5y: float,
    risk_profile: str
) -> float:
    """
    Adjust exit score based on user's risk profile.
    
    Conservative: Reduce score for long break-evens
    Aggressive: Increase score for long-term optimization
    """
    adjusted_score = exit_score
    
    if risk_profile == "CONSERVATIVE":
        # Penalize long break-evens
        if break_even_years > 5:
            adjusted_score -= 2.0
        if break_even_years > 7:
            adjusted_score -= 1.0
        if tax_pct_of_exit > 10:
            adjusted_score -= 1.0
        if net_benefit_5y < 0:
            adjusted_score -= 2.0  # Strong penalty for negative 5Y net
    
    elif risk_profile == "MODERATE":
        # Moderate adjustments
        if break_even_years > 6:
            adjusted_score -= 1.0
        if net_benefit_5y < 0:
            adjusted_score -= 1.0
    
    elif risk_profile == "AGGRESSIVE":
        # Boost long-term optimization plays
        if break_even_years <= 10:
            adjusted_score += 0.5  # Slight boost
        if net_benefit_5y > 0:
            adjusted_score += 0.5  # Reward positive long-term
    
    return max(0, min(10, adjusted_score))  # Keep in 0-10 range
```

---

## Summary Table

### HDFC Flexi Cap Regular (₹2.18L)

| Profile | Decision | Adjusted Score | Rationale |
|---------|----------|----------------|-----------|
| Conservative | ✅ EXIT | 5.95 | 4-year break-even acceptable |
| Moderate | ✅ EXIT | 5.95 | Clear positive net |
| Aggressive | ✅ EXIT | 6.45 | Perfect optimization |

---

### Parag Parikh Flexi Cap Regular (₹85K)

| Profile | Decision | Adjusted Score | Rationale |
|---------|----------|----------------|-----------|
| Conservative | ⏳ DEFER | 3.43 (-2.0) | 5.8-year break-even too long |
| Moderate | ✅ EXIT | 5.43 | Acceptable break-even |
| Aggressive | ✅ EXIT | 5.93 (+0.5) | Long-term optimization |

---

### HDFC Small Cap Regular (₹98K)

| Profile | Decision | Adjusted Score | Rationale |
|---------|----------|----------------|-----------|
| Conservative | ❌ KEEP | 1.30 (-5.0) | Negative 5Y + long break-even |
| Moderate | ⏳ DEFER | 5.30 (-1.0) | Wait for LTCG |
| Aggressive | ✅ EXIT | 6.80 (+0.5) | Small amount, long horizon |

---

## User Input Required

To personalize your action plan, please provide:

1. **Risk Profile:** Conservative / Moderate / Aggressive
2. **Age:** (to estimate time horizon)
3. **Investment Horizon:** Short (<5Y) / Medium (5-10Y) / Long (>10Y)
4. **Tax Planning:** Any capital losses to offset? Planning major withdrawals?

Based on your inputs, I will generate a **personalized action plan** with the right exits for your risk profile.

---

**END OF DOCUMENT**
