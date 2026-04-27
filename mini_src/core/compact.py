"""
Conversation compaction for mini_src.

Four-stage escalation (cheapest first):
  1. Microcompact — clear old tool result bodies
  2. Context collapse — deterministically truncate oversized text blocks
  3. Session memory — cheap one-line-per-message summary
  4. Full compact — LLM-based structured summarization

Port from OpenHarness ``services/compact/__init__.py``, simplified.
Omitted: attachment builders, progress callbacks, checkpoint tracking.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

from mini_src.api.client import ApiMessageCompleteEvent, ApiMessageRequest, SupportsStreamingMessages
from mini_src.core.messages import (
    ConversationMessage,
    ContentBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────

COMPACTABLE_TOOLS: frozenset[str] = frozenset({
    "read_file", "bash", "grep", "glob", "write_file", "edit_file",
})

TIME_BASED_MC_CLEARED_MESSAGE = "[Old tool result content cleared]"

AUTOCOMPACT_BUFFER_TOKENS = 13_000
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3
COMPACT_TIMEOUT_SECONDS = 25
MAX_COMPACT_STREAMING_RETRIES = 2
MAX_PTL_RETRIES = 3
SESSION_MEMORY_KEEP_RECENT = 12
SESSION_MEMORY_MAX_LINES = 48
SESSION_MEMORY_MAX_CHARS = 4_000
CONTEXT_COLLAPSE_TEXT_CHAR_LIMIT = 2_400
CONTEXT_COLLAPSE_HEAD_CHARS = 900
CONTEXT_COLLAPSE_TAIL_CHARS = 500
TOKEN_ESTIMATION_PADDING = 4 / 3
DEFAULT_KEEP_RECENT = 5
_DEFAULT_CONTEXT_WINDOW = 200_000
PTL_RETRY_MARKER = "[earlier conversation truncated for compaction retry]"
ERROR_MESSAGE_INCOMPLETE_RESPONSE = "Compaction interrupted before a complete summary was returned."

CompactionKind = Literal["full", "session_memory"]
CompactTrigger = Literal["auto", "manual", "reactive"]

# ── Data structures ────────────────────────────────────────────────────


@dataclass
class AutoCompactState:
    """Mutable state that persists across query loop turns."""

    compacted: bool = False
    turn_counter: int = 0
    consecutive_failures: int = 0


@dataclass
class CompactionResult:
    """Structured compaction result."""

    trigger: CompactTrigger
    compact_kind: CompactionKind
    boundary_marker: ConversationMessage
    summary_messages: list[ConversationMessage]
    messages_to_keep: list[ConversationMessage]
    compact_metadata: dict[str, Any] = field(default_factory=dict)


# ── Token estimation ──────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Naive char-based token estimate: ``max(1, len(text) // 4)``."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_message_tokens(messages: list[ConversationMessage]) -> int:
    """Estimate total tokens for a conversation, with padding."""
    total = 0
    for msg in messages:
        for block in msg.content:
            if isinstance(block, TextBlock):
                total += estimate_tokens(block.text)
            elif isinstance(block, ToolResultBlock):
                total += estimate_tokens(block.content)
            elif isinstance(block, ToolUseBlock):
                total += estimate_tokens(block.name)
                total += estimate_tokens(str(block.input))
    return int(total * TOKEN_ESTIMATION_PADDING)


# ── Context window helpers ────────────────────────────────────────────


def get_context_window(model: str, *, context_window_tokens: int | None = None) -> int:
    """Return the effective context window for *model*."""
    if context_window_tokens is not None and context_window_tokens > 0:
        return int(context_window_tokens)
    return _DEFAULT_CONTEXT_WINDOW


def get_autocompact_threshold(
    model: str,
    *,
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
) -> int:
    """Return the token count at which auto-compact fires."""
    if auto_compact_threshold_tokens is not None and auto_compact_threshold_tokens > 0:
        return int(auto_compact_threshold_tokens)
    context_window = get_context_window(model, context_window_tokens=context_window_tokens)
    reserved = min(MAX_OUTPUT_TOKENS_FOR_SUMMARY, 20_000)
    return context_window - reserved - AUTOCOMPACT_BUFFER_TOKENS


def should_autocompact(
    messages: list[ConversationMessage],
    model: str,
    state: AutoCompactState,
    *,
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
) -> bool:
    """Return True when the conversation should be auto-compacted."""
    if state.consecutive_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
        return False
    token_count = estimate_message_tokens(messages)
    threshold = get_autocompact_threshold(
        model,
        context_window_tokens=context_window_tokens,
        auto_compact_threshold_tokens=auto_compact_threshold_tokens,
    )
    return token_count >= threshold


# ── Stage 1: Microcompact ─────────────────────────────────────────────


def _collect_compactable_tool_ids(messages: list[ConversationMessage]) -> list[str]:
    """Walk messages and collect tool_use IDs whose results are compactable."""
    ids: list[str] = []
    for msg in messages:
        if msg.role != "assistant":
            continue
        for block in msg.content:
            if isinstance(block, ToolUseBlock) and block.name in COMPACTABLE_TOOLS:
                ids.append(block.id)
    return ids


def microcompact_messages(
    messages: list[ConversationMessage],
    *,
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> tuple[list[ConversationMessage], int]:
    """Clear old compactable tool results, keeping the most recent *keep_recent*.

    This is the cheap first pass — no LLM call required.
    Returns ``(messages, tokens_saved)``.
    """
    keep_recent = max(1, keep_recent)
    all_ids = _collect_compactable_tool_ids(messages)
    if len(all_ids) <= keep_recent:
        return messages, 0

    keep_set = set(all_ids[-keep_recent:])
    clear_set = set(all_ids) - keep_set
    tokens_saved = 0

    for msg in messages:
        if msg.role != "user":
            continue
        new_content: list[ContentBlock] = []
        for block in msg.content:
            if (
                isinstance(block, ToolResultBlock)
                and block.tool_use_id in clear_set
                and block.content != TIME_BASED_MC_CLEARED_MESSAGE
            ):
                tokens_saved += estimate_tokens(block.content)
                new_content.append(ToolResultBlock(
                    tool_use_id=block.tool_use_id,
                    content=TIME_BASED_MC_CLEARED_MESSAGE,
                    is_error=block.is_error,
                ))
            else:
                new_content.append(block)
        msg.content = new_content

    if tokens_saved > 0:
        log.info("Microcompact cleared %d tool results, saved ~%d tokens", len(clear_set), tokens_saved)
    return messages, tokens_saved


# ── Stage 2: Context collapse ─────────────────────────────────────────


def _collapse_text(text: str) -> str:
    """Truncate oversized text to head + tail with a collapse marker."""
    if len(text) <= CONTEXT_COLLAPSE_TEXT_CHAR_LIMIT:
        return text
    omitted = len(text) - CONTEXT_COLLAPSE_HEAD_CHARS - CONTEXT_COLLAPSE_TAIL_CHARS
    head = text[:CONTEXT_COLLAPSE_HEAD_CHARS].rstrip()
    tail = text[-CONTEXT_COLLAPSE_TAIL_CHARS:].lstrip()
    return f"{head}\n...[collapsed {omitted} chars]...\n{tail}"


def try_context_collapse(
    messages: list[ConversationMessage],
    *,
    preserve_recent: int,
) -> list[ConversationMessage] | None:
    """Deterministically shrink oversized text blocks before full compact."""
    if len(messages) <= preserve_recent + 2:
        return None

    older = messages[:-preserve_recent]
    newer = messages[-preserve_recent:]
    changed = False
    collapsed_older: list[ConversationMessage] = []
    for message in older:
        new_blocks: list[ContentBlock] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                collapsed = _collapse_text(block.text)
                if collapsed != block.text:
                    changed = True
                new_blocks.append(TextBlock(text=collapsed))
            else:
                new_blocks.append(block)
        collapsed_older.append(ConversationMessage(role=message.role, content=new_blocks))

    if not changed:
        return None
    result = [*collapsed_older, *newer]
    if estimate_message_tokens(result) >= estimate_message_tokens(messages):
        return None
    return result


# ── PTL retry helpers ─────────────────────────────────────────────────


def _group_messages_by_prompt_round(messages: list[ConversationMessage]) -> list[list[ConversationMessage]]:
    """Group messages into prompt-response rounds."""
    groups: list[list[ConversationMessage]] = []
    current: list[ConversationMessage] = []
    for message in messages:
        starts_new_round = (
            message.role == "user"
            and not any(isinstance(b, ToolResultBlock) for b in message.content)
            and bool(message.text.strip())
        )
        if starts_new_round and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    return groups


def truncate_head_for_ptl_retry(
    messages: list[ConversationMessage],
) -> list[ConversationMessage] | None:
    """Drop the oldest prompt rounds when the compact request itself is too large."""
    groups = _group_messages_by_prompt_round(messages)
    if len(groups) < 2:
        return None

    drop_count = max(1, len(groups) // 5)
    drop_count = min(drop_count, len(groups) - 1)
    retained = [message for group in groups[drop_count:] for message in group]
    if not retained:
        return None
    if retained[0].role == "assistant":
        return [ConversationMessage.from_user_text(PTL_RETRY_MARKER), *retained]
    return retained


# ── Stage 3: Session memory compaction ────────────────────────────────


def _summarize_message_for_memory(message: ConversationMessage) -> str:
    """Produce a one-line summary of a message for session memory."""
    text = " ".join(message.text.split())
    if text:
        text = text[:160]
        return f"{message.role}: {text}"
    tool_uses = [block.name for block in message.tool_uses]
    if tool_uses:
        return f"{message.role}: tool calls -> {', '.join(tool_uses[:4])}"
    if any(isinstance(block, ToolResultBlock) for block in message.content):
        return f"{message.role}: tool results returned"
    return f"{message.role}: [non-text content]"


def _build_session_memory_message(messages: list[ConversationMessage]) -> ConversationMessage | None:
    """Build a single user message that summarises *messages* as line items."""
    lines: list[str] = []
    total_chars = 0
    for message in messages:
        line = _summarize_message_for_memory(message)
        if not line:
            continue
        projected = total_chars + len(line) + 1
        if lines and (len(lines) >= SESSION_MEMORY_MAX_LINES or projected >= SESSION_MEMORY_MAX_CHARS):
            lines.append("... earlier context condensed ...")
            break
        lines.append(line)
        total_chars = projected
    if not lines:
        return None
    body = "\n".join(lines)
    return ConversationMessage.from_user_text(
        "Session memory summary from earlier in this conversation:\n" + body
    )


def try_session_memory_compaction(
    messages: list[ConversationMessage],
    *,
    preserve_recent: int = SESSION_MEMORY_KEEP_RECENT,
    trigger: CompactTrigger = "auto",
) -> CompactionResult | None:
    """Cheap deterministic compaction before full LLM compaction.

    Summarises older messages as one-line-per-message entries.
    Returns ``None`` when there are too few messages to compact or when
    the estimate does not actually decrease.
    """
    if len(messages) <= preserve_recent + 4:
        return None

    pre_compact_tokens = estimate_message_tokens(messages)
    older = messages[:-preserve_recent]
    newer = messages[-preserve_recent:]

    summary_msg = _build_session_memory_message(older)
    if summary_msg is None:
        return None

    candidate = [summary_msg, *newer]
    if estimate_message_tokens(candidate) >= pre_compact_tokens:
        return None

    compact_metadata: dict[str, Any] = {
        "compact_kind": "session_memory",
        "pre_compact_message_count": len(messages),
        "pre_compact_tokens": pre_compact_tokens,
    }

    return CompactionResult(
        trigger=trigger,
        compact_kind="session_memory",
        boundary_marker=_create_compact_boundary_message(compact_metadata),
        summary_messages=[summary_msg],
        messages_to_keep=newer,
        compact_metadata=compact_metadata,
    )


# ── Stage 4: Full compact — prompt & formatting ──────────────────────

NO_TOOLS_PREAMBLE = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use read_file, bash, grep, glob, edit_file, write_file, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

"""

