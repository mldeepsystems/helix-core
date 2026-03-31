"""
Stage 1 validation tests: model YAML configs + LiteLLM proxy configuration.

Gates:
  1. All 6 model YAMLs exist and parse cleanly
  2. litellm/config.yaml exists and parses cleanly
  3. LiteLLM config contains all spike-required keys
  4. Each model YAML contains all required fields
  5. Model YAML data is consistent with the setup.py registry (source of truth)
  6. models/community/README.md exists with required sections

Run:
  pytest tests/test_stage1_configs.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# ── Repo root ─────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
LITELLM_CONFIG = REPO_ROOT / "litellm" / "config.yaml"
COMMUNITY_README = REPO_ROOT / "models" / "community" / "README.md"

# ── Source of truth: registry from setup.py ───────────────────────────────────
# Duplicated here intentionally — if setup.py and the YAML files diverge,
# these tests catch it.

SETUP_PY_REGISTRY = {
    "qwen2.5-coder-7b": {
        "hf_repo": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        "hf_filename": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "vram_required_gb": 8,
        "context_length": 32768,
        "size_gb": 4.7,
        "quantization": "Q4_K_M",
    },
    "qwen2.5-coder-14b": {
        "hf_repo": "bartowski/Qwen2.5-Coder-14B-Instruct-GGUF",
        "hf_filename": "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
        "vram_required_gb": 16,
        "context_length": 32768,
        "size_gb": 9.0,
        "quantization": "Q4_K_M",
    },
    "qwen2.5-coder-32b": {
        "hf_repo": "bartowski/Qwen2.5-Coder-32B-Instruct-GGUF",
        "hf_filename": "Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf",
        "vram_required_gb": 24,
        "context_length": 32768,
        "size_gb": 19.8,
        "quantization": "Q4_K_M",
    },
    "deepseek-r1-70b": {
        "hf_repo": "bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF",
        "hf_filename": "DeepSeek-R1-Distill-Llama-70B-Q4_K_M.gguf",
        "vram_required_gb": 48,
        "context_length": 65536,
        "size_gb": 42.5,
        "quantization": "Q4_K_M",
    },
    "llama-3.3-70b": {
        "hf_repo": "bartowski/Llama-3.3-70B-Instruct-GGUF",
        "hf_filename": "Llama-3.3-70B-Instruct-Q4_K_M.gguf",
        "vram_required_gb": 48,
        "context_length": 131072,
        "size_gb": 42.5,
        "quantization": "Q4_K_M",
    },
    "qwen2.5-coder-7b-cpu": {
        "hf_repo": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
        "hf_filename": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "vram_required_gb": 0,
        "context_length": 16384,
        "size_gb": 4.7,
        "quantization": "Q4_K_M",
    },
}

REQUIRED_MODEL_FIELDS = [
    "model_key",
    "display_name",
    "hf_repo",
    "hf_filename",
    "quantization",
    "size_gb",
    "vram_required_gb",
    "context_length",
    "n_gpu_layers",
    "tool_call_parser",
    "temperature",
    "repeat_penalty",
    "stop_tokens",
]

VALID_TOOL_CALL_PARSERS = {"qwen2_5", "deepseek", "llama3_json", "mistral"}

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _load_model_yaml(key: str) -> dict:
    path = MODELS_DIR / f"{key}.yaml"
    return yaml.safe_load(path.read_text())


# ── Gate 1: All model YAMLs exist and parse ───────────────────────────────────

@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
def test_model_yaml_exists(model_key: str) -> None:
    """Each model YAML file referenced in setup.py must exist."""
    path = MODELS_DIR / f"{model_key}.yaml"
    assert path.exists(), f"Missing model config: {path}"


@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
def test_model_yaml_parses(model_key: str) -> None:
    """Each model YAML must be valid YAML."""
    path = MODELS_DIR / f"{model_key}.yaml"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path} did not parse to a dict"


def test_exactly_six_model_yamls() -> None:
    """models/ should contain exactly 6 YAML files (no extras, no missing)."""
    yamls = sorted(p.name for p in MODELS_DIR.glob("*.yaml"))
    expected = sorted(f"{k}.yaml" for k in SETUP_PY_REGISTRY)
    assert yamls == expected, f"Expected {expected}, found {yamls}"


# ── Gate 2: LiteLLM config exists and parses ─────────────────────────────────

def test_litellm_config_exists() -> None:
    assert LITELLM_CONFIG.exists(), f"Missing: {LITELLM_CONFIG}"


def test_litellm_config_parses() -> None:
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    assert isinstance(data, dict), "litellm/config.yaml did not parse to a dict"


# ── Gate 3: LiteLLM spike-required settings ───────────────────────────────────

def test_litellm_drop_params() -> None:
    """drop_params: true required — Anthropic params cause 422 without it."""
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    settings = data.get("litellm_settings", {})
    assert settings.get("drop_params") is True, "litellm_settings.drop_params must be true"


def test_litellm_modify_params() -> None:
    """modify_params: true required for Anthropic→OpenAI param translation."""
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    settings = data.get("litellm_settings", {})
    assert settings.get("modify_params") is True, "litellm_settings.modify_params must be true"


def test_litellm_disable_key_check() -> None:
    """disable_key_check: true required for Claude Code auth flow."""
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    settings = data.get("litellm_settings", {})
    assert settings.get("disable_key_check") is True, "litellm_settings.disable_key_check must be true"


def test_litellm_has_model_list() -> None:
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    assert "model_list" in data, "litellm/config.yaml must have a model_list"
    assert len(data["model_list"]) > 0, "model_list must not be empty"


def test_litellm_claude_wildcard() -> None:
    """model_list must have a claude-* wildcard entry."""
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    model_names = [entry.get("model_name", "") for entry in data.get("model_list", [])]
    assert any("claude" in name for name in model_names), (
        "model_list must contain a claude-* wildcard entry to catch all Claude Code requests"
    )


def test_litellm_routes_to_llama_server() -> None:
    """The claude-* entry must route to llama-server:8080/v1."""
    data = yaml.safe_load(LITELLM_CONFIG.read_text())
    for entry in data.get("model_list", []):
        if "claude" in entry.get("model_name", ""):
            api_base = entry.get("litellm_params", {}).get("api_base", "")
            assert "llama-server" in api_base and "8080" in api_base, (
                f"claude-* entry must route to llama-server:8080, got: {api_base!r}"
            )
            return
    pytest.fail("No claude-* entry found in model_list")


# ── Gate 4: Required fields in each model YAML ───────────────────────────────

@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
@pytest.mark.parametrize("field", REQUIRED_MODEL_FIELDS)
def test_model_yaml_has_required_field(model_key: str, field: str) -> None:
    data = _load_model_yaml(model_key)
    assert field in data, f"{model_key}.yaml missing required field: {field!r}"


@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
def test_model_yaml_tool_call_parser_valid(model_key: str) -> None:
    """tool_call_parser must be one of the known values — wrong parser = silent tool call failure."""
    data = _load_model_yaml(model_key)
    parser = data.get("tool_call_parser")
    assert parser in VALID_TOOL_CALL_PARSERS, (
        f"{model_key}.yaml: tool_call_parser={parser!r} not in {VALID_TOOL_CALL_PARSERS}"
    )


@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
def test_model_yaml_stop_tokens_is_list(model_key: str) -> None:
    data = _load_model_yaml(model_key)
    assert isinstance(data.get("stop_tokens"), list), (
        f"{model_key}.yaml: stop_tokens must be a list"
    )
    assert len(data["stop_tokens"]) > 0, f"{model_key}.yaml: stop_tokens must not be empty"


@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
def test_model_yaml_numeric_fields_positive(model_key: str) -> None:
    data = _load_model_yaml(model_key)
    for field in ("context_length", "temperature", "repeat_penalty", "size_gb"):
        val = data.get(field)
        assert isinstance(val, (int, float)) and val > 0, (
            f"{model_key}.yaml: {field} must be a positive number, got {val!r}"
        )


@pytest.mark.parametrize("model_key", list(SETUP_PY_REGISTRY.keys()))
def test_model_yaml_n_gpu_layers_valid(model_key: str) -> None:
    data = _load_model_yaml(model_key)
    n = data.get("n_gpu_layers")
    assert isinstance(n, int) and n >= 0, (
        f"{model_key}.yaml: n_gpu_layers must be a non-negative integer, got {n!r}"
    )


# ── Gate 5: Consistency with setup.py registry ───────────────────────────────

@pytest.mark.parametrize("model_key,expected", list(SETUP_PY_REGISTRY.items()))
def test_model_yaml_matches_setup_py(model_key: str, expected: dict) -> None:
    """YAML values must match the setup.py ModelConfig registry exactly."""
    data = _load_model_yaml(model_key)
    for field, expected_val in expected.items():
        actual_val = data.get(field)
        if isinstance(expected_val, float):
            assert actual_val == pytest.approx(expected_val, rel=0.01), (
                f"{model_key}.yaml: {field}={actual_val!r}, setup.py has {expected_val!r}"
            )
        else:
            assert actual_val == expected_val, (
                f"{model_key}.yaml: {field}={actual_val!r}, setup.py has {expected_val!r}"
            )


def test_cpu_model_has_zero_n_gpu_layers() -> None:
    """CPU offload variant must have n_gpu_layers=0."""
    data = _load_model_yaml("qwen2.5-coder-7b-cpu")
    assert data["n_gpu_layers"] == 0, "CPU variant must have n_gpu_layers=0"


def test_cpu_model_has_reduced_context() -> None:
    """CPU variant has reduced context window (16384 vs 32768) to fit in RAM."""
    data = _load_model_yaml("qwen2.5-coder-7b-cpu")
    assert data["context_length"] == 16384


# ── Gate 6: Community README ──────────────────────────────────────────────────

def test_community_readme_exists() -> None:
    assert COMMUNITY_README.exists(), f"Missing: {COMMUNITY_README}"


def test_community_readme_has_required_sections() -> None:
    content = COMMUNITY_README.read_text()
    for section in ("## Contributing", "## Required Fields", "## Template"):
        assert section in content, f"models/community/README.md missing section: {section!r}"


def test_community_readme_mentions_tool_call_parser() -> None:
    """Community contributors must know tool_call_parser is required."""
    content = COMMUNITY_README.read_text()
    assert "tool_call_parser" in content, (
        "community README must document tool_call_parser — wrong value causes silent failures"
    )
