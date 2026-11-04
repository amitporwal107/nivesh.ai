"""Exit watch: stop-loss levels and in-app exit alerts for live broker positions (docs/paper_pnl_dashboard/EXIT_WATCH.md).

rules    the 2 × ATR trailing stop (exit-atr-trail-v1), status, loss at stop, evening signals (pure)
book     broker rows → watched positions per account and underlying (pure)
view     one watched position as the screen sees it (pure)
store    Mongo: exit_watch_levels, exit_alerts, exit_watch_state
runner   the watcher: live rounds in the session, evening rounds after NSE's end-of-day file
service  the GET body and marking alerts seen
"""
