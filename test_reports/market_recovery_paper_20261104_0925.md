# Functionality Verification Report — Market Recovery › paper-trading the top 10, live

- **Branch:** feat/market-recovery-paper (stacked on feat/market-recovery-indices / PR #476; commits 919ca4c9, f1d1133c)
- **Date:** 2026-11-04 (IST)
- **Author:** Claude (Domain Expert Analyst + Full Stack Developer + QA)
- **Environment:** staging (nivesh-staging-app-backend container, owner's account, live Kite quotes in market hours) — pre-merge
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Owner, 4 Nov ~08:50 IST: paper-trade the recovery candidates, "assume you have sufficient margin", real-time quotes and P&L,
the existing risk configuration, the best strategy per trade. Decisions (AskUserQuestion): paper capital Rs 1 crore with the %
limits unchanged; the top 10 leading-sector candidates; best = highest reward : risk after costs; live entry and live closes.
Built: `GET /api/market-recovery/paper-plan`, live entry on `POST /api/desk/paper-trades` (`price_source` kite_live, checked
against today's live range), `GET /api/market-recovery/paper-trades/live`, a minute-by-minute live-close job (mf_scheduler,
leader-locked, market hours), and part "6 · Paper trades (live)". Then, on the owner's instruction, the trades were opened at
live prices at 09:17 IST (paper only). NOT verified: the deployed URL / page and the scheduler job in the deployed leader
(need merge + backend restart); until then live closes run only when the live book is read.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-P0 | capital | paper capital to Rs 1 crore via the audited adjust (owner's decision) | data | ledger row + account 1 crore | PASS |
| TC-P1 | picker | ranking by net R:R, ties by max loss, gate refusals / missing live quotes / prices outside the plan excluded, top 10 only, already-open shown | unit | as §10 A | PASS |
| TC-P2 | bodies | exact cash and strategy bodies (tags, price_source, legs, signal), Idempotency-Keys, share request within the desk limit, costs at size, wording | unit | as §10 A | PASS |
| TC-P3 | live entry | today's live range accepted; refused without a live quote of today; unchanged without price_source | unit | as §10 B | PASS |
| TC-P4 | live marks | shares and 2-leg structure P&L at live quotes | unit | as §10 C | PASS |
| TC-P5 | live closes | shares and structure at Stop loss / Target 1; none without live quotes; neutral skipped | unit | as §10 D | PASS |
| TC-P6 | scheduler | job registered (15 jobs), no-op outside 09:15–15:30 | unit | as §10 D | PASS |
| TC-P7 | routes | live / plan 200, flag 403 | unit | as API | PASS |
| TC-P8 | real staging | plan with live quotes; open via the desk endpoint with the owner's session; live book | api | 7 opened, 3 refused by the gate with reasons, live P&L | PASS |
| TC-P9 | UI | plan, skipped / already-open rows, button off unless live (Market not open / Kite login needed), confirm → POST each body with its key, 201 + 409 shown, live book, 390 px | e2e | as stated | PASS |
| TC-P10 | UI, real answers | the real plan and live book rendered at 1280 / 390 px | e2e | 10 plan rows, 7 live rows, lint 0 | PASS |

## API / Endpoint Tests (staging)
pytest (throwaway container, branch tree read-only, `--network none`) — every desk, paper-account, risk-gate, scheduler and
Market Recovery suite:
```
1077 passed, 5 skipped, 2 warnings in 39.83s
```
TC-P0 (capital, scratchpad `capital_topup.py`, owner's account checked by e-mail first, dry run then apply):
```
owner user_id: user_845232f38371
before: {'starting_capital_rs': 1000000.0, 'cash_rs': 1000000.0, 'blocked_rs': 123887.21, 'available_rs': 876112.79}
moved: True starting capital updated: 1
after: {'starting_capital_rs': 10000000.0, 'cash_rs': 10000000.0, 'blocked_rs': 123887.21, 'available_rs': 9876112.79}
ledger row: {'_id': 'owner-capital-topup-20261104', 'reason': "Owner decision 4 Nov 2026 (AskUserQuestion): raise paper capital to Rs 1 crore ('assume sufficient margin') so one-lot Market Recovery structures fit his unchanged % limits", 'action': 'adjust', 'cash_delta_rs': 9000000.0}
API paper-account: {'starting_capital_rs': 10000000.0, 'cash_rs': 10000000.0, 'blocked_rs': 123887.21, 'available_rs': 9876112.79}
```
TC-P8 — the plan at live quotes (09:16 IST; scratchpad `mr_paper_check.py`, branch code ahead of the deployed copy, real gate,
owner's cookie):
```
paper-plan -> HTTP 200 in 16.0s
market {'live': True, 'source': 'kite_live', …}
   1 LAURUSLABS   CHOSEN Bull Call Spread     rr 5.35 gain 129008.75 loss -24111.39 lots 1 gate allow key mr-2026-11-04-LAURUSLABS
   2 MSUMI        CHOSEN Shares               rr 1.86 gain 85795.13 loss -46189.51 qty 11457 gate reduce key mr-2026-11-04-MSUMI
   3 DIVISLAB     CHOSEN Bull Call Spread     rr 3.53 …
   4 SONACOMS     CHOSEN Bull Call Spread     rr 3.71 …
   5 BOSCHLTD     CHOSEN Bull Call Spread     rr 2.58 …
   6 DRREDDY      CHOSEN Protective Put       rr 4.35 …
   7 SYNGENE      CHOSEN Shares               rr 1.94 … qty 936 gate reduce
   8 PPLPHARMA    CHOSEN Shares               rr 2.01 … qty 1597 gate reduce
   9 TVSMOTOR     CHOSEN Protective Put       rr 4.72 …
  10 MINDACORP    CHOSEN Shares               rr 2.55 … qty 955 gate reduce
```
(The first live run refused every shares candidate as `invalid_quantity`: the dry-run request was over the desk's 1,000,000
limit. Fixed — the request is now all the cash could buy, capped at that limit — and a test added.)

Opening (09:17 IST, scratchpad `mr_paper_open.py`: each chosen body to the desk's own POST /api/desk/paper-trades with its
Idempotency-Key, owner's session, paper only):
```
  LAURUSLABS   OPENED Bull Call Spread  HTTP 201 id 3be1288b-5ec6-495b-ad18-95b6e8cdb354 risk allow
  MSUMI        OPENED Shares            HTTP 201 id 18f34ce6-5a44-4117-b70c-808ccb149d93 risk allow
  DIVISLAB     OPENED Bull Call Spread  HTTP 201 id 545c4598-15cf-49dc-a1a7-f46ad01f44f4 risk allow
  SONACOMS     OPENED Bull Call Spread  HTTP 201 id 5e5ab2ff-fc95-4ccc-9087-93a7a469dcf9 risk allow
  BOSCHLTD     OPENED Bull Call Spread  HTTP 201 id 6c9d7201-a413-4283-be35-b3d3f3083dd1 risk allow
  DRREDDY      OPENED Protective Put    HTTP 201 id adf192e8-4b26-41f9-8dbd-ccde890fd336 risk allow
  SYNGENE      OPENED Shares            HTTP 201 id 97e97782-4f0a-4010-8978-e38fec81d602 risk allow
  PPLPHARMA    REFUSED Shares            HTTP 409 risk_blocked: Open positions are at the limit.
  TVSMOTOR     REFUSED Protective Put    HTTP 409 risk_blocked: Open positions are at the limit.
  MINDACORP    REFUSED Shares            HTTP 409 risk_blocked: Open positions are at the limit.
live HTTP 200 market {'live': True, 'source': 'kite_live', …, 'options_live': True} totals {'open_pnl_rs': 4540.68, 'open_pnl_complete': True, 'realised_today_rs': 0.0, 'open_count': 7, 'closed_today_count': 0}
  LAURUSLABS   Bull call spread       open    entry 2292.8 live 2294.6 pnl 616.25 (0.4%) …
  SYNGENE      Shares                 open    entry 405.8 live 408.85 pnl 2870.05 (6.32%) …
```
The three refusals are the risk gate's 10-open-positions cap (3 earlier paper trades + 7) — shown, not worked around.
Live book at 09:24 IST: `totals {'open_pnl_rs': 16012.57, 'open_pnl_complete': True, 'realised_today_rs': 0.0, 'open_count': 7, 'closed_today_count': 0}`.

## Data Correctness (staging)
Entries are Kite live prices of 4 Nov at the moment of opening (stock `day_quotes` source kite_live; option legs Kite REST
quotes, traded today); the shares entry was checked against today's live range by the desk; levels are the page's plan of the
3 Nov close; sizes are the risk gate's approved quantities / lots on the Rs 1 crore paper equity (0.5% per trade ≈ Rs 50,000).

## UI / Playwright Tests
```
TSC_EXIT=0
BUILD_EXIT=0
✓ built in 31.27s
PW_EXIT=0
  ✓  105 … copilot-app-market-recovery.spec.ts:899:3 › … 6 · Paper trades (live) (§10) › TC-P9 the plan: the chosen structure, the gate's size, reward : risk after costs, skipped and already-open rows; the live book (3.1s)
  ✓  106 … :954:3 › … TC-P9 the button is off unless quotes are live: 'Market not open' and 'Kite login needed' (2.8s)
  ✓  107 … :965:3 › … TC-P9 Kite login needed when the market is open but the live feed is not (2.6s)
  ✓  108 … :974:3 › … TC-P9 opening: confirm, then each chosen body is POSTed to the desk with its Idempotency-Key; a 201 and a 409 refusal are shown (2.0s)
  ✓  109 … :1009:3 › … phone 390px › TC-P9 at 390 px part 6 stays inside the screen; its tables scroll in their own box (1.7s)
  109 passed (2.5m)
```
TC-P10 — the real plan and live book of 09:17 rendered (scratch spec, scratchpad `mr-paper-real/`):
```
W1280 planRows=10 liveRows=7 overflow=0 pageerrors=0 lint=0
W1280 totals="Open P&L +₹4,540.68 | Realised today ₹0.00 | 7 open · 0 closed today | updates every 30 s"
W390 planRows=10 liveRows=7 overflow=0 pageerrors=0 lint=0
  2 passed (4.7s)
```

## Inputs required from user
- none (the owner's staging session token on this VM was valid; the admin Kite login for 4 Nov was already done).

## Verdict: PASS
