"""Tool for writing messages to running agent tasks."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from mini_src.swarm.subprocess_backend import SubprocessBackend
from mini_src.swarm.types import TeammateMessage
from mini_src.tasks.manager import get_task_manager
from mini_src.tools.base import BaseTool, ToolExecutionContext, ToolResult

log = logging.getLogger(__name__)


class SendMessageToolInput(BaseModel):
    """Arguments for sending a follow-up message to a task."""

    task_id: str = Field(description="Target task id or swarm agent_id (name@team)")
    message: str = Field(description="Message to write to the task stdin")


class SendMessageTool(BaseTool):
    """Send a message to a running local agent task."""

    name = "send_message"
    description = "Send a follow-up message to a running local agent task."
    input_model = SendMessageToolInput

    async def execute(self, arguments: SendMessageToolInput, context: ToolExecutionContext) -> ToolResult:
        del context
        if "@" in arguments.task_id:
            backend = SubprocessBackend()
            teammate_msg = TeammateMessage(text=arguments.message, from_agent="coordinator")
            try:
                await backend.send_message(arguments.task_id, teammate_msg)
            except ValueError as exc:
                return ToolResult(output=str(exc), is_error=True)
            except Exception as exc:
                log.error("Failed to send message to %s: %s", arguments.task_id, exc)
                return ToolResult(output=str(exc), is_error=True)
            return ToolResult(output=f"Sent message to agent {arguments.task_id}")
        try:
            await get_task_manager().write_to_task(arguments.task_id, arguments.message)
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=f"Sent message to task {arguments.task_id}")
