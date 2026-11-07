# Autonomous AI Paper Trading Desk — how the AI bots work, end to end

Written 7 Nov 2026 for the owner and anyone new to the desk. It is a high-level map. Detail lives in `DESIGN.md` (Phase 1), `PHASE2_DESIGN.md` (paper execution), `source/PRD_v2.0.md` and `source/TECH_ARCH_v1.0.md`.
Every statement about status is taken from `STATUS.md` and the design docs on 7 Nov; it is not re-tested here.

## 1. The idea in one paragraph

Five software "bots" (agents) run a trading desk on **paper money**. Each session, one bot checks the data is fit to use, one scans the market for signals, one builds a trade plan, one checks the plan against hard risk rules, and one decides whether the plan may go ahead. If it may, a paper execution engine reserves capital, fills the order at a simulated or live-quote price, and tracks the position. **The AI proposes; code decides.** Nothing in the system can place a real broker order. Zerodha is used for live quotes only, read-only.

## 2. The five bots and what each one is allowed to do

| Bot | Job | Output | Cannot do |
|---|---|---|---|
| **Tech Support** | Pre-market health check: is yesterday's cash and F&O data present and fresh, is the data API up, is the desk DB up | READY / DEGRADED (cash only) / BLOCKED (no new risk) | Trade or score |
| **AI Trader** | Scan the universe (F&O, Nifty 500, Total Market) for breakouts, trend, momentum, unusual volume/delivery, OI build-up, index trend | Ranked **signals**, score 0–100 on 8 dimensions | Size or place anything. A score is not a probability |
| **Trading Assistant** | Turn a signal into alternative structures (cash, futures, options, spreads), rank them, pick the best, revise when risk objects | A 19-field **trade plan**, or NO_TRADE with reasons | Override the risk engine |
| **Risk & Operations** | Run the deterministic risk engine on the exact plan version against the account book | PASS / REDUCE (smaller size passes) / FAIL | Be voted away: a hard FAIL is final |
| **Middle Office** | Apply the approval policy, bind the scope (account, instrument, max lots/notional/risk, expiry) | APPROVED / NEEDS_HUMAN_APPROVAL / REJECTED | Approve outside policy |

In Phase 1 all five are deterministic code. Language-model narration is a later, flag-gated addition (owner question still open: which provider).

## 3. The daily workflow

```
 PREMARKET 08:30   Tech Support: data check ──── BLOCKED ──► stop, no new risk
        │ READY / DEGRADED
 SCAN 08:45        AI Trader: scan universe on the previous session's data ► signals (score ≥ min, one per instrument, top N)
        │
 PROPOSALS 09:00   for each signal, a TRADE_PROPOSAL:
        │            Trading Assistant ► plan ──► Risk & Ops ► assessment
        │                 ▲                          │ FAIL / REDUCE
        │                 └──── revise (max 2) ◄─────┘
        │            still failing ► NO_TRADE
        │            PASS ► Middle Office
        │                     ├─ AUTONOMOUS_PAPER inside the rules ► APPROVED
        │                     ├─ ASSISTED, or outside the rules ► waits for a person
        │                     └─ otherwise ► REJECTED
 OPEN 09:15        Execution gateway: controls ► reserve capital ► paper order ► fill ► position
 CLOSE 15:30       unfilled orders expire, reservation released, positions marked, equity snapshot written
 EOD 18:00         unused signals and unanswered approvals expire; journal and P&L complete
```

Every step is a persisted **task** (created → assigned → running → validated → completed) with a deadline, bounded retries and a handoff record. State lives in Postgres schema `autodesk`; the event log is append-only, so any decision can be replayed and audited.

Account modes: **RESEARCH** (plans are never executed), **ASSISTED** (a person approves each plan), **AUTONOMOUS_PAPER** (auto-approve inside policy). Default autonomy rule: risk ≤ 0.5 % of equity and signal score ≥ 70.

## 4. Where the bots get their judgment

**Signals and scoring.** Scoring **v1 is the only ACTIVE version** and must not change. **v2 and v2.1 run in shadow**: every signal carries all three scores, the screens label the shadow ones "not used for selection", and nothing is promoted until live scores confirm it. The universe is today's index members, with a survivorship caveat stated in results (no membership history).

**No look-ahead.** Agents read through a point-in-time market view. Cash data for session *d* is visible from 19:30 IST, F&O from 22:45 IST. A read of later data raises `LookAheadError`, and every read is stored on the task so it can be proved afterwards.

**Risk engine (`autodesk-risk-v1`).** Checks include data freshness, account active, strategy and segment allowed, defined risk only (no naked short options), contract expiry, liquidity, per-trade risk ≤ 0.5 % of equity, reward:risk ≥ 1.5, position ≤ 10 %, open risk ≤ 3 %, sector ≤ 25 %, margin ≤ 25 %. Daily loss, weekly loss and drawdown checks go live once P&L exists (Phase 3). Every check, input and version is stored.

