# Functionality Test Cases — Desk "Top 5 by regime" (index options · stock F&O · cash)

- **Branch:** feat/desk-top5-regime-fit (worktree, off origin/dev @ 60e5ccb5)
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Status:** cases authored UP FRONT, after API + UI design, before implementation.

## The ask

User, verbatim: *"Now what we need is the top 5 best trading strategy for nifty/banknifty options
and stock f/o and cash stocks."* Placed inside the desk Strategy Builder
(`/v5/app/trader/desk?tab=more&view=strategy`).

User chose the ranking rule: **regime fit, priced live** (over reward:risk-only, backtested
performance, and extending the existing evidence score).

## What "best" means here — and what it does not

There is **no realised performance history in this platform to rank strategies by**. Verified on
staging this session: `public.strategy_trades` holds 151 closed trades from 3 manually-triggered
cash backtests (all three net-negative); `strategy_signals`, `positional_outcomes` and
`positional_backtest_labels` hold **0 rows**; there is no options performance record anywhere, and
no `iv_percentile` / `iv_rank` in the codebase.

So "top 5" ranks **fit to today's measured market conditions**, priced from the live chain. It is
explicitly NOT a forecast, NOT a probability, and NOT a performance ranking. Every response must
carry that sentence.

## Design — inputs (all real, all verified live this session)

| Input | Source | Verified value (2026-10-21) |
|---|---|---|
| Trend | `/api/macro/today` → `regime.inputs.trend` | `down` (Nifty 22,888.95 vs 50-sess avg 23,514.27, −2.66%) |
| Volatility | `regime.inputs.india_vix` + `regime.rule.vix_high` | 14.77 vs threshold 20.0 → `volatility_high: false` |
| Breadth | `regime.inputs.breadth` | `down` (544 adv / 2,318 decl, 19.0% advancing) |
| Regime key | `regime.key` (desk-regime-v1) | `bearish`, as of **2026-10-19** |
| Option chain | `/api/fno/{sym}/chain` | NIFTY 81 strikes, ATM IV 14.04, OI, ΔOI, Black-76 Greeks, PCR, max pain, expected move — as of **2026-10-21** |
| F&O eligibility | `nidp.security_reference_daily.fno_eligible` | used to gate stock F&O |
| Cash candidates | AI scanner merged setups + Chartink hits | existing `selection.py` / `picks.py` |

**Known staleness:** the regime is 2 sessions older than the chain. Surfaced in the response, not hidden.

## Design — the selection rule (`regime-fit-v1`)

Deterministic. Reuses the **existing** `desk-regime-v1` thresholds rather than inventing new ones.

Two axes from real inputs: **direction** (trend + breadth) × **volatility** (india_vix vs `vix_high`).

| Direction | Vol | Favoured structures (priced, then ranked) |
|---|---|---|
| down | low | bear put spread · long put · bear call spread · protective put · collar |
| down | high | bear call spread · collar · protective put · bear put spread · covered call |
| up | low | bull call spread · long call · covered call · cash long · protective put |
| up | high | bull put spread · covered call · collar · bull call spread · cash long |
| flat | high | iron condor · bear call spread · bull put spread · covered call · collar |
| flat | low | bull call spread · bear put spread · long call · long put · cash long |

Fit score per idea = weighted sum of real factor states (supports / neutral / conflicts), in the
same shape `picks.py` already uses for its 0–100 evidence score. Reward:risk is the tiebreaker.

## Design — API

`POST /api/desk/strategy/top5` — reads only, writes nothing.

Body (all optional): `{ "capital": 1000000, "classes": [...], "expiry": "YYYY-MM-DD", "per_class": 5 }`

Response: `{ schema, rules_version, generated_at, regime{...}, classes{ index_options, stock_fno, cash }, ranking_note, gaps[] }`
Each idea: `{ rank, underlying, class, structure, name, direction, expiry, legs[], max_loss, max_gain,
reward_risk, breakevens[], capital_required, net_greeks{}, fit{ score, because[] }, data_as_of{} }`

## Design — UI

