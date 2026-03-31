# Model Compatibility Matrix

All reference models use Q4_K_M quantization (GGUF format, llama.cpp backend).

## Reference Models

| Model Key | Display Name | VRAM | Context | Download | tool_call_parser | Notes |
|---|---|---|---|---|---|---|
| `qwen2.5-coder-7b` | Qwen2.5-Coder 7B | 8 GB | 32K | ~4.7 GB | `qwen2_5` | Entry point |
| `qwen2.5-coder-14b` | Qwen2.5-Coder 14B | 16 GB | 32K | ~9 GB | `qwen2_5` | Balanced |
| `qwen2.5-coder-32b` | Qwen2.5-Coder 32B | 24 GB | 32K | ~19.8 GB | `qwen2_5` | **Reference config** |
| `deepseek-r1-70b` | DeepSeek-R1 70B | 48 GB | 64K | ~42.5 GB | `deepseek` | Reasoning |
| `llama-3.3-70b` | Llama 3.3 70B | 48 GB | 128K | ~42.5 GB | `llama3_json` | General |
| `qwen2.5-coder-7b-cpu` | Qwen2.5-Coder 7B (CPU) | None | 16K | ~4.7 GB | `qwen2_5` | CPU offload |

HuggingFace repos: all from [bartowski](https://huggingface.co/bartowski).

## Hardware Recommendations

| Hardware | Recommended Model |
|---|---|
| Apple Silicon 16 GB | `qwen2.5-coder-7b` |
| Apple Silicon 32 GB | `qwen2.5-coder-14b` |
| Apple Silicon 64 GB+ | `qwen2.5-coder-32b` |
| NVIDIA 8 GB VRAM | `qwen2.5-coder-7b` |
| NVIDIA 16 GB VRAM | `qwen2.5-coder-14b` |
| NVIDIA 24 GB VRAM | `qwen2.5-coder-32b` |
| NVIDIA 48 GB+ VRAM | `deepseek-r1-70b` or `llama-3.3-70b` |
| No GPU | `qwen2.5-coder-7b-cpu` |

`setup.py` detects your hardware and selects the recommended model automatically.

## Performance Targets

Measured on reference hardware (NVIDIA L4, 24 GB VRAM):

| Model | TTFT | Throughput |
|---|---|---|
| Qwen2.5-Coder 32B Q4_K_M | < 3s | ≥ 15 tokens/sec |

## Model YAML Config

Each model has a YAML config in `models/` with fields consumed by `setup.py` and `docker-compose.yml`:

```yaml
model_key: qwen2.5-coder-32b
context_length: 32768
n_gpu_layers: 99          # 0 for CPU offload
tool_call_parser: qwen2_5 # must match model family
hf_repo: bartowski/Qwen2.5-Coder-32B-Instruct-GGUF
hf_filename: Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf
```

## Community Models

Community-contributed configs live in `models/community/`. See `models/community/README.md` for the contribution template and required fields.

Key constraint: `tool_call_parser` must exactly match the model family — wrong value causes silent tool call failures with no error message.

| Model Family | tool_call_parser |
|---|---|
| Qwen2.x | `qwen2_5` |
| DeepSeek | `deepseek` |
| Llama 3.x | `llama3_json` |
| Mistral | `mistral` |
