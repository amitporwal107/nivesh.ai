# Nivesh Copilot V2 — Technical Specification
**Version:** 2.0  
**Date:** April 2026  
**Status:** Planning & Design

---

## 1. EXECUTIVE SUMMARY

### Product Vision
Transform Nivesh from a **portfolio analytics dashboard** → **decision & action system** that generates persistent, trackable action plans.

### Core Philosophy
**Signals → Decisions → Plan → Progress**

Users don't need more data; they need a plan they can follow over time.

### Key Changes
| Aspect | V1 (Current) | V2 (New) |
|--------|--------------|----------|
| **Focus** | Insights & Analytics | Action Plans |
| **Persistence** | Ephemeral (session-based) | Persistent (saved plans) |
| **User Journey** | View → Think → Manual action | Generate → Save → Track → Execute |
| **Primary View** | Dashboard with Insights tabs | Action Plan with progress tracking |
| **Analytics** | Primary feature | Optional exploration ("Deep Analytics") |

---

## 2. SYSTEM ARCHITECTURE

### High-Level Flow
```
Portfolio Data
    ↓
Analytics Engine (existing)
    ↓
Scoring Engine (MF/Stock EXIT/ADD)
    ↓
Signal Generation Layer (NEW)
    ↓
Action Plan Generator (NEW)
    ↓
Plan Storage (MongoDB - NEW)
    ↓
UI Layer (V1 + V2)
```

### Components Overview

#### **Existing Components (Reuse)**
- ✅ Portfolio Intelligence Engine
- ✅ Overlap/Compression calculation
- ✅ Top stock exposure
- ✅ Sector analysis
- ✅ Scoring Engine (just built)
- ✅ Tax Calculator (just built)
- ✅ Auth system
- ✅ MongoDB/PostgreSQL layer

#### **New Components (Build)**
- 🔨 Signal Generation Layer
- 🔨 Action Plan System
- 🔨 Plan Persistence & Lifecycle Management
- 🔨 V2 UI (Action Plan view)
- 🔨 Collapsible Signals Widget
- 🔨 Version Toggle System

---

## 3. SIGNAL GENERATION LAYER

### 3.1 Purpose
Group multiple portfolio insights into **3 clear problem signals** that drive action.

### 3.2 Signal Types

#### **Signal 1: Overlap / Redundancy**
**Triggered When:**
- Portfolio has ≥ 2 funds with overlap > 60%
- Compression score < 40/100 (highly compressed)
- Redundancy suggestions exist

**Data Sources:**
- `portfolio_intelligence.pairwise_overlap`
- `portfolio_intelligence.compression.score`
- `portfolio_intelligence.redundancy_suggestions`

**Signal Severity:**
- **HIGH**: Overlap > 80% OR Compression < 30
- **MEDIUM**: Overlap 60-80% OR Compression 30-40
- **LOW**: Overlap 40-60%

**Suggested Actions:**
- EXIT: Fund with highest overlap
- Type: "EXIT"
- Reason: "HIGH_OVERLAP"

---

#### **Signal 2: Overexposure / Allocation Imbalance**
**Triggered When:**
- Any single stock > 10% of portfolio
- Sector exposure > 30% in one sector
- Asset allocation imbalance (e.g., 95% equity, 0% debt)

**Data Sources:**
- `portfolio_intelligence.top_stocks`
- `portfolio_intelligence.sector_exposure`
- `portfolio.asset_allocation`

**Signal Severity:**
- **HIGH**: Stock > 15% OR Sector > 40%
- **MEDIUM**: Stock 10-15% OR Sector 30-40%
- **LOW**: Stock 8-10% OR Sector 25-30%

**Suggested Actions:**
- EXIT: Reduce overexposed stock/fund
- ADD: Increase underweight asset class
- Type: "EXIT" or "ADD"
- Reason: "OVEREXPOSURE", "ALLOCATION_IMBALANCE"

---

#### **Signal 3: Performance / Quality Issues**
**Triggered When:**
- MF quality score ≥ 7 (weak performer)
- Negative returns in last 1 year
- Expense ratio > 1.5%

**Data Sources:**
- `decision_engine.calculate_mf_quality_score()`
- `mutual_fund_performance_ratios.ret_1y`
- `mutual_fund_metadata.expense_ratio`

**Signal Severity:**
- **HIGH**: Quality score ≥ 8 OR Returns < -10%
- **MEDIUM**: Quality score 6-8 OR Returns -5% to -10%
- **LOW**: Quality score 5-6 OR Returns 0% to -5%

