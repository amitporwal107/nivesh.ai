"""Import every CAS statement found in Gmail: keep each as its own snapshot, and decide
which one the live portfolio shows.

Backs the opt-in ``all_statements`` mode of POST /api/onboarding/gmail/auto-import
(routes/onboarding_gmail.py). The default import is not touched by this module.

Product rules (decided 2026-10-14):

  * The portfolio is the latest CONSOLIDATED statement (NSDL / CDSL). A CAMS / KFintech
    statement holds mutual funds only: it is stored as history and never replaces a
    consolidated portfolio. Only an investor with no consolidated statement at all is
    shown the latest mutual-fund one.
  * Twelve months of Gmail are scanned (services.gmail_service.list_cas_history).
  * No model call is made here. The default import asks a vision model for the statement
    date and the monthly value table of CDSL / fallback layouts; this path takes the date
    from the file name or the email subject instead and stores the holdings only.
  * At most MAX_STATEMENTS_PER_CALL statements are read per call; the rest are counted in
    ``remaining`` and picked up by the next call.

How a statement is recognised as already stored, cheapest check first:

  1. the Gmail message id is on a stored snapshot      → nothing is downloaded
  2. the PDF's SHA-256 is on a stored snapshot         → downloaded, not parsed
  3. a snapshot exists for the statement's own date    → parsed; the higher-priority source
     (NSDL > CDSL > CAMS > KFintech) is the one kept

Statements are stored through services.cas_snapshot_engine.store_cas_snapshot, which only
stores. The live portfolio changes only through the ``mount`` callable the route passes in
(the same save the default import makes), and only when a statement read in this call is
newer than the statement on file — an older statement never reaches it.

An email that could not be read is remembered in ``gmail_imports`` (source "cas_history",
status "failed") so that the next call reads the emails not yet tried before retrying it.
"""
from __future__ import annotations

import asyncio
import calendar
import copy
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from helpers import holdings_reconcile
from services import cas_api_client, cas_snapshot_engine, gmail_service
from services.cas_period_detector import detect_period_from_filename, detect_period_from_text

logger = logging.getLogger(__name__)

# Six statements is half a year of monthly statements per click. Each one costs a Gmail
# download plus up to four passes over the PDF, all inside the request, so the number is
# kept small enough for the call to return while the user is still looking at the screen.
# The timings behind that are estimates until measured on staging.
MAX_STATEMENTS_PER_CALL = 6

LEDGER_SOURCE = "cas_history"
CONSOLIDATED_SOURCES = ("nsdl", "cdsl")
MF_ONLY_SOURCES = ("cams", "kfintech", "cams_kfintech")
_SOURCE_LABEL = {"nsdl": "NSDL", "cdsl": "CDSL", "cams": "CAMS", "kfintech": "KFintech",
                 "cams_kfintech": "CAMS / KFintech"}
_FILE_TYPE_SOURCE = {"NSDL": "nsdl", "CDSL": "cdsl", "CAMS": "cams", "KFINTECH": "kfintech", "KARVY": "kfintech"}
_DATE_SOURCE_WORDS = {"file_name": "file name", "email_subject": "email subject"}

# What the user is told. Exception text stays in the server log.
REASONS = {
    "no_pdf": "This email has no PDF statement that can be downloaded.",
    "download": "The statement could not be downloaded from Gmail.",
    "password": "The password did not unlock this statement. Check the PAN or statement password under Sync Gmail.",
    "parse": "This PDF could not be read as a CAS statement.",
    "service": "The statement reader hit an error. Try again.",
    "no_date": "The statement date could not be read from the statement, its file name or the email subject.",
    "store": "The statement was read but could not be stored. Try again.",
    "mount": "The statement could not be saved as your current portfolio. Try again.",
}


# ── small helpers ────────────────────────────────────────────────────────────────────────────
def source_rank(source: Optional[str]) -> int:
    """Lower is better: NSDL, CDSL, CAMS, KFintech, then anything else."""
    try:
        return gmail_service.SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(gmail_service.SOURCE_PRIORITY)


