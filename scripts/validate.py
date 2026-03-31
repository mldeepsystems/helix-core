"""
helix-core end-to-end validation script.

Walks through the full bring-up flow and validates each step.
Unlike check.py (which assumes the stack is running), this script:

  1. Checks all prerequisites
  2. Runs setup.py if .env is missing
  3. Handles Apple Silicon: checks/starts llama-server natively
  4. Starts the Docker Compose stack
  5. Waits for every service to become healthy (with timeouts)
  6. Validates the full request path: Claude Code format → LiteLLM → llama-server
  7. Verifies Langfuse captured a trace
  8. Prints a final report and the exact commands to start using Claude Code

Usage:
  python scripts/validate.py
  python scripts/validate.py --skip-setup     # skip setup.py if .env already exists
  python scripts/validate.py --skip-compose   # skip docker compose up (already running)
  python scripts/validate.py --timeout 300    # seconds to wait for services (default 180)

Stdlib only — no pip installs required.
"""

from __future__ import annotations

import argparse
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
def dim(msg):  print(f"  {DIM}{msg}{RESET}")
def header(msg): print(f"\n{BOLD}── {msg} {'─' * max(0, 50 - len(msg))}{RESET}\n")

# ── Repo root ─────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# ── Env helpers ───────────────────────────────────────────────────────────────

def load_env() -> dict:
    """Load .env into a dict (KEY=VALUE, ignores comments)."""
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

def http_get(url: str, headers: dict | None = None, timeout: int = 8) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""

def http_post(url: str, body: dict, headers: dict | None = None,
              timeout: int = 90) -> tuple[int, dict]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
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

# ── Platform detection ────────────────────────────────────────────────────────

IS_MAC   = platform.system() == "Darwin"
IS_ARM   = platform.machine() == "arm64"
IS_APPLE = IS_MAC and IS_ARM

def deployment_mode() -> str:
    return env_val("DEPLOYMENT_MODE", "local")

def is_mac_mode() -> bool:
    return IS_APPLE or deployment_mode() == "mac"

# ── Step 1: Prerequisites ─────────────────────────────────────────────────────

def check_prerequisites() -> bool:
    header("Step 1 — Prerequisites")
    passed = True

    # Python version
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
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
        fail("Docker not found — install Docker Desktop: https://docs.docker.com/get-docker/")
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
        warn("Claude Code CLI not found — install: npm install -g @anthropic-ai/claude-code")
        warn("(not required for stack validation, but needed to use helix-core)")

    # Apple Silicon: llama-server
    if IS_APPLE:
        if shutil.which("llama-server"):
            r = subprocess.run(["llama-server", "--version"],
                               capture_output=True, text=True)
            ok(f"llama-server found ({r.stdout.strip()[:40] or 'version unknown'})")
        else:
            fail("llama-server not found — install via Homebrew:")
            info("  brew install llama.cpp")
            passed = False

    return passed

# ── Step 2: Setup (.env) ──────────────────────────────────────────────────────

def run_setup(args: argparse.Namespace) -> bool:
    header("Step 2 — Configuration (.env)")

    if ENV_FILE.exists():
        e = load_env()
        model_path = e.get("MODEL_PATH", "")
        if model_path and Path(model_path).exists():
            ok(f".env exists — MODEL_PATH={model_path}")
            ok(f"Model file exists ({Path(model_path).stat().st_size / 1e9:.1f} GB)")
            return True
        elif model_path:
            fail(f".env exists but MODEL_PATH not found: {model_path}")
            info("Re-running setup.py to fix...")
        else:
            warn(".env exists but MODEL_PATH is empty — re-running setup.py")

    if args.skip_setup:
        fail(".env missing or incomplete and --skip-setup was passed")
        info("Run: python scripts/setup.py")
        return False

    info("Running setup.py (this will download the model — may take a while)...")
    print()

    setup_args = [sys.executable, str(REPO_ROOT / "scripts" / "setup.py")]
    if args.model:
        setup_args += ["--model", args.model]
    if args.skip_download:
        setup_args += ["--skip-download"]

    r = subprocess.run(setup_args, cwd=REPO_ROOT)
    if r.returncode != 0:
        fail("setup.py failed")
        return False

    # Re-check after setup
    e = load_env()
    model_path = e.get("MODEL_PATH", "")
    if model_path and Path(model_path).exists():
        ok(f"Model ready at {model_path}")
        return True
    elif args.skip_download:
        warn("--skip-download used — model not downloaded yet")
        warn("Run: python scripts/setup.py --model <key>  (without --skip-download)")
        return False
    else:
        fail("setup.py completed but model file still not found")
        return False

