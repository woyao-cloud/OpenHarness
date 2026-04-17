# Swarm 与 Services 模块详细设计

> 文档版本：1.0 | 最后更新：2026-04-17

---

## 1. 模块概述

OpenHarness 的 **swarm** 模块与 **services** 模块共同构成了多 Agent 协作的核心基础设施。swarm 模块负责 Agent 的身份识别、消息传递、后端调度、生命周期管理及权限同步；services 模块负责对话压缩、会话持久化、Token 估算与定时任务调度。

### 1.1 Swarm 模块

swarm 模块实现了一个基于文件系统的去中心化 Agent 协作架构，支持 4 种执行后端：

| 后端 | 优先级 | 特性 | 可用性 |
|------|--------|------|--------|
| `tmux` | 最高 | 可视化窗格、边框颜色、隐藏/显示窗格 | 需在 tmux session 内或 tmux 二进制可用 |
| `iterm2` | 次高 | macOS 原生标签页、it2 CLI 控制 | 仅 macOS、需安装 it2 |
| `subprocess` | 默认回退 | 始终可用、独立子进程 | 全平台 |
| `in_process` | 特殊 | 最快延迟、asyncio Task 共进程 | 需平台支持 swarm_mailbox |

**自动检测策略**：若进程在 tmux session 内（`$TMUX` 已设置）且 tmux 二进制可用，则选择 tmux；否则回退至 subprocess。当用户通过配置显式指定 `in_process` 模式或因 spawn 失败触发降级时，切换至 in_process。

swarm 模块各文件职责：

| 文件 | 行数 | 职责 |
|------|------|------|
| `swarm/types.py` | ~393 | 类型定义、Protocol 接口、数据模型 |
| `swarm/mailbox.py` | ~523 | 基于文件的异步消息队列 |
| `swarm/registry.py` | ~411 | 后端注册与自动检测 |
| `swarm/team_lifecycle.py` | ~911 | 团队生命周期管理（CRUD + 清理） |
| `swarm/permission_sync.py` | ~1169 | 双通道权限同步协议 |
| `swarm/in_process.py` | ~694 | 进程内执行后端（ContextVar 隔离） |

### 1.2 Services 模块

services 模块提供横切关注点的基础服务：

| 文件 | 行数 | 职责 |
|------|------|------|
| `services/compact/__init__.py` | ~1581 | 对话压缩（4 级策略） |
| `services/session_storage.py` | ~230 | 会话快照持久化 |
| `services/session_backend.py` | ~98 | 会话存储后端抽象 |
| `services/token_estimation.py` | ~16 | Token 估算工具 |
| `services/cron.py` | ~118 | Cron 任务注册表 |
| `services/cron_scheduler.py` | ~359 | Cron 调度守护进程 |

---

## 2. 核心类/接口

### 2.1 Swarm 模块核心类

#### 2.1.1 `PaneBackend` Protocol (`swarm/types.py`)

终端窗格管理后端的协议接口，定义了 tmux/iTerm2 必须实现的操作集：

```python
@runtime_checkable
class PaneBackend(Protocol):
    type: BackendType                              # 后端类型标识
    display_name: str                               # 可读名称
    supports_hide_show: bool                        # 是否支持窗格隐藏/显示

    async def is_available() -> bool                # 系统可用性检查
    async def is_running_inside() -> bool           # 是否在后端原生环境内
    async def create_teammate_pane_in_swarm_view(name, color) -> CreatePaneResult
    async def send_command_to_pane(pane_id, command, *, use_external_session) -> None
    async def set_pane_border_color(pane_id, color, *, use_external_session) -> None
    async def set_pane_title(pane_id, name, color, *, use_external_session) -> None
    async def enable_pane_border_status(window_target, *, use_external_session) -> None
    async def rebalance_panes(window_target, has_leader) -> None
    async def kill_pane(pane_id, *, use_external_session) -> bool
    async def hide_pane(pane_id, *, use_external_session) -> bool
    async def show_pane(pane_id, target_window_or_pane, *, use_external_session) -> bool
    def list_panes() -> list[PaneId]
```

关键设计要点：
- `use_external_session` 参数仅 tmux 需要，用于在非原生 tmux 环境下通过外部 socket 发送命令。
- `CreatePaneResult` 包含 `pane_id` 和 `is_first_teammate` 标记，后者影响窗格布局策略（首个队友使用 split 而非 new-window）。
- `hide_pane` 通过 `break-pane` 将窗格移至隐藏窗口；`show_pane` 通过 `join-pane` 将窗格移回主窗口。

#### 2.1.2 `TeammateExecutor` Protocol (`swarm/types.py`)

Agent 执行后端的统一协议，抽象了 spawn/消息/终止操作：

```python
@runtime_checkable
class TeammateExecutor(Protocol):
    type: BackendType
    def is_available(self) -> bool
    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult
    async def send_message(self, agent_id: str, message: TeammateMessage) -> None
    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool
```

所有 4 种后端（SubprocessBackend、InProcessBackend、TmuxBackend、ITerm2Backend）均需实现此协议。

#### 2.1.3 `BackendRegistry` (`swarm/registry.py`)

后端注册中心，负责管理可用后端实例及自动检测最佳后端：

**检测优先级管道**：
1. 若 `in_process_fallback_active` 标记已设置，返回 `in_process`（spawn 失败后的降级锁死）。
2. 若在 tmux session 内（`$TMUX` 已设置且 tmux 二进制可用），返回 `tmux`。
3. 否则返回 `subprocess`（始终可用的安全回退）。

**面板后端检测**（`detect_pane_backend`）实现更细粒度的 6 级策略：
1. 在 tmux 内 → 使用 tmux（原生）
2. 在 iTerm2 内且有 it2 CLI → 使用 iterm2（原生）
3. 在 iTerm2 内但无 it2、tmux 可用 → 使用 tmux（回退，标记 `needs_setup=True`）
4. 在 iTerm2 内且无 it2、无 tmux → 抛出 RuntimeError（安装指引）
5. 不在 tmux/iTerm2 内、tmux 二进制可用 → 使用 tmux（外部 session 模式）
6. 以上均不满足 → 抛出 RuntimeError（平台特定的 tmux 安装指引）

#### 2.1.4 `TeammateMailbox` (`swarm/mailbox.py`)

基于文件的异步消息队列，每个 Agent 拥有独立的收件箱目录：

```python
class TeammateMailbox:
    async def write(self, msg: MailboxMessage) -> None       # 原子写入
    async def read_all(self, unread_only=True) -> list[...]  # 读取消息
    async def mark_read(self, message_id: str) -> None       # 标记已读
    async def clear(self) -> None                             # 清空收件箱
```

#### 2.1.5 `TeamLifecycleManager` (`swarm/team_lifecycle.py`)

团队生命周期管理器，提供团队和成员的 CRUD 操作：

