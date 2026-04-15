# Phase 9: 高级特性 — Swarm, Services, UI 深度解析

> 涉及文件:
> - `swarm/types.py` (393行) — 核心类型: BackendType, PaneBackend, TeammateIdentity, SpawnConfig, SpawnResult
> - `swarm/mailbox.py` (523行) — 文件系统邮箱: Agent 间异步消息传递
> - `swarm/registry.py` (411行) — 后端注册: tmux/iTerm2/in_process/subprocess 检测与选择
> - `swarm/team_lifecycle.py` (830行) — 团队生命周期: TeamFile 持久化, 成员管理
> - `swarm/permission_sync.py` (1169行) — 权限同步: Worker ↔ Leader 间权限请求/响应
> - `swarm/in_process.py` (460行) — 进程内后端: ContextVar 隔离, TeammateAbortController
> - `swarm/subprocess_backend.py` — 子进程后端
> - `swarm/worktree.py` — Git Worktree 隔离
> - `swarm/lockfile.py` — 文件锁
> - `swarm/spawn_utils.py` — tmux 可用性检测
> - `services/compact/__init__.py` (1581行) — 上下文压缩: microcompact, full compact, auto-compact
> - `services/session_storage.py` (270行) — 会话持久化
> - `services/token_estimation.py` (40行) — Token 估算
> - `services/cron.py` / `cron_scheduler.py` — 定时任务
> - `services/session_backend.py` — 会话后端抽象
> - `ui/app.py` (303行) — 运行模式入口
> - `ui/protocol.py` (222行) — React TUI 通信协议
> - `ui/react_launcher.py` (175行) — React TUI 启动器
> - `ui/runtime.py` (648行) — 运行时核心
> - `ui/textual_app.py` (487行) — Textual TUI (备选)
> - `ui/backend_host.py` — 后端宿主进程

Swarm 多 Agent 系统:
  - 4 种后端: tmux (可视化面板) > iTerm2 (macOS 标签) > subprocess (回退) > in_process (最快)
  - 后端自动检测: 在 tmux 中 → tmux, 否则 → subprocess
  - ContextVar 隔离: in_process 后端用 Python ContextVar 实现同进程多 Worker 状态隔离, 无锁
  - 双信号中止: cancel_event (优雅) + force_cancel (强制), 支持完成当前工具后退出
  - 权限同步: Worker 写操作需 Leader 审批, 通过文件系统 (pending/resolved) 或邮箱协议
  - 团队持久化: ~/.openharness/teams/<name>/team.json, 原子写 (tmp + rename)

  上下文压缩 (最复杂的子系统, 1581 行):
  - 4 级递进策略: microcompact (替换旧工具结果) → context_collapse (截断长文本) → session_memory (确定性结构化摘要) → full compact (LLM 摘要)
  - Auto-compact: 每轮查询检查, 接近 context window 上限时自动触发
  - 连续 3 次失败后停止 auto-compact
  - tool_metadata 的 9 个关键键 (permission_mode, recent_work_log 等) 在压缩后保留

  UI 层:
  - 默认 React TUI (Ink), 通过 stdin/stdout JSON 与 Python 后端通信
  - 后端以 --backend-only 子进程模式运行
  - BackendEvent (18 种事件类型) → 前端, FrontendRequest (7 种请求类型) → 后端
---

## 1. Swarm 多 Agent 系统架构

```
Leader (主 Agent)
  │
  ├── BackendRegistry ──── 自动检测最优后端
  │   ├── tmux (在 tmux 会话中)     ← 多终端面板
  │   ├── iTerm2 (macOS + it2 CLI)  ← 多终端标签
  │   ├── subprocess               ← 子进程 (始终可用)
  │   └── in_process               ← 进程内 asyncio Task
  │
  ├── TeamLifecycleManager ──── 团队创建/销毁/成员管理
  │   └── TeamFile (team.json) ──── 持久化团队状态
  │
  ├── TeammateMailbox ──── Agent 间异步消息传递
  │   └── 文件系统队列 (JSON 文件 + 原子写)
  │
  └── PermissionSync ──── Worker ↔ Leader 权限协调
      ├── 文件系统协议 (pending/resolved 目录)
      └── 邮箱协议 (MailboxMessage)
```

