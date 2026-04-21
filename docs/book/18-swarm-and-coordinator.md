# 第十八章：多智能体群组与协调器架构

## 概述

OpenHarness 的群组（Swarm）系统实现了一个多智能体协作框架：一个主 Agent（Leader）可以动态生成多个工作 Agent（Worker），通过文件型邮箱（Mailbox）进行异步通信。协调器（Coordinator）层则提供了 Agent 定义加载、模式检测和任务编排能力。桥接层（Bridge）允许 Agent 与外部会话交互。

本章将深入解析：

- `swarm/types.py` — Protocol 类型定义与运行时检查
- `swarm/mailbox.py` — 文件型邮箱系统
- `swarm/registry.py` — 后端自动检测与注册
- `swarm/subprocess_backend.py` — 子进程执行后端
- `swarm/in_process.py` — 进程内执行后端
- `swarm/team_lifecycle.py` — 团队生命周期管理
- `coordinator/agent_definitions.py` — Agent 定义模型
- `coordinator/coordinator_mode.py` — 协调器模式
- `bridge/` — 桥接管理器与会话运行器

> **Java 对比**：群组系统可以类比为 Java 的 ExecutorService + Message Queue 架构。TeammateExecutor 对应 Java 的 Executor 接口，Mailbox 对应 JMS MessageQueue，BackendRegistry 对应 ServiceLoader 的动态发现机制。

---

## 1. Protocol 类型系统：swarm/types.py

### TeammateExecutor Protocol

```python
@runtime_checkable
class TeammateExecutor(Protocol):
    """Protocol for teammate execution backends."""

    type: BackendType

    def is_available(self) -> bool: ...

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult: ...

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None: ...

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool: ...
```

> **Java 对比**：Python 的 `Protocol` 对应 Java 的 `interface`。`@runtime_checkable` 允许在运行时使用 `isinstance(obj, TeammateExecutor)` 检查——这在 Java 中天然支持（`instanceof`），但 Python 默认的 Protocol 只做静态类型检查，加上此装饰器才支持运行时检查。

### PaneBackend Protocol

```python
@runtime_checkable
class PaneBackend(Protocol):
    """Protocol for pane management backends (tmux / iTerm2)."""

    @property
    def type(self) -> BackendType: ...

    @property
    def display_name(self) -> str: ...

    @property
    def supports_hide_show(self) -> bool: ...

    async def is_available(self) -> bool: ...

    async def create_teammate_pane_in_swarm_view(self, name: str, color: str | None = None) -> CreatePaneResult: ...

    async def send_command_to_pane(self, pane_id: PaneId, command: str, ...) -> None: ...

    async def kill_pane(self, pane_id: PaneId, ...) -> bool: ...
    # ... 更多方法
```

> **Java 对比**：Java 中 `@property` 对应 getter 方法。Python 的 `@property` 在 Protocol 中声明了属性而非方法——Java 接口只能声明方法，不能声明字段（除非是 `default` 方法返回值）。Python Protocol 的属性声明更像 Kotlin 的接口属性。

### Literal 类型和数据类

```python
BackendType = Literal["subprocess", "in_process", "tmux", "iterm2"]
MessageType = Literal[
    "user_message", "permission_request", "permission_response",
    "sandbox_permission_request", "sandbox_permission_response",
    "shutdown", "idle_notification",
]

@dataclass
class TeammateIdentity:
    agent_id: str
    name: str
    team: str
    color: str | None = None
    parent_session_id: str | None = None

@dataclass
class SpawnResult:
    task_id: str
    agent_id: str
    backend_type: BackendType
    success: bool = True
    error: str | None = None
    pane_id: PaneId | None = None
```

> **Java 对比**：`Literal` 类型对应 Java 的简单枚举。Python 选择 `Literal` 而非 `Enum` 是因为这些值本质上是字符串，不需要附加方法——在 Java 中等价于 `enum BackendType { SUBPROCESS, IN_PROCESS, TMUX, ITERM2; }` 但用法更轻量。`@dataclass` 对应 Java 14+ 的 `record`，但 Python 版本支持可变字段和默认值。