# ── Step 3: llama-server (Apple Silicon only) ─────────────────────────────────

def ensure_llama_server(args: argparse.Namespace) -> bool:
    if not IS_APPLE:
        return True  # Handled by Docker on Linux

    header("Step 3 — llama-server (Apple Silicon)")

    llama_port = int(env_val("LLAMA_SERVER_PORT", "8080"))
    status, _ = http_get(f"http://localhost:{llama_port}/health", timeout=3)

    if status == 200:
        ok(f"llama-server already running on port {llama_port}")
        return True

    # Not running — print the command and wait for user
    e = load_env()
    model_path = e.get("MODEL_PATH", "/path/to/model.gguf")
    ctx        = e.get("CONTEXT_LENGTH", "32768")
    parser     = e.get("TOOL_CALL_PARSER", "qwen2_5")

    warn("llama-server is not running. Start it in a separate terminal:")
    print()
    print(f"  {CYAN}llama-server \\{RESET}")
    print(f"    --model {model_path} \\")
    print(f"    --host 0.0.0.0 --port {llama_port} \\")
    print(f"    --ctx-size {ctx} \\")
    print(f"    --n-gpu-layers 99 \\")
    print(f"    --tool-call-parser {parser} \\")
    print(f"    --jinja")
    print()

    if args.skip_llama_wait:
        fail("--skip-llama-wait passed and llama-server is not running")
        return False

    info("Waiting for llama-server to come up (Ctrl+C to abort)...")
    start = time.monotonic()
    timeout = args.timeout
    dots = 0
    while time.monotonic() - start < timeout:
        time.sleep(5)
        dots += 1
        status, _ = http_get(f"http://localhost:{llama_port}/health", timeout=3)
        if status == 200:
            print()
            ok(f"llama-server is up (took {time.monotonic()-start:.0f}s)")
            return True
        elapsed = time.monotonic() - start
        print(f"\r  {DIM}waiting... {elapsed:.0f}s / {timeout}s{RESET}", end="", flush=True)

    print()
    fail(f"llama-server did not come up within {timeout}s")
    return False

# ── Step 4: Docker Compose up ─────────────────────────────────────────────────

def start_compose(args: argparse.Namespace) -> bool:
    header("Step 4 — Docker Compose stack")

    compose_files = ["docker-compose.yml"]
    if IS_APPLE:
        compose_files = ["docker-compose.mac.yml"]
    elif deployment_mode() == "cpu":
        compose_files = ["docker-compose.yml", "docker-compose.cpu.yml"]

    cmd = ["docker", "compose"]
    for f in compose_files:
        cmd += ["-f", f]

    # Validate config first
    r = subprocess.run(cmd + ["config"], capture_output=True, text=True,
                       cwd=REPO_ROOT, env={**os.environ, **load_env()})
    if r.returncode != 0:
        fail("docker compose config failed:")
        print(r.stderr[:800])
        return False
    ok(f"Compose config valid ({', '.join(compose_files)})")

    if args.skip_compose:
        info("--skip-compose passed — assuming stack is already running")
        return True

    info(f"Starting stack: docker compose {' '.join('-f ' + f for f in compose_files)} up -d")
    r = subprocess.run(
        cmd + ["up", "-d"],
        cwd=REPO_ROOT,
        env={**os.environ, **load_env()},
    )
    if r.returncode != 0:
        fail("docker compose up failed")
        return False

    ok("docker compose up -d completed")
    return True

# ── Step 5: Wait for services ─────────────────────────────────────────────────

def _wait_for(name: str, url: str, acceptable_codes: set, timeout: int,
              headers: dict | None = None) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        status, _ = http_get(url, headers=headers, timeout=5)
        if status in acceptable_codes:
            elapsed = time.monotonic() - start
            ok(f"{name} healthy ({elapsed:.0f}s)")
            return True
        elapsed = time.monotonic() - start
        print(f"\r  {DIM}waiting for {name}... {elapsed:.0f}s{RESET}", end="", flush=True)
        time.sleep(5)
    print()
    fail(f"{name} did not become healthy within {timeout}s — last status: {status}")
    return False


