"""Prompt request and response logger for LLM API calls.

Provides two output channels:
1. Python ``logging`` at DEBUG level under ``openharness.services.prompt_logger``
   — always active, one-line summary per request and response.
2. Dedicated ``prompt_debug_*.log`` file in ``~/.openharness/logs/``
   — only written when ``verbose=True``, contains full prompt and response content.

Detail levels:
- **Summary** (verbose=False): section names + char counts + message counts.
- **Full content** (verbose=True): everything above plus the complete system
  prompt text, each message's role/text, tool schema names, and full response content.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openharness.api.usage import UsageSnapshot
from openharness.config.paths import get_logs_dir
from openharness.engine.messages import (
    ConversationMessage,
    ToolResultBlock,
    ToolUseBlock,
)
from openharness.tools.base import ToolRegistry

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global request counter (thread-safe)
# ---------------------------------------------------------------------------

_request_counter = 0
_counter_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Session-scoped log file handle
# ---------------------------------------------------------------------------

_log_file_path: Path | None = None
_log_file_lock = threading.Lock()
_MAX_DEBUG_FILES = 15


def _get_log_file_path() -> Path:
    """Return (and lazily create) the session prompt debug log file path."""
    global _log_file_path
    if _log_file_path is not None:
        return _log_file_path

    logs_dir = get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file_path = logs_dir / f"prompt_debug_{timestamp}.log"

    # Rotate: remove oldest files beyond the limit.
    existing = sorted(logs_dir.glob("prompt_debug_*.log"))
    while len(existing) >= _MAX_DEBUG_FILES:
        oldest = existing.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass

    return _log_file_path


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
class PromptLogDetail:
    """Full detail for verbose logging mode."""

    entry: PromptLogEntry
    system_prompt_full: str
    messages_summary: list[dict]  # [{"role": ..., "chars": ..., "preview": ...}]
    tool_schemas: list[dict]  # simplified: [{"name": ..., "description": ...}]


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


def _next_request_id() -> int:
    global _request_counter
    with _counter_lock:
        _request_counter += 1
        return _request_counter


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
    """Return role counts, total chars, and per-message summaries."""
    by_role: dict[str, int] = defaultdict(int)
    total_chars = 0
    per_message: list[dict] = []

    for msg in messages:
        role = msg.role
        by_role[role] += 1

        msg_chars = 0
        text_parts: list[str] = []
        tool_use_names: list[str] = []
        tool_result_ids: list[str] = []

        for block in msg.content:
            block_text = getattr(block, "text", "") or ""
            block_name = getattr(block, "name", "") or ""
            block_id = getattr(block, "id", "") or ""

            msg_chars += len(block_text)
            text_parts.append(block_text)

            if isinstance(block, ToolUseBlock):
                tool_use_names.append(block_name)
                by_role["tool_uses"] += 1
            elif isinstance(block, ToolResultBlock):
                tool_result_ids.append(block_id)
                by_role["tool_results"] += 1

        total_chars += msg_chars

        preview = " ".join(t for t in text_parts if t)[:100]
        summary = {
            "role": role,
            "chars": msg_chars,
            "preview": preview,
        }
        if tool_use_names:
            summary["tool_uses"] = tool_use_names
        if tool_result_ids:
            summary["tool_results_count"] = len(tool_result_ids)

        per_message.append(summary)

    return dict(by_role), total_chars, per_message


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_summary(entry: PromptLogEntry) -> str:
    """Format a human-readable summary (used for both logging and file output)."""
    lines = [
        f"[PromptLog #{entry.request_id}] {entry.timestamp} | model={entry.model} | max_tokens={entry.max_tokens}",
        f"  System Prompt: {entry.system_prompt_total_chars} chars ({len(entry.system_prompt_sections)} sections)",
    ]
    for name, chars in entry.system_prompt_sections:
        lines.append(f"    [{name}] {chars} chars")

    role_parts = ", ".join(f"{k}={v}" for k, v in sorted(entry.message_count_by_role.items()))
    lines.append(f"  Messages: {sum(v for k, v in entry.message_count_by_role.items() if k in ('user', 'assistant'))} ({role_parts}), total {entry.message_total_chars} chars")
    lines.append(f"  Tools: {entry.tool_count} ({', '.join(entry.tool_names[:10])}{'...' if len(entry.tool_names) > 10 else ''})")

    return "\n".join(lines)


def _format_detail(detail: PromptLogDetail) -> str:
    """Format full detail for the debug log file."""
    lines = [_format_summary(detail.entry)]
    lines.append("")
    lines.append("=" * 80)
    lines.append("SYSTEM PROMPT (full)")
    lines.append("=" * 80)
    lines.append(detail.system_prompt_full)
    lines.append("")
    lines.append("=" * 80)
    lines.append("MESSAGES")
    lines.append("=" * 80)
    for i, msg in enumerate(detail.messages_summary):
        lines.append(f"--- Message {i + 1} ---")
        lines.append(f"  Role: {msg['role']}")
        lines.append(f"  Chars: {msg['chars']}")
        if "tool_uses" in msg:
            lines.append(f"  Tool Uses: {', '.join(msg['tool_uses'])}")
        if "tool_results_count" in msg:
            lines.append(f"  Tool Results: {msg['tool_results_count']}")
        lines.append(f"  Preview: {msg['preview']}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("TOOLS")
    lines.append("=" * 80)
    for tool in detail.tool_schemas:
        lines.append(f"  - {tool['name']}: {tool.get('description', '')[:80]}")

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

    This is the main entry point called from ``run_query()`` before
    ``stream_message()``.

    Parameters
    ----------
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
        The request ID, which can be passed to response logging functions
        to associate the request with its response.
    """
    request_id = _next_request_id()
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
    log.debug("step_remark: "+step_remark)
    # Always log summary to Python logging at DEBUG level.
    log.debug("\n%s", _format_summary(entry))

    # If verbose, also write full content to the dedicated log file.
    if verbose:
        detail = PromptLogDetail(
            entry=entry,
            system_prompt_full=system_prompt,
            messages_summary=per_message,
            tool_schemas=[
                {"name": t.get("name", "?"), "description": t.get("description", "")}
                for t in tool_schemas
            ],
        )
        _write_to_debug_file(_format_detail(detail))

    return request_id

