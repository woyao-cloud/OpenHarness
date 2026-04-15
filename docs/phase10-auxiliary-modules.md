# Phase 10: 辅助模块速览

> 涵盖 14 个辅助模块, 共 ~4500 行代码
> 目标: 了解每个模块的职责和核心导出, 需要时能快速定位

---

## 模块总览

| 模块 | 文件数 | 行数 | 核心概念 | 复杂度 |
|------|--------|------|----------|--------|
| `bridge/` | 5 | 450 | 会话桥接 (ohmo 用) | ★★ |
| `channels/` | 14 | 1000 | 消息通道 (10 平台) | ★★★ |
| `coordinator/` | 3 | 450 | Agent 定义与团队注册 | ★★ |
| `tasks/` | 6 | 480 | 后台任务管理 | ★★ |
| `mcp/` | 4 | 500 | MCP 客户端 | ★★★ |
| `sandbox/` | 6 | 450 | 沙箱隔离 | ★★★ |
| `themes/` | 4 | 200 | 主题配置 | ★ |
| `keybindings/` | 5 | 150 | 快捷键 | ★ |
| `output_styles/` | 2 | 60 | 输出样式 | ★ |
| `vim/` | 2 | 35 | Vim 模式 | ★ |
| `voice/` | 4 | 200 | 语音输入 | ★★ |
| `state/` | 3 | 100 | 应用状态 | ★ |
| `utils/` | 5 | 280 | 工具函数 | ★★ |

---

## 1. Bridge — 会话桥接

**职责**: 为 ohmo (OpenHarness 的 Web 扩展) 提供 Worker 会话管理。

### 核心类型

```python
@dataclass(frozen=True)
class WorkSecret:          # 编码后的会话令牌
    version: int           # 版本号 (必须为 1)
    session_ingress_token: str  # 会话入口 Token
    api_base_url: str      # API 基础 URL

@dataclass(frozen=True)
class BridgeConfig:        # 桥接配置
    dir: str               # 工作目录
    machine_name: str      # 机器名
    max_sessions: int = 1  # 最大并发会话
    session_timeout_ms: int = 24h  # 会话超时
```

### 关键函数

