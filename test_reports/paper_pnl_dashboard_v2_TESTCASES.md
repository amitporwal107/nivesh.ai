# P&L dashboard v2 (owner design, 4 Nov 2026 afternoon) — test cases, authored before implementation

Design: docs/paper_pnl_dashboard/DESIGN.md "v2". Unit: backend/tests/test_paper_pnl.py (+ test_paper_pnl_live.py,
test_desk_levels_edit.py). E2E (mocked API): frontend-v5/e2e/tests/copilot-app-desk-pnl.spec.ts. Staging: branch code in the staging
backend container against the real Mongo / Redis / feed; MOCK paper trades on real symbols, removed afterwards.

| ID | Area | Case | Type | Expected |
|---|---|---|---|---|
| V2-01 | api | `mode=PAPER` / `LIVE` / `ALL`; `mode=XYZ` | unit + staging | filtered positions + summary; 422 `invalid_mode` |
| V2-02 | api | `account=paper`, a broker id of the user, an id not the user's | unit | filtered; 422 `invalid_account` |
| V2-03 | api | `accounts` lists paper + every broker account with state (OK / SIGN_IN / ERROR / OFF / STALE) whatever the filters | unit + staging | as stated; expired sessions → SIGN_IN with a note |
| V2-04 | api | `modes.PAPER` / `modes.LIVE` unaffected by mode/account filters | unit | both present, sums of each mode's rows |
| V2-05 | live | Broker rows: long stock, short future, long option; signed qty; LTP from the resolver; unrealized = (LTP − avg) × qty × mult; realized null; broker_pnl carried | unit | as stated |
| V2-06 | live | A broker read fails (session expired) | unit | account SIGN_IN, no positions, snapshot still 200, `modes.LIVE.available` false with the reason |
| V2-07 | live | Broker read cached ≤ 60 s; read older than 2 × TTL → STALE | unit | one broker read for two snapshots inside TTL |
| V2-08 | live | Contract not mappable / no price | unit | MISSING, left out of totals, `complete` false |
| V2-09 | live | No stop/target/journal for live; `editable_levels` false | unit | null / false |
| V2-10 | timeseries | `mode=LIVE` curve from broker instruments; `trade=<paper share id>` since entry; `trade=<structure>` today only; unknown → 404 | unit | as stated |
| V2-11 | journal | Strong record on the entry day / only a day score / nothing / older than 3 days / a structure / not the user's | unit | found strong / scored / why / why / 404 / 404 |
| V2-12 | levels | PATCH valid stop + target on an open share trade | unit + staging | 200; `level_changes` v1 appended; pending until the next session |
| V2-13 | levels | Simulator: a stop change on day D applies to bars after D only (today's bar keeps the old stop) | unit | a bar on D below the NEW stop does not exit; the bar of D+1 does |
| V2-14 | levels | Simulator: target change likewise; trailing ATR raises from the new stop | unit | as stated |
| V2-15 | levels | 404 / 409 closed / 409 structure / 422 each validation code / unknown field / no change | unit | as the table in DESIGN |
| V2-16 | levels | Idempotency-Key replay; the exact body the screen sends | unit | same answer, one change |
| V2-17 | levels | Audit record written; nothing else changes on the trade | unit + staging | as stated |
| V2-18 | read-only | A P&L read (any mode) writes no paper trade; no broker order call exists in the paths | unit + staging | trade docs unchanged |
| V2-19 | e2e | Page order as drawn: header (pills, clock, pause), filter bar, hero + KPIs, mode cards, chart, table, risk + supervisor, footer, folded extras | e2e | all present in order |
| V2-20 | e2e | Mode toggle / account / segment change the request; search filters the table only | e2e | query carries mode/account/segment; totals unchanged by search |
| V2-21 | e2e | Row expand: breakdown, fills, actions, chart, journal, trade P&L; live row shows "not recorded" + read-only exit note | e2e | as stated |
| V2-22 | e2e | Modify risk: form, PATCH body, success, a 422 shown in words | e2e | as stated |
| V2-23 | e2e | Simulate exit: confirm → POST close; Initiate exit (live) places nothing | e2e | as stated |
| V2-24 | e2e | Pause / Resume stops and restarts updates; feed / account pills show states | e2e | as stated |
| V2-25 | e2e | 390 px: cards, no page sideways scroll; API error → problem + retry | e2e | as stated |
| V2-26 | wording | No "recommend", "pick", "suggested" in user-visible strings of the page | unit + e2e | none |
| V2-27 | staging | Real data: owner's account, MOCK paper trades on real symbols priced live; broker accounts' real states; journal for a symbol with a scan signal today; PATCH levels on a MOCK trade; cleanup | staging | figures consistent with the ledger and feed; MOCK rows removed |
| V2-28 | e2e | Real staging snapshot rendered (desktop + phone screenshots) | e2e | renders without errors |
