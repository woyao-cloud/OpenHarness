# OpenHarness 代码接手计划

> 项目规模: 177 个 .py 文件, ~19,400 行代码, 29 个模块, 92 个测试文件
> 目标: 从核心到外围, 沿数据流方向逐步掌握全部源码

---

## 学习路线总览

```
入口 → 核心类型 → 引擎(心脏) → 工具系统 → 周边子系统 → 高级特性
  │       │          │            │            │              │
  1       2          3            4           5-8           9-10
```

**核心原则**: 沿数据流学习, 先理解"请求怎么进来的, 怎么被处理的", 再理解"处理过程用了哪些基础设施"。

---

## Phase 1: 入口与启动流程 (1-2h)

**目标**: 理解 `oh` 命令从敲下回车到进入 Agent Loop 之间的全部流程

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `src/openharness/__main__.py` | ~5 | `python -m openharness` 入口 |
| `src/openharness/cli.py` | 1420 | **最大文件**, Typer CLI 定义; 重点看 `main()`, `run()`, `run_repl()` 三个函数, 忽略子命令细节 |
| `src/openharness/platforms.py` | 110 | 平台检测工具函数 |

**阅读方法**:
1. 从 `cli.py` 底部 `main()` 开始向上读
2. 追踪 `oh` → `main()` → `run()` → `run_repl()` / `run_print_mode()` 调用链
3. 记录: 启动时创建了哪些核心对象 (QueryEngine, ToolRegistry, Settings 等)

**验证**: 能画出自敲下 `oh` 到第一条消息发出之间的完整调用链

---

## Phase 2: 核心数据类型 (1-2h)

**目标**: 掌握贯穿全项目的数据模型, 后续阅读时遇到这些类型不需要回头查

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `engine/messages.py` | 177 | `TextBlock`, `ImageBlock`, `ToolUseBlock`, `ToolResultBlock`, `ConversationMessage` — 全部消息模型 |
| `engine/stream_events.py` | 90 | `AssistantTextDelta`, `AssistantTurnComplete`, `ToolExecutionStarted`, `ToolExecutionCompleted` — 事件类型 |
| `engine/cost_tracker.py` | 25 | `UsageSnapshot`, `CostTracker` — 用量追踪 |
| `config/schema.py` | 250 | Settings 数据结构定义 |
| `config/paths.py` | 100 | 配置目录路径约定 |

**阅读方法**:
1. 只看 Pydantic 模型 / dataclass 定义, 跳过函数实现
2. 画一张类型关系图: ConversationMessage 包含哪些 Block, StreamEvent 有哪些子类型

**验证**: 看到 `ToolUseBlock` 能立刻知道它有哪些字段, 知道 `ConversationMessage` 和 `StreamEvent` 的区别

---

## Phase 3: Agent Loop — 引擎核心 (3-4h) ⭐ 最重要

**目标**: 彻底理解 "用户提问 → 模型回复 → 工具调用 → 结果返回 → 循环" 这条主线

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `engine/query.py` | 746 | **核心中的核心**: `run_query()`, `_execute_tool_call()`, `QueryContext`, focus-state, carryover |
| `engine/query_engine.py` | 206 | `QueryEngine` 类: 拥有对话历史, `submit_message()`, `continue_pending()` |
| `engine/__init__.py` | 81 | 导出汇总, 帮助理解模块边界 |

**阅读方法**:
1. 从 `run_query()` 函数签名开始, 理解输入输出
2. 找到 `while True` 循环 — 这就是 Agent Loop
3. 追踪一次完整的工具调用流程:
   - 模型返回 `tool_use` → `_execute_tool_call()` → 权限检查 → Hook → 执行 → Hook → 结果
4. 理解 `QueryContext` 的作用 — 它贯穿整个查询, 携带上下文

**验证**: 能不看书复述 Agent Loop 的完整流程, 包括权限检查和 Hook 插入点

---

