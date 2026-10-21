#!/usr/bin/env python3
"""Claude Code gateway — an OpenAI-compatible chat endpoint backed by the Claude
Code CLI installed on this VM.

    POST /v1/chat/completions   (bearer auth; stream or non-stream)
    GET  /v1/models             (bearer auth)
    GET  /health                (no auth)

The app backend already speaks the OpenAI chat format, so it is pointed at this
service instead of api.openai.com (see copilot_agent/_llm.py, provider
"claude_code"). Each request runs one `claude -p` process under the login this
VM's Claude Code already has; no API key is involved.

What a request can and cannot do:
  * The caller's system message REPLACES Claude Code's own system prompt, so the
    model sees the same prompts the app sent to OpenAI.
  * Every tool is switched off (`--tools ""`, no MCP servers, no user/project
    settings). The text in a request comes from end users; with no tools the
    model can only answer in text and cannot read files or run commands here.
  * Text only: no images, no tool calling, no embeddings.

Standard library only, so it runs on the host Python with nothing to install.
Configuration is by environment variable — see load_config().
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

logger = logging.getLogger("claude-gateway")

MAX_BODY_BYTES = 8 * 1024 * 1024
_MODEL_ALIASES = {"opus", "sonnet", "haiku", "fable"}
_TEXT_PART_TYPES = {"text", "input_text", "output_text"}


class RequestError(Exception):
    """A request the gateway rejects; carries the HTTP status to answer with."""

    def __init__(self, status: int, message: str, kind: str = "invalid_request_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.kind = kind


def load_config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    token = env.get("CLAUDE_GATEWAY_TOKEN", "").strip()
    if not token:
        raise SystemExit("CLAUDE_GATEWAY_TOKEN is not set; refusing to start an unauthenticated gateway")
    return {
        "token":       token,
        "host":        env.get("CLAUDE_GATEWAY_HOST", "127.0.0.1"),
        "port":        int(env.get("CLAUDE_GATEWAY_PORT", "8790")),
        "claude_bin":  env.get("CLAUDE_GATEWAY_CLAUDE_BIN", "claude"),
        # Empty = whatever model the Claude Code login defaults to.
        "model":       env.get("CLAUDE_GATEWAY_MODEL", "").strip(),
        # An empty directory: nothing for Claude Code to discover (no CLAUDE.md, no repo).
        "work_dir":    env.get("CLAUDE_GATEWAY_WORK_DIR", "/var/lib/claude-gateway/work"),
        "timeout_s":   float(env.get("CLAUDE_GATEWAY_TIMEOUT_S", "180")),
        "max_running": int(env.get("CLAUDE_GATEWAY_MAX_CONCURRENCY", "4")),
        "queue_wait_s": float(env.get("CLAUDE_GATEWAY_QUEUE_WAIT_S", "30")),
    }


# ── request → prompt ─────────────────────────────────────────────────────────

def _content_text(content: Any) -> str:
    """An OpenAI message `content` (string or list of parts) as plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: List[str] = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and part.get("type") in _TEXT_PART_TYPES:
                out.append(str(part.get("text") or ""))
            else:
                raise RequestError(400, "only text content is supported by this gateway")
        return "\n".join(out)
    raise RequestError(400, "message content must be a string or a list of parts")


