# 第十一章：查询引擎 — 应用的心脏

## 概述

`QueryEngine` 是 OpenHarness 的核心组件——它接收用户消息，驱动 AI 模型循环（调用模型 -> 解析工具请求 -> 执行工具 -> 反馈结果），并通过 `AsyncIterator[StreamEvent]` 流式输出每个中间事件。

引擎的架构是一个经典的 **Agent Loop**（智能体循环）：用户消息进入后，模型生成回复；如果回复中包含工具调用请求，引擎执行工具并将结果追加到对话历史，然后再次调用模型——如此循环，直到模型不再请求工具或达到最大轮次限制。

## Java 类比

| Python 概念 | Java 对应 | 核心差异 |
|---|---|---|
| `AsyncIterator[StreamEvent]` | `Flux<StreamEvent>` | 拉取式迭代 vs 推送式订阅 |
| `ContentBlock` 判别联合 | Java `sealed interface` + `pattern matching` | Python 用 `Annotated` + 字面量判别器 |
| `CostTracker` 累加器 | `AtomicLong` 累加器 | Python 单线程事件循环无需原子操作 |
| `async for event in client.stream_message()` | `client.stream().doOnNext(event -> ...)` | Python 内联迭代 vs Java 响应式链 |
| `yield` 在 async generator | `Flux.create(sink -> ...)` | Python 原生语法 vs Java 构建器模式 |
| `dataclass(frozen=True)` | Java `record` | Python dataclass 可变默认值 vs Java record 不可变 |

> **Java 对比**
>
> 在 Java 中实现类似的流式引擎，你需要 `Flux<StreamEvent>` 或 `Flow.Publisher<StreamEvent>`，配合 `doOnNext()`, `flatMap()`, `onErrorResume()` 等操作符链。Python 的 `async for` + `yield` 模式更直观：你可以用普通 `for` 循环的心智模型来理解异步流，只是每个迭代点前加了 `await`。Python 不需要响应式编程的背压管理，因为 `AsyncIterator` 天然是拉取式的——消费者决定何时拉取下一个元素。

## 项目代码详解

### 1. QueryEngine — 核心引擎类

`engine/query_engine.py` 定义了引擎的公开接口：

```python
class QueryEngine:
    """拥有对话历史和工具感知模型循环的引擎。"""

    def __init__(
        self,
        *,
        api_client: SupportsStreamingMessages,
        tool_registry: ToolRegistry,
        permission_checker: PermissionChecker,
        cwd: str | Path,
        model: str,
        system_prompt: str,
        max_tokens: int = 4096,
        context_window_tokens: int | None = None,
        auto_compact_threshold_tokens: int | None = None,
        max_turns: int | None = 8,
        permission_prompt: PermissionPrompt | None = None,
        ask_user_prompt: AskUserPrompt | None = None,
        hook_executor: HookExecutor | None = None,
        tool_metadata: dict[str, object] | None = None,
        verbose: bool = False,
    ) -> None:
        self._api_client = api_client
        self._tool_registry = tool_registry
        self._permission_checker = permission_checker
        self._messages: list[ConversationMessage] = []
        self._cost_tracker = CostTracker()
        # ...

    async def submit_message(
        self, prompt: str | ConversationMessage
    ) -> AsyncIterator[StreamEvent]:
        """追加用户消息并执行查询循环。"""
        user_message = (
            prompt if isinstance(prompt, ConversationMessage)
            else ConversationMessage.from_user_text(prompt)
        )
        self._messages.append(user_message)
        context = QueryContext(...)
        async for event, usage in run_query(context, list(self._messages)):
            if isinstance(event, AssistantTurnComplete):
                self._messages = list(query_messages)
            if usage is not None:
                self._cost_tracker.add(usage)
            yield event
```

