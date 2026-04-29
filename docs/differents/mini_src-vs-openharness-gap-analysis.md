# mini_src vs OpenHarness — 差距分析

> 生成日期: 2026-04-27
> 范围: mini_src (41 文件, 9 包) vs OpenHarness (~150 文件, 25+ 包)

---

## 1. 总览

| 维度 | mini_src | OpenHarness |
|------|----------|-------------|
| Python 文件数 | ~41 | ~150 |
| 包/模块数 | 9 (api, core, tools, memory, hooks, tasks, swarm, coordinator + 根) | 25+ (api, auth, bridge, channels, cli, commands, config, coordinator, engine, hooks, keybindings, mcp, memory, output_styles, permissions, personalization, platforms, plugins, prompts, sandbox, services, skills, state, themes, tools, ui, utils) |
| 代码行数 (估算) | ~3,500 | ~18,000+ |
| 入口点 | `__main__.py` CLI | `__main__.py` + `cli.py` + `ui/app.py` + `textual_app.py` |
| 配置方式 | 仅环境变量 | 环境变量 + JSON 配置文件 + CLI 参数 |
| 定位 | 最小可运行子集/实验 | 完整生产级 AI 编码助手 |

---

## 2. 逐能力域对比

### 2.1 API 客户端

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| Anthropic | ✅ AnthropicApiClient | ✅ 完整版 (含重试逻辑) |
| OpenAI 兼容 | ✅ OpenAICompatibleClient | ✅ openai_client.py |
| Codex | ❌ | ✅ codex_client.py — Codex 订阅支持 |
| Copilot | ❌ | ✅ copilot_client.py — GitHub Copilot 客户端 |
| 提供商注册表 | ❌ | ✅ registry.py — 统一提供商元数据 |
| 多 API Key 管理 | ❌ 单 env var | ✅ auth/storage.py — 凭据持久化 |
| 使用量追踪 | ✅ UsageSnapshot | ✅ 更详细的追踪 |

### 2.2 引擎核心

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| QueryEngine | ✅ | ✅ QueryEngine (更丰富) |
| 消息循环 | ✅ run_query | ✅ query.py |
| 事件系统 | ✅ stream_events | ✅ stream_events |
| 压缩 | ✅ 4 阶段 | ✅ 相同架构 |
| 成本追踪 | ✅ cost_tracker | ✅ 相同 |
| 消息模型 | ✅ Pydantic | ✅ Pydantic |
| 最大轮次限制 | ✅ | ✅ |

**差距**: 核心引擎几乎是 1:1 移植, 差距很小。OpenHarness 引擎集成更多外部服务 (日志, LSP, 会话存储)。

### 2.3 工具系统

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 工具注册表 | ✅ ToolRegistry | ✅ 完整版 |
| BaseTool | ✅ | ✅ |
| FileRead | ✅ | ✅ |
| FileWrite | ✅ | ✅ |
| FileEdit | ✅ | ✅ |
| Bash | ✅ | ✅ |
| Glob | ✅ | ✅ |
| Grep | ✅ | ✅ |
| AgentTool | ✅ | ✅ (更丰富) |
| SendMessage | ✅ | ✅ |
| TaskStop/Get/List/Output | ✅ | ✅ |
| **工具总数** | **12** | **40+** |
| 缺失工具 | — | LSP, WebFetch, WebSearch, NotebookEdit, TaskCreate/Update, CronCreate/Delete/List, Monitor, RemoteTrigger, AskUserQuestion, ScheduleWakeup, EnterPlanMode/ExitPlanMode, EnterWorktree/ExitWorktree, Skill 等 |

**差距**: OpenHarness 有 40+ 工具, mini_src 只有 12 个核心工具。缺失的多为 Claude Code 特有的编排工具 (计划模式, 工作树, 定时任务等)。