```python
class TeamLifecycleManager:
    def create_team(self, name, description="") -> TeamFile
    def delete_team(self, name) -> None
    def get_team(self, name) -> TeamFile | None
    def list_teams(self) -> list[TeamFile]
    def add_member(self, team_name, member) -> TeamFile
    def remove_member(self, team_name, agent_id) -> TeamFile
    def set_member_mode(self, team_name, member_name, mode) -> bool
    async def set_member_active(self, team_name, member_name, is_active) -> None
```

该类无状态：每个方法直接读写磁盘，安全多实例使用。

#### 2.1.6 `InProcessBackend` (`swarm/in_process.py`)

进程内执行后端，将 Agent 作为 asyncio Task 运行在当前进程内：

```python
class InProcessBackend:
    type: BackendType = "in_process"
    async def spawn(self, config) -> SpawnResult
    async def send_message(self, agent_id, message) -> None
    async def shutdown(self, agent_id, *, force=False, timeout=10.0) -> bool
    async def shutdown_all(self, *, force=False, timeout=10.0) -> None
    def is_active(self, agent_id) -> bool
    def active_agents(self) -> list[str]
    def get_teammate_status(self, agent_id) -> dict | None
    def list_teammates(self) -> list[tuple[str, bool, float]]
```

#### 2.1.7 `TeammateAbortController` (`swarm/in_process.py`)

双信号中止控制器，提供优雅取消和强制终止两种语义：

```python
class TeammateAbortController:
    cancel_event: asyncio.Event    # 优雅取消（完成当前工具调用后退出）
    force_cancel: asyncio.Event    # 强制终止（立即取消 asyncio Task）
    def request_cancel(self, reason, *, force=False) -> None
    @property
    def is_cancelled(self) -> bool
    @property
    def reason(self) -> str | None
```

当 `force=True` 时，同时设置 `force_cancel` 和 `cancel_event`（确保两种检查都能触发）。

#### 2.1.8 `TeammateContext` (`swarm/in_process.py`)

每个 Agent 的隔离上下文，通过 ContextVar 实现 Task 级别隔离：

```python
@dataclass
class TeammateContext:
    agent_id: str
    agent_name: str
    team_name: str
    parent_session_id: str | None
    color: str | None
    plan_mode_required: bool
    abort_controller: TeammateAbortController
    message_queue: asyncio.Queue[TeammateMessage]
    status: TeammateStatus           # "starting"|"running"|"idle"|"stopping"|"stopped"
    started_at: float
    tool_use_count: int
    total_tokens: int
```

访问方式：`get_teammate_context()` / `set_teammate_context(ctx)`，基于 `_teammate_context_var: ContextVar` 实现。

### 2.2 Services 模块核心类

#### 2.2.1 压缩系统核心函数 (`services/compact/__init__.py`)

| 函数 | 说明 |
|------|------|
| `microcompact_messages()` | 无 LLM 调用，替换旧工具结果为占位符 |
| `try_context_collapse()` | 确定性截断长 TextBlock（head 900 + tail 500） |
| `try_session_memory_compaction()` | 确定性结构化摘要（48 行 / 4000 字符），无 LLM |
| `compact_conversation()` | 完整压缩：microcompact → LLM 生成摘要 |
| `auto_compact_if_needed()` | 每轮检查入口，依次尝试 4 级策略 |
| `should_autocompact()` | 判断是否触发自动压缩 |

#### 2.2.2 `AutoCompactState` (`services/compact/__init__.py`)

自动压缩的跨轮次状态：

```python
@dataclass
class AutoCompactState:
    compacted: bool = False
    turn_counter: int = 0
    turn_id: str = ""
    consecutive_failures: int = 0    # 连续失败 3 次后停止自动压缩
```

#### 2.2.3 `SessionBackend` Protocol (`services/session_backend.py`)

会话持久化后端的协议接口：

```python
class SessionBackend(Protocol):
    def get_session_dir(self, cwd) -> Path
    def save_snapshot(self, *, cwd, model, system_prompt, messages, usage, ...) -> Path
    def load_latest(self, cwd) -> dict | None
    def list_snapshots(self, cwd, limit=20) -> list[dict]
    def load_by_id(self, cwd, session_id) -> dict | None
    def export_markdown(self, *, cwd, messages) -> Path
```

默认实现为 `OpenHarnessSessionBackend`，委托给 `session_storage` 模块。

#### 2.2.4 Cron 调度器 (`services/cron_scheduler.py`)

后台守护进程，每 30 秒检查一次待执行的 Cron 任务：

```python
async def run_scheduler_loop(*, once=False) -> None
async def execute_job(job) -> dict[str, Any]
def start_daemon() -> int               # Fork 守护进程
def stop_scheduler() -> bool            # SIGTERM → SIGKILL
def is_scheduler_running() -> bool
def scheduler_status() -> dict[str, Any]
```

---

## 3. 数据模型

### 3.1 Swarm 数据模型

#### `TeammateIdentity`

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_id` | `str` | 唯一标识符，格式 `name@team` |
| `name` | `str` | Agent 名称（如 `researcher`） |
| `team` | `str` | 所属团队名 |
| `color` | `str \| None` | UI 区分颜色 |
| `parent_session_id` | `str \| None` | 父会话 ID，用于上下文关联 |

#### `TeammateSpawnConfig`

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 人类可读名称 |
| `team` | `str` | 团队名 |
| `prompt` | `str` | 初始提示/任务 |
| `cwd` | `str` | 工作目录 |
| `parent_session_id` | `str` | 父会话 ID |
| `model` | `str \| None` | 模型覆盖 |
| `system_prompt` | `str \| None` | 系统提示词 |
| `system_prompt_mode` | `"default"\|"replace"\|"append" \| None` | 系统提示词应用方式 |
| `color` | `str \| None` | UI 颜色 |
| `color_override` | `str \| None` | 显式颜色覆盖（优先级高于 color） |
| `permissions` | `list[str]` | 工具权限列表 |
| `plan_mode_required` | `bool` | 是否必须进入 plan mode |
| `allow_permission_prompts` | `bool` | 为 False 时未列出工具自动拒绝 |
| `worktree_path` | `str \| None` | Git 工作树路径 |
| `session_id` | `str \| None` | 显式会话 ID |
| `subscriptions` | `list[str]` | 事件订阅主题 |

#### `SpawnResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `str` | 任务管理器中的 ID |
| `agent_id` | `str` | 格式 `name@team` |
| `backend_type` | `BackendType` | 使用的后端类型 |
| `success` | `bool` | 是否成功（默认 True） |
| `error` | `str \| None` | 错误信息 |
| `pane_id` | `PaneId \| None` | 窗格 ID（仅 tmux/iTerm2） |

#### `MailboxMessage`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | UUID |
| `type` | `MessageType` | 消息类型（见 3.1.5） |
| `sender` | `str` | 发送者标识 |
| `recipient` | `str` | 接收者标识 |
| `payload` | `dict[str, Any]` | 消息体 |
| `timestamp` | `float` | Unix 时间戳 |
| `read` | `bool` | 是否已读 |

#### `MessageType` 字面量类型

```python
MessageType = Literal[
    "user_message",
    "permission_request",
    "permission_response",
    "sandbox_permission_request",
    "sandbox_permission_response",
    "shutdown",
    "idle_notification",
]
```

