# 日志系统增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the monolithic `prompt_logger.py` into a `services/log/` package with shared infrastructure, prompt/response/tool/compact/skill loggers, bug fixes, and 500-char truncation.

**Architecture:** Extract shared state (request counter, verbose gate, file writer, truncation) into `_shared.py`. Split each logging concern into its own module. Fix the `log_content_block` list-type bug, the `log_simple` verbose bypass, and unify OpenAI/Anthropic logging paths through `query.py`.

**Tech Stack:** Python 3.10+, dataclasses, threading, asyncio, Pydantic (ConversationMessage), pytest

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/openharness/services/log/__init__.py` | Public API re-exports |
| Create | `src/openharness/services/log/_shared.py` | Shared state, verbose gate, truncate, file writer, request counter |
| Create | `src/openharness/services/log/prompt_logger.py` | Request/response logging (migrated + enhanced) |
| Create | `src/openharness/services/log/tool_logger.py` | Tool execution logging |
| Create | `src/openharness/services/log/compact_logger.py` | Compaction logging |
| Create | `src/openharness/services/log/skill_logger.py` | Skill load logging |
| Modify | `src/openharness/services/prompt_logger.py` | Backward-compat re-export with DeprecationWarning |
| Modify | `src/openharness/engine/query.py` | Use new log package, add tool/compact logging calls, pass request_id |
| Modify | `src/openharness/api/openai_client.py` | Remove log_simple/log_content_block imports and calls |
| Modify | `src/openharness/cli.py` | Replace log_simple with log.debug |
| Modify | `src/openharness/ui/app.py` | Replace log_simple with log.debug |
| Modify | `src/openharness/ui/runtime.py` | Replace log_simple with log.debug |
| Create | `tests/test_services/test_log_shared.py` | Tests for _shared.py |
| Create | `tests/test_services/test_prompt_logger.py` | Tests for prompt_logger.py |
| Create | `tests/test_services/test_tool_logger.py` | Tests for tool_logger.py |
| Create | `tests/test_services/test_compact_logger.py` | Tests for compact_logger.py |
| Create | `tests/test_services/test_skill_logger.py` | Tests for skill_logger.py |

---

### Task 1: Create `_shared.py` — shared infrastructure

**Files:**
- Create: `src/openharness/services/log/__init__.py`
- Create: `src/openharness/services/log/_shared.py`
- Create: `tests/test_services/test_log_shared.py`

- [ ] **Step 1: Write failing tests for `_shared.py`**

```python
# tests/test_services/test_log_shared.py
import pytest
from openharness.services.log._shared import (
    next_request_id,
    set_verbose,
    is_verbose,
    truncate,
    write_to_debug_file,
    reset_session,
    _TRUNCATE_LIMIT,
)


def test_truncate_short_text_unchanged():
    assert truncate("hello") == "hello"


def test_truncate_exact_limit_unchanged():
    text = "x" * _TRUNCATE_LIMIT
    assert truncate(text) == text


def test_truncate_long_text():
    text = "x" * 600
    result = truncate(text)
    assert result.startswith("x" * _TRUNCATE_LIMIT)
    assert "... [truncated, total 600 chars]" in result
    assert len(result) < len(text)


def test_truncate_custom_limit():
    text = "abcdefghij"
    result = truncate(text, limit=5)
    assert result.startswith("abcde")
    assert "... [truncated, total 10 chars]" in result


def test_next_request_id_increments():
    reset_session()
    first = next_request_id()
    second = next_request_id()
    assert second == first + 1
    reset_session()


def test_verbose_gate():
    reset_session()
    set_verbose(False)
    assert is_verbose() is False
    set_verbose(True)
    assert is_verbose() is True
    set_verbose(False)
    reset_session()


def test_write_to_debug_file_skips_when_not_verbose(tmp_path, monkeypatch):
    reset_session()
    set_verbose(False)
    monkeypatch.setattr("openharness.services.log._shared._log_file_path", None)
    monkeypatch.setattr(
        "openharness.services.log._shared.get_log_file_path",
        lambda: tmp_path / "test.log",
    )
    write_to_debug_file("should not be written")
    # File should not exist because verbose=False
    assert not (tmp_path / "test.log").exists()
    reset_session()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_log_shared.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Create `log/` package and implement `_shared.py`**

