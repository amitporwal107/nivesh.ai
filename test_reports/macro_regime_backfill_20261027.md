# Market regime backfill on staging (macro_daily 21 and 26 Oct), 2026-10-27 about 16:50 IST

**Authority:** the owner's "approve regime fix" (27 Oct), covering the code fix (separate PR) and this backfill.
**Why:** the macro job's `CronTrigger(18:35)` has no timezone, so it runs at 00:05 IST in the UTC container and often
misses the session that just closed. `macro_daily` had no rows for 21 or 26 Oct. The risk service's regime read
**as of 23 Oct** with VIX 16.86. Diagnosis: `docs/` handoff and scratchpad `regime_staleness_diagnosis.md`.
**Source of the values:** warehouse `nidp.index_eod` (NSE_IND_CLOSE), re-read just before writing:

| session | Nifty 50 | pts change | India VIX |
|---|---|---|---|
| 2026-10-21 | 22811.35 | −77.60 | 15.68 |
| 2026-10-26 | 22753.20 | +153.20 | 17.16 |

(22 Oct 22687.65 = 22811.35 − 123.70 and 26 Oct = 22600.00 + 153.20, so the closes chain.)

## Test cases and results (real staging output)
| # | Case | Expected | Result |
|---|---|---|---|
| B-1 | Dry run (reads only) | all insert columns exist; no backup tables; no rows for the 2 dates | `has all insert columns: True`, `existing backup tables: []`, `pre macro_daily: 9 rows, max date 2026-10-23`, `pre … rows for the 2 dates: []` |
| B-2 | Backup + insert in ONE transaction | 3 backups, 2 rows | `transaction committed: backups 3, rows inserted 2`; backups hold 9 / 9 / 15 rows |
| B-3 | Recompute features and regime for 21 and 26 Oct, in order | no error | `recomputed 2026-10-21`, `recomputed 2026-10-26` |
| B-4 | Stored values | equal the warehouse | `2026-10-21 22811.3500 15.6800 nidp.index_eod NSE_IND_CLOSE`, `2026-10-26 22753.2000 17.1600 nidp.index_eod NSE_IND_CLOSE` |
| B-5 | No weekend rows | 0 | `weekend rows with Nifty: 0` |
| B-6 | Desk regime | as of 26 Oct, key mixed, trend down | `{'key': 'mixed', 'as_of': '2026-10-26', 'trend': 'down', 'nifty_close': 22753.2, 'nifty_average': 23370.07, 'india_vix': 17.16, 'breadth': 'up'}` |
| B-7 | Risk service input | BEAR, as of 26 Oct, VIX 17.16 | `{'regime': 'BEAR', 'vix': 17.16, 'as_of': '2026-10-26', 'error': None}` |
| B-8 | latest_state | 26 Oct | `latest_state date: 2026-10-26` |

The BEAR size cut is unchanged (the trend is still down). The as-of date, the VIX and the desk label are now correct.

## Rollback
```
DELETE FROM macro_daily WHERE date IN ('2026-10-21','2026-10-26') AND source_nifty='nidp.index_eod NSE_IND_CLOSE';
DELETE FROM macro_features WHERE date IN ('2026-10-21','2026-10-26');
-- restore the 2 macro_state rows from macro_state_bak_20261027
```

## Not done here
- **27 Oct:** the warehouse has it after about 19:00 IST. The code fix's 19:30 IST job ingests it once deployed;
  otherwise insert it the same way after 19:00.
- **Backup tables:** `macro_*_bak_20261027` stay until the owner agrees to drop them.

## Verdict: PASS
<!-- Scope: the staging data change above, real output. -->
