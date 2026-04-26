# 第 2 章：快速上手与核心流程

本章追踪一条用户输入从提交到最终响应的**完整旅程**，帮助读者建立对整个系统的整体认知。

## 2.1 启动入口

### 2.1.1 CLI 入口

用户运行 `oh` 命令时，入口在 `src/openharness/__main__.py`，调用 `cli:app`。

核心流程在 **`ui/runtime.py` 的 `handle_line()`** 函数中，这个函数处理用户输入的每一行文本。

### 2.1.2 RuntimeBundle：依赖容器

`build_runtime()` 创建 `RuntimeBundle`——一个包含所有运行时对象的"服务容器"：

```
RuntimeBundle
├── engine: QueryEngine          ← 会话循环引擎
├── tool_registry: ToolRegistry   ← 工具注册中心
├── commands: CommandRegistry    ← 斜杠命令
├── hook_executor: HookExecutor  ← 生命周期 Hook
├── mcp_manager: McpClientManager ← MCP 连接
├── session_backend              ← 会话持久化
├── app_state                    ← UI 状态
└── current_settings()            ← 当前配置
```

## 2.2 完整请求链路

### 2.2.1 步骤 1：用户输入处理

```
用户输入 "refactor this function"
        │
        ▼
handle_line(bundle, line)        ← ui/runtime.py:490
        │
        ├── 是斜杠命令? → 查找 CommandRegistry → 执行命令处理器 → 返回
        │
        └── 是普通文本 → 继续引擎链路
```

### 2.2.2 步骤 2：构造 QueryContext

```python
# query_engine.py:149
async def submit_message(self, prompt):
    user_message = ConversationMessage.from_user_text(prompt)
    self._messages.append(user_message)
    context = QueryContext(
        api_client=self._api_client,
        tool_registry=self._tool_registry,
        permission_checker=self._permission_checker,
        model=self._model,
        system_prompt=self._system_prompt,
        max_turns=self._max_turns,
        ...
    )
    async for event, usage in run_query(context, query_messages):
        yield event  # 流式事件 → UI 渲染
```

### 2.2.3 步骤 3：Agent Loop（核心循环）

`run_query()` 在 `engine/query.py:406` 实现，是**整个系统的核心**：

```
run_query(context, messages)
    │
    ├─ while turn_count < max_turns:
    │   │
    │   ├─ 1. 自动压缩检查（Token 预算）
    │   │
    │   ├─ 2. 调用 API 客户端
    │   │   context.api_client.stream_message(request)
    │   │       │
    │   │       ├─ 流式输出文本 → yield AssistantTextDelta
    │   │       ├─ 重试事件 → yield ApiRetryEvent
    │   │       └─ 完成事件 → final_message
    │   │
    │   ├─ 3. 处理异常
    │   │   ├─ PromptTooLong → 反应式压缩 → 重试
    │   │   ├─ NetworkError → yield ErrorEvent
    │   │   └─ API Error → yield ErrorEvent
    │   │
    │   ├─ 4. 检查消息有效性
    │   │
    │   ├─ 5. 追加模型响应到历史
    │   │   yield AssistantTurnComplete
    │   │
    │   ├─ 6. 有工具调用?
    │   │   ├─ 否 → return（模型回答完毕）
    │   │   └─ 是 → 执行工具 → 继续循环
    │   │       ├─ 单个工具 → 顺序执行
    │   │       └─ 多个工具 → 并发执行 (asyncio.gather)
    │   │
    │   └─ 7. tool results → 追加到 messages → 回到步骤 2
    │
    └─ MaxTurnsExceeded
```

### 2.2.4 步骤 4：工具执行

工具执行在 `_execute_tool_call()` 中完成（`query.py:654`）：

```
_execute_tool_call(context, tool_name, tool_use_id, tool_input)
    │
    ├─ 1. 执行 PRE_TOOL_USE Hook
    │   └─ Hook 阻止？→ 返回错误 ToolResultBlock
    │
    ├─ 2. 查找工具
    │   └─ 未找到？→ 返回未知工具错误
    │
    ├─ 3. 验证输入（Pydantic model）
    │   └─ 无效？→ 返回验证错误
    │
    ├─ 4. 权限检查
    │   ├─ 允许？→ 继续
    │   ├─ 需要确认？→ 提示用户
    │   └─ 拒绝？→ 返回权限错误
    │
    ├─ 5. 执行工具
    │   └─ await tool.execute(parsed_input, context)
    │
    ├─ 6. 记录工具元数据（跟踪读过的文件、调用的技能等）
    │
    └─ 7. 执行 POST_TOOL_USE Hook
```

### 2.2.5 步骤 5：事件流渲染

整个 `run_query()` 是一个异步生成器，产生 **`StreamEvent`** 对象：

```python
# stream_events.py
StreamEvent = (
    AssistantTextDelta      # 模型输出的文本片段
    | AssistantTurnComplete # 完整的一次 Assistant 回复
    | ToolExecutionStarted  # 工具开始执行
    | ToolExecutionCompleted # 工具执行完成
    | ErrorEvent            # 错误
    | StatusEvent           # 状态消息
    | CompactProgressEvent  # 压缩进度
)
```

UI 层通过 switch-case 处理这些事件：

```python
# textual_app.py:360
if isinstance(event, ToolExecutionStarted):    # 显示 "tool> tool_name ..."
if isinstance(event, ToolExecutionCompleted):  # 显示 "tool-result> ..." 或 "tool-error> ..."
if isinstance(event, ErrorEvent):              # 显示 "error> ..."
if isinstance(event, AssistantTextDelta):      # 追加文本到当前回复
if isinstance(event, StatusEvent):             # 显示 "system> ..."
```

## 2.3 关键源码路径总结

| 步骤 | 文件 | 关键函数 |
|------|------|---------|
| 入口 | `__main__.py` | CLI 启动 |
| 构建运行时 | `ui/runtime.py` | `build_runtime()`, `handle_line()` |
| 提交消息 | `engine/query_engine.py` | `submit_message()` |
| Agent Loop | `engine/query.py` | `run_query()` |
| API 调用 | `api/client.py` | `stream_message()` |
| 工具执行 | `engine/query.py` | `_execute_tool_call()` |
| 事件定义 | `engine/stream_events.py` | `StreamEvent` 联合类型 |
| UI 渲染 | `ui/textual_app.py` | 事件处理循环 |

## 2.4 本章小结

一条用户输入的完整旅程经过：**CLI → RuntimeBundle → QueryEngine → run_query (Agent Loop) → API Client → 工具执行 → 事件流 → UI 渲染**。每个环节都是异步的、流式的、可观察的。

> 下一章：[API 层与多 Provider 支持](03-api-layer.md) —— 深入理解 LLM API 调用的抽象与实现。
