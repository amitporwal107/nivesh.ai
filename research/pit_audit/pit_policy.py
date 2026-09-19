"""Enforceable feature-level PIT gate (plan §6-§7; G-05, AV-04, POL-01..06).

`is_feature_eligible` answers one question: may this feature value be used for a decision at `decision_at`?
It fails closed: anything unknown, unvalidated, unapproved or published after the cutoff is not eligible.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Optional

from contracts import PIT_CLASSES

POLICY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "policy.json")
HISTORICAL_OK = {"EXACT_PIT", "PIT_VALIDATED_RULE"}
RULE_KEYS = ("rule_id", "rule_version", "validation_sample_size", "validation_coverage", "evidence", "approval_status")
FEATURE_META_FIELDS = ("feature_name", "value", "source", "period_end", "available_at", "retrieved_at", "pit_class",
                       "point_in_time_validated", "data_version", "rule")


def load_policy(path: str = POLICY_FILE) -> dict:
    with open(path) as f:
        return json.load(f)


def _aware(t: Optional[dt.datetime], name: str) -> Optional[dt.datetime]:
    if t is not None and t.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return t


def rule_complete_and_approved(rule: Optional[dict]) -> bool:
    return bool(rule) and all(rule.get(k) not in (None, "", [], 0) for k in RULE_KEYS) and rule.get("approval_status") == "APPROVED"


def point_in_time_validated(pit_class: str, *, value_matches_filing: bool = False, availability_confidence: Optional[str] = None,
                            rule: Optional[dict] = None) -> bool:
    """PRD §9 flag, derived from the class and its evidence (POL-03)."""
    if pit_class not in PIT_CLASSES:
        raise ValueError(f"unknown PIT class {pit_class!r}")
    if pit_class == "EXACT_PIT":
        return bool(value_matches_filing) and availability_confidence == "HIGH"
    if pit_class == "PIT_VALIDATED_RULE":
        return rule_complete_and_approved(rule)
    return False


def is_feature_eligible(pit_class: str, available_at: Optional[dt.datetime], decision_at: Optional[dt.datetime],
                        point_in_time_validated: bool, *, feature_cutoff_at: Optional[dt.datetime] = None,
                        safety_margin: dt.timedelta = dt.timedelta(minutes=5), rule: Optional[dict] = None) -> tuple[bool, str]:
    """Historical-use gate. Inclusive after the margin: eligible iff available_at + margin <= cutoff."""
    if pit_class not in PIT_CLASSES:
        return False, f"unknown class {pit_class!r}"
    if not point_in_time_validated:
        return False, "not PIT-validated"
    if pit_class not in HISTORICAL_OK:
        return False, f"class {pit_class} is not eligible for historical use"
    _aware(available_at, "available_at"), _aware(decision_at, "decision_at"), _aware(feature_cutoff_at, "feature_cutoff_at")
    if available_at is None or decision_at is None:
        return False, "missing timestamp"
    cutoff = min(decision_at, feature_cutoff_at) if feature_cutoff_at else decision_at
    if available_at + safety_margin > cutoff:
        return False, "published after cutoff"
    if pit_class == "PIT_VALIDATED_RULE" and not rule_complete_and_approved(rule):
        return False, "rule not approved or incomplete"
    return True, "eligible"


def is_forward_eligible(category: str, decision_at: Optional[dt.datetime], retrieved_at: Optional[dt.datetime],
                        policy: Optional[dict] = None) -> tuple[bool, str]:
    """FORWARD_ONLY use (paper / forward validation only, never historical training): the value must have been
    retrieved by our own archive at or before the decision, and on/after the category's archive_start_at."""
    policy = policy or load_policy()
    cat = policy["categories"].get(category)
    if cat is None:
        return False, f"unknown category {category!r}"
    _aware(decision_at, "decision_at"), _aware(retrieved_at, "retrieved_at")
    if decision_at is None or retrieved_at is None:
        return False, "missing timestamp"
    start = cat.get("archive_start_at")
    if not start:
        return False, "no archive_start_at configured"
    if retrieved_at < dt.datetime.fromisoformat(start):
        return False, "retrieved before the archive started"
    if retrieved_at > decision_at:
        return False, "retrieved after the decision"
    return True, "forward-eligible"
