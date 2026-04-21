# 第八章：Python async/await — 从 Java 并发模型到协程世界

## 概述

Python 的 `async/await` 语法是 Java 开发者转型过程中最需要重新理解的概念之一。Java 的并发模型基于线程——无论是传统平台线程、`CompletableFuture`，还是 Java 21 引入的虚拟线程（Virtual Threads），本质上都是**抢占式多任务**。Python 的 asyncio 则采用**协作式多任务**：在单个事件循环线程中，协程主动让出控制权，由事件循环调度下一个就绪的协程。

OpenHarness 是一个高度异步的项目：消息总线的生产与消费、API 客户端的流式响应、Swarm 集群的文件邮箱通信——全部基于 asyncio 构建。理解 async/await 是理解整个项目架构的关键。

## Java 类比

| Python 概念 | Java 对应 | 核心差异 |
|---|---|---|
| `async def` / `await` | `CompletableFuture` / 虚拟线程 | 协作式 vs 抢占式 |
| `AsyncIterator` / `async for` | `Flux<T>` / `Stream<T>` | 拉取式迭代 vs 推送式订阅 |
| `asyncio.Queue` | `BlockingQueue` | 非阻塞等待 vs 阻塞等待 |
| `asyncio.create_task()` | `ExecutorService.submit()` | 轻量协程调度 vs 线程池调度 |
| `asyncio.get_event_loop().run_in_executor()` | 直接使用线程池 | 桥接阻塞 I/O 到事件循环 |

> **Java 对比**
>
> Java 开发者最常犯的错误是在 `async def` 函数中调用阻塞 I/O（如 `requests.get()` 或 `time.sleep()`）。在 Java 虚拟线程中，一个阻塞调用会自动让出载体线程；但在 Python asyncio 中，阻塞调用会**冻结整个事件循环**，导致所有协程停滞。必须用 `run_in_executor()` 将阻塞操作委派给线程池。

## 项目代码详解

### 1. MessageBus — 基于 asyncio.Queue 的消息总线

`channels/bus/queue.py` 实现了 OpenHarness 的核心消息总线，它是连接聊天渠道和 AI 引擎的枢纽：

```python
class MessageBus:
    """异步消息总线，解耦聊天渠道与 AI 引擎。"""

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """将渠道消息发布到入站队列。"""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """消费下一条入站消息（阻塞直到有消息可用）。"""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """将 AI 回复发布到出站队列。"""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """消费下一条出站消息（阻塞直到有消息可用）。"""
        return await self.outbound.get()
```

> **Java 对比**
>
> `asyncio.Queue` 对应 Java 的 `LinkedBlockingQueue`，但关键区别是：`LinkedBlockingQueue.put()` 阻塞调用线程，而 `asyncio.Queue.put()` **暂停当前协程**并让事件循环运行其他协程。这意味着你不会因为队列满而浪费线程资源——因为 asyncio.Queue 默认无界，且协程暂停成本极低（约 1KB 栈空间 vs 线程的 1MB）。

入站/出站事件类型定义在 `channels/bus/events.py` 中：

```python
@dataclass
class InboundMessage:
    """从聊天渠道接收的消息。"""
    channel: str           # telegram, discord, slack, whatsapp...
    sender_id: str         # 用户标识
    chat_id: str           # 会话标识
    content: str           # 消息文本
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_key_override: str | None = None

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"
```

### 2. ChannelBridge — async for 流式消费模式

`channels/adapter.py` 中的 `ChannelBridge` 展示了 `async for` 的经典用法：持续消费消息并流式转发到引擎：

