# Functionality Verification Report — ADX(14) into the chart indicator catalogue

- **Branch:** feat/charting-indicator-catalogue
- **Date:** 2026-09-23
- **Author:** Claude (full-stack developer + QA engineer)
- **Environment:** local research + backend test suites. **No staging surface changed** (see "Scope and what is NOT claimed").
- **Changed areas:** backend routes/services: **no** (only `backend/tests/`) · frontend src: **no** (only an e2e comment)

## Summary

§39.10's availability table listed ADX(14) as **not served**: it existed only as the private
`regime._adx_series` and was absent from the chart indicator catalogue. It is the most-cited Class C
context input in §39.9, so its absence was one of the two things blocking the Class C layer.

This change promotes the existing calculation to a public charting series and adds one catalogue
preset. It does **not** promote ADX into a pattern gate: Class C is evidence only (§39.9, C-8), and
nothing in the detector, the registry or the config reads it. The frozen v1 `config_hash` and the
NI-3 fingerprint are unchanged, and the committed snapshot is byte-identical to `origin/dev`.

The sequence followed is the one specified: private calculation → public charting series → catalogue
preset → API exposure → indicator fixture tests → chart rendering test.

- `series.adx(bars, period=14)` — public, named `"adx"`, registered in `series.INDICATORS`
  (`output_fields ("adx",)`, `warmup_period 28`, `calculation_version 1.0.0`).
- `regime._adx_series` now **delegates** to it (`series.adx(bars, period).rename(f"adx_{period}")`),
  so there is exactly one implementation, not two that can drift.
- Catalogue: `CATALOGUE_VERSION 1.0.0 → 1.1.0`, new indicator `adx` (category `trend`, own pane,
  reference bands 20.0 / 25.0 — §37.1's own regime thresholds, so the chart draws the lines the trend
  classifier actually uses), one preset `adx_14` → `series_id adx_14`. 17 presets → 18.
- `catalogue_hash()` moves from `6c263d64f462362e85d7d5c5e7fae9cd7b58c5d4a5e89249445d41a94659a94f`
  to `15cc5cf2d3f31547189a228ae6c625d366abf636e3a91607b9c47ff28664f6e4`.

## Scope and what is NOT claimed

**ADX is not visible on the deployed chart yet, and this report does not claim it is.** §38.5's rule
is that adding a preset means a new catalogue version **and a re-export**. `GET /api/research/chart/catalogue`
serves the catalogue recorded in the snapshot manifest (`backend/services/research_chart.py:295`), and
the committed snapshot is still at catalogue `1.0.0` / hash `6c263d64…`. So staging keeps serving 17
presets until the next re-export. That is deliberate here: the plan's own verification rule is that the
committed snapshot stays byte-identical to `dev` during this work, and a re-export would also refresh
every symbol's bars and pattern payloads — far more than an ADX addition.