BASE_COMPACT_PROMPT = """\
Your task is to create a detailed summary of the conversation so far. This summary will replace the earlier messages, so it must capture all important information.

First, draft your analysis inside <analysis> tags. Walk through the conversation chronologically and extract:
- Every user request and intent (explicit and implicit)
- The approach taken and technical decisions made
- Specific code, files, and configurations discussed (with paths and line numbers where available)
- All errors encountered and how they were fixed
- Any user feedback or corrections

Then, produce a structured summary inside <summary> tags with these sections:

1. **Primary Request and Intent**: All user requests in full detail, including nuances and constraints.
2. **Key Technical Concepts**: Technologies, frameworks, patterns, and conventions discussed.
3. **Files and Code Sections**: Every file examined or modified, with specific code snippets and line numbers.
4. **Errors and Fixes**: Every error encountered, its cause, and how it was resolved.
5. **Problem Solving**: Problems solved and approaches that worked vs. didn't work.
6. **All User Messages**: Non-tool-result user messages (preserve exact wording for context).
7. **Pending Tasks**: Explicitly requested work that hasn't been completed yet.
8. **Current Work**: Detailed description of the last task being worked on before compaction.
"""

NO_TOOLS_TRAILER = """
REMINDER: Do NOT call any tools. Respond with plain text only — an <analysis> block followed by a <summary> block. Tool calls will be rejected."""


