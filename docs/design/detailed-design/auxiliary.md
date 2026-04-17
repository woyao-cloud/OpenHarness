# OpenHarness 辅助模块详细设计文档

> 版本: 1.0 | 日期: 2026-04-17
> 覆盖模块: `coordinator/`, `tasks/`, `sandbox/`, `themes/`, `keybindings/`, `output_styles/`, `vim/`, `voice/`, `state/`, `utils/`, `platforms/`
> 总计: ~2,605 行, 44 文件

---

## 1. 模块概述

### 1.1 定位与职责

辅助模块群为 OpenHarness 的核心引擎与 TUI 提供横向支撑能力，涵盖：

- **Agent 编排**: Agent 定义加载、团队注册、协调者模式检测
- **后台任务**: Shell 与 Agent 子进程的创建、监控、输出收集
- **沙箱隔离**: 双后端（srt + Docker）的命令包装与路径边界校验
- **个性化**: 主题、快捷键、输出样式的加载与合并
- **交互模式**: Vim 模式切换、语音输入诊断
- **应用状态**: 可观测的共享状态存储（Observer 模式驱动 TUI 重渲染）
- **跨平台工具**: 文件原子写入、排他锁、Shell 解析、网络安全防护、平台能力检测

### 1.2 模块总览

| 模块 | 文件数 | 行数 | 核心概念 | 复杂度 |
|------|--------|------|----------|--------|
| `coordinator/` | 3 | ~450 | AgentDefinition, TeamRegistry, 协调者模式 | ★★ |
| `tasks/` | 6 | ~480 | TaskRecord, BackgroundTaskManager | ★★ |
| `sandbox/` | 6 | ~450 | 双后端沙箱, 路径校验, Docker 会话 | ★★★ |
| `themes/` | 4 | ~200 | ThemeConfig, 5 内置主题 | ★ |
| `keybindings/` | 5 | ~150 | 快捷键解析、合并、解析 | ★ |
| `output_styles/` | 2 | ~60 | 3 内置 + 自定义输出样式 | ★ |
| `vim/` | 2 | ~35 | Vim 模式状态切换 | ★ |
| `voice/` | 4 | ~200 | 语音诊断, 关键词提取, STT 占位 | ★★ |
| `state/` | 3 | ~100 | AppState, Observer Store | ★ |
| `utils/` | 5 | ~280 | 原子写入, 文件锁, Shell, 网络防护 | ★★ |
| `platforms.py` | 1 | ~110 | 平台检测, 能力矩阵 | ★ |

### 1.3 模块间依赖关系

```
platforms.py  ←── sandbox/adapter.py, sandbox/docker_backend.py, utils/file_lock.py, utils/shell.py
config/       ←── sandbox/adapter.py, tasks/manager.py, utils/shell.py
utils/fs.py   ←── config/settings.py (原子写入)
utils/file_lock.py ←── config/settings.py, swarm (排他锁)
utils/network_guard.py ←── tools/web_fetch, tools/web_search (SSRF 防护)
utils/shell.py ←── tasks/manager.py (子进程创建), sandbox (命令包装)
sandbox/      ←── utils/shell.py, tasks (间接)
state/        ←── ui/runtime (TUI 重渲染)
themes/       ←── ui (主题渲染)
keybindings/  ←── ui (键盘事件分发)
coordinator/  ←── engine (Agent 工具调度)
tasks/        ←── coordinator (后台任务), tools (task_create 等)
```

---

## 2. Coordinator — Agent 编排

### 2.1 模块概述

coordinator 模块负责 Agent 定义的加载、内存团队注册以及协调者模式的检测与配置。

| 文件 | 行数 | 职责 |
|------|------|------|
| `coordinator/__init__.py` | 13 | 模块公开导出 |
| `coordinator/agent_definitions.py` | ~893 | AgentDefinition 模型、YAML/Markdown 加载、内置 Agent |
| `coordinator/coordinator_mode.py` | ~520 | TeamRegistry、协调者模式检测、系统提示词、XML 通知 |

**模块总行数：~1,426 行**

### 2.2 核心类/接口

#### AgentDefinition (BaseModel)

```python
class AgentDefinition(BaseModel):
    # --- 必填 ---
    name: str                              # Agent 类型标识符
    description: str                       # whenToUse 描述

    # --- 提示词 / 工具 ---
    system_prompt: str | None              # 自定义系统提示词
    tools: list[str] | None                # 允许的工具列表 (None = 全部)
    disallowed_tools: list[str] | None     # 禁止的工具列表

    # --- 模型与努力度 ---
    model: str | None                      # 模型覆盖 (如 "haiku", "inherit")
    effort: str | int | None               # "low" | "medium" | "high" 或正整数

    # --- 权限 ---
    permission_mode: str | None            # PERMISSION_MODES 之一

    # --- Agent 循环控制 ---
    max_turns: int | None                  # 最大轮次 (> 0)

    # --- 技能与 MCP ---
    skills: list[str] = []                 # 订阅的 Skill 列表
    mcp_servers: list[Any] | None          # MCP 服务器引用或内联配置
    required_mcp_servers: list[str] | None  # 必须存在的服务器模式

    # --- 钩子 ---
    hooks: dict[str, Any] | None           # Agent 级会话钩子

    # --- UI ---
    color: str | None                      # AGENT_COLORS 之一

    # --- 生命周期 ---
    background: bool = False               # 始终以后台任务运行
    initial_prompt: str | None             # 首轮用户消息前置文本
    memory: str | None                     # "user" | "project" | "local"
    isolation: str | None                  # "worktree" | "remote"

    # --- 元数据 ---
    filename: str | None                   # 原始文件名 (不含 .md)
    base_dir: str | None                   # 加载来源目录
    critical_system_reminder: str | None   # 每轮重新注入的提醒消息
    pending_snapshot_update: dict | None   # 内存快照跟踪
    omit_claude_md: bool = False           # 跳过 CLAUDE.md 注入

    # --- Python 特有 ---
    permissions: list[str] = []            # 额外权限规则
    subagent_type: str = "general-purpose" # 路由键
    source: Literal["builtin", "user", "plugin"] = "builtin"
```

**常量约束**:

| 常量 | 值 | 用途 |
|------|----|------|
| `AGENT_COLORS` | `frozenset({"red","green","blue","yellow","purple","orange","cyan","magenta","white","gray"})` | 合法颜色名 |
| `EFFORT_LEVELS` | `("low", "medium", "high")` | 合法努力度 |
| `PERMISSION_MODES` | `("default","acceptEdits","bypassPermissions","plan","dontAsk")` | 合法权限模式 |
| `MEMORY_SCOPES` | `("user", "project", "local")` | 合法内存范围 |
| `ISOLATION_MODES` | `("worktree", "remote")` | 合法隔离模式 |

#### TeamRegistry

```python
class TeamRegistry:
    """内存中的轻量团队注册。"""

    def create_team(self, name: str, description: str = "") -> TeamRecord
    def delete_team(self, name: str) -> None
    def add_agent(self, team_name: str, task_id: str) -> None
    def send_message(self, team_name: str, message: str) -> None
    def list_teams(self) -> list[TeamRecord]
```

#### TeamRecord

```python
@dataclass
class TeamRecord:
    name: str
    description: str = ""
    agents: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
```

#### 协调者模式检测

```python
def is_coordinator_mode() -> bool
    # 检查 CLAUDE_CODE_COORDINATOR_MODE 环境变量

def match_session_mode(session_mode: str | None) -> str | None
    # 对齐环境变量与会话模式, 返回警告字符串或 None

def get_coordinator_tools() -> list[str]
    # 返回 ["agent", "send_message", "task_stop"]

def get_coordinator_user_context(mcp_clients, scratchpad_dir) -> dict[str, str]
    # 构建 workerToolsContext 注入

def get_coordinator_system_prompt() -> str
    # 返回协调者模式系统提示词
```

