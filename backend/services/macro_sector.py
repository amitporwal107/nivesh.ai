"""Sector sensitivity model — translates macro features into a per-sector
tilt that biases the positional engine's stock scoring.

PRD §9: each sector has a sensitivity vector against {crude, usd, yield}.
Multiply the sector's sensitivity by the daily momentum of each macro
input to get `sector_modifier ∈ approximately [-10, +10]`.

  • Positive sector_score → tailwind (boost the score)
  • Negative sector_score → headwind (penalize the score)

Examples:
  • Crude rising 5% in 5d, sector=PAINT (crude:-1) → -5 contribution
  • USD strengthening 2% in 5d, sector=IT (usd:+1) → +2 contribution
  • Yield rising 3% in 5d, sector=BANK (yield:-0.5) → -1.5 contribution

The map intentionally only encodes the strongest, most-stable sector ↔
macro relationships. Adding noisy second-order links (e.g. "auto loosely
benefits from low yields") dilutes the signal — we add new entries only
when the relationship is well-evidenced over multi-year data.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from services import pg_client

logger = logging.getLogger(__name__)


# ── Sector ↔ macro sensitivity map ─────────────────────────────────────
# Sign convention: +1.0 = strongly helped, -1.0 = strongly hurt.
# Magnitude reflects relative sensitivity (PAINT -1 vs AUTO -0.3 because
# crude is a much bigger input cost share for paint).
SECTOR_MACRO_MAP: Dict[str, Dict[str, float]] = {
    # Crude-sensitive
    "PAINT":      {"crude": -1.0},
    "AVIATION":   {"crude": -1.0},
    "FMCG":       {"crude": -0.5},
    "AUTO":       {"crude": -0.3},
    "TYRES":      {"crude": -0.7},
    "OIL_GAS":    {"crude": +1.0},
    "REFINERY":   {"crude": +0.5},     # mixed: input cost ↑ but margin pricing power
    # USD-sensitive
    "IT":         {"usd": +1.0},
    "PHARMA":     {"usd": +0.8},
    "CHEMICALS":  {"usd": +0.5},
    "TEXTILE":    {"usd": +0.4},
    "GEMS":       {"usd": +0.3},
    "METAL":      {"usd": +0.2, "crude": -0.2},   # exporters but energy-intensive
    # Yield-sensitive (rate-sensitive sectors)
    "BANK":       {"yield": -0.5},     # NII compression on the long end
    "NBFC":       {"yield": -0.7},
    "REALTY":     {"yield": -0.8},
    "INFRA":      {"yield": -0.6},
    "POWER":      {"yield": -0.4},
    "PSU_BANK":   {"yield": -0.3},
    # Defensives — minimal direct macro sensitivity
    "INSURANCE":  {"yield": +0.2},     # higher yields help reinvested float
    "CONSUMPTION":{"crude": -0.4, "usd": -0.2},   # imported inputs + discretionary spend
}


def _resolve_sector(raw_sector: Optional[str]) -> Optional[str]:
    """Map a free-form sector string from stock_master into a key in
    SECTOR_MACRO_MAP. Returns None if no match.

    Why this exists: stock_master.sector uses NSE/Morningstar labels
    ("Information Technology", "Banks", "Auto Components") which don't
    line up 1:1 with our macro keys. This is the single normalisation
    point so callers don't need to reason about label mismatches.
    """
    if not raw_sector:
        return None
    s = raw_sector.upper().strip()
    # Direct match first
    if s in SECTOR_MACRO_MAP:
        return s
    # Substring matches in priority order — highest-confidence pattern wins
    matchers: List[tuple[str, str]] = [
        ("INFORMATION TECHNOLOGY", "IT"),
        ("IT SERVICES", "IT"),
        ("SOFTWARE", "IT"),
        ("PHARMACEUTICAL", "PHARMA"),
        ("PHARMA", "PHARMA"),
        ("OIL", "OIL_GAS"),
        ("GAS", "OIL_GAS"),
        ("PETROLEUM", "OIL_GAS"),
        ("REFIN", "REFINERY"),
        ("PAINT", "PAINT"),
        ("AIRLINE", "AVIATION"),
        ("AVIATION", "AVIATION"),
        ("AUTO", "AUTO"),
        ("TYRE", "TYRES"),
        ("FMCG", "FMCG"),
        ("CONSUMER GOODS", "FMCG"),
        ("PERSONAL CARE", "FMCG"),
        ("CHEMICAL", "CHEMICALS"),
        ("TEXTILE", "TEXTILE"),
        ("APPAREL", "TEXTILE"),
        ("GEM", "GEMS"),
        ("JEWELL", "GEMS"),
        ("METAL", "METAL"),
        ("STEEL", "METAL"),
        ("MINING", "METAL"),
        ("PUBLIC SECTOR BANK", "PSU_BANK"),
        ("PSU BANK", "PSU_BANK"),
        ("BANK", "BANK"),
        ("FINANCIAL SERVIC", "NBFC"),
        ("NBFC", "NBFC"),
        ("FINANCE", "NBFC"),
        ("REAL ESTATE", "REALTY"),
        ("REALTY", "REALTY"),
        ("INFRASTRUCTURE", "INFRA"),
        ("CONSTRUCTION", "INFRA"),
        ("POWER", "POWER"),
        ("UTILIT", "POWER"),
        ("INSURANCE", "INSURANCE"),
        ("CONSUMER DURABLE", "CONSUMPTION"),
        ("CONSUMER SERVICE", "CONSUMPTION"),
    ]
    for needle, bucket in matchers:
        if needle in s:
            return bucket
    return None


# ── Compute sector_modifier for a given macro_features row ─────────────
def compute_modifier(
    sector_key: str, *,
    crude_momentum: Optional[float],
    usd_momentum: Optional[float],
    yield_momentum: Optional[float],
) -> float:
    """Pure-function: sensitivity vector × momentum vector → scalar tilt.

    Momentum inputs are 5d % change (e.g. 2.5 means +2.5%). Multiplied by
    the sensitivity weight, summed. Result is a small signed number,
    typically in the [-10, +10] band for normal market conditions.
    """
    sens = SECTOR_MACRO_MAP.get(sector_key, {})
    if not sens:
        return 0.0
    mod = 0.0
    if crude_momentum is not None:
        mod += sens.get("crude", 0.0) * float(crude_momentum)
    if usd_momentum is not None:
        mod += sens.get("usd", 0.0) * float(usd_momentum)
    if yield_momentum is not None:
        mod += sens.get("yield", 0.0) * float(yield_momentum)
    return round(mod, 3)


# ── Plain-English causal chains ────────────────────────────────────────
# (sector_key, macro_key, sign_of_momentum) → human sentence describing
# WHY this combination is a tailwind or headwind. Replaces the previous
# terse "USD 5d +0.7% → tailwind" with the actual mechanism — which is
# what advisors and traders actually care about.
_REASONS: Dict[tuple, str] = {
    # IT — exporter; weakening rupee means USD-denominated revenue is
    # worth more INR after conversion.
    ("IT", "usd", "up"):       "USD rising → export earnings ↑ → IT benefits",
    ("IT", "usd", "down"):     "USD falling → export earnings ↓ → IT pressured",
    # PHARMA — same export logic, slightly weaker exposure.
    ("PHARMA", "usd", "up"):   "USD rising → US generics revenue worth more in INR → Pharma tailwind",
    ("PHARMA", "usd", "down"): "USD falling → US revenue worth less in INR → Pharma headwind",
    # PAINT / TYRES / FMCG / AUTO — crude is a major raw-material input.
    ("PAINT", "crude", "up"):   "Crude rising → input costs ↑ → margin squeeze for paint",
    ("PAINT", "crude", "down"): "Crude falling → cheaper inputs → margin expansion for paint",
    ("TYRES", "crude", "up"):   "Crude rising → rubber + carbon black costs ↑ → margin squeeze for tyres",
    ("TYRES", "crude", "down"): "Crude falling → input relief for tyre makers",
    ("AVIATION", "crude", "up"):   "Crude rising → ATF (jet fuel) up → aviation margins compressed",
    ("AVIATION", "crude", "down"): "Crude falling → cheaper ATF → aviation margin tailwind",
    ("FMCG", "crude", "up"):    "Crude rising → packaging + transport costs ↑ → FMCG margins ↓",
    ("FMCG", "crude", "down"):  "Crude falling → cost relief for FMCG",
    ("AUTO", "crude", "up"):    "Crude rising → fuel + steel prices ↑ → demand softens for autos",
    ("AUTO", "crude", "down"):  "Crude falling → consumer fuel costs ease → demand support",
    # OIL_GAS / REFINERY — direct beneficiaries of crude rise.
    ("OIL_GAS", "crude", "up"):    "Crude rising → realisation prices ↑ → upstream tailwind",
    ("OIL_GAS", "crude", "down"):  "Crude falling → realisation prices ↓ → upstream pressured",
    ("REFINERY", "crude", "up"):   "Crude rising → mixed (input cost ↑ but pricing power)",
    ("REFINERY", "crude", "down"): "Crude falling → input cost relief for refiners",
    # Yield-sensitive — banks, NBFCs, REITs etc.
    ("BANK", "yield", "up"):    "10Y yield rising → loan-book repricing lag → NIM compression risk",
    ("BANK", "yield", "down"):  "10Y yield falling → bond book gains + lending margin support",
    ("NBFC", "yield", "up"):    "10Y yield rising → cost of borrowing ↑ → NBFC margin pressure",
    ("NBFC", "yield", "down"):  "10Y yield falling → cheaper funding → NBFC tailwind",
    ("REALTY", "yield", "up"):  "10Y yield rising → mortgage rates ↑ → housing demand softens",
    ("REALTY", "yield", "down"):"10Y yield falling → mortgage relief → realty support",
    ("INFRA", "yield", "up"):   "10Y yield rising → project IRRs squeezed → infra pressured",
    ("INFRA", "yield", "down"): "10Y yield falling → cheaper project funding → infra tailwind",
    ("POWER", "yield", "up"):   "10Y yield rising → debt-heavy power generators face higher cost of capital",
    ("POWER", "yield", "down"): "10Y yield falling → power generators benefit from cheaper debt",
    ("PSU_BANK", "yield", "up"):    "10Y yield rising → PSU bank bond books take a mark-to-market hit",
    ("PSU_BANK", "yield", "down"):  "10Y yield falling → PSU bank bond books gain on MTM",
    ("INSURANCE", "yield", "up"):   "10Y yield rising → insurance float reinvestment yield ↑",
    ("INSURANCE", "yield", "down"): "10Y yield falling → reinvestment yield squeezed for insurers",
    # Other
    ("METAL", "usd", "up"):     "USD rising → INR commodity prices ↑ → metals exporters benefit",
    ("METAL", "crude", "up"):   "Crude rising → energy costs hurt steel + alu producers",
    ("CHEMICALS", "usd", "up"): "USD rising → specialty chemical export realisations ↑",
    ("CHEMICALS", "usd", "down"): "USD falling → export realisations ↓",
    ("TEXTILE", "usd", "up"):   "USD rising → garment export realisations ↑",
    ("TEXTILE", "usd", "down"): "USD falling → garment export pressure",
    ("GEMS", "usd", "up"):      "USD rising → diamond/gold export realisations ↑",
    ("GEMS", "usd", "down"):    "USD falling → export pressure for gems & jewellery",
    ("CONSUMPTION", "crude", "up"):   "Crude rising → fuel + transport ↑ → discretionary spend pinched",
    ("CONSUMPTION", "crude", "down"): "Crude falling → consumer wallet eases → consumption support",
    ("CONSUMPTION", "usd", "up"):     "USD rising → imported goods cost more → margins squeezed",
    ("CONSUMPTION", "usd", "down"):   "USD falling → imported goods cheaper → margin support",
}


def _rationale(sector_key: str, *,
               crude_momentum: Optional[float], usd_momentum: Optional[float],
               yield_momentum: Optional[float]) -> str:
    """Plain-English causal chain for the dominant macro driver — falls
    back to the previous terse format for combos we haven't authored yet.

    We pick the SINGLE strongest contributor (largest |weight × momentum|)
    rather than concatenating all three. The sector cards are tight on
    space; one clear cause beats three weak ones."""
    sens = SECTOR_MACRO_MAP.get(sector_key, {})
    if not sens:
        return "no significant macro tilt"
    moms = {
        "crude": crude_momentum,
        "usd":   usd_momentum,
        "yield": yield_momentum,
    }
    # Find the dominant driver
    best_key, best_abs, best_mom = None, 0.0, 0.0
    for macro_key, weight in sens.items():
        mom = moms.get(macro_key)
        if mom is None or weight == 0:
            continue
        contrib = abs(weight * mom)
        if contrib > best_abs:
            best_key, best_abs, best_mom = macro_key, contrib, mom
    if best_key is None or best_abs < 0.05:
        return "no significant macro tilt"
    direction = "up" if best_mom > 0 else "down"
    sentence = _REASONS.get((sector_key, best_key, direction))
    if sentence:
        return sentence
    # Fallback for combos we haven't authored
    sign_word = "tailwind" if (sens[best_key] * best_mom) > 0 else "headwind"
    macro_label = {"crude": "crude", "usd": "USD/INR", "yield": "10Y yield"}[best_key]
    return f"{macro_label} 5d {best_mom:+.1f}% → {sign_word}"


# ── DB writes ──────────────────────────────────────────────────────────
async def compute_sector_scores(target_date: Optional[date] = None) -> Dict[str, Any]:
    """For the given date, look up macro_features, compute every sector's
    macro_score, persist into sector_macro_scores. Returns summary."""
    target = target_date or date.today()
    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool"}

    async with pool.acquire() as conn:
        feats = await conn.fetchrow(
            "SELECT crude_momentum_5d, usd_momentum_5d, yield_momentum_5d "
            "FROM macro_features WHERE date = $1", target,
        )
    if feats is None:
        # Most-recent-prior fallback so empty days don't blank the heatmap
        async with pool.acquire() as conn:
            feats = await conn.fetchrow(
                "SELECT crude_momentum_5d, usd_momentum_5d, yield_momentum_5d "
                "FROM macro_features WHERE date < $1 ORDER BY date DESC LIMIT 1",
                target,
            )
    if feats is None:
        return {"ok": False, "error": "no_features", "date": str(target)}

    crude_m = float(feats["crude_momentum_5d"]) if feats["crude_momentum_5d"] is not None else None
    usd_m = float(feats["usd_momentum_5d"]) if feats["usd_momentum_5d"] is not None else None
    yield_m = float(feats["yield_momentum_5d"]) if feats["yield_momentum_5d"] is not None else None

    rows: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        for sector_key in SECTOR_MACRO_MAP.keys():
            score = compute_modifier(
                sector_key,
                crude_momentum=crude_m, usd_momentum=usd_m, yield_momentum=yield_m,
            )
            rationale = _rationale(
                sector_key,
                crude_momentum=crude_m, usd_momentum=usd_m, yield_momentum=yield_m,
            )
            await conn.execute(
                """
                INSERT INTO sector_macro_scores (date, sector, macro_score, rationale)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (date, sector) DO UPDATE SET
                    macro_score = EXCLUDED.macro_score,
                    rationale = EXCLUDED.rationale
                """,
                target, sector_key, score, rationale,
            )
            rows.append({"sector": sector_key, "score": score, "rationale": rationale})
    return {
        "ok": True,
        "date": str(target),
        "n_sectors": len(rows),
        "rows": rows,
        "inputs": {
            "crude_momentum_5d": crude_m,
            "usd_momentum_5d": usd_m,
            "yield_momentum_5d": yield_m,
        },
    }


async def latest_heatmap() -> Dict[str, Any]:
    """Fetch the most recent sector_macro_scores rows for the API."""
    pool = await pg_client.get_pool()
    if pool is None:
        return {"date": None, "rows": []}
    async with pool.acquire() as conn:
        latest = await conn.fetchrow(
            "SELECT MAX(date) AS d FROM sector_macro_scores"
        )
        if not latest or latest["d"] is None:
            return {"date": None, "rows": []}
        d = latest["d"]
        rows = await conn.fetch(
            "SELECT sector, macro_score, rationale FROM sector_macro_scores "
            "WHERE date = $1 ORDER BY macro_score DESC", d,
        )
    return {
        "date": d.isoformat(),
        "rows": [
            {
                "sector": r["sector"],
                "macro_score": float(r["macro_score"]) if r["macro_score"] is not None else 0.0,
                "rationale": r["rationale"],
            }
            for r in rows
        ],
    }


async def score_for_sector(raw_sector: str, target_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """Look up the macro_score for an arbitrary sector label. Used by the
    /stock/{symbol}/why endpoint — input is the stock's `sector` field
    from stock_master, output is its mapped sector key + tilt + rationale."""
    sector_key = _resolve_sector(raw_sector)
    if not sector_key:
        return None
    target = target_date or date.today()
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT macro_score, rationale FROM sector_macro_scores "
            "WHERE date = $1 AND sector = $2", target, sector_key,
        )
        if row is None:
            row = await conn.fetchrow(
                "SELECT macro_score, rationale FROM sector_macro_scores "
                "WHERE sector = $1 ORDER BY date DESC LIMIT 1", sector_key,
            )
    if row is None:
        return None
    return {
        "raw_sector": raw_sector,
        "sector_key": sector_key,
        "macro_score": float(row["macro_score"]) if row["macro_score"] is not None else 0.0,
        "rationale": row["rationale"],
    }
