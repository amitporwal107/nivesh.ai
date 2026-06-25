"""
nidp_guards — checks that catch DATA-SYSTEM DEFECTS, not value-range violations.

The schema pass surfaced bugs a bound-check would pass forever:
  - quality_score identical to final_score (accidental column duplication)
  - v3_mf_scores keyed on isin with scheme_code fanning out
  - v_shareholding_latest nondeterministic pick (multi-source per symbol/period)
  - sharpe_1y = -99999 sentinel that a naive min-bound would chase
  - documents 99.99% parse-failure; rating/credit_quality 100% NULL

Each guard is the *inverse* of a range check: it stays quiet when the system is
healthy and fires when the structure is wrong. All return CheckResult, so they
compose into suites and persist through the same sink.
"""

from __future__ import annotations

from datetime import date
import pandas as pd

from .dq_primitives import CheckResult


def _r(name, category, success, severity, message, *, actual=None, expected=None, viols=None):
    obs = {}
    if actual is not None:
        obs["actual"] = actual
    if expected is not None:
        obs["expected"] = expected
    return CheckResult(check=name, asset="", success=success,
                       severity=severity if not success else "warn",
                       category=category, message=message, observed=obs,
                       violations=viols or [])


# ===========================================================================
# Columns-not-identical  — catches accidental score duplication
# ===========================================================================
def columns_not_identical(a, b, *, max_identical_frac=0.999, severity="warn"):
    """Two columns that should be DISTINCT metrics. Fires if they match on
    (almost) every row — i.e. the engine likely assigned one metric twice."""
    def _fn(df, *, severity, category, name, **_):
        if a not in df.columns or b not in df.columns:
            return _r(name, "meta", False, "error", f"column(s) absent: {a},{b}")
        av = pd.to_numeric(df[a], errors="coerce")
        bv = pd.to_numeric(df[b], errors="coerce")
        both = av.notna() & bv.notna()
        n = int(both.sum())
        if n == 0:
            return _r(name, category, True, severity, f"no overlapping non-null rows for {a},{b}")
        identical = int(((av[both] - bv[both]).abs() < 1e-9).sum())
        frac = identical / n
        bad = frac >= max_identical_frac
        return _r(name, category, not bad, severity,
                  f"{a} == {b} on {frac:.4%} of {n} rows "
                  f"({'DUPLICATE-METRIC suspected' if bad else 'ok'})",
                  actual=round(frac, 6),
                  expected={"max_identical_frac": max_identical_frac, "cols": [a, b]})
    from .dq_rules import Rule
    return Rule(f"C8.cols_not_identical[{a},{b}]", "C8", severity, _fn, {})


# ===========================================================================
# Distinct-count-per-key  — catches fan-out (isin -> many scheme_codes)
# ===========================================================================
def distinct_count_per_key(key_cols, attr_col, *, max_distinct=1, severity="fail"):
    """For each key group, the attribute should take <= max_distinct values.
    e.g. one scheme_code per (isin, as_of_date), else downstream joins fan out."""
    key_cols = list(key_cols)

    def _fn(df, *, severity, category, name, **_):
        miss = [c for c in key_cols + [attr_col] if c not in df.columns]
        if miss:
            return _r(name, "meta", False, "error", f"column(s) absent: {miss}")
        g = df.groupby(key_cols)[attr_col].nunique()
        bad = g[g > max_distinct]
        viols = []
        for keyvals, cnt in bad.items():
            kv = keyvals if isinstance(keyvals, tuple) else (keyvals,)
            viols.append({**dict(zip(key_cols, [str(x) for x in kv])),
                          f"distinct_{attr_col}": int(cnt)})
        return _r(name, category, bad.empty, severity,
                  f"{len(bad)} key group(s) with >{max_distinct} distinct {attr_col} "
                  f"(fan-out risk)",
                  actual=len(bad),
                  expected={"key": key_cols, "attr": attr_col, "max_distinct": max_distinct},
                  viols=viols[:50])
    from .dq_rules import Rule
    return Rule(f"C6.distinct_per_key[{attr_col} by {','.join(key_cols)}]",
                "C6", severity, _fn, {})


