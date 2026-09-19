"""Public-availability evidence rule AV-1 (plan §2; AV-01, AV-02, NSE-04).

Evidence items are (source, system, timestamp, precision). Independence is by OPERATOR: NSE's listing broadcast and
dissemination times and the NSE archive server's Last-Modified are all NSE-operated and count as ONE system ("NSE");
only a BSE announcement time (a different exchange) is independent. NSE-only agreement is reported as
MEDIUM + "nse_corroborated", never HIGH. A submission/creation time is corroboration of ordering only — it is never
public availability. The retrieval time is never evidence.

HIGH   : >= 2 independent systems with minute-or-better precision agree within 15 minutes →
         first_publicly_available_at = earliest agreeing time.
v1.1   : only ANNOUNCEMENT times (NSE broadcast/dissemination, BSE dissemination) set or agree on the time; a document's
         Last-Modified only corroborates (an archive file can exist before it is announced, so letting it set the time
         would move availability EARLIER - the leakage direction). HIGH precision = that of the earliest agreeing item.
MEDIUM : a broadcast/dissemination time with minute-or-better precision, not independently corroborated →
         available_at = that time (never EXACT_PIT).
LOW    : only day-precision or submission-side evidence → available_at = None (not usable without an approved rule).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from contracts import AVAILABILITY_RULE_ID, AVAILABILITY_RULE_VERSION, iso

AGREEMENT = dt.timedelta(minutes=15)
PUBLIC_SOURCES = {"nse_broadcast", "nse_dissemination", "bse_announcement", "document_last_modified"}
ANNOUNCEMENT_SOURCES = PUBLIC_SOURCES - {"document_last_modified"}
SUBMISSION_SOURCES = {"nse_submission", "nse_filename_creation"}
FINE = {"second", "minute"}


def evidence(source: str, system: str, ts: Optional[dt.datetime], precision: Optional[str]) -> Optional[dict]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        raise ValueError(f"naive timestamp for {source}")
    if source == "retrieved_at":
        raise ValueError("retrieval time is never availability evidence")
    return {"source": source, "system": system, "ts": ts, "precision": precision}


def assess(items: list[Optional[dict]]) -> dict:
    items = [e for e in items if e]
    public = [e for e in items if e["source"] in PUBLIC_SOURCES]
    fine = [e for e in public if e["precision"] in FINE]
    best_by_system: dict[str, dict] = {}
    for e in sorted((e for e in fine if e["source"] in ANNOUNCEMENT_SOURCES), key=lambda e: e["ts"]):
        best_by_system.setdefault(e["system"], e)          # earliest announcement time per system
    sys_items = sorted(best_by_system.values(), key=lambda e: e["ts"])
    agreeing = None
    for i, a in enumerate(sys_items):
        group = [b for b in sys_items if abs(b["ts"] - a["ts"]) <= AGREEMENT]
        if len(group) >= 2:
            agreeing = group
            break
    submitted = min((e["ts"] for e in items if e["source"] in SUBMISSION_SOURCES), default=None)
    broadcast = min((e["ts"] for e in fine if e["source"] in ("nse_broadcast", "nse_dissemination")), default=None)
    doc = min((e["ts"] for e in fine if e["source"] == "document_last_modified"), default=None)
    out = {"submitted_at": iso(submitted), "broadcast_at": iso(broadcast), "document_available_at": iso(doc),
           "availability_evidence": [{"source": e["source"], "system": e["system"], "ts": iso(e["ts"]),
                                      "precision": e["precision"]} for e in sorted(items, key=lambda e: e["ts"])],
           "rule_id": AVAILABILITY_RULE_ID, "rule_version": AVAILABILITY_RULE_VERSION}
    if agreeing:
        first = min(e["ts"] for e in agreeing)
        out.update(first_publicly_available_at=iso(first), available_at=iso(first), availability_confidence="HIGH",
                   timestamp_precision=next(e["precision"] for e in agreeing if e["ts"] == first))
    elif broadcast is not None:
        out.update(first_publicly_available_at=None, available_at=iso(broadcast), availability_confidence="MEDIUM",
                   timestamp_precision=next(e["precision"] for e in fine if e["ts"] == broadcast))
        out["nse_corroborated"] = doc is not None and abs(doc - broadcast) <= AGREEMENT
    else:
        coarse = [e for e in public if e["precision"] not in FINE]
        out.update(first_publicly_available_at=None, available_at=None, availability_confidence="LOW",
                   timestamp_precision=(coarse[0]["precision"] if coarse else None))
    if submitted and out["available_at"] and dt.datetime.fromisoformat(out["available_at"]) < submitted - AGREEMENT:
        out["contradiction"] = "public time precedes submission by more than 15 minutes"
        out["availability_confidence"] = "LOW"
        out["available_at"] = None
    return out
