"""Tool execution logging for LLM API calls.

Provides two output channels:

1. Python ``logging`` at DEBUG level under
   ``openharness.services.log.tool_logger`` — always active, concise
   one-line summary per tool execution.
2. Dedicated ``prompt_debug_*.log`` file — only written when
   ``verbose=True``, contains full tool input/output with truncation.
"""

from __future__ import annotations

import logging

from openharness.services.log._shared import truncate, write_to_debug_file

log = logging.getLogger(__name__)

_SEPARATOR = "=" * 80


def _format_tool_summary(
    tool_name: str, duration_seconds: float, is_error: bool
) -> str:
    """Format a one-line summary for DEBUG-level logging."""
    return (
        f"[ToolLog] {tool_name} ({duration_seconds:.2f}s)"
        f"{' ERROR' if is_error else ''}"
    )


def _format_tool_detail(
    *,
    request_id: int,
    tool_name: str,
    tool_input: dict,
    tool_output: str,
    is_error: bool,
    duration_seconds: float,
) -> str:
    """Format full detail for the debug log file."""
    lines = [
        _SEPARATOR,
        f"TOOL (request={request_id}) {tool_name} ({duration_seconds:.2f}s)",
        _SEPARATOR,
        "Input:",
    ]
    for key, value in tool_input.items():
        lines.append(f"  {key}: {truncate(str(value))}")
    lines.append(f"Output ({len(tool_output)} chars):")
    lines.append(truncate(tool_output))
    lines.append(f"Error: {is_error}")
    return "\n".join(lines)


def log_tool_execution(
    *,
    request_id: int,
    tool_name: str,
    tool_input: dict,
    tool_output: str,
    is_error: bool,
    duration_seconds: float,
) -> None:
    """Log a tool execution event.

    Parameters
    ----------
    request_id : int
        The request ID from ``log_prompt_request()``.
    tool_name : str
        Name of the tool that was executed.
    tool_input : dict
        The tool's input arguments.
    tool_output : str
        The tool's output content.
    is_error : bool
        Whether the tool execution resulted in an error.
    duration_seconds : float
        How long the tool execution took in seconds.
    """
    log.debug(_format_tool_summary(tool_name, duration_seconds, is_error))
    write_to_debug_file(
        _format_tool_detail(
            request_id=request_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            is_error=is_error,
            duration_seconds=duration_seconds,
        )
    )