# ===========================================================================
# Multi-source tripwire  — for nondeterministic "latest" views
# ===========================================================================
def single_source_per_key(key_cols, source_col="source", *, severity="warn"):
    """Every (symbol, period_end) with >1 source is a coin-flip in any latest-view
    that partitions without source. This is the tripwire; the durable fix is a
    deterministic tiebreak in the VIEW. Default warn (it's a latent risk, not yet
    a wrong value), raise to fail once the view is fixed."""
    key_cols = list(key_cols)

    def _fn(df, *, severity, category, name, **_):
        miss = [c for c in key_cols + [source_col] if c not in df.columns]
        if miss:
            return _r(name, "meta", False, "error", f"column(s) absent: {miss}")
        g = df.groupby(key_cols)[source_col].nunique()
        bad = g[g > 1]
        viols = []
        for keyvals, cnt in bad.items():
            kv = keyvals if isinstance(keyvals, tuple) else (keyvals,)
            viols.append({**dict(zip(key_cols, [str(x) for x in kv])), "sources": int(cnt)})
        return _r(name, category, bad.empty, severity,
                  f"{len(bad)} key group(s) with multiple sources "
                  f"(nondeterministic latest-pick)",
                  actual=len(bad), expected={"key": key_cols},
                  viols=viols[:50])
    from .dq_rules import Rule
    return Rule(f"C6.single_source[{','.join(key_cols)}]", "C6", severity, _fn, {})


# ===========================================================================
# Sentinel-aware between  — excludes -99999-style sentinels before bounding
# ===========================================================================
def between_excluding_sentinels(col, *, min=None, max=None, sentinels=(-99999.9999, -99999.99, -9999),
                                flag_sentinels=True, severity="fail"):
    """Bound a column AFTER removing known sentinels, so the bound isn't dragged
    to chase the sentinel. If flag_sentinels, sentinel presence is itself reported."""
    sentinels = tuple(sentinels)

    def _fn(df, *, severity, category, name, **_):
        if col not in df.columns:
            return _r(name, "meta", False, "error", f"column absent: {col}")
        v = pd.to_numeric(df[col], errors="coerce")
        is_sentinel = v.isin(sentinels)
        n_sentinel = int(is_sentinel.sum())
        real = v[~is_sentinel & v.notna()]
        cond = pd.Series(True, index=real.index)
        if min is not None:
            cond &= real >= min
        if max is not None:
            cond &= real <= max
        out_of_band = int((~cond).sum())
        msg = f"{out_of_band} row(s) of {col} outside [{min},{max}] (excl. sentinels)"
        if flag_sentinels and n_sentinel:
            msg += f"; {n_sentinel} sentinel row(s) present {sentinels}"
        bad = out_of_band > 0 or (flag_sentinels and n_sentinel > 0)
        return _r(name, category, not bad, severity, msg,
                  actual={"out_of_band": out_of_band, "sentinels": n_sentinel},
                  expected={"min": min, "max": max, "sentinels": list(sentinels)})
    from .dq_rules import Rule
    return Rule(f"C2.between_ex_sentinel[{col}]", "C2", severity, _fn, {})


# ===========================================================================
# Rate floor  — parse-success-rate / population floor
# ===========================================================================
def success_rate_floor(col, ok_values, *, min_rate, severity="warn"):
    """Fraction of rows where col ∈ ok_values must be >= min_rate. Catches the
    99.99% parse-failure case (col=parse_status, ok={'parsed'}, min_rate=0.5)."""
    ok_set = {str(x) for x in ok_values}

    def _fn(df, *, severity, category, name, **_):
        if col not in df.columns:
            return _r(name, "meta", False, "error", f"column absent: {col}")
        total = len(df)
        if total == 0:
            return _r(name, category, True, severity, "no rows")
        ok = int(df[col].astype(str).isin(ok_set).sum())
        rate = ok / total
        bad = rate < min_rate
        return _r(name, category, not bad, severity,
                  f"{col} success-rate {rate:.4%} (floor {min_rate:.2%}); ok={ok}/{total}",
                  actual=round(rate, 6),
                  expected={"ok_values": sorted(ok_set), "min_rate": min_rate})
    from .dq_rules import Rule
    return Rule(f"C8.success_rate[{col}]", "C8", severity, _fn, {})


# ===========================================================================
# NULL-rate within band  — coverage drift (band NULLs, untagged instruments)
# ===========================================================================
def null_rate_within(col, *, max_rate, severity="warn"):
    """Fraction of NULL in col must be <= max_rate. Baseline the current rate;
    a jump catches an engine that started emitting NULL en masse. For columns
    that are KNOWN ~100% NULL today (rating, portfolio_ytm), set max_rate=1.0 and
    raise it once the feed is built — the check then becomes meaningful."""
    def _fn(df, *, severity, category, name, **_):
        if col not in df.columns:
            return _r(name, "meta", False, "error", f"column absent: {col}")
        total = len(df)
        if total == 0:
            return _r(name, category, True, severity, "no rows")
        null_rate = float(df[col].isna().mean())
        bad = null_rate > max_rate
        return _r(name, category, not bad, severity,
                  f"{col} null-rate {null_rate:.2%} (max {max_rate:.2%})",
                  actual=round(null_rate, 4), expected={"max_null_rate": max_rate})
    from .dq_rules import Rule
    return Rule(f"C1.null_rate[{col}]", "C1", severity, _fn, {})
