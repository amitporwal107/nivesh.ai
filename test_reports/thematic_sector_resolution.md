# Functionality Verification Report — Thematic + Sector-aware copilot search (master-data resolution)

- **Branch:** feat/filings-intelligence-design (shipped to `dev`)
- **Date:** 2026-07-21
- **Author:** Claude (Full-Stack Developer + QA)
- **Environment:** staging (staging.niveshcopilot.com :443 API / :8443 UI · nidp_staging · DaaS 8084)
- **Changed areas:** backend routes/services: **yes** (daas_api/routers/intelligence.py) · copilot code: **yes** (copilot_agent/nodes/stocks_insights.py, copilot_tools/symbol_resolver.py) · frontend src: no

## Summary
The copilot's cross-company "thematic" search returned nothing in the UI. Root-caused to
five defects and fixed each, verifying every fix by firing the query through the **live
copilot SSE API** (`POST /api/chat/stream`, real `session_token`) and matching the widget
+ grounded answer against the corpus — not side-channel DB reads. (1) `/v1/intelligence/
events/search` queried `events.v_search_documents`, a pipeline that was never populated
(0 rows), instead of the 19,586 real filings in `nidp.corporate_announcements`. (2) Its
FTS used `'simple'` (no stemming) so `Dividends` never matched `Dividend`. (3) It ANDed
every term so a phrased ask matched no subject line. (4) The lexical symbol resolver
collapsed `company`→TITAN and sector words (`pharma`→SUNPHARMA) so cross-company asks ran
a single-ticker lookup. (5) New capability per user direction: **sector-aware resolution
via the master tables** — a sector ask resolves to its constituents from
`nidp.sector_master` keyed on **ISIN** (NSE filings carry it 100%) with a canonical-name
fallback (BSE filings have neither ISIN nor ticker).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | events/search | `q=dividend` direct on 8084 | api | >0 real dividend rows | PASS |
| TC-2 | FTS stemming | `q="Dividends declared this quarter"` direct | api | >0 (was 0 with 'simple') | PASS |
| TC-3 | copilot thematic | "Dividends declared this quarter" via live copilot | e2e | events>0, cited amounts | PASS |
| TC-4 | copilot thematic | "Biggest orders on the tape this week" | e2e | order events + values | PASS |
| TC-5 | copilot thematic | fund raise / board changes / rating / buyback / capex | e2e | correct category events | PASS |
| TC-6 | routing | "how big is each IT company…" not → TITAN | e2e | mode=thematic | PASS |
| TC-7 | resolver unit | `company`/`IT`→None; TITAN/RELIANCE/HDFCBANK still resolve | unit | as expected | PASS |
| TC-8 | sector SQL | Information Technology → constituents' events by ISIN | api | TCS/HCL/TechM/Wipro events | PASS |
| TC-9 | sector copilot | "how are IT companies doing" via live copilot | e2e | IT events + grounded answer | PASS |
| TC-10 | sector routing | "pharma sector M&A" not → SUNPHARMA | e2e | mode=thematic, pharma events | PASS |
| TC-11 | sector detector | pronoun "is it a good time" → None (no false sector) | unit | None | PASS |
| TC-12 | honesty | "AI business in dollars" → grounds out, no hallucination | e2e | "Data unavailable" | PASS |

## API / Endpoint Tests (staging)

- **Endpoint:** `GET /v1/intelligence/events/search` on DaaS 8084 (staging)
  - `q=dividend` → `events: 4` — CMPDI (Record Date/Dividend), One 97 (Bonus)  → PASS (TC-1)
  - `q="Dividends declared this quarter"` (pre-english fix) → `0`; (post-english+OR fix,
    verified against nidp_staging) → ICICI Bank / Zuari / CMPDI / Shyam Metalics → PASS (TC-2)
  - Sector SQL, `sector='Information Technology'` → TCS (orders), HCL/TechM/IKS (mna),
    Wipro/Cyient (buyback), L&T Tech (rating), Tata Tech (earnings), Sagility (dividend) → PASS (TC-8)

## Live Copilot Tests (POST https://staging.niveshcopilot.com/api/chat/stream)
> Real SSE fires with `Cookie: session_token=…` (user-provided token 7bde1212…). Widget +
> grounded answer captured verbatim.

- **"Dividends declared this quarter"** → `mode=thematic empty=False events=8 sources=8`;
  answer: "CMPDI: 1st interim dividend of ₹1.05… Shyam Metalics: ₹1.80… Oberoi Realty: ₹2…
  Wipro: ₹2…" [cited] → PASS (TC-3)