## Phase 4: 工具系统 (2-3h)

**目标**: 理解工具注册、发现、执行机制, 以及 43+ 工具的分类

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `tools/base.py` | 76 | `BaseTool(ABC)`, `ToolResult`, `ToolExecutionContext`, `ToolRegistry` — 工具基类和注册表 |
| `tools/__init__.py` | 104 | `create_default_tool_registry()` — 所有工具在此注册 |
| `tools/bash_tool.py` | 208 | 最复杂的工具, 包含沙箱、超时、输出处理 |
| `tools/grep_tool.py` | 361 | 第二复杂, ripgrep + Python fallback |
| `tools/file_read_tool.py` | ~60 | 典型的简单工具, 读一遍就知道模式 |

**阅读方法**:
1. 先读 `base.py` — 理解 `BaseTool` 接口: `name`, `description`, `input_model`, `execute()`
2. 读 `create_default_tool_registry()` — 看有哪些工具, 分哪几类
3. 精读 `bash_tool.py` 和 `file_read_tool.py` (一复杂一简单)
4. 其余工具快速扫描, 知道分类即可:
   - **文件 I/O**: Read, Write, Edit, Glob, Grep, NotebookEdit
   - **Shell**: Bash
   - **搜索**: WebFetch, WebSearch, ToolSearch, LSP
   - **Agent**: Agent, SendMessage, TeamCreate/Delete
   - **Task**: TaskCreate/Get/List/Update/Stop/Output (6 个)
   - **MCP**: McpTool, ListMcpResources, ReadMcpResource
   - **调度**: CronCreate/List/Delete/Toggle, RemoteTrigger
   - **交互**: AskUserQuestion, Skill, Config, Brief, Sleep
   - **模式**: EnterPlanMode, ExitPlanMode, EnterWorktree, ExitWorktree

**验证**: 能说出任意一个工具属于哪一类, 能自己写一个新工具

---

## Phase 5: 配置与权限 (2h)

**目标**: 理解多层配置系统和权限守卫, 这是系统安全的基石

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `config/settings.py` | 870 | `Settings`, `ProviderProfile` — 最大配置文件, 重点看类定义和方法签名 |
| `permissions/modes.py` | 20 | `PermissionMode` 枚举: default / auto / plan |
| `permissions/checker.py` | 201 | `PermissionChecker` — 核心权限逻辑, 路径规则、命令拒绝 |

**阅读方法**:
1. `settings.py` 只看类定义, 跳过迁移/兼容代码
2. `checker.py` 重点看 `check()` 方法: 决策流程 (deny → path_rules → mode → ask)
3. 理解 PermissionChecker 如何与 Agent Loop 集成 (在 Phase 3 的 `_execute_tool_call` 中调用)

**验证**: 能解释 default 模式下, 一个 Bash 命令的权限检查流程

---

## Phase 6: API 客户端与认证 (2-3h)

**目标**: 理解多 Provider 架构, 以及认证/密钥管理

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `api/client.py` | 405 | `AnthropicApiClient` — 主客户端, 流式消息协议 |
| `api/openai_client.py` | 267 | `OpenAICompatibleClient` — OpenAI 兼容层 |
| `api/provider.py` | 60 | `ProviderInfo`, `detect_provider()` — Provider 检测 |
| `api/registry.py` | 60 | API 客户端注册表 — 如何根据 profile 选择客户端 |
| `auth/manager.py` | 100 | `AuthManager` — 认证管理入口 |
| `auth/storage.py` | 200 | 密钥存储: 加密、存取、绑定 |
| `auth/flows.py` | 80 | 三种认证流: ApiKey, Browser, DeviceCode |

**阅读方法**:
1. 从 `registry.py` 入手 — 理解 profile → client 的映射
2. 精读 `client.py` 的 `stream_messages()` — 这是 Agent Loop 的上游
3. `auth/` 模块快速扫读, 重点理解 `store_credential` / `load_credential` 的加密存储

**验证**: 能解释当用户执行 `oh provider use kimi` 时, 系统如何选择 API 客户端并加载密钥

---

## Phase 7: Hook 与命令系统 (1-2h)

**目标**: 理解生命周期钩子和斜杠命令, 这是可扩展性的关键

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `hooks/events.py` | 30 | `HookEvent` 枚举: PreToolUse, PostToolUse, Stop |
| `hooks/executor.py` | 244 | `HookExecutor` — 执行钩子, 处理返回值 |
| `hooks/loader.py` | 80 | `load_hook_registry()` — 从 JSON 加载钩子配置 |
| `commands/registry.py` | 434 | `CommandRegistry` + ~30 个斜杠命令处理器 |

**阅读方法**:
1. `hooks/`: 理解事件类型 → 加载配置 → 执行 → 结果聚合
2. `commands/`: 看注册逻辑 + 2-3 个典型命令 (help, compact, skills), 其他略读

**验证**: 能解释 PreToolUse Hook 如何阻断一个工具调用

---

## Phase 8: 知识与记忆系统 (1-2h)

**目标**: 理解 Skills、Memory、CLAUDE.md 如何为 Agent 提供知识

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `skills/types.py` | 40 | `SkillDefinition` — Skill 数据结构 |
| `skills/loader.py` | 80 | `load_skill_registry()` — .md 文件解析 |
| `memory/manager.py` | 70 | 内存条目的增删查 |
| `memory/scan.py` | 40 | 内存文件扫描 |
| `memory/search.py` | 50 | 相关记忆检索 |
| `prompts/claudemd.py` | 60 | CLAUDE.md 发现与注入 |
| `prompts/system_prompt.py` | 110 | 系统提示词组装 — 理解知识如何注入 Agent |

**阅读方法**:
1. 从 `prompts/system_prompt.py` 入手 — 理解最终组装出的 system prompt 包含哪些部分
2. 逆向理解每个部分来自哪个模块 (Skills → skills/, 记忆 → memory/, 规则 → claudemd/)

**验证**: 能说出系统提示词的 5 个组成部分及其来源

---

## Phase 9: 高级特性 — Swarm, 服务, UI (3-4h)

**目标**: 理解多 Agent 协作、上下文压缩、前端渲染

### 9a: Swarm 多 Agent 系统

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `swarm/types.py` | 393 | 核心类型: `TeammateIdentity`, `SpawnConfig`, `SpawnResult` |
| `swarm/mailbox.py` | 523 | 邮箱通信: Agent 间消息传递 |
| `swarm/permission_sync.py` | 1169 | **最大单文件**: 文件 IPC 权限同步 |
| `swarm/team_lifecycle.py` | 830 | 团队生命周期管理 |
| `swarm/registry.py` | 411 | 后端注册 (tmux, iTerm2, in-process) |
| `swarm/in_process.py` | 460 | 进程内后端实现 |

**阅读策略**: swarm 是最复杂的模块 (~3800 行), 建议按以下顺序:
1. `types.py` → 理解数据结构
2. `mailbox.py` → 理解通信方式
3. `registry.py` → 理解后端选择
4. `team_lifecycle.py` → 理解团队管理
5. `permission_sync.py` → 理解权限同步 (最复杂, 最后看)
6. `in_process.py` → 理解进程内执行

### 9b: Services (上下文压缩等)

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `services/compact/__init__.py` | 1581 | **项目最大文件**: `compact_conversation()`, `auto_compact_if_needed()` — 重点看这两个主函数 |
| `services/session_storage.py` | 200 | 会话持久化 |
| `services/token_estimation.py` | 40 | Token 估算 |
| `services/cron_scheduler.py` | 359 | 定时任务调度 |

### 9c: UI 层

