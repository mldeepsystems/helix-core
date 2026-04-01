# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in helix-core, please report it responsibly.

**Email:** security@mldeep.io

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and aim to release a fix within 7 days for critical issues.

## Scope

helix-core is designed for **local deployment** — all services run on your machine or private network. The following are in scope:

- Secrets leaked in committed files or logs
- Container escape or privilege escalation
- Unauthorized access to Langfuse traces or Grafana dashboards
- Code injection via model configs or environment variables

## Security design

- **No external API calls** — Claude Code traffic stays on localhost. Zero calls to `api.anthropic.com`.
- **Secrets generated locally** — Langfuse encryption keys and salts are generated via `openssl rand` during setup and stored only in `.env` (gitignored).
- **No default passwords in production** — setup.py generates unique secrets on first run. Default passwords (`helix-local`, `langfuse-local`) are for development only.
- **Docker network isolation** — services communicate over an internal Docker network. Only proxy ports (4000) and observability ports (3000, 3002, 9090) are exposed to the host.
- **Non-root containers** — the agentdx-bridge runs as a non-root user inside the container.

## What helix-core does NOT protect against

- Malicious GGUF model files — helix-core downloads models from HuggingFace. Verify model integrity independently.
- Network-level attacks if you expose ports beyond localhost.
- Vulnerabilities in upstream dependencies (llama.cpp, LiteLLM, Langfuse, Grafana, Prometheus).

## Supported versions

Security fixes are applied to the latest release on `main`. There are no LTS branches.