---

## 2. 后端类型与检测优先级

### 四种后端

| 后端 | 执行方式 | 视觉 | 可用条件 |
|------|----------|------|----------|
| `tmux` | tmux 窗格中运行子进程 | 多面板 | 在 tmux 会话中 + tmux 二进制可用 |
| `iterm2` | iTerm2 标签页 | 多标签 | macOS + iTerm2 + `it2` CLI |
| `subprocess` | 后台子进程 | 无 | 始终可用 (安全回退) |
| `in_process` | asyncio Task (同进程) | 无 | 显式请求或回退激活 |

### 后端检测流程

```
detect_backend():
  1. in_process fallback 已激活? → "in_process"
  2. 在 tmux 中 ($TMUX set) + tmux 二进制? → "tmux"
  3. 否则 → "subprocess" (默认回退)

detect_pane_backend():
  1. 在 tmux 中 → "tmux"
  2. 在 iTerm2 中 + it2 CLI? → "iterm2"
  3. 在 iTerm2 中 + tmux 可用? → "tmux" (needs_setup=True)
  4. 在 iTerm2 中 + 无 tmux → RuntimeError
  5. 不在 tmux/iTerm2 + tmux 可用? → "tmux" (外部会话)
  6. 否则 → RuntimeError (安装指引)
```

### PaneBackend Protocol — 可视化面板管理

```python
class PaneBackend(Protocol):
    type: BackendType
    display_name: str
    supports_hide_show: bool
    
    async def is_available(self) -> bool
    async def is_running_inside(self) -> bool
    async def create_teammate_pane_in_swarm_view(name, color) -> CreatePaneResult
    async def send_command_to_pane(pane_id, command) -> None
    async def set_pane_border_color(pane_id, color) -> None
    async def set_pane_title(pane_id, name, color) -> None
    async def enable_pane_border_status(window_target) -> None
    async def rebalance_panes(window_target, has_leader) -> None
    async def kill_pane(pane_id) -> bool
    async def hide_pane(pane_id) -> bool
    async def show_pane(pane_id, target) -> bool
    def list_panes() -> list[PaneId]
```

---

## 3. TeammateIdentity 与 SpawnConfig

### TeammateIdentity — Agent 身份

```python
@dataclass
class TeammateIdentity:
    agent_id: str           # "agentName@teamName" 格式
    name: str               # "researcher", "tester" 等
    team: str               # 团队名
    color: str | None       # UI 颜色
    parent_session_id: str | None  # 父会话 ID
```

### TeammateSpawnConfig — 创建配置

```python
@dataclass
class TeammateSpawnConfig:
    name: str                              # 可读名
    team: str                              # 团队名
    prompt: str                            # 初始任务
    cwd: str                               # 工作目录
    parent_session_id: str                 # 父会话 ID
    model: str | None = None               # 模型覆盖
    system_prompt: str | None = None       # 自定义系统提示词
    system_prompt_mode: "default"|"replace"|"append"  # 提示词模式
    color: str | None = None               # UI 颜色
    permissions: list[str] = []            # 工具权限列表
    plan_mode_required: bool = False        # 是否需要 Plan 模式
    allow_permission_prompts: bool = False  # 是否允许权限提示
    worktree_path: str | None = None       # Git Worktree 隔离路径
    session_id: str | None = None          # 显式会话 ID
    subscriptions: list[str] = []           # 事件订阅主题
```

### SpawnResult — 创建结果

```python
@dataclass
class SpawnResult:
    task_id: str              # TaskManager 中的 ID
    agent_id: str             # "agentName@teamName"
    backend_type: BackendType # 使用的后端
    success: bool = True
    error: str | None = None
    pane_id: PaneId | None    # 可视化面板 ID
```

---

## 4. TeammateMailbox — 文件系统邮箱

### 消息类型

