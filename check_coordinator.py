"""Verify all new coordinator/subagent modules compile and import cleanly."""
import sys
sys.path.insert(0, ".")

print("=== Phase 1: Task types ===")
from mini_src.tasks.types import TaskRecord, TaskType, TaskStatus
print(f"  TaskRecord OK, TaskType={TaskType}, TaskStatus={TaskStatus}")

print("=== Phase 1: Task manager ===")
from mini_src.tasks.manager import BackgroundTaskManager, get_task_manager
print(f"  BackgroundTaskManager OK, manager={get_task_manager()}")

print("=== Phase 2: Swarm types ===")
from mini_src.swarm.types import BackendType, SpawnResult, TeammateSpawnConfig, TeammateMessage
print(f"  All swarm types OK, BackendType={BackendType}")

print("=== Phase 2: Subprocess backend ===")
from mini_src.swarm.subprocess_backend import SubprocessBackend
print(f"  SubprocessBackend OK")

print("=== Phase 3: Agent definitions ===")
from mini_src.coordinator.agent_definitions import AgentDefinition, get_agent_definition
print(f"  AgentDefinition OK")
for name in ["general-purpose", "Explore", "worker"]:
    d = get_agent_definition(name)
    print(f"    {name}: system_prompt={d.system_prompt[:50] if d.system_prompt else None}...")

print("=== Phase 3: Coordinator mode ===")
from mini_src.coordinator.coordinator_mode import (
    TaskNotification, format_task_notification, parse_task_notification,
    TeamRegistry, get_team_registry,
    is_coordinator_mode, get_coordinator_tools,
    get_coordinator_system_prompt, get_coordinator_user_context,
)
print(f"  All coordinator mode OK")
print(f"  Tools: {get_coordinator_tools()}")
prompt = get_coordinator_system_prompt()
print(f"  System prompt: {len(prompt)} chars")

# XML round-trip
n = TaskNotification(task_id="test-1", status="completed", summary="done", result="hello", usage={"total_tokens": 50, "tool_uses": 3, "duration_ms": 1000})
xml = format_task_notification(n)
parsed = parse_task_notification(xml)
assert parsed.task_id == "test-1"
assert parsed.status == "completed"
assert parsed.result == "hello"
assert parsed.usage["total_tokens"] == 50
print(f"  XML round-trip OK")

print("=== Phase 4: Agent tool ===")
from mini_src.tools.agent_tool import AgentTool, AgentToolInput
print(f"  AgentTool OK")

print("=== Phase 4: Send message tool ===")
from mini_src.tools.send_message_tool import SendMessageTool, SendMessageToolInput
print(f"  SendMessageTool OK")

print("=== Phase 4: Task tools ===")
from mini_src.tools.task_get_tool import TaskGetTool
from mini_src.tools.task_list_tool import TaskListTool
from mini_src.tools.task_output_tool import TaskOutputTool
from mini_src.tools.task_stop_tool import TaskStopTool
print(f"  All task tools OK")

print("=== Phase 5: Worker ===")
from mini_src.worker import run_task_worker, decode_worker_line, _build_api_client
print(f"  Worker imports OK")
# Test decode_worker_line
assert decode_worker_line('{"text": "hello"}') == "hello"
assert decode_worker_line("plain text") == "plain text"
assert decode_worker_line("") == ""
print(f"  decode_worker_line OK")

print("=== Phase 5: Coordinator mode tool registration ===")
from mini_src.tools.builtin import create_default_tool_registry
normal_tools = create_default_tool_registry(coordinator_mode=False)
coord_tools = create_default_tool_registry(coordinator_mode=True)
normal_names = [t.name for t in normal_tools]
coord_names = [t.name for t in coord_tools]
print(f"  Normal tools ({len(normal_tools)}): {normal_names}")
print(f"  Coordinator tools ({len(coord_tools)}): {coord_names}")
assert "agent" not in normal_names
assert "agent" in coord_names
assert "task_stop" in coord_names
print(f"  Tool registration OK: coordinator tools only added in coordinator_mode")

print()
print("=== ALL CHECKS PASSED ===")
