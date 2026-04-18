# Agent Loop 与 StreamEvent 实现指南

> 本文档面向 Python 初学者，逐步讲解 OpenHarness 项目中 **Agent Loop（智能体循环）** 如何通过 **StreamEvent（流式事件）** 实现增量输出。

内容涵盖：
  - 核心概念：Agent Loop、StreamEvent、async/await、生成器的通俗解释
  - 架构分层：API 客户端层 → 引擎层 → UI 层，每层各自的事件类型
  - 7 种 StreamEvent：每个事件的字段、含义、触发时机
  - run_query() 主循环：带伪代码和流程图，包括并发工具执行和压缩流式输出
  - API 客户端：Protocol 接口、重试机制（指数退避+抖动）
  - 三种消费端：终端/React TUI/聊天频道
  - Python 知识点：dataclass、Pydantic、Union Type、Protocol、AsyncIterator、asyncio.gather、asyncio.Queue
---

## 目录

1. [核心概念速览](#1-核心概念速览)
2. [整体架构：数据从哪来，到哪去](#2-整体架构数据从哪来到哪去)
3. [StreamEvent：七种事件类型](#3-streamevent七种事件类型)
4. [Agent Loop 主循环：run_query()](#4-agent-loop-主循环run_query)
5. [API 客户端层：事件的生产者](#5-api-客户端层事件的生产者)
6. [消费端：事件如何被渲染](#6-消费端事件如何被渲染)
7. [涉及的关键 Python 知识点](#7-涉及的关键-python-知识点)
8. [完整数据流图](#8-完整数据流图)

---

## 1. 核心概念速览

在阅读代码之前，你需要理解几个关键概念：

### Agent Loop（智能体循环）

Agent Loop 是一种 **循环驱动** 的工作模式：

```
用户输入 → AI 思考 → AI 可能调用工具 → 工具返回结果 → AI 继续思考 → ... → AI 给出最终回答
```

关键点在于：AI 不一定一次就能完成任务。它可能需要多轮「思考 → 调用工具 → 看结果 → 再思考」的循环，直到不再需要调用工具为止。

### StreamEvent（流式事件）

传统的程序调用是 **请求-等待-拿到完整结果**。但 AI 生成文本是一个字一个字输出的，如果等全部生成完再显示，用户会感到明显卡顿。

StreamEvent 的思路是：**把整个过程中发生的每件事都包装成一个事件（Event），逐个发出**。消费者收到一个事件就处理一个，不需要等全部完成。

类比：传统方式像下载完整视频后播放；StreamEvent 像直播流——边产边消费。

### 异步编程（async/await）

Python 的 `async/await` 用于处理「需要等待」的操作（如网络请求、文件读写），在等待期间不阻塞整个程序，而是切换去做别的事。

```python
# 同步：等 3 秒什么也做不了
time.sleep(3)

# 异步：等 3 秒期间可以处理其他任务
await asyncio.sleep(3)
```

### 生成器（Generator）与异步生成器

普通函数 `return` 一次就结束。生成器用 `yield` 可以 **逐个产出值**，调用方每消费一个值就推进一步：

```python
# 同步生成器
def count_to_three():
    yield 1    # 产出 1，暂停
    yield 2    # 产出 2，暂停
    yield 3    # 产出 3，结束

for n in count_to_three():
    print(n)   # 1, 2, 3

# 异步生成器 —— 用 async for 消费
async def count_slowly():
    yield 1
    await asyncio.sleep(1)  # 等待 1 秒
    yield 2

async for n in count_slowly():
    print(n)
```

本项目的核心函数 `run_query()` 就是一个异步生成器——每产出一个 `StreamEvent` 就 `yield` 出去，UI 层拿到就立即显示。

---

## 2. 整体架构：数据从哪来，到哪去

整个系统分四层，事件从底层流向顶层：

```
┌─────────────────────────────────────┐
│  用户界面层 (UI Layer)               │  ← 消费 StreamEvent，渲染给用户看
│  - OutputRenderer (终端)            │
│  - ReactBackendHost (React TUI)     │
│  - ChannelBridge (聊天频道)          │
├─────────────────────────────────────┤
│  引擎层 (Engine Layer)              │  ← Agent Loop 核心循环
│  - QueryEngine (状态管理)            │
│  - run_query() (主循环)             │
├─────────────────────────────────────┤
│  API 客户端层 (API Client Layer)    │  ← 调用 AI 服务，产出 ApiStreamEvent
│  - AnthropicApiClient              │
│  - OpenAICompatibleClient          │
│  - CodexApiClient / CopilotClient  │
├─────────────────────────────────────┤
│  AI 服务 (External AI Service)      │  ← 远程大模型 API
└─────────────────────────────────────┘
```

关键设计：每一层只关心自己那一种事件类型，互不干扰。

- API 客户端层产出 `ApiStreamEvent`（3 种）
- 引擎层把 `ApiStreamEvent` 翻译成 `StreamEvent`（7 种）
- UI 层只消费 `StreamEvent`

---

## 3. StreamEvent：七种事件类型

文件位置：`src/openharness/engine/stream_events.py`

### 事件一览表

| 事件类 | 字段 | 含义 | 何时发生 |
|--------|------|------|----------|
| `AssistantTextDelta` | `text: str` | AI 输出的一个文字片段 | AI 流式生成文字时，每个 token 一个 |
| `AssistantTurnComplete` | `message`, `usage` | AI 这一轮说完了 | AI 完成本轮回复后 |
| `ToolExecutionStarted` | `tool_name`, `tool_input` | 即将执行某个工具 | 检测到 AI 要求调用工具时 |
| `ToolExecutionCompleted` | `tool_name`, `output`, `is_error` | 工具执行完毕 | 工具运行结束后 |
| `ErrorEvent` | `message`, `recoverable` | 出错了 | 网络错误、API 异常等 |
| `StatusEvent` | `message: str` | 状态提示消息 | 重试中、压缩中等 |
| `CompactProgressEvent` | `phase`, `trigger`, `message`... | 对话压缩进度 | 对话过长触发自动压缩时 |

### 代码定义

所有事件都是 **frozen dataclass**（不可变的数据类）：

```python
from dataclasses import dataclass

@dataclass(frozen=True)          # frozen=True 表示创建后不可修改
class AssistantTextDelta:
    """Incremental assistant text."""
    text: str                     # 只有一个字段：文本片段

@dataclass(frozen=True)
class ToolExecutionStarted:
    tool_name: str                # 工具名称，如 "bash", "read_file"
    tool_input: dict[str, Any]    # 工具输入参数
```

> **为什么用 frozen？** 防止意外修改事件对象。事件一旦创建就是「事实记录」，不应该被篡改。

### 联合类型（Union Type）

七种事件用 Python 3.10+ 的联合类型语法组合在一起：

```python
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

`|` 在类型注解中表示「或」。`StreamEvent` 不是某个具体类，而是一个 **类型别名**，表示「这七种类型中的任意一种」。

消费者用 `isinstance()` 判断具体是哪种：

```python
def handle(event: StreamEvent):
    if isinstance(event, AssistantTextDelta):
        print(event.text)            # 文字事件 → 显示文字
    elif isinstance(event, ToolExecutionStarted):
        print(f"正在执行: {event.tool_name}")
    # ... 其他类型
```

---

## 4. Agent Loop 主循环：run_query()

文件位置：`src/openharness/engine/query.py` 第 398-605 行

这是整个系统的核心。让我用一个简化版来解释：

### 函数签名

```python
async def run_query(
    context: QueryContext,                                    # 运行上下文（API客户端、工具注册表等）
    messages: list[ConversationMessage],                     # 对话历史
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]: # 产出事件和用量信息
```

返回类型解读：这是一个 **异步生成器**，每次 `yield` 产出一个元组 `(事件, 用量)`。用量信息可能为 `None`。

### 主循环伪代码

```python
turn_count = 0
while turn_count < max_turns:           # 循环，最多 max_turns 轮
    turn_count += 1

    # ① 自动压缩检查（对话太长时压缩）
    async for event, usage in _stream_compaction(trigger="auto"):
        yield event, usage              # 产压缩进度事件

    # ② 调用 AI API，流式获取回复
    final_message = None
    async for event in api_client.stream_message(request):
        if isinstance(event, ApiTextDeltaEvent):
            yield AssistantTextDelta(text=event.text), None  # 文字片段 → 直接转发
        elif isinstance(event, ApiRetryEvent):
            yield StatusEvent(message="重试中..."), None     # 重试 → 状态提示
        elif isinstance(event, ApiMessageCompleteEvent):
            final_message = event.message                    # 最终完整消息

    # ③ 产出「本轮完成」事件
    yield AssistantTurnComplete(message=final_message, usage=usage), usage

    # ④ 如果 AI 没有要求调用工具 → 结束循环
    if not final_message.tool_uses:
        return

    # ⑤ AI 要求调用工具 → 执行工具
    for tc in tool_calls:
        yield ToolExecutionStarted(tool_name=tc.name, ...), None   # 工具开始
        result = await _execute_tool_call(context, tc.name, ...)
        yield ToolExecutionCompleted(tool_name=tc.name, ...), None # 工具完成

    # ⑥ 把工具结果附加到对话，回到第 ① 步继续循环
    messages.append(ConversationMessage(role="user", content=tool_results))
```

### 关键流程图解

```
    ┌──────────┐
    │ 开始循环  │
    └────┬─────┘
         ▼
    ┌─────────────┐     CompactProgressEvent
    │ ① 自动压缩   │ ──────────────────────► yield
    └────┬────────┘
         ▼
    ┌─────────────┐     AssistantTextDelta (多个)
    │ ② 调用AI API │ ──────────────────────► yield
    │  流式获取回复 │     StatusEvent (重试时)
    └────┬────────┘
         ▼
    ┌─────────────┐     AssistantTurnComplete
    │ ③ 本轮完成   │ ──────────────────────► yield
    └────┬────────┘
         ▼
    ┌─────────────┐
    │ ④ 有工具调用？│──── 否 ───► return (结束)
    └────┬────────┘
         │ 是
         ▼
    ┌─────────────┐     ToolExecutionStarted
    │ ⑤ 执行工具   │ ──────────────────────► yield
    │             │     ToolExecutionCompleted
    └────┬────────┘
         ▼
    ┌─────────────┐
    │ ⑥ 附加结果   │
    │ 回到 ①      │◄────────────────────────┘
    └─────────────┘
```

### 并发工具执行

当 AI 一次要求调用多个工具时，引擎会 **并发执行**：

```python
# 单工具 → 顺序执行，边执行边 yield 事件
if len(tool_calls) == 1:
    yield ToolExecutionStarted(...)
    result = await _execute_tool_call(...)
    yield ToolExecutionCompleted(...)

# 多工具 → 并发执行
else:
    # 先 yield 所有"开始"事件
    for tc in tool_calls:
        yield ToolExecutionStarted(...)

    # 并发执行所有工具（一个失败不影响其他）
    results = await asyncio.gather(
        *[_run(tc) for tc in tool_calls],
        return_exceptions=True    # ← 关键：异常不会取消其他任务
    )

    # 再 yield 所有"完成"事件
    for tc, result in zip(tool_calls, results):
        yield ToolExecutionCompleted(...)
```

> **为什么用 `return_exceptions=True`？** Anthropic API 要求每个 `tool_use` 都有对应的 `tool_result`。如果某个工具异常导致其他工具被取消，下次请求就会因为缺少 `tool_result` 而被 API 拒绝。

### 压缩进度的流式输出

`_stream_compaction()` 展示了一种 **生产者-消费者** 模式：

```python
async def _stream_compaction(trigger, force=False):
    progress_queue = asyncio.Queue()         # ① 创建队列

    async def _progress(event):
        await progress_queue.put(event)       # ② 压缩任务往队列放事件

    task = asyncio.create_task(               # ③ 后台启动压缩任务
        auto_compact_if_needed(..., progress_callback=_progress)
    )

    while True:
        try:
            event = await asyncio.wait_for(   # ④ 主循环每 50ms 从队列取事件
                progress_queue.get(), timeout=0.05
            )
            yield event, None                # ⑤ 取到就 yield 出去
        except asyncio.TimeoutError:
            if task.done():                   # ⑥ 超时且任务完成 → 退出
                break
            continue                          # ⑦ 超时但任务还在 → 继续等

    # ⑧ 排干队列中剩余事件
    while not progress_queue.empty():
        yield progress_queue.get_nowait(), None
```

这样主循环在等待压缩完成期间，不会卡住——它可以持续 yield 压缩进度事件给 UI。

---

## 5. API 客户端层：事件的生产者

文件位置：`src/openharness/api/client.py`

API 客户端负责和远程 AI 服务通信，把 AI 的流式输出翻译成 `ApiStreamEvent`。

### ApiStreamEvent：三种底层事件

```python
ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent
```

| 事件类 | 含义 |
|--------|------|
| `ApiTextDeltaEvent` | AI 输出的一个文字片段（一个 token） |
| `ApiMessageCompleteEvent` | AI 完整回复，包含完整消息和用量 |
| `ApiRetryEvent` | 请求失败，即将重试 |

### Protocol（协议类型）：统一的接口

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        ...
```

`Protocol` 是 Python 的 **结构化类型**（鸭子类型的类型注解版本）。任何类只要有 `stream_message` 方法，就算「实现了」这个 Protocol，不需要显式继承。

目前有 4 个实现：

| 客户端类 | 通信对象 |
|----------|----------|
| `AnthropicApiClient` | Anthropic Claude API |
| `OpenAICompatibleClient` | OpenAI 兼容 API |
| `CodexApiClient` | Codex Responses API |
| `CopilotClient` | GitHub Copilot API |

### 重试机制：指数退避 + 抖动

```python
async def stream_message(self, request):
    for attempt in range(MAX_RETRIES + 1):   # 最多重试 3 次
        try:
            async for event in self._stream_once(request):
                yield event                  # 成功 → 转发所有事件
            return                          # 成功 → 结束
        except Exception as exc:
            if not _is_retryable(exc):
                raise                       # 不可重试的错 → 直接抛

            delay = _get_retry_delay(attempt, exc)
            yield ApiRetryEvent(...)        # 可重试 → yield 重试事件
            await asyncio.sleep(delay)      # 等待后重试
```

`_get_retry_delay` 计算等待时间：

```python
def _get_retry_delay(attempt, exc=None):
    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)  # 1s, 2s, 4s, 8s...
    jitter = random.uniform(0, delay * 0.25)             # 加随机抖动
    return delay + jitter
```

> **为什么加抖动（jitter）？** 如果多个客户端同时重试，没有抖动它们会在同一时刻发起请求，造成「惊群效应」。加随机值让请求错开。

---

## 6. 消费端：事件如何被渲染

### 终端渲染：OutputRenderer

文件位置：`src/openharness/ui/output.py`

`OutputRenderer.render_event()` 用 `isinstance` 逐类型判断并处理：

```python
def render_event(self, event: StreamEvent):
    if isinstance(event, AssistantTextDelta):
        # 逐字输出 AI 文本（快速响应）
        self.console.print(event.text, end="")

    elif isinstance(event, AssistantTurnComplete):
        # AI 说完一轮 → 用 Rich Markdown 重新渲染（更好看）
        self.console.print(Markdown(self._assistant_buffer))

    elif isinstance(event, ToolExecutionStarted):
        # 显示工具名和参数摘要
        self.console.print(f"Tool: {event.tool_name}")

    elif isinstance(event, ToolExecutionCompleted):
        # 在 Rich Panel 里显示工具输出
        self.console.print(Panel(event.output))
```

> **为什么要「先快速输出，再重渲染」？** AI 一个字一个字出来时，用户想立即看到，所以先用 `print(text, end="")` 快速输出。等 AI 说完一整段后，再用 Rich Markdown 渲染一次，让格式（标题、代码块、列表等）更好看。

### React TUI 渲染：ReactBackendHost

文件位置：`src/openharness/ui/backend_host.py`

把 `StreamEvent` 翻译成 `BackendEvent`（JSON 格式），通过 stdout 发给 React 前端：

```python
def _render_event(self, event: StreamEvent):
    if isinstance(event, AssistantTextDelta):
        self._emit(BackendEvent(type="assistant_delta", text=event.text))

    elif isinstance(event, ToolExecutionStarted):
        self._emit(BackendEvent(type="tool_started", ...))
```

### 聊天频道：ChannelBridge

文件位置：`src/openharness/channels/adapter.py`

最简单的消费者——只关心文字，把所有 `AssistantTextDelta.text` 拼起来，最后作为一条消息发回聊天频道。

---

## 7. 涉及的关键 Python 知识点

### 7.1 dataclass（数据类）

普通类需要手写 `__init__`，`dataclass` 自动生成：

```python
from dataclasses import dataclass

# 手写类
class AssistantTextDelta:
    def __init__(self, text: str):
        self.text = text

# 等价的 dataclass（自动生成 __init__, __repr__, __eq__ 等）
@dataclass
class AssistantTextDelta:
    text: str

# frozen=True 还会自动生成 __hash__，并禁止赋值修改
@dataclass(frozen=True)
class AssistantTextDelta:
    text: str

event = AssistantTextDelta(text="hello")
event.text = "world"   # ❌ FrozenInstanceError: 不能修改
```

### 7.2 Pydantic BaseModel

`dataclass` 适合简单的内部数据。`Pydantic BaseModel` 额外提供数据校验和序列化：

```python
from pydantic import BaseModel

class ConversationMessage(BaseModel):    # 用 BaseModel
    role: Literal["user", "assistant"]
    content: list[ContentBlock] = []

msg = ConversationMessage(role="user", content=[...])  # 自动校验
json_str = msg.model_dump_json()                       # 自动序列化为 JSON
```

本项目的选择：
- **事件**（StreamEvent, ApiStreamEvent）→ `dataclass`：轻量、内部使用、不需要序列化
- **消息**（ConversationMessage, BackendEvent）→ `Pydantic BaseModel`：需要校验、需要跨层传输和序列化

### 7.3 Union Type（联合类型）

Python 3.10+ 新语法，用 `|` 表示「多种类型之一」：

```python
# Python 3.10 之前
from typing import Union
StreamEvent = Union[AssistantTextDelta, AssistantTurnComplete, ...]

# Python 3.10+（本项目使用）
StreamEvent = AssistantTextDelta | AssistantTurnComplete | ...
```

### 7.4 Protocol（协议类型）

Python 的 **结构化子类型**，类似 Go 的 interface——不需要 `implements` 声明：

```python
from typing import Protocol

class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request) -> AsyncIterator[ApiStreamEvent]:
        ...

# 任何有 stream_message 方法的类都算实现了这个 Protocol
class AnthropicApiClient:
    async def stream_message(self, request) -> AsyncIterator[ApiStreamEvent]:
        ...   # ✅ 自动满足 Protocol
```

对比传统 ABC（抽象基类）需要显式继承：`class MyClient(StreamingMessagesBase):`

### 7.5 AsyncIterator 与 async for

`AsyncIterator` 是异步版本的迭代器。用 `async for` 消费：

```python
async def my_generator():
    yield 1
    await asyncio.sleep(0.1)
    yield 2

# 消费方式
async for value in my_generator():
    print(value)  # 1, 2
```

`run_query()` 返回 `AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]`，调用方用 `async for event, usage in run_query(...)` 逐个消费事件。

### 7.6 asyncio.gather

并发运行多个协程：

```python
# 顺序执行：总时间 = A + B + C
result_a = await task_a()
result_b = await task_b()
result_c = await task_c()

# 并发执行：总时间 ≈ max(A, B, C)
results = await asyncio.gather(task_a(), task_b(), task_c())

# return_exceptions=True：某个任务异常时不取消其他任务
results = await asyncio.gather(task_a(), task_b(), return_exceptions=True)
# results[0] 可能是异常对象而不是返回值
```

### 7.7 asyncio.Queue

线程安全的异步队列，常用于 **生产者-消费者** 模式：

```python
queue = asyncio.Queue()

# 生产者
await queue.put(item)

# 消费者
item = await queue.get()              # 阻塞等待
item = await asyncio.wait_for(queue.get(), timeout=0.05)  # 带超时
item = queue.get_nowait()             # 非阻塞，空则抛 QueueEmpty
```

---

## 8. 完整数据流图

```
用户输入 "帮我读一下 main.py"
         │
         ▼
┌──────────────────────┐
│  handle_line()       │  ui/runtime.py
│  构建系统提示，调用   │
│  QueryEngine         │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│  QueryEngine         │  engine/query_engine.py
│  .submit_message()   │
│                      │
│  1. 追加用户消息      │
│  2. 构建 QueryContext │
│  3. 调用 run_query() │
└────────┬─────────────┘
         │  async for event, usage in run_query(...)
         ▼
┌──────────────────────────────────────────────────────┐
│  run_query() —— Agent Loop 主循环                    │  engine/query.py
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │  while turn_count < max_turns:                  │  │
│  │                                                │  │
│  │  ① _stream_compaction()                        │  │
│  │     └─ yield CompactProgressEvent              │  │
│  │                                                │  │
│  │  ② api_client.stream_message(request)          │  │
│  │     │                                          │  │
│  │     │  ┌────────────────────────────────────┐   │  │
│  │     │  │  AnthropicApiClient                │   │  │
│  │     │  │  ._stream_once()                   │   │  │
│  │     │  │  │                                  │   │  │
│  │     │  │  │  async with client.stream() as s │   │  │
│  │     │  │  │    async for event in s:         │   │  │
│  │     │  │  │      yield ApiTextDeltaEvent     │──┼──┼──► yield AssistantTextDelta
│  │     │  │  │                                  │   │  │
│  │     │  │  │  yield ApiMessageCompleteEvent   │──┼──┼──► yield AssistantTurnComplete
│  │     │  │  │                                  │   │  │
│  │     │  │  │  (retry 时)                      │   │  │
│  │     │  │  │  yield ApiRetryEvent             │──┼──┼──► yield StatusEvent
│  │     │  │  └────────────────────────────────────┘   │  │
│  │     │                                          │  │
│  │  ③ yield AssistantTurnComplete                 │  │
│  │                                                │  │
│  │  ④ AI 要求调用 read_file 工具                    │  │
│  │     yield ToolExecutionStarted ──────────────────────► yield ToolExecutionStarted
│  │     await _execute_tool_call()                 │  │
│  │     yield ToolExecutionCompleted ───────────────────► yield ToolExecutionCompleted
│  │                                                │  │
│  │  ⑤ 附加工具结果，回到 ①                         │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
         │
         │  yield StreamEvent
         ▼
┌──────────────────────┐
│  消费者 (三选一)      │
│                      │
│  a) OutputRenderer   │  → 终端 Rich 渲染
│     .render_event()  │
│                      │
│  b) ReactBackendHost │  → BackendEvent → JSON → React 前端
│     ._render_event() │
│                      │
│  c) ChannelBridge    │  → 拼接文本 → 聊天频道消息
│     ._handle()       │
└──────────────────────┘
```

---

## 涉及的关键文件索引

| 文件路径 | 核心内容 |
|----------|----------|
| `src/openharness/engine/stream_events.py` | 7 种 StreamEvent 事件定义 |
| `src/openharness/engine/query.py` | `run_query()` Agent Loop 主循环 |
| `src/openharness/engine/query_engine.py` | `QueryEngine` 状态管理包装 |
| `src/openharness/engine/messages.py` | `ConversationMessage`, `TextBlock`, `ToolUseBlock`, `ToolResultBlock` |
| `src/openharness/api/client.py` | `ApiStreamEvent` 定义、`SupportsStreamingMessages` Protocol、`AnthropicApiClient` |
| `src/openharness/api/usage.py` | `UsageSnapshot` 用量模型 |
| `src/openharness/tools/base.py` | `BaseTool`, `ToolRegistry`, `ToolResult` |
| `src/openharness/ui/output.py` | `OutputRenderer` 终端渲染 |
| `src/openharness/ui/backend_host.py` | `ReactBackendHost` React 前端桥接 |
| `src/openharness/ui/protocol.py` | `BackendEvent` 前端协议 |
| `src/openharness/channels/adapter.py` | `ChannelBridge` 聊天频道桥接 |