**Suggested Actions:**
- EXIT: Weak performing fund
- Type: "EXIT"
- Reason: "WEAK_PERFORMANCE", "HIGH_COST"

---

### 3.3 Signal Aggregation Logic

```python
def generate_signals(portfolio_intelligence, scoring_results):
    """Generate max 3 signals from portfolio data."""
    
    signals = []
    
    # Signal 1: Overlap/Redundancy
    if has_high_overlap(portfolio_intelligence):
        signals.append({
            "signal_id": "overlap_1",
            "type": "OVERLAP_REDUNDANCY",
            "severity": calculate_overlap_severity(),
            "title": "High overlap detected between your mutual funds",
            "impact": "₹X locked in duplicate holdings",
            "suggested_actions": [exit_highest_overlap_fund()],
            "reason_codes": ["HIGH_OVERLAP"],
        })
    
    # Signal 2: Overexposure
    if has_overexposure(portfolio_intelligence):
        signals.append({
            "signal_id": "exposure_1",
            "type": "OVEREXPOSURE",
            "severity": calculate_exposure_severity(),
            "title": "Overexposed to X sector/stock",
            "impact": "Y% concentration risk",
            "suggested_actions": [reduce_concentration()],
            "reason_codes": ["OVEREXPOSURE"],
        })
    
    # Signal 3: Performance
    if has_weak_performers(scoring_results):
        signals.append({
            "signal_id": "quality_1",
            "type": "QUALITY_ISSUES",
            "severity": calculate_quality_severity(),
            "title": "Underperforming funds detected",
            "impact": "₹Z potential savings",
            "suggested_actions": [exit_weak_fund()],
            "reason_codes": ["WEAK_PERFORMANCE"],
        })
    
    # Return top 3 signals
    return sorted(signals, key=lambda x: severity_order[x["severity"]])[:3]
```

---

## 4. ACTION PLAN SYSTEM

### 4.1 Purpose
Convert signals into a **persistent, versioned action plan** that users can track over time.

### 4.2 Plan Structure

```javascript
{
  "plan_id": "plan_abc123xyz",
  "user_id": "user_f087c6332922",
  "version": 1,
  "status": "active",  // active | completed | archived
  "created_at": "2026-04-19T10:30:00Z",
  "updated_at": "2026-04-19T10:30:00Z",
  "total_actions": 3,
  "completed_actions": 1,
  "signals": [
    {
      "signal_id": "overlap_1",
      "type": "OVERLAP_REDUNDANCY",
      "severity": "HIGH"
    }
  ],
  "actions": [
    {
      "action_id": "exit_1",
      "type": "EXIT",
      "asset_type": "mutual_fund",
      "asset_name": "HDFC Flexi Cap Direct Plan Growth",
      "asset_id": "instrument_123",
      "amount": 480000,
      "confidence": "HIGH",
      "reason_codes": ["HIGH_OVERLAP", "WEAK_PERFORMANCE"],
      "reason_text": "95% overlap with HDFC Flexi Cap Fund Growth",
      "tax_impact": {
        "tax_liability": 12000,
        "tax_type": "LTCG",
        "post_tax_proceeds": 468000
      },
      "status": "PENDING",  // PENDING | COMPLETED | SKIPPED
      "completed_at": null,
      "priority": 1
    },
    {
      "action_id": "exit_2",
      "type": "EXIT",
      "asset_type": "equity",
      "asset_name": "Reliance Industries",
      "amount": 250000,
      "confidence": "MEDIUM",
      "reason_codes": ["OVEREXPOSURE"],
      "reason_text": "12% portfolio concentration (target: <10%)",
      "tax_impact": {
        "tax_liability": 8500,
        "tax_type": "LTCG",
        "post_tax_proceeds": 241500
      },
      "status": "PENDING",
      "completed_at": null,
      "priority": 2
    },
    {
      "action_id": "add_1",
      "type": "ADD",
      "asset_type": "mutual_fund",
      "asset_name": "Recommended Debt Fund (TBD)",
      "amount": 300000,
      "confidence": "HIGH",
      "reason_codes": ["ALLOCATION_IMBALANCE"],
      "reason_text": "Portfolio lacks debt allocation (currently 5%, target 20%)",
      "status": "PENDING",
      "completed_at": null,
      "priority": 3
    }
  ],
  "freed_capital": 709500,  // Post-tax proceeds from exits
  "reinvestment_plan": {
    "total_amount": 709500,
    "allocations": [
      {
        "asset_class": "debt",
        "amount": 300000,
        "percentage": 42.3
      },
      {
        "asset_class": "equity",
        "amount": 409500,
        "percentage": 57.7
      }
    ]
  },
  "metadata": {
    "source": "auto_generated",
    "generation_time_ms": 1234,
    "ai_confidence": "HIGH"
  }
}
```