#### `SwarmPermissionRequest`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 格式 `perm-{timestamp_ms}-{random7}` |
| `worker_id` | `str` | 请求者 Agent ID |
| `worker_name` | `str` | 请求者 Agent 名称 |
| `team_name` | `str` | 团队名 |
| `tool_name` | `str` | 需要权限的工具名 |
| `tool_use_id` | `str` | 原始工具调用 ID |
| `description` | `str` | 操作描述 |
| `input` | `dict[str, Any]` | 工具输入参数 |
| `permission_suggestions` | `list[Any]` | 权限规则建议 |
| `worker_color` | `str \| None` | 请求者颜色 |
| `status` | `"pending"\|"approved"\|"rejected"` | 状态 |
| `resolved_by` | `"worker"\|"leader" \| None` | 解析者 |
| `resolved_at` | `float \| None` | 解析时间戳 |
| `feedback` | `str \| None` | 拒绝原因或注释 |
| `updated_input` | `dict \| None` | 解析者修改后的输入 |
| `permission_updates` | `list \| None` | "始终允许"规则 |
| `created_at` | `float` | 创建时间戳 |

#### `TeamMember`

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent_id` | `str` | Agent 标识 |
| `name` | `str` | 名称 |
| `backend_type` | `BackendType` | 后端类型 |
| `joined_at` | `float` | 加入时间戳 |
| `agent_type` | `str \| None` | 角色（如 researcher） |
| `model` | `str \| None` | 使用的模型 |
| `prompt` | `str \| None` | 初始提示 |
| `color` | `str \| None` | 显示颜色 |
| `plan_mode_required` | `bool` | 是否需要 plan mode |
| `session_id` | `str \| None` | 会话 UUID |
| `subscriptions` | `list[str]` | 事件订阅 |
| `is_active` | `bool` | 是否活跃 |
| `mode` | `str \| None` | 权限模式 |
| `tmux_pane_id` | `str` | tmux/iTerm2 窗格 ID |
| `cwd` | `str` | 工作目录 |
| `worktree_path` | `str \| None` | Git 工作树路径 |
| `permissions` | `list[str]` | 权限列表 |
| `status` | `"active"\|"idle"\|"stopped"` | 粗粒度状态 |

#### `TeamFile`

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 团队名 |
| `created_at` | `float` | 创建时间戳 |
| `description` | `str` | 描述 |
| `lead_agent_id` | `str` | 领导者 Agent ID |
| `lead_session_id` | `str \| None` | 领导者会话 UUID |
| `hidden_pane_ids` | `list[str]` | 隐藏的窗格 ID 列表 |
| `members` | `dict[str, TeamMember]` | agent_id → TeamMember |
| `team_allowed_paths` | `list[AllowedPath]` | 无需权限的共享路径 |
| `allowed_paths` | `list[str]` | 旧版路径列表 |
| `metadata` | `dict[str, Any]` | 扩展元数据 |

#### `AllowedPath`

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | `str` | 绝对路径 |
| `tool_name` | `str` | 适用的工具名 |
| `added_by` | `str` | 添加者 Agent 名 |
| `added_at` | `float` | 添加时间戳 |

### 3.2 Services 数据模型

#### `CompactAttachment`

| 字段 | 类型 | 说明 |
|------|------|------|
| `kind` | `str` | 附件类型标识 |
| `title` | `str` | 可读标题 |
| `body` | `str` | 正文内容 |
| `metadata` | `dict[str, Any]` | 扩展元数据 |

内置附件类型（kind）：

| kind | 工厂函数 | 说明 |
|------|----------|------|
| `recent_attachments` | `_create_recent_attachments_attachment_if_needed` | 本地附件路径 |
| `recent_files` | `create_recent_files_attachment_if_needed` | 最近读取的文件 |
| `task_focus` | `create_task_focus_attachment_if_needed` | 当前工作焦点 |
| `recent_verified_work` | `create_recent_verified_work_attachment_if_needed` | 已验证的工作 |
| `plan` | `create_plan_attachment_if_needed` | Plan mode 上下文 |
| `invoked_skills` | `create_invoked_skills_attachment_if_needed` | 已调用的技能 |
| `async_agents` | `create_async_agent_attachment_if_needed` | 异步 Agent 状态 |
| `recent_work_log` | `create_work_log_attachment_if_needed` | 工作日志 |
| `hook_results` | `_create_hook_attachments` | Hook 输出笔记 |

#### `CompactionResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `trigger` | `CompactTrigger` | 触发方式：auto/manual/reactive |
| `compact_kind` | `CompactionKind` | 压缩类型：full/session_memory |
| `boundary_marker` | `ConversationMessage` | 压缩边界标记消息 |
| `summary_messages` | `list[ConversationMessage]` | 摘要消息 |
| `messages_to_keep` | `list[ConversationMessage]` | 保留的近期消息 |
| `attachments` | `list[CompactAttachment]` | 结构化附件 |
| `hook_results` | `list[CompactAttachment]` | Hook 输出附件 |
| `compact_metadata` | `dict[str, Any]` | 压缩元数据 |

#### `AutoCompactState`

| 字段 | 类型 | 说明 |
|------|------|------|
| `compacted` | `bool` | 是否已执行过压缩 |
| `turn_counter` | `int` | 轮次计数器 |
| `turn_id` | `str` | 当前轮次 ID |
| `consecutive_failures` | `int` | 连续失败次数 |

---

## 4. 关键算法

### 4.1 后端自动检测算法 (`swarm/registry.py`)

```
BackendRegistry.detect_backend():
  if cached_detection exists:
    return cached
  if in_process_fallback_active:
    return "in_process"
  if $TMUX is set AND "tmux" binary on PATH:
    return "tmux"
  else:
    return "subprocess"

BackendRegistry.detect_pane_backend():
  if in_tmux:         return BackendDetectionResult("tmux", is_native=True)
  if in_iterm2:
    if it2 available: return BackendDetectionResult("iterm2", is_native=True)
    if tmux binary:   return BackendDetectionResult("tmux", is_native=False, needs_setup=True)
    raise RuntimeError("iTerm2 需要 it2 CLI")
  if tmux binary:     return BackendDetectionResult("tmux", is_native=False)
  raise RuntimeError(平台特定安装指引)
```

### 4.2 邮箱原子写入算法 (`swarm/mailbox.py`)

```
TeammateMailbox.write(msg):
  1. 构造文件名: {timestamp:.6f}_{msg.id}.json
  2. 构造路径: inbox/final_path, inbox/final_path.tmp, inbox/.write_lock
  3. 将 msg 序列化为 JSON
  4. 在线程池中执行:
     a. 获取 exclusive_file_lock(.write_lock)
     b. 写入 .tmp 文件
     c. os.replace(.tmp, final_path)   # 原子操作
     d. 释放锁
```

`os.replace` 在 POSIX 和 Windows 上均为原子操作，保证读者不会看到部分写入。

### 4.3 权限同步双通道算法 (`swarm/permission_sync.py`)

