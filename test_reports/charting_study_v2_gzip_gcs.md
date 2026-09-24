# Functionality Verification Report — study-v2: gzip artefacts + GCS upload

- **Branch:** `feat/charting-study-v2-gzip-gcs` (stacked on steps 5–7)
- **Date:** 2026-09-23
- **Author:** Claude (full-stack developer + QA engineer)
- **Changed areas:** backend routes/services: **no** · frontend src: **no** · `research/` only

## Summary

Two levers, solving two different halves of the storage problem:

- **gzip** on the row and summary artefacts (`events.writer.write_run(compress=True)` and the
  summary writers). Measured **24.8×** on real pattern-event rows built from **real Kite bars** —
  not the synthetic fixture, which is scaled copies of one frame and would have flattered gzip.
- **`research/charting/study/remote_store.py`** — upload a finished run to GCS and verify it by
  re-reading every object, so a run is not bounded by the host's free disk at all.

Both are **off by default**. `--summarise-controls`, `--compress-events` and `--upload-to` are opt-in
CLI flags; an existing caller behaves exactly as before.

## The measurement that drove the gzip level

496 real pattern-event rows from real Kite bars, post-sealed bars only:

```
RAW events.jsonl :  33.042 MB   (65.1 KB/row)
gzip -1          :   2.079 MB   ratio  15.9x   379 MB/s
gzip -6          :   1.331 MB   ratio  24.8x   124 MB/s
gzip -9          :   1.271 MB   ratio  26.0x    63 MB/s
```

**-6 is the knee** — -9 buys 4% more for half the speed. The rows compress this well because every
line repeats the same ~350 key names; that is a property of the *format*, not of one dataset, so the
ratio should hold at scale rather than decay.

Per tree: pattern events **24.8×** · random-control rows 19.4× · buy-next-open 22.6× ·
`summaries.jsonl` **29.0×** · group `summary.json` 58.9×.

## End-to-end, four configurations, same inputs (20 seeds)

```
configuration                          MB    vs v1
v1: rows, uncompressed             13.426     1.0x
gzip only                           1.117    12.0x
summaries only                      7.540     1.8x
BOTH                                0.672    20.0x
```

Note "summaries only" is just 1.8× **here** because a seed summary has a fixed cost and this run
draws ~1.5 rows/seed. At V-3's scale that reverses — the summaries are what stop 32 TB existing,
and gzip is what shrinks the dataset. Neither substitutes for the other.

## Projection against 9.3 GB free local disk

| Tree | Uncompressed | gzip -6 |
|---|---|---|
| Pattern events (TC-113: 24 GB) | 24.00 GB | **0.97 GB** |
| Buy-next-open rows (54 GB) | 54.00 GB | 2.18 GB |
| Seed summaries @V-3, wide | 5.60 GB | **0.19 GB** |
| Random-control **rows** @V-3 (~32 TB) | 32,000 GB | 1,289 GB ← still absurd; this is why summaries exist |

**gzip alone unblocks step 8.** It also settles the S-1 narrowing question: the wide accumulator
gzips to 0.19 GB, so there is no longer a storage reason to narrow it. **Keep it wide.**

## The §8 property that had to be preserved

`integrity.kill_switch_check` hashes `writer._dump_jsonl(rows)` **in memory**. So the manifest's
`sha256` still hashes the **uncompressed** bytes when `compress=True` — a manifest written before and
after this option existed compares identically, and the kill switch is untouched. The stored bytes
are recorded separately as `compressed_sha256`, so they are verifiable too.

`gzip.compress` stamps the current time into the header, which would make two identical runs produce
different artefact bytes — and byte-identical output across runs is exactly what §8 checks. The
writer uses `GzipFile(mtime=0)` and a test pins the header bytes.

## Credentials

`remote_store` uses **Application Default Credentials** via `google.cloud.storage`. No token is read,
passed on a command line, or logged anywhere in this module. If ADC is missing it raises
`RemoteStoreError` — it never falls back to an anonymous client and never silently skips the upload.

Note for operators: `/app/.gcp-token` is **stale**, and gcloud is configured to read it via
`auth/access_token_file`, so `gcloud storage` 401s until that property is cleared
(`CLOUDSDK_AUTH_ACCESS_TOKEN_FILE=`). The `nidp-sa` service account itself authenticates fine and has
object read/write on the bucket; it lacks `storage.buckets.list`, which does not matter here. **No
global gcloud config was changed.**

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-270 | A gzipped artifact round-trips to exactly the same rows | unit | PASS |
| TC-271 | The manifest `sha256` still hashes the **uncompressed** bytes (§8 unaffected) | unit | PASS |
| TC-272 | gzip output is byte-identical across runs; the header mtime is zero | unit | PASS |
| TC-273 | Compression actually compresses (>5× on the fixture) | unit | PASS |
| TC-274 | Uncompressed remains the default for existing callers | unit | PASS |
| TC-275 | A real study run writes `events.jsonl.gz` and no plain copy | e2e | PASS |
| TC-276 | The gz artefacts read back as the rows the manifest counts; both hashes check | e2e | PASS |
| TC-277 | Dry-run sizes the tree without contacting GCS | unit | PASS |
| TC-278 | Upload then verify passes against a fake bucket | unit | PASS |
| TC-279 | **Negative control:** verification catches a corrupted object | unit | PASS |
| TC-280 | **Negative control:** verification catches a missing object | unit | PASS |
| TC-281 | An empty or missing directory is an error, not a silent success | unit | PASS |
| TC-282 | A failed verification raises out of `execute_study` rather than reporting success | unit | PASS |
| TC-283 | **Real upload to the real bucket, verified by re-reading** | live | PASS |

## Real output

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/ -q
1269 passed, 2 warnings in 108.40s (0:01:48)
```

TC-283 — a real run uploaded to `gs://nidp-raw-niveshdataintelligence`:

```
REAL GCS UPLOAD: {
  "uri": "gs://nidp-raw-niveshdataintelligence/research/charting_study_v2/_smoke/both",
  "n_objects": 25,
  "bytes": 671830,
  "verified": {"objects": 25, "manifests": 2, "artifacts": 2,
               "missing": [], "mismatched": [], "passed": true}
}
```

The smoke-test objects were removed afterwards:

```
$ gcloud storage rm -r gs://.../research/charting_study_v2/_smoke
Removing gs://.../_smoke/both/post_sealed/.../summaries.jsonl.gz#1790181029879876...
$ gcloud storage ls gs://.../research/charting_study_v2/
ERROR: (gcloud.storage.ls) One or more URLs matched no objects.     <- confirmed clean
```

## UNVERIFIED

- **Not run at TC-113's real universe.** The 24.8× is measured on real rows, but the 24 GB and 54 GB
  tree sizes are TC-113's figures, not re-measured here. Step 8 is the first run at real scale.
- **Upload throughput at scale is unmeasured.** 25 objects is not a load test; a real run writes far
  more, and per-object overhead may dominate. Worth a measurement before relying on it for a
  long run.
- **No lifecycle/retention policy is set** on the GCS prefix. Study runs will accumulate until
  someone decides a retention rule.

## Verdict: PASS