#### 通知序列化

```python
@dataclass
class TaskNotification:
    task_id: str
    status: str
    summary: str
    result: str | None
    usage: dict[str, int] | None

def format_task_notification(n: TaskNotification) -> str   # XML 序列化
def parse_task_notification(xml: str) -> TaskNotification   # XML 反序列化
```

### 2.3 数据模型

**Worker 工具矩阵**:

| 模式 | 工具集 |
|------|--------|
| 标准模式 | bash, file_read, file_edit, file_write, glob, grep, web_fetch, web_search, task_create, task_get, task_list, task_output, skill |
| Simple 模式 (`CLAUDE_CODE_SIMPLE=1`) | bash, file_read, file_edit |

**7 个内置 Agent**:

| Agent | subagent_type | 模型 | 颜色 | 只读 | 特点 |
|-------|---------------|------|------|------|------|
| general-purpose | general-purpose | 默认 | - | 否 | 全工具访问 |
| statusline-setup | statusline-setup | sonnet | orange | 否 | Read + Edit |
| claude-code-guide | claude-code-guide | haiku | - | 否 | Glob+Grep+Read+WebFetch+WebSearch |
| Explore | Explore | haiku | - | 是 | 禁止 agent/edit/write/notebook |
| Plan | Plan | inherit | - | 是 | 禁止 agent/edit/write/notebook |
| worker | worker | 默认 | - | 否 | 全工具访问 |
| verification | verification | inherit | red | 是 | 后台运行, 禁止 agent/edit/write/notebook |

### 2.4 关键算法

**Agent 定义加载流程** (`load_agents_dir`):

```
遍历目录 *.md 文件
  → 解析 YAML 前置元数据 (--- 封装块)
    → yaml.safe_load() 解析, 失败回退简单 key:value 解析
  → Markdown body 作为 system_prompt
  → 逐字段解析: name, description, tools, disallowedTools, model, effort,
    permissionMode, maxTurns, skills, mcpServers, hooks, color, background,
    initialPrompt, memory, isolation, omitClaudeMd, criticalSystemReminder,
    requiredMcpServers, permissions
  → 构造 AgentDefinition(source="user")
  → 解析失败: logger.debug + 跳过
```

**辅助解析器**:
- `_parse_str_list(raw)`: 将逗号分隔字符串或列表统一为 `list[str]`
- `_parse_positive_int(raw)`: 将前向值解析为正整数, 无效返回 `None`

### 2.5 接口规范

| 函数 | 签名 | 返回值 | 异常 |
|------|------|--------|------|
| `get_builtin_agent_definitions()` | `() -> list[AgentDefinition]` | 7 个内置 Agent 副本 | 无 |
| `load_agents_dir(directory)` | `(Path) -> list[AgentDefinition]` | 用户自定义 Agent 列表 | 解析失败静默跳过 |
| `get_team_registry()` | `() -> TeamRegistry` | 单例 TeamRegistry | 无 |
| `format_task_notification(n)` | `(TaskNotification) -> str` | XML 字符串 | 无 |
| `parse_task_notification(xml)` | `(str) -> TaskNotification` | 结构化通知 | 格式错误返回空字段 |

### 2.6 错误处理

| 场景 | 处理方式 |
|------|----------|
| Team 已存在 | `ValueError(f"Team '{name}' already exists")` |
| Team 不存在 | `ValueError(f"Team '{name}' does not exist")` |
| Agent 定义文件解析失败 | `logger.debug` + `continue` (静默跳过) |
| 无效 effort / permission_mode / memory / isolation | `logger.debug` 记录 + 字段设为 `None` |

### 2.7 配置项

| 配置路径 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| `CLAUDE_CODE_COORDINATOR_MODE` | 环境变量 | `""` | `"1"/"true"/"yes"` 启用协调者模式 |
| `CLAUDE_CODE_SIMPLE` | 环境变量 | `""` | `"1"/"true"/"yes"` 使用简化 Worker 工具集 |
| `~/.openharness/agents/*.md` | 文件 | 无 | 用户自定义 Agent 定义 |

### 2.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `engine/` | ← | 调用 `is_coordinator_mode()` 判断角色, 使用 `get_coordinator_tools()` 获取工具列表 |
| `tools/` (agent 工具) | ← | 使用 `AgentDefinition` 创建子 Agent |
| `swarm/` | ← | `TeamFile` 是 `TeamRegistry` 的持久化版本 |
| `config/paths.py` | ← | `get_config_dir()` 提供 Agent 定义目录路径 |

---

## 3. Tasks — 后台任务管理

### 3.1 模块概述

tasks 模块管理 Shell 和 Agent 子进程任务的生命周期, 包括创建、监控、输出收集与停止。

| 文件 | 行数 | 职责 |
|------|------|------|
| `tasks/__init__.py` | 19 | 模块导出 |
| `tasks/types.py` | 31 | TaskType, TaskStatus, TaskRecord 数据模型 |
| `tasks/manager.py` | ~279 | BackgroundTaskManager 核心逻辑 |
| `tasks/local_shell_task.py` | 18 | Shell 任务创建门面 |
| `tasks/local_agent_task.py` | 29 | Agent 任务创建门面 |
| `tasks/stop_task.py` | 12 | 任务停止门面 |

**模块总行数：~488 行**

### 3.2 核心类/接口

#### TaskType 与 TaskStatus

```python
TaskType = Literal["local_bash", "local_agent", "remote_agent", "in_process_teammate"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]
```

#### TaskRecord

```python
@dataclass
class TaskRecord:
    id: str                        # 唯一 ID (格式: b/a/r/t + uuid4[:8])
    type: TaskType                  # 任务类型
    status: TaskStatus              # 当前状态
    description: str                # 描述
    cwd: str                        # 工作目录 (绝对路径)
    output_file: Path               # 输出日志路径
    command: str | None             # Shell 命令
    prompt: str | None              # Agent 提示词
    created_at: float               # 创建时间戳
    started_at: float | None        # 启动时间戳
    ended_at: float | None          # 结束时间戳
    return_code: int | None         # 进程退出码
    metadata: dict[str, str]        # 额外元数据 (progress, status_note, restart_count, agent_mode)
```

**ID 生成规则**: 类型前缀 + UUID4 前 8 位十六进制字符

| TaskType | 前缀 | 示例 |
|----------|------|------|
| local_bash | `b` | `b3a7f1c2` |
| local_agent | `a` | `a9e4d2b1` |
| remote_agent | `r` | `r5c8a1f3` |
| in_process_teammate | `t` | `t2b6e9d4` |

#### BackgroundTaskManager

```python
class BackgroundTaskManager:
    _tasks: dict[str, TaskRecord]
    _processes: dict[str, asyncio.subprocess.Process]
    _waiters: dict[str, asyncio.Task[None]]
    _output_locks: dict[str, asyncio.Lock]
    _input_locks: dict[str, asyncio.Lock]
    _generations: dict[str, int]         # Agent 任务重启代数

    # --- 公开 API ---
    async def create_shell_task(*, command, description, cwd, task_type="local_bash") -> TaskRecord
    async def create_agent_task(*, prompt, description, cwd, model, api_key, command) -> TaskRecord
    def get_task(task_id) -> TaskRecord | None
    def list_tasks(*, status=None) -> list[TaskRecord]
    def update_task(task_id, *, description, progress, status_note) -> TaskRecord
    async def stop_task(task_id) -> TaskRecord
    async def write_to_task(task_id, data) -> None
    def read_task_output(task_id, *, max_bytes=12000) -> str

    # --- 内部方法 ---
    async def _start_process(task_id) -> asyncio.subprocess.Process
    async def _watch_process(task_id, process, generation) -> None
    async def _copy_output(task_id, process) -> None
    async def _ensure_writable_process(task) -> asyncio.subprocess.Process
    async def _restart_agent_task(task) -> asyncio.subprocess.Process
```