```python
MessageType = Literal[
    "user_message",                    # 用户消息转发
    "permission_request",              # 权限请求
    "permission_response",             # 权限响应
    "sandbox_permission_request",      # 沙箱权限请求
    "sandbox_permission_response",     # 沙箱权限响应
    "shutdown",                        # 关闭指令
    "idle_notification",               # 空闲通知
]
```

### 存储路径

```
~/.openharness/teams/<team>/agents/<agent_id>/inbox/<timestamp>_<message_id>.json
```

### 消息模型

```python
@dataclass
class MailboxMessage:
    id: str                    # 唯一 ID
    type: MessageType           # 消息类型
    sender: str                # 发送者 agent_id
    recipient: str             # 接收者 agent_id
    payload: dict[str, Any]    # 消息负载
    timestamp: float            # 时间戳
    read: bool = False         # 已读标记
```

### 核心操作

```python
class TeammateMailbox:
    async def send(message: MailboxMessage)    # 写入收件人 inbox
    async def receive() → list[MailboxMessage] # 读取自己的 inbox
    async def poll(interval=1.0)               # 轮询新消息
```

**原子写**: 使用 `.tmp` + `os.rename` 防止部分读。**文件锁**: `exclusive_file_lock` 保证并发安全。

---

## 5. TeamLifecycle — 团队生命周期管理

### TeamFile — 团队持久化状态

```python
@dataclass
class TeamFile:
    name: str                              # 团队名
    created_at: float                      # 创建时间
    description: str = ""                  # 描述
    lead_agent_id: str = ""                # Leader agent_id
    lead_session_id: str | None = None     # Leader 会话 ID
    hidden_pane_ids: list[str] = []        # 隐藏的面板
    members: dict[str, TeamMember] = {}   # agent_id → TeamMember
    team_allowed_paths: list[AllowedPath] = []  # 团队共享路径
    allowed_paths: list[str] = []          # 遗留路径列表
    metadata: dict[str, Any] = {}          # 额外元数据
```

### TeamMember — 成员信息

```python
@dataclass
class TeamMember:
    agent_id: str                           # "name@team"
    name: str                               # 可读名
    backend_type: BackendType               # 执行后端
    joined_at: float                        # 加入时间
    agent_type: str | None = None           # "researcher" 等
    model: str | None = None               # 使用的模型
    prompt: str | None = None              # 初始提示词
    color: str | None = None               # UI 颜色
    plan_mode_required: bool = False       # Plan 模式要求
    session_id: str | None = None         # 会话 UUID
    subscriptions: list[str] = []          # 事件订阅
    is_active: bool = True                 # 活跃状态
    mode: str | None = None               # 权限模式
    tmux_pane_id: str = ""                # 面板 ID
    cwd: str = ""                          # 工作目录
    worktree_path: str | None = None      # Git Worktree 路径
    permissions: list[str] = []            # 权限列表
    status: "active"|"idle"|"stopped" = "active"
```

### 持久化路径

```
~/.openharness/teams/<team_name>/team.json              ← 团队状态
~/.openharness/teams/<team_name>/agents/<id>/inbox/     ← 消息队列
~/.openharness/teams/<team_name>/permissions/pending/   ← 待审批权限
~/.openharness/teams/<team_name>/permissions/resolved/   ← 已审批权限
```

### 原子写

```python
def save(self, path: Path):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
    tmp.rename(path)   # 原子重命名
```

---

## 6. PermissionSync — 权限同步协议

### 两种协议

**文件系统协议**:
```
1. Worker: write_permission_request() → pending/<id>.json
2. Leader: read_pending_permissions() → 列出待审批
3. Leader: resolve_permission() → 移到 resolved/<id>.json
4. Worker: read_resolved_permission(id) → 读取审批结果
```

**邮箱协议**:
```
1. Worker: send_permission_request_via_mailbox()
2. Leader: 轮询邮箱 → send_permission_response_via_mailbox()
3. Worker: poll_permission_response() → 等待响应
```

### SwarmPermissionRequest — 权限请求

