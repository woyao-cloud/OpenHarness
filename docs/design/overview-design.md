# OpenHarness 概要设计文档

> 版本: 1.0 | 日期: 2026-04-15

---

## 1. 系统概述

### 1.1 项目定位

OpenHarness 是一个开源的 AI 编程助手命令行基础设施, 提供多模型、多 Provider 的 Agent 运行时, 支持工具调用、多 Agent 协作、上下文压缩、多通道接入等能力。

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.12+ (类型提示, dataclass, async/await) |
| CLI 框架 | Typer + Click |
| 数据模型 | Pydantic v2 (验证 + Schema 生成) |
| 异步 | asyncio (EventLoop, Task, Queue) |
| HTTP | httpx (异步 HTTP 客户端) |
| API SDK | anthropic, openai (官方 Python SDK) |
| TUI 前端 | React + Ink (Node.js tsx) |
| 文件 I/O | 原子写 (tempfile + os.replace), fcntl/msvcrt 文件锁 |
| 包管理 | uv / pip |

### 1.3 规模统计

| 指标 | 数值 |
|------|------|
| Python 文件 | ~177 |
| 代码行数 | ~19,400 |
| 模块数 | 29 |
| 内置工具 | 36+ |
| 斜杠命令 | ~50 |
| 测试文件 | 92 |
| API 客户端 | 4 种 |

---

## 2. 架构总览

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────┐
│                    CLI 层                            │
│  __main__.py → cli.py → main() → run_repl()        │
├─────────────────────────────────────────────────────┤
│                    UI 层                             │
│  React TUI (Ink) ←──→ Backend Host ←──→ Textual     │
│  stdin/stdout JSON 协议                             │
├─────────────────────────────────────────────────────┤
│                   引擎层                             │
│  QueryEngine → run_query() → Agent Loop             │
│  消息模型 · 事件流 · 状态携带 · 自动压缩            │
├──────────┬──────────┬──────────┬─────────────────────┤
│ 工具系统  │ API 客户端 │ 权限系统  │ Hook 系统        │
│ BaseTool  │ Supports  │ Permission│ HookExecutor     │
│ Registry  │ Streaming │ Checker  │ HookRegistry      │
│ 36+ Tools │ Messages  │ 9级决策链 │ 4种Hook类型      │
├──────────┴──────────┴──────────┴─────────────────────┤
│                  服务层                              │
│  上下文压缩 · 会话持久化 · Cron调度 · Token估算      │
├─────────────────────────────────────────────────────┤
│                知识与记忆层                           │
│  Skills · Memory · CLAUDE.md · Personalization       │
│  系统提示词组装 (11 个 Section)                      │
├─────────────────────────────────────────────────────┤
│               命令与扩展层                            │
│  CommandRegistry · MCP · Swarm · Channels · Bridge  │
└─────────────────────────────────────────────────────┘
```

### 2.2 核心运行时对象组装

`build_runtime()` (ui/runtime.py) 是所有运行模式的共享组装点:

```
build_runtime()
  ├── load_settings()                  → 加载 ~/.openharness/settings.json
  ├── load_plugins()                   → 发现并加载插件
  ├── _resolve_api_client()            → 根据 provider 创建 API 客户端
  ├── McpClientManager()               → MCP 服务器管理器
  ├── create_default_tool_registry()   → 注册 36+ 工具
  ├── PermissionChecker()              → 权限检查器
  ├── build_runtime_system_prompt()     → 组装系统提示词
  ├── QueryEngine()                    → 核心引擎
  └── RuntimeBundle()                  → 打包所有运行时对象
```

**RuntimeBundle** 是运行时会话的"上帝对象", 持有所有子系统引用: api_client, engine, tool_registry, mcp_manager, permission_checker, hook_executor, commands, app_state, session_backend 等。

---

## 3. 模块依赖图

### 3.1 29 个模块总览

```
核心引擎:
  engine/          ← 消息模型、事件流、Agent Loop (query.py, query_engine.py)

