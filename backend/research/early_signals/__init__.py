"""Early-signals study for the Scan dashboard (owner, 3 Nov 2026): which dashboard widgets, alone or together, flag the stocks
that go on to move +5% above the day's open, and how early.

    replay.py    (main session) replays the widgets through past sessions on 5-minute candles -> flags.csv, universe.csv
    outcomes.py  what happened after each flag, from the same candles
    report.py    precision, lift, recall, lead time, upside and drawdown after the flag, per widget / confluence / pair

In-sample, research only: nothing here places or suggests a trade.
"""
