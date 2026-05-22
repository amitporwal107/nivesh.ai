"""Unit tests for the source-priority decision logic (pure functions)."""
from __future__ import annotations

import pytest

from portfolio_ingestion.services.source_priority import (
    METHOD_PRIORITY,
    Method,
    SnapshotKey,
    SourceType,
    incoming_wins,
    method_priority,
)


def _k(source: SourceType, statement_to: str, method: Method) -> SnapshotKey:
    return SnapshotKey(
        source_type=source,
        statement_to=statement_to,
        method_priority=method_priority(method),
    )


# ── No current active ──────────────────────────────────────────────────────


def test_no_current_active_anything_wins() -> None:
    incoming = _k(SourceType.MF_CAMS, "2026-01-31", Method.UPLOAD)
    assert incoming_wins(incoming, None) is True


# ── eCAS vs MF ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ecas_source,mf_source",
    [
        (SourceType.ECAS_CDSL, SourceType.MF_CAMS),
        (SourceType.ECAS_CDSL, SourceType.MF_KFIN),
        (SourceType.ECAS_NSDL, SourceType.MF_CAMS),
        (SourceType.ECAS_NSDL, SourceType.MF_KFIN),
    ],
)
def test_ecas_supersedes_mf_even_when_mf_is_newer(
    ecas_source: SourceType, mf_source: SourceType
) -> None:
    """Incoming eCAS (older statement) still beats current MF (newer)."""
    incoming = _k(ecas_source, "2026-01-31", Method.UPLOAD)
    current = _k(mf_source, "2026-03-31", Method.INBOX)
    assert incoming_wins(incoming, current) is True


def test_mf_does_not_supersede_ecas_even_when_mf_is_newer() -> None:
    """Never demote eCAS to MF (would lose stocks/bonds/ETFs)."""
    incoming = _k(SourceType.MF_CAMS, "2026-03-31", Method.INBOX)
    current = _k(SourceType.ECAS_CDSL, "2026-01-31", Method.UPLOAD)
    assert incoming_wins(incoming, current) is False


# ── Same tier — later statement wins ──────────────────────────────────────


def test_same_tier_later_statement_wins() -> None:
    incoming = _k(SourceType.ECAS_CDSL, "2026-03-31", Method.UPLOAD)
    current = _k(SourceType.ECAS_CDSL, "2026-02-28", Method.UPLOAD)
    assert incoming_wins(incoming, current) is True


def test_same_tier_older_statement_loses() -> None:
    incoming = _k(SourceType.ECAS_CDSL, "2026-01-31", Method.UPLOAD)
    current = _k(SourceType.ECAS_CDSL, "2026-02-28", Method.UPLOAD)
    assert incoming_wins(incoming, current) is False


# ── Same tier + same statement — method priority tie-break ────────────────


@pytest.mark.parametrize(
    "winner,loser",
    [
        (Method.CDSL_FETCH, Method.INBOX),
        (Method.CDSL_FETCH, Method.UPLOAD),
        (Method.INBOX,      Method.UPLOAD),
        (Method.GENERATOR,  Method.UPLOAD),
        (Method.INBOX,      Method.GENERATOR),
    ],
)
def test_method_priority_tie_break(winner: Method, loser: Method) -> None:
    incoming = _k(SourceType.ECAS_CDSL, "2026-01-31", winner)
    current = _k(SourceType.ECAS_CDSL, "2026-01-31", loser)
    assert incoming_wins(incoming, current) is True


def test_method_priority_status_quo_when_equal() -> None:
    """Identical incoming → don't churn (incoming loses)."""
    incoming = _k(SourceType.ECAS_CDSL, "2026-01-31", Method.UPLOAD)
    current = _k(SourceType.ECAS_CDSL, "2026-01-31", Method.UPLOAD)
    assert incoming_wins(incoming, current) is False


# ── Source enum / method-priority sanity ──────────────────────────────────


def test_method_priority_unknown_string_is_zero() -> None:
    assert method_priority("not-a-method") == 0


def test_method_priority_known_string_resolves() -> None:
    assert method_priority("inbox") == METHOD_PRIORITY[Method.INBOX]


def test_source_type_is_ecas_flag() -> None:
    assert SourceType.ECAS_CDSL.is_ecas is True
    assert SourceType.ECAS_NSDL.is_ecas is True
    assert SourceType.MF_CAMS.is_ecas is False
    assert SourceType.MF_KFIN.is_ecas is False
