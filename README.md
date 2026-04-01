<p align="center">
  <h1 align="center">helix-core</h1>
  <p align="center">
    Run Claude Code with local models. Zero API costs. Fully private.
  </p>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> &middot;
  <a href="#how-it-works">How it works</a> &middot;
  <a href="#models">Models</a> &middot;
  <a href="docs/quickstart.md">Docs</a>
</p>

---

Claude Code is the best agentic coding tool that exists today. It edits files, runs commands, uses tools, handles multi-step tasks — all from your terminal.

But every session hits `api.anthropic.com`. Your code leaves your machine. Every token costs money. There's no way to observe what's happening under the hood.

**helix-core fixes all of that with one command.**

```bash
git clone https://github.com/mldeepsystems/helix-core.git && cd helix-core
./scripts/helix
```

That's it. It detects your hardware, downloads the right model, spins up every service, and drops you into Claude Code — running against a local LLM on your own machine. No API key. No cloud calls. No config files to hand-edit. Nothing leaves your network.

---

## What you get

- **Full Claude Code agentic capability** — file edits, bash execution, tool use, multi-step tasks. The exact same workflow, running locally.
- **Zero token cost** — the model runs on your hardware. No API billing.
- **Complete privacy** — your code never leaves your machine. Zero calls to `api.anthropic.com`.
- **Built-in observability** — every session traced in Langfuse. GPU metrics and inference stats in Grafana. Agent pathology detection via AgentDx.
- **One command** — `helix` handles hardware detection, model download, container orchestration, health checks, and Claude Code launch. You type one word.

---

## Quickstart

### Prerequisites

