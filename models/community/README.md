# Community Model Configs

Community-contributed YAML configurations for models not in the reference set.

## Contributing

1. Fork the repo and create a branch: `community/<model-name>`
2. Copy the template below into `models/community/<your-model-key>.yaml`
3. Fill in all required fields — see the reference configs in `models/` for examples
4. Test it: run `python scripts/setup.py --model <your-model-key>` and confirm
   `docker compose up` starts and tool calls work end-to-end
5. Open a PR with the title: `community: add <model-name> config`

## Required Fields

Every community config must include these fields:

```yaml
model_key:          # unique key used with --model flag
display_name:       # human-readable name shown in setup menu
hf_repo:            # HuggingFace repo, e.g. bartowski/ModelName-GGUF
hf_filename:        # exact filename in the repo
quantization:       # e.g. Q4_K_M, Q5_K_M, Q8_0
size_gb:            # approximate download size
vram_required_gb:   # minimum VRAM for full GPU offload
context_length:     # context window in tokens
n_gpu_layers:       # 99 for full GPU, 0 for CPU only
tool_call_parser:   # qwen2_5 | deepseek | llama3_json | mistral
temperature:        # sampling temperature
repeat_penalty:     # repetition penalty
stop_tokens:        # list of stop strings for this model family
```

## Template

```yaml
model_key: your-model-key
display_name: "Your Model Name (Q4_K_M)"
hf_repo: username/ModelName-GGUF
hf_filename: ModelName-Q4_K_M.gguf
quantization: Q4_K_M
size_gb: 0.0
vram_required_gb: 0
context_length: 32768
n_gpu_layers: 99
tool_call_parser: qwen2_5
temperature: 0.7
repeat_penalty: 1.1
stop_tokens:
  - "<|endoftext|>"
```

## Notes

- Only GGUF format models are supported (llama.cpp backend)
- `tool_call_parser` must match the model family — wrong parser = silent tool call failures
- Community configs are not tested by CI; they are accepted on a best-effort basis
- Reference configs in `models/*.yaml` are the canonical validated configs
