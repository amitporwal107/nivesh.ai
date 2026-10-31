"""DaaS — Evidence & Validation: the real, pre-registered post-disclosure forward-returns study.

    GET /v1/desk/evidence/post-disclosure-study   the frozen study's contract + its real result,
                                                   one row per horizon (5 / 20 / 60 sessions)

Read-only, and there is nothing to read: this endpoint serves no live SQL. It reports a FINISHED,
HASH-GUARDED research study (NIDP-SHP-FWD-001, branch `study/post-disclosure-forward-returns`,
commit `62443b98`) whose script (`backend/nidp/analysis/shp_post_disclosure/study.py`) re-hashes
its own pre-registration contract and aborts before touching data on any mismatch. That script and
its contract live on an unmerged branch and are NOT part of this deployment; re-running them is the
orchestrator's job when that branch is merged, not this endpoint's. So the numbers below are a
VERBATIM, frozen snapshot of the study's own already-run, already-verified output
(`test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md` on that branch), each one cited to the
exact line it was read from in this module's comments. Nothing here is re-derived, re-estimated or
guessed, and nothing here may ever be promoted to a score.

RESEARCH ARTIFACT. NOT A PRODUCT FEATURE. The study's own verdict is INCONCLUSIVE and stays the loud,
primary fact on this screen:

  * 10 formation quarters (2024-03-31 .. 2026-06-30) against a review floor of 12 independent
    blocks — a POSITIVE verdict was unreachable by construction, declared before any result was
    computed.
  * At the primary horizon (20 sessions) the increased-minus-reduced spread is +1.0749 pp with a
    95% date-block-bootstrap CI of [-0.8673, +2.9054] pp. The interval straddles zero.
  * Net of ~0.9874pp of estimated round-trip costs (two legs, 0.4937% each), the 20-session spread
    is +0.0875 pp — i.e. inconclusive before costs are even applied, and flat to slightly negative
    after.
  * The sign is not robust to specification: +1.07pp on delta(FII+DII), -0.47pp on delta(FII) alone,
    +1.28pp on threshold-free terciles. Two signs from three reasonable readings of the same
    question is the signature of noise.
  * 2026-09-30 is the ONLY quarter with a genuine NSE publication timestamp for its disclosure, and
    it is excluded: no trading session exists yet after its 25-day availability date, so it has no
    forward window at all. This is reported as its own explicit field, never silently dropped.

Deliberate omission: no Nifty 500 TRI row. There is no total-return index in this warehouse —
nidp.index_eod's 'Nifty 500' is a PRICE index with severe gaps (25.4% of 2025 sessions missing,
largest gap 375 days) — and the study's own estimand is market-neutral by construction (both legs
occupy the same quarter and window), so no benchmark is used or implied anywhere in this payload.

No predictive score. No ranking. No buy/sell framing. This endpoint explains what was tested and
what the result was -- nothing more.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from nidp.services.daas_api.auth import require_api_key

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

STUDY_ID = "NIDP-SHP-FWD-001"
STUDY_TITLE = "Post-disclosure forward returns by institutional ownership change"
STUDY_BRANCH = "study/post-disclosure-forward-returns"
STUDY_COMMIT = "62443b98"
#: Mirrors preregistration.json's own hash guard (study.py:PREREG_SHA256 on that branch). Recorded
#: here as provenance only -- this endpoint does not re-hash anything, it has nothing to hash.
PREREGISTRATION_SHA256 = "5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071"
REPORT_PATH = "test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md"

PRIMARY_HORIZON = 20
SECONDARY_HORIZONS = (5, 60)
HURDLE_PP = 1.00
REVIEW_FLOOR_BLOCKS = 12
COST_PCT_PER_LEG = 0.4937
COST_TOTAL_PP = 0.9874  # two legs

#: Report §4.1, "Primary — delta(FII+DII), bands ±0.50 pp" -- the mean-spread line for each horizon,
#: copied verbatim from the real, already-run output in REPORT_PATH.
_HORIZON_ROWS: List[Dict[str, Any]] = [
    {
        "sessions": 5,
        "is_primary": False,
        "mean_spread_pp": -0.0007,
        "ci_low_pp": -1.1932,
        "ci_high_pp": 1.1074,
        "blocks": 10,
        "positive_quarters": 5,
        "net_of_cost_pp": -0.9881,
        "verdict": "INCONCLUSIVE",
    },
    {
        "sessions": 20,
        "is_primary": True,
        "mean_spread_pp": 1.0749,
        "ci_low_pp": -0.8673,
        "ci_high_pp": 2.9054,
        "blocks": 10,
        "positive_quarters": 6,
        "net_of_cost_pp": 0.0875,
        "verdict": "INCONCLUSIVE",
        "verdict_reason": (
            "10 formation quarters against a review floor of 12; the 95% CI [-0.8673, +2.9054] pp "
            "does not clear the +1.00 pp hurdle and the interval straddles zero."
        ),
    },
    {
        "sessions": 60,
        "is_primary": False,
        "mean_spread_pp": -0.7468,
        "ci_low_pp": -5.6316,
        "ci_high_pp": 3.6992,
        "blocks": 10,
        "positive_quarters": 5,
        "net_of_cost_pp": -1.7342,
        "verdict": "INCONCLUSIVE",
    },
]

#: Report §4.4, "the sign is not robust" -- the three specifications' 20-session mean spread.
#: Shown for transparency only; none of this is the primary estimand and none of it is a finding.
_ROBUSTNESS_20_SESSIONS: List[Dict[str, Any]] = [
    {"specification": "delta(FII+DII)", "role": "primary", "mean_spread_pp": 1.0749,
     "ci_low_pp": -0.8673, "ci_high_pp": 2.9054, "positive_quarters": 6},
    {"specification": "delta(FII) alone", "role": "robustness", "mean_spread_pp": -0.4687,
     "ci_low_pp": -1.4073, "ci_high_pp": 0.5148, "positive_quarters": 4},
    {"specification": "delta(FII+DII) terciles (threshold-free)", "role": "robustness", "mean_spread_pp": 1.2752,
     "ci_low_pp": -0.0964, "ci_high_pp": 2.5984, "positive_quarters": 6},
]


def _payload() -> Dict[str, Any]:
    rows = [dict(r) for r in _HORIZON_ROWS]
    out: Dict[str, Any] = {
        "as_of": "2026-10-23",
        "study_id": STUDY_ID,
        "title": STUDY_TITLE,
        "stage": "exploratory",
        "preregistration_sha256": PREREGISTRATION_SHA256,
        "source": (
            f"{STUDY_BRANCH}@{STUDY_COMMIT}: backend/nidp/analysis/shp_post_disclosure/"
            f"{{preregistration.json,panel.sql,study.py}}; frozen result in {REPORT_PATH}"
        ),
        "disclosure": (
            "RESEARCH ARTIFACT. NOT A PRODUCT FEATURE. Nothing on this screen is promoted to any "
            "score. No predictive score, no ranking, no buy/sell framing -- this reports what was "
            "tested and what the result was, nothing more. The verdict is INCONCLUSIVE: 10 "
            "formation quarters against a review floor of 12 independent blocks, declared below "
            "floor before any result was computed, so a POSITIVE verdict was unreachable by "
            "construction. No Nifty 500 TRI is used or implied -- this warehouse holds no "
            "total-return index, and the study's estimand is market-neutral by construction, so no "
            "benchmark is needed or shown."
        ),
        "verdict": "INCONCLUSIVE",
        "verdict_reason": (
            "At the primary horizon (20 sessions) the 95% CI [-0.8673, +2.9054] pp straddles zero "
            "and does not clear the +1.00 pp hurdle. The sample is also below the pre-registered "
            "review floor (10 of 12 blocks), which alone makes a POSITIVE verdict unreachable. The "
            "sign is additionally not robust across three reasonable specifications of the same "
            "grouping variable (see `robustness_20_sessions`)."
        ),
        "study_period": {"start": "2024-03-31", "end": "2026-06-30"},
        "quarters": 10,
        "review_floor_blocks": REVIEW_FLOOR_BLOCKS,
        "primary_horizon_sessions": PRIMARY_HORIZON,
        "secondary_horizons_sessions": list(SECONDARY_HORIZONS),
        "hurdle_pp": HURDLE_PP,
        "cost_pct_round_trip_per_leg": COST_PCT_PER_LEG,
        "cost_total_pp": COST_TOTAL_PP,
        "cost_note": (
            "Two legs, so the spread carries two round-trip costs (0.4937% each = 0.9874pp total). "
            "GROSS is the primary figure because this study measures information content, not a "
            "tradeable strategy; the net figure is always shown alongside, never hidden."
        ),
        "eligible_population": 1255,
        "eligible_population_note": (
            "1,255 (quarter, symbol) pairs survive all six pre-registered screens out of 1,881 raw "
            "pairs with a prior quarter. The PRIMARY estimand (delta(FII+DII)) additionally requires "
            "both components non-null in both quarters, which narrows this to 1,248 pairs; the "
            "delta(FII)-alone robustness variable uses the full 1,255."
        ),
        "eligible_primary_estimand_n": 1248,
        "not_yet_eligible": {
            "quarter": "2026-09-30",
            "reason": (
                "Not yet eligible for forward-return evaluation. This is the only formation quarter "
                "with a genuine NSE filing-broadcast timestamp, but its 25-day availability date "
                "(2026-10-25) has no trading session after it yet in this warehouse, so the forward "
                "window has not elapsed."
            ),
        },
        "excluded_quarters": [
            {"quarter": "2023-12-31", "reason": "Only 61 of the panel's names have a comparable prior quarter."},
        ],
        "benchmark_note": (
            "No Nifty 500 total-return index exists in this warehouse. nidp.index_eod's 'Nifty 500' "
            "row is a PRICE index with severe gaps -- 25.4% of 2025 sessions missing, largest gap 375 "
            "days -- and is never used or implied as a benchmark here. The study's primary estimand "
            "is market-neutral by construction: both legs (institutions-increased vs "
            "institutions-reduced) occupy the identical quarter and window, so the market factor "
            "cancels exactly and no index is needed."
        ),
        "robustness_note": (
            "The same 20-session spread is +1.07pp on delta(FII+DII) [primary], -0.47pp on delta(FII) "
            "alone, and +1.28pp on threshold-free terciles -- two signs from three defensible "
            "readings of 'institutional ownership change', a range wider than the hurdle itself. "
            "That is the signature of noise, not of a small effect measured imprecisely."
        ),
        "robustness_20_sessions": [dict(r) for r in _ROBUSTNESS_20_SESSIONS],
        "count": len(rows),
        "total": len(rows),
        "rows": rows,
    }
    return out


@router.get(
    "/evidence/post-disclosure-study",
    summary="The pre-registered post-disclosure forward-returns study: contract + real result, by horizon",
)
async def post_disclosure_study() -> Dict[str, Any]:
    return _payload()
