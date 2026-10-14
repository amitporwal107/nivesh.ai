# Functionality Verification Report — Live holdings and F&O positions from every connected broker

- **Branch:** feat/broker-live-holdings (worktree /home/deploy/nivesh-broker-live, off origin/dev 3f6521fd)
- **Date:** 2026-10-14
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Changed areas:** backend routes/services: yes (routes/broker_connect.py, services/brokers/hub_reads.py) · frontend src: yes (screens/desk/broker.ts, desk/BrokerPositions.tsx)

## Summary
User (2026-10-14): "I need all broker connectivity where the broker connections are already established and fetch live
portfolio holdings and F/O positions". Today holdings reach the screens only through sync (stored, "as of last sync");
positions are already read live (GET /api/broker/positions). This adds a live, unstored holdings read across every
connected account and shows live holdings + live F&O positions per account in the broker block (Trader desk and the
Smart trading desk's Portfolio tab). Read-only; nothing places an order.

Staging state (read-only check, 2026-10-14 15:20 IST): one user, two accounts — ICICI Direct (session live until
midnight IST, 9 holdings stored) and Zerodha (session ended 06:31 IST, reason broker_rejected → needs a reconnect;
likely the research job's sign-in on the same Kite app).

## Test Cases
> Authored up front — after the API + UI design and before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| BL-1 | route | GET /api/broker/holdings: every account read concurrently, per-account entry with holdings, counts, totals, as_of | unit | shape as specified || PASS — unit (test_broker_live_holdings.py); staging read: 2 accounts in 1147 ms |
| BL-2 | route | one account fails / session ended / not supported → that entry ok:false with code+message; others still returned | unit | isolation || PASS — unit; staging: Zerodha ok:false BROKER_SESSION_EXPIRED while ICICI ok:true |
| BL-3 | route | broker rejects the token → session ended (as for positions), entry says reconnect | unit | as stated || PASS — unit (session ended on rejection); not triggered on staging (no broker refused a token) |
| BL-4 | route | another user's account id → 404; GET /api/broker/accounts/{id}/holdings live for one account | unit (security) | as stated || PASS — unit (404 for another user, single-account route, 401, flag off) |
| BL-5 | route | nothing written to db.holdings by a live read; nulls (not zeros) when a price/average is missing | unit | as stated || PASS — unit (no writes to db.holdings / broker_accounts); staging writes check unchanged=True for both accounts; unpriced ICICI row has null figures |
| BL-6 | UI | per account: broker icon + name, live holdings table with icons, totals worked from payload, "Live · read HH:MM" | e2e (mocked) | as stated || PASS — Playwright (mocked) |
| BL-7 | UI | failed account: reason + Reconnect / retry; stored rows below labelled "as of last sync", never as live | e2e | as stated || PASS — Playwright (mocked) |
| BL-8 | UI | positions All / F&O switch with F&O count; F&O rows keep contract details; Refresh refetches holdings + positions | e2e | as stated || PASS — Playwright (mocked) |
| BL-9 | UI | 390px no sideways scroll; existing Trader desk + trading desk specs still pass | e2e + regression | as stated || PASS — Playwright 390px + Trader desk / Portfolio regression, 33 passed |
| BL-10 | staging data | branch code against staging: ICICI live holdings (ISIN, quantity) equal the 9 stored rows or the difference is explained; positions + F&O counts read; Zerodha entry says reconnect | live read-only | as stated || PASS with explained difference — 6 live = the 6 non-zero stored rows; 3 stored rows have quantity 0 (sold out) and are skipped by sync and live alike |
| BL-11 | staging API | after merge: GET /api/broker/holdings with the user's session token | staging API | 200 with real rows || PENDING — needs merge to dev and a staging session token |


## Backend unit tests (re-run by me, 2026-10-14 ~16:15 IST, branch code, staging backend image, no network)
`py-run-broker.sh tests/test_broker*.py -q` (all broker test files, including the new tests/test_broker_live_holdings.py with 30 tests):
```
870 passed, 1 skipped, 1 warning in 15.13s
```

## Frontend (re-run by me, same time)
`broker-run.sh tsc` → `TSC CLEAN`
`broker-run.sh pw e2e/tests/copilot-app-trader.spec.ts e2e/tests/copilot-app-desk-portfolio-fno.spec.ts` (production build, then `npx playwright test`, every /api call route-mocked, labelled MOCK):
```
vite build ok
  ✓  20 … Trader desk — broker block › live holdings: the feature switched off, a failed read and a wrong-shaped answer each say so, and the stored rows stay labelled
  ✓  19 … Trader desk — broker block › open positions: an account with none, the feature switched off, a failed read and a wrong-shaped answer each say so
  ✓  31 … Trader desk and Paper trades — phone (390×844) › the desk with live holdings, positions and stored rows does not scroll sideways; each table scrolls inside itself
  …
  33 passed (23.1s)
```

## Staging data (BL-10) — branch code against the staging databases, read-only
Run by the agent at 2026-10-14 15:38 IST: the branch's backend mounted read-only into the staging backend image on the staging network.
- The real route functions were called inside one `asyncio.run`. Only the user dependency was replaced, with the staging owner .
- The env dump was mode 600 and was deleted in the same command.

Output, verbatim:
```
account ba_<zerodha> broker=zerodha native=True status=expired ended_reason=broker_rejected
account ba_<icici> broker=icicidirect native=True status=active ended_reason=None
GET /api/broker/holdings: 2 accounts in 1147 ms
  ba_<icici> ICICI Direct: ok=True error=None count=6 price_source={'broker': 5, None: 1} totals_null={'invested_rs': True, 'value_rs': True, 'pnl_rs': True, 'pnl_pct': True}
    live   (ISIN, qty) x6: [redacted in the committed copy: the user's real holdings]
    stored (ISIN, qty) x9: [redacted: 3 rows with quantity 0 + the same 6 as live]
    only live: []; only stored: [3 rows, each with quantity 0.0]
    rows lacking average or price: [1 ISIN, redacted]
  ba_<zerodha> Zerodha: ok=False error=BROKER_SESSION_EXPIRED count=None
GET /api/broker/positions: 2 accounts in 153 ms
  ba_<icici> ICICI Direct: ok=True counts={'total': 4, 'fno': 2, 'intraday': 0}
  ba_<zerodha> Zerodha: ok=False error=BROKER_SESSION_EXPIRED counts={'total': 0, 'fno': 0, 'intraday': 0}
writes check: ba_<zerodha> unchanged=True; ba_<icici> unchanged=True
```
What the output shows:
- **Holdings:** the 6 live ICICI holdings equal the 6 stored rows with a quantity. The other 3 stored rows have quantity 0 (sold out); sync and the live read both skip such lines.
- **Unpriced holding:** One holding came back from ICICI with no average and no price, and masterdata has no price for it either. Its figures are null, so the account totals are null. The screen sums the 5 complete rows and labels that sum.
- **Positions:** ICICI has 4 live positions, 2 of them F&O.
- **Zerodha:** needs a reconnect. It was not called.
- **Writes:** nothing changed for either account.

**Known gap, existing behaviour, not changed here:** in the all-accounts positions route, an account that could not be read carries counts of 0 rather than null. The UI does not show those counts for a failed account. A follow-up should make them null.

## Not verified
- **BL-11:** not run yet. It needs the branch merged to dev and deployed, plus a staging session token from the user. Then I can call `GET /api/broker/holdings` and `/api/broker/positions` over HTTP with real auth and the real flag, and check the screen against the real ICICI and Zerodha accounts.
- **Zerodha live read:** the user must reconnect first. Its saved session was rejected at 06:31 IST.

## Verdict: BLOCKED
Unit, Playwright and the read-only staging data check pass. The HTTP check on staging (BL-11) waits for the merge and a session token, so this is recorded as an override and is not PASS.