---

## 2. TeammateMailbox：文件型邮箱

### 项目代码详解

`swarm/mailbox.py` 实现了基于文件系统的异步消息队列：

```python
class TeammateMailbox:
    """File-based mailbox for a single agent within a swarm team."""

    def __init__(self, team_name: str, agent_id: str) -> None:
        self.team_name = team_name
        self.agent_id = agent_id

    async def write(self, msg: MailboxMessage) -> None:
        """Atomically write msg to the inbox as a JSON file."""
        inbox = self.get_mailbox_dir()
        filename = f"{msg.timestamp:.6f}_{msg.id}.json"
        final_path = inbox / filename
        tmp_path = inbox / f"{filename}.tmp"

        payload = json.dumps(msg.to_dict(), indent=2)

        def _write_atomic() -> None:
            with exclusive_file_lock(lock_path):
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, final_path)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_atomic)

    async def read_all(self, unread_only: bool = True) -> list[MailboxMessage]:
        """Return messages from the inbox, sorted by timestamp."""
        # ... 阻塞 I/O 委托给线程池
        return await loop.run_in_executor(None, _read_all)
```

关键设计决策：
- 每条消息一个 JSON 文件，文件名包含时间戳和 UUID
- 原子写入：先写 `.tmp` 再 `os.replace()`
- `exclusive_file_lock` 防止并发写入冲突
- 阻塞 I/O 使用 `run_in_executor()` 委托给线程池

> **Java 对比**：Java 中的消息传递通常使用 JMS、Kafka 或内存队列（`BlockingQueue`）。文件型邮箱更像是 ActiveMQ 的 KahaDB 持久化——用文件系统作为消息存储。`asyncio.create_subprocess_exec()` 对应 Java 的 `ProcessBuilder`。Python 的 `asyncio` + `run_in_executor` 对应 Java 的 `CompletableFuture.supplyAsync()`。

---

## 3. BackendRegistry：后端自动检测

### 项目代码详解

`swarm/registry.py` 实现了后端的自动检测和注册：

```python
class BackendRegistry:
    """Registry that maps BackendType names to TeammateExecutor instances."""

    def __init__(self) -> None:
        self._backends: dict[BackendType, TeammateExecutor] = {}
        self._detected: BackendType | None = None
        self._register_defaults()

    def detect_backend(self) -> BackendType:
        """Detect and cache the most capable available backend."""
        # Priority 1: in-process fallback
        if self._in_process_fallback_active:
            self._detected = "in_process"
            return self._detected

        # Priority 2: tmux (inside session + binary available)
        if _detect_tmux() and "tmux" in self._backends:
            self._detected = "tmux"
            return self._detected

        # Priority 3: subprocess (always available)
        self._detected = "subprocess"
        return self._detected

    def detect_pane_backend(self) -> BackendDetectionResult:
        """Detect which pane backend (tmux / iTerm2) should be used."""
        # 1. tmux > 2. iTerm2+it2 > 3. iTerm2+tmux > 4. error
```

检测策略：
- **tmux**：检查 `$TMUX` 环境变量 + `which tmux`
- **iTerm2**：检查 `$ITERM_SESSION_ID` + `which it2`
- **子进程**：永远可用的兜底方案

> **Java 对比**：BackendRegistry 对应 Java 的 `ServiceLoader` 机制——动态发现可用实现，按优先级选择最佳候选。模块级单例 `get_backend_registry()` 对应 Spring 的单例 Bean 或 Java 的 `ServiceLoader.load()`。

---

## 4. SubprocessBackend：子进程执行后端