**文件通道**：
```
Worker:
  1. create_permission_request() → 构造 SwarmPermissionRequest
  2. write_permission_request()  → pending/{id}.json（带锁原子写入）

Leader:
  3. read_pending_permissions()  → 扫描 pending/ 目录
  4. resolve_permission()        → 写入 resolved/{id}.json，删除 pending/{id}.json

Worker:
  5. poll_for_response(id)       → 检查 resolved/{id}.json
  6. delete_resolved_permission() → 删除已处理的 resolved 文件
```

**邮箱通道**：
```
Worker:
  1. create_permission_request_message() → 构造 permission_request 消息
  2. send_permission_request_via_mailbox() → 写入 leader 邮箱

Leader:
  3. 读取邮箱中 permission_request 消息
  4. handle_permission_request() → 使用 PermissionChecker 评估
  5. create_permission_response_message() → 构造 permission_response 消息
  6. send_permission_response_via_mailbox() → 写入 worker 邮箱

Worker:
  7. poll_permission_response() → 轮询自己的邮箱（0.5s 间隔，最长 60s）
```

**只读工具自动批准**：当 `tool_name` 在 `_READ_ONLY_TOOLS` 集合中时，`handle_permission_request()` 直接返回 `allowed=True`，无需咨询 PermissionChecker。

只读工具白名单：
```python
_READ_ONLY_TOOLS = frozenset({
    "read_file", "glob", "grep", "web_fetch", "web_search",
    "task_get", "task_list", "task_output", "cron_list",
})
```

### 4.4 进程内 Agent 执行循环算法 (`swarm/in_process.py`)

```
start_in_process_teammate(config, agent_id, abort_controller):
  1. 构造 TeammateContext，绑定到 ContextVar
  2. 创建 TeammateMailbox
  3. status = "running"
  4. if query_context 存在:
       _run_query_loop(query_context, config, ctx, mailbox)
     else:
       stub 运行（每 0.1s 检查取消信号，最多 10 轮）
  5. finally:
       status = "stopped"
       发送 idle_notification 到 leader 邮箱

_run_query_loop():
  for event, usage in run_query(query_context, messages):
    - 累加 total_tokens, tool_use_count
    - 检查 abort_controller.is_cancelled
    - _drain_mailbox() → 处理 shutdown 和 user_message
    - 清空 message_queue → 注入新 user turn

_drain_mailbox():
  for msg in mailbox.read_all(unread_only=True):
    if msg.type == "shutdown" → request_cancel(), return True
    if msg.type == "user_message" → 推入 ctx.message_queue
```

### 4.5 4 级压缩策略算法 (`services/compact/__init__.py`)

`auto_compact_if_needed()` 的执行流程：

```
auto_compact_if_needed():
  if not force and not should_autocompact():
    return (messages, False)

  ┌─ Level 1: Microcompact ─────────────────────────────────────┐
  │ messages, freed = microcompact_messages(messages)            │
  │ 替换旧工具结果为 "[Old tool result content cleared]"        │
  │ if freed > 0 and not should_autocompact():                  │
  │   return (messages, True)  # microcompact 足够              │
  └──────────────────────────────────────────────────────────────┘

  ┌─ Level 2: Context Collapse ────────────────────────────────┐
  │ collapsed = try_context_collapse(messages, preserve_recent) │
  │ 截断过长 TextBlock: head 900 chars + tail 500 chars        │
  │ if collapsed and not should_autocompact():                  │
  │   return (collapsed, True)  # context collapse 足够          │
  └──────────────────────────────────────────────────────────────┘

  ┌─ Level 3: Session Memory ──────────────────────────────────┐
  │ result = try_session_memory_compaction(messages)             │
  │ 确定性结构化摘要：每条消息压缩为 "role: text[:160]"         │
  │ 最多 48 行 / 4000 字符，无 LLM 调用                        │
  │ if result:                                                  │
  │   return (build_post_compact_messages(result), True)        │
  └──────────────────────────────────────────────────────────────┘

  ┌─ Level 4: Full Compact ───────────────────────────────────┐
  │ result = compact_conversation(messages, ...)                 │
  │ 1. 先执行 microcompact（减少 token）                        │
  │ 2. 分割为 older（待摘要）+ newer（保留）                    │
  │ 3. 调用 LLM 生成结构化摘要（<analysis> + <summary>）       │
  │ 4. 若 prompt 过长：truncate_head_for_ptl_retry（删 1/5 轮次）│
  │ 5. 替换 older 为摘要消息                                    │
  │ 6. 附件：_build_compact_attachments()                       │
  │ 7. Hook：PRE_COMPACT / POST_COMPACT                         │
  │ return (build_post_compact_messages(result), True)          │
  └──────────────────────────────────────────────────────────────┘

  except Exception:
    consecutive_failures += 1
    if consecutive_failures >= 3:  # 停止自动压缩
      以后不再触发 should_autocompact()
    return (messages, False)
```

**Microcompact 详情**：
- 扫描 `assistant` 消息中属于 `COMPACTABLE_TOOLS` 的工具调用 ID。
- `COMPACTABLE_TOOLS` = {`read_file`, `bash`, `grep`, `glob`, `web_search`, `web_fetch`, `edit_file`, `write_file`}
- 保留最近 `keep_recent`（默认 5）个工具结果，其余替换为 `"[Old tool result content cleared]"`。
- 返回 `(messages, tokens_saved)`。

**Context Collapse 详情**：
- 仅截断 `TextBlock`，不影响 `ToolResultBlock`、`ToolUseBlock`。
- 截断格式：`{head}\n...[collapsed N chars]...\n{tail}`
- 仅当截断后的 token 数确实减少时才返回结果。

**Session Memory 详情**：
- 保留最近 `SESSION_MEMORY_KEEP_RECENT`（默认 12）条消息。
- 旧消息逐条压缩为单行：`"role: text[:160]"` 或 `"role: tool calls -> name1, name2"`。
- 受 `SESSION_MEMORY_MAX_LINES`（48）和 `SESSION_MEMORY_MAX_CHARS`（4000）双约束。
- 到达限制时追加 `"... earlier context condensed ..."`。

**Full Compact 详情**：
- 压缩提示词要求 LLM 输出 `<analysis>` + `<summary>` 两个 XML 块。
- `format_compact_summary()` 提取 `<summary>` 内容，丢弃 `<analysis>` 草稿。
- PTL（Prompt Too Long）重试：最多 3 次，每次删除 1/5 的最旧 prompt round。
- 流式重试：最多 `MAX_COMPACT_STREAMING_RETRIES`（2）次。
- 超时：`COMPACT_TIMEOUT_SECONDS`（25s）。
- 最大输出 token：`MAX_OUTPUT_TOKENS_FOR_SUMMARY`（20000）。

### 4.6 会话快照存储算法 (`services/session_storage.py`)

```
save_session_snapshot():
  1. 计算项目目录哈希: sha1(cwd)[:12]
  2. 构造路径: ~/.openharness/sessions/{dirname}-{hash}/
  3. 消息消毒: sanitize_conversation_messages()
  4. 提取摘要: 首条 user 消息的前 80 字符
  5. 构造 payload: session_id, model, messages, usage, tool_metadata...
  6. 原子写入:
     a. latest.json（始终指向最新快照）
     b. session-{sid}.json（按 ID 命名的持久快照）
```

