"""NIVESH_CAS_PARSER — Google Document AI based CAS parser.

This is the alternative path to `casparser.in` (text-PDF) and Claude
Vision (image OCR via Sonnet 4.5). It uses Google Cloud Document AI to
OCR + table-extract scanned/image-based NSDL CAS PDFs and then walks
the result through `nivesh_cas_normalizer.normalize` so the final JSON
shape is identical to the Claude/CAS-Connect schema. Downstream code
(holdings mapper, transactions normalizer) is unchanged.

Public entry:
    raw_json = parse_with_nivesh(pdf_bytes, password="ABCDE1234F")

Configuration (read from `helpers.secrets`):
    GOOGLE_DOCAI_CREDENTIALS_JSON  — full service-account JSON content
    GOOGLE_DOCAI_PROJECT           — GCP project id
    GOOGLE_DOCAI_PROCESSOR         — Document AI processor id
    GOOGLE_DOCAI_LOCATION          — processor region (default "us")

Optional fast-path: if `casparser` succeeds on a text-based PDF, we
return that result immediately and skip Document AI entirely (saving
~$0.05 per parse + several seconds). Otherwise we split the PDF into
12-page chunks (Document AI sync limit = 15 pages) and parse them
in parallel via a thread pool.
"""
from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Document AI sync API limit is 15 pages — keep chunks safely below.
CHUNK_SIZE_PAGES = 12
MAX_PARALLEL_CHUNKS = 3
TEXT_PDF_MIN_CHARS = 200  # threshold to consider a PDF text-extractable


# ── Configuration helpers ─────────────────────────────────────────────
def _cfg(key: str) -> str:
    from helpers import secrets as _secrets
    return _secrets.get(key) or os.environ.get(key, "")


def is_configured() -> bool:
    """True iff the four DocAI secrets are all set."""
    return bool(
        _cfg("GOOGLE_DOCAI_CREDENTIALS_JSON")
        and _cfg("GOOGLE_DOCAI_PROJECT")
        and _cfg("GOOGLE_DOCAI_PROCESSOR")
    )


def _location() -> str:
    return _cfg("GOOGLE_DOCAI_LOCATION") or "us"


# ── PDF helpers ───────────────────────────────────────────────────────
def _decrypt_pdf(content: bytes, password: str) -> bytes:
    """Return decrypted PDF bytes if encrypted, else passthrough."""
    from PyPDF2 import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(content))
    if not reader.is_encrypted:
        return content
    if not reader.decrypt(password or ""):
        raise ValueError("PDF password rejected")
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _extracted_text_size(content: bytes) -> int:
    """Best-effort text length from the first 3 pages of the PDF."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        text = ""
        for i in range(min(3, len(reader.pages))):
            text += reader.pages[i].extract_text() or ""
        return len(text.strip())
    except Exception:  # noqa: BLE001
        return 0


def _split_pdf(content: bytes, chunk_size: int = CHUNK_SIZE_PAGES) -> List[bytes]:
    """Split a PDF byte string into chunked PDF byte strings."""
    from PyPDF2 import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(content))
    n = len(reader.pages)
    if n <= chunk_size:
        return [content]
    chunks: List[bytes] = []
    for i in range(0, n, chunk_size):
        writer = PdfWriter()
        for j in range(i, min(i + chunk_size, n)):
            writer.add_page(reader.pages[j])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append(buf.getvalue())
    return chunks


# ── Document AI client ────────────────────────────────────────────────
def _build_client():
    """Build a `documentai.DocumentProcessorServiceClient` from the
    service-account JSON stored in secrets. Writes to a temp file
    because the GCP client lib expects a file path on disk for
    `GOOGLE_APPLICATION_CREDENTIALS`.
    """
    from google.cloud import documentai_v1 as documentai
    from google.oauth2 import service_account

    raw = _cfg("GOOGLE_DOCAI_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_DOCAI_CREDENTIALS_JSON missing")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"GOOGLE_DOCAI_CREDENTIALS_JSON is not valid JSON: {e}") from e
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    # Choose the regional endpoint
    location = _location()
    api_endpoint = f"{location}-documentai.googleapis.com"
    client = documentai.DocumentProcessorServiceClient(
        credentials=creds,
        client_options={"api_endpoint": api_endpoint},
    )
    return client, documentai


DOCAI_PROCESS_TIMEOUT_SEC = 120  # hard ceiling; Document AI usually takes <30s for a 10-page CAS


def _process_chunk(chunk_bytes: bytes) -> Dict[str, Any]:
    """Call Document AI on a single PDF chunk; return {text, tables}.

    Uses a hard timeout — without it a network blip can hang an event-loop
    thread indefinitely (we hit this in prod and the entire backend
    wedged on accept()). The gRPC client raises DeadlineExceeded after
    `timeout`, which the chain handler treats as a normal parser failure
    and falls back to claude_vision / casparser_api.
    """
    client, documentai = _build_client()
    project = _cfg("GOOGLE_DOCAI_PROJECT")
    processor = _cfg("GOOGLE_DOCAI_PROCESSOR")
    name = client.processor_path(project, _location(), processor)

    raw_doc = documentai.RawDocument(content=chunk_bytes, mime_type="application/pdf")
    request = documentai.ProcessRequest(name=name, raw_document=raw_doc)
    result = client.process_document(request=request, timeout=DOCAI_PROCESS_TIMEOUT_SEC)
    return _extract_text_and_tables(result.document)


def _extract_text_and_tables(document) -> Dict[str, Any]:
    """Pull the full text and every detected table from a Document AI
    `Document` proto. Mirrors the user's app.py logic verbatim so the
    `{text, tables}` shape is identical."""
    full_text = document.text or ""
    tables: List[List[List[str]]] = []
    for page in document.pages:
        for table in page.tables:
            rows: List[List[str]] = []
            for row in table.body_rows:
                cells: List[str] = []
                for cell in row.cells:
                    cell_text = ""
                    for seg in cell.layout.text_anchor.text_segments:
                        start = int(seg.start_index) if seg.start_index else 0
                        end = int(seg.end_index) if seg.end_index else 0
                        cell_text += full_text[start:end]
                    cells.append(cell_text.strip())
                rows.append(cells)
            tables.append(rows)
    return {"text": full_text, "tables": tables}


def _merge_chunks(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Concatenate text and tables across chunks (in chunk order)."""
    merged_text = ""
    merged_tables: List[List[List[str]]] = []
    for c in chunks:
        merged_text += (c.get("text") or "")
        merged_tables.extend(c.get("tables") or [])
    return {"text": merged_text, "tables": merged_tables}