def get_compact_prompt(custom_instructions: str | None = None) -> str:
    """Build the full compaction prompt sent to the model."""
    prompt = NO_TOOLS_PREAMBLE + BASE_COMPACT_PROMPT
    if custom_instructions and custom_instructions.strip():
        prompt += f"\n\nAdditional Instructions:\n{custom_instructions}"
    prompt += NO_TOOLS_TRAILER
    return prompt


def format_compact_summary(raw_summary: str) -> str:
    """Strip the <analysis> scratchpad and extract the <summary> content."""
    text = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw_summary)
    m = re.search(r"<summary>([\s\S]*?)</summary>", text)
    if m:
        text = text.replace(m.group(0), f"Summary:\n{m.group(1).strip()}")
    text = re.sub(r"\n\n+", "\n\n", text)
    return text.strip()


def build_compact_summary_message(
    summary: str,
    *,
    suppress_follow_up: bool = True,
    recent_preserved: bool = False,
) -> str:
    """Create the injected user message that replaces compacted history."""
    formatted = format_compact_summary(summary)
    text = (
        "This session is being continued from a previous conversation that ran "
        "out of context. The summary below covers the earlier portion of the "
        "conversation.\n\n"
        f"{formatted}"
    )
    if recent_preserved:
        text += "\n\nRecent messages are preserved verbatim."
    if suppress_follow_up:
        text += (
            "\nContinue the conversation from where it left off without asking "
            "the user any further questions. Resume directly — do not acknowledge "
            "the summary, do not recap what was happening, do not preface with "
            '"I\'ll continue" or similar. Pick up the last task as if the break '
            "never happened."
        )
    return text


