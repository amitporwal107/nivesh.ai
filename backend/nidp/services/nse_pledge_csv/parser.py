"""Parser for NSE's SAST pledged-data CSV (CF-SAST-Pledged-Data-<DD-Mon-YYYY>.csv).

Why a CSV path exists at all: the equivalent API, ``/api/corporate-pledgedata``,
is served behind NSE's edge, which 403s this platform's egress. Verified
2026-08-19 — a browser UA, cookie priming from the homepage and a correct Referer
all still return "Access Denied", from two unrelated networks. That is an IP-level
block, so ``nse_pledge_data`` cannot fetch on a schedule and the file is downloaded
by hand from:

    https://www.nseindia.com/companies-listing/corporate-filings-pledged-data

This module turns that file into ``nidp.shareholding_pattern`` rows. It is the only
source of promoter-pledge data the platform has: measured 2026-08-19,
``promoter_pledged_pct`` was NULL for all 8,955 existing rows.

THREE TRAPS IN THIS FILE, each of which would produce a confidently wrong number:

1. **Empty is not zero.** Some rows carry an empty encumbrance field rather than
   ``0.00`` (e.g. "Alchemist Limited", "Metkore Alloys & Industries Limited"). A
   company with no disclosure is NOT a company with no pledge, and coercing it to
   0 would show it as clean on exactly the screen built to find pledged promoters.
   Empty parses to ``None``.

2. **Company names are not unique.** "Future Enterprises Limited", "GACM
   Technologies Limited" and "Jain Irrigation Systems Limited" each appear TWICE
   with different issued-share counts — separate series/DVR lines. Since the join
   key to NIDP is the name, an ambiguous name cannot be resolved to one symbol, so
   those rows are REJECTED and reported rather than silently overwriting each other.

3. **Two different pledge measures.** ``% OF PROMOTER SHARES (X/A)`` and
   ``(%) PLEDGE / DEMAT`` are different quantities: A2Z Infra shows 99.68% of
   promoter holding encumbered but 31.11% pledge/demat. They are kept in separate
   fields and never conflated.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

SOURCE_NAME = "NSE_SAST_CSV"

# Header -> our field. Matched on a normalised header so NSE's irregular spacing
# and the long explanatory column titles do not have to be reproduced exactly.
_COLUMNS = {
    "nameofcompany":                                        "company_name",
    "totalnoofissuedsharesabc":                             "total_shares",
    "totalpromoterholdingnoofsharesa":                      "promoter_shares",
    "totalpromoterholdingaabc":                             "promoter_pct",
    "totalpublicholdingb":                                  "public_shares",
    "promotersharesencumberedasoflastquarternoofsharesx":   "pledged_shares",
    "promotersharesencumberedasoflastquarterofpromotersharesxa":        "promoter_pledged_pct",
    "promotersharesencumberedasoflastquarteroftotalsharesxabc":         "promoter_pledged_to_total_pct",
    "noofsharespledgedinthedepositorysystemnoofsharespledged":          "depository_pledged_shares",
    "noofsharespledgedinthedepositorysystemtotalnoofdematshares":       "demat_shares",
    "pledgedemat":                                          "pledge_demat_pct",
    "broadcastdate":                                        "broadcast_at",
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def normalise_company_name(name: str) -> str:
    """Join key to ``nidp.sector_master.company_name``.

    Both sides carry the same registrar-style legal name ("Laurus Labs Limited"),
    but punctuation and spacing differ, so both are reduced to upper-case
    alphanumerics. Measured against nidp_staging 2026-08-19, 40 of 40 sampled names
    resolved — a hand-picked large-cap sample, so it establishes that the FORMAT
    matches, not a coverage figure for a whole file. Run the ingester's --dry-run for
    the real split. Known limitation: "&" does not fold into "AND", so those names go
    to `unresolved` rather than to the wrong symbol.
    """
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _num(raw: Any) -> Optional[float]:
    """Empty -> None. See trap 1: a missing disclosure must not read as 0.00."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _bigint(raw: Any) -> Optional[int]:
    v = _num(raw)
    return None if v is None else int(v)