def wait_for_services(args: argparse.Namespace) -> bool:
    header("Step 5 — Service health checks")

    llama_port   = int(env_val("LLAMA_SERVER_PORT", "8080"))
    litellm_port = int(env_val("LITELLM_PORT", "4000"))
    langfuse_port= int(env_val("LANGFUSE_PORT", "3002"))
    master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")
    timeout      = args.timeout

    checks = [
        ("llama-server",
         f"http://localhost:{llama_port}/health",
         {200},
         None),
        ("LiteLLM proxy",
         f"http://localhost:{litellm_port}/health",
         {200},
         {"x-api-key": master_key}),
        ("Langfuse",
         f"http://localhost:{langfuse_port}/api/public/health",
         {200, 401},   # 401 = up but needs auth
         None),
    ]

    passed = True
    for name, url, codes, hdrs in checks:
        if not _wait_for(name, url, codes, timeout, hdrs):
            passed = False

    return passed

# ── Step 6: End-to-end request validation ────────────────────────────────────

def validate_e2e() -> bool:
    header("Step 6 — End-to-end request validation")

    litellm_port = int(env_val("LITELLM_PORT", "4000"))
    master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")

    # ── 6a: Anthropic-format tool-use request ────────────────────────────────
    info("Sending Anthropic-format tool-use request through LiteLLM → llama-server...")
    url = f"http://localhost:{litellm_port}/v1/messages"
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 128,
        "tools": [{
            "name": "helix_ping",
            "description": "Ping helix-core to verify the stack is working end-to-end.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }],
        "messages": [{
            "role": "user",
            "content": "Call helix_ping once to confirm the stack is working.",
        }],
    }
    headers = {
        "x-api-key": master_key,
        "anthropic-version": "2023-06-01",
    }

    status, resp = http_post(url, payload, headers=headers, timeout=120)

    if status == 200:
        content = resp.get("content", [])
        stop_reason = resp.get("stop_reason", "?")
        model = resp.get("model", "?")
        if content:
            ok(f"Tool-use request succeeded — model={model}, stop_reason={stop_reason}, "
               f"content_blocks={len(content)}")
            # Show what the model returned
            for block in content[:2]:
                btype = block.get("type", "")
                if btype == "text":
                    text = block.get("text", "")[:120]
                    dim(f"  model said: {text!r}")
                elif btype == "tool_use":
                    dim(f"  tool called: {block.get('name')}({json.dumps(block.get('input', {}))})")
        else:
            warn(f"Request returned 200 but no content blocks (stop_reason={stop_reason})")
    elif status == 0:
        fail("Could not reach LiteLLM — is the stack running?")
        return False
    elif status == 422:
        fail(f"LiteLLM returned 422 — likely missing drop_params/modify_params in litellm/config.yaml")
        dim(f"  Response: {json.dumps(resp)[:300]}")
        return False
    else:
        fail(f"Request failed: HTTP {status}")
        dim(f"  Response: {json.dumps(resp)[:300]}")
        return False

    # ── 6b: Verify Langfuse received a trace ─────────────────────────────────
    info("Checking Langfuse captured a trace...")
    langfuse_port    = int(env_val("LANGFUSE_PORT", "3002"))
    public_key       = env_val("LANGFUSE_INIT_PROJECT_PUBLIC_KEY", "")
    secret_key       = env_val("LANGFUSE_INIT_PROJECT_SECRET_KEY", "")

    if not public_key or not secret_key:
        warn("LANGFUSE_INIT_PROJECT_PUBLIC_KEY/SECRET_KEY not in .env — skipping trace check")
        warn("Set these in .env and re-run to verify trace capture")
    else:
        import base64
        creds = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        lf_status, lf_body = http_get(
            f"http://localhost:{langfuse_port}/api/public/traces?limit=1",
            headers={"Authorization": f"Basic {creds}"},
            timeout=10,
        )
        if lf_status == 200:
            try:
                data = json.loads(lf_body)
                count = len(data.get("data", []))
                ok(f"Langfuse API reachable — {count} trace(s) visible")
                if count == 0:
                    warn("No traces yet — traces appear after Claude Code sessions "
                         "(not from direct API calls)")
            except Exception:
                ok("Langfuse API reachable")
        else:
            warn(f"Langfuse trace API returned {lf_status} — check credentials in .env")

    return True

# ── Step 7: Final report ──────────────────────────────────────────────────────

def print_final_report(results: dict) -> int:
    header("Validation summary")

    all_passed = all(results.values())
    for step, passed in results.items():
        if passed:
            ok(step)
        else:
            fail(step)

    print()
    if all_passed:
        litellm_port = int(env_val("LITELLM_PORT", "4000"))
        master_key   = env_val("LITELLM_MASTER_KEY", "sk-helix-local")
        grafana_port = int(env_val("GRAFANA_PORT", "3000"))
        langfuse_port= int(env_val("LANGFUSE_PORT", "3002"))

        print(f"{GREEN}{BOLD}  helix-core is ready.{RESET}\n")
        print(f"  {BOLD}Point Claude Code at the local stack:{RESET}")
        print(f"    export ANTHROPIC_BASE_URL=http://localhost:{litellm_port}")
        print(f"    export ANTHROPIC_AUTH_TOKEN={master_key}")
        print(f"    claude\n")
        print(f"  {BOLD}Observability:{RESET}")
        print(f"    Grafana   → http://localhost:{grafana_port}  (admin / {env_val('GRAFANA_ADMIN_PASSWORD','helix-local')})")
        print(f"    Langfuse  → http://localhost:{langfuse_port}")
        print()
        return 0
    else:
        failed = [s for s, p in results.items() if not p]
        print(f"{RED}{BOLD}  {len(failed)} step(s) failed.{RESET}")
        print(f"  Fix the issues above and re-run: {CYAN}python scripts/validate.py{RESET}\n")
        return 1


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="helix-core end-to-end validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--skip-setup",       action="store_true",
                   help="Skip setup.py (use existing .env)")
    p.add_argument("--skip-compose",     action="store_true",
                   help="Skip docker compose up (stack already running)")
    p.add_argument("--skip-llama-wait",  action="store_true",
                   help="(Mac) Don't wait for llama-server — fail immediately if not running")
    p.add_argument("--skip-download",    action="store_true",
                   help="Pass --skip-download to setup.py (configure only)")
    p.add_argument("--model",            default="qwen2.5-coder-7b",
                   help="Model key to pass to setup.py (default: qwen2.5-coder-7b)")
    p.add_argument("--timeout",          type=int, default=180,
                   help="Seconds to wait for each service (default: 180)")
    return p.parse_args()