| 文件 | 行数 | 关注点 |
|------|------|--------|
| `ui/app.py` | 400 | `run_repl()`, `run_print_mode()` — 主循环 |
| `ui/textual_app.py` | 487 | Textual TUI 实现 |
| `ui/protocol.py` | 100 | UI 与后端的通信协议 |
| `ui/react_launcher.py` | 120 | React/Ink TUI 启动器 |

**验证**: 能解释一个子 Agent 如何被创建、与主 Agent 通信、以及权限如何同步

---

## Phase 10: 辅助模块速览 (1h)

这些模块体量小、职责单一, 快速扫读即可:

| 模块 | 文件数 | 行数 | 核心概念 |
|------|--------|------|----------|
| `bridge/` | 5 | 450 | 会话桥接 (ohmo 用) |
| `channels/` | 14 | 1000 | 消息通道 (Telegram, Slack, Discord 等) |
| `coordinator/` | 3 | 450 | Agent 定义与团队注册 |
| `tasks/` | 6 | 480 | 后台任务管理 |
| `mcp/` | 4 | 500 | Model Context Protocol 客户端 |
| `sandbox/` | 6 | 450 | Docker 沙箱 |
| `themes/` | 4 | 200 | 主题配置 |
| `keybindings/` | 5 | 150 | 快捷键 |
| `personalization/` | 4 | 200 | 个性化规则 |
| `output_styles/` | 2 | 60 | 输出样式 |
| `vim/` | 2 | 35 | Vim 模式 |
| `voice/` | 4 | 200 | 语音输入 |
| `state/` | 3 | 100 | 应用状态 |
| `utils/` | 5 | 280 | 工具函数 (fs, shell, network_guard) |

**验证**: 知道每个模块的职责和核心导出, 需要时能快速定位

---

## 附加: 测试驱动的理解法

每个 Phase 读完后, 用对应测试验证理解:

| Phase | 测试目录 | 推荐测试 |
|-------|----------|----------|
| 1 | `test_commands/cli.py` | CLI 入口测试 |
| 2 | `test_engine/query_engine.py` | 消息模型测试 |
| 3 | `test_engine/query_engine.py` | Agent Loop 测试 |
| 4 | `test_tools/core_tools.py`, `test_tools/bash_tool.py` | 工具注册和执行 |
| 5 | `test_permissions/checker.py` | 权限决策测试 |
| 6 | `test_api/client.py` | API 客户端测试 |
| 7 | `test_hooks/executor.py` | Hook 执行测试 |
| 8 | `test_prompts/system_prompt.py` | 提示词组装测试 |
| 9 | `test_swarm/`, `test_services/compact.py` | Swarm 和压缩测试 |

**实践建议**: 每读完一个模块, 跑一遍对应测试, 确保理解与实现一致:
```bash
uv run pytest tests/test_engine/ -q
```

---

## 时间估算汇总

| Phase | 内容 | 估计时间 | 累计 |
|-------|------|----------|------|
| 1 | 入口与启动 | 1-2h | 2h |
| 2 | 核心类型 | 1-2h | 4h |
| 3 | Agent Loop ⭐ | 3-4h | 8h |
| 4 | 工具系统 | 2-3h | 11h |
| 5 | 配置与权限 | 2h | 13h |
| 6 | API 与认证 | 2-3h | 16h |
| 7 | Hook 与命令 | 1-2h | 18h |
| 8 | 知识与记忆 | 1-2h | 20h |
| 9 | Swarm/Services/UI | 3-4h | 24h |
| 10 | 辅助模块 | 1h | 25h |

**总计: ~25 小时, 约 3-4 个工作日**

---

## 阅读优先级速查

如果时间有限, 按以下优先级读:

```
必读 (理解系统运转):
  engine/query.py → tools/base.py → permissions/checker.py → api/client.py → cli.py

推荐 (理解可扩展性):
  hooks/ → commands/ → prompts/ → skills/ → memory/

选读 (按需深入):
  swarm/ → services/compact → channels/ → bridge/ → mcp/
```