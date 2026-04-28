"""Coordinator mode detection, system prompt, and XML notification protocol."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional


# ── TeamRegistry ──────────────────────────────────────────────────────


@dataclass
class TeamRecord:
    """A lightweight in-memory team."""

    name: str
    description: str = ""
    agents: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class TeamRegistry:
    """Store teams and agent memberships."""

    def __init__(self) -> None:
        self._teams: dict[str, TeamRecord] = {}

    def create_team(self, name: str, description: str = "") -> TeamRecord:
        if name in self._teams:
            raise ValueError(f"Team '{name}' already exists")
        team = TeamRecord(name=name, description=description)
        self._teams[name] = team
        return team

    def delete_team(self, name: str) -> None:
        if name not in self._teams:
            raise ValueError(f"Team '{name}' does not exist")
        del self._teams[name]

    def add_agent(self, team_name: str, task_id: str) -> None:
        team = self._require_team(team_name)
        if task_id not in team.agents:
            team.agents.append(task_id)

    def send_message(self, team_name: str, message: str) -> None:
        self._require_team(team_name).messages.append(message)

    def list_teams(self) -> list[TeamRecord]:
        return sorted(self._teams.values(), key=lambda t: t.name)

    def _require_team(self, name: str) -> TeamRecord:
        team = self._teams.get(name)
        if team is None:
            raise ValueError(f"Team '{name}' does not exist")
        return team


_DEFAULT_TEAM_REGISTRY: TeamRegistry | None = None


def get_team_registry() -> TeamRegistry:
    """Return the singleton team registry."""
    global _DEFAULT_TEAM_REGISTRY
    if _DEFAULT_TEAM_REGISTRY is None:
        _DEFAULT_TEAM_REGISTRY = TeamRegistry()
    return _DEFAULT_TEAM_REGISTRY


# ── Task Notification XML protocol ────────────────────────────────────


@dataclass
class TaskNotification:
    """Structured result from a completed agent task."""

    task_id: str
    status: str
    summary: str
    result: Optional[str] = None
    usage: Optional[dict[str, int]] = None


_USAGE_FIELDS = ("total_tokens", "tool_uses", "duration_ms")


def format_task_notification(n: TaskNotification) -> str:
    """Serialize a TaskNotification to the canonical XML envelope."""
    parts = [
        "<task-notification>",
        f"<task-id>{n.task_id}</task-id>",
        f"<status>{n.status}</status>",
        f"<summary>{n.summary}</summary>",
    ]
    if n.result is not None:
        parts.append(f"<result>{n.result}</result>")
    if n.usage:
        parts.append("<usage>")
        for key in _USAGE_FIELDS:
            if key in n.usage:
                parts.append(f"  <{key}>{n.usage[key]}</{key}>")
        parts.append("</usage>")
    parts.append("</task-notification>")
    return "\n".join(parts)


def parse_task_notification(xml: str) -> TaskNotification:
    """Parse a <task-notification> XML string into a TaskNotification."""

    def _extract(tag: str) -> Optional[str]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
        return m.group(1).strip() if m else None

    task_id = _extract("task-id") or ""
    status = _extract("status") or ""
    summary = _extract("summary") or ""
    result = _extract("result")

    usage: Optional[dict[str, int]] = None
    usage_block = re.search(r"<usage>(.*?)</usage>", xml, re.DOTALL)
    if usage_block:
        usage = {}
        for key in _USAGE_FIELDS:
            m = re.search(rf"<{key}>(\d+)</{key}>", usage_block.group(1))
            if m:
                usage[key] = int(m.group(1))

    return TaskNotification(
        task_id=task_id,
        status=status,
        summary=summary,
        result=result,
        usage=usage,
    )


# ── Coordinator mode detection ───────────────────────────────────────


_AGENT_TOOL_NAME = "agent"
_SEND_MESSAGE_TOOL_NAME = "send_message"
_TASK_STOP_TOOL_NAME = "task_stop"


def is_coordinator_mode() -> bool:
    """Return True when the process is running in coordinator mode."""
    val = os.environ.get("CLAUDE_CODE_COORDINATOR_MODE", "")
    return val.lower() in {"1", "true", "yes"}


def get_coordinator_tools() -> list[str]:
    """Return the tool names reserved for the coordinator."""
    return [
        _AGENT_TOOL_NAME,
        _SEND_MESSAGE_TOOL_NAME,
        _TASK_STOP_TOOL_NAME,
        "task_output",
        "task_list",
        "task_get",
    ]


def get_coordinator_user_context() -> dict[str, str]:
    """Build the workerToolsContext for the coordinator's user turn."""
    if not is_coordinator_mode():
        return {}
    return {
        "workerToolsContext": (
            f"Workers spawned via the {_AGENT_TOOL_NAME} tool have "
            "access to read, write, edit, bash, glob, and grep tools. "
            "They run autonomously and report results via XML task notifications."
        )
    }


