"""Owner wording rule (3 Nov 2026): "Please check compliance and do not use words like buy, stop loss, target".

Nivesh is not a SEBI-registered Research Analyst, so no user-visible text may read like a trading call. Approved
vocabulary: Buy / Sell → Long / Short; Stop loss / SL / stop → Risk level; Target / T1 / T2 → Reward level; Entry →
Reference price; "Loss at stop" → "Loss at risk level"; never pick / recommend / suggested trade (25 Oct rule: "ideas",
"fits", "ordered for review"). Test cases TC-1..TC-3 of test_reports/compliance_wording_TESTCASES.md.

What this guards, permanently:
  WL-1  every prose string literal in services/copilot_visual/*.py (builders' titles, labels, notices, follow-up chips),
        read from the source with `ast` — question-recognition regexes (re.compile), dict keys, comparisons, `.get()`
        keys and single contract tokens ("stop", "entry", "BUY", "stop_breached") are not prose and are skipped;
  WL-2  the payloads the builders actually produce for the fixtures tests/test_copilot_visual.py and
        tests/test_copilot_research_answers.py use (every user-visible string, as the research TC-B7 lint walks them);
  WL-3  every suggestion template and rule text in services/suggestions/catalog.py, placeholders removed;
  WL-4  the Copilot's suggested-prompt chips (routes/copilot_prompts.py + routes/copilot_prompt_catalog.py);
  WL-5  the compliance node: its follow-up chips, its note and scrub marker are clean; the shared VOCABULARY_RULE reaches
        every answer prompt; the scrub catches the imperative forms and leaves the approved vocabulary alone.

Recognising these words in a USER'S question is not advice, so the routing regexes keep them (and are skipped here).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# The banned words (the research TC-B7 LINT, extended to the owner's 3 Nov list and its approved replacements).
LINT = re.compile(
    r"\b(buy|buys|buying|bought|sell|sells|selling|sold|stop[- ]?loss(?:es)?|sl|stops?|targets?|t1|t2|entry|entries|"
    r"exit|exits|exited|book(?:ing)?\s+profits?|profit[- ]booking|accumulate|trim|upside|downside|recommend\w*|picks?|"
    r"price\s+targets?|suggested\s+(?:trade|trades|strateg(?:y|ies)))\b", re.I)
# Non-trading senses, removed before the lint (each one is a fixed term, not a call).
ALLOW = re.compile(r"\bexit\s+load\b|\b(?:long|short)\s+build[- ]?ups?\b|\bshort\s+covering\b|\blong\s+unwinding\b", re.I)


def hits(text: str) -> List[str]:
    return LINT.findall(ALLOW.sub(" ", re.sub(r"\{[^{}]*\}", " ", text)))


# ── WL-1: static strings of every copilot_visual module ────────────────────────────────────────────────────────────

_CONTRACT_TOKEN = re.compile(r"[a-z0-9_\-.:/#]+|[A-Z0-9_&]+")          # "stop", "entry_not_reached", "BUY", "SL"
_SKIP_FILES = {"intents.py", "research_intents.py", "screen_spec.py"}     # question recognition only (see the module docs)


def _prose_literals(path: Path) -> Iterator[Tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    docs = {n.body[0].value for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}

    def skipped(node: ast.AST) -> bool:
        child, p = node, parents.get(node)
        while isinstance(p, (ast.JoinedStr, ast.FormattedValue, ast.BinOp, ast.IfExp, ast.BoolOp)):
            child, p = p, parents.get(p)
        if isinstance(p, ast.Dict) and child in p.keys:
            return True                                                    # a key, not text
        if isinstance(p, (ast.Compare, ast.Subscript)):
            return True                                                    # a comparison / an index: data codes
        if isinstance(p, ast.Call):
            fn = ast.unparse(p.func)
            if fn.endswith(("re.compile", ".get", ".setdefault", ".pop", "getattr", "logger.warning", "logger.info",
                            "logger.debug", "logger.exception")):
                return True                                                # a question regex, a key read, a log line
        return False

    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n in docs or isinstance(parents.get(n), ast.JoinedStr) or skipped(n):
                continue
            text = n.value
        elif isinstance(n, ast.JoinedStr):
            if isinstance(parents.get(n), ast.JoinedStr) or skipped(n):
                continue
            text = "".join(v.value if isinstance(v, ast.Constant) else "{…}" for v in n.values)
        else:
            continue
        if _CONTRACT_TOKEN.fullmatch(text.strip()):
            continue                                                       # a data code / field name, never shown as prose
        yield n.lineno, text


@pytest.mark.parametrize("path", sorted(p for p in (BACKEND / "services" / "copilot_visual").glob("*.py")
                                        if p.name not in _SKIP_FILES), ids=lambda p: p.name)
def test_wl1_copilot_visual_static_strings_have_no_trading_call_words(path):
    bad = [(line, text[:120], hits(text)) for line, text in _prose_literals(path) if hits(text)]
    assert bad == [], bad


def test_wl1_the_lint_catches_the_old_wording():
    # The lint itself: the labels this branch replaced would fail it; their replacements pass.
    for old in ("Stop", "Target 1", "Entry", "Loss at stop", "Buy 1 lot of the 24,000 put", "Should I book profits or hold AAA?",
                "Ideas to review, not recommendations.", "first target", "T1", "Top 3 picks", "a sell signal", "upside capped"):
        assert hits(old), old
    for new in ("Risk level", "Reward level 1", "Reference price", "Loss at risk level", "Long 1 lot of the 24,000 put",
                "Close or hold AAA? Show my trade's levels", "Ideas to review, not advice.", "Long buildup", "exit load",
                "Suggestions", "Accumulation"):
        assert not hits(new), new


# ── WL-2: the payloads the builders produce ───────────────────────────────────────────────────────────────────────

def _texts(x) -> List[str]:
    """Every user-visible string in a payload (the research TC-B7 walk). Keys that carry codes are skipped; so are the
    cells of a contract column (a level `kind`, a block `type`)."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [t for k, v in x.items() if k not in ("intent", "schema", "id", "key", "type", "kind", "plan_id", "action",
                                                      "path", "query_string", "screener_query", "symbol", "tone", "format")
                for t in _texts(v)]
    if isinstance(x, list):
        return [t for v in x for t in _texts(v)]
    return []