```python
# src/openharness/services/log/__init__.py
"""Structured logging for LLM API requests, responses, and internal events."""

from openharness.services.log._shared import (
    is_verbose,
    next_request_id,
    reset_session,
    set_verbose,
    truncate,
    write_to_debug_file,
)
from openharness.services.log.prompt_logger import (
    log_prompt_request,
    log_response_complete,
    log_response_event,
)
from openharness.services.log.tool_logger import log_tool_execution
from openharness.services.log.compact_logger import log_compact_event
from openharness.services.log.skill_logger import log_skill_load

__all__ = [
    "is_verbose",
    "log_compact_event",
    "log_prompt_request",
    "log_response_complete",
    "log_response_event",
    "log_skill_load",
    "log_tool_execution",
    "next_request_id",
    "reset_session",
    "set_verbose",
    "truncate",
    "write_to_debug_file",
]
```

```python
# src/openharness/services/log/_shared.py
"""Shared state and utilities for the logging package."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from openharness.config.paths import get_logs_dir

log = logging.getLogger(__name__)

_MAX_DEBUG_FILES = 15
_TRUNCATE_LIMIT = 500

_request_counter: int = 0
_counter_lock = threading.Lock()

_log_file_path: Path | None = None
_log_file_lock = threading.Lock()

_verbose_enabled: bool = False


def next_request_id() -> int:
    global _request_counter
    with _counter_lock:
        _request_counter += 1
        return _request_counter


def set_verbose(enabled: bool) -> None:
    global _verbose_enabled
    _verbose_enabled = enabled


def is_verbose() -> bool:
    return _verbose_enabled


def truncate(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated, total {len(text)} chars]"


def get_log_file_path() -> Path:
    global _log_file_path
    with _log_file_lock:
        if _log_file_path is not None:
            return _log_file_path

        logs_dir = get_logs_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_file_path = logs_dir / f"prompt_debug_{timestamp}.log"

        existing = sorted(logs_dir.glob("prompt_debug_*.log"))
        while len(existing) >= _MAX_DEBUG_FILES:
            oldest = existing.pop(0)
            try:
                oldest.unlink()
            except OSError:
                pass

        return _log_file_path


def write_to_debug_file(content: str) -> None:
    if not is_verbose():
        return
    try:
        log_path = get_log_file_path()
        with _log_file_lock:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(content)
                f.write("\n\n")
    except OSError:
        log.warning("Failed to write prompt debug log to %s", _log_file_path)


def reset_session() -> None:
    global _request_counter, _log_file_path
    with _counter_lock:
        _request_counter = 0
    with _log_file_lock:
        _log_file_path = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_log_shared.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/openharness/services/log/__init__.py src/openharness/services/log/_shared.py tests/test_services/test_log_shared.py
git commit -m "feat(log): create log package with shared infrastructure"
```

---

### Task 2: Create `prompt_logger.py` — request/response logging

