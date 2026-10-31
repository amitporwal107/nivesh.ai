"""The suggestion engine's default catalog: the four tabs, the three classes with their wording, the query templates
and the rules. This is DATA. `store.seed` writes it into `query_templates` and `suggestion_rules`; a stored document
with the same id overrides the default here (enabled, thresholds, wording), so a rule can be tuned without a deploy.

Every template's `query` resolves through services/copilot_visual.resolve_intent to its declared `intent` (None = the
chat's usual path, e.g. the portfolio analyst), so clicking a card opens the same answer typing the question does.
"""
from __future__ import annotations

from typing import Any, Dict, List

SCHEMA = "suggestions-v1"
CATALOG_VERSION = 1

TABS: List[Dict[str, str]] = [
    {"key": "for_you", "label": "For you"},
    {"key": "market", "label": "Market"},
    {"key": "my_trades", "label": "My trades"},
    {"key": "fno_lab", "label": "F&O Lab"},
]
TAB_KEYS = tuple(t["key"] for t in TABS)

# One class per suggestion, each with its own wording and card treatment. No class text says buy, recommend or pick.
CLASSES: Dict[str, Dict[str, Any]] = {
    "informational": {
        "label": "To explore", "weight": 100,
        "footer": "A question to explore with the latest data. Not advice.",
    },
    "validated_signal": {
        "label": "Rule-based signal", "weight": 200,
        "footer": "Met a scanner rule on {date}. An idea to review with its evidence, not advice.",
    },
    "risk_alert": {
        "label": "Risk check", "weight": 300,
        "footer": "About your own trade's levels and limits. It does not tell you to exit or hold.",
    },
}

AUDIENCES = ("investor", "trader")