API与认证:
  api/             ← 4种API客户端 + Provider检测 + 错误层级
  auth/            ← 认证管理 + 3种认证流 + 凭证存储 (Keyring/文件双后端)

工具系统:
  tools/           ← BaseTool + 36+ 工具实现 + MCP动态工具

配置与权限:
  config/          ← Settings (870行) + 路径约定 + Schema
  permissions/     ← PermissionMode + PermissionChecker (9级决策链)

Hook与命令:
  hooks/           ← 4种Hook类型 + 执行引擎 + 热重载
  commands/        ← ~50个斜杠命令 + CommandRegistry

知识与记忆:
  skills/          ← Skill定义 + 加载 + 注册
  memory/          ← 项目级持久记忆 + 搜索
  prompts/         ← 系统提示词组装 + 环境信息 + CLAUDE.md
  personalization/  ← 自动环境事实提取 + 持久化

Swarm与服务:
  swarm/           ← 多Agent协作 (4种后端 + 邮箱 + 权限同步)
  services/        ← 上下文压缩 (1581行) + 会话持久化 + Cron + Token估算

UI与通道:
  ui/              ← React TUI + Backend Host + 通信协议
  channels/        ← 10种聊天平台通道
  bridge/          ← 会话桥接 (ohmo用)

辅助模块:
  coordinator/     ← Agent定义 + 团队注册
  tasks/           ← 后台任务管理 (5种类型/状态)
  mcp/             ← MCP客户端 (3种传输协议)
  sandbox/         ← 沙箱隔离 (srt + Docker)
  themes/          ← TUI主题配置
  keybindings/     ← 快捷键
  output_styles/   ← 输出样式
  vim/             ← Vim模式
  voice/           ← 语音输入
  state/           ← 应用状态 (观察者模式)
  utils/           ← 原子写 + 文件锁 + Shell + SSRF防护
  platforms/       ← 平台检测
```

### 3.2 模块依赖关系

```
cli ─→ ui/runtime ─→ engine ─→ api, tools, permissions, hooks, services
                  ─→ skills, memory, prompts, personalization
                  ─→ commands ─→ config, auth
                  ─→ swarm ─→ tasks, mcp
                  ─→ channels ─→ engine
                  ─→ bridge ─→ tasks
                  ─→ sandbox ─→ config
                  ─→ state ─→ ui
                  ─→ utils (被所有模块使用)
```

**utils 是基础设施层**: atomic_write_text, exclusive_file_lock, create_shell_subprocess, network_guard 被 config, auth, memory, sandbox, tools, hooks 等广泛依赖。

---

## 4. 核心数据流

### 4.1 主请求流: 用户输入 → Agent 回复

```
用户输入 "读取 main.py"
    │
    ▼
handle_line() [ui/runtime.py]
    ├── 检查斜杠命令 → 否
    ├── build_runtime_system_prompt() → 组装11个Section
    │   ├── BASE_SYSTEM_PROMPT + 环境信息
    │   ├── Fast Mode / Reasoning Settings
    │   ├── Skills 列表
    │   ├── Delegation 指南
    │   ├── CLAUDE.md (向上遍历发现)
    │   ├── Local Rules (自动环境事实)
    │   ├── Issue / PR Context
    │   └── Memory Index + Relevant Memories (关键词搜索)
    │
    ▼
QueryEngine.submit_message("读取 main.py")
    ├── 记录用户目标 → tool_metadata["task_focus_state"]
    ├── 构造 ConversationMessage(role="user", content=[TextBlock])
    ├── 打包 QueryContext (无状态上下文)
    │
    ▼