def _create_compact_boundary_message(metadata: dict[str, Any]) -> ConversationMessage:
    """Create a boundary marker message for post-compact conversation rebuild."""
    lines = [
        "Earlier conversation was compacted. The summary below covers the earlier portion.",
    ]
    compact_kind = str(metadata.get("compact_kind") or "").strip()
    pre_messages = metadata.get("pre_compact_message_count")
    pre_tokens = metadata.get("pre_compact_tokens")

    if compact_kind:
        lines.append(f"Compaction kind: {compact_kind}")
    if pre_messages:
        lines.append(f"Pre-compact message count: {pre_messages}")
    if pre_tokens:
        lines.append(f"Pre-compact token estimate: ~{pre_tokens}")

    text = "\n".join(lines)
    return ConversationMessage.from_user_text(text)


# ── Stage 4: Full compact — execution ─────────────────────────────────


async def compact_conversation(
    messages: list[ConversationMessage],
    *,
    api_client: SupportsStreamingMessages,
    model: str,
    system_prompt: str = "",
    preserve_recent: int = 6,
    custom_instructions: str | None = None,
    suppress_follow_up: bool = True,
    trigger: CompactTrigger = "manual",
) -> CompactionResult:
    """Compact messages by calling the LLM to produce a summary.

    1. Microcompact first (cheap token reduction).
    2. Split into older (to summarize) and recent (to preserve).
    3. Call the LLM with the compact prompt to get a structured summary.
    4. Replace older messages with the summary + preserved recent messages.
    """
    if len(messages) <= preserve_recent:
        return _passthrough_result(
            messages, trigger=trigger, compact_kind="full",
            reason="conversation already within preserve_recent window",
        )

    # Step 1: microcompact
    messages, tokens_freed = microcompact_messages(messages, keep_recent=DEFAULT_KEEP_RECENT)

    pre_compact_tokens = estimate_message_tokens(messages)
    log.info("Compacting conversation: %d messages, ~%d tokens", len(messages), pre_compact_tokens)

    # Step 2: split
    older = messages[:-preserve_recent]
    newer = messages[-preserve_recent:]

    # Step 3: build compact request
    compact_prompt = get_compact_prompt(custom_instructions)
    compact_messages: list[ConversationMessage] = list(older) + [ConversationMessage.from_user_text(compact_prompt)]

    # Step 4: call LLM with retry
    summary_text = await _collect_summary(api_client, model, system_prompt, compact_messages)

    if not summary_text:
        log.warning("Compact summary was empty, returning passthrough")
        return _passthrough_result(
            messages, trigger=trigger, compact_kind="full",
            reason="empty summary from LLM",
        )

    # Step 5: build post-compact messages
    summary_msg_text = build_compact_summary_message(
        summary_text,
        suppress_follow_up=suppress_follow_up,
        recent_preserved=True,
    )
    summary_msg = ConversationMessage.from_user_text(summary_msg_text)

    compact_metadata: dict[str, Any] = {
        "compact_kind": "full",
        "pre_compact_message_count": len(messages),
        "pre_compact_tokens": pre_compact_tokens,
        "post_compact_message_count": len(newer) + 1,
        "tokens_freed_by_microcompact": tokens_freed,
    }

    return CompactionResult(
        trigger=trigger,
        compact_kind="full",
        boundary_marker=_create_compact_boundary_message(compact_metadata),
        summary_messages=[summary_msg],
        messages_to_keep=newer,
        compact_metadata=compact_metadata,
    )