```python
@dataclass
class SwarmPermissionRequest:
    id: str                    # 请求唯一 ID
    worker_id: str             # Worker 的 agent_id
    worker_name: str           # Worker 可读名
    team_name: str             # 团队名
    tool_name: str             # 工具名 (Bash, Edit 等)
    tool_use_id: str           # 原始 tool-use ID
    description: str           # 操作描述
    input: dict[str, Any]      # 工具输入参数
    permission_suggestions: list  # 建议的权限规则
    worker_color: str | None   # Worker 颜色
    status: "pending"|"approved"|"rejected"  # 状态
    resolved_by: "worker"|"leader"|None       # 谁审批的
    resolved_at: float | None                 # 审批时间
    feedback: str | None                      # 拒绝原因
```

### 只读工具白名单

```python
_READ_ONLY_TOOLS = frozenset({
    "read_file", "glob", "grep", "web_fetch", "web_search",
    "task_get", "task_list", "task_output", "cron_list",
})
```

只读工具不需要权限审批, Worker 可直接执行。

### 环境变量身份

```python
CLAUDE_CODE_TEAM_NAME     # 团队名
CLAUDE_CODE_AGENT_ID      # agent_id
CLAUDE_CODE_AGENT_NAME    # 可读名
CLAUDE_CODE_AGENT_COLOR   # 颜色
```

这些环境变量在 Worker 进程中设置, 用于身份识别。

---

## 7. InProcessBackend — 进程内执行

### ContextVar 隔离

```python
_teammate_context: ContextVar[TeammateContext | None] = ContextVar("_teammate_context", default=None)

def get_teammate_context() -> TeammateContext | None:
    return _teammate_context.get()

def set_teammate_context(ctx: TeammateContext | None):
    _teammate_context.set(ctx)
```

**关键**: 同一进程内的多个 Worker 通过 `ContextVar` 实现状态隔离 — 每个 asyncio Task 看到自己的 teammate context, 无需加锁。

### TeammateContext — 每个同事的隔离状态

```python
@dataclass
class TeammateContext:
    agent_id: str
    agent_name: str
    team_name: str
    parent_session_id: str | None
    color: str | None
    plan_mode_required: bool
    abort_controller: TeammateAbortController   # 双信号中止
    message_queue: asyncio.Queue[TeammateMessage]  # 消息队列
    tool_use_count: int = 0
    total_tokens: int = 0
    status: TeammateStatus = "starting"          # starting/running/idle/stopping/stopped
```

### TeammateAbortController — 双信号中止

```python
class TeammateAbortController:
    cancel_event: asyncio.Event    # 优雅中止: 完成当前工具使用后退出
    force_cancel: asyncio.Event    # 强制中止: 立即取消 asyncio Task
    
    def request_cancel(reason, *, force=False):
        if force:
            self.force_cancel.set()
            self.cancel_event.set()    # 两个都设
        else:
            self.cancel_event.set()   # 只设优雅信号
```

---

## 8. 上下文压缩系统 — Compact

### 压缩策略层级

```
auto_compact_if_needed()
│
├── 1. microcompact (便宜) ──→ 清除旧工具结果内容
│   └── 够了? → 返回
│
├── 2. context_collapse (中等) ──→ 截断过长的 TextBlock
│   └── 够了? → 返回
│
├── 3. session_memory (确定性) ──→ 将旧消息压缩为结构化摘要
│   └── 够了? → 返回
│
└── 4. full compact (昂贵) ──→ LLM 调用生成摘要
    └── 失败? → consecutive_failures++ (连续3次后停止)
```

### Microcompact — 最便宜的压缩

```python
def microcompact_messages(messages, *, keep_recent=5):
    """清除旧的可压缩工具结果, 替换为占位符"""
    # 可压缩工具: read_file, bash, grep, glob, web_search, web_fetch, edit_file, write_file
    # 保留最近 keep_recent 条消息不变
    # 旧消息中的 ToolResultBlock → content 替换为 "[Old tool result content cleared]"
    return modified_messages, tokens_freed
```

**不需要 LLM 调用** — 纯粹的字符串替换。

### Context Collapse — 文本块截断

