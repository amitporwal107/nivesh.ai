"""The advisor chat's system prompt must carry the portfolio context.

The prompt ends with a chart contract that contains literal JSON. Its braces
used to break str.format(), and the fallback returned the template untouched,
so the model was sent the text "{portfolio_context}" and no portfolio.
"""
import asyncio

from services import ai_engine, prompts_manager
from services.copilot_charts import CHART_PROTOCOL

CONTEXT = "HOLDINGS: Alpha Flexi Cap Fund 60% (made-up test data)"


def test_the_code_default_formats_and_keeps_the_chart_contract_verbatim():
    out = ai_engine.FINANCIAL_ADVISOR_SYSTEM.format(portfolio_context=CONTEXT)
    assert CONTEXT in out
    assert "{portfolio_context}" not in out
    assert out.endswith(CHART_PROTOCOL)              # wording unchanged, braces intact


def test_prompts_manager_returns_the_prompt_with_the_context_filled_in(monkeypatch):
    prompts_manager._ensure_bootstrap()
    monkeypatch.setattr(prompts_manager, "_cache",
                        {"financial_advisor_system": ai_engine.FINANCIAL_ADVISOR_SYSTEM})
    out = asyncio.run(prompts_manager.get("financial_advisor_system", portfolio_context=CONTEXT))
    assert CONTEXT in out and "{portfolio_context}" not in out
    assert '{"label":"HDFC","value":31.2}' in out


def test_an_override_with_literal_json_braces_still_gets_its_placeholders(monkeypatch):
    override = 'Use this shape: {"label": "x"}.\nCONTEXT:\n{portfolio_context}\nEND'
    monkeypatch.setattr(prompts_manager, "_cache", {"financial_advisor_system": override})
    out = asyncio.run(prompts_manager.get("financial_advisor_system", portfolio_context=CONTEXT))
    assert out == f'Use this shape: {{"label": "x"}}.\nCONTEXT:\n{CONTEXT}\nEND'
