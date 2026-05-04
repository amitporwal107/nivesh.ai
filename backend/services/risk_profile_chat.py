"""Conversational Risk Profiling — replaces the 12-question form.

A 5-step scenario chat that produces the same `risk_profile` shape the
rest of the engine consumes. The questions are framed as concrete loss
scenarios rather than abstract "rate your tolerance" sliders, because
behavioural research shows users self-report higher tolerance on sliders
than they actually exhibit during real drawdowns.

State machine:

    /risk-profile/start                        → returns {session_id, first_question}
    /risk-profile/{session_id}/answer          → returns {next_question | result}

Each session is short-lived (TTL 30 min) and stored in-memory. Production
should persist to mongo; we keep it simple for the MVP.

Output (`/answer` returns this once the last question is answered):

    {
      "complete": true,
      "session_id": "...",
      "score": 62,                            # 0-100, higher = more aggressive
      "category": "moderate",                 # conservative | moderate | aggressive
      "persona": "Balanced",                  # display label
      "loss_tolerance_pct": 20,               # max drawdown they'd absorb
      "horizon_years": 12,                    # from the horizon question
      "answers": [...],                       # full Q+A trail for audit
      "narrative": "Based on your answers...", # 2-3 sentence summary
    }

Persistence: caller decides whether to write the result onto user_profiles.
This keeps the module pure compute / state transitions.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Question library ───────────────────────────────────────────────────
# Each question carries weighted answer choices. The total possible score
# across all 5 questions is 100; calibrated so a typical "Moderate" investor
# lands in the 40-70 band.
QUESTIONS: List[Dict[str, Any]] = [
    {
        "id": "horizon",
        "section": "Time Horizon",
        "prompt": "When do you plan to use this money?",
        "subtitle": "Longer horizons absorb volatility better.",
        "input_type": "choice",
        "choices": [
            {"label": "Within 1 year",        "value": "lt_1y",  "score": 0,  "horizon_years": 0.5},
            {"label": "1 to 3 years",         "value": "1_3y",   "score": 5,  "horizon_years": 2},
            {"label": "3 to 7 years",         "value": "3_7y",   "score": 12, "horizon_years": 5},
            {"label": "7 to 15 years",        "value": "7_15y",  "score": 20, "horizon_years": 10},
            {"label": "More than 15 years",   "value": "15y_plus","score": 25,"horizon_years": 20},
        ],
    },
    {
        "id": "loss_scenario",
        "section": "Loss Tolerance",
        "prompt": "Your ₹10 lakh investment drops to ₹7 lakh in 3 months. What do you do?",
        "subtitle": "Panic selling is the #1 wealth destroyer — be honest.",
        "input_type": "choice",
        "choices": [
            {"label": "Sell everything to stop further losses",                 "value": "sell_all",      "score": 0,  "loss_tolerance_pct": 5},
            {"label": "Sell some — switch the rest to safer investments",       "value": "sell_partial",  "score": 5,  "loss_tolerance_pct": 10},
            {"label": "Hold and wait — markets recover",                        "value": "hold",          "score": 15, "loss_tolerance_pct": 25},
            {"label": "Invest more at the lower price",                         "value": "buy_more",      "score": 25, "loss_tolerance_pct": 40},
        ],
    },
    {
        "id": "experience",
        "section": "Investment Experience",
        "prompt": "How much investing have you done in the last 5 years?",
        "subtitle": "Experience builds emotional capital for downturns.",
        "input_type": "choice",
        "choices": [
            {"label": "First-time investor",                          "value": "none",     "score": 0},
            {"label": "Mostly FDs / RDs / PPF",                       "value": "fd",       "score": 4},
            {"label": "Some mutual funds",                            "value": "some_mf",  "score": 10},
            {"label": "Diversified across MFs / stocks / debt",       "value": "diverse",  "score": 18},
            {"label": "Active investor including international / alts","value": "active",   "score": 22},
        ],
    },
    {
        "id": "income_stability",
        "section": "Capacity",
        "prompt": "How stable is your monthly income?",
        "subtitle": "Stable income = ability to absorb portfolio drawdowns without selling.",
        "input_type": "choice",
        "choices": [
            {"label": "Variable — could drop sharply (gig / business)",  "value": "variable", "score": 2},
            {"label": "Mostly stable — some bonus variability",          "value": "stable",   "score": 10},
            {"label": "Very stable — salaried with low risk of loss",    "value": "very_stable","score": 14},
        ],
    },
    {
        "id": "behaviour_check",
        "section": "Behavioural Pattern",
        "prompt": "When the market moves a lot, how often do you check your portfolio?",
        "subtitle": "Frequent checking correlates strongly with panic selling.",
        "input_type": "choice",
        "choices": [
            {"label": "Multiple times a day",       "value": "intraday",  "score": 0},
            {"label": "Once a day",                 "value": "daily",     "score": 4},
            {"label": "Few times a week",           "value": "weekly",    "score": 9},
            {"label": "Monthly or less",            "value": "monthly",   "score": 14},
        ],
    },
]

MAX_SCORE = sum(max(c["score"] for c in q["choices"]) for q in QUESTIONS)

# Persona buckets — the score thresholds align with target_allocator's
# {conservative, moderate, aggressive} taxonomy so the rest of the engine
# can consume the result without translation.
PERSONA_BANDS: List[Dict[str, Any]] = [
    {"min": 0,   "max": 35,  "category": "conservative", "persona": "Capital Preserver",
     "summary": "Your priority is protecting what you have. Volatility hurts more than potential upside excites."},
    {"min": 36,  "max": 60,  "category": "moderate",     "persona": "Balanced",
     "summary": "You can stomach moderate ups and downs in exchange for steady long-term growth."},
    {"min": 61,  "max": 85,  "category": "moderate",     "persona": "Growth-Tilted",
     "summary": "You're comfortable with sharper drawdowns when you believe in the long-term thesis."},
    {"min": 86,  "max": 100, "category": "aggressive",   "persona": "Wealth Builder",
     "summary": "You actively seek growth and treat market crashes as buying opportunities."},
]


# ── In-memory session store ────────────────────────────────────────────
# Each session: {session_id, user_id, created_at, expires_at, answers: [...]}
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSION_TTL = timedelta(minutes=30)


def _gc_sessions():
    """Drop expired sessions. Cheap — runs on every start/answer call."""
    now = datetime.now(timezone.utc)
    expired = [sid for sid, s in _SESSIONS.items() if s["expires_at"] < now]
    for sid in expired:
        _SESSIONS.pop(sid, None)


def _persona_for(score: float) -> Dict[str, str]:
    for band in PERSONA_BANDS:
        if band["min"] <= score <= band["max"]:
            return {
                "category": band["category"],
                "persona": band["persona"],
                "summary": band["summary"],
            }
    return {"category": "moderate", "persona": "Balanced",
            "summary": "Default profile — please complete the questionnaire."}


def _public_question(q: Dict[str, Any], idx: int, total: int) -> Dict[str, Any]:
    """Strip internal scoring fields from a question before sending to client."""
    return {
        "id": q["id"],
        "section": q["section"],
        "prompt": q["prompt"],
        "subtitle": q.get("subtitle"),
        "input_type": q["input_type"],
        "choices": [
            {"label": c["label"], "value": c["value"]} for c in q["choices"]
        ],
        "step": idx + 1,
        "total_steps": total,
    }


# ── Public API ─────────────────────────────────────────────────────────
def start_session(user_id: str) -> Dict[str, Any]:
    """Begin a new risk-profile chat. Returns the session id + first question."""
    _gc_sessions()
    sid = f"rp_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    _SESSIONS[sid] = {
        "session_id": sid,
        "user_id": user_id,
        "created_at": now,
        "expires_at": now + _SESSION_TTL,
        "answers": [],
    }
    return {
        "session_id": sid,
        "question": _public_question(QUESTIONS[0], 0, len(QUESTIONS)),
        "intro": "Let's build your risk profile in 5 quick scenarios. Honest answers = better recommendations.",
    }


def submit_answer(session_id: str, question_id: str, value: str) -> Dict[str, Any]:
    """Record one answer; return the next question OR the final result."""
    _gc_sessions()
    sess = _SESSIONS.get(session_id)
    if not sess:
        return {"error": "session_not_found",
                "message": "This risk-profile session expired or doesn't exist. Start over."}

    # Resolve the question + choice
    q_idx = next((i for i, q in enumerate(QUESTIONS) if q["id"] == question_id), -1)
    if q_idx < 0:
        return {"error": "question_not_found", "message": f"Unknown question id: {question_id}"}
    q = QUESTIONS[q_idx]
    choice = next((c for c in q["choices"] if c["value"] == value), None)
    if not choice:
        return {"error": "invalid_choice",
                "message": f"Choice '{value}' is not valid for question '{question_id}'."}

    sess["answers"].append({
        "question_id": question_id,
        "value": value,
        "label": choice["label"],
        "score": choice["score"],
        # Carry through any extra metadata the question attaches to choices
        # (e.g. horizon_years on the horizon Q, loss_tolerance_pct on loss Q)
        **{k: v for k, v in choice.items() if k not in ("label", "value", "score")},
    })

    next_idx = q_idx + 1
    if next_idx < len(QUESTIONS):
        return {
            "complete": False,
            "session_id": session_id,
            "question": _public_question(QUESTIONS[next_idx], next_idx, len(QUESTIONS)),
        }

    # All questions answered — compute the result.
    return _finalize(sess)


def _finalize(sess: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the final risk profile from the recorded answers."""
    raw = sum(a["score"] for a in sess["answers"])
    score_100 = round(raw / max(1, MAX_SCORE) * 100, 1)
    persona = _persona_for(score_100)

    # Pull the carry-through metadata into top-level fields
    horizon_years = next(
        (a.get("horizon_years") for a in sess["answers"] if a.get("horizon_years") is not None),
        None,
    )
    loss_tolerance_pct = next(
        (a.get("loss_tolerance_pct") for a in sess["answers"] if a.get("loss_tolerance_pct") is not None),
        None,
    )

    narrative = (
        f"You scored {score_100:.0f}/100 on our risk assessment — "
        f"placing you in the **{persona['persona']}** band. "
        f"{persona['summary']} "
        + (f"Your stated loss tolerance is around {loss_tolerance_pct}% drawdown. "
           if loss_tolerance_pct is not None else "")
        + (f"Investment horizon: ~{int(horizon_years)} years."
           if horizon_years is not None else "")
    )

    return {
        "complete": True,
        "session_id": sess["session_id"],
        "score": score_100,
        "category": persona["category"],
        "persona": persona["persona"],
        "loss_tolerance_pct": loss_tolerance_pct,
        "horizon_years": horizon_years,
        "answers": sess["answers"],
        "narrative": narrative,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def persist_profile(user_id: str, result: Dict[str, Any]) -> None:
    """Write the final risk-profile result onto user_profiles.

    Mirrors the existing shape `target_allocator` reads:
        user_profiles.risk_profile = {category, score, persona, ...}

    Non-blocking — caller can fire-and-forget. Failures logged, not raised.
    """
    if not result.get("complete"):
        return
    try:
        from deps import db
        await db.user_profiles.update_one(
            {"user_id": user_id},
            {"$set": {
                "risk_profile": {
                    "category": result["category"],
                    "score": result["score"],
                    "persona": result["persona"],
                    "loss_tolerance_pct": result.get("loss_tolerance_pct"),
                    "horizon_years": result.get("horizon_years"),
                    "narrative": result["narrative"],
                    "answers": result["answers"],
                    "source": "conversational_chat",
                    "computed_at": result["computed_at"],
                },
            }},
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("persist risk profile failed for %s: %s", user_id, e)
