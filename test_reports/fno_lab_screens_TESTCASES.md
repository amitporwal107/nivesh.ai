# Test cases: F&O lab screens (`feat/fno-lab-screens`)

Written before implementation. The design comes from `docs/ai_research/designs/Nivesh F&O Desk (1).html` (seven PRD §15.1 screens).

## Scope

The product implements the design's **today** state. Every panel reads real data where it exists on `dev`. Where a feature is not built yet, the panel says so with its backlog tag, as the design does.

The design's **target** state is not implemented. Its illustrative numbers would read as real data inside the product.

The screen lives at `/app/tool/fnolab`; `?screen=` picks one of the seven.

## Shell (S)

| ID | Case | Expected |
|---|---|---|
| S-1 | Open `/app/tool/fnolab` | `screen-tool-fnolab` renders with seven tabs, in order: Market Intelligence, Strategy Programs, Replay Lab, Shadow Mode, Live Desk, Certification, Audit. Market Intelligence is selected. |
| S-2 | Open `?screen=audit`, then click the Shadow tab | Audit opens first. After the click, the URL holds `screen=shadow` and Shadow opens. |
| S-3 | Mode strip per screen | Research for MI, Replay and Audit. Governance for Programs and Certification. Shadow for Shadow. "Live · disabled" for Live, saying no order path exists. |
| S-4 | Source cards | Each screen shows a source row. Each card names a real source and time, or a backlog tag (P0.1, P2.1 and so on) for something not built. No card claims a source that does not exist. |
| S-5 | 390 px viewport | No horizontal page scroll. The tab bar scrolls by itself. |
| S-6 | Footer | The SEBI F&O note is shown, along with the line that the system places no orders. |
| S-7 | No illustrative data | No panel shows a number that did not come from an endpoint. The text "Illustrative" never appears. |

## 01 Market Intelligence (MI)

| ID | Case | Expected |
|---|---|---|
| MI-1 | Underlying picker | NIFTY, BANKNIFTY, RELIANCE, HDFCBANK, TCS. Switching changes the symbol in the futures and chain requests. |
| MI-2 | Regime | From `GET /api/macro/today` → `regime`. Shows the regime label, the rule version (`desk-regime-v1`), the session it read and the inputs it used. Says the rule reads India VIX, trend and breadth, not VIX alone. If the response has no regime, the panel reads "Regime not available" and invents none. |
| MI-3 | Futures build-up per expiry | One row per contract from `GET /api/fno/{sym}/futures`: expiry, price change %, OI change % (change_in_oi ÷ (oi − change_in_oi)) and the label from `oi_buildup`. A missing value shows "—", never 0. A note says each expiry is read on its own (the scan sums OI across expiries). |
| MI-4 | Options from the EOD chain | From `GET /api/fno/{sym}/chain`: OI by strike for ATM ±3, PCR, max pain, ATM IV, and the chain's as-of date. IV rank reads "Unavailable · no IV history (P0.2)". |
| MI-5 | Quote quality, indices | From `GET /api/live/option-chain?underlying=&expiry=`: ATM ±5 median spread %, p95 quote age, stale count, contracts cached. `cache` empty or unavailable → "No live option quotes cached", with the reason (outside the session or feed down). No tile is computed from an empty cache. |
| MI-6 | Quote quality, stocks | "Stock options are not on the live feed (P0.1)". No tiles. |
| MI-7 | Greeks source | "Calculated · Black-76 from end-of-day prices · fixed rate". The design says no broker Greeks and no provenance flag yet (P0.2). |

## 05 Strategy Programs (P)

| ID | Case | Expected |
|---|---|---|
| P-1 | Library | From `GET /api/desk/strategy/templates`. Each template shows its name, legs, parameters, calculation version and the status "Template · not a certified program". |
| P-2 | Dry run | Pick a template and an index. Strikes come from the EOD chain around ATM; premiums are the chain closes. Calls `POST /api/desk/strategy/payoff` and shows the net premium, max loss, max profit, breakevens and calculation version, plus the legs as the child orders it would produce. The page says nothing was sent anywhere. |
| P-3 | Not built | Compiler, executor and program certification are listed as not built (P3.1, P3.2). The risk pre-check says no dry-run check exists. |
| B-1 | Backend `GET /api/desk/strategy/templates` | Without auth → 401. With auth → 200 `{templates: [{name, kind, legs, params, calculation_version: "payoff-v1"}], read_only: true}`. The list matches the functions in `services/strategy_plan/templates.py`. |