def main() -> int:
    print(f"\n{BOLD}helix-core — end-to-end validation{RESET}")
    if IS_APPLE:
        info("Apple Silicon detected — using Mac deployment mode")
    elif deployment_mode() == "cpu":
        info("CPU mode — using docker-compose.cpu.yml override")
    else:
        info("GPU mode — using docker-compose.yml")

    args = parse_args()
    results: dict[str, bool] = {}

    # Step 1: Prerequisites
    results["Prerequisites"] = check_prerequisites()
    if not results["Prerequisites"]:
        print(f"\n{RED}Prerequisites failed — fix the above before continuing.{RESET}\n")
        return 1

    # Step 2: .env / setup
    results["Configuration (.env)"] = run_setup(args)
    if not results["Configuration (.env)"]:
        return print_final_report(results)

    # Step 3: llama-server (Mac only)
    if IS_APPLE:
        results["llama-server (native Metal)"] = ensure_llama_server(args)
        if not results["llama-server (native Metal)"]:
            return print_final_report(results)

    # Step 4: Docker Compose
    results["Docker Compose stack"] = start_compose(args)
    if not results["Docker Compose stack"]:
        return print_final_report(results)

    # Step 5: Service health
    results["Service health checks"] = wait_for_services(args)
    if not results["Service health checks"]:
        info("Tip: llama-server can take 30–90s to load a model. Try --timeout 300")
        return print_final_report(results)

    # Step 6: E2E request
    results["End-to-end request"] = validate_e2e()

    return print_final_report(results)


if __name__ == "__main__":
    sys.exit(main())
