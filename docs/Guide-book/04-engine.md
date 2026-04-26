# 第 4 章：会话引擎

## 4.1 解决的问题

会话引擎是 OpenHarness 的"大脑"——它负责编排从用户输入到模型输出的完整交互循环，包括消息管理、工具调度、压缩控制和状态追踪。

## 4.2 消息模型

### 4.2.1 ConversationMessage

`engine/messages.py` 定义了对话核心数据结构：

```python
@dataclass
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: list[ContentBlock]

ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock
```

消息模型的精妙之处：

1. **User 消息可以包含 ToolResult**：这是因为在 Anthropic API 中，tool_result 属于 user 角色的内容块
2. **ContentBlock 是带判别器的联合类型**：通过 `isinstance` 检查和序列化，支持扩展
3. **不可变性**：操作消息时创建新副本而非修改原对象

**关键辅助函数**：

```python
assistant_message_from_api(response)  # 从 Anthropic SDK 响应解析
serialize_content_block(block)        # 序列化为 API 参数格式
ConversationMessage.from_user_text("hello")  # 从纯文本创建
```

### 4.2.2 流式事件

`engine/stream_events.py` 定义了引擎产生的事件类型：

| 事件 | 含义 | 字段 |
|------|------|------|
| `AssistantTextDelta` | 模型输出文本片段 | `text: str` |
| `AssistantTurnComplete` | 完整 Assistant 回复 | `message`, `usage` |
| `ToolExecutionStarted` | 工具开始执行 | `tool_name`, `tool_input` |
| `ToolExecutionCompleted` | 工具执行完成 | `tool_name`, `output`, `is_error` |
| `ErrorEvent` | 错误 | `message`, `recoverable` |
| `StatusEvent` | 系统状态 | `message` |
| `CompactProgressEvent` | 压缩进度 | `phase`, `trigger`, `message` |

### 4.2.3 UsageSnapshot

`api/usage.py`：

```python
@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
```

## 4.3 Query Engine（QueryEngine）

### 4.3.1 QueryEngine 类

`engine/query_engine.py:19` 是高层 API，负责：

1. **管理对话历史**：`_messages` 列表持久化会话状态
2. **提交消息**：`submit_message()` 追加用户消息 → 调用 `run_query()`
3. **继续会话**：`continue_pending()` 在不追加消息的情况下恢复循环
4. **属性管理**：模型、系统提示词、API 客户端、权限检查器的动态更新

### 4.3.2 QueryContext

`engine/query.py:88` 是一个参数对象，封装一次 `run_query()` 调用所需的所有依赖：

```python
@dataclass
class QueryContext:
    api_client: SupportsStreamingMessages
    tool_registry: ToolRegistry
    permission_checker: PermissionChecker
    cwd: Path
    model: str
    system_prompt: str
    max_tokens: int
    context_window_tokens: int | None
    auto_compact_threshold_tokens: int | None
    max_turns: int | None
    permission_prompt: PermissionPrompt | None
    ask_user_prompt: AskUserPrompt | None
    hook_executor: HookExecutor | None
    tool_metadata: dict[str, object] | None
    verbose: bool
```

## 4.4 Agent Loop 详解

### 4.4.1 循环结构

`run_query()`（`engine/query.py:406`）的完整逻辑：

```python
async def run_query(context, messages):
    compact_state = AutoCompactState()
    reactive_compact_attempted = False
    
    while turn_count < max_turns:
        # 1. 自动压缩检查
        async for event, usage in _stream_compaction(trigger="auto"):
            yield event, usage
        
        # 2. 调用 API
        try:
            async for event in api_client.stream_message(request):
                if isinstance(event, ApiTextDeltaEvent):
                    yield AssistantTextDelta(...)
                elif isinstance(event, ApiRetryEvent):
                    yield StatusEvent(...)
                elif isinstance(event, ApiMessageCompleteEvent):
                    final_message = event.message
                    usage = event.usage
        except Exception as exc:
            # 3. 异常处理
            if prompt_too_long:
                # 反应式压缩 → 重试
                continue
            if network_error:
                yield ErrorEvent("Network error: ...")
            else:
                yield ErrorEvent(f"API error: {error_msg}")
            return
        
        # 4. 处理空消息
        if final_message.is_effectively_empty():
            yield ErrorEvent("empty assistant message")
            return
        
        # 5. 追加到历史
        messages.append(final_message)
        yield AssistantTurnComplete(...)
        
        # 6. 检查是否需要执行工具
        if not final_message.tool_uses:
            return  # 模型回答完毕
        
        # 7. 执行工具
        if len(tool_calls) == 1:
            yield ToolExecutionStarted(...)
            result = await _execute_tool_call(...)
            yield ToolExecutionCompleted(...)
        else:
            # 并发执行
            for tc in tool_calls:
                yield ToolExecutionStarted(...)
            results = await asyncio.gather(
                *[_run(tc) for tc in tool_calls], 
                return_exceptions=True
            )
            for tc, result in zip(tool_calls, results):
                yield ToolExecutionCompleted(...)
        
        # 8. 追加工具结果 → 继续循环
        messages.append(ConversationMessage(role="user", content=tool_results))
    
    raise MaxTurnsExceeded(max_turns)
```

### 4.4.2 关键设计决策

**1. 单工具 vs 多工具的执行策略**

