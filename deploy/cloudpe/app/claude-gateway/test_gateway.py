"""Tests for gateway.py. The Claude Code CLI is replaced by a fake that echoes
what it was given, so nothing here calls a model.

    python3 -m unittest deploy/cloudpe/app/claude-gateway/test_gateway.py
"""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gateway  # noqa: E402

# MOCK — not real data: stands in for the `claude` binary and echoes its inputs.
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, sys, time
argv = sys.argv[1:]
system = open(argv[argv.index("--system-prompt-file") + 1], encoding="utf-8").read()
prompt = sys.stdin.read()
def emit(o): print(json.dumps(o), flush=True)
emit({"type": "system", "subtype": "init", "model": "fake-claude", "tools": []})
if "MAKE_IT_FAIL" in prompt:
    emit({"type": "result", "subtype": "error", "is_error": True, "result": "usage limit reached"})
    sys.exit(1)
if "MAKE_IT_HANG" in prompt:
    time.sleep(30)
echo = json.dumps({"system": system, "prompt": prompt, "argv": argv})
for piece in (echo[: len(echo) // 2], echo[len(echo) // 2:]):
    emit({"type": "stream_event", "event": {"type": "content_block_delta",
          "delta": {"type": "text_delta", "text": piece}}})
emit({"type": "stream_event", "event": {"type": "content_block_delta",
      "delta": {"type": "thinking_delta", "thinking": "hidden"}}})
emit({"type": "result", "subtype": "success", "is_error": False, "result": echo, "stop_reason": "end_turn",
      "usage": {"input_tokens": 3, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 7, "output_tokens": 5}})
'''


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        fake = os.path.join(cls.tmp.name, "claude")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write(FAKE_CLAUDE)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        work = os.path.join(cls.tmp.name, "work")
        os.makedirs(work)
        cls.cfg = gateway.load_config({
            "CLAUDE_GATEWAY_TOKEN": "test-token", "CLAUDE_GATEWAY_PORT": "0",
            "CLAUDE_GATEWAY_CLAUDE_BIN": fake, "CLAUDE_GATEWAY_WORK_DIR": work,
            "CLAUDE_GATEWAY_TIMEOUT_S": "2",
        })
        cls.server = gateway.make_server(cls.cfg)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def _post(self, body, token="test-token", path="/v1/chat/completions"):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def _echo(self, body):
        status, raw = self._post(body)
        self.assertEqual(status, 200, raw)
        return json.loads(raw), json.loads(json.loads(raw)["choices"][0]["message"]["content"])

    def test_health_needs_no_token_and_completions_do(self):
        with urllib.request.urlopen(self.base + "/health", timeout=5) as resp:
            self.assertEqual(json.loads(resp.read())["ok"], True)
        for token in (None, "wrong"):
            status, raw = self._post({"messages": [{"role": "user", "content": "hi"}]}, token=token)
            self.assertEqual(status, 401)
            self.assertEqual(json.loads(raw)["error"]["type"], "authentication_error")

    def test_system_and_user_text_reach_claude_unchanged(self):
        system = "MASTER PROMPT — line one\nline two with ₹ and \"quotes\""
        out, echo = self._echo({"model": "gpt-4o-mini", "temperature": 0.2, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": "What is my XIRR?"}]})
        self.assertEqual(echo["system"], system)
        self.assertEqual(echo["prompt"], "What is my XIRR?")
        self.assertEqual(out["object"], "chat.completion")
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")
        self.assertEqual(out["model"], "fake-claude")
        self.assertEqual(out["usage"], {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25})

    def test_claude_runs_with_every_tool_and_setting_source_switched_off(self):
        _, echo = self._echo({"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]})
        argv = echo["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertNotIn("--model", argv)             # an OpenAI model id is not passed on
        self.assertEqual(echo["system"], "You are a helpful assistant.")

    def test_a_claude_model_id_is_passed_on(self):
        _, echo = self._echo({"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "hi"}]})
        argv = echo["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-5-5")

    def test_multi_turn_history_becomes_a_transcript(self):
        _, echo = self._echo({"messages": [
            {"role": "system", "content": "S"},
            {"role": "user", "content": [{"type": "text", "text": "first question"}]},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"}]})
        p = echo["prompt"]
        self.assertLess(p.index("first question"), p.index("first answer"))
        self.assertLess(p.index("first answer"), p.index("second question"))
        self.assertIn('<turn role="assistant">', p)

    def test_streaming_emits_openai_chunks_and_drops_thinking(self):
        status, raw = self._post({"stream": True, "stream_options": {"include_usage": True}, "messages": [
            {"role": "system", "content": "S"}, {"role": "user", "content": "stream please"}]})
        self.assertEqual(status, 200, raw)
        events = [ln[6:] for ln in raw.splitlines() if ln.startswith("data: ")]
        self.assertEqual(events[-1], "[DONE]")
        chunks = [json.loads(e) for e in events[:-1]]
        self.assertEqual(chunks[0]["choices"][0]["delta"], {"role": "assistant", "content": ""})
        text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks if c["choices"])
        self.assertEqual(json.loads(text)["prompt"], "stream please")
        self.assertNotIn("hidden", raw)
        self.assertEqual([c["choices"][0]["finish_reason"] for c in chunks if c["choices"]][-1], "stop")
        self.assertEqual(chunks[-1]["usage"]["total_tokens"], 25)

    def test_a_claude_failure_is_an_error_not_an_empty_answer(self):
        for stream in (False, True):
            status, raw = self._post({"stream": stream, "messages": [{"role": "user", "content": "MAKE_IT_FAIL"}]})
            self.assertEqual(status, 502, raw)
            self.assertIn("usage limit reached", json.loads(raw)["error"]["message"])

    def test_a_hung_claude_is_killed_and_reported_as_a_timeout(self):
        status, raw = self._post({"messages": [{"role": "user", "content": "MAKE_IT_HANG"}]})
        self.assertEqual(status, 504, raw)

    def test_unsupported_requests_are_rejected(self):
        user = {"role": "user", "content": "hi"}
        for body in (
            {"messages": []},
            {"messages": [{"role": "system", "content": "only a system message"}]},
            {"messages": [user], "tools": [{"type": "function", "function": {"name": "f"}}]},
            {"messages": [user], "n": 2},
            {"messages": [{"role": "tool", "content": "x"}]},
            {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:..."}}]}]},
        ):
            status, raw = self._post(body)
            self.assertEqual(status, 400, raw)
        self.assertEqual(self._post({"messages": [user]}, path="/v1/embeddings")[0], 404)

    def test_the_gateway_refuses_to_start_without_a_token(self):
        with self.assertRaises(SystemExit):
            gateway.load_config({})


if __name__ == "__main__":
    unittest.main()