> **Java 对比**
>
> `QueryEngine.submit_message()` 的签名 `async def submit_message() -> AsyncIterator[StreamEvent]` 对应 Java 的 `Flux<StreamEvent> submitMessage(String prompt)`。关键差异是：Python 的 `AsyncIterator` 是**惰性求值**的——只有当消费者 `async for` 迭代时，循环才会推进。Java 的 `Flux` 默认是**热源**——即使没有订阅者，数据也可能开始流动。Python 的方式更安全：没有消费者 = 没有副作用。

### 2. ConversationMessage — 判别联合类型

`engine/messages.py` 使用 Pydantic 的判别联合（discriminated union）来建模消息内容：

```python
class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    media_type: str
    data: str
    source_path: str = ""

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str = Field(default_factory=lambda: f"toolu_{uuid4().hex}")
    name: str
    input: dict[str, Any] = Field(default_factory=dict)

class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False

ContentBlock = Annotated[
    TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]

class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock] = Field(default_factory=list)
```

> **Java 对比**
>
> 这对应 Java 17+ 的 `sealed interface` + `pattern matching`：
>
> ```java
> sealed interface ContentBlock permits TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock {
>     String type();
> }
> record TextBlock(String text) implements ContentBlock { public String type() { return "text"; } }
> // ...
>
> switch (block) {
>     case TextBlock tb -> processText(tb.text());
>     case ToolUseBlock tu -> executeTool(tu.name(), tu.input());
>     case ToolResultBlock tr -> handleResult(tr.content());
>     case ImageBlock img -> processImage(img.data());
> }
> ```
>
> Python 使用 `isinstance(event, AssistantTextDelta)` 进行模式匹配，等价于 Java 的 `switch` 模式匹配，但更灵活——不需要实现 `sealed interface`，任何类都可以参与匹配。

### 3. StreamEvent — 事件联合类型

`engine/stream_events.py` 定义了引擎产生的所有事件类型：

```python
@dataclass(frozen=True)
class AssistantTextDelta:
    """增量助手文本。"""
    text: str

@dataclass(frozen=True)
class AssistantTurnComplete:
    """助手回合完成。"""
    message: ConversationMessage
    usage: UsageSnapshot

@dataclass(frozen=True)
class ToolExecutionStarted:
    """引擎即将执行工具。"""
    tool_name: str
    tool_input: dict[str, Any]

@dataclass(frozen=True)
class ToolExecutionCompleted:
    """工具执行完成。"""
    tool_name: str
    output: str
    is_error: bool = False

@dataclass(frozen=True)
class ErrorEvent:
    """应向用户展示的错误。"""
    message: str
    recoverable: bool = True

@dataclass(frozen=True)
class StatusEvent:
    """临时系统状态消息。"""
    message: str

@dataclass(frozen=True)
class CompactProgressEvent:
    """对话压缩的结构化进度事件。"""
    phase: Literal[
        "hooks_start", "context_collapse_start", "context_collapse_end",
        "session_memory_start", "session_memory_end",
        "compact_start", "compact_retry", "compact_end", "compact_failed",
    ]
    trigger: Literal["auto", "manual", "reactive"]
    message: str | None = None
    attempt: int | None = None

StreamEvent = (
    AssistantTextDelta
    | AssistantTurnComplete
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | ErrorEvent
    | StatusEvent
    | CompactProgressEvent
)
```

> **Java 对比**
>
> `StreamEvent` 是一个联合类型，对应 Java 的 `sealed interface StreamEvent permits AssistantTextDelta, AssistantTurnComplete, ...`。Python 的 `dataclass(frozen=True)` 等价于 Java 的 `record`——不可变、自动生成 `equals()`/`hashCode()`/`toString()`。但 Python 的 `frozen=True` 只是约定性的（不强制不可变），而 Java 的 `record` 是编译时强制的。

### 4. CostTracker — 令牌用量累加器

