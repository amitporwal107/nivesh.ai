"""OCR for scanned filing pages (ocr.py), and what it changes downstream: the collector reads the
image pages, a filing whose text grew is judged and analysed again, and the new version is posted.
No network and no model call. The last test runs real tesseract and is skipped where it is not
installed (the backend image before tesseract was added to it)."""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))           # ai_analysis/
sys.path.insert(0, str(HERE.parents[4] / "backend"))

import analyse  # noqa: E402
import ea_core as core  # noqa: E402
import ingest  # noqa: E402
import ocr  # noqa: E402

NOW = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)
COVER = ("Bajaj Auto Ltd. To the Manager, Listing Department. Sub: Outcome of the board meeting. The board "
         "approved the unaudited financial results for the quarter and half year ended 30 September 2026. ") * 3
TABLE = "Total revenue from operations 20,003.43 17,243.72 14,922.05\nProfit for the period 3,353.76 2,982.84 2,479.74"


def _reader(text=TABLE):
    calls = []

    def read(pdf_path, page_no, workdir):
        calls.append(page_no)
        return text
    return read, calls


# ── which pages are read, and how the text says so ──────────────────────────
def test_only_pages_without_a_text_layer_are_read_by_ocr():
    """TC-O1: a typed cover letter and two scanned pages: the two image pages are OCR'd, the
    cover is kept as it is, and each OCR'd page is marked so the model knows its figures may
    carry recognition errors."""
    read, calls = _reader()
    text, info = ocr.fill(b"%PDF-1.4", [COVER, "", "  \n "], enabled=True, reader=read)
    assert calls == [2, 3]
    assert info == {"pages": 3, "low_text_pages": [2, 3], "ocr_pages": [2, 3], "ocr": ocr.OCR_TAG}
    assert text.startswith(COVER)
    assert f"{ocr.marker(2)}\n{TABLE}" in text and f"{ocr.marker(3)}\n{TABLE}" in text
    assert "recognition errors" in ocr.marker(2)


def test_without_ocr_the_text_is_the_text_layer_as_before():
    """TC-O2: OCR off (or not installed): nothing is read, the text is unchanged and the record
    says which pages had no text, so the filing is collected again once OCR can run."""
    read, calls = _reader()
    text, info = ocr.fill(b"%PDF-1.4", [COVER, ""], enabled=False, reader=read)
    assert calls == [] and text == COVER + "\n"
    assert info == {"pages": 2, "low_text_pages": [2], "ocr_pages": [], "ocr": None}


def test_a_page_ocr_cannot_read_stays_empty():
    """TC-O3: OCR ran but read (almost) nothing: the page stays empty, no marker, and the record
    says OCR ran, so it is not collected again and again."""
    read, _ = _reader(text="  ~ ")
    text, info = ocr.fill(b"%PDF-1.4", [COVER, ""], enabled=True, reader=read)
    assert "read by OCR" not in text and info["ocr_pages"] == [] and info["ocr"] == ocr.OCR_TAG


def test_a_document_with_text_on_every_page_is_never_ocrd():
    read, calls = _reader()
    _, info = ocr.fill(b"%PDF-1.4", [COVER, COVER], enabled=True, reader=read)
    assert calls == [] and info["ocr"] is None and info["low_text_pages"] == []


# ── collecting again once OCR can run ───────────────────────────────────────
def _subject(rec):
    return "result" in str(rec.get("title") or "").lower() or "outcome" in str(rec.get("title") or "").lower()


def test_new_records_are_collected_again_only_when_ocr_did_not_run_on_their_image_pages():
    """TC-O4."""
    assert ocr.needs_ocr({"low_text_pages": [2], "ocr": None}, True, None, _subject) is True
    assert ocr.needs_ocr({"low_text_pages": [2], "ocr": ocr.OCR_TAG}, True, None, _subject) is False
    assert ocr.needs_ocr({"low_text_pages": [], "ocr": None}, True, None, _subject) is False
    assert ocr.needs_ocr({"low_text_pages": [2], "ocr": None}, False, None, _subject) is False


