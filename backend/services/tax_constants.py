"""Versioned Indian capital-gains tax constants.

All rates are for the current financial year (FY 2025-26 / AY 2026-27),
enacted by Finance Act 2024 (Budget 2024) effective 23-Jul-2024.

CHANGELOG
---------
FY 2025-26 (current): STCG equity 20%, LTCG equity 12.5%, LTCG exemption ₹1.25L
FY 2024-25           : STCG equity 15%, LTCG equity 10%, LTCG exemption ₹1.00L
                        (retained in comments only; no longer in use)

UPDATE PROCEDURE
----------------
1. Check https://incometaxindia.gov.in after each Union Budget.
2. Update the constants below and add a new CHANGELOG entry.
3. Bump CURRENT_FY and run: python -m pytest backend/tests/ -k tax
4. PR review required before merging any rate change.
"""

CURRENT_FY = "2025-26"

# ── Equity / Equity-MF / ETF ─────────────────────────────────────────────────
# Sec 111A (STCG ≤ 12 months), Sec 112A (LTCG > 12 months)
EQUITY_STCG_RATE     = 0.20          # 20%
EQUITY_LTCG_RATE     = 0.125         # 12.5%
EQUITY_LTCG_EXEMPTION = 125_000      # ₹1.25L per FY (shared: equity + equity-MF + REIT/InvIT)
EQUITY_LT_DAYS       = 365           # holding period for long-term classification

# ── Debt MF / Gold ETF / Non-equity listed ───────────────────────────────────
# Post-Apr-2023 debt MF taxed at slab (no LTCG/STCG distinction)
NON_EQUITY_LTCG_RATE  = 0.125        # 12.5% — gold/SGB/listed bonds/pre-Apr-23 debt
NON_EQUITY_LT_DAYS    = 730          # 24 months for debt long-term

# ── Surcharge cap (Budget 2023) ──────────────────────────────────────────────
SURCHARGE_CAP_SPECIAL_RATE = 0.15    # 15% on Sec 111A / 112A gains
CESS_RATE                  = 0.04    # 4% health + education cess
