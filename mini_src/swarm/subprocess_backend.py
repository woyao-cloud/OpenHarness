"""Subprocess-based TeammateExecutor for mini_src."""

from __future__ import annotations

import json
import logging
import os
import shlex
import sys

from mini_src.swarm.types import BackendType, SpawnResult, TeammateMessage, TeammateSpawnConfig
from mini_src.tasks.manager import get_task_manager

log = logging.getLogger(__name__)


class SubprocessBackend:
    """Spawn each teammate as a separate subprocess via the task manager."""

    type: BackendType = "subprocess"

    _agent_tasks: dict[str, str]

    def __init__(self) -> None:
        self._agent_tasks = {}

    def is_available(self) -> bool:
        return True

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        """Spawn a new teammate as a subprocess."""
        agent_id = f"{config.name}@{config.team}"

        # Build CLI command
        cmd_parts = [sys.executable, "-m", "mini_src", "--task-worker"]
        if config.model:
            cmd_parts.extend(["--model", shlex.quote(config.model)])
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if api_key:
            cmd_parts.extend(["--api-key", shlex.quote(api_key)])
        command = " ".join(cmd_parts)

        manager = get_task_manager()
        try:
            record = await manager.create_agent_task(
                prompt=config.prompt,
                description=f"Teammate: {agent_id}",
                cwd=config.cwd,
                task_type="local_agent",
                model=config.model,
                command=command,
            )
        except Exception as exc:
            log.error("Failed to spawn teammate %s: %s", agent_id, exc)
            return SpawnResult(
                task_id="",
                agent_id=agent_id,
                backend_type=self.type,
                success=False,
                error=str(exc),
            )

        self._agent_tasks[agent_id] = record.id
        log.debug("Spawned teammate %s as task %s", agent_id, record.id)
        return SpawnResult(task_id=record.id, agent_id=agent_id, backend_type=self.type)

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """Send a message to a running teammate via its stdin."""
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            raise ValueError(f"No active subprocess for agent {agent_id!r}")

        payload: dict[str, str | None] = {
            "text": message.text,
            "from": message.from_agent,
            "timestamp": message.timestamp,
        }
        if message.color:
            payload["color"] = message.color
        if message.summary:
            payload["summary"] = message.summary

        manager = get_task_manager()
        await manager.write_to_task(task_id, json.dumps(payload))
        log.debug("Sent message to %s (task %s)", agent_id, task_id)

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool:
        """Terminate a subprocess teammate."""
        del force
        task_id = self._agent_tasks.get(agent_id)
        if task_id is None:
            log.warning("shutdown() called for unknown agent %s", agent_id)
            return False

        manager = get_task_manager()
        try:
            await manager.stop_task(task_id)
        except ValueError as exc:
            log.debug("stop_task for %s: %s", task_id, exc)
        finally:
            self._agent_tasks.pop(agent_id, None)

        log.debug("Shut down teammate %s (task %s)", agent_id, task_id)
        return True

    def get_task_id(self, agent_id: str) -> str | None:
        """Return the task manager task ID for a given agent."""
        return self._agent_tasks.get(agent_id)