### 3.3 数据模型

**任务状态机**:

```
                  ┌──────────┐
                  │ pending  │ (create_agent_task 初始态, 实际几乎不驻留)
                  └────┬─────┘
                       │ _start_process
                       v
                  ┌──────────┐
            ┌─────│ running  │──────┐
            │     └────┬─────┘      │
            │          │            │ stop_task (terminate → kill)
            │   进程退出            │
            │   return_code         │
            │   == 0    != 0        v
            v          v       ┌──────────┐
      ┌───────────┐  ┌────────┐│  killed  │
      │ completed │  │ failed │└──────────┘
      └───────────┘  └────────┘

      Agent 类型任务额外路径:
      running → (进程退出/管道断开) → _restart_agent_task → running
```

### 3.4 关键算法

**Agent 任务创建流程** (`create_agent_task`):

```
1. 若 command 为 None:
   a. 获取 api_key (参数 或 ANTHROPIC_API_KEY 环境变量)
   b. 构建 "python -m openharness --api-key <key>" 命令
   c. 可选追加 --model 参数
2. 调用 create_shell_task() 创建 TaskRecord (type="local_agent")
3. 用 dataclasses.replace() 设置 prompt 字段
4. 若 task_type != "local_agent", 设置 metadata["agent_mode"]
5. 通过 write_to_task() 向 stdin 写入 prompt
```

**输出收集算法** (`_copy_output`):

```
循环:
  读取 stdout (4096 字节块)
  → 获取 _output_locks[task_id]
  → 以追加模式打开 output_file
  → 写入原始字节
  → 读取到空块时退出
```

**Agent 任务自动重启** (`_ensure_writable_process`):

```
1. 检查进程是否存活 (stdin 可写 + returncode is None)
2. 非进程可写时:
   - 若非 Agent 类型 → 抛出 ValueError
   - 若 Agent 类型 → 调用 _restart_agent_task()
3. 重启流程:
   - 等待当前 waiter 完成
   - 递增 restart_count 元数据
   - 重置状态/时间戳
   - 调用 _start_process()
```

### 3.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `spawn_shell_task` | `async (command, description, cwd) -> TaskRecord` | Shell 任务门面 |
| `spawn_local_agent_task` | `async (*, prompt, description, cwd, model, api_key, command) -> TaskRecord` | Agent 任务门面 |
| `stop_task` | `async (task_id) -> TaskRecord` | 停止任务门面 |
| `get_task_manager` | `() -> BackgroundTaskManager` | 获取单例管理器 |

### 3.6 错误处理

| 场景 | 异常 | 说明 |
|------|------|------|
| Agent 任务无 API Key | `ValueError` | 需要 `ANTHROPIC_API_KEY` 或显式 `command` |
| 任务不存在 | `ValueError(f"No task found with ID: {task_id}")` | `_require_task` 内部方法 |
| 任务无命令 | `ValueError(f"Task {task_id} does not have a command to run")` | `_start_process` 检查 |
| 非运行态停止 | `ValueError(f"Task {task_id} is not running")` | `stop_task` 检查 |
| 非输入型任务写入 | `ValueError(f"Task {task_id} does not accept input")` | `write_to_task` / `_ensure_writable_process` |
| 管道断开且重启失败 | 原始异常传播 | Agent 类型尝试重启, 失败则抛出 |

### 3.7 配置项

| 配置路径 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| `ANTHROPIC_API_KEY` | 环境变量 | 无 | Agent 任务必需 |
| `~/.openharness/data/tasks/<task_id>.log` | 文件 | 自动创建 | 输出日志 |
| `read_task_output.max_bytes` | 参数 | `12000` | 输出截断字节数 |
| `stop_task.terminate_timeout` | 硬编码 | `3` 秒 | 优雅终止超时, 超时后 SIGKILL |

### 3.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `utils/shell.py` | ← | `create_shell_subprocess()` 创建子进程 |
| `config/paths.py` | ← | `get_tasks_dir()` 提供输出目录 |
| `coordinator/` | → | 通过 `spawn_local_agent_task` 创建 Worker Agent |
| `tools/` (task_create 等) | → | 通过 `BackgroundTaskManager` API 管理任务 |
| `sandbox/` | 间接 | `create_shell_subprocess` 内部调用沙箱包装 |

---

## 4. Sandbox — 沙箱隔离

### 4.1 模块概述

sandbox 模块实现双后端沙箱隔离, 保护宿主机免受 Agent 执行的未受信任代码的影响。

| 文件 | 行数 | 职责 |
|------|------|------|
| `sandbox/__init__.py` | 33 | 模块导出 |
| `sandbox/adapter.py` | ~149 | srt 后端适配器, 可用性检测, 命令包装 |
| `sandbox/docker_backend.py` | ~228 | Docker 后端, 容器会话管理 |
| `sandbox/docker_image.py` | ~104 | Docker 镜像检查与自动构建 |
| `sandbox/path_validator.py` | ~38 | 沙箱路径边界校验 |
| `sandbox/session.py` | ~64 | Docker 会话模块级单例注册 |

**模块总行数：~616 行**

### 4.2 核心类/接口

#### SandboxAvailability

```python
@dataclass(frozen=True)
class SandboxAvailability:
    enabled: bool                  # 配置是否启用
    available: bool                # 运行时是否可用
    reason: str | None             # 不可用原因
    command: str | None            # 可用时 srt/docker 可执行文件路径

    @property
    def active(self) -> bool       # enabled AND available
```

#### SandboxUnavailableError

```python
class SandboxUnavailableError(RuntimeError):
    """沙箱不可用但配置要求使用时抛出。"""
```

#### srt 后端

```python
def build_sandbox_runtime_config(settings: Settings) -> dict[str, Any]
    # 将 Settings 转换为 srt 设置载荷:
    # {
    #   "network": {"allowedDomains": [...], "deniedDomains": [...]},
    #   "filesystem": {
    #     "allowRead": [...], "denyRead": [...],
    #     "allowWrite": [...], "denyWrite": [...]
    #   }
    # }

def get_sandbox_availability(settings=None) -> SandboxAvailability
    # 检测链: sandbox.enabled → platform → enabled_platforms → srt 可执行文件 → bwrap/sandbox-exec

def wrap_command_for_sandbox(command, *, settings=None) -> tuple[list[str], Path | None]
    # 返回: (wrapped_argv, temp_settings_path)
    # 若 backend=docker 或沙箱不可用: 返回 (原始命令, None)
    # 若 fail_if_unavailable 且不可用: 抛出 SandboxUnavailableError
```

#### Docker 后端

```python
def get_docker_availability(settings: Settings) -> SandboxAvailability
    # 检测链: sandbox.enabled → backend=docker → platform → docker CLI → docker info

class DockerSandboxSession:
    settings: Settings
    session_id: str
    cwd: Path

    @property
    def container_name(self) -> str     # "openharness-sandbox-{session_id}"
    @property
    def is_running(self) -> bool

    def _build_run_argv(self) -> list[str]  # docker run 参数构建
    async def start(self) -> None          # 创建并启动容器
    async def stop(self) -> None           # 异步停止容器 (5 秒优雅超时)
    def stop_sync(self) -> None            # 同步停止 (atexit 用, 3 秒超时)
    async def exec_command(self, argv, *, cwd, stdin, stdout, stderr, env) -> Process
```

#### 路径校验

