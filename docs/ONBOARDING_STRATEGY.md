# NIVESH — Smart Client Onboarding Flow

## Goal

Create the fastest possible onboarding journey for:

* Retail investors
* HNI investors
* MFD/IFA-assisted clients
* PMS/advisory clients

while maximizing:

* Portfolio ingestion rate
* Activation rate
* Trust
* Data completeness
* "Wow" moments in first 2 minutes

Core principle:

> Ask for the minimum possible information upfront and progressively enrich later.

---

# 1. North Star Metrics

| Metric                          | Target       |
| ------------------------------- | ------------ |
| Time to first portfolio insight | < 60 seconds |
| Steps to onboarding             | <= 3         |
| Broker connect success rate     | > 85%        |
| Portfolio upload success        | > 90%        |
| User drop before insight        | < 15%        |
| First-session wow moment        | < 90 seconds |

---

# 2. Golden UX Principles

## A. No Forced Signup First

Avoid:

* Long registration forms
* PAN upfront
* Risk questionnaire upfront
* KYC before value

Instead:

1. Connect broker
2. Upload statement
3. View instant insights
4. THEN ask signup/login

This dramatically improves conversion.

---

## B. Give Value Before Asking Questions

Wrong flow:

* Name
* PAN
* Email
* Mobile
* Risk profile
* OTP

Correct flow:

* Upload/connect
* Show portfolio health
* Show hidden insights
* THEN ask for account creation

---

## C. One CTA Only

Homepage should have ONE dominant action:

# "Import Your Portfolio"

Subtext:
"Works with Zerodha, Groww, Angel One, ICICI Direct, CAMS & Excel uploads"

---

# 3. Ideal Client Onboarding Flow

# FLOW A — Retail Self-Serve (Recommended Default)

## Step 1 — Import Portfolio

### User sees:

## "How would you like to import your investments?"

### Options:

| Option         | UX Complexity      | Recommended |
| -------------- | ------------------ | ----------- |
| Connect Broker | Lowest friction    | Primary     |
| Upload CAS PDF | Excellent coverage | Primary     |
| Upload Excel   | Fallback           | Secondary   |
| Manual Entry   | Avoid initially    | Hidden      |

---

## UI Recommendation

Large cards:

* Zerodha
* Angel One
* Groww
* ICICI Direct
* Upstox
* Motilal Oswal
* Upload CAS
* Upload Excel

with:

* Broker logos
* "Takes ~30 sec"
* "Secure & Read Only"

---

# Step 2 — Auto Fetch & Parse

Immediately after upload/connect:

## Background Processing

System should:

* Detect broker
* Parse holdings
* Normalize data
* Fetch live prices
* Categorize assets
* Calculate allocation
* Detect duplicates
* Identify risk

Target time:
< 15 seconds

---

# Step 3 — Instant WOW Dashboard

This is the MOST important screen.

User should immediately see:

## Portfolio Snapshot

| Insight               | Example   |
| --------------------- | --------- |
| Net Worth             | ₹18.4L    |
| Total Gain            | +₹2.3L    |
| XIRR                  | 18.2%     |
| Diversification Score | 62/100    |
| Risk Score            | High      |
| Hidden Concentration  | 42% in IT |
| Portfolio Health      | 7.4/10    |

---

# 4. First "Wow" Moments

Nivesh must generate emotional value instantly.

## Recommended wow widgets

### A. "Your money personality"

"You invest like a growth-focused moderate-risk investor"

---

### B. Concentration detector

"You may be overexposed to Midcap IT"

---

### C. Hidden overlap detector

"3 mutual funds hold the same stocks"

---

### D. Better alternative insight

"You are paying high expense ratio in 2 funds"

---

### E. Goal gap estimation

"At current growth, your retirement goal may fall short by ₹1.2Cr"

---

### F. Risk visualization

Interactive risk meter.

---

### G. AI portfolio summary

Example:

"Your portfolio is moderately diversified but heavily tilted toward technology and large-cap equities. Risk-adjusted returns are strong, but debt allocation is low for your age profile."

---

# 5. Only AFTER Value → Ask Signup

Once user sees insights:

## Modal:

### "Save your portfolio insights"

Options:

* Continue with Google
* Continue with mobile OTP
* Continue with email

Avoid password creation.

---

# 6. Smart Progressive Profiling

DO NOT ask 20 questions upfront.

Instead collect over time:

| Stage     | Data Collected |
| --------- | -------------- |
| Session 1 | Mobile/email   |
| Session 2 | Age + goals    |
| Session 3 | Income range   |
| Session 4 | Risk profile   |
| Session 5 | Family details |