### 2.4 协调器 & 子代理

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 协调器模式 | ✅ | ✅ |
| 代理定义 | ✅ agent_definitions.py | ✅ (更丰富, 支持插件) |
| TeamRegistry | ✅ | ✅ |
| TaskNotification XML | ✅ | ✅ |
| 子进程后端 | ✅ SubprocessBackend | ✅ |
| 任务管理器 | ✅ BackgroundTaskManager | ✅ |
| 工作树隔离 | ❌ | ✅ 支持 |
| 代理颜色/努力值/记忆范围 | ❌ | ✅ |
| 插件代理定义 | ❌ | ✅ |
| inbox 邮箱系统 | ❌ | ✅ |
| tmux/iTerm2 面板 | ❌ | ✅ |

**差距**: 核心协调器功能已移植, 但缺少工作树隔离、邮箱系统和高级代理配置。足够基本使用。

### 2.5 配置系统

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 环境变量 | ✅ | ✅ |
| JSON 配置文件 | ❌ | ✅ settings.py — 多层配置 |
| 路径解析 | ❌ 无 | ✅ paths.py — 配置/数据目录管理 |
| 频道配置 | ❌ | ✅ schema.py — 通道配置模型 |
| CLI 参数 | ✅ (基础) | ✅ (完整, typer) |

**差距**: 较大。mini_src 仅靠环境变量, OpenHarness 有完整的 CLI > 环境变量 > 配置文件 > 默认值层级。

### 2.6 认证系统

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| API Key 读取 | ✅ | ✅ |
| 设备码 OAuth | ❌ | ✅ flows.py |
| 凭据存储 | ❌ | ✅ storage.py (文件 + 钥匙串) |
| GitHub Copilot 认证 | ❌ | ✅ copilot_auth.py |
| 认证管理器 | ❌ | ✅ manager.py |
| 外部 CLI 集成 | ❌ | ✅ external.py |

**差距**: 大。mini_src 只有最基础的 API key 读取, OpenHarness 有完整的 OAuth 框架。

### 2.7 用户界面

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 交互式 REPL | ✅ (基础 input()) | ✅ |
| Textual TUI | ❌ | ✅ textual_app.py |
| React 终端 UI | ❌ | ✅ react_launcher.py |
| JSON-lines 后端 | ❌ | ✅ backend_host.py |
| 富文本输出 | ❌ | ✅ output.py (rich + Markdown) |
| 权限对话框 | ❌ | ✅ permission_dialog.py |
| 结构化协议 | ❌ | ✅ protocol.py |
| 无头运行 | ❌ | ✅ runtime.py |

**差距**: 巨大。mini_src 只有最基本的 `input()` REPL, OpenHarness 有完整的 TUI (Textual + React 双模式)。

### 2.8 工具 — 完整列表

**OpenHarness 有但 mini_src 没有的工具 (约 30 个)**:

| 类别 | 缺失工具 |
|------|----------|
| **计划/架构** | EnterPlanMode, ExitPlanMode |
| **工作树** | EnterWorktree, ExitWorktree |
| **任务管理** | TaskCreate, TaskUpdate |
| **定时任务** | CronCreate, CronDelete, CronList |
| **监控** | Monitor |
| **远程触发器** | RemoteTrigger |
| **代码智能** | LSP (goToDefinition, findReferences 等 6 个子操作) |
| **网络** | WebFetch, WebSearch |
| **笔记本** | NotebookEdit |
| **对话** | AskUserQuestion |
| **调度** | ScheduleWakeup |
| **技能** | Skill |
| **文件/编辑** | FileEdit (差异版), FileWrite (差异版) |
| **其他** | 各渠道特有的输出格式化工具 |

**mini_src 独有的工具**: 无 (所有 mini_src 工具都是 OpenHarness 的子集)。

### 2.9 对话通道

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 终端 REPL | ✅ | ✅ |
| Slack | ❌ | ✅ |
| Discord | ❌ | ✅ |
| Telegram | ❌ | ✅ |
| 钉钉 | ❌ | ✅ |
| 飞书 | ❌ | ✅ |
| QQ | ❌ | ✅ |
| Matrix | ❌ | ✅ |
| WhatsApp | ❌ | ✅ |
| Email | ❌ | ✅ |
| Mochat | ❌ | ✅ |
| 消息总线 | ❌ | ✅ MessageBus |
| 通道适配器 | ❌ | ✅ ChannelBridge |