async def _collect_summary(
    api_client: SupportsStreamingMessages,
    model: str,
    system_prompt: str,
    compact_messages: list[ConversationMessage],
) -> str:
    """Call the LLM with the compact prompt and collect the summary text.

    Retries on errors and prompt-too-long conditions.
    """
    text_chunks: list[str] = []
    retry_messages = compact_messages
    ptl_retries_left = MAX_PTL_RETRIES
    streaming_retries_left = MAX_COMPACT_STREAMING_RETRIES

    for attempt in range(MAX_PTL_RETRIES + MAX_COMPACT_STREAMING_RETRIES + 1):
        text_chunks.clear()
        final_event: ApiMessageCompleteEvent | None = None

        try:
            request = ApiMessageRequest(
                model=model,
                messages=retry_messages,
                system_prompt=system_prompt,
                max_tokens=8192,
                tools=[],
            )
            async for event in api_client.stream_message(request):
                if isinstance(event, ApiMessageCompleteEvent):
                    final_event = event
                else:
                    text_chunks.append(event.text)

            text = "".join(text_chunks)
            if final_event is not None and final_event.message.text:
                text = final_event.message.text
            return text

        except Exception as exc:
            error_msg = str(exc).lower()
            log.warning("Compact LLM call failed (attempt %d): %s", attempt + 1, exc)

            # PTL retry — drop oldest ~20% of prompt rounds
            if any(needle in error_msg for needle in ("prompt too long", "context length", "context window", "too many tokens")):
                if ptl_retries_left > 0:
                    ptl_retries_left -= 1
                    truncated = truncate_head_for_ptl_retry(retry_messages)
                    if truncated is not None:
                        retry_messages = truncated
                        log.info("PTL retry: dropped oldest ~20%% of prompt rounds (%d remaining)", ptl_retries_left)
                        continue

            # Streaming retry
            if streaming_retries_left > 0:
                streaming_retries_left -= 1
                log.info("Streaming retry (%d remaining)", streaming_retries_left)
                continue

            # All retries exhausted
            log.error("Compact LLM call exhausted all retries: %s", exc)
            return ""

    return ""


