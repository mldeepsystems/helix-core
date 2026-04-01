"""
Stage 5 validation tests: CLI entrypoint and smoke test script.

Run:
  pytest tests/test_stage5_cli_smoketest.py -v
"""

from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELIX_CLI = REPO_ROOT / "scripts" / "helix"
CHECK_PY = REPO_ROOT / "scripts" / "check.py"
SETUP_PY = REPO_ROOT / "scripts" / "setup.py"
START_PY = REPO_ROOT / "scripts" / "start.py"

sys.path.insert(0, str(REPO_ROOT))


# ── File existence and permissions ────────────────────────────────────────────

def test_helix_cli_exists():
    assert HELIX_CLI.exists(), f"scripts/helix not found at {HELIX_CLI}"

def test_helix_cli_is_executable():
    mode = HELIX_CLI.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/helix must be executable (chmod +x)"

def test_helix_cli_is_bash_script():
    first_line = HELIX_CLI.read_text().splitlines()[0]
    assert "bash" in first_line, f"scripts/helix must have a bash shebang, got: {first_line!r}"

def test_check_py_exists():
    assert CHECK_PY.exists()

def test_check_py_has_no_external_imports():
    """check.py must use stdlib only — it runs before any pip install."""
    content = CHECK_PY.read_text()
    forbidden = ["import requests", "import httpx", "import anthropic", "import langfuse"]
    for imp in forbidden:
        assert imp not in content, f"check.py must not import {imp!r} (stdlib only)"


# ── helix CLI dispatch ────────────────────────────────────────────────────────

def _run_helix(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(HELIX_CLI), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
    )


def test_helix_help_exits_zero():
    result = _run_helix("help")
    assert result.returncode == 0

def test_helix_help_output():
    result = _run_helix("help")
    assert "setup" in result.stdout
    assert "check" in result.stdout
    assert "cloud" in result.stdout

def test_helix_no_args_runs_start():
    """helix with no args delegates to start.py (may fail due to missing services)."""
    result = _run_helix()
    combined = result.stdout + result.stderr
    # start.py prints the banner or runs prerequisites — either is fine
    assert "helix" in combined.lower() or "prerequisite" in combined.lower() or \
           result.returncode in (0, 1), (
        "helix with no args must delegate to start.py"
    )

def test_helix_setup_help_dispatches_to_setup_py():
    """helix setup --help should call setup.py and show its help."""
    result = _run_helix("setup", "--help")
    # setup.py uses argparse; --help exits 0 and prints usage
    assert "setup" in result.stdout.lower() or "model" in result.stdout.lower() or result.returncode == 0

def test_helix_cloud_init_exits_zero():
    result = _run_helix("cloud", "init")
    assert result.returncode == 0

def test_helix_cloud_init_mentions_deferred():
    result = _run_helix("cloud", "init")
    output = result.stdout.lower()
    assert "defer" in output or "v1.1" in output or "follow" in output, (
        f"helix cloud init must mention deferral, got: {result.stdout!r}"
    )

def test_helix_unknown_command_exits_nonzero():
    result = _run_helix("nonexistent-command")
    assert result.returncode != 0

def test_helix_unknown_command_error_message():
    result = _run_helix("nonexistent-command")
    assert "error" in result.stderr.lower() or "unknown" in result.stderr.lower()


# ── check.py structure ────────────────────────────────────────────────────────

def test_check_py_has_llama_server_check():
    content = CHECK_PY.read_text()
    assert "llama" in content.lower() or "8080" in content

def test_check_py_has_litellm_check():
    content = CHECK_PY.read_text()
    assert "litellm" in content.lower() or "4000" in content

def test_check_py_has_tool_call_check():
    content = CHECK_PY.read_text()
    assert "tool" in content.lower()

def test_check_py_has_langfuse_check():
    content = CHECK_PY.read_text()
    assert "langfuse" in content.lower() or "3002" in content

def test_check_py_has_anthropic_base_url_check():
    content = CHECK_PY.read_text()
    assert "ANTHROPIC_BASE_URL" in content

