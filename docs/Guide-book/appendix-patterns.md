# 附录：关键设计模式总结

## 全书设计模式索引

OpenHarness 使用了一系列经典设计模式。本附录总结了所有模式及其在源码中的位置。

## A.1 创建型模式

### 工厂方法

| 位置 | 描述 |
|------|------|
| `create_default_tool_registry()` | 创建并注册所有内置工具 |
| `build_runtime()` | 构建完整的 RuntimeBundle |
| `build_ohmo_system_prompt()` | 构建 ohmo 系统提示词 |

### 单例

| 位置 | 描述 |
|------|------|
| `get_bridge_manager()` | 全局唯一的 BridgeSessionManager |
| `get_docker_sandbox()` | 全局唯一的 Docker 沙箱会话 |

## A.2 结构型模式

### 适配器

| 位置 | 描述 |
|------|------|
| `McpToolAdapter` | 将 MCP 工具适配为 BaseTool |
| `ChannelBridge` | 将 MessageBus 桥接到 QueryEngine |
| `BaseChannel` 子类 | 各自平台 API → 统一 channel 接口 |
| `CodexApiClient` | 将 Codex API 适配为 SupportsStreamingMessages |

### 协议（Protocol）

Python Protocol 在多个地方替代了传统的接口继承：

| 位置 | 描述 |
|------|------|
| `SupportsStreamingMessages` | 所有 API 客户端的统一协议 |
| `SessionBackend` | 会话管理的统一协议 |

### 组合

| 位置 | 描述 |
|------|------|
| `RuntimeBundle` | 组合所有运行时对象的容器 |
| `ContentBlock` 联合类型 | `TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock` |

## A.3 行为型模式

### 策略

| 位置 | 描述 |
|------|------|
| 四个 API 客户端 | 同一 `stream_message` 接口的不同实现 |
| 三种认证流程 | `ApiKeyFlow`, `DeviceCodeFlow`, `BrowserFlow` |
| `PermissionMode` | DEFAULT, PLAN, FULL_AUTO 三种安全策略 |

### 观察者 / 发布-订阅

| 位置 | 描述 |
|------|------|
| `MessageBus`（asyncio.Queue） | 频道 ↔ 引擎的解耦通信 |
| `HookExecutor` | 生命周期事件的发布-订阅 |
| `StreamEvent` 生成器 | 引擎 → UI 的事件流 |

### 责任链

| 位置 | 描述 |
|------|------|
| `PermissionChecker.evaluate()` | 敏感路径 → 拒绝规则 → 允许规则 → 模式判断 |
| `HookExecutor.execute()` | 同一事件下多个 Hook 的顺序执行 |

### 模板方法

| 位置 | 描述 |
|------|------|
| `run_query()` | 定义 Agent Loop 的骨架，工具执行等步骤可子类化扩展 |
| `BaseTool.execute()` | 定义工具执行的模板：验证 → 执行 → 结果 |

### 命令

| 位置 | 描述 |
|------|------|
| `CommandRegistry` | 斜杠命令的注册与执行 |
| `AgentDefinition` | Agent 行为作为可执行的命令式定义 |

## A.4 架构模式

### 注册中心

这是 OpenHarness 中使用最广泛的模式：

| 注册中心 | 注册内容 | 用途 |
|---------|---------|------|
| `ToolRegistry` | 名称 → BaseTool | 运行中工具查找 |
| `SkillRegistry` | 名称 → SkillDefinition | 技能管理 |
| `CommandRegistry` | 名称 → SlashCommand | 斜杠命令 |
| `HookRegistry` | 事件 → [HookDefinition] | 生命周期 Hook |
| `TeamRegistry` | 名称 → TeamRecord | 团队管理 |
| `ProviderSpec` | 30+ Provider 元数据 | Provider 检测和配置 |

### 流式事件管道（Pipeline）

```
User Input
  → QueryEngine.submit_message()     → StreamEvent 生成器
    → handle_line() / ChannelBridge   → 事件循环
      → UI 渲染 / 消息发送
```

### 模块化分层

```
UI 层 (app.py, textual_app.py, react_launcher.py)
    │
运行时层 (runtime.py, handle_line())
    │
引擎层 (query_engine.py, query.py)
    │
API 层 (client.py, openai_client.py, codex_client.py)
    │
LLM Provider (Anthropic, OpenAI, DeepSeek, ...)
```

### 服务定位器

`RuntimeBundle` 是一个服务定位器，持有：

- `engine: QueryEngine`
- `tool_registry: ToolRegistry`
- `commands: CommandRegistry`
- `hook_executor: HookExecutor`
- `mcp_manager: McpClientManager`
- `session_backend: SessionBackend`
- 各属性访问方法

## A.5 关键设计决策

### 1. 为什么使用 Protocol 而非 ABC？

Python Protocol 允许**结构子类型化**——任何具有 `stream_message` 方法的类都可以是 API 客户端，无需继承。这使得新增 Provider 更加灵活，测试更容易 mock。

### 2. 为什么工具使用 Pydantic？

Pydantic 实现了**声明式输入验证**：
- 自动生成 JSON Schema（LLM 理解参数格式）
- 运行时类型检查
- 清晰的错误消息
- 与 FastAPI/Pydantic 生态系统兼容

### 3. 为什么是 asyncio？

OpenHarness 涉及大量 I/O 操作：
- 多个 API 请求（可并发执行工具）
- 多个 MCP 连接
- 多个聊天频道
- 流式事件

asyncio 使得**高效并发**成为可能，同时避免了多线程的复杂性和 GIL 限制。

### 4. 为什么使用事件流而非回调？

异步生成器（`AsyncIterator`）提供了：
- **自然的中止语义**：`return` 或 `break` 即可停止
- **背压支持**：消费者慢时自动减速
- **资源安全**：`async for` 确保正确的资源释放
- **可组合性**：`async for` + `yield` 可无限组合

### 5. 为什么使用不可变数据？

虽然代码中不完全遵循不可变性，但消息和事件被设计为 `@dataclass(frozen=True)`：
- 防止意外的副作用
- 简化调试
- 支持安全的并发访问

## A.6 贡献指南总结

### 添加新工具

```python
from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolResult, ToolExecutionContext

class MyToolInput(BaseModel):
    query: str = Field(description="Search query")

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    input_model = MyToolInput

    async def execute(self, arguments: MyToolInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Result: {arguments.query}")
```

### 添加新 Provider

1. 在 `api/registry.py` 中添加 `ProviderSpec`
2. 设置 `backend_type`（anthropic / openai_compat / copilot）
3. 配置检测关键词
4. 如需要特殊客户端：实现 `SupportsStreamingMessages`

### 添加新频道

1. 继承 `channels/impl/base.py` 中的 `BaseChannel`
2. 实现 `start()`, `stop()`, `send()`
3. 在 `ChannelManager._create_channel()` 中注册

### 添加新 Hook 类型

1. 在 `hooks/schemas.py` 中添加新的 HookDefinition
2. 在 `hooks/executor.py` 的 `_run_hook()` 中添加处理分支