def _parse_ts(raw: Any) -> Optional[datetime]:
    """NSE stamps these as '18-Aug-2026 16:31:28'."""
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def last_completed_quarter_end(on: date) -> date:
    """The quarter the encumbrance figures describe.

    The column is "PROMOTER SHARES ENCUMBERED **AS OF LAST QUARTER**", so a file
    broadcast in August 2026 reports the quarter ended 2026-06-30. Dating these
    rows by the broadcast day instead would invent a quarter that no filing covers
    and would not line up with the exchange SHP rows already in the table.
    """
    q_first_month = ((on.month - 1) // 3) * 3 + 1          # 1, 4, 7, 10
    prev_q_end_month = q_first_month - 1                    # 0, 3, 6, 9
    year = on.year if prev_q_end_month > 0 else on.year - 1
    month = prev_q_end_month or 12
    day = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return date(year, month, day)


@dataclass
class ParseResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    duplicate_names: list[str] = field(default_factory=list)
    unparsable: list[str] = field(default_factory=list)
    period_end: Optional[date] = None

    @property
    def summary(self) -> str:
        return (f"{len(self.rows)} usable rows, period_end={self.period_end}, "
                f"{len(self.duplicate_names)} ambiguous name(s) rejected, "
                f"{len(self.unparsable)} unparsable")


def parse_sast_csv(text: str, *, file_date: Optional[date] = None) -> ParseResult:
    """Parse the SAST pledged-data CSV into shareholding_pattern-shaped dicts.

    ``file_date`` overrides the period derivation; by default it comes from the
    BROADCAST DATE on the rows themselves, which is what the exchange actually
    stamped rather than whatever the file happened to be renamed to.
    """
    # The file is served with a UTF-8 BOM; utf-8-sig strips it, and without that
    # the first header becomes "﻿NAME OF COMPANY" and never matches.
    if text.startswith("﻿"):
        text = text[1:]

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return ParseResult()

    header_map = {}
    for h in reader.fieldnames:
        key = _COLUMNS.get(_norm_header(h))
        if key:
            header_map[h] = key
    missing = {"company_name", "promoter_pledged_pct"} - set(header_map.values())
    if missing:
        raise ValueError(f"SAST CSV is missing required column(s): {sorted(missing)}")

    staged: dict[str, dict[str, Any]] = {}
    dupes: set[str] = set()
    result = ParseResult()
    broadcasts: list[datetime] = []

    for raw in reader:
        rec = {field_: raw.get(header) for header, field_ in header_map.items()}
        name = (rec.get("company_name") or "").strip()
        if not name:
            continue
        key = normalise_company_name(name)
        if not key:
            result.unparsable.append(name)
            continue

        ts = _parse_ts(rec.get("broadcast_at"))
        if ts:
            broadcasts.append(ts)

        row = {
            "company_name": name,
            "name_key": key,
            "total_shares": _bigint(rec.get("total_shares")),
            "promoter_shares": _bigint(rec.get("promoter_shares")),
            "public_shares": _bigint(rec.get("public_shares")),
            "promoter_pct": _num(rec.get("promoter_pct")),
            # Trap 3: these three are distinct quantities, kept apart on purpose.
            "pledged_shares": _bigint(rec.get("pledged_shares")),
            "promoter_pledged_pct": _num(rec.get("promoter_pledged_pct")),
            "promoter_pledged_to_total_pct": _num(rec.get("promoter_pledged_to_total_pct")),
            "pledge_demat_pct": _num(rec.get("pledge_demat_pct")),
            "broadcast_at": ts,
        }

        # Trap 2: a repeated name cannot be resolved to a single symbol.
        if key in staged:
            dupes.add(name)
            continue
        staged[key] = row

    for name in sorted(dupes):
        staged.pop(normalise_company_name(name), None)
    result.duplicate_names = sorted(dupes)
    result.rows = list(staged.values())

    basis = file_date or (max(broadcasts).date() if broadcasts else None)
    result.period_end = last_completed_quarter_end(basis) if basis else None
    for row in result.rows:
        row["period_end"] = result.period_end
        row["source"] = SOURCE_NAME
    return result


def pledge_stats(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Distribution summary — used to prove the ingest is not degenerate.

    ``pb`` taught this lesson: 177 non-null values that were all 0.00 read as 7.5%
    coverage under a plain null-rate check. Distinct-count is the real test.
    """
    vals = [r.get("promoter_pledged_pct") for r in rows]
    present = [v for v in vals if v is not None]
    nonzero = [v for v in present if v > 0]
    return {
        "rows": len(vals),
        "with_pledge_pct": len(present),
        "distinct_values": len(set(present)),
        "nonzero": len(nonzero),
        "zero": len(present) - len(nonzero),
        "max": max(present) if present else None,
    }
