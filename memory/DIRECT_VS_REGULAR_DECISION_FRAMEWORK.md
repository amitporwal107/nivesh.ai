# Direct vs Regular Plan Exit Decision Framework

**Document:** Tax-Aware Exit Decision Logic  
**Date:** April 19, 2026  
**Principle:** Consider both tax impact AND expense ratio savings

---

## Decision Formula

When you have both Direct and Regular plans of the same fund, calculate:

### Total Cost of Keeping Regular Plan
```
Total Cost = Immediate Tax (if exiting) + Future Expense Waste
```

### Break-Even Analysis
```
Break-even Years = Exit Tax ÷ Annual Expense Savings

Where:
  Annual Expense Savings = Fund Value × (Regular ER% - Direct ER%)
```

---

## Decision Rules

### ✅ **EXIT REGULAR if:**

1. **Break-even < 3 years** → Always exit (quick payback)
2. **Break-even < 5 years + Holding horizon > 5 years** → Exit (medium-term benefit)
3. **Both are STCG** → Exit Regular (no tax advantage either way)
4. **Regular is LTCG, Direct is STCG** → Exit Regular (lower tax on older fund)

### ⚠️ **EXIT DIRECT if (RARE):**

1. **Regular is LTCG with very low tax (<2% of value)** AND
2. **Direct is STCG with high tax (>10% of value)** AND
3. **Short holding horizon (<3 years)** AND
4. **Planning to exit the fund entirely soon**

   *(This scenario is uncommon - usually better to exit Regular)*

---

## Real Example: HDFC Flexi Cap

### Scenario Data:
- **Direct Plan:** ₹3.77L, 0 days holding, 0.5% expense, STCG tax ₹20,439
- **Regular Plan:** ₹2.18L, 0 days holding, 1.8% expense, STCG tax ₹11,445
- **Expense Difference:** 1.3% per year

### Analysis:

**Option 1: Exit Regular**
```
Immediate Tax Cost: ₹11,445
Annual Savings: ₹2,835/year (from 1.3% expense difference)
Break-even: 11,445 ÷ 2,835 = 4.0 years

5-Year Net Benefit:
  Savings: ₹2,835 × 5 = ₹14,175
  Tax: -₹11,445
  Net: +₹2,730 ✅
```

**Option 2: Exit Direct**
```
Immediate Tax Cost: ₹20,439
Annual Loss: -₹4,900/year (keeping expensive Regular)

5-Year Net Loss:
  Extra expense: ₹4,900 × 5 = ₹24,500
  Tax: -₹20,439
  Net: -₹44,939 ❌
```

**Decision:** Exit Regular (break-even in 4 years, net positive in 5 years)

---

## Break-Even Thresholds

| Break-even Period | Decision | Rationale |
|-------------------|----------|-----------|
| < 1 year | **EXIT immediately** | Instant payback |
| 1-3 years | **EXIT (high priority)** | Quick payback |
| 3-5 years | **EXIT (medium priority)** | Acceptable if long-term holding |
| 5-10 years | **Evaluate case-by-case** | Check holding horizon |
| > 10 years | **Consider alternatives** | May wait for LTCG or other options |

---

## Special Cases

### Case 1: Regular is LTCG, Direct is STCG

**Example:**
- Regular: 3 years old (LTCG), tax = ₹5,000
- Direct: 6 months old (STCG), tax = ₹25,000

**Analysis:**
- Exit Regular (LTCG tax is lower)
- Annual savings still apply
- Break-even calculation: 5,000 ÷ annual_savings

### Case 2: Both are LTCG

**Both have low tax** (10% after ₹1L exemption)
- Exit Regular (no tax advantage for either)
- Higher expense ratio is the deciding factor

### Case 3: Both are STCG

**Both have high tax** (15%)
- Exit the **smaller amount** to minimize tax
- But check if break-even is still reasonable

---

## Updated Exit Score Formula (Tax-Aware)

When evaluating Direct vs Regular for the same fund:

```python
# Calculate net benefit over 5 years
net_benefit_exit_regular = (
    (regular_value × expense_diff × 5) - regular_exit_tax
)

net_benefit_exit_direct = (
    (direct_value × expense_diff × 5) - direct_exit_tax
)

# Choose the option with higher net benefit
if net_benefit_exit_regular > net_benefit_exit_direct:
    recommendation = "EXIT REGULAR"
else:
    recommendation = "EXIT DIRECT"  # Rare
```

**Incorporate into Exit Score:**
```python
# If net benefit is negative (loss scenario)
if net_benefit < 0:
    exit_score -= 2.0  # Reduce exit score (don't exit)
elif net_benefit < 10000:
    exit_score -= 1.0  # Small benefit (lower priority)
elif net_benefit > 50000:
    exit_score += 1.0  # Large benefit (higher priority)
```

---

## Implementation in Code

### Location: `/app/backend/services/action_plan_manager.py`

**Add logic to compare Direct vs Regular:**

```python
def _resolve_direct_vs_regular_pairs(
    self, 
    exit_candidates: List[Dict]
) -> List[Dict]:
    """
    When both Direct and Regular plans exist, choose which to exit
    based on tax impact + expense ratio savings.
    """
    # Group by base fund name
    fund_groups = defaultdict(list)
    for candidate in exit_candidates:
        base_name = candidate['fund_name'].replace('Direct', '').replace('Regular', '').strip()
        fund_groups[base_name].append(candidate)
    
    final_candidates = []
    
    for base_name, funds in fund_groups.items():
        if len(funds) == 1:
            # No conflict, add as-is
            final_candidates.append(funds[0])
        else:
            # Both Direct and Regular exist
            direct = next((f for f in funds if 'Direct' in f['fund_name']), None)
            regular = next((f for f in funds if 'Regular' in f['fund_name']), None)
            
            if direct and regular:
                # Calculate net benefit for each option
                expense_diff = regular['expense_ratio'] - direct['expense_ratio']
                
                # Option 1: Exit Regular
                annual_savings_regular = regular['value'] * expense_diff
                net_benefit_regular = (annual_savings_regular * 5) - regular['tax_liability']
                
                # Option 2: Exit Direct
                annual_loss_direct = direct['value'] * expense_diff
                net_benefit_direct = (annual_loss_direct * 5) - direct['tax_liability']
                
                # Choose the better option (usually Exit Regular)
                if net_benefit_regular > net_benefit_direct:
                    final_candidates.append(regular)
                else:
                    final_candidates.append(direct)
    
    return final_candidates
```

---

## Summary

**Default Rule:** Exit Regular plans (they cost more every year)

**Tax Consideration:** Check if tax cost is recovered within 5 years through expense savings

**Rare Exception:** Only exit Direct if:
- Tax difference is MASSIVE (>₹50K difference)
- Regular plan is very old (LTCG with minimal tax)
- You plan to exit the fund entirely within 2-3 years

**In 99% of cases:** Exit Regular, Keep Direct

---

**END OF DOCUMENT**