```python
def validate_sandbox_path(path: Path, cwd: Path, extra_allowed=None) -> tuple[bool, str]
    # 主检查: path.resolve() 必须在 cwd.resolve() 内
    # 副检查: path 可在 extra_allowed 列表中任一路径内
    # 返回: (True, "") 或 (False, reason)
```

#### 会话管理

```python
def get_docker_sandbox() -> DockerSandboxSession | None  # 获取活跃会话
def is_docker_sandbox_active() -> bool                    # 会话是否运行中
async def start_docker_sandbox(settings, session_id, cwd) -> None
async def stop_docker_sandbox() -> None
```

### 4.3 数据模型

**srt 可用性检测决策树**:

```
settings.sandbox.enabled == False
  → SandboxAvailability(enabled=False, available=False, reason="sandbox is disabled")

platform not supports_sandbox_runtime
  → windows: reason="sandbox runtime is not supported on native Windows; use WSL"
  → else: reason="sandbox runtime is not supported on platform {name}"

platform not in enabled_platforms
  → reason="sandbox is disabled for platform {name} by configuration"

shutil.which("srt") == None
  → reason="sandbox runtime CLI not found; install with npm install -g @anthropic-ai/sandbox-runtime"

linux/wsl + bwrap missing
  → reason="bubblewrap (bwrap) is required for sandbox runtime on Linux/WSL"

macos + sandbox-exec missing
  → reason="sandbox-exec is required for sandbox runtime on macOS"

全部通过 → SandboxAvailability(enabled=True, available=True, command=srt_path)
```

**Docker run 参数构建**:

```
docker run -d --rm --name <container_name>
  [--network bridge|none]              # 根据 allowed_domains 选择
  [--cpus <limit>]                     # cpu_limit > 0 时
  [--memory <limit>]                   # memory_limit 非空时
  -v <cwd>:<cwd> -w <cwd>             # 项目目录绑定挂载
  [-v <extra_mount>]*                  # 额外挂载
  [-e <key>=<value>]*                  # 额外环境变量
  <image> tail -f /dev/null            # 保持容器运行
```

### 4.4 关键算法

**srt 命令包装** (`wrap_command_for_sandbox`):

```
1. 解析 Settings, 若 backend=docker → 返回原始命令
2. 获取 SandboxAvailability
3. 不可用时:
   - fail_if_unavailable → 抛出 SandboxUnavailableError
   - 否则 → 返回原始命令
4. 可用时:
   - 调用 build_sandbox_runtime_config() 生成配置
   - _write_runtime_settings() 写入临时 JSON 文件
   - 构建: [srt, "--settings", <tmp_path>, "-c", shlex.join(command)]
   - 返回 (wrapped_argv, tmp_path)
```

**Docker 镜像可用性** (`ensure_image_available`):

```
1. 检查镜像是否本地存在 (docker image inspect)
2. 存在 → 返回 True
3. 不存在 + auto_build=False → 返回 False
4. 不存在 + auto_build=True → 尝试构建默认镜像:
   a. 优先使用 Dockerfile 文件构建
   b. 回退: 通过 stdin 管道 Dockerfile 内容
   c. 默认镜像: openharness-sandbox:latest
```

### 4.5 接口规范

| 函数 | 签名 | 返回值 |
|------|------|--------|
| `get_sandbox_availability` | `(Settings?) -> SandboxAvailability` | 可用性状态 |
| `wrap_command_for_sandbox` | `(list[str], **Settings?) -> tuple[list[str], Path?]` | 包装后命令 + 临时文件路径 |
| `validate_sandbox_path` | `(Path, Path, list[str]?) -> tuple[bool, str]` | (允许, 原因) |
| `get_docker_availability` | `(Settings) -> SandboxAvailability` | Docker 可用性 |
| `start_docker_sandbox` | `async (Settings, str, Path) -> None` | 启动 Docker 会话 |
| `stop_docker_sandbox` | `async () -> None` | 停止 Docker 会话 |

### 4.6 错误处理

| 场景 | 异常 | 说明 |
|------|------|------|
| 沙箱不可用 + fail_if_unavailable | `SandboxUnavailableError` | srt/Docker 后端均适用 |
| Docker 容器启动失败 | `SandboxUnavailableError(msg)` | stderr 内容作为消息 |
| Docker 会话非运行态执行命令 | `SandboxUnavailableError("session is not running")` | exec_command 检查 |
| Docker 镜像不可用 + 禁止自动构建 | 不抛异常, 返回不可用 | `ensure_image_available` 返回 False |
| Docker daemon 未运行 | 不可用 (reason 包含详情) | `docker info` 检查失败 |

### 4.7 配置项

| 配置路径 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| `settings.sandbox.enabled` | bool | `False` | 是否启用沙箱 |
| `settings.sandbox.backend` | str | `"srt"` | 后端选择: "srt" 或 "docker" |
| `settings.sandbox.fail_if_unavailable` | bool | `False` | 不可用时是否抛出异常 |
| `settings.sandbox.enabled_platforms` | list | `[]` | 限制允许沙箱的平台 |
| `settings.sandbox.network.allowed_domains` | list | `[]` | 允许的网络域 |
| `settings.sandbox.network.denied_domains` | list | `[]` | 拒绝的网络域 |
| `settings.sandbox.filesystem.allow_read/deny_read/allow_write/deny_write` | list | `[]` | 文件系统 ACL |
| `settings.sandbox.docker.image` | str | `"openharness-sandbox:latest"` | Docker 镜像名 |
| `settings.sandbox.docker.auto_build_image` | bool | `False` | 是否自动构建镜像 |
| `settings.sandbox.docker.cpu_limit` | float | `0` | CPU 限制 |
| `settings.sandbox.docker.memory_limit` | str | `""` | 内存限制 |
| `settings.sandbox.docker.extra_mounts` | list | `[]` | 额外卷挂载 |
| `settings.sandbox.docker.extra_env` | dict | `{}` | 额外环境变量 |

### 4.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `utils/shell.py` | ← | `wrap_command_for_sandbox()` 包装命令, `get_docker_sandbox()` 路由 Docker 执行 |
| `platforms.py` | ← | `get_platform()` / `get_platform_capabilities()` 判断平台支持 |
| `config/` | ← | `load_settings()` 获取沙箱配置 |
| `tasks/manager.py` | 间接 | `create_shell_subprocess()` 内部调用沙箱逻辑 |

---

## 5. Themes — 主题配置

### 5.1 模块概述

themes 模块提供 TUI 的颜色、边框、图标和布局配置, 支持内置主题与用户自定义主题的加载和合并。

| 文件 | 行数 | 职责 |
|------|------|------|
| `themes/__init__.py` | 22 | 模块导出 |
| `themes/schema.py` | ~55 | Pydantic 主题配置模型 |
| `themes/builtin.py` | ~90 | 5 个内置主题定义 |
| `themes/loader.py` | ~56 | 加载与合并逻辑 |

**模块总行数：~223 行**

### 5.2 核心类/接口

```python
class ColorsConfig(BaseModel):
    primary: str = "#5875d4"       # 主色
    secondary: str = "#4a9eff"     # 副色
    accent: str = "#61afef"        # 强调色
    error: str = "#e06c75"        # 错误色
    muted: str = "#5c6370"         # 静音色
    background: str = "#282c34"   # 背景色
    foreground: str = "#abb2bf"   # 前景色

class BorderConfig(BaseModel):
    style: Literal["rounded", "single", "double", "none"] = "rounded"
    char: str | None = None       # 自定义边框字符

class IconConfig(BaseModel):
    spinner: str = "⠋"             # 加载动画
    tool: str = "⚙"                # 工具图标
    error: str = "✖"              # 错误图标
    success: str = "✔"            # 成功图标
    agent: str = "◆"              # Agent 图标

class LayoutConfig(BaseModel):
    compact: bool = False          # 紧凑模式
    show_tokens: bool = True       # 显示 Token 数
    show_time: bool = True         # 显示时间

class ThemeConfig(BaseModel):
    name: str                      # 主题名称 (唯一标识)
    colors: ColorsConfig = ColorsConfig()
    borders: BorderConfig = BorderConfig()
    icons: IconConfig = IconConfig()
    layout: LayoutConfig = LayoutConfig()
```

