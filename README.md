# helix-core

Run Claude Code against a local or cloud-hosted LLM — zero token cost, fully private.

helix-core is a Docker Compose stack that intercepts Claude Code CLI's API calls and routes them through a local model via a LiteLLM proxy. Full Claude Code agentic capability (file edits, bash, tool use, multi-step tasks) against a model you control.

```
Claude Code CLI
      │  ANTHROPIC_BASE_URL=http://localhost:4000
      ▼
LiteLLM proxy  :4000   ← translates Anthropic → OpenAI format
      │
      ▼
llama-server   :8080   ← inference (llama.cpp, any GGUF model)
      │
      ├─► Langfuse    :3002   ← session traces
      ├─► Prometheus  :9090   ← metrics
      └─► Grafana     :3000   ← dashboard
```

## Quickstart

```bash
git clone https://github.com/mldeepsystems/helix-core.git
cd helix-core

# Detect hardware, download model, write .env
python scripts/setup.py

# Start the stack
docker compose up -d

# Verify everything works
./scripts/helix check

# Point Claude Code at the local stack
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_AUTH_TOKEN=sk-helix-local
claude
```

→ Full setup guide: [docs/quickstart.md](docs/quickstart.md)

## Models

| Model | VRAM | Context | Notes |
|---|---|---|---|
| Qwen2.5-Coder 7B | 8 GB | 32K | Entry point |
| Qwen2.5-Coder 14B | 16 GB | 32K | Balanced |
| Qwen2.5-Coder 32B | 24 GB | 32K | Reference config |
| DeepSeek-R1 70B | 48 GB | 64K | Reasoning |
| Llama 3.3 70B | 48 GB | 128K | General |
| Qwen2.5-Coder 7B CPU | None | 16K | CPU offload |

`setup.py` detects your hardware and recommends the best fit automatically.

→ Full matrix: [docs/model-matrix.md](docs/model-matrix.md)

## Deployment modes

**GPU (Linux / WSL2)**
```bash
docker compose up -d
```

**CPU only**
```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d
```

**Apple Silicon (macOS)**
```bash
# llama-server runs natively on Metal — start it first
llama-server --model /path/to/model.gguf --host 0.0.0.0 --port 8080 \
  --ctx-size 32768 --n-gpu-layers 99 --tool-call-parser qwen2_5 --jinja

# Then start proxy + observability in Docker
docker compose -f docker-compose.mac.yml up -d
```

## Observability

After `docker compose up -d`:

| Service | URL | What it shows |
|---|---|---|
| Grafana | http://localhost:3000 | tokens/sec, TTFT, KV cache, request queue, AgentDx |
| Langfuse | http://localhost:3002 | Session traces: prompts, completions, tool calls |
| Prometheus | http://localhost:9090 | Raw metrics |

## AgentDx pathology detection (optional)

[AgentDx](https://mldeep.io) detects 9 failure pathologies in agent traces (context erosion, tool thrashing, instruction drift, etc.). The bridge sidecar polls Langfuse, runs detection, and surfaces results in Grafana.

```bash
docker compose --profile agentdx up -d
```

## CLI reference

```bash
./scripts/helix setup              # Detect hardware, download model, write .env
./scripts/helix check              # Smoke test: verify full stack is working
./scripts/helix cloud init         # Provision cloud GPU (GCP / RunPod) — v1.1
```

## Repository structure

```
helix-core/
├── docker-compose.yml           — GPU stack (Linux / WSL2)
├── docker-compose.cpu.yml       — CPU offload override
├── docker-compose.mac.yml       — Apple Silicon (llama-server native)
├── litellm/
│   ├── config.yaml              — Anthropic → OpenAI routing (GPU/CPU)
│   └── config.mac.yaml          — Routing for Mac (host.docker.internal)
├── models/
│   ├── qwen2.5-coder-*.yaml     — Model configs (context, parser, GPU layers)
│   ├── deepseek-r1-70b.yaml
│   ├── llama-3.3-70b.yaml
│   └── community/               — Community-contributed configs
├── prometheus/prometheus.yml    — Scrape config
├── grafana/dashboards/          — Pre-built dashboard JSON
├── agentdx_bridge/              — Langfuse → agentdx → Prometheus sidecar
├── scripts/
│   ├── setup.py                 — Hardware detection + model download + .env
│   ├── check.py                 — Smoke test
│   └── helix                    — CLI entrypoint
├── spikes/
│   └── wire_format_spike.py     — Confirmed Anthropic↔OpenAI incompatibility
├── tests/                       — pytest suite (301 tests across 5 stages)
├── docs/
│   ├── quickstart.md            — Zero to running agentic session
│   ├── model-matrix.md          — VRAM requirements, context windows, parsers
│   └── cloud-setup.md           — Cloud GPU setup (v1.1)
└── SCOPE.md                     — Full product and technical specification
```

## How it works

Claude Code is hardwired to call `api.anthropic.com`. helix-core intercepts this by:

1. **LiteLLM proxy** (port 4000) — accepts Anthropic SDK format (`/v1/messages` with `input_schema` tool schemas), translates to OpenAI format (`/v1/chat/completions` with `function.parameters`), forwards to llama-server
2. **llama-server** (port 8080) — llama.cpp inference server with `--jinja` flag for tool calling support
3. **Langfuse v2** (port 3002) — captures every session via the official Claude Code ↔ Langfuse integration

The wire format incompatibility was confirmed by `spikes/wire_format_spike.py` (Anthropic SDK sends to `/v1/messages` with `input_schema`; llama-server only accepts `/v1/chat/completions` with `function.parameters`). LiteLLM is the translation layer.

## Docs

- [Quickstart](docs/quickstart.md)
- [Model Matrix](docs/model-matrix.md)
- [Cloud Setup](docs/cloud-setup.md) — v1.1
- [Scope & Requirements](SCOPE.md)
