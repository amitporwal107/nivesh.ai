# Functionality verification — Signals Phase 1 contract (§36), and the 2A/4A gap analysis

Date: 2026-09-23
Scope: `research/charting/signal_contract.py`, its tests, `docs/charting_2a_4a_backend_gap_analysis.md`,
and amendments to both PRD bodies.

## What the owner asked, and what was actually blocking

Asked: get the backend working for 2A (Signals & Alerts) and 4A (Paper Trading), and say what is
missing. Reading both PRDs, §38.19 Amendment E and the code they name produced a different picture
than the "not built" labels suggested.

**Far more is built than expected.** `research/charting/states.py` already derives the lifecycle;
`research/charting/events/` (2,367 lines) already implements the event dataset schema, versioning,
entry-at-next-open outcomes, the AMBIGUOUS rule, the stop/target/R framework and the cost bridge.
The execution mathematics 4A describes is largely written; it is not exposed.

**The real blockers are decisions, not code** — three of four:

1. Study plan v2 is **"Status: DRAFT — awaiting owner approval"** and has never reported. Amendment E
   gates signals Phases 2–6 *and all of paper trading* on "after study plan v2 reports".
2. SEBI RA/IA (NI-1a) unanswered → entry/stop/targets stay owner-allowlist-only.
3. The 0–100 headline score was removed by Amendment E but still lived in both PRD bodies.
4. Live push infrastructure (per-bar loop, WebSocket/SSE) does not exist.

**One assumed blocker was disproved.** I had intraday market data down as a hard blocker. Measured
with the owner-supplied Kite token:

```
15minute  requested 200d ->  3338 bars | first 2026-03-09 09:15 | last 2026-09-23 15:00 IST
60minute  requested 400d ->  1854 bars | first 2025-08-20 09:15 | last 2026-09-23 14:15 IST
5minute   requested 100d ->  5139 bars | first 2026-06-16 09:15 | last 2026-09-23 15:10 IST
day       requested 400d ->   272 bars
```

All three §17 timeframes are obtainable with 6–13 months of history. Captured for all 50 snapshot
symbols before the token expired: `research/kite_history/intraday_20260923/` — **166,974** 15-minute
and **92,774** 60-minute bars, 50/50 symbols, 0 failures, 15 MB, with a MANIFEST.json. Not committed
(research data, not source).

What intraday data does **not** fix: a Kite access token expires ~06:00 IST and renewing it needs a
manual owner login (headless login is against Zerodha's terms, already a recorded project
constraint). So "live" means batch replay refreshed per login, not always-on — which is what
Amendment E already says: *"The first live version is end-of-day daily signals from the batch replay."*

## Owner decisions taken this session

- **v2 gate:** build Phase 1 contract only. Nothing else until a gate is cleared.
- **0–100 score:** strike it from both PRD bodies, not just override it in the filing headers.

## What was built — Phase 1 only

Amendment E position 1, verbatim: *"Only Phase 1 (§36: the signal contract, schema, versioning,
timestamp semantics, and the lifecycle mapping below) may be written now."* All six §36 Phase 1 items
are in one module, `research/charting/signal_contract.py` (273 lines), following the
`indicator_catalogue.py` pattern already established in this repo: declarations plus pure validators,
versioned, content-hashed, computing and reading nothing.

- **States** — 8. The first six are exactly `states.RESEARCH_STATES`; `NOT_TRIGGERED` and
  `INCONCLUSIVE` come from owner decision #110.
- **Transitions** — a table plus `validate_transition()`. Forward-only; terminal states cannot be
  left; same-state is rejected so the audit trail cannot fill with non-events.
- **Signal schema / alert schema** — field-by-field, with §16's dedupe key
  (`symbol + timeframe + pattern + state + bar`) as a function.
- **Versioning** — `CONTRACT_VERSION` + `contract_hash()`.
- **Timestamp semantics** — `bar_time < known_at <= published_at`, enforced. This is the look-ahead
  guard: a bar is known at its **close**, never its open.

Amendment E's two removals are enforced by the contract rather than left to discipline:
`SIGNAL_FIELDS` has `score_components` and **no** `score`; `entry`/`stop`/`targets` are reserved but
listed in `OWNER_ONLY_FIELDS` so a serving layer strips them without guessing.

### A real gap found and recorded, not bridged

`states.derive_research_state()` returns `None` for lifecycle INVALIDATED / EXPIRED / DATA_BLOCKED /
UNRESOLVED, with a comment saying it is "pending an owner decision on two extra states". **That
decision was since made** (#110, in `CHARTING_NI3_PREDICATES_V1.md` §1.2). So this contract declares
8 states while `states.py` produces 6 and `None` for the rest. Closing it is Phase 2 (the
pattern→signal adapter). `states.py` is production research code with its own tests and was not
touched.

Related: Amendment E's own mapping table lists PRD `INVALIDATED` against "INVALIDATED or
FAILED_BREAKOUT … must not be merged". `prd_state("INVALIDATED")` therefore **raises**, explaining
that invalidation before a breakout is `NOT_TRIGGERED` and a failed confirmed breakout is
`FAILED_BREAKOUT`, rather than silently picking one and merging them.

## Test cases

| # | Case | Expectation |
|---|---|---|
| states | contract states agree with `states.py`, no fork | extra states are exactly the two #110 ones |
| transitions | table is closed, terminal states have no successors, no backwards edge | enforced structurally |
| transitions | EARLY_SIGNAL cannot jump to CONFIRMED_BREAKOUT | an unconfirmed pattern is never a breakout |
| mapping | PRD words map correctly; `INVALIDATED` raises | the two states are not merged |
| mapping | RETEST / CONTINUATION are events, not states | absent from SIGNAL_STATES |
| Amendment E | no `score` / `signal_score` field | only `score_components` |
| Amendment E | entry/stop/targets reserved AND owner-only | present in both dicts |
| timestamps | valid ordering passes | — |
| timestamps | known_at == bar_time rejected | the look-ahead guard |
| timestamps | published_at < known_at rejected | cannot publish before knowing |
| alerts | dedupe key stable per bar, separates timeframe and bar | §16 |
| versioning | hash deterministic, 64 chars; JSON round-trips | — |

## Real output

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/test_signal_contract.py -q
...........................                                              [100%]
27 passed in 0.45s
```

Full research suite, to confirm nothing else moved:
```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/ -q
1069 passed, 2 warnings in 90.57s (0:01:30)
```

## PRD amendments (owner decision 2)

- Alerts §12 "Signal Score" → "Signal Components": headline number removed; retest quality and
  risk/reward marked out of any live weighting (Amendment E); §18 example box and the §28 "Minimum
  signal score" preference filter removed, since they filtered on a number that no longer exists.
- Paper §16 `signal_score` → `signal_components`; §23 and §28 displays show components.
- Both carry a dated in-body note pointing at Amendment E; original text is in git history.

## Not done — and why

Phases 2–6, the alert engine, any `/api/signals` or `/api/alerts` endpoint, and all of 4A. Every one
is gated on study plan v2 reporting, which has not happened. Building them now would produce results
that cannot be reconciled with a v2 that has not run — the exact failure Amendment E is written to
prevent.

## Verdict: PASS
