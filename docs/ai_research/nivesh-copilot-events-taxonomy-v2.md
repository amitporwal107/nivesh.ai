# Nivesh Copilot — Master Corporate Events Taxonomy (v2)

Purpose: the complete coverage map of corporate events for the feed, classifier,
and sentiment engine. Expands the ten UI chips into 12 event families and 70+
distinct event types. For each: what triggers it, the disclosure rule, default
sentiment logic, materiality guidance, and detection keywords for the classifier.

Legend: Reg30 = SEBI LODR Regulation 30 (24h disclosure; 12h if from board
meeting; 30min for board meeting outcomes). Sentiment defaults are starting
points — the LLM rubric judges the specific filing.

---

## Family 1 — ORDERS & CONTRACTS (chip: ORDERS)

| Event | Disclosure | Default sentiment | Detection keywords |
|---|---|---|---|
| Order/contract win | Reg30 if material | Positive; score by value/mcap | "award of order", "letter of award", "LoI", "bagging", "work order", "purchase order" |
| Framework/rate contract empanelment | Reg30 (often voluntary) | Mildly positive — revenue not committed | "empanelment", "rate contract", "framework agreement" |
| Order cancellation / termination | Reg30 | Negative | "termination of contract", "cancellation of order", "foreclosure" |
| Liquidated damages / penalty invoked | Reg30 if material | Negative | "liquidated damages", "penalty", "LD" |
| L1 status (lowest bidder) | Voluntary/press | Cautiously positive — not yet an award | "L1", "lowest bidder", "emerged L1" |
| Contract value revision | Reg30 | Direction of revision | "amendment to contract", "revised order value" |

Notes: L1 announcements are a known pump pattern in smallcaps — badge as
"pre-award" and never as an order win. Track order win -> execution updates ->
completion as one linked entity where companies file updates.

## Family 2 — M&A & RESTRUCTURING (chip: MNA)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Acquisition (company/stake) | Reg30 + detailed annexure | Judge structure & funding | "acquisition", "share purchase agreement", "SPA" |
| Merger/amalgamation | Reg30 + scheme filings | Judge ratio & rationale | "amalgamation", "scheme of arrangement" |
| Demerger / spin-off | Reg30 + scheme | Often positive (value unlock); judge costs | "demerger", "resulting company" |
| Slump sale / asset sale | Reg30 | Depends: monetization vs distress | "slump sale", "business transfer agreement", "BTA" |
| Joint venture formation | Reg30 | Mildly positive | "joint venture", "JV agreement", "MoU" |
| JV/alliance termination | Reg30 | Negative unless exit at gain | "termination of JV", "exit from joint venture" |
| Open offer (SAST) | SEBI SAST filings | Positive for target holders | "open offer", "detailed public statement" |
| Delisting proposal | Reg30 + SEBI process | Usually positive (exit premium); judge price | "voluntary delisting", "floor price" |
| Divestment by promoter/PE | Block deal disclosures | Neutral-to-negative signal | "stake sale", "block deal", "OFS" |
| Merger called off | Reg30 | Negative (usually) | "mutually agreed to terminate", "called off" |

Notes: M&A is a LIFECYCLE — announce -> CCI approval -> NCLT -> completion.
Link stages to one deal entity; sentiment can flip mid-lifecycle (CCI
objections, valuation revisions).

## Family 3 — RESULTS & FINANCIAL DISCLOSURES (chip: EARNINGS)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Quarterly/annual results | Reg33; 30min after board | Arithmetic vs comparatives | "financial results", "regulation 33" |
| Results press release / presentation | With results | Same event, richer color | "earnings presentation", "press release" |
| Earnings call transcript | Within days of call | Feeds tone engine | "transcript", "conference call" |
| Guidance issuance/revision | Voluntary, in above docs | raised/reiterated/lowered/withdrawn | "guidance", "outlook", "we expect FY" |
| Auditor qualification / EoM | In results/annual report | Negative; emphasis-of-matter milder | "qualified opinion", "emphasis of matter", "adverse opinion", "disclaimer of opinion" |
| Restatement of accounts | Reg30 | Strongly negative | "restatement", "rectification of financial statements" |
| Delay in results filing | Exchange notice | Negative (governance) | "extension of time", "unable to declare results" |
| Impairment / write-off | In results or Reg30 | Negative; judge size | "impairment", "write-off", "provision for diminution" |