**差距**: 巨大。10 个聊天通道是 OpenHarness 的核心功能之一, mini_src 完全没有。

### 2.10 权限 & 安全

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 权限检查 | ❌ | ✅ checker.py |
| 权限模式 | ❌ | ✅ PermissionMode 枚举 |
| 沙箱 (Docker) | ❌ | ✅ sandbox/ (docker_backend, path_validator, session) |
| 网络防护 | ❌ | ✅ network_guard.py |
| 路径验证 | ❌ | ✅ path_validator.py |

**差距**: 大。mini_src 完全信任所有工具调用。

### 2.11 记忆系统

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| MemoryHeader | ✅ | ✅ |
| 路径解析 | ✅ paths.py | ✅ |
| 扫描 | ✅ scan.py | ✅ |
| 搜索 | ✅ search.py | ✅ |
| memdir | ✅ memdir.py | ✅ |
| 管理器 CRUD | ✅ manager.py | ✅ |

**差距**: 几乎 1:1 移植, 功能对等。

### 2.12 钩子系统

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| HookEvent 枚举 | ✅ (仅 COMPACT) | ✅ (完整事件集) |
| HookResult | ✅ | ✅ |
| Hook 定义模型 | ✅ schemas.py | ✅ |
| 执行器 | ✅ executor.py | ✅ |
| 加载器 | ✅ loader.py | ✅ |
| 热重载 | ❌ | ✅ hot_reload.py |
| 事件种类 | PRE_COMPACT, POST_COMPACT | 完整事件生命周期 |

**差距**: mini_src 的钩子系统是功能子集, 仅支持压缩相关事件。OpenHarness 有完整的钩子生命周期。

### 2.13 配置缺失的完整模块

**以下 OpenHarness 模块在 mini_src 中完全不存在**:

| 模块 | 文件数 | 说明 |
|------|--------|------|
| `auth/` | 5 | OAuth 认证框架 |
| `bridge/` | 4 | 桥接会话管理 |
| `channels/` | 16 | 10 个聊天通道实现 |
| `cli.py` | 1 | typer CLI 入口 |
| `commands/` | 1 | 斜杠命令注册表 |
| `config/` | 3 | 完整多层配置系统 |
| `keybindings/` | 4 | 键盘绑定系统 |
| `mcp/` | 3 | MCP 协议客户端 |
| `output_styles/` | 1 | 输出样式 |
| `permissions/` | 2 | 权限检查 |
| `personalization/` | 3 | 本地规则学习 |
| `platforms.py` | 1 | 平台检测 |
| `plugins/` | 5 | 插件系统 |
| `prompts/` | 4 | 系统提示构建 |
| `sandbox/` | 5 | Docker 沙箱 |
| `services/` | 13 | 后台服务 (cron, LSP, OAuth, 日志) |
| `skills/` | 4 | 技能系统 |
| `state/` | 2 | 应用状态管理 |
| `themes/` | 3 | UI 主题 |
| `ui/` | 10 | 用户界面 (Textual + React) |
| `utils/` | 3 | 工具函数 |

### 2.14 代码质量基础设施

| 项目 | mini_src | OpenHarness |
|------|----------|-------------|
| 类型标注 | ✅ 完整 | ✅ 完整 |
| 测试 | ❌ 无 | ✅ tests/ 目录 |
| 代码格式化 | ❌ | ✅ pyproject.toml 配置 |
| CI/CD | ❌ | ✅ GitHub Actions |
| pyproject.toml | ❌ | ✅ |
| 包发布配置 | ❌ | ✅ |

---

## 3. 优先级演进建议

### P0 — 核心差距 (影响基本使用)

