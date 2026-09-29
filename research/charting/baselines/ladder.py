"""Fit the nested ladder and report INCREMENTS, per PATTERN_VALIDATION_PRD_V1 §§10, 24 and §A3.

THREE RULES THIS MODULE EXISTS TO ENFORCE
-----------------------------------------
1. **Nested, not rival.** Each rung's feature set is a strict subset of the next, fit by the same
   procedure on the same rows and the same folds. The statistic is the INCREMENT. A richer model
   beating a smaller one proves capacity, not information.

2. **Split by SYMBOL and by TIME, never by row.** Rows are not independent: overlapping 20-session
   windows on one symbol, and many symbols moving together on one day. Row-level CV leaks symbol
   identity and inflates every number.

3. **Symbol-clustered intervals.** Effective n is nearer the symbol count than the row count.
   Measured in §A3: ATR's AUC 0.635 carries a symbol-clustered 95% CI of [0.515, 0.708] -- it
   barely excludes a coin flip. A row-level interval on the same estimate looks decisive and is
   not.

No sklearn on the study box, so the logistic fit is plain gradient descent on standardised
features. That is sufficient: the question is whether an increment exists, not whether it is
optimally extracted, and every rung is fit by the identical procedure so the comparison is fair.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Mapping, Optional, Sequence


def auc(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    """Mann-Whitney AUC with tie handling."""
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    if n == 0:
        return None
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    pos = sum(l for _s, l in pairs)
    neg = n - pos
    if pos == 0 or neg == 0:
        return None
    rsum = sum(rk for rk, (_s, l) in zip(ranks, pairs) if l == 1)
    return (rsum - pos * (pos + 1) / 2.0) / (pos * neg)


def brier(probs: Sequence[float], labels: Sequence[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def _standardise(cols: list) -> tuple:
    """Per-column mean/sd from the TRAIN fold only. Standardising on the full set would leak test
    information into the fit, which is the quiet version of the same mistake as row-level CV."""
    stats = []
    for c in cols:
        have = [v for v in c if v is not None]
        m = sum(have) / len(have) if have else 0.0
        var = sum((v - m) ** 2 for v in have) / len(have) if len(have) > 1 else 1.0
        stats.append((m, math.sqrt(var) or 1.0))
    return stats


def _design(rows_feats: list, names: Sequence[str], stats) -> list:
    """Missing values go to the column MEAN (a standardised 0), never to a raw 0 -- which for a
    distance-from-SMA feature would mean 'exactly at the average', a real and wrong claim."""
    out = []
    for fr in rows_feats:
        x = [1.0]
        for (m, sd), nm in zip(stats, names):
            v = fr.get(nm)
            x.append(0.0 if v is None else (float(v) - m) / sd)
        out.append(x)
    return out


def _fit_logistic(X: list, y: Sequence[int], *, epochs: int = 300, lr: float = 0.3,
                  l2: float = 1e-3) -> list:
    w = [0.0] * len(X[0])
    n = len(X)
    for _ in range(epochs):
        g = [0.0] * len(w)
        for xi, yi in zip(X, y):
            z = sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - yi
            for j, xj in enumerate(xi):
                g[j] += e * xj
        for j in range(len(w)):
            w[j] -= lr * (g[j] / n + (l2 * w[j] if j else 0.0))
    return w


def _predict(X: list, w: Sequence[float]) -> list:
    out = []
    for xi in X:
        z = sum(wj * xj for wj, xj in zip(w, xi))
        out.append(1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z)))))
    return out


def symbol_time_folds(symbols: Sequence[str], dates: Sequence[str], k: int = 5,
                      seed: int = 0) -> list:
    """Folds that hold out whole SYMBOLS. Rows of one symbol never straddle the split, so a model
    cannot memorise a symbol in train and be rewarded for it in test."""
    uniq = sorted(set(symbols))
    rng = random.Random(seed)
    shuffled = uniq[:]
    rng.shuffle(shuffled)
    assign = {s: i % k for i, s in enumerate(shuffled)}
    return [[i for i, s in enumerate(symbols) if assign[s] != f] for f in range(k)], \
           [[i for i, s in enumerate(symbols) if assign[s] == f] for f in range(k)]


def cross_val_auc(rows_feats: list, names: Sequence[str], labels: Sequence[int],
                  symbols: Sequence[str], dates: Sequence[str], *, k: int = 5,
                  seed: int = 0) -> dict:
    """Out-of-sample AUC and Brier, pooled across symbol-held-out folds.

    With `names` empty this is the B0 rung: an intercept only, which predicts the base rate for
    every row and therefore has AUC exactly 0.5 by construction. That is the correct floor.
    """
    train_idx, test_idx = symbol_time_folds(symbols, dates, k=k, seed=seed)
    fold_aucs: list = []
    all_p: list = []
    all_y: list = []
    row_order: list = []
    for tr, te in zip(train_idx, test_idx):
        if not tr or not te:
            continue
        cols = [[rows_feats[i].get(nm) for i in tr] for nm in names]
        stats = _standardise(cols) if names else []
        Xtr = _design([rows_feats[i] for i in tr], names, stats)
        Xte = _design([rows_feats[i] for i in te], names, stats)
        w = _fit_logistic(Xtr, [labels[i] for i in tr])
        p = _predict(Xte, w)
        y = [labels[i] for i in te]
        # AUC PER FOLD, then averaged -- never pooled across folds.
        #
        # Pooling is the obvious thing and it is wrong: each fold has its own intercept, fitted to
        # its own training base rate, so a row's score depends on WHICH FOLD it landed in as well
        # as on its features. That is discrimination the model did not earn. Caught by the B0 rung,
        # which is intercept-only and must therefore score exactly 0.5 -- pooled, it scored 0.3821.
        a = auc(p, y)
        if a is not None:
            fold_aucs.append(a)
        all_p.extend(p)
        all_y.extend(y)
        row_order.extend(te)
    mean_auc = sum(fold_aucs) / len(fold_aucs) if fold_aucs else None
    return {"auc": mean_auc, "fold_aucs": fold_aucs,
            "brier": brier(all_p, all_y) if all_p else None, "n": len(all_y),
            "base_rate": sum(all_y) / len(all_y) if all_y else None,
            # Per-ROW out-of-fold predictions, indexed back to the caller's rows. Needed for
            # market-sensitivity analysis: one model, evaluated WITHIN each regime. Fitting a
            # separate model per regime would be a different experiment with a fraction of the n,
            # and the segment differences would partly be fitting noise.
            "oof": {i: p for i, p in zip(row_order, all_p)}}


def symbol_cluster_ci(scores: Sequence[float], labels: Sequence[int], symbols: Sequence[str],
                      *, draws: int = 400, seed: int = 0) -> tuple:
    """95% CI by resampling SYMBOLS with replacement, not rows.

    §A3: the row-level interval on ATR's AUC looks decisive; the symbol-clustered one is
    [0.515, 0.708] and barely excludes 0.5. Which interval you quote changes the conclusion.
    """
    by_sym: dict = {}
    for s, sc, y in zip(symbols, scores, labels):
        by_sym.setdefault(s, []).append((sc, y))
    uniq = sorted(by_sym)
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        picked = [by_sym[uniq[rng.randrange(len(uniq))]] for _ in range(len(uniq))]
        flat = [p for grp in picked for p in grp]
        a = auc([p for p, _y in flat], [y for _p, y in flat])
        if a is not None:
            vals.append(a)
    if not vals:
        return (None, None)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])