```python
def try_context_collapse(messages, *, preserve_recent):
    """截断过长的 TextBlock, 保留头尾"""
    # 阈值: 2400 字符
    # 保留: 头 900 字符 + 尾 500 字符
    # 中间: "...[collapsed N chars]..."
    if not changed or tokens_not_reduced:
        return None
```

### Session Memory — 确定性结构化摘要

```python
def try_session_memory_compaction(messages, *, preserve_recent=12):
    """将旧消息压缩为简洁的结构化摘要, 不需要 LLM 调用"""
    # 保留最近 12 条
    # 提取: 附件路径, 发现的工具, 最近工作日志
    # 生成紧凑的摘要消息 (最多 48 行 / 4000 字符)
```

### Full Compact — LLM 摘要

```python
async def compact_conversation(messages, *, api_client, model, ...):
    """调用 LLM 生成结构化摘要"""
    # 1. microcompact 先做 (减少 token)
    # 2. 分割: older (要摘要的) + newer (保留的)
    # 3. 提取: 附件路径 + 发现的工具
    # 4. 触发 PRE_COMPACT Hook
    # 5. 调用 LLM: 发送 older + compact_prompt
    # 6. 解析 LLM 响应为摘要
    # 7. 触发 POST_COMPACT Hook
    # 8. 构建 CompactionResult
    # 9. 如果 prompt-too-long: 截断头部重试
```

### Auto-Compact 触发条件

```python
def should_autocompact(messages, model, state, ...):
    # 不触发条件:
    # - consecutive_failures >= 3 (连续3次失败后放弃)
    # - 估计 token < context_window - buffer (13000)
    
    # 触发条件:
    # - 估计 token 接近 context window 上限
    # - 或 force=True
```

### CompactionResult 与消息重建

```python
@dataclass
class CompactionResult:
    trigger: "auto"|"manual"|"reactive"
    compact_kind: "full"|"session_memory"
    boundary_marker: ConversationMessage    # 边界标记
    summary_messages: list[ConversationMessage]  # LLM 摘要
    messages_to_keep: list[ConversationMessage]  # 保留的近期消息
    attachments: list[CompactAttachment]         # 附件信息
    hook_results: list[CompactAttachment]        # Hook 结果
    compact_metadata: dict                       # 元数据

def build_post_compact_messages(result):
    return [
        result.boundary_marker,    # "[Conversation compacted at ...]"
        *result.summary_messages,  # 摘要
        *result.messages_to_keep,  # 近期消息
        *attachment_messages,      # 附件
        *hook_messages,            # Hook 结果
    ]
```

### Token 估算

```python
def estimate_tokens(text: str) -> int:
    """粗略估算: 每 4 个字符 ≈ 1 token"""
    return max(1, (len(text) + 3) // 4)

def estimate_message_tokens(messages):
    """总估算 × 4/3 padding (保守估计)"""
    total = sum(estimate_tokens(block text) for all blocks)
    return int(total * 4/3)
```

### Compact 保留的 tool_metadata 键

```python
_PERSISTED_TOOL_METADATA_KEYS = (
    "permission_mode",          # 权限模式
    "read_file_state",          # 文件读取状态
    "invoked_skills",           # 已调用 Skill
    "async_agent_state",        # 异步 Agent 状态
    "recent_work_log",          # 最近工作日志
    "recent_verified_work",      # 最近验证工作
    "task_focus_state",          # 任务聚焦状态
    "compact_checkpoints",      # 压缩检查点
    "compact_last",             # 最近压缩
)
```

**关键**: 这些键在压缩前后持久保留, 确保压缩不丢失关键状态。

---

## 9. 会话持久化

### 存储路径

```
~/.openharness/sessions/<project-name>-<sha1-hash>/
├── latest.json          ← 最新快照
├── <session_id>.json    ← 按会话 ID 保存
├── <session_id>.md      ← Markdown 导出
└── <tag>.json / <tag>.md  ← 命名标签
```

### 快照内容

```python
def save_session_snapshot(*, cwd, model, system_prompt, messages, usage, ...):
    # 提取第一条用户消息作为摘要
    # 保存 tool_metadata 中的持久化键
    # 写入 <session_id>.json 和 latest.json
    # 导出 Markdown 转录
```