### 5.3 数据模型

**5 个内置主题**:

| 主题 | 配色风格 | 边框 | 布局 | 特点 |
|------|----------|------|------|------|
| default | One Dark 风格 | rounded | 完整 | 默认主题 |
| dark | Tokyo Night 风格 | single | 完整 | 深色主题 |
| minimal | 黑白极简 | none | compact + 隐藏 tokens/time | 最简输出 |
| cyberpunk | 绿紫霓虹 | double | 完整 | 赛博朋克风格 |
| solarized | Solarized Dark | rounded | 完整 | 经典 Solarized |

### 5.4 关键算法

**主题加载与合并**:

```
1. 自定义主题: 遍历 ~/.openharness/themes/*.json
   → json.loads + ThemeConfig.model_validate()
   → 解析失败: logger.debug + 跳过
2. list_themes(): 内置名 + 自定义名 (去重)
3. load_theme(name):
   → 先查自定义 (优先覆盖)
   → 再查内置
   → 均无: KeyError
```

### 5.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_custom_themes_dir()` | `() -> Path` | 返回 `~/.openharness/themes/` |
| `load_custom_themes()` | `() -> dict[str, ThemeConfig]` | 加载所有自定义主题 |
| `list_themes()` | `() -> list[str]` | 所有可用主题名称 |
| `load_theme(name)` | `(str) -> ThemeConfig` | 按名加载, 自定义优先 |

### 5.6 错误处理

| 场景 | 处理方式 |
|------|----------|
| 自定义主题 JSON 无效 | `logger.debug` + 跳过 |
| 主题名称不存在 | `KeyError(f"Unknown theme: {name!r}")` |

### 5.7 配置项

| 配置路径 | 类型 | 说明 |
|----------|------|------|
| `~/.openharness/themes/*.json` | JSON 文件 | 用户自定义主题 |
| `settings.ui.theme` | str | 当前主题名称 |

### 5.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `ui/` | ← | 使用 `load_theme()` 渲染 TUI 颜色/边框/图标 |
| `state/` | → | `AppState.theme` 跟踪当前主题名 |

---

## 6. Keybindings — 快捷键

### 6.1 模块概述

keybindings 模块管理 TUI 快捷键映射, 支持内置默认值与用户自定义覆盖。

| 文件 | 行数 | 职责 |
|------|------|------|
| `keybindings/__init__.py` | 15 | 模块导出 |
| `keybindings/default_bindings.py` | ~12 | 默认快捷键映射 |
| `keybindings/parser.py` | ~19 | JSON 解析 |
| `keybindings/resolver.py` | ~12 | 默认值与覆盖合并 |
| `keybindings/loader.py` | ~23 | 文件加载入口 |

**模块总行数：~81 行**

### 6.2 核心类/接口

```python
# 默认快捷键
DEFAULT_KEYBINDINGS: dict[str, str] = {
    "ctrl+l": "clear",
    "ctrl+k": "toggle_vim",
    "ctrl+v": "toggle_voice",
    "ctrl+t": "tasks",
}

# 解析
def parse_keybindings(text: str) -> dict[str, str]
    # JSON 解析, 校验 key/value 均为字符串

# 合并
def resolve_keybindings(overrides: dict[str, str] | None = None) -> dict[str, str]
    # DEFAULT_KEYBINDINGS 浅拷贝 + overrides 覆盖

# 加载
def get_keybindings_path() -> Path
    # ~/.openharness/keybindings.json
def load_keybindings() -> dict[str, str]
    # 文件存在 → parse → resolve
    # 文件不存在 → 直接 resolve
```

### 6.3 关键算法

**加载流程**:

```
get_keybindings_path() → ~/.openharness/keybindings.json
  → 存在 → read_text → parse_keybindings → resolve_keybindings(overrides)
  → 不存在 → resolve_keybindings()
```

### 6.4 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_keybindings_path` | `() -> Path` | 配置文件路径 |
| `load_keybindings` | `() -> dict[str, str]` | 最终生效的快捷键映射 |
| `parse_keybindings` | `(str) -> dict[str, str]` | 解析 JSON 文本 |
| `resolve_keybindings` | `(dict?) -> dict[str, str]` | 合并默认与自定义 |

### 6.5 错误处理

| 场景 | 异常 |
|------|------|
| JSON 非对象 | `ValueError("keybindings file must be a JSON object")` |
| key 或 value 非字符串 | `ValueError("keybindings keys and values must be strings")` |

### 6.6 配置项

| 配置路径 | 类型 | 说明 |
|----------|------|------|
| `~/.openharness/keybindings.json` | JSON 对象 | 用户自定义快捷键 |

### 6.7 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `ui/` | ← | 使用 `load_keybindings()` 处理键盘事件 |
| `vim/` | → | `ctrl+k` 触发 `toggle_vim` |
| `voice/` | → | `ctrl+v` 触发 `toggle_voice` |
| `config/paths.py` | ← | `get_config_dir()` 提供路径 |

---

## 7. Output Styles — 输出样式

### 7.1 模块概述

output_styles 模块管理 Agent 输出的格式化样式, 包括 3 个内置样式与用户自定义 `.md` 文件。

| 文件 | 行数 | 职责 |
|------|------|------|
| `output_styles/__init__.py` | 6 | 模块导出 |
| `output_styles/loader.py` | ~43 | 加载逻辑 |

**模块总行数：~49 行**

### 7.2 核心类/接口

```python
@dataclass(frozen=True)
class OutputStyle:
    name: str        # 样式名称
    content: str      # 样式内容/描述
    source: str       # "builtin" | "user"

def get_output_styles_dir() -> Path
    # ~/.openharness/output_styles/

def load_output_styles() -> list[OutputStyle]
    # 加载 3 个内置样式 + 自定义 .md 文件
```

### 7.3 数据模型

**3 个内置输出样式**:

| 样式名 | 内容 | 说明 |
|--------|------|------|
| default | "Standard rich console output." | 标准富文本输出 |
| minimal | "Very terse plain-text output." | 极简纯文本输出 |
| codex | "Codex-like compact transcript and tool output." | 类 Codex 紧凑输出 |

### 7.4 关键算法

**加载流程**:

```
1. 构造 3 个内置 OutputStyle(source="builtin")
2. 遍历 ~/.openharness/output_styles/*.md
   → 文件名(stem) = name
   → 文件内容 = content
   → source = "user"
3. 返回合并列表
```

### 7.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_output_styles_dir` | `() -> Path` | 自定义样式目录 |
| `load_output_styles` | `() -> list[OutputStyle]` | 所有可用样式 |

### 7.6 错误处理

加载过程无显式异常处理; 自定义文件读取失败会传播 IOError。

### 7.7 配置项

| 配置路径 | 类型 | 说明 |
|----------|------|------|
| `~/.openharness/output_styles/*.md` | Markdown 文件 | 用户自定义输出样式 |

### 7.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `state/` | → | `AppState.output_style` 跟踪当前样式名 |
| `engine/` | ← | 根据 output_style 调整输出格式 |
| `config/paths.py` | ← | `get_config_dir()` 提供路径 |

---

## 8. Vim — Vim 模式

### 8.1 模块概述

vim 模块提供 Vim 编辑模式的开关切换, 是 TUI 交互模式的基础组件。

