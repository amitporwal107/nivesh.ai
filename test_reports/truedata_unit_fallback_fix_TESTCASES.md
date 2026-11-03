# TrueData fundamentals — no unit from the filing's rounding text — test cases (written BEFORE the fix, 3 Nov 2026)

Branch `fix/truedata-unit-no-rounding-fallback` (from origin/dev 6d30a7f7). Fixes the merged job of PRs #456/#462
(`backend/nidp/services/truedata_fundamentals/transform.py`).

**Defect.** `unit_for` decides a filing's unit from (1) the company's revenue anchor, (2) its share-capital anchor,
(3) **the filing's own `LevelOfRoundingUsedInFinancialStatements` text**, else refuses. Step 3 is unsafe: TrueData's
text is wrong for real companies (SWIGGY 2024-09-30 says "Millions" with crore values; MANYAVAR, VIMTALABS, KICL have
no anchor and say "Millions" while their values are crore-consistent — MANYAVAR's half-year CFO would load as ₹7.9 cr,
10x too small). Owner rule: never guess a unit. A filing without a revenue or share-capital anchor is REFUSED.

**Fix.** Remove step 3. An anchorless filing is refused with the reason "no revenue or share-capital anchor", plus the
anchor note when there is one and "(filing rounding text 'X' is not trusted)" when the filing carries one. Nothing else
in the transform changes.

Fixtures are SYNTHETIC (TrueData material is under NDA). PG tests run on a throwaway `postgres:16-alpine`,
`--network none`.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| UF-01 | transform | `unit_for`: no anchor, rounding text "Millions" (also "Lakhs", "Crores") | unit | `(None, reason)`; reason says no revenue or share-capital anchor and that the text 'Millions' is not trusted |
| UF-02 | transform | `unit_for`: no anchor, blank rounding text; no anchor with an anchor-mismatch note (RADICO-like ratio 3.475) | unit | `(None, "no revenue or share-capital anchor")`; the mismatch note is kept in the reason |
| UF-03 | transform | `build()`: an anchorless company (no revenue anchor, no shares) whose balance sheet, cash flow and quarter P&L say "Millions" | unit | 0 offers; balance-sheet, cash-flow and finance-cost rejects, each "unit unknown (no revenue or share-capital anchor … 'Millions' is not trusted)" |
| UF-04 | transform | `build()`: an anchored company (revenue anchor → crore) whose filing text says "Lakhs" | unit | offers load in crore (the anchor decides; the text is ignored), values unchanged from before the fix |
| UF-05 | transform | SWIGGY-like: anchored crore with anchor share capital 261; a pre-IPO H1 filing with share capital 13,440 and text "Millions" | unit | balance sheet refused "share capital 13440 vs anchor 261 (unit may differ …)"; still refused after the fix |
| UF-06 | job | whole job (fake client + fake warehouse): anchorless company, text "Millions" | unit | the warehouse is handed 0 offers; status OK; the rejects list the reason |
| UF-07 | loader (PG) | anchorless "Millions" company and an anchored company built together, then loaded into a real Postgres | integration | anchored rows written; for the anchorless company 0 rows changed, 0 rows inserted, 0 provenance rows |
| UF-08 | code | nothing in the module decides a unit from `LevelOfRoundingUsedInFinancialStatements`; the module docstring no longer says "else the filing's own rounding text" | review | grep: the field is read only to quote it in a refusal reason |
| UF-09 | regression | every truedata_fundamentals + truedata_corporate test file, the PG tests, and the CI "Backend unit tests (allowlist)" subset that holds these files | regression | all pass, or failures shown identical on untouched origin/dev |
| UF-10 | real data | the job's transform (`T.build`) offline over `/home/deploy/nivesh-truedata-raw` (read-only), origin/dev code vs this branch, same references (staging snapshot, read-only) | data | refusals for "no anchor" before vs after counted; MANYAVAR, VIMTALABS, KICL refused; SWIGGY 2024-09-30 refused; TCS, RELIANCE, RADICO offers identical before and after; the only offers that disappear are those whose unit came from the rounding text |

Out of scope: no warehouse write, no deploy, no cron install. The rows the supervised loads took from the rounding
text were removed from staging tonight by a separate supervised step (not this PR).
