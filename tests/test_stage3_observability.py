"""
Stage 3 validation tests: Prometheus scrape config and Grafana dashboard.

Run:
  pytest tests/test_stage3_observability.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMETHEUS_CONFIG = REPO_ROOT / "prometheus" / "prometheus.yml"
GRAFANA_DATASOURCE = REPO_ROOT / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
GRAFANA_DASHBOARD_PROVISIONING = REPO_ROOT / "grafana" / "provisioning" / "dashboards" / "dashboard.yml"
GRAFANA_DASHBOARD_JSON = REPO_ROOT / "grafana" / "dashboards" / "helix-core.json"

EXPECTED_SCRAPE_JOBS = ["llama-server", "litellm", "prometheus"]
EXPECTED_PANEL_TITLES = [
    "Token Throughput",
    "Time to First Token",
    "Request Queue",
    "KV Cache",
    "LiteLLM",
    "AgentDx",
]
AGENTDX_METRICS = ["agentdx_health_score", "agentdx_pathology_detections_total"]
LLAMACPP_METRICS = [
    "llamacpp_tokens_generated_total",
    "llamacpp_time_to_first_token_seconds",
    "llamacpp_kv_cache_usage_ratio",
    "llamacpp_kv_cache_tokens",
    "llamacpp_prompt_tokens_total",
    "llamacpp_requests_processing",
]


# ── File existence ────────────────────────────────────────────────────────────

def test_prometheus_config_exists():
    assert PROMETHEUS_CONFIG.exists()

def test_grafana_datasource_provisioning_exists():
    assert GRAFANA_DATASOURCE.exists()

def test_grafana_dashboard_provisioning_exists():
    assert GRAFANA_DASHBOARD_PROVISIONING.exists()

def test_grafana_dashboard_json_exists():
    assert GRAFANA_DASHBOARD_JSON.exists()


# ── Prometheus config ─────────────────────────────────────────────────────────

def test_prometheus_config_parses():
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    assert isinstance(data, dict)

def test_prometheus_has_global_scrape_interval():
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    assert "global" in data
    assert "scrape_interval" in data["global"]

def test_prometheus_has_scrape_configs():
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    assert "scrape_configs" in data
    assert len(data["scrape_configs"]) > 0

@pytest.mark.parametrize("job", EXPECTED_SCRAPE_JOBS)
def test_prometheus_has_job(job: str):
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    job_names = [c.get("job_name") for c in data.get("scrape_configs", [])]
    assert job in job_names, f"prometheus.yml missing scrape job: {job!r}"

def test_prometheus_scrapes_llama_server_on_8080():
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    for job in data.get("scrape_configs", []):
        if job.get("job_name") == "llama-server":
            targets = job.get("static_configs", [{}])[0].get("targets", [])
            assert any("8080" in t for t in targets), (
                "llama-server scrape job must target port 8080"
            )
            return
    pytest.fail("llama-server scrape job not found")

def test_prometheus_scrapes_litellm_on_4000():
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    for job in data.get("scrape_configs", []):
        if job.get("job_name") == "litellm":
            targets = job.get("static_configs", [{}])[0].get("targets", [])
            assert any("4000" in t for t in targets), (
                "litellm scrape job must target port 4000"
            )
            return
    pytest.fail("litellm scrape job not found")

def test_prometheus_uses_docker_service_names():
    """Scrape targets must use Docker service names (not localhost) for inter-container routing."""
    data = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    for job in data.get("scrape_configs", []):
        name = job.get("job_name", "")
        if name in ("llama-server", "litellm"):
            for sc in job.get("static_configs", []):
                for target in sc.get("targets", []):
                    assert "localhost" not in target, (
                        f"Scrape target {target!r} for {name!r} uses localhost — "
                        "use Docker service name for inter-container networking"
                    )


# ── Grafana datasource provisioning ──────────────────────────────────────────

def test_grafana_datasource_parses():
    data = yaml.safe_load(GRAFANA_DATASOURCE.read_text())
    assert isinstance(data, dict)

def test_grafana_datasource_has_prometheus():
    data = yaml.safe_load(GRAFANA_DATASOURCE.read_text())
    sources = data.get("datasources", [])
    names = [s.get("name") for s in sources]
    assert "Prometheus" in names

def test_grafana_datasource_prometheus_url():
    data = yaml.safe_load(GRAFANA_DATASOURCE.read_text())
    for ds in data.get("datasources", []):
        if ds.get("name") == "Prometheus":
            url = ds.get("url", "")
            assert "prometheus" in url and "9090" in url, (
                f"Prometheus datasource URL should point to prometheus:9090, got: {url!r}"
            )
            return
    pytest.fail("Prometheus datasource not found")

def test_grafana_datasource_is_default():
    data = yaml.safe_load(GRAFANA_DATASOURCE.read_text())
    for ds in data.get("datasources", []):
        if ds.get("name") == "Prometheus":
            assert ds.get("isDefault") is True
            return
    pytest.fail("Prometheus datasource not found")


# ── Grafana dashboard provisioning ────────────────────────────────────────────

def test_grafana_dashboard_provisioning_parses():
    data = yaml.safe_load(GRAFANA_DASHBOARD_PROVISIONING.read_text())
    assert isinstance(data, dict)

def test_grafana_dashboard_provisioning_has_provider():
    data = yaml.safe_load(GRAFANA_DASHBOARD_PROVISIONING.read_text())
    providers = data.get("providers", [])
    assert len(providers) > 0, "dashboard provisioning must have at least one provider"

def test_grafana_dashboard_provisioning_file_path():
    """Provider path must match the Grafana container volume mount."""
    data = yaml.safe_load(GRAFANA_DASHBOARD_PROVISIONING.read_text())
    for p in data.get("providers", []):
        if p.get("type") == "file":
            path = p.get("options", {}).get("path", "")
            assert "/var/lib/grafana/dashboards" in path, (
                f"Dashboard provider path must be /var/lib/grafana/dashboards, got: {path!r}"
            )
            return
    pytest.fail("No file-type dashboard provider found")


# ── Dashboard JSON ────────────────────────────────────────────────────────────

def test_dashboard_json_parses():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    assert isinstance(data, dict)

def test_dashboard_json_has_uid():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    assert data.get("uid"), "Dashboard must have a uid for stable provisioning"

def test_dashboard_json_has_title():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    assert data.get("title"), "Dashboard must have a title"

def test_dashboard_json_has_panels():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    panels = data.get("panels", [])
    assert len(panels) > 0, "Dashboard must have panels"

def test_dashboard_has_timeseries_panels():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    panel_types = [p.get("type") for p in data.get("panels", [])]
    assert "timeseries" in panel_types, "Dashboard must have at least one timeseries panel"

@pytest.mark.parametrize("keyword", EXPECTED_PANEL_TITLES)
def test_dashboard_has_expected_panel(keyword: str):
    """Dashboard must contain panels covering each required metric area."""
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    titles = [p.get("title", "") for p in data.get("panels", [])]
    assert any(keyword.lower() in t.lower() for t in titles), (
        f"Dashboard missing panel for: {keyword!r}. Found: {titles}"
    )

@pytest.mark.parametrize("metric", LLAMACPP_METRICS)
def test_dashboard_queries_llamacpp_metric(metric: str):
    """Dashboard panels must query llama.cpp metrics by name."""
    raw = GRAFANA_DASHBOARD_JSON.read_text()
    assert metric in raw, f"Dashboard does not reference llama.cpp metric: {metric!r}"

@pytest.mark.parametrize("metric", AGENTDX_METRICS)
def test_dashboard_has_agentdx_metric(metric: str):
    """Dashboard must have AgentDx metrics panel (populated by agentdx-bridge)."""
    raw = GRAFANA_DASHBOARD_JSON.read_text()
    assert metric in raw, f"Dashboard does not reference AgentDx metric: {metric!r}"

def test_dashboard_has_agentdx_row():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    row_titles = [p.get("title", "") for p in data.get("panels", []) if p.get("type") == "row"]
    assert any("agentdx" in t.lower() for t in row_titles), (
        f"Dashboard must have an AgentDx row panel. Found rows: {row_titles}"
    )

def test_dashboard_has_refresh_interval():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    assert data.get("refresh"), "Dashboard should have an auto-refresh interval"

def test_dashboard_has_datasource_template_variable():
    """Dashboard should use a datasource template variable for portability."""
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    variables = data.get("templating", {}).get("list", [])
    var_types = [v.get("type") for v in variables]
    assert "datasource" in var_types, (
        "Dashboard should have a datasource template variable for portability"
    )

def test_dashboard_panels_reference_datasource_variable():
    """All data panels should use ${datasource} variable, not hardcoded UID."""
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    for panel in data.get("panels", []):
        if panel.get("type") == "row":
            continue
        ds = panel.get("datasource", {})
        if isinstance(ds, dict):
            uid = ds.get("uid", "")
            assert uid == "${datasource}" or not uid, (
                f"Panel {panel.get('title')!r} datasource uid should be ${{datasource}}, got {uid!r}"
            )

def test_dashboard_schema_version():
    data = json.loads(GRAFANA_DASHBOARD_JSON.read_text())
    assert data.get("schemaVersion", 0) >= 30, (
        "Dashboard schemaVersion should be >= 30 (Grafana 9+)"
    )