def _payload_hits(p) -> List[Tuple[str, List[str]]]:
    return [(t[:120], hits(t)) for t in _texts(p) if hits(t)]


from tests import test_copilot_visual as _tcv  # noqa: E402  (the shared fakes: tests/test_copilot_visual.py Src)

_CORE = [("market_view", None, {}, ""), ("smart_money", None, {}, ""), ("top_opportunities", None, {"n": 5}, ""),
         ("breakouts", None, {}, ""), ("unusual_volume", None, {}, ""),
         ("stock_decision", "TVSMOTOR", {}, "Trade plan for TVSMOTOR"), ("expected_move", "NIFTY", {}, ""),
         ("expected_move", "BANKNIFTY", {}, ""), ("open_trades", None, {}, ""), ("fno_setups", None, {}, ""),
         ("trade_validity", "TVSMOTOR", {}, "Is TVSMOTOR still valid?"),
         ("exit_options", "AAA", {}, "Close or hold AAA? Show my trade's levels"), ("position_size", None, {}, ""),
         ("position_size", "TVSMOTOR", {}, ""), ("daily_review", None, {"period": "day"}, ""),
         ("daily_review", None, {"period": "week"}, ""), ("sector_rotation", None, {}, ""),
         ("screen_stocks", None, {}, "Screen large cap stocks with ROE over 20")]


@pytest.fixture
def vsrc(monkeypatch):
    return _tcv.Src(monkeypatch)


@pytest.mark.parametrize("name, symbol, params, message", _CORE, ids=[f"{c[0]}:{c[1] or ''}:{c[2]}" for c in _CORE])
def test_wl2_built_payloads_have_no_trading_call_words(vsrc, name, symbol, params, message):
    p = _tcv.build(name, symbol, params, message=message)
    assert _payload_hits(p) == [], (name, _payload_hits(p))


def test_wl2_built_payloads_when_every_read_fails(vsrc):
    vsrc.fail.update({"market_snapshot", "sector_returns", "chain", "fii_dii", "buildup", "regime", "market_state", "watchlist_day",
                      "positional_watchlist", "scan_snapshot", "open_trades", "fno_top", "risk_profile", "risk_book",
                      "latest_trade_plan", "closed_trades", "risk_decisions", "stock_bars", "open_book", "broker_trades"})
    for name, symbol, params, message in _CORE:
        p = _tcv.build(name, symbol, params, message=message)
        assert _payload_hits(p) == [], (name, _payload_hits(p))


def test_wl2_hedge_payload_says_long_and_short(vsrc):
    # Quick Hedge structures read "Long 2 lots of the 24,000 put, short the 23,000 put" (owner: Buy/Sell → Long/Short).
    from services.copilot_visual import builders
    assert builders._hedge_structure({"structure": "put_spread", "legs": [{"strike": 24000, "qty": 150}, {"strike": 23000, "qty": 150}]}, 75) \
        == "Long 2 lots of the 24,000 put, short the 23,000 put"
    assert builders._hedge_structure({"legs": [{"strike": 24000, "qty": 75}]}, 75) == "Long 1 lot of the 24,000 put"


from tests import test_copilot_research_answers as _tra  # noqa: E402  (the research answers' fakes)


@pytest.fixture
def rsrc(monkeypatch):
    return _tra.Readers(monkeypatch)


@pytest.mark.parametrize("name, params", [("financial_trend", {}), ("valuation_view", {"growth": [15.0]}), ("ownership_trend", {}),
                                          ("peer_compare", {"symbols": ["ACME", "PEERA"]}), ("company_risks", {})])
def test_wl2_research_payloads_have_no_trading_call_words(rsrc, name, params):
    p = _tra.build(name, **params)
    assert _payload_hits(p) == [], (name, _payload_hits(p))


# ── WL-3: suggestion templates and rules ──────────────────────────────────────────────────────────────────────────