---

## 10. UI 层架构

### 三种运行模式

```
oh (无参数) → run_repl() → launch_react_tui()
oh --print-mode → run_print_mode() → 非交互输出
oh --backend-only → run_backend_host() → 纯后端 (React TUI 的子进程)
```

### React TUI 启动流程

```
launch_react_tui()
│
├── 1. 查找前端目录
│   ├── 包内: openharness/_frontend/ (pip install)
│   └── 开发: <repo>/frontend/terminal/
│
├── 2. npm install (如果 node_modules 不存在)
│
├── 3. 构建后端命令
│   └── [python, -m, openharness, --backend-only, --cwd, ..., --model, ...]
│
├── 4. 设置环境变量
│   └── OPENHARNESS_FRONTEND_CONFIG = {
│         "backend_command": [...],
│         "initial_prompt": "...",
│         "theme": "default"
│       }
│
├── 5. 解析 tsx 命令
│   ├── 本地: node_modules/.bin/tsx
│   ├── 全局: which("tsx")
│   └── 回退: npm exec -- tsx
│
└── 6. 启动 React 进程
    └── tsx src/index.tsx
```

### BackendEvent — 后端 → 前端事件

```python
class BackendEvent(BaseModel):
    type: Literal[
        "ready",               # 初始化完成
        "state_snapshot",       # 状态快照 (model, provider, ...)
        "tasks_snapshot",      # 后台任务列表
        "transcript_item",     # 对话转录项
        "compact_progress",    # 压缩进度
        "assistant_delta",     # 流式文本增量
        "assistant_complete",  # 助手轮次完成
        "line_complete",       # 用户输入行完成
        "tool_started",        # 工具开始执行
        "tool_completed",      # 工具执行完成
        "clear_transcript",    # 清空转录
        "modal_request",       # 弹窗请求 (权限确认等)
        "select_request",      # 选择请求
        "todo_update",         # Todo 更新
        "plan_mode_change",    # Plan 模式切换
        "swarm_status",        # Swarm 状态更新
        "error",               # 错误
        "shutdown",            # 关闭
    ]
    # + 各种可选字段携带事件数据
```

### FrontendRequest — 前端 → 后端请求

```python
class FrontendRequest(BaseModel):
    type: Literal[
        "submit_line",          # 提交用户输入
        "permission_response",  # 权限审批响应
        "question_response",    # 问题回答
        "list_sessions",       # 列出会话
        "select_command",      # 选择命令
        "apply_select_command", # 应用选中命令
        "shutdown",            # 关闭
    ]
```

### 通信架构

```
┌─────────────────────┐     stdin/stdout/JSON     ┌────────────────────┐
│  React TUI (Node.js) │ ◄──────────────────────► │  Backend Host (Py)  │
│  tsx src/index.tsx   │                           │  python -m oh       │
│                     │   FrontendRequest →        │  --backend-only     │
│                     │   ← BackendEvent           │                    │
│                     │                            │  ┌──────────────┐ │
│                     │                            │  │ handle_line()│ │
│                     │                            │  │  ↓           │ │
│                     │                            │  │ QueryEngine  │ │
│                     │                            │  │  ↓           │ │
│                     │                            │  │ Agent Loop   │ │
│                     │                            │  └──────────────┘ │
└─────────────────────┘                            └────────────────────┘
```

### State Payload — 前端状态

```python
def _state_payload(state: AppState):
    return {
        "model": state.model,
        "cwd": state.cwd,
        "provider": state.provider,
        "auth_status": state.auth_status,
        "base_url": state.base_url,
        "permission_mode": ...,   # Default/Plan Mode/Auto
        "theme": state.theme,
        "vim_enabled": state.vim_enabled,
        "voice_enabled": state.voice_enabled,
        "fast_mode": state.fast_mode,
        "effort": state.effort,
        "passes": state.passes,
        "mcp_connected": state.mcp_connected,
        "bridge_sessions": state.bridge_sessions,
        "output_style": state.output_style,
        "keybindings": dict(state.keybindings),
    }
```

