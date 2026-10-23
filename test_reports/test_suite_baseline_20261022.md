# Test-suite baseline — recorded separately from any change verification

**Date:** 2026-10-22 · **Tree:** `dev` at `72a9243c` (the PR #298 merge), as deployed to the
staging NIDP VM and bind-mounted into `nidp-daas-api-staging` at `/app/backend`.

This file is a **baseline record**, not a verification of a change. It deliberately carries no
`## Verdict: PASS` line, because nothing here proves a fix — it measures the harness itself so
that future runs can be compared against a known floor, and so that pre-existing failures are
never silently attributed to a new change.

## There are two test trees and they behave completely differently

| Tree | Result | Usable? |
|---|---|---|
| `backend/tests` (278 files) | **cannot collect at all** — 84 collection errors | ❌ no signal |
| `backend/nidp/tests` | **51 failed, 1281 passed, 5 skipped** in ~11 s | ✅ usable |

Command, run inside the staging container:

```
docker exec -w /app/backend nidp-daas-api-staging \
  sh -c "python -m pytest nidp/tests -q -p no:cacheprovider"
```

```
51 failed, 1281 passed, 5 skipped, 23 warnings in 10.99s
```

## `backend/tests` cannot collect — and that is pre-existing, not caused by the merge

```
Interrupted: 84 errors during collection
2 skipped, 26 warnings, 84 errors in 19.20s     <- container's own untouched tree
Interrupted: 83 errors during collection
2 skipped, 26 warnings, 83 errors in 18.80s     <- the merged tree under test
```

The untouched baseline errors on **84** files and the merged tree on **83**, i.e. the merged tree
errors on *fewer* files. Causes are environmental: `RuntimeError: REACT_APP_BACKEND_URL not set`,
`KeyError: 'REACT_APP_BACKEND_URL'`, and `FileNotFoundError` from env-relative paths.

**Consequence to state plainly: this tree gives no signal about any change.** A failing run here
is not evidence that a change broke something, and a green run is not obtainable. Any claim of
"the suite passes" based on `backend/tests` would be false.

## 30 of the 51 `nidp/tests` failures are one missing plugin

```
async def functions are not natively supported.
You need to install a suitable plugin for your async framework, for example:
  - anyio
  - pytest-asyncio
```

Count of failures carrying that exact message: **30**.

```
pytest 9.1.1
ModuleNotFoundError: No module named 'pytest_asyncio'
anyio present
```

`anyio` the library is installed but the tests are marked `@pytest.mark.asyncio`, which requires
`pytest-asyncio` specifically — hence the companion warning `PytestUnknownMarkWarning: Unknown
pytest.mark.asyncio`. So **30 of 51 failures are an environment gap, not defects**, and installing
`pytest-asyncio` into the test image should recover them. The modules affected are the async-heavy
ones: `test_dynamic_runner`, `quality/test_replay_engine`, `test_amfi_amc_autoregister`,
`test_announcement_classifier_provider`, `test_copilot_llm_provider`, `test_mf_amc_robustness`.

That leaves **21 failures that are potentially real** and worth triage on their own merits.

## Two registry-completeness failures checked individually

These two were checked specifically because PR #298 **added new feed services**
(`sensibull_fii_dii`, `scanx_mf_holdings`, `scanx_shareholding`, `trendlyne_ownership`,
`smart_money_study`), so a "every feed is registered/scheduled" test failing could plausibly have
been caused by that. Neither was.

```
________________ test_every_recoverable_daily_feed_is_scheduled ________________
E       AssertionError: recoverable daily feeds NOT scheduled in nidp.cron: ['corporate_announcements']
E       assert not ['corporate_announcements']
nidp/tests/test_feed_registry_drift.py:43: AssertionError
```

The single unscheduled feed is `corporate_announcements`, which predates PR #298. **Not caused by
the new services.**

```
________ TestResolveTable.test_dataset_map_covers_all_documented_feeds _________
async def functions are not natively supported.
```

This one is simply the missing `pytest-asyncio` again — it never actually executed, so it asserts
nothing about feed coverage either way.

## Container quirks worth knowing before running anything here

- `pytest` lives **inside** `nidp-daas-api-staging` (9.1.1). The VM host has none.
- **`pytest-timeout` is not installed** — passing `--timeout=` is rejected outright with
  `error: unrecognized arguments: --timeout=120`.
- The container bind-mounts `/opt/nidp/dev-repo/nivesh.ai/backend` → `/app/backend`, which is a
  **different checkout** from `/home/deploy/nivesh.ai`. To test an unmerged local tree, copy it in
  (`docker cp`) rather than editing the mounted checkout, which staging is serving from.
- A redeploy wipes `/tmp` inside the container, so a copied-in tree does not survive one.

## Independent evidence used in place of a full-suite pass

Since no full-suite green run is obtainable, PR #298's structural soundness rests on:

```
python3 -m compileall -q -j 4 nidp
exit=0 (0 = every .py in nidp/ compiles)
files: 712
```

All **712** backend `.py` files byte-compile on the merged tree (one pre-existing `SyntaxWarning:
invalid escape sequence '\.'` in `nidp/services/mf_disclosure_snapshot/discovery.py`, unrelated),
plus the two targeted PASS reports `smart_money_paired_evaluator_20261022.md` and
`sensibull_fii_dii_20261022.md`.

## Recommended, in priority order

1. Install `pytest-asyncio` in the test image — recovers 30 tests for one dependency.
2. Triage the remaining 21 `nidp/tests` failures on their merits.
3. Fix `backend/tests` collection (supply `REACT_APP_BACKEND_URL` and make fixture paths
   cwd-independent) so that 278-file tree yields signal at all.
4. Until 1–3 land, treat `nidp/tests` **51 failed / 1281 passed / 5 skipped** as the comparison
   floor, and compare against it rather than claiming an absolute pass.