Consequence for the e2e fixture: `frontend-v5/e2e/fixtures/research-chart-catalogue.json` is
byte-equal to `manifest.indicator_catalogue` + its hash (verified below), so it stays at 17 presets and
the TC-213 count assertion stays at 17 — matching what staging actually serves. The deliberate skew is
documented in the spec itself rather than left silent.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-220 | series | `series.adx` matches an independently written naive Wilder loop (no shared helpers) | unit | element-wise equal, ≥20 valid overlap, 3 seeds | PASS |
| TC-221 | series | One implementation: `regime._adx_series` delegates, so the naive oracle binds both | unit | same NaN mask and values for both callables | PASS |
| TC-222 | series | Warmup: ADX is DX Wilder-smoothed twice, first value at 2·period−1 = 27 | unit | NaN through index 26, value at 27 | PASS |
| TC-223 | series | Registry contract: declared `warmup_period 28` matches empirical NaN count | unit | driven off `series.INDICATORS`, not a literal | PASS |
| TC-224 | look-ahead | Probe B2: poisoning the future never changes a past ADX value | unit/edge | truncated == poisoned-then-truncated, exact, 6 cut points | PASS |
| TC-225 | catalogue | The `adx_14` preset is present, ids/series ids unique, 18 presets | unit | `by_indicator["adx"] == [{"period": 14}]`, count 18 | PASS |
| TC-226 | catalogue | No second calculation path: the preset's `compute` equals `series.adx` on real bars | unit | element-wise equal on RELIANCE daily | PASS |
| TC-227 | API | `GET /catalogue` serves ADX with its bands, own pane and one preset | api | `adx` between `bollinger` and `atr`; bands [20.0, 25.0]; 18 presets | PASS |
| TC-228 | API | Served catalogue still equals the one the snapshot was built with | api | served hash == manifest hash == `catalogue_hash()` on a freshly exported snapshot | PASS |
| TC-229 | frozen | Neither frozen hash moves | data | `config_hash 05167d3a…`, NI-3 `de86626c…` | PASS |
| TC-230 | frozen | The committed snapshot is untouched | data | `git diff origin/dev -- backend/services/research_chart_snapshot/` empty | PASS |
| TC-231 | scope | ADX is not promoted to a gate | review | no detector/registry/config reads ADX | PASS |

## Unit and API tests (real output)

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest \
    research/charting/tests/test_series.py \
    research/charting/tests/test_indicator_catalogue.py \
    research/charting/tests/test_regime_trend.py \
    backend/tests/test_research_chart.py -q
........................................................................ [ 46%]
........................................................................ [ 92%]
............                                                             [100%]
156 passed in 5.54s
```

Full charting research suite, no regressions (1189 before this work item, 1202 after — the extra 13
are this change plus the P-1 apex boundary and NLA-005 tests landed alongside):

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -m pytest research/charting/tests/ -q
1202 passed, 2 warnings in 89.39s (0:01:29)
```

## Data correctness

Catalogue shape, read back from the module:

```
$ PYTHONPATH=. /opt/nidp/venv/bin/python -c "..."
version: 1.1.0
indicators: 8 presets: 18
hash: 15cc5cf2d3f31547189a228ae6c625d366abf636e3a91607b9c47ff28664f6e4
  adx_14 adx adx_14 None        <- export spec: series_id, registry_key, pane, warmup override
```

ADX registry entry, as `serialisable()` reads it:

```
"indicator_id": "adx", "output_fields": ["adx"], "warmup_period": 28,
"calculation_version": "1.0.0",
"missing_data_policy": "NaN until 2*period bars are available -- ADX is DX Wilder-smoothed a
  second time, so its first valid index is 2*period - 1."
```

Frozen hashes and snapshot immutability:

```
$ PYTHONPATH=. python -c "from research.charting.config import config_hash, CONFIG; print(config_hash(CONFIG))"
frozen v1 config_hash: 05167d3ae57f18602b8761ee21de311f5ffb96c428a16df5c119678a748514cf
$ PYTHONPATH=. python -c "from research.charting import ni3_config; print(ni3_config.fingerprint(ni3_config.load()))"
NI-3 fingerprint: de86626c6f15e5f2d41708e92f8b66367394eb1c8e52ed2534ecfd8e0ded44a8
$ git diff --stat origin/dev -- backend/services/research_chart_snapshot/
(no output — byte-identical)
```

Fixture / snapshot equivalence, which is why the e2e count stays at 17:

```
manifest catalogue version: 1.0.0 | hash field: 6c263d64f462
fixture == manifest catalogue + hash : True
```

## UNVERIFIED

- **The dialog has not been seen with ADX in it.** It cannot be until the snapshot is re-exported,
  which is a separate, owner-gated step (it changes a 21 MB committed artefact and triggers a staging
  deploy). Next step: re-export, regenerate `research-chart-catalogue.json` from the new manifest,
  move the TC-213 count to 18, and run the chart specs.
- **No staging call was made**, because no route or service changed and staging serves the 1.0.0
  catalogue by design. Nothing here claims staging behaviour.

## Verdict: PASS
