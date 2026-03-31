"""
Stage 2 validation tests: Docker Compose structural correctness.

These tests validate compose file structure and configuration without
requiring Docker or a running stack. Runtime gates (health checks,
actual LiteLLM requests) are performed manually and documented in the PR.

Run:
  pytest tests/test_stage2_compose.py -v
"""

from __future__ import annotations

import subprocess
import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
COMPOSE_CPU = REPO_ROOT / "docker-compose.cpu.yml"
COMPOSE_MAC = REPO_ROOT / "docker-compose.mac.yml"
LITELLM_CONFIG = REPO_ROOT / "litellm" / "config.yaml"
LITELLM_MAC_CONFIG = REPO_ROOT / "litellm" / "config.mac.yaml"

# Minimal .env for docker compose config validation
MINIMAL_ENV = {
    "MODEL_PATH": "/tmp/model.gguf",
    "CONTEXT_LENGTH": "32768",
    "N_GPU_LAYERS": "99",
    "TOOL_CALL_PARSER": "qwen2_5",
    "LITELLM_PORT": "4000",
    "LITELLM_MASTER_KEY": "sk-helix-local",
    "LLAMA_SERVER_PORT": "8080",
    "LANGFUSE_PORT": "3002",
    "LANGFUSE_NEXTAUTH_SECRET": "test-secret-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "LANGFUSE_SALT": "test-salt-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "LANGFUSE_ENCRYPTION_KEY": "a" * 64,
    "LANGFUSE_DB_PASSWORD": "langfuse-local",
    "LANGFUSE_INIT_USER_EMAIL": "admin@helix.local",
    "LANGFUSE_INIT_USER_PASSWORD": "test-password",
    "LANGFUSE_INIT_PROJECT_NAME": "helix-core",
    "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": "pk-helix-local-1234",
    "LANGFUSE_INIT_PROJECT_SECRET_KEY": "sk-lf-helix-local-1234",
    "PROMETHEUS_PORT": "9090",
    "GRAFANA_PORT": "3000",
    "GRAFANA_ADMIN_PASSWORD": "helix-local",
    "AGENTDX_POLL_INTERVAL": "30",
}


def _docker_compose_config(*extra_files: str) -> tuple[bool, str]:
    """Run docker compose config and return (success, output)."""
    cmd = ["docker", "compose"]
    for f in extra_files:
        cmd += ["-f", f]
    cmd += ["config"]

    env = {**os.environ, **MINIMAL_ENV}
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode == 0, result.stdout + result.stderr


def _load_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


# ── File existence ────────────────────────────────────────────────────────────

def test_compose_gpu_exists():
    assert COMPOSE_FILE.exists()

def test_compose_cpu_exists():
    assert COMPOSE_CPU.exists()

def test_compose_mac_exists():
    assert COMPOSE_MAC.exists()

def test_litellm_mac_config_exists():
    assert LITELLM_MAC_CONFIG.exists()


# ── YAML validity ─────────────────────────────────────────────────────────────

def test_compose_gpu_parses():
    data = _load_compose(COMPOSE_FILE)
    assert isinstance(data.get("services"), dict)

def test_compose_cpu_parses():
    data = _load_compose(COMPOSE_CPU)
    assert isinstance(data.get("services"), dict)

def test_compose_mac_parses():
    data = _load_compose(COMPOSE_MAC)
    assert isinstance(data.get("services"), dict)


# ── docker compose config (structural validation) ─────────────────────────────

def test_docker_compose_config_gpu():
    """docker compose config must exit 0 for the GPU stack."""
    ok, out = _docker_compose_config("docker-compose.yml")
    assert ok, f"docker compose config failed:\n{out}"

def test_docker_compose_config_cpu():
    """docker compose config must exit 0 for the CPU override."""
    ok, out = _docker_compose_config("docker-compose.yml", "docker-compose.cpu.yml")
    assert ok, f"docker compose config (CPU) failed:\n{out}"

def test_docker_compose_config_mac():
    """docker compose config must exit 0 for the Mac variant."""
    ok, out = _docker_compose_config("docker-compose.mac.yml")
    assert ok, f"docker compose config (Mac) failed:\n{out}"


# ── Required services ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("service", [
    "llama-server", "litellm", "postgres", "langfuse",
    "prometheus", "grafana",
])
def test_gpu_compose_has_service(service: str):
    data = _load_compose(COMPOSE_FILE)
    assert service in data["services"], f"docker-compose.yml missing service: {service}"

