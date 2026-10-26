# Test cases — AI scanner watchlist: F&O chain date gate, cron after the F&O ingest, board expiry rule

- **Date:** 2026-10-27 · **Branch:** `fix/watchlist-fno-chain-expiry` (worktree `/home/deploy/nivesh-watchlist-fix`, off
  `origin/dev` 5b6b3cfd)
- **Roles:** FULL_STACK_DEVELOPER + QA_ENGINEER (+ DOMAIN_EXPERT: data trust, "ideas" wording)
- Authored before implementation, after the design below.

## The defects (both verified before this branch)

1. **Stale F&O chain.** `scripts/build_ai_watchlist.py` runs at 20:15 IST (retry 22:15 with `--skip-if-done`). The NIDP
   F&O bhavcopy lands at 22:15 IST (`nidp.fno_bhavcopy` ingest 22:15:03–22:15:17 IST every day since 19 Oct). The 20:15
   run therefore builds the day's F&O half on the previous session's chain, and the store is insert-once, so the 22:15
   retry skips. The 26 Oct list is right only because it was built by hand at 23:44 IST.
2. **Expired contracts offered.** `regime_fit.build_top` takes the nearest listed expiry, and
   `routes/fno.live_option_expiries` lists an expiry on its own day (`days_to_expiry` 0). On a monthly-expiry day every
   F&O row expires that day (7 of 61 replayed sessions). 2026-10-27 is a monthly expiry.

## Design

**Job (`scripts/build_ai_watchlist.py`, `services/ai_watchlist_build.py`)**
- The list date is the session the job builds for (`--date`, default today IST). After the build and before any write,
  the F&O half's chain dates are checked: every chain day the board read (`notes.fno_chain_dates`: each option class's
  `as_of` and each idea's `data_as_of.chain`) must equal the list date, and there must be at least one.
- Otherwise the whole day is refused: nothing written, one log line naming the chain date(s) and the list date (or the
  board's unavailable reasons), **exit 4**. A later retry builds the day. `--dry-run` applies the same check (exit 4).
- Cash side unchanged.

**Cron (`deploy/nivesh-staging/ai-watchlist.cron`, repo file only, not installed)**
- 22:45 IST, retries 23:30 and 23:55, Mon–Fri, all `--skip-if-done`, each under `flock -n` (the job has no lock).

**Board (`services/strategy_plan/regime_fit.py`)**
- One constant `MIN_SESSIONS_TO_EXPIRY = 1`: an offered contract's expiry must be at least that many sessions after the
  chain's own day (1 = strictly after). Sessions are counted as weekdays; exchange holidays are not known here.
- Applied in the one place the board chooses an expiry (`_chain_for`): the nearest listed expiry that meets the rule is
  used; nearer expiries that fail it are recorded as skipped with the reason; with none qualifying the underlying is
  dropped (reported under `unavailable` with the reason). A requested `expiry` that fails the rule is refused the same
  way. The chain that comes back is checked again against its own `as_of` (the data can advance between the two reads).
- The rule is stated in `GAPS`. `REGIME_FIT_VERSION` moves to `regime-fit-v1.1 (2026-10-27)` so a stored day records
  which rule set built it.

## Backend cases (pytest, unit; no DB, DaaS, NSE or Kite — every outside call is stubbed)

### Job

| ID | Case | Expected |
|----|------|----------|
| J-1 | chain date = list date | built, stored once, exit 0 |
| J-2 | chain date = previous session | exit 4, nothing written, log names both dates |
| J-3 | board read no chain at all (every underlying unavailable / regime unavailable) | exit 4, nothing written, log carries the reasons |
| J-4 | mixed chain dates (one idea from the previous session) | exit 4, nothing written |
| J-5 | retry after the chain arrives: run 1 stale → 4; run 2 fresh → stored; run 3 `--skip-if-done` | 4, then 0 with one insert, then 0 with no build |
| J-6 | `--skip-if-done` with the day stored | nothing built, exit 0 (existing B-5) |
| J-7 | `--dry-run` with a stale chain / a fresh chain | exit 4 / exit 0; nothing written either way |
| J-8 | `shape_day` records every chain day in `notes.fno_chain_dates`; cash entries unchanged | as stated; existing B-7 cases pass |

### Board

| ID | Case | Expected |
|----|------|----------|
| E-1 | `sessions_to_expiry`: same day, earlier, next weekday, Fri→Mon, Thu→next Tue | 0, 0, 1, 1, 3 |
| E-2 | chain dated an expiry day (listed: that day, next week) | the chain read is for next week's expiry, never the chain day's |
| E-3 | the next listed expiry is used | idea `expiry` = next expiry; the skipped expiry is recorded with its reason |
| E-4 | no listed expiry qualifies | `_chain_for` raises; `ideas_for_underlying` → unavailable with the reason; `build_top` lists it under `unavailable`, no row |
| E-5 | requested `expiry` on the chain day | refused with the reason, no chain read for it |
| E-6 | chain read answers for a later day than the listing (data advanced) and its expiry fails the rule | refused |
| E-7 | `MIN_SESSIONS_TO_EXPIRY` raised to 2 | an expiry one session out is skipped too |
| E-8 | `GAPS` states the expiry rule; nothing in the module's notes tells anyone to trade | as stated (existing TC-17/21/22/26 pass) |

### Existing suites (must still pass)

`tests/test_regime_fit.py`, `tests/test_regime_fit_distinct.py`, `tests/test_ai_watchlist.py`,
`tests/test_strategy_ideas.py`, `tests/test_fno_routes.py` (the expiry listing is unchanged).

### Cron (static; not installed)

| ID | Case | Expected |
|----|------|----------|
| C-1 | the file's job lines | exactly three, at 22:45, 23:30, 23:55, `1-5`, each `flock -n` + `--skip-if-done` |

## Staging proof (read-only: no writes, no install)

| ID | Case | Expected |
|----|------|----------|
| S-1 | the stored 2026-10-26 list | its chain date and every F&O expiry; all expiries after 2026-10-26 |
| S-2 | the new board replayed in memory against the live chain (2026-10-26) | no offered contract (lead or alternative) expires on or before the chain date; the job gate passes for list date 2026-10-26 and refuses list date 2026-10-27 |
| S-3 | chain 2026-10-27 | only if the 27 Oct F&O bhavcopy is in the warehouse (it lands at 22:15 IST); otherwise stated as not yet available |

Frontend: no frontend file changes. The desk board specs (`copilot-app-desk-strategy-top.spec.ts`,
`copilot-app-desk-top10.spec.ts`) stub the API from fixtures, so they do not see this change; they are run only if a
fixture or asserted expiry text has to change.
