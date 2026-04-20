"""Compaction event logging for LLM API calls.

Provides two output channels:

1. Python ``logging`` at DEBUG level under
   ``openharness.services.log.compact_logger`` — always active, concise
   one-line summary per compaction event.
2. Dedicated ``prompt_debug_*.log`` file — only written when
   ``verbose=True``, contains full compaction details with truncation.
"""

from __future__ import annotations

import logging

from openharness.services.log._shared import truncate, write_to_debug_file

log = logging.getLogger(__name__)

_SEPARATOR = "=" * 80


def _format_compact_summary(
    trigger: str, phase: str, before_tokens: int | None, after_tokens: int | None
) -> str:
    """Format a one-line summary for DEBUG-level logging."""
    saved = ""
    if before_tokens and after_tokens:
        pct = int((1 - after_tokens / before_tokens) * 100)
        saved = f" (saved {pct}%)"
    return (
        f"[CompactLog] trigger={trigger} phase={phase}"
        f" before={before_tokens} after={after_tokens}{saved}"
    )


def _format_compact_detail(
    *,
    request_id: int,
    trigger: str,
    phase: str,
    message: str | None,
    before_tokens: int | None,
    after_tokens: int | None,
    summary: str | None,
) -> str:
    """Format full detail for the debug log file."""
    lines = [
        _SEPARATOR,
        f"COMPACT (request={request_id}) trigger={trigger} phase={phase}",
        _SEPARATOR,
    ]
    if before_tokens is not None:
        lines.append(f"Before: ~{before_tokens} tokens")
    if after_tokens is not None:
        lines.append(f"After:  ~{after_tokens} tokens")
        if before_tokens:
            pct = int((1 - after_tokens / before_tokens) * 100)
            lines.append(f"Saved:  {pct}%")
    if message:
        lines.append(f"Message: {message}")
    if summary:
        lines.append("Summary:")
        lines.append(truncate(summary))
    return "\n".join(lines)


def log_compact_event(
    *,
    request_id: int,
    trigger: str,
    phase: str,
    message: str | None = None,
    before_tokens: int | None = None,
    after_tokens: int | None = None,
    summary: str | None = None,
) -> None:
    """Log a context compaction event.

    Parameters
    ----------
    request_id : int
        The request ID associated with this compaction event.
        Use 0 for pre-request compaction.
    trigger : str
        What triggered the compaction: "auto", "manual", or "reactive".
    phase : str
        The compaction phase (e.g., "compact_start", "compact_end").
    message : str | None
        Optional human-readable message about the compaction.
    before_tokens : int | None
        Approximate token count before compaction.
    after_tokens : int | None
        Approximate token count after compaction.
    summary : str | None
        Optional summary of what was compacted.
    """
    log.debug(
        _format_compact_summary(trigger, phase, before_tokens, after_tokens)
    )
    write_to_debug_file(
        _format_compact_detail(
            request_id=request_id,
            trigger=trigger,
            phase=phase,
            message=message,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            summary=summary,
        )
    )