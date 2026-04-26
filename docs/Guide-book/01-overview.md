# 第 1 章：概述与架构全景

## 1.1 OpenHarness 解决什么问题

OpenHarness 是一个 **开源 AI Agent Harness（智能体基础设施框架）**。它解决的问题可以归结为一句话：

> **LLM 本身只是一个"大脑"，它需要"身体"才能与世界交互。OpenHarness 就是那个"身体"。**

具体来说，它面临的核心挑战是：

### 1.1.1 从"对话"到"行动"

一个普通的 LLM 只能生成文本。要让 AI 真正帮助开发工作，它需要能够：

- **读取文件**：理解项目代码
- **写入文件**：修改代码、创建文件
- **执行命令**：运行测试、启动服务
- **搜索代码**：查找定义、引用
- **访问网络**：获取文档、调用 API

OpenHarness 通过**工具系统（Tool System）** 将 LLM 的文本输出转化为实际的操作。

### 1.1.2 多 Provider 兼容

开发者使用不同的 LLM 提供商（Anthropic Claude、OpenAI GPT、DeepSeek、本地模型等）。OpenHarness 通过统一的 API 抽象层，让同一个 Agent 可以在不同后端之间切换。

### 1.1.3 持久化上下文

普通聊天没有记忆。OpenHarness 提供：
- **项目记忆**：跨会话持久化知识
- **对话压缩**：在 Token 预算内保持上下文
- **会话恢复**：随时恢复之前的会话

### 1.1.4 安全控制

AI Agent 可以执行任意命令和修改文件——这带来了安全风险。OpenHarness 提供：
- **多层权限模型**：从"完全放行"到"计划模式"
- **敏感路径保护**：自动阻止对 `~/.ssh`、`~/.aws` 等路径的操作
- **可编程 Hook**：在工具执行前后注入自定义逻辑

### 1.1.5 可扩展性

不同场景需要不同的能力。OpenHarness 的插件和技能系统允许：
- 加载社区贡献的 Skills（知识包）
- 安装第三方 Plugins（命令、Hook、Agent）
- 集成 MCP 服务器（外部工具协议）

## 1.2 核心设计理念

### 1.2.1 Harness = Tools + Knowledge + Observation + Action + Permissions

```
Agent = LLM + Harness
Harness = Tools + Knowledge + Observation + Action + Permissions
```

- **Tools（工具）**：LLM 可以调用的能力（读文件、写文件、执行命令等）
- **Knowledge（知识）**：系统提示词、项目规则、记忆
- **Observation（观察）**：工具执行结果、环境信息
- **Action（行动）**：LLM 决定调用哪个工具
- **Permissions（权限）**：安全边界，决定什么可以做

### 1.2.2 流式事件驱动

整个系统围绕**异步生成器（AsyncIterator）** 构建：

```python
async for event in engine.submit_message(prompt):
    # event 可以是文本增量、工具调用开始/完成、错误等
    await render_event(event)
```

这种设计使得：
- UI 层可以实时渲染流式响应
- 工具执行结果可以即时推送
- 错误处理可以在事件层面精细化控制

### 1.2.3 协议化多态

关键接口定义为 **Protocol**（Python 结构化子类型）：

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request) -> AsyncIterator[ApiStreamEvent]: ...
```

任何实现该协议的类都可以作为 API 客户端，无需继承。这使得 Anthropic、OpenAI、Codex、Copilot 等客户端可以透明替换。

### 1.2.4 组合优于继承

系统倾向于**小模块 + 注册中心**的模式：

- `ToolRegistry`：按名称注册和查找工具
- `SkillRegistry`：按名称注册和查找技能
- `ProviderSpec`：30+ Provider 的元数据注册表
- `CommandRegistry`：斜杠命令注册
- `HookRegistry`：生命周期 Hook 注册

## 1.3 系统架构总览

### 1.3.1 高层架构

```
┌─────────────────────────────────────────────────────────────┐
│                        UI Layer                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ Textual  │  │  React   │  │ Headless │  │  Channel     │ │
│  │   TUI    │  │   TUI    │  │  (Print) │  │  Bridge      │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘ │
│       │             │             │               │         │
└───────┼─────────────┼─────────────┼───────────────┼─────────┘
        │             │             │               │
        ▼             ▼             ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Runtime / handle_line                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    QueryEngine                           │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │ │
│  │  │  Tool    │  │  Permission │  │  Hook   │              │ │
│  │  │ Registry │  │  Checker  │  │ Executor│              │ │
│  │  └────┬─────┘  └──────────┘  └──────────┘              │ │
│  │       │                                                 │ │
│  │       ▼                                                 │ │
│  │  ┌──────────┐  ┌──────────┐                             │ │
│  │  │   run_query()    │                                   │ │
│  │  └────┬─────┘                                           │ │
│  └───────┼─────────────────────────────────────────────────┘ │
└──────────┼──────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│                   API Layer                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │Anthropic │  │  OpenAI  │  │  Codex   │  │   Copilot    │ │
│  │  Client  │  │  Client  │  │  Client  │  │   Client     │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 1.3.2 模块全景

| 子系统 | 职责 | 核心文件 |
|--------|------|---------|
| **engine/** | 会话循环、消息模型、流式事件 | `query.py`, `query_engine.py`, `messages.py` |
| **api/** | LLM 客户端、Provider 注册、错误类型 | `client.py`, `openai_client.py`, `registry.py` |
| **tools/** | 工具定义、注册中心、30+ 内置工具 | `base.py`, `__init__.py` |
| **memory/** | 持久化记忆、搜索、管理 | `manager.py`, `memdir.py`, `search.py` |
| **permissions/** | 权限检查、敏感路径保护 | `checker.py`, `modes.py` |
| **hooks/** | 生命周期事件、Hook 执行 | `events.py`, `executor.py`, `loader.py` |
| **plugins/** | 插件发现、加载、管理 | `loader.py`, `installer.py`, `schemas.py` |
| **skills/** | 技能定义、注册、加载 | `registry.py`, `loader.py`, `types.py` |
| **mcp/** | MCP 客户端、服务器管理 | `client.py`, `config.py`, `types.py` |
| **channels/** | 消息总线、多平台聊天适配 | `bus/queue.py`, `adapter.py`, `impl/` |
| **sandbox/** | Docker 沙箱、命令隔离 | `docker_backend.py`, `adapter.py` |
| **auth/** | 认证流程、凭据管理 | `flows.py`, `manager.py`, `storage.py` |
| **config/** | 设置模型、Profile 管理 | `settings.py`, `paths.py` |
| **coordinator/** | Agent 定义、团队管理、协调模式 | `coordinator_mode.py`, `agent_definitions.py` |
| **prompts/** | 系统提示词组装、CLAUDE.md | `system_prompt.py`, `context.py`, `claudemd.py` |
| **ui/** | 用户界面层 | `app.py`, `runtime.py`, `backend_host.py` |
| **commands/** | 斜杠命令系统 | `registry.py` |
| **services/** | 支持服务（Cron, LSP, 日志等） | `cron.py`, `session_backend.py`, `compact/` |
| **bridge/** | 子进程管理 | `session_runner.py`, `manager.py` |

## 1.4 本章小结

OpenHarness 的核心贡献是**将 LLM 从对话模型转变为可行动的 Agent**。它通过五个核心支柱（工具、知识、观察、行动、权限）构建了一个完整的基础设施，覆盖了从 API 调用到用户交互的全链路。

> 下一章：[快速上手与核心流程](02-quickstart-core-loop.md) —— 追踪一条用户输入从提交到最终响应的完整旅程。
