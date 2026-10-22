# Desk macro-release calendar: backend (US via FRED, India via RBI + MoSPI) — 2026-10-21

- **Branch:** feat/desk-macro-calendar (from dev 445550f0)
- **Changed areas:** backend routes/services: yes · frontend src: no
- **Status:** IN PROGRESS (see the end of this file; sections marked PENDING are filled once run)

## Scope and decisions
Free sources only (user, 2026-10-21). US: FRED API (key from env FRED_API_KEY; never stored in the repo). India: MoSPI advance release calendar (PDF) for CPI / IIP / GDP / PLFS dates; RBI press release for the MPC 2026-27 schedule and rbi.org.in home page for the current policy repo rate. No consensus estimates exist in free sources: `estimate` is always null and the API says so in `gaps`.

## Test cases (authored before the code)
| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | FRED parse | A vintage matrix (output_type=2) is read into {vintage date: {observation date: value}}; '.' means missing | unit | missing values dropped, vintages sorted |
| TC-2 | FRED maths | CPI YoY = value(t) ÷ value(t−12m) − 1 from ONE vintage; hand example 336.940 ÷ 326.9 → check | unit | rounds to 2 dp, uses the vintage's own history |
| TC-3 | FRED maths | NFP change = value(t) − value(t−1m); previous = the same figure for t−1 as known on that vintage (revised) | unit | hand example |
| TC-4 | FRED maths | Claims level scaled to thousands; retail sales MoM %; GDP uses the growth series as is | unit | hand examples |
| TC-5 | Release matching | A release date matches the first vintage on/after it within 5 days; none → actual null | unit | no guess when FRED has no vintage |
| TC-6 | Future release | release date after today → actual null, previous = last known | unit | actual is null |
| TC-7 | GDP stage | First / second / third release of one quarter are labelled advance / second / third | unit | by order of release dates |
| TC-8 | FOMC | decision actual = target upper the day after the meeting; previous = day before | unit | no change → equal |
| TC-9 | MoSPI PDF | Calendar blocks → (date, title); "7thJan" with no space parses; year from the 2026-27 fiscal year (Apr–Dec 2026, Jan–Mar 2027) | unit | CPI 12 Nov, IIP 28 Nov, GDP 30 Nov, 7 Jan GDP advance |
| TC-10 | MoSPI filter | Only CPI, IIP, GDP and PLFS monthly rows are kept; ISP, flash reports, surveys dropped | unit | counts |
| TC-11 | RBI MPC | Meeting text "October 5, 6 and 7, 2026" → decision date 7 Oct; Feb 3, 4 and 5, 2027 | unit | 6 meetings |
| TC-12 | RBI rate | "Policy Repo Rate : 5.50%" → 5.5; missing → None (gap), never a default | unit | |
| TC-13 | Time zones | 08:30 New York → 18:00 IST in summer, 19:00 in winter; FOMC 14:00 ET → 00:30 IST next day in winter | unit | DST correct |
| TC-14 | Ingester | per-source failure isolation: FRED down still writes India rows; all fail → FAILED; missing key → fails fast | unit | |
| TC-15 | DaaS calendar | month filter, country filter, impact filter, shaping, gaps (estimate, India actuals, WPI, times), empty month gap | unit | |
| TC-16 | DaaS history | reaction session = first Nifty session after the release (after-close releases use the next session); n and coverage_from honest; no padding | unit | hand example |
| TC-17 | DaaS params | bad month / country / impact / code → 400; app route → 422; upstream failure → 502 | unit | |
| TC-18 | App routes | forward params unchanged, pass the body through, auth required | unit | |
| TC-19 | Real FRED run | the ingester's US logic run against FRED with the real key (key never printed): rows it would write | real run, read-only | rows shown below |
| TC-20 | Real India run | MoSPI PDF + RBI pages parsed live | real run, read-only | dates shown below |
| TC-21 | Migration | SQL applies and re-applies on a scratch Postgres | dry run | applies twice, no error |
| TC-22 | End to end on scratch Postgres | the real upsert, the real router SQL and the real route functions on real collected rows + Nifty / holiday rows copied read-only from staging | e2e (scratch) | upsert idempotent, NULL never erases, calendar and history shaped |
| TC-23 | Staging HTTP | /api/markets/macro-calendar on staging | api | BLOCKED until merge + migration + FRED key + ingester run (see "To deploy") |

