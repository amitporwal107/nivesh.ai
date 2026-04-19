# Nivesh Copilot V2 — Final Implementation Plan
**Version:** 2.0 FINAL  
**Date:** April 2026  
**Status:** Ready for Implementation

---

## 📋 DECISIONS FINALIZED

### 1. **Signal Generation (Extensible)**
✅ Start with 3 signals, design for easy addition of more
- Architecture: Plugin-based signal detectors
- Easy to add: Signal 4, 5, 6... in future

### 2. **Action Plan (Configurable)**
✅ Not limited to 3 actions, system can handle N actions
- Priority-based ranking
- User can skip/complete any action

### 3. **Plan Refresh**
✅ **On-demand only** (no auto-refresh)
- User clicks "Update Plan" when ready
- Future: Auto-detect portfolio changes

### 4. **Version Toggle**
✅ Simple UI toggle
- New users → V2 by default
- Existing users → Can switch anytime
- Preference saved in DB

### 5. **ADD Recommendations**
✅ Generic, user selects themselves
- Show scoring mechanism
- If scoring unavailable → Skip recommendation

### 6. **Tax Logic**
✅ **FIFO-based LTCG/STCG calculation**
- Detailed implementation provided (see tax_calculator.py update)
- ₹1L exemption aggregated across all equity
- Loss offset rules

### 7. **Plan History**
✅ Archive old plans, **read-only** (no revert)
- View history for reference only

### 8. **Signal Thresholds**
✅ Keep as proposed (can tune later)

### 9. **UI Layout**
✅ **Single dashboard screen**
- Club everything together
- Simple, readable charts (not fancy)
- **Mobile-first** design philosophy

### 10. **Data & Execution**
✅ Scrape Groww for missing data
- Manual execution tracking (broker integration later)
- Reuse maximum existing codebase

---

## 🎨 DESIGN SYSTEM (Mobile-First)

### Color Palette
- 🔴 **Red:** Urgent (EXIT actions)
- 🟡 **Amber:** Warning (HOLD, moderate issues)
- 🟢 **Green:** Good (completed actions, positive signals)

### Typography Hierarchy
1. **₹ Amount:** Largest (text-4xl on mobile)
2. **Action Type:** Medium (text-xl)
3. **Reason:** Small (text-sm)

### Key Principles
- **1-hand usage** (thumb zone)
- **< 10 second** comprehension
- **< 3 taps** to action
- **Touch-first:** Button height ≥ 48px, padding ≥ 16px
- **No paragraphs:** Title → 1 line, Reason → 1 line

### Screen Structure (Top → Bottom)
```
[Sticky Action Plan] ← Always visible, collapsible
[Progress Indicator] ← ● ○ ○ 1/3
[Next Action CTA]    ← Large, thumb-friendly
[Portfolio Signals]  ← Collapsed by default
[Details]            ← Expandable, lazy-loaded
[Bottom Action Bar]  ← Sticky [Simulate] [Update]
```

### Component Rules
- **Card padding:** 16-20px
- **Vertical spacing:** 12-16px
- **Full-width cards** on mobile
- **No multi-column layouts** on mobile
- **Load time < 2s** (use skeleton loaders)

---

## 🏗️ ARCHITECTURE (Extensible)

### Backend Structure
```python
/app/backend/
├── services/
│   ├── decision_engine.py (EXISTING - 90% reuse)
│   ├── tax_calculator.py (UPDATE - Add FIFO logic)
│   ├── signal_detector.py (NEW - Extensible plugin system)
│   ├── action_plan_manager.py (NEW - CRUD + lifecycle)
│   └── groww_scraper.py (EXISTING - Reuse for missing data)
├── routes/
│   ├── decisions.py (EXISTING - Expand)
│   └── plans.py (NEW - Plan CRUD APIs)
```

### Extensible Signal Architecture
```python
# Base class for all signals
class SignalDetector:
    def detect(self, portfolio_data) -> Signal:
        pass

# Plugin registry
SIGNAL_DETECTORS = [
    OverlapSignalDetector(),     # Signal 1
    OverexposureSignalDetector(), # Signal 2
    QualitySignalDetector(),     # Signal 3
    # Future: Add more here
]

# Easy to extend
def generate_signals(portfolio):
    signals = []
    for detector in SIGNAL_DETECTORS:
        signal = detector.detect(portfolio)
        if signal:
            signals.append(signal)
    return signals
```

---

## 📊 DATABASE SCHEMA (Simplified)