```python
class ChannelBridge:
    """将入站渠道消息桥接到 QueryEngine，并将回复路由回渠道。"""

    def __init__(self, *, engine: "QueryEngine", bus: MessageBus) -> None:
        self._engine = engine
        self._bus = bus
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """将桥接循环作为后台任务启动。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="channel-bridge")

    async def _loop(self) -> None:
        """主处理循环：消费 -> 处理 -> 发布。"""
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._bus.consume_inbound(), timeout=1.0,
                )
                await self._handle(msg)
            except asyncio.TimeoutError:
                continue  # 超时后继续循环，检查 _running 标志
            except asyncio.CancelledError:
                break

    async def _handle(self, msg: InboundMessage) -> None:
        """处理一条入站消息并发布回复。"""
        reply_parts: list[str] = []
        try:
            async for event in self._engine.submit_message(msg.content):
                if isinstance(event, AssistantTextDelta):
                    reply_parts.append(event.text)
        except Exception:
            reply_parts = ["[Error: failed to process your message]"]

        reply_text = "".join(reply_parts).strip()
        outbound = OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id,
            content=reply_text,
            metadata={"_session_key": msg.session_key},
        )
        await self._bus.publish_outbound(outbound)
```

这里有两层 `async for`：
1. **外层**：`_loop()` 中 `await self._bus.consume_inbound()` — 无限循环消费队列
2. **内层**：`_handle()` 中 `async for event in self._engine.submit_message()` — 流式消费引擎事件

> **Java 对比**
>
> `async for event in engine.submit_message()` 对应 Java 中 `Flux<StreamEvent>.doOnNext(event -> ...)` 的响应式流。Python 的 `AsyncIterator` 是拉取式（pull）的——消费者主动 `await` 下一个元素；Java Reactor 的 `Flux` 是推送式（push）的——发布者推送数据到订阅者。Python 的方式更直观，调试更容易，因为调用栈是完整的。

### 3. asyncio.create_task() — 后台协程调度

`ChannelBridge.start()` 中的 `asyncio.create_task(self._loop(), name="channel-bridge")` 是 Python 中启动后台协程的标准方式：

```python
async def start(self) -> None:
    if self._running:
        return
    self._running = True
    self._task = asyncio.create_task(self._loop(), name="channel-bridge")
```

> **Java 对比**
>
> `asyncio.create_task()` 对应 Java 的 `executor.submit(callable)` 或 `CompletableFuture.runAsync()`。但 Python 协程比 Java 线程轻量几个数量级：创建一个协程只需几微秒和约 1KB 内存，而 Java 虚拟线程虽然也比平台线程轻量，但仍有几 KB 的栈空间开销。你可以在 Python 中轻松创建数万个 `asyncio.Task`，而无需担心线程池耗尽。

### 4. 重试逻辑与指数退避 — API 客户端

`api/client.py` 展示了 asyncio 环境中的重试模式：

```python
async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
    """流式传输文本增量与最终消息，遇到瞬时错误自动重试。"""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):  # MAX_RETRIES = 3
        try:
            self._refresh_client_auth()
            async for event in self._stream_once(request):
                yield event
            return  # 成功，退出重试循环
        except OpenHarnessApiError:
            raise  # 认证错误不重试
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_RETRIES or not _is_retryable(exc):
                raise _translate_api_error(exc) from exc

            delay = _get_retry_delay(attempt, exc)
            yield ApiRetryEvent(
                message=str(exc),
                attempt=attempt + 1,
                max_attempts=MAX_RETRIES + 1,
                delay_seconds=delay,
            )
            await asyncio.sleep(delay)  # 非阻塞等待
```

指数退避计算函数：

```python
def _get_retry_delay(attempt: int, exc: Exception | None = None) -> float:
    """计算带抖动的指数退避延迟。"""
    import random
    # 检查 Retry-After 响应头
    if isinstance(exc, APIStatusError):
        retry_after = getattr(exc, "headers", {})
        if hasattr(retry_after, "get"):
            val = retry_after.get("retry-after")
            if val:
                try:
                    return min(float(val), MAX_DELAY)
                except (ValueError, TypeError):
                    pass
    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)  # 1s, 2s, 4s, ...
    jitter = random.uniform(0, delay * 0.25)               # 25% 随机抖动
    return delay + jitter
```