def test_wl3_suggestion_catalog_text_has_no_trading_call_words():
    from services.suggestions import catalog
    shown = ("label", "query", "title", "why", "description", "name", "footer")
    texts: List[Tuple[str, str]] = []
    for c, spec in catalog.CLASSES.items():
        texts += [(f"class {c}.{k}", spec[k]) for k in shown if isinstance(spec.get(k), str)]
    for coll in ("QUERY_TEMPLATES", "RULES"):
        for item in getattr(catalog, coll):
            texts += [(f"{coll} {item.get('_id')}.{k}", item[k]) for k in shown if isinstance(item.get(k), str)]
    assert len(texts) > 20
    bad = [(where, text, hits(text)) for where, text in texts if hits(text)]
    assert bad == [], bad


# ── WL-4: the suggested-prompt chips ──────────────────────────────────────────────────────────────────────────────

# Kept on purpose, each listed for the owner in test_reports/compliance_wording_<date>.md: a SIP that "stopped" is not a
# trading word, and "exit load" is a fund fee term (ALLOW above).
def _chip_dicts(x) -> Iterator[dict]:
    if isinstance(x, dict):
        if any(k in x for k in ("label", "outcome", "query", "caption")):
            yield x
        for v in x.values():
            yield from _chip_dicts(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _chip_dicts(v)


def test_wl4_suggested_prompt_chips_have_no_trading_call_words():
    from routes import copilot_prompt_catalog as cat, copilot_prompts as cp
    rows = list(_chip_dicts([cat.PERSONA_TEMPLATES, cp._PROMPT_TEMPLATES, cp._advisor_prompts(), cp._trader_prompts(),
                             cp._investor_prompts_curated()]))
    texts = [(r.get("id") or r.get("_id") or r.get("label"), k, r[k]) for r in rows for k in ("label", "outcome", "query", "caption")
             if isinstance(r.get(k), str)]
    assert len(texts) > 50
    bad = [(i, k, t, hits(t)) for i, k, t in texts if hits(t)]
    assert bad == [], bad


# ── WL-5: the compliance node and the answer prompts ──────────────────────────────────────────────────────────────

def test_wl5_compliance_chips_note_and_marker_are_clean():
    from nidp.services.copilot_agent.nodes import compliance
    for agent, chips in compliance._DEFAULT_FOLLOW_UPS.items():
        for chip in chips:
            assert not hits(chip), (agent, chip)
    assert not hits(compliance._ADVICE_NOTE)
    scrubbed, had = compliance._scrub_advice("You should buy TCS now.")
    assert had and "[factual data only — not advice]" in scrubbed and not hits(scrubbed.replace("TCS", ""))


@pytest.mark.parametrize("persona, desk", [(None, None), ("active_trader", None), ("swing_trader", "trader"),
                                           ("retail_investor", "investor"), ("mfd_advisor", None), ("unknown", "advisor")])
def test_wl5_every_answer_prompt_carries_the_vocabulary_rule(persona, desk):
    from nidp.services.copilot_agent import persona_framing as pf
    from nidp.services.copilot_agent.nodes import compliance
    text = pf.frame_for_persona(persona, desk)
    assert compliance.VOCABULARY_RULE in text
    for word in ("reference price", "risk level", "reward level", "long", "short", "ideas", "ordered for review"):
        assert word in compliance.VOCABULARY_RULE, word


def test_wl5_every_specialist_node_builds_its_prompt_through_the_framing():
    # The rule reaches an answer only through frame_for_persona: every specialist node must call it.
    nodes = BACKEND / "nidp" / "services" / "copilot_agent" / "nodes"
    for name in ("market", "stock", "mf", "portfolio", "risk", "goal", "recommendation", "backtest", "stocks_insights"):
        assert "frame_for_persona(state.persona, state.desk_persona)" in (nodes / f"{name}.py").read_text(encoding="utf-8"), name


@pytest.mark.parametrize("phrase", ["Keep a stop loss at ₹2,350.", "Stop-loss: 2350", "Target of ₹2,600 is in reach.",
                                    "T1: 2600", "SL ₹2,340", "Buy now before results.", "This is a sell signal.",
                                    "Book profits above 2,600.", "Accumulate on dips.", "Exit at ₹2,300 if it breaks.",
                                    "Set a stop loss under support.", "Analysts' price targets are higher."])
def test_wl5_the_scrub_catches_imperative_calls(phrase):
    from nidp.services.copilot_agent.nodes import compliance
    out, had = compliance._scrub_advice(phrase)
    assert had and out != phrase, phrase


@pytest.mark.parametrize("phrase", ["The reference price is ₹2,400, the risk level ₹2,350 and reward level 1 ₹2,500.",
                                    "Long 1 NIFTY 24000 CE, short 1 NIFTY 24200 CE.", "Loss at risk level: ₹4,500.",
                                    "FIIs had a net outflow of ₹1,200 Cr.", "Close or hold TCS? Show my trade's levels",
                                    "These are ideas that fit the rules, ordered for review.", "Check the exit load first."])
def test_wl5_the_scrub_leaves_the_approved_vocabulary_alone(phrase):
    from nidp.services.copilot_agent.nodes import compliance
    assert compliance._scrub_advice(phrase) == (phrase, False)