run_query(context, messages) [engine/query.py]
    │
    ├── [Turn 1] auto-compact检查 (首次不触发)
    ├── api_client.stream_message(request) → 流式API调用
    │   ├── ApiTextDeltaEvent → yield AssistantTextDelta (UI实时渲染)
    │   └── ApiMessageCompleteEvent → 拿到 final_message
    │       → 包含: TextBlock("我来读取") + ToolUseBlock(name="read_file", input={...})
    ├── yield AssistantTurnComplete
    │
    ├── 检测到 tool_uses → 进入工具执行管道
    │   ├── PreToolUse Hook → 未阻断
    │   ├── tool_registry.get("read_file") → FileReadTool
    │   ├── tool.input_model.model_validate(input) → Pydantic验证
    │   ├── permission_checker.evaluate(tool="read_file", is_read_only=True) → 允许
    │   ├── tool.execute(parsed_input, context) → ToolResult(output="1: import os...")
    │   ├── _record_tool_carryover() → 更新 read_file_state, active_artifacts, work_log
    │   └── PostToolUse Hook
    │
    ├── yield ToolExecutionStarted / ToolExecutionCompleted
    ├── 追加工具结果 → ConversationMessage(role="user", content=[ToolResultBlock])
    │
    ▼
    ├── [Turn 2] API调用 → 模型看到文件内容 → TextBlock("这个文件是...")
    ├── 没有 tool_uses → return (循环结束)
    │
    ▼
返回 QueryEngine → 更新messages, 累加cost → 保存会话快照
```

### 4.2 Agent Loop 伪代码

```python
async def run_query(context, messages):
    turn_count = 0
    while turn_count < context.max_turns:
        # ① 自动压缩检查
        if should_autocompact(messages):
            messages = await compact(messages)

        # ② 流式API调用
        async for event in api_client.stream_message(request):
            if isinstance(event, ApiTextDeltaEvent):
                yield AssistantTextDelta(event.text)
            elif isinstance(event, ApiMessageCompleteEvent):
                final_message = event.message
                usage = event.usage

        # ③ 错误/空消息保护
        if error or empty_message:
            yield ErrorEvent; return

        # ④ 记录助手回复
        messages.append(final_message)
        yield AssistantTurnComplete

        # ⑤ 无工具调用 → 退出
        if not final_message.tool_uses:
            return

        # ⑥ 执行工具
        if len(tool_calls) == 1:
            # 单工具: 顺序执行, 实时流式事件
            result = await _execute_tool_call(context, tool_calls[0])
        else:
            # 多工具: asyncio.gather并行, return_exceptions=True
            results = await asyncio.gather(*[_execute_tool_call(tc) for tc in tool_calls])

        # ⑦ 追加工具结果
        messages.append(ConversationMessage(role="user", content=tool_results))

        turn_count += 1
```

### 4.3 工具执行管道 (5道关卡)

```
_execute_tool_call()
  ├── ① PreToolUse Hook → 可能阻断
  ├── ② 工具查找 → tool_registry.get(name)
  ├── ③ 输入验证 → Pydantic model_validate
  ├── ④ 权限检查 → permission_checker.evaluate()
  │   ├── allowed → 执行
  │   ├── requires_confirmation → 弹确认框
  │   └── denied → 返回 ToolResultBlock(is_error=True)
  ├── ⑤ 工具执行 → tool.execute(parsed_input, context)
  ├── ⑥ 状态携带 → _record_tool_carryover()
  └── ⑦ PostToolUse Hook
```

任何关卡失败都返回 `is_error=True` 的 ToolResultBlock, 而不是抛异常 — 保证对话历史完整性。

---

## 5. 关键设计决策

### 5.1 Protocol 模式 (鸭子类型接口)

`SupportsStreamingMessages` 是 Python Protocol, 而非 ABC:

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request) -> AsyncIterator[ApiStreamEvent]: ...
```

**Why**: 允许4种API客户端独立演化, 只需实现同一接口, 不需要共享基类。CopilotClient 通过包装 OpenAICompatibleClient 复用代码, 而非继承。

**How to apply**: 新增API客户端只需实现 `stream_message()` 方法, 自动接入Agent Loop。