### 4.7 Cron 调度算法 (`services/cron_scheduler.py`)

```
run_scheduler_loop():
  1. 写入 PID 文件
  2. 注册 SIGTERM/SIGINT 处理器
  3. loop:
     a. 加载 cron_jobs 列表
     b. _jobs_due(): 筛选 enabled && next_run <= now 的任务
     c. asyncio.gather() 并发执行到期任务
     d. execute_job():
        - create_shell_subprocess(command, cwd)
        - wait_for(communicate(), timeout=300s)
        - 记录 stdout（末尾 2000 字符）、stderr、returncode
        - append_history() → cron_history.jsonl
        - mark_job_run() → 更新 last_run、next_run
     e. wait_for(shutdown_event, timeout=30s)
  4. finally: 删除 PID 文件
```

### 4.8 团队清理算法 (`swarm/team_lifecycle.py`)

```
cleanup_session_teams():
  1. 遍历本次会话创建的所有团队
  2. 并发执行 _kill_orphaned_teammate_panes():
     - 读取 TeamFile 获取 pane 成员
     - 通过 BackendRegistry 获取对应 executor
     - 调用 executor.kill_pane()
  3. 并发执行 cleanup_team_directories():
     - 销毁成员的 git worktree（git worktree remove --force，失败则 shutil.rmtree）
     - 删除整个团队目录（shutil.rmtree）
```

---

## 5. 接口规范

### 5.1 Swarm 模块公开接口

#### `swarm/types.py`

| 导出 | 类型 | 说明 |
|------|------|------|
| `BackendType` | `Literal` | `"subprocess"\|"in_process"\|"tmux"\|"iterm2"` |
| `PaneBackendType` | `Literal` | `"tmux"\|"iterm2"` |
| `PaneId` | `str` | 窗格不透明标识符 |
| `PaneBackend` | `Protocol` | 窗格管理后端协议 |
| `CreatePaneResult` | `@dataclass` | 创建窗格结果 |
| `BackendDetectionResult` | `@dataclass` | 后端检测结果 |
| `TeammateIdentity` | `@dataclass` | Agent 身份信息 |
| `TeammateSpawnConfig` | `@dataclass` | Spawn 配置 |
| `SpawnResult` | `@dataclass` | Spawn 结果 |
| `TeammateMessage` | `@dataclass` | Agent 间消息 |
| `TeammateExecutor` | `Protocol` | 执行后端协议 |
| `is_pane_backend()` | 函数 | 判断是否为面板后端 |

#### `swarm/mailbox.py`

| 导出 | 说明 |
|------|------|
| `MessageType` | 消息类型字面量 |
| `MailboxMessage` | 消息数据类 |
| `TeammateMailbox` | 文件邮箱类 |
| `get_team_dir(team_name)` | 获取团队目录 |
| `get_agent_mailbox_dir(team_name, agent_id)` | 获取 Agent 收件箱目录 |
| `create_user_message(sender, recipient, content)` | 创建用户消息 |
| `create_shutdown_request(sender, recipient)` | 创建关闭请求 |
| `create_idle_notification(sender, recipient, summary)` | 创建空闲通知 |
| `create_permission_request_message(sender, recipient, request_data)` | 创建权限请求消息 |
| `create_permission_response_message(sender, recipient, response_data)` | 创建权限响应消息 |
| `create_sandbox_permission_request_message(...)` | 创建沙箱权限请求 |
| `create_sandbox_permission_response_message(...)` | 创建沙箱权限响应 |
| `is_permission_request(msg)` | 类型守卫 |
| `is_permission_response(msg)` | 类型守卫 |
| `is_sandbox_permission_request(msg)` | 类型守卫 |
| `is_sandbox_permission_response(msg)` | 类型守卫 |
| `write_to_mailbox(recipient_name, message, team_name)` | 全局邮箱写入 |

#### `swarm/registry.py`

| 导出 | 说明 |
|------|------|
| `BackendRegistry` | 后端注册中心 |
| `get_backend_registry()` | 获取进程级单例 |
| `mark_in_process_fallback()` | 标记 in_process 降级 |

#### `swarm/team_lifecycle.py`

| 导出 | 说明 |
|------|------|
| `sanitize_name(name)` | 名称清洗（非字母数字→连字符，小写） |
| `sanitize_agent_name(name)` | Agent 名称清洗（@ → -） |
| `AllowedPath` | 允许路径数据类 |
| `TeamMember` | 团队成员数据类 |
| `TeamFile` | 团队文件数据类 |
| `TeamLifecycleManager` | 团队生命周期管理器 |
| `read_team_file(team_name)` | 同步读取团队文件 |
| `write_team_file(team_name, team_file)` | 同步写入团队文件 |
| `read_team_file_async(team_name)` | 异步读取 |
| `write_team_file_async(team_name, team_file)` | 异步写入 |
| `remove_teammate_from_team_file(team, identifier)` | 按 ID/名称移除成员 |
| `add_hidden_pane_id(team, pane_id)` | 添加隐藏窗格 ID |
| `remove_hidden_pane_id(team, pane_id)` | 移除隐藏窗格 ID |
| `remove_member_from_team(team, tmux_pane_id)` | 按 tmux 窗格 ID 移除 |
| `remove_member_by_agent_id(team, agent_id)` | 按 Agent ID 移除 |
| `set_member_mode(team, member_name, mode)` | 设置权限模式 |
| `sync_teammate_mode(mode, team_name_override)` | 同步当前 Agent 模式 |
| `set_multiple_member_modes(team, mode_updates)` | 批量设置模式 |
| `set_member_active(team, member_name, is_active)` | 设置活跃状态 |
| `register_team_for_session_cleanup(team)` | 注册清理追踪 |
| `unregister_team_for_session_cleanup(team)` | 取消清理追踪 |
| `cleanup_session_teams()` | 清理会话团队 |
| `cleanup_team_directories(team)` | 清理团队目录 |
| `get_team_file_path(team)` | 获取 team.json 路径 |

#### `swarm/permission_sync.py`

