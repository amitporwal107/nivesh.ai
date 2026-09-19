# Trendlyne point-in-time audit — Day 0 (2026-09-19)

**Status: sample audit complete; NOT a certification.** Two approvals are pending:
- **DEL-06:** your approval before any audited data is used in training or backtests.
- **QA-06:** your confirmation of the 3 manual PDF checks.

`config/policy.json` is unchanged: every category is still `UNVERIFIED`. The classes below are **proposals**.

Plan: `/root/.claude/plans/cryptic-sleeping-flask.md` (rev. 3). Acceptance matrix: `PIT_AUDIT_ACCEPTANCE.md`.
Code: `research/pit_audit/`. Data (not in git): `/app/research/pit_audit/{nse,bse,trendlyne,analysis,manual}`.

Final analysis file: `analysis/analysis_20260919T130527.json`, sha256 `707561677c14f927f20e4e84be957b2cd7e40958542794eff19ac9549d5c775d`. The file lists the sha256 of every input it read. Every number below comes from that file.

> **Scope statement.** The audit certifies only the tested data categories, metrics, filing formats and sample
> population under the documented methodology. It does not certify Trendlyne PIT validity for the entire stock
> universe or for untested metrics and periods.

## 1. Executive summary

| Question | Answer |
|---|---|
| **Q1. Can Trendlyne say what was known at a past date?** | **No.** Every tool rejects an as-of argument: `additionalProperties: false` on all 12 tools, and the probe returned `Unexpected keyword argument`. No parameter carries a filing or publication time. Quarterly values are today's snapshot, labelled relative to today ("Net Profit 1Q Ago" … "8Q Ago"). |
| **Q2. Do Trendlyne's values match the exchange filings?** | **Mostly, for the latest quarters, but with documented definition differences.** Of 665 financial values compared, 406 match an NSE filing and 229 differ for a known definition reason (next row). 30 are unexplained, 18 of them material. For ownership, promoter (219) and MF (234) always match within display rounding; FII (17 of 234) and DII (75 of 234) differ by category mapping. |
| **Trendlyne definitions found** | "Total Rev." is **total income** (revenue plus other income): 138 cases. "Net Profit" is the **owners' share** of consolidated PAT: 80 cases. "Basic EPS" **includes discontinued operations**: 10 cases (HUL Dec-25: 28.12 vs 9.03 from continuing operations). |
| **A match is not point-in-time evidence** | RKFORGE Dec-24: the first XBRL filed PAT of ₹996.1 cr, a 10× scale error that a later filing corrected to ₹99.6 cr. **Trendlyne shows the corrected 99.61.** Its history is the latest revision, not what was known on the day. |
| **Q3. When did filings become public?** | NSE's XBRL listing time is exact to the second, but it is **not** first publication. In 472 of the 502 results filings matched to BSE, BSE published the results PDF **more than 15 minutes earlier (median 1.98 h)**. Board meetings end, BSE publishes 11–39 minutes later, and NSE's XBRL follows hours after that (manual checks). |
| **Availability confidence** | 24 of 576 original results filings reach HIGH (two exchanges agree within 15 minutes); 548 are MEDIUM; 4 are LOW (contradictions). All 323 shareholding filings are MEDIUM (NSE only; BSE shareholding times were not collected). |
| **Q4. Feature eligibility** | The gate `is_feature_eligible()` is implemented and tested, including all 7 leakage scenarios. **No Trendlyne category is historically eligible.** NSE-filed results and shareholding are eligible only for the 24 HIGH filings (EXACT_PIT), or under a conservative rule that needs your approval (§8). |

## 2. Sample, window and what was NOT tested

- **Sample (OPS-01):** `config/sample_manifest.json`, seed 20260919.
  - 30 random Nifty 500 members.
  - 10 risk stocks: ITC, HINDUNILVR, SIEMENS, ULTRACEMCO, IDFCFIRSTB, TMPV (alias TATAMOTORS), ABCAPITAL, VEDL, CASTROLIND, ABB.
  - Sector mix includes banks (IDFCFIRSTB, PNB), NBFC/HFC, general insurers (NIACL, GODIGIT) and non-March year-ends (CASTROLIND, ABB, SIEMENS, 3MINDIA).