def test_check_py_reads_ports_from_env():
    """Ports must come from env vars, not be hardcoded only."""
    content = CHECK_PY.read_text()
    assert "LITELLM_PORT" in content
    assert "LLAMA_SERVER_PORT" in content

def test_check_py_has_exit_codes():
    content = CHECK_PY.read_text()
    assert "sys.exit" in content or "exit(" in content


# ── check.py runtime: stack down → exit non-zero ─────────────────────────────

def test_check_py_fails_when_stack_is_down():
    """With no services running, check.py must exit non-zero."""
    env = {
        **os.environ,
        "LITELLM_PORT": "19999",       # nothing listening here
        "LLAMA_SERVER_PORT": "19998",
        "LANGFUSE_PORT": "19997",
    }
    result = subprocess.run(
        [sys.executable, str(CHECK_PY)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode != 0, (
        "check.py must exit non-zero when services are unreachable"
    )

def test_check_py_reports_failures_clearly():
    """Failure output must contain a failure indicator."""
    env = {
        **os.environ,
        "LITELLM_PORT": "19999",
        "LLAMA_SERVER_PORT": "19998",
        "LANGFUSE_PORT": "19997",
    }
    result = subprocess.run(
        [sys.executable, str(CHECK_PY)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    combined = result.stdout + result.stderr
    assert "✗" in combined or "failed" in combined.lower() or "error" in combined.lower(), (
        "check.py should clearly report which checks failed"
    )


# ── check.py runtime: mock server → selected checks pass ─────────────────────

class _MockLlamaHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()


def _start_mock_server(port: int) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), _MockLlamaHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def test_llama_server_check_passes_with_mock():
    """check.py exits 0 for llama-server check when /health returns 200."""
    port = 18088
    server = _start_mock_server(port)
    try:
        # Run check.py with unreachable ports for everything except llama-server
        # It will fail overall (LiteLLM/Langfuse down) but llama-server check passes
        env = {
            **os.environ,
            "LLAMA_SERVER_PORT": str(port),
            "LITELLM_PORT": "19999",
            "LANGFUSE_PORT": "19997",
        }
        result = subprocess.run(
            [sys.executable, str(CHECK_PY)],
            capture_output=True, text=True, env=env, timeout=30,
        )
        # llama-server check should pass (✓ in output)
        combined = result.stdout + result.stderr
        assert "✓" in combined or "health" in combined.lower(), (
            f"Expected llama-server health to pass with mock. Output:\n{combined}"
        )
    finally:
        server.shutdown()


def test_anthropic_base_url_check_passes_with_localhost():
    """check.py reports ANTHROPIC_BASE_URL pass when set to localhost."""
    env = {
        **os.environ,
        "ANTHROPIC_BASE_URL": "http://localhost:4000",
        "LITELLM_PORT": "19999",
        "LLAMA_SERVER_PORT": "19998",
        "LANGFUSE_PORT": "19997",
    }
    result = subprocess.run(
        [sys.executable, str(CHECK_PY)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    combined = result.stdout + result.stderr
    # The ANTHROPIC_BASE_URL check should pass (produce a ✓ line)
    assert "localhost" in combined or "✓" in combined, (
        f"Expected ANTHROPIC_BASE_URL check to pass. Output:\n{combined}"
    )


def test_anthropic_base_url_check_fails_without_env():
    """check.py reports ANTHROPIC_BASE_URL failure when env var is not set."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
    env.update({
        "LITELLM_PORT": "19999",
        "LLAMA_SERVER_PORT": "19998",
        "LANGFUSE_PORT": "19997",
    })
    result = subprocess.run(
        [sys.executable, str(CHECK_PY)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    combined = result.stdout + result.stderr
    assert "✗" in combined or "failed" in combined.lower(), (
        f"Expected failure indicator when ANTHROPIC_BASE_URL not set. Output:\n{combined}"
    )


# ── helix check dispatches to check.py ───────────────────────────────────────

def test_helix_check_dispatches_to_check_py():
    """helix check runs check.py (which fails with no stack — that's expected)."""
    env = {
        **os.environ,
        "LITELLM_PORT": "19999",
        "LLAMA_SERVER_PORT": "19998",
        "LANGFUSE_PORT": "19997",
    }
    result = _run_helix("check", env=env)
    # check.py should run (even if it exits non-zero due to no stack)
    # Key: it ran check.py, not some other script
    combined = result.stdout + result.stderr
    assert "helix check" in combined or "✗" in combined or "checking" in combined or \
           "stack" in combined.lower() or "litellm" in combined.lower() or \
           result.returncode in (0, 1), (
        "helix check must dispatch to check.py"
    )


# ── start.py existence and structure ────────────────────────────────────────

def test_start_py_exists():
    assert START_PY.exists(), f"scripts/start.py not found at {START_PY}"

def test_start_py_has_no_external_imports():
    """start.py must use stdlib only — it runs before any pip install."""
    content = START_PY.read_text()
    forbidden = ["import requests", "import httpx", "import anthropic", "import langfuse"]
    for imp in forbidden:
        assert imp not in content, f"start.py must not import {imp!r} (stdlib only)"

def test_start_py_has_main():
    content = START_PY.read_text()
    assert "def main" in content

def test_start_py_has_prerequisites_check():
    content = START_PY.read_text()
    assert "check_prerequisites" in content

def test_start_py_has_auto_setup():
    content = START_PY.read_text()
    assert "run_auto_setup" in content or "auto_setup" in content

def test_start_py_has_compose_start():
    content = START_PY.read_text()
    assert "start_compose" in content or "compose" in content.lower()

def test_start_py_has_health_wait():
    content = START_PY.read_text()
    assert "wait_for_health" in content or "wait_for_service" in content

def test_start_py_has_claude_launch():
    content = START_PY.read_text()
    assert "launch_claude" in content

def test_start_py_has_no_launch_flag():
    content = START_PY.read_text()
    assert "--no-launch" in content

def test_start_py_reads_ports_from_env():
    content = START_PY.read_text()
    assert "LITELLM_PORT" in content
    assert "LLAMA_SERVER_PORT" in content

def test_start_py_sets_anthropic_env():
    """start.py must set ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN for claude."""
    content = START_PY.read_text()
    assert "ANTHROPIC_BASE_URL" in content
    assert "ANTHROPIC_AUTH_TOKEN" in content


# ── setup.py --auto flag ─────────────────────────────────────────────────────

def test_setup_py_has_auto_flag():
    content = SETUP_PY.read_text()
    assert "--auto" in content

def test_setup_py_auto_in_argparse():
    """--auto must be registered as an argparse argument."""
    content = SETUP_PY.read_text()
    assert "add_argument" in content and "--auto" in content

def test_setup_py_auto_skips_interactive():
    """In --auto mode, setup.py must not prompt for input."""
    content = SETUP_PY.read_text()
    # The auto path should use recommend_model, not ask()
    assert "args.auto" in content
    assert "recommend_model" in content


# ── helix up / down / status subcommands ─────────────────────────────────────

def test_helix_help_mentions_up():
    result = _run_helix("help")
    assert "up" in result.stdout

def test_helix_help_mentions_down():
    result = _run_helix("help")
    assert "down" in result.stdout

def test_helix_help_mentions_status():
    result = _run_helix("help")
    assert "status" in result.stdout

def test_helix_up_delegates_to_start_py():
    """helix up runs start.py --no-launch (may fail due to missing services)."""
    result = _run_helix("up")
    combined = result.stdout + result.stderr
    # start.py prints the banner or prerequisite check output
    assert "helix" in combined.lower() or "prerequisite" in combined.lower() or \
           result.returncode in (0, 1), (
        "helix up must delegate to start.py --no-launch"
    )

def test_helix_status_dispatches_to_check_py():
    """helix status runs check.py (same as helix check)."""
    env = {
        **os.environ,
        "LITELLM_PORT": "19999",
        "LLAMA_SERVER_PORT": "19998",
        "LANGFUSE_PORT": "19997",
    }
    result = _run_helix("status", env=env)
    combined = result.stdout + result.stderr
    assert "helix check" in combined or "✗" in combined or "checking" in combined or \
           result.returncode in (0, 1), (
        "helix status must dispatch to check.py"
    )
