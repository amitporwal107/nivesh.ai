"""Portfolio import with a preview before commit (PRD §8.2, §14.3; backend addition B17) — routes/upload.py.

    POST /api/portfolio/upload/preview                    read + validate + flag; stores the preview, saves no holding
    POST /api/portfolio/upload/preview/{id}/commit        saves only the rows chosen (default: the ready ones)

No Mongo and no network: `db` is an in-memory fake (only what upload.py uses), `save_holdings` and the dashboard cache
are recorders, the malware scan is a stub that reports "scanner unavailable" (as on a host without ClamAV), and the NSE
symbol index is a small dict. The parsing (helpers/statement_exports.py) and the upload validation
(helpers/upload_validation.py) run for real.

MOCK — not real data: every holding below is made up. The ISINs are real, valid ISINs of listed companies so that the
check-digit rule is exercised on real codes (INE009A01021 Infosys, INE040A01034 HDFC Bank, INE002A01018 Reliance).
"""
from __future__ import annotations

import copy
import io
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.upload as up
from helpers import holdings_reconcile

PREVIEW = "/api/portfolio/upload/preview"
A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}
NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)

INFY, HDFC, RIL = "INE009A01021", "INE040A01034", "INE002A01018"


# ── an in-memory Mongo ───────────────────────────────────────────────────────
def _match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    return all(doc.get(k) == v for k, v in query.items())


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length):
        return self._docs if length is None else self._docs[:length]


class _Res:
    def __init__(self, matched=0):
        self.matched_count = self.modified_count = matched


class FakeCol:
    def __init__(self, docs=()):
        self.docs: List[Dict[str, Any]] = [copy.deepcopy(d) for d in docs]
        self.indexes: List[Any] = []
        self.writes: List[str] = []

    async def create_index(self, keys, **kw):
        self.indexes.append((keys, kw))

    def find(self, query, projection=None):
        return _Cursor([copy.deepcopy(d) for d in self.docs if _match(d, query)])

    async def find_one(self, query, projection=None):
        return next((copy.deepcopy(d) for d in self.docs if _match(d, query)), None)

    async def insert_one(self, doc):
        self.writes.append("insert_one")
        self.docs.append(copy.deepcopy(doc))

    async def update_one(self, query, update):
        self.writes.append("update_one")
        for d in self.docs:
            if _match(d, query):
                d.update(copy.deepcopy(update["$set"]))
                return _Res(1)
        return _Res(0)


class FakeDb:
    def __init__(self, holdings=()):
        self.holdings = FakeCol(holdings)
        self.cols = {up.PREVIEWS: FakeCol()}

    def __getitem__(self, name):
        return self.cols[name]

    @property
    def previews(self) -> FakeCol:
        return self.cols[up.PREVIEWS]


class World:
    def __init__(self, holdings=()):
        self.db = FakeDb(holdings)
        self.saved: List[Dict[str, Any]] = []
        self.invalidated: List[str] = []
        self.now = NOW


@pytest.fixture
def world(monkeypatch):
    return make_world(monkeypatch)


def make_world(monkeypatch, holdings=()) -> World:
    w = World(holdings)
    monkeypatch.setattr(up, "db", w.db)
    monkeypatch.setattr(up, "_previews_ready", False)
    monkeypatch.setattr(up, "_utcnow", lambda: w.now)

    async def fake_user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}

    async def fake_save(user_id, parsed, file_type, task_id=None, portfolio_id=""):
        w.saved.append({"user_id": user_id, "rows": copy.deepcopy(parsed), "file_type": file_type})
        return [{"holding_id": f"hold_{i}", "name": r.get("name"), "asset_type": r.get("asset_type"),
                 "quantity": r.get("quantity")} for i, r in enumerate(parsed)]

    async def fake_invalidate(user_id):
        w.invalidated.append(user_id)

    from services import malware_scanner

    async def no_scanner(content):
        return malware_scanner.ScanResult(clean=True, threat=None, scanner_available=False, bytes_scanned=len(content))

    monkeypatch.setattr(up, "get_current_user", fake_user)
    monkeypatch.setattr(up, "save_holdings", fake_save)
    monkeypatch.setattr(up.dashboard_cache, "invalidate", fake_invalidate)
    monkeypatch.setattr(malware_scanner, "scan", no_scanner)
    monkeypatch.setattr(holdings_reconcile, "_symbol_index", {"INFY": INFY, "HDFCBANK": HDFC, "RELIANCE": RIL, "TCS": "INE467B01029"})
    return w


@pytest.fixture
def api(world) -> TestClient:
    app = FastAPI()
    app.include_router(up.router)
    return TestClient(app)


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def preview(api, content: bytes, name: str = "holdings.csv", who=A):
    return api.post(PREVIEW, files={"file": (name, content, "text/csv")}, headers=who)


