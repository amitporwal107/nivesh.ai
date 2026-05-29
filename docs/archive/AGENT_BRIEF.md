# Task: Adapt Backend APIs to Nivesh v4 UI Designs

## Context
Nivesh is a portfolio health-check and advisory product. Central concept: 
a 0–100 Health Score (graded A–D) computed across 6 analytical dimensions, 
each exposed as a dashboard with ranked recommendations that flow into a 
unified Plan board. Has investor-facing and advisor-facing surfaces.

We have working backend APIs and new v4 designs covering 17 screens across 
mobile and webapp. The backend has most data needed; we need to expose it 
correctly for the new UI without breaking existing clients.

## Inputs

### Mockups (process in numerical order)
- v4-designs/mobile/ — mobile SVGs (01_homepage.svg through 17_sip_board.svg)
- v4-designs/webapp/ — webapp SVGs (same naming)
- v4-designs/nivesh_mobile.html — mobile HTML reference (field names)
- v4-designs/nivesh_app.html — webapp HTML reference (field names)

Note: SVG files are PNG screenshots wrapped in SVG. To read content, 
extract the embedded base64 PNG and OCR it (tesseract). HTML files contain 
the actual field names — check those first for any field-name questions.

### Product Requirements
- v4-designs/Nivesh_PRD.docx (primary source of truth)
- v4-designs/PRD.pdf (verify identical to docx; if different, flag and 
  treat docx as canonical)

### Existing APIs
- v4-designs/nivesh-postman-collection.json — product/experience APIs
- v4-designs/nidp-postman-collection.json — NIDP data/analytics platform APIs

NIDP = "Nivesh Investment Data Platform" (confirmed from screens showing 
"NIDP-grounded" and "NIDP connected" indicators). Architecture appears to be:
- NIDP = holdings ingestion, classification, score/metric computation
- Nivesh = chat, plan board, recommendations, advisor workflows
Confirm this split in Phase 1.

## Key Domain Concepts (from screens)
- **Health Score**: 0–100, graded A–D, central metric
- **6 Dashboards**: concentration, diversification, risk, performance, 
  goals, tax — all share identical structural pattern
- **Recommendation**: {title, action, impact, effort, tradeOff, priority} 
  — first-class entity, produced by dashboards, consumed by plan board
- **Plan Board**: unified action queue aggregating recommendations from 
  all 6 dashboards with to-do/done/skipped state
- **Sleeve**: asset class bucket (equity/debt/gold) in portfolio builder
- **Two personas**: investor (screens 01–14, 17) and advisor (15, 16, 17)

## Constraints

- **Additive changes only**: do NOT break existing endpoints. Mobile app 
  and any partners still use them. Deprecate, don't delete.
- **Both mobile and webapp**: assume response-shape parity unless mockups 
  clearly diverge. If they diverge, prefer one endpoint with optional 
  fields or a `view=mobile|web` param over two endpoints.
- **Role separation**: investor and advisor endpoints must have clear 
  permission boundaries. Default pattern: advisor endpoints under 
  `/advisor/*` namespace; flag if a different pattern fits better.
- **Naming and conventions**: follow the existing Postman collection's 
  patterns (HTTP verbs, path style, auth header, error format, pagination).
- **Performance budget**: no endpoint should require more than 3 DB queries; 
  use joins/includes for related data. Flag any required computation 
  that exceeds this.
- **PRD wins conflicts**: when mockup and PRD disagree, PRD is canonical. 
  Always flag the conflict in open questions.

## Workflow — Strict Phase Gates

### Phase 1: Gap Analysis (STOP for review)
1. Read PRD first
2. Extract and OCR all 17 mobile + 17 webapp screens
3. Cross-reference HTML files for exact field names
4. Read both Postman collections; build endpoint index
5. Produce `docs/gap-analysis.md` using `docs/gap-analysis-template.md` 
   as the structure
6. STOP. Wait for explicit approval before Phase 2.

### Phase 2: Design Proposal (STOP for review)
1. Produce `docs/api-changes.md` using `docs/api-changes-template.md`
2. Decide and justify:
   - Dashboard endpoint shape (one composite vs six focused)
   - Advisor access pattern (scoped vs mirrored namespace)
   - NIDP vs Nivesh placement for each new endpoint
   - Recommendation entity schema (shared across dashboards + plan board)
3. Produce draft `v4-designs/nivesh-postman-collection.v2.json` with all 
   proposed new/modified endpoints
4. STOP. Wait for explicit approval before Phase 3.

### Phase 3: Implementation
1. Implement one endpoint at a time
2. After the FIRST endpoint, pause and show the diff so I can confirm the 
   pattern before you continue with the rest
3. For each endpoint:
   - Match reference pattern from [SPECIFY PATH TO REFERENCE ENDPOINT]
   - Add integration test asserting every mockup field is present in response
   - Update v2 Postman collection
   - Add code comment listing screens served (see Traceability below)
4. Group commits by logical unit (one group of related endpoints per commit)

### Phase 4: Verification
1. Run full test suite; report results
2. For each changed endpoint, generate a sample response and verify every 
   field shown in the corresponding mockup is present
3. Produce PR description with table mapping screens (mobile + web) to 
   endpoints serving them
4. Update `docs/api-changes.md` to reflect final state

## Traceability Requirement
Every new or modified endpoint must have a code comment listing screens served: