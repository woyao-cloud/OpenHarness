# OpenHarness 系统功能说明书

> 版本：0.1.6 | 最后更新：2026-04-21
> 源码位置：`src/openharness/`

---

## 1. 项目概述

OpenHarness 是一个开源 AI 编码助手 CLI 工具，是 Claude Code 的 Python 移植版。它支持多 LLM 提供商（Anthropic、OpenAI、Copilot 等 20+）、10 个聊天平台渠道、插件/技能扩展、MCP 协议集成、沙箱隔离执行、多智能体协作等功能。

### 系统架构总览

```
┌──────────────────────────────────────────────────────────┐
│                    CLI 入口 (cli.py)                      │
│  oh / openh / openharness — Typer 应用 + 6 个子应用      │
└──────────┬───────────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────┐
│              UI 层 (ui/app.py, ui/runtime.py)              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  React TUI  │  │ Textual TUI  │  │  Task Worker      │ │
│  └─────────────┘  └──────────────┘  └──────────────────┘ │
│  RuntimeBundle: api_client + engine + tools + permissions │
└──────────┬───────────────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────┐
│                 查询引擎 (engine/query.py)                  │
│  消息 → API 调用 → 流式响应 → 工具解析 → 执行 → 循环      │
└────┬──────────┬─────────────┬────────────────────────────┘
     │          │             │
┌────▼───┐ ┌───▼──────┐ ┌────▼──────────────────────────┐
│ API    │ │ 工具系统 │ │  权限/钩子/内存/沙箱/日志       │
│ 提供商 │ │ 33+ 工具 │ │  横切关注点                     │
└────────┘ └──────────┘ └─────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────┐
│              渠道系统 (channels/)                          │
│  Telegram / Slack / Discord / 飞书 / 钉钉 / QQ / ...     │
│  ← MessageBus → ChannelBridge → QueryEngine →            │
└──────────────────────────────────────────────────────────┘
```

---

## 2. CLI 模块

**源码：** `src/openharness/cli.py`

### 功能概述

提供 `oh` 命令行界面，基于 Typer 框架。包含 6 个子应用和 30+ 个命令。

### 用户交互方式

| 命令 | 功能 |
|------|------|
| `oh` | 启动交互式 REPL（默认） |
| `oh -p "prompt"` | 非交互模式，输出后退出 |
| `oh --task-worker` | 无头工作进程，从 stdin 读取 |
| `oh --continue` | 恢复上次会话 |
| `oh --resume [ID]` | 恢复指定会话 |
| `oh setup` | 引导式配置向导 |
| `oh auth login/logout/switch/status` | 认证管理 |
| `oh auth copilot-login/codex-login/claude-login` | 特定提供商认证 |
| `oh provider list/use/add/edit/remove` | 提供商配置管理 |
| `oh mcp list/add/remove` | MCP 服务器管理 |
| `oh plugin list/install/uninstall` | 插件管理 |
| `oh cron start/stop/status/list/toggle/history/logs` | 定时任务管理 |

### CLI 选项

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--model` | str | claude-sonnet-4-6 | 使用的模型 |
| `--permission-mode` | str | default | 权限模式 (default/plan/full_auto) |
| `--system-prompt` | str | None | 自定义系统提示 |
| `--base-url` | str | None | API 基础 URL |
| `--api-key` | str | None | API 密钥 |
| `--api-format` | str | anthropic | API 格式 (anthropic/openai/copilot) |
| `--max-turns` | int | 200 | 最大工具调用轮数 |
| `--verbose` | bool | False | 详细日志 |
| `--debug` | bool | False | 调试模式 |
| `--bare` | bool | False | 无系统提示启动 |
| `--theme` | str | default | UI 主题 |
| `--effort` | str | medium | 推理努力级别 |
| `--dangerously-skip-permissions` | bool | False | 跳过权限确认（= full_auto） |
| `--allowed-tools` | str | None | 白名单工具（逗号分隔） |
| `--disallowed-tools` | str | None | 黑名单工具（逗号分隔） |

### 输入/输出

- **输入**：命令行参数、交互式 stdin
- **输出**：stdout（正常输出）、stderr（错误信息）、退出码（0=成功，非0=错误）

### 错误处理

- 无效输入：`typer.Exit(1)`
- 运行时致命错误：`SystemExit`
- 认证缺失：提示运行 `oh auth login`

---

## 3. UI / 运行时模块

**源码：** `src/openharness/ui/app.py`, `src/openharness/ui/runtime.py`

### 功能概述

提供三种运行模式，并负责组装完整的运行时环境（RuntimeBundle）。

### 运行模式

| 模式 | 入口函数 | 说明 |
|------|---------|------|
| 交互式 REPL | `run_repl()` | React TUI 或 Textual TUI，前后端分离 |
| 非交互模式 | `run_print_mode()` | 提交提示 → 流式输出 → 退出 |
| 任务工作进程 | `run_task_worker()` | 从 stdin 读取 JSON，处理后退出 |

### 输出格式（非交互模式）

| 格式 | 说明 |
|------|------|
| `text` | 流式文本（默认） |
| `json` | 收集完整结果后输出 JSON |
| `stream-json` | 每行一个 JSON 事件 |

### RuntimeBundle 组装流程

`build_runtime()` 按以下顺序组装：

1. 加载配置 → 合并 CLI 覆盖
2. 加载插件 → 发现技能/命令/Agent/钩子/MCP
3. 解析 API 客户端 → 选择 Anthropic/OpenAI/Copilot/Codex
4. 创建 MCP 管理器 → 连接 MCP 服务器
5. 创建工具注册表 → 注册 33+ 内置工具 + MCP 工具
6. 检测提供商 → ProviderInfo
7. 加载钩子注册表 → HookExecutor
8. 构建系统提示
9. 创建 QueryEngine
10. 创建 AppState + AppStateStore

### 依赖

几乎所有子系统：api, engine, permissions, tools, mcp, hooks, plugins, bridge, commands, state, sandbox

---

## 4. 查询引擎

**源码：** `src/openharness/engine/query.py`

### 功能概述

核心代理循环：发送消息到 LLM → 解析工具调用 → 执行工具 → 反馈结果 → 重复，直到模型停止请求工具或达到轮数上限。

### 核心流程

```
用户输入 → handle_line()
    ├── 斜杠命令 → 命令处理器
    └── 普通文本 → QueryEngine
         │
         ▼
    1. 调用 API 客户端 (stream_message)
    2. 接收流式事件 (AssistantTextDelta)
    3. 解析 tool_use 块
    4. 权限检查 (PermissionChecker)
    5. 执行工具 (ToolRegistry)
    6. 收集工具结果
    7. 将结果加入消息列表
    8. 回到步骤 1（循环）
```

### 输入/输出

- **输入**：`QueryContext` + `list[ConversationMessage]`
- **输出**：`AsyncIterator[(StreamEvent, UsageSnapshot | None)]`

### 流事件类型

| 事件 | 说明 |
|------|------|
| `AssistantTextDelta` | 增量文本输出 |
| `AssistantTurnComplete` | 一轮完成 |
| `ToolExecutionStarted` | 工具开始执行 |
| `ToolExecutionCompleted` | 工具执行完成 |
| `StatusEvent` | 状态消息 |
| `ErrorEvent` | 错误事件 |
| `CompactProgressEvent` | 压缩进度 |

### 配置选项

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_turns` | 200 | 最大工具调用轮数 |
| `context_window_tokens` | None | 上下文窗口大小 |
| `auto_compact_threshold_tokens` | None | 自动压缩阈值 |

### 错误处理

- 网络/连接错误 → `ErrorEvent`（"Network error"前缀）
- 认证错误 → `AuthenticationFailure`
- 速率限制 → `RateLimitFailure`
- 上下文过长 → 自动触发响应式压缩
- 工具执行错误 → `ToolResult(is_error=True)`
- 权限拒绝 → 错误结果（含拒绝原因）

---

## 5. API 提供商系统

**源码：** `src/openharness/api/client.py`, `src/openharness/api/registry.py`, `src/openharness/api/provider.py`

### 功能概述