---

# 7. HNI Onboarding Flow

HNI users usually:

* Have multiple brokers
* Have PMS/AIF
* Use CA/family office
* Need trust

## Recommended HNI flow

### Step 1

"Connect all your investment accounts"

### Step 2

Bulk import:

* NSDL/CDSL
* CAMS/KFintech
* Broker statements
* PMS statements

### Step 3

Unified family net-worth dashboard.

---

# 8. MFD / IFA Assisted Onboarding

Critical for scaling distribution.

## Advisor Flow

### Step 1

Advisor invites client via:

* WhatsApp
* Email
* QR code

### Step 2

Client opens smart upload page.

### Step 3

Client uploads:

* CAS
* Broker statement
* Excel

### Step 4

Nivesh auto-generates:

* Client portfolio dashboard
* Health score
* Risk analysis
* Suggested actions

### Step 5

Advisor reviews before sharing.

---

# 9. Recommended Architecture

# Ingestion Layer

## Sources

| Source           | Priority |
| ---------------- | -------- |
| Broker APIs      | P1       |
| CAS PDF          | P1       |
| Excel Upload     | P1       |
| NSDL/CDSL        | P1       |
| Email Parsing    | P2       |
| WhatsApp Parsing | P3       |

---

# 10. Recommended Broker Connect Strategy

## Best UX Approach

### OAuth / Deep Link Connect

Avoid:

* Asking broker passwords
* Manual token entry

Preferred:

* Redirect-based auth
* OpenAlgo/OpenWealth style adapters
* Read-only permission

---

# 11. Smart Error Recovery

Critical for conversion.

## If parsing fails:

DO NOT show:
"Upload failed"

Instead:

### "We found 92% of your portfolio. Help us verify 2 entries."

This dramatically reduces abandonment.

---

# 12. Recommended AI Features During Onboarding

## AI Auto Categorization

Example:

* IT
* Banking
* Defence
* Gold
* US Equity

---

## AI Duplicate Detection

"You hold Infosys directly and through 4 mutual funds"

---

## AI Risk Narration

"Your portfolio may fall more than market averages during volatility"

---

## AI Opportunity Detection

"Your cash allocation is unusually high"

---

# 13. Smart Gamification

## Portfolio Health Score

| Score | Meaning         |
| ----- | --------------- |
| 90+   | Excellent       |
| 70–89 | Strong          |
| 50–69 | Moderate        |
| <50   | Needs Attention |

This increases engagement massively.

---

# 14. Trust Builders

Critical for finance onboarding.

## Must Have

* "Read Only Access" badge
* SEBI-style security messaging
* AES-256 encryption messaging
* No trading permissions
* No bank access
* Delete data anytime

---

# 15. Mobile-First Strategy

Most Indian users will onboard via mobile.

## Must optimize:

* WhatsApp-first flows
* PDF upload from phone
* One-click Google login
* Autofill OTP
* Camera scan upload

---

# 16. Best Performing Entry Point

Most effective landing page hero:

# "See all your investments in one place"

Subtext:

"Connect brokers, mutual funds & statements in under 60 seconds"

CTA:

# "Import Portfolio"

NOT:

* "Sign Up"
* "Create Account"
* "Get Started"

---

# 17. Recommended Phase-wise Rollout

# Phase 1 — MVP

## Must Have

* CAS upload
* Excel upload
* Zerodha connect
* Angel One connect
* Holdings dashboard
* Portfolio health score
* AI summary

---

# Phase 2

* ICICI Direct
* Groww
* Upstox
* Transaction parsing
* P&L analytics
* Goal tracking

---

# Phase 3

* PMS/AIF onboarding
* Family office dashboard
* AI advisor copilot
* WhatsApp onboarding
* Voice onboarding

---

# 18. Most Important Strategic Insight

The onboarding itself should feel like:

## "Instant portfolio intelligence"

—not a financial form.

The faster users see:

* gains
* risk
* mistakes
* opportunities
* insights

…the higher your activation and retention.

---

# 19. Recommended Final UX Flow

## 3-Step Golden Flow

# STEP 1

Import Portfolio
(Broker/CAS/Excel)

↓

# STEP 2

AI analyzes portfolio
(10–15 seconds)

↓

# STEP 3

See insights instantly
(Health, risk, gains, overlap, opportunities)

↓

# STEP 4

Optional signup to save progress

This is likely the highest-converting onboarding strategy for Nivesh.
