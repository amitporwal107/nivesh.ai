# Ten-Percent Days research — project status, 19 Sep 2026 (13:15 IST)

Page: https://claude.ai/artifact/9AzQETCUUbVW7DzXKEuQFr (private until shared) · branch `feat/paper-trade-engine`
(local only)

**Overall: the research machinery works; no trading edge has been found yet.** Today's data-timing audit is committed
and needs two sign-offs from the owner. The next study, positional trades held up to 5 sessions, is agreed and is next
to be drafted.

| Complete | Waiting on owner | Next up | Blocked / constrained | Concerns |
|---|---|---|---|---|
| 7 | 8 | 2 | 6 | 8 |

## Complete (committed)

| Work | Result | Commit |
|---|---|---|
| H-B sealed test (buy gap-downs after 09:45) | **FAIL**: −0.40% per session after costs; checked for data errors, then accepted | 931a8766 |
| APARINDS case study | Results reach NIDP a median 36 days late; the model has no trend, sector or event inputs; two hypotheses logged | caf66b79 |
| Trendlyne connection | 10 stocks × 50 fields per call; Redis cache, daily archive, daily job, top-gainers list | 82b233aa → c3eede16 |
| Local screener and model scorecard | 11 screens plus accuracy tracking for v4 | 5fc10d11 |
| Phase 1 screeners | Volatility expansion and gap-down recovery/continuation closed; 20/55-day breakouts predict bigger moves but lose money, so they're kept for monitoring only | 6818f078 · 7cc924a3 · 2230aec1 |
| Requirements docs v1.0 and v1.1 | Saved with checksums, plus the audit acceptance matrix | 0181e08b |
| Data-timing audit, Day 0 | 66 of 74 checks pass; the eligibility gate is built, with 76 tests | 0aebc4c6 |

**Audit acceptance matrix (74 IDs):**
- 66 pass.
- 2 fail: NSE-01 and ARC-02.
- 4 unverified: TL-03, CMP-06, CAT-03 and CAT-04.
- 2 pending the owner: QA-06 and DEL-06.

**Key audit findings:**
- **Trendlyne can't say what was known on a past date.** It rejects any as-of argument and shows corrected values. RKFORGE's 10× filing error was fixed a month later, and Trendlyne shows only the fix.
- **Trendlyne uses different definitions.** Of 665 values, 406 match the original filing and 229 differ by definition: its revenue includes other income, its profit is the owners' share, and its EPS includes discontinued operations. 30 are unexplained.
- **NSE's XBRL filing time is late.** In 472 of 502 cases the results PDF was already out on BSE, a median of about 2 hours earlier. Using NSE's time is safe but conservative.
- **Ownership mostly matches.** Promoter and mutual-fund holdings match every time; FII and DII differ because Trendlyne groups some holders differently.

## Waiting on the owner

| # | Decision | Why it matters |
|---|---|---|
| 1 | Approve the audit's proposed data classes | Until then nothing from the audit can enter training or backtests; every category stays UNVERIFIED |
| 2 | Confirm the 3 manual PDF checks | LICHSGFIN, 3M India and HUL all matched; the check stays open until confirmed |
| 3 | Compare the requirements docs' checksums with the originals | The originals aren't on the research server |
| 4 | Send the model and paper-trading changes | Kite/Trendlyne substitution; not started, as instructed |
| 5 | Should Phase 1b run? | Tests whether the breakout flag improves v4; needs its own pre-registration |
| 6 | Collect NSE announcement times through the production proxy (about 120 requests) | Only 24 of 576 filings reach high timing confidence without them |
| 7 | When to fix the parser and cache bugs | Three affect production NIDP data |
| 8 | Track 1 forward ledger: rehearse, repoint or pause | Carried over from the overnight notes; not re-checked today |

## Next up (agreed, not started)

**Positional-trade pre-registration:**
- **Hold:** up to 5 sessions.
- **Risk per trade:** configurable, default 1%, maximum 2%.
- **Positions:** up to 8.
- **Entries:** pre-breakout buy-stop; pullback in uptrend; 55-day breakout with risk management; signal-day close.
- **Controls:** random entries with identical exits and sizing; a Nifty 500 benchmark.
- **Check first:** delivery costs (STT 0.1% each side).

**Remaining audit items:**
- TL-03 and CMP-06 need a second Trendlyne snapshot date, a few weeks from now.
- CAT-03 (corporate actions) and CAT-04 (SAST, deals) are untested.
- ARC-02: NSE's newer results listing carries no ISIN.

## Blocked or constrained

| Item | What's in the way |
|---|---|
| Post-results drift (best candidate for predicting direction) | NIDP ingests results a median 36 days late. The audit's filing data offers a way round it for the 40-stock sample; a wider rollout needs its own approval and budget |
| NSE data collection | NSE blocks the server's IP, so listing requests go through the production proxy, which is capped by the minimal-use rule. Documents come direct |
| Validation data | 2021–22 has been used twice and can't validate new ideas. **Jan 2023 – Jul 2024 is the only untouched period, and it can be used once** |
| Fundamentals history in NIDP | Past fundamentals are overwritten with current values; the fix (migration 148) is committed but not applied |
| Trendlyne history | Forward-only; our own daily archive of it starts 19 Sep 2026 |
| Intraday bars (Kite) | The access token needs an owner login every trading day |

## Concerns (severity is my rating)

| Severity | Concern | Detail |
|---|---|---|
| HIGH | No edge across 26 hypothesis families | Movement is predictable; direction after costs isn't. Each new test adds false-discovery risk; the positional study takes the count to 30 |
| HIGH | Bugs in production NIDP parsers | Profit missing for filings using one common tag (DEF-6); shareholding before mid-2025 unread (DEF-8); mutual-fund holdings always empty (DEF-9). Anything built on NIDP fundamentals or ownership inherits these |
| HIGH | Today's work exists only locally | The branch has no remote copy (49 commits today). Pushing needs owner approval, and the GitHub token may have expired on 1 Aug |
| MEDIUM | Trendlyne cache returns blanks silently | Requests for historical values come back empty without an error (DEF-7). The raw data is intact; the fix is small |
| MEDIUM | 235 uncommitted changes in the main checkout | Branch `feat/research-qa-exercise`. They aren't from this session, but they're at risk |
| MEDIUM | Research server disk at 84% | 13 GB free, and disk-full incidents have happened before. The production app server wasn't checked today |
| LOW | Survivorship bias | All research uses current Nifty 500 members only |
| LOW | Trendlyne licence | Its data is for internal use only; the repo holds 3 of its values in the manual-check record |

## Scheduled jobs (checked 13:15 IST)

| Job | Last run | State |
|---|---|---|
| Trendlyne daily (07:30 Mon–Sat) | Sat 19 Sep 09:59 | OK: exit 0; 4,850 values from cache, 0 new calls |
| Screener (19:30 and 21:30 Mon–Fri) | not yet run | UNVERIFIED: installed today; first run Mon 21 Sep 19:30 |
| TPD tracker | Fri 18 Sep 23:40 | OK |
| Paper engine | Fri 18 Sep 23:40 | OK: exit 0; 20 trades, 100 exits written to the staging DB |
| Catalyst monitor (every 15 min) | Sat 19 Sep 13:15 | Running, with 3 known source errors per run (e.g. IBBI HTTP 500) |

---
Figures come from committed research documents and from live checks of jobs, logs and git state at 13:15 IST on
19 Sep 2026. Full audit report: `docs/ai_research/tpd3/data/PIT_AUDIT.md` (commit 0aebc4c6).