- **单工具**：顺序执行，立即流式输出事件
- **多工具**：并发执行（`asyncio.gather`），使用 `return_exceptions=True` 防止单工具失败导致其他工具被取消

**2. prompt too long 的两级处理**

- **自动压缩**：每次循环开始前检查 Token 预算，超阈值则自动压缩
- **反应式压缩**：API 返回 prompt too long 错误时，强制压缩后重试

**3. MaxTurnsExceeded**

当循环次数超过 `max_turns` 限制时抛出，由上层（`handle_line`）捕获并展示：

```python
except MaxTurnsExceeded as exc:
    await print_system(f"Stopped after {exc.max_turns} turns (max_turns).")
```

## 4.5 工具执行细节

### 4.5.1 _execute_tool_call()

`engine/query.py:654` 负责单次工具执行的完整流程：

```python
async def _execute_tool_call(context, tool_name, tool_use_id, tool_input):
    # 1. Pre-Tool-Use Hook
    if context.hook_executor:
        result = await context.hook_executor.execute(PRE_TOOL_USE, ...)
        if result.blocked:
            return ToolResultBlock(content="...blocked...", is_error=True)
    
    # 2. 查找工具
    tool = context.tool_registry.get(tool_name)
    if tool is None:
        return ToolResultBlock(content="Unknown tool", is_error=True)
    
    # 3. 输入验证
    parsed_input = tool.input_model.model_validate(tool_input)
    
    # 4. 权限检查
    file_path = _resolve_permission_file_path(...)
    command = _extract_permission_command(...)
    decision = permission_checker.evaluate(tool_name, file_path, command)
    if not decision.allowed:
        if decision.requires_confirmation:
            confirmed = await permission_prompt(tool_name, decision.reason)
            if not confirmed:
                return ToolResultBlock(content="...denied...", is_error=True)
        else:
            return ToolResultBlock(content="...blocked...", is_error=True)
    
    # 5. 执行
    result = await tool.execute(parsed_input, ToolExecutionContext(...))
    
    # 6. 记录元数据
    _record_tool_carryover(context, tool_name, tool_input, tool_output, ...)
    
    # 7. Post-Tool-Use Hook
    if context.hook_executor:
        await hook_executor.execute(POST_TOOL_USE, ...)
    
    return ToolResultBlock(content=result.output, is_error=result.is_error)
```

### 4.5.2 工具元数据追踪

`_record_tool_carryover()`（`query.py:296`）维护一个 **"工作记忆"** 字典，让模型了解之前做了什么：

- `read_file_state`：最近读取的文件列表
- `invoked_skills`：已调用的技能
- `async_agent_state`：已派生的子 Agent
- `recent_work_log`：工作日志
- `recent_verified_work`：已验证的工作项

这些信息被注入到系统提示词的 "Task Focus State" 部分。

## 4.6 会话管理

### 4.6.1 会话持久化

`services/session_backend.py` 定义了 `SessionBackend` 协议：

```python
class SessionBackend(Protocol):
    def save_snapshot(self, cwd, model, system_prompt, messages, usage, session_id, tool_metadata): ...
    def load_latest(self) -> SessionSnapshot | None: ...
    def list_snapshots(self) -> list[SessionSnapshot]: ...
    def load_by_id(self, session_id: str) -> SessionSnapshot | None: ...
    def export_markdown(self, session_id: str) -> str: ...
```

`OpenHarnessSessionBackend` 使用 JSON 文件存储：

```python
# services/session_storage.py
get_data_dir() / "sessions" / f"{session_id}.json"
```

### 4.6.2 RuntimeBundle 构建

`build_runtime()`（`ui/runtime.py`）组装所有组件：

```python
async def build_runtime(model, max_turns, system_prompt, ...):
    # 1. 加载设置
    settings = Settings.load()
    
    # 2. 创建 API 客户端
    api_client = create_api_client(settings)
    
    # 3. 创建 MCP 管理器
    mcp_manager = McpClientManager()
    await mcp_manager.connect_all()
    
    # 4. 创建工具注册中心
    tool_registry = create_default_tool_registry(mcp_manager)
    
    # 5. 创建 Hook 执行器
    hook_executor = HookExecutor(...)
    
    # 6. 创建权限检查器
    permission_checker = PermissionChecker(...)
    
    # 7. 创建 QueryEngine
    engine = QueryEngine(api_client, tool_registry, permission_checker, ...)
    
    # 8. 创建 RuntimeBundle
    return RuntimeBundle(engine, tool_registry, commands, session_backend, ...)
```

## 4.7 关键源码路径

| 组件 | 文件 | 行号 |
|------|------|------|
| QueryEngine | `engine/query_engine.py` | 19 |
| run_query() | `engine/query.py` | 406 |
| _execute_tool_call() | `engine/query.py` | 654 |
| 消息模型 | `engine/messages.py` | - |
| 流式事件 | `engine/stream_events.py` | - |
| 成本追踪 | `engine/cost_tracker.py` | - |
| 构建运行时 | `ui/runtime.py` | build_runtime |

## 4.8 本章小结

会话引擎是 OpenHarness 的核心编排层。它实现了**工具感知的 Agent Loop**：提交消息 → 调用模型 → 处理流式响应 → 执行工具 → 循环。通过异步生成器模式，引擎将中间状态以事件形式暴露给 UI 层，实现实时、可观察的交互体验。

> 下一章：[工具系统](05-tool-system.md) —— 30+ 工具的定义规范与实现。
