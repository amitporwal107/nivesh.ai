#!/usr/bin/env bash
# verify_selection_framework.sh — staging verification runbook for the
# selection-framework Portfolio Builder MVP.
#
# WHY THIS EXISTS: the framework's app-tests run in CI with no DB
# (`pytest backend/tests/test_selection_*.py`, 85 passing). The DATA half of the
# acceptance contract (CONTEXT.md §1 "app AND data") needs a real DB and could
# NOT be run in the build environment. This script runs the DB-gated spikes
# (S1–S5), applies the audit migration, smoke-tests the builder end-to-end, and
# runs the 4 proposal data-tests. Run it on STAGING (read-mostly; the only write
# is the additive migration 023 + one audit row from the smoke).
#
# USAGE:
#   export NIDP_DATABASE_URL="postgres://…/nidp"      # the NIDP data platform DB
#   export APP_DATABASE_URL="postgres://…/nivesh"     # the main-app DB (pg_client)
#   bash diagnostics/verify_selection_framework.sh
#
# Each section prints its result and the PASS threshold; a human/CI judges PASS.
# Sections that can decide automatically exit non-zero on failure.
set -uo pipefail

NIDP="${NIDP_DATABASE_URL:-}"
APP="${APP_DATABASE_URL:-${DATABASE_URL:-}}"
BACKEND_DIR="${BACKEND_DIR:-/app/backend}"
fail=0

hr(){ printf '\n========== %s ==========\n' "$1"; }
need(){ [ -n "$1" ] || { echo "🔴 MISSING env $2 — cannot run this section"; return 1; }; }
psql_nidp(){ need "$NIDP" NIDP_DATABASE_URL || return 1; psql "$NIDP" -X -A -t -v ON_ERROR_STOP=1 -c "$1"; }
psql_app(){  need "$APP" APP_DATABASE_URL  || return 1; psql "$APP"  -X -A -t -v ON_ERROR_STOP=1 -c "$1"; }

# ─────────────────────────────────────────────────────────────────────────────
hr "APP-TESTS (no DB) — selection framework unit suite (expect 85 passed)"
( cd "$BACKEND_DIR" && python3 -m pytest \
    tests/test_selection_framework.py tests/test_selection_ranking.py \
    tests/test_buyable_universe.py tests/test_proposal_audit.py \
    tests/test_portfolio_result_transformer.py -p no:cacheprovider -q ) || fail=1

# ─────────────────────────────────────────────────────────────────────────────
hr "S1 — corrected-rank prod liveness (gates rank-wiring, Step 2)"
# PASS: status='ranked' rows > 0, rank_date fresh (≤7d), and category_rank_pct
# non-null coverage ≥ 80% of the MVP universe in v_v3_mf_primitives.
echo "[mf_category_rank_daily] ranked rows + latest rank_date + staleness(days):"
psql_nidp "SELECT count(*) FILTER (WHERE status='ranked') AS ranked_rows,
                  max(rank_date) AS latest,
                  (current_date - max(rank_date)) AS stale_days
           FROM nidp.mf_category_rank_daily;"
echo "[v_v3_mf_primitives] category_rank_pct non-null coverage (target ≥ 0.80):"
psql_nidp "SELECT round(count(*) FILTER (WHERE category_rank_pct IS NOT NULL)::numeric
                  / NULLIF(count(*),0), 3) AS coverage
           FROM nidp.v_v3_mf_primitives;"

# ─────────────────────────────────────────────────────────────────────────────
hr "S2 — gate-input coverage (gates hard-gates, Step 3)"
# PASS: aum_cr and fund_age_years coverage ≥ 0.95 over the MVP universe.
# manager_tenure_years may be lower → that gate degrades to 'not_evaluated'.
psql_nidp "SELECT round(count(*) FILTER (WHERE aum_cr IS NOT NULL)::numeric/NULLIF(count(*),0),3) AS aum_cov,
                  round(count(*) FILTER (WHERE fund_age_years IS NOT NULL)::numeric/NULLIF(count(*),0),3) AS age_cov,
                  round(count(*) FILTER (WHERE manager_tenure_years IS NOT NULL)::numeric/NULLIF(count(*),0),3) AS tenure_cov
           FROM nidp.v_v3_mf_primitives;"

# ─────────────────────────────────────────────────────────────────────────────
hr "S3 — category_change event source (gates debt category-integrity)"
# PASS: a queryable category_change event exists. EXPECTED FAIL per feasibility §B
# → the category_integrity gate stays 'not_evaluated' (documented, not silent-pass).
echo "Probe mf events for a category_change type (adjust table if your schema differs):"
psql_nidp "SELECT to_regclass('nidp.mf_events') AS events_table;" || true
psql_nidp "SELECT DISTINCT event_type FROM nidp.mf_events
           WHERE event_type ILIKE '%categor%' LIMIT 10;" 2>/dev/null \
  || echo "  (no nidp.mf_events / no category_change type — gate stays not_evaluated, as designed)"