- **Window (OPS-02):** 8 quarters, 2024-09-30 → 2026-06-30. Results filings with broadcast dates from 2024-10-01 to 2026-09-19.
- **Tested:**
  - quarterly PAT, revenue and basic EPS, plus the explanatory definitions (total income, interest earned, owners' PAT, EPS including discontinued operations);
  - shareholding: promoter, FII, DII, MF, public;
  - board-meeting dates (4 stocks);
  - Trendlyne capability.
- **Formats tested:**
  - results: legacy Reg-33 (Sep-24, Dec-24) and Integrated Filing (Mar-25 onwards); Ind-AS, Banking, NBFC and General-Insurance taxonomies;
  - shareholding: pre-2025, transition (mid-2025, percent values) and current (fractions).
- **NOT tested (they stay UNVERIFIED or FORWARD_ONLY):**
  - Trendlyne ratios/scores, news, SAST, bulk/block deals, bonus/split/rights, and annual statements;
  - BSE shareholding times;
  - NSE corporate-announcement (PDF) times, not collected under the minimal-proxy rule;
  - effects of corporate actions on ownership (CAT-03);
  - a second Trendlyne archive date (needed for TL-03 and CMP-06).
- **Survivorship:** current Nifty 500 members only.

## 3. Definitions used (G-04, G-05, AV-01..05)

- **Times kept separately:** `period_end`, `submitted_at`, `broadcast_at`, `exchange_disseminated_at`, `document_available_at` (HTTP Last-Modified), `first_publicly_available_at` and `available_at`.
- **`retrieved_at` is never evidence:** `availability.evidence()` raises an error if given one.
- **Rule AV-1 v1.1:**
  - HIGH = at least two independent operators (NSE, BSE) with announcement times at minute precision or better, agreeing within 15 minutes. Availability = the earliest agreeing time.
  - MEDIUM = an NSE broadcast or dissemination time only.
  - LOW = day precision only, or a contradiction (a public time more than 15 minutes before submission).
  - **v1.1 change:** a document's Last-Modified time only corroborates. An archive file can exist before it is announced, so letting it set the time would move availability earlier, in the leakage direction.
- **Decision cutoffs:** eod 15:30 IST; next_open 09:14 on the next session; intraday = the close of the last completed bar. Rule: `available_at + 5 min <= cutoff` (inclusive). Calendar = actual traded sessions (Kite Nifty 500 index, 2024-08-01 → 2026-09-18); dates outside it are *unknown*, not guessed.
- **Classes and the `point_in_time_validated` flag (POL-03):**
  - `EXACT_PIT` → validated only if the value matches the filing AND availability is HIGH.
  - `PIT_VALIDATED_RULE` → validated only if the rule has an id, version, sample size, coverage and `approval_status = APPROVED`.
  - `ESTIMATED_RULE`, `RESTATED`, `FORWARD_ONLY`, `UNVERIFIED` → always false.
  - `FORWARD_ONLY` data is usable only through `is_forward_eligible()`, for decisions at or after the category's `archive_start_at`, and never for historical training.

## 4. Data collected (OPS-03..05)

| Source | Route | Estimated | Actual | Failed | Rate-limited |
|---|---|---|---|---|---|
| NSE results and shareholding listings | production proxy, paced 2.5 s, abort after 2 consecutive 403/429 | 69 | 69 | 0 | 0 |
| NSE XBRL documents (GET + HEAD) | direct to nsearchives, paced 0.4 s | 926 + 926 (after a 3-document trial) | 929 + 929 | 2: an `/-` placeholder link and one SHYAMMETL shareholding 404 | 0 |
| BSE scrip master and "Result" announcements | direct | ≥ 313 (1 + 39 scrips × 8 windows) | 322 (including a 9-request trial) | 0 | 0 |
| BSE results PDFs (manual checks) | direct; AttachLive, then AttachHis | 3 | 5 (2 AttachLive 404s → AttachHis) | 2 fell back successfully | 0* |
| Trendlyne MCP | Redis-cached client | ≤ 60 | **57** (56 main run + 1 confirmation call) | 0 | — |

\*The run summary shows 1 because of a counting bug: the request logger matched "403"/"429" anywhere in the error text, including attachment names. It's fixed and tested (`test_request_log_counts_rate_limits_from_status_not_from_url_digits`).

- NSE listings: 35,135 filing rows (all symbols; the sample is filtered afterwards). 929 unique sample documents.
- Artifacts are content-addressed and write-once: NSE 982, BSE 293. `verify_artifacts()` found 0 corrupt files.
- Metrics were re-derived **offline from the stored artifacts** through five extractor versions (0.1.1 → 0.1.5); nothing was overwritten (ARC-05).

## 5. Findings and deficiencies

**New findings (F):**
- **F-1:** XBRL (both formats) has no comparative-period columns, so a **restatement cannot be proven from XBRL**; only the PDFs show it. No difference is labelled RESTATEMENT.
- **F-2:** in legacy XBRL, the year-to-date context declares the quarter's dates. Only the per-context `DateOfStart/EndOfReportingPeriod` facts identify the quarter. The audit extractor uses those, and the NH fixture proves it.
- **F-3:** the timestamp in an XBRL `.xml` file name is a **12-hour clock without AM/PM**. Across 35,135 listing rows the hour is never above 12 and always equals the broadcast time or sits exactly 12 hours earlier. It's stored only when the hour proves a 24-hour clock (13–23 or 00), as in iXBRL `.html` names, and is never used as a public time.
- **F-4:** legacy `reInd` is **not a revision flag**. It is the accounting format (N = Ind-AS, F = NBFC, A = non-Ind-AS/bank) and tracks `bank`/`indAs` exactly. The legacy listing has no revision indicator, so later filings are ordered by broadcast time and labelled `LATER_FILING_UNFLAGGED`.
- **F-5:** the NSE XBRL listing broadcast is **not first publication**. It is BSE-earlier by more than 15 minutes in 472 of 502 matched filings (median 1.98 h), within 15 minutes in 24, and later in 6. Using it as `available_at` is **conservative** (it is NSE's own public time, never earlier than it), but it loses the same-session window (HUL: PDF at 10:21, XBRL at 17:25).
- **F-6:** a first-filed XBRL can be wrong and later corrected: RKFORGE Dec-24, 10× scale; 3MINDIA and SHYAMMETL total EPS at 2×; ABCAPITAL EPS 0.00 → 1.55. **10 later filings changed an as-filed value** (§6c).
- **F-7:** NSE legacy rows carry pre-split ISINs (ONGC INE213A01011; BSE lists INE213A01029). BSE codes were resolved by issuer prefix plus symbol, and the method is recorded per stock.
- **F-8:** mid-2025 transition shareholding filings use the new contexts with **percent** values. The scale is read from the filing's own total (1 or 100), never guessed.

**Deficiencies in existing code:** documented only. NIDP parsers and production services were not modified (G-02).
- **DEF-1:** the NIDP shareholding list parser merges broadcastDate and submissionDate.
- **DEF-2:** the NIDP results parser matches contexts on end date only, and the first write wins, so it can return the YTD value as the quarter.
- **DEF-3:** the list parser drops `filingDate`, `exchdisstime` and `isin`, and skips filings without XBRL.
- **DEF-4:** integrated revisions have no broadcast date, so they are LOW and never eligible.
- **DEF-5:** `plain_http` returns no response headers (HEAD requests are done separately).
- **DEF-6:** the NIDP results PAT map lacks `ProfitLossForPeriod`, so PAT is None. **This may affect production NIDP.**
- **DEF-7:** `research/trendlyne/tl_cache` maps response labels to codes by fuzzy match. The historical codes (`npqmq1`…) went unmapped, and **`get_params` returned None silently** for all 40 stocks. The raw labelled values were archived and are used here. The cache needs a fix (not in scope).
- **DEF-8:** the NIDP shareholding parser returns no rows for the pre-2025 format (every Sep-24, Dec-24 and Mar-25 filing).
- **DEF-9:** the NIDP shareholding parser expects `MutualFunds_ContextI`, but filings use `MutualFundsOrUTI_ContextI`, so **mf_pct is always None**.
- **Mitigation:** the audit uses its own tested readers (`xbrl_extract.py`, `shp_extract.py`) for DEF-2, 6, 8 and 9.

## 6. Q2 — value representation

### 6a. Financials: Trendlyne vs NSE first filing (CMP-01..06)
- Trendlyne snapshot as of 2026-09-18, fetched 12:13 IST on 2026-09-19. 40 stocks; PAT for lags 0–8, revenue and EPS for lags 0–4.
- Primary basis: consolidated when the company files it, else standalone. The other basis counts only as an explanation.
- Tolerance (`config/comparison.json`): PAT and revenue max(₹0.5 cr, 0.5%); EPS max(₹0.01, 1%). Materiality 5%, reported separately.

| Metric | Trendlyne values | Compared | Match first filing | Match later revision | Definition difference (reason) | Unexplained (material) | NSE value missing | Outside window | Trendlyne blank |
|---|---|---|---|---|---|---|---|---|---|
| PAT | 360 | 303 | 206 | 1 (RKFORGE) | 80 (owners' share) | 16 (7) | 16 | 39 | 2 |
| Revenue | 200 | 177 | 26 | 0 | 139 (138 total income, 1 other basis) | 12 (9) | 23 | 0 | 0 |
| Basic EPS | 200 | 185 | 173 | 0 | 10 (includes discontinued) | 2 (2) | 15 | 0 | 0 |
| **Total** | **760** | **665** | **405** | **1** | **229** | **30 (18)** | **54** | **39** | **2** |

- **Lag anchoring (TL-03):** 635 of 665 compared values match the quarter implied by "NQ ago" counted back from each stock's latest filed quarter. The other 30 are unexplained, and none maps to a different quarter. Only one archive date exists, so behaviour across archive dates is **untested (TL-03 UNVERIFIED)**.
- **Sign changes:** 0.
- **NSE value missing** has three causes:
  - bank and insurer revenue tags (the taxonomy has no `RevenueFromOperations`);
  - 12 documents whose XBRL holds only half-year or YTD contexts (IDFCFIRSTB, PNB and RAILTEL Sep-25; SHYAMMETL and MANKIND Q4; SIEMENS Mar-25);
  - pre-listing quarters (ATHERENERG, TENNIND).

### 6b. Ownership: Trendlyne chart (1 decimal) vs NSE shareholding XBRL (CMP-07, CAT-01)
| Category | Compared | Match or within display rounding (±0.05) | Unexplained | of which material (>0.5 pp) | Median / max gap |
|---|---|---|---|---|---|
| Promoter | 219 | **219** | 0 | 0 | — |
| MF | 234 | **234** | 0 | 0 | — |
| FII | 234 | 217 | 17 | 11 | 0.52 / 1.00 pp |
| DII | 234 | 159 | 75 | 24 | 0.08 / 10.31 pp |

- **Mapping:**
  - Trendlyne FII = NSE `InstitutionsForeign` (FPI category I + II).
  - Trendlyne DII = MF + "other institutions".
  - The FII/DII gaps are category assignment: ABCAPITAL's FII + DII totals 19.2% on Trendlyne and 19.22% on NSE, with part of NSE's FII shown as DII. Large DII gaps (ONGC, ACC, ULTRACEMCO, HINDPETRO, TMPV) need a category-level reconciliation.
- **Not compared:** 23 values where NSE has no value (companies without a promoter context, or a missing filing), plus the quarters before Mar-25, which Trendlyne's chart doesn't cover.

### 6c. Revisions and first-filed values (NSE-05, ARC-04, TOL-04/05)
- 2,999 (symbol, quarter, basis, metric) keys:
  - no later filing: 2,860;
  - later filing with the same value: 129;
  - later filing with a changed value: 10 (RKFORGE Dec-24 PAT, revenue, total income and owners' PAT at 10×; ACC Dec-24 revenue; ABCAPITAL Sep-24 EPS; 3MINDIA Sep-25 and SHYAMMETL Dec-24 total EPS).
- Later entries by kind: 20 flagged revisions, 8 unflagged later filings (legacy, F-4), and no duplicate listings disagreeing.
- `comparative_status = BLOCKED_F1_XBRL_HAS_NO_COMPARATIVE_COLUMNS` for every key.

## 7. Q3 — public availability (AV-01..06, NSE-04, CMP-08)

| Quarter | Format | Original filings | HIGH | MEDIUM | LOW | BSE matched | BSE earlier > 15 min | After the close | Non-session day | Median days after quarter end |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024-09-30 | legacy | 69 | 2 | 67 | 0 | 63 | 61 | 47 | 10 | 31 |
| 2024-12-31 | legacy | 73 | 1 | 72 | 0 | 57 | 54 | 53 | 4 | 31 |
| 2025-03-31 | integrated | 71 | 1 | 70 | 0 | 53 | 52 | 56 | 6 | 43 |
| 2025-06-30 | integrated | 70 | 5 | 65 | 0 | 63 | 58 | 58 | 6 | 32 |
| 2025-09-30 | integrated | 73 | 3 | 70 | 0 | 68 | 65 | 61 | 9 | 35 |
| 2025-12-31 | integrated | 73 | 9 | 60 | 4 | 69 | 60 | 54 | 9 | 33 |
| 2026-03-31 | integrated | 73 | 0 | 73 | 0 | 67 | 65 | 62 | 9 | 41 |
| 2026-06-30 | integrated | 74 | 3 | 71 | 0 | 62 | 57 | 60 | 6 | 30 |

"Original filings" counts one row per basis, so a company filing both standalone and consolidated appears twice.

- **Results:**
  - 30 flagged revisions have no broadcast time (DEF-4), so all are LOW.
  - 4 contradictions (VEDL and GLAND Dec-25: `creation_Date` about a day after the broadcast) are LOW.
  - Broadcast time is second-precision in 576 of 576 originals, and filing time is minute-precision in legacy (142) and second-precision in integrated (464).
  - The broadcast is never on the quarter-end date: at least 13 days later, median 34 (so `period_end` is never a publication time).
  - Filename-clock consistency (F-3): 572 of 576 match one of the two clock readings.
  - Session buckets for originals: after close 451, market hours 54, pre-open 8, non-session day 59, no time 4.
- **BSE match (identity):** the one "Financial Results" announcement per company-quarter, from 24 hours before to 2 hours after NSE's broadcast. 16 filings had more than one candidate; the earliest is used, and it can only set the time if NSE agrees within 15 minutes.
- **Shareholding:** 323 filings (312 quarter-end, 11 event-driven). All MEDIUM. The NSE broadcast is second-precision; submission is day-precision only (kept separate; DEF-1 avoided). Last-Modified corroborates 293. Median 17 days after quarter end (range 0–184).
- **Events (AV-06, CAT-06):** 32 Trendlyne results-meeting dates (4 stocks) vs NSE broadcasts: same day 20, broadcast after the meeting date 12. Meeting dates are day-precision with no time, so **an event date is never an availability time** (leakage test 6).

## 8. Q4 — category verdicts and proposed classes (TL-06, POL-01, DEL-02/03)

| Category | Q1 capability | Q2 values | Q3 availability | **Proposed class** | Effective now |
|---|---|---|---|---|---|
| Trendlyne quarterly financials | NOT_CAPABLE (no as-of; snapshot relative to today) | 406 of 665 match; 229 definition; 30 unexplained | none from Trendlyne | **UNVERIFIED** historically; **FORWARD_ONLY** from 2026-09-19 09:40 (daily archive) | UNVERIFIED |
| Trendlyne ownership | NOT_CAPABLE (6-quarter snapshot, 1 decimal) | promoter and MF all match; FII/DII mapping gaps | none (no disclosure date) | UNVERIFIED historically; FORWARD_ONLY | UNVERIFIED |
| Trendlyne events (board meetings) | dates only, day precision | 32 dates checked | meeting date ≠ publication (12 of 32 broadcast later) | UNVERIFIED historically; FORWARD_ONLY | UNVERIFIED |
| Trendlyne SAST, deals, bonus/split/rights | not tested | — | — | UNVERIFIED | UNVERIFIED |
| Trendlyne ratios/scores | NOT_CAPABLE (current only) | not tested | — | FORWARD_ONLY | UNVERIFIED |
| Trendlyne news | not tested | — | — | FORWARD_ONLY (CAT-05 default) | UNVERIFIED |
| NSE filed results (sample, first filing) | ground truth | audit readers pass fixtures and 3 manual checks; F-6 errors preserved as filed | HIGH 24, MEDIUM 548, LOW 4 | **EXACT_PIT for the 24 HIGH filings**. Others: **rule candidate R-NSE-RES-1** (`available_at` = NSE XBRL broadcast, conservative per F-5; sample 576 originals, 40 stocks × 8 quarters; BSE-checked 502) | UNVERIFIED |
| NSE filed shareholding (sample) | ground truth | audit reader passes fixtures; 321 of 321 fetched documents read | MEDIUM 323 | **rule candidate R-NSE-SHP-1** (`available_at` = NSE shareholding broadcast; BSE not collected) | UNVERIFIED |

Rule candidates carry `approval_status: PENDING_OWNER`. Under `rule_complete_and_approved()` they are **not eligible until you approve them**. Flagged revisions (LOW) are never eligible; only first-filed values are.

## 9. Coverage (NSE-03, DEL-04)

| Quarter | Stocks with an original results filing (of 40) | PAT | Revenue | EPS | BSE-matched |
|---|---|---|---|---|---|
| 2024-09-30 | 36 | 36 | 34 | 36 | 34 |
| 2024-12-31 | 36 | 36 | 34 | 36 | 31 |
| 2025-03-31 | 39 | 37 | 33 | 35 | 31 |
| 2025-06-30 | 39 | 39 | 35 | 37 | 35 |
| 2025-09-30 | 40 | 37 | 35 | 35 | 38 |
| 2025-12-31 | 40 | 40 | 36 | 38 | 38 |
| 2026-03-31 | 40 | 39 | 35 | 37 | 37 |
| 2026-06-30 | 40 | 40 | 36 | 38 | 34 |

- **Missing cells:**
  - before listing: ATHERENERG (Sep-24, Dec-24) and TENNIND (Sep-24 → Jun-25);
  - **not explained:** the general insurers GODIGIT and NIACL have no Sep-24 or Dec-24 row in the legacy Reg-33 listing, although both were listed. A separate insurance format is the likely cause; UNVERIFIED.
- **Revenue gaps:** banks and general insurers (no `RevenueFromOperations`; interest earned and total income kept as explanations).
- **BSE gaps:** bank results filed outside the "Result" category (IDFCFIRSTB Sep-24), and XBRL filed more than 24 hours after the PDF.

## 10. Exception report — unexplained Trendlyne differences (TOL-06)

All 30 are `DIFFERS_UNEXPLAINED`; none is labelled a restatement (F-1).

Material (18):
- **Revenue (9):**
  - HINDPETRO, 4 quarters about 7% below NSE. No excise tag is in the XBRL, so a net-of-excise definition is plausible but unproven.
  - ITC Jun-26 −33% (NSE's gross revenue includes the reintroduced excise), Mar-26 −22.7%, Sep-25 −5.5%.
  - ABB Jun-25 standalone +7.8%.
  - TMPV Jun-25 −14.8% (demerger).
- **PAT (7):** AUROPHARMA Dec-25 +25%, BHARATFORG Dec-25 +7%, VEDL Dec-24 −27%, SHYAMMETL Mar-25 standalone +120%, NIACL Sep-25 and Mar-25, GODIGIT Mar-26 +15.5%.
- **EPS (2):** NAUKRI Sep-25 −8% and Dec-25 +14.3%.

Immaterial but outside tolerance (12): NIACL (4 quarters, 0.5–2.4%), ITC revenue Dec-25 (−5.0%) and Jun-25 (−4.1%), KIRLOSENG (2 quarters, about 2%), MANKIND, SHYAMMETL Sep-25, SONACOMS and HINDPETRO Jun-26. Five of these 30 (ITC Mar-26, Dec-25 and Jun-25, KIRLOSENG Mar-26, NAUKRI Dec-25) were first labelled PERIOD_MAPPING, then reclassified once cross-period candidates were limited to adjacent and year-apart quarters on the same basis. The first rule accepted coincidental 0.5% matches.

Row-level detail is in the analysis JSON (`trendlyne_financials`, `reconciliation_status == DIFFERS_UNEXPLAINED`).

## 11. Manual checks (QA-06)

Record: `research/pit_audit/manual_checks.json`. **Performed by the agent; your confirmation is pending.** Values were read by eye from the BSE results PDFs and the filed shareholding XBRL facts.

| Stock / quarter | PAT: PDF vs archive vs Trendlyne | Meeting ended → BSE → NSE XBRL | Promoter %: filing vs archive vs Trendlyne |
|---|---|---|---|
| LICHSGFIN Q2 FY25 (legacy, NBFC) | 1,328.89 / 1,328.899 standalone; 1,327.79 / 1,327.79 consolidated; Trendlyne 1,327.71 | 15:00 → 15:13:13 → 19:16:10 | 45.24 / 45.24 / — (Trendlyne chart starts Mar-25) |
| 3MINDIA Q1 FY27 (integrated) | 233.07 / 233.07 / 233.07 (includes a ₹73.13 cr land-sale gain) | 12:50 → 13:00:52 → 17:04:16 | 0.75 (fraction) → 75 / 75 / 75 |
| HINDUNILVR Q3 FY26 (discontinued operations) | 6,603 / 6,603 / 6,607; EPS 9.03 continuing, 28.12 total (Trendlyne 28.12) | 09:42 → 10:21:32 → 17:25:10 | 0.619 → 61.9 / 61.9 / 61.9 |

LICHSGFIN and HUL PDFs came from BSE AttachHis after AttachLive returned 404.

## 12. Tests and QA (QA-01..07, OPS-06/07)

| Check | Command | Result |
|---|---|---|
| Audit suite (fixtures, AV-1, sessions, tolerances, classification, gate, 7 leakage tests, revisions, archive, SHP formats, request log) | `cd research/pit_audit && python3 -m pytest -q test_core.py test_fixtures_nse.py` | **76 passed** |
| Research regression | venv pytest: `research/trendlyne` 18, `research/screener` 8, `research/phase1` 7, `research/track1` 23 | **56 passed** |
| NIDP parser regression (unchanged code) | `cd backend && python3 -m pytest -q tests/test_nidp_nse_financials_parser.py tests/test_nidp_nse_shareholding_parser.py nidp/tests/services/test_shareholding_quarter_guard.py` | **43 passed** |
| Compile | `python3 -m py_compile research/pit_audit/*.py` | ok |
| No NIDP database access (OPS-06) | grep for asyncpg, psycopg, NIDP_POSTGRES, postgres://, create_pool, nidp.shared.storage/db in `research/pit_audit` | none. Reused NIDP modules are the parsers (XML helpers) and `nse_fetcher`, `plain_http` and `bse_fetcher` (HTTP only). |
| Secret scan (OPS-07) | 10 credential values (Trendlyne URL and its path parts, OpenAI, GitHub, Kite key/secret/access token, ledger) searched in 1,361 code, log, archive (decompressed) and artifact files | **0 hits** |
| Artifact integrity (ARC-01/05) | `Archive.verify_artifacts()` on the nse, bse and trendlyne archives | 0 corrupt |
| Diff scope (G-02, DEL-05) | `git status` in the `feat/paper-trade-engine` worktree | only `research/pit_audit/` and this report |

## 13. Acceptance matrix

| ID | Status | Evidence |
|---|---|---|
| G-01 | PASS | PRDs copied verbatim with README and sha256 (commit 0181e08b). Your comparison with the originals is pending: they are not on disk. |
| G-02 | PASS | §12 diff scope; no model, paper-trading, NIDP service/table or cron change |
| G-03 | PASS | §2 |
| G-04 | PASS | §3; `contracts.FILING_FIELDS` |
| G-05 | PASS | `is_feature_eligible` requires `decision_at` / `feature_cutoff_at`; leakage tests |
| TL-01 | PASS | as-of probe rejected (raw response in the `tl_raw` archive) |
| TL-02 | PASS | schema snapshot, sha256 `60e6a4888f8e…20c9b0`; `additionalProperties: false` on 12 of 12 tools; no date arguments; date searches return only 52-week-high/low dates |
| TL-03 | **UNVERIFIED** | Stocks × periods: 635 of 665 anchored as expected. Archive-date dimension untested (one snapshot); needs a re-check on a later archive date. |
| TL-04 | PASS | §6a definitions; units crore and ₹/share; consolidated-first basis |
| TL-05 | PASS | server "Trendlyne-Financial-Server" 3.1.1 and schema hash on every `tl_raw` record; response as-of date 2026-09-18 |
| TL-06 | PASS | §8, individual verdicts (ratios and news by construction and the CAT-05 default) |
| NSE-01 | **FAIL (mitigated)** | Existing NIDP parsers fail hand-read fixtures (DEF-2, 6, 8, 9). Audit readers pass fixtures for Reg-33, Integrated, consolidated and standalone, Banking, and pre-2025, transition and current shareholding. |
| NSE-02 | PASS | `raw_row` + sha256 kept; parsed timestamps held in separate fields |
| NSE-03 | PASS | §9 and §7 |
| NSE-04 | PASS | contradictions and revisions without broadcast → LOW; F-3 filename clock never used |
| NSE-05 | PASS | append-only; chronology (§6c); tests |
| NSE-06 | PASS | every metric has `document_url`, `document_sha256`, `retrieved_at`, `parser_version` |
| ARC-01 | PASS | append-only jsonl.gz (flock), write-once artifacts, verified |
| ARC-02 | **FAIL (gap)** | ISIN is absent for Integrated-listing rows (NSE's listing does not carry it); every other identity field is present |
| ARC-03 | PASS | metric name, value, unit, `context_role`, statement type, consolidation type |
| ARC-04 | PASS | `as_filed` table: `as_filed_value`, `latest_known_value`, `first_filed_at`, `latest_filing_at`/kind |
| ARC-05 | PASS | 5 offline re-extractions from artifacts; hashes verified |
| AV-01 | PASS | §3, §7 |
| AV-02 | PASS | evidence list and confidence on every availability record |
| AV-03 | PASS | session tests (15:29/15:31, pre-open, holidays, beyond calendar) |
| AV-04 | PASS | gate rule with margin; leakage tests |
| AV-05 | PASS | IST-aware only (naive times rejected); traded-session calendar |
| AV-06 | PASS | §7 events |
| CMP-01 | PASS | §6a |
| CMP-02 | PASS | latest-revision comparison (RKFORGE) |
| CMP-03 | PASS | period anchoring; coincidental cross-period matches rejected (tested) |
| CMP-04 | PASS | same basis only; other basis only as an explanation |
| CMP-05 | PASS | reason codes (definition, rounding, unit, period) |
| CMP-06 | **UNVERIFIED** | Missing values counted (§6a). Missing-to-present and zero-to-nonzero changes need a second archive date. |
| CMP-07 | PASS | §6b mapping |
| CMP-08 | PASS | broadcast, submission, BSE, Last-Modified, Trendlyne as-of and retrieval kept apart (§7) |
| TOL-01 | PASS | `config/comparison.json` |
| TOL-02 | PASS | zero, negative, missing, sign-change and rounding-boundary tests |
| TOL-03 | PASS | tolerance and materiality reported separately |
| TOL-04 | PASS | no RESTATEMENT without comparative evidence (F-1) |
| TOL-05 | PASS | chronology before classification |
| TOL-06 | PASS | §10 |
| CAT-01 | PASS | quarter end and broadcast stored separately (median 17 days) |
| CAT-02 | PASS | MEDIUM without an approved rule → not eligible |
| CAT-03 | **UNVERIFIED** | corporate-action effects on ownership not analysed |
| CAT-04 | **UNVERIFIED** | board meetings tested; SAST, deals and corporate actions not tested |
| CAT-05 | PASS | news FORWARD_ONLY |
| CAT-06 | PASS | §7 events |
| POL-01 | PASS | §8 proposed classes (effective classes await DEL-06) |
| POL-02 | PASS | `FEATURE_META_FIELDS` schema test |
| POL-03 | PASS | `point_in_time_validated` tests |
| POL-04 | PASS | eligibility tests |
| POL-05 | PASS | FORWARD_ONLY before `archive_start_at` rejected (test) |
| POL-06 | PASS | `rule_complete_and_approved` (id, version, sample, coverage, approval) |
| OPS-01 | PASS | manifest + universe sha256 |
| OPS-02 | PASS | §2 |
| OPS-03 | PASS | §4 paced, logged, abort logic; documents direct per your decision |
| OPS-04 | PASS | 57 of 60 |
| OPS-05 | PASS | §4 estimate vs actual |
| OPS-06 | PASS | §12 |
| OPS-07 | PASS | §12 |
| QA-01 | PASS | fixture tests |
| QA-02 | PASS | timestamp, session and timezone tests |
| QA-03 | PASS | revision chronology tests |
| QA-04 | PASS | all six classes and missing or invalid evidence |
| QA-05 | PASS | 7 leakage tests |
| QA-06 | PASS (agent) / **PENDING owner** | §11 |
| QA-07 | PASS | §12 |
| DEL-01 | PASS | this document |
| DEL-02 | PASS | §8 |
| DEL-03 | PASS | §3, §8 |
| DEL-04 | PASS | §2, §9 |
| DEL-05 | PASS at commit | audit files only |
| DEL-06 | **PARTLY APPROVED** (2026-09-19 20:21 IST) | The owner approved R-NSE-RES-1: `nse_filed_results` → PIT_VALIDATED_RULE in `policy.json`, scoped to research use by the positional study, with model training needing separate approval. Every other category stays UNVERIFIED. |

**Definition of done:**
- **Met:**
  - PIT semantics documented;
  - no silent overwrites;
  - no global certification;
  - parser and timestamp tests pass (audit readers);
  - no unexplained difference silently accepted;
  - all negative PIT tests pass;
  - the gate is implemented and tested.
- **Pending:** your approval.
- **Open:** TL-03, CMP-06, CAT-03 and CAT-04 are UNVERIFIED; NSE-01 and ARC-02 are FAIL and documented.

## 14. Decisions needed from you

1. **DEL-06:** approve or reject the proposed classes (§8), especially rule candidates R-NSE-RES-1 and R-NSE-SHP-1 (conservative NSE broadcast as `available_at`).
2. **QA-06:** confirm the 3 manual checks (§11).
3. **HIGH coverage:** collecting NSE corporate-announcement (PDF) times would lift HIGH above 24 of 576 and remove the F-5 delay. It needs about 40 symbols × a few windows through the production proxy. Approve or decline.
4. **Fixes outside this audit:** DEF-7 (the Trendlyne cache silently drops historical codes), and DEF-6, DEF-8 and DEF-9 in production NIDP parsers (a separate PR through `dev`).
5. **Second Trendlyne archive date:** a re-check (for example after the next results season) would close TL-03 and CMP-06.

## 15. Files

- **New:** `research/pit_audit/`, containing:
  - `contracts.py`, `session.py`, `archive.py`, `availability.py`, `pit_policy.py`, `compare.py`;
  - `xbrl_extract.py`, `shp_extract.py`, `sample.py`;
  - `nse_ground_truth.py`, `bse_evidence.py`, `trendlyne_side.py`, `analyze.py`, `manual_checks.py`;
  - `config/{comparison,policy,sample_manifest}.json`, `manual_checks.json`;
  - `fixtures/raw/*` (9 files);
  - `test_core.py`, `test_fixtures_nse.py`.
- **New:** this report.
- **Unchanged:** NIDP code, NIDP databases, model, paper-trading and crons.
