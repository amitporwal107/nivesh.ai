# H-B sealed validation (2021-01 → 2022-12) — result

**Registered verdict: FAIL. Accepted verdict: FAIL.** The extreme-trade audit found the trades executable and the result
independent of ETFs, of the 5-position cap and of liquidity. Abandon conditions 1 (the CI's lower bound is not above 0 — here the whole CI
is below 0) and 5 (≤ 0 at 2× costs) are triggered.

Run once, 2026-09-19 08:57 IST · runner `research/sealed/run_hb_validation.py` @ `f25b48e3` (committed before running
and unchanged since; the run recorded HEAD `5a03918c`) · spec `TRACK1_SCOPE_v2.md` sha256 `46b174ca…` · cost model
v1 accepted as-is by the owner · 5-minute bars from Kite, fetched 08:33–08:55 (3,609 signal-days, 0 errors, coverage
100%) · result file `HB_validation_2021_2022.json` · audit `HB_AUDIT.md` · universe conditional on the available Kite
historical universe (survivorship-limited).

## What was tested
A liquid (20-day value ≥ Rs 5 cr) EQ stock opens ≥ 3% below the previous close. Watch 09:15–09:45. Enter at the
open of the 09:45 bar only if the 09:40 close is ≥ 99.5% of the open **and** above the 09:15–09:45 VWAP. Stop −2%,
target +3%, else the official close. At most 5 entries per session, deepest gap first.

## Registered result (as run)
| metric | value |
|---|---|
| signals | 3,609 → 1,680 confirmed (48.6% of resolved), 1,778 rejected, 126 missing bars, 25 open mismatches |
| trades / sessions (after the 5-position cap) | 772 / 314 (63% of sessions had an entry; median 1 per session) |
| mean net per session | **−0.402%**, 95% NW CI [−0.567, −0.236], t −4.76; bootstrap [−0.567, −0.237] |
| median session / winning sessions | −0.503% / 36.6% |
| 2× costs | −0.750% (t −8.87) |
| 2021 / 2022 | −0.501% (t −4.32) / −0.315% (t −2.66) |
| > Rs 25 cr / Rs 5–25 cr | −0.430% (t −3.39) / −0.349% (t −3.31) |
| exits | time 41% · stop 36% · target 23% · stop-gap 0.1% |
| abandon conditions | **1 and 5 triggered**; 2, 3, 4 not |

## Audit (required before accepting a verdict)
| check | result |
|---|---|
| entry or exit price outside Kite's daily low–high | 0 of 772 / 0 of 772 |
| 09:45 entry bar missing / zero volume | 0 / 2 |
| returns beyond ±25%, duplicate symbol-days | 0 / 0 |
| ETFs | 87 of 772 entries (11.3%), 8.5% of net P&L; **ETFs dropped: −0.435%/session (t −4.58)** |
| 5-position cap removed (all 1,680 confirmed) | −0.412%/session (t −5.01); ETFs also dropped −0.446% (t −4.84) |
| same entries held to the close, no stop/target | −0.616%/session (t −5.06) — the −2/+3 exits are not the cause |

The best trades (ASTRAZEN, NATCOPHARM, OLECTRA, BUTTERFLY …) are ordinary +3% target exits at traded prices; the worst
are −2% stops. Nothing in the tails is a data artefact. Unlike H-A, ETFs do not drive this result.

## Why it fails — the rebound is over by 09:45
Same signals, registered section 8 (net of costs):
| | open → close (H-A) | 09:45 → close |
|---|---|---|
| signals H-B confirmed | **+2.32%** | **−0.55%** |
| signals H-B rejected | −1.27% | — |

Confirmation picks the gap-downs that recovered in the first 30 minutes. It identifies them correctly (+2.32% vs
−1.27% from the open), but by 09:45 the recovery has already happened, and what remains to the close is slightly
negative. Waiting to confirm means buying after the move. This is the same shape as family #20 (early strength fades)
and as the timing study (the day's low is usually in the first minutes). The +2.32% is hindsight about the first 30
minutes, **not** a tradable number: the only way to hold it is to enter at the open, which is the H-A family the owner
closed.

## Consequences
1. **H-B is closed as failed validation.** No retuning (other confirmation times, thresholds or stops) on this slice.
2. **Both Track 2 arms are now closed.** The gap-down sleeve has no surviving hypothesis.
3. **The final-test slice 2023-01 → 2024-07 stays sealed and unread.** It is the last untouched data, one use only.
4. **The 2021–22 validation slice has now been used twice** (H-A, H-B). It must not be the validation set for a
   hypothesis designed after seeing these results.
5. Track 1 (live paper tracking from Mon 2026-09-21) was built to test H-B operationally. With H-A and H-B closed, its
   signals are no longer candidate trades; whether to run it as a plumbing rehearsal, repoint it, or pause it is an
   owner decision (see `track1/TRACK1_STATUS.md`).

Audit script fix, recorded for transparency: the first audit run crashed on two wrong column names (`hb_exit`,
`hb_reason`); fixed to `exit_reason`, and the executability, cap and hold-to-close checks were added. The audit is a
diagnostic and never changes the registered result file.