Third mode in the desk Strategy Builder beside "From AI opportunities" / "One stock":
**"Top 5 by regime"**, with three labelled sections (Index options · Stock F&O · Cash stocks),
the regime strip at the top, and the ranking caveat printed under the heading.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Regime | Engine reads the live regime; trend/vix/breadth match `/api/macro/today` exactly | api | identical values, no re-derivation | |
| TC-2 | Regime | Regime source unreadable → endpoint returns 200 with `regime.available: false` and NO ideas invented | failure | degrades, never fabricates | |
| TC-3 | Regime | Response states the regime/chain date gap when they differ | api | staleness note present | |
| TC-4 | Rules | `regime-fit-v1` maps (down, low-vol) to the documented 5 structures | unit | table honoured | |
| TC-5 | Rules | Every one of the 6 (direction × vol) cells yields exactly 5 structure keys | unit | no empty cell | |
| TC-6 | Rules | Rules version string is carried on every response | unit | `regime-fit-v1` | |
| TC-7 | Index | `NIFTY` produces priced ideas (the blocker fixed) | api | ≥1 idea, no `unknown_symbol` | |
| TC-8 | Index | `BANKNIFTY` produces priced ideas | api | ≥1 idea | |
| TC-9 | Index | Index ideas never claim equity-only evidence (no ATR / candle patterns — index_eod is close-only) | unit | those factors absent, reason given | |
| TC-10 | Index | Index spot comes from the chain summary, not from `prices_eod_adjusted` | unit | correct source string | |
| TC-11 | Pricing | Each leg's price traces to a real chain row (strike, type, close/settle) | api | `price_source` names the bhavcopy date | |
| TC-12 | Pricing | `max_loss`, `max_gain`, `breakevens` agree with `payoff.py` for the same legs | unit | identical to existing engine | |
| TC-13 | Pricing | Debit structure `capital_required` = net debit; credit structure uses `margin.py` | unit | correct per structure | |
| TC-14 | Pricing | Net Greeks are the signed sum of leg Greeks from the chain | unit | matches chain | |
| TC-15 | Ranking | Ideas are ordered by fit score desc, reward:risk as tiebreaker | unit | stable order | |
| TC-16 | Ranking | `per_class` caps at 5 by default and is honoured when passed | api | exact count | |
| TC-17 | Ranking | Response carries the "not a forecast / not a probability / not performance-ranked" note | api | exact sentence present | |
| TC-18 | Stock F&O | Only `fno_eligible` symbols appear in the stock_fno class | api | gate honoured | |
| TC-19 | Stock F&O | A non-F&O stock requested explicitly is reported as unavailable with the existing NOT_FNO_TEXT reason | failure | named, not dropped | |
| TC-20 | Cash | Cash class reuses the existing scanner/Chartink selection, unchanged | api | same symbols as `/ideas` | |
| TC-21 | Gaps | Response lists the IV-percentile gap explicitly | api | gap text present | |
| TC-22 | Gaps | Response lists the no-performance-history gap explicitly | api | gap text present | |
| TC-23 | Chain | Expiry defaults to the nearest listed; an explicit expiry is honoured | api | correct expiry | |
| TC-24 | Chain | Chain unreadable for one underlying → that underlying listed under `unavailable`, others still returned | failure | partial success | |
| TC-25 | Auth | No session → 401 | failure | 401 | |
| TC-26 | Safety | No response field recommends an action (no "buy"/"sell" imperative) | unit | wording gate | |
| TC-27 | Safety | Nothing is written to any table by this endpoint | api (data) | row counts unchanged | |
| TC-28 | UI | "Top 5 by regime" mode renders three labelled sections | e2e | visible | |
| TC-29 | UI | Regime strip shows trend, VIX and breadth with their as-of date | e2e | visible | |
| TC-30 | UI | Each idea card shows max loss, max gain, breakeven and capital | e2e | visible | |
| TC-31 | UI | The ranking caveat is visible, not hidden behind a tooltip | e2e | visible on screen | |
| TC-32 | UI | A class with no ideas shows the reason, not an empty box | e2e | reason shown | |
| TC-33 | Typecheck | `tsc --noEmit` clean | unit | 0 errors | |

## API / Endpoint Tests (staging)
<!-- filled after implementation -->

## UI / Playwright Tests
<!-- filled after implementation -->

## Data Correctness
<!-- filled after implementation -->

## Verdict
<!-- pending -->
