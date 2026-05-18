"""Nightly refresh of nidp.mf_derived_analytics.

Calls the SQL helper ``nidp.refresh_mf_derived_analytics`` (migration 051)
which iterates all active schemes and recomputes consistency, downside
capture, AUM trend, turnover, credit-quality and duration-risk fields.

The function has its own skip-logic (re-uses values < 7 days old unless
forced), so it is safe to invoke nightly.
"""