**Files:**
- Create: `src/openharness/services/log/prompt_logger.py`
- Create: `tests/test_services/test_prompt_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services/test_prompt_logger.py
import pytest
from unittest.mock import MagicMock
from openharness.services.log.prompt_logger import (
    log_prompt_request,
    log_response_event,
    log_response_complete,
)
from openharness.services.log._shared import reset_session, set_verbose, truncate
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock, ToolUseBlock


@pytest.fixture(autouse=True)
def _reset():
    reset_session()
    set_verbose(False)
    yield
    reset_session()
    set_verbose(False)


def _make_tool_registry(names=None):
    if names is None:
        names = ["read_file"]
    reg = MagicMock()
    reg.to_api_schema.return_value = [
        {"name": n, "description": f"Tool {n} description"} for n in names
    ]
    return reg


def test_log_prompt_request_returns_request_id():
    rid = log_prompt_request(
        model="test-model",
        max_tokens=1024,
        system_prompt="You are helpful.",
        messages=[ConversationMessage.from_user_text("hello")],
        tool_registry=_make_tool_registry(),
    )
    assert isinstance(rid, int)
    assert rid > 0


def test_log_prompt_request_ids_increment():
    rid1 = log_prompt_request(
        model="m1", max_tokens=100, system_prompt="",
        messages=[], tool_registry=_make_tool_registry(),
    )
    rid2 = log_prompt_request(
        model="m2", max_tokens=200, system_prompt="",
        messages=[], tool_registry=_make_tool_registry(),
    )
    assert rid2 == rid1 + 1


def test_log_response_event_no_crash():
    log_response_event(delta_text="Hello", request_id=1)


def test_log_response_complete_no_crash():
    msg = ConversationMessage(role="assistant", content=[TextBlock(text="Hi there")])
    log_response_complete(
        message=msg,
        usage=UsageSnapshot(input_tokens=10, output_tokens=5),
        request_id=1,
        model="test",
        stop_reason="end_turn",
    )


def test_log_response_complete_with_tool_use():
    msg = ConversationMessage(
        role="assistant",
        content=[
            TextBlock(text="I'll read that."),
            ToolUseBlock(id="toolu_1", name="read_file", input={"file_path": "/a.py"}),
        ],
    )
    log_response_complete(
        message=msg,
        usage=UsageSnapshot(input_tokens=50, output_tokens=20),
        request_id=2,
        model="test",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_prompt_logger.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `prompt_logger.py`**

```python
# src/openharness/services/log/prompt_logger.py
"""Request and response logging for LLM API calls."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import (
    ConversationMessage,
    ImageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from openharness.services.log._shared import (
    is_verbose,
    next_request_id,
    truncate,
    write_to_debug_file,
)
from openharness.tools.base import ToolRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PromptLogEntry:
    request_id: int
    timestamp: str
    model: str
    max_tokens: int
    system_prompt_sections: list[tuple[str, int]]
    system_prompt_total_chars: int
    message_count_by_role: dict[str, int]
    message_total_chars: int
    tool_count: int
    tool_names: list[str]


@dataclass
class ResponseLogEntry:
    request_id: int
    text_length: int
    text_preview: str


@dataclass
class ResponseCompleteLogEntry:
    request_id: int
    model: str
    text: str
    tool_uses: list[dict]
    stop_reason: str | None
    input_tokens: int
    output_tokens: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _categorize_system_prompt(system_prompt: str) -> list[tuple[str, int]]:
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
) -> tuple[dict[str, int], int]:
    by_role: dict[str, int] = defaultdict(int)
    total_chars = 0
    for msg in messages:
        by_role[msg.role] += 1
        for block in msg.content:
            total_chars += len(getattr(block, "text", "") or "")
            if isinstance(block, ToolUseBlock):
                by_role["tool_uses"] += 1
            elif isinstance(block, ToolResultBlock):
                by_role["tool_results"] += 1
    return dict(by_role), total_chars


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_SEP = "=" * 80


def _format_request_summary(entry: PromptLogEntry, step_remark: str) -> str:
    lines = [
        f"[PromptLog #{entry.request_id}] {entry.timestamp} | "
        f"model={entry.model} | max_tokens={entry.max_tokens}"
        f"{f' | step={step_remark}' if step_remark else ''}",
        f"  System Prompt: {entry.system_prompt_total_chars} chars "
        f"({len(entry.system_prompt_sections)} sections)",
    ]
    for name, chars in entry.system_prompt_sections:
        lines.append(f"    [{name}] {chars} chars")
    role_parts = ", ".join(
        f"{k}={v}" for k, v in sorted(entry.message_count_by_role.items())
    )
    lines.append(
        f"  Messages: {sum(v for k, v in entry.message_count_by_role.items() if k in ('user', 'assistant'))} "
        f"({role_parts}), total {entry.message_total_chars} chars"
    )
    lines.append(
        f"  Tools: {entry.tool_count} "
        f"({', '.join(entry.tool_names[:10])}{'...' if len(entry.tool_names) > 10 else ''})"
    )
    return "\n".join(lines)


def _format_request_detail(
    entry: PromptLogEntry,
    step_remark: str,
    system_prompt: str,
    messages: list[ConversationMessage],
    tool_schemas: list[dict],
) -> str:
    lines = [
        _SEP,
        f"REQUEST #{entry.request_id} "
        f"(model={entry.model}, max_tokens={entry.max_tokens}"
        f"{f', step={step_remark}' if step_remark else ''})",
        _SEP,
    ]
    lines.append(f"SYSTEM PROMPT ({len(system_prompt)} chars):")
    lines.append(truncate(system_prompt))
    lines.append("")
    lines.append(f"MESSAGES ({len(messages)}):")
    for i, msg in enumerate(messages, 1):
        tool_uses = msg.tool_uses
        tool_results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
        text_parts = [b for b in msg.content if isinstance(b, TextBlock)]
        images = [b for b in msg.content if isinstance(b, ImageBlock)]
        header = f"  --- Message {i} (role={msg.role}"
        if tool_uses:
            header += f", {len(tool_uses)} tool_use"
        if tool_results:
            header += f", {len(tool_results)} tool_result"
        if images:
            header += f", {len(images)} image"
        header += ") ---"
        lines.append(header)
        for tp in text_parts:
            lines.append(truncate(tp.text))
        for tu in tool_uses:
            lines.append(f"    tool_use: {tu.name}(id={tu.id})")
            lines.append(f"      input: {json.dumps(tu.input, ensure_ascii=False)}")
        for tr in tool_results:
            lines.append(
                f"    tool_result(id={tr.tool_use_id}, is_error={tr.is_error}):"
            )
            lines.append(truncate(tr.content))
        for img in images:
            lines.append(f"    [image: {img.media_type}, {len(img.data)} base64 chars]")
    lines.append("")
    lines.append(f"TOOLS ({len(tool_schemas)}):")
    for i, ts in enumerate(tool_schemas, 1):
        desc = ts.get("description", "")
        lines.append(f"  {i}. {ts.get('name', '?')}: {truncate(desc)}")
    return "\n".join(lines)


def _format_response_delta_summary(entry: ResponseLogEntry) -> str:
    preview = entry.text_preview[:60]
    return f'[ResponseLog #{entry.request_id} delta] "{preview}" ({entry.text_length} chars)'


def _format_response_complete_summary(entry: ResponseCompleteLogEntry) -> str:
    lines = [
        f"[ResponseLog #{entry.request_id} complete] "
        f"model={entry.model} | stop_reason={entry.stop_reason}",
        f"  Text: {len(entry.text)} chars",
    ]
    if entry.tool_uses:
        tool_names = [tu.get("name", "?") for tu in entry.tool_uses]
        lines.append(f"  Tools: {tool_names}")
    lines.append(f"  Usage: in={entry.input_tokens} out={entry.output_tokens}")
    return "\n".join(lines)


def _format_response_complete_detail(entry: ResponseCompleteLogEntry) -> str:
    lines = [
        _SEP,
        f"RESPONSE #{entry.request_id} "
        f"(model={entry.model}, stop={entry.stop_reason}, "
        f"in={entry.input_tokens} out={entry.output_tokens})",
        _SEP,
    ]
    if entry.text:
        lines.append(f"TEXT ({len(entry.text)} chars):")
        lines.append(truncate(entry.text))
    else:
        lines.append("TEXT: (empty)")
    if entry.tool_uses:
        lines.append("")
        lines.append("TOOL_USES:")
        for i, tu in enumerate(entry.tool_uses, 1):
            name = tu.get("name", "?")
            inp = tu.get("input", {})
            lines.append(
                f"  {i}. {name}({json.dumps(inp, ensure_ascii=False) if inp else ''})"
            )
    lines.append("")
    lines.append("USAGE:")
    lines.append(
        f"  input_tokens={entry.input_tokens} output_tokens={entry.output_tokens}"
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
    request_id = next_request_id()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections = _categorize_system_prompt(system_prompt)
    role_counts, total_chars = _summarize_messages(messages)
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
    log.debug("\n%s", _format_request_summary(entry, step_remark))

    if verbose:
        write_to_debug_file(
            _format_request_detail(
                entry, step_remark, system_prompt, messages, tool_schemas
            )
        )

    return request_id


def log_response_event(
    *,
    delta_text: str,
    request_id: int,
    verbose: bool = False,
) -> None:
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
        write_to_debug_file(_format_response_complete_detail(entry))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_prompt_logger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/openharness/services/log/prompt_logger.py tests/test_services/test_prompt_logger.py
git commit -m "feat(log): add prompt_logger with request/response logging and truncation"
```

---

### Task 3: Create `tool_logger.py` — tool execution logging

**Files:**
- Create: `src/openharness/services/log/tool_logger.py`
- Create: `tests/test_services/test_tool_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services/test_tool_logger.py
import pytest
from openharness.services.log.tool_logger import log_tool_execution
from openharness.services.log._shared import reset_session, set_verbose


@pytest.fixture(autouse=True)
def _reset():
    reset_session()
    set_verbose(False)
    yield
    reset_session()
    set_verbose(False)


def test_log_tool_execution_no_crash():
    log_tool_execution(
        request_id=1,
        tool_name="read_file",
        tool_input={"file_path": "/a.py"},
        tool_output="file contents here",
        is_error=False,
        duration_seconds=0.35,
    )


def test_log_tool_execution_with_long_output():
    log_tool_execution(
        request_id=1,
        tool_name="bash",
        tool_input={"command": "cat huge_file.txt"},
        tool_output="x" * 1000,
        is_error=False,
        duration_seconds=1.5,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_tool_logger.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `tool_logger.py`**

```python
# src/openharness/services/log/tool_logger.py
"""Tool execution logging."""

from __future__ import annotations

import json
import logging

from openharness.services.log._shared import truncate, write_to_debug_file

log = logging.getLogger(__name__)

_SEP = "=" * 80


def _format_tool_summary(
    tool_name: str, duration_seconds: float, is_error: bool
) -> str:
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
    lines = [
        _SEP,
        f"TOOL (request={request_id}) {tool_name} ({duration_seconds:.2f}s)",
        _SEP,
        "Input:",
    ]
    for key, value in tool_input.items():
        text = str(value)
        lines.append(f"  {key}: {truncate(text)}")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_tool_logger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/openharness/services/log/tool_logger.py tests/test_services/test_tool_logger.py
git commit -m "feat(log): add tool_logger for tool execution logging"
```

---

### Task 4: Create `compact_logger.py` and `skill_logger.py`

**Files:**
- Create: `src/openharness/services/log/compact_logger.py`
- Create: `src/openharness/services/log/skill_logger.py`
- Create: `tests/test_services/test_compact_logger.py`
- Create: `tests/test_services/test_skill_logger.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_services/test_compact_logger.py
import pytest
from openharness.services.log.compact_logger import log_compact_event
from openharness.services.log._shared import reset_session, set_verbose


@pytest.fixture(autouse=True)
def _reset():
    reset_session()
    set_verbose(False)
    yield
    reset_session()
    set_verbose(False)


def test_log_compact_event_no_crash():
    log_compact_event(
        request_id=1,
        trigger="auto",
        phase="compact_end",
        before_tokens=12000,
        after_tokens=4000,
        summary="Compacted messages 1-15",
    )
```

```python
# tests/test_services/test_skill_logger.py
import pytest
from openharness.services.log.skill_logger import log_skill_load
from openharness.services.log._shared import reset_session, set_verbose


@pytest.fixture(autouse=True)
def _reset():
    reset_session()
    set_verbose(False)
    yield
    reset_session()
    set_verbose(False)


def test_log_skill_load_no_crash():
    log_skill_load(
        request_id=1,
        skill_name="architecture-review",
        skill_content="# Architecture Review Skill\n" + "x" * 600,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_services/test_compact_logger.py tests/test_services/test_skill_logger.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `compact_logger.py`**

```python
# src/openharness/services/log/compact_logger.py
"""Compaction event logging."""

from __future__ import annotations

import logging

from openharness.services.log._shared import truncate, write_to_debug_file

log = logging.getLogger(__name__)

_SEP = "=" * 80


def _format_compact_summary(
    trigger: str, phase: str, before_tokens: int | None, after_tokens: int | None
) -> str:
    saved = ""
    if before_tokens and after_tokens:
        pct = int((1 - after_tokens / before_tokens) * 100)
        saved = f" (saved {pct}%)"
    return f"[CompactLog] trigger={trigger} phase={phase} before={before_tokens} after={after_tokens}{saved}"


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
    lines = [
        _SEP,
        f"COMPACT (request={request_id}) trigger={trigger} phase={phase}",
        _SEP,
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
```

- [ ] **Step 4: Implement `skill_logger.py`**

```python
# src/openharness/services/log/skill_logger.py
"""Skill load logging."""

from __future__ import annotations

import logging

from openharness.services.log._shared import truncate, write_to_debug_file

log = logging.getLogger(__name__)

_SEP = "=" * 80


def _format_skill_summary(skill_name: str, content_len: int) -> str:
    return f"[SkillLog] {skill_name} ({content_len} chars)"


def _format_skill_detail(
    *,
    request_id: int,
    skill_name: str,
    skill_content: str,
) -> str:
    lines = [
        _SEP,
        f"SKILL (request={request_id}) {skill_name}",
        _SEP,
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
    log.debug(_format_skill_summary(skill_name, len(skill_content)))
    write_to_debug_file(
        _format_skill_detail(
            request_id=request_id,
            skill_name=skill_name,
            skill_content=skill_content,
        )
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_services/test_compact_logger.py tests/test_services/test_skill_logger.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/openharness/services/log/compact_logger.py src/openharness/services/log/skill_logger.py tests/test_services/test_compact_logger.py tests/test_services/test_skill_logger.py
git commit -m "feat(log): add compact_logger and skill_logger"
```

---

### Task 5: Backward-compat re-export and remove old `log_simple`/`log_content_block`

**Files:**
- Modify: `src/openharness/services/prompt_logger.py` — replace with thin re-export

- [ ] **Step 1: Replace `prompt_logger.py` with backward-compat re-export**

Read the current file first, then overwrite:

```python
# src/openharness/services/prompt_logger.py
"""Backward-compatible re-export. Use openharness.services.log instead."""

from __future__ import annotations

import warnings

warnings.warn(
    "openharness.services.prompt_logger is deprecated. "
    "Use openharness.services.log instead.",
    DeprecationWarning,
    stacklevel=2,
)

from openharness.services.log import *  # noqa: F401,F403
```

- [ ] **Step 2: Verify old import paths still work**

Run: `python -c "from openharness.services.prompt_logger import log_prompt_request; print('OK')"`
Expected: prints "OK" with a DeprecationWarning

- [ ] **Step 3: Commit**

```bash
git add src/openharness/services/prompt_logger.py
git commit -m "refactor(log): replace prompt_logger.py with backward-compat re-export"
```

---

### Task 6: Wire new log package into `query.py`

**Files:**
- Modify: `src/openharness/engine/query.py`

- [ ] **Step 1: Update imports in `query.py`**

Replace:
```python
from openharness.services.prompt_logger import log_prompt_request, log_response_complete, log_response_event
```

With:
```python
from openharness.services.log import (
    log_compact_event,
    log_prompt_request,
    log_response_complete,
    log_response_event,
    log_tool_execution,
    set_verbose,
)
```

- [ ] **Step 2: Add `set_verbose()` and `request_id` to `run_query()` loop**

In `run_query()`, after the `while` line and before the auto-compact check, add:

```python
    turn_count = 0
    while context.max_turns is None or turn_count < context.max_turns:
        turn_count += 1
        set_verbose(context.verbose)
```

Keep the existing `request_id = log_prompt_request(...)` line.

- [ ] **Step 3: Add `log_tool_execution()` after tool calls**

For single tool execution (after `result = await _execute_tool_call(context, tc.name, tc.id, tc.input)` and before the `yield ToolExecutionCompleted`), add timing and logging:

```python
        if len(tool_calls) == 1:
            tc = tool_calls[0]
            yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
            t0 = time.monotonic()
            result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
            elapsed = time.monotonic() - t0
            log_tool_execution(
                request_id=request_id,
                tool_name=tc.name,
                tool_input=tc.input,
                tool_output=result.content,
                is_error=result.is_error,
                duration_seconds=elapsed,
            )
            yield ToolExecutionCompleted(
```

For concurrent tool execution, after `raw_results = await asyncio.gather(...)` and before the `for tc, result in zip(tool_calls, tool_results):` yield loop, add logging for each result. Since tools run concurrently, we capture elapsed time around the gather:

```python
        else:
            for tc in tool_calls:
                yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None

            async def _run(tc):
                return await _execute_tool_call(context, tc.name, tc.id, tc.input)

            t0 = time.monotonic()
            raw_results = await asyncio.gather(
                *[_run(tc) for tc in tool_calls], return_exceptions=True
            )
            gather_elapsed = time.monotonic() - t0
            tool_results = []
            for tc, result in zip(tool_calls, raw_results):
                if isinstance(result, BaseException):
                    log.exception(
                        "tool execution raised: name=%s id=%s",
                        tc.name, tc.id, exc_info=result,
                    )
                    result = ToolResultBlock(
                        tool_use_id=tc.id,
                        content=f"Tool {tc.name} failed: {type(result).__name__}: {result}",
                        is_error=True,
                    )
                tool_results.append(result)

            for tc, result in zip(tool_calls, tool_results):
                log_tool_execution(
                    request_id=request_id,
                    tool_name=tc.name,
                    tool_input=tc.input,
                    tool_output=result.content,
                    is_error=result.is_error,
                    duration_seconds=gather_elapsed,
                )
                yield ToolExecutionCompleted(
```

- [ ] **Step 4: Add `log_compact_event()` in `_stream_compaction()`**

Inside the `_stream_compaction()` inner function, after `last_compaction_result = await task` and before `return`, add:

```python
        last_compaction_result = await task
        log_compact_event(
            request_id=0,
            trigger=trigger,
            phase="compact_end",
            before_tokens=getattr(compact_state, 'before_tokens', None),
            after_tokens=getattr(compact_state, 'after_tokens', None),
            summary=str(last_compaction_result[0])[:500] if last_compaction_result[1] else None,
        )
        return
```

Note: `request_id=0` here because compaction happens before the API call assigns a request_id. This is acceptable — compaction is a pre-request event.

- [ ] **Step 5: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/openharness/engine/query.py', encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add src/openharness/engine/query.py
git commit -m "feat(log): wire new log package into query.py with tool and compact logging"
```

---

### Task 7: Remove `log_simple`/`log_content_block` from OpenAI client and migrate callers

**Files:**
- Modify: `src/openharness/api/openai_client.py`
- Modify: `src/openharness/cli.py`
- Modify: `src/openharness/ui/app.py`
- Modify: `src/openharness/ui/runtime.py`

- [ ] **Step 1: Remove from `openai_client.py`**

Remove the import line:
```python
from openharness.services.prompt_logger import log_content_block, log_simple
```

Remove the call at the streaming delta (the `log_simple(f"(StreamEvent)...")` line).

Remove the call at the final content (`log_content_block(content)` line).

- [ ] **Step 2: Migrate `cli.py`**

Replace:
```python
from openharness.services.prompt_logger import log_simple
```
With:
```python
import logging
_log = logging.getLogger(__name__)
```

Replace:
```python
log_simple("Starting OpenHarness task worker...")
```
With:
```python
_log.debug("Starting OpenHarness task worker...")
```

- [ ] **Step 3: Migrate `ui/app.py`**

Replace:
```python
from openharness.services.prompt_logger import log_simple
```
With:
```python
import logging
_log = logging.getLogger(__name__)
```

Replace all 3 `log_simple(...)` calls with `_log.debug(...)`.

- [ ] **Step 4: Migrate `ui/runtime.py`**

Replace:
```python
from openharness.services.prompt_logger import log_simple
```
With:
```python
import logging
_log = logging.getLogger(__name__)
```

Replace all 3 `log_simple(...)` calls with `_log.debug(...)`.

- [ ] **Step 5: Verify all files parse**

Run:
```
python -c "import ast; ast.parse(open('src/openharness/api/openai_client.py', encoding='utf-8').read()); print('openai_client: OK')"
python -c "import ast; ast.parse(open('src/openharness/cli.py', encoding='utf-8').read()); print('cli: OK')"
python -c "import ast; ast.parse(open('src/openharness/ui/app.py', encoding='utf-8').read()); print('app: OK')"
python -c "import ast; ast.parse(open('src/openharness/ui/runtime.py', encoding='utf-8').read()); print('runtime: OK')"
```
Expected: All print OK

- [ ] **Step 6: Commit**

```bash
git add src/openharness/api/openai_client.py src/openharness/cli.py src/openharness/ui/app.py src/openharness/ui/runtime.py
git commit -m "refactor(log): remove log_simple/log_content_block from callers, use log.debug instead"
```

---

### Task 8: Run full test suite and fix any issues

**Files:** None (verification only)

- [ ] **Step 1: Run all existing tests**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: All pass. If any test imports `log_simple` or `log_content_block` from the old path, fix the import.

- [ ] **Step 2: Run all new log tests**

Run: `python -m pytest tests/test_services/test_log_shared.py tests/test_services/test_prompt_logger.py tests/test_services/test_tool_logger.py tests/test_services/test_compact_logger.py tests/test_services/test_skill_logger.py -v`
Expected: All pass

- [ ] **Step 3: Fix any failures, then commit**

```bash
git add -A
git commit -m "fix(log): address test failures after log system refactor"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Section 2 (architecture) → Task 1-4. Section 3 (logger specs) → Task 2-4. Section 4 (bug fixes) → Task 5, 7. Section 5 (unified paths) → Task 6, 7. Section 6 (call sites) → Task 6, 7. Section 7 (truncation) → Task 1 (`_shared.py`).
- [x] **Placeholder scan:** No TBD/TODO. All code blocks contain real implementations.
- [x] **Type consistency:** All function signatures match between definition and call sites. `request_id: int` used consistently. `verbose: bool` parameter present on prompt/response functions.