### 5.2 Immutable Dataclass (不可变数据)

`ToolResult`, `ApiTextDeltaEvent`, `ApiMessageCompleteEvent`, `HookResult` 等核心数据类型使用 `frozen=True` 的 dataclass。

**Why**: 不可变数据防止隐藏副作用, 在异步并发环境中尤其重要。异步生成器、asyncio.gather 并行执行、多Agent邮箱传递都需要数据不可被意外修改。

**How to apply**: 事件和数据传输对象用 frozen dataclass; 状态对象 (QueryContext, TeammateContext) 用可变 dataclass。

### 5.3 原子写 + 文件锁 (崩溃安全 + 并发安全)

所有配置/凭证/会话写入使用两道保护:

1. **atomic_write_text** (utils/fs.py): temp文件 + fsync + os.replace, 保证崩溃不丢失
2. **exclusive_file_lock** (utils/file_lock.py): fcntl/msvcrt, 保证并发不竞争

**Why**: `Path.write_text()` 中途崩溃留下截断文件; 两个oh进程同时写settings.json导致数据丢失。这是生产环境必须解决的问题。

**How to apply**: 所有 `save_settings()`, `store_credential()`, `save_session()`, memory写入都使用此模式。

### 5.4 权限拒绝 = ToolResultBlock(is_error=True)

权限拒绝不抛异常, 而是返回带错误标记的 ToolResultBlock。

**Why**: Anthropic API硬性要求每个 `tool_use_id` 必须有对应 `tool_result`。如果抛异常导致缺少tool_result, 下一次API调用会被拒绝。返回is_error=True的ToolResultBlock保证对话历史完整, 模型还能看到拒绝原因并调整策略。

### 5.5 多工具并行 + return_exceptions=True

```python
results = await asyncio.gather(*[execute(tc) for tc in tool_calls], return_exceptions=True)
```

**Why**: 模型同时请求多个只读工具 (如read_file(a.py) + read_file(b.py)) 时, 并行节省等待时间。`return_exceptions=True` 确保单个工具失败不取消其他, 因为每个tool_use都必须有对应tool_result。

### 5.6 Carryover 系统 (tool_metadata)

`tool_metadata` 是可变dict, 在Agent Loop中被 `_record_tool_carryover()` 持续更新。

**Why**: 上下文压缩会丢弃消息, 但Agent需要记住"我做了什么"。tool_metadata在压缩后保留, 作为压缩后系统提示词的补充信息注入, 包含: 已读文件、已调Skill、工作日志、用户目标等。

### 5.7 双层压缩 (auto + reactive)

- **Auto-compact**: 每轮查询前检查, 估算token接近上限时自动触发
- **Reactive compact**: API报 `prompt_too_long` 时补救, 只尝试一次

**Why**: 上下文溢出是Agent长会话的核心问题。自动压缩在问题发生前解决, 响应式压缩在问题发生后补救, 形成双层防线。

---

## 6. 接口契约

### 6.1 模块间主要接口

| 接口 | 定义位置 | 消费者 | 协议 |
|------|----------|--------|------|
| `SupportsStreamingMessages` | `api/client.py` | QueryEngine | `stream_message(request) → AsyncIterator[ApiStreamEvent]` |
| `BaseTool` | `tools/base.py` | Agent Loop | `execute(args, ctx) → ToolResult`, `is_read_only(args) → bool` |
| `HookExecutor` | `hooks/executor.py` | Agent Loop | `execute(event, payload) → AggregatedHookResult` |
| `PermissionChecker` | `permissions/checker.py` | Agent Loop | `evaluate(tool, read_only, path, cmd) → PermissionDecision` |
| `CommandHandler` | `commands/registry.py` | handle_line | `(args, ctx) → CommandResult` |
| `PaneBackend` | `swarm/registry.py` | Swarm | `create_pane()`, `send_command()`, `kill_pane()` |
| `BaseChannel` | `channels/base.py` | ChannelBridge | `start()`, `stop()`, `send()`, `receive()` |
| `AppStateStore` | `state/` | TUI | `subscribe(listener)`, `set(**updates)` |

