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
from functools import lru_cache
from typing import Any, Optional

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class RuleError(ValueError):
    """Raised for a missing rule set, an unresolvable date, or an ambiguous/absent match."""


def _safe_id(rule_id: str) -> str:
    if not rule_id or not _ID_RE.fullmatch(rule_id):
        raise RuleError(f"invalid rule id {rule_id!r}")
    return rule_id


@lru_cache(maxsize=None)
def _load_rule_file_cached(rule_id: str, rules_dir: str) -> dict:
    path = os.path.join(rules_dir, f"{_safe_id(rule_id)}.json")
    if not os.path.exists(path):
        raise RuleError(f"unknown rule set {rule_id!r} (looked in {rules_dir})")
    with open(path) as fh:
        return json.load(fh)


def load_rule_file(rule_id: str, *, rules_dir: str = RULES_DIR) -> dict:
    """Load and return the raw JSON for a rule id (the filename stem, no extension).

    PERFORMANCE: memoized by (rule_id, rules_dir) -- `research/charting/study/execute.py`'s own
    profiling (PERF-CONTROLS package) found this the single largest cost in a full study run:
    the same handful of rule files (nse-equity-statutory-v1, tax-equity-v1, zerodha-equity-v1)
    are re-read from disk and re-`json.load`ed on EVERY cost/tax computation -- hundreds of
    thousands of times across a 200-seed x ~2,132-symbol run, for content that never changes
    within a process. Every caller here only ever READS the returned dict (verified: no caller
    anywhere in research/costs or research/charting assigns into, pops from, or otherwise
    mutates the returned rule-file dict) -- so returning the SAME cached dict object on every
    call for the same (rule_id, rules_dir) is behaviourally identical to re-reading the file
    each time, just far cheaper. `rules_dir` is part of the cache key (not just `rule_id`) so a
    test pointed at its own synthetic tmp_path never collides with another test's or the real
    rules/ directory's cache entry -- each `tmp_path` pytest gives out is a distinct string, so a
    test that writes then later REWRITES a rule file at the SAME path (see
    tests/test_date_effectiveness.py's `test_a_null_rate_raises_loudly_instead_of_pricing_zero`,
    which uses its own fresh `tmp_path` rather than reusing `synthetic_rules_dir`'s) still gets
    a correct, uncached first read.
    """
    return _load_rule_file_cached(rule_id, rules_dir)


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


_RESOLVE_RECORD_CACHE: dict = {}


def resolve_record(records: list, on_date: dt.date, **selectors: Any) -> TimeBoxed:
    """The single record in `records` whose date window contains `on_date` and whose selector
    fields (segment=, exchange=, side=, ...) match. Raises RuleError if zero or more than one match
    -- an ambiguous rule table is a defect, never silently resolved by "pick the first".

    PERFORMANCE: memoized by `(id(records), on_date, selectors)`. `records` is a plain `list`,
    not hashable, so it cannot be a `functools.lru_cache` argument directly -- `id(records)` is
    used instead of the list's own contents. This is safe because every real caller's `records`
    list comes from a `load_rule_file()` return value (now itself cached -- see that function's
    docstring), which is held alive for the rest of the process by that cache, so its `id()` can
    never be reused by an unrelated, later-created list while this cache entry is still live (the
    one situation that would make an `id()`-keyed cache wrong). A caller passing its own literal
    list (as this module's tests do) is equally safe: that list is kept alive by whatever local/
    module variable already references it. Nothing here changes WHICH record is chosen -- the
    original linear scan runs unchanged on a cache miss; a hit returns the exact same `TimeBoxed`
    a fresh scan would have produced. A miss that raises `RuleError` is deliberately not cached
    (the scan is cheap on the rare error path, and caching a raised exception would need a second
    code path here for no real benefit)."""
    cache_key = (id(records), on_date, tuple(sorted(selectors.items())))
    cached = _RESOLVE_RECORD_CACHE.get(cache_key)
    if cached is not None:
        return cached
    hits = [r for r in records if _in_window(on_date, r) and _matches_selectors(r, selectors)]
    if not hits:
        raise RuleError(f"no rate covers {on_date} for {selectors!r}")
    if len(hits) > 1:
        raise RuleError(f"ambiguous rate table: {len(hits)} records cover {on_date} for {selectors!r}")
    rec = hits[0]
    result = TimeBoxed(
        record=rec,
        effective_from=_parse_date(rec.get("effective_from")),
        effective_to=_parse_date(rec.get("effective_to")),
        verified=bool(rec.get("verified", False)),
        source_url=rec.get("source_url"),
        note=rec.get("note"),
    )
    _RESOLVE_RECORD_CACHE[cache_key] = result
    return result


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
