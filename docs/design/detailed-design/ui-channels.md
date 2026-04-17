# UI 与通道模块详细设计

> 覆盖模块: ui/, channels/, bridge/
> 文件数: ~25 | 总行数: ~2,500

---

## 1. 模块概述

### 职责定位

| 模块 | 职责 | 复杂度 |
|------|------|--------|
| `ui/` | 用户交互层: React TUI + Backend Host + 通信协议 + 运行时核心 | ★★★ |
| `channels/` | 消息通道: 10种聊天平台 → Agent 桥接 | ★★★ |
| `bridge/` | 会话桥接: ohmo Web 扩展的 Worker 会话管理 | ★★ |

### 模块依赖关系

```
ui/
  ├── runtime.py ─→ engine, config, auth, tools, permissions, hooks, skills, memory, prompts, commands, mcp, sandbox, state
  ├── app.py ─→ runtime, react_launcher, textual_app
  ├── protocol.py ─→ engine (StreamEvent → BackendEvent 转换)
  ├── react_launcher.py ─→ platforms (tsx 二进制查找)
  └── backend_host.py ─→ runtime, protocol

channels/
  ├── base.py ─→ (ABC, 无外部依赖)
  ├── bus.py ─→ asyncio.Queue
  ├── bridge.py ─→ engine (QueryEngine.submit_message)
  └── telegram/discord/slack/... ─→ 各平台 SDK

bridge/
  ├── work_secret.py ─→ base64, hashlib
  ├── manager.py ─→ tasks (BackgroundTaskManager), utils/shell
  └── session.py ─→ manager, work_secret
```

---

## 2. 核心类/接口

### 2.1 UI 层类图

```
┌──────────────────────────────────────────────┐
│                  UI 层                        │
├──────────────────────────────────────────────┤
│                                              │
│  ┌──────────────┐    ┌───────────────────┐   │
│  │  React TUI   │    │  Textual TUI      │   │
│  │ (Ink/Node.js)│    │ (Python Textual)  │   │
│  └──────┬───────┘    └─────────┬─────────┘   │
│         │                      │             │
│  stdin/stdout JSON        Textual App        │
│         │                      │             │
│  ┌──────▼──────────────────────▼─────────┐   │
│  │           BackendHost (Py)            │   │
│  │  --backend-only 子进程模式            │   │
│  └──────────────────┬───────────────────┘   │
│                     │                        │
│  ┌──────────────────▼───────────────────┐   │
│  │          handle_line()               │   │
│  │  ┌────────────┐  ┌───────────────┐   │   │
│  │  │CommandReg. │  │ QueryEngine   │   │   │
│  │  │(斜杠命令)  │  │ (Agent Loop)  │   │   │
│  │  └────────────┘  └───────────────┘   │   │
│  └──────────────────────────────────────┘   │
│                     │                        │
│  ┌──────────────────▼───────────────────┐   │
│  │        AppStateStore (观察者)         │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

### 2.2 通道层类图

```
BaseChannel(ABC)              ← 通道接口
  ├── name: str
  ├── start() → None
  ├── stop() → None
  ├── send(OutboundMessage) → None
  └── receive() → InboundMessage

MessageBus                    ← 异步消息队列
  ├── inbound: asyncio.Queue[InboundMessage]
  └── outbound: asyncio.Queue[OutboundMessage]

ChannelBridge                 ← 核心桥接
  ├── engine: QueryEngine
  ├── bus: MessageBus
  ├── start() → None
  ├── stop() → None
  └── run() → None (阻塞)
```

### 2.3 Bridge 层类图

```
BridgeSessionManager          ← 会话管理
  ├── spawn(session_id, command, cwd) → SessionHandle
  ├── list_sessions() → list[BridgeSessionRecord]
  ├── read_output(session_id) → str
  └── stop(session_id) → None

WorkSecret                    ← 会话令牌 (frozen dataclass)
  ├── version: int (必须为1)
  ├── session_ingress_token: str
  └── api_base_url: str