| 文件 | 行数 | 职责 |
|------|------|------|
| `vim/__init__.py` | 6 | 模块导出 |
| `vim/transitions.py` | ~8 | 模式切换逻辑 |

**模块总行数：~14 行**

### 8.2 核心类/接口

```python
def toggle_vim_mode(enabled: bool) -> bool
    # 取反当前状态: return not enabled
```

### 8.3 数据模型

**Vim 模式状态机 (设计意图)**:

```
Normal ──toggle──→ Insert ──toggle──→ Normal
                          │
                     Visual ──toggle──→ Normal
```

当前实现为简单布尔切换; 完整的三态 (Normal/Insert/Visual) 状态机为未来扩展方向。

### 8.4 关键算法

无复杂算法, 纯布尔取反。

### 8.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `toggle_vim_mode` | `(bool) -> bool` | 切换 Vim 模式状态 |

### 8.6 错误处理

无异常。

### 8.7 配置项

| 配置路径 | 类型 | 说明 |
|----------|------|------|
| `AppState.vim_enabled` | bool | 当前 Vim 模式状态 |
| `keybindings["ctrl+k"]` | str | 默认绑定到 "toggle_vim" |

### 8.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `state/` | → | `AppState.vim_enabled` 存储状态 |
| `keybindings/` | → | `ctrl+k` 绑定触发 |
| `ui/` | ← | 根据 vim_enabled 切换输入模式 |

---

## 9. Voice — 语音输入

### 9.1 模块概述

voice 模块提供语音输入能力的诊断与切换, 当前所有 Provider 的 `voice_supported` 均为 `False`, STT 为占位实现。

| 文件 | 行数 | 职责 |
|------|------|------|
| `voice/__init__.py` | 8 | 模块导出 |
| `voice/voice_mode.py` | ~44 | 语音诊断与模式切换 |
| `voice/keyterms.py` | ~11 | 关键词提取 |
| `voice/stream_stt.py` | ~9 | 流式 STT 占位 |

**模块总行数：~72 行**

### 9.2 核心类/接口

```python
@dataclass(frozen=True)
class VoiceDiagnostics:
    available: bool              # 语音功能是否可用
    reason: str                  # 不可用原因或 "voice shell is available"
    recorder: str | None         # 检测到的录制工具路径

def toggle_voice_mode(enabled: bool) -> bool
    # 取反当前状态

def inspect_voice_capabilities(provider: ProviderInfo) -> VoiceDiagnostics
    # Provider 不支持 → available=False, reason=provider.voice_reason
    # 无录制工具 → available=False, reason="no supported recorder found..."
    # 均通过 → available=True, reason="voice shell is available"

def extract_keyterms(text: str) -> list[str]
    # 提取 >= 4 字符的字母数字下划线词元, 去重排序

async def transcribe_stream(_: bytes) -> str
    # 占位: 返回 "Streaming STT is not configured in this build."
```

### 9.3 数据模型

**录制工具检测优先级**:

```
shutil.which("sox") → shutil.which("ffmpeg") → shutil.which("arecord")
```

### 9.4 关键算法

**关键词提取算法** (`extract_keyterms`):

```python
# 正则: [A-Za-z0-9_]{4,}
# 1. 提取所有 >= 4 字符的词元
# 2. 转小写
# 3. 去重 (set)
# 4. 排序 (sorted)
```

### 9.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `toggle_voice_mode` | `(bool) -> bool` | 切换语音模式 |
| `inspect_voice_capabilities` | `(ProviderInfo) -> VoiceDiagnostics` | 诊断语音能力 |
| `extract_keyterms` | `(str) -> list[str]` | 提取关键词 |
| `transcribe_stream` | `async (bytes) -> str` | 流式 STT (占位) |

### 9.6 错误处理

无显式异常; 诊断失败通过 `VoiceDiagnostics.available=False` 和 `reason` 字段表达。

### 9.7 配置项

| 配置路径 | 类型 | 说明 |
|----------|------|------|
| `AppState.voice_enabled` | bool | 语音模式开关 |
| `AppState.voice_available` | bool | 语音能力可用性 |
| `AppState.voice_reason` | str | 不可用原因 |
| `ProviderInfo.voice_supported` | bool | Provider 是否支持语音 |
| `keybindings["ctrl+v"]` | str | 默认绑定到 "toggle_voice" |

### 9.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `api/provider.py` | ← | `ProviderInfo.voice_supported` / `voice_reason` |
| `state/` | → | `AppState.voice_*` 字段 |
| `keybindings/` | → | `ctrl+v` 绑定触发 |
| `ui/` | ← | 根据 voice_enabled/available 控制 UI |

---

## 10. State — 应用状态

### 10.1 模块概述

state 模块实现可观测的共享状态存储, 通过 Observer 模式驱动 TUI 重渲染。

| 文件 | 行数 | 职责 |
|------|------|------|
| `state/__init__.py` | 7 | 模块导出 |
| `state/app_state.py` | ~31 | AppState 数据模型 |
| `state/store.py` | ~41 | Observer Store |

**模块总行数：~79 行**

### 10.2 核心类/接口

```python
@dataclass
class AppState:
    """共享可变 UI/会话状态。"""
    model: str                     # 当前模型
    permission_mode: str            # 权限模式
    theme: str                      # 主题名称
    cwd: str = "."                  # 工作目录
    provider: str = "unknown"       # Provider 名称
    auth_status: str = "missing"    # 认证状态
    base_url: str = ""             # API 基础 URL
    vim_enabled: bool = False      # Vim 模式开关
    voice_enabled: bool = False    # 语音模式开关
    voice_available: bool = False   # 语音能力可用性
    voice_reason: str = ""         # 语音不可用原因
    fast_mode: bool = False        # 快速模式
    effort: str = "medium"         # 努力度
    passes: int = 1                # 通过次数
    mcp_connected: int = 0         # 已连接 MCP 服务器数
    mcp_failed: int = 0            # 连接失败的 MCP 服务器数
    bridge_sessions: int = 0       # 桥接会话数
    output_style: str = "default"  # 输出样式
    keybindings: dict[str, str]    # 快捷键映射

class AppStateStore:
    """可观测状态存储。"""
    def __init__(self, initial_state: AppState) -> None

    def get(self) -> AppState
        # 返回当前状态快照

    def set(self, **updates) -> AppState
        # 使用 dataclasses.replace() 创建新状态
        # 通知所有监听器

    def subscribe(self, listener: Callable[[AppState], None]) -> Callable[[], None]
        # 注册监听器, 返回取消订阅回调
```

### 10.3 数据模型

**AppState 17 个字段分类**:

| 类别 | 字段 |
|------|------|
| API/模型 | model, provider, base_url, auth_status |
| 权限 | permission_mode, effort, passes |
| 交互模式 | vim_enabled, voice_enabled, voice_available, voice_reason, fast_mode |
| 外部服务 | mcp_connected, mcp_failed, bridge_sessions |
| 个性化 | theme, output_style, keybindings |
| 运行时 | cwd |

### 10.4 关键算法

**Observer 通知机制**:

```python
def set(self, **updates) -> AppState:
    self._state = replace(self._state, **updates)   # 不可变更新
    for listener in list(self._listeners):            # 快照遍历, 防止迭代中修改
        listener(self._state)
    return self._state
```

**取消订阅**:

```python
def subscribe(self, listener) -> Callable[[], None]:
    self._listeners.append(listener)

    def _unsubscribe():
        if listener in self._listeners:
            self._listeners.remove(listener)
    return _unsubscribe
```

### 10.5 接口规范

| 方法 | 签名 | 说明 |
|------|------|------|
| `get` | `() -> AppState` | 返回状态快照 |
| `set` | `(**updates) -> AppState` | 更新状态并通知监听器 |
| `subscribe` | `(Callable[[AppState], None]) -> Callable[[], None]` | 注册监听器, 返回取消函数 |

