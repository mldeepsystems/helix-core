# helix-core — Scope & Requirements

> **One-line definition:** A Docker Compose stack that serves any local or cloud-hosted LLM via a LiteLLM proxy, wired to Claude Code CLI via `ANTHROPIC_BASE_URL`.
>
> **What it is not:** An agent framework, an orchestration layer, a router. That is helix-router. helix-core is purely the model serving + observability substrate.

## Architecture (Spike-Validated 2026-03-31)

```
Claude Code CLI
      │  ANTHROPIC_BASE_URL=http://localhost:4000
      │  ANTHROPIC_AUTH_TOKEN=sk-helix-local
      ▼
LiteLLM proxy  (port 4000)   ← translates Anthropic → OpenAI format
      │  POST /v1/chat/completions
      ▼
llama-server   (port 8080)   ← OpenAI-compatible inference (--jinja required)
      │
      ▼
[any GGUF model]

                     ↓ traces (official Claude Code integration)
                  Langfuse  (port 3002)
                     ↓ SDK polling
                  agentdx-bridge  →  Prometheus (port 9090)  →  Grafana (port 3000)
```

**Spike results:**

**Wire format (spike 1):** Anthropic SDK sends to `/v1/messages` with `input_schema` tool schema. llama-server only has `/v1/chat/completions` with `function.parameters`. Direct connection → 404. LiteLLM proxy is required. See `spikes/wire_format_spike.py`.

**LiteLLM (spike 1):** `drop_params: true` and `modify_params: true` required or Anthropic-specific params cause 422 errors. `claude-*` wildcard in model_list catches all Claude model names. `disable_key_check: true` required for Claude Code's auth flow.

**llama-server flags (spike 1):** `--jinja` is required for any tool calling — without it, llama-server silently ignores the `tools` field. `--tool-call-parser qwen2_5` required for Qwen models; must match model family.

**Langfuse (spike 2):** Use v2 (2 containers: server + Postgres). v3 requires 6 containers (+ ClickHouse + Redis + MinIO) — too heavy for this stack. 3 secrets (`NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY`) must be pre-generated and stable — changing them breaks all sessions and API key hashes.

**Langfuse trace capture (spike 3):** Official Claude Code ↔ Langfuse integration exists (`langfuse.com/integrations/other/claude-code`). Traces captured via SDK or the claude-code-langfuse-template pattern.