```python
class SubprocessBackend:
    """TeammateExecutor that runs each teammate as a separate subprocess."""

    type: BackendType = "subprocess"

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult:
        agent_id = f"{config.name}@{config.team}"
        # 构建 CLI 命令
        teammate_cmd = get_teammate_command()
        cmd_parts = [teammate_cmd, "--task-worker"] + flags
        # 通过 TaskManager 创建子进程
        record = await manager.create_agent_task(
            prompt=config.prompt,
            description=f"Teammate: {agent_id}",
            cwd=config.cwd,
            command=command,
        )
        self._agent_tasks[agent_id] = record.id
        return SpawnResult(task_id=record.id, agent_id=agent_id, backend_type=self.type)

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None:
        """Send a message to a running teammate via its stdin pipe."""
        payload = {"text": message.text, "from": message.from_agent}
        await manager.write_to_task(task_id, json.dumps(payload))
```

> **Java 对比**：`asyncio.create_subprocess_exec()` 直接对应 Java 的 `ProcessBuilder`/`Runtime.exec()`。Python 版本的优势在于 `asyncio` 的异步 I/O——可以非阻塞地管理多个子进程的 stdin/stdout，而 Java 需要 `Process.getInputStream()` + 独立线程来读取。

---

## 5. InProcessBackend：进程内执行后端

### ContextVar 上下文隔离

`swarm/in_process.py` 使用 `contextvars` 实现同一进程内的多 Agent 上下文隔离：

```python
_teammate_context_var: ContextVar[TeammateContext | None] = ContextVar(
    "_teammate_context_var", default=None
)

@dataclass
class TeammateContext:
    agent_id: str
    agent_name: str
    team_name: str
    abort_controller: TeammateAbortController = field(default_factory=TeammateAbortController)
    message_queue: asyncio.Queue[TeammateMessage] = field(default_factory=asyncio.Queue)
    status: TeammateStatus = "starting"
    tool_use_count: int = 0
    total_tokens: int = 0
```

> **Java 对比**：`ContextVar` 对应 Java 的 `ThreadLocal`（或虚拟线程中的 `ScopedValue`）。Python 的 `asyncio.create_task()` 会自动复制当前 Context，等价于 Java 虚拟线程的 `ScopedValue.where()` 绑定。

### 双信号中止控制器

```python
class TeammateAbortController:
    """Dual-signal abort controller for in-process teammates."""

    def __init__(self) -> None:
        self.cancel_event: asyncio.Event = asyncio.Event()    # 优雅取消
        self.force_cancel: asyncio.Event = asyncio.Event()   # 强制终止

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set() or self.force_cancel.is_set()

    def request_cancel(self, reason: str | None = None, *, force: bool = False) -> None:
        if force:
            self.force_cancel.set()
            self.cancel_event.set()
        else:
            self.cancel_event.set()
```

> **Java 对比**：这对应 Java 的 `Future.cancel(mayInterruptIfRunning)` + `Thread.interrupt()` 双通道取消模式。Python 的 `asyncio.Event` 比 Java 的 `CountDownLatch` 更轻量——可以重复 set/reset。

---

## 6. TeamLifecycleManager：团队生命周期

`swarm/team_lifecycle.py` 提供团队的 CRUD 和成员管理：

```python
@dataclass
class TeamFile:
    """Persistent team metadata stored as team.json."""
    name: str
    created_at: float
    description: str = ""
    lead_agent_id: str = ""
    members: dict[str, TeamMember] = field(default_factory=dict)
    team_allowed_paths: list[AllowedPath] = field(default_factory=list)
    hidden_pane_ids: list[str] = field(default_factory=list)

class TeamLifecycleManager:
    def create_team(self, name: str, description: str = "") -> TeamFile: ...
    def delete_team(self, name: str) -> None: ...
    def add_member(self, team_name: str, member: TeamMember) -> TeamFile: ...
    def remove_member(self, team_name: str, agent_id: str) -> TeamFile: ...
```

> **Java 对比**：`TeamFile` 类似于 JPA 的 Entity 类，`TeamLifecycleManager` 类似于 DAO/Repository 层。但 OpenHarness 使用 JSON 文件而非数据库——更轻量，更符合 CLI 工具的场景。

---

## 7. AgentDefinition：Pydantic 模型

