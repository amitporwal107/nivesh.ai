"""Masterdata enrichment must not rewrite a broker's own figures.

`validate_and_enrich_holdings` was built for parsed statements: it fuzzy-matches
names and re-derives quantities from market prices. A broker export states
exact quantities and often names a holding by its symbol alone, so both of
those would corrupt it (10 Reliance Industries became 483.76 Reliance Power)."""
import asyncio

import pytest

from helpers import holdings_reconcile as hr
from helpers import parsing
from services import masterdata

RELIANCE = "INE002A01018"
MASTER = {
    RELIANCE: {"name": "RELIANCE INDUSTRIES LTD", "price": 1400.0, "source": "nse",
               "symbol": "RELIANCE", "series": "EQ"},
}


@pytest.fixture
def stub_master(monkeypatch):
    """Exact lookups from a tiny table; any fuzzy match is an error."""
    fuzzy_calls = []

    def _fuzzy(name, asset_type=""):
        fuzzy_calls.append(name)
        return ("INE614G01033", {"name": "RELIANCE POWER LTD.", "price": 28.94, "source": "nse", "score": 80})

    monkeypatch.setattr(masterdata, "lookup_isin", lambda isin: dict(MASTER[isin]) if isin in MASTER else None)
    monkeypatch.setattr(masterdata, "find_isin_by_name", _fuzzy)
    monkeypatch.setattr(hr, "_symbol_index", {"RELIANCE": RELIANCE})
    return fuzzy_calls


def _export_row(**over):
    row = {"name": "RELIANCE", "ticker": "RELIANCE", "isin": RELIANCE, "asset_type": "equity",
           "quantity": 10.0, "buy_price": 1300.5, "current_price": 1400.0,
           "source": "broker_export", "broker": "kotak"}
    row.update(over)
    return row


def _enrich(row):
    return masterdata.validate_and_enrich_holdings([row])[0]


def test_broker_export_row_keeps_its_quantity_cost_and_symbol(stub_master):
    out = _enrich(_export_row())
    assert (out["quantity"], out["buy_price"], out["current_price"]) == (10.0, 1300.5, 1400.0)
    assert (out["ticker"], out["isin"]) == ("RELIANCE", RELIANCE)
    assert out["name"] == "RELIANCE INDUSTRIES LTD"       # the symbol-only name is completed
    assert stub_master == []                               # never matched by name


def test_broker_export_price_is_not_corrected_against_the_market(stub_master):
    # 60% away from the masterdata price: for a parsed statement this re-derives the quantity.
    out = _enrich(_export_row(current_price=560.0))
    assert (out["quantity"], out["buy_price"], out["current_price"]) == (10.0, 1300.5, 560.0)


def test_broker_export_without_a_price_takes_the_masterdata_price(stub_master):
    out = _enrich(_export_row(current_price=0))
    assert (out["current_price"], out["quantity"], out["buy_price"]) == (1400.0, 10.0, 1300.5)


def test_broker_export_keeps_a_real_name(stub_master):
    assert _enrich(_export_row(name="Reliance Industries"))["name"] == "Reliance Industries"


def test_broker_export_without_an_isin_column_is_resolved_by_exact_symbol(stub_master):
    row = _export_row()
    del row["isin"]
    out = _enrich(row)
    assert (out["isin"], out["ticker"], out["quantity"]) == (RELIANCE, "RELIANCE", 10.0)
    assert stub_master == []


def test_broker_export_that_cannot_be_resolved_is_left_exactly_as_it_is(stub_master):
    row = _export_row(name="UNITEC", ticker="UNITEC")      # ICICI's own stock code
    del row["isin"]
    assert _enrich(dict(row)) == row
    assert stub_master == []


def test_a_row_that_states_its_isin_is_looked_up_by_it_and_never_name_matched(stub_master):
    # e.g. a holdings table whose broker could not be identified: no source, symbol in ticker.
    known = {"name": "RELIANCE", "ticker": "RELIANCE", "isin": RELIANCE, "asset_type": "equity",
             "quantity": 10.0, "buy_price": 1300.5, "current_price": 1400.0}
    out = _enrich(dict(known))
    assert (out["ticker"], out["quantity"], out["name"]) == ("RELIANCE", 10.0, "RELIANCE INDUSTRIES LTD")

    unknown = dict(known, isin="INE999Z01011")
    assert _enrich(dict(unknown)) == unknown
    assert stub_master == []


def test_statement_rows_are_still_enriched_as_before(stub_master):
    # ISIN in ticker and no `isin` key: the exact lookup, as before.
    cas = {"name": RELIANCE, "ticker": RELIANCE, "asset_type": "equity",
           "quantity": 10.0, "buy_price": 1400.0, "current_price": 1400.0}
    assert _enrich(cas)["name"] == "RELIANCE INDUSTRIES LTD"
    # No ISIN anywhere: the name match still runs.
    loose = {"name": "Reliance Power", "ticker": "", "asset_type": "equity",
             "quantity": 5.0, "buy_price": 28.94, "current_price": 28.94}
    assert _enrich(loose)["ticker"] == "INE614G01033"
    assert stub_master == ["Reliance Power"]


# ── The real masterdata files, through the real import path ──────────────
class _Result:
    deleted_count = 0


class _Collection:
    def __init__(self):
        self.rows = []

    def find(self, *_a, **_k):
        return self

    async def to_list(self, length=None):
        return []

    async def count_documents(self, *_a, **_k):
        return 0

    async def delete_many(self, *_a, **_k):
        return _Result()

    async def delete_one(self, *_a, **_k):
        return _Result()

    async def update_one(self, *_a, **_k):
        return None

    async def insert_one(self, doc):
        self.rows.append(doc)


class _Db:
    def __init__(self):
        for name in ("holdings", "mfd_profile_signal_cache", "fund_performance_cache", "upload_tasks"):
            setattr(self, name, _Collection())


def test_save_holdings_stores_a_symbol_named_export_row_intact(monkeypatch):
    if not masterdata.lookup_isin(RELIANCE):
        pytest.skip("masterdata files are not on disk in this environment")

    async def _no_background(*_a, **_k):
        return None

    db = _Db()
    monkeypatch.setattr(parsing, "db", db)
    monkeypatch.setattr(parsing, "_enrich_after_upload", _no_background)
    monkeypatch.setattr(hr, "_symbol_index", None)         # build it from the real files

    async def _go():
        await parsing.save_holdings("u1", [_export_row()], "Excel")
        await asyncio.sleep(0)

    asyncio.run(_go())

    (stored,) = db.holdings.rows
    assert (stored["quantity"], stored["buy_price"]) == (10.0, 1300.5)
    assert (stored["ticker"], stored["isin"], stored["source"], stored["broker"]) == (
        "RELIANCE", RELIANCE, "broker_export", "kotak")
    assert "RELIANCE INDUSTRIES" in stored["name"].upper()
