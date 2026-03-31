"""
Spike: Claude Code / Anthropic SDK ↔ llama-server wire format compatibility.

What this tests:
  1. What exact HTTP request does the Anthropic SDK send when ANTHROPIC_BASE_URL
     points at a local server? (path, headers, body schema)
  2. Does llama-server's /v1/chat/completions accept Anthropic-format tool-use requests?
  3. Where exactly does the format mismatch occur?

Run:
  python spikes/wire_format_spike.py

No llama-server required — we spin up a minimal capture server to log what the
Anthropic SDK sends, then compare to llama-server's expected OpenAI format.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

RESET = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[32m"
YELLOW = "\033[33m"; RED = "\033[31m"; CYAN = "\033[36m"

captured: dict = {}


# ── Minimal capture server ────────────────────────────────────────────────────

class CaptureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # silence default logging

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        captured["path"] = self.path
        captured["headers"] = dict(self.headers)
        try:
            captured["body"] = json.loads(body)
        except Exception:
            captured["body"] = body.decode()

        # Return a minimal valid Anthropic response so the SDK doesn't error
        response = json.dumps({
            "id": "msg_spike",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "spike captured"}],
            "model": "claude-sonnet-4-6",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def start_capture_server(port: int = 9999) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", port), CaptureHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ── Send Anthropic SDK request ────────────────────────────────────────────────

def send_anthropic_tool_use_request(base_url: str) -> dict:
    """Send a real tool-use request via the Anthropic SDK."""
    try:
        import anthropic
    except ImportError:
        print(f"{RED}✗{RESET}  anthropic SDK not installed: pip install anthropic")
        sys.exit(1)

    client = anthropic.Anthropic(
        api_key="spike-test-key",  # dummy key — our server doesn't validate
        base_url=base_url,
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        tools=[{
            "name": "read_file",
            "description": "Read a file from disk",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
        }],
        messages=[{
            "role": "user",
            "content": "Read the file /tmp/test.txt",
        }],
    )
    return response


# ── Analysis ──────────────────────────────────────────────────────────────────

OPENAI_FORMAT = {
    "path": "/v1/chat/completions",
    "body_key_messages": "messages",
    "tool_key": "tools",
    "tool_schema_key": "function",  # OpenAI: tools[].function.{name, description, parameters}
    "tool_call_role": "tool",       # OpenAI tool result role
}

def analyse(captured: dict) -> None:
    print(f"\n{BOLD}═══ Spike Results ═══{RESET}\n")

    if not captured:
        print(f"{RED}✗  Nothing captured — server may not have received the request{RESET}")
        return

    path = captured.get("path", "")
    body = captured.get("body", {})

    print(f"{BOLD}1. Request path{RESET}")
    print(f"   Anthropic SDK sent to:  {CYAN}{path}{RESET}")
    print(f"   llama-server expects:   {CYAN}/v1/chat/completions{RESET}")
    if path != "/v1/chat/completions":
        print(f"   {RED}✗  PATH MISMATCH{RESET} — llama-server will 404 this request")
    else:
        print(f"   {GREEN}✓  paths match{RESET}")

    print(f"\n{BOLD}2. Tool definition schema{RESET}")
    tools = body.get("tools", [])
    if tools:
        first_tool = tools[0]
        print(f"   Anthropic SDK sends:    {json.dumps(first_tool, indent=4)}")
        # OpenAI format wraps in .function
        if "input_schema" in first_tool:
            print(f"   {RED}✗  SCHEMA MISMATCH{RESET} — Anthropic uses 'input_schema', OpenAI uses 'function.parameters'")
        elif "function" in first_tool:
            print(f"   {GREEN}✓  OpenAI-compatible tool schema{RESET}")
    else:
        print(f"   {YELLOW}⚠  No tools in captured body — tool schema not tested{RESET}")

    print(f"\n{BOLD}3. Message format{RESET}")
    messages = body.get("messages", [])
    if messages:
        print(f"   Message roles present: {[m.get('role') for m in messages]}")
        # Check for Anthropic-specific content block format
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                print(f"   {YELLOW}⚠  Content is a list of blocks (Anthropic format), not a string{RESET}")
                break
        else:
            print(f"   {GREEN}✓  String content (OpenAI-compatible){RESET}")
    else:
        print(f"   {YELLOW}⚠  No messages in body{RESET}")

    print(f"\n{BOLD}4. Full captured body{RESET}")
    print(json.dumps(body, indent=2))

    print(f"\n{BOLD}5. Verdict{RESET}")
    issues = []
    if path and path != "/v1/chat/completions":
        issues.append(f"path is {path!r}, not /v1/chat/completions")
    if tools and "input_schema" in tools[0]:
        issues.append("tool schema uses Anthropic format (input_schema), not OpenAI (function.parameters)")

    if issues:
        print(f"\n  {RED}✗  INCOMPATIBLE — a proxy layer is required:{RESET}")
        for i in issues:
            print(f"     • {i}")
        print(f"""
  {BOLD}Recommended solution:{RESET} add LiteLLM proxy between Claude Code and llama-server.
  LiteLLM speaks both Anthropic and OpenAI format and handles the translation.

  Architecture change:
    Claude Code → LiteLLM proxy (Anthropic in, OpenAI out) → llama-server

  docker-compose.yml addition:
    litellm:
      image: ghcr.io/berriai/litellm:main-latest
      ports: ["4000:4000"]
      environment:
        - ANTHROPIC_API_KEY=dummy
      command: --model openai/local --api_base http://llama-server:8080/v1

  Then: ANTHROPIC_BASE_URL=http://localhost:4000

  LiteLLM is MIT-licensed, actively maintained, and handles this exact use case.
""")
    else:
        print(f"\n  {GREEN}✓  Compatible — direct connection works{RESET}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    PORT = 9999
    BASE_URL = f"http://127.0.0.1:{PORT}"

    print(f"\n{BOLD}helix-core spike: Anthropic SDK wire format{RESET}")
    print(f"{CYAN}Starting capture server on {BASE_URL}{RESET}")

    server = start_capture_server(PORT)

    # Point SDK at our capture server
    os.environ["ANTHROPIC_BASE_URL"] = BASE_URL

    print(f"Sending tool-use request via Anthropic SDK...\n")
    try:
        send_anthropic_tool_use_request(BASE_URL)
    except Exception as e:
        # Expected — our fake response may not satisfy full SDK validation
        # but the request was captured
        if not captured:
            print(f"{RED}✗  Request failed before capture: {e}{RESET}")
            sys.exit(1)

    server.shutdown()
    analyse(captured)


if __name__ == "__main__":
    main()
