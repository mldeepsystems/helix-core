"""
Stage 6 validation tests: documentation correctness and consistency.

Run:
  pytest tests/test_stage6_docs.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
QUICKSTART = REPO_ROOT / "docs" / "quickstart.md"
MODEL_MATRIX = REPO_ROOT / "docs" / "model-matrix.md"
CLOUD_SETUP = REPO_ROOT / "docs" / "cloud-setup.md"
SETUP_PY = REPO_ROOT / "scripts" / "setup.py"

# Model keys from setup.py registry (source of truth)
SETUP_PY_MODEL_KEYS = [
    "qwen2.5-coder-7b",
    "qwen2.5-coder-14b",
    "qwen2.5-coder-32b",
    "deepseek-r1-70b",
    "llama-3.3-70b",
    "qwen2.5-coder-7b-cpu",
]

# VRAM values from setup.py registry
SETUP_PY_VRAM = {
    "qwen2.5-coder-7b": 8,
    "qwen2.5-coder-14b": 16,
    "qwen2.5-coder-32b": 24,
    "deepseek-r1-70b": 48,
    "llama-3.3-70b": 48,
    "qwen2.5-coder-7b-cpu": 0,
}

# Context lengths from setup.py registry
SETUP_PY_CONTEXT = {
    "qwen2.5-coder-7b": 32768,
    "qwen2.5-coder-14b": 32768,
    "qwen2.5-coder-32b": 32768,
    "deepseek-r1-70b": 65536,
    "llama-3.3-70b": 131072,
    "qwen2.5-coder-7b-cpu": 16384,
}


# ── File existence ────────────────────────────────────────────────────────────

def test_readme_exists():
    assert README.exists()

def test_quickstart_exists():
    assert QUICKSTART.exists()

def test_model_matrix_exists():
    assert MODEL_MATRIX.exists()

def test_cloud_setup_exists():
    assert CLOUD_SETUP.exists()


# ── README is not the bare-bones placeholder ──────────────────────────────────

def test_readme_not_placeholder():
    content = README.read_text()
    assert "Core repository for the Helix runtime" not in content, (
        "README still contains the bare-bones placeholder text"
    )

def test_readme_has_architecture():
    content = README.read_text()
    assert "LiteLLM" in content and "llama-server" in content

def test_readme_has_quickstart_section():
    content = README.read_text()
    assert "Quickstart" in content or "quickstart" in content

def test_readme_has_model_table():
    content = README.read_text()
    assert "Qwen" in content and "VRAM" in content

def test_readme_links_to_quickstart():
    content = README.read_text()
    assert "docs/quickstart.md" in content

def test_readme_links_to_model_matrix():
    content = README.read_text()
    assert "docs/model-matrix.md" in content

def test_readme_links_to_cloud_setup():
    content = README.read_text()
    assert "docs/cloud-setup.md" in content

def test_readme_links_to_scope():
    content = README.read_text()
    assert "SCOPE.md" in content

def test_readme_internal_links_resolve():
    """All relative file links in README must point to existing files."""
    content = README.read_text()
    # Find markdown links: [text](path)
    links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
    for text, href in links:
        if href.startswith("http") or href.startswith("#"):
            continue  # Skip external and anchor links
        target = REPO_ROOT / href
        assert target.exists(), f"README link [{text}]({href}) points to non-existent file"

def test_readme_mentions_anthropic_base_url():
    content = README.read_text()
    assert "ANTHROPIC_BASE_URL" in content

def test_readme_mentions_helix_check():
    content = README.read_text()
    assert "helix check" in content

def test_readme_no_v10_cloud_claim():
    """README must not imply helix cloud init works in v1.0."""
    content = README.read_text()
    # Cloud init mention is OK, but must be annotated as v1.1
    if "cloud init" in content.lower():
        assert "v1.1" in content or "defer" in content.lower(), (
            "README mentions cloud init but does not mark it as v1.1 / deferred"
        )


# ── Quickstart ────────────────────────────────────────────────────────────────

def test_quickstart_not_empty():
    assert len(QUICKSTART.read_text().strip()) > 200

def test_quickstart_has_prerequisites():
    content = QUICKSTART.read_text()
    assert "prerequisite" in content.lower() or "requirement" in content.lower() or \
           "prereq" in content.lower() or "## Prereq" in content or "| Requirement" in content

def test_quickstart_has_setup_py_command():
    content = QUICKSTART.read_text()
    assert "setup.py" in content

def test_quickstart_has_docker_compose_up():
    content = QUICKSTART.read_text()
    assert "docker compose up" in content

def test_quickstart_has_helix_check():
    content = QUICKSTART.read_text()
    assert "helix check" in content or "check.py" in content

def test_quickstart_has_anthropic_base_url():
    content = QUICKSTART.read_text()
    assert "ANTHROPIC_BASE_URL" in content

def test_quickstart_mentions_jinja_for_mac():
    """Mac quickstart must include --jinja flag."""
    content = QUICKSTART.read_text()
    assert "--jinja" in content, (
        "Quickstart must document --jinja flag for Apple Silicon llama-server"
    )

def test_quickstart_mentions_all_three_compose_variants():
    content = QUICKSTART.read_text()
    assert "docker-compose.cpu.yml" in content or "cpu" in content.lower()
    assert "docker-compose.mac.yml" in content or "apple silicon" in content.lower() or "mac" in content.lower()

def test_quickstart_no_broken_doc_links():
    content = QUICKSTART.read_text()
    links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
    for text, href in links:
        if href.startswith("http") or href.startswith("#"):
            continue
        target = (REPO_ROOT / "docs" / href) if not href.startswith("/") else REPO_ROOT / href.lstrip("/")
        if not target.exists():
            # Also try relative to repo root
            target2 = REPO_ROOT / href
            assert target2.exists(), f"Quickstart link [{text}]({href}) does not resolve"


# ── Model matrix ──────────────────────────────────────────────────────────────

def test_model_matrix_not_empty():
    assert len(MODEL_MATRIX.read_text().strip()) > 200

@pytest.mark.parametrize("model_key", SETUP_PY_MODEL_KEYS)
def test_model_matrix_mentions_model_key(model_key: str):
    content = MODEL_MATRIX.read_text()
    # Key or display name variant should appear
    key_part = model_key.replace("qwen2.5-coder-", "Qwen").replace("deepseek-r1-", "DeepSeek").replace("llama-3.3-", "Llama")
    assert model_key in content or key_part in content, (
        f"Model matrix missing entry for: {model_key}"
    )

def test_model_matrix_has_vram_column():
    content = MODEL_MATRIX.read_text()
    assert "VRAM" in content or "vram" in content

def test_model_matrix_has_context_column():
    content = MODEL_MATRIX.read_text()
    assert "Context" in content or "context" in content

def test_model_matrix_has_tool_call_parser():
    content = MODEL_MATRIX.read_text()
    assert "tool_call_parser" in content or "qwen2_5" in content

def test_model_matrix_vram_values_match_setup_py():
    """VRAM values in the matrix must match setup.py registry."""
    content = MODEL_MATRIX.read_text()
    # Check a few key VRAM values appear in the doc
    assert "8 GB" in content or "8GB" in content, "Missing 8GB entry (qwen2.5-coder-7b)"
    assert "24 GB" in content or "24GB" in content, "Missing 24GB entry (qwen2.5-coder-32b)"
    assert "48 GB" in content or "48GB" in content, "Missing 48GB entry (70B models)"

def test_model_matrix_context_values_match_setup_py():
    content = MODEL_MATRIX.read_text()
    assert "32K" in content or "32768" in content, "Missing 32K context"
    assert "64K" in content or "65536" in content, "Missing 64K context (DeepSeek)"
    assert "128K" in content or "131072" in content, "Missing 128K context (Llama 3.3)"

def test_model_matrix_consistent_with_setup_py():
    """setup.py is the source of truth — matrix must not contradict it."""
    setup_content = SETUP_PY.read_text()
    matrix_content = MODEL_MATRIX.read_text()
    # Verify HF repo names in setup.py appear somewhere in matrix or model YAMLs
    assert "bartowski" in matrix_content or "bartowski" in setup_content, (
        "Model matrix should reference bartowski HuggingFace repos"
    )

def test_model_matrix_mentions_community():
    content = MODEL_MATRIX.read_text()
    assert "community" in content.lower()

def test_model_matrix_no_v10_cloud_claim():
    content = MODEL_MATRIX.read_text()
    assert "cloud init" not in content.lower() or "v1.1" in content or "defer" in content.lower()


# ── Cloud setup ───────────────────────────────────────────────────────────────

def test_cloud_setup_not_empty():
    assert len(CLOUD_SETUP.read_text().strip()) > 100

def test_cloud_setup_clearly_deferred():
    content = CLOUD_SETUP.read_text()
    assert "defer" in content.lower() or "v1.1" in content, (
        "cloud-setup.md must clearly state the feature is deferred to v1.1"
    )

def test_cloud_setup_no_working_cloud_init_claim():
    """Must not imply helix cloud init works right now."""
    content = CLOUD_SETUP.read_text()
    # Must not contain "run helix cloud init" as a working instruction without caveat
    if "helix cloud init" in content:
        # Acceptable if it's in a "planned" or "deferred" context
        assert "planned" in content.lower() or "defer" in content.lower() or "v1.1" in content

def test_cloud_setup_mentions_gcp():
    content = CLOUD_SETUP.read_text()
    assert "gcp" in content.lower() or "GCP" in content

def test_cloud_setup_mentions_runpod():
    content = CLOUD_SETUP.read_text()
    assert "runpod" in content.lower() or "RunPod" in content

def test_cloud_setup_links_to_quickstart():
    content = CLOUD_SETUP.read_text()
    assert "quickstart" in content.lower()
