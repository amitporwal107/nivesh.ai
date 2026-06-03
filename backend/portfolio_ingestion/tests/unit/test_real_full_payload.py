"""End-to-end schema + builder test against the REAL CASParser SDK payload.

The fixture is verbatim from a real /v4/ onboarding upload captured via
the /api/admin/diag/sdk-result diagnostic endpoint. This test is the
ground-truth check for the 60-vs-112-holdings bug: if it ever drops below
112 again, the schema or builder lost data on the way through.

Earlier the schema modelled `mutual_funds[]` as a list of AMC wrappers
(amc → folios → schemes). The real SDK shape is FLAT — each entry IS a
folio. That bug silently dropped 52 MF rows.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from portfolio_ingestion.schemas.parsed_data import ParsedData
from portfolio_ingestion.services.portfolio_builder import build_holdings


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sdk_real_nsdl_full.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_real_payload_parses_without_loss():
    """Schema must accept the real SDK shape — no 422, no silent drops."""
    raw = _load()
    payload = ParsedData.model_validate(raw)
    assert len(payload.demat_accounts) == 2
    assert len(payload.mutual_funds) == 38   # 38 folios (not AMCs)


def test_demat_side_yields_60_lines():
    """Demat side: 1 + 14 + 43 + 2 = 60 line items across two accounts."""
    payload = ParsedData.model_validate(_load())
    n = sum(len(da.iter_lines()) for da in payload.demat_accounts)
    assert n == 60


def test_mutual_funds_section_yields_52_schemes():
    """Top-level mutual_funds[]: 38 folios contain a TOTAL of 52 schemes.
    Earlier schema (with the fictitious AMC wrapper) saw 0 schemes here."""
    payload = ParsedData.model_validate(_load())
    total = sum(len(fol.schemes) for fol in payload.mutual_funds)
    assert total == 52


def test_total_value_matches_summary():
    """summary.total_value is the source of truth from the SDK. Our
    derived total_value must equal it exactly."""
    raw = _load()
    payload = ParsedData.model_validate(raw)
    expected = Decimal(str(raw["summary"]["total_value"]))
    assert payload.total_value == expected


def test_builder_emits_112_holdings():
    """The whole point of the fix: 60 demat lines + 52 MF schemes = 112."""
    payload = ParsedData.model_validate(_load())
    rows = build_holdings(
        payload,
        pan_hash="0" * 64,
        source_type="ECAS_NSDL",
        statement_to="2026-04-30",
        ingestion_job_id=uuid4(),
        raw_data_ref=None,
    )
    assert len(rows) == 112


def test_builder_breakdown_per_asset_class():
    """Per-asset-class COUNTS — guards against silent row drops."""
    payload = ParsedData.model_validate(_load())
    rows = build_holdings(
        payload, pan_hash="0" * 64, source_type="ECAS_NSDL",
        statement_to="2026-04-30", ingestion_job_id=uuid4(),
    )
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.asset_class] = counts.get(r.asset_class, 0) + 1
    # demat side: 1 equity (account 0) + 43 equities (account 1) = 44
    assert counts.get("equity") == 44
    # demat side: 14 demat_mutual_funds + 2 demat_mutual_funds = 16
    # plus top-level mutual_funds: 52 schemes
    # → total mutual_fund-type rows = 16 + 52 = 68
    assert counts.get("mutual_fund") == 68
    assert sum(counts.values()) == 112


def test_builder_value_sums_per_asset_class_match_sdk_truth():
    """Per-asset-class VALUE SUMS — proves we didn't drop or double-count anything.

    Truth (from the fixture's own summary + per-account totals):
      demat equities       :  1,115.00 + 1,766,820.64 = 1,767,935.64
      demat mutual_funds   :  966,080.56 +     6,512.94 =   972,593.50
      top-level mutual_fund (per summary.accounts.mutual_funds.total_value)
                           : 7,880,303.28
      combined `mutual_fund` row class (demat + top-level)
                           : 8,852,896.78
      grand total          : 10,620,832.42 (== summary.total_value)
    """
    raw = _load()
    payload = ParsedData.model_validate(raw)
    rows = build_holdings(
        payload, pan_hash="0" * 64, source_type="ECAS_NSDL",
        statement_to="2026-04-30", ingestion_job_id=uuid4(),
    )

    sums: dict[str, Decimal] = {}
    for r in rows:
        sums[r.asset_class] = sums.get(r.asset_class, Decimal("0")) + r.value

    # Equity = sum of `equities` across both demat accounts.
    expected_equity = Decimal("0")
    for acc in raw["demat_accounts"]:
        for h in acc["holdings"].get("equities", []):
            expected_equity += Decimal(str(h.get("value", 0) or 0))
    assert sums.get("equity") == expected_equity == Decimal("1767935.64")

    # mutual_fund (row class) = demat-side `demat_mutual_funds` + top-level `mutual_funds`.
    expected_demat_mf = Decimal("0")
    for acc in raw["demat_accounts"]:
        for h in acc["holdings"].get("demat_mutual_funds", []):
            expected_demat_mf += Decimal(str(h.get("value", 0) or 0))
    expected_toplevel_mf = Decimal(str(raw["summary"]["accounts"]["mutual_funds"]["total_value"]))
    expected_mf_total = expected_demat_mf + expected_toplevel_mf
    assert sums.get("mutual_fund") == expected_mf_total
    assert sums.get("mutual_fund") == Decimal("972593.50") + Decimal("7880303.28")

    # No silent buckets: every row class we emitted is one we expected.
    assert set(sums.keys()) == {"equity", "mutual_fund"}

    # Grand total must equal summary.total_value to the paisa.
    grand = sum(sums.values(), Decimal("0"))
    assert grand == Decimal(str(raw["summary"]["total_value"])) == Decimal("10620832.42")


def test_mf_folio_carries_amc_folio_registrar_in_source_trace():
    payload = ParsedData.model_validate(_load())
    rows = build_holdings(
        payload, pan_hash="0" * 64, source_type="ECAS_NSDL",
        statement_to="2026-04-30", ingestion_job_id=uuid4(),
    )
    # Pick any MF row and check provenance metadata is populated.
    mf_rows = [r for r in rows if r.asset_class == "mutual_fund" and r.folio]
    assert mf_rows, "expected at least one MF row with folio"
    r0 = mf_rows[0]
    assert r0.amc       # AMC name carried
    assert r0.folio     # folio_number carried
    assert r0.source_trace.get("folio") == r0.folio


# ── PER-HOLDING RECONCILIATION ─────────────────────────────────────────────
# Per the CAS reconciliation testing standard: every holding must reconcile
# against the SDK truth at the (units, value) level. A test that confirms
# "111 rows exist" is worthless if any individual ISIN's value silently
# differs from what CASParser produced.


def _d(v) -> Decimal:
    """Coerce SDK numeric (often float) → Decimal via str to avoid FP error."""
    return Decimal(str(v if v is not None else 0))


def _build_rows() -> list:
    payload = ParsedData.model_validate(_load())
    return build_holdings(
        payload, pan_hash="0" * 64, source_type="ECAS_NSDL",
        statement_to="2026-04-30", ingestion_job_id=uuid4(),
    )


def test_per_holding_demat_equity_reconciliation():
    """For EVERY demat equity in the SDK truth, the builder row keyed by
    (dp_id, client_id, isin) must have the EXACT same units and value.
    No tolerance — eCAS equity values are reported to paisa."""
    raw = _load()
    rows = _build_rows()

    # Build {(dp_id, client_id, isin): row} index from builder output.
    built = {
        (r.source_trace.get("demat_dp_id"),
         r.source_trace.get("demat_client_id"),
         r.isin): r
        for r in rows
        if r.asset_class == "equity" and r.isin
    }

    matched = 0
    for acc in raw["demat_accounts"]:
        dp_id, client_id = acc.get("dp_id"), acc.get("client_id")
        for h in acc["holdings"].get("equities", []):
            isin = h.get("isin")
            assert isin and len(isin) == 12, f"truth equity missing valid ISIN: {h.get('name')}"
            key = (dp_id, client_id, isin)
            assert key in built, f"builder dropped equity {isin} in account {dp_id}/{client_id}"
            row = built[key]
            assert row.quantity == _d(h["units"]), \
                f"{isin}: units mismatch — truth={h['units']} built={row.quantity}"
            assert row.value == _d(h["value"]), \
                f"{isin}: value mismatch — truth={h['value']} built={row.value}"
            assert row.name == h["name"], \
                f"{isin}: name mismatch — truth={h['name']!r} built={row.name!r}"
            matched += 1

    # Sanity: matched every demat-equity row in the truth (44 from prior test).
    assert matched == 44
    # And the index has no extras (no phantom equities).
    assert len(built) == 44


def test_per_holding_demat_mutual_fund_reconciliation():
    """For EVERY demat-side mutual_fund holding (the SDK's `demat_mutual_funds`
    bucket — these are MF units custodied in the demat, not the registrar
    MF section), the builder row must have exact units + value."""
    raw = _load()
    rows = _build_rows()

    # Demat-side MF rows are those with asset_class=mutual_fund AND
    # source_trace.demat_dp_id present (registrar-side MFs have folio/registrar,
    # not dp_id).
    built = {
        (r.source_trace.get("demat_dp_id"),
         r.source_trace.get("demat_client_id"),
         r.isin): r
        for r in rows
        if r.asset_class == "mutual_fund" and r.source_trace.get("demat_dp_id")
    }

    matched = 0
    for acc in raw["demat_accounts"]:
        dp_id, client_id = acc.get("dp_id"), acc.get("client_id")
        for h in acc["holdings"].get("demat_mutual_funds", []):
            isin = h.get("isin")
            assert isin and len(isin) == 12, \
                f"truth demat MF missing valid ISIN: {h.get('name')}"
            key = (dp_id, client_id, isin)
            assert key in built, \
                f"builder dropped demat MF {isin} in account {dp_id}/{client_id}"
            row = built[key]
            assert row.quantity == _d(h["units"])
            assert row.value == _d(h["value"])
            matched += 1

    assert matched == 16            # 14 (acc 0) + 2 (acc 1) per prior breakdown
    assert len(built) == 16


def _norm(v):
    """HoldingRow's _empty_string_is_none validator normalizes "" → None for
    the identifier fields. Truth-side keys must apply the same normalization
    to compare correctly."""
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


def test_per_scheme_top_level_mutual_fund_reconciliation():
    """For EVERY scheme in EVERY top-level mutual_funds[] folio, the builder
    row keyed by (amc, folio_number, isin) must reconcile to the paisa.

    Note: the SDK ships at least one phantom 'GROWTH' folio with empty
    folio_number and isin — that's real SDK output, not corruption. The
    HoldingRow schema normalizes empty strings to None, so we mirror that
    on the truth side."""
    raw = _load()
    rows = _build_rows()

    built = {
        (r.amc, r.folio, r.isin): r
        for r in rows
        if r.asset_class == "mutual_fund" and not r.source_trace.get("demat_dp_id")
    }

    matched = 0
    for fol in raw["mutual_funds"]:
        amc = _norm(fol.get("amc"))
        folio_num = _norm(fol.get("folio_number"))
        for s in fol.get("schemes", []):
            isin = _norm(s.get("isin"))
            key = (amc, folio_num, isin)
            assert key in built, \
                f"builder dropped MF scheme amc={amc} folio={folio_num} isin={isin}"
            row = built[key]
            assert row.quantity == _d(s["units"]), \
                f"amc={amc} folio={folio_num} isin={isin}: units {s['units']} vs {row.quantity}"
            assert row.value == _d(s["value"]), \
                f"amc={amc} folio={folio_num} isin={isin}: value {s['value']} vs {row.value}"
            matched += 1

    assert matched == 52
    assert len(built) == 52


def test_per_account_total_value_reconciles_to_sdk_account_value():
    """The SDK reports each demat account's own `value`, AND each holding
    within the account has its own `value`. Our builder rows for that
    account must sum to the same total as the truth-side sum of holdings.

    Note: we re-derive the expected from per-holding Decimal arithmetic
    rather than `acc["value"]` directly, because the SDK pre-computes the
    account `value` field in JS floating-point. For this fixture the SDK
    cache reads e.g. `967195.5599999999` while clean Decimal arithmetic
    gives `967195.56`. The reconciliation that matters is per-holding-sum
    consistency; we additionally assert the float-cache is within 1 paisa
    of the Decimal truth so we catch real drift but ignore FP jitter."""
    raw = _load()
    rows = _build_rows()

    by_account: dict[tuple[str, str], Decimal] = {}
    for r in rows:
        dp = r.source_trace.get("demat_dp_id")
        cl = r.source_trace.get("demat_client_id")
        if dp is None:
            continue
        by_account[(dp, cl)] = by_account.get((dp, cl), Decimal("0")) + r.value

    for acc in raw["demat_accounts"]:
        key = (acc.get("dp_id"), acc.get("client_id"))
        # Truth derived from per-holding Decimal arithmetic.
        expected = Decimal("0")
        for bucket in ("equities", "demat_mutual_funds", "corporate_bonds",
                       "government_securities", "aifs"):
            for h in acc["holdings"].get(bucket, []):
                expected += _d(h.get("value", 0) or 0)

        actual = by_account.get(key, Decimal("0"))
        assert actual == expected, \
            f"account {key}: derived truth {expected} != builder sum {actual}"

        # The SDK's pre-summed cache must be within 1 paisa of the
        # Decimal truth (catches real corruption; tolerates JS-float jitter).
        cached = _d(acc["value"])
        drift = abs(cached - expected)
        assert drift <= Decimal("0.01"), \
            f"account {key}: SDK cached value {cached} drifts {drift} from derived {expected}"


def test_per_folio_total_reconciles_to_sdk_folio_value():
    """Each top-level MF folio reports its own `value`. Sum of our scheme
    rows for that folio must match."""
    raw = _load()
    rows = _build_rows()

    by_folio: dict[tuple[str, str], Decimal] = {}
    for r in rows:
        if r.asset_class != "mutual_fund" or r.source_trace.get("demat_dp_id"):
            continue
        k = (r.amc, r.folio)
        by_folio[k] = by_folio.get(k, Decimal("0")) + r.value

    mismatches: list[str] = []
    for fol in raw["mutual_funds"]:
        key = (fol.get("amc"), fol.get("folio_number"))
        expected = _d(fol.get("value", 0))
        actual = by_folio.get(key, Decimal("0"))
        if actual != expected:
            mismatches.append(f"{key}: SDK {expected} vs built {actual}")
    assert not mismatches, "Folio value mismatches:\n  " + "\n  ".join(mismatches)


def test_mf_units_times_nav_approximates_cost_within_rounding():
    """NAV invariant — CASParser's `nav` field on an MF scheme is the
    AVERAGE PURCHASE NAV (used to compute cost basis), NOT the current
    market NAV. So the deterministic invariant is:

        units × purchase_nav ≈ cost     (within rounding tolerance)

    `value` is current market value (current NAV × units), but current NAV
    isn't shipped in the SDK payload, so we can't reconstruct it here.

    Tolerance: ₹2 per scheme — captures real corruption while allowing for
    the SDK rounding `nav` to 4 places and `cost` to 2 places on folios
    with large unit counts (~10K units × 4-place rounding ≈ ₹1)."""
    raw = _load()
    tolerance = Decimal("2.00")
    drift: list[str] = []
    checked = 0
    for fol in raw["mutual_funds"]:
        for s in fol["schemes"]:
            nav = _d(s.get("nav") or 0)
            units = _d(s.get("units") or 0)
            cost = _d(s.get("cost") or 0)
            if nav == 0 or units == 0 or cost == 0:
                continue
            implied = (units * nav).quantize(Decimal("0.01"))
            if abs(implied - cost) > tolerance:
                drift.append(
                    f"amc={fol['amc']} folio={fol['folio_number']} "
                    f"isin={s.get('isin')}: units={units} nav={nav} "
                    f"implied={implied} sdk_cost={cost}"
                )
            checked += 1
    assert checked >= 40, f"expected most schemes to have nav+cost+units; only {checked} checked"
    assert not drift, f"NAV×units vs cost drift exceeds ₹2:\n  " + "\n  ".join(drift)


def test_data_integrity_no_negative_or_invalid_holdings():
    """Data-integrity sweep on the builder output — every row must pass:
    - units >= 0 (zero ALLOWED: closed/redeemed positions linger as
      placeholders in the SDK; negative would be corruption)
    - value >= 0 (same logic; negative is corruption)
    - if both units AND value are zero, treat as placeholder — but still
      assert that NO row has units>0 with value<=0 (that's a price-feed
      failure) and no row has value>0 with units<=0 (impossible)
    - if isin set, exactly 12 chars
    - name non-empty
    - asset_class non-empty"""
    rows = _build_rows()
    violations: list[str] = []
    placeholders = 0
    for r in rows:
        if r.quantity < 0:
            violations.append(f"NEGATIVE units: isin={r.isin} qty={r.quantity}")
        if r.value < 0:
            violations.append(f"NEGATIVE value: isin={r.isin} value={r.value}")
        if r.quantity == 0 and r.value == 0:
            placeholders += 1
        elif r.quantity == 0 and r.value > 0:
            violations.append(f"value>0 but units==0 (impossible): isin={r.isin} value={r.value}")
        elif r.quantity > 0 and r.value == 0:
            violations.append(f"units>0 but value==0 (price-feed gap): isin={r.isin} qty={r.quantity}")
        if r.isin is not None and len(r.isin) != 12:
            violations.append(f"malformed ISIN: {r.isin!r}")
        if not r.name or not r.name.strip():
            violations.append(f"empty name on row isin={r.isin}")
        if not r.asset_class:
            violations.append(f"empty asset_class on row isin={r.isin}")
    assert not violations, "Data integrity:\n  " + "\n  ".join(violations)
    # SDK is known to ship 1 'GROWTH OPTION' placeholder folio in this fixture.
    # If that count changes, we want to know (the SDK shape may have shifted).
    assert placeholders == 1, f"expected 1 zero/zero placeholder, got {placeholders}"


def test_no_silent_dedupe_against_real_payload():
    """The builder dedupes equities on (isin, qty) and MFs on
    (amc, folio, isin|scheme_code). For THIS real payload no holding
    should collide on those keys — i.e. builder output count must equal
    the raw truth count (60 + 52 = 112). If this fails, either the
    payload genuinely has duplicates (investigate the SDK) or our
    dedupe key is too aggressive."""
    raw = _load()
    truth_demat = sum(len(acc["holdings"].get(k, []))
                      for acc in raw["demat_accounts"]
                      for k in ("equities", "demat_mutual_funds",
                                "corporate_bonds", "government_securities", "aifs"))
    truth_mf = sum(len(f["schemes"]) for f in raw["mutual_funds"])
    assert truth_demat == 60
    assert truth_mf == 52
    assert len(_build_rows()) == truth_demat + truth_mf == 112


def test_per_amc_grouping_reconciles_against_sdk():
    """AMC-level grouping check: for every AMC appearing in the SDK's
    top-level mutual_funds, sum-of-scheme-values per AMC must match
    what we sum across the builder's MF rows for that same AMC."""
    raw = _load()
    rows = _build_rows()

    truth_by_amc: dict[str, Decimal] = {}
    for fol in raw["mutual_funds"]:
        amc = fol.get("amc")
        for s in fol["schemes"]:
            truth_by_amc[amc] = truth_by_amc.get(amc, Decimal("0")) + _d(s["value"])

    built_by_amc: dict[str, Decimal] = {}
    for r in rows:
        if r.asset_class != "mutual_fund" or r.source_trace.get("demat_dp_id"):
            continue
        built_by_amc[r.amc] = built_by_amc.get(r.amc, Decimal("0")) + r.value

    assert set(truth_by_amc.keys()) == set(built_by_amc.keys()), \
        f"AMC set mismatch: truth={set(truth_by_amc) - set(built_by_amc)} " \
        f"built_extra={set(built_by_amc) - set(truth_by_amc)}"
    for amc in truth_by_amc:
        assert built_by_amc[amc] == truth_by_amc[amc], \
            f"AMC {amc}: truth {truth_by_amc[amc]} != built {built_by_amc[amc]}"


# ── DEFERRED reconciliation categories (per CAS testing standard) ──────────
# Categories from the testing standard that cannot be asserted at the
# CURRENT layer (T1.5 builder) because the data isn't yet captured in
# our HoldingRow schema:
#
#   - Invested amount / cost basis      → SDK ships `cost` on MF schemes but
#                                          HoldingRow doesn't persist it yet.
#   - Absolute / percentage gain/loss   → ditto (SDK has `gain.absolute/percentage`).
#   - XIRR / CAGR                       → not in eCAS holdings statement.
#   - SIP / redemption / switch / STP   → eCAS holdings is point-in-time;
#                                          transaction statement is a separate
#                                          CAS variant we don't yet ingest.
#   - Dividend / realized gain          → same — transaction-statement only.
#   - NAV-date                          → not in SDK output.
#   - Sector / debt-equity classification → enrichment, not the parser's job.
#
# When the schema gains those fields (T2/T3), add per-holding cost,
# gain, and transaction-sum reconciliation tests here.