## Family 4 — CAPITAL RAISING & STRUCTURE (chips: QIP, part of ALL)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| QIP launch/closure | Reg30 + placement doc | Mixed: dilution vs growth capital | "qualified institutions placement", "QIP" |
| Rights issue | Reg30 + letter of offer | Judge purpose & pricing | "rights issue", "letter of offer" |
| Preferential allotment | Reg30 | Scrutinize allottees & pricing; promoter-favorable -> negative | "preferential issue", "preferential allotment" |
| FPO | Full process | As QIP | "further public offer" |
| NCD / bond issuance | Reg30 + term sheet | Neutral-to-mild; judge coupon vs history | "non-convertible debentures", "NCD", "commercial paper" |
| FCCB / ADR / GDR | Reg30 | Judge terms | "FCCB", "foreign currency convertible" |
| Warrant issue/conversion | Reg30 | Watch promoter warrants pricing | "convertible warrants", "conversion of warrants" |
| Debt repayment / prepayment | Voluntary/Reg30 | Positive (deleveraging) | "prepayment of debt", "redemption of NCD", "debt reduction" |
| DEFAULT on debt obligations | SEBI Nov-2019 circular: disclosure within 24h of default beyond 30 days | Strongly negative, max materiality | "default in payment", "delay in servicing" |
| One-time settlement with lenders | Reg30 | Mixed: relief but distress signal | "one time settlement", "OTS" |
| Capital reduction | Scheme + Reg30 | Case-by-case | "reduction of share capital" |

## Family 5 — SHAREHOLDER RETURNS (chips: DIVIDEND, BUYBACK)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Dividend (interim/final/special) | Board outcome, 30min | vs prior-year DPS | "dividend", "record date" |
| Dividend cut/skip | Same | Negative vs stated policy | absence vs history — needs DPS table |
| Buyback (tender/open market) | Reg30 + public announcement | Positive; size & premium | "buyback", "tender offer" |
| Bonus issue | Board outcome | Mildly positive (liquidity signal) | "bonus issue", "bonus shares" |
| Stock split | Board outcome | Neutral-to-mild | "sub-division", "stock split", "face value" |
| Bonus debentures | Scheme | Mildly positive | "bonus debentures" |

## Family 6 — GOVERNANCE & PEOPLE (chip: MANAGEMENT)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| CEO/MD/CFO resignation | Reg30, with reasons letter | Judge why/how fast/succession | "resignation", "cessation", "relinquish" |
| KMP appointment | Reg30 | Marquee hire -> positive | "appointment of", "elevated to" |
| AUDITOR resignation | Reg30 + detailed reasons (SEBI mandate) | ALWAYS negative, high materiality | "resignation of statutory auditor" |
| Independent director exodus | Reg30 | Negative when clustered | "resignation of independent director" |
| Promoter/board dispute | Reg30/media | Negative | "removal of director", "requisition", "EGM by shareholders" |
| Succession announcement | Reg30 | Neutral-positive when planned | "succession", "designate" |
| Key managerial fraud/arrest | Reg30 | Strongly negative | "arrest", "investigation against", "vigilance" |
| Remuneration controversies | AGM outcomes/proxy | Mildly negative | "special resolution rejected" |

Notes: AGM voting RESULTS are underrated signals — a defeated resolution
(auditor reappointment, remuneration) is a governance red flag with a
structured filing (voting results under Reg 44).

## Family 7 — LEGAL, REGULATORY & DISTRESS (chip: LITIGATION)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Material litigation initiated | Reg30 | Negative; size vs mcap | "suit filed", "arbitration invoked", "legal proceedings" |
| Adverse order/award | Reg30 | Negative | "arbitral award", "order passed against" |
| Favorable outcome | Reg30/voluntary | Positive | "demand quashed", "ruled in favour", "set aside" |
| Tax demand (IT/GST) | Reg30 | Negative; judge stage & size | "demand notice", "show cause notice", "assessment order" |
| Search/survey/raid | Reg30 | Negative | "search operations", "survey under section" |
| SEBI order/penalty | SEBI site + Reg30 | Negative | "adjudication order", "SEBI", "debarred" |
| Insolvency petition (IBC 7/9/10) | Reg30 + NCLT | Strongly negative, max severity | "insolvency", "CIRP", "section 7", "section 9" |
| CIRP admission / resolution plan | NCLT/IBBI | Admission negative; approved plan can be positive for acquirer | "admitted", "resolution plan approved" |
| Guarantee invocation | Reg30 | Negative | "invocation of corporate guarantee" |
| Fraud classification by bank | Bank filing + Reg30 | Strongly negative | "classified as fraud" |

## Family 8 — RATINGS & CREDIT (chip: RATING)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Rating upgrade/downgrade | Reg30 mandatory + agency site | Direction; notches | "revised the rating", "upgraded", "downgraded" |
| Outlook change | Same | Same direction, lower score | "outlook revised to" |
| Credit watch | Same | Direction, moderate | "placed on watch" |
| Rating withdrawal (non-cooperation) | Agency | Negative — transparency signal | "issuer not cooperating", "INC" |
| Fresh rating assignment | Same | Contextual | "assigned rating" |

Note: "Issuer Not Cooperating" is a distinctive Indian red flag most
platforms under-weight — treat as negative with medium-high materiality.

