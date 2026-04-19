# Nivesh Copilot V2 — Database Schema Design
**Version:** 2.0  
**Date:** April 2026

---

## 1. MONGODB COLLECTIONS

### 1.1 `action_plans` (NEW)

**Purpose:** Store user action plans with versioning and state tracking.

**Schema:**
```javascript
{
  // Plan identification
  "plan_id": "plan_20260419_abc123xyz",  // Unique plan ID
  "user_id": "user_f087c6332922",         // FK to users
  "version": 1,                           // Plan version number
  
  // Plan status
  "status": "active",  // Enum: "preview" | "active" | "completed" | "archived"
  
  // Timestamps
  "created_at": ISODate("2026-04-19T10:30:00Z"),
  "updated_at": ISODate("2026-04-19T10:30:00Z"),
  "completed_at": null,  // Set when status = "completed"
  
  // Progress tracking
  "total_actions": 3,
  "completed_actions": 1,
  "skipped_actions": 0,
  "pending_actions": 2,
  "completion_pct": 33.3,
  
  // Signals that triggered this plan
  "signals": [
    {
      "signal_id": "overlap_1",
      "type": "OVERLAP_REDUNDANCY",  // Enum: OVERLAP_REDUNDANCY | OVEREXPOSURE | QUALITY_ISSUES
      "severity": "HIGH",            // Enum: HIGH | MEDIUM | LOW
      "title": "High overlap detected between your mutual funds",
      "description": "2 of your funds hold 95% similar stocks",
      "impact": "₹480,000 locked in duplicate holdings",
      "details": {
        "overlap_pct": 95.8,
        "shared_stocks": 62,
        "compression_score": 30.4,
        "affected_assets": [
          "HDFC Flexi Cap Direct Plan Growth",
          "HDFC Flexi Cap Fund Growth"
        ]
      }
    },
    {
      "signal_id": "exposure_1",
      "type": "OVEREXPOSURE",
      "severity": "MEDIUM",
      "title": "Overexposed to Financial sector",
      "description": "35% portfolio in one sector",
      "impact": "High concentration risk",
      "details": {
        "sector": "Financial Services",
        "exposure_pct": 35.2,
        "target_pct": 25.0,
        "top_stocks": ["HDFC Bank", "ICICI Bank", "Axis Bank"]
      }
    }
  ],
  
  // Actions (2-3 per plan)
  "actions": [
    {
      "action_id": "exit_1",
      "type": "EXIT",  // Enum: EXIT | ADD | SWITCH
      "priority": 1,   // 1 = highest
      
      // Asset details
      "asset_type": "mutual_fund",  // mutual_fund | equity | debt | gold
      "asset_name": "HDFC Flexi Cap Direct Plan Growth",
      "asset_id": "instrument_hdfc_flexi_123",  // FK to holdings or instrument_master
      
      // Financial details
      "amount": 480000,
      "current_value": 480000,
      "units": null,  // For MF/stocks if applicable
      
      // Decision metadata
      "confidence": "HIGH",  // HIGH | MEDIUM | LOW
      "exit_score": 8.5,     // From decision_engine
      "reason_codes": ["HIGH_OVERLAP", "WEAK_PERFORMANCE"],
      "reason_text": "95% overlap with HDFC Flexi Cap Fund Growth. Underperforming category average by 3%.",
      
      // Tax impact
      "tax_impact": {
        "holding_period_days": 450,
        "holding_period_years": 1.23,
        "is_long_term": true,
        "capital_gain": 80000,
        "taxable_gain": 0,  // After ₹1L exemption
        "tax_liability": 0,
        "tax_type": "LTCG",
        "tax_efficiency_pct": 100,
        "post_tax_proceeds": 480000
      },
      
      // Execution tracking
      "status": "COMPLETED",  // PENDING | COMPLETED | SKIPPED
      "completed_at": ISODate("2026-04-20T15:30:00Z"),
      "skipped_at": null,
      "completion_note": "Redeemed via Groww app",  // User-entered
      
      // Signal mapping
      "triggered_by_signal": "overlap_1"
    },
    {
      "action_id": "exit_2",
      "type": "EXIT",
      "priority": 2,
      "asset_type": "equity",
      "asset_name": "Reliance Industries Ltd.",
      "asset_id": "holding_rel_456",
      "amount": 250000,
      "confidence": "MEDIUM",
      "exit_score": 6.8,
      "reason_codes": ["OVEREXPOSURE"],
      "reason_text": "12% portfolio concentration (target: <10%)",
      "tax_impact": {
        "holding_period_days": 800,
        "is_long_term": true,
        "capital_gain": 50000,
        "taxable_gain": 0,
        "tax_liability": 0,
        "tax_type": "LTCG",
        "post_tax_proceeds": 250000
      },
      "status": "PENDING",
      "completed_at": null,
      "triggered_by_signal": "exposure_1"
    },
    {
      "action_id": "add_1",
      "type": "ADD",
      "priority": 3,
      "asset_type": "mutual_fund",
      "asset_name": "HDFC Corporate Bond Fund Direct Growth",
      "asset_id": null,  // New investment
      "amount": 300000,
      "confidence": "HIGH",
      "add_score": 7.8,
      "reason_codes": ["ALLOCATION_IMBALANCE"],
      "reason_text": "Portfolio lacks debt allocation (currently 5%, target 20%)",
      "tax_impact": null,  // No tax for new investments
      "status": "PENDING",
      "completed_at": null,
      "triggered_by_signal": null  // Fills gap, not triggered by specific signal
    }
  ],
  
  // Capital management
  "freed_capital": 730000,       // Total exit amounts
  "tax_liability": 20500,        // Total tax on exits
  "post_tax_proceeds": 709500,   // freed_capital - tax_liability
  
  // Reinvestment plan
  "reinvestment_plan": {
    "total_amount": 709500,
    "allocations": [
      {
        "asset_class": "debt",
        "amount": 300000,
        "percentage": 42.3,
        "suggested_funds": [
          "HDFC Corporate Bond Fund Direct Growth"
        ]
      },
      {
        "asset_class": "equity",
        "amount": 409500,
        "percentage": 57.7,
        "suggested_funds": [
          "Nifty Index Fund"
        ]
      }
    ]
  },
  
  // Metadata
  "metadata": {
    "source": "auto_generated",  // auto_generated | user_modified
    "generation_time_ms": 1234,
    "ai_model": "decision_engine_v2",
    "ai_confidence": "HIGH",
    "portfolio_value_at_creation": 5200000,
    "parent_plan_id": null  // If this is a refreshed version, link to previous
  },
  
  // User interactions
  "user_notes": "Planning to execute in May after tax filing",
  "user_rating": null,  // 1-5 stars (optional feedback)
  
  // Indexes (see below)
}
```