def consolidated(source: Optional[str]) -> Optional[bool]:
    """True for a depository statement, False for a mutual-fund-only one, None when unknown."""
    if source in CONSOLIDATED_SOURCES:
        return True
    if source in MF_ONLY_SOURCES:
        return False
    return None


def _label(source: Optional[str]) -> str:
    return _SOURCE_LABEL.get(source or "", "")


_DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d-%b-%y")


def to_iso_date(value: Any) -> Optional[str]:
    """A statement date in any of the forms the readers and the profile carry → 'YYYY-MM-DD'."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    for candidate in (s, s[:10]):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _period(iso_date: Optional[str]) -> Optional[str]:
    return cas_api_client.period_label_from_date(iso_date) if iso_date else None


def _month_end(period_label: Any) -> Optional[str]:
    """'Sep/2026' → '2026-09-30'. Used when the profile has a period but no readable date."""
    if not isinstance(period_label, str) or "/" not in period_label:
        return None
    try:
        d = datetime.strptime(period_label.strip(), "%b/%Y")
    except ValueError:
        return None
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1]).isoformat()


# ── reading one statement ────────────────────────────────────────────────────────────────────
@dataclass
class ParsedStatement:
    holdings: List[Dict[str, Any]] = field(default_factory=list)
    layout: str = ""                         # the reader that won: nsdl | cdsl | cams_kfin | offline
    statement_date: str = ""                 # as that reader gave it; "" when it gave none
    total_value: Optional[float] = None      # the total printed on the statement, when the reader has it
    monthly_values: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Optional[Dict[str, Any]] = None        # the fallback parser's own output
    error: Optional[Dict[str, str]] = None           # {"kind", "detail"} when nothing could be read


def parse_statement(content: bytes, password: str) -> ParsedStatement:
    """Read one CAS PDF with the existing extractors, in the order and under the gates the
    default import uses (routes.onboarding_gmail.gmail_auto_import): the reconciling NSDL,
    CDSL and CAMS/KFintech extractors each win only when they tie out to the printed total,
    then the offline casparser library. Unlike the default import this makes NO model call
    and persists nothing. Blocking — call it from a worker thread.

    tests/test_cas_import_all.py pins this to the default import: both must read the same
    holdings from the same statement."""
    try:
        from services import nsdl_cas_extractor as _nsdl
        ext = _nsdl.extract_nsdl_cas(content, password)
        if ext.reconciled and ext.holdings:
            return ParsedStatement(
                holdings=[h.as_holding_dict() for h in ext.holdings], layout="nsdl",
                statement_date=ext.statement_date or "", total_value=ext.grand_total,
                monthly_values=list(ext.monthly_values or []),
            )
    except Exception as e:  # noqa: BLE001 — a reader that cannot read the file is not an error here
        logger.warning("cas-history: NSDL extractor error, trying the next reader: %s", e)

    try:
        from services import cdsl_cas_extractor as _cdsl
        cext = _cdsl.extract_cdsl_cas(content, password)
        if cext.reconciled and cext.holdings:
            return ParsedStatement(
                holdings=[h.as_holding_dict() for h in cext.holdings], layout="cdsl",
                total_value=cext.grand_total,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("cas-history: CDSL extractor error, trying the next reader: %s", e)

    try:
        from services import cams_kfin_cas_extractor as _ck
        ckext = _ck.extract_cams_kfin_cas(content, password)
        if ckext.reconciled and ckext.holdings:
            return ParsedStatement(
                holdings=[h.as_holding_dict() for h in ckext.holdings], layout="cams_kfin",
                statement_date=ckext.statement_date or "", total_value=ckext.grand_total,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("cas-history: CAMS/KFintech extractor error, trying the next reader: %s", e)

    try:
        holdings, raw_data, parse_err = cas_api_client.parse_cas_offline(content, password=password)
    except Exception as e:  # noqa: BLE001
        logger.exception("cas-history: offline casparser crashed: %s", e)
        return ParsedStatement(error={"kind": "service", "detail": str(e)[:200]})
    if holdings:
        period = (raw_data or {}).get("statement_period") or ((raw_data or {}).get("meta") or {}).get("statement_period") or {}
        printed = period.get("to") if isinstance(period, dict) else None
        return ParsedStatement(
            holdings=list(holdings), layout="offline", raw_data=raw_data,
            statement_date=to_iso_date(printed) or "",
        )
    kind = (parse_err or {}).get("kind") or "parse"
    return ParsedStatement(error={
        "kind": kind if kind in ("password", "service") else "parse",
        "detail": str((parse_err or {}).get("detail", ""))[:200],
    })


def statement_source(parsed: ParsedStatement, email_source: str) -> str:
    """Which kind of statement the file is. The file decides; the sender of the email is
    only the tie-break between the two registrars, whose layout is the same."""
    if parsed.layout in ("nsdl", "cdsl"):
        return parsed.layout
    if parsed.layout == "cams_kfin":
        return email_source if email_source in ("cams", "kfintech") else "cams_kfintech"
    raw = parsed.raw_data or {}
    file_type = raw.get("file_type")
    name = str(getattr(file_type, "name", file_type) or "").upper().split(".")[-1]
    if name in _FILE_TYPE_SOURCE:
        return _FILE_TYPE_SOURCE[name]
    return email_source if email_source in gmail_service.SOURCE_PRIORITY else "unknown"


def resolve_statement_date(
    parsed: ParsedStatement, *, filename: str, subject: str, emailed: Optional[datetime],
) -> Tuple[Optional[str], Optional[str]]:
    """(ISO statement date, where it was read) — the statement itself, else the file name,
    else the email subject; (None, None) when none of them gives one.

    A date from the file name or the subject is the END of the month they name. A month that
    had not ended when the email was sent cannot be the statement's, so it is not accepted."""
    iso = to_iso_date(parsed.statement_date)
    if iso:
        return iso, "statement"
    latest = None
    if emailed is not None and emailed.year > 1:
        latest = (emailed.astimezone(timezone.utc).date() + timedelta(days=1)).isoformat()
    for where, (_start, end) in (
        ("file_name", detect_period_from_filename(filename or "")),
        ("email_subject", detect_period_from_text(subject or "")),
    ):
        if end and (latest is None or end <= latest):
            return end, where
    return None, None