QUERY_TEMPLATES: List[Dict[str, Any]] = [
    # market
    {"_id": "t_market_view", "label": "Today's market view", "query": "What is the market view today?",
     "intent": "market_view", "tab": "market", "audience": ["investor", "trader"]},
    {"_id": "t_smart_money", "label": "Where smart money is moving", "query": "Where is smart money moving?",
     "intent": "smart_money", "tab": "market", "audience": ["investor", "trader"]},
    {"_id": "t_sector_rotation", "label": "Sector leaders and laggards", "query": "Which sectors are leading and lagging?",
     "intent": "sector_rotation", "tab": "market", "audience": ["investor", "trader"]},
    {"_id": "t_expected_move_nifty", "label": "Nifty's expected move", "query": "What is the expected move in Nifty?",
     "intent": "expected_move", "tab": "market", "audience": ["trader"]},
    {"_id": "t_breakouts", "label": "Confirmed breakouts", "query": "Which breakouts are confirmed?",
     "intent": "breakouts", "tab": "market", "audience": ["trader"]},
    {"_id": "t_unusual_volume", "label": "Unusual volume", "query": "Which stocks have unusual volume?",
     "intent": "unusual_volume", "tab": "market", "audience": ["trader"]},
    {"_id": "t_results_calendar", "label": "Who reports results this week", "query": "Which companies report results this week?",
     "intent": "results_calendar", "tab": "market", "audience": ["investor", "trader"]},
    {"_id": "t_results_fno_tomorrow", "label": "F&O names reporting tomorrow", "query": "Which F&O stocks report results tomorrow?",
     "intent": "results_calendar", "tab": "market", "audience": ["trader"]},
    {"_id": "t_event_orders", "label": "Order wins this week", "query": "Any order wins this week?",
     "intent": "event_intelligence", "tab": "market", "audience": ["investor", "trader"]},
    {"_id": "t_event_mna", "label": "M&A and corporate actions", "query": "Any M&A announcements today?",
     "intent": "event_intelligence", "tab": "market", "audience": ["investor", "trader"]},
    {"_id": "t_event_deals", "label": "Bulk and block deals", "query": "Which stocks saw bulk deals today?",
     "intent": "event_intelligence", "tab": "market", "audience": ["trader"]},
    # for you
    {"_id": "t_top_opportunities", "label": "Find today's opportunities", "query": "Which are today's top 5 opportunities?",
     "intent": "top_opportunities", "tab": "for_you", "audience": ["investor", "trader"]},
    {"_id": "t_stock_setup", "label": "The setup for a stock", "query": "What's the setup for {symbol}?",
     "intent": "stock_decision", "tab": "for_you", "audience": ["investor", "trader"], "params": ["symbol"]},
    {"_id": "t_review_portfolio", "label": "Review my portfolio",
     "query": "Review my portfolio: which holdings need attention, and why?",
     "intent": None, "tab": "for_you", "audience": ["investor", "trader"]},
    {"_id": "t_sector_exposure", "label": "Analyse sector exposure",
     "query": "Show the sector concentration and overlapping holdings in my portfolio",
     "intent": None, "tab": "for_you", "audience": ["investor", "trader"]},
    {"_id": "t_fund_overlap", "label": "Check fund overlap", "query": "Which funds in my portfolio overlap the most?",
     "intent": None, "tab": "for_you", "audience": ["investor"]},
    {"_id": "t_allocation", "label": "Review asset allocation",
     "query": "How is my portfolio split across equity, debt and gold against my risk profile?",
     "intent": None, "tab": "for_you", "audience": ["investor"]},
    {"_id": "t_plan_costs", "label": "Check regular-plan costs",
     "query": "How much of my portfolio sits in regular plans, and what does that cost each year?",
     "intent": None, "tab": "for_you", "audience": ["investor"]},
    # my trades
    {"_id": "t_open_trades", "label": "Check my open positions", "query": "What are my open trades doing?",
     "intent": "open_trades", "tab": "my_trades", "audience": ["trader"]},
    {"_id": "t_exit_options", "label": "Review a trade's levels", "query": "Should I book profits or hold {symbol}?",
     "intent": "exit_options", "tab": "my_trades", "audience": ["trader"], "params": ["symbol"]},
    {"_id": "t_position_size", "label": "How much to risk", "query": "How much should I risk?",
     "intent": "position_size", "tab": "my_trades", "audience": ["trader"]},
    {"_id": "t_trade_validity", "label": "Is a trade still valid", "query": "Is my trade in {symbol} still valid?",
     "intent": "trade_validity", "tab": "my_trades", "audience": ["trader"], "params": ["symbol"]},
    {"_id": "t_daily_review", "label": "What I learned today", "query": "What did I learn from today's trades?",
     "intent": "daily_review", "tab": "my_trades", "audience": ["trader"]},
    {"_id": "t_weekly_review", "label": "How I did this week", "query": "How did I do this week?",
     "intent": "daily_review", "tab": "my_trades", "audience": ["trader"]},
    # F&O lab
    {"_id": "t_fno_setups", "label": "F&O setups that fit today", "query": "Which F&O setups are attractive?",
     "intent": "fno_setups", "tab": "fno_lab", "audience": ["trader"]},
    {"_id": "t_expected_move_banknifty", "label": "Bank Nifty's expected move",
     "query": "What is the expected move in Bank Nifty?", "intent": "expected_move", "tab": "fno_lab", "audience": ["trader"]},
]