def test_old_records_are_collected_again_only_inside_the_reocr_window():
    """TC-O5: records from before OCR do not list their pages. Inside an explicit --reocr-since
    window: no text at all, or a short text on a subject that carries figures (Bajaj Auto's
    results: 1,446 characters of cover letter). Never outside it, never a long text, never a
    routine subject."""
    short = {"when": "2026-10-27T09:51:40", "title": "Outcome of Board Meeting", "text_status": "OK", "text": "x" * 1446}
    assert ocr.needs_ocr(short, True, "2026-10-20", _subject) is True
    assert ocr.needs_ocr(short, True, None, _subject) is False                                  # no window
    assert ocr.needs_ocr(short, True, "2026-10-28", _subject) is False                          # before it
    assert ocr.needs_ocr({**short, "text": "x" * 9000}, True, "2026-10-20", _subject) is False  # full text
    assert ocr.needs_ocr({**short, "title": "Change in Director(s)"}, True, "2026-10-20", _subject) is False
    assert ocr.needs_ocr({**short, "text_status": "NO_TEXT", "text": "", "title": "Change in Director(s)"},
                         True, "2026-10-20", _subject) is True
    assert ocr.needs_ocr(short, False, "2026-10-20", _subject) is False


# ── the collector on a real PDF ─────────────────────────────────────────────
def _pdf_cover_plus_scan() -> bytes:
    """Page 1: a typed cover letter (text layer). Page 2: a picture of a results table (no text)."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.new("L", (2400, 900), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=56)
    for i, line in enumerate(TABLE.splitlines()):
        d.text((80, 120 + i * 160), line, fill=0, font=font)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    t = c.beginText(40, 800)
    for k in range(0, len(COVER), 90):
        t.textLine(COVER[k:k + 90])
    c.drawText(t)
    c.showPage()
    c.drawImage(ImageReader(img), 20, 400, width=560, height=210)
    c.showPage()
    c.save()
    return buf.getvalue()


class _Resp:
    def __init__(self, body):
        self.content = body

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, body):
        self.body = body

    def get(self, url, **kw):
        return _Resp(self.body)


def test_collector_ocrs_the_scanned_page_of_a_cover_plus_scan_pdf(monkeypatch):
    """TC-O6: the collector on a real two-page PDF: the cover is read from its text layer, the
    scanned page goes to OCR, and the status says so (OK_OCR). Without OCR it stays OK with the
    cover alone, and the record lists page 2 as having no text."""
    pytest.importorskip("pdfplumber")
    import collect
    body = _pdf_cover_plus_scan()
    read, calls = _reader()
    monkeypatch.setattr(ocr, "read_page", read)
    text, status, info = collect.document_text(_Client(body), "https://example.invalid/r.pdf", use_ocr=True)
    assert status == "OK_OCR" and calls == [2] and info["ocr_pages"] == [2]
    assert "Bajaj Auto Ltd" in text and "Profit for the period 3,353.76" in text
    text, status, info = collect.document_text(_Client(body), "https://example.invalid/r.pdf", use_ocr=False)
    assert status == "OK" and "Profit for the period" not in text and info["low_text_pages"] == [2]


@pytest.mark.skipif(not ocr.available(), reason="tesseract / pdftoppm not installed in this image")
def test_real_tesseract_reads_the_figures_of_a_scanned_results_table():
    """TC-O7: the real binaries, with the settings in ocr.py, read the figures of the scanned page."""
    pytest.importorskip("pdfplumber")
    import collect
    text, status, info = collect.document_text(_Client(_pdf_cover_plus_scan()), "https://example.invalid/r.pdf", use_ocr=True)
    assert status == "OK_OCR" and info["ocr_pages"] == [2]
    assert "20,003.43" in text and "3,353.76" in text


# ── judged and analysed again when the text grew ────────────────────────────
def test_documents_made_before_ocr_are_no_longer_current():
    """TC-O8."""
    old_text, new_text = "cover letter only", "cover letter only\n[page 2: read by OCR] revenue 20,003.43"
    filing = {"text": new_text, "ocr_pages": [2]}
    assert core.is_current({"text_sha256": core.text_sha(new_text)}, filing) is True
    assert core.is_current({"text_sha256": core.text_sha(old_text)}, filing) is False
    assert core.is_current({}, filing) is False                       # an old verdict, no text hash
    assert core.is_current({}, {"text": old_text}) is True            # untouched filings keep their documents


def _analysis():
    return {"event_type": "earnings", "event_subtype": "quarterly_results", "event_certainty": "final",
            "net_impact_score": 40, "materiality_score": 70, "confidence_score": 80,
            "sum": "Q2 revenue up 34 % YoY.", "amt": [{"v": 20003.43, "u": "cr", "what": "revenue"}],
            "pf": [{"text": "Revenue up 34 % YoY", "weight": 40}], "nf": [{"text": "Margin pressure", "weight": 10}],
            "unk": ["Export outlook"]}


def test_a_filing_whose_text_grew_is_judged_and_analysed_again(tmp_path, monkeypatch):
    """TC-O9: Bajaj Auto's results were judged and analysed on the cover letter. After OCR the
    filing text holds the results pages: the analyser judges it again and analyses it again, and
    a filing that did not change is not sent to the model."""
    (tmp_path / "filings").mkdir()
    old_text = COVER
    new_text = COVER + "\n" + ocr.marker(2) + "\n" + TABLE
    grown = {"id": "a" * 40, "symbol": "BAJAJ-AUTO", "company": "Bajaj Auto Ltd", "title": "Outcome of Board Meeting",
             "summary": "results", "source": "NSE_ANN", "when": "2026-10-27T09:51:40", "text": new_text,
             "text_status": "OK_OCR", "ocr_pages": [2], "low_text_pages": [2], "ocr": ocr.OCR_TAG}
    same = {**grown, "id": "b" * 40, "symbol": "ACME", "text": "Acme order win " * 20, "text_status": "OK",
            "ocr_pages": [], "low_text_pages": [], "ocr": None}
    for f in (grown, same):
        (tmp_path / "filings" / f"{f['id']}.json").write_text(json.dumps(f))
    f_sha = core.prompt_sha((analyse.HERE / "prompts" / "filter_v1.md").read_text())
    a_sha = core.prompt_sha((analyse.HERE / "prompts" / "analysis_v1.md").read_text())
    verdict = {"importance": 85, "category": "earnings", "confidence": "HIGH", "positive": 50, "negative": 5,
               "title": "Q2 results above last year", "why": "Revenue and profit up", "cats": ["exports"], "risks": ["margins"]}
    docs = []
    for f, text in ((grown, old_text), (same, same["text"])):
        before = {**f, "text": text, "ocr_pages": []}
        v = core.filter_doc(before, verdict, f_sha, analyse.MODEL, NOW)
        v.pop("text_sha256")                                           # verdicts made before OCR had no hash
        docs += [v, core.analysis_doc(before, core.clean_analysis(_analysis()), a_sha, analyse.MODEL, NOW)]
    (tmp_path / "docs.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))

    sent = []

    def fake_claude(system, user, schema):
        if schema is core.FILTER_SCHEMA:
            ids = [x["id"] for x in json.loads(user)]
            sent.append(("filter", ids))
            return {"verdicts": [{"id": i, **verdict} for i in ids]}
        sent.append(("analysis", json.loads(user)["symbol"]))
        assert "Profit for the period 3,353.76" in json.loads(user)["document_text"]
        return _analysis()
    monkeypatch.setattr(analyse, "run_claude", fake_claude)
    assert analyse.main(["--work", str(tmp_path)]) == 0
    assert sent == [("filter", ["a" * 40]), ("analysis", "BAJAJ-AUTO")]
    out = [json.loads(x) for x in (tmp_path / "docs.jsonl").read_text().splitlines()]
    redo = [d for d in out[len(docs):] if d["announcement_id"] == "a" * 40]
    assert [d["mode"] for d in redo] == [core.FILTER_MODE, core.ANALYSIS_MODE]
    assert all(d["text_sha256"] == core.text_sha(new_text) and d["ocr_pages"] == [2] for d in redo)
    assert redo[1]["_id"] == docs[1]["_id"]                            # same id: the API replaces the old one


# ── posting the new version ─────────────────────────────────────────────────
def test_a_document_made_again_is_posted_although_its_id_was_sent():
    """TC-O10: ingested.txt lines written before were a bare _id, standing for the first version.
    A second version of the same _id is posted (the API replaces by _id), once, and both
    versions are then recorded as sent."""
    v1 = {"_id": "NSE_ANN:x:abc:m", "analyzed_at": "2026-10-27T10:00:00+00:00"}
    v2 = {"_id": "NSE_ANN:x:abc:m", "analyzed_at": "2026-10-28T01:00:00+00:00"}
    other = {"_id": "NSE_ANN:y:abc:m", "analyzed_at": "2026-10-27T10:00:00+00:00"}
    todo, copies = ingest.unsent([v1, other, v2], {"NSE_ANN:x:abc:m", "NSE_ANN:y:abc:m"})
    assert todo == [v2] and copies == {v2["_id"]: [ingest.sent_key(v2)]}
    todo, _ = ingest.unsent([v1, other, v2], {"NSE_ANN:x:abc:m", "NSE_ANN:y:abc:m", ingest.sent_key(v2)})
    assert todo == []
    # two unsent versions: only the latest is posted, and both are recorded with it
    todo, copies = ingest.unsent([v1, v2], set())
    assert todo == [v2] and copies[v2["_id"]] == [ingest.sent_key(v1), ingest.sent_key(v2)]
