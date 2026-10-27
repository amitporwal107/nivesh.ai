"""The AI idea scorecard: the Phase 4.3 pre-registered study, served as committed (GET /api/desk/idea-scorecard).

WHAT IT SERVES
The study's numbers come from ONE file, `research/p4_adx_rs/results_20261027/result.json`, written by
`research/p4_adx_rs/run_study.py`. Nothing here computes a statistic: each figure is copied from that file, nulls and
negatives included. The verdict and the RS63 status are fixed sentences taken from the study's write-up
(docs/ai_research/P4_ADX_RS_RESULTS.md). They are served only while the file still supports them: no arm adopted, and
no B0 Newey-West t of 2 or more in any split. Otherwise the answer is `ScorecardUnavailable("scorecard_out_of_date")`.

WHAT IT REFUSES
A missing, unreadable or incomplete `result.json` raises ScorecardUnavailable with the reason; the route answers 503.
A missing write-up document is reported as `present: false` and does not block the answer. Staging mounts
`research/` into the backend container but not `docs/`.

Wording: the scanner produces IDEAS. Nothing here calls them picks or recommendations (SEBI).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

#: The repository root: backend/services/ -> backend/ -> the root (/app inside the backend container).
REPO_ROOT = Path(__file__).resolve().parents[2]

STUDY_ID = "p4_adx_rs"
STUDY_PHASE = "4.3"
STUDY_TITLE = "ADX and relative-strength variants of the AI scanner score"
RUN_DATE = "2026-10-27"                        # the results directory's date; the run is recorded in the write-up
RESULT_PATH = "research/p4_adx_rs/results_20261027/result.json"
DOCUMENTS = (
    ("docs/ai_research/P4_ADX_RS_PREREGISTRATION.md", "the pre-registered rule"),
    ("docs/ai_research/P4_ADX_RS_RESULTS.md", "the write-up the verdict and the RS63 status are taken from"),
    ("docs/ai_research/P4_RS63_CONFIRMATION_PREREGISTRATION.md", "the RS63 confirmation test, registered, not yet run"),
)
SPLITS = ("discovery", "validation", "test")
BASELINE = "B0"
ARM_ORDER = ("B0", "A1", "A2", "A3")
ARM_LABELS = {
    "B0": "the current ranking",
    "A1": "current ranking + an ADX term",
    "A2": "RS63 vs Nifty 50 replaces the sector term",
    "A3": "A2 + an ADX term",
}
VERDICT = "keep B0; the current ranking shows no measurable skill"
RS63_ARM = "A2"
RS63_STATUS = "promising, awaiting its pre-registered confirmation"
DISCLAIMER = ("Ideas, not recommendations. The rank orders ideas; this study found no measurable ranking skill, so the "
              "rank is not a prediction.")
UNITS = {
    "rank_ic": "mean daily Spearman rank correlation between the score and the 10-session excess return",
    "nw_t": "Newey-West t-statistic, lag 9",
    "permutation_p": "one-sided block-permutation p of the difference with B0 (10-session blocks, 1,000 draws)",
    "top_decile_net_mean": "mean 10-session return of the arm's highest-scored 10%, net of the study's costs, as a "
                           "fraction (-0.00992 = -0.99%)",
    "top_decile_hit_rate": "share of the top decile with an excess return above 0, as a fraction",
    "coverage_top_movers_outside_universe": "share of each day's top-decile forward movers outside the scanner's "
                                            "universe, as a fraction",
}
OUTCOME = "10-session excess return, entry at the next session's open"
#: |t| at or above this in any split would contradict "no measurable skill"; the fixed text is then not served.
SKILL_T = 2.0


class ScorecardUnavailable(RuntimeError):
    """The study cannot be served as committed. `code` is scorecard_unavailable or scorecard_out_of_date."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code, self.reason = code, reason

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "reason": self.reason, "study_id": STUDY_ID}


def _source(root: Path, rel: str, role: str) -> Dict[str, Any]:
    path = root / rel
    try:
        data = path.read_bytes()
    except OSError as e:
        return {"path": rel, "role": role, "present": False, "sha256": None, "bytes": None,
                "reason": f"not readable here ({type(e).__name__})"}
    return {"path": rel, "role": role, "present": True, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "reason": None}


def _need(obj: Any, *keys: str) -> Any:
    """obj[k1][k2]..., or ScorecardUnavailable naming the missing key."""
    cur = obj
    for i, k in enumerate(keys):
        if not isinstance(cur, dict) or k not in cur:
            raise ScorecardUnavailable("scorecard_unavailable",
                                       f"{RESULT_PATH} has no '{'.'.join(keys[:i + 1])}'")
        cur = cur[k]
    return cur


