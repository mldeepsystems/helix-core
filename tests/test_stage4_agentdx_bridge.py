"""
Stage 4 validation tests: AgentDx bridge — converter, Dockerfile, structure.

The converter is tested with fixture data (no agentdx/langfuse runtime needed).
Dockerfile and requirements are validated structurally.

Run:
  pytest tests/test_stage4_agentdx_bridge.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_DIR = REPO_ROOT / "agentdx_bridge"

# Inject bridge dir so we can import the converter directly
sys.path.insert(0, str(REPO_ROOT))


# ── Fixtures: Langfuse trace shapes ──────────────────────────────────────────

GENERATION_WITH_TOOL_USE = {
    "id": "trace-001",
    "sessionId": "session-abc",
    "name": "claude-code-session",
    "tags": [],
    "observations": [
        {
            "id": "obs-gen-1",
            "type": "GENERATION",
            "name": "llm-call",
            "startTime": "2026-03-31T10:00:00.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Read the file /tmp/test.txt"},
            ],
            "output": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll read that file for you."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "read_file",
                        "input": {"path": "/tmp/test.txt"},
                    },
                ],
            },
        },
        {
            "id": "obs-tool-1",
            "type": "TOOL",
            "name": "read_file",
            "startTime": "2026-03-31T10:00:01.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": {"path": "/tmp/test.txt"},
            "output": "hello world",
        },
        {
            "id": "obs-gen-2",
            "type": "GENERATION",
            "name": "llm-call-2",
            "startTime": "2026-03-31T10:00:02.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [
                {"role": "user", "content": "Read the file /tmp/test.txt"},
                {"role": "assistant", "content": "I'll read that file."},
                {"role": "tool", "content": "hello world"},
            ],
            "output": {"role": "assistant", "content": [
                {"type": "text", "text": "The file contains: hello world"}
            ]},
        },
    ],
}

GENERATION_WITH_ERROR_TOOL = {
    "id": "trace-002",
    "sessionId": "session-err",
    "name": "failing-session",
    "tags": [],
    "observations": [
        {
            "id": "obs-gen",
            "type": "GENERATION",
            "name": "llm",
            "startTime": "2026-03-31T10:00:00.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [{"role": "user", "content": "Delete /etc/passwd"}],
            "output": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "bash", "input": {"cmd": "rm /etc/passwd"}}
            ]},
        },
        {
            "id": "obs-tool-err",
            "type": "TOOL",
            "name": "bash",
            "startTime": "2026-03-31T10:00:01.000",
            "level": "ERROR",
            "statusMessage": "Permission denied",
            "input": {"cmd": "rm /etc/passwd"},
            "output": None,
        },
    ],
}

SIMPLE_TEXT_ONLY = {
    "id": "trace-003",
    "sessionId": "session-simple",
    "name": "simple",
    "tags": [],
    "observations": [
        {
            "id": "obs-1",
            "type": "GENERATION",
            "name": "llm",
            "startTime": "2026-03-31T10:00:00.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [{"role": "user", "content": "Say hello"}],
            "output": {"role": "assistant", "content": [{"type": "text", "text": "Hello!"}]},
        }
    ],
}

EMPTY_OBSERVATIONS = {
    "id": "trace-empty",
    "sessionId": "session-empty",
    "observations": [],
}

STRING_CONTENT = {
    "id": "trace-str",
    "sessionId": "session-str",
    "observations": [
        {
            "id": "obs-1",
            "type": "GENERATION",
            "name": "llm",
            "startTime": "2026-03-31T10:00:00.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [{"role": "user", "content": "ping"}],
            "output": "pong",  # string output (not dict)
        }
    ],
}

OUT_OF_ORDER_TIMESTAMPS = {
    "id": "trace-order",
    "sessionId": "session-order",
    "observations": [
        {
            "id": "obs-b",
            "type": "GENERATION",
            "name": "second",
            "startTime": "2026-03-31T10:00:02.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [{"role": "user", "content": "second"}],
            "output": {"role": "assistant", "content": [{"type": "text", "text": "B"}]},
        },
        {
            "id": "obs-a",
            "type": "GENERATION",
            "name": "first",
            "startTime": "2026-03-31T10:00:01.000",
            "level": "DEFAULT",
            "statusMessage": None,
            "input": [{"role": "user", "content": "first"}],
            "output": {"role": "assistant", "content": [{"type": "text", "text": "A"}]},
        },
    ],
}


# ── File structure ────────────────────────────────────────────────────────────

def test_bridge_init_exists():
    assert (BRIDGE_DIR / "__init__.py").exists()

def test_bridge_main_exists():
    assert (BRIDGE_DIR / "main.py").exists()

def test_bridge_converter_exists():
    assert (BRIDGE_DIR / "langfuse_converter.py").exists()

def test_bridge_dockerfile_exists():
    assert (BRIDGE_DIR / "Dockerfile").exists()

def test_bridge_requirements_exists():
    assert (BRIDGE_DIR / "requirements.txt").exists()


# ── requirements.txt ─────────────────────────────────────────────────────────

def test_requirements_has_agentdx():
    content = (BRIDGE_DIR / "requirements.txt").read_text()
    assert "agentdx" in content

def test_requirements_has_langfuse():
    content = (BRIDGE_DIR / "requirements.txt").read_text()
    assert "langfuse" in content

def test_requirements_has_prometheus_client():
    content = (BRIDGE_DIR / "requirements.txt").read_text()
    assert "prometheus_client" in content

def test_requirements_pins_langfuse_v2():
    """Must use langfuse v2 SDK (<3.0) matching the Langfuse v2 server."""
    content = (BRIDGE_DIR / "requirements.txt").read_text()
    assert "<3" in content or "2." in content, (
        "langfuse dependency must be pinned to v2 (<3.0) to match the server"
    )


# ── Dockerfile ────────────────────────────────────────────────────────────────

def test_dockerfile_uses_python_311():
    content = (BRIDGE_DIR / "Dockerfile").read_text()
    assert "python:3.11" in content or "python:3.12" in content, (
        "Dockerfile must use Python 3.11+"
    )

def test_dockerfile_installs_requirements():
    content = (BRIDGE_DIR / "Dockerfile").read_text()
    assert "requirements.txt" in content

def test_dockerfile_exposes_7700():
    content = (BRIDGE_DIR / "Dockerfile").read_text()
    assert "EXPOSE 7700" in content

def test_dockerfile_has_healthcheck():
    content = (BRIDGE_DIR / "Dockerfile").read_text()
    assert "HEALTHCHECK" in content

def test_dockerfile_has_non_root_user():
    content = (BRIDGE_DIR / "Dockerfile").read_text()
    assert "USER" in content, "Dockerfile should run as non-root user"

def test_dockerfile_cmd_runs_main():
    content = (BRIDGE_DIR / "Dockerfile").read_text()
    assert "main" in content


# ── main.py structure ─────────────────────────────────────────────────────────

def test_main_has_env_vars_documented():
    content = (BRIDGE_DIR / "main.py").read_text()
    for var in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
                "AGENTDX_POLL_INTERVAL", "METRICS_PORT"):
        assert var in content, f"main.py must reference env var: {var}"

def test_main_has_prometheus_metrics():
    content = (BRIDGE_DIR / "main.py").read_text()
    assert "agentdx_pathology_detections_total" in content
    assert "agentdx_health_score" in content

def test_main_has_cursor_persistence():
    content = (BRIDGE_DIR / "main.py").read_text()
    assert "cursor" in content.lower()

def test_main_has_poll_loop():
    content = (BRIDGE_DIR / "main.py").read_text()
    assert "poll" in content.lower()

def test_main_has_metrics_server():
    content = (BRIDGE_DIR / "main.py").read_text()
    assert "metrics" in content.lower() and ("7700" in content or "METRICS_PORT" in content)


# ── Converter: import ─────────────────────────────────────────────────────────

def test_converter_imports():
    from agentdx_bridge.langfuse_converter import convert  # noqa: F401


# ── Converter: empty observations → None ─────────────────────────────────────

def test_convert_empty_observations_returns_none():
    from agentdx_bridge.langfuse_converter import convert
    result = convert(EMPTY_OBSERVATIONS)
    assert result is None


# ── Converter: basic GENERATION → messages ───────────────────────────────────

def test_convert_simple_returns_trace():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    assert trace is not None

def test_convert_simple_trace_id():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    assert trace.trace_id == "trace-003"

def test_convert_simple_session_id():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    assert trace.session_id == "session-simple"

def test_convert_simple_has_user_message():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    roles = [m.role for m in trace.messages]
    assert "user" in roles

def test_convert_simple_has_assistant_message():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    roles = [m.role for m in trace.messages]
    assert "assistant" in roles

def test_convert_simple_user_content():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    user_msgs = [m for m in trace.messages if m.role == "user"]
    assert any("Say hello" in m.content for m in user_msgs)

def test_convert_simple_assistant_content():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(SIMPLE_TEXT_ONLY)
    assistant_msgs = [m for m in trace.messages if m.role == "assistant"]
    assert any("Hello" in m.content for m in assistant_msgs)


# ── Converter: GENERATION with tool_use → ToolCall ───────────────────────────

def test_convert_tool_use_trace_not_none():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    assert trace is not None

def test_convert_tool_use_has_system_message():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    roles = [m.role for m in trace.messages]
    assert "system" in roles

def test_convert_tool_use_assistant_has_tool_calls():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    assistant_msgs = [m for m in trace.messages if m.role == "assistant"]
    all_tool_calls = [tc for m in assistant_msgs for tc in m.tool_calls]
    assert len(all_tool_calls) > 0, "Expected ToolCall objects from tool_use blocks"

def test_convert_tool_call_name():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    assistant_msgs = [m for m in trace.messages if m.role == "assistant"]
    tool_names = [tc.tool_name for m in assistant_msgs for tc in m.tool_calls]
    assert "read_file" in tool_names

def test_convert_tool_call_input():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    assistant_msgs = [m for m in trace.messages if m.role == "assistant"]
    for m in assistant_msgs:
        for tc in m.tool_calls:
            if tc.tool_name == "read_file":
                assert tc.tool_input.get("path") == "/tmp/test.txt"
                return
    pytest.fail("read_file ToolCall not found")

def test_convert_tool_observation_produces_tool_message():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    roles = [m.role for m in trace.messages]
    assert "tool" in roles

def test_convert_tool_message_success_true():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    tool_msgs = [m for m in trace.messages if m.role == "tool"]
    assert all(tc.success for m in tool_msgs for tc in m.tool_calls)

def test_convert_tool_message_output():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    tool_msgs = [m for m in trace.messages if m.role == "tool"]
    assert any("hello world" in m.content for m in tool_msgs)


# ── Converter: error TOOL observation ────────────────────────────────────────

def test_convert_error_tool_success_false():
    """TOOL observation with level=ERROR must produce success=False."""
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_ERROR_TOOL)
    assert trace is not None
    tool_msgs = [m for m in trace.messages if m.role == "tool"]
    error_calls = [tc for m in tool_msgs for tc in m.tool_calls if not tc.success]
    assert len(error_calls) > 0, "Expected at least one failed ToolCall"

def test_convert_error_tool_error_message():
    """statusMessage must be mapped to error_message on failed ToolCall."""
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_ERROR_TOOL)
    tool_msgs = [m for m in trace.messages if m.role == "tool"]
    for m in tool_msgs:
        for tc in m.tool_calls:
            if not tc.success:
                assert tc.error_message == "Permission denied"
                return
    pytest.fail("No failed ToolCall with error_message found")


# ── Converter: step_index ordering ───────────────────────────────────────────

def test_convert_step_index_chronological():
    """Messages must be ordered by startTime regardless of observation order in input."""
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(OUT_OF_ORDER_TIMESTAMPS)
    assert trace is not None
    step_indices = [m.step_index for m in trace.messages]
    # step_indices should be non-decreasing (observations sorted by startTime)
    assert step_indices == sorted(step_indices), (
        f"Messages not in chronological order: {step_indices}"
    )

def test_convert_earlier_observation_lower_step_index():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(OUT_OF_ORDER_TIMESTAMPS)
    # obs-a (10:00:01) should come before obs-b (10:00:02)
    first_content = trace.messages[0].content if trace.messages else ""
    # The "first" observation (obs-a, startTime 10:00:01) should produce content "A"
    user_msgs = [m for m in trace.messages if m.role == "user"]
    assert user_msgs[0].content == "first", (
        f"First user message should be 'first' (earliest timestamp), got: {user_msgs[0].content!r}"
    )


# ── Converter: string output ──────────────────────────────────────────────────

def test_convert_string_output():
    """GENERATION output can be a plain string (not a dict)."""
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(STRING_CONTENT)
    assert trace is not None
    assistant_msgs = [m for m in trace.messages if m.role == "assistant"]
    assert len(assistant_msgs) > 0

def test_convert_string_output_content():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(STRING_CONTENT)
    assistant_msgs = [m for m in trace.messages if m.role == "assistant"]
    assert any("pong" in m.content for m in assistant_msgs)


# ── Converter: metadata ───────────────────────────────────────────────────────

def test_convert_metadata_has_observation_count():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    assert trace.metadata.get("observation_count") == 3

def test_convert_metadata_has_name():
    from agentdx_bridge.langfuse_converter import convert
    trace = convert(GENERATION_WITH_TOOL_USE)
    assert trace.metadata.get("name") == "claude-code-session"


# ── Converter helper: _content_to_str ────────────────────────────────────────

def test_content_to_str_none():
    from agentdx_bridge.langfuse_converter import _content_to_str
    assert _content_to_str(None) == ""

def test_content_to_str_string():
    from agentdx_bridge.langfuse_converter import _content_to_str
    assert _content_to_str("hello") == "hello"

def test_content_to_str_text_block():
    from agentdx_bridge.langfuse_converter import _content_to_str
    result = _content_to_str([{"type": "text", "text": "hello"}])
    assert result == "hello"

def test_content_to_str_tool_use_block():
    from agentdx_bridge.langfuse_converter import _content_to_str
    result = _content_to_str([{"type": "tool_use", "name": "bash"}])
    assert "tool_use" in result and "bash" in result

def test_content_to_str_mixed_blocks():
    from agentdx_bridge.langfuse_converter import _content_to_str
    result = _content_to_str([
        {"type": "text", "text": "Let me run"},
        {"type": "tool_use", "name": "bash", "input": {}},
    ])
    assert "Let me run" in result
