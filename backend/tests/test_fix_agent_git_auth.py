"""services.fix_agent: the GitHub token never appears in a git URL, a git command line or the
clone's .git/config.

The clone and push tests run real git against a local bare repository (no network); the GitHub
REST call is faked.
"""
from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from pathlib import Path

import pytest

from services import fix_agent

TOKEN = "unit-test-token-0123456789abcdef"


def _run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def origin(tmp_path, monkeypatch) -> Path:
    """A bare repository with a `dev` branch, standing in for GitHub."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    _run(["git", "init", "-q", "--bare", str(bare)])
    _run(["git", "init", "-q", "-b", fix_agent.BASE_BRANCH, str(seed)])
    (seed / "app.py").write_text("print('hello')\n")
    _run(["git", "add", "-A"], seed)
    _run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init"], seed)
    _run(["git", "push", "-q", str(bare), fix_agent.BASE_BRANCH], seed)
    monkeypatch.setattr(fix_agent, "_repo_url", lambda: f"file://{bare}")
    return bare


@pytest.fixture
def git_calls(monkeypatch) -> list:
    """Every subprocess.run the module makes, recorded, then run for real."""
    calls: list = []
    real = subprocess.run

    def recording(args, *a, **kw):
        calls.append({"argv": list(args), "env": kw.get("env")})
        return real(args, *a, **kw)

    monkeypatch.setattr(fix_agent.subprocess, "run", recording)
    return calls


def _no_token_in(argv):
    joined = " ".join(argv)
    assert TOKEN not in joined
    assert base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode() not in joined
    assert "x-access-token" not in joined


def test_the_auth_env_carries_the_token_only_as_a_github_scoped_header():
    env = fix_agent._git_auth_env(TOKEN)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    scheme, value = env["GIT_CONFIG_VALUE_0"].split(": ", 1)[1].split(" ", 1)
    assert scheme == "Basic" and base64.b64decode(value).decode() == f"x-access-token:{TOKEN}"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_the_repo_url_has_no_credentials():
    url = fix_agent._repo_url()
    assert url == f"https://github.com/{fix_agent.REPO_OWNER}/{fix_agent.REPO_NAME}.git"
    assert "@" not in url


def test_the_clone_command_has_no_token(monkeypatch, tmp_path):
    seen = []

    def fake_run(args, *a, **kw):
        seen.append((list(args), kw.get("env") or {}))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(fix_agent.subprocess, "run", fake_run)
    fix_agent._clone(TOKEN, tmp_path)
    argv, env = seen[0]
    assert argv[:2] == ["git", "clone"] and fix_agent._repo_url() in argv
    _no_token_in(argv)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"


def test_a_real_clone_keeps_the_token_out_of_the_repository(origin, tmp_path, git_calls):
    repo = fix_agent._clone(TOKEN, tmp_path / "work")
    assert (repo / "app.py").is_file()
    remote = _run(["git", "config", "--get", "remote.origin.url"], repo)
    assert remote == f"file://{origin}" and "@" not in remote
    for f in (repo / ".git").rglob("*"):
        if f.is_file():
            assert TOKEN.encode() not in f.read_bytes(), f
    for c in git_calls:
        _no_token_in(c["argv"])


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_push_and_pr_pushes_without_the_token_on_the_command_line_and_without_hooks(
        origin, tmp_path, git_calls, monkeypatch):
    repo = fix_agent._clone(TOKEN, tmp_path / "work")
    (repo / "app.py").write_text("print('fixed')\n")
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)

    requests = []

    def fake_urlopen(req, timeout=None):
        requests.append(req)
        return _FakeResponse({"html_url": "https://github.com/example/pr/1"})

    monkeypatch.setattr(fix_agent.urllib.request, "urlopen", fake_urlopen)
    branch = "fix/work-0001-test"
    url, created = fix_agent._push_and_pr(repo, branch, TOKEN, {"issue_id": "WORK-0001", "title": "t"}, "ok")

    assert (url, created) == ("https://github.com/example/pr/1", True)
    assert _run(["git", "--git-dir", str(origin), "rev-parse", "--verify", f"refs/heads/{branch}"])
    assert not marker.exists()                                  # repository hooks did not run
    push = next(c for c in git_calls if "push" in c["argv"])
    assert "--no-verify" in push["argv"] and "core.hooksPath=/dev/null" in push["argv"]
    assert push["env"]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    for c in git_calls:
        _no_token_in(c["argv"])
    assert TOKEN.encode() not in (repo / ".git" / "config").read_bytes()
    # The PR is still opened with the token, in the API request header only.
    assert requests[0].get_header("Authorization") == f"Bearer {TOKEN}"


def test_a_disabled_agent_stays_disabled(monkeypatch):
    failed = []

    async def fake_fail(issue_id, detail):
        failed.append((issue_id, detail))

    def no_clone(*a, **k):
        raise AssertionError("must not clone when disabled")

    monkeypatch.setenv("FIX_AGENT_ENABLED", "false")
    monkeypatch.setattr(fix_agent, "_fail", fake_fail)
    monkeypatch.setattr(fix_agent, "_clone", no_clone)
    asyncio.run(fix_agent.run_fix("WORK-0001"))
    assert failed == [("WORK-0001", "fix agent disabled (set FIX_AGENT_ENABLED=true to allow)")]