支持 20+ LLM 提供商，通过 Protocol 实现统一流式接口，带自动重试和提供商检测。

### 提供商类型

| 类型 | 客户端 | 说明 |
|------|--------|------|
| Anthropic | `AnthropicApiClient` | 原生 Anthropic SDK |
| OpenAI 兼容 | `OpenAICompatibleClient` | 消息格式转换 |
| GitHub Copilot | `CopilotClient` | OAuth 设备流 |
| OpenAI Codex | `CodexApiClient` | 订阅认证 |

### 已注册提供商（20+）

Anthropic, OpenAI, DeepSeek, Gemini, Groq, Mistral, DashScope, Moonshot, MiniMax, Zhipu AI, StepFun, Baidu, AWS Bedrock, Google Vertex AI, OpenRouter, AiHubMix, SiliconFlow, VolcEngine, GitHub Copilot, Ollama, vLLM

### 提供商检测优先级

1. API 密钥前缀匹配
2. Base URL 关键词匹配
3. 模型名称关键词匹配

### 重试策略

| 参数 | 值 |
|------|-----|
| 最大重试次数 | 3 |
| 基础延迟 | 1.0 秒 |
| 最大延迟 | 30.0 秒 |
| 可重试状态码 | 429, 500, 502, 503, 529 |
| 退避策略 | 指数退避 + 随机抖动 |

---

## 6. 认证系统

**源码：** `src/openharness/auth/manager.py`, `src/openharness/auth/flows.py`

### 功能概述

管理多提供商认证状态，支持 API 密钥、OAuth 设备流和外部 CLI 绑定三种认证方式。

### 认证方式

| 方式 | 类 | 流程 |
|------|-----|------|
| API 密钥 | `ApiKeyFlow` | 提示输入 → getpass 安全读取 → 存储 |
| OAuth 设备流 | `DeviceCodeFlow` | 获取设备码 → 打印验证 URL → 轮询令牌 |
| 浏览器流 | `BrowserFlow` | 打开浏览器 → 粘贴令牌 |

### 内置提供商配置

| 配置名 | 提供商 | 认证来源 | 默认模型 |
|--------|--------|----------|----------|
| claude-api | Anthropic | anthropic_api_key | claude-sonnet-4-6 |
| claude-subscription | Anthropic 订阅 | claude_subscription | claude-sonnet-4-6 |
| openai-compatible | OpenAI | openai_api_key | gpt-5.4 |
| codex | Codex 订阅 | codex_subscription | gpt-5.4 |
| copilot | GitHub Copilot | copilot_oauth | gpt-5.4 |
| moonshot | Moonshot | moonshot_api_key | kimi-k2.5 |
| gemini | Google Gemini | gemini_api_key | gemini-2.5-flash |

### 凭据存储

路径：`~/.openharness/credentials.json`，支持双后端（文件 + keyring）。

---

## 7. 工具系统

**源码：** `src/openharness/tools/base.py`, `src/openharness/tools/__init__.py`

### 功能概述

33+ 内置工具 + MCP 动态工具，统一通过 `BaseTool` ABC 管理，Pydantic 输入模型自动验证。

### 内置工具列表

| 工具 | 说明 | 只读 |
|------|------|------|
| `BashTool` | 执行 shell 命令 | 否 |
| `FileReadTool` | 读取文件 | 是 |
| `FileWriteTool` | 写入文件 | 否 |
| `FileEditTool` | 编辑文件（精确替换） | 否 |
| `NotebookEditTool` | 编辑 Jupyter Notebook | 否 |
| `GrepTool` | 正则搜索文件内容 | 是 |
| `GlobTool` | Glob 模式搜索文件 | 是 |
| `LspTool` | LSP 代码操作 | 否 |
| `WebFetchTool` | 获取网页内容 | 是 |
| `WebSearchTool` | 网络搜索 | 是 |
| `AskUserQuestionTool` | 向用户提问 | 是 |
| `SkillTool` | 执行技能 | 是 |
| `ToolSearchTool` | 搜索可用工具 | 是 |
| `ConfigTool` | 修改配置 | 否 |
| `BriefTool` | 简要说明工具 | 是 |
| `EnterPlanModeTool` / `ExitPlanModeTool` | 计划模式切换 | 否 |
| `EnterWorktreeTool` / `ExitWorktreeTool` | Worktree 管理 | 否 |
| `CronCreateTool/ListTool/DeleteTool/ToggleTool` | 定时任务管理 | 否 |
| `TaskCreateTool/GetTool/ListTool/UpdateTool/StopTool/OutputTool` | 任务管理 | 否 |
| `AgentTool` | 启动子 Agent | 否 |
| `SendMessageTool` | 向 Agent 发消息 | 否 |
| `TeamCreateTool` / `TeamDeleteTool` | 团队管理 | 否 |
| `RemoteTriggerTool` | 远程触发器 | 否 |
| `McpAuthTool` | MCP 认证 | 否 |
| `McpToolAdapter` | MCP 工具适配器 | 视情况 |
| `SleepTool` | 等待/延迟 | 是 |
| `TodoWriteTool` | 待办事项 | 否 |

### 工具执行流程

```
1. QueryEngine 解析 tool_use 块
2. PermissionChecker 评估权限
3. HookExecutor 运行 PRE_TOOL_USE 钩子
4. BaseTool.execute(arguments, context) → ToolResult
5. HookExecutor 运行 POST_TOOL_USE 钩子
6. 返回 ToolResult 给 QueryEngine
```

---

## 8. 渠道系统

**源码：** `src/openharness/channels/`

### 功能概述

通过 Bus/Adapter 模式统一 10 个聊天平台，解耦渠道实现与查询引擎。

### 支持的渠道

| 渠道 | SDK | 说明 |
|------|-----|------|
| Telegram | python-telegram-bot | Bot API |
| Slack | slack-sdk | Socket Mode |
| Discord | discord.py | Bot Gateway |
| 飞书 (Feishu) | lark-oapi | 事件订阅 |
| 钉钉 (DingTalk) | HTTP | Stream 模式 |
| Email | smtplib | SMTP 收发 |
| QQ | HTTP | 官方 Bot API |
| Matrix | HTTP | 协议客户端 |
| WhatsApp | HTTP | Cloud API |
| Mochat | HTTP | 自定义端点 |

### 数据流

```
用户消息 → BaseChannel._handle_message() → 权限检查(allow_from)
    → MessageBus.inbound → ChannelBridge._loop()
    → QueryEngine.submit_message() → 流式事件
    → ChannelBridge 收集文本 → MessageBus.outbound
    → ChannelManager 分发 → BaseChannel.send() → 用户收到回复
```

### 配置

每个渠道有独立的配置模型（`TelegramConfig`, `SlackConfig` 等），均继承 `BaseChannelConfig`（`enabled`, `allow_from` 字段）。

---

## 9. 配置系统

**源码：** `src/openharness/config/settings.py`, `src/openharness/config/schema.py`

### 加载优先级

```
CLI 参数（最高）→ 环境变量 → ~/.openharness/settings.json → 内置默认值（最低）
```

### 核心配置模型

**Settings(BaseModel)** 主要字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | str | "" | API 密钥 |
| `model` | str | claude-sonnet-4-6 | 默认模型 |
| `max_tokens` | int | 16384 | 最大输出 token |
| `base_url` | str \| None | None | API 基础 URL |
| `timeout` | float | 30.0 | 请求超时（秒） |
| `api_format` | str | anthropic | API 格式 |
| `provider` | str | "" | 提供商标识 |
| `active_profile` | str | claude-api | 活跃配置名 |
| `max_turns` | int | 200 | 最大工具调用轮数 |
| `system_prompt` | str \| None | None | 自定义系统提示 |
| `permission` | PermissionSettings | — | 权限配置 |
| `memory` | MemorySettings | — | 记忆配置 |
| `sandbox` | SandboxSettings | — | 沙箱配置 |
| `theme` | str | default | UI 主题 |
| `vim_mode` | bool | False | Vim 模式 |
| `fast_mode` | bool | False | 快速模式 |
| `effort` | str | medium | 推理努力级别 |
| `verbose` | bool | False | 详细日志 |

---

## 10. 权限系统

**源码：** `src/openharness/permissions/checker.py`, `src/openharness/permissions/modes.py`

### 权限模式

| 模式 | 行为 |
|------|------|
| `DEFAULT` | 变更操作需用户确认 |
| `PLAN` | 阻止所有变更操作 |
| `FULL_AUTO` | 允许所有操作 |

### 评估顺序

1. **内置敏感路径保护**（SSH 密钥、AWS/GCP/Azure 凭证、GPG 密钥、Docker 凭证、K8s 配置）— 不可覆盖
2. **工具拒绝列表** — `denied_tools` 中的工具直接拒绝
3. **工具允许列表** — `allowed_tools` 中的工具直接允许
4. **路径规则** — glob 匹配的拒绝规则
5. **命令拒绝模式** — glob 匹配的命令拒绝
6. **FULL_AUTO 模式** — 全部允许
7. **只读工具** — 总是允许
8. **PLAN 模式** — 阻止变更
9. **DEFAULT 模式** — 需确认

---

## 11. 定时任务

**源码：** `src/openharness/services/cron_scheduler.py`

### 功能概述

后台守护进程，30 秒轮询间隔，执行 cron 定时任务。

### 功能

| 功能 | 命令/函数 |
|------|----------|
| 启动守护进程 | `oh cron start` / `start_daemon()` |
| 停止守护进程 | `oh cron stop` / `stop_scheduler()` |
| 查看状态 | `oh cron status` / `scheduler_status()` |
| 列出任务 | `oh cron list` |
| 启用/禁用 | `oh cron toggle` |
| 查看历史 | `oh cron history` |
| 查看日志 | `oh cron logs` |

### 参数

| 参数 | 值 |
|------|-----|
| 轮询间隔 | 30 秒 |
| 任务超时 | 300 秒 |
| PID 文件 | `~/.openharness/cron_scheduler.pid` |
| 日志文件 | `~/.openharness/logs/cron_scheduler.log` |
| 历史文件 | `~/.openharness/cron_history.jsonl` |

---

## 12. 记忆系统

**源码：** `src/openharness/memory/manager.py`

### 功能概述

项目级 Markdown 记忆文件管理，支持 CRUD 操作和索引维护。

### 功能

| 操作 | 函数 | 说明 |
|------|------|------|
| 列出 | `list_memory_files(cwd)` | 列出项目记忆目录下所有 .md 文件 |
| 添加 | `add_memory_entry(cwd, title, content)` | 创建记忆文件 + 更新 MEMORY.md 索引 |
| 删除 | `remove_memory_entry(cwd, name)` | 删除记忆文件 + 更新索引 |

### 并发安全

- 使用 `exclusive_file_lock` 保证多进程安全
- 使用 `atomic_write_text` 防止文件损坏

---

## 13. 沙箱系统

**源码：** `src/openharness/sandbox/adapter.py`, `src/openharness/sandbox/docker_backend.py`

### 功能概述

两种沙箱后端：srt CLI（sandbox-runtime）和 Docker，提供网络/文件系统隔离。

### 后端对比

| 特性 | srt (sandbox-runtime) | Docker |
|------|----------------------|--------|
| 隔离级别 | OS 级（bwrap/sandbox-exec） | 容器级 |
| 平台 | Linux/WSL (bwrap), macOS (sandbox-exec) | 跨平台 |
| 开销 | 低 | 中（容器启动） |
| 配置 | 网络规则 + 文件系统规则 | 镜像/CPU/内存/挂载 |

### 配置

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | False | 启用沙箱 |
| `backend` | srt | 后端类型 (srt/docker) |
| `fail_if_unavailable` | False | 不可用时是否报错 |
| `network.allowed_domains` | [] | 允许的网络域名 |
| `network.denied_domains` | [] | 拒绝的网络域名 |
| `filesystem.allow_write` | ["."] | 允许写入的路径 |
| `docker.image` | openharness-sandbox:latest | Docker 镜像 |

---

## 14. 插件/技能/MCP

**源码：** `src/openharness/plugins/`, `src/openharness/skills/`, `src/openharness/mcp/`

### 插件系统

插件清单（`plugin.json`）包含：名称、版本、描述、技能目录、钩子文件、MCP 文件。

发现来源：
1. 用户目录：`~/.openharness/plugins/`
2. 项目目录：`<cwd>/.openharness/plugins/`
3. 额外根目录

### 技能系统

技能基于 `SKILL.md` Markdown 文件，从三个来源加载：
1. 内置技能
2. 用户技能：`~/.openharness/skills/`
3. 插件技能

### MCP 集成

支持三种传输配置：
- `StdioConfig`：子进程标准 I/O
- `HttpConfig`：HTTP SSE
- `WsConfig`：WebSocket

---

## 15. 钩子/事件系统

**源码：** `src/openharness/hooks/`

### 钩子类型

| 类型 | 触发时机 |
|------|---------|
| `CommandHook` | 匹配特定命令 |
| `PromptHook` | 匹配提示模式 |
| `HttpHook` | 匹配 HTTP 请求 |
| `AgentHook` | 匹配 Agent 事件 |

### 事件类型

| 事件 | 说明 |
|------|------|
| `SESSION_START` | 会话开始 |
| `SESSION_END` | 会话结束 |
| `PRE_TOOL_USE` | 工具执行前（可阻止） |
| `POST_TOOL_USE` | 工具执行后 |
| `SUBAGENT_STOP` | 子 Agent 停止 |

### 热重载

`HookReloader` 使用 `watchfiles` 监控钩子配置变更，自动重载无需重启。

---

## 16. 多智能体/协调器

**源码：** `src/openharness/swarm/`, `src/openharness/coordinator/`, `src/openharness/bridge/`

### 功能概述

主 Agent（Leader）可动态生成工作 Agent（Worker），通过文件型邮箱异步通信。

### 后端类型

| 后端 | 说明 |
|------|------|
| `subprocess` | 独立子进程 |
| `in_process` | 进程内（同进程） |
| `tmux` | tmux 窗格 |
| `iterm2` | iTerm2 窗格 |

### 通信方式

- **TeammateMailbox**：基于 JSON 文件的异步消息系统
- **Bridge**：连接 Agent 与外部会话

### Agent 定义

`AgentDefinition(BaseModel)` 从 YAML 加载，包含：名称、模型、系统提示、工具列表等。

---

## 17. 日志服务

**源码：** `src/openharness/services/log/`

### 功能概述

结构化日志包，包含 5 个子模块：

| 子模块 | 说明 |
|--------|------|
| `_shared.py` | 共享基础设施（请求计数、详细模式、日志路径、文件轮转） |
| `prompt_logger.py` | 提示/响应日志 |
| `tool_logger.py` | 工具执行日志 |
| `compact_logger.py` | 压缩事件日志 |
| `skill_logger.py` | 技能加载日志 |

### 参数

| 参数 | 值 |
|------|-----|
| 最大调试文件数 | 15 |
| 截断限制 | 500 字符 |
| 线程安全 | `threading.Lock` 保护全局计数器 |

---

## 18. 状态/会话管理

**源码：** `src/openharness/state/store.py`, `src/openharness/services/`

### AppStateStore

可观察状态存储，支持 subscribe/notify 模式。使用 `dataclasses.replace()` 进行不可变更新。

### 会话存储

JSON 持久化对话历史，支持会话恢复。

### 对话压缩

- **微压缩**：本地规则移除冗余消息
- **LLM 压缩**：调用 LLM 生成摘要

---

## 19. 跨模块依赖关系

```
CLI ──→ UI/App ──→ Runtime(build_runtime)
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
      QueryEngine    Permissions     Hooks
          │              │              │
    ┌─────┼─────┐        │         ┌───┴───┐
    ▼     ▼     ▼        ▼         ▼       ▼
  API   Tools  Memory   Config   Loader  Executor
  Client  │     │        │                   │
    │     ▼     ▼        ▼                   ▼
  Auth  Registry Scan  Settings         Hot-Reload
    │     │             │
    ▼     ▼             ▼
 Storage MCP          Paths
    │     │
    └──┬──┘
       ▼
    Channels
    (10 platforms)
```