### `action_plans` Collection
```javascript
{
  "plan_id": "plan_abc123",
  "user_id": "user_xyz",
  "version": 1,
  "status": "active",  // active | completed | archived
  "created_at": ISODate(),
  "updated_at": ISODate(),
  
  // Signals (extensible array)
  "signals": [
    {
      "signal_id": "overlap_1",
      "type": "OVERLAP_REDUNDANCY",
      "severity": "HIGH",
      "title": "High overlap detected",
      "impact": "₹4.8L locked in duplicates"
    }
    // Can add more signal types here
  ],
  
  // Actions (configurable count)
  "actions": [
    {
      "action_id": "exit_1",
      "type": "EXIT",  // EXIT | ADD | SWITCH
      "priority": 1,
      "asset_type": "mutual_fund",
      "asset_name": "HDFC Flexi Cap",
      "amount": 480000,
      "confidence": "HIGH",
      "reason_codes": ["HIGH_OVERLAP"],
      "reason_text": "60% duplication with other fund",
      "tax_impact": {
        "ltcg": 80000,
        "stcg": 0,
        "tax_liability": 0,
        "tax_type": "LTCG",
        "note": "Within ₹1L exemption"
      },
      "status": "PENDING",  // PENDING | COMPLETED | SKIPPED
      "completed_at": null
    }
    // No limit on action count
  ],
  
  // Aggregated tax (across all actions)
  "total_tax_impact": {
    "total_ltcg": 130000,
    "total_stcg": 0,
    "exemption_used": 100000,
    "taxable_ltcg": 30000,
    "total_tax": 3000
  },
  
  "progress": {
    "total_actions": 3,
    "completed": 1,
    "pending": 2,
    "completion_pct": 33.3
  }
}
```

### `users` Update
```javascript
{
  "preferences": {
    "ui_version": "v2"  // Simple toggle
  }
}
```

---

## 🔧 TAX CALCULATOR UPDATE (FIFO Logic)

### Enhanced Implementation
```python
def calculate_tax_impact_fifo(holding_lots: list, exit_amount: float):
    """
    Calculate tax with FIFO logic for partial sells.
    
    Args:
        holding_lots: [
            {"buy_date": "2023-01-01", "units": 100, "price": 50},
            {"buy_date": "2023-06-01", "units": 50, "price": 55}
        ]
        exit_amount: 5000 (₹ to exit)
    
    Returns:
        {
            "ltcg": 2000,
            "stcg": 500,
            "total_tax": 75,
            "lot_breakdown": [...]
        }
    """
    # Sort by buy_date (FIFO)
    lots = sorted(holding_lots, key=lambda x: x["buy_date"])
    
    remaining_amount = exit_amount
    total_ltcg = 0
    total_stcg = 0
    
    for lot in lots:
        if remaining_amount <= 0:
            break
        
        # Calculate gain for this lot
        lot_value = lot["units"] * lot["current_price"]
        exit_from_lot = min(remaining_amount, lot_value)
        
        holding_period = (today - lot["buy_date"]).days
        gain = exit_from_lot * (lot["current_price"] - lot["buy_price"]) / lot["current_price"]
        
        if holding_period > 365:
            total_ltcg += gain
        else:
            total_stcg += gain
        
        remaining_amount -= exit_from_lot
    
    # Apply ₹1L LTCG exemption (aggregated across portfolio)
    taxable_ltcg = max(0, total_ltcg - LTCG_EXEMPTION)
    
    # Calculate tax
    ltcg_tax = taxable_ltcg * 0.10
    stcg_tax = total_stcg * 0.15
    total_tax = ltcg_tax + stcg_tax
    
    return {
        "ltcg": total_ltcg,
        "stcg": total_stcg,
        "taxable_ltcg": taxable_ltcg,
        "total_tax": total_tax,
        "note": "FIFO applied, ₹1L exemption used"
    }
```

---

## 🎯 IMPLEMENTATION PHASES

### **Phase 1: Backend Core** (Day 1)
- [ ] Update `tax_calculator.py` with FIFO logic
- [ ] Create `signal_detector.py` (extensible plugin system)
- [ ] Create `action_plan_manager.py` (CRUD + lifecycle)
- [ ] Update `decision_engine.py` to use signals
- [ ] Create API routes: `/api/plans/*`

### **Phase 2: Database** (Day 1)
- [ ] Create `action_plans` collection
- [ ] Update `users` with preferences
- [ ] Create indexes
- [ ] Migration script for existing users

### **Phase 3: V2 UI** (Day 2)
- [ ] Sticky Action Plan component
- [ ] Action Cards (mobile-first, touch-friendly)
- [ ] Progress Indicator
- [ ] Collapsible Signals widget
- [ ] Bottom Action Bar
- [ ] Mobile-responsive design

### **Phase 4: Version Toggle** (Day 2)
- [ ] Dashboard header toggle
- [ ] User preference persistence
- [ ] Route-based version switching