def _format_response_delta_summary(entry: ResponseLogEntry) -> str:
    """Format a human-readable summary of a streaming text delta."""
    preview = entry.text_preview[:60]
    return f"[ResponseLog #{entry.request_id} delta] \"{preview}\" ({entry.text_length} chars)"


def _format_response_complete_summary(entry: ResponseCompleteLogEntry) -> str:
    """Format a human-readable summary of a completed model response."""
    lines = [
        f"[ResponseLog #{entry.request_id} complete] model={entry.model} | stop_reason={entry.stop_reason}",
        f"  Text: {len(entry.text)} chars",
    ]
    if entry.tool_uses:
        tool_names = [tu.get("name", "?") for tu in entry.tool_uses]
        lines.append(f"  Tools: {tool_names}")
    lines.append(f"  Usage: in={entry.input_tokens} out={entry.output_tokens}")
    return "\n".join(lines)


def _format_response_complete_detail(entry: ResponseCompleteLogEntry) -> str:
    """Format full detail of a completed model response for the debug log file."""
    sep = "=" * 80
    lines = [
        sep,
        f"RESPONSE #{entry.request_id} (model={entry.model}, stop={entry.stop_reason}, in={entry.input_tokens} out={entry.output_tokens})",
        sep,
    ]
    if entry.text:
        lines.append("TEXT:")
        lines.append(entry.text)
    else:
        lines.append("TEXT: (empty)")
    if entry.tool_uses:
        lines.append("")
        lines.append("TOOL_USES:")
        for i, tu in enumerate(entry.tool_uses, 1):
            name = tu.get("name", "?")
            inp = tu.get("input", {})
            lines.append(f"  {i}. {name}({json.dumps(inp, ensure_ascii=False) if inp else ''})")
    lines.append("")
    lines.append("USAGE:")
    lines.append(f"  input_tokens={entry.input_tokens} output_tokens={entry.output_tokens}")
    return "\n".join(lines)


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
        _write_to_debug_file(f"[ResponseLog #{request_id} delta] \"{delta_text}\"")


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
    tool_uses = [
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
        _write_to_debug_file(_format_response_complete_detail(entry))


def log_simple(content: str) -> None:
    """Log a simple message to the prompt debug file (for ad-hoc notes)."""
    _write_to_debug_file(content)


def log_content_block(content_block) -> None:
    """Log a ContentBlock to the prompt debug file.

    Parameters
    ----------
    content_block : ContentBlock
        The content block to log.
    """
    from openharness.engine.messages import TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock
    
    lines = ["=" * 80]
    
    if isinstance(content_block, TextBlock):
        lines.append(f"ContentBlock Type: TextBlock")
        lines.append("=" * 80)
        lines.append(f"Text: {content_block.text}")
    elif isinstance(content_block, ImageBlock):
        lines.append(f"ContentBlock Type: ImageBlock")
        lines.append("=" * 80)
        lines.append(f"Media Type: {content_block.media_type}")
        lines.append(f"Source Path: {content_block.source_path}")
        lines.append(f"Data Length: {len(content_block.data)} characters")
    elif isinstance(content_block, ToolUseBlock):
        lines.append(f"ContentBlock Type: ToolUseBlock")
        lines.append("=" * 80)
        lines.append(f"ID: {content_block.id}")
        lines.append(f"Name: {content_block.name}")
        lines.append(f"Input: {content_block.input}")
    elif isinstance(content_block, ToolResultBlock):
        lines.append(f"ContentBlock Type: ToolResultBlock")
        lines.append("=" * 80)
        lines.append(f"Tool Use ID: {content_block.tool_use_id}")
        lines.append(f"Content: {content_block.content}")
        lines.append(f"Is Error: {content_block.is_error}")
    else:
        lines.append(f"ContentBlock Type: Unknown")
        lines.append("=" * 80)
        lines.append(f"Content: {content_block}")
    
    content = "\n".join(lines)
    _write_to_debug_file(content)


def _write_to_debug_file(content: str) -> None:
    """Append formatted content to the session prompt debug log file."""
    try:
        log_path = _get_log_file_path()
        with _log_file_lock:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(content)
                f.write("\n\n")
    except OSError:
        # Non-critical: debug logging should never break the main flow.
        log.warning("Failed to write prompt debug log to %s", _log_file_path)


def reset_session() -> None:
    """Reset session state (for testing or new sessions)."""
    global _request_counter, _log_file_path
    with _counter_lock:
        _request_counter = 0
    with _log_file_lock:
        _log_file_path = None