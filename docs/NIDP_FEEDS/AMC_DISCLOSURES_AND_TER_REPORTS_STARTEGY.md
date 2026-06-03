# AMC Disclosure Discovery Engine Strategy

## Objective

Build a resilient and scalable AMC disclosure ingestion framework for:

* Monthly Portfolio Disclosure
* TER (Total Expense Ratio) Reports
* Factsheets
* Statutory Disclosures
* AUM Reports
* SID/KIM Documents

The architecture should:

* Avoid hardcoded PDF URLs
* Automatically discover latest disclosures
* Survive AMC website changes
* Support static and dynamic websites
* Validate downloaded files
* Self-heal broken extraction flows

---

# Core Engineering Principle

## DO NOT STORE

```text
final_pdf_url
```

Because AMC URLs:

* change monthly
* move across CDNs
* change naming conventions
* expire
* break frequently

---

## STORE THIS INSTEAD

```json
{
  "discovery_url": "...",
  "strategy": "playwright",
  "regex": ".*portfolio.*"
}
```

The system should know:

* how to discover files
* not where files permanently exist

---

# Tier Classification

| Tier | Meaning                                    |
| ---- | ------------------------------------------ |
| T1   | Highly stable static disclosure pages      |
| T2   | Stable but partially dynamic               |
| T3   | Dynamic React/JS-driven                    |
| T4   | Weak discovery / recursive crawling needed |

---

# HDFC Mutual Fund (T1)

## Discovery URLs

### Monthly Portfolio

```text
https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio
```

### TER Disclosure

```text
https://www.hdfcfund.com/statutory-disclosure/total-expense-ratio-of-mutual-fund-schemes
```

### Factsheets

```text
https://www.hdfcfund.com/mutual-funds/factsheets
```

## Extraction Strategy

```text
STATIC HTML ONLY
```

### Extraction Rules

```css
a[href$='.pdf']
a[href$='.xlsx']
```

---

# Nippon India Mutual Fund (T1)

## Discovery URL

```text
https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures
```

## Regex

```regex
.*(portfolio|factsheet|expense|ter).*\.(pdf|xlsx)
```

---

# SBI Mutual Fund (T1)

## Discovery URLs

### Portfolio

```text
https://www.sbimf.com/en-us/portfolios
```

### TER Disclosure

```text
https://www.sbimf.com/disclosure
```

### Factsheets

```text
https://www.sbimf.com/en-us/factsheets
```

### Important Pattern

```text
/docs/default-source/scheme-portfolios/
```

---

# Tata Mutual Fund (T1)

## Discovery URLs

### Portfolio

```text
https://www.tatamutualfund.com/schemes-related/portfolio
```

### Statutory Disclosure

```text
https://www.tatamutualfund.com/statutory-disclosures
```

---

# UTI Mutual Fund (T2)

## Discovery URLs

### Forms & Downloads

```text
https://www.utimf.com/forms-and-downloads/
```

### Factsheets

```text
https://www.utimf.com/factsheets/
```

---

# ICICI Prudential Mutual Fund (T3)

## Discovery URLs

### Monthly Portfolio Downloads

```text
https://www.icicipruamc.com/news-and-media/downloads?currentTabFilter=OtherSchemeDisclosures&subCatTabFilter=Monthly+Portfolio+Disclosures
```

### TER Disclosure

```text
https://www.icicipruamc.com/about-us/statutory-disclosures
```

### Factsheets

```text
https://www.icicipruamc.com/downloads/fund-factsheets
```

## Extraction Strategy

```text
PLAYWRIGHT + NETWORK INTERCEPTION
```

### Required Steps

```javascript
await page.goto(url)
await page.waitForLoadState('networkidle')
page.on('response')
```

### Regex

```regex
.*(portfolio|expense|ter).*\.(pdf|xlsx)
```

---

# Axis Mutual Fund (T3)

## Discovery URLs

### Statutory Disclosure

```text
https://www.axismf.com/statutory-disclosures
```

### Downloads

```text
https://www.axismf.com/downloads
```

## Recursive Flow

```text
Disclosure Page
  → Category
      → Monthly Disclosure
          → PDF
```

---

# Kotak Mutual Fund (T3)

## Discovery URLs

### Statutory Disclosure

```text
https://www.kotakmf.com/Information/about-mutual-funds/statutory-disclosure
```

### Factsheets

```text
https://www.kotakmf.com/Information/about-mutual-funds/factsheets
```

## Extraction Strategy

```text
PLAYWRIGHT + ACCORDION EXPANSION
```

---

# Aditya Birla Sun Life Mutual Fund (T3)

## Discovery URLs

### Downloads

```text
https://mutualfund.adityabirlacapital.com/downloads
```

### Resources

```text
https://mutualfund.adityabirlacapital.com/resources
```

## Extraction Strategy

```text
XHR API EXTRACTION
```

---

# Mirae Asset Mutual Fund (T4)

## Discovery URLs

### Statutory Disclosure

```text
https://www.miraeassetmf.co.in/investor-services/statutory-disclosures
```

### Downloads

```text
https://www.miraeassetmf.co.in/downloads
```

## Extraction Strategy

```text
HYBRID FALLBACK
```

---

# Universal AMC Discovery Engine

## Phase 1 — Static Parse

### Libraries

```text
JSoup
BeautifulSoup
Cheerio
```

### Extract

```css
a[href$='.pdf']
a[href$='.xlsx']
```

---

## Phase 2 — Browser Rendering

### Libraries

```text
Playwright
Puppeteer
```

### Wait Condition

```javascript
networkidle
```

---

## Phase 3 — Network Interception

### Capture

```text
XHR
fetch
GraphQL
```

Mandatory for:

* ICICI
* ABSL
* Kotak

---

## Phase 4 — Recursive Discovery

Required for:

* Axis
* Mirae
* UTI

---

## Phase 5 — File Validation

### Validate

```text
HTTP 200
mime-type
content-length
```

### Semantic Validation

Extract PDF/XLS text and verify:

```text
Portfolio
Expense Ratio
Scheme
AUM
```

Reject:

* empty files
* broken downloads
* login pages masquerading as PDFs

---

# Recommended Registry Schema

```sql
CREATE TABLE amc_discovery_registry (
    amc_code TEXT,
    report_type TEXT,
    discovery_url TEXT,
    extraction_strategy TEXT,
    render_mode TEXT,
    regex_pattern TEXT,
    validation_strategy TEXT,
    health_status TEXT,
    last_verified_at TIMESTAMP
);
```

---

# Recommended Architecture

```text
AMC Discovery URL
      ↓
Static HTML Extractor
      ↓
Did files exist?
      ↓
NO
      ↓
Headless Browser Rendering
      ↓
Capture DOM + XHR
      ↓
Extract PDF/XLS/XLSX URLs
      ↓
Validate Files
      ↓
Metadata Extraction
      ↓
Store Metadata + File
```

---

# Final Recommendation

Build:

```text
Universal AMC Disclosure Discovery Engine
```

NOT:

```text
Hardcoded AMC PDF Scrapers
```

The discovery engine itself becomes:

* resilient
* scalable
* self-healing
* difficult to replicate

This is the correct long-term architecture for the Nivesh data platform.