### 10.6 错误处理

| 场景 | 处理方式 |
|------|----------|
| `set()` 中无效字段名 | `dataclasses.replace()` 抛出 `TypeError` |
| 监听器抛出异常 | 异常传播, 后续监听器不执行 |

### 10.7 配置项

无直接配置项; AppState 字段由各模块写入。

### 10.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `ui/` | ← | 订阅 `AppStateStore`, 状态变更时重渲染 |
| `themes/` | → | `AppState.theme` |
| `keybindings/` | → | `AppState.keybindings` |
| `output_styles/` | → | `AppState.output_style` |
| `vim/` | → | `AppState.vim_enabled` |
| `voice/` | → | `AppState.voice_enabled/available/reason` |
| `engine/` | → | `AppState.model/effort/permission_mode` |

---

## 11. Utils — 工具函数

### 11.1 模块概述

utils 模块提供跨模块复用的底层工具函数, 涵盖文件原子写入、排他锁、Shell 解析和网络安全防护。

| 文件 | 行数 | 职责 |
|------|------|------|
| `utils/__init__.py` | 1 | 空模块标记 |
| `utils/fs.py` | ~99 | 原子写入 |
| `utils/file_lock.py` | ~81 | 排他文件锁 |
| `utils/shell.py` | ~121 | Shell 命令解析与子进程创建 |
| `utils/network_guard.py` | ~128 | SSRF 防护 |

**模块总行数：~430 行**

### 11.2 核心类/接口

#### 原子写入 (fs.py)

```python
def atomic_write_bytes(path: str | PathLike, data: bytes, *, mode: int | None = None) -> None
    # 1. 创建同目录临时文件 (tempfile.mkstemp)
    # 2. 写入数据
    # 3. flush + fsync
    # 4. 应用目标 POSIX mode
    # 5. os.replace() 原子替换
    # 异常时: 删除临时文件

def atomic_write_text(path, data, *, encoding="utf-8", mode=None) -> None
    # text → bytes 编码后委托 atomic_write_bytes
```

#### 排他文件锁 (file_lock.py)

```python
class SwarmLockError(RuntimeError):                # 基础锁错误
class SwarmLockUnavailableError(SwarmLockError):  # 平台不支持

@contextmanager
def exclusive_file_lock(lock_path: Path, *, platform_name=None) -> Iterator[None]
    # POSIX: fcntl.flock(fd, LOCK_EX / LOCK_UN)
    # Windows: msvcrt.locking(fd, LK_LOCK / LK_UNLCK, 1)
    # 其它: 抛出 SwarmLockUnavailableError
```

#### Shell 解析 (shell.py)

```python
def resolve_shell_command(command, *, platform_name=None, prefer_pty=False) -> list[str]
    # Windows: bash → pwsh → cmd.exe
    # POSIX: bash → $SHELL → /bin/sh
    # prefer_pty: 尝试用 script 命令包装

async def create_shell_subprocess(command, *, cwd, settings=None, prefer_pty=False,
                                    stdin=None, stdout=None, stderr=None, env=None) -> Process
    # Docker 后端: 路由到 docker exec
    # srt 后端: wrap_command_for_sandbox
    # 清理: 异常时删除临时文件, 正常时进程退出后清理
```

#### 网络安全防护 (network_guard.py)

```python
class NetworkGuardError(ValueError):
    """HTTP 目标违反安全策略时抛出。"""

def validate_http_url(url: str) -> None
    # 检查: scheme 为 http/https, 存在 hostname, 无内嵌凭证

async def ensure_public_http_url(url: str) -> None
    # 1. validate_http_url
    # 2. DNS 解析 hostname
    # 3. 拒绝非全局 IP (is_global == False)

async def fetch_public_http_response(url, *, headers=None, params=None,
                                       timeout=15.0, max_redirects=5) -> httpx.Response
    # 逐跳验证重定向, 最多 5 次
```

### 11.3 数据模型

**Shell 解析决策矩阵**:

| 平台 | 首选 | 备选 1 | 备选 2 | 参数格式 |
|------|------|--------|--------|----------|
| Windows | bash -lc | pwsh -NoLogo -NoProfile -Command | cmd.exe /d /s /c | - |
| macOS/Linux/WSL | bash -lc | $SHELL -lc | /bin/sh -lc | prefer_pty 时用 script 包装 |

**IP 过滤规则** (`is_global` 检查):

| 范围 | 结果 | 说明 |
|------|------|------|
| 127.0.0.0/8 | 拒绝 | IPv4 环回 |
| 10.0.0.0/8 | 拒绝 | RFC 1918 A 类私有 |
| 172.16.0.0/12 | 拒绝 | RFC 1918 B 类私有 |
| 192.168.0.0/16 | 拒绝 | RFC 1918 C 类私有 |
| 0.0.0.0/8 | 拒绝 | 当前网络 |
| 255.255.255.255/32 | 拒绝 | 广播 |
| ::1/128 | 拒绝 | IPv6 环回 |
| fc00::/7 | 拒绝 | IPv6 唯一本地 |
| 公网 IP | 允许 | `is_global == True` |

### 11.4 关键算法

**原子写入算法** (temp-file + fsync + os.replace):

```
1. dst.parent.mkdir(parents=True, exist_ok=True)
2. _resolve_target_mode(dst, mode):
   - 显式 mode → 使用
   - 已有文件 → 保留 st_mode
   - 新文件 → 0o666 & ~umask
3. tempfile.mkstemp(prefix=".{name}.", suffix=".tmp", dir=parent)
4. os.fdopen(fd, "wb") → write → flush → fsync
5. _apply_mode(tmp_path, target_mode)
6. os.replace(tmp_path, dst)      # 原子操作
7. 异常时: tmp_path.unlink(missing_ok=True)
```

**SSRF 防护算法** (ensure_public_http_url):

```
1. validate_http_url: scheme + hostname + 无凭证
2. 解析端口号 (显式 or 默认 80/443)
3. _resolve_host_addresses:
   - IP 字面量 → 直接解析
   - 域名 → socket.getaddrinfo(AF_UNSPEC, SOCK_STREAM)
   - 提取 IPv4/IPv6 地址
4. 过滤: not address.is_global → 收集为 blocked
5. blocked 非空 → 抛出 NetworkGuardError
```

**重定向逐跳验证** (fetch_public_http_response):

```
for redirect_count in range(max_redirects + 1):
    await ensure_public_http_url(current_url)     # 每跳都验证
    response = await client.get(current_url)
    if not response.has_redirect_location: return response
    if redirect_count >= max_redirects: raise NetworkGuardError
    current_url = urljoin(response.url, location)  # 解析相对重定向
    current_params = None                          # 仅首次带 params
```

### 11.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `atomic_write_bytes` | `(PathLike, bytes, *, mode?) -> None` | 原子字节写入 |
| `atomic_write_text` | `(PathLike, str, *, encoding?, mode?) -> None` | 原子文本写入 |
| `exclusive_file_lock` | `(Path, *, platform_name?) -> ContextManager[None]` | 排他文件锁 |
| `resolve_shell_command` | `(str, *, platform_name?, prefer_pty?) -> list[str]` | Shell 命令解析 |
| `create_shell_subprocess` | `async (str, *, cwd, ...) -> Process` | 沙箱感知的子进程创建 |
| `validate_http_url` | `(str) -> None` | URL 基本验证 |
| `ensure_public_http_url` | `async (str) -> None` | SSRF 防护 |
| `fetch_public_http_response` | `async (str, **kw) -> Response` | 安全 HTTP 获取 |

### 11.6 错误处理

