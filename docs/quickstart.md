# Quickstart — zero to agentic session

Get Claude Code running against a local model in under 10 minutes.

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | For `scripts/setup.py` and `scripts/check.py` |
| Docker + Docker Compose | Stack runs in containers |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| GPU (optional) | NVIDIA with 8GB+ VRAM, or Apple Silicon, or CPU-only |
| NVIDIA Container Toolkit | Linux GPU mode only — [install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) |

## Step 1 — Clone and set up

```bash
git clone https://github.com/mldeepsystems/helix-core.git
cd helix-core
python scripts/setup.py
```

`setup.py` will:
1. Detect your GPU / Apple Silicon / CPU
2. Recommend a model based on available VRAM
3. Download the GGUF model file from HuggingFace
4. Write a `.env` file with all required configuration

To skip the download (configure only):
```bash
python scripts/setup.py --skip-download
```

To select a specific model non-interactively:
```bash
python scripts/setup.py --model qwen2.5-coder-7b --skip-download
```

## Step 2 — Start the stack

**GPU (Linux / WSL2):**
```bash
docker compose up -d
```

**CPU only (any machine):**
```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d
```

**Apple Silicon (macOS):**

First, start llama-server natively (Metal):
```bash
llama-server \
  --model /path/to/model.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 32768 \
  --n-gpu-layers 99 \
  --tool-call-parser qwen2_5 \
  --jinja
```

Then start the proxy + observability stack:
```bash
docker compose -f docker-compose.mac.yml up -d
```

## Step 3 — Verify the stack

```bash
python scripts/check.py
# or: ./scripts/helix check
```

All 5 checks should pass:
- `✓  llama-server health`
- `✓  LiteLLM proxy health`
- `✓  Tool-use request`
- `✓  Langfuse trace store`
- `✓  ANTHROPIC_BASE_URL points to localhost`

## Step 4 — Point Claude Code at the local stack

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_AUTH_TOKEN=sk-helix-local
claude
```

That's it. Every Claude Code session now routes through your local model. Zero tokens sent to Anthropic.

## Step 5 — Observe

| Service | URL | What it shows |
|---|---|---|
| Grafana | http://localhost:3000 | tokens/sec, TTFT, KV cache, request queue |
| Langfuse | http://localhost:3002 | Full session traces: prompts, completions, tool calls |
| Prometheus | http://localhost:9090 | Raw metrics |

Default Grafana login: `admin` / `helix-local` (set `GRAFANA_ADMIN_PASSWORD` in `.env` to change).

## Optional — AgentDx pathology detection

Start the bridge alongside the main stack:
```bash
docker compose --profile agentdx up -d
```

The AgentDx panel in Grafana will populate as sessions complete.

## Stopping

```bash
docker compose down
```

To also remove all stored data (Langfuse traces, Prometheus metrics):
```bash
docker compose down -v
```

## Troubleshooting

**`docker compose config` fails** — check that `.env` exists and is populated. Run `python scripts/setup.py --skip-download`.

**llama-server health check times out** — model loading can take 30–90 seconds for large models. Wait and retry.

**LiteLLM returns 422** — the `litellm/config.yaml` requires `drop_params: true` and `modify_params: true`. These are already set; if you've edited the config, verify those keys are present.

**Tool calls not working** — llama-server requires `--jinja` for tool calling. This flag is set in `docker-compose.yml`. If running natively on Mac, ensure you include `--jinja` in your llama-server command.

**Model not found** — `MODEL_PATH` in `.env` must be the absolute path to your GGUF file. Run `python scripts/setup.py` to regenerate.