> **Java 对比**
>
> Python 的 `await asyncio.sleep(delay)` 对应 Java 中的 `Thread.sleep(delay)`，但关键区别是：`asyncio.sleep()` **不会阻塞线程**，它暂停当前协程，让事件循环运行其他就绪的协程。这意味着即使有 100 个并发请求同时在退避等待，也只使用一个线程。Java 中如果用 `Thread.sleep()`，100 个线程就全部被阻塞了；用 `CompletableFuture.delayedExecutor()` 可以避免，但 API 更复杂。

### 5. run_in_executor — 桥接阻塞 I/O

`swarm/mailbox.py` 中的 `TeammateMailbox` 类是文件 I/O 密集的组件。由于文件操作是阻塞的（`Path.read_text()`, `os.replace()` 等），必须用 `run_in_executor()` 将它们移到线程池：

```python
class TeammateMailbox:
    async def write(self, msg: MailboxMessage) -> None:
        """原子写入消息到收件箱。"""
        inbox = self.get_mailbox_dir()
        filename = f"{msg.timestamp:.6f}_{msg.id}.json"
        final_path = inbox / filename
        tmp_path = inbox / f"{filename}.tmp"
        lock_path = inbox / ".write_lock"
        payload = json.dumps(msg.to_dict(), indent=2)

        def _write_atomic() -> None:
            with exclusive_file_lock(lock_path):
                tmp_path.write_text(payload, encoding="utf-8")
                os.replace(tmp_path, final_path)

        # 将阻塞 I/O 委派到线程池
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_atomic)

    async def read_all(self, unread_only: bool = True) -> list[MailboxMessage]:
        """从收件箱读取消息，按时间戳排序。"""
        inbox = self.get_mailbox_dir()

        def _read_all() -> list[MailboxMessage]:
            messages: list[MailboxMessage] = []
            for path in sorted(inbox.glob("*.json")):
                if path.name.startswith(".") or path.name.endswith(".tmp"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    msg = MailboxMessage.from_dict(data)
                    if not unread_only or not msg.read:
                        messages.append(msg)
                except (json.JSONDecodeError, KeyError):
                    continue
            return messages

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read_all)
```

> **Java 对比**
>
> `run_in_executor(None, blocking_func)` 对应 Java 中将阻塞操作提交到 `ExecutorService`：`executor.submit(blockingCallable).get()`。Python 的 `None` 参数使用默认的 `ThreadPoolExecutor`（线程数 = `min(32, os.cpu_count() + 4)`）。在 Java 中这更自然，因为所有 I/O 默认就是多线程的；在 Python asyncio 中，这是唯一安全的将阻塞代码融入事件循环的方式。

## Python 概念说明

### 协作式多任务 vs 抢占式多任务

Python asyncio 的核心原则：**一个协程只有主动 `await` 时才让出控制权**。这意味着：

```python
# 错误示范 — 冻结事件循环！
async def bad_handler():
    time.sleep(10)         # 阻塞整个事件循环 10 秒！
    result = requests.get(url)  # 同步 HTTP 请求，同样阻塞！

# 正确示范 — 非阻塞
async def good_handler():
    await asyncio.sleep(10)  # 让出控制权，其他协程可以运行
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            result = await resp.text()
```

### AsyncIterator 与 async for

Python 的 `AsyncIterator` 是异步版本的迭代器协议：

```python
# 定义 AsyncIterator
async def submit_message(prompt: str) -> AsyncIterator[StreamEvent]:
    async for event in api_client.stream_message(request):
        if isinstance(event, ApiTextDeltaEvent):
            yield AssistantTextDelta(text=event.text)
        elif isinstance(event, ApiMessageCompleteEvent):
            yield AssistantTurnComplete(...)

# 消费 AsyncIterator
async for event in engine.submit_message("你好"):
    if isinstance(event, AssistantTextDelta):
        print(event.text, end="", flush=True)
```

