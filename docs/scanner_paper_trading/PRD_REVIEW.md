# Review: Scanner-to-Paper Trading PRD + Workflow against the code (5 Nov 2026, 02:30 IST)

**Inputs**
- the PRD (`docs/prd/Nivesh_Scanner_Paper_Trading_Capital_Allocation_Risk_Management_PRD.md`)
- the Workflow (`docs/prd/Nivesh_Scanner_to_Paper_Trading_Workflow.md`)
- the code map (`EXISTING_CODE_MAP.md`), read from `origin/dev` 74ec45d6
- 4 Nov's real scan signals

## Verdict

The owner is right that most of the core is already in place. **The accounting and risk core is about 60% built** and
mandatory today:
- a universal risk service with per-trade, open-risk, exposure, sector, daily/weekly loss and drawdown checks
- an atomic paper ledger with risk reservations, an equity peak and reconciliation
- a kill switch, per-user limits, a regime classifier, the cost card, and exit rules with an ATR trail and a trend exit
- a real-time P&L dashboard over SSE

What is **new** is everything between the scanner and the ledger, plus a realistic order model:
- signals are persisted and normalised, then consolidated into one opportunity per stock
- each opportunity is validated with an explainable opportunity score, and proposals are generated from it
- account modes: auto / approval / tracking
- orders separate from fills and positions, with partial fills and partial exits
- bid/ask execution
- live exits for these positions
- signal-outcome and per-scanner analytics

All of this is being built overnight in three slices (`DESIGN.md`).

## Section by section

| PRD / Workflow | Have | Change | New (tonight unless marked) |
|---|---|---|---|
| §6 / WF §4 Signal ingestion | Signals recorded in Redis (list entries + strong ≥ 70 with a frozen plan) | — | Persisted immutable events in `spt_signal_events` with PRD §6.2 fields, quarantine on bad input, idempotent; hook in the scan loop; backfill (4 Nov archived; **3 Nov already expired**) |
| §6.3–6.4 / WF §5 Normalise + consolidate | — | — | Map of the 31 lists → category / family / horizon / direction; one opportunity per stock + direction + horizon + window; conflicting signals kept; scores never summed |
| §6.5 Three scores | Scanner score 0–100 (rule-based) | — | Opportunity score (explainable, versioned, "not a probability"); outcome probability = **later**, only after forward-testing evidence |
| §7.3 / WF §6 Validation | Regime classifier (desk-regime-v1), indicators, ADV, sector, OI build-up | — | Validation record + decisions QUALIFIED / CONDITIONAL / WATCHLIST / REJECTED / EXPIRED / DATA_INSUFFICIENT |
| §7.1 / WF §7 Trade proposal | scan-plan-v3 (2 × ATR stop, 2R / 4R, trend exit); strategy planner for F&O | Entry type by the price vs the plan (immediate or a limit pullback); never widen the stop to fit a size | Per-account proposals, expiry, R:R at the actual entry; F&O proposals = **P1** |
| §8.4 / WF §8 Sizing | Risk-first sizing with costs (`max_units_within_budget`, scenario route) | Liquidity cap and reserve bucket added | Stored inputs / steps / outputs + version |
| §8.6–8.8 / WF §9, §18 Allocation | Available cash, open-risk counters, sector counters on the account | — | Category buckets (45/25/20/10), ranking of competing opportunities, max new per day; optimiser = **P2** |
| §9 / WF §10 Risk engine | Universal risk service (allow / reduce / block, recorded before the write, replayable); limits from the risk profile | New path `spt_entry`; decisions mapped to PRD codes | Drawdown ladder (2/4/6%), stressed risk, max positions, min R:R per strategy, kill-switch state view; correlation stays **skipped** (P1) |
| §9.5–9.7 Daily / weekly loss, drawdown | Yes (risk service, risk book, equity peak) | — | Ladder states |
| §10 F&O risk | Defined-risk gate, Black-76 Greeks per group, the margin calculator | — | **P1**: F&O proposals, legging, portfolio Greeks, scenario grid |
| §11 / WF §12 Paper engine | One-document trades, end-of-day fills, no partial fills; live exits only for Market Recovery trades | — | Orders / fills / positions, partial fills from depth, bid/ask fills, DAY/GTD expiry, never a fill from a stale quote, restart-safe |
| §11.6 / WF §13–14 Stops, targets, modifications | Stop / target / time, opt-in ATR trail and trend exit, audited level changes | — | T1 partial exit + breakeven stop, live stop/target monitor, modification workflow with re-risk for increases, exits always allowed |
| §12 Dashboard | P&L dashboard (paper + live) | Show SPT positions on it (**follow-up**) | APIs carry the PRD §12 / §19 data; **screens wait for the owner's design** |
| §13 Analytics | Win rate, profit factor and drawdown on the P&L dashboard; backtest Sharpe/Sortino | — | Signal outcomes T+1/5/10/20, MFE/MAE, per-scanner report (P1 tonight); trade outcomes on close (P1); evidence policy = later |
| §14.3 Point in time | Strong signals freeze score, parts and plan | Persist them (Redis expires) | Every decision stores its inputs and versions |
| §15 Libraries | numpy, pandas | — | None needed for P0; riskfolio / cvxpy / quantstats / vectorbt / QuantLib = **P2**, not installed |
| §16 Database | Mongo for all paper/risk state; app Postgres for strategy-builder data | **Deviation: Mongo (D1)** | `spt_*` collections behind store modules |
| §17 APIs | `/api/desk/...` | — | `/api/v1/...` per §17.1–17.5; SSE instead of WebSockets |
| §20 Alerts | In-app only (desk alerts, exit watch, P&L alerts) | — | Events for every state change; outbound channels blocked (no SMTP/Telegram configured) |
| §21 Governance | Decisions recorded and replayable; the risk engine imports no AI code | — | Event log with idempotency keys |

