"""Canonicalization tests for `validate_and_enrich_holdings` (the single import
chokepoint: save_holdings → validate_and_enrich_holdings).

The CAS/Claude extractor frequently truncates scheme names to a 2-3 word stub
("ICICI Prudential", "Mirae Asset Large", "Kotak Midcap Fund"). These pass the
garbled-name guard (they have letters, length >= 5, no '#', not a raw ISIN), so
the old enrichment KEPT them and every consumer (Performance "Top Holdings",
X-ray, Portfolio, Copilot) rendered the stub.

The enrichment now also replaces a name when the masterdata record — resolved by
ISIN, so it is unambiguous — is materially longer, swapping in the full canonical
scheme/company name. These assertions run against the committed AMFI master
(backend/data/amfi_data.csv) with real ISINs, so they are deterministic and
offline. Resolution MUST key off the ISIN, never a fuzzy name match ("Kotak
Midcap" alone matches a dozen distinct schemes).
"""
from services.masterdata import lookup_isin, validate_and_enrich_holdings


def _mf(name, ticker, asset_type="mutual_fund"):
    return {"name": name, "ticker": ticker, "asset_type": asset_type,
            "quantity": 100.0, "buy_price": 50.0, "current_price": 60.0}


def test_truncated_mf_name_expands_to_canonical_by_isin():
    """A truncated stub is replaced by the exact AMFI scheme name for its ISIN."""
    isin = "INF769K01AX2"  # Mirae Asset Large Cap Fund - Direct Plan - Growth
    canonical = lookup_isin(isin)["name"]
    assert len(canonical) > len("Mirae Asset Large")  # masterdata is the longer truth

    out = validate_and_enrich_holdings([_mf("Mirae Asset Large", isin)])

    assert out[0]["name"] == canonical
    assert out[0]["ticker"] == isin  # ISIN is never mutated by name resolution


def test_canonical_name_is_idempotent():
    """A name that already equals the canonical AMFI name is left untouched —
    re-running enrichment (e.g. re-import) must not churn or shorten it."""
    isin = "INF769K01HF4"  # Mirae Asset NYSE FANG + ETF
    canonical = lookup_isin(isin)["name"]

    out = validate_and_enrich_holdings([_mf(canonical, isin, asset_type="etf")])

    assert out[0]["name"] == canonical


def test_unknown_isin_preserves_user_name():
    """No masterdata match → the user's name is preserved verbatim (no guess)."""
    out = validate_and_enrich_holdings([_mf("My Private Note", "ZZZNOTAREALISIN")])

    assert out[0]["name"] == "My Private Note"


def test_comma_glue_name_resolves_to_canonical():
    """The CAS extractor inserts stray commas when a name wraps across PDF
    columns ("ICICI Prudential, Large Cap Fund, (erstwhile...)"). These are
    ~the same length as canonical so the truncation rule misses them — the
    comma signal must trigger replacement with the comma-free AMFI name."""
    isin = "INF109K016L0"
    canonical = lookup_isin(isin)["name"]
    glued = "ICICI Prudential, Large Cap Fund, (erstwhile Bluechip)"

    out = validate_and_enrich_holdings([_mf(glued, isin)])

    assert out[0]["name"] == canonical
    assert "," not in out[0]["name"]


def test_real_isins_resolve_to_full_scheme_names():
    """The specific holdings from the reported Top-Holdings screenshot all
    expand from their truncated stub to the full canonical name."""
    cases = [
        ("Mirae Asset Large", "INF769K01AX2"),
        ("ICICI Prudential", "INF109K016L0"),
    ]
    holdings = [_mf(stub, isin) for stub, isin in cases]
    out = validate_and_enrich_holdings(holdings)

    for (stub, isin), o in zip(cases, out):
        canonical = lookup_isin(isin)["name"]
        assert o["name"] == canonical
        assert o["name"] != stub          # actually changed
        assert stub.split()[0] in o["name"]  # and stayed the same fund (AMC preserved)