```

---

## 3. 数据模型

### 3.1 BackendEvent — 后端 → 前端事件 (18种)

```python
class BackendEvent(BaseModel):
    type: Literal[
        "ready",               # 初始化完成
        "state_snapshot",       # 状态快照 (model, provider, ...)
        "tasks_snapshot",       # 后台任务列表
        "transcript_item",      # 对话转录项
        "compact_progress",    # 压缩进度
        "assistant_delta",     # 流式文本增量
        "assistant_complete",  # 助手轮次完成
        "line_complete",        # 用户输入行完成
        "tool_started",         # 工具开始执行
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

### 3.2 FrontendRequest — 前端 → 后端请求 (7种)

```python
class FrontendRequest(BaseModel):
    type: Literal[
        "submit_line",          # 提交用户输入
        "permission_response",  # 权限审批响应
        "question_response",    # 问题回答
        "list_sessions",        # 列出会话
        "select_command",      # 选择命令
        "apply_select_command", # 应用选中命令
        "shutdown",            # 关闭
    ]
```

### 3.3 AppState — 前端状态

```python
@dataclass
class AppState:
    model: str                # 当前模型
    permission_mode: str       # 权限模式
    theme: str                 # 主题名
    cwd: str                   # 工作目录
    provider: str              # Provider 名
    auth_status: str           # 认证状态
    base_url: str              # API 基础 URL
    vim_enabled: bool          # Vim 模式
    voice_enabled: bool        # 语音模式
    voice_available: bool      # 语音可用
    voice_reason: str          # 不可用原因
    fast_mode: bool            # 快速模式
    effort: str                # 推理强度
    passes: int                # 推理轮次
    mcp_connected: int         # MCP 已连接数
    mcp_failed: int            # MCP 失败数
    bridge_sessions: int       # 桥接会话数
    output_style: str          # 输出样式
    keybindings: dict          # 快捷键映射
```

### 3.4 AppStateStore — 观察者模式

```python
class AppStateStore:
    def __init__(self, initial_state: AppState)
    def get(self) → AppState
    def set(self, **updates) → AppState       # 更新状态 + 通知监听器
    def subscribe(self, listener) → callable   # 返回取消函数
```

### 3.5 通道消息模型

```python
@dataclass
class InboundMessage:          # 平台 → Agent
    channel: str               # "telegram" / "discord" / "slack" 等
    sender_id: str
    chat_id: str
    content: str               # 消息文本
    timestamp: datetime
    media: list[str]           # 媒体 URL
    metadata: dict             # 平台特定数据
    session_key_override: str  # 会话键覆盖

@dataclass
class OutboundMessage:         # Agent → 平台
    channel: str
    chat_id: str
    content: str
    reply_to: str | None       # 回复目标
    media: list[str]
    metadata: dict
```

### 3.6 Bridge 数据模型

```python
@dataclass(frozen=True)
class WorkSecret:
    version: int               # 版本号 (必须为1)
    session_ingress_token: str  # 会话入口 Token
    api_base_url: str           # API 基础 URL

@dataclass(frozen=True)
class BridgeConfig:
    dir: str                    # 工作目录
    machine_name: str           # 机器名
    max_sessions: int = 1       # 最大并发会话
    session_timeout_ms: int = 86400000  # 24h
```

---

## 4. 关键算法

### 4.1 React TUI 启动流程

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

### 4.2 handle_line() — 消息处理主循环

```
handle_line(user_input, bundle)
│
├── 1. 检查斜杠命令
│   ├── CommandRegistry.lookup(input)
│   ├── 命令存在 → 执行 handler(args, context)
│   │   └── CommandResult.refresh_runtime=True?
│   │       └── refresh_runtime_client(bundle)  # 重建 RuntimeBundle
│   └── 命令不存在 → 继续步骤 2
│
├── 2. 处理普通消息
│   ├── build_runtime_system_prompt(settings, cwd, latest_user_prompt)
│   │   └── 组装 11 个 Section (见 knowledge.md)
│   ├── engine.submit_message(user_input)
│   │   └── 流式 yield StreamEvent
│   └── 事件转换:
│       ├── AssistantTextDelta → BackendEvent(assistant_delta)
│       ├── AssistantTurnComplete → BackendEvent(assistant_complete)
│       ├── ToolExecutionStarted → BackendEvent(tool_started)
│       └── ToolExecutionCompleted → BackendEvent(tool_completed)
│
└── 3. 后处理
    ├── 保存会话快照
    └── sync_app_state(bundle)  # 刷新 UI 状态
```

### 4.3 StreamEvent → BackendEvent 转换

```
Agent Loop 产出 StreamEvent
    │
    ├── AssistantTextDelta       → BackendEvent(type="assistant_delta", text=...)
    ├── AssistantTurnComplete     → BackendEvent(type="assistant_complete", ...)
    ├── ToolExecutionStarted     → BackendEvent(type="tool_started", tool_name=...)
    ├── ToolExecutionCompleted   → BackendEvent(type="tool_completed", tool_name=...)
    ├── ErrorEvent               → BackendEvent(type="error", message=...)
    ├── StatusEvent              → BackendEvent(type="assistant_delta", text=...)  # 作为文本渲染
    └── CompactProgressEvent     → BackendEvent(type="compact_progress", ...)
```

### 4.4 ChannelBridge 消息流

```
聊天平台 (Telegram/Discord/...)
    │
    │  平台 SDK 回调
    ▼
BaseChannel.receive() → InboundMessage
    │
    │  MessageBus.publish_inbound()
    ▼
MessageBus.inbound (asyncio.Queue)
    │
    │  ChannelBridge.consume_inbound()
    ▼
QueryEngine.submit_message(inbound.content)
    │
    │  流式响应
    ▼
MessageBus.publish_outbound(OutboundMessage)
    │
    │  MessageBus.outbound
    ▼
BaseChannel.send(outbound)
    │
    │  平台 API 调用
    ▼
聊天平台
```

### 4.5 WorkSecret 编解码

```python
# 编码
def encode_work_secret(secret: WorkSecret) -> str:
    payload = {"v": secret.version, "token": secret.session_ingress_token, "url": secret.api_base_url}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

# 解码
def decode_work_secret(encoded: str) -> WorkSecret:
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    if payload.get("v") != 1:
        raise ValueError("Unsupported work secret version")
    return WorkSecret(version=1, session_ingress_token=payload["token"], api_base_url=payload["url"])

# SDK URL 构建
def build_sdk_url(base_url: str, session_id: str) -> str:
    # localhost / 127.0.0.1 → ws:// (本地 WebSocket)
    # 其他 → wss:// (远程 WebSocket)
    if is_local(base_url):
        return f"ws://{base_url}/ws/sdk/{session_id}"
    return f"wss://{base_url}/ws/sdk/{session_id}"
```

---

## 5. 接口规范

### 5.1 ui/app.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `run_repl` | `(bundle: RuntimeBundle, *, initial_prompt, ...) → None` | 交互模式入口, 调用 launch_react_tui |
| `run_print_mode` | `(bundle: RuntimeBundle, prompt: str, ...) → None` | 非交互模式, 流式输出到 stdout |
| `run_task_worker` | `(bundle: RuntimeBundle) → None` | 后台工作者模式, stdin 驱动 |

### 5.2 ui/runtime.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `build_runtime` | `(*, cwd, settings, ...) → RuntimeBundle` | 组装所有运行时对象 |
| `handle_line` | `(line: str, bundle: RuntimeBundle) → None` | 处理用户输入 (命令或消息) |
| `refresh_runtime_client` | `(bundle: RuntimeBundle) → RuntimeBundle` | 重建运行时 (API Client 等) |
| `_resolve_api_client_from_settings` | `(settings) → SupportsStreamingMessages` | 根据 settings 选择 API 客户端 |

### 5.3 ui/protocol.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `stream_event_to_backend_event` | `(event: StreamEvent) → BackendEvent` | StreamEvent → BackendEvent 转换 |
| `_state_payload` | `(state: AppState) → dict` | 提取前端状态快照 |

### 5.4 ui/react_launcher.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `launch_react_tui` | `(bundle, *, initial_prompt, ...) → None` | 启动 React TUI |
| `_find_frontend_dir` | `() → Path` | 查找前端目录 |
| `_resolve_tsx_command` | `(frontend_dir) → list[str]` | 解析 tsx 命令 |

### 5.5 channels/base.py

| 方法 | 签名 | 说明 |
|------|------|------|
| `start` | `async () → None` | 开始监听 |
| `stop` | `async () → None` | 停止监听 |
| `send` | `async (msg: OutboundMessage) → None` | 发送消息 |
| `receive` | `async () → InboundMessage` | 接收消息 |

### 5.6 channels/bus.py

| 方法 | 签名 | 说明 |
|------|------|------|
| `publish_inbound` | `async (msg: InboundMessage) → None` | 发布入站消息 |
| `consume_inbound` | `async () → InboundMessage` | 消费入站消息 |
| `publish_outbound` | `async (msg: OutboundMessage) → None` | 发布出站消息 |
| `consume_outbound` | `async () → OutboundMessage` | 消费出站消息 |

### 5.7 channels/bridge.py

| 方法 | 签名 | 说明 |
|------|------|------|
| `start` | `async () → None` | 启动后台循环 |
| `stop` | `async () → None` | 停止 |
| `run` | `async () → None` | 内联运行 (阻塞) |

### 5.8 bridge/manager.py

| 方法 | 签名 | 说明 |
|------|------|------|
| `spawn` | `async (*, session_id, command, cwd) → SessionHandle` | 启动桥接会话 |
| `list_sessions` | `() → list[BridgeSessionRecord]` | 列出所有会话 |
| `read_output` | `(session_id: str) → str` | 读取输出日志 |
| `stop` | `async (session_id: str) → None` | 停止会话 |

---

## 6. 错误处理

### 6.1 UI 层错误场景

| 场景 | 处理 | 恢复策略 |
|------|------|----------|
| 前端目录不存在 | 回退到 Textual TUI 或 print_mode | 降级运行 |
| npm install 失败 | 提示用户手动安装 | 降级运行 |
| tsx 命令未找到 | 尝试 npm exec 回退 | 降级运行 |
| Backend Host 崩溃 | React 进程退出, 用户看到错误 | 重新启动 |
| API 认证失败 | ErrorEvent → 前端显示错误信息 | 用户修正密钥 |
| Agent Loop 超轮次 | MaxTurnsExceeded → 前端显示 | 用户 /continue |
| 压缩连续失败 | 停止 auto-compact, 状态栏提示 | 用户手动 /compact |

### 6.2 通道层错误场景

| 场景 | 处理 | 恢复策略 |
|------|------|----------|
| 平台 SDK 连接断开 | 自动重连 (指数退避) | 透明恢复 |
| 消息发送失败 | 重试 3 次, 记录日志 | 部分丢失 |
| Agent 响应超时 | 发送超时提示给用户 | 透明 |
| 媒体下载失败 | 跳过媒体, 发送纯文本 | 降级 |
| 不支持的消息格式 | 记录日志, 忽略 | 跳过 |

### 6.3 Bridge 层错误场景

| 场景 | 处理 | 恢复策略 |
|------|------|----------|
| WorkSecret 版本不匹配 | ValueError, 拒绝连接 | 需要重新生成 |
| 会话超时 | 自动停止会话 | 重新 spawn |
| 输出日志超过 12000 字节 | 截断 | 部分保留 |
| 子进程崩溃 | 记录退出码 | 重新 spawn |

---

## 7. 配置项

### 7.1 UI 相关 Settings 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `theme` | str | "default" | TUI 主题名 |
| `output_style` | str | "default" | 输出样式 (default/minimal/codex) |
| `vim_mode` | bool | False | Vim 键绑定模式 |
| `voice_mode` | bool | False | 语音模式 |
| `fast_mode` | bool | False | 快速模式 |
| `effort` | str | "medium" | 推理强度 (low/medium/high) |
| `passes` | int | 1 | 推理轮次 |
| `verbose` | bool | False | 详细输出 |

### 7.2 通道配置 (config/schema.py)

每个通道配置模型包含:

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | bool | 是否启用 |
| `allow_from` | list[str] | 允许的用户/频道 ID |
| 通道特有字段 | 各异 | 如 Telegram: bot_token, Discord: bot_token 等 |

10种通道配置: telegram, discord, slack, whatsapp, email, feishu, dingtalk, qq, matrix, mochat

### 7.3 Bridge 配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_sessions` | int | 1 | 最大并发桥接会话 |
| `session_timeout_ms` | int | 86400000 | 会话超时 (24h) |
| `output_log_max_bytes` | int | 12000 | 输出日志最大字节 |

### 7.4 环境变量

| 变量 | 说明 |
|------|------|
| `OPENHARNESS_FRONTEND_CONFIG` | React TUI 配置 JSON (backend_command, initial_prompt, theme) |
| `TMUX` | tmux 会话检测 |
| `ITERM_SESSION_ID` | iTerm2 会话检测 |

---

## 8. 与其它模块的交互

### 8.1 UI 与其它模块

```
ui/runtime.py
  ├── config/       → load_settings(), save_settings()
  ├── auth/         → AuthManager (provider/profile 管理)
  ├── api/          → _resolve_api_client_from_settings()
  ├── mcp/          → McpClientManager
  ├── tools/        → create_default_tool_registry()
  ├── permissions/  → PermissionChecker
  ├── hooks/        → HookExecutor, HookReloader
  ├── skills/       → load_skill_registry()
  ├── memory/       → add/remove_memory_entry
  ├── prompts/      → build_runtime_system_prompt()
  ├── commands/     → CommandRegistry
  ├── sandbox/      → SandboxAvailability
  ├── state/        → AppStateStore (TUI 状态管理)
  ├── services/     → SessionBackend (会话持久化)
  ├── swarm/        → BackendRegistry (多 Agent 后端)
  └── tasks/        → BackgroundTaskManager
```

### 8.2 通道与其它模块

```
channels/bridge.py
  └── engine/       → QueryEngine.submit_message() (核心处理)

channels/telegram.py 等
  └── 各平台 SDK    → python-telegram-bot, discord.py, slack-sdk 等
```

### 8.3 Bridge 与其它模块

```
bridge/manager.py
  └── tasks/         → BackgroundTaskManager (会话生命周期)
  └── utils/shell   → create_shell_subprocess (启动桥接进程)
```

### 8.4 10 种 Channel 实现对比

| Channel | 协议 | 依赖 SDK | 特点 |
|---------|------|----------|------|
| Telegram | Bot API (长轮询) | python-telegram-bot | 最成熟的通道 |
| Discord | Gateway | discord.py | 实时消息 |
| Slack | Events API | slack-sdk | 企业场景 |
| WhatsApp | Web API | 无官方 SDK | 非官方接口 |
| Email | SMTP/IMAP | stdlib | 异步通信 |
| Feishu | 开放平台 API | httpx | 中国企业 |
| DingTalk | 机器人 Webhook | httpx | 简单通知 |
| QQ | QQ 机器人 API | httpx | 社区 |
| Matrix | Matrix 协议 | matrix-nio | 去中心化 |
| MoChat | MoChat API | httpx | 内部通信 |

### 8.5 三种运行模式的完整交互

```
┌──────────────────────────────────────────────────────────────┐
│  交互模式 (run_repl)                                          │
│                                                              │
│  React TUI ◄──stdin/stdout JSON──► Backend Host              │
│     │                                │                       │
│     │ FrontendRequest                │ BackendEvent          │
│     │ (submit_line, ...)             │ (assistant_delta, ...)│
│     │                                │                       │
│     │    ┌───────────────────────────┤                       │
│     │    │ handle_line()             │                       │
│     │    │  ├── /command → CommandReg│                       │
│     │    │  └── message → QueryEng  │                       │
│     │    │       └── Agent Loop      │                       │
│     │    └───────────────────────────┤                       │
│     │                                │                       │
│     │ AppStateStore ←── set() ──────┘                       │
│     │ (subscribe → 重新渲染)                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  非交互模式 (run_print_mode)                                  │
│                                                              │
│  stdout ←── StreamEvent (直接输出)                            │
│  无 TUI, 无交互, 适合管道/pipeline                            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  通道模式 (ChannelBridge)                                     │
│                                                              │
│  平台 SDK → InboundMessage → MessageBus → QueryEngine         │
│  QueryEngine → OutboundMessage → MessageBus → 平台 SDK       │
│                                                              │
│  支持多平台并发, 每个 chat_id 独立会话                         │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  桥接模式 (Bridge)                                            │
│                                                              │
│  ohmo Web → WorkSecret → BridgeSessionManager → Agent Worker  │
│  Worker 输出 → 输出日志 (12000 字节上限)                      │
│  WebSocket: ws:// (本地) / wss:// (远程)                      │
└──────────────────────────────────────────────────────────────┘
```