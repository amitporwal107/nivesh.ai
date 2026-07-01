"""Demo target for INC-1845 (synthetic). A tiny slice of a 'recommendation flow'.

BUG (intentional, for the Phoenix walking-skeleton demo): recommend_allocation
crashes with a TypeError when a holding's weight is None (unknown). A None weight
should be treated as 0.0, not raise. This is the null-handling defect Phoenix's
ClaudeTask is asked to fix, scoped by the constraint_set to THIS file only.
"""


def recommend_allocation(holdings):
    """Sum the weights across holdings.

    holdings: list of {"weight": float | None}
    Returns the total allocated weight.
    """
    total = 0.0
    for h in holdings:
        total += h["weight"] or 0.0
    return total
