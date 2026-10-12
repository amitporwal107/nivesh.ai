"""Provider selection and reply handling for the copilot chat model
(nidp/services/copilot_agent/_llm.py). No network calls: the Claude client is
constructed and its request payload inspected, never sent."""
import pytest

from nidp.services.copilot_agent import _llm

KEYS = ("COPILOT_LLM_PROVIDER", "COPILOT_ANTHROPIC_MODEL", "COPILOT_LLM_MODEL", "GROQ_MODEL",
        "ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    # keys come from env only in these tests (no Secret Manager / admin overrides)
    monkeypatch.setattr(_llm, "get_anthropic_api_key", lambda: __import__("os").environ.get("ANTHROPIC_API_KEY", ""))
    monkeypatch.setattr(_llm, "get_groq_api_key", lambda: __import__("os").environ.get("GROQ_API_KEY", ""))


def test_claude_is_used_when_an_anthropic_key_is_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")            # Claude wins over Groq
    assert _llm.llm_provider() == "anthropic"
    assert _llm.resolve_model() == "claude-opus-5-5"


def test_without_an_anthropic_key_the_previous_order_is_unchanged(monkeypatch):
    assert _llm.llm_provider() == "openai"
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert _llm.llm_provider() == "groq"


@pytest.mark.parametrize("value, expected", [("anthropic", "anthropic"), ("claude", "anthropic"), ("openai", "openai"), ("groq", "groq")])
def test_explicit_provider_setting_wins(monkeypatch, value, expected):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("COPILOT_LLM_PROVIDER", value)
    assert _llm.llm_provider() == expected


def test_claude_model_ignores_the_openai_model_pin(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("COPILOT_LLM_MODEL", "gpt-5.5")        # stale OpenAI id must not reach Claude
    assert _llm.resolve_model() == "claude-opus-5-5"
    monkeypatch.setenv("COPILOT_ANTHROPIC_MODEL", "claude-sonnet-5-5")
    assert _llm.resolve_model() == "claude-sonnet-5-5"


def test_claude_chat_model_sends_no_sampling_parameters(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llm = _llm.make_chat_llm(_llm.temperature_for(0.2))
    assert type(llm).__name__ == "ChatAnthropic"
    payload = llm._get_request_payload([("system", "be brief"), ("human", "hi")])
    assert payload["model"] == "claude-opus-5-5"
    assert payload["max_tokens"] == 16000
    # current Claude models reject temperature / top_p / top_k with a 400
    assert not {"temperature", "top_p", "top_k"} & set(payload)
    assert payload["system"] and payload["messages"][0]["role"] == "user"


def test_openai_path_still_builds_a_chatopenai_with_temperature(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(_llm, "get_openai_api_key", lambda: "sk-test")
    llm = _llm.make_chat_llm(0.2)
    assert type(llm).__name__ == "ChatOpenAI" and llm.temperature == 0.2


class _Msg:
    def __init__(self, content):
        self.content = content


@pytest.mark.parametrize("content, expected", [
    ("plain string", "plain string"),
    ([{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}], "Hello world"),
    ([{"type": "thinking", "thinking": "private reasoning", "signature": "s"}], ""),     # reasoning is never shown
    ([{"type": "text", "text": "a", "index": 0}], "a"),                                   # stream chunk shape
    ([], ""), (None, ""), ("", ""),
])
def test_text_of_returns_only_reply_text(content, expected):
    assert _llm.text_of(_Msg(content)) == expected


def test_intent_routing_json_survives_a_code_fence(monkeypatch):
    import asyncio
    from nidp.services.copilot_agent.nodes import intent

    class _LLM:
        async def ainvoke(self, messages, config=None):
            return _Msg([{"type": "thinking", "thinking": "", "signature": "s"},
                         {"type": "text", "text": 'Here you go:\n```json\n{"agent": "mf_analyst", "confidence": 0.9}\n```'}])
    monkeypatch.setattr(intent, "make_chat_llm", lambda *_a, **_k: _LLM())
    out = asyncio.run(intent._llm_classify("which funds overlap?"))
    assert getattr(out.agent, "value", out.agent) == "mf_analyst"
