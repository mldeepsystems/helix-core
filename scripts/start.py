#!/usr/bin/env python3
"""
helix start — zero-friction launcher for helix-core.

Orchestrates the full flow: prerequisites → auto-setup → compose up →
health checks → launch Claude Code. Designed to be the default when
the user types `helix` with no arguments.

Stdlib only — no pip installs required.

Usage:
  python scripts/start.py              # full auto: setup + start + launch claude
  python scripts/start.py --no-launch  # start stack but don't launch claude
  python scripts/start.py --timeout 300
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── Colours ───────────────────────────────────────────────────────────────────

BOLD  = "\033[1m"
GREEN = "\033[32m"
RED   = "\033[31m"
YELLOW= "\033[33m"
CYAN  = "\033[36m"
DIM   = "\033[2m"
RESET = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def info(msg): print(f"  {CYAN}→{RESET}  {msg}")
def header(msg): print(f"\n{BOLD}── {msg} {'─' * max(0, 50 - len(msg))}{RESET}\n")

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / ".env"
SETUP_PY  = REPO_ROOT / "scripts" / "setup.py"

# ── Platform detection ────────────────────────────────────────────────────────

IS_MAC   = platform.system() == "Darwin"
IS_ARM   = platform.machine() == "arm64"
IS_APPLE = IS_MAC and IS_ARM

# ── Env helpers ───────────────────────────────────────────────────────────────

def load_env() -> dict:
    if not ENV_FILE.exists():
        return {}
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().split("#")[0].strip()
    return env


def env_val(key: str, default: str = "") -> str:
    e = load_env()
    return e.get(key) or os.environ.get(key, default)

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def http_get(url: str, timeout: int = 5) -> int:
    """Return HTTP status code, or 0 on connection failure."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def http_post_json(url: str, body: dict, headers: dict,
                   timeout: int = 90) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:    detail = json.loads(e.read())
        except: detail = {}
        return e.code, detail
    except Exception as exc:
        return 0, {"error": str(exc)}

# ── Step 1: Prerequisites ────────────────────────────────────────────────────

