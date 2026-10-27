# Staging repair of the scanner bar store: run record (2026-10-27, 03:03–03:16 IST)

**Authority:** owner decision §9.1 (1) and (2) in `docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md`. This was a controlled
staging run subject to a preflight, recomputing the latest date only. PR #355 stays unmerged. No production change.
**Code run:** the reviewed PR head `26040c45`, from a scratch copy inside `nivesh-staging-app-backend` (`/tmp/scanner-repair-26040c45`,
removed afterwards). The served checkout `/app/backend` was not touched.
**Run-book:** `runbook_scanner_repair.md` (steps 0–8), followed without deviation.
**Evidence:**
- container: `/app/data/scanner-repair-20261027/` (host: `/opt/nivesh-staging/data/app/scanner-repair-20261027/`, mode 600);
- printed results: `/home/deploy/scanner-repair-20261027/01…14_*.txt`.

## Preconditions (step 0)
- Time 03:03 IST, outside the 19:00–23:00 job window. No scanner, watchlist or repair process was running.
- Latest scored date `2026-10-26`, the reviewed one. Disk 5.2 GB free (95% used).

## Preflight (step 2): every owner condition met before the first write
| Condition | Result |
|---|---|
| Counts match the reviewed dry run | 14 phantom dates / 36,361 bars, every one a 100% copy of the previous session; non-session dates that are not copies: none; missing 2026-10-21 (2,916) and 2026-10-22 (2,915), NSE files "trade date matches", 0 close mismatches; recompute `["2026-10-26"]`; `expect_arg` = `stock_ohlcv=36361,stock_technical_features=28280,positional_signals=9412` |
| Snapshot on persistent storage, readable, complete, non-empty | `--snapshot-only` → `"verification": {"ok": true, "rows": {"stock_ohlcv": 36361, "stock_technical_features": 28280, "positional_signals": 9412}, "problems": []}`; independent `--verify-snapshot` → `"ok": true, "against": "the current store (not yet applied)"`; file 61,209,933 bytes |
| Coverage of every affected table | bars, technical features and signals (per-table counts above) |
| Fingerprint before | `fp_0_before.json` (row count + md5 per table and date) |

## Apply #1 (step 3): one transaction
```
"changed": true
"written": {"stock_ohlcv_deleted": 36361, "stock_technical_features_deleted": 26070, "positional_signals_deleted": 8746,
            "stock_ohlcv_inserted": 5831, "features_written": 2205, "signals_written": 682}
"after": {"phantom": 0, "missing": 0, "unverified_extra": 0, "pending": {"delete_dates": [], "backfill_dates": [], "recompute_dates": []}}
"quality_after": {"ok": true, "clean": true, "problems": [], "counts": {"copied_sessions": 0, "missing_sessions": 0,
                  "extra_dates": 0, "duplicate_bars": 2, "stale_symbols": 137, "invalid_ohlc": 0, "zero_volume": 0}}
recomputed 2026-10-26: scored 2205, actionable 682; price basis: warehouse_adjusted 2194, raw_no_factors 11
before/after record: apply1_snapshot.json.before_after.json (code_change_only: actionable 666 -> 676, +11/-1)
```

## Quality rerun (step 4)
`copied_sessions`, `missing_sessions` and `extra_dates` are all 0, and "--apply would" is empty for delete, back-fill and
recompute. `stock_ohlcv` total = **657,593** (= 688,123 − 36,361 + 5,831).

## Apply #2 (step 5): must change nothing
`"changed": false, "reason": "nothing to repair: no phantom date, no missing session, recompute dates already on positional.v1.1"`.
No `apply2_snapshot.json` was created. Fingerprint compare after apply #1 vs after apply #2: `"identical": true`.

## Restore (step 6): exact prior state
`"restored": true`, verification `"ok": true`, `"run_records_rolled_back": 1`. Fingerprint compare before vs after restore:
**`"identical": true`**, over every table and date, row counts and md5.

## Final apply (step 7)
`"written"` is identical to apply #1 (36,361 / 26,070 / 8,746 deleted; 5,831 inserted; 2,205 features; 682 signals).
`after`: phantom 0, missing 0, clean. The dry run afterwards has nothing to do.
Compared with apply #1, the fingerprints differ only on `stock_ohlcv` 2026-10-21/22 and on features and signals for
2026-10-26, as the run-book predicts: the row counts there are equal (2,916 / 2,915 / 2,205 / 682); only the
`ingested_at` / `computed_at` times are new. The two before/after records match apart from `committed_at`.

## Independent data check (SQL, after the run)
```
bars on the 14 phantom dates: 0       signals on phantom dates: 0
2026-10-21 bars: 2916   2026-10-22 bars: 2915   2026-10-23 bars: 2925   2026-10-26 bars: 2930
26 Oct signals by engine: [('positional.v1.1', 682)]      latest signal date: 2026-10-26
```

## Still open
- **Deployed code is still the pre-#355 engine.** Tonight's 19:45 IST scan scores 2026-10-27 with `positional.v1.0` on raw
  prices (on the repaired bars), and its ingester can again stamp a holiday: the next NSE holiday the rehearsal found is
  2026-11-10. Merge #355 before then. The `scan_basis` line in the API and UI appears only after deploy.
- After #355 is deployed, the latest date then stored (2026-10-27 or later) is on v1.0. Rerun the dry run and recompute
  that one date, with the counts reviewed first.
- The quality counts `duplicate_bars: 2` and `stale_symbols: 137` are informational (clean = true). Not investigated in
  this run.
- Rollback at any time: restage the reviewed code, then
  `--restore /app/data/scanner-repair-20261027/apply_final_snapshot.json` (one transaction), and compare a new
  fingerprint with `fp_0_before.json`.

## Verdict: PASS
<!-- Scope: the staging data repair against the owner's preflight conditions (all met, real output above). It does not
     cover the merge or deploy of PR #355, which remain the owner's decision. -->