**agentdx converter (spike 3):** 80% of fields map directly. Main work: unpack system/user messages from GENERATION observation `input` arrays (they're not separate observations). `ToolCall.success` maps from `observation.level != "ERROR"`. Use Langfuse Python SDK for polling, not raw REST.

---

## Problem It Solves

Claude Code CLI is hardwired to call `api.anthropic.com`. Every agentic session costs real money and sends code to a third party. helix-core intercepts that by standing up a local or cloud-hosted LLM behind an OpenAI-compatible API, and pointing Claude Code at it instead. The result: full Claude Code agentic capability (file edits, bash, tool use, multi-step tasks) against a model you control, at zero per-token cost.

---

## Functional Requirements

### F0 — Setup Script (`scripts/setup.py`)
The entry point for all new users. One command from a fresh machine to a fully configured, ready-to-run stack.

```bash
python scripts/setup.py
```

**Steps the script runs in order:**

1. **Hardware detection** — probes GPU (nvidia-smi / Apple Silicon), VRAM, RAM, OS
2. **Deployment mode selection** — Local GPU / CPU offload / Cloud (interactive, with hardware-aware default)
3. **Prerequisite check** — Claude Code CLI, Docker, Docker Compose, Python 3.10+, NVIDIA Container Toolkit (GPU mode)
4. **Model selection** — shows compatibility matrix filtered by detected hardware; recommends best fit; user can override
5. **Model download** — downloads GGUF from HuggingFace via `huggingface_hub` (resumable) or direct URL fallback; skips if already present
6. **Config generation** — writes `.env` from `.env.example` with model path, context length, ports, and deployment mode pre-filled
7. **Summary** — prints exact commands to start the stack and verify it works

**Flags:**
```
--model qwen2.5-coder-32b   skip interactive model selection
--mode  local|cpu|cloud     skip interactive mode selection
--skip-download             configure only, no model download
```

**Model compatibility matrix (baked into setup.py):**
| Key | VRAM | Download | Notes |
|---|---|---|---|
| `qwen2.5-coder-7b` | 8GB | ~4.7GB | Entry point |
| `qwen2.5-coder-14b` | 16GB | ~9GB | Balanced |
| `qwen2.5-coder-32b` | 24GB | ~19.8GB | Reference config |
| `deepseek-r1-70b` | 48GB | ~42.5GB | Reasoning |
| `llama-3.3-70b` | 48GB | ~42.5GB | General |
| `qwen2.5-coder-7b-cpu` | none | ~4.7GB | CPU offload |

**No external dependencies for setup.py itself** — uses only stdlib. `huggingface_hub` used if installed (optional, for resumable downloads).

---

### F1 — Model Serving
- **llama-server** (llama.cpp): OpenAI-compatible REST API on `localhost:8080`
  - Required flags: `--jinja` (enables tool calling), `--host 0.0.0.0`, `--ctx-size` from model YAML
  - Required per model family: `--tool-call-parser qwen2_5` (Qwen), `--tool-call-parser deepseek` (DeepSeek)
- **LiteLLM proxy**: Anthropic-compatible API on `localhost:4000`
  - `litellm/config.yaml` with `claude-*` wildcard → `openai/local-model` → `http://llama-server:8080/v1`
  - Required settings: `drop_params: true`, `modify_params: true`, `disable_key_check: true`
  - Docker image: `ghcr.io/berriai/litellm:main-stable` (pin to specific version, not `main-latest`)
- Per-model YAML config: context window, temperature, stop tokens, repeat penalty, `n_gpu_layers`

### F2 — Claude Code Integration
Two env vars required (both must be set):
```bash
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_AUTH_TOKEN=sk-helix-local  # matches LiteLLM master_key
```
- Validate end-to-end: file read/write/edit, bash execution, multi-step tasks, long context
- Smoke test: zero calls to `api.anthropic.com` confirmed via Langfuse

### F3 — Deployment Modes

**Mode 1: Local GPU (Linux / WSL2)**
- Docker Compose with GPU passthrough (`deploy.resources.reservations.devices`)
- NVIDIA Container Toolkit as prerequisite

**Mode 2: Apple Silicon (macOS)**
- llama-server runs natively via Metal (not in Docker GPU mode)
- VRAM detection uses `sysctl hw.memsize` for total unified memory — NOT `system_profiler SPDisplaysDataType` which returns display VRAM (~1GB), not usable inference memory
- Recommended: run llama-server natively, proxy + observability stack in Docker
- Model recommendation based on total unified memory: 16GB → 7B, 32GB → 14B, 64GB+ → 32B

**Mode 3: CPU Offload**
- Docker Compose without GPU requirement, `-ngl 0` flag
- Any machine fallback

**Mode 4: Self-hosted Cloud GPU — DEFERRED to v1.1**
- GCP + RunPod provisioning deferred out of v1.0 — doubles blast radius for initial release
- Local stack (Modes 1–3) must be validated first
- `helix cloud init` ships as a follow-on milestone

### F4 — Observability Stack

Three tiers of observability, each answering a different question:

| Service | Answers | Port |
|---|---|---|
| Prometheus + Grafana | "How is the infrastructure performing?" | 9090 / 3000 |
| Langfuse | "What did the model do?" | 3002 |
| AgentDx *(optional)* | "What went wrong in the agent's behavior?" | 7700 |

**Prometheus + Grafana** — scrapes GPU utilization, CPU, memory, inference latency, LiteLLM request metrics. Pre-built dashboard JSON in repo. Port 3000.

**Langfuse v2** — captures Claude Code sessions (prompts, completions, tool calls, latency). Port **3002** (not 3000 — conflicts with Grafana). Uses official Claude Code ↔ Langfuse integration.
- Requires 2 containers: `langfuse/langfuse:2` + `postgres:17`
- 3 secrets must be pre-generated and stable (changing them breaks all sessions):
  - `NEXTAUTH_SECRET`: `openssl rand -base64 32`
  - `SALT`: `openssl rand -base64 32`
  - `ENCRYPTION_KEY`: `openssl rand -hex 32` (must be 64-char hex)
- Headless init via `LANGFUSE_INIT_*` env vars — project API keys set by you, not auto-generated by the server
- setup.py generates these secrets on first run and writes them to `.env`

**AgentDx** (`pip install agentdx`) — runs pathology detection against traces captured by Langfuse. **Enabled by default.** Disable via env var:
```bash
AGENTDX_ENABLED=false docker compose up
```

agentdx is a trace-based analyzer: reads completed traces, runs 7/9 detectors (ContextErosion, GoalHijacking, HallucinatedToolSuccess, InstructionDrift, RecoveryBlindness, SilentDegradation, ToolThrashing), returns a DiagnosticReport.

**Integration architecture:**
```
Claude Code session
      ↓
Langfuse (trace storage)
      ↓ polls every N seconds
agentdx-bridge (helix-core sidecar)
      ↓ Langfuse API → agentdx Trace schema → Diagnoser.diagnose()
Prometheus metrics endpoint
      ↓
Grafana (AgentDx panel: health score, pathology counts, per-session detections)
```

**What helix-core must build** (agentdx-bridge sidecar):
- **Langfuse poller** (`langfuse` Python SDK): `GET /api/public/traces?fromTimestamp=...&orderBy=timestamp.asc` — cursor advances per poll, persisted between runs. Fetch individual trace for full observations.
- **Trace converter** (`langfuse_converter.py`): Langfuse `TraceWithFullDetails` → agentdx `Trace/Message/ToolCall`
  - Unpack system/user messages from GENERATION observation `input[]` array (not separate observations)
  - GENERATION output → assistant Message (+ extract ToolCall objects from `tool_use` blocks)
  - TOOL observation → tool Message with ToolCall (`success = level != "ERROR"`, `error_message = statusMessage`)
  - Sort all observations by `startTime` to derive `step_index`
- **Prometheus metrics exporter**: pathology detection counts, health scores per session
- **Grafana AgentDx panel**: bundled in `grafana/dashboard.json`

### F5 — `helix cloud init`
Interactive CLI script for cloud GPU provisioning. Runs outside Docker.

**GCP flow:**
1. Check `gcloud` CLI installed; prompt to install if not
2. `gcloud auth login` (opens browser)
3. Prompt: project ID, region, instance name
4. Prompt: model selection from the model matrix
5. Provision L4 Spot VM with startup script (installs Docker, NVIDIA drivers, pulls helix-core image)
6. Wait for health check to pass
7. Print: `ANTHROPIC_BASE_URL=http://<external-ip>:4000` — ready to paste

**RunPod flow:**
1. Prompt for RunPod API key
2. Prompt: GPU type (L4, A100 40GB, A100 80GB), model selection
3. Deploy pod via RunPod API with helix-core Docker image
4. Wait for pod to be ready
5. Print: `ANTHROPIC_BASE_URL=http://<pod-endpoint>:4000`

Both flows: print estimated cost per hour before provisioning. Require explicit confirmation.

### F6 — Model Compatibility Matrix
Tested, validated configs shipped in `models/` directory. Each model has its own `.yaml` config file.

| Model | VRAM | Quantization | Context | Status |
|---|---|---|---|---|
| Qwen2.5-Coder 7B | 8GB | Q4_K_M | 32K | Reference (8GB) |
| Qwen2.5-Coder 14B | 16GB | Q4_K_M | 32K | Reference (16GB) |
| Qwen2.5-Coder 32B | 24GB | Q4_K_M | 32K | Reference (24GB) |
| Deepseek R1 70B | 48GB | Q4_K_M | 64K | Reference (48GB+) |
| Llama 3.3 70B | 48GB | Q4_K_M | 128K | Reference (48GB+) |
| Qwen2.5-Coder 7B | no GPU | Q4_K_M | 16K | CPU offload |

Community-contributed configs for other models are accepted via PR into `models/community/`.

---

## Non-Functional Requirements

### Performance
- Time-to-first-token < 3s for 32B Q4 on 24GB VRAM (local GPU mode)
- Sustained throughput: ≥ 15 tokens/sec for 32B Q4 on L4 GPU
- Docker Compose `up` to ready endpoint: < 2 minutes (model already downloaded)

### Reliability
- llama-server process restart policy: `always` (Docker handles crashes)
- Health check endpoint: `GET /health` returns 200 when model is loaded
- Graceful handling of context overflow — return structured error, not silent truncation

### Security
- Endpoint bound to `localhost` by default in local mode — not exposed to network
- Cloud mode: firewall rule restricts access to user's IP only (provisioned by setup script)
- No API keys stored in Docker Compose files — passed via `.env` (gitignored template provided)

### Developer Experience
- Single command to start: `docker compose up`
- Single command to validate: `helix check` — confirms endpoint is live, model is loaded, Claude Code can reach it
- `docker compose down` tears everything down cleanly including volumes
- Model download handled by a separate `helix pull <model>` command, not on first `up`

---

## Repository Structure

```
helix-core/
├── docker-compose.yml           — GPU stack: llama-server + litellm + langfuse + prometheus + grafana
├── docker-compose.cpu.yml       — CPU offload override (no GPU passthrough)
├── docker-compose.mac.yml       — Apple Silicon: llama-server native, proxy+observability in Docker
├── litellm/
│   └── config.yaml              — LiteLLM model routing: Anthropic model names → llama-server endpoint
├── models/
│   ├── qwen2.5-coder-7b.yaml    — context, stop tokens, repeat penalty, n_gpu_layers
│   ├── qwen2.5-coder-14b.yaml
│   ├── qwen2.5-coder-32b.yaml   — reference config
│   ├── deepseek-r1-70b.yaml
│   ├── llama-3.3-70b.yaml
│   └── community/               — community-contributed configs (PR welcome)
├── grafana/
│   └── dashboard.json           — pre-built dashboard: tokens/sec, VRAM, TTFT, request queue
├── prometheus/
│   └── prometheus.yml           — scrape config for llama-server + litellm metrics
├── .env.example                 — all config keys documented; secrets auto-generated by setup.py
├── agentdx_bridge/
│   ├── main.py                  — Langfuse poller → agentdx Diagnoser → Prometheus metrics
│   ├── langfuse_converter.py    — Langfuse TraceWithFullDetails → agentdx Trace/Message/ToolCall
│   └── Dockerfile
├── scripts/
│   ├── setup.py                 — hardware detect → model download → .env write (incl. Langfuse secrets)
│   ├── check.py                 — smoke test: LiteLLM live + tool call works + zero Anthropic calls
│   ├── cloud_init.py            — cloud GPU provisioning (GCP + RunPod)
│   └── helix                    — CLI entrypoint: helix setup | helix check | helix cloud init
├── spikes/
│   └── wire_format_spike.py     — confirmed Anthropic↔OpenAI incompatibility (2026-03-31)
└── docs/
    ├── quickstart.md            — zero to running agentic session
    ├── model-matrix.md          — compatibility table with benchmark notes
    └── cloud-setup.md           — GCP + RunPod deployment guide
```
- `docs/cloud-setup.md`

---

## Out of Scope for helix-core

The following are explicitly **not** in helix-core. They belong to later packages.

| Capability | Belongs to |
|---|---|
| Semantic routing between models | helix-router |
| Episodic memory / ChromaDB | helix-memory |
| Skill evolution / OpenSpace | helix-memory |
| Self-refinement loops | helix-router |
| Autoresearch / overnight loop | helix-research |
| AgentDx diagnostic pipeline | helix-agentdx |
| Multiple specialist siloes | helix-router |
| Fine-tuning pipeline | helix-os |

---

## Acceptance Criteria — v1.0

helix-core v1.0 is done when:

**Setup**
- [ ] `python scripts/setup.py` completes on a clean machine: detects hardware, downloads selected model, writes `.env`
- [ ] Apple Silicon: setup correctly uses unified memory (not display VRAM) for model recommendation
- [ ] `--skip-download` flag configures without downloading

**Stack**
- [ ] `docker compose up` starts all services (llama-server, LiteLLM, Langfuse, Prometheus, Grafana) within 2 minutes (model pre-downloaded)
- [ ] LiteLLM health check passes: `GET http://localhost:4000/health` → 200
- [ ] llama-server health check passes: `GET http://localhost:8080/health` → 200

**Claude Code integration**
- [ ] `ANTHROPIC_BASE_URL=http://localhost:4000 claude` opens a session routing through LiteLLM → llama-server
- [ ] Tool calls work end-to-end: file read/write/edit and bash execution complete without errors
- [ ] Full agentic task completes: multi-file edit + bash command + follow-up
- [ ] Langfuse shows zero calls to `api.anthropic.com` — all traffic hits localhost

**Observability**
- [ ] Grafana dashboard shows live: tokens/sec, VRAM utilisation, TTFT, request queue depth
- [ ] Langfuse captures full trace for each Claude Code session (prompt, completion, tool calls, latency)

**Models**
- [ ] All 6 reference model YAML configs validated end-to-end (correct context, no truncation errors)
- [ ] Community PR template exists in `models/community/`

**Smoke test**
- [ ] `python scripts/check.py` passes on a clean install: LiteLLM live, tool call succeeds, Langfuse trace written

- [ ] agentdx-bridge polls Langfuse, runs `Diagnoser.diagnose()`, pathology detections appear in Grafana AgentDx panel
- [ ] `AGENTDX_ENABLED=false docker compose up` starts cleanly without the bridge
- [ ] `helix cloud init` provisions a GCP L4 Spot VM and returns a working `ANTHROPIC_BASE_URL`
- [ ] `helix cloud init` provisions a RunPod pod and returns a working `ANTHROPIC_BASE_URL`
- [ ] `helix setup`, `helix check`, `helix cloud init` all work via the CLI entrypoint
