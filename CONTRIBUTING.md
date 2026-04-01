# Contributing to helix-core

We welcome contributions. Here's how to get involved.

## Getting started

```bash
git clone https://github.com/mldeepsystems/helix-core.git
cd helix-core
python scripts/setup.py --skip-download   # configure without downloading a model
```

## Running tests

```bash
pip install pytest pyyaml
python -m pytest tests/ -v
```

The test suite has 366 tests across 6 stages. All tests must pass before submitting a PR.

## What to work on

Check [TODO.md](TODO.md) for known issues organized by priority (P0/P1/P2). Issues labeled `good first issue` on GitHub are a good starting point.

## Adding a model config

Community model configs live in `models/community/`. See `models/community/README.md` for the template and required fields.

Key constraint: `tool_call_parser` must exactly match the model family — wrong value causes silent tool call failures.

| Model Family | tool_call_parser |
|---|---|
| Qwen 2.x | `qwen2_5` |
| DeepSeek | `deepseek` |
| Llama 3.x | `llama3_json` |
| Mistral | `mistral` |

## Submitting changes

1. Fork the repo and create a branch from `main`.
2. Make your changes. Add tests if you're adding new functionality.
3. Run the full test suite: `python -m pytest tests/ -v`
4. Submit a pull request. Describe what changed and why.

## Code style

- Python: stdlib only for all scripts in `scripts/`. No external dependencies.
- Shell: bash, `set -euo pipefail`.
- No unnecessary abstractions. Three similar lines are better than a premature helper function.
- Comments only where the logic isn't self-evident.

## Reporting bugs

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Your hardware (GPU, VRAM, OS)
- Output of `helix status`