这比 Java 的 `Flux` 更简洁，因为不需要 `subscribe()`、`doOnNext()`、`doOnError()` 等操作符链。

### asyncio.Queue 的背压机制

```python
queue = asyncio.Queue(maxsize=100)  # 有界队列

async def producer():
    await queue.put(item)  # 队列满时暂停生产者

async def consumer():
    item = await queue.get()  # 队列空时暂停消费者
    queue.task_done()         # 标记任务完成
```

`asyncio.Queue` 天然支持背压：当队列满时，`put()` 暂停生产者协程，直到消费者取出元素。这与 Java `BlockingQueue` 的行为类似，但不阻塞线程。

## 架构图

```
+-------------------+     +-------------------+     +-------------------+
|  Telegram/Discord |     |     Slack/WeChat   |     |    Email/Matrix   |
|  Channel Adapter  |     |   Channel Adapter  |     |   Channel Adapter |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         | publish_inbound()       | publish_inbound()       | publish_inbound()
         v                         v                         v
+--------------------------------------------------------------------------+
|                          asyncio.Queue[InboundMessage]                    |
|                            (MessageBus.inbound)                          |
+--------------------------------------------------------------------------+
         |                         |
         | consume_inbound()       |
         v                         |
+--------+----------+     +--------+----------+
|  ChannelBridge     |     |  ChannelBridge     |
|  (async for loop)  |     |  (async for loop)  |
+--------+----------+     +--------+----------+
         |                         |
         | submit_message()        |
         v                         |
+-------------------+     +--------+----------+
|   QueryEngine     |     |   QueryEngine     |
| (agent loop +     |     | (agent loop +     |
|  tool execution)  |     |  tool execution)  |
+--------+----------+     +--------+----------+
         |                         |
         | yield StreamEvent       |
         v                         v
+--------------------------------------------------------------------------+
|                          asyncio.Queue[OutboundMessage]                  |
|                           (MessageBus.outbound)                          |
+--------------------------------------------------------------------------+
         |                         |                         |
         | consume_outbound()     | consume_outbound()      |
         v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|  Telegram Channel |     |  Slack Channel    |     |  Email Channel    |
|  send response    |     |  send response    |     |  send response    |
+-------------------+     +-------------------+     +-------------------+

         +----------------------------------------------------+
         |              Swarm TeammateMailbox                  |
         |  (文件系统 + run_in_executor 桥接)                   |
         |  write() -> run_in_executor(_write_atomic)          |
         |  read_all() -> run_in_executor(_read_all)           |
         +----------------------------------------------------+
```

## 小结

本章覆盖了 OpenHarness 中 asyncio 使用的核心模式：

1. **asyncio.Queue 作为消息总线**：`MessageBus` 用入站/出站双队列解耦渠道与引擎，与 Java `BlockingQueue` 功能等价但不阻塞线程。

2. **async for 流式消费**：`ChannelBridge` 通过嵌套的 `async for` 循环实现消息消费和流式事件处理，比 Java Reactor 的操作符链更直观。

3. **asyncio.create_task() 后台调度**：桥接循环作为独立任务运行，类比 `ExecutorService.submit()` 但开销更低。

4. **指数退避重试**：`AnthropicApiClient` 的重试逻辑使用 `await asyncio.sleep()` 而非 `Thread.sleep()`，确保等待期间事件循环不被阻塞。

5. **run_in_executor 桥接阻塞 I/O**：`TeammateMailbox` 将文件操作委派到线程池，是 asyncio 中处理阻塞操作的标准模式。

从 Java 转向 Python asyncio 的关键思维转换是：**一切必须是非阻塞的**。如果在 `async def` 函数中调用了阻塞操作，整个事件循环都会停摆。`run_in_executor` 是你的逃生通道。