# ── one statement on its way through a call ──────────────────────────────────────────────────
@dataclass
class Statement:
    message_id: str
    filename: str
    email_date: Optional[str]
    source: str
    statement_date: str                      # ISO
    date_source: str                         # statement | file_name | email_subject
    parsed: ParsedStatement
    content: bytes
    sha256: str
    mounted: bool = False
    replaces: Optional[Dict[str, Any]] = None        # the stored snapshot this one takes the place of
    # Emails read in this call that turned out to carry this same statement: (row, reason).
    same_statement: List[Tuple[Dict[str, Any], str]] = field(default_factory=list)

    @property
    def consolidated(self) -> Optional[bool]:
        return consolidated(self.source)

    @property
    def period(self) -> Optional[str]:
        return _period(self.statement_date)

    def row(self, status: str, *, reason: Optional[str] = None, error_kind: Optional[str] = None) -> Dict[str, Any]:
        return _row(
            self.message_id, status, filename=self.filename, email_date=self.email_date, source=self.source,
            statement_date=self.statement_date, date_source=self.date_source, reason=reason,
            error_kind=error_kind, holdings_count=len(self.parsed.holdings), mounted=self.mounted,
        )


def _row(message_id: str, status: str, *, filename: Optional[str] = None, email_date: Optional[str] = None,
         source: Optional[str] = None, statement_date: Optional[str] = None, date_source: Optional[str] = None,
         reason: Optional[str] = None, error_kind: Optional[str] = None, holdings_count: Optional[int] = None,
         mounted: bool = False) -> Dict[str, Any]:
    return {
        "message_id": message_id,
        "filename": filename,
        "email_date": email_date,
        "source": source,
        "consolidated": consolidated(source),
        "statement_date": statement_date,
        "statement_period": _period(statement_date),
        "date_source": date_source,
        "status": status,                    # imported | already_stored | failed
        "reason": reason,
        "error_kind": error_kind,
        "holdings_count": holdings_count,
        "mounted": mounted,
    }


