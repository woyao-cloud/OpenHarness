"""Skill load logging for LLM API calls.

Provides two output channels:

1. Python ``logging`` at DEBUG level under
   ``openharness.services.log.skill_logger`` — always active, concise
   one-line summary per skill load.
2. Dedicated ``prompt_debug_*.log`` file — only written when
   ``verbose=True``, contains skill name and content with truncation.
"""

from __future__ import annotations

import logging

from openharness.services.log._shared import truncate, write_to_debug_file

log = logging.getLogger(__name__)

_SEPARATOR = "=" * 80


def _format_skill_summary(skill_name: str, content_len: int) -> str:
    """Format a one-line summary for DEBUG-level logging."""
    return f"[SkillLog] {skill_name} ({content_len} chars)"


def _format_skill_detail(
    *,
    request_id: int,
    skill_name: str,
    skill_content: str,
) -> str:
    """Format full detail for the debug log file."""
    lines = [
        _SEPARATOR,
        f"SKILL (request={request_id}) {skill_name}",
        _SEPARATOR,
    ]
    lines.append(f"Content ({len(skill_content)} chars, showing first 500):")
    lines.append(truncate(skill_content))
    return "\n".join(lines)


def log_skill_load(
    *,
    request_id: int,
    skill_name: str,
    skill_content: str,
) -> None:
    """Log a skill load event.

    Parameters
    ----------
    request_id : int
        The request ID from ``log_prompt_request()``.
    skill_name : str
        Name of the skill that was loaded.
    skill_content : str
        Full content of the skill markdown.
    """
    log.debug(_format_skill_summary(skill_name, len(skill_content)))
    write_to_debug_file(
        _format_skill_detail(
            request_id=request_id,
            skill_name=skill_name,
            skill_content=skill_content,
        )
    )