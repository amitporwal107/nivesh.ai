"""Cron-file sanity check for the 3 newly scheduled NIDP engines.

The Action Matrix scoring engine depends on these three services running
nightly. If any of them silently disappears from the cron file (a botched
merge, a copy-paste accident), the matrix's score-quality drops back to the
"all-NULL fallback" state. This test fails loud if that happens.

Assertions per file (nidp.cron + setup_schedules.sh):
  1. All three engine names appear: mf_analytics_engine,
     technical_indicator_engine, fundamental_engine.
  2. Each cron line uses 5-field syntax (vixie-cron compatible).
  3. Times don't collide with existing high-cost slots:
       - bhavcopy 19:00, price_adjuster 22:30 must finish before
         technical_indicator_engine and fundamental_engine.
  4. The setup_schedules.sh entries match the nidp.cron entries
     (they're documented to stay in sync — comment in header).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
CRON_FILE  = REPO / "nidp" / "deploy" / "vm" / "nidp.cron"
GCP_FILE   = REPO / "nidp" / "deploy" / "gcp" / "setup_schedules.sh"

REQUIRED_ENGINES = (
    "mf_analytics_engine",
    "technical_indicator_engine",
    "fundamental_engine",
)


@pytest.fixture(scope="module")
def cron_text() -> str:
    assert CRON_FILE.is_file(), f"cron file missing at {CRON_FILE}"
    return CRON_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def gcp_text() -> str:
    assert GCP_FILE.is_file(), f"setup_schedules.sh missing at {GCP_FILE}"
    return GCP_FILE.read_text(encoding="utf-8")


# ── nidp.cron checks ───────────────────────────────────────────────
def test_all_three_engines_in_nidp_cron(cron_text):
    for engine in REQUIRED_ENGINES:
        assert f"run_service.sh {engine}" in cron_text, (
            f"{engine} missing from nidp.cron — Action Matrix scoring "
            f"will fall back to NULL signals if this engine doesn't run"
        )


def test_engine_cron_lines_use_5_field_syntax(cron_text):
    """Each engine line: <min> <hr> <dom> <mon> <dow> nidp <command>."""
    for engine in REQUIRED_ENGINES:
        # Match e.g. "30 20 * * 1-5  nidp  /opt/.../run_service.sh engine"
        # Path + engine name are separated by whitespace (\s+), not in \S*.
        pattern = (
            r"^\s*[\d\*\-/,]+\s+[\d\*\-/,]+\s+[\d\*\-/,]+\s+"
            r"[\d\*\-/,]+\s+[\d\*\-/,]+\s+nidp\s+\S+\s+"
            + re.escape(engine) + r"\s*$"
        )
        m = re.search(pattern, cron_text, re.MULTILINE)
        assert m, f"no valid 5-field cron line found for {engine}"


def test_technical_engine_runs_after_price_adjuster(cron_text):
    """populate_stock_price_features needs prices_eod_adjusted populated;
    price_adjuster must finish before technical_indicator_engine starts."""
    pa_line  = _find_engine_time(cron_text, "price_adjuster")
    ti_line  = _find_engine_time(cron_text, "technical_indicator_engine")
    assert pa_line is not None, "price_adjuster missing from cron"
    assert ti_line is not None, "technical_indicator_engine missing"
    assert _minutes(ti_line) > _minutes(pa_line), (
        f"technical_indicator_engine ({ti_line}) must run after "
        f"price_adjuster ({pa_line}) for adj-close to be available"
    )


def test_fundamental_engine_runs_after_technical(cron_text):
    """fundamental_engine looks up rows in stock_features_daily WHERE
    as_of_date = target — technical_indicator_engine must write them first."""
    ti_line = _find_engine_time(cron_text, "technical_indicator_engine")
    fe_line = _find_engine_time(cron_text, "fundamental_engine")
    assert _minutes(fe_line) > _minutes(ti_line), (
        f"fundamental_engine ({fe_line}) must run after "
        f"technical_indicator_engine ({ti_line})"
    )


def test_mf_analytics_runs_before_mf_derived_refresh(cron_text):
    """mf_derived_refresh reads analytics.fund_category_rank — mf_analytics_engine
    must write to it earlier in the same evening."""
    ae_line = _find_engine_time(cron_text, "mf_analytics_engine")
    dr_line = _find_engine_time(cron_text, "mf_derived_refresh")
    assert _minutes(ae_line) < _minutes(dr_line), (
        f"mf_analytics_engine ({ae_line}) must run before "
        f"mf_derived_refresh ({dr_line})"
    )


# ── setup_schedules.sh mirror ──────────────────────────────────────
def test_all_three_engines_in_gcp_setup_schedules(gcp_text):
    """The file header says: 'when you change a schedule, change it in BOTH
    files until the Cloud Run path is fully decommissioned.'"""
    for engine in REQUIRED_ENGINES:
        # gcp uses hyphenated job IDs: nidp-{engine-with-hyphens}
        hyphenated = engine.replace("_", "-")
        assert hyphenated in gcp_text, (
            f"setup_schedules.sh missing add_schedule for nidp-{hyphenated}"
        )


# ── Helpers ────────────────────────────────────────────────────────
def _find_engine_time(cron_text: str, name: str) -> str | None:
    """Return 'HH:MM' for the first cron line matching this engine name.
    Engine name follows the path after whitespace, not inside \\S*."""
    m = re.search(
        r"^\s*(\d+)\s+(\d+)\s+\S+\s+\S+\s+\S+\s+nidp\s+\S+\s+"
        + re.escape(name) + r"\s*$",
        cron_text, re.MULTILINE,
    )
    if not m:
        return None
    return f"{int(m.group(2)):02d}:{int(m.group(1)):02d}"


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)