```python
# coordinator/agent_definitions.py
class AgentDefinition(BaseModel):
    """Full agent definition with all configuration fields."""
    name: str
    description: str
    system_prompt: str | None = None
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    model: str | None = None
    effort: str | int | None = None
    permission_mode: str | None = None
    color: str | None = None
    # ... 更多字段
```

> **Java 对比**：`AgentDefinition(BaseModel)` 对应 Java 的 POJO + Jackson 注解（`@JsonProperty`）。Pydantic 的 `BaseModel` 自带 JSON 序列化/反序列化、字段验证和默认值——在 Java 中需要 Lombok + Jackson + Bean Validation 才能达到同等效果。

---

## 8. CoordinatorMode：协调器模式

```python
# coordinator/coordinator_mode.py
def is_coordinator_mode() -> bool:
    val = os.environ.get("CLAUDE_CODE_COORDINATOR_MODE", "")
    return val.lower() in {"1", "true", "yes"}

_WORKER_TOOLS = [
    "bash", "file_read", "file_edit", "file_write",
    "glob", "grep", "web_fetch", "web_search",
    "task_create", "task_get", "task_list", "task_output", "skill",
]
```

协调器模式通过环境变量激活。Leader Agent 生成 Worker Agent 时，Worker 只能访问受限的工具集——这确保了安全性边界。

> **Java 对比**：这类似 Java SecurityManager 的权限沙箱——Worker Agent 的工具白名单等价于 Java 的 `PermissionCollection`。

---

## 架构图

```
+-------------------+      Mailbox (JSON)      +-------------------+
|   Leader Agent    |<----------------------->|   Worker Agent 1  |
|   (Main Session)  |                         +-------------------+
|                   |<----------------------->+-------------------+
| TeammateExecutor  |      Permission          |   Worker Agent 2  |
|   (Protocol)      |      Requests/Responses  +-------------------+
+-------------------+       via Mailbox                ...
        |
        | spawn (subprocess / in-process / tmux)
        v
+-------------------+
| Backend Registry  |
| (detect: tmux,   |
|  iterm2, etc.)    |
+-------------------+
        |
        | agent definition
        v
+-------------------+     +-------------------+
| AgentDefinition   |     | CoordinatorMode   |
| (BaseModel/       |     | (env-var gate)    |
|  Pydantic)        |     +-------------------+
+-------------------+
        |
        v
+-------------------+     +-------------------+
| BridgeManager     |     | TeamLifecycle     |
| (session spawner) |     | Manager           |
+-------------------+     +-------------------+
```

---

## 小结

| 模块 | 核心机制 | Java 等价物 |
|------|---------|------------|
| `TeammateExecutor(Protocol)` | 结构化子类型 | `@FunctionalInterface` / Java interface |
| `PaneBackend(Protocol)` + `@runtime_checkable` | 运行时类型检查 | interface + instanceof |
| `TeammateMailbox` | 文件型消息队列 | JMS / Kafka / ActiveMQ KahaDB |
| `BackendRegistry` | 动态发现 + 优先级选择 | ServiceLoader / Spring @Autowired |
| `SubprocessBackend` | asyncio 子进程 | ProcessBuilder |
| `InProcessBackend` | ContextVar 隔离 | ThreadLocal / ScopedValue |
| `TeamAbortController` | 双信号取消 | Future.cancel() + Thread.interrupt() |
| `AgentDefinition(BaseModel)` | Pydantic 模型 | POJO + Jackson + Bean Validation |
| `CoordinatorMode` | 环境变量门控 | SecurityManager 权限沙箱 |
| `exclusive_file_lock` | fcntl/msvcrt 跨平台锁 | FileChannel.lock() |

关键设计原则：
1. **Protocol 优先于继承**：所有后端通过 Protocol 定义契约，无需继承基类
2. **文件型通信**：Mailbox 使用 JSON 文件而非网络套接字——简单、持久化、可调试
3. **上下文隔离**：ContextVar 为并发 Agent 提供独立的执行上下文
4. **优雅降级**：tmux -> iTerm2 -> subprocess -> in_process 逐级回退
5. **原子写入 + 文件锁**：确保多进程环境下的数据一致性