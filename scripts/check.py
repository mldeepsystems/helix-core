"""
helix check — smoke test for the helix-core stack.

Validates end-to-end that all services are running and the Claude Code
integration works. Uses stdlib only (no external dependencies).

Exit codes:
  0  — all checks passed
  1  — one or more checks failed

Usage:
  python scripts/check.py
  ./scripts/helix check
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# ── Config (from environment, with defaults matching .env.example) ────────────

LITELLM_PORT = int(os.environ.get("LITELLM_PORT", "4000"))
LLAMA_SERVER_PORT = int(os.environ.get("LLAMA_SERVER_PORT", "8080"))
LANGFUSE_PORT = int(os.environ.get("LANGFUSE_PORT", "3002"))
LITELLM_MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-helix-local")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_INIT_PROJECT_SECRET_KEY", "")

TIMEOUT = 10  # seconds per HTTP request

# ── ANSI colours ──────────────────────────────────────────────────────────────

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"

def _ok(msg: str) -> str:
    return f"  {GREEN}✓{RESET}  {msg}"

def _fail(msg: str) -> str:
    return f"  {RED}✗{RESET}  {msg}"

def _warn(msg: str) -> str:
    return f"  {YELLOW}⚠{RESET}  {msg}"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str, headers: dict | None = None, timeout: int = TIMEOUT) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def _post_json(url: str, payload: dict, headers: dict | None = None,
               timeout: int = TIMEOUT) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())
        except Exception:
            detail = {}
        return e.code, detail
    except Exception as exc:
        return 0, {"error": str(exc)}


# ── Checks ────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    detail: str = ""


def check_llama_server() -> CheckResult:
    status, body = _get(f"http://localhost:{LLAMA_SERVER_PORT}/health")
    if status == 200:
        return CheckResult("llama-server health", True, f"GET /health → {status}")
    return CheckResult(
        "llama-server health", False,
        f"GET http://localhost:{LLAMA_SERVER_PORT}/health → {status or 'connection refused'}",
        "Is llama-server running? Try: docker compose up -d llama-server",
    )


def check_litellm() -> CheckResult:
    status, body = _get(
        f"http://localhost:{LITELLM_PORT}/health",
        headers={"x-api-key": LITELLM_MASTER_KEY},
    )
    if status == 200:
        return CheckResult("LiteLLM proxy health", True, f"GET /health → {status}")
    return CheckResult(
        "LiteLLM proxy health", False,
        f"GET http://localhost:{LITELLM_PORT}/health → {status or 'connection refused'}",
        "Is LiteLLM running? Try: docker compose up -d litellm",
    )


def check_tool_call() -> CheckResult:
    """Send a real Anthropic-format tool-use request through LiteLLM."""
    url = f"http://localhost:{LITELLM_PORT}/v1/messages"
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 64,
        "tools": [{
            "name": "helix_ping",
            "description": "Returns pong",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }],
        "messages": [{"role": "user", "content": "Call helix_ping to verify the stack works."}],
    }
    headers = {
        "x-api-key": LITELLM_MASTER_KEY,
        "anthropic-version": "2023-06-01",
    }
    status, resp = _post_json(url, payload, headers=headers, timeout=60)

    if status == 200:
        content = resp.get("content", [])
        has_response = len(content) > 0
        stop_reason = resp.get("stop_reason", "")
        return CheckResult(
            "Tool-use request (Anthropic format → LiteLLM → llama-server)",
            has_response,
            f"POST /v1/messages → {status}, stop_reason={stop_reason!r}",
            "" if has_response else "Response had no content blocks",
        )
    return CheckResult(
        "Tool-use request (Anthropic format → LiteLLM → llama-server)",
        False,
        f"POST /v1/messages → {status or 'connection refused'}",
        f"Response: {json.dumps(resp)[:200]}" if resp else "No response",
    )


def check_langfuse() -> CheckResult:
    status, _ = _get(f"http://localhost:{LANGFUSE_PORT}/api/public/health")
    if status == 200:
        return CheckResult("Langfuse trace store", True, f"GET /api/public/health → {status}")

    # Langfuse v2 may return 401 on the health endpoint without auth — that still means it's up
    if status == 401:
        return CheckResult("Langfuse trace store", True, f"GET /api/public/health → {status} (up, auth required)")

    return CheckResult(
        "Langfuse trace store", False,
        f"GET http://localhost:{LANGFUSE_PORT}/api/public/health → {status or 'connection refused'}",
        "Is Langfuse running? Try: docker compose up -d langfuse",
    )


def check_no_anthropic_calls() -> CheckResult:
    """
    Verify ANTHROPIC_BASE_URL is set so Claude Code routes to localhost, not api.anthropic.com.
    This is a config check — runtime verification requires inspecting Langfuse traces.
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if base_url and "localhost" in base_url:
        return CheckResult(
            "ANTHROPIC_BASE_URL points to localhost",
            True,
            f"ANTHROPIC_BASE_URL={base_url}",
        )
    if base_url and "anthropic.com" not in base_url:
        return CheckResult(
            "ANTHROPIC_BASE_URL points to localhost",
            True,
            f"ANTHROPIC_BASE_URL={base_url} (non-Anthropic endpoint)",
        )
    return CheckResult(
        "ANTHROPIC_BASE_URL points to localhost",
        False,
        f"ANTHROPIC_BASE_URL={base_url!r}",
        "Set: export ANTHROPIC_BASE_URL=http://localhost:4000\n"
        "     export ANTHROPIC_AUTH_TOKEN=sk-helix-local",
    )


# ── Runner ────────────────────────────────────────────────────────────────────

CHECKS = [
    check_llama_server,
    check_litellm,
    check_tool_call,
    check_langfuse,
    check_no_anthropic_calls,
]


def main() -> int:
    print(f"\n{BOLD}helix check — stack validation{RESET}\n")

    results: list[CheckResult] = []
    for fn in CHECKS:
        name = fn.__name__.replace("check_", "").replace("_", " ")
        print(f"  checking {name}...", end="", flush=True)
        result = fn()
        results.append(result)
        if result.passed:
            print(f"\r{_ok(result.message)}")
        else:
            print(f"\r{_fail(result.message)}")
            if result.detail:
                for line in result.detail.splitlines():
                    print(f"       {YELLOW}{line}{RESET}")

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print()
    if passed == total:
        print(f"{GREEN}{BOLD}  All {total} checks passed.{RESET}")
        print(f"\n  Claude Code is ready:")
        print(f"    export ANTHROPIC_BASE_URL=http://localhost:{LITELLM_PORT}")
        print(f"    export ANTHROPIC_AUTH_TOKEN={LITELLM_MASTER_KEY}")
        print(f"    claude\n")
        return 0
    else:
        print(f"{RED}{BOLD}  {passed}/{total} checks passed — fix the failures above.{RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