---

## 11. 子 Agent 完整生命周期

```
1. 用户/Leader 请求创建子 Agent

2. Agent Tool: agent_tool.py
   → 读取 TeammateSpawnConfig
   → BackendRegistry.get_executor() 获取执行后端
   → executor.spawn(config)
   
3. InProcessBackend.spawn():
   → 创建 TeammateContext (ContextVar 隔离)
   → 创建 TeammateAbortController
   → asyncio.create_task(start_in_process_teammate(ctx, config))
   → 注册到 TaskManager
   
4. start_in_process_teammate():
   → set_teammate_context(ctx)  # 设置 ContextVar
   → build_runtime()  # 构建子 Agent 的 RuntimeBundle
   → 进入 Agent Loop (run_query)
   → 每轮之间: drain message_queue (处理 Leader 发来的消息)
   → 检查 cancel_event (优雅中止)
   
5. Leader → Worker 通信:
   → TeammateMailbox.send(message)  # 写入文件系统
   → Worker: mailbox.receive()     # 轮询读取
   
6. Worker → Leader 权限请求:
   → write_permission_request()     # pending/<id>.json
   → Leader: read_pending → resolve → resolved/<id>.json
   → Worker: poll_for_response()   # 等待审批
   
7. 关闭:
   → abort_controller.request_cancel()  # 优雅中止
   → 或 abort_controller.request_cancel(force=True)  # 强制中止
   → 从 TeamFile 移除成员
   → 清理 mailbox / pane
```

---

## 12. Cron 调度

### 服务文件

- `services/cron.py` — Cron 数据模型与解析
- `services/cron_scheduler.py` — 调度器实现

### 功能

- 支持 5 字段 cron 表达式 (分 时 日 月 周)
- 一次性提醒 (`recurring: false`)
- 定期任务 (`recurring: true`, 7 天自动过期)
- 与 CLI 的 `CronCreate`/`CronDelete` 工具集成

---

## 13. 服务层对比

| 服务 | 职责 | 复杂度 | 核心概念 |
|------|------|--------|----------|
| compact | 上下文压缩 | ★★★★★ | 4 级压缩策略 + auto-compact |
| session_storage | 会话持久化 | ★★ | 快照 + Markdown 导出 |
| cron_scheduler | 定时任务 | ★★ | cron 表达式 + 7 天过期 |
| token_estimation | Token 估算 | ★ | 4 字符/token + 4/3 padding |
| session_backend | 会话后端抽象 | ★★ | 存储路径 + 快照 CRUD |
| lsp | Language Server Protocol | ★★★ | 诊断/补全/跳转 |
| oauth | OAuth 辅助 | ★★ | Device Flow 支持 |

---

## 14. 安全考虑

### Swarm 安全

1. **只读工具白名单**: Worker 可直接执行 `read_file`, `glob` 等无需审批
2. **权限同步协议**: 写操作需要 Leader 审批 (文件系统或邮箱协议)
3. **Git Worktree 隔离**: Worker 可在独立 worktree 中操作, 不影响主分支
4. **Plan Mode 限制**: `plan_mode_required=True` 的 Worker 必须先进入 Plan 模式
5. **环境变量身份**: 通过 `CLAUDE_CODE_AGENT_*` 环境变量标识 Worker

### Compact 安全

1. **连续失败保护**: 3 次连续失败后停止 auto-compact, 防止无限循环
2. **超时保护**: compact LLM 调用有 25 秒超时
3. **Prompt-too-long 处理**: 如果 compact 请求本身太大, 截断头部重试
4. **tool_metadata 保留**: 压缩后保留关键状态 (权限模式, 工作日志等)

### UI 安全

1. **后端隔离**: React TUI 通过 stdin/stdout JSON 与后端通信, 不直接暴露 Python 对象
2. **子进程模式**: `--backend-only` 在独立进程中运行, 前端崩溃不影响后端
3. **TTY 继承**: Windows/WSL 上直接调用 `tsx` 二进制, 避免 npm 中间进程破坏 TTY