# ── Public entry point ────────────────────────────────────────────────
def parse_with_nivesh(content: bytes, password: str = "") -> Optional[Dict[str, Any]]:
    """Parse a CAS PDF via Google Document AI + the Nivesh normalizer.

    Returns a JSON dict in the SAME shape as `claude_cas_parser` so
    callers can hand the result straight to `claude_cas_mapper.
    map_to_internal()`. Returns None when DocAI is not configured.
    Raises on credential / API errors so the upload route can render a
    meaningful failure to the admin.
    """
    if not is_configured():
        logger.warning(
            "NIVESH_CAS_PARSER not configured (missing GOOGLE_DOCAI_* secrets)"
        )
        return None

    # 1) Decrypt password-protected PDFs
    try:
        decrypted = _decrypt_pdf(content, password or "")
    except Exception as e:
        logger.error("NIVESH: PDF decryption failed: %s", e)
        raise

    # 1b) Fast-path: try casparser library first for text-based PDFs.
    # Digitally generated NSDL/CDSL/CAMS PDFs parse in < 1 s this way,
    # saving Document AI cost and latency entirely.
    try:
        import casparser as _cp
        import time as _t
        t0 = _t.monotonic()
        _raw = _cp.read_cas_pdf(io.BytesIO(decrypted), password or "", output="dict")
        from helpers.parsing import convert_casparser_to_holdings
        if convert_casparser_to_holdings(_raw):
            logger.info("NIVESH: casparser fast-path hit in %.2fs — skipping Document AI", _t.monotonic() - t0)
            # Return in the same shape as the normalizer so callers work unchanged
            from services.nivesh_cas_normalizer import normalize_casparser_dict
            return normalize_casparser_dict(_raw)
    except ImportError:
        pass
    except Exception as _e:
        logger.info("NIVESH: casparser fast-path failed (%s), proceeding to Document AI", _e)

    # 2) Document AI: split into chunks if large
    chunks = _split_pdf(decrypted)
    logger.info("NIVESH: Document AI processing %s chunk(s)", len(chunks))

    chunk_results: List[Dict[str, Any]] = [None] * len(chunks)  # type: ignore
    if len(chunks) == 1:
        chunk_results[0] = _process_chunk(chunks[0])
    else:
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHUNKS) as ex:
            future_to_idx = {
                ex.submit(_process_chunk, c): i for i, c in enumerate(chunks)
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                try:
                    chunk_results[idx] = fut.result()
                except Exception as e:  # noqa: BLE001
                    logger.error("NIVESH: chunk %s failed: %s", idx, e)
                    raise

    docai_output = _merge_chunks(chunk_results)

    # 3) Normalize {text, tables} → Claude/CAS-Connect schema
    from services.nivesh_cas_normalizer import normalize
    normalized = normalize(docai_output)
    # Strip our internal classification debug field before returning
    normalized.pop("_classification", None)

    h = normalized.get("holdings") or {}
    t = normalized.get("transactions") or {}
    logger.info(
        f"NIVESH parse done — eq={len(h.get('equities') or [])} "
        f"folios={len(h.get('mutual_fund_folios') or [])} "
        f"mf_demat={len(h.get('mutual_funds_demat') or [])} "
        f"sgb={len(h.get('sovereign_gold_bonds') or [])} "
        f"mf_txns={len(t.get('mutual_fund_transactions') or [])}"
    )
    return normalized