```python
class CostTracker:
    """在会话生命周期内累加使用量。"""

    def __init__(self) -> None:
        self._usage = UsageSnapshot()

    def add(self, usage: UsageSnapshot) -> None:
        self._usage = UsageSnapshot(
            input_tokens=self._usage.input_tokens + usage.input_tokens,
            output_tokens=self._usage.output_tokens + usage.output_tokens,
        )

    @property
    def total(self) -> UsageSnapshot:
        return self._usage
```

```python
class UsageSnapshot(BaseModel):
    """模型提供商返回的令牌使用量。"""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
```

> **Java 对比**
>
> 在 Java 中，这种累加器通常使用 `AtomicLong` 来保证线程安全：
>
> ```java
> AtomicLong inputTokens = new AtomicLong(0);
> AtomicLong outputTokens = new AtomicLong(0);
> inputTokens.addAndGet(snapshot.getInputTokens());
> ```
>
> 但在 Python asyncio 的单线程事件循环中，`CostTracker.add()` 不需要原子操作——因为在任何两个 `await` 点之间，代码是串行执行的。`UsageSnapshot` 使用 `model_copy(update={...})` 创建新对象，遵循不可变模式。

### 5. Agent Loop — 查询循环核心

`engine/query.py` 中的 `run_query()` 函数实现了完整的智能体循环：

```python
async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
    """运行对话循环，直到模型停止请求工具。"""

    turn_count = 0
    while context.max_turns is None or turn_count < context.max_turns:
        turn_count += 1

        # 1. 自动压缩检查
        async for event, usage in _stream_compaction(trigger="auto"):
            yield event, usage
        messages, was_compacted = last_compaction_result

        # 2. 调用模型 API
        async for event in context.api_client.stream_message(ApiMessageRequest(...)):
            if isinstance(event, ApiTextDeltaEvent):
                yield AssistantTextDelta(text=event.text), None
            elif isinstance(event, ApiRetryEvent):
                yield StatusEvent(message=f"Retrying: {event.message}"), None
            elif isinstance(event, ApiMessageCompleteEvent):
                final_message = event.message
                usage = event.usage

        # 3. 如果没有工具调用，返回最终回复
        if not final_message.tool_uses:
            return

        # 4. 执行工具调用
        tool_calls = final_message.tool_uses
        for tc in tool_calls:
            yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None

        # 并行执行多个工具
        raw_results = await asyncio.gather(
            *[_run(tc) for tc in tool_calls], return_exceptions=True
        )

        # 5. 将工具结果追加到消息历史
        messages.append(ConversationMessage(role="user", content=tool_results))
```

> **Java 对比**
>
> `asyncio.gather(*[_run(tc) for tc in tool_calls], return_exceptions=True)` 对应 Java 中的 `CompletableFuture.allOf(futures)`，但 `return_exceptions=True` 参数让所有任务的结果（包括异常）都被收集，而不是在第一个失败时取消其他任务。这等价于 Java 的 `CompletableFuture.allOf().exceptionally()` 组合，但语义更清晰。

### 6. MAX_TRACKED_* 常量 — 会话状态限制

```python
MAX_TRACKED_READ_FILES = 6
MAX_TRACKED_SKILLS = 8
MAX_TRACKED_ASYNC_AGENT_EVENTS = 8
MAX_TRACKED_WORK_LOG = 10
MAX_TRACKED_USER_GOALS = 5
MAX_TRACKED_ACTIVE_ARTIFACTS = 8
MAX_TRACKED_VERIFIED_WORK = 10
```

这些常量限制了引擎在 `tool_metadata` 字典中跟踪的会话状态量，防止内存无限增长。每个列表用 `_append_capped_unique()` 维护：

```python
def _append_capped_unique(bucket: list[Any], value: Any, *, limit: int) -> None:
    if value in bucket:
        bucket.remove(value)
    bucket.append(value)
    if len(bucket) > limit:
        del bucket[:-limit]
```

