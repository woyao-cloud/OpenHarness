"""HTTPX-based API clients for Anthropic and OpenAI providers.

Replaces the anthropic and openai SDKs with direct HTTP calls.
Implements the SupportsStreamingMessages protocol used by the query engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

import httpx

from mini_src.api.errors import (
    AuthenticationFailure,
    OpenHarnessApiError,
    RateLimitFailure,
    RequestFailure,
)
from mini_src.api.usage import UsageSnapshot
from mini_src.config import needs_max_completion_tokens
from mini_src.core.messages import (
    ConversationMessage,
    ContentBlock,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    assistant_message_from_api,
)

log = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_ANTHROPIC_VERSION = "2023-06-01"


# ── Shared protocol and event types ────────────────────────────────────


@dataclass(frozen=True)
class ApiMessageRequest:
    """Input parameters for a model invocation."""

    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ApiTextDeltaEvent:
    """Incremental text produced by the model."""

    text: str


@dataclass(frozen=True)
class ApiMessageCompleteEvent:
    """Terminal event containing the full assistant message."""

    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None = None


@dataclass(frozen=True)
class ApiRetryEvent:
    """A recoverable upstream failure that will be retried automatically."""

    message: str
    attempt: int
    max_attempts: int
    delay_seconds: float


ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent


class SupportsStreamingMessages(Protocol):
    """Protocol used by the query engine."""

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        ...


# ── Retry helpers ─────────────────────────────────────────────────────


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status and status in RETRYABLE_STATUS_CODES:
        return True
    if isinstance(exc, (ConnectionError, TimeoutError, OSError, httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


def _get_retry_delay(attempt: int) -> float:
    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def _ensure_str(value: object) -> str:
    """Convert API error message to a readable string."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip() or "(empty response)"
    if value is None:
        return "(no error message)"
    return str(value)


def _translate_anthropic_error(status_code: int, body: dict[str, Any]) -> OpenHarnessApiError:
    error = body.get("error", {})
    error_type = error.get("type", "") if isinstance(error, dict) else ""
    msg = _ensure_str(error.get("message", str(body) if not isinstance(error, dict) else ""))
    prefix = f"[HTTP {status_code}] "
    if error_type in {"authentication_error", "permission_error"}:
        return AuthenticationFailure(prefix + msg)
    if status_code == 429 or error_type == "rate_limit_error":
        return RateLimitFailure(prefix + msg)
    return RequestFailure(prefix + msg)


def _translate_openai_error(status_code: int, body: dict[str, Any]) -> OpenHarnessApiError:
    raw = body.get("error", {})
    msg = _ensure_str(raw.get("message", str(body)) if isinstance(raw, dict) else str(body))
    prefix = f"[HTTP {status_code}] "
    if status_code in (401, 403):
        return AuthenticationFailure(prefix + msg)
    if status_code == 429:
        return RateLimitFailure(prefix + msg)
    return RequestFailure(prefix + msg)


# ── Anthropic client ──────────────────────────────────────────────────


