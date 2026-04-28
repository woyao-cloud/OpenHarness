"""Swarm type definitions for mini_src."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BackendType = Literal["subprocess"]


@dataclass
class TeammateSpawnConfig:
    """Configuration for spawning a teammate subprocess."""

    name: str
    """Human-readable teammate name (e.g. 'researcher')."""

    team: str
    """Team name this teammate belongs to."""

    prompt: str
    """Initial prompt / task for the teammate."""

    cwd: str
    """Working directory for the teammate."""

    model: str | None = None
    """Model override for this teammate."""

    system_prompt: str | None = None
    """System prompt resolved from agent definition."""

    permissions: list[str] = field(default_factory=list)
    """Tool permissions to grant this teammate."""


@dataclass
class SpawnResult:
    """Result from spawning a teammate."""

    task_id: str
    """Task ID in the task manager."""

    agent_id: str
    """Unique agent identifier (format: name@team)."""

    backend_type: BackendType = "subprocess"
    """The backend used to spawn this agent."""

    success: bool = True
    error: str | None = None


@dataclass
class TeammateMessage:
    """Message to send to a teammate."""

    text: str
    from_agent: str
    color: str | None = None
    timestamp: str | None = None
    summary: str | None = None
