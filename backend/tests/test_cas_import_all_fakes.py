"""Stand-ins used by test_cas_import_all.py. Everything here is MOCK — not real data.

  * FakeDb        an in-memory stand-in for the Mongo calls the import path makes, with enough of the
                  query and update language to run helpers.parsing.save_holdings and the snapshot engine
                  for real. Every write is recorded in `db.writes`.
  * FakeGmail     the slice of the Gmail API client the scanners use: messages.list (query, paging),
                  messages.get (headers + PDF parts), attachments.get, getProfile. Calls are recorded.
  * statement()   "PDF bytes" for the tests: a JSON description of a statement that the fake
                  extractors (install_parsers) read back. No real statement, PAN or password is involved.
"""
from __future__ import annotations

import base64
import copy
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

_MISSING = object()


# ── Mongo stand-in ───────────────────────────────────────────────────────────────────────────
def _get(doc: Dict[str, Any], dotted: str) -> Any:
    cur: Any = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _is_ops(cond: Any) -> bool:
    return isinstance(cond, dict) and bool(cond) and all(k.startswith("$") for k in cond)


def _test(val: Any, cond: Dict[str, Any]) -> bool:
    """One field against an operator document. A missing field reads as null, as in Mongo."""
    plain = None if val is _MISSING else val
    for op, arg in cond.items():
        if op == "$exists":
            ok = (val is not _MISSING) == bool(arg)
        elif op == "$not":
            ok = not _test(val, arg)
        elif op == "$size":
            ok = isinstance(plain, list) and len(plain) == arg
        elif op == "$ne":
            ok = plain != arg
        elif op == "$in":
            ok = plain in arg or (isinstance(plain, list) and any(v in arg for v in plain))
        elif op == "$nin":
            ok = plain not in arg
        elif op in ("$gt", "$gte", "$lt", "$lte"):
            if plain is None:
                ok = False
            else:
                ok = {"$gt": plain > arg, "$gte": plain >= arg, "$lt": plain < arg, "$lte": plain <= arg}[op]
        else:
            raise NotImplementedError(op)
        if not ok:
            return False
    return True


def match(doc: Dict[str, Any], query: Optional[Dict[str, Any]]) -> bool:
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(match(doc, q) for q in cond):
                return False
        elif key == "$and":
            if not all(match(doc, q) for q in cond):
                return False
        elif _is_ops(cond):
            if not _test(_get(doc, key), cond):
                return False
        else:
            val = _get(doc, key)
            plain = None if val is _MISSING else val
            if plain != cond and not (isinstance(plain, list) and cond in plain):
                return False
    return True


