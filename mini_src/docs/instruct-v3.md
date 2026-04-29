 Plan: Port Coordinator & Subagent to mini_src

 Context

 Allow mini_src to spawn background subagent tasks (subprocess workers) for parallel work, and add a coordinator mode where the AI acts as an "orchestrator" that delegates
 to workers. Port from OpenHarness's coordinator/, swarm/, tasks/ packages. Workers run as headless --task-worker subprocesses.

 Not porting (v1): in-process backend, mailbox system, worktree isolation, tmux/iTerm2 panes, plugin agent definitions, permission sync, agent colors/effort/memory scopes.

 ---
 File Changes (18 files, ~1100 lines)

 Phase 1 — Task Foundation

 ┌────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                File                │                                                             Content                                                              │
 ├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tasks/types.py (NEW,      │ TaskType, TaskStatus, TaskRecord dataclass                                                                                       │
 │ ~30L)                              │                                                                                                                                  │
 ├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tasks/manager.py (NEW,    │ BackgroundTaskManager — spawn subprocesses via create_subprocess_shell, track state, read output log, stop tasks, write to       │
 │ ~200L)                             │ stdin. Singleton via get_task_manager().                                                                                         │
 ├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tasks/__init__.py (NEW)   │ Package init                                                                                                                     │
 └────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 Phase 2 — Swarm Backend

 ┌───────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                     File                      │                                                        Content                                                        │
 ├───────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/swarm/types.py (NEW, ~40L)           │ BackendType, SpawnResult, TeammateSpawnConfig, TeammateMessage dataclasses                                            │
 ├───────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/swarm/subprocess_backend.py (NEW,    │ SubprocessBackend — spawn() builds CLI python -m mini_src --task-worker, calls task manager; send_message() writes    │
 │ ~120L)                                        │ JSON to stdin; shutdown() stops task                                                                                  │
 ├───────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/swarm/__init__.py (NEW)              │ Package init                                                                                                          │
 └───────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 Phase 3 — Coordinator Mode

 ┌─────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                      File                       │                                                       Content                                                       │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/coordinator/agent_definitions.py (NEW, │ AgentDefinition Pydantic model; built-in definitions: general-purpose, Explore, worker                              │
 │  ~80L)                                          │                                                                                                                     │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/coordinator/coordinator_mode.py (NEW,  │ TaskNotification + XML serialization, TeamRegistry, is_coordinator_mode(), get_coordinator_tools(),                 │
 │ ~200L)                                          │ get_coordinator_system_prompt() (~120 lines), get_coordinator_user_context()                                        │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/coordinator/__init__.py (NEW)          │ Package init                                                                                                        │
 └─────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 Phase 4 — Coordinator Tools

 ┌─────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                      File                       │                                               Content                                               │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/agent_tool.py (NEW, ~70L)        │ agent tool — description, prompt, subagent_type, model, command, team. Spawns via SubprocessBackend │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/send_message_tool.py (NEW, ~50L) │ send_message tool — task_id, message. Routes via task manager or subprocess backend                 │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/task_stop_tool.py (NEW, ~25L)    │ task_stop tool — stop a background task                                                             │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/task_output_tool.py (NEW, ~30L)  │ task_output tool — read task output log                                                             │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/task_list_tool.py (NEW, ~30L)    │ task_list tool — list tasks, optional status filter                                                 │
 ├─────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/task_get_tool.py (NEW, ~30L)     │ task_get tool — get single task details                                                             │
 └─────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────┘

 Phase 5 — Integration

 ┌────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                File                │                                                             Content                                                              │
 ├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/worker.py (NEW, ~130L)    │ run_task_worker() — reads one JSON line from stdin, builds QueryEngine, submits prompt, streams AssistantTextDelta to stdout,    │
 │                                    │ emits <task-notification> XML on completion                                                                                      │
 ├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/tools/builtin.py (MODIFY, │ create_default_tool_registry(coordinator_mode=False) — lazy-imports coordinator tools when coordinator_mode=True                 │
 │  +20L)                             │                                                                                                                                  │
 ├────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ mini_src/__main__.py (MODIFY,      │ Add --task-worker, --api-key, --task-id CLI args; route to run_task_worker(); inject coordinator system prompt + tools when      │
 │ +60L)                              │ is_coordinator_mode()                                                                                                            │
 └────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 ---
 Key Design Decisions

 1. Worker is one-shot: reads one stdin line, processes, exits. Task manager restarts for follow-ups.
 2. No BackendRegistry: SubprocessBackend instantiated directly in agent/send_message tools. Only subprocess backend.
 3. Coordinator tools injected via create_default_tool_registry(coordinator_mode): lazy imports inside function body avoid circular deps.
 4. Coordinator prompt replaces default (~120 lines vs OpenHarness's ~520): core structure preserved (role, tools, workers, XML protocol, best practices), examples
 condensed.
 5. Worker streams text to stdout, emits <task-notification> XML as final line. Coordinator reads via task_output.
 6. Task log files: get_data_dir() / "tasks/" (same as OpenHarness path convention).

 ---
 Circular Import Safety

 - tasks/types.py, swarm/types.py, coordinator/agent_definitions.py — leaf nodes
 - tasks/manager.py → tasks/types, config
 - swarm/subprocess_backend.py → swarm/types, tasks/manager
 - coordinator/coordinator_mode.py → coordinator/agent_definitions
 - tools/agent_tool.py → coordinator/*, swarm/*, tools/base
 - tools/send_message_tool.py → swarm/*, tasks/manager, tools/base
 - tools/task_*.py → tasks/manager, tools/base
 - tools/builtin.py (modified) → lazy imports inside create_default_tool_registry()
 - worker.py → core/engine, core/events, tools/builtin, coordinator/coordinator_mode
 - __main__.py → coordinator/*, tools/builtin, worker

 No cycles.

 ---
 Verification

 1. Import check: python -c "from mini_src.tasks.manager import BackgroundTaskManager"
 2. Coordinator mode off: python -m mini_src "hello" — existing behavior unchanged
 3. Coordinator tools registered: Run with CLAUDE_CODE_COORDINATOR_MODE=1, verify agent, send_message, task_stop tools appear in schema
 4. Worker test: echo '{"text":"say hello"}' | python -m mini_src --task-worker — should output text + <task-notification> XML
 5. Agent tool flow (requires API key): Run in coordinator mode, spawn subagent via agent tool, poll with task_get/task_output
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌

 Claude has written up a plan and is ready to execute. Would you like to proceed?



 ● Coordinator and subagent port is complete. Here's the summary:

  Files Created (15 new, 2 modified, ~1100 lines total)

  Phase 1 — Task Foundation

  ┌────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │            File            │                                                       Lines                                                       │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/tasks/__init__.py │ 1                                                                                                                 │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/tasks/types.py    │ 31                                                                                                                │
  ├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/tasks/manager.py  │ 203 — BackgroundTaskManager with create_shell_task, create_agent_task, stop_task, write_to_task, read_task_output │
  └────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Phase 2 — Swarm Backend

  ┌──────────────────────────────────────┬────────────────────────────────────────────────────────────┐
  │                 File                 │                           Lines                            │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ mini_src/swarm/__init__.py           │ 1                                                          │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ mini_src/swarm/types.py              │ 59 — TeammateSpawnConfig, SpawnResult, TeammateMessage     │
  ├──────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ mini_src/swarm/subprocess_backend.py │ 118 — SubprocessBackend with spawn, send_message, shutdown │
  └──────────────────────────────────────┴────────────────────────────────────────────────────────────┘

  Phase 3 — Coordinator Mode

  ┌───────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                   File                    │                                                           Lines                                                            │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/coordinator/__init__.py          │ 1                                                                                                                          │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/coordinator/agent_definitions.py │ 50 — AgentDefinition model, general-purpose, Explore, worker built-in types                                                │
  ├───────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/coordinator/coordinator_mode.py  │ 255 — TaskNotification + XML protocol, TeamRegistry, is_coordinator_mode(), get_coordinator_system_prompt() (~120 lines),  │
  │                                           │ get_coordinator_user_context()                                                                                             │
  └───────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  Phase 4 — Coordinator Tools (6 tools)

  ┌─────────────────────────────────────┬──────────────────────────────────────────┐
  │                File                 │                  Lines                   │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ mini_src/tools/agent_tool.py        │ 75 — agent tool (spawn subagents)        │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ mini_src/tools/send_message_tool.py │ 56 — send_message tool (continue agents) │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ mini_src/tools/task_stop_tool.py    │ 26 — task_stop tool                      │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ mini_src/tools/task_output_tool.py  │ 31 — task_output tool                    │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ mini_src/tools/task_list_tool.py    │ 36 — task_list tool                      │
  ├─────────────────────────────────────┼──────────────────────────────────────────┤
  │ mini_src/tools/task_get_tool.py     │ 31 — task_get tool                       │
  └─────────────────────────────────────┴──────────────────────────────────────────┘

  Phase 5 — Integration

  ┌───────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────┐
  │           File            │                                             Lines                                              │
  ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/worker.py        │ 129 — run_task_worker() entry point (stdin → engine → stdout + XML notification)               │
  ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/tools/builtin.py │ modified — create_default_tool_registry(coordinator_mode=False)                                │
  ├───────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ mini_src/__main__.py      │ modified — added --task-worker, coordinator mode detection, coordinator tools/prompt injection │
  └───────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────┘

  Key differences from full OpenHarness

  - No in-process backend, no mailbox system, no tmux/iTerm2 panes, no worktree isolation
  - Worker is one-shot: reads one prompt, processes, exits. Task manager restarts for follow-ups
  - Coordinator prompt is ~120 lines vs OpenHarness's ~520 (core structure preserved, examples condensed)
  - Only subprocess backend supported — SubprocessBackend instantiated directly, no BackendRegistry

  How to use

  # Coordinator mode
  CLAUDE_CODE_COORDINATOR_MODE=1 python -m mini_src
  # → agent, send_message, task_stop, task_get/list/output tools registered

  # Worker mode (used by subagent subprocesses automatically)
  echo '{"text":"read src/main.py"}' | python -m mini_src --task-worker
  # → streams assistant text + <task-notification> XML to stdout


    具体流程：

  1. 启动 coordinator 模式：CLAUDE_CODE_COORDINATOR_MODE=1 python -m mini_src
  2. AI 在一次回复中发起多个 agent 工具调用，例如：
    - agent(description="研究后端API", subagent_type="Explore", prompt="...")
    - agent(description="研究前端组件", subagent_type="Explore", prompt="...")
  3. 所有 agent 工具调用被并行执行（asyncio.gather），每个 spawn 一个 python -m mini_src --task-worker 子进程
  4. coordinater 用 task_get/task_output 轮询各 worker 的完成状态和输出
  5. worker 完成时，输出的最后一行是 <task-notification> XML，包含 task-id、status、summary、result、usage

  示例交互：

  You: 让我并行调查这个问题。
    ▶ agent({"description": "研究数据库schema", "prompt": "..."})
    ▶ agent({"description": "研究API路由", "prompt": "..."})
    两个worker已启动，等待结果...

  User: <task-notification><task-id>researcher@default</task-id><status>completed</status>...</task-notification>
  User: <task-notification><task-id>researcher@default</task-id><status>completed</status>...</task-notification>

  You: 结果已返回，[合成结果...]
    ▶ send_message({"task_id": "researcher@default", "message": "继续修复..."})

  关键点：多个 agent 工具调用必须在 AI 的同一条回复消息中发出，run_query() 才会用 asyncio.gather 并行执行它们。如果 AI 分多条消息发出，worker 会串行启动。