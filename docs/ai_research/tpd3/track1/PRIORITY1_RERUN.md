# Priority 1 — research-integrity rerun of H-A (discovery period only), 2026-09-19

Owner review item: three-way lower-circuit rerun, full session-level metrics, excluded observations, liquidity,
costs. Script: `/app/research/priority1/ha_rerun.py`; table: `ha_rerun_table.csv`. Universe = the **frozen Track 1
spec** (EQ, 20-day value ≥ Rs 5 cr, Kite real gap ≤ −3%, **no per-day cap**), cost model v1 (0.20/0.30/0.40% round
trip by liquidity), 2024-08 → 2026-09. **Unit of analysis: the session** (equal-weight mean per session; Newey-West t;
bootstrap resamples whole sessions).

**Primary gate chosen before this rerun:** B (open at a lower band, knowable at 09:15), frozen in `TRACK1_SCOPE_v1.md`
at 04:42 IST on the look-ahead principle, not on performance. A and C are sensitivity analyses.

## Results
| metric | A close-only (look-ahead) | **B close-only (frozen gate)** | C close-only (no gate) | A −2/+3/close | **B −2/+3/close** | C −2/+3/close |
|---|---|---|---|---|---|---|
| stock-days | 5,149 | **4,815** | 5,594 | 5,149 | **4,815** | 5,594 |
| sessions | 443 | **437** | 458 | 443 | **437** | 458 |
| mean gross per trade | 1.968% | 2.091% | 2.023% | 0.971% | 1.023% | 1.024% |
| median trade, net | 1.507% | 1.584% | 1.407% | 2.600% | 2.600% | 2.600% |
| **mean net per session** | +0.344% | **+0.498%** | +0.525% | −0.032% | **+0.016%** | +0.072% |
| median session | +0.213% | +0.265% | +0.240% | −0.036% | +0.075% | +0.042% |
| std per session | 3.364% | 3.408% | 3.432% | 1.504% | 1.550% | 1.408% |
| t (session, Newey-West) | 1.92 | **2.79** | 3.03 | −0.43 | **0.22** | 1.01 |
| bootstrap 95% (whole sessions) | [+0.038, +0.657] | [+0.185, +0.829] | [+0.217, +0.844] | [−0.167, +0.104] | [−0.121, +0.160] | [−0.053, +0.201] |
| trades won / sessions won | 67.2% / 53.7% | 68.0% / 55.4% | 65.3% / 55.0% | 60.2% / 49.7% | 61.3% / 51.5% | 59.8% / 51.7% |
| worst 5% of sessions (mean) | −6.40% | −6.17% | −5.64% | −2.36% | −2.36% | −2.35% |
| top 5 / top 10 sessions' share of total P&L | 52% / 82% | **36% / 58%** | 39% / 60% | n/a | 195% / 387% | 42% / 84% |
| max / median positions in a session | 807 / 4 | **749 / 3** | 899 / 4 | same | same | same |
| **net per session at 2× costs** | +0.023% (t 0.13) | **+0.175% (t 0.98)** | +0.199% (t 1.15) | −0.354% | −0.306% | −0.254% |
| Rs 5–25 cr | +0.569% (t 3.08) | +0.691% (t 3.67) | +0.679% (t 3.92) | +0.098% | +0.147% | +0.189% |
| **> Rs 25 cr** | +0.216% (t 0.87) | **+0.411% (t 1.66)** | +0.328% (t 1.43) | −0.170% | −0.112% | −0.092% |

## Findings
1. **The previously quoted +0.665% (t 3.67) depended on a top-20-per-day cap that is not in the frozen spec** and a flat
   0.25% cost. Under the frozen spec: **+0.498%/session, t 2.79**.
2. **Not robust to costs:** at 2× costs +0.175% (t 0.98).
3. **Concentrated:** the 10 best sessions give 58% of total P&L; the 10 busiest sessions hold **48.2%** of all qualifying
   stock-days (2025-04-07: 899 names; 2026-03-02: 712; 2025-05-09: 301).
4. **Liquidity:** > Rs 25 cr is +0.411% (t 1.66) — on discovery data this would already trigger the frozen abandon
   condition 3 ("effect only in Rs 5–25 cr").
5. **The frozen H-A arm with −2/+3/close exits is ~0** (+0.016%, t 0.22) in every gate version.
6. **Capacity:** up to 749 simultaneous positions on one day — not a realistic manual book.

## The excluded observations
| group | stock-days | sessions | close-only net per session | on the 10 busiest sessions | never traded below the open | locked all day at the band (unsellable at the close) |
|---|---|---|---|---|---|---|
| excluded by B (open at a band) | 779 | 265 | +0.135% (t 0.53) | 38.3% | 57.1% | **30.8%** |
| excluded by A only (look-ahead) | 445 | 194 | +1.340% (t 4.95) | 35.3% | 100% | 53.9% |
B's exclusion is justified on tradability: nearly a third of those names could not be sold at the close.

## Capital-level sensitivity (NOT rule selection): H-A close-only, gate B, max N per session, deepest gaps first
| max positions | stock-days | net per session | t | top-10 share | 2× costs |
|---|---|---|---|---|---|
| 3 | 1,060 | +0.740% | 3.81 | 44.6% | +0.418% (t 2.16) |
| 5 | 1,445 | +0.686% | 3.75 | 45.1% | +0.364% (t 1.99) |
| 10 | 1,966 | +0.604% | 3.35 | 51.0% | +0.281% (t 1.57) |
| 20 | 2,380 | +0.549% | 3.02 | 56.0% | +0.226% (t 1.25) |
| none | 4,815 | +0.498% | 2.79 | 58.4% | +0.175% (t 0.98) |
The cap is a material parameter. **It must be frozen from the owner's manual capacity (decision D8) before the sealed
test — never chosen from this table.** These discovery t-statistics are optimistic after 19+ hypothesis families.

## Status
H-A remains an **exploratory finding** until the v2 specification (H-A variant + daily cap + ordering) is frozen; it
then becomes a **validation candidate**. It is not a validated strategy.