# ─────────────────────────────────────────────────────────────────────────────
hr "S4 — holdings-feed coverage (gates overlap, Step 4)"
# PASS: current-month holdings coverage ≥ 0.80 of the MVP universe. Below that,
# overlap degrades to 'not_evaluated' for uncovered schemes (honest, by design).
psql_nidp "WITH latest AS (SELECT max(as_of_month) m FROM nidp.mf_holdings_monthly)
           SELECT count(DISTINCT scheme_code) AS schemes_with_current_holdings,
                  (SELECT m FROM latest) AS as_of_month
           FROM nidp.mf_holdings_monthly, latest
           WHERE as_of_month = (SELECT m FROM latest);"

# ─────────────────────────────────────────────────────────────────────────────
hr "S5 — buyable-universe source (gates platform filter, V2-1)"
# PASS: a transactable-scheme source exists. EXPECTED FAIL per feasibility §E →
# MVP uses the AMFI direct-growth fallback (buyable_universe.get_buyable_isins()).
echo "MVP fallback set size — active direct-growth MF ISINs (main-app DB):"
psql_app "SELECT count(*) AS amfi_direct_growth_isins
          FROM instrument_master im JOIN mutual_fund_metadata mfm USING (instrument_id)
          WHERE im.is_active = TRUE AND im.isin IS NOT NULL
            AND lower(im.instrument_name) LIKE '%direct%'
            AND lower(im.instrument_name) NOT LIKE '%idcw%'
            AND lower(im.instrument_name) NOT LIKE '%dividend%';"
echo "  (No broker-connect/OpenAlgo MF instrument-master exists — V2-1 blocked until one does.)"

# ─────────────────────────────────────────────────────────────────────────────
hr "MIGRATION — apply 023_portfolio_proposal_audit (additive, forward-only)"
if [ -n "$APP" ]; then
  psql "$APP" -X -v ON_ERROR_STOP=1 -f "$BACKEND_DIR/migrations/023_portfolio_proposal_audit.sql" \
    && echo "✅ migration applied (idempotent)" || { echo "🔴 migration failed"; fail=1; }
  psql_app "SELECT to_regclass('public.portfolio_proposal_audit') AS audit_table;"
else
  echo "🔴 MISSING env APP_DATABASE_URL — skipped migration"
fi

# ─────────────────────────────────────────────────────────────────────────────
hr "E2E SMOKE — build a real proposal (named-scheme mode) + assemble data-tests"
# Requires the backend env (DaaS/pg reachable). Generates a Moderate/10y proposal
# and runs the 4 proposal data-tests in-process, then prints PASS/FAIL per check.
( cd "$BACKEND_DIR" && python3 - <<'PY'
import asyncio, json, sys
async def main():
    from services import sleeve_builder, allocation_policy as p
    if not p.names_allowed():
        print("compliance mode = category_and_model → no named picks to data-test.")
        print("Set compliance.mf_recommendations_mode=named_scheme on staging to exercise picks.")
        return 0
    out = await sleeve_builder.build_sleeve_portfolio("moderate", horizon_years=10, monthly_sip_rs=20000)
    picks = [f for s in out.get("sleeves", []) for f in s.get("funds", [])]
    isins = [f.get("isin") for f in picks if f.get("isin")]
    print(f"generated {len(picks)} picks across {len(out.get('sleeves', []))} sleeves")

    ok = True
    # DT2 — no gate-failed instrument leaked into picks
    bad = [f.get("isin") for f in picks
           if any(g.get("status") == "failed" for g in (f.get("gate_results") or []))]
    print(("  ✅" if not bad else "  🔴"), "DT2 no gate-failed in output:", bad or "clean"); ok &= not bad
    # DT3 — no overlap-pair breach among selected (overlap_status must never be 'rejected' in picks)
    breach = [f.get("isin") for f in picks if f.get("overlap_status") == "rejected"]
    print(("  ✅" if not breach else "  🔴"), "DT3 no overlap breach in picks:", breach or "clean"); ok &= not breach
    # DT4 — audit record present + complete
    a = out.get("audit") or {}
    need = ["inputs", "weights", "scoring_config_version", "generated_at", "picks"]
    miss = [k for k in need if not a.get(k)]
    print(("  ✅" if a and not miss else "  🔴"), "DT4 audit complete:", miss or f"ok (proposal_id={a.get('proposal_id')})"); ok &= bool(a) and not miss
    # DT1 — every pick name traces to a real scored universe row (needs DB)
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool and isins:
        async with pool.acquire() as c:
            rows = await c.fetch(
                "SELECT isin FROM mutual_fund_metadata mfm JOIN instrument_master im "
                "ON im.instrument_id=mfm.instrument_id "
                "WHERE im.isin = ANY($1::text[]) AND mfm.quality_score IS NOT NULL", isins)
        traced = {r["isin"] for r in rows}
        invented = [i for i in isins if i not in traced]
        print(("  ✅" if not invented else "  🔴"), "DT1 no invented instruments:", invented or "all trace"); ok &= not invented
    else:
        print("  ⚠️ DT1 skipped (no pool/isins) — UNVERIFIED")
    return 0 if ok else 1
sys.exit(asyncio.get_event_loop().run_until_complete(main()))
PY
) || fail=1

hr "RESULT"
[ "$fail" -eq 0 ] && echo "✅ runbook completed (review S1–S5 thresholds above for go/no-go)" \
                  || echo "🔴 one or more sections failed — see above"
exit "$fail"
