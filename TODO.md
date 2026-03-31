# helix-core — open issues and next steps

Last updated: 2026-04-01 (after first live E2E validation on Apple Silicon M4 48GB)

## Current state

helix-core is **validated and working** end-to-end on Apple Silicon:

```
llama-server (Metal, Qwen2.5-Coder 7B) → LiteLLM proxy → Claude Code CLI
```

Supporting services running: Langfuse (traces), Prometheus (metrics), Grafana (dashboards).

Claude Code responds to prompts routed through the local model. Zero tokens sent to Anthropic.

---

## Bugs to fix

### P0 — breaks functionality

1. **`docker-compose.yml` (Linux) missing `--override-kv` and `--parallel 1`**
   - Linux llama-server container still uses `--ctx-size ${CONTEXT_LENGTH}` without the GGUF metadata override
   - Will hit the same 32K context cap we hit on Mac
   - Fix: add `--parallel 1 --override-kv ${GGUF_ARCH}.context_length=int:${CONTEXT_LENGTH}` to the llama-server command in docker-compose.yml
   - Need to add `GGUF_ARCH` to `.env.example` and `setup.py` output

2. **`setup.py` does not validate downloaded file size**
   - If download is interrupted (Ctrl+C), the truncated file passes the existence check
   - Next run skips download: "Model already downloaded"
   - Fix: compare actual file size against `size_gb` from model YAML (within ~5% tolerance)

3. **Tests out of date with runtime changes**
   - `test_stage1_configs.py`: model YAMLs now have `gguf_arch` field and `context_length: 131072` — tests hardcode old values (32768)
   - `test_stage6_docs.py`: VRAM/context values hardcoded for 32K — need updating
   - `test_stage2_compose.py`: compose files changed (health check URL, volume mounts, Grafana port)

### P1 — usability issues

4. **Grafana port inconsistency in docs**
   - `docker-compose.mac.yml` defaults to 3001 (Docker Desktop takes 3000)
   - `docs/quickstart.md` and `README.md` still say `http://localhost:3000`
   - `validate.py` final summary says 3000
   - Fix: update docs and validate.py to use `${GRAFANA_PORT}` or document Mac vs Linux difference

5. **`validate.py` does not auto-start llama-server on Mac**
   - Currently prints the command and waits for user to start it manually
   - Could auto-start in background with `subprocess.Popen` and log to `/tmp/llama-server.log`
   - Lower priority — manual start gives user visibility into model loading

6. **NVIDIA Container Toolkit warning on Mac**
   - `setup.py` warns about missing NVIDIA toolkit on Apple Silicon — irrelevant
   - Fix: skip the check when `platform.machine() == "arm64"` and `platform.system() == "Darwin"`

### P2 — nice to have

7. **`add_function_to_prompt` / `model_info.supports_function_calling` have no effect**
   - We tried both in LiteLLM config — tools are still forwarded to llama-server regardless
   - The `strip_schema_patterns` callback works but is a workaround
   - Investigate: may be a LiteLLM bug or the OpenAI provider ignoring these settings

8. **Model quality at 4x context extension**
   - Qwen2.5-Coder 7B trained on 32K, we run at 131K via `--override-kv`
   - Quality likely degrades for tokens beyond the training window
   - Consider: YaRN RoPE scaling (`--rope-scaling yarn`) for better extrapolation

9. **Prompt processing time for large context**
   - 65K token prompt takes ~2-3 minutes on M4 to process
   - Every new Claude Code session pays this cost (no KV cache persistence between sessions)
   - Consider: llama-server `--cache-type-k q8_0` to reduce KV memory and speed up processing

---

## Next steps (in priority order)

### 1. Fix Linux docker-compose (P0)
- Add `GGUF_ARCH` env var to `.env.example` and `setup.py`
- Update `docker-compose.yml` llama-server command with `--parallel 1` and `--override-kv`
- Test with `docker compose config`

### 2. Fix setup.py download validation (P0)
- Add file size check after download and on "already downloaded" path
- Use `os.path.getsize()` vs `size_gb * 1e9` with tolerance

### 3. Update tests (P0)
- Run `pytest tests/` and fix all failures from the runtime changes
- Key changes: context_length 131072, gguf_arch field, health check URLs, Grafana port

### 4. Fix docs (P1)
- Update quickstart.md Grafana URL for Mac
- Update README.md observability table
- Update validate.py final summary to read GRAFANA_PORT from .env

### 5. Interactive Claude Code session test
- Actually use `claude` interactively against the local model
- Test: can it read files? Use tools? Handle multi-turn?
- Document what works and what doesn't with the 7B model

### 6. Try Qwen2.5-Coder 32B
- Download the 32B model (~20GB)
- Compare response quality and tool-use reliability vs 7B
- Your Mac has 48GB — should handle 32B Q4_K_M comfortably

---

## Files changed during validation (committed to main)

| Commit | Change |
|--------|--------|
| `d020a12` | Timeout on llama-server --version check |
| `8c2388c` | Use `which()` instead of `--version` for llama-server |
| `2dfad99` | Grafana port 3001 on Mac, remove --tool-call-parser |
| `7590dde` | LiteLLM health check → `/health/readiness` |
| `842d01e` | Remove master_key from LiteLLM config |
| `a7094e3` | Add `add_function_to_prompt` (ineffective, kept for ref) |
| `23705d9` | `strip_schema_patterns.py` callback for tool schemas |
| `068bad4` | Context 131072, gguf_arch field, --parallel 1, --override-kv |

## Working llama-server command (Mac reference)

```bash
llama-server \
  --model models/downloads/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 131072 \
  --n-gpu-layers 99 \
  --parallel 1 \
  --override-kv "qwen2.context_length=int:131072" \
  --jinja
```

## Working validation command

```bash
python3 scripts/validate.py --skip-setup --skip-compose --model qwen2.5-coder-7b
```