**关键不变量**：
- Engine 依赖 API Client（通过 Protocol），不依赖 UI
- UI 依赖 Engine，反向不成立
- 渠道依赖 MessageBus 和 Engine 事件，Engine 不感知渠道
- 所有模块依赖 Config

---

## 20. 环境变量完整参考

| 变量名 | 对应字段 | 说明 |
|--------|---------|------|
| `ANTHROPIC_API_KEY` | api_key | Anthropic API 密钥 |
| `OPENAI_API_KEY` | api_key | OpenAI API 密钥 |
| `ANTHROPIC_MODEL` | model | Anthropic 模型名 |
| `OPENHARNESS_MODEL` | model | 通用模型名覆盖 |
| `ANTHROPIC_BASE_URL` | base_url | Anthropic API URL |
| `OPENAI_BASE_URL` | base_url | OpenAI API URL |
| `OPENHARNESS_BASE_URL` | base_url | 通用 API URL 覆盖 |
| `OPENHARNESS_MAX_TOKENS` | max_tokens | 最大输出 token |
| `OPENHARNESS_TIMEOUT` | timeout | 请求超时 |
| `OPENHARNESS_MAX_TURNS` | max_turns | 最大工具调用轮数 |
| `OPENHARNESS_CONTEXT_WINDOW_TOKENS` | context_window_tokens | 上下文窗口大小 |
| `OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` | auto_compact_threshold_tokens | 自动压缩阈值 |
| `OPENHARNESS_API_FORMAT` | api_format | API 格式 |
| `OPENHARNESS_PROVIDER` | provider | 提供商标识 |
| `OPENHARNESS_VERBOSE` | verbose | 详细日志 |
| `OPENHARNESS_SANDBOX_ENABLED` | sandbox.enabled | 沙箱启用 |
| `OPENHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | sandbox.fail_if_unavailable | 沙箱不可用时报错 |
| `OPENHARNESS_SANDBOX_BACKEND` | sandbox.backend | 沙箱后端 |
| `OPENHARNESS_SANDBOX_DOCKER_IMAGE` | sandbox.docker.image | Docker 镜像 |
| `OPENHARNESS_CONFIG_DIR` | — | 配置目录覆盖 |
| `OPENHARNESS_DATA_DIR` | — | 数据目录覆盖 |
| `OPENHARNESS_LOGS_DIR` | — | 日志目录覆盖 |
| `OPENHARNESS_CHANNEL_MEDIA_DIR` | — | 渠道媒体目录 |
| `OHMO_WORKSPACE` | — | Ohmo 工作空间 |

---

## 21. 错误处理策略汇总

| 模块 | 错误类型 | 处理方式 |
|------|---------|---------|
| API Client | 认证错误 | 抛出 `AuthenticationFailure`，不重试 |
| API Client | 速率限制 | 抛出 `RateLimitFailure`，可重试 |
| API Client | 服务器错误 (5xx) | 自动重试（3次，指数退避） |
| API Client | 网络错误 | 自动重试 |
| Query Engine | 上下文过长 | 自动触发响应式压缩 |
| Query Engine | 工具执行失败 | 返回 `ToolResult(is_error=True)` |
| Query Engine | 权限拒绝 | 返回错误结果（含拒绝原因） |
| Query Engine | 最大轮数超限 | 抛出 `MaxTurnsExceeded` |
| Auth | 设备流失败 | 抛出 `RuntimeError` |
| Auth | 空输入 | 抛出 `ValueError` |
| Channel | 权限不足 | 静默忽略，记录日志 |
| Channel | 处理失败 | 回复 `[Error: ...]` |
| Cron | 任务超时 | 杀进程，记录 status="timeout" |
| Cron | 调度器异常 | 记录 status="error" |
| Sandbox | 不可用 | `fail_if_unavailable=True` 时抛异常，否则静默降级 |
| Memory | 并发写入 | `exclusive_file_lock` 保护 |
| Memory | 崩溃保护 | `atomic_write_text` 原子写入 |