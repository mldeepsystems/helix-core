"""
Langfuse TraceWithFullDetails → agentdx Trace/Message/ToolCall converter.

Spike 3 findings (SCOPE.md):
  - GENERATION observation input[] holds system/user messages (not separate observations)
  - GENERATION output → assistant Message; extract ToolCall from tool_use blocks
  - TOOL observation → tool Message (success = level != "ERROR")
  - Sort all observations by startTime → step_index
  - 80% of fields map directly; main work is message unpacking
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


# ── agentdx schema (imported at runtime; defined here as fallback dataclasses) ─

try:
    from agentdx.models import Message, ToolCall, Trace  # type: ignore[import]
    _AGENTDX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AGENTDX_AVAILABLE = False

    from dataclasses import dataclass, field

    @dataclass
    class ToolCall:  # type: ignore[no-redef]
        tool_name: str
        tool_input: dict = field(default_factory=dict)
        tool_output: str | None = None
        success: bool = True
        error_message: str | None = None
        step_index: int = 0

    @dataclass
    class Message:  # type: ignore[no-redef]
        role: str          # system | user | assistant | tool
        content: str
        step_index: int = 0
        tool_calls: list[ToolCall] = field(default_factory=list)

    @dataclass
    class Trace:  # type: ignore[no-redef]
        trace_id: str
        session_id: str
        messages: list[Message] = field(default_factory=list)
        metadata: dict = field(default_factory=dict)


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_time(ts: str | None) -> datetime:
    """Parse ISO-8601 timestamp from Langfuse into datetime."""
    if not ts:
        return datetime.min
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return datetime.min


def _content_to_str(content: Any) -> str:
    """Normalise Langfuse content to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "text":
                    parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    parts.append(f"[tool_use:{block.get('name','')}]")
                elif btype == "tool_result":
                    inner = block.get("content", "")
                    parts.append(_content_to_str(inner))
                else:
                    parts.append(str(block))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return json.dumps(content)
    return str(content)


def _extract_tool_calls(content: Any, step_index: int) -> list[ToolCall]:
    """Extract ToolCall objects from an assistant message's content blocks."""
    if not isinstance(content, list):
        return []
    calls = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        calls.append(ToolCall(
            tool_name=block.get("name", "unknown"),
            tool_input=block.get("input", {}),
            tool_output=None,   # filled in when matching TOOL observation
            success=True,
            error_message=None,
            step_index=step_index,
        ))
    return calls


# ── main converter ────────────────────────────────────────────────────────────

def convert(langfuse_trace: dict) -> Trace | None:
    """
    Convert a Langfuse TraceWithFullDetails dict to an agentdx Trace.

    Returns None if the trace has no observations worth analysing.
    """
    trace_id: str = langfuse_trace.get("id", "unknown")
    session_id: str = langfuse_trace.get("sessionId") or trace_id

    observations: list[dict] = langfuse_trace.get("observations", [])
    if not observations:
        log.debug("trace %s has no observations — skipping", trace_id)
        return None

    # Sort observations by startTime so step_index is chronological
    observations = sorted(observations, key=lambda o: _parse_time(o.get("startTime")))

    messages: list[Message] = []

    for step_index, obs in enumerate(observations):
        obs_type: str = (obs.get("type") or "").upper()
        level: str = obs.get("level", "DEFAULT")
        status_msg: str = obs.get("statusMessage") or ""

        if obs_type == "GENERATION":
            # ── unpack system/user messages from input array ──────────────────
            raw_input = obs.get("input")
            if isinstance(raw_input, list):
                for msg_block in raw_input:
                    if not isinstance(msg_block, dict):
                        continue
                    role = msg_block.get("role", "user")
                    content_str = _content_to_str(msg_block.get("content", ""))
                    if content_str:
                        messages.append(Message(
                            role=role,
                            content=content_str,
                            step_index=step_index,
                            tool_calls=[],
                        ))
            elif isinstance(raw_input, dict):
                role = raw_input.get("role", "user")
                content_str = _content_to_str(raw_input.get("content", ""))
                if content_str:
                    messages.append(Message(
                        role=role,
                        content=content_str,
                        step_index=step_index,
                        tool_calls=[],
                    ))

            # ── GENERATION output → assistant message + tool calls ────────────
            raw_output = obs.get("output")
            if raw_output is not None:
                output_content = raw_output
                # Langfuse may wrap in {"role": "assistant", "content": [...]}
                if isinstance(raw_output, dict) and "content" in raw_output:
                    output_content = raw_output["content"]

                tool_calls = _extract_tool_calls(output_content, step_index)
                content_str = _content_to_str(output_content)

                if content_str or tool_calls:
                    messages.append(Message(
                        role="assistant",
                        content=content_str,
                        step_index=step_index,
                        tool_calls=tool_calls,
                    ))

        elif obs_type == "TOOL":
            # ── TOOL observation → tool result message ────────────────────────
            success = level != "ERROR"
            raw_output = obs.get("output")
            output_str = _content_to_str(raw_output)

            tool_call = ToolCall(
                tool_name=obs.get("name", "unknown"),
                tool_input=obs.get("input") or {},
                tool_output=output_str,
                success=success,
                error_message=status_msg if not success else None,
                step_index=step_index,
            )
            messages.append(Message(
                role="tool",
                content=output_str,
                step_index=step_index,
                tool_calls=[tool_call],
            ))

        else:
            # SPAN, EVENT, or unknown — treat as a system annotation if it has output
            raw_output = obs.get("output")
            if raw_output is not None:
                content_str = _content_to_str(raw_output)
                if content_str:
                    messages.append(Message(
                        role="system",
                        content=f"[{obs.get('name', obs_type)}] {content_str}",
                        step_index=step_index,
                        tool_calls=[],
                    ))

    if not messages:
        log.debug("trace %s produced no messages after conversion — skipping", trace_id)
        return None

    metadata = {
        "name": langfuse_trace.get("name", ""),
        "tags": langfuse_trace.get("tags", []),
        "userId": langfuse_trace.get("userId"),
        "observation_count": len(observations),
    }

    return Trace(
        trace_id=trace_id,
        session_id=session_id,
        messages=messages,
        metadata=metadata,
    )