### 6.2 数据流经接口

```
ConversationMessage ──→ API Client ──→ LLM ──→ API Client ──→ StreamEvent ──→ UI
      ↑                    ↑                         ↑
  ToolRegistry        ToolResult              ToolResultBlock
      ↑                    ↑                         ↑
  BaseTool.execute   _execute_tool_call      messages.append
```

---

## 7. 配置体系

### 7.1 多层配置合并

优先级从高到低:

```
1. CLI 参数         (--model sonnet, --permission-mode full_auto)
2. 环境变量         (ANTHROPIC_API_KEY, OPENHARNESS_MODEL, ...)
3. 配置文件         (~/.openharness/settings.json)
4. 代码默认值        (Settings 类字段默认值)
```

### 7.2 Profile 物化

`Settings` 同时持有 flat 字段 (`self.model`) 和 profile 字段 (`self.profiles["claude-api"].default_model`)。`materialize_active_profile()` 将active profile投影到flat字段, 确保一致性。

### 7.3 运行时热生效

配置修改 → `save_settings()` → `CommandResult(refresh_runtime=True)` → `refresh_runtime_client()` 重建 RuntimeBundle (API Client, HookExecutor, PermissionChecker 等)。

### 7.4 ProviderProfile — 多Provider架构

```python
class ProviderProfile:
    label, provider, api_format, auth_source
    default_model, last_model, base_url
    credential_slot  # 独立密钥槽位 (解决多兼容端点问题)
```

7个内置Profile + 自定义, 通过 `oh provider use <name>` 切换。

---

## 8. 安全架构

### 8.1 权限9级决策链

```
① 内置敏感路径保护 (不可覆盖!) → ② 工具黑名单 → ③ 工具白名单
→ ④ 路径 deny 规则 → ⑤ 命令 deny 模式 → ⑥ FULL_AUTO 模式
→ ⑦ 只读判断 → ⑧ PLAN 模式拒绝 → ⑨ DEFAULT 模式确认框
```

**敏感路径硬保护**: .ssh/, .aws/, .gnupg/ 等, 即使full_auto模式也不可访问 — 防御prompt injection的纵深措施。

### 8.2 SSRF防护

`utils/network_guard.py` 的 `ensure_public_http_url()`:
1. DNS解析目标主机
2. 检查每个IP: `is_global`?
3. 拒绝非全局IP (127.0.0.1, 10.x, 192.168.x等)
4. 重定向逐跳验证

### 8.3 沙箱隔离

双后端 (srt runtime + Docker), 透明集成:
- 文件工具: `validate_sandbox_path()` 检查路径边界
- Shell工具: `create_shell_subprocess()` 自动路由到Docker
- 网络ACL: allowed_domains / denied_domains

### 8.4 凭据保护

| 机制 | 安全等级 | 用途 |
|------|----------|------|
| Keyring | 高 | API Key (OS级加密) |
| credentials.json (mode 600) | 中 | API Key (文件权限) |
| XOR + Base64 | 低 | Session Token (仅防偶然读取) |

### 8.5 Swarm权限同步

Worker写操作需Leader审批:
- 文件系统协议: `pending/<id>.json` → Leader审批 → `resolved/<id>.json`
- 邮箱协议: MailboxMessage(type="permission_request")
- 只读工具白名单: read_file, glob, grep等无需审批

---

## 9. 错误处理

### 9.1 错误层级

```
OpenHarnessApiError (基类)
├── AuthenticationFailure   # 401/403 — 不重试
├── RateLimitFailure        # 429 — 自动重试
└── RequestFailure          # 其他 — 条件重试
```

### 9.2 重试策略