# `trigger` names an evaluator in rules.py; `inputs` are the sources it reads (inputs.py), each gated by `freshness`
# ("session": today's or the previous NSE session's data, services/market_freshness; "days": not older than N days).
# `title` / `why` are format strings over the evaluator's facts. `priority` is added to the class weight when ranking.
RULES: List[Dict[str, Any]] = [
    # ── Market: daily starters, one per source that is current today ─────────────────────────────────────────────
    {"_id": "market_view_daily", "name": "Daily market view", "class": "informational", "tab": "market",
     "trigger": "source_current", "inputs": ["market_snapshot"], "freshness": {"kind": "session"},
     "template_id": "t_market_view", "priority": 40, "cooldown_hours": 20, "audience": ["investor", "trader"],
     "title": "Today's key market levels", "why": "Nifty, breadth, India VIX and sector moves for {date}.",
     "description": "Shown when the market snapshot is today's or the previous session's."},
    {"_id": "smart_money_daily", "name": "Daily smart-money flows", "class": "informational", "tab": "market",
     "trigger": "source_current", "inputs": ["fii_dii"], "freshness": {"kind": "session"},
     "template_id": "t_smart_money", "priority": 35, "cooldown_hours": 20, "audience": ["investor", "trader"],
     "title": "Where smart money is moving", "why": "FII cash {fii_net}, DII cash {dii_net} on {date}.",
     "description": "Shown when NSE's FII/DII cash figures are today's or the previous session's."},
    {"_id": "expected_move_nifty_daily", "name": "Nifty expected move", "class": "informational", "tab": "market",
     "trigger": "source_current", "inputs": ["chain_NIFTY"], "freshness": {"kind": "session"},
     "template_id": "t_expected_move_nifty", "priority": 30, "cooldown_hours": 20, "audience": ["trader"],
     "title": "Nifty's expected move to {expiry}", "why": "Priced from the NIFTY option chain of {date}.",
     "description": "Shown when the NIFTY option chain (NSE F&O bhavcopy) is current."},
    {"_id": "breakouts_daily", "name": "Confirmed breakouts", "class": "informational", "tab": "market",
     "trigger": "source_current", "inputs": ["positional_watchlist"], "freshness": {"kind": "session"},
     "params": {"min_count": 1}, "template_id": "t_breakouts", "priority": 25, "cooldown_hours": 20, "audience": ["trader"],
     "title": "Which breakouts are confirmed?", "why": "{count} stocks met the confirmed-breakout rule on {date}.",
     "description": "Shown when the positional scanner's scan is current."},
    {"_id": "unusual_volume_daily", "name": "Unusual volume", "class": "informational", "tab": "market",
     "trigger": "source_current", "inputs": ["scan_snapshot"], "freshness": {"kind": "session"},
     "params": {"min_count": 1}, "template_id": "t_unusual_volume", "priority": 20, "cooldown_hours": 20, "audience": ["trader"],
     "title": "Stocks trading on unusual volume", "why": "{count} stocks met the unusual-volume rule on {date}.",
     "description": "Shown when the scan snapshot (stock features + NSE bhavcopy) is current."},
    # ── For you: opportunities and the user's own portfolio ────────────────────────────────────────────────────────
    {"_id": "opportunities_daily", "name": "Today's opportunities", "class": "informational", "tab": "for_you",
     "trigger": "ai_list_current", "inputs": ["ai_watchlist"], "freshness": {"kind": "session"},
     "template_id": "t_top_opportunities", "priority": 45, "cooldown_hours": 20, "audience": ["investor", "trader"],
     "title": "Find today's opportunities", "why": "The AI scanner's list of {date}: {ready} of the top {n} have a setup with levels.",
     "description": "Shown when the AI scanner's daily Top 10 is current."},
    {"_id": "watchlist_on_scanner", "name": "Your stock on the scanner's list", "class": "validated_signal",
     "tab": "for_you", "trigger": "watchlist_on_scanner", "inputs": ["ai_watchlist", "user_symbols"],
     "freshness": {"kind": "session"}, "template_id": "t_stock_setup", "priority": 40, "cooldown_hours": 24,
     "audience": ["investor", "trader"], "params": {"max": 3},
     "title": "{symbol} from your {where} is on today's scanner list",
     "why": "Rank {rank} of the AI scanner's list of {date}; desk status: {status}.",
     "description": "A stock you hold or watch is in the AI scanner's daily Top 10 (cash)."},
    {"_id": "portfolio_review", "name": "Review my portfolio", "class": "informational", "tab": "for_you",
     "trigger": "portfolio_review", "inputs": ["holdings", "portfolio_rules"], "freshness": {"kind": "days", "days": 7},
     "template_id": "t_review_portfolio", "priority": 38, "cooldown_hours": 72, "audience": ["investor", "trader"],
     "title": "Review my portfolio", "why": "{count} portfolio checks flag something ({topics}); holdings as of {date}.",
     "description": "The portfolio rules (routes/insights._deterministic_insights) flag at least one item."},
    {"_id": "sector_concentration", "name": "Sector concentration", "class": "informational", "tab": "for_you",
     "trigger": "portfolio_insight", "inputs": ["holdings", "portfolio_rules"], "freshness": {"kind": "days", "days": 7},
     "template_id": "t_sector_exposure", "priority": 34, "cooldown_hours": 72, "audience": ["investor", "trader"],
     "params": {"kind": "sector"},
     "title": "Analyse sector exposure", "why": "{subject} is {current} of your holdings, above the {target} ceiling the portfolio checks use.",
     "description": "A sector is above the portfolio rules' ceiling."},
    {"_id": "amc_concentration", "name": "Fund-house concentration", "class": "informational", "tab": "for_you",
     "trigger": "portfolio_insight", "inputs": ["holdings", "portfolio_rules"], "freshness": {"kind": "days", "days": 7},
     "template_id": "t_sector_exposure", "priority": 30, "cooldown_hours": 72, "audience": ["investor"],
     "params": {"kind": "amc"},
     "title": "One fund house holds a large share", "why": "{subject} manages {current} of your holdings, above the {target} guardrail.",
     "description": "One AMC is above the configured concentration guardrail."},
    {"_id": "fund_overlap", "name": "Fund overlap", "class": "informational", "tab": "for_you",
     "trigger": "fund_overlap", "inputs": ["holdings", "portfolio_facts"], "freshness": {"kind": "days", "days": 7},
     "template_id": "t_fund_overlap", "priority": 28, "cooldown_hours": 72, "audience": ["investor"],
     "params": {"min_pct": 40},
     "title": "Check fund overlap", "why": "Your two most similar funds share {pct} of their holdings.",
     "description": "The largest pairwise fund overlap is at or above the threshold."},
    {"_id": "debt_allocation", "name": "Asset allocation", "class": "informational", "tab": "for_you",
     "trigger": "portfolio_insight", "inputs": ["holdings", "portfolio_rules"], "freshness": {"kind": "days", "days": 7},
     "template_id": "t_allocation", "priority": 24, "cooldown_hours": 72, "audience": ["investor"],
     "params": {"kind": "debt"},
     "title": "Review your asset allocation", "why": "Debt is {current} of your holdings; the portfolio checks look for {target}.",
     "description": "Debt allocation is below the portfolio rules' floor."},
    {"_id": "regular_plan_cost", "name": "Regular-plan costs", "class": "informational", "tab": "for_you",
     "trigger": "portfolio_insight", "inputs": ["holdings", "portfolio_rules"], "freshness": {"kind": "days", "days": 7},
     "template_id": "t_plan_costs", "priority": 22, "cooldown_hours": 168, "audience": ["investor"],
     "params": {"kind": "cost"},
     "title": "Check regular-plan costs", "why": "{current} sits in regular plans of mutual funds.",
     "description": "Regular-plan holdings carry an estimated annual cost above the rule's floor."},
    # ── My trades: the user's own paper trades and limits ──────────────────────────────────────────────────────────
    {"_id": "open_trades_check", "name": "Open positions", "class": "informational", "tab": "my_trades",
     "trigger": "open_trades", "inputs": ["paper_trades"], "freshness": {"kind": "session"},
     "template_id": "t_open_trades", "priority": 40, "cooldown_hours": 20, "audience": ["trader"],
     "title": "Check my open positions", "why": "{count} open paper trades, marked at the close of {date}.",
     "description": "The user has open paper trades with a current end-of-day mark."},
    {"_id": "near_stop", "name": "A trade near its stop", "class": "risk_alert", "tab": "my_trades",
     "trigger": "trade_near_level", "inputs": ["paper_trades"], "freshness": {"kind": "session"},
     "template_id": "t_exit_options", "priority": 45, "cooldown_hours": 24, "audience": ["investor", "trader"],
     "params": {"level": "stop", "min_fraction": 0.7},
     "title": "{symbol} is near its stop-loss", "why": "Last close {last} on {date}; stop {level_price}, {distance} away.",
     "description": "An open paper trade has used at least 70% of the distance from its entry to its stop."},
    {"_id": "near_target", "name": "A trade near its target", "class": "informational", "tab": "my_trades",
     "trigger": "trade_near_level", "inputs": ["paper_trades"], "freshness": {"kind": "session"},
     "template_id": "t_exit_options", "priority": 30, "cooldown_hours": 24, "audience": ["trader"],
     "params": {"level": "target", "min_fraction": 0.8},
     "title": "{symbol} is near its target", "why": "Last close {last} on {date}; target {level_price}, {distance} away.",
     "description": "An open paper trade has covered at least 80% of the distance from its entry to its target."},
    {"_id": "loss_limit_use", "name": "Daily loss limit in use", "class": "risk_alert", "tab": "my_trades",
     "trigger": "loss_limit_use", "inputs": ["risk_book"], "freshness": {"kind": "session"},
     "template_id": "t_position_size", "priority": 42, "cooldown_hours": 12, "audience": ["investor", "trader"],
     "params": {"min_used_pct": 50},
     "title": "{used} of today's loss limit is used", "why": "Today's paper P&L {pnl} against a {limit} daily limit, marked {date}.",
     "description": "Today's paper loss has used at least half of the account's daily loss limit."},
    {"_id": "position_size_starter", "name": "How much to risk", "class": "informational", "tab": "my_trades",
     "trigger": "always", "inputs": [], "freshness": {"kind": "none"},
     "template_id": "t_position_size", "priority": 10, "cooldown_hours": 20, "audience": ["trader"],
     "title": "How much should I risk?", "why": "Your risk limits and how much of them is in use, from your own risk profile.",
     "description": "A starter question; it carries no figure."},
    {"_id": "daily_review_starter", "name": "Daily review", "class": "informational", "tab": "my_trades",
     "trigger": "always", "inputs": [], "freshness": {"kind": "none"},
     "template_id": "t_daily_review", "priority": 12, "cooldown_hours": 20, "audience": ["trader"],
     "title": "What did I learn from today's trades?",
     "why": "What closed and how, plan against actual, and what the risk checks refused, from your own paper trades.",
     "description": "A starter question; it carries no figure. The answer reads your paper-trade record."},
    # ── F&O lab ──────────────────────────────────────────────────────────────────────────────────────────────────────
    {"_id": "fno_setups_daily", "name": "F&O setups", "class": "informational", "tab": "fno_lab",
     "trigger": "fno_list_current", "inputs": ["ai_watchlist"], "freshness": {"kind": "session"},
     "template_id": "t_fno_setups", "priority": 40, "cooldown_hours": 20, "audience": ["trader"],
     "title": "F&O setups that fit today's regime", "why": "Defined-risk structures on the AI scanner's F&O list of {date} ({n} instruments).",
     "description": "Shown when the AI scanner's F&O list is current and its chain data is not stale."},
    {"_id": "fno_top_signals", "name": "F&O list ideas", "class": "validated_signal", "tab": "fno_lab",
     "trigger": "fno_list_signals", "inputs": ["ai_watchlist"], "freshness": {"kind": "session"},
     "template_id": "t_stock_setup", "priority": 35, "cooldown_hours": 24, "audience": ["trader"], "params": {"max": 3},
     "title": "{underlying}: {structure} fits today's regime",
     "why": "Rank {rank} on the AI scanner's F&O list of {date}; regime fit {fit}.",
     "description": "The top instruments of the AI scanner's daily F&O list (one row per instrument)."},
    {"_id": "expected_move_banknifty_daily", "name": "Bank Nifty expected move", "class": "informational",
     "tab": "fno_lab", "trigger": "source_current", "inputs": ["chain_BANKNIFTY"], "freshness": {"kind": "session"},
     "template_id": "t_expected_move_banknifty", "priority": 30, "cooldown_hours": 20, "audience": ["trader"],
     "title": "Bank Nifty's expected move to {expiry}", "why": "Priced from the BANKNIFTY option chain of {date}.",
     "description": "Shown when the BANKNIFTY option chain is current."},
]

# The index underlyings of the F&O list have no single-stock setup answer: their card opens the F&O board, where the
# structure is listed with its max loss and profit.
INDEX_TEMPLATES = {"NIFTY": "t_fno_setups", "BANKNIFTY": "t_fno_setups", "FINNIFTY": "t_fno_setups",
                   "MIDCPNIFTY": "t_fno_setups"}

for _r in RULES:
    _r.setdefault("enabled", True)
    _r.setdefault("version", CATALOG_VERSION)
    _r.setdefault("params", {})
for _t in QUERY_TEMPLATES:
    _t.setdefault("params", [])
    _t.setdefault("version", CATALOG_VERSION)