def build_prompt(messages: Any) -> Tuple[str, str]:
    """OpenAI `messages` → (system prompt, prompt text).

    System (and developer) messages are joined, unchanged, into the system
    prompt. A single user message is passed through verbatim. A longer
    conversation is rendered as a transcript, because `claude -p` takes one
    prompt per run.
    """
    if not isinstance(messages, list) or not messages:
        raise RequestError(400, "'messages' must be a non-empty list")
    system_parts: List[str] = []
    turns: List[Tuple[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            raise RequestError(400, "every message must be an object")
        role = m.get("role")
        text = _content_text(m.get("content"))
        if role in ("system", "developer"):
            system_parts.append(text)
        elif role in ("user", "assistant"):
            turns.append((role, text))
        else:
            raise RequestError(400, f"unsupported message role {role!r}")
    if not turns:
        raise RequestError(400, "'messages' needs at least one user message")
    system = "\n\n".join(p for p in system_parts if p)
    if len(turns) == 1 and turns[0][0] == "user":
        return system, turns[0][1]
    lines = ["The conversation so far:", ""]
    for role, text in turns:
        lines.append(f'<turn role="{role}">\n{text}\n</turn>')
    lines += ["", "Write the assistant's next reply to this conversation. Reply with the message only."]
    return system, "\n".join(lines)


def pick_model(requested: Any, default: str) -> Optional[str]:
    """Callers built for OpenAI send ids like `gpt-4o-mini`; those are ignored
    and the gateway's own default is used. A Claude id or alias is honoured."""
    if isinstance(requested, str):
        r = requested.strip()
        if r.startswith("claude-") or r in _MODEL_ALIASES:
            return r
    return default or None


def validate(body: Any) -> None:
    if not isinstance(body, dict):
        raise RequestError(400, "request body must be a JSON object")
    if body.get("tools") or body.get("functions"):
        raise RequestError(400, "tool calling is not supported by this gateway")
    if body.get("n") not in (None, 1):
        raise RequestError(400, "only n=1 is supported")


# ── claude -p ────────────────────────────────────────────────────────────────

def claude_argv(cfg: Dict[str, Any], system_file: str, model: Optional[str]) -> List[str]:
    argv = [
        cfg["claude_bin"], "-p",
        "--system-prompt-file", system_file,
        "--tools", "",                    # no built-in tools at all
        "--strict-mcp-config",            # and no MCP servers
        "--setting-sources", "",          # ignore user/project/local settings and hooks
        "--no-session-persistence",       # nothing from a request is saved to disk
        "--output-format", "stream-json", "--include-partial-messages", "--verbose",
    ]
    if model:
        argv += ["--model", model]
    return argv


def parse_stream(lines: Iterable[str]) -> Iterator[Tuple[str, Any]]:
    """Claude Code stream-json lines → ("model", id) | ("text", delta) | ("result", event)."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            if ev.get("model"):
                yield "model", ev["model"]
        elif kind == "stream_event":
            inner = ev.get("event") or {}
            delta = inner.get("delta") or {}
            if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                if delta.get("text"):
                    yield "text", delta["text"]
        elif kind == "result":
            yield "result", ev


def _child_env() -> Dict[str, str]:
    """The gateway's environment minus its own token and minus the markers that
    make Claude Code think it is nested inside another Claude Code session."""
    return {
        k: v for k, v in os.environ.items()
        if not (k.startswith("CLAUDE_GATEWAY_") or k == "CLAUDECODE" or k == "CLAUDE_CODE_ENTRYPOINT")
    }


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _usage(result: Optional[Dict[str, Any]]) -> Dict[str, int]:
    u = (result or {}).get("usage") or {}
    prompt = sum(int(u.get(k) or 0) for k in
                 ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    completion = int(u.get("output_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "claude-gateway/1"
    cfg: Dict[str, Any] = {}
    slots: threading.BoundedSemaphore

    def log_message(self, fmt, *args):  # request lines are logged by _log_done instead
        pass

    # -- plumbing --
    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _send_error(self, status: int, message: str, kind: str = "invalid_request_error") -> None:
        self._send_json(status, {"error": {"message": message, "type": kind, "code": status}})

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
        return bool(supplied) and hmac.compare_digest(supplied.encode(), self.cfg["token"].encode())

    def _path(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/")

    # -- routes --
    def do_GET(self):
        path = self._path()
        if path == "/health":
            return self._send_json(200, {"ok": True, "service": "claude-gateway"})
        if path in ("/v1/models", "/models"):
            if not self._authorised():
                return self._send_error(401, "missing or invalid bearer token", "authentication_error")
            mid = self.cfg["model"] or "claude-code"
            return self._send_json(200, {"object": "list", "data": [
                {"id": mid, "object": "model", "owned_by": "anthropic"}]})
        self._send_error(404, "not found")

    def do_POST(self):
        if self._path() not in ("/v1/chat/completions", "/chat/completions"):
            return self._send_error(404, "not found")
        if not self._authorised():
            return self._send_error(401, "missing or invalid bearer token", "authentication_error")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise RequestError(413 if length > MAX_BODY_BYTES else 400, "missing or oversized request body")
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                raise RequestError(400, "request body is not valid JSON") from None
            validate(body)
            system, prompt = build_prompt(body.get("messages"))
        except RequestError as exc:
            return self._send_error(exc.status, exc.message, exc.kind)

        if not self.slots.acquire(timeout=self.cfg["queue_wait_s"]):
            return self._send_error(429, "the gateway is busy; retry shortly", "rate_limit_error")
        try:
            self._complete(body, system, prompt)
        finally:
            self.slots.release()

    # -- one completion --
    def _complete(self, body: Dict[str, Any], system: str, prompt: str) -> None:
        cfg = self.cfg
        stream = bool(body.get("stream"))
        want_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        model = pick_model(body.get("model"), cfg["model"])
        req_id = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())
        started_at = time.monotonic()

        # A caller that sends no system message must still not get Claude Code's
        # own coding-assistant prompt, so a neutral one is substituted.
        sys_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        sys_file.write(system or "You are a helpful assistant.")
        sys_file.close()
        err_file = tempfile.TemporaryFile()
        timed_out = threading.Event()
        proc: Optional[subprocess.Popen] = None
        timer: Optional[threading.Timer] = None
        model_name = model or "claude-code"
        parts: List[str] = []
        result: Optional[Dict[str, Any]] = None
        headers_sent = False
        status = "ok"

        def chunk(delta: Dict[str, Any], finish: Optional[str] = None) -> bytes:
            return b"data: " + json.dumps({
                "id": req_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }).encode() + b"\n\n"

        try:
            try:
                proc = subprocess.Popen(
                    claude_argv(cfg, sys_file.name, model),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err_file,
                    cwd=cfg["work_dir"], env=_child_env(), text=True, encoding="utf-8",
                    start_new_session=True,
                )
            except OSError as exc:
                status = "spawn_failed"
                logger.error("cannot start claude: %s", exc)
                return self._send_error(502, "the Claude Code CLI could not be started", "api_error")

            def on_timeout():
                timed_out.set()
                _kill(proc)
            timer = threading.Timer(cfg["timeout_s"], on_timeout)
            timer.daemon = True
            timer.start()

            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except BrokenPipeError:
                pass                      # the process died early; its exit is reported below

            for kind, value in parse_stream(proc.stdout):
                if kind == "model":
                    model_name = value
                elif kind == "text":
                    parts.append(value)
                    if stream:
                        if not headers_sent:
                            self.send_response(200)
                            self.send_header("Content-Type", "text/event-stream")
                            self.send_header("Cache-Control", "no-cache")
                            self.send_header("Connection", "close")
                            self.end_headers()
                            self.close_connection = True
                            headers_sent = True
                            self.wfile.write(chunk({"role": "assistant", "content": ""}))
                        self.wfile.write(chunk({"content": value}))
                        self.wfile.flush()
                elif kind == "result":
                    result = value
            rc = proc.wait()

            failed = timed_out.is_set() or result is None or bool(result.get("is_error")) or rc != 0
            if failed:
                if timed_out.is_set():
                    status, http, message = "timeout", 504, f"Claude Code did not answer within {int(cfg['timeout_s'])}s"
                else:
                    err_file.seek(0)
                    detail = str((result or {}).get("result") or "").strip() \
                        or err_file.read().decode("utf-8", "replace").strip()
                    status, http, message = "claude_error", 502, ("Claude Code failed: " + detail[-400:]) if detail \
                        else f"Claude Code exited with status {rc}"
                if headers_sent:          # mid-stream: the status line is gone, so send an error event
                    self.wfile.write(b"data: " + json.dumps(
                        {"error": {"message": message, "type": "api_error", "code": http}}).encode() + b"\n\n")
                    self.wfile.flush()
                    return
                return self._send_error(http, message, "api_error")

            text = "".join(parts) or str(result.get("result") or "")
            finish = "length" if result.get("stop_reason") == "max_tokens" else "stop"
            usage = _usage(result)
            if not stream:
                return self._send_json(200, {
                    "id": req_id, "object": "chat.completion", "created": created, "model": model_name,
                    "choices": [{"index": 0, "finish_reason": finish,
                                 "message": {"role": "assistant", "content": text}}],
                    "usage": usage,
                })
            if not headers_sent:          # an answer that arrived without partial events
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                headers_sent = True
                self.wfile.write(chunk({"role": "assistant", "content": text}))
            self.wfile.write(chunk({}, finish))
            if want_usage:
                self.wfile.write(b"data: " + json.dumps({
                    "id": req_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
                    "choices": [], "usage": usage}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            status = "client_gone"        # the caller hung up; stop paying for the answer
        finally:
            if timer:
                timer.cancel()
            if proc is not None and proc.poll() is None:
                _kill(proc)
                proc.wait()
            if proc is not None:
                for pipe in (proc.stdin, proc.stdout):
                    try:
                        pipe.close()
                    except OSError:
                        pass
            err_file.close()
            try:
                os.unlink(sys_file.name)
            except OSError:
                pass
            u = _usage(result)
            # Sizes and timings only — never prompt or answer text.
            logger.info("%s status=%s stream=%s model=%s secs=%.1f in_tok=%d out_tok=%d sys_chars=%d prompt_chars=%d",
                        req_id, status, stream, model_name, time.monotonic() - started_at,
                        u["prompt_tokens"], u["completion_tokens"], len(system), len(prompt))


def make_server(cfg: Dict[str, Any]) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {
        "cfg": cfg, "slots": threading.BoundedSemaphore(cfg["max_running"])})
    server = ThreadingHTTPServer((cfg["host"], cfg["port"]), handler)
    server.daemon_threads = True
    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    cfg = load_config()
    os.makedirs(cfg["work_dir"], exist_ok=True)
    server = make_server(cfg)
    logger.info("listening on %s:%s (model=%s, max_concurrency=%s)",
                cfg["host"], cfg["port"], cfg["model"] or "claude-code default", cfg["max_running"])
    server.serve_forever()


if __name__ == "__main__":
    main()