> **Java 对比**
>
> 这对应 Java 中 `LinkedHashMap` + `eviction policy` 的 LRU 缓存，但 Python 版更简单——直接在列表上操作，最新的元素总在末尾，超出限制时删除最老的。不需要 `synchronized` 或 `ConcurrentHashMap`，因为事件循环是单线程的。

## 架构图

```
+----------------+     +----------------+     +----------------+
|  User Input    | --> |  QueryEngine   | --> |  API Client    |
|  (Message)     |     |  (Core Loop)   |     |  (Streaming)   |
+----------------+     +----------------+     +----------------+
                              |                        |
                              | ToolExecution          | StreamEvents
                              v                        v
                       +----------------+     +----------------+
                       |  ToolRegistry  |     |  UI/Channel    |
                       |  (30+ tools)   |     |  (Output)      |
                       +----------------+     +----------------+
                              |
                              | CostTracker.add()
                              v
                       +----------------+
                       |  UsageSnapshot |
                       |  (Tokens)       |
                       +----------------+

QueryEngine 内部循环:
  ┌──────────────────────────────────────────────────────────────┐
  │  while turn < max_turns:                                     │
  │    1. Auto-compact check                                     │
  │    2. Call API: async for event in client.stream_message()   │
  │       ├── ApiTextDeltaEvent → yield AssistantTextDelta       │
  │       ├── ApiRetryEvent      → yield StatusEvent            │
  │       └── ApiMessageCompleteEvent → extract final_message   │
  │    3. If no tool_uses → return (done)                       │
  │    4. Execute tools: asyncio.gather(...)                     │
  │       ├── yield ToolExecutionStarted                         │
  │       └── yield ToolExecutionCompleted                       │
  │    5. Append tool results to messages                       │
  │    6. Loop back to step 2                                   │
  └──────────────────────────────────────────────────────────────┘

StreamEvent 类型层次:
  StreamEvent
  ├── AssistantTextDelta      (增量文本)
  ├── AssistantTurnComplete   (回合完成 + Usage)
  ├── ToolExecutionStarted    (工具开始执行)
  ├── ToolExecutionCompleted  (工具执行完成)
  ├── ErrorEvent              (错误，可恢复/不可恢复)
  ├── StatusEvent             (临时状态消息)
  └── CompactProgressEvent    (对话压缩进度)

ContentBlock 判别联合:
  ContentBlock (discriminator="type")
  ├── TextBlock       (type="text")
  ├── ImageBlock      (type="image")
  ├── ToolUseBlock    (type="tool_use")
  └── ToolResultBlock (type="tool_result")
```

## 小结

OpenHarness 的查询引擎是一个典型的 Agent Loop 实现：

1. **AsyncIterator 流式架构**：`submit_message()` 返回 `AsyncIterator[StreamEvent]`，消费者通过 `async for` 逐事件处理，比 Java 的 `Flux` 更直观。

2. **判别联合类型**：`ContentBlock` 和 `StreamEvent` 都使用 Pydantic 的 `Annotated[Union, discriminator]` 和 `dataclass(frozen=True)` 实现类型安全的事件分发。

3. **CostTracker 累加器**：在单线程事件循环中无需原子操作，使用不可变 `UsageSnapshot` + `model_copy(update={...})` 模式。

4. **工具并行执行**：`asyncio.gather(*tasks, return_exceptions=True)` 并行执行多个工具调用，异常不取消兄弟任务。

5. **会话状态限制**：`MAX_TRACKED_*` 常量确保元数据不会无限增长，使用 `_append_capped_unique()` 实现简单的 LRU 淘汰。

6. **自动压缩**：每轮调用模型前检查上下文窗口是否超出阈值，如果超出则自动压缩对话历史。

从 Java 转向 Python 的核心认知：**Python 的 async/await 让流式处理回归了同步代码的可读性**——你不需要响应式操作符链，只需要 `async for` + `isinstance`。