| 导出 | 说明 |
|------|------|
| `SwarmPermissionRequest` | 权限请求数据类 |
| `PermissionResolution` | 解析结果数据类 |
| `PermissionResponse` | 旧版响应数据类 |
| `SwarmPermissionResponse` | 权限响应数据类 |
| `generate_request_id()` | 生成权限请求 ID |
| `generate_sandbox_request_id()` | 生成沙箱请求 ID |
| `create_permission_request(tool_name, ...)` | 构造权限请求 |
| `write_permission_request(request)` | 写入 pending 目录 |
| `read_pending_permissions(team_name)` | 读取待处理请求 |
| `read_resolved_permission(request_id, team_name)` | 读取已解析请求 |
| `resolve_permission(request_id, resolution, team_name)` | 解析请求 |
| `cleanup_old_resolutions(team_name, max_age_seconds)` | 清理旧解析文件 |
| `delete_resolved_permission(request_id, team_name)` | 删除已解析文件 |
| `poll_for_response(request_id, ...)` | 轮询响应（旧版） |
| `remove_worker_response(request_id, ...)` | 删除响应（旧版） |
| `submit_permission_request` | `write_permission_request` 的别名 |
| `is_team_leader(team_name)` | 判断是否为领导者 |
| `is_swarm_worker()` | 判断是否为工作者 |
| `get_leader_name(team_name)` | 获取领导者名称 |
| `send_permission_request_via_mailbox(request)` | 邮箱通道发送请求 |
| `send_permission_response_via_mailbox(...)` | 邮箱通道发送响应 |
| `send_sandbox_permission_request_via_mailbox(...)` | 邮箱通道发送沙箱请求 |
| `send_sandbox_permission_response_via_mailbox(...)` | 邮箱通道发送沙箱响应 |
| `send_permission_request(request, ...)` | 结构化负载发送（旧版） |
| `poll_permission_response(team, worker, request_id, timeout)` | 邮箱轮询响应 |
| `handle_permission_request(request, checker)` | 评估权限请求 |
| `send_permission_response(response, ...)` | 结构化负载响应（旧版） |

#### `swarm/in_process.py`

| 导出 | 说明 |
|------|------|
| `TeammateAbortController` | 双信号中止控制器 |
| `TeammateStatus` | 状态字面量类型 |
| `TeammateContext` | Agent 隔离上下文 |
| `get_teammate_context()` | 获取当前上下文 |
| `set_teammate_context(ctx)` | 设置当前上下文 |
| `start_in_process_teammate(...)` | Agent 执行协程 |
| `InProcessBackend` | 进程内后端类 |

### 5.2 Services 模块公开接口

#### `services/compact/__init__.py`

| 导出 | 说明 |
|------|------|
| `CompactAttachment` | 压缩附件数据类 |
| `CompactionResult` | 压缩结果数据类 |
| `AutoCompactState` | 自动压缩状态 |
| `COMPACTABLE_TOOLS` | 可压缩工具集合 |
| `TIME_BASED_MC_CLEARED_MESSAGE` | 工具结果清除占位符 |
| `AUTO_COMPACT_BUFFER_TOKENS` | 自动压缩缓冲（13000） |
| `MAX_OUTPUT_TOKENS_FOR_SUMMARY` | 摘要最大输出 token（20000） |
| `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` | 最大连续失败次数（3） |
| `estimate_message_tokens(messages)` | 估算消息 token 数 |
| `estimate_conversation_tokens(messages)` | 同上（旧版别名） |
| `microcompact_messages(messages, keep_recent)` | 微压缩 |
| `try_context_collapse(messages, preserve_recent)` | 上下文折叠 |
| `try_session_memory_compaction(messages, ...)` | 会话记忆压缩 |
| `compact_conversation(messages, ...)` | 完整 LLM 压缩 |
| `auto_compact_if_needed(messages, ...)` | 自动压缩入口 |
| `should_autocompact(messages, model, state, ...)` | 是否需要自动压缩 |
| `get_autocompact_threshold(model, ...)` | 获取自动压缩阈值 |
| `get_context_window(model, ...)` | 获取模型上下文窗口大小 |
| `get_compact_prompt(custom_instructions)` | 构造压缩提示词 |
| `format_compact_summary(raw_summary)` | 格式化压缩摘要 |
| `build_compact_summary_message(summary, ...)` | 构造注入消息 |
| `build_post_compact_messages(result)` | 构建压缩后消息列表 |
| `create_compact_boundary_message(metadata)` | 创建边界标记消息 |
| `render_compact_attachment(attachment)` | 渲染附件为消息 |
| `summarize_messages(messages, ...)` | 旧版文本摘要 |
| `compact_messages(messages, ...)` | 旧版消息压缩 |

附件工厂函数：

| 导出 | 说明 |
|------|------|
| `create_task_focus_attachment_if_needed(metadata)` | 工作焦点附件 |
| `create_recent_verified_work_attachment_if_needed(...)` | 已验证工作附件 |
| `create_recent_files_attachment_if_needed(read_file_state)` | 最近文件附件 |
| `create_plan_attachment_if_needed(metadata)` | Plan mode 附件 |
| `create_invoked_skills_attachment_if_needed(invoked_skills)` | 已调用技能附件 |
| `create_async_agent_attachment_if_needed(async_agent_state)` | 异步 Agent 附件 |
| `create_work_log_attachment_if_needed(recent_work_log)` | 工作日志附件 |

#### `services/session_storage.py`

| 导出 | 说明 |
|------|------|
| `get_project_session_dir(cwd)` | 获取项目会话目录 |
| `save_session_snapshot(...)` | 保存快照 |
| `load_session_snapshot(cwd)` | 加载最新快照 |
| `list_session_snapshots(cwd, limit)` | 列出快照 |
| `load_session_by_id(cwd, session_id)` | 按 ID 加载 |
| `export_session_markdown(...)` | 导出 Markdown |

#### `services/session_backend.py`

| 导出 | 说明 |
|------|------|
| `SessionBackend` | 会话后端 Protocol |
| `OpenHarnessSessionBackend` | 默认实现 |
| `DEFAULT_SESSION_BACKEND` | 默认实例 |

#### `services/token_estimation.py`

| 导出 | 说明 |
|------|------|
| `estimate_tokens(text)` | 估算单文本 token |
| `estimate_message_tokens(messages)` | 估算消息列表 token |

#### `services/cron.py`

| 导出 | 说明 |
|------|------|
| `load_cron_jobs()` | 加载任务列表 |
| `save_cron_jobs(jobs)` | 保存任务列表 |
| `validate_cron_expression(expression)` | 验证 cron 表达式 |
| `next_run_time(expression, base)` | 计算下次运行时间 |
| `upsert_cron_job(job)` | 插入或替换任务 |
| `delete_cron_job(name)` | 删除任务 |
| `get_cron_job(name)` | 获取单个任务 |
| `set_job_enabled(name, enabled)` | 启用/禁用任务 |
| `mark_job_run(name, *, success)` | 标记任务执行结果 |

#### `services/cron_scheduler.py`

| 导出 | 说明 |
|------|------|
| `TICK_INTERVAL_SECONDS` | 调度间隔（30s） |
| `get_history_path()` | 历史文件路径 |
| `append_history(entry)` | 追加执行记录 |
| `load_history(limit, job_name)` | 加载执行历史 |
| `get_pid_path()` | PID 文件路径 |
| `read_pid()` / `write_pid()` / `remove_pid()` | PID 文件管理 |
| `is_scheduler_running()` | 调度器是否运行 |
| `stop_scheduler()` | 停止调度器 |
| `execute_job(job)` | 执行单个任务 |
| `run_scheduler_loop(*, once)` | 调度主循环 |
| `start_daemon()` | Fork 守护进程 |
| `scheduler_status()` | 获取状态信息 |

---

## 6. 错误处理

### 6.1 Swarm 模块错误处理

