#!/usr/bin/env python3
"""
helix-core setup script.

Detects hardware, recommends a model, downloads it, writes configuration,
and validates the stack is ready to run.

Usage:
    python scripts/setup.py
    python scripts/setup.py --model qwen2.5-coder-32b  # skip interactive selection
    python scripts/setup.py --mode cloud               # skip local hardware detection
    python scripts/setup.py --skip-download            # configure only, no model download
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
MODELS_DIR = ROOT / "models"
DOWNLOADS_DIR = ROOT / "models" / "downloads"

# ─── ANSI colours (no external deps) ────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def err(msg: str) -> None:
    print(f"  {RED}✗{RESET}  {msg}")


def info(msg: str) -> None:
    print(f"  {CYAN}→{RESET}  {msg}")


def header(msg: str) -> None:
    print(f"\n{BOLD}{msg}{RESET}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {BOLD}?{RESET}  {prompt}{suffix}: ").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)


def confirm(prompt: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    val = ask(prompt + suffix, "y" if default else "n").lower()
    return val in ("y", "yes", "")


# ─── MODEL REGISTRY ──────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    key: str
    display_name: str
    vram_gb: int               # minimum VRAM required (0 = CPU only)
    ram_gb: int                # minimum RAM for CPU offload
    quant: str
    context_length: int
    hf_repo: str
    hf_filename: str
    size_gb: float             # approximate download size
    config_file: str           # path under models/

MODELS: list[ModelConfig] = [
    ModelConfig(
        key="qwen2.5-coder-7b",
        display_name="Qwen2.5-Coder 7B (Q4_K_M)",
        vram_gb=8,
        ram_gb=12,
        quant="Q4_K_M",
        context_length=32768,
        hf_repo="bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        hf_filename="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        size_gb=4.7,
        config_file="qwen2.5-coder-7b.yaml",
    ),
    ModelConfig(
        key="qwen2.5-coder-14b",
        display_name="Qwen2.5-Coder 14B (Q4_K_M)",
        vram_gb=16,
        ram_gb=20,
        quant="Q4_K_M",
        context_length=32768,
        hf_repo="bartowski/Qwen2.5-Coder-14B-Instruct-GGUF",
        hf_filename="Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
        size_gb=9.0,
        config_file="qwen2.5-coder-14b.yaml",
    ),
    ModelConfig(
        key="qwen2.5-coder-32b",
        display_name="Qwen2.5-Coder 32B (Q4_K_M)  ← recommended for 24GB VRAM",
        vram_gb=24,
        ram_gb=32,
        quant="Q4_K_M",
        context_length=32768,
        hf_repo="bartowski/Qwen2.5-Coder-32B-Instruct-GGUF",
        hf_filename="Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        size_gb=19.8,
        config_file="qwen2.5-coder-32b.yaml",
    ),
    ModelConfig(
        key="deepseek-r1-70b",
        display_name="DeepSeek-R1 70B (Q4_K_M)  ← reasoning; needs 48GB VRAM",
        vram_gb=48,
        ram_gb=64,
        quant="Q4_K_M",
        context_length=65536,
        hf_repo="bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF",
        hf_filename="DeepSeek-R1-Distill-Llama-70B-Q4_K_M.gguf",
        size_gb=42.5,
        config_file="deepseek-r1-70b.yaml",
    ),
    ModelConfig(
        key="llama-3.3-70b",
        display_name="Llama 3.3 70B (Q4_K_M)  ← general; needs 48GB VRAM",
        vram_gb=48,
        ram_gb=64,
        quant="Q4_K_M",
        context_length=131072,
        hf_repo="bartowski/Llama-3.3-70B-Instruct-GGUF",
        hf_filename="Llama-3.3-70B-Instruct-Q4_K_M.gguf",
        size_gb=42.5,
        config_file="llama-3.3-70b.yaml",
    ),
    ModelConfig(
        key="qwen2.5-coder-7b-cpu",
        display_name="Qwen2.5-Coder 7B (Q4_K_M, CPU offload)  ← no GPU required",
        vram_gb=0,
        ram_gb=12,
        quant="Q4_K_M",
        context_length=16384,
        hf_repo="bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        hf_filename="Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        size_gb=4.7,
        config_file="qwen2.5-coder-7b-cpu.yaml",
    ),
]

MODEL_BY_KEY = {m.key: m for m in MODELS}


# ─── HARDWARE DETECTION ──────────────────────────────────────────────────────

@dataclass
class Hardware:
    vram_gb: int
    ram_gb: int
    has_gpu: bool
    gpu_name: str
    os: str
    docker_ok: bool
    nvidia_toolkit_ok: bool


def detect_hardware() -> Hardware:
    """Probe the current machine for GPU, VRAM, RAM, Docker."""
    vram_gb = 0
    has_gpu = False
    gpu_name = "none"

    # NVIDIA GPU via nvidia-smi
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip().splitlines()
            if out:
                first = out[0].split(",")
                gpu_name = first[0].strip()
                vram_gb = int(first[1].strip()) // 1024
                has_gpu = True
        except Exception:
            pass

    # Apple Silicon — use total unified memory via sysctl, NOT system_profiler
    # system_profiler SPDisplaysDataType returns display VRAM (~1GB), not usable
    # inference memory. On a 36GB M3 Pro it would report 1GB. sysctl hw.memsize
    # returns the full unified memory pool, which llama-server can use entirely.
    if not has_gpu and platform.system() == "Darwin":
        try:
            mem_bytes = int(
                subprocess.check_output(["sysctl", "-n", "hw.memsize"],
                                        stderr=subprocess.DEVNULL, text=True).strip()
            )
            vram_gb = mem_bytes // (1024 ** 3)
            has_gpu = vram_gb > 0
            gpu_name = "Apple Silicon (unified memory)"
        except Exception:
            pass

    # RAM
    ram_gb = 0
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_gb = int(line.split()[1]) // (1024 * 1024)
                        break
        elif platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            ram_gb = int(out) // (1024 ** 3)
    except Exception:
        pass

    docker_ok = shutil.which("docker") is not None
    nvidia_toolkit_ok = False
    if docker_ok and has_gpu:
        try:
            subprocess.check_output(
                ["docker", "run", "--rm", "--gpus", "all", "nvidia/cuda:12.0-base-ubuntu22.04", "nvidia-smi"],
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            nvidia_toolkit_ok = True
        except Exception:
            pass

    return Hardware(
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        has_gpu=has_gpu,
        gpu_name=gpu_name,
        os=platform.system(),
        docker_ok=docker_ok,
        nvidia_toolkit_ok=nvidia_toolkit_ok,
    )


def recommend_model(hw: Hardware) -> ModelConfig:
    """Return the best model for the detected hardware."""
    if hw.vram_gb >= 48:
        return MODEL_BY_KEY["deepseek-r1-70b"]    # full reasoning capability at 48GB+
    elif hw.vram_gb >= 24:
        return MODEL_BY_KEY["qwen2.5-coder-32b"]  # reference config; GPT-4 level on coding
    elif hw.vram_gb >= 16:
        return MODEL_BY_KEY["qwen2.5-coder-14b"]
    elif hw.vram_gb >= 8:
        return MODEL_BY_KEY["qwen2.5-coder-7b"]
    else:
        return MODEL_BY_KEY["qwen2.5-coder-7b-cpu"]


# ─── MODEL DOWNLOAD ──────────────────────────────────────────────────────────

def download_model(model: ModelConfig) -> Path:
    """Download model GGUF file. Returns path to the downloaded file."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS_DIR / model.hf_filename

    if dest.exists():
        ok(f"Model already downloaded: {dest.name}")
        return dest

    # Try huggingface_hub first (cleaner, resumes partial downloads)
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
        info(f"Downloading via huggingface_hub (~{model.size_gb:.1f} GB) ...")
        path = hf_hub_download(
            repo_id=model.hf_repo,
            filename=model.hf_filename,
            local_dir=str(DOWNLOADS_DIR),
            resume_download=True,
        )
        ok(f"Downloaded to {path}")
        return Path(path)
    except ImportError:
        pass

    # Fallback: direct URL download with progress
    url = f"https://huggingface.co/{model.hf_repo}/resolve/main/{model.hf_filename}"
    info(f"Downloading from HuggingFace (~{model.size_gb:.1f} GB) ...")
    info(f"URL: {url}")
    info("Tip: install huggingface_hub for resumable downloads: pip install huggingface_hub")

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(downloaded / total_size * 100, 100)
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        mb = downloaded / (1024 ** 2)
        total_mb = total_size / (1024 ** 2)
        print(f"\r  [{bar}] {pct:.1f}%  {mb:.0f}/{total_mb:.0f} MB", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print()
    ok(f"Downloaded to {dest}")
    return dest


# ─── CONFIGURATION WRITING ───────────────────────────────────────────────────

def _generate_secret(hex: bool = False) -> str:
    """Generate a cryptographic secret via openssl rand."""
    flag = "-hex" if hex else "-base64"
    length = "32"
    try:
        return subprocess.check_output(
            ["openssl", "rand", flag, length], text=True
        ).strip()
    except Exception:
        # Fallback: use Python secrets module
        import secrets as _secrets
        return _secrets.token_hex(32) if hex else _secrets.token_urlsafe(32)


def write_env(model: ModelConfig, dest: Path, mode: str) -> None:
    """Write .env from .env.example with model-specific values filled in."""
    # If .env already exists, preserve existing Langfuse secrets — never rotate them
    existing: dict[str, str] = {}
    if dest.exists():
        for line in dest.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    langfuse_nextauth = existing.get("LANGFUSE_NEXTAUTH_SECRET") or _generate_secret()
    langfuse_salt     = existing.get("LANGFUSE_SALT")            or _generate_secret()
    langfuse_enc_key  = existing.get("LANGFUSE_ENCRYPTION_KEY")  or _generate_secret(hex=True)

    if ENV_EXAMPLE.exists():
        template = ENV_EXAMPLE.read_text()
    else:
        template = _default_env_template()

    replacements = {
        "MODEL_PATH": str(DOWNLOADS_DIR / model.hf_filename),
        "MODEL_KEY": model.key,
        "CONTEXT_LENGTH": str(model.context_length),
        "DEPLOYMENT_MODE": mode,
        "LLAMA_SERVER_PORT": "8080",
        "LITELLM_PORT": "4000",
        "LANGFUSE_PORT": "3002",
        "LANGFUSE_NEXTAUTH_SECRET": langfuse_nextauth,
        "LANGFUSE_SALT": langfuse_salt,
        "LANGFUSE_ENCRYPTION_KEY": langfuse_enc_key,
        "PROMETHEUS_PORT": "9090",
        "GRAFANA_PORT": "3000",
        "AGENTDX_ENABLED": "true",
        "AGENTDX_POLL_INTERVAL": "30",
    }

    lines = []
    for line in template.splitlines():
        for key, val in replacements.items():
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                line = f"{key}={val}"
                break
        lines.append(line)

    dest.write_text("\n".join(lines) + "\n")
    ok(f"Written {dest}")


def _default_env_template() -> str:
    return """\
# helix-core configuration
# Generated by scripts/setup.py — edit as needed

# Model
MODEL_PATH=
MODEL_KEY=
CONTEXT_LENGTH=32768
DEPLOYMENT_MODE=local

# Ports
LLAMA_SERVER_PORT=8080
LANGFUSE_PORT=3002
PROMETHEUS_PORT=9090
GRAFANA_PORT=3000

# AgentDx bridge
AGENTDX_ENABLED=true
AGENTDX_POLL_INTERVAL=30

# Langfuse (set your keys if using cloud Langfuse)
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=

# Claude Code
# After setup, run: export ANTHROPIC_BASE_URL=http://localhost:8080
"""


# ─── VALIDATION ──────────────────────────────────────────────────────────────

def check_claude_code() -> bool:
    """Check if Claude Code CLI is installed. Returns True if found."""
    if shutil.which("claude"):
        version = ""
        try:
            version = subprocess.check_output(
                ["claude", "--version"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            pass
        ok(f"Claude Code installed{(' (' + version + ')') if version else ''}")
        return True
    else:
        err("Claude Code not found")
        info("Install via npm:  npm install -g @anthropic-ai/claude-code")
        info("Requires Node.js 18+. Install Node: https://nodejs.org")
        info("After installing, re-run this setup script.")
        return False


def validate_prerequisites(hw: Hardware, mode: str) -> bool:
    """Check all prerequisites and print status. Returns True if OK to proceed."""
    header("Checking prerequisites")
    all_ok = True

    # Claude Code
    if not check_claude_code():
        all_ok = False

    # Docker
    if hw.docker_ok:
        ok("Docker installed")
    else:
        err("Docker not found — install Docker Desktop or Docker Engine")
        info("https://docs.docker.com/get-docker/")
        all_ok = False

    # Docker Compose
    try:
        subprocess.check_output(["docker", "compose", "version"], stderr=subprocess.DEVNULL)
        ok("Docker Compose available")
    except Exception:
        err("Docker Compose not found — update Docker to a recent version")
        all_ok = False

    # NVIDIA Container Toolkit (GPU mode only)
    if mode == "local" and hw.has_gpu and not hw.nvidia_toolkit_ok:
        warn("NVIDIA Container Toolkit not detected")
        info("Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html")
        warn("Continuing — will use CPU offload if GPU passthrough fails")

    # Python version
    if sys.version_info >= (3, 10):
        ok(f"Python {sys.version_info.major}.{sys.version_info.minor}")
    else:
        err(f"Python 3.10+ required (found {sys.version_info.major}.{sys.version_info.minor})")
        all_ok = False

    return all_ok


# ─── MAIN FLOW ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="helix-core setup")
    parser.add_argument("--model", help="Model key to use (skip interactive selection)")
    parser.add_argument("--mode", choices=["local", "cpu", "cloud"], help="Deployment mode")
    parser.add_argument("--skip-download", action="store_true", help="Skip model download")
    args = parser.parse_args()

    print(f"\n{BOLD}helix-core setup{RESET}")
    print(f"{DIM}Claude Code + local LLM — zero API cost, full data sovereignty{RESET}\n")

    # ── Step 1: Detect hardware ──────────────────────────────────────────────
    header("Detecting hardware")
    hw = detect_hardware()

    if hw.has_gpu:
        ok(f"GPU: {hw.gpu_name} ({hw.vram_gb}GB VRAM)")
    else:
        warn("No GPU detected — will use CPU offload")

    if hw.ram_gb:
        ok(f"RAM: {hw.ram_gb}GB")
    else:
        warn("Could not detect RAM")

    ok(f"OS: {hw.os}")

    # ── Step 2: Deployment mode ──────────────────────────────────────────────
    header("Deployment mode")

    if args.mode:
        mode = args.mode
    else:
        print(f"\n  {BOLD}1{RESET}  Local GPU       — model runs on your machine")
        print(f"  {BOLD}2{RESET}  CPU offload     — no GPU required (slower)")
        print(f"  {BOLD}3{RESET}  Cloud GPU       — run helix cloud init after setup")
        choice = ask("Select mode", "1" if hw.has_gpu else "2")
        mode = {"1": "local", "2": "cpu", "3": "cloud"}.get(choice, "local")

    ok(f"Mode: {mode}")

    # ── Step 3: Prerequisites ────────────────────────────────────────────────
    if not validate_prerequisites(hw, mode):
        print(f"\n{RED}Fix the above issues and re-run setup.{RESET}\n")
        sys.exit(1)

    # ── Step 4: Model selection ──────────────────────────────────────────────
    if mode != "cloud":
        header("Model selection")

        if args.model and args.model in MODEL_BY_KEY:
            selected = MODEL_BY_KEY[args.model]
        else:
            recommended = recommend_model(hw)
            info(f"Recommended for your hardware: {BOLD}{recommended.display_name}{RESET}")
            print()

            for i, m in enumerate(MODELS, 1):
                marker = " ←" if m.key == recommended.key else ""
                accessible = "✓" if (m.vram_gb == 0 or hw.vram_gb >= m.vram_gb) else "✗"
                print(f"  {BOLD}{i}{RESET}  [{accessible}] {m.display_name}  {DIM}~{m.size_gb:.1f}GB download{RESET}{marker}")

            choice = ask(f"\n  Select model", str(MODELS.index(recommended) + 1))
            try:
                selected = MODELS[int(choice) - 1]
            except (ValueError, IndexError):
                selected = recommended

        ok(f"Selected: {selected.display_name}")

        # ── Step 5: Download model ───────────────────────────────────────────
        if not args.skip_download:
            header("Model download")
            model_path = download_model(selected)
        else:
            model_path = DOWNLOADS_DIR / selected.hf_filename
            info("Skipping download (--skip-download)")

        # ── Step 6: Write config ─────────────────────────────────────────────
        header("Writing configuration")
        write_env(selected, ENV_FILE, mode)

    # ── Step 7: Summary ──────────────────────────────────────────────────────
    header("Setup complete")

    print(f"""
  Start the stack:

    {BOLD}docker compose up{RESET}

  Point Claude Code at the LiteLLM proxy:

    {BOLD}export ANTHROPIC_BASE_URL=http://localhost:4000{RESET}
    {BOLD}export ANTHROPIC_AUTH_TOKEN=sk-helix-local{RESET}
    {BOLD}claude{RESET}

  Verify everything is working:

    {BOLD}python scripts/check.py{RESET}

  Dashboards (once running):
    Grafana:   http://localhost:3000  {DIM}(GPU metrics + AgentDx pathology panel){RESET}
    Langfuse:  http://localhost:3002  {DIM}(LLM traces){RESET}
""")

    if mode == "cloud":
        info("For cloud GPU setup, run:")
        print(f"\n    {BOLD}python scripts/cloud_init.py{RESET}\n")


if __name__ == "__main__":
    main()