| 模块 | 理由 |
|------|------|
| **配置系统** | 仅环境变量不够, 需要 JSON 配置文件支持 |
| **测试** | 无测试, 无法保证重构安全 |
| **工具补齐** | 至少增加 WebFetch, WebSearch, TaskCreate/Update |

### P1 — 重要功能 (提升开发体验)

| 模块 | 理由 |
|------|------|
| **Sandbox** | Docker 隔离执行对安全至关重要 |
| **Permissions** | 工具调用权限管控 |
| **Platforms** | 跨平台兼容性 |
| **Utils** | 文件锁、原子写入等基础设施 |

### P2 — 增强功能 (面向生产)

| 模块 | 理由 |
|------|------|
| **Auth** | OAuth 设备流、凭据存储 |
| **Plugins** | 扩展性 |
| **Skills** | 可复用技能 |
| **MCP** | 模型上下文协议 |

### P3 — 丰富生态 (完整复制)

| 模块 | 理由 |
|------|------|
| **Channels** | 10 个聊天通道 |
| **UI** | Textual TUI |
| **Services** | Cron, LSP, 日志服务 |
| **Themes** | 主题系统 |
| **Personalization** | 本地规则学习 |
| **Commands** | 斜杠命令 |
| **Keybindings** | 键盘绑定 |
| **Bridge** | 桥接会话 |

---

## 4. 代码复用策略

对于 P0 和 P1 模块, 建议直接复制 OpenHarness 代码并精简:

| 模块 | 策略 |
|------|------|
| `config/settings.py` | 提取核心类, 去掉频道相关配置 |
| `permissions/checker.py` | 直接移植, 约 100 行 |
| `sandbox/docker_backend.py` | 直接移植 |
| `utils/fs.py` | 直接移植 (约 30 行) |
| `platforms.py` | 直接移植 (约 80 行) |
| 测试框架 | 从 `tests/` 复制最小测试集 |

对于 P2/P3 模块, 建议按需移植而非整体复制。

---

## 5. 已移植模块状态

| 模块 | 移植状态 | 覆盖度 |
|------|----------|--------|
| `core/engine` | ✅ 完整移植 | ~100% |
| `core/events` | ✅ 完整移植 | ~100% |
| `core/messages` | ✅ 完整移植 | ~100% |
| `core/compact` | ✅ 完整移植 | ~100% |
| `core/loop` | ✅ 完整移植 | ~100% |
| `core/cost_tracker` | ✅ 完整移植 | ~100% |
| `api/client` | ✅ 完整移植 | ~100% |
| `tools/base` | ✅ 完整移植 | ~100% |
| `tools/builtin` | ✅ 12 个基础工具 | 30% (共 40+) |
| `memory/` | ✅ 完整移植 | ~100% |
| `hooks/` | ✅ 部分移植 | ~30% (仅 COMPACT 事件) |
| `tasks/` | ✅ 完整移植 | ~100% |
| `swarm/` | ✅ 完整移植 | ~100% (不含邮箱系统) |
| `coordinator/` | ✅ 完整移植 | ~80% (不含插件定义) |
| `worker.py` | ✅ 完整移植 | ~100% |
| `config.py` | ⚠️ 基础移植 | ~20% (仅环境变量) |

---

## 6. 总结

mini_src 当前约 **3,500 行代码**, 覆盖了 OpenHarness (~18,000 行) 约 **20%** 的功能。核心引擎、记忆系统、工具框架、协调器/子代理已完成移植。

主要差距在于:
1. **配置系统** — 需要从仅环境变量升级到文件配置
2. **安全层** — 权限检查 + Docker 沙箱缺失
3. **工具补齐** — 关键工具 (WebFetch, WebSearch, 任务管理) 缺失
4. **测试** — 完全没有测试覆盖
5. **UI** — 仅有基础 REPL, 无 Textual TUI
6. **通信通道** — 10 个聊天通道均未移植

按优先级的推荐: 配置系统 → 安全层 → 工具补齐 → 测试 → 后续增强功能。