## Results (real output, 2026-10-21)

### Unit and route tests (staging backend image, `--network none`)
```
tests/test_macro_calendar_routes.py nidp/tests/services/test_daas_desk_macro.py nidp/tests/services/test_macro_calendar.py
100 passed, 1 warning in 7.32s
tests/test_events_calendar_routes.py nidp/tests/services/test_daas_desk_events.py nidp/tests/services/test_daas_desk_market.py   (neighbours, unchanged)
74 passed, 1 warning in 7.51s
```
Hand-checked examples in the tests: CPI YoY 332.8/320−1 = 4.0 %; Jul 336/320−1 = 5.0 %; payrolls 1130−1100 = 30; 08:30 New York = 18:00 IST (EDT) / 19:00 (EST); FOMC 14:00 ET = 00:30 IST next day in winter; Nifty 100→101→102.01…106.06 = +1.00 % / +1.00 % / +5.01 %.

### TC-19/20 real collection (dry run, nothing written; FRED key passed as a mounted file, never printed; 0 hits of the key in output or repo)
```
$ python -m nidp.services.macro_calendar --dry-run
ROWS 380  FAILURES 0
by indicator: US_JOBLESS_CLAIMS 117, US_UNRATE 28, US_RETAIL_MOM 28, US_NFP 28, US_CORE_PCE_YOY 28, US_PPI_YOY 27, US_CPI_YOY 27,
              US_GDP_QOQ 25, US_FOMC 25, IN_PLFS 12, IN_IIP 12, IN_CPI 12, IN_RBI_MPC 6, IN_GDP 5
2026-10-02 US_NFP      period=Sep 2026  previous=133.0 actual=29.0   08:30
2026-10-02 US_UNRATE   period=Sep 2026  previous=4.1   actual=4.2    08:30
2026-10-07 IN_RBI_MPC  period=Oct meeting previous=None actual=5.5   10:00   (the latest decision only)
2026-10-12 IN_CPI      period=Sep 2026  previous=None  actual=None   16:00   (India values are a named gap)
2026-10-14 US_CPI_YOY  period=Sep 2026  previous=3.4   actual=3.74   08:30
2026-10-28 US_FOMC     period=Oct meeting previous=4.0  actual=None   14:00
2026-10-29 US_GDP_QOQ  period=Q2 2026 (third) previous=2.5 actual=None
2026-11-06 US_NFP      period=Oct 2026  previous=29.0  actual=None
2026-11-10 US_CPI_YOY  period=Oct 2026  previous=3.74  actual=None
2026-11-12 IN_CPI      period=Oct 2026  previous=None  actual=None
2026-11-30 IN_GDP      period=Q2 FY2026-27
2027-01-07 IN_GDP      period=FY 2026-27 (first advance)
```
MoSPI rows carry the real release date where MoSPI states one (e.g. CPI 13 Apr, IIP 29 Jun, CPI 14 Sep; source text says "planned 12 Sep, released 14 Sep").

### TC-21 migration (postgres:16-alpine scratch)
```
apply #1: CREATE TABLE / CREATE INDEX / COMMENT / INSERT 0 1
apply #2: NOTICE relation "macro_releases" already exists, skipping ... INSERT 0 0      (no error)
PRIMARY KEY (indicator_code, release_date); CHECK impact IN (H,M,L); CHECK country IN (IN,US)
```

### TC-22 end to end on scratch Postgres
```
collected 380 failures []
rows in table: 380
after re-run rows: 380 | RBI actual kept: 5.5000        (a NULL re-upsert did not erase the stored figure)
NOV 2026 calendar: count 15 | holidays include 2026-11-08 Diwali Laxmi Pujan (muhurat true) | 6 CM holidays loaded
   2026-11-06 19:00 IST US_NFP   Oct 2026 previous 29.0 actual None H
   2026-11-10 19:00 IST US_CPI_YOY Oct 2026 previous 3.74 H     2026-11-12 16:00 IST IN_CPI Oct 2026 H
HISTORY US_CPI_YOY n 12 coverage_from 2025-10-01  newest: 2026-10-14 -> session 2026-10-15 event_day +1.66 d1 +0.65
HISTORY IN_RBI_MPC n 4: 2026-10-07 -> session 2026-10-07 (10:00 IST decision reacts the same day) event_day -0.76
```
Hand check against the Nifty rows copied from staging: 15 Oct close 22,997.35 vs 14 Oct 22,622.70 = +1.656 % (shown 1.66); 16 Oct 23,146.15 ÷ 22,997.35 = +0.647 % (shown 0.65). The 11 Sep CPI reacts on 15 Sep because 14 Sep 2026 was an NSE holiday (Ganesh Chaturthi), correct.

