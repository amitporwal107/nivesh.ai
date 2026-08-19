# 132 — localizing `nidp.mf_nav_daily` is DEFERRED, with measurements

Not a `.sql` file on purpose: the migration runner globs `*.sql`, and this must
**not** run until the capacity question below is answered. Writing it as SQL now
would fill the staging disk and take Postgres down.

## The same defect as index_eod

`nidp.mf_nav_daily` is a pass-through VIEW over an FDW foreign table into prod, so
`amfi_nav`'s `INSERT … ON CONFLICT` can never match a conflict target:

```
InvalidColumnReferenceError: there is no unique or exclusion constraint
matching the ON CONFLICT specification
```

85 consecutive failures, never once green. Unlike `index_close`, the *source* is
healthy — AMFI's `NAVAll.txt` returns HTTP 200 / 1.65 MB — so `amfi_nav` would
genuinely start working the moment it has somewhere to write.

## Why the obvious fix is unsafe — measured, not assumed

Copying the FDW history into a local table looks cheap because prod reports the
hypertable as **65 MB**. It is not: 82 of prod's 83 chunks are Timescale
**compressed**. Uncompressed the same data is far larger.

| measurement | value |
|---|---|
| rows behind the FDW view | 21,692,626 |
| prod on-disk (82/83 chunks compressed) | 65 MB |
| same data dumped as text | **1.7 GB** |
| `mf_nav_daily_local` after VACUUM FULL | 97 MB for 411,409 rows (~236 B/row) |
| projected for 21.7M rows at that density | **~5 GB** |
| staging free disk | ~4.4 GB |

A 5 GB write into 4.4 GB of headroom recreates precisely the disk-full outage that
crashed Postgres, broke MinIO (`XMinioStorageFull` → `nse_shareholding`) and
stalled the nightly analytics chain. It must not be attempted as-is.

An initial attempt confirmed the danger empirically: dumping the table to text
took staging from 5.6 GB free to 3.1 GB before it was killed and reclaimed.

## Options, best first

1. **Overlay (no bulk copy, no disk cost).** Point `amfi_nav`'s writer at
   `nidp.mf_nav_daily_local` — already a real, writable table with 411k rows of
   history — and expose the canonical name as a view unioning the local table with
   the FDW view for deep history. Costs one small code change in
   `nidp/services/amfi_nav/writer.py` and one view. Turns `amfi_nav` green today.
   Caveat: `nidp.v_v3_mf_primitives` is a MATERIALIZED view bound to the current
   object, so rebinding it to see fresh NAVs is a separate change that must drop
   and repopulate it (and `nidp.v_international_funds` depends on it in turn).
2. **Compress on staging, then copy.** Make the local table a compressed
   hypertable matching prod, then the full 21.7M rows land in ~65-200 MB. Correct
   end state and removes the FDW dependency, but adds a compression policy and
   means recent chunks must stay uncompressed for upserts to work.
3. **Bounded-window copy.** Localize only the last N years (~1.1M rows/year, so
   ~250 MB/yr uncompressed). Cheap, but silently truncates the history that MF
   return/CAGR analytics read.
4. **Grow the disk.** Removes the constraint entirely and is the only option that
   makes the naive full copy safe.

## Already done (so whichever option is chosen starts from here)

- `mf_nav_daily_local` VACUUM FULL'd across 56 chunks: **2,477 MB → 97 MB**,
  ~2.38 GB of allocated-but-unused space reclaimed. Chunks held as little as 19
  live rows in 109 MB before this.
- `index_eod` is handled separately and safely in `131_localize_index_eod.sql`.