def _passthrough_result(
    messages: list[ConversationMessage],
    *,
    trigger: CompactTrigger,
    compact_kind: CompactionKind,
    reason: str = "",
) -> CompactionResult:
    """Create a passthrough result when compaction is skipped."""
    compact_metadata: dict[str, Any] = {"reason": reason, "compact_kind": compact_kind}
    log.info("Compact passthrough (%s): %s", compact_kind, reason)
    return CompactionResult(
        trigger=trigger,
        compact_kind=compact_kind,
        boundary_marker=_create_compact_boundary_message(compact_metadata),
        summary_messages=[],
        messages_to_keep=list(messages),
        compact_metadata=compact_metadata,
    )


# ── Auto-compact orchestration ────────────────────────────────────────


async def auto_compact_if_needed(
    messages: list[ConversationMessage],
    *,
    api_client: SupportsStreamingMessages,
    model: str,
    system_prompt: str = "",
    state: AutoCompactState,
    preserve_recent: int = 6,
    force: bool = False,
    trigger: CompactTrigger = "auto",
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
) -> tuple[list[ConversationMessage], bool]:
    """Check if auto-compact should fire, and if so, compact.

    Progressive escalation:
      1. Microcompact (cheapest)
      2. Context collapse (deterministic truncation)
      3. Session memory (line-per-message summary)
      4. Full compact (LLM summary)

    Returns ``(messages, was_compacted)``.
    """
    if not force and not should_autocompact(
        messages, model, state,
        context_window_tokens=context_window_tokens,
        auto_compact_threshold_tokens=auto_compact_threshold_tokens,
    ):
        return messages, False

    log.info("Auto-compact triggered (failures=%d)", state.consecutive_failures)

    # Stage 1: microcompact
    mc_messages, tokens_freed = microcompact_messages(list(messages))
    if tokens_freed > 0:
        mc_messages_list = list(mc_messages)
        if not should_autocompact(
            mc_messages_list, model, state,
            context_window_tokens=context_window_tokens,
            auto_compact_threshold_tokens=auto_compact_threshold_tokens,
        ):
            log.info("Microcompact freed ~%d tokens, auto-compact no longer needed", tokens_freed)
            return mc_messages_list, True

    # Stage 2: context collapse
    collapsed = try_context_collapse(mc_messages, preserve_recent=preserve_recent)
    if collapsed is not None:
        if not should_autocompact(
            collapsed, model, state,
            context_window_tokens=context_window_tokens,
            auto_compact_threshold_tokens=auto_compact_threshold_tokens,
        ):
            log.info("Context collapse freed enough tokens")
            return collapsed, True

    # Stage 3: session memory
    session_result = try_session_memory_compaction(
        collapsed if collapsed is not None else mc_messages,
        preserve_recent=preserve_recent,
        trigger=trigger,
    )
    if session_result is not None:
        state.compacted = True
        state.consecutive_failures = 0
        log.info("Session memory compaction successful")
        return _build_post_compact_messages(session_result), True

    # Stage 4: full compact
    try:
        result = await compact_conversation(
            collapsed if collapsed is not None else mc_messages,
            api_client=api_client,
            model=model,
            system_prompt=system_prompt,
            preserve_recent=preserve_recent,
            trigger=trigger,
        )
        if result.summary_messages:
            state.compacted = True
            state.consecutive_failures = 0
            log.info("Full compaction successful")
            return _build_post_compact_messages(result), True
    except Exception as exc:
        log.error("Auto-compact failed: %s", exc)
        state.consecutive_failures += 1
        return messages, False

    return messages, False


def _build_post_compact_messages(result: CompactionResult) -> list[ConversationMessage]:
    """Rebuild the post-compact message list."""
    return [
        result.boundary_marker,
        *result.summary_messages,
        *result.messages_to_keep,
    ]
