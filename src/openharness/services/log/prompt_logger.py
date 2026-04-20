"""Prompt request and response logger for LLM API calls.

Provides two output channels:

1. Python ``logging`` at DEBUG level under
   ``openharness.services.log.prompt_logger`` -- always active, concise
   summary per request and response.
2. Dedicated ``prompt_debug_*.log`` file -- only written when
   ``verbose=True``, contains full prompt and response content.

Detail levels:

- **Summary** (verbose=False): section names + char counts + message counts.
- **Full content** (verbose=True): everything above plus the complete system
  prompt text, each message's role/text with tool_use/tool_result details,
  and tool schemas with descriptions.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import (
    ConversationMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from openharness.services.log._shared import (
    next_request_id,
    truncate,
    write_to_debug_file,
)
from openharness.tools.base import ToolRegistry

log = logging.getLogger(__name__)

_SEPARATOR = "=" * 80


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PromptLogEntry:
    """Summary of a single LLM API request."""

    request_id: int
    timestamp: str
    model: str
    max_tokens: int
    system_prompt_sections: list[tuple[str, int]]  # (section_name, char_count)
    system_prompt_total_chars: int
    message_count_by_role: dict[str, int]
    message_total_chars: int
    tool_count: int
    tool_names: list[str]


@dataclass
class ResponseLogEntry:
    """Summary of a single streaming text delta from the model."""

    request_id: int
    text_length: int
    text_preview: str


@dataclass
class ResponseCompleteLogEntry:
    """Summary of a completed model response."""

    request_id: int
    model: str
    text: str
    tool_uses: list[dict]  # [{"name": ..., "input": ...}]
    stop_reason: str | None
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _categorize_system_prompt(system_prompt: str) -> list[tuple[str, int]]:
    """Split an assembled system prompt into named sections by ``# `` headers.

    Returns a list of ``(section_name, char_count)`` pairs.
    """
    if not system_prompt:
        return []

    sections: list[tuple[str, int]] = []
    current_header = "Preamble"
    current_text = ""

    for line in system_prompt.split("\n"):
        if line.startswith("# ") and current_text.strip():
            sections.append((current_header, len(current_text.strip())))
            current_header = line.lstrip("# ").strip()
            current_text = ""
        current_text += line + "\n"

    if current_text.strip():
        sections.append((current_header, len(current_text.strip())))

    return sections


def _summarize_messages(
    messages: list[ConversationMessage],
) -> tuple[dict[str, int], int, list[dict]]:
    """Return role counts, total chars, and per-message detail summaries."""
    by_role: dict[str, int] = defaultdict(int)
    total_chars = 0
    per_message: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.role
        by_role[role] += 1

        msg_chars = 0
        text_parts: list[str] = []
        tool_use_names: list[str] = []
        tool_result_ids: list[str] = []

        for block in msg.content:
            if isinstance(block, TextBlock):
                msg_chars += len(block.text)
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                by_role["tool_uses"] += 1
                tool_use_names.append(block.name)
                inp_json = json.dumps(block.input, ensure_ascii=False)
                msg_chars += len(inp_json)
                text_parts.append(f"[tool_use: {block.name}({inp_json})]")
            elif isinstance(block, ToolResultBlock):
                by_role["tool_results"] += 1
                tool_result_ids.append(block.tool_use_id)
                msg_chars += len(block.content)
                text_parts.append(f"[tool_result: {truncate(block.content)}]")

        total_chars += msg_chars

        summary: dict[str, Any] = {
            "role": role,
            "chars": msg_chars,
            "preview": truncate(" ".join(t for t in text_parts if t)[:100]),
        }
        if tool_use_names:
            summary["tool_uses"] = tool_use_names
        if tool_result_ids:
            summary["tool_results_count"] = len(tool_result_ids)

        per_message.append(summary)

    return dict(by_role), total_chars, per_message


# ---------------------------------------------------------------------------
# Formatting -- summary (always emitted to Python logging)
# ---------------------------------------------------------------------------


def _format_summary(entry: PromptLogEntry) -> str:
    """Format a human-readable summary for DEBUG-level logging."""
    lines = [
        f"[PromptLog #{entry.request_id}] {entry.timestamp}"
        f" | model={entry.model} | max_tokens={entry.max_tokens}",
        f"  System Prompt: {entry.system_prompt_total_chars} chars"
        f" ({len(entry.system_prompt_sections)} sections)",
    ]
    for name, chars in entry.system_prompt_sections:
        lines.append(f"    [{name}] {chars} chars")

    role_parts = ", ".join(
        f"{k}={v}" for k, v in sorted(entry.message_count_by_role.items())
    )
    msg_count = sum(
        v for k, v in entry.message_count_by_role.items() if k in ("user", "assistant")
    )
    lines.append(
        f"  Messages: {msg_count} ({role_parts}),"
        f" total {entry.message_total_chars} chars"
    )
    tool_display = ", ".join(entry.tool_names[:10])
    if len(entry.tool_names) > 10:
        tool_display += "..."
    lines.append(f"  Tools: {entry.tool_count} ({tool_display})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting -- detail (emitted to debug file when verbose)
# ---------------------------------------------------------------------------


def _format_detail(
    entry: PromptLogEntry,
    system_prompt_full: str,
    messages_summary: list[dict[str, Any]],
    tool_schemas: list[dict[str, Any]],
) -> str:
    """Format full detail for the debug log file."""
    lines = [_format_summary(entry), ""]
    lines.append(_SEPARATOR)
    lines.append("SYSTEM PROMPT (full)")
    lines.append(_SEPARATOR)
    lines.append(truncate(system_prompt_full))
    lines.append("")
    lines.append(_SEPARATOR)
    lines.append("MESSAGES")
    lines.append(_SEPARATOR)
    for i, msg in enumerate(messages_summary, 1):
        lines.append(f"--- Message {i} ---")
        lines.append(f"  Role: {msg['role']}")
        lines.append(f"  Chars: {msg['chars']}")
        if "tool_uses" in msg:
            lines.append(f"  Tool Uses: {', '.join(msg['tool_uses'])}")
        if "tool_results_count" in msg:
            lines.append(f"  Tool Results: {msg['tool_results_count']}")
        lines.append(f"  Preview: {msg['preview']}")
    lines.append("")
    lines.append(_SEPARATOR)
    lines.append("TOOLS")
    lines.append(_SEPARATOR)
    for tool in tool_schemas:
        desc = tool.get("description", "")
        lines.append(f"  - {tool['name']}: {truncate(desc)}")

    return "\n".join(lines)


def _format_response_delta_summary(entry: ResponseLogEntry) -> str:
    """Format a human-readable summary of a streaming text delta."""
    preview = truncate(entry.text_preview, limit=60)
    return f'[ResponseLog #{entry.request_id} delta] "{preview}" ({entry.text_length} chars)'


def _format_response_complete_summary(entry: ResponseCompleteLogEntry) -> str:
    """Format a human-readable summary of a completed model response."""
    lines = [
        f"[ResponseLog #{entry.request_id} complete]"
        f" model={entry.model} | stop_reason={entry.stop_reason}",
        f"  Text: {len(entry.text)} chars",
    ]
    if entry.tool_uses:
        tool_names = [tu.get("name", "?") for tu in entry.tool_uses]
        lines.append(f"  Tools: {tool_names}")
    lines.append(f"  Usage: in={entry.input_tokens} out={entry.output_tokens}")
    return "\n".join(lines)


def _format_response_complete_detail(entry: ResponseCompleteLogEntry) -> str:
    """Format full detail of a completed model response for the debug log file."""
    lines = [
        _SEPARATOR,
        f"RESPONSE #{entry.request_id}"
        f" (model={entry.model}, stop={entry.stop_reason},"
        f" in={entry.input_tokens} out={entry.output_tokens})",
        _SEPARATOR,
    ]
    if entry.text:
        lines.append("TEXT:")
        lines.append(truncate(entry.text))
    else:
        lines.append("TEXT: (empty)")
    if entry.tool_uses:
        lines.append("")
        lines.append("TOOL_USES:")
        for i, tu in enumerate(entry.tool_uses, 1):
            name = tu.get("name", "?")
            inp = tu.get("input", {})
            inp_str = json.dumps(inp, ensure_ascii=False) if inp else ""
            lines.append(f"  {i}. {name}({inp_str})")
    lines.append("")
    lines.append("USAGE:")
    lines.append(
        f"  input_tokens={entry.input_tokens}"
        f" output_tokens={entry.output_tokens}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def log_prompt_request(
    *,
    step_remark: str = "",
    model: str,
    max_tokens: int,
    system_prompt: str,
    messages: list[ConversationMessage],
    tool_registry: ToolRegistry,
    verbose: bool = False,
) -> int:
    """Log an LLM API request with categorized prompt information.

    Parameters
    ----------
    step_remark : str
        Optional remark about the current step (logged at DEBUG).
    model : str
        The model identifier being used.
    max_tokens : int
        Maximum output tokens.
    system_prompt : str
        The fully assembled system prompt.
    messages : list[ConversationMessage]
        The conversation history being sent.
    tool_registry : ToolRegistry
        The tool registry (for listing available tools).
    verbose : bool
        If True, also write full prompt content to a dedicated log file.

    Returns
    -------
    int
        The request ID for associating with response logging functions.
    """
    request_id = next_request_id()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sections = _categorize_system_prompt(system_prompt)
    role_counts, total_chars, per_message = _summarize_messages(messages)

    tool_schemas = tool_registry.to_api_schema()
    tool_names = [t.get("name", "?") for t in tool_schemas]

    entry = PromptLogEntry(
        request_id=request_id,
        timestamp=timestamp,
        model=model,
        max_tokens=max_tokens,
        system_prompt_sections=sections,
        system_prompt_total_chars=len(system_prompt),
        message_count_by_role=role_counts,
        message_total_chars=total_chars,
        tool_count=len(tool_schemas),
        tool_names=tool_names,
    )

    if step_remark:
        log.debug("step_remark: %s", step_remark)
    log.debug("\n%s", _format_summary(entry))

    if verbose:
        simplified_schemas = [
            {"name": t.get("name", "?"), "description": t.get("description", "")}
            for t in tool_schemas
        ]
        detail_text = _format_detail(
            entry,
            system_prompt_full=system_prompt,
            messages_summary=per_message,
            tool_schemas=simplified_schemas,
        )
        write_to_debug_file(detail_text)

    return request_id


def log_response_event(
    *,
    delta_text: str,
    request_id: int,
    verbose: bool = False,
) -> None:
    """Log a streaming text delta from the model response.

    Parameters
    ----------
    delta_text : str
        The text content of this streaming delta.
    request_id : int
        The request ID (from ``log_prompt_request()``) to associate with.
    verbose : bool
        If True, also write to the dedicated debug log file.
    """
    entry = ResponseLogEntry(
        request_id=request_id,
        text_length=len(delta_text),
        text_preview=delta_text,
    )
    log.debug(_format_response_delta_summary(entry))

    if verbose:
        write_to_debug_file(
            f'[ResponseLog #{request_id} delta] "{truncate(delta_text)}"'
        )


def log_response_complete(
    *,
    message: ConversationMessage,
    usage: UsageSnapshot,
    request_id: int,
    model: str = "",
    stop_reason: str | None = None,
    verbose: bool = False,
) -> None:
    """Log a completed model response with full content.

    Parameters
    ----------
    message : ConversationMessage
        The complete assistant message.
    usage : UsageSnapshot
        Token usage for this response.
    request_id : int
        The request ID (from ``log_prompt_request()``) to associate with.
    model : str
        The model identifier.
    stop_reason : str | None
        The stop reason from the API.
    verbose : bool
        If True, also write full response content to the dedicated log file.
    """
    text = message.text
    tool_uses: list[dict[str, Any]] = [
        {"name": tu.name, "input": tu.input}
        for tu in message.content
        if isinstance(tu, ToolUseBlock)
    ]
    entry = ResponseCompleteLogEntry(
        request_id=request_id,
        model=model,
        text=text,
        tool_uses=tool_uses,
        stop_reason=stop_reason,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    log.debug("\n%s", _format_response_complete_summary(entry))

    if verbose:
        write_to_debug_file(_format_response_complete_detail(entry))

def log_simple(
    *,
    step_remark: str = "",
    message: str,
    verbose: bool = False,
) -> None:
    """Log a simple message at DEBUG level.

    Parameters
    ----------
    step_remark : str
        Optional remark about the current step (logged at DEBUG).
    message : str
        The message to log.
    verbose : bool
        If True, also write to the dedicated debug log file.
    """
    log.debug(message)
    if verbose:
        write_to_debug_file(step_remark + ": "+message)