@pytest.mark.parametrize("service", [
    "litellm", "postgres", "langfuse", "prometheus", "grafana",
])
def test_mac_compose_has_service(service: str):
    data = _load_compose(COMPOSE_MAC)
    assert service in data["services"], f"docker-compose.mac.yml missing service: {service}"

def test_mac_compose_has_no_llama_server():
    """Mac variant: llama-server runs natively, must not be in Docker Compose."""
    data = _load_compose(COMPOSE_MAC)
    assert "llama-server" not in data["services"], (
        "docker-compose.mac.yml must not define llama-server (runs natively on Metal)"
    )

def test_agentdx_bridge_has_agentdx_profile():
    """agentdx-bridge must be on the 'agentdx' profile so it's opt-in."""
    data = _load_compose(COMPOSE_FILE)
    bridge = data["services"].get("agentdx-bridge", {})
    profiles = bridge.get("profiles", [])
    assert "agentdx" in profiles, (
        "agentdx-bridge must have profiles: [agentdx] to be opt-in"
    )


# ── llama-server flags (spike-validated) ─────────────────────────────────────

def test_llama_server_has_jinja_flag():
    """--jinja is required for tool calling — missing it silently breaks tools."""
    data = _load_compose(COMPOSE_FILE)
    command = str(data["services"]["llama-server"].get("command", ""))
    assert "--jinja" in command, "llama-server command must include --jinja flag"

def test_llama_server_has_host_flag():
    data = _load_compose(COMPOSE_FILE)
    command = str(data["services"]["llama-server"].get("command", ""))
    assert "--host" in command and "0.0.0.0" in command

def test_llama_server_has_tool_call_parser():
    data = _load_compose(COMPOSE_FILE)
    command = str(data["services"]["llama-server"].get("command", ""))
    assert "--tool-call-parser" in command

def test_llama_server_has_ctx_size():
    data = _load_compose(COMPOSE_FILE)
    command = str(data["services"]["llama-server"].get("command", ""))
    assert "--ctx-size" in command

def test_llama_server_restart_always():
    data = _load_compose(COMPOSE_FILE)
    restart = data["services"]["llama-server"].get("restart")
    assert restart == "always"

def test_llama_server_has_gpu_reservation():
    """GPU passthrough must be configured for the main compose file."""
    data = _load_compose(COMPOSE_FILE)
    deploy = data["services"]["llama-server"].get("deploy", {})
    devices = (
        deploy.get("resources", {})
        .get("reservations", {})
        .get("devices", [])
    )
    assert len(devices) > 0, "llama-server must have GPU device reservation"
    caps = devices[0].get("capabilities", [])
    assert "gpu" in caps

def test_cpu_override_removes_gpu():
    """CPU override must clear the deploy block (no GPU reservation)."""
    data = _load_compose(COMPOSE_CPU)
    deploy = data["services"]["llama-server"].get("deploy", {})
    # deploy: resources: {} means no GPU reservation
    resources = deploy.get("resources", {})
    assert resources == {} or not resources.get("reservations"), (
        "docker-compose.cpu.yml must remove GPU reservation"
    )

def test_cpu_override_has_zero_n_gpu_layers():
    """CPU override command must set --n-gpu-layers 0."""
    data = _load_compose(COMPOSE_CPU)
    command = str(data["services"]["llama-server"].get("command", ""))
    assert "--n-gpu-layers 0" in command or "--n-gpu-layers" in command


# ── Ports ─────────────────────────────────────────────────────────────────────

def test_langfuse_port_not_3000():
    """Langfuse must not use port 3000 — that's Grafana. Use 3002."""
    data = _load_compose(COMPOSE_FILE)
    ports = data["services"]["langfuse"].get("ports", [])
    for p in ports:
        host_port = str(p).split(":")[0].strip('"').strip("'")
        assert host_port != "3000", (
            "Langfuse must not use host port 3000 (conflicts with Grafana)"
        )

def test_grafana_on_port_3000():
    data = _load_compose(COMPOSE_FILE)
    ports = data["services"]["grafana"].get("ports", [])
    port_strings = [str(p) for p in ports]
    assert any("3000" in p for p in port_strings)

def test_litellm_on_port_4000():
    data = _load_compose(COMPOSE_FILE)
    ports = data["services"]["litellm"].get("ports", [])
    port_strings = [str(p) for p in ports]
    assert any("4000" in p for p in port_strings)