def row(body, n: int) -> Dict[str, Any]:
    return next(r for r in body["rows"] if r["row_no"] == n)


def codes(r: Dict[str, Any]) -> List[str]:
    return [f["code"] for f in r["flags"]]


GENERIC = csv_bytes(
    "Name,Symbol,Type,Quantity,Buy Price,Current Price",
    "Infosys,INFY,equity,10,1400,1525",                       # 1 ready
    "HDFC Bank,HDFCBANK,equity,5,0,1650",                     # 2 no average cost → review
    "Infosys again,INFY,equity,4,1450,1525",                   # 3 duplicate of row 1 → review
    "Nifty future,NIFTY26OCTFUT,equity,75,25100,25050",        # 4 a derivative contract → rejected
    "Gold contract,GOLDM,futures,1,70000,71000",               # 5 unsupported type → rejected
    "Zero line,TCS,equity,0,3000,3100",                        # 6 no quantity → rejected
    "=HYPERLINK(\"http://x\"),RELIANCE,equity,2,1200,1300",    # 7 formula-like text → review, neutralised
    "Odd lot,TCS,equity,2.5,3000,3100",                        # 8 fractional shares (and TCS twice) → review
    "Mystery,ZZZNOTREAL,equity,3,10,12",                       # 9 not on the NSE list → review
)