**Indexes:**
```javascript
db.action_plans.createIndex({ "user_id": 1, "status": 1 });
db.action_plans.createIndex({ "user_id": 1, "version": -1 });
db.action_plans.createIndex({ "plan_id": 1 }, { unique: true });
db.action_plans.createIndex({ "created_at": -1 });
```

---

### 1.2 `plan_history` (NEW)

**Purpose:** Archive old plan versions for audit trail and analytics.

**Schema:**
```javascript
{
  "history_id": "hist_abc123",
  "plan_id": "plan_20260419_abc123xyz",
  "user_id": "user_f087c6332922",
  "version": 1,
  "status": "archived",
  "archived_at": ISODate("2026-04-25T10:00:00Z"),
  "archive_reason": "portfolio_updated",  // portfolio_updated | user_refresh | completed
  "plan_snapshot": {
    // Full plan object at time of archival
  },
  "completion_stats": {
    "total_actions": 3,
    "completed": 2,
    "skipped": 1,
    "completion_rate": 66.7,
    "avg_days_to_complete": 5.5
  }
}
```

**Indexes:**
```javascript
db.plan_history.createIndex({ "user_id": 1, "archived_at": -1 });
db.plan_history.createIndex({ "plan_id": 1, "version": 1 });
```

---

### 1.3 `users` (UPDATED)

**Purpose:** Add UI version preference and analytics visibility settings.

**New Fields:**
```javascript
{
  // ... existing fields ...
  
  "preferences": {
    // Version toggle
    "ui_version": "v2",  // Enum: "v1" | "v2"
    "ui_version_updated_at": ISODate("2026-04-19T10:00:00Z"),
    
    // Analytics visibility (for V2 configurable analytics)
    "analytics_visibility": {
      "overlap": true,
      "overexposure": true,
      "performance": true,
      "cost": false,
      "tax": true
    },
    
    // Other preferences
    "auto_generate_plan": true,  // Auto-generate on portfolio update
    "plan_notifications": true,  // Email when plan is ready
    "action_reminders": true     // Remind to complete actions
  }
}
```

---

### 1.4 `portfolio_snapshots` (NEW - Optional)

**Purpose:** Store portfolio state at time of plan creation for comparison.

**Schema:**
```javascript
{
  "snapshot_id": "snap_abc123",
  "user_id": "user_f087c6332922",
  "plan_id": "plan_20260419_abc123xyz",
  "created_at": ISODate("2026-04-19T10:30:00Z"),
  
  // Portfolio state
  "total_value": 5200000,
  "holdings_count": 28,
  "asset_allocation": {
    "equity_pct": 72.5,
    "debt_pct": 18.0,
    "gold_pct": 9.5
  },
  "sector_exposure": [...],
  "top_holdings": [...],
  
  // Intelligence metrics
  "compression_score": 30.4,
  "overlap_pairs": 15,
  "unique_stocks": 50,
  "effective_stocks": 24.3
}
```

