# Track 1 / Track 2 — frozen scope v2

**Status: FROZEN** at the commit that adds this file. Supersedes v1 (`TRACK1_SCOPE_v1.md`) only where listed below;
every other v1 definition stands unchanged (universe, 09:15 signal, at-band exclusion, H-B confirmation rule, exit
priority rules, missing data → UNRESOLVED, cost model v1, recorded fields, report layout).

Owner decisions frozen here (2026-09-19): **D1** sealed split · **D2** hypotheses · **D8** daily cap · **D12** H-A variant.
Rationale for D12, recorded before any sealed outcome was read: on 2024–26 discovery data H-A open→close made
+0.498%/session (t 2.79) while the −2%/+3%/close version made +0.016% (t 0.22) (`PRIORITY1_RERUN.md`). Choosing on
discovery data is legitimate; this file fixes the choice before the sealed test.

> **H-A — validation candidate (frozen rule, awaiting the sealed test). Not a validated strategy.**
> **H-B candidate confirmation rule — operational test, not validated edge.**

## Changes from v1
| # | Item | v2 definition |
|---|---|---|
| 1 | **H-A exit (D12)** | Enter at the open `O` (+ slippage); **exit at the official close. No stop, no target.** The −2%/+3%/close outcome is still recorded per trade as a **secondary description**, never an endpoint |
| 2 | H-B exit | **Unchanged from v1**: −2% / +3% from the actual entry, both touched → stop, else the official close. H-B close-only is recorded as a secondary description |
| 3 | **Daily cap (D8)** | **At most 5 positions per session per arm.** Order: deepest gap first (most negative `g`); ties → higher 20-day traded value. H-A applies it at 09:15 to all signals; H-B applies it at 09:45 to confirmed signals only (knowable then) |
| 4 | **Sealed split (D1)** | **Validation slice 2021-01-01 → 2022-12-31. Final-test slice 2023-01-01 → 2024-07-31 stays sealed** until a hypothesis passes validation (Stage 3) |
| 5 | **Hypotheses (D2)** | **Only H-A and H-B** use the validation slice |
| 6 | Sealed-period data sources | Kite daily (adjusted) for gaps, open, close and 20-session traded value (volume × close) — NIDP bhavcopy does not cover 2021–22. Kite 5-minute bars for H-B (one login). Results labelled **"conditional on the available Kite historical universe"** (today's names only) |

## Sealed validation test (replaces v1 section 9)
| Item | Registration |
|---|---|
| Primary endpoint | **H-B**: mean per-session net return (cost model v1), sessions with ≥ 1 H-B entry, 5-position cap; success = mean > 0 and 95% Newey-West lower bound > 0 (α 0.025) |
| Co-primary | **H-A open→close**, 5-position cap; same success rule (α 0.025) |
| Required report | Trade- and session-level tables; median; std; whole-session bootstrap; worst 10 sessions; top-5/top-10 share of P&L; max simultaneous positions; year split (2021 vs 2022); liquidity split (Rs 5–25 cr vs > Rs 25 cr); 2× costs; H-A↔H-B comparisons from v1 section 8; survivorship counts |
| Abandon conditions (each arm) | (1) CI includes 0; (2) 2021 and 2022 disagree in sign; (3) effect only in Rs 5–25 cr and not > Rs 25 cr; (4) median entries per session < 1; (5) mean ≤ 0 at 2× costs |
| Run rule | **Once.** Code version, data manifest and this file's SHA-256 recorded. No tuning, no reruns with small changes, and the final-test slice is never used to choose between variants |
| Precondition | Charges in cost model v1 (0.10% round trip) confirmed against one of the owner's contract notes, or explicitly accepted as-is by the owner |

## Discovery-period reference (2024-08 → 2026-09; NOT evidence)
H-A open→close with the 5-position cap, deepest gaps first: +0.686%/session (t 3.75); at 2× costs +0.364% (t 1.99)
(`PRIORITY1_RERUN.md`, sensitivity table — shown for context; the cap was chosen by the owner from manual capacity).
