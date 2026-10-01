# Functionality Verification Report — Universe: liquidity rule replaces the rank cap

Date: 2026-10-01 · Branch: `feat/universe-liquidity-rule` · Base: `feat/paper-trade-engine` @ 8418037b

## Problem

Of 136 distinct stocks that moved >5% between 28 Sep and 1 Oct 2026, **46 liquid ones were never
candidates** — the model never scored them. Root cause, traced to one line:

```python
# universe.py:9 (before)
def pit_universe(panel, D, n: int = 1000, lookback: int = 126, min_bars: int = 100):
    ...
    return stats["symbol"].head(n).tolist()
```

A top-1,000 cap, never overridden. Measured on 2026-09-30 it put the real floor at
**Rs 4.67 cr median turnover — 4.7x the Rs 1 crore `rules_v1` documents** — leaving 371 symbols
that cleared the documented bar permanently unscored, plus 189 more barred by `min_bars=100`.

`997 = 1000 − 3` (HFCL, HEG, TBZ had no bar on T).

## Change

| | before | after |
|---|---|---|
| selection | top 1,000 by median turnover | **median turnover >= Rs 1 cr** (the documented rule) |
| `min_bars` | 100 | **60** (= `forward.WARMUP_BARS`) |
| rank cap | `n=1000`, always on | `max_symbols=None`, off by default |

`min_bars` moves to 60 because 60 is what the **scorer** already requires, and that is set by the
longest feature window in `MODEL_COLUMNS_V4` — `ret60`, with `dist_sma50` and `sma50_slope`
behind it. A universe gate stricter than the scorer silently drops symbols the model could handle;
a looser one admits symbols whose features are undefined. They should be the same number.

`universe_by_session` (training) was changed identically. **If those two diverge, every forward
number is measured against a membership the model was never trained on** — there is now a test
pinning their agreement.

## Measured effect on the 22-stock target list

| blocker | count | recovered |
|---|---|---|
| cap only (126 bars, ranks 110-1453) | 16 | **yes** |
| warm-up 60-100 bars (STLNETWORK, 68) | 1 | **yes** |
| warm-up <60 bars | 4 | **no — see below** |
| unrankable (VIVIANA, 17 bars) | 1 | no |

**17 of 22 recovered.** TCIEXP at rank 1453 was the binding case and now enters on turnover
(Rs 1.23 cr) rather than rank.

**The 5 not recovered are blocked by the model, not the config.** MOLBIO (32 bars, **Rs 213 cr
median turnover**, would rank 110th on liquidity), AUGMONT (22), VIVIANA (17), MCLEODRUSS (47),
STLTECH (29 — and its feed died 2026-05-13). `ret60` is undefined below 60 bars. Forcing them
through would feed NaNs into an 84-input model and produce a confident number from nothing.
Covering them needs a short-history model, not a lower threshold. This is recorded in the lock.

## Pre-registration

v1 (`locked_at` 2026-09-15) is **VOID** from this date — its 10 graded sessions were scored on a
different universe and must not be pooled. `thresholds_lock_v4_forward_v2.json` resets the window;
**all success criteria are carried over byte-identical** (asserted in the generator):
`bars`, `high_confidence`, `snapshot_rules`, `heads`, `model`. Only `_what`, `version`,
`locked_at`, `forward_window`, `supersedes` and `universe` differ.

Restarting now costs the 10 sessions banked. Discovering the same need in six months would cost 150.

## Real output

```
$ PYTHONPATH=. pytest nidp/tests/services/tpd_model/test_universe.py -q
12 passed in 1.79s

$ PYTHONPATH=. pytest nidp/tests/services/tpd_model/ -q
351 passed in 48.79s
```

Run with `/app/research/tpd3_forward/venv/bin/python` — the interpreter `run_v4.sh` actually uses
(sklearn 1.9.1). `/opt/nidp/venv` has no sklearn, so `backtest.py` cannot even import there; two
tests in this suite already failed collection on the unmodified branch for that reason.

New tests pin: the Rs 1 cr floor, that it is a **median** (one frenzied session must not buy a
year of membership), that `MIN_BARS == forward.WARMUP_BARS`, that `max_symbols` is a ceiling and
not the rule, and that `pit_universe` and `universe_by_session` agree both with and without the
floor engaged.

## Limits

- **Not deployed.** The nightly run uses pinned detached worktrees (`forward-v4` @ 4d90472b,
  `forward-paper` @ b3305593). They must be re-pinned after merge or nothing changes.
- `first_target_session` is set to **2026-10-05** on the assumption that 2026-10-02 is Gandhi
  Jayanti. **Verify against the NSE calendar before the first run.**
- Universe size will rise from 997 to ~1,400-1,500 and vary daily. Record it per session;
  runtime and cost change with it.
- **This does not create edge.** The control beat selection 6/6 in the stop/target matrix. It
  changes which stocks are reachable, not whether they pay.

## Verdict: PASS