## 5. From approved plan to paper position (Phase 2)

1. **Execution intent** is saved first, bound to the exact trade, plan version, plan hash and approval. A repeat request with the same key returns the same intent.
2. **Controls** run and are stored with their results: account active, mode allowed, policy and plan unchanged since the risk check, approval valid and in scope, lot size, tick, price collar, entries not stopped.
3. **Capital reservation** takes a row lock on the account, so two proposals cannot spend the same free funds. Funds come from an append-only **ledger**; balances are derived, never edited.
4. **Orders** are made per plan leg. Multi-leg plans are all-or-none at a net limit.
5. **Fill model.**
   - *Simulation:* priced from the session's daily bar with spread, seeded slippage, 10 % volume cap, latency and rejection rules. The fill engine sees only the open at 09:15; a resting limit fills at the close only if price traded through it. The same seed gives identical fills.
   - *Live desk:* priced from a live Zerodha quote only. A missing, stale (over 120 s) or not-today quote means **no fill**; the order waits and retries. It never fills at an old price.
6. **Position, charges and journal.** Fills create a position, book costs, and write the chain signal → plan → risk → approval → intent → reservation → order → fill → position → mark. Every fill is labelled simulated (`broker_confirmed: false`).

## 6. Phases and who builds them

| Phase | Adds | Owner | Status on 7 Nov (from STATUS.md) |
|---|---|---|---|
| 1 | Five agents, risk engine, workflows, simulator, APIs | Account 1 | Merged (PR #499 merged for the desk fixes on top) |
| Scoring v2.1 + wider universe (package 5 A+C) | Shadow scores, Nifty 500 and Total Market scan | Account 2 | Branch pushed; Account 1 reviewing and opening the PR |
| Shadow scores on screens (package 5 B) | Scanner and Studio labels | Account 2 | Branch pushed, no PR yet |
| 2 Paper execution | Ledger, reservation, orders, fills, positions, journal | Account 1, taken over by Account 2 when Account 1's limit ran out | **IN PROGRESS** (branch `feat/autodesk-phase2-paper-exec-a2`; not verified) |
| 3 Lifecycle | Stops, targets, trailing, partial exits, loss and drawdown limits, scenarios, run comparison | Account 1 | Not started |
| 4 Live shadow | Live Kite feed view, hypothetical book, outcome comparison; no order capability | Account 1 | Not started |
| Screens (package 4) | Six remaining screens plus Studio P&L, positions, scenarios | Account 2 | Waits for the Phase 2 and 3 APIs |
| Early-movers re-test (package 6) | Study, docs only | Account 3 | Idle until its weekly limit resets |

Merge order: package 1 → Phase 2 → Phase 3 → Phase 4. Each package is its own PR to `dev`; Account 1 reviews and opens PRs; the owner merges.

## 7. Hard rules that cut across everything

- No order placement code of any kind (`backend/tests/test_order_path_guard.py`). Gateway verbs are submit / amend / withdraw.
- No stale market data; no look-ahead in simulations.
- Paper fills are always labelled simulated.
- Agent-written narrative avoids advice words (buy, sell, stop loss, target, entry, exit, recommend, pick and similar). API field names may use standard trading words.
- Test cases are written before code, and nothing is called done without real command output.

## 8. Open points

- Owner decisions still on defaults: first-release strategy list, autonomy thresholds, default limits, LLM provider, screen wording, app URL (`DESIGN.md` §10).
- What a daily bar cannot show: queue position, intraday timing of resting fills, basket simultaneity. Fill results state these limits.
- The Total Market scan timing (64.6 s for 754 names) was measured once on real data; a full multi-session replay has not been done.

## 9. The complete logical workflow (all phases built)

This is the end state: Phases 1–4 done. Today only Phase 1 is merged and Phase 2 is in progress; Phase 3 items (the lifecycle manager, loss limits, scenarios) and Phase 4 (live shadow) are from the PRD (§8, §12, §13) and `DESIGN.md` §7 and are **not built yet**. Words here are neutral; API fields keep the PRD names.

### 9.1 One picture

```
 ┌──────────────────────────── CONTROL PLANE (policy, limits, modes, emergency controls) ────────────────────────────┐
 │                                                                                                                    │
 │  DATA ──► [1 Tech Support] ──► [2 AI Trader] ──► [3 Trading Assistant] ──► [4 Risk & Ops] ──► [5 Middle Office]   │
 │  health      READY?            signals (v1)       trade plan v1..vN         PASS/REDUCE/FAIL    approve / human   │
 │                                shadow v2, v2.1         ▲                         │                    │           │
 │                                                       └──── revise (≤2) ◄───────┘                    ▼           │
 │                                                                                         EXECUTION GATEWAY          │
 │                                                                       controls ► capital reservation ► orders      │
 │                                                                                         │                          │
 │                                              SIMULATION: daily-bar fills   │   LIVE DESK: fresh Kite quote fills   │
 │                                                                                         ▼                          │
 │                                                                              POSITION (opens on fills only)       │
 │                                                                                         ▼                          │
 │                                         TRADE LIFECYCLE MANAGER (rules, no AI): monitor ► protect ► reduce ► close │
 │                                                                                         ▼                          │
 │                                       LEDGER ► P&L ► JOURNAL ► PERFORMANCE ANALYTICS ► LEARNING (versioned, shadow) │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
        LIVE SHADOW: the same chain on the live Kite feed with a hypothetical book and no order capability
```

### 9.2 Stages in order

| # | Stage | Who | Logic | Output |
|---|---|---|---|---|
| 1 | **Configure** | Owner / admin | Set account mode, policy version, risk limits, allowed strategies. Tightening is free; loosening needs an admin | Versioned policy, account |
| 2 | **Prepare** | Tech Support | Check last session's data, data API, desk DB | READY / DEGRADED / BLOCKED |
| 3 | **Find** | AI Trader | Scan the universe, score, dedupe, keep top N above the minimum | Signals with evidence; v1 active, v2/v2.1 shadow |
| 4 | **Plan** | Trading Assistant | Build alternatives, rank, choose; or say NO_TRADE | Plan with reason, levels, size, max loss |
| 5 | **Check** | Risk & Ops | Hard rules, no override. Daily loss, weekly loss and drawdown now live | PASS / REDUCE / FAIL, stored |
| 6 | **Decide** | Middle Office | Policy match; bind scope and expiry; person decides if outside policy | APPROVED / WAITING_HUMAN / REJECTED |
| 7 | **Authorize and reserve** | Gateway + capital engine | Exact version and hash match, mode, stop switches; atomic reservation | Intent, reservation, orders |
| 8 | **Fill** | Paper adapter | Simulation from the session bar, live desk from a fresh quote only; partial fills, rejections, costs | Fills labelled simulated |
| 9 | **Activate** | Lifecycle manager | Starts only on confirmed fills, with the filled quantity and average price. Sets the protective level | ACTIVE position |
| 10 | **Monitor** | Lifecycle manager | Price, P&L, protective and profit levels, trailing state, margin, data freshness, expiry, event by event | Marks, alerts |
| 11 | **Act** | Lifecycle manager | Rule-based: close the remainder at the protective level, partial close at the first profit level, close more at the second, tighten the trailing level. Never widens the original loss limit, adds size or adds leverage without fresh approval | Close orders, realized P&L |
| 12 | **Protect the desk** | Control plane | Daily loss limit blocks new risk; drawdown limit suspends trading and escalates; emergency stop-new-entries switch | Suspended or blocked state |
| 13 | **Settle** | Ledger | Release reservation and margin, book fees, settle expiries, reconcile | Position CLOSED / SETTLED |
| 14 | **Record** | Journal | Signal → plan versions → risk → approval → intent → orders → fills → position events → closes → final P&L | Complete audit chain |
| 15 | **Measure** | Analytics | Win rate, expectancy, profit factor, drawdown, realized reward:risk, return on risk, slippage, charges, signal-to-trade conversion | Performance views |
| 16 | **Learn** | Research | Propose scoring or parameter changes; they run in shadow, get historical and out-of-sample checks, and need owner approval before any change to live rules | Versioned change proposals |

### 9.3 Three kinds of run, same chain

| Run type | Data | Fills | Purpose |
|---|---|---|---|
| **Historical replay / accelerated replay** (simulation) | Past sessions, no look-ahead | Daily-bar model, seeded, reproducible (fingerprint) | Test strategies and agent versions |
| **Scenario** (Phase 3) | Replay plus injected events: gap, volatility spike, partial fill, leg rejected, stale data, agent timeout | As above | Prove the desk behaves under stress |
| **Live desk / live shadow** | Today's data; Kite live quotes only | Paper fills from fresh quotes; live shadow keeps a hypothetical book and compares outcomes | Run alongside the market with no order capability |

Run comparison (Phase 3) sets two runs side by side on the same sessions: versions, P&L, drawdown, fill ratio, rejections.

### 9.4 Rules that hold at every stage

- **AI proposes, code decides.** Agents produce plans; only deterministic code approves, reserves, fills and closes.
- **Nothing real moves.** No order-placement code exists; Zerodha is read-only quotes.
- **Exact version binding.** An approval covers one plan version and hash; any change needs a new check and approval.
- **Capital is a ledger.** Balances are derived from append-only entries, never edited; equity must equal cash plus position value.
- **Failures stop, not guess.** A stale or missing quote means no fill; blocked data means no new risk; an unknown order state is reconciled, never retried blindly.
- **Everything is traceable.** Each decision stores its inputs, policy version, agent version and the data it read.
- **Restart safe.** Active positions, orders and pending actions are recovered from durable state and reconciled before anything resumes.
