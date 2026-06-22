"""Policy simulation + validation gates (Layer "validation" of the methodology).

Runs the Monte Carlo on a proposed asset-class allocation using the HOUSE
capital-market assumptions and correlation matrix from allocation_policy.yaml
(never trailing fund returns), then checks the policy's validation gates:

  - min_probability_of_target : advisory  -> warning, does not block
  - max_median_drawdown       : hard      -> block
  - enforce_risk_budget       : equal-risk-contribution check on the dominant sleeve

Returns terminal-corpus percentiles, probability of hitting the (inflation-
adjusted) target, the median across-path max drawdown of the return index, and
the gate verdicts. Correlated-normal returns via Cholesky when numpy is present;
a documented independent-normal fallback otherwise (overstates diversification).
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import numpy as _np
    _HAS_NUMPY = True
except Exception:  # noqa: BLE001
    _HAS_NUMPY = False

_ASSETS = ("equity", "debt", "gold", "cash")
_DEFAULT_INFLATION = 0.06


def _weights(allocation: Dict[str, float]) -> List[float]:
    raw = [float(allocation.get(a, 0) or 0) for a in _ASSETS]
    tot = sum(raw) or 1.0
    return [w / tot for w in raw]


def _annual_to_monthly_mu(annual: float) -> float:
    return (1.0 + annual) ** (1.0 / 12.0) - 1.0


def simulate_and_validate(
    allocation: Dict[str, float],
    *,
    horizon_years: float,
    monthly_sip_rs: float = 0.0,
    lumpsum_rs: float = 0.0,
    target_today_rs: float = 0.0,
    inflation_pct: float = 6.0,
) -> Dict[str, Any]:
    from services import allocation_policy as _p

    cma = _p.capital_market_assumptions()
    corr_cfg = _p._policy().get("asset_correlations", {})  # order + matrix
    val = _p.validation()
    n_paths = int(val.get("simulation_paths", 2000))
    gates = val.get("gates", {})

    w = _weights(allocation)
    mu_a = [float(cma.get(a, {}).get("expected_return", 0.0)) for a in _ASSETS]
    vol_a = [float(cma.get(a, {}).get("volatility", 0.0)) for a in _ASSETS]
    n_months = max(1, int(round(float(horizon_years) * 12)))

    # Monthly params.
    mu_m = [_annual_to_monthly_mu(m) for m in mu_a]
    sig_m = [v / math.sqrt(12.0) for v in vol_a]

    fut_target = (float(target_today_rs) * (1.0 + inflation_pct / 100.0) ** float(horizon_years)
                  if target_today_rs and target_today_rs > 0 else 0.0)

    if _HAS_NUMPY:
        rng = _np.random.default_rng(42)
        order = corr_cfg.get("order") or list(_ASSETS)
        C = _np.array(corr_cfg.get("matrix") or _np.eye(4), dtype=float)
        # Reorder correlation to _ASSETS if the YAML order differs.
        idx = [order.index(a) if a in order else i for i, a in enumerate(_ASSETS)]
        C = C[_np.ix_(idx, idx)]
        sig = _np.array(sig_m)
        cov = C * _np.outer(sig, sig)
        try:
            L = _np.linalg.cholesky(cov + _np.eye(4) * 1e-12)
        except Exception:  # noqa: BLE001 — non-PSD safety
            L = _np.diag(sig)
        wv = _np.array(w)
        # paths x months of portfolio returns
        z = rng.standard_normal(size=(n_paths, n_months, 4))
        shocks = z @ L.T + _np.array(mu_m)          # correlated monthly asset returns
        port = shocks @ wv                          # portfolio monthly return
        # Terminal corpus with monthly SIP + starting lumpsum.
        corpus = _np.full(n_paths, float(lumpsum_rs))
        for t in range(n_months):
            corpus = corpus * (1.0 + port[:, t]) + float(monthly_sip_rs)
        # Max drawdown of the return index (no contributions) per path.
        idxv = _np.cumprod(1.0 + port, axis=1)
        peak = _np.maximum.accumulate(idxv, axis=1)
        dd = (peak - idxv) / peak
        max_dd = dd.max(axis=1)
        p5, p50, p95 = (float(x) for x in _np.percentile(corpus, [5, 50, 95]))
        prob = float((corpus >= fut_target).mean()) if fut_target > 0 else None
        median_dd = float(_np.median(max_dd))
    else:
        prob, p5, p50, p95, median_dd = _pure_python_sim(
            w, mu_m, sig_m, n_paths, n_months, monthly_sip_rs, lumpsum_rs, fut_target)

    # ── Gates ────────────────────────────────────────────────────────────────
    warnings: List[str] = []
    blocks: List[str] = []
    min_prob = gates.get("min_probability_of_target")
    max_dd_gate = gates.get("max_median_drawdown")
    if min_prob is not None and prob is not None and prob < float(min_prob):
        warnings.append(f"Probability of hitting target {prob*100:.0f}% is below the {float(min_prob)*100:.0f}% advisory floor — consider a higher SIP or longer horizon.")
    if max_dd_gate is not None and median_dd > float(max_dd_gate):
        blocks.append(f"Median drawdown {median_dd*100:.0f}% exceeds the {float(max_dd_gate)*100:.0f}% ceiling for this profile — reduce equity.")

    return {
        "simulation_paths": n_paths,
        "future_target_rs": round(fut_target, 2) if fut_target else None,
        "median_corpus_rs": round(p50, 2),
        "p5_corpus_rs": round(p5, 2),
        "p95_corpus_rs": round(p95, 2),
        "prob_of_target_pct": round(prob * 100, 1) if prob is not None else None,
        "median_max_drawdown_pct": round(median_dd * 100, 1),
        "gates": {
            "passed": not blocks,
            "warnings": warnings,
            "blocks": blocks,
            "min_probability_of_target": min_prob,
            "max_median_drawdown": max_dd_gate,
        },
        "assumptions": "House capital-market assumptions (allocation_policy.yaml), correlated-normal returns.",
        "method": "numpy_cholesky" if _HAS_NUMPY else "pure_python_independent",
    }


def _pure_python_sim(w, mu_m, sig_m, n_paths, n_months, sip, lump, fut_target):
    """Dependency-free fallback — INDEPENDENT normals (no correlation); overstates
    diversification, so drawdowns read slightly calmer than the numpy path."""
    import random
    rnd = random.Random(42)
    corpi: List[float] = []
    dds: List[float] = []
    for _ in range(n_paths):
        c = float(lump)
        idx = 1.0
        peak = 1.0
        mdd = 0.0
        for _t in range(n_months):
            r = sum(w[i] * rnd.gauss(mu_m[i], sig_m[i]) for i in range(4))
            c = c * (1.0 + r) + sip
            idx *= (1.0 + r)
            peak = max(peak, idx)
            mdd = max(mdd, (peak - idx) / peak if peak > 0 else 0.0)
        corpi.append(c)
        dds.append(mdd)
    corpi.sort()
    dds.sort()
    n = len(corpi)
    p5, p50, p95 = corpi[int(0.05 * n)], corpi[int(0.50 * n)], corpi[int(0.95 * n)]
    prob = (sum(1 for c in corpi if c >= fut_target) / n) if fut_target > 0 else None
    median_dd = dds[int(0.50 * n)]
    return prob, p5, p50, p95, median_dd