| 场景 | 处理方式 |
|------|----------|
| 邮箱 JSON 解析失败 | `read_all()` 跳过损坏文件，不抛异常 |
| 邮箱写入锁竞争 | `exclusive_file_lock` 阻塞等待，超时抛 `SwarmLockUnavailableError` |
| Agent 重复 spawn | `InProcessBackend.spawn()` 返回 `SpawnResult(success=False, error=...)` |
| 权限请求 team_name 缺失 | `create_permission_request()` 抛 `ValueError` |
| 权限解析 pending 文件不存在 | `resolve_permission()` 返回 `False` |
| 团队已存在 | `TeamLifecycleManager.create_team()` 抛 `ValueError` |
| 团队不存在 | `TeamLifecycleManager.delete_team()` / `_require_team()` 抛 `ValueError` |
| 面板后端不可用 | `detect_pane_backend()` 抛 `RuntimeError`（含安装指引） |
| 后端未注册 | `get_executor()` 抛 `KeyError` |
| Agent Task 异常退出 | `_on_done` 回调记录错误日志并从 `_active` 移除 |
| 优雅关闭超时 | `InProcessBackend.shutdown()` 升级为 `force_cancel` + `task.cancel()` |
| worktree 销毁失败 | 先 `git worktree remove --force`，失败则 `shutil.rmtree` |
| 孤儿窗格 kill 失败 | `_kill_orphaned_teammate_panes()` 忽略异常（`return_exceptions=True`） |

### 6.2 Services 模块错误处理

| 场景 | 处理方式 |
|------|----------|
| Microcompact 无工具可清 | 返回 `(messages, 0)`，不报错 |
| Context Collapse 无变化 | 返回 `None`，不执行后续步骤 |
| Session Memory 无旧消息 | 返回 `None` |
| Full Compact LLM 超时 | `asyncio.wait_for` 抛 `TimeoutError`，触发流式重试 |
| Full Compact PTL | 检测 `"prompt too long"` 等关键词，截断最旧轮次重试（最多 3 次） |
| Full Compact 摘要为空 | 返回 passthrough 结果（保留原始消息） |
| 自动压缩连续失败 3 次 | `should_autocompact()` 返回 `False`，不再触发 |
| 会话快照 JSON 损坏 | `load_session_snapshot()` 返回 `None` |
| Cron 任务执行超时 | 300s 超时后 kill 进程，记录 `"status": "timeout"` |
| Cron 任务沙箱不可用 | 捕获 `SandboxUnavailableError`，记录 `"status": "error"` |
| Cron 注册表 JSON 损坏 | `load_cron_jobs()` 返回空列表 |
| Cron 表达式无效 | `upsert_cron_job()` 不计算 `next_run`，但仍保存 |
| 调度器 PID 文件残留 | `read_pid()` 检测进程存活，清理陈旧 PID 文件 |
| 调度器优雅停止失败 | 10 轮检查后 SIGKILL 强制终止 |

---

## 7. 配置项

### 7.1 环境变量

| 变量 | 模块 | 说明 |
|------|------|------|
| `CLAUDE_CODE_TEAM_NAME` | permission_sync, team_lifecycle, mailbox | 当前团队名 |
| `CLAUDE_CODE_AGENT_ID` | permission_sync | 当前 Agent ID（name@team） |
| `CLAUDE_CODE_AGENT_NAME` | permission_sync, team_lifecycle | 当前 Agent 名称 |
| `CLAUDE_CODE_AGENT_COLOR` | permission_sync | 当前 Agent 颜色 |
| `TMUX` | registry | tmux 会话标识（由 tmux 自动设置） |
| `ITERM_SESSION_ID` | registry | iTerm2 会话标识（由 iTerm2 自动设置） |
| `OPENHARNESS_TEAMMATE_MODE` | registry | 后端模式覆盖：`"auto"\|"in_process"\|"tmux"` |

### 7.2 文件路径

| 路径 | 模块 | 说明 |
|------|------|------|
| `~/.openharness/teams/<name>/team.json` | team_lifecycle | 团队元数据 |
| `~/.openharness/teams/<name>/agents/<id>/inbox/` | mailbox | Agent 收件箱 |
| `~/.openharness/teams/<name>/permissions/pending/` | permission_sync | 待处理权限请求 |
| `~/.openharness/teams/<name>/permissions/resolved/` | permission_sync | 已解析权限请求 |
| `~/.openharness/sessions/<dirname>-<hash>/latest.json` | session_storage | 最新会话快照 |
| `~/.openharness/sessions/<dirname>-<hash>/session-<id>.json` | session_storage | 按 ID 的会话快照 |
| `~/.openharness/sessions/<dirname>-<hash>/transcript.md` | session_storage | Markdown 格式转录 |
| `~/.openharness/data/cron_history.jsonl` | cron_scheduler | Cron 执行历史 |
| `~/.openharness/data/cron_scheduler.pid` | cron_scheduler | 调度器 PID 文件 |
| `~/.openharness/logs/cron_scheduler.log` | cron_scheduler | 调度器日志 |

### 7.3 常量配置

#### 压缩系统常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `AUTOCOMPACT_BUFFER_TOKENS` | 13000 | 自动压缩缓冲 |
| `MAX_OUTPUT_TOKENS_FOR_SUMMARY` | 20000 | 摘要最大输出 token |
| `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES` | 3 | 最大连续失败次数 |
| `COMPACT_TIMEOUT_SECONDS` | 25 | 压缩超时 |
| `MAX_COMPACT_STREAMING_RETRIES` | 2 | 流式重试次数 |
| `MAX_PTL_RETRIES` | 3 | PTL 重试次数 |
| `SESSION_MEMORY_KEEP_RECENT` | 12 | Session Memory 保留消息数 |
| `SESSION_MEMORY_MAX_LINES` | 48 | Session Memory 最大行数 |
| `SESSION_MEMORY_MAX_CHARS` | 4000 | Session Memory 最大字符数 |
| `CONTEXT_COLLAPSE_TEXT_CHAR_LIMIT` | 2400 | Context Collapse 触发阈值 |
| `CONTEXT_COLLAPSE_HEAD_CHARS` | 900 | Context Collapse 保留头部 |
| `CONTEXT_COLLAPSE_TAIL_CHARS` | 500 | Context Collapse 保留尾部 |
| `MAX_COMPACT_ATTACHMENTS` | 6 | 最大附件数 |
| `MAX_DISCOVERED_TOOLS` | 12 | 最大发现工具数 |
| `DEFAULT_KEEP_RECENT` | 5 | Microcompact 默认保留数 |
| `DEFAULT_GAP_THRESHOLD_MINUTES` | 60 | 时间间隔阈值（分钟） |
| `TOKEN_ESTIMATION_PADDING` | 4/3 | Token 估算膨胀系数 |
| `_DEFAULT_CONTEXT_WINDOW` | 200000 | 默认上下文窗口大小 |

#### 会话持久化常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `_PERSISTED_TOOL_METADATA_KEYS` | 9 个键 | 跨压缩持久化的元数据键 |

