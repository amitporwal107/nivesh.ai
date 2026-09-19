"""PIT audit data contracts (docs/ai_research/tpd3/data/PIT_AUDIT_ACCEPTANCE.md, plan revision 3).

Every record is a plain dict built by the helpers below so it serializes deterministically. Timestamps are ISO-8601
strings with the +05:30 offset, or None. None always means "unknown" — never a guessed value.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
PARSER_VERSION = "pit_audit-0.1.5"  # 0.1.1 F-3 clock, bank tags, "/-" URLs; 0.1.2 F-4 reInd, GI PAT, total EPS;
#                                      0.1.3 audit-side SHP reader (DEF-8, DEF-9); 0.1.4 SHP scale from the 100% identity (superseded); 0.1.5 SHP scale from the filing total
AVAILABILITY_RULE_ID, AVAILABILITY_RULE_VERSION = "AV-1", "1.1"  # 1.1: Last-Modified corroborates only

PIT_CLASSES = ("EXACT_PIT", "PIT_VALIDATED_RULE", "ESTIMATED_RULE", "RESTATED", "FORWARD_ONLY", "UNVERIFIED")
RECONCILIATION = ("MATCH_FIRST_FILED", "MATCH_LATEST_REVISION", "DIFFERS_EXPLAINED", "DIFFERS_UNEXPLAINED")
DIFFERENCE_TYPES = ("NO_DIFFERENCE", "ROUNDING", "UNIT_CONVERSION", "DEFINITION_DIFFERENCE", "PERIOD_MAPPING",
                    "FIRST_FILED_MATCH", "LATEST_REVISION_MATCH", "RESTATEMENT", "UNRESOLVED")
REVISION_TYPES = ("NONE", "FILING_REVISION", "RESTATEMENT", "NORMALIZATION", "PERIOD_CORRECTION", "PROVIDER_UPDATE")
CONFIDENCE = ("HIGH", "MEDIUM", "LOW")

FILING_FIELDS = ("symbol", "isin", "exchange", "listing", "filing_id", "period_start", "period_end", "filing_type",
                 "statement_type", "consolidation_type", "submitted_at", "broadcast_at", "exchange_disseminated_at",
                 "document_created_at", "revised_at", "revision_flag", "retrieved_at", "source_url", "document_url",
                 "raw_row", "raw_row_sha256", "parser_version")
METRIC_FIELDS = ("symbol", "filing_id", "period_start", "period_end", "context_role", "metric_name", "metric_value",
                 "unit", "consolidation_type", "document_url", "document_sha256", "parser_version", "retrieved_at")


def iso(t: Optional[dt.datetime]) -> Optional[str]:
    if t is None:
        return None
    if t.tzinfo is None:
        raise ValueError("naive datetime: every timestamp in the audit must carry a timezone")
    return t.astimezone(IST).isoformat(timespec="seconds")


def _default(o: Any):
    if isinstance(o, dt.datetime):
        return iso(o)
    if isinstance(o, dt.date):
        return o.isoformat()
    raise TypeError(f"not serializable: {type(o).__name__}")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 text."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def make_record(fields: tuple, **kw) -> dict:
    """A record with exactly `fields` as keys; unknown keys are an error, missing keys are explicit None."""
    extra = set(kw) - set(fields)
    if extra:
        raise KeyError(f"unknown fields: {sorted(extra)}")
    return {f: kw.get(f) for f in fields}


def filing_record(**kw) -> dict:
    rec = make_record(FILING_FIELDS, **kw)
    if rec["raw_row"] is not None and rec["raw_row_sha256"] is None:
        rec["raw_row_sha256"] = sha256_json(rec["raw_row"])
    rec["parser_version"] = rec["parser_version"] or PARSER_VERSION
    return rec


def metric_record(**kw) -> dict:
    rec = make_record(METRIC_FIELDS, **kw)
    rec["parser_version"] = rec["parser_version"] or PARSER_VERSION
    return rec
