"""Portfolio Builder export — PDF + WhatsApp deeplink generation.

Two surfaces:

  • render_portfolio_pdf(builder_payload)
        Returns PDF bytes (reportlab). Used by /api/portfolio-builder/export.pdf.

  • build_whatsapp_message(builder_payload, *, public_url=None)
        Returns a plain-text summary the frontend wraps in https://wa.me/?text=...

The PDF is intentionally one-page, advisor-presentable: hero allocation
gauge + bucket table + per-fund rationale + footer disclaimer. We use
reportlab (already in requirements.txt) to avoid pulling in heavyweight
HTML→PDF libraries like weasyprint that need system fonts + libcairo.
"""
from __future__ import annotations

import io
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fmt_rs(n: Optional[float]) -> str:
    if n is None:
        return "—"
    n = float(n)
    if n >= 1e7:
        return f"Rs.{n/1e7:.2f}Cr"
    if n >= 1e5:
        return f"Rs.{n/1e5:.2f}L"
    if n >= 1000:
        return f"Rs.{n/1000:.1f}k"
    return f"Rs.{int(n):,}"


def _fmt_pct(n: Optional[float], dp: int = 1) -> str:
    return "—" if n is None else f"{float(n):.{dp}f}%"


def render_portfolio_pdf(payload: Dict[str, Any], *, client_name: str = "Client") -> bytes:
    """Render the proposed portfolio as a PDF and return raw bytes.

    Layout:
      ┌────────────────────────────────────────────────────┐
      │  Proposed Portfolio for {client_name}              │
      │  Generated {date} · Risk: {persona}                │
      ├────────────────────────────────────────────────────┤
      │  Asset Allocation                                  │
      │    Equity 60%   ████████████░░░  Rs. xx           │
      │    Debt   25%   ██████░░░░░░░░░  Rs. xx           │
      │    Gold   10%   ██░░░░░░░░░░░░░  Rs. xx           │
      │    Cash    5%   █░░░░░░░░░░░░░░  Rs. xx           │
      ├────────────────────────────────────────────────────┤
      │  Equity (3 funds)                                  │
      │    1. Fund A — Quality 78 · Expense 0.62%          │
      │    2. ...                                          │
      ├────────────────────────────────────────────────────┤
      │  Why this portfolio                                │
      │    • Asset mix from your moderate risk profile     │
      │    • ...                                           │
      └────────────────────────────────────────────────────┘
      Disclaimer: Educational. Consult a SEBI-registered advisor.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        )
    except ImportError:
        # Defensive: shouldn't fire (reportlab is in requirements.txt) but if
        # it does, we'd rather raise a clear error than crash inside reportlab.
        raise RuntimeError("reportlab is required for PDF export but is not installed")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Portfolio Proposal — {client_name}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18,
                        spaceAfter=4, textColor=colors.HexColor("#0f172a"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12,
                        spaceBefore=12, spaceAfter=6,
                        textColor=colors.HexColor("#1e293b"))
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5,
                          textColor=colors.HexColor("#334155"))
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8,
                           textColor=colors.HexColor("#64748b"))

    story: List[Any] = []

    # ── Header ────────────────────────────────────────────────────────
    story.append(Paragraph(f"Proposed Portfolio for {client_name}", h1))
    risk_line = (
        f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y')}"
        f" &nbsp;·&nbsp; Risk: <b>{(payload.get('risk_profile') or 'moderate').title()}</b>"
    )
    if payload.get("totals", {}).get("monthly_sip_rs"):
        risk_line += f" &nbsp;·&nbsp; SIP: {_fmt_rs(payload['totals']['monthly_sip_rs'])}/mo"
    if payload.get("totals", {}).get("lumpsum_rs"):
        risk_line += f" &nbsp;·&nbsp; Lump sum: {_fmt_rs(payload['totals']['lumpsum_rs'])}"
    story.append(Paragraph(risk_line, body))

    # ── Asset allocation table ────────────────────────────────────────
    story.append(Paragraph("Asset allocation", h2))
    alloc = payload.get("allocation") or {}
    alloc_rs = payload.get("allocation_rs") or {}
    sip_rs = payload.get("monthly_sip_split_rs") or {}
    rows = [["Bucket", "Target %", "Lump-sum (Rs.)", "Monthly SIP (Rs.)"]]
    for bucket, pct in alloc.items():
        rows.append([
            bucket.title(),
            _fmt_pct(float(pct), 1),
            _fmt_rs(alloc_rs.get(bucket)) if alloc_rs else "—",
            _fmt_rs(sip_rs.get(bucket)) if sip_rs else "—",
        ])
    tbl = Table(rows, colWidths=[40 * mm, 30 * mm, 50 * mm, 50 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)

    # ── Per-bucket fund picks ─────────────────────────────────────────
    for bucket in payload.get("buckets", []):
        if not bucket.get("funds"):
            continue
        title = (
            f"{bucket['bucket'].title()} ({bucket['n_funds_picked']} fund{'s' if bucket['n_funds_picked'] != 1 else ''})"
            f" &nbsp;·&nbsp; {_fmt_pct(bucket.get('target_pct'), 1)} of portfolio"
        )
        story.append(Paragraph(title, h2))
        fund_rows = [["#", "Scheme", "Why", "Lump-sum"]]
        for i, f in enumerate(bucket["funds"], start=1):
            fund_rows.append([
                str(i),
                f.get("scheme_name") or "—",
                Paragraph(f.get("rationale") or "—", small),
                _fmt_rs(f.get("lumpsum_rs")) if f.get("lumpsum_rs") else "—",
            ])
        ftbl = Table(fund_rows, colWidths=[8 * mm, 60 * mm, 75 * mm, 27 * mm])
        ftbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ]))
        story.append(ftbl)
        story.append(Spacer(1, 4))

    # ── Why this portfolio ────────────────────────────────────────────
    if payload.get("rationale"):
        story.append(Paragraph("Why this portfolio", h2))
        for r in payload["rationale"]:
            story.append(Paragraph(f"• {r}", body))

    # ── Disclaimer ────────────────────────────────────────────────────
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<i>Proposal generated for educational purposes. Mutual fund investments are subject "
        "to market risks; please read all scheme-related documents before investing. Consult a "
        "SEBI-registered investment advisor for personal financial advice.</i>",
        small,
    ))

    doc.build(story)
    return buf.getvalue()


# ── WhatsApp deeplink summary ──────────────────────────────────────────
def build_whatsapp_message(
    payload: Dict[str, Any], *,
    client_name: str = "Hi",
    public_url: Optional[str] = None,
) -> Dict[str, str]:
    """Return {message, deeplink} where deeplink is a wa.me URL.

    The frontend opens the deeplink in a new tab; the user's WhatsApp picks
    the contact and pre-fills the message. No BSP / Twilio integration
    needed for this MVP — that's the cleanest way to ship a WhatsApp share
    flow without comms infrastructure.
    """
    risk = (payload.get("risk_profile") or "moderate").title()
    alloc = payload.get("allocation") or {}
    sip_rs = (payload.get("totals") or {}).get("monthly_sip_rs")
    lump_rs = (payload.get("totals") or {}).get("lumpsum_rs")
    n_funds = (payload.get("totals") or {}).get("total_funds") or sum(
        b.get("n_funds_picked", 0) for b in payload.get("buckets", [])
    )

    lines: List[str] = []
    lines.append(f"Hi {client_name}, here's the portfolio I built for you:")
    lines.append("")
    lines.append(f"📊 *Risk profile:* {risk}")
    if sip_rs:
        lines.append(f"📅 *Monthly SIP:* {_fmt_rs(sip_rs)}")
    if lump_rs:
        lines.append(f"💰 *Lump sum:* {_fmt_rs(lump_rs)}")
    lines.append("")
    lines.append("*Asset mix:*")
    for bucket, pct in alloc.items():
        lines.append(f"  • {bucket.title()}: {pct:.0f}%")
    lines.append("")
    lines.append(f"*{n_funds} funds picked* across the buckets — top quality + low expense.")
    if payload.get("rationale"):
        lines.append("")
        lines.append("*Why this mix:*")
        for r in payload["rationale"][:2]:
            lines.append(f"  • {r}")
    if public_url:
        lines.append("")
        lines.append(f"View full proposal: {public_url}")

    msg = "\n".join(lines)
    return {
        "message": msg,
        "deeplink": f"https://wa.me/?text={urllib.parse.quote(msg)}",
    }