---

## 2. POSTGRESQL TABLES (No Changes)

**Existing tables remain unchanged:**
- `instrument_master`
- `mutual_fund_holdings`
- `mutual_fund_metadata`
- `mutual_fund_performance_ratios`
- `scrape_audit_log`

---

## 3. DATA RELATIONSHIPS

```
┌──────────────┐
│   users      │
└──────┬───────┘
       │ 1:N
       ↓
┌──────────────┐       ┌─────────────────┐
│action_plans  │──────→│ plan_history    │
└──────┬───────┘  1:N  └─────────────────┘
       │
       │ 1:1 (optional)
       ↓
┌──────────────────────┐
│portfolio_snapshots   │
└──────────────────────┘
```

---

## 4. SAMPLE QUERIES

### Get Active Plan for User
```javascript
db.action_plans.findOne({
  user_id: "user_f087c6332922",
  status: "active"
});
```

### Get All Plans for User (with pagination)
```javascript
db.action_plans.find({
  user_id: "user_f087c6332922"
})
.sort({ created_at: -1 })
.limit(10);
```

### Update Action Status
```javascript
db.action_plans.updateOne(
  {
    plan_id: "plan_abc123",
    "actions.action_id": "exit_1"
  },
  {
    $set: {
      "actions.$.status": "COMPLETED",
      "actions.$.completed_at": new Date(),
      "completed_actions": { $add: ["$completed_actions", 1] },
      "pending_actions": { $subtract: ["$pending_actions", 1] },
      "updated_at": new Date()
    }
  }
);
```

### Archive Old Plan (Create New Version)
```javascript
// Step 1: Insert old plan into history
db.plan_history.insertOne({
  history_id: "hist_abc123",
  plan_id: oldPlan.plan_id,
  version: oldPlan.version,
  archived_at: new Date(),
  plan_snapshot: oldPlan
});

// Step 2: Create new plan with incremented version
db.action_plans.insertOne({
  ...newPlan,
  version: oldPlan.version + 1,
  metadata: {
    ...newPlan.metadata,
    parent_plan_id: oldPlan.plan_id
  }
});

// Step 3: Update old plan status
db.action_plans.updateOne(
  { plan_id: oldPlan.plan_id },
  { $set: { status: "archived" } }
);
```

---

## 5. DATA MIGRATION PLAN

### Step 1: Create New Collections
```javascript
// Run in MongoDB shell
db.createCollection("action_plans");
db.createCollection("plan_history");
db.createCollection("portfolio_snapshots");
```

### Step 2: Add Indexes
```javascript
// See index definitions above
```

### Step 3: Update Existing Users
```javascript
db.users.updateMany(
  { "preferences.ui_version": { $exists: false } },
  {
    $set: {
      "preferences.ui_version": "v1",  // Default to V1 for existing users
      "preferences.analytics_visibility": {
        "overlap": true,
        "overexposure": true,
        "performance": true,
        "cost": true,
        "tax": true
      }
    }
  }
);
```

### Step 4: Validation
```javascript
// Verify indexes
db.action_plans.getIndexes();

// Verify user updates
db.users.countDocuments({ "preferences.ui_version": { $exists: true } });
```

---

## 6. STORAGE ESTIMATES

**Assumptions:**
- 1,000 active users
- Each user generates 1 plan per month
- Each plan has 3 actions

**action_plans:**
- Document size: ~8 KB per plan
- Monthly: 1,000 × 8 KB = 8 MB
- Yearly: 96 MB

**plan_history:**
- Document size: ~10 KB per archived plan (with snapshots)
- Yearly: 1,000 × 12 × 10 KB = 120 MB

**Total Storage (Year 1):** ~216 MB (negligible)

---

## 7. BACKUP & RETENTION POLICY

**action_plans:**
- Backup: Daily
- Retention: Indefinite (active plans)
- Archive: Move to `plan_history` when status = "archived"

**plan_history:**
- Backup: Weekly
- Retention: 2 years
- Cleanup: Delete plans older than 2 years (compliance)

---

## 8. DATA PRIVACY & SECURITY

**PII Fields:**
- `user_id`, `asset_name` (contains fund names, may reveal financial status)

**Security Measures:**
- Encrypt `action_plans` at rest (MongoDB encryption)
- Access control: User can only access their own plans
- Audit log: Track all plan modifications

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-19  
**Author:** E1 Agent  
**Status:** Draft for Review