---

### 4.3 Plan Lifecycle

```
┌─────────────────────────────────────────────────┐
│  CREATE                                         │
│  - User clicks "Generate Plan"                  │
│  - System runs scoring + signal generation      │
│  - Preview shown to user                        │
│  - User clicks "Save Plan"                      │
│  - Plan stored in MongoDB                       │
└─────────────────┬───────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────┐
│  ACTIVE                                         │
│  - Shown on every login                         │
│  - User tracks progress                         │
│  - Actions can be marked COMPLETED/SKIPPED      │
│  - Progress bar updates                         │
└─────────────────┬───────────────────────────────┘
                  ↓
         ┌────────┴────────┐
         ↓                 ↓
┌─────────────────┐  ┌─────────────────────────────┐
│  UPDATE         │  │  COMPLETE                   │
│  - Portfolio    │  │  - All actions done         │
│    changed      │  │  - Plan archived            │
│  - User clicks  │  │  - "Generate new plan?"     │
│    "Refresh"    │  │                             │
│  - New version  │  │                             │
│    created      │  │                             │
│  - Old version  │  │                             │
│    archived     │  │                             │
└─────────────────┘  └─────────────────────────────┘
```

---

### 4.4 Action State Transitions

```
PENDING
  ↓
  ├─→ User marks "Done" → COMPLETED
  ├─→ User marks "Skip" → SKIPPED
  └─→ Plan updated/refreshed → PENDING (new version)
```

---

## 5. VERSION TOGGLE SYSTEM

### 5.1 Purpose
Allow users to switch between V1 (current dashboard) and V2 (action plan system).

### 5.2 User Preference Storage

```javascript
// MongoDB: users collection
{
  "user_id": "user_xyz",
  "email": "user@example.com",
  "preferences": {
    "ui_version": "v2",  // "v1" | "v2"
    "analytics_visibility": {
      "overlap": true,
      "overexposure": true,
      "performance": true,
      "cost": false,
      "tax": true
    }
  }
}
```

### 5.3 Toggle Locations

1. **Login Page**
   - Checkbox: "Try New Action Plan Experience (Beta)"
   - Default: V1 for existing users, V2 for new users

2. **Dashboard Header**
   - Dropdown: "Switch to V1 Dashboard" / "Switch to V2 Action Plan"
   - Preference saved on change

3. **Settings Page**
   - Toggle: "Use Action Plan View (V2)"
   - Description of differences

---

## 6. API CONTRACT

### 6.1 Signal Generation

**Endpoint:** `GET /api/signals/generate`

**Request:**
```bash
curl -X GET "https://app.nivesh.ai/api/signals/generate" \
  -H "Cookie: session_token=xyz"
```

**Response:**
```json
{
  "signals": [
    {
      "signal_id": "overlap_1",
      "type": "OVERLAP_REDUNDANCY",
      "severity": "HIGH",
      "title": "High overlap detected between your mutual funds",
      "description": "2 of your funds hold 95% similar stocks",
      "impact": "₹480,000 locked in duplicate holdings",
      "suggested_actions": 1,
      "affected_assets": ["HDFC Flexi Cap Direct", "HDFC Flexi Cap Regular"],
      "details": {
        "overlap_pct": 95.8,
        "shared_stocks": 62,
        "compression_score": 30.4
      }
    }
  ],
  "total_signals": 3,
  "timestamp": "2026-04-19T10:30:00Z"
}
```

---

### 6.2 Action Plan CRUD

#### **Create Plan**
**Endpoint:** `POST /api/plans/generate`

**Request:**
```json
{
  "include_signals": ["overlap_1", "exposure_1"]
}
```

**Response:**
```json
{
  "plan_id": "plan_abc123",
  "status": "preview",
  "actions": [...],
  "total_actions": 3,
  "freed_capital": 709500,
  "preview_url": "/plans/preview/plan_abc123"
}
```

---

#### **Save Plan**
**Endpoint:** `POST /api/plans/{plan_id}/save`