# ── Coordinator system prompt ────────────────────────────────────────


def get_coordinator_system_prompt() -> str:
    """Return the system prompt for coordinator mode."""
    return f"""You are an AI assistant that orchestrates software engineering tasks across multiple workers.

## 1. Your Role

You are a **coordinator**. Your job is to:
- Help the user achieve their goal
- Direct workers to research, implement and verify code changes
- Synthesize results and communicate with the user
- Answer questions directly when possible — don't delegate work that you can handle without tools

Every message you send is to the user. Worker results are internal signals — never thank or acknowledge them. Summarize new information for the user as it arrives.

## 2. Your Tools

- **{_AGENT_TOOL_NAME}** — Spawn a new worker subagent
- **{_SEND_MESSAGE_TOOL_NAME}** — Continue an existing worker (send a follow-up)
- **{_TASK_STOP_TOOL_NAME}** — Stop a running worker
- **task_get** — Check a worker's status
- **task_list** — List all workers (optionally filter by status)
- **task_output** — Read a worker's output log

When calling {_AGENT_TOOL_NAME}:
- Use subagent_type "worker" for implementation tasks, "Explore" for research
- Do not use workers to trivially report file contents — give them substantive tasks
- Use {_SEND_MESSAGE_TOOL_NAME} to continue workers whose work is in progress
- Briefly tell the user what you launched and end your response

### Worker Results

Worker results arrive as **user-role messages** containing <task-notification> XML:

```xml
<task-notification>
<task-id>{{agentId}}</task-id>
<status>completed|failed|killed</status>
<summary>{{human-readable status summary}}</summary>
<result>{{agent's final text response}}</result>
<usage>
  <total_tokens>N</total_tokens>
  <tool_uses>N</tool_uses>
  <duration_ms>N</duration_ms>
</usage>
</task-notification>
```

<result> and <usage> are optional. The <summary> describes the outcome. Use {_SEND_MESSAGE_TOOL_NAME} with the <task-id> to continue a worker.

## 3. Workers

Workers have access to read, write, edit, bash, glob, and grep tools. They execute autonomously and report back when done. Workers cannot see your conversation with the user — every prompt must be self-contained.

## 4. Task Workflow

Most tasks break down into phases:

| Phase | Who | Purpose |
|-------|-----|---------|
| Research | Workers (parallel) | Investigate codebase, find files, understand problem |
| Synthesis | **You** | Read findings, understand the problem, craft specs |
| Implementation | Workers | Make targeted changes per spec |
| Verification | Workers | Test changes work |

**Parallelism is your superpower.** Launch independent workers concurrently — don't serialize work that can run simultaneously.

### Writing Worker Prompts

Every prompt must be self-contained. When research completes, you must:
1. Read the findings
2. Synthesize a specific prompt with file paths, line numbers, and exactly what to change
3. Choose: continue the same worker (it has context) or spawn a fresh one (clean context)

**Good**: "Fix the null pointer in src/auth/validate.ts:42. Add a null check before accessing user.id — if null, return 401."
**Bad**: "Based on your findings, fix the bug" — you must synthesize, not delegate understanding.

### Handling Worker Failures

When a worker reports failure, continue it with {_SEND_MESSAGE_TOOL_NAME} — it has the full error context. If a correction attempt fails, try a different approach or report to the user.

### Stopping Workers

Use {_TASK_STOP_TOOL_NAME} to stop a worker you sent in the wrong direction. Stopped workers can be continued with {_SEND_MESSAGE_TOOL_NAME}. Workers that have already completed can also be continued — they restart and receive the new prompt."""