| 场景 | 异常 | 说明 |
|------|------|------|
| 原子写入失败 | 基础异常 + 临时文件清理 | `BaseException` 捕获确保清理 |
| chmod 失败 (Windows/FAT) | 静默忽略 | `_apply_mode` 中 `except OSError: pass` |
| 不支持的平台锁 | `SwarmLockUnavailableError` | 非 POSIX/Windows 平台 |
| URL 非 http/https | `NetworkGuardError` | `validate_http_url` |
| URL 含内嵌凭证 | `NetworkGuardError` | `validate_http_url` |
| 目标解析为私有 IP | `NetworkGuardError` | `ensure_public_http_url` |
| DNS 解析失败 | `NetworkGuardError` | `_resolve_host_addresses` |
| 重定向过多 (>5) | `NetworkGuardError` | `fetch_public_http_response` |
| Docker 会话未运行 + fail_if_unavailable | `SandboxUnavailableError` | `create_shell_subprocess` |

### 11.7 配置项

| 配置路径 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| `atomic_write_bytes.mode` | int | `None` | POSIX 文件模式 (0o600 等) |
| `atomic_write_text.encoding` | str | `"utf-8"` | 文本编码 |
| `fetch_public_http_response.timeout` | float | `15.0` | HTTP 超时秒数 |
| `fetch_public_http_response.max_redirects` | int | `5` | 最大重定向次数 |

### 11.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `config/` | ← | `atomic_write_text` 用于配置文件写入, `exclusive_file_lock` 保护并发读写 |
| `sandbox/` | ← | `create_shell_subprocess` 调用 `wrap_command_for_sandbox` |
| `tasks/` | ← | `create_shell_subprocess` 创建子进程 |
| `platforms.py` | ← | `get_platform()` 判断平台 |
| `tools/web_*` | ← | `fetch_public_http_response` 安全 HTTP 获取 |
| `swarm/` | ← | `exclusive_file_lock` 保护共享注册表 |

---

## 12. Platforms — 平台检测

### 12.1 模块概述

platforms 模块检测运行平台并提供能力矩阵, 驱动 Shell、Swarm、沙箱等模块的平台适配决策。

| 文件 | 行数 | 职责 |
|------|------|------|
| `platforms.py` | ~88 | 平台检测与能力查询 |

**模块总行数：~88 行**

### 12.2 核心类/接口

```python
PlatformName = Literal["macos", "linux", "windows", "wsl", "unknown"]

@dataclass(frozen=True)
class PlatformCapabilities:
    name: PlatformName
    supports_posix_shell: bool
    supports_native_windows_shell: bool
    supports_tmux: bool
    supports_swarm_mailbox: bool
    supports_sandbox_runtime: bool
    supports_docker_sandbox: bool

def detect_platform(*, system_name=None, release=None, env=None) -> PlatformName
    # Darwin → "macos"
    # Windows → "windows"
    # Linux + Microsoft/WSL_DISTRO_NAME/WSL_INTEROP → "wsl"
    # Linux → "linux"
    # 其它 → "unknown"

@lru_cache(maxsize=1)
def get_platform() -> PlatformName
    # 缓存的 detect_platform()

def get_platform_capabilities(platform_name=None) -> PlatformCapabilities
    # 查询能力矩阵
```

### 12.3 数据模型

**平台能力矩阵**:

| 能力 | macOS | Linux | WSL | Windows | unknown |
|------|-------|-------|-----|---------|---------|
| POSIX Shell | Y | Y | Y | N | N |
| Native Windows Shell | N | N | N | Y | N |
| tmux | Y | Y | Y | N | N |
| Swarm Mailbox | Y | Y | Y | N | N |
| Sandbox Runtime (srt) | Y | Y | Y | N | N |
| Docker Sandbox | Y | Y | Y | N | N |

### 12.4 关键算法

**WSL 检测逻辑**:

```python
if system == "linux":
    kernel_release = platform.release().lower()
    if ("microsoft" in kernel_release
        or env.get("WSL_DISTRO_NAME")
        or env.get("WSL_INTEROP")):
        return "wsl"
    return "linux"
```

三个独立信号任一匹配即为 WSL:
1. 内核版本字符串含 "microsoft"
2. `WSL_DISTRO_NAME` 环境变量
3. `WSL_INTEROP` 环境变量

### 12.5 接口规范

| 函数 | 签名 | 说明 |
|------|------|------|
| `detect_platform` | `(*, system_name?, release?, env?) -> PlatformName` | 平台检测 (可注入参数用于测试) |
| `get_platform` | `() -> PlatformName` | 缓存的平台检测结果 |
| `get_platform_capabilities` | `(PlatformName?) -> PlatformCapabilities` | 能力矩阵查询 |

### 12.6 错误处理

无显式异常; 未知平台返回 `"unknown"` 与全 `False` 能力矩阵。

### 12.7 配置项

无配置项; 完全依赖运行时检测。

### 12.8 与其它模块的交互

| 交互方 | 方向 | 内容 |
|--------|------|------|
| `sandbox/adapter.py` | ← | `get_platform()` / `get_platform_capabilities()` 判断 srt 可用性 |
| `sandbox/docker_backend.py` | ← | `get_platform_capabilities()` 判断 Docker 可用性 |
| `utils/file_lock.py` | ← | `get_platform()` 选择 POSIX/Windows 锁实现 |
| `utils/shell.py` | ← | `get_platform()` 选择 Shell 命令 |

---

## 13. 安全机制汇总

辅助模块群实现了以下多层安全机制:

| 层级 | 机制 | 模块 | 说明 |
|------|------|------|------|
| 1 | SSRF 防护 | `utils/network_guard.py` | DNS 解析 + 全局 IP 检查, 拒绝私有地址段 |
| 2 | 沙箱路径校验 | `sandbox/path_validator.py` | 文件操作必须在 cwd 或 extra_allowed 内 |
| 3 | 原子写入 | `utils/fs.py` | temp+fsync+os.replace, 防崩溃导致文件截断 |
| 4 | 排他文件锁 | `utils/file_lock.py` | POSIX fcntl / Windows msvcrt, 防并发写冲突 |
| 5 | 凭证模式 600 | `utils/fs.py` | `atomic_write_bytes(path, data, mode=0o600)` |
| 6 | Keyring 集成 | `auth/storage.py` | 凭证存储优先使用系统密钥链 |
| 7 | XOR 混淆 | `auth/storage.py` | Keyring 不可用时的轻量凭证保护 |
| 8 | 9 级权限链 | `permissions/checker.py` | 工具执行的多级决策判定 |
| 9 | Worker→Leader 权限同步 | `permissions/` | Worker Agent 继承 Leader 权限上下文 |
| 10 | Git Worktree 隔离 | `coordinator/` | Agent isolation=worktree 时的文件系统隔离 |
| 11 | 内存 Slug 路径保护 | `memory/` | 防止路径遍历攻击内存文件 |
| 12 | URL 内嵌凭证拒绝 | `utils/network_guard.py` | `http://user:pass@host` 格式直接拒绝 |
| 13 | 重定向逐跳验证 | `utils/network_guard.py` | 每次重定向均重新执行 SSRF 检查 |
| 14 | Docker 网络隔离 | `sandbox/docker_backend.py` | `--network none/bridge` 控制容器网络 |
| 15 | Docker 资源限制 | `sandbox/docker_backend.py` | `--cpus` + `--memory` 限制 |
| 16 | srt 网络域 ACL | `sandbox/adapter.py` | allowedDomains / deniedDomains |
| 17 | srt 文件系统 ACL | `sandbox/adapter.py` | allowRead/denyRead/allowWrite/denyWrite |
| 18 | atexit 清理 | `sandbox/session.py` | 进程异常退出时停止 Docker 容器 |