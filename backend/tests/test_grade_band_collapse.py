"""Unit tests for the 7-band → 4-band grade collapse (api-changes.md C.2)."""
import pytest
from services.portfolio_health import grade_to_band


@pytest.mark.parametrize("grade, expected_band", [
    ("A+", "A"),
    ("A",  "A"),
    ("B+", "B"),
    ("B",  "B"),
    ("C",  "C"),
    ("D",  "D"),
    ("F",  "D"),
])
def test_grade_to_band_collapse(grade, expected_band):
    """7-band grade collapses to 4-band per PRD §13.1."""
    assert grade_to_band(grade) == expected_band


def test_grade_to_band_handles_none():
    assert grade_to_band(None) is None


def test_grade_to_band_handles_na():
    assert grade_to_band("N/A") is None


def test_grade_to_band_unknown_grade_passes_through():
    """Unknown grade values pass through unchanged to avoid silent data loss."""
    assert grade_to_band("Z") == "Z"
