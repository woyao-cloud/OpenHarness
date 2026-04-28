"""Tool for spawning local agent subprocesses."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from mini_src.coordinator.agent_definitions import get_agent_definition
from mini_src.coordinator.coordinator_mode import get_team_registry
from mini_src.swarm.subprocess_backend import SubprocessBackend
from mini_src.swarm.types import TeammateSpawnConfig
from mini_src.tools.base import BaseTool, ToolExecutionContext, ToolResult

log = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    """Arguments for local agent spawning."""

    description: str = Field(description="Short description of the delegated work")
    prompt: str = Field(description="Full prompt for the local agent")
    subagent_type: str | None = Field(
        default=None,
        description="Agent type: 'general-purpose', 'Explore', 'worker'",
    )
    model: str | None = Field(default=None)
    command: str | None = Field(default=None, description="Override spawn command")
    team: str | None = Field(default=None, description="Optional team to attach the agent to")


class AgentTool(BaseTool):
    """Spawn a local background agent task."""

    name = "agent"
    description = "Spawn a local background agent task."
    input_model = AgentToolInput

    async def execute(self, arguments: AgentToolInput, context: ToolExecutionContext) -> ToolResult:
        agent_def = None
        if arguments.subagent_type:
            agent_def = get_agent_definition(arguments.subagent_type)

        team = arguments.team or "default"
        agent_name = arguments.subagent_type or "agent"

        backend = SubprocessBackend()
        config = TeammateSpawnConfig(
            name=agent_name,
            team=team,
            prompt=arguments.prompt,
            cwd=str(context.cwd),
            model=arguments.model or (agent_def.model if agent_def else None),
            system_prompt=agent_def.system_prompt if agent_def else None,
            permissions=agent_def.permissions if agent_def else [],
        )

        try:
            result = await backend.spawn(config)
        except Exception as exc:
            log.error("Failed to spawn agent: %s", exc)
            return ToolResult(output=str(exc), is_error=True)

        if not result.success:
            return ToolResult(output=result.error or "Failed to spawn agent", is_error=True)

        if arguments.team:
            registry = get_team_registry()
            try:
                registry.add_agent(arguments.team, result.task_id)
            except ValueError:
                registry.create_team(arguments.team)
                registry.add_agent(arguments.team, result.task_id)

        return ToolResult(
            output=(
                f"Spawned agent {result.agent_id} "
                f"(task_id={result.task_id}, backend={result.backend_type})"
            )
        )
