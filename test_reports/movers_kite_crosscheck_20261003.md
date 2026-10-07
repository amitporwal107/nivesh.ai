# Cross-source validation — the movers screener, nidp vs Kite

- **Date:** 2026-10-03 · **Author:** Claude (QA + domain analyst)
- **Question:** is `/api/movers`' ranking right? Built the same screener a second time from an
  independent source (Kite daily bars, `research/kite_history/day_2021`, 2,957,649 rows / 2,936 symbols)
  and diffed it against the nidp ranking.
- **Why this test:** every Playwright case so far fed the UI *my own* fixtures. This is the first check
  of the numbers themselves against something I did not produce.

## Method

Same rule on both sides, computed independently: rank each session by `|close / prev_close − 1|`,
liquidity floor ₹50 L, top 20. nidp uses its own `prev_close` column; Kite has none, so the previous
Kite bar's close is used — deliberately a different derivation. Kite tradingsymbols carry the series
suffix (`PAR-BE`), normalised for name matching. Kite covers 17 of September's 21 sessions (its data
ends 2026-09-24).

**Date alignment checked first**, because of the known `row t = session t+1` trap on Kite intraday:

```
  EMUDHRA    2026-09-15  kite  +20.00%   nidp  +20.00%   MATCH
  PNCINFRA   2026-09-15  kite  -20.00%   nidp  -20.00%   MATCH
  TATACHEM   2026-09-15  kite  +19.99%   nidp  +19.99%   MATCH
  WHIRLPOOL  2026-09-23  kite  +20.00%   nidp  +20.00%   MATCH
  OPTIEMUS   2026-09-22  kite  +20.00%   nidp  +20.00%   MATCH
```
Daily bars are not offset.

## Result

```
top-20 overlap, all 17 sessions           : 18.35/20  (91.8%)
top-20 overlap, excluding the partial day : 18.56/20  (92.8%)

shared names across those 16 sessions      : 297
of which differ by more than 0.75pp        : 0
```

**On every session with full bars, the two feeds agree on every shared name to within 0.75 percentage
points — 297 of 297.** Two sessions (09-08, 09-09) match 20/20. The ranking is sound.

## Finding 1 — Kite's last day is a mid-session snapshot, not a close

2026-09-24 was the worst session (15/20) and the only one with percentage disagreements — eight of them,
up to 9.99pp (POLICYBZR nidp −36.00% vs Kite −26.01%).

```
  fetched_at 2026-09-24T05:26:40Z = 10:56 IST   (NSE session 09:15–15:30)
  2026-09-22: 2,894 symbols, median volume  99,820
  2026-09-23: 2,901 symbols, median volume 105,950
  2026-09-24: 2,872 symbols, median volume  32,341
```

A third of the usual volume, pulled 4.5 hours before the close. **Anyone treating Kite's final date as a
settled session gets wrong numbers**, and every one of the eight discrepancies is explained by it. The
delta puller should drop or mark its last day unless it ran after 15:30 IST.

## Finding 2 — the circuit-band check is validated

A move beyond ±20.5% cannot happen in an ordinary banded session. Of the 10 such rows in nidp's top-20,
**9 are not corroborated by Kite at all**:

```
  2026-09-03  LUMINO      +34.50%   in kite top-20 that day? no
  2026-09-04  ESDS       +111.70%   no
  2026-09-04  TCC         -81.10%   no
  2026-09-11  PGIL        -50.10%   no
  2026-09-17  KARAMTARA   +38.60%   no
  2026-09-17  RENTOMOJO   +32.20%   no
  2026-09-17  STEAMHOUSE  +26.60%   no
  2026-09-22  TAALTECH    -79.30%   no
  2026-09-23  SSRETAIL    +76.60%   no
  2026-09-24  POLICYBZR   -36.00%   YES  (but on the partial-bar day, and Kite says -26.01%)
```

Withholding them by default is correct: an independent feed does not see these moves.

## Finding 3 — neither feed is clean, and they disagree about which names are dirty

Kite carries beyond-band rows that nidp does not:

```
  2026-09-02  INDIAGLYCO  -78.75%   absent from nidp top-20
  2026-09-07  HEG         -62.62%   absent from nidp top-20
  2026-09-21  TAALTECH    -78.90%   absent from nidp top-20
```

**TAALTECH's split appears in both feeds one day apart** — Kite on 09-21, nidp on 09-22. The two sources
disagree about the ex-date itself.

The lesson for the screener: this is not a per-feed fixup to be patched in an ingestion job. Both feeds
carry unadjusted corporate actions, on different names and sometimes different days, so the check belongs
in the ranking — which is where it now is.

## Open question for the owner

**MONQ50 reaches nidp's top 20 on 7 of 21 sessions**, repeatedly pinned at ±20.0%, with no sector
mapping. It looks like an ETF, and an ETF hitting the band eight times in a month is a stale-NAV artifact
rather than a mover. Kite shows it too, so both feeds agree it printed — the question is whether it
belongs in a *movers* list at all. **`/api/movers` has no ETF exclusion.** Owner policy for the TPD model
is to exclude ETFs, and the sealed ETF list is recorded as contaminated, so there is no trustworthy
source to filter on without a decision. Not fixed; needs the owner's call on what identifies an ETF here.

## Verdict: PASS
