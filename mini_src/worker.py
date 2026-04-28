"""Worker entry point for background agent tasks (subprocess mode)."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from mini_src.api.client import AnthropicApiClient, OpenAICompatibleClient
from mini_src.config import (
    get_api_key, get_api_provider, get_base_url, get_max_tokens, get_max_turns,
    get_model, get_provider_base_url,
)
from mini_src.coordinator.coordinator_mode import TaskNotification, format_task_notification
from mini_src.core.engine import QueryEngine
from mini_src.core.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from mini_src.tools.base import ToolRegistry
from mini_src.tools.builtin import create_default_tool_registry

log = logging.getLogger(__name__)


def _build_api_client(api_key: str | None = None, model: str | None = None):
    """Build API client using env vars (same logic as __main__.py)."""
    provider = get_api_provider()
    effective_key = api_key or get_api_key(provider)
    if not effective_key:
        raise ValueError("No API key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY.")

    base_url = get_base_url()

    if provider in ("openai", "deepseek"):
        url = base_url or get_provider_base_url(provider)
        return OpenAICompatibleClient(effective_key, base_url=url)

    return AnthropicApiClient(effective_key, base_url=base_url)


def decode_worker_line(raw: str) -> str:
    """Decode a stdin line — plain text or JSON with 'text' field."""
    stripped = raw.strip()
    if not stripped:
        return ""
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str):
            return text.strip()
    return stripped


async def run_task_worker(
    *,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    task_id: str | None = None,
    max_tokens: int = 4096,
) -> None:
    """Run a stdin-driven headless worker for background agent tasks.

    Reads one line from stdin (the prompt), runs it through the engine,
    streams text output to stdout, and emits a <task-notification> XML
    envelope on completion.
    """
    # 1. Read one line from stdin
    raw = await asyncio.to_thread(sys.stdin.readline)
    if raw == "":
        return
    prompt = decode_worker_line(raw)
    if not prompt:
        return

    # 2. Build API client
    effective_model = model or get_model()
    api_client = _build_api_client(api_key=api_key, model=effective_model)

    # 3. Build tool registry (worker tools only — no coordinator tools)
    registry = ToolRegistry()
    for tool in create_default_tool_registry(coordinator_mode=False):
        registry.register(tool)

    # 4. Build engine
    engine = QueryEngine(
        api_client=api_client,
        tool_registry=registry,
        cwd=Path(cwd or ".").resolve(),
        model=effective_model,
        system_prompt=system_prompt or "You are a helpful AI assistant with access to tools.",
        max_tokens=max_tokens,
        max_turns=max_turns or 200,
    )

    # 5. Submit prompt, stream to stdout
    summary = "completed"
    result_text = ""
    total_tokens = 0
    tool_uses = 0
    start_time = time.monotonic()

    try:
        async for event in engine.submit_message(prompt):
            if isinstance(event, AssistantTextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
                result_text += event.text
            elif isinstance(event, AssistantTurnComplete):
                sys.stdout.write("\n")
                sys.stdout.flush()
                if event.usage:
                    total_tokens += getattr(event.usage, "input_tokens", 0)
                    total_tokens += getattr(event.usage, "output_tokens", 0)
            elif isinstance(event, ToolExecutionStarted):
                tool_uses += 1
            elif isinstance(event, ErrorEvent):
                sys.stdout.write(f"\n[Error: {event.message}]\n")
                sys.stdout.flush()
                summary = f"failed: {event.message}"
            elif isinstance(event, StatusEvent):
                sys.stdout.write(f"\n[{event.message}]\n")
                sys.stdout.flush()
    except Exception as exc:
        log.exception("Worker task failed")
        summary = f"failed: {exc}"
    finally:
        duration_ms = int((time.monotonic() - start_time) * 1000)

    # 6. Emit task notification XML
    notification = TaskNotification(
        task_id=task_id or "",
        status="completed" if not summary.startswith("failed") else "failed",
        summary=summary,
        result=result_text,
        usage={"total_tokens": total_tokens, "tool_uses": tool_uses, "duration_ms": duration_ms},
    )
    sys.stdout.write("\n" + format_task_notification(notification) + "\n")
    sys.stdout.flush()
