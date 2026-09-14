"""Ten-Percent Days 3.0 — point-in-time large-move probability model (MVP).

Four heads: P(high >= +10%) and P(low <= -10%) for the next session, and the same within five sessions
measured from the prediction day's close. Everything a prediction for session T uses must have been knowable
at 15:30 IST on T; the tests in nidp/tests/services/tpd_model pin that contract.

Spec and plan: .claude/workspace/ten-percent-days-3/.
"""