# ── No hardcoded secrets ──────────────────────────────────────────────────────

KNOWN_SAFE_STRINGS = {"sk-helix-local", "dummy", "langfuse-local", "helix-local"}

@pytest.mark.parametrize("compose_path", [
    "docker-compose.yml",
    "docker-compose.cpu.yml",
    "docker-compose.mac.yml",
])
def test_no_hardcoded_secrets(compose_path: str):
    """Compose files must not contain Langfuse secrets or real API keys."""
    content = (REPO_ROOT / compose_path).read_text()
    suspicious_patterns = [
        "NEXTAUTH_SECRET=",
        "ENCRYPTION_KEY=",
        "LANGFUSE_SALT=",
    ]
    for pattern in suspicious_patterns:
        # These keys should only appear as ${VAR} references, not hardcoded
        idx = content.find(pattern)
        if idx != -1:
            snippet = content[idx:idx+80]
            assert "${" in snippet, (
                f"{compose_path} appears to hardcode secret at: {snippet!r}"
            )


# ── LiteLLM config mounts ─────────────────────────────────────────────────────

def test_litellm_mounts_config():
    data = _load_compose(COMPOSE_FILE)
    volumes = data["services"]["litellm"].get("volumes", [])
    vol_strings = [str(v) for v in volumes]
    assert any("config.yaml" in v for v in vol_strings), (
        "litellm service must mount litellm/config.yaml"
    )

def test_mac_litellm_mounts_mac_config():
    data = _load_compose(COMPOSE_MAC)
    volumes = data["services"]["litellm"].get("volumes", [])
    vol_strings = [str(v) for v in volumes]
    assert any("config.mac.yaml" in v for v in vol_strings), (
        "Mac litellm must mount litellm/config.mac.yaml (routes to host.docker.internal)"
    )

def test_mac_litellm_config_routes_to_host_gateway():
    """Mac LiteLLM config must route to host.docker.internal, not llama-server."""
    data = yaml.safe_load(LITELLM_MAC_CONFIG.read_text())
    for entry in data.get("model_list", []):
        if "claude" in entry.get("model_name", ""):
            api_base = entry.get("litellm_params", {}).get("api_base", "")
            assert "host.docker.internal" in api_base, (
                f"Mac LiteLLM config must route to host.docker.internal, got: {api_base!r}"
            )
            return
    pytest.fail("No claude-* entry in Mac LiteLLM config")


# ── Langfuse v2 config ────────────────────────────────────────────────────────

def test_langfuse_uses_v2_image():
    data = _load_compose(COMPOSE_FILE)
    image = data["services"]["langfuse"].get("image", "")
    assert image == "langfuse/langfuse:2", (
        f"Langfuse must use v2 image (not v3 which requires 6 containers), got: {image!r}"
    )

def test_postgres_uses_v17():
    data = _load_compose(COMPOSE_FILE)
    image = data["services"]["postgres"].get("image", "")
    assert "postgres:17" in image

def test_langfuse_has_headless_init_vars():
    """Langfuse must have LANGFUSE_INIT_* vars for headless project creation."""
    data = _load_compose(COMPOSE_FILE)
    env = data["services"]["langfuse"].get("environment", {})
    env_keys = list(env.keys()) if isinstance(env, dict) else [
        e.split("=")[0] for e in env
    ]
    for key in ("LANGFUSE_INIT_USER_EMAIL", "LANGFUSE_INIT_PROJECT_NAME",
                "LANGFUSE_INIT_PROJECT_PUBLIC_KEY", "LANGFUSE_INIT_PROJECT_SECRET_KEY"):
        assert key in env_keys, f"Langfuse service missing env var: {key}"

def test_langfuse_has_three_stable_secrets():
    """Langfuse must have all 3 secrets that must not change after first boot."""
    data = _load_compose(COMPOSE_FILE)
    env = data["services"]["langfuse"].get("environment", {})
    env_keys = list(env.keys()) if isinstance(env, dict) else [
        e.split("=")[0] for e in env
    ]
    for key in ("NEXTAUTH_SECRET", "SALT", "ENCRYPTION_KEY"):
        assert key in env_keys, f"Langfuse service missing stable secret: {key}"


# ── Volumes defined ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("volume", ["langfuse_postgres", "prometheus_data", "grafana_data"])
def test_compose_defines_volume(volume: str):
    data = _load_compose(COMPOSE_FILE)
    assert volume in data.get("volumes", {}), f"docker-compose.yml missing volume: {volume}"