## Family 9 — OPERATIONS, ASSETS & PRODUCTS (chip: CAPEX + new)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Capacity expansion announced | Reg30 | Positive if funded | "capacity expansion", "brownfield", "greenfield" |
| Plant commissioning | Reg30/voluntary | Positive — capex converting | "commissioned", "commercial production commenced" |
| Capex deferral/shelving | Reg30 | Negative demand signal | "deferred", "put on hold" |
| New product/segment launch | Voluntary/Reg30 | Mildly positive | "launch of", "foray into" |
| Product recall | Reg30 | Negative | "recall", "withdrawal of product" |
| Plant shutdown/disruption | Reg30 | Negative; judge duration | "shutdown", "suspension of operations", "fire", "accident" |
| Labour strike/unrest | Reg30 | Negative | "strike", "lockout", "labour unrest" |
| Cyber incident / data breach | Reg30 (mandatory since 2023) | Negative | "cyber", "ransomware", "IT security incident" |
| Land/mining lease acquisition | Reg30 | Positive for resource cos | "mining lease", "land acquisition", "allotment of land" |
| Force majeure invocation | Reg30 | Negative | "force majeure" |

## Family 10 — REGULATORY APPROVALS & IP (new — high value for pharma/tech)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| USFDA outcome (EIR/483/OAI/WL) | Reg30 | EIR positive; OAI/Warning Letter negative | "EIR", "form 483", "warning letter", "OAI", "VAI" |
| USFDA product approval (ANDA/NDA) | Reg30/voluntary | Positive; judge market size | "ANDA approval", "final approval", "tentative approval" |
| DCGI/CDSCO approval | Reg30 | Positive | "DCGI", "marketing authorization" |
| Import alert / export ban | Reg30 | Strongly negative | "import alert", "export restriction" |
| Patent grant | Voluntary | Mildly positive | "patent granted" |
| Patent litigation (Para IV etc.) | Reg30 | Case-by-case | "paragraph IV", "patent infringement" |
| License/spectrum win | Reg30 | Positive | "spectrum", "license awarded", "banking licence" |
| Environmental clearance | Reg30/voluntary | Positive (unblocks capex) | "environmental clearance", "consent to establish" |

## Family 11 — OWNERSHIP SIGNALS (Insider/SAST — feeds E-group questions)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| Promoter open-market purchase | PIT disclosures | Positive signal | "acquisition", disclosure under PIT |
| Promoter sale | PIT/SAST | Negative-to-neutral; judge size & stated reason | "disposal", "sale of shares" |
| Pledge creation/increase | SAST pledge disclosure | Negative; track % of holding pledged | "pledge", "encumbrance" |
| Pledge release/revocation | Same | Positive | "release of pledge", "revocation" |
| Pledge INVOCATION by lender | Same | Strongly negative | "invocation of pledge" |
| Bulk/block deals by institutions | Exchange bulk-deal data | Contextual | daily bulk deal files |
| Shareholding pattern shifts | Quarterly Reg 31 XBRL | FII/DII/promoter deltas | structured filing |

## Family 12 — LISTING LIFECYCLE (new)

| Event | Disclosure | Default sentiment | Detection |
|---|---|---|---|
| IPO/listing of subsidiary | DRHP/Reg30 | Often positive (value unlock) | "DRHP", "IPO of subsidiary" |
| New listing / migration to main board | Exchange | Neutral-positive | "listing approval", "migration from SME" |
| Name/symbol change | Exchange | Neutral; CRITICAL for entity resolution | "change of name" |
| GDR/ADR delisting | Reg30 | Neutral | "termination of depositary" |
| Suspension of trading | Exchange action | Strongly negative | "suspension of trading" |
| Exit from F&O / surveillance measures (ASM/GSM) | Exchange lists | Negative liquidity/risk signal | ASM/GSM stage lists |

---

## Coverage engineering notes

1. **Three detection layers per event**: exchange category/subcategory (hint),
   keyword patterns above (candidate), LLM confirmation with the sentiment
   rubric (verdict). Keywords alone misfire ("termination" appears in routine
   agency agreements).
2. **Lifecycle linking** is what separates a feed from a research tool:
   M&A stages, order win -> execution, litigation initiated -> order ->
   appeal, pledge created -> increased -> invoked. Link on (company,
   counterparty/case-id, event family).
3. **Severity ladder** (feed ranking beyond materiality_score): default <
   auditor resignation < fraud classification < insolvency admission <
   trading suspension. These override normal scoring to top-of-feed.
4. **New chips worth adding to the UI** given this taxonomy: APPROVALS
   (Family 10 — pharma users will live in it), PLEDGE/INSIDER (Family 11),
   DISTRESS (defaults + IBC + fraud, Family 4/7 subsets).
5. **Structured filings to parse beyond PDFs**: Reg 31 shareholding XBRL,
   Reg 44 voting results, bulk/block deal CSVs, ASM/GSM lists — all
   machine-readable, all high-signal, all currently outside your pipeline.
