# 第 8 章：多 Agent 协调

## 8.1 解决的问题

复杂任务需要多个专业 Agent 协作。Coordinator 模式让一个"主 Agent"可以：
1. **派生子 Agent**：为特定任务创建专用 Agent
2. **监控进度**：跟踪子 Agent 的执行状态
3. **收集结果**：获取子 Agent 的输出
4. **管理团队**：创建和管理 Agent 团队

## 8.2 Agent 定义

### 8.2.1 AgentDefinition

`coordinator/agent_definitions.py`：

```python
@dataclass
class AgentDefinition:
    name: str                    # Agent 名称
    description: str             # 描述（LLM 理解何时使用）
    system_prompt: str | None    # 自定义系统提示词
    tools: list[str] | None      # 允许使用的工具
    disallowed_tools: list[str]  # 禁止使用的工具
    model: str | None            # 使用的模型
    effort: int | None           # 推理努力等级 (1-5)
    permissions: str | None      # 权限模式
    memory: str | None           # 记忆范围
    isolation: str | None        # 隔离模式
    color: str | None            # UI 颜色
    max_turns: int | None        # 最大轮次
    skills: list[str] | None     # 加载的技能
    mcp_servers: list[str] | None # 连接的 MCP 服务器
    hooks: list[str] | None      # Hook 配置
    initial_prompt: str | None   # 初始提示词
    critical_system_reminder: str | None  # 关键系统提醒
```

### 8.2.2 从 Markdown 文件加载

Agent 定义可以从 Markdown 文件加载（支持 YAML frontmatter + Markdown 正文）：

```markdown
---
name: code-reviewer
description: Expert code review specialist
model: claude-sonnet-4-6
tools: [Read, Grep, Bash]
permissions: plan
memory: project
isolation: worktree
color: green
---

You are a code review expert. Review code for:
1. Logic defects
2. Security issues
3. Performance problems
4. Style violations
```

## 8.3 Coordinator 模式

### 8.3.1 模式触发

`coordinator/coordinator_mode.py` 通过环境变量触发：

```python
def is_coordinator_mode() -> bool:
    """检查环境变量 OPENHARNESS_COORDINATOR_MODE。"""
    return os.environ.get("OPENHARNESS_COORDINATOR_MODE") == "1"
```

### 8.3.2 系统提示词替换

在 Coordinator 模式下，系统提示词被替换为 `get_coordinator_system_prompt()`，其中包含：

1. **角色定义**：你是协调者，负责分派工作
2. **工具列表**：Agent（派生）、SendMessage（通信）、TaskStop（管理）
3. **工作流程**：
   ```
   1) Analyze task → 2) Pick agent(s) → 3) Assign work → 4) Monitor → 5) Collect results
   ```
4. **任务管理**：如何创建、监控、取消任务
5. **结果格式**：如何汇总结果

### 8.3.3 Coordinator 工具

```python
def get_coordinator_tools() -> list[BaseTool]:
    """Coordinator 模式只有三个工具。"""
    return [
        AgentTool(),         # 派生子 Agent
        SendMessageTool(),   # 与子 Agent 通信
        TaskStopTool(),      # 停止任务
    ]
```

### 8.3.4 结果收集

子 Agent 的结果通过 XML 格式信封传递：

```xml
<result agent="code-reviewer" task="review-auth-module">
  <findings>
    <issue severity="high">硬编码密钥在 auth.py:42</issue>
    <issue severity="medium">缺少输入验证在 login()</issue>
  </findings>
</result>
```

## 8.4 Agent 工具实现

### 8.4.1 AgentTool

`tools/agent_tool.py` 实现了子 Agent 派生：

```python
class AgentTool(BaseTool):
    name = "agent"
    description = "Spawn a sub-agent for parallel task execution"
    
    async def execute(self, args, context):
        # 1. 查找 Agent 定义
        agent_def = find_agent_definition(args.name)
        
        # 2. 构建子 Agent 的 RuntimeBundle
        child_bundle = await build_child_runtime(
            agent_def=agent_def,
            task=args.task,
            parent_context=context,
        )
        
        # 3. 启动后台任务
        task_id = start_background_task(child_bundle)
        
        # 4. 返回任务引用
        return ToolResult(output=f"Spawned agent '{args.name}' as task {task_id}")
```

### 8.4.2 SendMessageTool

`tools/send_message_tool.py` 实现 Agent 间通信：

```python
class SendMessageTool(BaseTool):
    name = "send_message"
    description = "Send follow-up to an async agent"
    
    async def execute(self, args, context):
        task_id = args.task_id
        message = args.message
        # 通过 TaskOutput / TaskGet 获取子 Agent 状态
        # 或通过 session_runner 发送新消息
        ...
```

## 8.5 团队管理

### 8.5.1 TeamRegistry

`coordinator/coordinator_mode.py`：

```python
class TeamRegistry:
    """管理 Agent 团队。"""
    
    def __init__(self):
        self._teams: dict[str, TeamRecord] = {}
    
    def create_team(self, name: str, agent_names: list[str]) -> TeamRecord: ...
    def delete_team(self, name: str) -> None: ...
    def get_team(self, name: str) -> TeamRecord | None: ...
    def list_teams(self) -> dict[str, TeamRecord]: ...
```

### 8.5.2 TeamRecord

```python
@dataclass
class TeamRecord:
    name: str
    agent_names: list[str]
    created_at: float
    active_tasks: list[str]  # 当前活跃的任务 ID
```

## 8.6 子会话管理

### 8.6.1 BridgeSessionManager

`bridge/manager.py` 管理子进程会话：

```python
class BridgeSessionManager:
    """追踪派生的子 Agent 会话。"""
    
    def __init__(self):
        self._sessions: dict[str, SessionHandle] = {}
    
    def start_session(self, name, cwd, command) -> SessionHandle: ...
    def stop_session(self, session_id) -> None: ...
    def list_sessions(self) -> list[SessionHandle]: ...
    def read_output(self, session_id) -> str: ...
```

### 8.6.2 子 Agent 进程

子 Agent 以 `run_task_worker` 模式运行（`ui/app.py`），通过 stdin/stdout 的 JSON-lines 协议与父进程通信：

```python
# 子 Agent 启动
python -m openharness --task-worker

# 子 Agent 通过 stdin 接收任务
{"type": "task", "prompt": "review auth.py", ...}

# 子 Agent 通过 stdout 输出结果
{"type": "result", "output": "...", ...}
```

## 8.7 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| Agent 定义 | `coordinator/agent_definitions.py` | `AgentDefinition` |
| Coordinator 模式 | `coordinator/coordinator_mode.py` | `get_coordinator_system_prompt()` |
| Team 管理 | `coordinator/coordinator_mode.py` | `TeamRegistry` |
| Agent 工具 | `tools/agent_tool.py` | `AgentTool` |
| 通信工具 | `tools/send_message_tool.py` | `SendMessageTool` |
| 子会话管理 | `bridge/manager.py` | `BridgeSessionManager` |
| 任务 Worker | `ui/app.py` | `run_task_worker()` |
| 子进程运行 | `bridge/session_runner.py` | `spawn_session()` |

## 8.8 本章小结

多 Agent 协调系统通过 **Coordinator 模式（Master/Worker）+ Agent 定义 + Team 管理** 实现任务分派。主 Agent 负责分解任务、分派给专业子 Agent、监控进度并汇总结果。子 Agent 以独立进程运行，通过 JSON-lines 协议与父进程通信。

> 下一章：[插件与技能系统](09-plugins-skills.md) —— 可扩展架构的核心。