- **可重试状态码**: 429, 500, 502, 503, 529
- **退避算法**: 指数退避 (1s→2s→4s→8s, 上限30s) + 随机抖动 (0~25%)
- **优先使用 Retry-After Header** (429常见)
- **最多4次尝试** (1 + 3 retries)

### 9.3 压缩策略 (4级递进)

| 级别 | 策略 | 成本 | 机制 |
|------|------|------|------|
| 1 | microcompact | 免费 | 清除旧工具结果内容 → 占位符 |
| 2 | context_collapse | 免费 | 截断过长TextBlock (保留头900+尾500字符) |
| 3 | session_memory | 免费 | 确定性结构化摘要 (48行/4000字符) |
| 4 | full compact | 昂贵 | LLM调用生成摘要 |

- **Auto-compact**: 每轮检查, 接近上限时自动触发
- **连续3次失败后停止** auto-compact
- **tool_metadata 9个键**在压缩后保留

### 9.4 Agent Loop错误处理

| 场景 | 处理 |
|------|------|
| 网络错误 | yield ErrorEvent, 退出 |
| prompt_too_long | 尝试reactive compact, 成功则continue |
| 空助手消息 | yield ErrorEvent, 退出 |
| 工具验证失败 | 返回 ToolResultBlock(is_error=True) |
| 权限拒绝 | 返回 ToolResultBlock(is_error=True) |
| Hook阻断 | 返回 ToolResultBlock(is_error=True) |
| 超轮次 | 抛出 MaxTurnsExceeded |

---

## 10. 技术选型

### 10.1 核心选型理由

| 选型 | 理由 |
|------|------|
| Python 3.12+ | 类型提示完善 (union type `X \| Y`), asyncio成熟 |
| Pydantic v2 | 同时解决输入验证 + JSON Schema生成 + 序列化 (一石三鸟) |
| asyncio | Agent Loop天然异步 (流式API + 并行工具 + 后台任务) |
| Typer | 类型安全的CLI定义, 自动生成帮助 |
| httpx | 异步HTTP, 替代requests |
| React/Ink | 丰富TUI渲染, 社区生态, 组件化 |

### 10.2 数据模型选型

| 类型 | 选择 | 理由 |
|------|------|------|
| API传输对象 | frozen dataclass | 不可变, 轻量, 不需验证 |
| 配置/输入模型 | Pydantic BaseModel | 验证 + Schema + 序列化 |
| 运行时上下文 | 可变 dataclass | 需要可变字段 (tool_metadata) |
| 枚举 | str + Enum | 可序列化, 兼容JSON |
| 接口 | Protocol | 鸭子类型, 不强制继承 |

---

## 附录: 详细设计文档索引

| 文档 | 覆盖模块 | 详见 |
|------|----------|------|
| [engine.md](detailed-design/engine.md) | engine/ | 消息模型, 事件流, Agent Loop, QueryEngine |
| [api-auth.md](detailed-design/api-auth.md) | api/, auth/ | 4种客户端, Provider检测, 认证流, 凭证存储 |
| [tools.md](detailed-design/tools.md) | tools/, mcp/ | BaseTool, 36+工具, MCP动态工具 |
| [config-permissions.md](detailed-design/config-permissions.md) | config/, permissions/ | Settings, Profile, 权限9级决策链 |
| [hooks-commands.md](detailed-design/hooks-commands.md) | hooks/, commands/ | 4种Hook, ~50命令, CommandRegistry |
| [knowledge.md](detailed-design/knowledge.md) | skills/, memory/, prompts/, personalization/ | 三层知识架构, 系统提示词组装 |
| [swarm-services.md](detailed-design/swarm-services.md) | swarm/, services/ | 多Agent协作, 上下文压缩, 会话持久化 |
| [ui-channels.md](detailed-design/ui-channels.md) | ui/, channels/, bridge/ | React TUI, 10通道, Bridge |
| [auxiliary.md](detailed-design/auxiliary.md) | 其余14个模块 | 沙箱, MCP, 任务, 主题等 |