def _arm(name: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    ic = raw.get("ic") or {}
    diff = raw.get("ic_diff_vs_B0")
    return {
        "arm": name,
        "label": ARM_LABELS.get(name),
        "rank_ic": {"mean": ic.get("mean"), "nw_t": ic.get("t"), "se": ic.get("se"), "n": ic.get("n")},
        "vs_b0": None if diff is None else {
            "delta_ic": diff.get("mean"), "nw_t": diff.get("t"), "se": diff.get("se"), "n": diff.get("n"),
            "permutation_p": diff.get("perm_p_one_sided"),
            "by_regime": {reg: {"n": v.get("n"), "delta_ic": v.get("mean"), "nw_t": v.get("t")}
                          for reg, v in (diff.get("by_regime") or {}).items() if isinstance(v, dict)},
        },
        "permutation_p": None if diff is None else diff.get("perm_p_one_sided"),
        "top_decile_net_mean": raw.get("top_decile_net_mean"),
        "top_decile_hit_rate": raw.get("top_hit_rate"),
        "top_minus_median": raw.get("top_minus_median"),
    }


def _ordered(arms: Dict[str, Any]) -> List[str]:
    return [a for a in ARM_ORDER if a in arms] + sorted(a for a in arms if a not in ARM_ORDER)


def _check_text(result: Dict[str, Any]) -> None:
    """The fixed verdict is true only while no arm is adopted and B0 shows no t of SKILL_T or more in any split."""
    decision = _need(result, "decision")
    if decision.get("adopted") is not None:
        raise ScorecardUnavailable("scorecard_out_of_date", f"{RESULT_PATH} adopts arm {decision.get('adopted')!r}; "
                                                            "the served verdict 'keep B0' would be false")
    for split in SPLITS:
        t = _need(result, "splits", split, "arms", BASELINE, "ic").get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool):
            raise ScorecardUnavailable("scorecard_unavailable", f"{RESULT_PATH}: B0's {split} t is not a number")
        if abs(t) >= SKILL_T:
            raise ScorecardUnavailable("scorecard_out_of_date", f"{RESULT_PATH}: B0's {split} t is {t}; the served "
                                                                "text 'no measurable skill' would be false")


def load(root: Optional[Path] = None) -> Dict[str, Any]:
    """The scorecard, read from the committed files under `root` (default: the repository root)."""
    root = Path(root) if root is not None else REPO_ROOT
    path = root / RESULT_PATH
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ScorecardUnavailable("scorecard_unavailable", f"{RESULT_PATH} is not present on this server")
    except OSError as e:
        raise ScorecardUnavailable("scorecard_unavailable", f"{RESULT_PATH} could not be read ({type(e).__name__})")
    try:
        result = json.loads(raw)
    except ValueError:
        raise ScorecardUnavailable("scorecard_unavailable", f"{RESULT_PATH} is not valid JSON")
    if not isinstance(result, dict):
        raise ScorecardUnavailable("scorecard_unavailable", f"{RESULT_PATH} is not a JSON object")
    _check_text(result)

    splits = []
    for name in SPLITS:
        arms = _need(result, "splits", name, "arms")
        s = result["splits"][name]
        bounds = _need(result, "bounds", name)
        if not isinstance(arms, dict) or BASELINE not in arms or not all(isinstance(v, dict) for v in arms.values()):
            raise ScorecardUnavailable("scorecard_unavailable", f"{RESULT_PATH}: the {name} split's arms are incomplete")
        splits.append({
            "name": name,
            "from": bounds[0] if isinstance(bounds, list) and len(bounds) == 2 else None,
            "to": bounds[1] if isinstance(bounds, list) and len(bounds) == 2 else None,
            "dates": s.get("dates"),
            "names_per_date_median": s.get("names_per_date_median"),
            "coverage_top_movers_outside_universe": s.get("coverage_top_movers_outside_universe"),
            "arms": [_arm(a, arms[a]) for a in _ordered(arms)],
        })
    decision = _need(result, "decision")
    watermark = result.get("watermark") or {}
    sources = [{"path": RESULT_PATH, "role": "every number on this scorecard", "present": True,
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "reason": None}]
    sources += [_source(root, rel, role) for rel, role in DOCUMENTS]
    return {
        "study": {"id": STUDY_ID, "phase": STUDY_PHASE, "title": STUDY_TITLE, "run_date": RUN_DATE,
                  "registration_commit": result.get("registration_commit"), "code_sha": result.get("code_sha"),
                  "signal_dates": result.get("signal_dates"), "sessions": result.get("sessions"),
                  "input_hash": watermark.get("input_hash"), "bar_rows": watermark.get("bar_rows"),
                  "outcome": OUTCOME},
        "splits": splits,
        "decision": {"verdict": VERDICT, "study_verdict": decision.get("verdict"), "adopted": decision.get("adopted"),
                     "per_arm": decision.get("per_arm")},
        "rs63": {"arm": RS63_ARM, "label": ARM_LABELS[RS63_ARM], "status": RS63_STATUS,
                 "adopted": (decision.get("per_arm") or {}).get(RS63_ARM, {}).get("adopt"),
                 "confirmation": DOCUMENTS[2][0]},
        "coverage": {s["name"]: {"top_movers_outside_universe": s["coverage_top_movers_outside_universe"],
                                 "names_per_date_median": s["names_per_date_median"]} for s in splits},
        "units": UNITS,
        "disclaimer": DISCLAIMER,
        "sources": sources,
    }
