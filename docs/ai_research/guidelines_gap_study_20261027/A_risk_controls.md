# Study A: risk controls and execution safety vs the trading-decision PRD

Scope: PRD `docs/NIVESH_AI_LAB_TRADING_DECISION_GUIDELINES.md` §1 gates 4–5, §5 capital-risk stop, §6 sizing and portfolio risk, §7 "Mandatory safeguards", §11 pseudocode.
Code: clean checkout `/home/deploy/nivesh-idea-levels` at HEAD `5b6b3cfd` (= origin/dev). Staging runs the same commit: `sudo git -C /opt/nivesh-staging/repo log -1` printed `5b6b3cfd Merge pull request #352`. All file:line references are relative to `backend/` unless they say otherwise.
Method: I read the code, ran 20 existing test files (817 passed), probed pure functions in a throwaway container (read-only mount, `--network none`), and ran read-only Mongo and NIDP queries against staging. I wrote nothing to the repo or to staging.

Labels: **VERIFIED** means I read the code or ran the command this session and the output is below. **UNVERIFIED** means I could not prove it, and I say why.

---

## 0. Verdict on the claims I was asked to check

| Earlier claim | Verdict | Evidence |
|---|---|---|
| Desk paper trades only check the kill switch (`assert_allowed`) | **Partly true. Missing two things.** With the gate off (staging's setting), the desk runs three checks: the kill switch, an atomic paper-account funding reservation (quantity × entry must fit in cash − blocked), and a cap of 100 open trades. No governor limit runs. | `routes/desk_trading.py:103-110` (kill switch, only when not gated), `:138-143` (reserve), `:147-155` (open-trade cap) |
| The AI-Trader governor limits (1%/trade, 3% daily, 15% DD, 30% sector, min RR 1.5) apply only to AI Trader | **CONFIRMED.** `evaluate()` has exactly two callers, both in `routes/ai_trader.py` (`:672`, `:816`). Two more facts. First, no frontend-v5 screen calls `/api/ai-trader/*`. Second, staging holds **0 AI-trader tickets**, so on staging the governor has never decided a real entry. | grep output in Q1; staging counts in Q9 |
| `fno_risk_gate` exists but is off by default | **CONFIRMED.** The default is `"off"` (`feature_flags.py:57`). It is also **off on staging**: the persisted value is `{'mode': 'off', 'allowlist_len': 0}`. It was briefly on during a test on 2026-10-24 (two gate rows at 23:07:32) and turned off at 23:08:51. | Q4 |
| Capital basis is maybe a hard-coded ₹10 lakh | **CONFIRMED, with a twist.** The paper account starts at a constant `DEFAULT_CAPITAL = 1_000_000.0` (`services/paper_account.py:37`), and no route can change it. The governor does **not** use that account. It measures against the AI strategy's own `config.initial_capital`, which the user sets per strategy (default 1e6, maximum 1e10). So the "1%" can be 1% of a number the user chose. | Q2 |
| Total open risk, correlation/concentration, cost/gap stress | **Total open risk: missing everywhere. Correlation: missing. Concentration:** a position cap of 10% and a sector cap of 30% exist, but only in the AI governor, and the sector input is usually unknown. **Costs and gap stress are not in any sizing or limit.** | Q3, probes P2/P3 |
| Atomic risk reservation for concurrent entries | **Partial.** Paper-account *notional* funding is atomic (one conditional `$inc`). *Risk* budget (the governor's limits, the gate's open-structure count) is read-then-write with no lock or reservation. | Q5 |
| Rejection audit | **Partial.** `risk_decisions` records gate decisions (fail-closed) and governor and kill-switch decisions (fail-open writes). Validator, funding, open-trade-cap and journal refusals are not recorded. A desk trade that is allowed with the gate off has no decision row. | Q6 |
| Live-execution separation | **CONFIRMED as separated today.** No order call exists in the backend, enforced by an AST test. `LIVE_EXECUTION_AVAILABLE = False` is a code constant. The OpenAlgo proxy route is gone from origin/dev and from the running staging app. Raw `KiteConnect` objects with user tokens still exist, so the guard is a test, not a capability boundary. | Q7 |

---

## 1. PRD rule → status table

Statuses: Implemented / Partial / Missing / Contradicts. Severity reflects risk to users and to the product's claims.

| # | PRD rule | Status | Evidence (file:line, probe, data) | Severity |
|---|---|---|---|---|
| R1 | §1 gate 4: size within per-trade, portfolio and drawdown limits before eligibility, on every entry | **Partial** | Only the AI-trader path runs the governor (`routes/ai_trader.py:672,816`). The desk (every UI "Add paper trade" button) and the journal run no sizing limit. Staging counterfactual: all 6 real desk cash entries would have been reduced or rejected by the governor (Q9). | **High** |
| R2 | §1 gate 5: spread, slippage, event risk, margin and order mechanics acceptable | **Missing** | No bid/ask or spread check on any path. `Intent.event_blackout` is never set by any caller (grep printed nothing). ADV is never supplied (`services/ai_trader/execution.py:31-33` docstring; the provider adds no `avg_daily_value`, per grep). Margin is computed by `routes/fno.py:813` (`fno_margin`) but no entry path checks it; `services/risk_gate/readiness.py:90-92` says so itself. | High |
| R3 | §1: a strong score never overrides a hard risk rejection | **Partial** | The governor and gate are independent of scores (`risk_governor.py:124-133`, AST test `test_the_governor_imports_nothing_from_the_strategy_evidence_or_ai_side`). The desk path, which carries scanner "Top 10" ideas, has no hard risk rejection to override. | Med |
| R4 | §5: quantity = floor(max trade risk ÷ risk per share), rounded down to the lot | **Partial** | AI path: `execution.py:137,154` sizes from budget = capital × 1%. The governor caps it (`risk_governor.py:296`). Desk: quantity is **user input** up to 1,000,000 (`services/desk_trading.py:319`, `MAX_QUANTITY=1_000_000`). The Top-10 UI pre-fills a "sized quantity" but the field is editable (`frontend-v5/.../ScannerTop10.tsx:74-84`). F&O lots are user input. The gate verifies the lot size equals the exchange lot only when it is on. | High |
| R5 | §5: include fees, taxes, spread and slippage in the risk estimate | **Missing** (in limits) | The governor's risk is `cap × 1% / (e − s)` with no costs (`risk_governor.py:296`). Probe P2: PRD Example A at qty 85 has gross risk ₹2,975 against a ₹3,000 budget, but the **net-of-cost loss at the stop is ₹3,098.94, which exceeds the budget**. The scenario calculator (`routes/positional.py:1625+`) reports `loss_at_stop_net` but still sizes on gross risk. Taxes are excluded by its own caveat. | Med |
| R6 | §5: stop fills can be worse than the trigger (gaps) | **Missing** (in limits) | No gap stress anywhere. Probe P3: a 10% gap through the Example A stop loses ₹11,220, which is 3.74% of capital against the 1% limit. | Med |
| R7 | §5/§7: do not widen a stop after entry | **Implemented (by absence)** | No update route for stop or levels on the desk (strategy trades are immutable, `desk_strategy_trades.py:16-17`), the journal (only create, fill, close and delete), or AI tickets. | Low |
| R8 | §6: maximum rupee risk per trade | **Partial** | Governor: 1% of `initial_capital`, AI only. Gate (when on): an absolute ₹2,00,000 cap on *capital at risk*. For cash that is **notional**, not stop risk (`services/risk_gate/gate.py:297-301`, `routes/desk_trading.py:132`). Probe G2: a cash trade with ₹1,99,995 notional and ₹6,965 stop risk (2.3% of ₹3L) is **allowed**. Basket sizing uses 2% (`routes/positional.py:1588,1601`). That makes three inconsistent definitions. | High |
| R9 | §6: total open risk across positions | **Missing** | No open-risk sum in the governor, the gate or the paper account (grep for `open_risk` found nothing). The governor has gross *exposure* ≤80% and position count ≤10. `gate.usage()` sums structure capital at risk for display only (`gate.py:497-510`). | **High** |
| R10 | §6: correlation and concentration | **Partial** (concentration) / **Missing** (correlation) | The governor has position ≤10% of capital (`risk_governor.py:298`), sector ≤30% (`:303-317`) and ALREADY_HELD (`:271-272`), on the AI path only. A new intent's sector comes from the candidate row. The provider adds none (grep), so it reports SECTOR_UNKNOWN and skips the check. There is no correlation check. (`graph.correlations` exists for the MF engine, `services/rules_config.py:185-189`.) | High |
| R11 | §6/§7: daily and weekly loss limits | **Partial / Missing** | Daily: AI path only. It uses **realised** P&L only, and gross `realized_pnl_rs` rather than net (`routes/ai_trader.py:363-369`; probe P7). Unrealised losses never trigger it. Weekly: none anywhere (grep printed nothing). | High |
| R12 | §6/§7: portfolio drawdown limit | **Partial, fail-open** | The governor halts at ≥15% (`risk_governor.py:241-242`). When equity is unknown, which is **always the case while any F&O structure is open** (`routes/ai_trader.py:386-410`), it records `DRAWDOWN_UNKNOWN` at severity `info` and approves (probe P4b). The peak store `risk_equity_peaks` does not exist on staging. The halt is never persisted into `risk_controls.halted`; only a person sets that (`set_control` callers are routes only). | High |
| R13 | §6: available margin | **Partial** | Paper funding = cash − blocked (`paper_account.py:128-150`). That is notional for cash and "capital at risk" for F&O, explicitly not exchange margin (`paper_account.py:15-18`). Real SPAN margin is not checked before entry. | Med |
| R14 | §6: options max loss from the full multi-leg payoff | **Implemented in the gate (off) / Partial on the desk** | Gate: exact max loss at expiry over the strike kinks (`gate.py:223-231`). Probe G3: Example F gives ₹4,500. The paper-account reservation uses a different bound, the outer strike span × quantity (`desk_strategy_trades.py:606-653`). Staging spread: gate ₹4,618.25 against a reservation of ₹13,000 for the same position. | Med |
| R15 | §6/§9: defined risk; reject unbounded structures | **Contradicts on the desk with the gate off** | The desk validator accepts futures-only structures, including a short future, and stamps them `"defined_risk": True` with an "unbounded" note (`desk_strategy_trades.py:209-211`; probe D1). The reservation for a short future is notional, but its loss is unbounded upward. The validator also accepts any `lot_size`: probe D2 shows NIFTY at lot_size=1 reserving only ₹25,000. The gate (off) blocks both (`futures_only`, probe G5). | High |
| R16 | §7: honor the initial risk plan | **Partial** | The desk stores stop and target immutably. The journal stores `stop_loss` as **0 when missing** (`routes/positional_journal.py:196`), so a journal trade can have no stop. Journal ENTRY fills can add any quantity at any price. | Med |
| R17 | §7: do not average down unless permitted and within the original budget | **Missing** (desk, journal) | Desk: no same-symbol check. Probe: an identical POST twice gives `201 201` and three open trades in one symbol. Staging: **HAL opened 3× and ICICIBANK 2×** at identical levels (Q9). Journal: unlimited ENTRY fills. ALREADY_HELD exists only in the governor. | High |
| R18 | §7: do not reverse a stopped trade without a new setup | **Missing** | No cooldown or re-entry rule on any path. | Low |
| R19 | §7: respect daily/weekly loss and drawdown limits (safeguard) | **Missing outside AI** | Same as R11 and R12. The kill switch and halt are manual only. | High |
| R20 | §11: one `evaluate_trade` that rejects with reasons before anything is written | **Partial** | Two engines (governor and gate) with different limits, inputs and audit semantics, and neither runs on every path. See Q1 matrix. | High |
| R21 | §11: concurrency controls | **Partial** | Funding reservation is atomic. The governor book, gate open-structure count, ALREADY_HELD and sector are read-then-write. There is no idempotency key on the desk POST. The OMS idempotent store exists but nothing calls it (`services/oms/orders.py`; only `risk_gate/replay.py` and tests import it). | High |
| R22 | §11/§10: audit logs; rejection reasons with timestamp and rule version | **Partial** | `risk_decisions` (Q6). Gaps: desk-allowed trades have no decision row (staging: 8 of 9 desk trades have no `risk_decision_id`); validator, funding and cap refusals are not logged; kill-switch rows carry no symbol and no correlation id; the governor's and kill switch's own audit writes are fail-open (`risk_controls.py:250-256`). | Med |
| R23 | §11: failure-safe behaviour | **Partial** | Fail-closed: kill switch (`risk_controls.py:197-210`), gate reads and decision write (`gate.py:408-422,486-491`), reference lookup. Fail-open: governor unknowns (drawdown, VIX, regime, sector, ADV are all `info`), the record_decision write, and the journal fill when the gate is off (next row). | High |
| R24 | Kill switch blocks **all** position-creating paths | **Contradicts** | `risk_controls.py:12` and `routes/risk_controls.py:21-23` claim the journal is blocked. But `add_fill` checks the kill switch **only when the gate is on** (`routes/positional_journal.py:315`). Probe: kill switch ON, gate OFF, a ₹1 crore ENTRY fill returns **200**. | **High** |
| R25 | Live execution separated and guarded | **Implemented** | Q7. | Low (today) |

---

## Q1. Every entry path that creates a paper trade or position

Staging route table (VERIFIED, imported from the running app's code inside the backend container):
```
openalgo routes: []
order-like routes: []
paper/position-creating POST routes: [... '/api/ai-trader/strategies/{strategy_id}/signals', '/api/ai-trader/tickets/{ticket_id}/confirm', ...,
 '/api/desk/paper-trades', '/api/desk/paper-trades/{trade_id}/close', '/api/positional/journal', '/api/positional/journal/{trade_id}/close', '/api/positional/journal/{trade_id}/fill']
```
Writers to `desk_paper_trades` (grep): only `routes/desk_trading.py:150` and `routes/ai_trader.py:751`. Copilot tools write no paper trades (grep found nothing). Scripts only close trades (`scripts/check_desk_alerts.py:57`, exits).

| Path | Store | Kill switch | Governor | Gate (flag) | Funding reservation | Other checks | Bypass |
|---|---|---|---|---|---|---|---|
| P1 `POST /api/desk/paper-trades` cash. **Every frontend "Add paper trade"** (Top 10 `ScannerTop10.tsx:84`, AI watchlist `AiScannerWatchlist.tsx:92`, lab `FnoStrategies.tsx:362`, RiskDesk, StrategyBuilder, TopByRegime via `desk-trading.ts:565`) | Mongo `desk_paper_trades` | Yes, if the gate is off (`desk_trading.py:103-110`); inside the gate if on | **No** | If on: controls, mode, ₹2L notional cap (`:129-133`) | Yes, atomic `qty×entry` (`:138-143`) | 100 open-trade cap with a count/insert/recount compensation (`:147-155`); validator: stop < entry, target > entry if given, qty ≤ 1e6, price ≤ ₹1 crore (`services/desk_trading.py:314-372`) | Quantity, entry price and stop are **client-supplied**. Entry is not checked against the market. No same-symbol check. No RR minimum. No sizing. |
| P2 `POST /api/desk/paper-trades` `kind:"strategy"` (F&O lab, Top-by-regime) | same, `kind:"strategy"` | same | **No** | If on: defined risk, exchange lot, listed expiry, max loss ≤ ₹2L, ≤10 open structures, ≤4 legs, ≤10 lots/leg | Yes: `exposure_rs` (strike span or notional) | Validator: no naked short calls or puts, one option expiry; **futures-only allowed** (`desk_strategy_trades.py:190-224`) | Gate off (staging): any lot size (probe D2), short futures allowed, stamped `defined_risk: True` (probe D1) |
| P3 `POST /api/positional/journal` | Mongo `trade_journal` (absent on staging, 0 rows) | Yes, if the gate is off (`positional_journal.py:167-178`) | No | If on: ₹2L cap on `capital_alloc_rs` (`:183-189`) | **No** | `nse_symbol` and `capital_alloc_rs > 0` only. **The stop defaults to 0** (`:196`) | Not linked to the paper account; no stop required |
| P4 `POST /api/positional/journal/{id}/fill` kind ENTRY | `trade_journal.fills[]` | **No when the gate is off** (`:315` checks only `if ... enabled_for`) | No | If on: notional cap (`:315-319`) | No | Owner + OPEN filter (`:321-327`) | **Kill-switch bypass, VERIFIED by probe (200 with the kill switch on).** Unlimited averaging. |
| P5 `POST /api/ai-trader/strategies/{id}/signals` (mode paper/assisted). **No UI caller in frontend-v5** (grep printed nothing) | `ai_trader_tickets` + `desk_paper_trades` (paper mode) | Through `Portfolio.kill_switch/halted` from `rc.read` (`routes/ai_trader.py:376-381`); an unreadable store raises (fail-closed) | **Yes** (`:666-672`) | If on, before writes (`:654-664`) | Yes (`:745-750`) | Unique ticket index (user, strategy, date, symbol) (`:233-236`); stage gate; sealed window; ≤4-day-old signal | Capital = the user's `initial_capital` (Q2). Book read and write are not atomic (Q5). |
| P6 `POST /api/ai-trader/tickets/{id}/confirm` | same | same | **Yes, re-run on the current book** (`:816`); size never raised above the signal (`:818-827`) | If on (`:847-852`) | Yes | CAS claim on status (`:859-862`) | Same as P5 |
| (not a position) `POST /api/desk/strategy/plans`, strategy-builder backtests (`strategy_runs`/`strategy_trades` Postgres), `/api/positional/basket`, `/scenario` | plans / backtest rows / computed only | – | – | – | – | – | Read-only or simulation; no position |
| (system) NIDP TPD paper engine via `GET /api/paper-trades/*` (`routes/paper_trades.py`) | NIDP (DaaS) | – | – | – | – | – | Research portfolio, read-only proxy; outside per-user risk |
| `services/oms/orders.create_order` | `oms_orders` (absent on staging) | – | – | – | – | Idempotent per `client_order_id` | **No caller in production code** |

Callers, VERIFIED by grep (output abbreviated):
```
routes/ai_trader.py:84:from services.ai_trader.risk_governor import (... evaluate)     <- only importer of evaluate
routes/ai_trader.py:654 / :847   risk_gate.enabled_for     routes/desk_trading.py:98   routes/positional_journal.py:167, :315
routes/positional_journal.py:172: await rc.assert_allowed(...)    routes/desk_trading.py:105: await rc.assert_allowed(...)
```

## Q2. Capital basis per path

| Path | Capital that sizing or limits measure against | Configurable? | If absent |
|---|---|---|---|
| Desk P1/P2 | No sizing. Funding only: `paper_accounts.cash_rs − blocked_rs`, created at `DEFAULT_CAPITAL = 1_000_000.0` (`paper_account.py:37,100-101`) | **No.** `starting_capital_rs` is written only by `ensure()` (grep: no other writer, no route) | `public()` reads defaults when there is no row (`:70-72`); `reserve()` creates the row first (`:139`) |
| Journal P3/P4 | `capital_alloc_rs` from the request body; no account | Per request | 400 if ≤ 0 |
| AI P5/P6 | `strategy.config.initial_capital` (`routes/ai_trader.py:666,809`), from `ui_config` at creation, default `AI_DEFAULTS.initial_capital = 1_000_000.0` (`services/ai_trader/config.py:17`), range (0, 1e10] (`:29-31`) | **Yes, per strategy, by the user**, independent of the paper account | Confirm uses `or 0` (`:809`), and the governor rejects `NO_CAPITAL` |
| Gate (all, when on) | No capital: an absolute ₹2,00,000 per trade (`services/risk_gate/policy.py:110`) | Code constant (bump `POLICY_VERSION`) | n/a |
| Governor limits | `DEFAULT_LIMITS` (`risk_governor.py:144-163`), always passed by the routes (`:672,816`) | **Code constant.** The docstring says "Limits come from `Limits`, which a person sets", but there is no store or route for that | n/a |
| Basket `/api/positional/basket` | `capital_rs` from the body, 2% per position (`routes/positional.py:1568,1601`) | Per request | 422 |

Probe P6 (VERIFIED): with `initial_capital=1e8` the governor **approves** 2,857 shares (₹28.7 L notional) unchanged. The paper account (₹10 L) is the only thing that would then stop it, and only on notional. Staging data: both AI strategies use `initial_capital = 1000000.0`; the one paper account has `starting_capital = 1000000.0`.

## Q3. The governor

`services/ai_trader/risk_governor.py` (`LIMITS_VERSION = "gov-v1"`), a pure function of `(Intent, Portfolio, Market, Limits)`.

| Limit | Default | Severity | Input it reads | When the input is missing |
|---|---|---|---|---|
| kill switch / halted | – | halt | `rc.read` → Portfolio (`routes/ai_trader.py:376-381`) | Unreadable → exception → 500 (closed) |
| drawdown | 15% | halt | `risk_equity.snapshot` (equity = capital + net realised + net unrealised; stored peak) | **None → `DRAWDOWN_UNKNOWN` info → proceeds (open).** Always None while an F&O structure is open (`routes/ai_trader.py:399-409`) |
| daily loss | 3% of capital | halt | Σ `realized_pnl_rs` (gross) of trades closed today in IST (`:362-369`) | Unrealised loss ignored; no weekly limit |
| capital > 0, qty, entry > 0 | – | reject | intent | reject |
| stop required, below entry, ≤15% away | 15% | reject | intent | reject (`STOP_REQUIRED`) |
| target required, RR ≥ 1.5 | 1.5 | reject | intent | reject |
| open positions | 10 | reject | open desk trades (cash + strategies as one unit each) | – |
| already held | – | reject | same symbol in the book | – |
| VIX defer / reduce | 35 / 25 (×0.5) | defer / reduce | `market_context` | **None → info, skipped (open)** |
| event blackout | – | defer | `Intent.event_blackout` | **Never set by any caller** (grep) |
| BEAR regime | ×0.5 | reduce | `market_context` | None → info, skipped |
| risk per trade | 1% | reduce (cap) | `(e − s)`, **no costs, slippage or gap** | – |
| position size | 10% of capital | reduce | entry | – |
| net exposure | 80% (hedge hint 70%) | reduce | Σ qty × **entry price** (not the mark) | Strategy with no computable exposure → counted as the whole capital (`:355-359`, conservative) |
| sector | 30% | reduce | intent sector; held sector from the ticket that opened it | **Intent sector None → skipped (open).** Unclassified held positions counted against the sector (conservative) |
| liquidity | 5% of ADV | reduce | `Intent.avg_daily_value` | **Never supplied → skipped (open)** (`execution.py:31-33`) |

Total open risk (Σ qty × (entry − stop)): **not computed**. Correlation: **none**. Costs, slippage, gap: **not in the risk figure** (probes P2, P3).

Probe output (VERIFIED, `governor_probe.py` in a throwaway container):
```
P1 ExampleA, drawdown/VIX/regime/sector/ADV unknown: action=reduce req=85 approved=29 codes=['DRAWDOWN_UNKNOWN', 'VIX_UNKNOWN', 'REGIME_UNKNOWN', 'SECTOR_UNKNOWN', 'LIQUIDITY_UNKNOWN', 'POSITION_SIZE']
P2 qty 85: gross risk 2975.00 vs budget 3000.00; net-of-cost loss at stop 3098.94 (slip 0.0005, brokerage 20.0/side) -> exceeds budget: True
P3 gap-through-stop to 873.0: loss 11220.00 = 3.74% of capital (governor limit 1%) -- no gap stress in governor
P4a drawdown known 40%: action=halt req=85 approved=0 codes=['DRAWDOWN_HALT', ...]
P4b drawdown None (unmarked F&O open): action=reduce req=85 approved=29 codes=['DRAWDOWN_UNKNOWN', ...]
P5 9 open positions, gross 90% of capital: action=reject req=85 approved=0 codes=[..., 'POSITION_SIZE', 'NET_EXPOSURE', 'SIZE_BELOW_ONE_SHARE']
P6 initial_capital=1e8 (paper account is 10L): action=approve req=2857 approved=2857 codes=['DRAWDOWN_UNKNOWN', 'VIX_UNKNOWN', 'REGIME_UNKNOWN', 'SECTOR_UNKNOWN', 'LIQUIDITY_UNKNOWN']
P7 realised today 0, (unrealised loss invisible): action=reduce req=85 approved=29 ...
P7b realised today -9000 (3%): action=halt req=85 approved=0 codes=['DRAWDOWN_UNKNOWN', 'DAILY_LOSS_HALT', ...]
```
(P1 reduces to 29 because the 10% position cap binds before the 1% risk cap at ₹3 L capital.)

## Q4. F&O risk gate

What it checks, in order (`services/risk_gate/gate.py:47`): `controls` (kill switch and halt; unreadable → block), `mode` (paper or assisted only; live refused, `LIVE_EXECUTION_AVAILABLE=False`), `structure` (well-formed legs), `defined_risk` (no naked short call or put, no futures-only, no unhedged future, one expiry), `lot_size` (equals the exchange lot from the Kite NFO list in memory or the NSE bhavcopy ≤7 days old; unknown → block), `expiry` (listed and not past; unknown → block), `caps` (≤4 legs, ≤10 lots/leg, capital at risk ≤ ₹2,00,000; unknown → block), `open_structures` (<10 open; uncountable → block).

It does **not** check: margin, liquidity or spread, data freshness of the entry prices (the user supplies leg prices; `readiness.py:87-89` says "no freshness check runs before a decision"), stop-based risk for cash (it uses notional), total open risk, daily or weekly loss, drawdown, or per-user capital.

Missing data: every outside read fails closed (`gate.py:408-422`). An unrecorded decision raises → 503 and nothing is written (`:486-491`). Probe G4: when the reference is unreadable it blocks with `['lot_size_unverified', 'lot_size_unverified', 'expiry_unverified']`.

Flag: default `"off"` (`feature_flags.py:48-59`), judged on the signed-in person's email (`wiring.py:156-170`). **Staging value (VERIFIED, read-only):**
```
fno_risk_gate persisted: {'mode': 'off', 'allowlist_len': 0} | system_config.updated_at: 2026-10-24T23:08:51.399331+00:00
```
The workers re-read this from the DB on `refresh_if_stale` (`feature_gate.py:23-29`). UNVERIFIED: the in-memory value of each running worker. I did not call the authenticated `/api/risk/status`. Staging `risk_decisions` holds two gate rows at 2026-10-24T23:07:32 (one blocked `lot_size_mismatch`, one allowed NIFTY spread), so the gate was briefly on for a test.

Paths that call it when on: P1, P2, P3, P4 (ENTRY only), P5, P6 (Q1).

Probes (VERIFIED):
```
G1 cash 85 x 1005 (notional as capital at risk): allow 85425.0 [... 'caps:pass' ...]
G2 cash 199 x 1005 notional 199,995 with stop 970 (risk 6,965 = 2.3% of 3L): allow 199995.0
G3 PRD Example F bull call spread (max loss 4,500 vs PRD budget 2,500): allow capital_at_risk 4500.0
G5 gate ON, short future: block ['futures_only', 'capital_at_risk_unknown']
D1 desk validator, short future (gate OFF path): accepted; risk: {'defined_risk': True, 'futures_exposure': True, 'note': 'Futures losses can exceed the margin posted; ...'} ; reservation exposure_rs: 1875000.0
D2 same with lot_size=1 (NIFTY exchange lot is not 1): accepted, exposure_rs 25000.0
```
G3 shows the gate has no per-user budget. The PRD's own Example F says this trade should be rejected at a ₹2,500 budget.

## Q5. Concurrency and idempotency

- **Funding: atomic.** One conditional update: filter `cash − blocked ≥ amount`, then `$inc` (`paper_account.py:140-148`). It is tested by `test_two_concurrent_reserves_cannot_overdraw` (`tests/test_paper_account.py:179`). This is the only true reservation, and it reserves notional, not risk.
- **Desk open-trade cap:** count → insert → recount → compensating delete and release (`routes/desk_trading.py:146-155`). It is eventually correct for the count only.
- **Governor (AI):** reads the book (`_portfolio`, `routes/ai_trader.py:326-381`), evaluates, then inserts, with no lock and no reservation. Within one `/signals` call the in-memory book is updated after each opened trade (`:706-712`). Across concurrent requests it is not: two signals for different strategies, or a signal plus a desk POST, can both see the same free exposure, sector room, position count and absence of the symbol. Uniqueness covers only (user, strategy, signal_date, symbol) (`:233-236`). Confirm uses a CAS on ticket status (`:859-862`), which stops double confirm, not budget races.
- **Gate:** `open_structures` is count-then-insert (`gate.py:340-346`). Two concurrent structures at count 9 can both pass. UNVERIFIED at runtime: I reasoned this from code and did not run a real-Mongo race, because the suites use in-memory fakes that do not interleave.
- **Duplicate submit:** the desk POST has **no idempotency key**. Each request mints a uuid4 (`desk_trading.py:345`). The client only disables the button and uses `noRetry` (`ScannerTop10.tsx:92`, `desk-trading.ts:565`). Probe (VERIFIED): `PROBE desk identical POST twice -> 201 201 | a third at qty 9000 -> 201 created; PROBE open trades for the same symbol: 3`. The idempotent store `services/oms/orders.py:101-134` (unique `(user_id, client_order_id)` plus a fingerprint) is unused.

## Q6. Rejection audit

Store: Mongo `risk_decisions` (`risk_controls.py:41`), indexed by user and time and by correlation id (`:81-82`). It is append-only by code convention. There is no TTL and no DB-level immutability (UNVERIFIED: Mongo role permissions; I did not inspect DB users).

| Event | Recorded? | Fields | Write failure |
|---|---|---|---|
| Gate allow or block | Yes, both | `policy_version` fno-risk-v1, `inputs_hash`, `checks[]`, reasons, path, mode, actor, correlation_id, `snapshot` + hash (replayable, `routes/risk_controls.py:199`) | **503, nothing written** (closed) |
| Governor decision (AI signal / confirm) | Yes, allowed or refused | reasons with value and limit, `limits_version` gov-v1, correlation = strategy or ticket id | logged, **proceeds** (open, `risk_controls.py:250-281`) |
| Kill-switch block (desk/journal, gate off) | Yes | code `RISK_CONTROL`, controls state; **no symbol, no correlation id** (it runs before the body is parsed) | open |
| Desk allowed (gate off) | **No row** | – | – |
| Validator 422, `insufficient_paper_funds` 409, `open_trade_limit` 409, journal 400 | **Not recorded** | – | – |
| Control changes | `risk_control_audit` (audit before state, `risk_controls.py:164-192`) | who, when, before→after, reason | raises |
| Funding | `paper_account_ledger` reserve and release | amount, trade_id | logged only |

Staging (VERIFIED, read-only, allow-list projection, user ids hashed):
```
risk_decisions by action/outcome/source: [('desk_paper_trade', 'allowed', 'risk_gate', 1), ('desk_paper_trade', 'blocked', 'risk_gate', 1), ('desk_paper_trade', 'blocked', None, 5)]
desk_paper_trades with risk_decision_id: 1 | with paper_reserved_rs: 3 | open without paper_reserved_rs: 1
```
The 5 kill-switch rows all show `sym=None cid=no`. 8 of 9 desk trades have no decision record. The 2 gate rows lack `snapshot_version` (written before the snapshot feature).

## Q7. Live execution separation

- No call to `place_order / modify_order / cancel_order / place_gtt / modify_gtt / cancel_gtt` in `backend/`, including `backend/nidp`. This is enforced by `tests/test_order_path_guard.py` (AST, also catches `getattr`), which **passed** in my run (8 tests). Repo-wide grep over backend, frontend-v5/src and scripts found only comments.
- `services/execution_modes.py:32` `LIVE_EXECUTION_AVAILABLE = False` (code constant). `is_live_allowed` needs the constant **and** an admin grant (`:85-94`). Staging: `live_authorizations granted: 0`. The gate refuses `live` (`gate.py:376-388`). The AI trader refuses `live` at the schema level (`routes/ai_trader.py:601`, `Literal["paper","assisted"]`). The OMS refuses live (`oms/orders.py:92-93`).
- OpenAlgo: `routes/openalgo_proxy.py` **does not exist** on origin/dev (`ls backend/routes` and `ls /opt/nivesh-staging/repo/backend/routes | grep -i openalgo` gave exit=1). The running staging app mounts **no** `/openalgo` route and no route containing "order". `services/openalgo_client.py` posts only to `/api/v1/funds|holdings|positionbook` (`:135-164`). `docs/RISK_CONTROL_INVENTORY.md:126-130` records its removal.
- Residual risk (Low today): full `KiteConnect` objects with access tokens are built in `services/brokers/zerodha.py:56-73`, `nidp/services/kite_bars/client.py:64-73`, `services/fno_margin.py:120-126` (wrapped by a `Calculator` exposing instruments and basket margins only) and `services/kite_live_feed/gateway.py:55-58` (wrapped by `ReadOnlyKite`). The only barrier against an order call is the name-based AST test. A raw `requests.post` to a broker order URL, or a renamed call, would not be caught. Frontend-v5 copy consistently says "Nivesh cannot place orders" (e.g. `TradingDesk.tsx:660`).

## Q8. Tests

Command (VERIFIED):
```
sudo docker run --rm --network none -v /home/deploy/nivesh-idea-levels:/work:ro -w /work/backend ... nivesh/backend:staging python -m pytest tests/test_ai_trader.py tests/test_ai_trader_config_risk.py tests/test_ai_trader_execution.py tests/test_desk_paper_sim.py tests/test_desk_strategy_trades.py tests/test_desk_trading.py tests/test_execution_modes.py tests/test_fno_margin.py tests/test_oms_contract.py tests/test_order_path_guard.py tests/test_paper_account.py tests/test_paper_trades_routes.py tests/test_positional_scenario.py tests/test_risk_controls.py tests/test_risk_equity.py tests/test_risk_gate.py tests/test_risk_gate_ai_trader.py tests/test_risk_gate_desk_journal.py tests/test_risk_replay.py tests/test_risk_routes.py -q -p no:cacheprovider
...
817 passed, 3 warnings in 55.80s
```
Per file: ai_trader 43, ai_trader_config_risk 202, ai_trader_execution 81, desk_paper_sim 40, desk_strategy_trades 68, desk_trading 74, execution_modes 15, fno_margin 6, oms_contract 28, order_path_guard 8, paper_account 20, paper_trades_routes 9, positional_scenario 26, risk_controls 19, risk_equity 17, risk_gate 73, risk_gate_ai_trader 5, risk_gate_desk_journal 18, risk_replay 20, risk_routes 45. All collected; none failed for environment reasons.

The tests pass, but they test the controls that exist. **PRD rules with no test** (because no implementation exists): total open risk (R9); weekly loss (R11); costs or gap stress in the risk figure (R5, R6); correlation (R10); governor or any limit on the desk and journal paths (R1); same-symbol or averaging-down refusal on desk and journal (R17); re-entry after a stop (R18); concurrent-entry risk-budget races for the governor and gate (R21; only funding has a concurrency test); desk idempotency key; journal ENTRY fill blocked by the kill switch with the gate off. The existing `test_flag_off_a_journal_entry_is_as_before` and `test_the_fill_write_is_filtered_on_owner_and_status` assert the flag-off fill path writes and records nothing, so they lock the bypass in. Also untested: PRD worked examples A–H as golden sizing tests.

Scratch probe (VERIFIED, not in the repo; it reuses the suites' fakes; MOCK fixture symbol FIXA):
```
PROBE journal create with kill switch ON, gate OFF -> 409
PROBE journal ENTRY fill qty=100000 @100 (Rs 1 crore) with kill switch ON, gate OFF -> 200 fills now: 1 decision rows: 1
PROBE desk identical POST twice -> 201 201 | a third at qty 9000 -> 201 created
PROBE open trades for the same symbol: 3
2 passed
```

## Q9. Staging data (read-only)

Queries were run with `sudo docker exec -i nivesh-staging-app-backend python - < script` using the backend's own env, without printing it, with allow-list projections and hashed user ids. Scripts are in `docs/ai_research/guidelines_gap_study_20261027/probe/staging_counts.py`, `staging_detail.py` and `staging_times.py`.

```
collections present: {'desk_paper_trades': True, 'ai_trader_tickets': True, 'ai_trader_strategies': True, 'trade_journal': False, 'paper_accounts': True, 'paper_account_ledger': True, 'risk_controls': True, 'risk_control_audit': True, 'risk_decisions': True, 'risk_equity_peaks': False, 'oms_orders': False, 'live_authorizations': True, 'desk_strategy_plans': False}
desk_paper_trades by kind/status/source.kind: [('cash', 'closed', 'scanner', 4), ('cash', 'closed', None, 2), ('cash', 'open', 'scanner', 2), ('strategy', 'closed', None, 1)]
desk_paper_trades distinct users: 1
ai_trader_tickets by status/mode/rejected_by: []
ai_trader_strategies: 2 | by stage: [('backtested', 1), ('draft', 1)]
trade_journal by status: []
paper_accounts: 1 | starting_capital values: [(1000000.0, 1)]
risk_controls rows: 2 | kill_switch on: 0 | halted: 0
risk_equity_peaks: 0 | oms_orders: 0 | live_authorizations granted: 0
```
Trades (one user, u=a5530afb; FIXA and FIXC are test fixtures):
```
NORTHARC  closed qty=417 entry=280.66 stop=268.67 notional=117,035 stop_risk=5,000 reserved=None opened 10-19 exit=stop net=-5154.37
ICICIBANK open   qty=89  entry=1400.2 stop=1363.26 notional=124,618 stop_risk=3,288 reserved=None      opened 10-20 03:03
HAL       closed qty=25  entry=4989.0 stop=4822.25 notional=124,725 stop_risk=4,169 reserved=None opened 10-20 04:53 exit=stop net=-5137.24
HAL       closed qty=25  (identical)                                                                    opened 10-20 05:25 exit=stop net=-5137.24
HAL       closed qty=25  (identical)                                                                    opened 10-21 16:35 exit=stop net=-5137.24
ICICIBANK open   qty=89  (identical to the first)              reserved=124617.8                         opened 10-21 23:51
NIFTY strategy closed bull_call_spread 1x65 22600C/22800C reserved=13000.0 gate_id=yes (gate said capital at risk 4618.25)
paper_account starting=1000000.0 cash=984547.28 blocked=124617.8 | sum(open paper_reserved_rs)=124617.8 | open cash positions=2 total open stop-risk=6,575 (0.66%) gross=249,236 (24.9%)
```
All three HAL entries were open together and all stopped in the 2026-10-22 session, a net loss of ₹15,411.72 from one symbol on one day. NIDP sectors (VERIFIED): HAL "Capital Goods"; ICICIBANK and NORTHARC "Financial Services".

**Counterfactual: what the governor would have done** (VERIFIED, `counterfactual.py`, capital = the paper account's ₹10 L, actual book at each entry, market context unknown):
```
NORTHARC 10-19       asked  417 -> reduce  approved  356  [('POSITION_SIZE', 356, 10.0)]
ICICIBANK#1 10-20    asked   89 -> reduce  approved   71  [('POSITION_SIZE', 71, 10.0)]
HAL#1 10-20          asked   25 -> reduce  approved   20  [('POSITION_SIZE', 20, 10.0)]
HAL#2 10-20          asked   25 -> reject  approved    0  [('ALREADY_HELD', 'HAL', None), ('POSITION_SIZE', 20, 10.0)]
HAL#3 10-21          asked   25 -> reject  approved    0  [('ALREADY_HELD', 'HAL', None), ('POSITION_SIZE', 20, 10.0), ('SECTOR_LIMIT', 10, 30.0)]
ICICIBANK#2 10-21    asked   89 -> reject  approved    0  [('ALREADY_HELD', 'ICICIBANK', None), ('POSITION_SIZE', 71, 10.0)]
```
So **6 of 6** real desk cash entries breach governor limits: 3 exceed the 10% position cap and 3 are duplicates. One (HAL#3) also takes Capital Goods to 37% against the 30% sector cap. Per-trade stop risk was within 1% in every case (0.33–0.50% of ₹10 L). Open stop-risk now is 0.66%.

Data-integrity side findings (paper account, VERIFIED arithmetic): `cash 984,547.28 = 1,000,000 − 41.00 − 3×5,137.24`. NORTHARC's −₹5,154.37 is not in cash (it closed before the account existed). The first ICICIBANK (₹1,24,618) reserves nothing, so `available_rs` overstates free capital by ₹1,24,618. The NIFTY spread closed with `realized_pnl_rs: None`, so its P&L never reached cash. Two definitions of one position's risk: reservation ₹13,000 against gate max loss ₹4,618.25.

Kill-switch audit: the user turned their own switch on and off within the same second 5 times (E2E-style tests), which a self-clear is allowed to do because that user is an admin. The second user's switch was cleared by the admin. No switch is on now.

## Q10. Recommendation: one shared risk-decision service

**Core: grow `services/risk_gate` into the single decision service and make `risk_governor.evaluate` one of its checks.** Do not build a third engine.

Why the gate: it already has the contract (`RiskRequest/RiskDecision`), fail-closed reads, a fail-closed decision write (503), correlation ids, policy versioning, a stored snapshot plus `replay`, mode and live-grant handling, and it is wired (behind a flag) into five of the six entry points. Why keep the governor as a library: it is the only place with portfolio maths (position, sector, exposure, RR, VIX and regime, drawdown, daily loss). It is pure and deterministic, and 202 tests cover it. Its `_portfolio()` book reader is in the wrong place (`routes/ai_trader.py`) and should become a shared `risk_book.read(db, user_id)`.

**Interface** (extend `RiskRequest`):
- in: `user_id, actor_id, correlation_id, idempotency_key, path, mode, action(open|add), instrument(cash|structure), side, symbol, quantity|legs, entry_price, stop_price, target_price, signal_at`
- server-resolved, never client-supplied: `sector, last_close + as_of, lot_size, ADV, event window, capital basis, limits`
- out: `outcome allow|reduce|block, approved_qty|lots, reasons[{code, check, severity, value, limit}], checks[], estimated_risk_rs{gross, costs, gap_stress, total}, budget{capital_basis, per_trade, open_risk_before/after, daily_loss, weekly_loss, drawdown}, policy_version, limits_version, inputs_hash, snapshot_hash, reservation_id`

Check order: controls → mode → structure → stop/target validity (stop required on every path, including the journal) → instrument reference → **data freshness** (entry within N% of a last close no older than M sessions) → per-trade risk = qty×|e−s| + round-trip costs + gap stress ≤ per-trade budget (reduce to max qty, round down to the lot) → **total open risk** + new ≤ portfolio cap → concentration (position %, sector %, ALREADY_HELD, or `add` only if the policy allows and the total stays within the original budget) → daily and **weekly** loss (realised + unrealised, net) → drawdown → funding/margin → liquidity.

**Fail-closed rules:** any input an enabled check needs that is unknown → block with `<check>_unknown`, unless the policy names it as "reduce when unknown" (VIX or regime → apply the 0.5 factor). Change `DRAWDOWN_UNKNOWN`, `SECTOR_UNKNOWN`, `LIQUIDITY_UNKNOWN` from `info` (open) to block or reduce. A decision write that fails → 503 (as today). The flag must never weaken the kill switch: fix `positional_journal.py:315` now.

**Atomic reservation:** put the risk budget on the existing per-user `paper_accounts` document, which already has the proven conditional-`$inc` pattern. Add `open_risk_rs`, `open_positions`, `held_symbols[]`, `sector_rs.{sector}`. Reserve in **one** `update_one` whose filter encodes every budget (`cash−blocked ≥ notional`, `open_risk_rs ≤ cap − est`, `open_positions < max`, `held_symbols ≠ symbol`, `sector_rs.X ≤ cap − value`). Use `$inc` and `$addToSet` in the same write, so Mongo's single-document atomicity gives a race-free check-and-reserve. Store `reservation_id = decision_id` on the trade. Release on close, cancel or expiry, and compensate when the insert fails. Make the trade write itself idempotent: unique `(user_id, idempotency_key)` on `desk_paper_trades`, or route writes through `services/oms/orders.create_order`, which is already idempotent with a fingerprint.

**Capital basis configuration:** one per-user `risk_profile`. This can be fields on `paper_accounts` plus an audited setter modelled on `risk_controls.set_control` (reason required; tightening by the user, loosening by an admin):
`{capital_basis: "paper_equity" (default) | "fixed", capital_rs, per_trade_risk_pct: 1.0, max_open_risk_pct: e.g. 5, max_position_pct: 10, max_sector_pct: 30, daily_loss_pct: 3, weekly_loss_pct: e.g. 6, max_drawdown_pct: 15, min_rr: 1.5, gap_stress_pct, cost_model_ref, limits_version, set_by, set_at}`.
Equity = paper cash + net unrealised (from `risk_equity`). The AI trader's `initial_capital` should stop being an independent basis; at minimum, cap it at account equity. When the profile is absent, use the defaults with `stored: false` shown explicitly, as `risk_controls.default_state` does. Values marked "e.g." are product decisions. NEEDS-INPUT for the owner.

**Migration risks:**
1. Existing open trades without a reservation or open-risk entry (staging: 1 of 2) need a backfill from stored stop distances. Journal trades with `stop_loss=0` need notional as their risk.
2. Making drawdown fail-closed will block **every** user with an open F&O structure until strategy marks feed `risk_equity`. Sequence F&O marking first, or make "unknown drawdown" a reduce.
3. A new 409 or "reduce" on the desk breaks the current UI assumption that a POST with a valid body is 201. The frontend must render `approved_qty` and the reasons.
4. Existing duplicates (ICICIBANK ×2) are grandfathered.
5. Behaviour change on the AI path (the gate plus the governor) must keep the 202 governor tests green.
6. Rollout stays per user behind `fno_risk_gate` (rename it). Deploy needs a backend restart.

**Effort:** **M–L overall.**
- (a) Journal kill-switch fix, S.
- (b) Desk idempotency key, S.
- (c) Shared `risk_book` plus the governor inside the gate on all six paths, M.
- (d) Atomic risk reservation on `paper_accounts`, M.
- (e) Costs and gap stress in estimated risk, S–M.
- (f) Per-user risk profile plus an audited setter, M.
- (g) Open-risk and weekly limits, S each once (c)/(d) exist.

**Tests that would prove it:**
1. A route-inventory test, modelled on `test_order_path_guard`, that fails if any route writing `desk_paper_trades`, `trade_journal`, `ai_trader_tickets` or `oms_orders` does not call the decision service.
2. A parametrised matrix of six paths × each reason (kill switch, per-trade, open risk, sector, already held, daily, weekly, drawdown-unknown, stale data, funds) asserting a 409, **no trade written, no reservation**, and one `risk_decisions` row with reason, version and correlation id.
3. A real-Mongo concurrency test (the in-memory fakes cannot interleave): N concurrent entries, then assert Σ reserved risk ≤ cap and exactly k successes.
4. Idempotency: the same key twice gives one trade and one reservation.
5. Fail-closed: each input unreadable gives a block.
6. Golden tests for PRD Examples A–H (85/178/400/227 shares; Example F rejected at a ₹2,500 budget).
7. Net-of-cost and gap-stress assertions (probe P2/P3 values).
8. A staging E2E with a real session token, checked against `risk_decisions` and `paper_accounts` reads.

---

### Cross-area notes (for B and C)
- Desk entry is "assumed at the recorded price" with no check against the market (`services/desk_trading.py:98-99`, `ENTRY_RULE_TEXT["at_once"]`). The user-typed `entry_price` is accepted as is (lane B and C: data trust).
- The scenario calculator sizes on gross risk while showing net loss (`routes/positional.py:1711` qty from gross budget vs `outcomes.loss_at_stop_net`).
- The paper account ignores P&L of trades closed before it existed and of strategies closed with `None` P&L (Q9).
- `backend/tests/conftest.py` hard-codes default test tokens and account emails (`os.environ.setdefault("NIVESH_TEST_*_TOKEN", ...)`). This breaks the "secrets never touch code" rule. I did not reproduce the values here.