持久化键列表：
```python
_PERSISTED_TOOL_METADATA_KEYS = (
    "permission_mode",
    "read_file_state",
    "invoked_skills",
    "async_agent_state",
    "recent_work_log",
    "recent_verified_work",
    "task_focus_state",
    "compact_checkpoints",
    "compact_last",
)
```

#### Cron 调度常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `TICK_INTERVAL_SECONDS` | 30 | 调度检查间隔 |
| 任务超时 | 300 | 单任务执行超时 |
| stdout/stderr 截断 | 2000 字符 | 执行记录保留 |

#### InProcess 后端常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `shutdown timeout` | 10.0s | 优雅关闭等待时间 |
| stub 运行轮次 | 10 | 无 query_context 时的最大等待轮次 |
| stub 轮次间隔 | 0.1s | 每轮等待时间 |

---

## 8. 与其它模块的交互

### 8.1 Swarm 模块交互图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        外部调用方                                    │
│  (coordinator_mode.py / CLI / API)                                  │
└──────┬──────────┬──────────────┬───────────────┬────────────────────┘
       │          │              │               │
       ▼          ▼              ▼               ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌────────────────┐
│ registry │ │ team_    │ │ permission_  │ │  in_process     │
│          │ │ lifecycle│ │ sync         │ │                │
└──┬───┬───┘ └──┬───┬──┘ └──┬────┬──────┘ └──┬──────┬──────┘
   │   │        │   │       │    │            │      │
   │   │        │   │       │    │            │      │
   ▼   ▼        ▼   ▼       ▼    ▼            ▼      ▼
┌──────┐  ┌──────┐  ┌───────────┐  ┌──────────────────────┐
│types │  │mailbox│  │ lockfile  │  │ engine.query         │
│      │  │      │  │(re-export)│  │ (run_query)          │
└──────┘  └──────┘  └───────────┘  └──────────────────────┘
```

**交互关系**：

1. **registry → types**：`BackendRegistry` 依赖 `BackendType`、`TeammateExecutor`、`BackendDetectionResult` 类型定义。
2. **registry → platforms**：通过 `get_platform()` / `get_platform_capabilities()` 获取平台信息，决定是否注册 `InProcessBackend`。
3. **registry → spawn_utils**：使用 `is_tmux_available()` 检测 tmux 二进制可用性。
4. **team_lifecycle → mailbox**：使用 `get_team_dir()` 构造团队目录路径；`_kill_orphaned_teammate_panes()` 通过 registry 获取 executor。
5. **permission_sync → mailbox**：权限请求/响应通过 `TeammateMailbox`、`write_to_mailbox()`、消息工厂函数发送。
6. **permission_sync → lockfile**：文件通道使用 `exclusive_file_lock` 保证原子操作。
7. **permission_sync → team_lifecycle**：`get_leader_name()` 通过 `read_team_file_async()` 查找领导者。
8. **in_process → mailbox**：`start_in_process_teammate()` 创建 `TeammateMailbox`，在 `_drain_mailbox()` 中读取消息，退出时写入 `idle_notification`。
9. **in_process → types**：依赖 `SpawnResult`、`TeammateSpawnConfig`、`TeammateMessage`。
10. **in_process → engine.query**：`_run_query_loop()` 调用 `run_query()` 驱动 Agent 执行。

### 8.2 Services 模块交互图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    查询引擎 (engine.query)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │  auto_compact│  │ session_     │  │   CronCreate/CronDelete  │  │
│  │  _if_needed  │  │ save/restore │  │   工具集成               │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────────┘  │
└─────────┼─────────────────┼─────────────────────┼──────────────────┘
          │                 │                     │
          ▼                 ▼                     ▼
┌─────────────────┐ ┌───────────────┐ ┌─────────────────────┐
│  compact/       │ │ session_      │ │ cron /               │
│  __init__.py    │ │ storage.py    │ │ cron_scheduler.py    │
└────┬────┬───────┘ └──────┬────────┘ └────┬────────┬────────┘
     │    │                 │               │        │
     ▼    ▼                 ▼               ▼        ▼
┌────────┐ ┌──────┐  ┌──────────┐  ┌────────┐  ┌───────────┐
│token_  │ │hooks │  │session_  │  │config/ │  │utils/     │
│estimat.│ │      │  │backend   │  │paths   │  │file_lock  │
│        │ │      │  │          │  │        │  │fs         │
└────────┘ └──────┘  └──────────┘  └────────┘  └───────────┘
```

**交互关系**：

1. **compact → token_estimation**：`estimate_message_tokens()` 使用 `estimate_tokens()` 基础函数 + 4/3 膨胀系数。
2. **compact → engine.messages**：依赖 `ConversationMessage`、`TextBlock`、`ToolResultBlock`、`ToolUseBlock`、`ImageBlock` 等消息类型。
3. **compact → hooks**：`compact_conversation()` 在压缩前后执行 `PRE_COMPACT` / `POST_COMPACT` 钩子。
4. **compact → engine.stream_events**：通过 `CompactProgressEvent` 报告压缩进度。
5. **compact → api.client**：Full compact 调用 `api_client.stream_message()` 生成摘要。
6. **session_storage → engine.messages**：使用 `ConversationMessage`、`sanitize_conversation_messages()`。
7. **session_storage → config.paths**：通过 `get_sessions_dir()` 获取会话存储根目录。
8. **session_storage → utils.fs**：使用 `atomic_write_text()` 原子写入。
9. **session_storage → api.usage**：使用 `UsageSnapshot.model_dump()` 序列化用量数据。
10. **session_backend → session_storage**：`OpenHarnessSessionBackend` 委托所有操作至 `session_storage` 模块。
11. **cron → config.paths**：通过 `get_cron_registry_path()` 获取注册表路径。
12. **cron → utils.file_lock / utils.fs**：使用 `exclusive_file_lock` 和 `atomic_write_text`。
13. **cron → croniter**：使用 `croniter` 第三方库解析 cron 表达式。
14. **cron_scheduler → cron**：加载任务、标记执行结果、验证表达式。
15. **cron_scheduler → config.paths**：获取数据目录和日志目录。
16. **cron_scheduler → sandbox**：捕获 `SandboxUnavailableError`。
17. **cron_scheduler → utils.shell**：使用 `create_shell_subprocess()` 执行任务命令。

### 8.3 跨模块交互

1. **swarm ↔ services/compact**：无直接依赖。但 swarm 中 `TeammateContext.total_tokens` 的值由 compact 模块的 `estimate_message_tokens()` 语义驱动。
2. **swarm ↔ services/session_storage**：`TeammateSpawnConfig.parent_session_id` 与 `session_storage` 中的 `session_id` 对应，用于跨 Agent 的会话关联。
3. **swarm/permission_sync ↔ services/cron**：`cron_list` 在只读工具白名单中，意味着 Cron 工具不需要领导者权限审批。
4. **services/compact → swarm（间接）**：压缩后保留的 `_PERSISTED_TOOL_METADATA_KEYS` 中包含 `permission_mode`、`task_focus_state` 等字段，这些字段在 swarm 的权限同步和工作焦点追踪中被使用。