**Response:**
```json
{
  "plan_id": "plan_abc123",
  "status": "active",
  "message": "Plan saved successfully"
}
```

---

#### **Get Active Plan**
**Endpoint:** `GET /api/plans/active`

**Response:**
```json
{
  "plan": {...},
  "progress": {
    "total_actions": 3,
    "completed": 1,
    "pending": 2,
    "completion_pct": 33.3
  }
}
```

---

#### **Update Action Status**
**Endpoint:** `PATCH /api/plans/{plan_id}/actions/{action_id}`

**Request:**
```json
{
  "status": "COMPLETED"
}
```

**Response:**
```json
{
  "action_id": "exit_1",
  "status": "COMPLETED",
  "completed_at": "2026-04-20T15:30:00Z",
  "plan_progress": {
    "completed": 2,
    "remaining": 1
  }
}
```

---

## 7. DATA FLOW DIAGRAMS

### 7.1 Plan Generation Flow

```
User clicks "Generate Plan"
    ↓
[Frontend] POST /api/plans/generate
    ↓
[Backend] Fetch portfolio holdings
    ↓
[Backend] Run portfolio_intelligence.compute()
    ↓
[Backend] Run decision_engine.generate_portfolio_actions()
    ↓
[Backend] Run signal_generator.generate_signals()
    ↓
[Backend] Create action plan object
    ↓
[Backend] Store as "preview" status
    ↓
[Backend] Return plan preview
    ↓
[Frontend] Show preview modal
    ↓
User reviews + clicks "Save Plan"
    ↓
[Frontend] POST /api/plans/{plan_id}/save
    ↓
[Backend] Update plan status to "active"
    ↓
[Frontend] Redirect to Action Plan view
```

---

### 7.2 Returning User Flow

```
User logs in
    ↓
[Frontend] GET /api/plans/active
    ↓
[Backend] Query: action_plans.find({user_id, status: "active"})
    ↓
[Backend] Return active plan
    ↓
[Frontend] Show Action Plan view
    ↓
User sees: 3 actions, progress tracker, signals
    ↓
User clicks "Mark as Done" on Action 1
    ↓
[Frontend] PATCH /api/plans/{plan_id}/actions/{action_id}
    ↓
[Backend] Update action.status = "COMPLETED"
    ↓
[Backend] Calculate new progress
    ↓
[Frontend] Update progress bar (33% → 66%)
```

---

## 8. MIGRATION STRATEGY

### 8.1 Database Changes

**New Collections:**
- `action_plans` (store user plans)
- `plan_history` (versioned plans)

**Updated Collections:**
- `users` → Add `preferences.ui_version`

### 8.2 Rollout Plan

**Phase 1: Backend + Schema** (Day 1)
- Add signal generation layer
- Create action plan CRUD APIs
- Add MongoDB collections
- Test with Postman

**Phase 2: V2 UI** (Day 2)
- Build Action Plan view
- Build Signals widget
- Test both V1 and V2 UIs

**Phase 3: Version Toggle** (Day 2-3)
- Add toggle on login
- Add dashboard switcher
- Test version switching

**Phase 4: Beta Testing** (Day 3)
- Enable V2 for internal users
- Collect feedback
- Fix bugs

**Phase 5: Gradual Rollout** (Week 2)
- Enable V2 for 10% users
- Monitor metrics
- Scale to 100%

---

## 9. SUCCESS METRICS

### Key Metrics to Track

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Plan Creation Rate** | 70% of active users | `plans_created / active_users` |
| **Action Completion Rate** | 50% within 30 days | `actions_completed / actions_created` |
| **Repeat Visits** | 3x per week | Avg. sessions per user |
| **Time to First Action** | < 48 hours | `first_action_completed_at - plan_created_at` |
| **V2 Adoption Rate** | 80% after 30 days | `v2_users / total_users` |

---

## 10. NEXT STEPS

**Before Implementation:**
1. ✅ Review this spec with stakeholders
2. ✅ Finalize database schema (see separate doc)
3. ✅ Review UI wireframes (see separate doc)
4. ✅ Confirm API contract
5. ✅ Approve migration strategy

**Implementation Order:**
1. Signal generation layer (Backend)
2. Action plan system (Backend)
3. MongoDB schema + migrations
4. V2 UI components
5. Version toggle system
6. Integration testing
7. Beta rollout

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-19  
**Author:** E1 Agent  
**Status:** Draft for Review