## Sources: what each supplied URL yielded
| URL | Result |
|---|---|
| https://www.rbi.org.in/ | readable: Policy Repo Rate 5.50 %, and the notice "Monetary Policy Committee October 5 to 7, 2026". No schedule on the page. Used for the repo rate. |
| https://www.rbi.org.in/Scripts/NotificationUser.aspx | readable (HTTP 200) but it lists regulatory notifications, not release dates; not used. |
| https://trackrbi.com/press-release/62422/... (mirror) | readable; gave the 2026-27 MPC dates and the official id (prid 62422). Dates identical to the official page. |
| https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422 | the OFFICIAL press release, directly readable: 6 meetings (Apr 6-8, Jun 3-5, Aug 3-5, Oct 5-7, Dec 2-4 2026, Feb 3-5 2027). Used as source and source_url; the mirror is not a source. |
| https://mospi.gov.in/ and /release-calendar | a JavaScript shell. Its XHR `GET /api/documents/get-latest-release-calender` names the current Advance Release Calendar PDF (ARC_2026_27_Sept_2026.pdf, 8 pages, text); parsed by block position: 41 kept rows (CPI 12, IIP 12, GDP 5, PLFS 12). The other XHR (`POST /api/release-calender/fetch-all-release-calender-Web`) lists only releases already published, so it is not used. |
| https://eaindustry.nic.in/ | readable, but it lists only published WPI/PPI press-release PDFs (e.g. press_release_202609.pdf); no forward calendar, so WPI dates are a named gap. |
| MoSPI data API (api.mospi.gov.in; the eSankhyiki client's default 10.24.89.9) | does not connect from our VM: India CPI / IIP / GDP / PLFS VALUES are a named gap. FRED's India series stop in 2025. |

## Gaps (also returned in the API's `gaps`)
- Estimates: none (no free source). Impact ratings and release times are editorial.
- India values (CPI, IIP, GDP, PLFS): dates only. RBI: only the latest decision has a rate.
- India CPI / IIP reference month is inferred as the month before the release month (MoSPI's calendar gives no period); one row (IIP 1 Jun, the new-series launch) has no period.
- Not listed: India WPI / trade balance / PMI; US ISM and other licensed surveys.
- RBI MPC URL is per fiscal year (prid 62422 = 2026-27): in April 2027 it needs the new year's release (constant RBI_MPC_SCHEDULE_URL); until then the RBI rows stop at Feb 2027.
- FRED vintage matrix covers 26 months; earlier history is not loaded.

## To deploy (needs the user)
1. Merge the branch to dev (a push to dev auto-deploys the app VM; the NIDP deploy workflow follows).
2. Run migration 164 on the NIDP warehouse (shared staging write: needs the user's explicit OK).
3. Put FRED_API_KEY (the user's key) into the NIDP environment (`nidp.env.staging` on the NIDP VM): a secret-store write that needs the user's explicit OK. The key is not in the repo or in this report.
4. Run the ingester once: `python -m nidp.services.macro_calendar` (or the nidp-run-service workflow), then add a daily cron (suggest 02:30 IST and 20:30 IST, since US releases land in the Indian evening). Container: `backend/nidp/services/macro_calendar/Dockerfile`.
5. Then verify: GET /api/markets/macro-calendar?month=2026-11 and /history?code=US_CPI_YOY with a staging session token.

## Status
IN PROGRESS. VERIFIED: unit/route tests (100 + 74 neighbours), real collection from FRED / Fed / MoSPI / RBI (380 rows, 0 failures), migration twice on scratch Postgres, real upsert + router SQL + route functions on scratch Postgres. UNVERIFIED: anything on staging (not deployed, table not migrated, key not in the NIDP environment).

## Verdict: BLOCKED (staging HTTP not run; see OVERRIDE_desk_macro_calendar_backend.md)