## 06 Replay Lab (R)

| ID | Case | Expected |
|---|---|---|
| R-1 | Today | Not built (P2.1, P0.1). Says what exists: futures-signal research studies (`services/fno_backtest`) using cash prices as a futures proxy, not options replay. No metric is shown. |

## 08 Shadow Mode (SH)

| ID | Case | Expected |
|---|---|---|
| SH-1 | Today | Not built (P2.2). Shows the real forward-test status from `GET /api/fno/forward-test` (sessions recorded, signals, judged), labelled a forward test of a futures signal and not shadow mode. An error in that panel does not hide the gap message. |

## 09 Live Desk (L)

| ID | Case | Expected |
|---|---|---|
| L-1 | Readiness list | The 12 PRD §21 conditions with "0 of 12 enforceable" and the backlog tag that closes each one. The kill-switch row reads `/api/risk/status` (on/off). The risk-policy row reads `gate.enabled` and the policy version. |
| L-2 | No order path | No authorise button and no order ticket. `live_execution_available: false` reads "Live orders are off". |

## Kite sessions panel on Live Desk and MI (K) — added 2026-10-26 ("Need a kite login for the same")

Two Kite logins already exist in the backend. Both are reused here; neither is new.
- The platform's daily data session, admin only: `POST /api/live/kite/login-url`. Its state is read from `GET /api/live/status`.
- The user's own Zerodha account, read-only, which is the future order route: `GET /api/broker/accounts`, `GET /api/broker/native/supported`, `GET /api/broker/native/start/zerodha`.

| ID | Case | Expected |
|---|---|---|
| K-1 | Admin; feed expired in an open session (`alert_state: TOKEN_ALERT`) | `fnolab-kite-platform` has `data-state="login_needed"` and the text "Kite login needed". The button `fnolab-kite-login` sends `POST /api/live/kite/login-url` and the browser goes to the returned `login_url`. |
| K-2 | Non-admin; same feed state | No `fnolab-kite-login` button. The text says an admin logs in once a day. |
| K-3 | Feed LIVE | `data-state="live"`, the text says the Kite session is active, and there is no login button. |
| K-4 | Market closed, platform token stored and not expired | `data-state="closed"`. The text says the market is closed and shows how long today's session is valid. No login button. |
| K-5 | No Zerodha account; the zerodha adapter is connectable | `fnolab-kite-own` has `data-state="none"`. `fnolab-kite-connect` goes to `/api/broker/native/start/zerodha?return_to=` plus the encoded `/v5/app/tool/fnolab?screen=live`. |
| K-6 | Zerodha account active (masked id ••••34) | `data-state="connected"` and the text "••••34". No connect button. The read-only line is shown. |
| K-7 | Zerodha account with `needs_reconnect: true` | `data-state="reconnect"` and the button `fnolab-kite-connect` reads "Reconnect Zerodha". |
| K-8 | MI screen | The platform row (`fnolab-kite-platform`) is shown above the live chain. The own-account row is not shown on MI. |
| K-S | Staging after merge (admin session) | The panel reads the real `/api/live/status` and `/api/broker/accounts`, and its state matches the API answers in the report. |

## 11 Certification (C)

| ID | Case | Expected |
|---|---|---|
| C-1 | Today | No certification records. Shows the PRD §14.6 status ladder of seven statuses and the note that data-lake date certification is not agent certification. |

## 12 Audit (A)

| ID | Case | Expected |
|---|---|---|
| A-1 | Decisions | From `GET /api/risk/decisions`: outcome, path, symbol, time, correlation id, newest first. |
| A-2 | Lineage | Selecting a decision shows the 10-step lineage. Only the steps that are recorded today are marked Recorded (risk decision, plus the control audit when present). The others read "Not recorded · P0.3". |
| A-3 | Search | Searching by decision id or correlation id filters the list. |
| A-4 | Control changes | From `GET /api/risk/audit`, newest first. |
| A-5 | Replay | No replay button. Instead: "Replay needs the snapshot store (P0.3)". |

## Verification plan

1. Frontend: `tsc --noEmit`, then a Playwright spec with mocked endpoints through the docker recipe, on desktop and 390 px.
2. Backend: pytest for B-1 through the throwaway-container recipe.
3. Staging after the merge and a backend restart: B-1 with a real session, and Playwright against staging with the admin session for S-1 and A-1.