| 函数 | 用途 |
|------|------|
| `encode_work_secret(secret)` | 编码为 base64url JSON |
| `decode_work_secret(secret)` | 解码并验证版本 |
| `build_sdk_url(base_url, session_id)` | 构建 WebSocket 入口 URL (本地 ws://, 远程 wss://) |

### BridgeSessionManager

```python
class BridgeSessionManager:
    async def spawn(*, session_id, command, cwd) → SessionHandle  # 启动桥接会话
    def list_sessions() → list[BridgeSessionRecord]               # 列出所有会话
    def read_output(session_id) → str                              # 读取输出日志
    async def stop(session_id)                                     # 停止会话
```

**输出日志**: 写入 `~/.openharness/data/bridge/<session_id>.log`, 最多 12000 字节。

---

## 2. Channels — 消息通道

**职责**: 将 10 种聊天平台的消息桥接到 Agent。

### 架构

```
聊天平台 (Telegram/Discord/Slack/...)
  │
  │  InboundMessage
  ▼
MessageBus ──── asyncio.Queue 双队列
  │
  │  InboundMessage → consume_inbound()
  ▼
ChannelBridge ──── 连接 MessageBus 与 QueryEngine
  │
  │  QueryEngine.submit_message()
  ▼
Agent 处理 → OutboundMessage → publish_outbound()
  │
  ▼
聊天平台 (通过各 Channel 实现)
```

### 消息模型

```python
@dataclass
class InboundMessage:          # 平台 → Agent
    channel: str               # "telegram" / "discord" / "slack" 等
    sender_id: str             # 用户 ID
    chat_id: str               # 聊天/频道 ID
    content: str               # 消息文本
    timestamp: datetime        # 时间戳
    media: list[str]           # 媒体 URL
    metadata: dict             # 平台特定数据
    session_key_override: str  # 会话键覆盖

@dataclass
class OutboundMessage:        # Agent → 平台
    channel: str
    chat_id: str
    content: str
    reply_to: str | None       # 回复目标
    media: list[str]
    metadata: dict
```

### MessageBus — 异步消息队列

```python
class MessageBus:
    inbound: asyncio.Queue[InboundMessage]   # 平台 → Agent
    outbound: asyncio.Queue[OutboundMessage]   # Agent → 平台
    
    async def publish_inbound(msg)   # 平台发布用户消息
    async def consume_inbound()     # Agent 消费用户消息
    async def publish_outbound(msg) # Agent 发布回复
    async def consume_outbound()    # 平台消费回复
```

### ChannelBridge — 核心桥接

```python
class ChannelBridge:
    def __init__(*, engine: QueryEngine, bus: MessageBus)
    async def start()  # 启动后台循环
    async def stop()   # 停止
    async def run()    # 内联运行 (阻塞)
```

**工作方式**: 循环消费 inbound → `engine.submit_message()` → 流式收集响应 → 发布 outbound。

### 10 种 Channel 实现

| Channel | 文件 | 协议 |
|---------|------|------|
| Telegram | `telegram.py` | Bot API (长轮询) |
| Discord | `discord.py` | Bot Gateway |
| Slack | `slack.py` | RTM / Events API |
| WhatsApp | `whatsapp.py` | Web API |
| Email | `email.py` | SMTP/IMAP |
| Feishu (飞书) | `feishu.py` | 开放平台 API |
| DingTalk (钉钉) | `dingtalk.py` | 机器人 Webhook |
| QQ | `qq.py` | QQ 机器人 API |
| Matrix | `matrix.py` | Matrix 协议 |
| MoChat | `mochat.py` | MoChat API |

所有 Channel 实现 `BaseChannel(ABC)` 接口:

```python
class BaseChannel(ABC):
    name: str
    
    @abstractmethod async def start()        # 开始监听
    @abstractmethod async def stop()         # 停止
    @abstractmethod async def send(msg)     # 发送消息
    @abstractmethod async def receive()      # 接收消息
```

---

## 3. Coordinator — Agent 编排

**职责**: Agent 定义加载与团队注册。

### AgentDefinition — Agent 配置

```python
class AgentDefinition(BaseModel):
    name: str                    # Agent 类型名
    description: str             # whenToUse 描述
    system_prompt: str | None    # 自定义系统提示词
    tools: list[str] | None      # 允许的工具 (None = 全部)
    disallowed_tools: list[str]   # 禁止的工具
    skills: list[str]            # 订阅的 Skill
    mcp_servers: list[str]       # 订阅的 MCP 服务器
    hooks: dict | None           # Agent 级 Hook
    color: str | None            # UI 颜色 (red/green/blue/...)
    model: str | None            # 模型覆盖
    effort: str | None           # low/medium/high
    permission_mode: str | None  # default/plan/bypassPermissions 等
    max_turns: int | None       # 最大轮次
    memory_scope: str            # user/project/local
    isolation: str | None        # worktree/remote
    # ... 更多字段
```

**加载来源**: `~/.openharness/agents/*.yaml` — YAML 格式的 Agent 定义文件。

### TeamRegistry — 内存团队注册

```python
class TeamRegistry:
    def create_team(name, description) → TeamRecord
    def delete_team(name)
    def add_agent(team_name, task_id)
    def send_message(team_name, message)
    def list_teams() → list[TeamRecord]
```

**注意**: `TeamRegistry` 是内存中的轻量注册, 持久化版本在 `swarm/team_lifecycle.py` 的 `TeamFile`。

---

## 4. Tasks — 后台任务管理

**职责**: 管理 Shell 和 Agent 子进程任务。

### TaskRecord — 任务数据

```python
TaskType = Literal["local_bash", "local_agent", "remote_agent", "in_process_teammate"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]

@dataclass
class TaskRecord:
    id: str                     # 唯一 ID
    type: TaskType              # 类型
    status: TaskStatus          # 状态
    description: str            # 描述
    cwd: str                    # 工作目录
    output_file: Path           # 输出日志路径
    command: str | None         # Shell 命令
    prompt: str | None          # Agent 提示词
    created_at: float           # 创建时间
    started_at: float | None    # 启动时间
    ended_at: float | None     # 结束时间
    return_code: int | None     # 退出码
    metadata: dict[str, str]    # 额外元数据
```

### BackgroundTaskManager

```python
class BackgroundTaskManager:
    async def create_shell_task(*, command, description, cwd) → TaskRecord
    async def create_agent_task(*, prompt, description, cwd, model, ...) → TaskRecord
    def list_tasks() → list[TaskRecord]
    def get_task(task_id) → TaskRecord | None
    def read_task_output(task_id) → str
    async def stop_task(task_id) → TaskRecord
    def update_task(task_id, **kwargs) → TaskRecord
```

**输出日志**: `~/.openharness/data/tasks/<task_id>.log`

**Agent 任务**: 启动 `python -m openharness --api-key <key>` 子进程, 通过 stdin 传递提示词。

---

## 5. MCP — Model Context Protocol

**职责**: 连接外部 MCP 服务器, 暴露工具和资源给 Agent。

### 服务器配置类型

```python
class McpStdioServerConfig(BaseModel):   # stdio 传输
    type: Literal["stdio"] = "stdio"
    command: str                         # 启动命令
    args: list[str]                      # 参数
    env: dict[str, str] | None           # 环境变量
    cwd: str | None                      # 工作目录

class McpHttpServerConfig(BaseModel):    # HTTP 传输
    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str]

class McpWebSocketServerConfig(BaseModel):  # WebSocket 传输
    type: Literal["ws"] = "ws"
    url: str
    headers: dict[str, str]

McpServerConfig = McpStdioServerConfig | McpHttpServerConfig | McpWebSocketServerConfig
```

### 运行时状态

```python
@dataclass(frozen=True)
class McpToolInfo:                    # MCP 工具元数据
    server_name: str
    name: str
    description: str
    input_schema: dict[str, object]

@dataclass
class McpConnectionStatus:           # 连接状态
    name: str
    state: "connected" | "failed" | "pending" | "disabled"
    detail: str
    transport: str
    auth_configured: bool
    tools: list[McpToolInfo]
    resources: list[McpResourceInfo]
```

### McpClientManager

```python
class McpClientManager:
    async def connect_all()                  # 连接所有配置的服务器
    async def reconnect_all()               # 重连所有
    async def close()                        # 关闭所有
    def update_server_config(name, config)   # 更新配置
    async def call_tool(name, arguments)     # 调用工具
    async def read_resource(uri)             # 读取资源
    def list_tools() → list[McpToolInfo]     # 列出所有工具
```

**SDK**: 使用 `mcp` Python SDK (`ClientSession`, `stdio_client`, `streamable_http_client`)。

**动态工具注册**: `McpToolInfo.input_schema` → `tools/mcp_tool.py` 动态生成 Pydantic 模型 → 注册到 ToolRegistry。

---

## 6. Sandbox — 沙箱隔离

**职责**: 在隔离环境中执行工具, 防止对宿主系统的未授权访问。

### 两种后端

| 后端 | 实现 | 依赖 | 平台 |
|------|------|------|------|
| `srt` (sandbox-runtime) | `adapter.py` | `srt` CLI + `bwrap`(Linux)/`sandbox-exec`(macOS) | Linux, macOS, WSL |
| `docker` | `docker_backend.py` | Docker Engine | 所有平台 |

### SandboxAvailability 检测

```python
@dataclass(frozen=True)
class SandboxAvailability:
    enabled: bool      # 设置中启用
    available: bool    # 运行时可用
    reason: str | None # 不可用原因
    command: str | None # srt/docker 命令路径
    
    @property
    def active(self) -> bool:
        return self.enabled and self.available
```

**不可用原因**:
- Windows: "sandbox runtime 不支持原生 Windows, 用 WSL"
- `srt` 未安装: "npm install -g @anthropic-ai/sandbox-runtime"
- Linux/WSL 缺 `bwrap`: "apt install bubblewrap"
- macOS 缺 `sandbox-exec`: 较少见
- Docker 未运行: "Docker daemon is not running"

### 命令包装

```python
def wrap_command_for_sandbox(command, *, settings) -> tuple[list[str], Path | None]:
    """将命令包装在 srt 中执行"""
    # 1. 检查后端类型 (docker → 不包装, 直接返回)
    # 2. 检查 srt 可用性
    # 3. 写临时配置文件 (network/filesystem 规则)
    # 4. 返回: ["srt", "--settings", path, "-c", joined_command]
```

### 沙箱配置

```python
def build_sandbox_runtime_config(settings):
    return {
        "network": {
            "allowedDomains": settings.sandbox.network.allowed_domains,
            "deniedDomains": settings.sandbox.network.denied_domains,
        },
        "filesystem": {
            "allowRead": settings.sandbox.filesystem.allow_read,
            "denyRead": settings.sandbox.filesystem.deny_read,
            "allowWrite": settings.sandbox.filesystem.allow_write,
            "denyWrite": settings.sandbox.filesystem.deny_write,
        },
    }
```

### 路径验证

```python
def validate_sandbox_path(path, cwd, extra_allowed=None) → tuple[bool, str]:
    """验证路径是否在沙箱边界内"""
    # 1. 主检查: path 必须在 cwd 内
    # 2. 次检查: path 在 extra_allowed 列表内
    # 3. 否则: 拒绝
```

### Docker 沙箱会话

```python
async def start_docker_sandbox(settings, session_id, cwd)  # 启动容器
async def stop_docker_sandbox()                              # 停止容器
def is_docker_sandbox_active() → bool                       # 检查状态
```

**安全网**: `atexit.register(session.stop_sync)` — 进程退出时自动停止容器。

---

## 7. Themes — 主题配置

**职责**: TUI 的颜色、边框、图标、布局配置。

### ThemeConfig Schema

```python
class ColorsConfig(BaseModel):
    primary: str = "#5875d4"     # 主色
    secondary: str = "#4a9eff"   # 辅色
    accent: str = "#61afef"      # 强调色
    error: str = "#e06c75"       # 错误色
    muted: str = "#5c6370"       # 弱化色
    background: str = "#282c34"  # 背景色
    foreground: str = "#abb2bf"  # 前景色

class BorderConfig(BaseModel):
    style: "rounded"|"single"|"double"|"none" = "rounded"

class IconConfig(BaseModel):
    spinner: str = "⠋"           # 加载动画
    tool: str = "⚙"             # 工具图标
    error: str = "✖"            # 错误图标
    success: str = "✔"          # 成功图标
    agent: str = "◆"            # Agent 图标

class LayoutConfig(BaseModel):
    compact: bool = False        # 紧凑布局
    show_tokens: bool = True    # 显示 Token
    show_time: bool = True     # 显示时间

class ThemeConfig(BaseModel):
    name: str
    colors: ColorsConfig
    borders: BorderConfig
    icons: IconConfig
    layout: LayoutConfig
```

**加载来源**: 内置 + `~/.openharness/themes/*.json`

---

## 8. Keybindings — 快捷键

**职责**: 加载和解析自定义键盘快捷键。

| 文件 | 职责 |
|------|------|
| `default_bindings.py` | 默认快捷键定义 |
| `parser.py` | 快捷键格式解析 |
| `resolver.py` | 合并默认 + 用户自定义 |
| `loader.py` | 从配置文件加载 |

**配置路径**: `~/.openharness/keybindings.json`

---

## 9. Output Styles — 输出样式

**职责**: 控制 Agent 输出的渲染风格。

```python
@dataclass(frozen=True)
class OutputStyle:
    name: str       # "default" / "minimal" / "codex"
    content: str    # 样式指令 (Markdown)
    source: str     # "builtin" / "user"

# 内置样式:
# default: 标准 rich 控制台输出
# minimal: 极简纯文本
# codex:  Codex 风格紧凑输出 (减少流式闪烁)
```

**自定义**: `~/.openharness/output_styles/*.md`

---

## 10. Vim — Vim 模式

**职责**: TUI 的 Vim 键绑定模式。

| 文件 | 职责 |
|------|------|
| `transitions.py` | Vim 模式状态机 (Normal → Insert → Visual 等) |

**最简单的模块** — 只有 35 行, 实现模式切换的状态转换。

---

## 11. Voice — 语音输入

**职责**: 语音转文字输入支持。

### VoiceDiagnostics

```python
@dataclass(frozen=True)
class VoiceDiagnostics:
    available: bool          # 是否可用
    reason: str              # 不可用原因
    recorder: str | None     # 录音器 (sox/ffmpeg/arecord)
```

### 可用性检测

```python
def inspect_voice_capabilities(provider: ProviderInfo) -> VoiceDiagnostics:
    # 1. 检查 Provider 是否支持语音 (当前全部 False)
    # 2. 检查录音器: sox → ffmpeg → arecord
    # 3. 返回诊断结果
```

### 附加文件

| 文件 | 职责 |
|------|------|
| `keyterms.py` | 从文本提取关键词 (用于语音命令) |
| `stream_stt.py` | 流式语音转文字 (STT) |

**当前状态**: 所有 Provider 的 `voice_supported = False`, 语音功能尚未完整实现。

---

## 12. State — 应用状态

**职责**: 可观察的 UI 状态存储。

### AppState — 状态模型

```python
@dataclass
class AppState:
    model: str               # 当前模型
    permission_mode: str      # 权限模式
    theme: str                # 主题名
    cwd: str                  # 工作目录
    provider: str             # Provider 名
    auth_status: str          # 认证状态
    base_url: str             # API 基础 URL
    vim_enabled: bool         # Vim 模式
    voice_enabled: bool       # 语音模式
    voice_available: bool     # 语音可用
    voice_reason: str         # 不可用原因
    fast_mode: bool           # 快速模式
    effort: str               # 推理强度
    passes: int               # 推理轮次
    mcp_connected: int        # MCP 已连接数
    mcp_failed: int           # MCP 失败数
    bridge_sessions: int      # 桥接会话数
    output_style: str         # 输出样式
    keybindings: dict         # 快捷键映射
```

### AppStateStore — 观察者模式

```python
class AppStateStore:
    def __init__(self, initial_state: AppState)
    def get(self) → AppState                    # 获取当前状态
    def set(self, **updates) → AppState         # 更新状态 + 通知监听器
    def subscribe(self, listener) → callable    # 注册监听器, 返回取消函数
```

**使用**: TUI 层监听状态变化, 自动重新渲染。命令处理器通过 `context.app_state.set()` 更新。

---

## 13. Utils — 工具函数

### fs.py — 原子文件写入

```python
def atomic_write_bytes(path, data, *, mode=None):
    """原子写入: temp file + fsync + os.replace"""
    # 1. 同目录创建临时文件 (.name.tmp)
    # 2. 写入 + flush + fsync
    # 3. 设置 POSIX mode
    # 4. os.replace (原子替换)
    # 5. 失败时清理临时文件

def atomic_write_text(path, data, *, encoding="utf-8", mode=None):
    """文本变体"""
```

**核心保证**: 任何时刻, 读者看到的要么是完整的旧文件, 要么是完整的新文件, 不会看到半写的文件。

### file_lock.py — 跨平台文件锁

```python
@contextmanager
def exclusive_file_lock(lock_path):
    """获取独占文件锁"""
    # POSIX: fcntl.flock(fd, LOCK_EX) / LOCK_UN
    # Windows: msvcrt.locking(fd, LK_LOCK, 1) / LK_UNLCK
```

**用途**: 序列化并发读写 (credentials.json, settings.json, memory 等)。

**与 `atomic_write_text` 配合**: `exclusive_file_lock` + `atomic_write_text` = 无竞争 + 无崩溃丢失。

### shell.py — Shell 子进程

```python
def resolve_shell_command(command, *, platform_name=None, prefer_pty=False):
    """解析最优 Shell 命令"""
    # Windows: bash → pwsh → cmd.exe
    # POSIX: bash → $SHELL → /bin/sh
    # prefer_pty: 用 script 命令包装 (伪终端)

async def create_shell_subprocess(command, *, cwd, settings=None, ...):
    """创建 Shell 子进程 (可能包装沙箱)"""
    # 1. resolve_shell_command()
    # 2. wrap_command_for_sandbox() (如果启用)
    # 3. asyncio.create_subprocess_exec()
```

### network_guard.py — 网络安全守卫

```python
def validate_http_url(url):
    """验证 HTTP/HTTPS URL 语法"""
    # 拒绝非 http/https
    # 拒绝嵌入凭据 (user:pass@host)
    # 拒绝缺少主机名

async def ensure_public_http_url(url):
    """拒绝回环/私有网络地址"""
    # DNS 解析目标主机
    # 检查每个 IP: is_global? → 非全局 IP 拒绝
    # 防止 SSRF 攻击 (127.0.0.1, 10.x, 192.168.x, etc.)

async def fetch_public_http_response(url, *, headers, params, timeout, max_redirects):
    """安全获取 HTTP 资源"""
    # 逐跳验证每个重定向目标
    # 最多 5 次重定向
    # 每跳都检查 ensure_public_http_url
```

**SSRF 防护**: 通过 DNS 解析后检查 IP 地址是否为全局地址, 防止攻击者通过 URL 访问内网服务。

---

## 14. 全项目关键工具函数速查

| 函数 | 所在 | 用途 |
|------|------|------|
| `atomic_write_text()` | `utils/fs.py` | 崩溃安全写文件 |
| `exclusive_file_lock()` | `utils/file_lock.py` | 并发安全读-改-写 |
| `create_shell_subprocess()` | `utils/shell.py` | 创建沙箱子进程 |
| `validate_http_url()` | `utils/network_guard.py` | URL 安全验证 |
| `ensure_public_http_url()` | `utils/network_guard.py` | SSRF 防护 |
| `wrap_command_for_sandbox()` | `sandbox/adapter.py` | 命令沙箱包装 |
| `estimate_tokens()` | `services/token_estimation.py` | Token 估算 |
| `encode_work_secret()` | `bridge/work_secret.py` | 会话令牌编码 |
| `detect_provider()` | `api/provider.py` | Provider 自动检测 |
| `discover_claude_md_files()` | `prompts/claudemd.py` | CLAUDE.md 发现 |
| `find_relevant_memories()` | `memory/search.py` | 记忆搜索 |
| `sanitize_name()` | `swarm/team_lifecycle.py` | Agent 名清理 |

---

## 15. 配置文件目录树

```
~/.openharness/
├── settings.json              ← 全局设置
├── credentials.json           ← API Key 存储 (mode 600)
├── local_rules/
│   ├── rules.md               ← 自动提取的环境规则
│   └── facts.json             ← 环境事实数据库
├── skills/                    ← 用户 Skill
│   └── <skill-name>/SKILL.md
├── themes/                    ← 自定义主题
│   └── <theme-name>.json
├── keybindings.json           ← 快捷键
├── output_styles/             ← 自定义输出样式
│   └── <style-name>.md
├── agents/                    ← Agent 定义
│   └── <agent-name>.yaml
├── data/
│   ├── memory/<project-hash>/  ← 项目记忆
│   ├── sessions/<project-hash>/ ← 会话快照
│   ├── tasks/                  ← 任务输出日志
│   ├── bridge/                 ← 桥接会话日志
│   ├── media/                  ← 通道媒体下载
│   └── feedback.log            ← 反馈日志
└── teams/
    └── <team-name>/
        ├── team.json           ← 团队状态
        ├── agents/<id>/inbox/  ← 邮箱
        └── permissions/
            ├── pending/        ← 待审批权限
            └── resolved/       ← 已审批权限
```

---

## 16. 安全机制汇总

| 层级 | 机制 | 模块 |
|------|------|------|
| **网络** | SSRF 防护 (DNS 解析 + 私有 IP 拒绝) | `utils/network_guard.py` |
| **网络** | 沙箱网络白名单/黑名单 | `sandbox/adapter.py` |
| **文件** | 沙箱路径边界验证 | `sandbox/path_validator.py` |
| **文件** | 原子写 (防崩溃丢失) | `utils/fs.py` |
| **文件** | 文件锁 (防并发竞争) | `utils/file_lock.py` |
| **文件** | credentials.json mode 600 | `auth/storage.py` |
| **凭据** | Keyring 优先 (OS 级加密) | `auth/storage.py` |
| **凭据** | XOR 混淆 (非加密, 仅防偶然读取) | `auth/storage.py` |
| **权限** | 9 级决策链 + 敏感路径保护 | `permissions/checker.py` |
| **权限** | Worker → Leader 权限审批 | `swarm/permission_sync.py` |
| **Agent** | 只读工具白名单 (无需审批) | `swarm/permission_sync.py` |
| **Agent** | Git Worktree 隔离 | `swarm/worktree.py` |
| **Agent** | Plan Mode 限制 | `swarm/types.py` |
| **URL** | http/https only, 无嵌入凭据 | `utils/network_guard.py` |
| **Memory** | 路径 slug 化防遍历 | `memory/manager.py` |
| **Memory** | 路径边界验证 (resolve + relative_to) | `commands/registry.py` |