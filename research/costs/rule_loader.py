"""Generic, schema-agnostic loading and date-range resolution for the JSON rule sets in rules/.

Two JSON shapes are supported (see rules/*.json for concrete examples):

- "bundled_broker_plan_v1": a single-snapshot broker plan (zerodha-equity-v1.json,
  prd-illustrative-v1.json). One `effective_from` for the whole file; a fill dated before it is
  retroactive use of a later schedule and must be flagged, never silent.
- "statutory_time_series_v1" / "tax_time_series_v1": one or more named components, each a LIST of
  time-boxed records (effective_from inclusive, effective_to exclusive or null = open-ended).
  `resolve_record` picks the single record whose window contains the trade date and whose selector
  fields (segment/exchange/side/...) match.

Nothing here computes money; this module only answers "which rate applies on this date".
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class RuleError(ValueError):
    """Raised for a missing rule set, an unresolvable date, or an ambiguous/absent match."""


def _safe_id(rule_id: str) -> str:
    if not rule_id or not _ID_RE.fullmatch(rule_id):
        raise RuleError(f"invalid rule id {rule_id!r}")
    return rule_id


def load_rule_file(rule_id: str, *, rules_dir: str = RULES_DIR) -> dict:
    """Load and return the raw JSON for a rule id (the filename stem, no extension)."""
    path = os.path.join(rules_dir, f"{_safe_id(rule_id)}.json")
    if not os.path.exists(path):
        raise RuleError(f"unknown rule set {rule_id!r} (looked in {rules_dir})")
    with open(path) as fh:
        return json.load(fh)


def _parse_date(s: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(s) if s else None


@dataclass(frozen=True)
class TimeBoxed:
    """One resolved record plus the window it came from, for provenance in engine output."""

    record: dict
    effective_from: dt.date
    effective_to: Optional[dt.date]
    verified: bool
    source_url: Optional[str]
    note: Optional[str]


def _in_window(on_date: dt.date, rec: dict) -> bool:
    frm = _parse_date(rec.get("effective_from"))
    to = _parse_date(rec.get("effective_to"))
    if frm is not None and on_date < frm:
        return False
    if to is not None and on_date >= to:
        return False
    return True


def _matches_selectors(rec: dict, selectors: dict) -> bool:
    for key, want in selectors.items():
        have = rec.get(key)
        if have is None:
            continue  # the record doesn't discriminate on this key -> treat as a wildcard match
        if isinstance(have, str) and isinstance(want, str):
            if have.upper() == "BOTH" or have.upper() == want.upper():
                continue
            return False
        if have != want:
            return False
    return True


def resolve_record(records: list, on_date: dt.date, **selectors: Any) -> TimeBoxed:
    """The single record in `records` whose date window contains `on_date` and whose selector
    fields (segment=, exchange=, side=, ...) match. Raises RuleError if zero or more than one match
    -- an ambiguous rule table is a defect, never silently resolved by "pick the first"."""
    hits = [r for r in records if _in_window(on_date, r) and _matches_selectors(r, selectors)]
    if not hits:
        raise RuleError(f"no rate covers {on_date} for {selectors!r}")
    if len(hits) > 1:
        raise RuleError(f"ambiguous rate table: {len(hits)} records cover {on_date} for {selectors!r}")
    rec = hits[0]
    return TimeBoxed(
        record=rec,
        effective_from=_parse_date(rec.get("effective_from")),
        effective_to=_parse_date(rec.get("effective_to")),
        verified=bool(rec.get("verified", False)),
        source_url=rec.get("source_url"),
        note=rec.get("note"),
    )


def unverified_records(rule_json: dict) -> list[dict]:
    """Every record anywhere in a statutory/tax rule file with verified == False, flattened, each
    tagged with its component name -- used to produce the "list every rate marked unverified"
    deliverable without hand-maintaining a separate list."""
    out = []
    components = rule_json.get("components") or {}
    for comp_name, comp in components.items():
        for rec in comp.get("records", []):
            if not rec.get("verified", False):
                out.append({"component": comp_name, **rec})
    rates = rule_json.get("rates") or {}
    for rate_name, recs in rates.items():
        for rec in recs:
            if not rec.get("verified", False):
                out.append({"component": f"rates.{rate_name}", **rec})
    for rec in (rule_json.get("cess") or []):
        if not rec.get("verified", False):
            out.append({"component": "cess", **rec})
    surcharge = rule_json.get("surcharge") or {}
    for rec in surcharge.get("records", []):
        if not rec.get("verified", False):
            out.append({"component": "surcharge", **rec})
    if "holding_period" in rule_json and not rule_json["holding_period"].get("verified", False):
        out.append({"component": "holding_period", **rule_json["holding_period"]})
    return out