## Blockers and decisions for the owner

1. **Storage: Mongo vs PostgreSQL** (PRD §16). The build uses Mongo, because the ledger, reservations and risk decisions it
   must update together already live there and staging Mongo has no multi-document transactions. Moving to Postgres
   later touches one store module per slice. *Confirm, or ask for Postgres.*
2. **Signal history is being lost every day until slice A is deployed.** Redis keeps 3 days; 3 Nov is gone, and 4 Nov is
   archived to `/home/deploy/nivesh-signal-archive/` (expires from Redis ~7 Nov 09:00).
3. **The morning Kite login drives everything real-time.** Live fills, depth, live exits and the margin calculator all
   need the admin Kite login each day. The token-alert job has no working channel on staging: SMTP and Telegram are
   unset, so the reminder never sends. Without the login, orders stay PENDING and exits wait. *Provide an SMTP or
   Telegram channel, or log in each morning.*
4. **Point-in-time fundamentals.** `stock_fundamental_values` keeps only the latest value, so backtests of past signals
   can use fundamentals that were not known then. Going forward each signal stores the inputs it was scored on. A daily
   fundamentals snapshot is needed for history.
5. **Intraday data.** No intraday bars are stored (the collector exists but is not scheduled), and the TrueData sandbox
   WebSocket login ended 5 Nov. The intraday persona and the 15m/5m lists stay "tracked, not traded" until a stored
   source exists.
6. **Adjusted prices on staging are unconfirmed.** The adjusted endpoint returned 0 rows on 4 Nov, and `fetch_bars` is
   unadjusted (the HDFCAMC 1:1 bonus). The build uses a series-break guard; a staging adjuster run would remove the need.
7. **Screens.** The PRD §19 navigation (Trading › Overview / Scanner Opportunities / Paper Trading / Capital Allocation /
   Risk / Analytics / Configuration) overlaps the Trader workspace (Market Overview / Trade Desk / Market Desk / Risk
   Desk), and the Paper Lab UI is on hold for the owner's own design. *Decide placement or send the design.* The APIs are
   ready for either.
8. **Compliance wording.** A "Scanner Opportunities" screen that shows entry, stop loss, targets and a suggested quantity
   to users reads as research advice (SEBI RA). Plan words are approved today only on the Scan dashboard and the P&L
   dashboard. *Decide the wording before the screen ships*; the paper APIs are scoped to the user's own paper account.
9. **The PRD's own conflicts:**
   - §10.1 lists **Call/Put Ratio Spreads**, which carry a naked short leg. That conflicts with §10.3 ("disabled by
     default") and with the live defined-risk gate. *Remove them or mark them "authorization required".*
   - §8.2 `Equity = Cash + Realized P&L + Unrealized P&L` double-counts realised P&L if cash already includes it. The
     build uses equity = cash + market value of open positions.
   - §9.2 planned risk uses the entry; the build also reports risk from the current price to the current stop, which is
     the risk still open after a trail.
10. **Limit defaults differ.** PRD §26 vs the owner's current `risk_profile` defaults:

    | limit | PRD §26 | risk_profile |
    |---|---|---|
    | daily loss | 1.5% | 2% |
    | weekly loss | 3% | 4% |
    | drawdown halt | 6% | 10% |
    | min R:R | 2 | 1.5 |

    The build keeps the `risk_profile` as the authority and adds the PRD's ladder and min R:R as SPT extras, so SPT halts
    new entries at 6% before the profile's 10%. *Confirm.*
11. **Approval vs auto.** PRD §26 says approval initially, so every user starts in mode `off` and opts in. Auto mode books
    paper trades unattended; this PRD now allows that (Mode B), unlike the 27 Oct DCARE PRD §16.
12. **Four paper paths will coexist:** the manual desk, the AI trader, Market Recovery, and SPT. *Plan to converge them*:
    show SPT on the P&L dashboard, and route the AI trader through SPT.
13. **App VM disk:** 7.0 GB free, and a deploy needs 6 GB. Older worktrees hold root-owned test files that only a sudo
    cleanup can remove. *Owner OK needed.*
14. **CI:** PR #483's CI was cancelled by the 4 Nov GitHub Actions outage, and the token cannot re-run it.

## Real numbers that shape allocation (4 Nov)

- **Volume:** 2,281 list entries and 86 strong signals. All 86 arrived after 14:45, because the score went live at 14:42;
  5 Nov is the first full day.
- **Stop distance:** a median 5.7% of the entry (range 3.8–11.6%). At 0.5% risk per trade, a cash position is about 9% of
  capital, so **capital, not risk, binds first**: about 10 positions fill ₹10 lakh.
- **Consequence:** ranking and the max-new-per-day cap matter more than the risk-% knob.