- Python 3.10+
- [Docker](https://docs.docker.com/get-docker/)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) — `npm install -g @anthropic-ai/claude-code`
- A GPU with 8GB+ VRAM (NVIDIA or Apple Silicon) — or no GPU at all (CPU mode works too, just slower)

### Install and run

```bash
git clone https://github.com/mldeepsystems/helix-core.git
cd helix-core
./scripts/helix
```

That's the whole install. `helix` will:

1. Check prerequisites (Docker, Python, Claude Code CLI)
2. Detect your GPU and available VRAM
3. Pick the best model for your hardware
4. Download it from HuggingFace (~5-43 GB depending on model)
5. Write all configuration
6. Start the Docker Compose stack (LiteLLM proxy, llama-server, Langfuse, Grafana, Prometheus)
7. Wait for every service to be healthy
8. Run an end-to-end smoke test
9. Launch Claude Code, pointed at your local model

On subsequent runs, if the stack is already up, `helix` skips straight to launching Claude Code in about 2 seconds.

### CLI

```bash
helix              # Auto-setup + start + launch Claude Code
helix up            # Start the stack (without launching Claude)
helix down          # Stop everything
helix status        # Check service health
helix setup         # Interactive setup (pick model, mode, etc.)
helix check         # Run the smoke test suite
```

---

## How it works

```
Claude Code CLI
      |  ANTHROPIC_BASE_URL=http://localhost:4000
      v
LiteLLM proxy  :4000   <-- translates Anthropic --> OpenAI format
      |
      v
llama-server   :8080   <-- inference (llama.cpp, any GGUF model)
      |
      |---> Langfuse    :3002   <-- session traces
      |---> Prometheus  :9090   <-- metrics
      +---> Grafana     :3000   <-- dashboards
```

Claude Code is hardwired to call `api.anthropic.com` using the Anthropic SDK format (`/v1/messages`). Local models speak the OpenAI format (`/v1/chat/completions`). These are incompatible — a direct connection returns 404.

helix-core puts a **LiteLLM proxy** in the middle that translates between the two wire formats in real time. Claude Code thinks it's talking to Anthropic. llama-server thinks it's getting standard OpenAI requests. Neither knows the other exists.

Two environment variables make it work:

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_AUTH_TOKEN=sk-helix-local
```

`helix` sets these automatically when it launches Claude Code.

---

## Models

helix-core ships with 6 pre-configured models. `setup.py` detects your hardware and recommends the best one automatically.

| Model | VRAM | Download | Best for |
|---|---|---|---|
| Qwen2.5-Coder 7B | 8 GB | ~4.7 GB | Entry point, laptops |
| Qwen2.5-Coder 14B | 16 GB | ~9 GB | Balanced performance |
| **Qwen2.5-Coder 32B** | **24 GB** | **~19.8 GB** | **Reference config** |
| DeepSeek-R1 70B | 48 GB | ~42.5 GB | Reasoning tasks |
| Llama 3.3 70B | 48 GB | ~42.5 GB | General purpose |
| Qwen2.5-Coder 7B (CPU) | None | ~4.7 GB | No GPU required |

All models use Q4_K_M quantization (GGUF format). Community-contributed model configs welcome in `models/community/`.

Full hardware recommendations: [docs/model-matrix.md](docs/model-matrix.md)

---

## Deployment modes

helix-core runs on everything from a MacBook to a multi-GPU server.

### GPU — Linux / WSL2

```bash
helix  # auto-detects NVIDIA GPU, handles everything
```

Requires NVIDIA Container Toolkit for GPU passthrough.

### Apple Silicon — macOS

```bash
helix  # auto-detects Apple Silicon, uses Metal acceleration
```

llama-server runs natively on Metal (not in Docker). The proxy and observability stack run in Docker. `helix` handles both.

### CPU only — any machine

```bash
helix  # auto-detects no GPU, falls back to CPU mode
```

Slower, but it works. Good for trying things out.

---

## Observability

Every service in the stack is observable out of the box. No configuration needed.

| Service | URL | What it shows |
|---|---|---|
| **Grafana** | http://localhost:3000 | tokens/sec, TTFT, KV cache utilization, request queue, AgentDx pathology panel |
| **Langfuse** | http://localhost:3002 | Full session traces — every prompt, completion, tool call, and latency breakdown |
| **Prometheus** | http://localhost:9090 | Raw metrics from llama-server, LiteLLM, and AgentDx bridge |

Grafana comes with pre-built dashboards. Langfuse captures traces automatically via the official Claude Code integration.

### AgentDx pathology detection

[AgentDx](https://pypi.org/project/agentdx/) detects failure patterns in agent behavior — context erosion, tool thrashing, instruction drift, goal hijacking, hallucinated tool success, and more. The helix-core bridge sidecar polls Langfuse traces, runs detection, and surfaces results in Grafana.

```bash
docker compose --profile agentdx up -d
```

---

## Project structure

```
helix-core/
├── scripts/
│   ├── helix                    CLI entrypoint
│   ├── start.py                 Zero-friction orchestrator
│   ├── setup.py                 Hardware detection + model download + config
│   ├── check.py                 Smoke test (5 checks)
│   └── validate.py              Full end-to-end validation
├── docker-compose.yml           GPU stack (Linux / WSL2)
├── docker-compose.cpu.yml       CPU offload override
├── docker-compose.mac.yml       Apple Silicon variant
├── litellm/
│   ├── config.yaml              Anthropic → OpenAI routing
│   ├── config.mac.yaml          Mac variant (host.docker.internal)
│   └── strip_schema_patterns.py Custom callback for schema compatibility
├── models/
│   ├── *.yaml                   Per-model configs
│   └── community/               Community-contributed configs
├── agentdx_bridge/              Langfuse → AgentDx → Prometheus sidecar
├── grafana/dashboards/          Pre-built Grafana dashboards
├── prometheus/prometheus.yml    Scrape configuration
├── tests/                       366 tests across 6 stages
└── docs/                        Quickstart, model matrix, cloud setup
```

---

## Architecture decisions

This isn't a prototype. Every design choice was validated with spike tests before writing a line of production code.

- **LiteLLM as translation layer** — confirmed via `spikes/wire_format_spike.py`. Anthropic SDK sends `/v1/messages` with `input_schema` tool schemas. llama-server only accepts `/v1/chat/completions` with `function.parameters`. Direct connection returns 404. LiteLLM bridges the gap.
- **llama.cpp as inference backend** — runs any GGUF model. `--jinja` flag required for tool calling (without it, tool schemas are silently ignored). One binary, no framework dependencies.
- **Langfuse v2 over v3** — v3 requires 6 containers (ClickHouse, Redis, MinIO). v2 requires 2 (server + Postgres). Same trace capture for this use case.
- **Schema pattern stripping** — llama-server rejects unanchored regex patterns in JSON schemas. Claude Code's built-in tool schemas have them. A custom LiteLLM callback strips these before they hit the model.
- **No shared Python modules between scripts** — each script (`setup.py`, `check.py`, `start.py`, `validate.py`) uses stdlib only and runs standalone. No `pip install` required. No import path management. Copy the repo and it works.

---

## Docs

- [Quickstart](docs/quickstart.md) — zero to running in under 10 minutes
- [Model Matrix](docs/model-matrix.md) — hardware recommendations, context windows, parsers
- [Cloud Setup](docs/cloud-setup.md) — cloud GPU provisioning (coming in v1.1)
- [Scope & Requirements](SCOPE.md) — full technical specification

---

## Contributing

Community model configs are welcome. See `models/community/README.md` for the template.

## License

See LICENSE for details.