- **"Biggest orders on the tape this week"** → `events=8`; answer: "EMS: LOA from UP Jal
  Nigam ₹10,284.76 lakhs; Goldiam: export order ₹60 cr; Monarch: ₹4,36,17,000; Cosmic CRF:
  ₹292.76 lakhs" [cited] → PASS (TC-4)
- **fund raise** → `qip` events (Emrock ₹43.44 cr warrants, Viceroy); **board changes** →
  `management` (Vivo Bio Tech, Bandhan Bank); **credit rating** → `rating` (Aeroflex/CRISIL);
  **buyback** → `buyback` (Kajaria, Orbit ₹250/sh); **capex** → `capex` (Smartworks, Tatva
  Chintan Dahej-III) → PASS (TC-5)
- **"how big is each IT company AI business in dollars"** → pre-fix `mode=ticker` (TITAN);
  post-fix `mode=thematic`, answer "Data unavailable… Which company? Type $TICKER" (correct —
  Indian IT filings carry no standalone $ AI-revenue line; no hallucination) → PASS (TC-6, TC-12)
- **"how are IT companies doing this quarter"** → `mode=thematic events=8`; answer: "TCS:
  multi-year AI deal with ABB; Tata Technologies: PAT ₹174.55 cr; HCLTech: GIFT City centre"
  [cited] → PASS (TC-9)
- **"which banks are in the news"** → `mode=thematic`; answer: "Kotak Mahindra Bank: business
  transfer to acquire Deutsche Bank's India retail/wealth business ~₹281.7 cr; Karur Vysya
  Bank: appointment" [cited] → PASS
- **"pharma sector M&A and news"** → pre-fix `mode=ticker` (SUNPHARMA); post-fix
  `mode=thematic`, answer: "Aster DM Healthcare + Quality Care merger (39 hospitals);
  Aurobindo Pharma acquired Lannett" [cited] → PASS (TC-10)
- **"metal and steel companies news"** → JSW Steel NCLT amalgamation, PAT ₹5,514 cr [cited];
  **"auto sector this month"** → Samvardhana Motherson acquisitions [cited] → PASS

## Unit Tests
- `resolve_symbol`: `company`/`IT company`/`Dividends…`/`PSU banks` → None; TITAN, RELIANCE,
  HDFCBANK, TATAMOTORS, `$INFY`, `$PERSISTENT` still resolve; no regression on lowercase
  `persistent` (was already None pre-edit, confirmed via git-stash A/B) → PASS (TC-7)
- `_detect_sector` (DaaS): IT/pharma/banks/cement/auto/metal/telecom → correct sector;
  "is it a good time" & "Dividends declared this quarter" → None → PASS (TC-11)
- `_names_sector` (node): "pharma sector"/"IT companies"/"banking stocks" → True; "how is
  sun pharma looking"/"reliance industries results" → False → PASS

## Data Correctness (staging)
- Identity coverage (30d): NSE_ANN 14,352 rows — 100% carry ISIN + ticker; BSE_ANN 5,234 —
  **0** carry ISIN/ticker (scrip_code only). Confirms ISIN is the right NSE key and canonical
  name is the only BSE bridge.
- `nidp.sector_master`: 2,415 rows, all ISIN; **500** carry sector/industry (NIFTY-500),
  20 sectors, IT = 27 companies.
- IT sector → 352 announcements/30d (294 via exact ISIN), categories incl. mna 17, dividend
  11, buyback 3, earnings 7, management 19 → the golden events the feature surfaces.

## Known limitations (honest scope)
- Sector classification covers **500 companies** (NIFTY-500) — BSE-only micro-caps and the
  ~4,400 unclassified NSE equities have no sector, so a sector answer is NIFTY-500-scoped.
- BSE filings (no ISIN/ticker) join only by canonical name; 0 IT-sector BSE rows recovered in
  the window (big IT names are NSE-primary, so covered). A durable fix needs a BSE
  scrip_code→ISIN master to populate `corporate_announcements.isin` / `security_master.bse_code`.
- **prod (`/opt/nidp/repo`, `main`) deliberately untouched** per standing instruction; all of
  the above is staging (`dev` branch, dev-repo mount, nidp_staging).

## Inputs required from user
- session_token for the live copilot fires (provided: 7bde1212-6773-4913-bfee-f39aec2c2695).

## Verdict: PASS