def _project(doc: Dict[str, Any], projection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = copy.deepcopy(doc)
    wanted = [k for k, v in (projection or {}).items() if v and k != "_id"]
    dropped = [k for k, v in (projection or {}).items() if not v]
    if wanted:
        out = {k: out[k] for k in wanted if k in out}
    for k in dropped:
        out.pop(k, None)
    out.pop("_id", None)
    return out


def _set_path(doc: Dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = doc
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = copy.deepcopy(value)


def _apply(doc: Dict[str, Any], update: Dict[str, Any], *, inserting: bool) -> None:
    for op, fields in update.items():
        if op == "$set":
            for k, v in fields.items():
                _set_path(doc, k, v)
        elif op == "$setOnInsert":
            if inserting:
                for k, v in fields.items():
                    _set_path(doc, k, v)
        elif op == "$unset":
            for k in fields:
                doc.pop(k, None)
        elif op == "$inc":
            for k, v in fields.items():
                doc[k] = (doc.get(k) or 0) + v
        elif op == "$addToSet":
            for k, v in fields.items():
                doc.setdefault(k, [])
                if v not in doc[k]:
                    doc[k].append(copy.deepcopy(v))
        else:
            raise NotImplementedError(op)


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def sort(self, key, direction=1):
        spec = key if isinstance(key, list) else [(key, direction)]
        for k, d in reversed(spec):
            self._docs.sort(key=lambda doc: (doc.get(k) is not None, doc.get(k) or ""), reverse=d < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return self._docs if length is None else self._docs[:length]

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _Result(SimpleNamespace):
    pass


class FakeCollection:
    def __init__(self, name: str, writes: List[tuple]):
        self.name = name
        self.docs: List[Dict[str, Any]] = []
        self._writes = writes

    def _hits(self, query):
        return [d for d in self.docs if match(d, query)]

    async def find_one(self, query=None, projection=None, sort=None):
        hits = self._hits(query)
        for key, direction in reversed(sort or []):
            hits.sort(key=lambda d: (d.get(key) is not None, d.get(key) or ""), reverse=direction < 0)
        return _project(hits[0], projection) if hits else None

    def find(self, query=None, projection=None):
        return _Cursor([_project(d, projection) for d in self._hits(query)])

    async def count_documents(self, query=None):
        return len(self._hits(query))

    async def insert_one(self, doc):
        self._writes.append((self.name, "insert_one"))
        self.docs.append(copy.deepcopy({k: v for k, v in doc.items() if k != "_id"}))
        doc["_id"] = object()  # Mongo adds `_id` to the caller's dict
        return _Result(inserted_id=doc["_id"])

    async def insert_many(self, docs):
        self._writes.append((self.name, "insert_many"))
        self.docs.extend(copy.deepcopy(d) for d in docs)

    async def update_one(self, query, update, upsert=False):
        self._writes.append((self.name, "update_one"))
        hits = self._hits(query)
        if hits:
            _apply(hits[0], update, inserting=False)
            return _Result(matched_count=1, modified_count=1, upserted_id=None)
        if not upsert:
            return _Result(matched_count=0, modified_count=0, upserted_id=None)
        doc = {k: copy.deepcopy(v) for k, v in query.items() if not k.startswith("$") and not _is_ops(v)}
        _apply(doc, update, inserting=True)
        self.docs.append(doc)
        return _Result(matched_count=0, modified_count=0, upserted_id=object())

    async def update_many(self, query, update):
        self._writes.append((self.name, "update_many"))
        hits = self._hits(query)
        for d in hits:
            _apply(d, update, inserting=False)
        return _Result(matched_count=len(hits), modified_count=len(hits))

    async def delete_one(self, query):
        self._writes.append((self.name, "delete_one"))
        hits = self._hits(query)[:1]
        for d in hits:
            self.docs.remove(d)
        return _Result(deleted_count=len(hits))

    async def delete_many(self, query):
        self._writes.append((self.name, "delete_many"))
        hits = self._hits(query)
        for d in hits:
            self.docs.remove(d)
        return _Result(deleted_count=len(hits))

    async def create_index(self, *_a, **_k):
        return None


class FakeDb:
    """`db.<anything>` is a collection. `db.writes` lists (collection, operation) in call order."""

    def __init__(self):
        self.writes: List[tuple] = []
        self._collections: Dict[str, FakeCollection] = {}

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._collections.setdefault(name, FakeCollection(name, self.writes))

    def written(self, *, ignore=()) -> List[tuple]:
        return [w for w in self.writes if w[0] not in ignore]


# ── statements and the fake extractors that read them ────────────────────────────────────────
def holding(isin: str, qty: float = 10, price: float = 100.0, asset: str = "equity") -> Dict[str, Any]:
    """One row in the shape the statement extractors emit (Holding.as_holding_dict)."""
    return {"name": f"Company {isin}", "ticker": isin, "asset_type": asset, "quantity": qty,
            "buy_price": 0.0, "current_price": price, "sector": "", "source": "nsdl_cas"}


def statement(layout: str, date: str = "", isins=("INE000A01001", "INE000A01002"), *, tag: str = "",
              total: Optional[float] = None, monthly=None, file_type: str = "CAMS") -> bytes:
    """Bytes standing in for a statement PDF. `layout` decides which fake extractor reads it:
    nsdl | cdsl | cams (the CAMS/KFintech extractor) | offline (the casparser fallback) |
    junk (nothing reads it) | locked (wrong password) | crash (the fallback raises)."""
    rows = [holding(i) for i in isins]
    return json.dumps({
        "layout": layout, "date": date, "holdings": rows, "tag": tag or f"{layout}:{date}",
        "total": total if total is not None else float(sum(r["quantity"] * r["current_price"] for r in rows)),
        "monthly": monthly or [], "file_type": file_type,
    }).encode()


def _read(content: bytes) -> Dict[str, Any]:
    try:
        spec = json.loads(content)
        return spec if isinstance(spec, dict) else {"layout": "junk", "tag": "junk"}
    except (ValueError, UnicodeDecodeError):
        return {"layout": "junk", "tag": "junk"}


class _Row:
    def __init__(self, row):
        self._row = row

    def as_holding_dict(self):
        return dict(self._row)


def _no_match():
    return SimpleNamespace(reconciled=False, holdings=[], grand_total=None, statement_date="",
                           monthly_values=[], layout="", reconciliation={"reason": "not this layout"})


class Parsers:
    """Records which extractor was handed which statement."""

    def __init__(self):
        self.calls: List[tuple] = []     # (extractor, statement tag)
        self.passwords: List[str] = []

    def tags(self) -> List[str]:
        """Statements any extractor was asked to read, once each, in order."""
        seen: List[str] = []
        for _, tag in self.calls:
            if tag not in seen:
                seen.append(tag)
        return seen

    def clear(self):
        self.calls.clear()


def install_parsers(monkeypatch) -> Parsers:
    """Replace the four statement extractors (and nothing else) with readers of statement()."""
    from services import cams_kfin_cas_extractor, cas_api_client, cdsl_cas_extractor, nsdl_cas_extractor

    rec = Parsers()

    def _custom(name: str, layout: str):
        def extract(content: bytes, password: str = ""):
            spec = _read(content)
            rec.calls.append((name, spec.get("tag")))
            rec.passwords.append(password)
            if spec["layout"] == "locked":
                raise ValueError("Incorrect password")
            if spec["layout"] != layout:
                return _no_match()
            out = SimpleNamespace(reconciled=True, holdings=[_Row(r) for r in spec["holdings"]],
                                  grand_total=spec["total"], reconciliation={})
            if layout == "nsdl":
                out.statement_date, out.monthly_values = spec["date"], spec["monthly"]
            if layout == "cams":
                out.statement_date, out.layout = spec["date"], "detailed"
            return out          # the CDSL result carries no statement date, as in the real extractor
        return extract

    def offline(content: bytes, password: str = ""):
        spec = _read(content)
        rec.calls.append(("offline", spec.get("tag")))
        rec.passwords.append(password)
        if spec["layout"] == "crash":
            raise RuntimeError("fallback parser blew up")
        if spec["layout"] == "locked":
            return [], None, {"kind": "password", "message": "That PAN didn't unlock the statement.",
                              "detail": "Incorrect password"}
        if spec["layout"] != "offline":
            return [], None, {"kind": "parse", "message": "The CAS statement couldn't be read (offline parser).",
                              "detail": "not a statement"}
        raw = {"statement_period": {"from": "", "to": spec["date"]}, "file_type": spec["file_type"]}
        if spec["file_type"] in ("NSDL", "CDSL"):
            raw["accounts"] = [{"name": "demat"}]
        return [dict(r) for r in spec["holdings"]], raw, None

    monkeypatch.setattr(nsdl_cas_extractor, "extract_nsdl_cas", _custom("nsdl", "nsdl"))
    monkeypatch.setattr(cdsl_cas_extractor, "extract_cdsl_cas", _custom("cdsl", "cdsl"))
    monkeypatch.setattr(cams_kfin_cas_extractor, "extract_cams_kfin_cas", _custom("cams_kfin", "cams"))
    monkeypatch.setattr(cas_api_client, "parse_cas_offline", offline)
    return rec


# ── Gmail stand-in ───────────────────────────────────────────────────────────────────────────
SENDERS = {
    "nsdl": "NSDL e-CAS <NSDL-CAS@nsdl.co.in>",
    "cdsl": "CDSL <eCAS@cdslindia.com>",
    "cams": "CAMS <donotreply@camsonline.com>",
    "kfintech": "KFintech <noreply@kfintech.com>",
}


def mail(message_id: str, source: str, when: datetime, content: Optional[bytes], *, filename: str = "",
         subject: str = "Consolidated Account Statement", download_error: bool = False,
         inline_pdf: bool = False) -> Dict[str, Any]:
    """One email in the fake mailbox. `content` is the attachment (statement()); None = no PDF at all.
    `inline_pdf` = a PDF part Gmail gives no attachment id for, so it cannot be downloaded."""
    return {"id": message_id, "sender": SENDERS[source], "subject": subject,
            "when": when.replace(tzinfo=when.tzinfo or timezone.utc), "content": content,
            "filename": filename or f"{message_id}.pdf", "download_error": download_error,
            "inline_pdf": inline_pdf}


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeGmail:
    def __init__(self, emails=(), *, today: datetime, address: str = "investor@example.com"):
        self.emails: List[Dict[str, Any]] = list(emails)
        self.today = today
        self.address = address
        self.list_calls: List[Dict[str, Any]] = []
        self.gets: List[str] = []
        self.downloads: List[str] = []
        self.fail_lists = False
        self._att = 0

    def clear_calls(self):
        self.list_calls.clear(), self.gets.clear(), self.downloads.clear()

    # service.users()…
    def users(self):
        return self

    def getProfile(self, userId="me"):  # noqa: N802 (Gmail's name)
        return _Exec(lambda: {"emailAddress": self.address})

    def messages(self):
        return _Messages(self)

    def _matching(self, q: str) -> List[Dict[str, Any]]:
        hits = [e for e in self.emails if e["content"] is not None or e["inline_pdf"]]
        for token in q.split():
            if token.startswith("from:"):
                needle = token[5:].lower()
                hits = [e for e in hits if needle in e["sender"].lower()]
            elif token.startswith("newer_than:"):
                amount, unit = int(token[11:-1]), token[-1]
                days = amount * {"d": 1, "m": 31, "y": 366}[unit]
                hits = [e for e in hits if e["when"] >= self.today - timedelta(days=days)]
        return sorted(hits, key=lambda e: e["when"], reverse=True)   # Gmail lists newest first


class _Messages:
    def __init__(self, box: FakeGmail):
        self._box = box

    def list(self, userId="me", q="", maxResults=100, pageToken=None):  # noqa: N803
        box = self._box

        def run():
            box.list_calls.append({"q": q, "maxResults": maxResults, "pageToken": pageToken})
            if box.fail_lists:
                raise RuntimeError("invalid_grant: Token has been expired or revoked.")
            hits = box._matching(q)
            start = int(pageToken or 0)
            page = hits[start:start + maxResults]
            out: Dict[str, Any] = {"messages": [{"id": e["id"], "threadId": e["id"]} for e in page]}
            if start + maxResults < len(hits):
                out["nextPageToken"] = str(start + maxResults)
            return out
        return _Exec(run)

    def get(self, userId="me", id="", format="full"):  # noqa: A002 (Gmail's name)
        box = self._box

        def run():
            box.gets.append(id)
            e = next(m for m in box.emails if m["id"] == id)
            parts: List[Dict[str, Any]] = [{"mimeType": "text/html", "body": {"data": "…"}}]
            if e["content"] is not None or e["inline_pdf"]:
                body: Dict[str, Any] = {"size": len(e["content"] or b"")}
                if not e["inline_pdf"]:
                    box._att += 1                       # Gmail hands out a new attachment id per read
                    body["attachmentId"] = f"att-{id}-{box._att}"
                parts.append({"filename": e["filename"], "mimeType": "application/pdf", "body": body})
            return {"id": id, "internalDate": str(int(e["when"].timestamp() * 1000)), "payload": {
                "headers": [{"name": "From", "value": e["sender"]}, {"name": "Subject", "value": e["subject"]},
                            {"name": "Date", "value": format_datetime(e["when"])}],
                "parts": parts,
            }}
        return _Exec(run)

    def attachments(self):
        return _Attachments(self._box)


class _Attachments:
    def __init__(self, box: FakeGmail):
        self._box = box

    def get(self, userId="me", messageId="", id=""):  # noqa: A002, N803
        box = self._box

        def run():
            box.downloads.append(messageId)
            e = next(m for m in box.emails if m["id"] == messageId)
            if e["download_error"] or not id.startswith(f"att-{messageId}-"):
                raise RuntimeError("attachment not found")
            return {"data": base64.urlsafe_b64encode(e["content"]).decode()}
        return _Exec(run)