# ── preview: nothing is saved, every row is validated and flagged ────────────
def test_preview_flags_rows_and_saves_nothing(api, world):
    r = preview(api, GENERIC)
    assert r.status_code == 200, r.text
    body = r.json()
    assert world.saved == [] and world.db.holdings.writes == []           # nothing applied
    assert body["nothing_saved"] is True and body["status"] == "open"
    assert body["created_at"] == NOW.isoformat() and body["expires_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert body["file"]["format"] == "generic" and body["file"]["kind"] == "csv" and len(body["file"]["sha256"]) == 64
    assert body["currency"] == "INR" and body["account_ref"]["broker"] is None

    one = row(body, 1)
    assert (one["status"], one["include"], one["symbol"], one["isin"], one["quantity"], one["avg_cost"]) == (
        "ready", True, "INFY", INFY, 10.0, 1400.0)
    assert (one["instrument_type"], one["currency"], one["exchange"]) == ("equity", "INR", None)
    assert one["isin_source"] == "nse_list"                       # resolved from the symbol, not stated in the file
    assert "no_average_cost" in codes(row(body, 2)) and row(body, 2)["status"] == "review" and row(body, 2)["include"] is False
    dup = row(body, 3)
    assert dup["status"] == "review" and "duplicate_in_file" in codes(dup)
    assert "row 1" in next(f["text"] for f in dup["flags"] if f["code"] == "duplicate_in_file")
    assert row(body, 4)["status"] == "rejected" and "unsupported_instrument" in codes(row(body, 4))
    assert row(body, 5)["status"] == "rejected" and "unsupported_instrument" in codes(row(body, 5))
    assert row(body, 6)["status"] == "rejected" and "no_quantity" in codes(row(body, 6))
    seven = row(body, 7)
    assert seven["status"] == "review" and "formula_text" in codes(seven)
    assert seven["name"] == 'HYPERLINK("http://x")'                 # stored without the leading "="
    eight = row(body, 8)
    assert {"fractional_shares", "duplicate_in_file"} <= set(codes(eight))
    assert "unknown_symbol" in codes(row(body, 9)) and row(body, 9)["status"] == "review"
    assert body["counts"] == {"rows": 9, "ready": 1, "review": 5, "rejected": 3}
    # The preview is stored for this user only, with the rows it will save.
    [stored] = world.db.previews.docs
    assert stored["user_id"] == "user_a" and stored["_id"] == body["preview_id"]
    assert any(ix[1].get("expireAfterSeconds") == 0 for ix in world.db.previews.indexes)


def test_isin_check_digit_and_symbol_mismatch_are_flagged(api, world):
    # "Company Name" + "Avg Price": a holdings table whose broker the columns do not name (read with its ISIN column).
    body = preview(api, csv_bytes(
        "Company Name,Symbol,ISIN,Quantity,Avg Price",
        "Infosys,INFY,INE009A01022,10,1400",        # check digit wrong
        "HDFC Bank,INFY,INE040A01034,5,1600",       # the symbol is Infosys's, the ISIN HDFC Bank's
        "Reliance,RELIANCE,INE002A01018,2,1200",    # consistent
    )).json()
    assert "isin_check_failed" in codes(row(body, 1))
    mism = row(body, 2)
    assert "symbol_isin_mismatch" in codes(mism) and mism["status"] == "review"
    assert row(body, 3)["status"] == "ready" and row(body, 3)["isin_source"] == "file"


def test_a_holding_already_on_file_is_flagged_not_merged(monkeypatch):
    w = make_world(monkeypatch, holdings=[
        {"user_id": "user_a", "holding_id": "h1", "name": "Infosys", "ticker": INFY, "source": "cas", "quantity": 7},
        {"user_id": "user_b", "holding_id": "h2", "name": "HDFC Bank", "ticker": HDFC, "source": "cas", "quantity": 1},
    ])
    app = FastAPI()
    app.include_router(up.router)
    body = preview(TestClient(app), csv_bytes("Name,Symbol,Quantity,Buy Price", "Infosys,INFY,10,1400",
                                              "HDFC Bank,HDFCBANK,5,1600")).json()
    infy = row(body, 1)
    assert infy["status"] == "review" and "already_on_file" in codes(infy)
    assert "CAS statement" in next(f["text"] for f in infy["flags"] if f["code"] == "already_on_file")
    assert row(body, 2)["status"] == "ready"                       # another user's holding is not compared
    assert w.saved == []


ZERODHA = csv_bytes(
    "Instrument,ISIN,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.,Day chg.",
    "INFY,INE009A01021,10,1400,1525,15250,1245,8.9,0.5",
    "HDFCBANK,INE040A01034,5,1600,1650,8250,250,3.1,0.2",
    "RELIANCE,INE002A01018,2,1200,1300,2600,200,8.3,0.1",
)


def test_a_broker_export_says_what_it_replaces_and_what_a_connection_already_reports(monkeypatch):
    w = make_world(monkeypatch, holdings=[
        {"user_id": "user_a", "holding_id": "e1", "name": "Infosys", "ticker": "INFY", "isin": INFY,
         "source": "broker_export", "broker": "zerodha"},
        {"user_id": "user_a", "holding_id": "e2", "name": "Old line", "ticker": "OLD", "source": "broker_export", "broker": "zerodha"},
        {"user_id": "user_a", "holding_id": "l1", "name": "HDFC Bank", "ticker": "HDFCBANK", "isin": HDFC,
         "source": "broker_native", "broker": "zerodha", "broker_account_id": "ba_z"},
        {"user_id": "user_a", "holding_id": "c1", "name": "Reliance", "ticker": RIL, "source": "cas"},
    ])
    app = FastAPI()
    app.include_router(up.router)
    body = preview(TestClient(app), ZERODHA, name="zerodha_holdings.csv").json()
    assert body["file"]["broker"] == "zerodha" and body["account_ref"]["broker_name"] == "Zerodha"
    assert body["effects"]["replaces_export_rows"] == 2
    assert row(body, 1)["status"] == "ready" and "replaces_earlier_export" in codes(row(body, 1))
    held = row(body, 2)
    assert held["status"] == "rejected" and "held_by_connected_account" in codes(held)
    assert row(body, 3)["status"] == "ready" and "replaces_statement_row" in codes(row(body, 3))
    assert w.saved == []


# ── commit: only the chosen rows, once, for the owner only ───────────────────
def test_commit_saves_the_ready_rows_by_default(api, world):
    body = preview(api, GENERIC).json()
    r = api.post(f"{PREVIEW}/{body['preview_id']}/commit", headers=A)
    assert r.status_code == 200, r.text
    out = r.json()
    [call] = world.saved
    assert call["user_id"] == "user_a" and call["file_type"] == "CSV"
    assert [x["name"] for x in call["rows"]] == ["Infosys"]
    assert out["committed_rows"] == [1] and sorted(out["left_out_rows"]) == [2, 3, 4, 5, 6, 7, 8, 9]
    assert out["count"] == 1 and world.invalidated == ["user_a"]
    assert world.db.previews.docs[0]["status"] == "committed"


def test_commit_takes_review_rows_the_user_ticked_and_refuses_rejected_ones(api, world):
    body = preview(api, GENERIC).json()
    pid = body["preview_id"]
    r = api.post(f"{PREVIEW}/{pid}/commit", json={"rows": [1, 4]}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_rows")
    r = api.post(f"{PREVIEW}/{pid}/commit", json={"rows": [99]}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_rows")
    assert world.saved == []
    r = api.post(f"{PREVIEW}/{pid}/commit", json={"rows": [1, 2, 7]}, headers=A)
    assert r.status_code == 200, r.text
    names = [x["name"] for x in world.saved[0]["rows"]]
    assert names == ["Infosys", "HDFC Bank", 'HYPERLINK("http://x")']
    # HDFC Bank had no average cost: it is handed on with none (save_holdings then records the price as the cost,
    # which the preview's flag says in words).
    assert world.saved[0]["rows"][1]["buy_price"] == 0.0
    assert "records the file's price as the cost" in next(f["text"] for f in row(body, 2)["flags"] if f["code"] == "no_average_cost")


def test_commit_twice_is_409_and_another_users_preview_is_404(api, world):
    pid = preview(api, GENERIC).json()["preview_id"]
    assert api.post(f"{PREVIEW}/{pid}/commit", headers=B).status_code == 404
    assert api.post(f"{PREVIEW}/{pid}/commit", headers=A).status_code == 200
    r = api.post(f"{PREVIEW}/{pid}/commit", headers=A)
    assert (r.status_code, r.json()["detail"]) == (409, "preview_already_committed")
    assert len(world.saved) == 1
    assert api.post(f"{PREVIEW}/nope/commit", headers=A).status_code == 404


def test_an_expired_preview_is_410(api, world):
    pid = preview(api, GENERIC).json()["preview_id"]
    world.now = NOW + timedelta(minutes=31)
    r = api.post(f"{PREVIEW}/{pid}/commit", headers=A)
    assert (r.status_code, r.json()["detail"]) == (410, "preview_expired")
    assert world.saved == []


def test_a_failed_save_leaves_the_preview_open(api, world, monkeypatch):
    pid = preview(api, GENERIC).json()["preview_id"]

    async def broken(*a, **k):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(up, "save_holdings", broken)
    with pytest.raises(RuntimeError):
        api.post(f"{PREVIEW}/{pid}/commit", headers=A)
    assert world.db.previews.docs[0]["status"] == "open"


def test_the_preview_and_commit_need_a_signed_in_user(api, world):
    assert api.post(PREVIEW, files={"file": ("h.csv", GENERIC, "text/csv")}).status_code == 401
    assert api.post(f"{PREVIEW}/x/commit").status_code == 401
    assert world.db.previews.docs == []


# ── §14.3 file security ──────────────────────────────────────────────────────
def _xlsx(rows: List[List[Any]]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip(members: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_an_xlsx_is_read_for_the_preview(api, world):
    content = _xlsx([["Name", "Symbol", "Quantity", "Buy Price"], ["Infosys", "INFY", 10, 1400]])
    r = api.post(PREVIEW, files={"file": ("h.xlsx", content, "application/octet-stream")}, headers=A)
    assert r.status_code == 200, r.text
    assert r.json()["file"]["kind"] == "xlsx" and row(r.json(), 1)["status"] == "ready"


@pytest.mark.parametrize("name, content, status", [
    ("book.xlsx", _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<x/>", "xl/vbaProject.bin": b"\x00" * 64}), 415),
    ("book.xlsx", _zip({"[Content_Types].xml": b"<Types/>", "xl/activeX/activeX1.xml": b"<x/>"}), 415),
    ("book.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + "_VBA_PROJECT_CUR".encode("utf-16-le") + b"\x00" * 64, 415),
    ("bomb.xlsx", _zip({"[Content_Types].xml": b"<Types/>", "xl/worksheets/sheet1.xml": b"\x00" * (60 * 1024 * 1024)}), 413),
    ("big.csv", b"Name,Quantity\n" + b"x,1\n" * (2 * 1024 * 1024), 413),          # over the 5 MB preview limit
    ("cas.pdf", b"%PDF-1.4 fixture", 415),                                       # a statement PDF is not taken here
    ("fake.xlsx", b"PK\x03\x04 not really a zip", 400),
    ("empty.csv", b"", 400),
])
def test_unsafe_or_unreadable_files_are_refused_before_any_parse(api, world, name, content, status):
    r = api.post(PREVIEW, files={"file": (name, content, "application/octet-stream")}, headers=A)
    assert r.status_code == status, r.text
    assert world.db.previews.docs == [] and world.saved == []


def test_too_many_rows_is_refused(api, world, monkeypatch):
    monkeypatch.setattr(up, "PREVIEW_MAX_ROWS", 3)
    r = preview(api, GENERIC)
    assert r.status_code == 413 and "rows" in r.json()["detail"]
    assert world.db.previews.docs == []


def test_csv_safe_cell_neutralises_formulas_for_exports():
    assert up.csv_safe_cell("=1+2") == "'=1+2"
    assert up.csv_safe_cell("+91 98") == "'+91 98"
    assert up.csv_safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert up.csv_safe_cell("-5") == "'-5"
    assert up.csv_safe_cell("Infosys") == "Infosys" and up.csv_safe_cell(None) is None
