# Cloud Setup — GCP + RunPod

> **Status: deferred to v1.1**
>
> Cloud GPU provisioning ships as a follow-on milestone after the local stack
> (Modes 1–3) is validated. The `helix cloud init` command currently prints
> this message and exits.

## Planned: `helix cloud init`

When shipped, `helix cloud init` will provision a cloud GPU and return a
working `ANTHROPIC_BASE_URL` in one command.

### GCP flow (planned)

1. Check `gcloud` CLI installed
2. `gcloud auth login` (opens browser)
3. Prompt: project ID, region, instance name
4. Prompt: model selection from the model matrix
5. Provision L4 Spot VM (~$0.40/hr) with Docker + NVIDIA drivers + helix-core
6. Wait for health check to pass
7. Print: `export ANTHROPIC_BASE_URL=http://<external-ip>:4000`

Target instance: `n1-standard-4` + L4 GPU, Spot pricing, `us-central1`.
Estimated cost: ~INR 35/hr for Spot L4.

### RunPod flow (planned)

1. Prompt for RunPod API key
2. Prompt: GPU type (L4, A100 40GB, A100 80GB), model
3. Deploy pod via RunPod API with helix-core Docker image
4. Wait for pod to be ready
5. Print: `export ANTHROPIC_BASE_URL=http://<pod-endpoint>:4000`

Both flows will print estimated cost per hour and require explicit confirmation before provisioning.

## In the meantime

You can run helix-core on a cloud GPU manually:

1. Provision a VM with an NVIDIA GPU (L4 recommended for cost/performance)
2. Install Docker, NVIDIA Container Toolkit, and clone this repo
3. Run `python scripts/setup.py` on the VM
4. Run `docker compose up -d`
5. Open port 4000 in your firewall (restrict to your IP)
6. Set `export ANTHROPIC_BASE_URL=http://<vm-ip>:4000` locally

See the [quickstart](quickstart.md) for the full setup flow.
