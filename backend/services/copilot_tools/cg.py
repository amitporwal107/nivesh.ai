"""Realised Capital-Gains statement tool for the Nivesh Copilot (WF-04-07).

Wraps the proven FIFO engine (``services.tax_engine_fifo``) + the locked A/B/C
formatter (``services.cg_statement``) into a chat-ready result, so a user can ask
*"what are my capital gains / tax if I book gains this FY?"* and get the
Section A (STCG 111A) / B (LTCG 112A) / summary statement as a chat widget.

Pure wrapper — NO new tax logic. Every number is exactly what the FIFO engine and
``cg_statement.build_statement`` already produce (both staging-verified in epic 0.12).

Public entry point:
    get_capital_gains(user_id, fy=None, holder=None, pan=None) -> CgResult
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CgResult:
    """Mirrors BacktestResult / SipResult — `rows`+`data` are widget-ready,
    `summary` (≤300 chars) is the only thing the LLM sees."""

    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"CAPITAL_GAINS status=error reason={self.error}"
        return f"CAPITAL_GAINS | {self.summary}"


def _fy_bounds(fy: Optional[str], today: Optional[date] = None) -> Tuple[date, date, str]:
    """(start, end, label) for an Indian FY. Accepts 'FY 2025-26' / '2025-26' /
    '2025'; defaults to the current FY (Apr 1 – Mar 31). Same rule as
    routes/portfolio_tax.py:_fy_bounds so the chat tool and the REST endpoint agree."""
    today = today or date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    if fy:
        m = re.search(r"(20\d{2})", fy)
        if m:
            start_year = int(m.group(1))
    return (date(start_year, 4, 1), date(start_year + 1, 3, 31),
            f"FY {start_year}-{str(start_year + 1)[2:]}")


def parse_fy(text: str) -> Optional[str]:
    """Extract an FY label from free text ('FY 2024-25', '2023-24', 'FY2025'); None → current."""
    if not text:
        return None
    m = re.search(r"(?:fy\s*)?(20\d{2})\s*[-/]\s*(\d{2,4})", text, re.IGNORECASE)
    if m:
        return f"FY {m.group(1)}-{m.group(2)[-2:]}"
    m = re.search(r"\bfy\s*(20\d{2})\b", text, re.IGNORECASE)
    if m:
        return f"FY {m.group(1)}"
    return None


def _inr(v: Any) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "₹0"
    if abs(v) >= 1e7:
        return f"₹{v/1e7:.2f}Cr"
    if abs(v) >= 1e5:
        return f"₹{v/1e5:.2f}L"
    return f"₹{v:,.0f}"


async def get_capital_gains(
    user_id: str,
    fy: Optional[str] = None,
    holder: Optional[str] = None,
    pan: Optional[str] = None,
) -> CgResult:
    """Realised FIFO capital-gains statement for `user_id` and the given FY.

    Reuses ``tax_engine_fifo.build_user_tax_state`` + ``cg_statement.build_statement``
    verbatim. An empty portfolio / no realised events is a valid *empty* statement
    (ok=True with zeroed sections), not an error.
    """
    try:
        from services import tax_engine_fifo, cg_statement
    except ImportError as exc:  # pragma: no cover — engine always present in app
        return CgResult(ok=False, summary="Capital-gains engine unavailable", error=str(exc))

    start, end, fy_label = _fy_bounds(fy)
    events: List[Dict[str, Any]] = []
    try:
        state = await tax_engine_fifo.build_user_tax_state(user_id)
        for e in state.calculator.events:
            d = asdict(e)
            sd = d.get("sell_date")
            sdate = sd.date() if isinstance(sd, datetime) else sd
            if sdate is None or (start <= sdate <= end):
                events.append(d)
    except Exception as exc:  # noqa: BLE001 — no CAS / no realised events → empty statement, not a crash
        logger.warning("cg tool: FIFO build failed for %s: %s", user_id, exc)

    statement = cg_statement.build_statement(
        events, fy_label=fy_label, holder=holder, pan=pan,
        period=f"{start.strftime('%d-%b-%Y')} to {end.strftime('%d-%b-%Y')}",
        generated_on=date.today().isoformat(),
    )

    a = statement["sections"]["A_stcg_equity"]
    b = statement["sections"]["B_ltcg_equity"]
    stcg = a["total"]["gain_rs"]
    ltcg = b["total"]["gain_rs"]
    est_tax = statement.get("estimated_tax_rs", 0)
    n_rows = len(a["rows"]) + len(b["rows"])

    if n_rows == 0:
        summary = (f"{fy_label}: no realised capital gains — no sell/redeem transactions "
                   "recorded in this FY (statement is empty).")
    else:
        summary = (
            f"{fy_label}: STCG {_inr(stcg)} (Sec 111A) · LTCG {_inr(ltcg)} "
            f"(Sec 112A, ₹1.25L exempt) · est. tax {_inr(est_tax)} across {n_rows} lot(s)."
        )

    # Widget rows = every lot across both sections (already shaped by cg_statement).
    rows = a["rows"] + b["rows"]
    return CgResult(ok=True, summary=summary, data=statement, rows=rows)