### **Phase 5: Integration** (Day 3)
- [ ] Connect V2 UI to backend APIs
- [ ] Scrape Groww for missing data
- [ ] Test with real user (priyankamantri@gmail.com)
- [ ] Fix bugs

### **Phase 6: Polish** (Day 3)
- [ ] Skeleton loaders
- [ ] Error states
- [ ] Empty states
- [ ] Loading animations
- [ ] Testing agent validation

---

## 📱 MOBILE-FIRST UI MOCKUP

```
┌───────────────────────────────────┐
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │ ← Sticky
│ Fix Your Portfolio (3 steps)      │
│ 1. Sell ₹4.8L  2. Switch ₹13L    │
│ Progress: ● ○ ○  0/3             │
│ [Start] ▼                         │
└───────────────────────────────────┘
│
│ ┌─────────────────────────────┐
│ │ 🔴 SELL ₹4.8L              │
│ │ Reduce overlap             │
│ │                             │
│ │ Why: 60% duplication       │
│ │ Impact: ✔ Better diversity │
│ │                             │
│ │ Tax: ₹0 (LTCG exempt)      │
│ │                             │
│ │ [Mark as Done]             │ ← 48px height
│ └─────────────────────────────┘
│
│ ┌─────────────────────────────┐
│ │ 🟡 SWITCH ₹13L             │
│ │ Better performance         │
│ │ [View Details] ▼           │
│ └─────────────────────────────┘
│
│ ┌─────────────────────────────┐
│ │ 🔴 High Overlap [▼]        │ ← Collapsed
│ │ 🟡 Overexposure [▼]        │
│ │ 🟢 Portfolio Health [▼]    │
│ └─────────────────────────────┘
│
│ [Full scroll, no tabs]
│
┌───────────────────────────────────┐
│ [Simulate] [Update Plan]          │ ← Sticky bottom
└───────────────────────────────────┘
```

---

## 🔄 CODE REUSE STRATEGY

### Reuse 100%
- ✅ Authentication system
- ✅ MongoDB/PostgreSQL layer
- ✅ Portfolio Intelligence engine
- ✅ Groww scraper
- ✅ Overlap/Compression calculation

### Reuse 90% (Minor updates)
- ✅ Scoring Engine (add signal mapping)
- ✅ Tax Calculator (add FIFO logic)

### Reuse 70% (Refactor)
- ✅ Decision Engine (integrate signals)
- ✅ Analytics routes (expose for V2)

### New (30%)
- 🆕 Signal Detector (plugin system)
- 🆕 Action Plan Manager (CRUD)
- 🆕 V2 UI Components
- 🆕 Version Toggle

**Total Reuse: ~70%**

---

## 🚀 DEPLOYMENT STRATEGY

### Step 1: Backend Deployment
- Deploy new APIs (`/api/plans/*`, `/api/signals/*`)
- Create MongoDB collections
- Migrate user preferences

### Step 2: Frontend Build
- Build V2 UI components
- Add version toggle
- Test V1 still works

### Step 3: Gradual Rollout
1. **Week 1:** Internal testing (team accounts)
2. **Week 2:** Beta users (10% of active users)
3. **Week 3:** Expand to 50%
4. **Week 4:** 100% rollout

### Step 4: Monitor Metrics
- Plan creation rate
- Action completion rate
- V2 adoption rate
- Bug reports

---

## ✅ SUCCESS CRITERIA

### Functional
- [ ] User can generate action plan
- [ ] User can mark actions as done
- [ ] Plan persists across sessions
- [ ] Tax calculations are accurate (FIFO)
- [ ] Signals are detected correctly
- [ ] Version toggle works smoothly

### Performance
- [ ] Page load < 2s
- [ ] Plan generation < 10s
- [ ] No blocking UI operations

### User Experience
- [ ] < 10 second comprehension
- [ ] < 3 taps to complete action
- [ ] 1-hand thumb usage works
- [ ] Mobile-friendly (no zooming needed)

### Business Metrics
- [ ] 70% plan creation rate
- [ ] 50% action completion (30 days)
- [ ] 80% V2 adoption (30 days)

---

## 📝 NEXT ACTIONS

**Immediate:**
1. ✅ Review this plan with stakeholders
2. ✅ Confirm all decisions are aligned
3. ⏳ Start Phase 1: Backend Core

**Questions for You:**
1. Should I start building now?
2. Any changes to this plan?
3. Priority: Build backend first, or UI first?

---

**Document Version:** 2.0 FINAL  
**Last Updated:** 2026-04-19  
**Author:** E1 Agent  
**Status:** ✅ Ready for Implementation