def _interleave(ids_by_source: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    """Newest of each source first, then the second newest of each, and so on — so a source
    with a lot of mail does not push the others out of a call."""
    order: List[Tuple[str, str]] = []
    depth = max((len(ids) for ids in ids_by_source.values()), default=0)
    for i in range(depth):
        for source, ids in ids_by_source.items():
            if i < len(ids):
                order.append((ids[i], source))
    return order


# ── what is already on record ────────────────────────────────────────────────────────────────
async def _stored_statements(db, user_id: str) -> List[Dict[str, Any]]:
    cursor = db.portfolio_snapshots.find(
        {"user_id": user_id, "holdings": {"$exists": True, "$not": {"$size": 0}}},
        {"_id": 0, "snapshot_date": 1, "cas_source": 1, "cas_filename": 1, "gmail_message_id": 1,
         "duplicate_message_ids": 1, "file_sha256": 1, "holdings_count": 1, "statement_date_source": 1},
    )
    return await cursor.to_list(length=2000)


async def _failed_before(db, user_id: str) -> Dict[str, Dict[str, Any]]:
    cursor = db.gmail_imports.find(
        {"user_id": user_id, "source": LEDGER_SOURCE, "status": "failed"},
        {"_id": 0, "message_id": 1, "filename": 1, "email_date": 1, "cas_source": 1, "reason": 1, "error_kind": 1},
    )
    return {r["message_id"]: r for r in await cursor.to_list(length=2000) if r.get("message_id")}


def _ledger_key(user_id: str, message_id: str) -> Dict[str, Any]:
    return {"user_id": user_id, "message_id": message_id, "source": LEDGER_SOURCE}


async def _log_failed(db, user_id: str, row: Dict[str, Any]) -> None:
    await db.gmail_imports.update_one(
        _ledger_key(user_id, row["message_id"]),
        {"$set": {"status": "failed", "filename": row["filename"], "email_date": row["email_date"],
                  "cas_source": row["source"], "reason": row["reason"], "error_kind": row["error_kind"],
                  "imported_at": datetime.now(timezone.utc).isoformat()},
         "$inc": {"attempts": 1}},
        upsert=True,
    )


async def _log_stored(db, user_id: str, st: Statement) -> None:
    await db.gmail_imports.update_one(
        _ledger_key(user_id, st.message_id),
        {"$set": {"status": "completed", "filename": st.filename, "email_date": st.email_date,
                  "cas_source": st.source, "statement_date": st.statement_date,
                  "count": len(st.parsed.holdings), "reason": None, "error_kind": None,
                  "imported_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


# ── the import ───────────────────────────────────────────────────────────────────────────────
async def import_all_statements(
    *,
    db,
    user_id: str,
    service,
    password: str,
    profile: Dict[str, Any],
    ids_by_source: Dict[str, List[str]],
    mount: Callable[[Statement], Awaitable[None]],
    cap: int = MAX_STATEMENTS_PER_CALL,
) -> Dict[str, Any]:
    """Read up to `cap` statements not yet on record, store each, and show the latest.

    `ids_by_source` is gmail_service.list_cas_history's answer. `mount(statement)` makes one
    statement the live portfolio; it is awaited at most once, and never for a statement
    that is not newer than the one on file. Returns the response body's own fields.
    """
    order = _interleave(ids_by_source)
    position = {mid: i for i, (mid, _) in enumerate(order)}
    stored = await _stored_statements(db, user_id)
    failed_before = await _failed_before(db, user_id)

    by_message: Dict[str, Tuple[Dict[str, Any], bool]] = {}      # message id → (snapshot, is its own email)
    by_sha: Dict[str, Dict[str, Any]] = {}
    by_date: Dict[str, Dict[str, Any]] = {}
    for doc in stored:
        by_date[doc["snapshot_date"]] = doc
        if doc.get("gmail_message_id"):
            by_message[doc["gmail_message_id"]] = (doc, True)
        for mid in doc.get("duplicate_message_ids") or []:
            by_message.setdefault(mid, (doc, False))
        if doc.get("file_sha256"):
            by_sha[doc["file_sha256"]] = doc

    untried = [c for c in order if c[0] not in by_message and c[0] not in failed_before]
    retry = [c for c in order if c[0] in failed_before and c[0] not in by_message]
    attempts = (untried + retry)[:cap]
    attempted = {mid for mid, _ in attempts}
    remaining = max(0, len(untried) - cap)

    rows: List[Dict[str, Any]] = []
    for mid, _hint in order:
        if mid in by_message:
            doc, own = by_message[mid]
            rows.append(_row(
                mid, "already_stored", filename=doc.get("cas_filename") if own else None,
                source=doc.get("cas_source"), statement_date=doc["snapshot_date"],
                date_source=doc.get("statement_date_source"), holdings_count=doc.get("holdings_count"),
                reason=None if own else "A statement for the same date is already stored.",
            ))
    for mid, _hint in retry:
        if mid not in attempted:      # failed before and no room to retry it in this call
            old = failed_before[mid]
            rows.append(_row(mid, "failed", filename=old.get("filename"), email_date=old.get("email_date"),
                             source=old.get("cas_source"), reason=old.get("reason"), error_kind=old.get("error_kind")))

    failed_now: List[Dict[str, Any]] = []

    async def fail(row: Dict[str, Any]) -> None:
        rows.append(row)
        failed_now.append(row)
        await _log_failed(db, user_id, row)

    async def duplicate_of(snapshot_date: str, row: Dict[str, Any]) -> None:
        rows.append(row)
        await cas_snapshot_engine.note_duplicate_statement(user_id, snapshot_date, gmail_message_id=row["message_id"])
        if row["message_id"] in failed_before:      # it is no longer a failure
            await db.gmail_imports.delete_one({**_ledger_key(user_id, row["message_id"]), "status": "failed"})

    # 1. Open, download and read each email of this call. Nothing is stored yet.
    read: List[Statement] = []
    by_sha_now: Dict[str, Statement] = {}
    for mid, hint in attempts:
        try:
            email = await asyncio.to_thread(gmail_service.fetch_cas_email, service, mid, hint)
        except Exception as e:  # noqa: BLE001
            logger.warning("cas-history: could not open email %s for %s: %s", mid, user_id, e)
            await fail(_row(mid, "failed", source=hint, reason=REASONS["download"], error_kind="download"))
            continue
        if email is None:
            await fail(_row(mid, "failed", source=hint, reason=REASONS["no_pdf"], error_kind="no_pdf"))
            continue

        filename = email.get("filename") or f"CAS-{mid}.pdf"
        emailed = email.get("date_dt")
        email_date = emailed.astimezone(timezone.utc).date().isoformat() if emailed is not None and emailed.year > 1 else None
        email_source = email.get("source") or hint
        known = dict(filename=filename, email_date=email_date)

        try:
            content = await asyncio.to_thread(gmail_service.download_attachment, service, mid, email.get("attachment_id"))
        except Exception as e:  # noqa: BLE001
            logger.warning("cas-history: download failed for %s/%s: %s", user_id, mid, e)
            await fail(_row(mid, "failed", source=email_source, reason=REASONS["download"], error_kind="download", **known))
            continue

        digest = hashlib.sha256(content).hexdigest()
        if digest in by_sha:
            doc = by_sha[digest]
            await duplicate_of(doc["snapshot_date"], _row(
                mid, "already_stored", source=doc.get("cas_source"), statement_date=doc["snapshot_date"],
                date_source=doc.get("statement_date_source"), holdings_count=doc.get("holdings_count"),
                reason="This file is already stored.", **known))
            continue
        if digest in by_sha_now:
            first = by_sha_now[digest]
            first.same_statement.append((_row(
                mid, "already_stored", source=first.source, statement_date=first.statement_date,
                date_source=first.date_source, holdings_count=len(first.parsed.holdings), **known),
                "This file is already stored."))
            continue

        parsed = await asyncio.to_thread(parse_statement, content, password)
        if parsed.error:
            kind = parsed.error["kind"]
            logger.warning("cas-history: %s could not be read for %s — kind=%s detail=%s",
                           filename, user_id, kind, parsed.error.get("detail"))
            await fail(_row(mid, "failed", source=email_source, reason=REASONS[kind], error_kind=kind, **known))
            continue

        source = statement_source(parsed, email_source)
        iso, date_source = resolve_statement_date(
            parsed, filename=filename, subject=email.get("subject") or "", emailed=emailed)
        if not iso:
            await fail(_row(mid, "failed", source=source, reason=REASONS["no_date"], error_kind="no_date",
                            holdings_count=len(parsed.holdings), **known))
            continue

        st = Statement(message_id=mid, filename=filename, email_date=email_date, source=source,
                       statement_date=iso, date_source=date_source, parsed=parsed, content=content, sha256=digest)
        read.append(st)
        by_sha_now[digest] = st

    # 2. One statement per date: the higher-priority source is the one kept.
    best: Dict[str, Statement] = {}
    for st in read:
        cur = best.get(st.statement_date)
        if cur is None:
            best[st.statement_date] = st
        elif source_rank(st.source) < source_rank(cur.source):
            st.same_statement = [*cur.same_statement, (cur.row("already_stored"), _kept_instead(st.source, cur.source)), *st.same_statement]
            cur.same_statement = []
            best[st.statement_date] = st
        else:
            cur.same_statement.append((st.row("already_stored"), _kept_instead(cur.source, st.source)))

    to_store: List[Statement] = []
    for st in best.values():
        on_record = by_date.get(st.statement_date)
        if on_record is None:
            to_store.append(st)
        elif on_record.get("cas_source") and source_rank(st.source) < source_rank(on_record["cas_source"]):
            st.replaces = on_record
            to_store.append(st)
        else:
            reason = _kept_instead(on_record.get("cas_source"), st.source)
            await duplicate_of(st.statement_date, st.row("already_stored", reason=reason))
            for other, why in st.same_statement:
                await duplicate_of(st.statement_date, {**other, "reason": why})

    # 3. Which statement the portfolio shows.
    on_file = await _on_file(db, user_id, profile, by_date, best)
    pick, mf_only = _choose(to_store, read, stored, on_file)
    mount_failed: Optional[Statement] = None
    if pick is not None:
        try:
            await mount(pick)
            pick.mounted = True
        except Exception as e:  # noqa: BLE001
            logger.exception("cas-history: could not save %s as the live portfolio for %s: %s",
                             pick.message_id, user_id, e)
            mount_failed = pick

    # 4. Store, oldest first. A statement that could not be shown is not stored either,
    #    so the next call reads it and tries again.
    for st in sorted(to_store, key=lambda s: s.statement_date):
        failure = "mount" if st is mount_failed else None
        if failure is None:
            try:
                await cas_snapshot_engine.store_cas_snapshot(
                    user_id=user_id, holdings=copy.deepcopy(st.parsed.holdings), transactions=[],
                    sips_detected=[], period_start=None, period_end=st.statement_date,
                    cas_file_id=f"gmail:{st.message_id}", cas_filename=st.filename, cas_source=st.source,
                    gmail_message_id=st.message_id, file_sha256=st.sha256,
                    statement_date_source=st.date_source,
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("cas-history: could not store %s for %s: %s", st.message_id, user_id, e)
                failure = "store"
        if failure:
            await fail(st.row("failed", reason=REASONS[failure], error_kind=failure))
            for other, _why in st.same_statement:
                await fail({**other, "status": "failed", "reason": REASONS[failure], "error_kind": failure})
            continue

        rows.append(st.row("imported"))
        await _log_stored(db, user_id, st)
        if st.replaces and st.replaces.get("gmail_message_id"):
            await cas_snapshot_engine.note_duplicate_statement(
                user_id, st.statement_date, gmail_message_id=st.replaces["gmail_message_id"])
        for other, why in st.same_statement:
            await duplicate_of(st.statement_date, {**other, "reason": why})
        logger.info("cas-history: stored %s statement %s (%d holdings, date from %s) for %s",
                    st.source, st.statement_date, len(st.parsed.holdings), st.date_source, user_id)

    # 5. The answer.
    rows.sort(key=lambda r: position.get(r["message_id"], len(position)))
    rows.sort(key=lambda r: r["statement_date"] or "", reverse=True)        # stable: undated rows keep scan order, last
    count = {s: sum(1 for r in rows if r["status"] == s) for s in ("imported", "already_stored", "failed")}
    shown = pick if pick is not None and pick.mounted else None
    first_failure = failed_now[0] if failed_now else None
    return {
        "ok": not (count["imported"] == 0 and count["already_stored"] == 0 and count["failed"] > 0),
        "mode": "all_statements",
        "months": gmail_service.HISTORY_MONTHS,
        "cap": cap,
        "scanned": len(order),
        "attempted": len(attempts),
        "imported": count["imported"],
        "already_stored": count["already_stored"],
        "failed": count["failed"],
        "remaining": remaining,
        "statements": rows,
        "mounted": _describe(shown, mf_only, mount_failed, to_store, on_file),
        # The default import's names for the same facts, so one reader can take either answer.
        "imported_files": count["imported"],
        "imported_holdings": len(shown.parsed.holdings) if shown else 0,
        "parse_errors": count["failed"],
        "parse_error": (
            {"kind": first_failure["error_kind"], "message": first_failure["reason"]}
            if first_failure and count["imported"] == 0 else None
        ),
    }


def _kept_instead(kept: Optional[str], other: Optional[str]) -> str:
    if kept and kept != other and _label(kept):
        return f"The {_label(kept)} statement for the same date is kept instead."
    return "A statement for the same date is already stored."


# ── the mount rule ───────────────────────────────────────────────────────────────────────────
@dataclass
class OnFile:
    exists: bool                     # a statement's portfolio is live, whether or not its date is known
    statement_date: Optional[str]    # ISO, None when it is not on record
    period: Optional[str]
    source: Optional[str]

    @property
    def consolidated(self) -> Optional[bool]:
        return consolidated(self.source)


async def _on_file(db, user_id: str, profile: Dict[str, Any], by_date: Dict[str, Dict[str, Any]],
                   read_by_date: Dict[str, Statement]) -> OnFile:
    """The statement the live portfolio was last written from, as the profile records it."""
    printed, label = profile.get("cas_statement_date"), profile.get("cas_statement_period")
    iso = to_iso_date(printed) or _month_end(label)
    exists = bool(printed or label)
    if not exists:
        # Statement rows with no statement fields beside them: an import that recorded no date.
        exists = await db.holdings.count_documents(
            {"user_id": user_id, "source": {"$in": list(holdings_reconcile.STATEMENT_SOURCES)}}) > 0
    source = profile.get("cas_statement_source")
    if not source and iso:
        # The default import does not record what kind of statement it saved. The same
        # statement, stored or read in this call, tells us.
        if iso in by_date:
            source = by_date[iso].get("cas_source")
        elif iso in read_by_date:
            source = read_by_date[iso].source
    return OnFile(exists=exists, statement_date=iso, period=label or _period(iso), source=source)


def _choose(to_store: List[Statement], read: List[Statement], stored: List[Dict[str, Any]],
            on_file: OnFile) -> Tuple[Optional[Statement], bool]:
    """(the statement to show, whether it is a mutual-fund-only one) — or (None, False).

    Only a statement read in this call, about to be stored, whose date the statement itself
    gave can be shown. It must be newer than the one on file; with nothing on file, the
    newest wins. A mutual-fund statement is considered only when there is no sign of a
    consolidated one anywhere: none stored, none read, and none (or an unknown kind) on file."""
    def newer(st: Statement) -> bool:
        if not on_file.exists:
            return True
        return on_file.statement_date is not None and st.statement_date > on_file.statement_date

    dated = [st for st in to_store if st.date_source == "statement"]
    cons = [st for st in dated if st.consolidated is True]
    if cons:
        newest = max(cons, key=lambda s: s.statement_date)
        return (newest, False) if newer(newest) else (None, False)

    maybe_consolidated = (
        any(consolidated(d.get("cas_source")) is not False for d in stored)
        or any(st.consolidated is not False for st in read)
        or (on_file.exists and on_file.consolidated is not False)
    )
    if maybe_consolidated:
        return None, False
    funds = [st for st in dated if st.consolidated is False]
    if funds:
        newest = max(funds, key=lambda s: s.statement_date)
        if newer(newest):
            return newest, True
    return None, False


def _describe(shown: Optional[Statement], mf_only: bool, mount_failed: Optional[Statement],
              to_store: List[Statement], on_file: OnFile) -> Dict[str, Any]:
    """What the portfolio shows after the call, and one plain sentence on why."""
    if shown is not None:
        out = {"changed": True, "statement_period": shown.period, "statement_date": shown.statement_date,
               "source": shown.source, "consolidated": shown.consolidated, "mf_only": mf_only}
        if mf_only:
            reason = ("No consolidated (NSDL or CDSL) statement was found, so your portfolio shows the "
                      f"latest mutual-fund statement ({shown.period}).")
        else:
            reason = f"Your portfolio now shows the {_label(shown.source)} statement for {shown.period}."
    else:
        out = {"changed": False, "statement_period": on_file.period, "statement_date": on_file.statement_date,
               "source": on_file.source, "consolidated": on_file.consolidated,
               "mf_only": on_file.exists and on_file.consolidated is False}
        reason = _why_unchanged(mount_failed, to_store, on_file)

    # A consolidated statement newer than the one shown, held back because its date is a guess.
    shown_date = out["statement_date"] or ""
    held_back = [st for st in to_store if st.consolidated is True and st.date_source != "statement"
                 and st is not mount_failed and st.statement_date > shown_date]
    if held_back and not (on_file.exists and on_file.statement_date is None):
        st = max(held_back, key=lambda s: s.statement_date)
        opener = "A newer" if shown_date else "A"
        hint = (f"{opener} {_label(st.source)} statement ({st.period}) was stored, but its date was read from the "
                f"{_DATE_SOURCE_WORDS.get(st.date_source, st.date_source)}, so it was not made your current "
                "portfolio. Use Sync Gmail to show it.")
        reason = f"{reason} {hint}" if shown is not None or on_file.exists else hint
    out["reason"] = reason
    return out


def _why_unchanged(mount_failed: Optional[Statement], to_store: List[Statement], on_file: OnFile) -> str:
    if mount_failed is not None:
        return f"The newest statement ({mount_failed.period}) could not be saved as your current portfolio. Try again."
    if not on_file.exists:
        return "No statement could be made your current portfolio yet."
    if on_file.statement_date is None:
        return ("The date of the statement your portfolio shows is not on record, so it was left as it is. "
                "Use Sync Gmail to show the latest statement.")
    dated = [st for st in to_store if st.date_source == "statement"]
    cons = [st for st in dated if st.consolidated is True]
    if cons and on_file.consolidated is False:
        st = max(cons, key=lambda s: s.statement_date)
        how = "is older than" if st.statement_date < on_file.statement_date else "has the same date as"
        return (f"A consolidated statement ({st.period}) was stored, but it {how} the mutual-fund statement "
                f"your portfolio shows ({on_file.period}), so nothing was changed.")
    newer_funds = [st for st in dated if st.consolidated is False and st.statement_date > on_file.statement_date]
    if newer_funds and on_file.consolidated is not False:
        st = max(newer_funds, key=lambda s: s.statement_date)
        what = "your consolidated portfolio" if on_file.consolidated else "the statement your portfolio shows"
        return (f"A newer mutual-fund statement ({st.period}) was stored. It does not replace {what} "
                f"({on_file.period}).")
    return f"Your portfolio already shows the latest statement ({on_file.period})."
