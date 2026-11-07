"""SPT slice A, part 3: signal outcomes (PRD §13.1; Workflow §17.1) — what happened to the price after each scanner
signal, measured apart from any paper trade (Workflow §25 item 20).

    tracker.py    forward returns, MFE/MAE, fade and the hypothetical scan-plan-v3 outcome → `spt_signal_outcomes`
    analytics.py  GET /api/v1/analytics/scanners: per scanner / category / score band, with sample sizes
"""