def check_prerequisites() -> bool:
    header("Prerequisites")
    passed = True

    # Python version
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}")
    else:
        fail(f"Python {v.major}.{v.minor} — need 3.10+")
        passed = False

    # Docker
    if shutil.which("docker"):
        r = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            ok(f"Docker {r.stdout.strip()}")
        else:
            fail("Docker installed but daemon not running — start Docker Desktop")
            passed = False
    else:
        fail("Docker not found — install: https://docs.docker.com/get-docker/")
        passed = False

    # Docker Compose
    r = subprocess.run(["docker", "compose", "version", "--short"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        ok(f"Docker Compose {r.stdout.strip()}")
    else:
        fail("Docker Compose not found (included with Docker Desktop)")
        passed = False

    # Claude Code CLI
    if shutil.which("claude"):
        ok("Claude Code CLI found")
    else:
        fail("Claude Code CLI not found — install: npm install -g @anthropic-ai/claude-code")
        passed = False

    return passed

# ── Step 2: Auto-setup ────────────────────────────────────────────────────────

def needs_setup() -> bool:
    """Return True if .env is missing or MODEL_PATH doesn't exist."""
    if not ENV_FILE.exists():
        return True
    e = load_env()
    model_path = e.get("MODEL_PATH", "")
    if not model_path or not Path(model_path).exists():
        return True
    return False


def run_auto_setup() -> bool:
    header("Auto-setup")

    if not needs_setup():
        e = load_env()
        model_path = e.get("MODEL_PATH", "")
        model_key = e.get("MODEL_KEY", "unknown")
        ok(f"Already configured — model={model_key}")
        return True

    info("First run detected — auto-detecting hardware and selecting best model...")
    print()

    result = subprocess.run(
        [sys.executable, str(SETUP_PY), "--auto"],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        fail("Auto-setup failed")
        info("Try running manually: helix setup")
        return False

    # Verify .env was created with a valid MODEL_PATH
    e = load_env()
    model_path = e.get("MODEL_PATH", "")
    if model_path and Path(model_path).exists():
        ok("Setup complete")
        return True
    elif model_path:
        fail(f"Setup completed but model not found at {model_path}")
        return False
    else:
        fail("Setup completed but MODEL_PATH is empty")
        return False

# ── Step 3: Docker Compose ────────────────────────────────────────────────────

def deployment_mode() -> str:
    return env_val("DEPLOYMENT_MODE", "local")


def compose_cmd() -> list[str]:
    """Build the docker compose command with the right -f flags for this platform."""
    compose_files = ["docker-compose.yml"]
    if IS_APPLE:
        compose_files = ["docker-compose.mac.yml"]
    elif deployment_mode() == "cpu":
        compose_files = ["docker-compose.yml", "docker-compose.cpu.yml"]

    cmd = ["docker", "compose"]
    for f in compose_files:
        cmd += ["-f", f]
    return cmd


def stack_is_healthy() -> bool:
    """Quick check: are all critical services already responding?"""
    llama_port   = int(env_val("LLAMA_SERVER_PORT", "8080"))
    litellm_port = int(env_val("LITELLM_PORT", "4000"))

    llama_ok  = http_get(f"http://localhost:{llama_port}/health", timeout=3) == 200
    litellm_ok = http_get(f"http://localhost:{litellm_port}/health/readiness", timeout=3) == 200

    return llama_ok and litellm_ok


def start_compose() -> bool:
    header("Docker Compose")

    if stack_is_healthy():
        ok("Stack already running and healthy")
        return True

    cmd = compose_cmd()
    info(f"Starting: {' '.join(cmd)} up -d")

    env = {**os.environ, **load_env()}
    result = subprocess.run(cmd + ["up", "-d"], cwd=REPO_ROOT, env=env)
    if result.returncode != 0:
        fail("docker compose up failed")
        return False

    ok("docker compose up -d completed")
    return True

# ── Step 4: Wait for health ──────────────────────────────────────────────────

def wait_for_service(name: str, url: str, timeout: int,
                     acceptable: set[int] = {200}) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        status = http_get(url, timeout=5)
        if status in acceptable:
            elapsed = time.monotonic() - start
            ok(f"{name} ready ({elapsed:.0f}s)")
            return True
        elapsed = time.monotonic() - start
        print(f"\r  {DIM}waiting for {name}... {elapsed:.0f}s{RESET}", end="", flush=True)
        time.sleep(5)
    print()
    fail(f"{name} not healthy after {timeout}s")
    return False


def wait_for_health(timeout: int) -> bool:
    header("Waiting for services")

    llama_port   = int(env_val("LLAMA_SERVER_PORT", "8080"))
    litellm_port = int(env_val("LITELLM_PORT", "4000"))
    langfuse_port= int(env_val("LANGFUSE_PORT", "3002"))

    checks = [
        ("llama-server",  f"http://localhost:{llama_port}/health",             {200}),
        ("LiteLLM proxy", f"http://localhost:{litellm_port}/health/readiness", {200}),
        ("Langfuse",      f"http://localhost:{langfuse_port}/api/public/health", {200, 401}),
    ]

    passed = True
    for name, url, codes in checks:
        if not wait_for_service(name, url, timeout, codes):
            passed = False

    if not passed:
        info("Tip: model loading can take 30-90s. Try: helix up --timeout 300")

    return passed

# ── Step 5: Quick smoke test ─────────────────────────────────────────────────

def smoke_test() -> bool:
    header("Smoke test")

    litellm_port = int(env_val("LITELLM_PORT", "4000"))
    master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")

    info("Sending test request through the stack...")
    url = f"http://localhost:{litellm_port}/v1/messages"
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 64,
        "tools": [{
            "name": "helix_ping",
            "description": "Returns pong",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }],
        "messages": [{"role": "user", "content": "Call helix_ping once."}],
    }
    headers = {
        "x-api-key": master_key,
        "anthropic-version": "2023-06-01",
    }

    status, resp = http_post_json(url, payload, headers=headers, timeout=120)

    if status == 200 and resp.get("content"):
        ok("End-to-end request succeeded")
        return True
    elif status == 0:
        fail("Could not reach LiteLLM — stack may still be starting")
        return False
    else:
        fail(f"Smoke test failed: HTTP {status}")
        return False

# ── Step 6: Launch Claude Code ───────────────────────────────────────────────

def launch_claude() -> None:
    litellm_port = int(env_val("LITELLM_PORT", "4000"))
    master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")

    print(f"\n{GREEN}{BOLD}  helix-core is ready.{RESET}\n")
    info("Launching Claude Code...\n")

    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://localhost:{litellm_port}"
    env["ANTHROPIC_AUTH_TOKEN"] = master_key

    claude_path = shutil.which("claude")
    if claude_path:
        os.execve(claude_path, ["claude"], env)
    else:
        fail("claude command not found in PATH")
        info(f"Set these and run claude manually:")
        print(f"    export ANTHROPIC_BASE_URL=http://localhost:{litellm_port}")
        print(f"    export ANTHROPIC_AUTH_TOKEN={master_key}")
        print(f"    claude\n")
        sys.exit(1)

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="helix-core zero-friction launcher")
    parser.add_argument("--no-launch", action="store_true",
                        help="Start stack but don't launch Claude Code")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Seconds to wait for each service (default: 180)")
    parser.add_argument("--skip-smoke-test", action="store_true",
                        help="Skip the end-to-end smoke test")
    args = parser.parse_args()

    print(f"\n{BOLD}helix — zero-friction local AI{RESET}")
    print(f"{DIM}Claude Code + local LLM — zero API cost, full data sovereignty{RESET}")

    # Fast path: if stack is already healthy and .env is good, go straight to claude
    if not needs_setup() and stack_is_healthy():
        ok("Stack is already running")
        if args.no_launch:
            print(f"\n{GREEN}{BOLD}  helix-core is ready.{RESET}\n")
            litellm_port = int(env_val("LITELLM_PORT", "4000"))
            master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")
            print(f"  {BOLD}Run Claude Code:{RESET}")
            print(f"    export ANTHROPIC_BASE_URL=http://localhost:{litellm_port}")
            print(f"    export ANTHROPIC_AUTH_TOKEN={master_key}")
            print(f"    claude\n")
            return 0
        launch_claude()
        return 0  # unreachable after exec, but keeps the type checker happy

    # Full flow
    if not check_prerequisites():
        print(f"\n{RED}Fix the above and re-run: helix{RESET}\n")
        return 1

    if not run_auto_setup():
        return 1

    if not start_compose():
        return 1

    if not wait_for_health(args.timeout):
        return 1

    if not args.skip_smoke_test:
        if not smoke_test():
            warn("Smoke test failed — stack may still be warming up")
            info("You can retry with: helix check")

    if args.no_launch:
        litellm_port = int(env_val("LITELLM_PORT", "4000"))
        master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")
        print(f"\n{GREEN}{BOLD}  helix-core is ready.{RESET}\n")
        print(f"  {BOLD}Run Claude Code:{RESET}")
        print(f"    export ANTHROPIC_BASE_URL=http://localhost:{litellm_port}")
        print(f"    export ANTHROPIC_AUTH_TOKEN={master_key}")
        print(f"    claude\n")
        return 0

    launch_claude()
    return 0


if __name__ == "__main__":
    sys.exit(main())