class AnthropicApiClient:
    """HTTPX-based Anthropic Messages API client."""

    BASE_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, *, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.BASE_URL).rstrip("/")

    @property
    def base_url(self) -> str:
        return self._base_url

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async for event in self._stream_once(request):
                    yield event
                return
            except OpenHarnessApiError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= MAX_RETRIES or not _is_retryable(exc):
                    raise RequestFailure(str(exc)) from exc
                delay = _get_retry_delay(attempt)
                log.warning("Anthropic API failed (attempt %d/%d, url=%s), retrying in %.1fs: %s",
                            attempt + 1, MAX_RETRIES + 1, self._base_url, delay, exc)
                yield ApiRetryEvent(
                    message=str(exc), attempt=attempt + 1,
                    max_attempts=MAX_RETRIES + 1, delay_seconds=delay,
                )
                await asyncio.sleep(delay)

        if last_error is not None:
            msg = str(last_error)
            if any(x in msg.lower() for x in ("connect", "timeout", "dns", "resolve")):
                raise RequestFailure(
                    f"Cannot reach Anthropic API at {self._base_url}. "
                    f"Check network connectivity.  Details: {msg}"
                ) from last_error

    async def _stream_once(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [m.to_api_param() for m in request.messages],
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        if request.system_prompt:
            body["system"] = request.system_prompt
        if request.tools:
            body["tools"] = request.tools

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", self._base_url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    err_body = await _read_body(resp)
                    raise _translate_anthropic_error(resp.status_code, err_body)

                collected_text = ""
                collected_tool_calls: dict[int, dict[str, Any]] = {}
                usage_data: dict[str, int] = {}
                stop_reason: str | None = None
                reasoning_content: str | None = None

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    # Capture reasoning_content for DeepSeek thinking mode
                    # (may appear in content_block_delta, message_start, or as a top-level field)
                    raw = data
                    raw_reasoning = (
                        raw.get("reasoning_content")
                        or (raw.get("delta") or {}).get("reasoning_content")
                        or (raw.get("message") or {}).get("reasoning_content")
                    )
                    if raw_reasoning and isinstance(raw_reasoning, str):
                        if reasoning_content is None:
                            reasoning_content = ""
                        reasoning_content += raw_reasoning

                    if event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                collected_text += text
                                yield ApiTextDeltaEvent(text=text)

                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            idx = data.get("index", 0)
                            collected_tool_calls[idx] = {
                                "id": block.get("id", f"toolu_{uuid.uuid4().hex}"),
                                "name": block.get("name", ""),
                                "input": "",
                            }

                    elif event_type == "content_block_stop":
                        pass

                    elif event_type == "message_start":
                        msg = data.get("message", {})
                        usage = msg.get("usage", {})
                        if usage:
                            usage_data = {
                                "input_tokens": usage.get("input_tokens", 0),
                                "output_tokens": usage.get("output_tokens", 0),
                            }

                    elif event_type == "message_delta":
                        delta = data.get("delta", {})
                        stop_reason = delta.get("stop_reason", stop_reason)
                        usage = data.get("usage", {})
                        if usage:
                            usage_data = {
                                "input_tokens": usage_data.get("input_tokens", 0),
                                "output_tokens": usage.get("output_tokens", 0),
                            }

                # Build final message
                content: list[ContentBlock] = []
                if collected_text:
                    content.append(TextBlock(text=collected_text))
                for _idx in sorted(collected_tool_calls.keys()):
                    tc = collected_tool_calls[_idx]
                    content.append(ToolUseBlock(
                        id=tc["id"], name=tc["name"], input=tc.get("input") or {},
                    ))

                final_message = ConversationMessage(
                    role="assistant", content=content,
                    reasoning_content=reasoning_content,
                )

                yield ApiMessageCompleteEvent(
                    message=final_message,
                    usage=UsageSnapshot(
                        input_tokens=usage_data.get("input_tokens", 0),
                        output_tokens=usage_data.get("output_tokens", 0),
                    ),
                    stop_reason=stop_reason,
                )


# ── OpenAI-compatible client ──────────────────────────────────────────


def _convert_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic tool schemas to OpenAI function-calling format."""
    result = []
    for tool in tools:
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        })
    return result


def _convert_messages_to_openai(
    messages: list[ConversationMessage],
    system_prompt: str | None,
) -> list[dict[str, Any]]:
    """Convert Anthropic-style messages to OpenAI chat format."""
    openai_messages: list[dict[str, Any]] = []

    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if msg.role == "assistant":
            text_parts = [b.text for b in msg.content if isinstance(b, TextBlock)]
            tool_uses = [b for b in msg.content if isinstance(b, ToolUseBlock)]
            content = "".join(text_parts)
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            assistant_msg["content"] = content if content else None
            if msg.reasoning_content:
                assistant_msg["reasoning_content"] = msg.reasoning_content
            if tool_uses:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tu.id,
                        "type": "function",
                        "function": {
                            "name": tu.name,
                            "arguments": json.dumps(tu.input),
                        },
                    }
                    for tu in tool_uses
                ]
            openai_messages.append(assistant_msg)

        elif msg.role == "user":
            tool_results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
            user_blocks = [b for b in msg.content if isinstance(b, (TextBlock,))]

            if tool_results:
                for tr in tool_results:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_use_id,
                        "content": tr.content,
                    })
            if user_blocks:
                text = "".join(b.text for b in user_blocks)
                if text.strip():
                    openai_messages.append({"role": "user", "content": text})

    return openai_messages


class OpenAICompatibleClient:
    """HTTPX-based OpenAI-compatible API client."""

    BASE_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, *, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.BASE_URL).rstrip("/")

    @property
    def base_url(self) -> str:
        return self._base_url

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async for event in self._stream_once(request):
                    yield event
                return
            except OpenHarnessApiError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= MAX_RETRIES or not _is_retryable(exc):
                    api_status = getattr(exc, "status_code", None)
                    if api_status:
                        raise _translate_openai_error(api_status, {"error": {"message": str(exc)}}) from exc
                    raise RequestFailure(str(exc)) from exc
                delay = _get_retry_delay(attempt)
                log.warning("OpenAI API failed (attempt %d/%d, url=%s), retrying in %.1fs: %s",
                            attempt + 1, MAX_RETRIES + 1, self._base_url, delay, exc)
                yield ApiRetryEvent(
                    message=str(exc), attempt=attempt + 1,
                    max_attempts=MAX_RETRIES + 1, delay_seconds=delay,
                )
                await asyncio.sleep(delay)

        if last_error is not None:
            msg = str(last_error)
            if any(x in msg.lower() for x in ("connect", "timeout", "dns", "resolve")):
                raise RequestFailure(
                    f"Cannot reach API at {self._base_url}. "
                    f"Check: 1) network connectivity  2) OPENHARNESS_BASE_URL is correct  "
                    f"3) a VPN/proxy may be required.  Details: {msg}"
                ) from last_error
            raise RequestFailure(msg) from last_error

    async def _stream_once(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        openai_messages = _convert_messages_to_openai(request.messages, request.system_prompt)
        openai_tools = _convert_tools_to_openai(request.tools) if request.tools else None

        body: dict[str, Any] = {
            "model": request.model,
            "messages": openai_messages,
            "stream": True,
        }
        if needs_max_completion_tokens(request.model):
            body["max_completion_tokens"] = request.max_tokens
        else:
            body["max_tokens"] = request.max_tokens
        if openai_tools:
            body["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", self._base_url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    err_body = await _read_body(resp)
                    raise _translate_openai_error(resp.status_code, err_body)

                collected_content = ""
                collected_tool_calls: dict[int, dict[str, Any]] = {}
                usage_data: dict[str, int] = {}
                finish_reason: str | None = None
                reasoning_content: str | None = None

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if not chunk.get("choices"):
                        if chunk.get("usage"):
                            usage_data = {
                                "input_tokens": chunk["usage"].get("prompt_tokens", 0),
                                "output_tokens": chunk["usage"].get("completion_tokens", 0),
                            }
                        continue

                    delta = chunk["choices"][0].get("delta", {})
                    chunk_finish = chunk["choices"][0].get("finish_reason")
                    if chunk_finish:
                        finish_reason = chunk_finish

                    if delta.get("content"):
                        collected_content += delta["content"]
                        yield ApiTextDeltaEvent(text=delta["content"])

                    # Capture reasoning_content for DeepSeek thinking mode
                    raw_reasoning = delta.get("reasoning_content")
                    if raw_reasoning and isinstance(raw_reasoning, str):
                        if reasoning_content is None:
                            reasoning_content = ""
                        reasoning_content += raw_reasoning

                    if delta.get("tool_calls"):
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            if idx not in collected_tool_calls:
                                collected_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                            entry = collected_tool_calls[idx]
                            if tc_delta.get("id"):
                                entry["id"] = tc_delta["id"]
                            if tc_delta.get("function"):
                                if tc_delta["function"].get("name"):
                                    entry["name"] = tc_delta["function"]["name"]
                                if tc_delta["function"].get("arguments"):
                                    entry["arguments"] += tc_delta["function"]["arguments"]

                content: list[ContentBlock] = []
                if collected_content:
                    content.append(TextBlock(text=collected_content))
                for _idx in sorted(collected_tool_calls.keys()):
                    tc = collected_tool_calls[_idx]
                    if not tc["name"]:
                        continue
                    try:
                        args = json.loads(tc["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    content.append(ToolUseBlock(id=tc["id"], name=tc["name"], input=args))

                final_message = ConversationMessage(
                    role="assistant", content=content,
                    reasoning_content=reasoning_content,
                )
                yield ApiMessageCompleteEvent(
                    message=final_message,
                    usage=UsageSnapshot(
                        input_tokens=usage_data.get("input_tokens", 0),
                        output_tokens=usage_data.get("output_tokens", 0),
                    ),
                    stop_reason=finish_reason,
                )


async def _read_body(resp: httpx.Response) -> dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        raw = await resp.aread()
        text = raw.decode("utf-8", errors="replace").strip()[:500] if raw else "(empty response)"
        return {"error": {"message": text}}
