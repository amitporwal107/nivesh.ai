"""nidp.mf_amc_master must keep up with the AMFI feed on its own.

amc_id is resolved by prefix-matching amc_name_raw against mf_amc_master.
That master held 10 AMCs while the feed carries 51, so 5,154 of 14,454 scheme
rows had a NULL amc_id despite 5,149 of them knowing their AMC by name — and
the mf_holdings quant adapter, which looks up `WHERE amc_id = 'quant'`,
silently discarded 29 already-downloaded funds because of it.

A one-off backfill does not hold: AlphaGrep Mutual Fund entered the feed within
a day and immediately had 12 unmapped schemes.
"""
from __future__ import annotations

import pytest

from nidp.services.amfi_nav.writer import _amc_slug, register_unknown_amcs


# ── slug derivation ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("DSP Mutual Fund",                "dsp"),
    ("Baroda BNP Paribas Mutual Fund", "baroda_bnp_paribas"),
    ("IL&FS Mutual Fund (IDF)",        "il_and_fs"),
    ("360 ONE Mutual Fund",            "360_one"),
    ("WhiteOak Capital Mutual Fund",   "whiteoak_capital"),
    ("AlphaGrep Mutual Fund",          "alphagrep"),
    ("PGIM India Mutual Fund",         "pgim_india"),
])
def test_slug_derivation(raw, expected):
    assert _amc_slug(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("quant Mutual Fund",        "quant"),
    ("JM Financial Mutual Fund", "jm_financial"),
])
def test_ids_already_used_by_the_source_registry_are_preserved(raw, expected):
    """A second id for the same AMC would silently split its schemes."""
    assert _amc_slug(raw) == expected


def test_quant_and_quantum_get_distinct_ids():
    """The collision that makes this fiddly: one name prefixes the other."""
    assert _amc_slug("quant Mutual Fund") != _amc_slug("Quantum Mutual Fund")


# ── registration ─────────────────────────────────────────────────────
class _Conn:
    def __init__(self, results=None):
        self.calls = []
        self._results = results or {}

    async def execute(self, sql, *args):
        self.calls.append(args)
        return self._results.get(args[0], "INSERT 0 1")


@pytest.mark.asyncio
async def test_registers_each_distinct_amc_once():
    conn = _Conn()
    rows = [{"amc_name_raw": "DSP Mutual Fund"},
            {"amc_name_raw": "DSP Mutual Fund"},
            {"amc_name_raw": "Groww Mutual Fund"}]
    added = await register_unknown_amcs(conn, rows)
    assert added == 2
    assert sorted(c[0] for c in conn.calls) == ["dsp", "groww"]


@pytest.mark.asyncio
async def test_stores_the_full_name_not_a_stem():
    """The resolver disambiguates by ORDER BY length(amc_name) DESC, so a
    bare stem would let 'quant' swallow 'Quantum'."""
    conn = _Conn()
    await register_unknown_amcs(conn, [{"amc_name_raw": "quant Mutual Fund"}])
    assert conn.calls[0] == ("quant", "quant Mutual Fund")


@pytest.mark.asyncio
async def test_rows_without_an_amc_name_are_skipped():
    conn = _Conn()
    added = await register_unknown_amcs(
        conn, [{"amc_name_raw": None}, {"amc_name_raw": "  "}, {}])
    assert added == 0
    assert conn.calls == []


@pytest.mark.asyncio
async def test_already_present_amc_is_not_counted():
    conn = _Conn(results={"dsp": "INSERT 0 0"})
    added = await register_unknown_amcs(conn, [{"amc_name_raw": "DSP Mutual Fund"}])
    assert added == 0
