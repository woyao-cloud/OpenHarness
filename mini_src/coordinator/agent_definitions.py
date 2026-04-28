"""Agent definition models for subagent types."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentDefinition(BaseModel):
    """Configuration for a subagent type."""

    name: str
    description: str
    system_prompt: str | None = None
    model: str | None = None
    permissions: list[str] = Field(default_factory=list)
    subagent_type: str = "general-purpose"


_SHARED_PREFIX = (
    "You are an agent for mini_src. Given the user's message, "
    "use the tools available to complete the task. Complete the task fully."
)

_BUILTIN_DEFINITIONS: dict[str, AgentDefinition] = {
    "general-purpose": AgentDefinition(
        name="general-purpose",
        description="General-purpose agent with full tool access",
        system_prompt=_SHARED_PREFIX,
        subagent_type="general-purpose",
    ),
    "Explore": AgentDefinition(
        name="Explore",
        description="Read-only exploration and research agent",
        system_prompt=(
            _SHARED_PREFIX
            + "\n\nYou are in read-only exploration mode. "
            "You can read files, search code, and browse the web, "
            "but you must NOT write, edit, or execute commands that modify files."
        ),
        subagent_type="Explore",
    ),
    "worker": AgentDefinition(
        name="worker",
        description="Implementation-focused worker agent",
        system_prompt=_SHARED_PREFIX,
        subagent_type="worker",
    ),
}


def get_agent_definition(name: str) -> AgentDefinition | None:
    """Look up a built-in agent definition by name."""
    return _BUILTIN_DEFINITIONS.get(name)
