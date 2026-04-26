"""Tests for the gmail_service CAS email scanner — specifically the
flattened attachment fields used by the public CAS-invite flow.
"""
from unittest.mock import MagicMock

from services.gmail_service import _find_pdf_attachments


def test_find_pdf_attachments_handles_nested_parts():
    """NSDL CAS emails wrap PDFs in multipart/mixed → multipart/alternative
    nesting. The recursion must descend into all parts."""
    payload = {
        "parts": [
            {"mimeType": "text/html", "body": {"data": "..."}},
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "filename": "CAS_OCT_2025.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "ATT-1", "size": 124000},
                    }
                ],
            },
        ],
    }
    res = _find_pdf_attachments(payload)
    assert len(res) == 1
    assert res[0]["filename"] == "CAS_OCT_2025.pdf"
    assert res[0]["attachment_id"] == "ATT-1"
    assert res[0]["size"] == 124000


def test_find_pdf_attachments_skips_inline_pdfs_without_id():
    """An inline content-id PDF without `attachmentId` shouldn't crash —
    Gmail uses inline body for tiny attachments and only assigns an
    attachmentId when the part exceeds ~1 MB."""
    payload = {
        "filename": "tiny.pdf",
        "mimeType": "application/pdf",
        "body": {"size": 500},     # no attachmentId
    }
    res = _find_pdf_attachments(payload)
    assert res == []


def test_find_pdf_attachments_ignores_non_pdf():
    payload = {
        "filename": "spreadsheet.xlsx",
        "mimeType": "application/vnd.ms-excel",
        "body": {"attachmentId": "ATT-2", "size": 50000},
    }
    res = _find_pdf_attachments(payload)
    assert res == []


def test_find_pdf_attachments_returns_multiple():
    """Some CAMS / KFinTech emails attach BOTH NSDL and CDSL PDFs."""
    payload = {
        "parts": [
            {
                "filename": "NSDL_CAS.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "A1", "size": 100000},
            },
            {
                "filename": "CDSL_CAS.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "A2", "size": 80000},
            },
        ],
    }
    res = _find_pdf_attachments(payload)
    assert {a["filename"] for a in res} == {"NSDL_CAS.pdf", "CDSL_CAS.pdf"}


def test_scan_for_cas_emails_flattens_first_attachment():
    """End-to-end: `scan_for_cas_emails` should now expose `attachment_id`
    + `filename` at the top level so the client doesn't have to dig into
    the array. Critical for the CasConnect.jsx → /import flow."""
    from services import gmail_service

    # Stub the Gmail SDK
    fake_msg = {
        "payload": {
            "headers": [
                {"name": "From", "value": "noreply@nsdlcas.nsdl.com"},
                {"name": "Subject", "value": "Consolidated Account Statement"},
                {"name": "Date", "value": "Wed, 01 Oct 2025 09:00:00 +0530"},
            ],
            "parts": [{
                "filename": "NSDL_CAS_OCT.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "FLAT-1", "size": 156000},
            }],
        }
    }

    msg_chain = MagicMock()
    msg_chain.users().messages().list.return_value.execute.return_value = {
        "messages": [{"id": "MSG-1"}]
    }
    msg_chain.users().messages().get.return_value.execute.return_value = fake_msg

    res = gmail_service.scan_for_cas_emails(msg_chain, max_results=10)
    assert len(res) == 1
    e = res[0]
    # Flattened fields — these are what CasConnect.jsx uses
    assert e["attachment_id"] == "FLAT-1"
    assert e["filename"] == "NSDL_CAS_OCT.pdf"
    assert e["size"] == 156000
    # Array still present for multi-PDF consumers
    assert len(e["attachments"]) == 1
    assert e["attachments"][0]["attachment_id"] == "FLAT-1"
