# 第十三章：Channel 系统 —— 总线/适配器模式与十平台接入

## 概述

OpenHarness 的 Channel 子系统负责将 10 个聊天平台（Telegram、Slack、Discord、飞书、钉钉、Email、QQ、Matrix、WhatsApp、Mochat）统一接入到同一个查询引擎。它的核心设计采用「消息总线 + 适配器」模式：各平台通过 `BaseChannel` 适配器接入，所有消息经由 `MessageBus` 异步队列进行解耦传递，`ChannelBridge` 负责在总线和引擎之间桥接流转。

这种架构让新增一个聊天平台只需实现一个 `BaseChannel` 子类，无需修改引擎或总线逻辑——体现了开闭原则（OCP）的精髓。

## Java 类比

> **Java 对比**：如果你熟悉 Spring Integration，`MessageBus` 的角色类似于 `MessageChannel`——它解耦了生产者和消费者。Spring Integration 通过 `DirectChannel`、`QueueChannel` 等实现消息管道；OpenHarness 的 `MessageBus` 则用 `asyncio.Queue` 实现了类似的功能，但更轻量、更 Pythonic。`BaseChannel` 的 ABC（抽象基类）类似于 Java 的 `interface`，`_handle_message` 中的权限检查则类似于 Spring Security 的 `@PreAuthorize` 注解。`ChannelBridge` 承担了 Mediator 模式的角色，类似 Spring 中 `@Service` 编排多个组件的协作。

## 项目代码详解

### MessageBus：异步消息队列

`MessageBus` 是整个 Channel 子系统的中枢，位于 `channels/bus/queue.py`：

```python
class MessageBus:
    """Async message bus that decouples chat channels from the agent core."""

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        return self.outbound.qsize()
```

关键设计点：
- **双队列分离**：`inbound` 和 `outbound` 是两条独立的 `asyncio.Queue`，保证出入方向互不干扰
- **泛型队列**：`asyncio.Queue[InboundMessage]` 利用 Python 3.12+ 的泛型语法，在类型层面约束消息类型
- **阻塞式消费**：`consume_inbound()` 和 `consume_outbound()` 是 `async` 方法，在没有消息时会自动挂起当前协程，不占用线程

> **Java 对比**：`asyncio.Queue` 的效果类似于 Java 中 `BlockingQueue`（如 `LinkedBlockingQueue`），但 `asyncio.Queue` 是协程级别的非阻塞等待，不会占用线程池资源。Spring Integration 的 `QueueChannel` 配合 `@ServiceActivator` 实现类似解耦，但需要更多配置代码。

### InboundMessage 和 OutboundMessage：消息数据类

位于 `channels/bus/events.py`，采用 Python 的 `@dataclass` 定义：

```python
@dataclass
class InboundMessage:
    """Message received from a chat channel."""
    channel: str                          # telegram, discord, slack, whatsapp ...
    sender_id: str                        # 用户标识
    chat_id: str                          # 会话/频道标识
    content: str                          # 消息文本
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)    # 媒体文件 URL
    metadata: dict[str, Any] = field(default_factory=dict)  # 平台特有数据
    session_key_override: str | None = None  # 可选的线程级会话覆盖

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""
    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

> **Java 对比**：Java 中的 DTO（Data Transfer Object）通常需要手写 getter/setter、构造函数、equals/hashCode。Python 的 `@dataclass` 自动生成 `__init__`、`__repr__`、`__eq__` 等，代码量减少 70%+。`field(default_factory=list)` 等价于 Java 中在构造器里初始化 `new ArrayList<>()`，避免了可变默认参数的陷阱。

### BaseChannel：抽象基类与权限检查

`BaseChannel` 位于 `channels/impl/base.py`，是所有平台适配器的父类：

```python
class BaseChannel(ABC):
    """Abstract base class for chat channel implementations."""

    name: str = "base"

    def __init__(self, config: Any, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start the channel and begin listening for messages."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through this channel."""
        pass

    def is_allowed(self, sender_id: str) -> bool:
        """Check if sender_id is permitted."""
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            return False
        if "*" in allow_list:
            return True
        sender_str = str(sender_id)
        return sender_str in allow_list or any(
            p in allow_list for p in sender_str.split("|") if p
        )

    async def _handle_message(self, sender_id, chat_id, content, ...):
        """Handle an incoming message: check permissions, forward to bus."""
        if not self.is_allowed(sender_id):
            logger.warning("Access denied for sender %s on channel %s", ...)
            return
        msg = InboundMessage(channel=self.name, sender_id=str(sender_id), ...)
        await self.bus.publish_inbound(msg)
```

关键设计点：
- **ABC 抽象基类**：Python 的 `ABC` + `@abstractmethod` 类似 Java 的 `abstract class`，强制子类实现 `start`、`stop`、`send`
- **模板方法模式**：`_handle_message` 是一个模板方法，子类无需重写它，只需在各自的平台回调中调用即可
- **权限检查**：`is_allowed` 方法实现了白名单检查，`"*"` 表示允许所有用户，空列表拒绝所有

`resolve_channel_media_dir()` 工具函数为每个频道提供媒体下载目录：

```python
def resolve_channel_media_dir(channel_name: str) -> Path:
    """Return the local download directory for inbound channel media."""
    custom_root = os.environ.get("OPENHARNESS_CHANNEL_MEDIA_DIR")
    if custom_root:
        root = Path(custom_root).expanduser().resolve()
    else:
        ohmo_workspace = os.environ.get("OHMO_WORKSPACE")
        if ohmo_workspace:
            from ohmo.workspace import get_attachments_dir
            root = get_attachments_dir(ohmo_workspace)
        else:
            root = get_data_dir() / "media"
    media_dir = root / channel_name
    media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir
```

> **Java 对比**：`BaseChannel` 的 ABC 模式等价于 Java 的 `abstract class Channel { abstract void start(); abstract void stop(); abstract void send(OutboundMessage msg); }`。Python 的 `@abstractmethod` 在运行时检查实例化，而 Java 在编译期检查。`is_allowed` 的白名单模式类似 Spring Security 的 `AccessDecisionManager` 中基于角色的投票器。

### ChannelManager：生命周期与分发

`ChannelManager` 位于 `channels/impl/manager.py`，负责初始化、启动、停止所有频道，并分发 outbound 消息：

```python
class ChannelManager:
    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        if self.config.channels.telegram.enabled:
            from openharness.channels.impl.telegram import TelegramChannel
            self.channels["telegram"] = TelegramChannel(...)
        if self.config.channels.discord.enabled:
            from openharness.channels.impl.discord import DiscordChannel
            self.channels["discord"] = DiscordChannel(...)
        # ... 8 more channels
        self._validate_allow_from()

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        tasks = [asyncio.create_task(self._start_channel(name, ch))
                 for name, ch in self.channels.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        while True:
            msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
            channel = self.channels.get(msg.channel)
            if channel:
                await channel.send(msg)
```

关键设计点：
- **延迟导入**：各频道实现在 `_init_channels` 中使用函数级 `import`，避免缺少可选依赖时全局崩溃
- **优雅降级**：`_start_channel` 包裹了 try/except，单个频道启动失败不影响其他频道
- **asyncio.gather**：`start_all` 用 `gather` 并发启动所有频道，而非逐个等待

### ChannelBridge：总线与引擎的桥梁

`ChannelBridge` 位于 `channels/adapter.py`，是连接 MessageBus 和 QueryEngine 的关键组件：

```python
class ChannelBridge:
    def __init__(self, *, engine: "QueryEngine", bus: MessageBus) -> None:
        self._engine = engine
        self._bus = bus
        self._running = False
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        """Main processing loop: consume -> process -> publish."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._bus.consume_inbound(), timeout=1.0)
                await self._handle(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _handle(self, msg: InboundMessage) -> None:
        """Process one inbound message and publish the reply."""
        reply_parts: list[str] = []
        async for event in self._engine.submit_message(msg.content):
            if isinstance(event, AssistantTextDelta):
                reply_parts.append(event.text)
        reply_text = "".join(reply_parts).strip()
        if not reply_text:
            return
        outbound = OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id,
            content=reply_text,
            metadata={"_session_key": msg.session_key},
        )
        await self._bus.publish_outbound(outbound)
```

> **Java 对比**：`ChannelBridge` 承担了 Mediator 模式的角色，类似于 Spring 中 `@Service` 编排多个组件的协作。`_loop` 中的 `asyncio.wait_for` 模式等价于 Java 的 `CompletableFuture.get(timeout, TimeUnit)`，但基于协程，不会阻塞线程。整个 Bridge 的事件流处理类似于 Spring Integration 的 `@ServiceActivator` + `IntegrationFlow`。

### 10 个频道实现

OpenHarness 目前支持 10 个聊天平台，每个都继承 `BaseChannel`：

| 平台 | 类名 | 关键依赖 | 接入方式 |
|------|------|----------|----------|
| Telegram | `TelegramChannel` | `python-telegram-bot` | Long Polling |
| Slack | `SlackChannel` | `slack_sdk` | Socket Mode (WebSocket) |
| Discord | `DiscordChannel` | `websockets`, `httpx` | Gateway WebSocket |
| 飞书 | `FeishuChannel` | `lark_oapi` | WebSocket Long Connection |
| 钉钉 | `DingTalkChannel` | `dingtalk_stream` | Stream Mode |
| Email | `EmailChannel` | `aiosmtplib`, `imapclient` | SMTP/IMAP |
| QQ | `QQChannel` | `aiocqhttp` | HTTP/WebSocket |
| Matrix | `MatrixChannel` | `matrix-nio` | E2EE WebSocket |
| WhatsApp | `WhatsAppChannel` | `httpx` | WhatsApp Cloud API |
| Mochat | `MochatChannel` | `httpx` | HTTP Webhook |

每个频道实现只需关注三件事：
1. **`start()`**：连接到平台 API，开始监听
2. **`stop()`**：断开连接，清理资源
3. **`send(msg)`**：将 `OutboundMessage` 发送到对应平台

以 TelegramChannel 为例，`start()` 方法初始化 `python-telegram-bot` 的 `Application`，注册消息处理器，然后启动 Long Polling：

```python
class TelegramChannel(BaseChannel):
    name = "telegram"

    async def start(self) -> None:
        self._app = Application.builder().token(self.config.token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        while self._running:
            await asyncio.sleep(1)
```

## Python 概念说明

### asyncio.Queue：协程级消息队列

Python 的 `asyncio.Queue` 是协程安全的生产者-消费者队列。与 Java 的 `BlockingQueue` 不同：
- `asyncio.Queue` 的 `put()` 和 `get()` 是 `async` 协程方法，挂起时不占用线程
- Java 的 `BlockingQueue.put()` 会阻塞线程，高并发下线程池容易耗尽
- Python 的模式天然适合 I/O 密集型场景（如同时监听 10 个聊天平台）

### @dataclass：零样板数据类

Python 3.7+ 的 `@dataclass` 自动生成 `__init__`、`__repr__`、`__eq__` 等方法：

```python
@dataclass
class InboundMessage:
    channel: str
    sender_id: str
    content: str
```

等价于 Java 中手写几十行的 DTO 类。`frozen=True` 参数使其不可变，类似于 Java 14+ 的 `record`。

### ABC：抽象基类

Python 的 `ABC` + `@abstractmethod` 提供了与 Java `abstract class` 类似的功能：

```python
from abc import ABC, abstractmethod

class BaseChannel(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None: ...
```

区别在于：Java 在编译期检查抽象方法实现，Python 在实例化时检查。如果你忘记实现 `start()`，Python 会在 `BaseChannel()` 时抛出 `TypeError`。

### 延迟导入（Lazy Import）

`ChannelManager._init_channels()` 中使用了函数级导入：

```python
if self.config.channels.telegram.enabled:
    from openharness.channels.impl.telegram import TelegramChannel  # 延迟导入
    self.channels["telegram"] = TelegramChannel(...)
```

这样做的优势：
- 可选依赖只在需要时才导入，缺少 `python-telegram-bot` 不影响 Discord 用户
- 导入错误被捕获并降级为警告，不会导致整个应用崩溃
- Java 中类似效果需要用 `Class.forName()` 或 OSGi 动态加载

## 架构图

```
+--------+  +--------+  +--------+       +---------+  +---------+
|Telegram|  | Slack  |  |Discord |  ...  |WhatsApp |  | Mochat  |
+---+----+  +---+----+  +---+----+       +----+----+  +----+----+
    |           |           |                  |             |
    v           v           v                  v             v
+------------------------------------------------------------------+
|                    BaseChannel._handle_message()                  |
|                    (权限检查 + 构造 InboundMessage)                |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
|                    MessageBus.inbound (asyncio.Queue)             |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
|                    ChannelBridge._loop()                          |
|                    (消费 inbound -> 提交引擎 -> 发布 outbound)     |
+------------------------------------------------------------------+
                            |
                +-----------+-----------+
                |                       |
                v                       v
+------------------------+   +--------------------------+
| QueryEngine           |   | ChannelBridge._handle()  |
| .submit_message()     |   | (组装 OutboundMessage)    |
+------------------------+   +-----------+--------------+
                                         |
                                         v
                    +--------------------------+
                    | MessageBus.outbound      |
                    | (asyncio.Queue)          |
                    +------------+-------------+
                                 |
                                 v
+------------------------------------------------------------------+
|               ChannelManager._dispatch_outbound()                |
|               (路由到目标频道)                                      |
+------------------------------------------------------------------+
                            |
    +-----------+-----------+-----------+-----------+
    |           |           |           |           |
    v           v           v           v           v
 Telegram     Slack     Discord     Feishu     DingTalk ...
 .send()     .send()    .send()     .send()    .send()
```

## 小结

本章深入解析了 OpenHarness 的 Channel 子系统，核心要点如下：

1. **MessageBus** 用 `asyncio.Queue` 实现了线程安全（协程安全）的双向消息管道，完全解耦了频道层和引擎层
2. **InboundMessage / OutboundMessage** 用 `@dataclass` 实现了零样板的消息 DTO，包含频道、会话、媒体等完整上下文
3. **BaseChannel** ABC 定义了 `start/stop/send` 三个抽象方法，`_handle_message` 模板方法内嵌权限检查
4. **ChannelManager** 采用延迟导入 + 优雅降级策略管理 10 个平台，`_dispatch_outbound` 持续消费 outbound 队列并路由
5. **ChannelBridge** 作为 Mediator，将 inbound 消息送入 QueryEngine，将流式响应组装为 outbound 消息
6. 新增平台只需继承 `BaseChannel`，实现三个方法，在配置中启用即可——无需修改总线或引擎代码

对于 Java 转 Python 的开发者，关键差异在于：`asyncio.Queue` 替代 `BlockingQueue`、`@dataclass` 替代手写 DTO、ABC 替代 `interface`，以及函数级延迟导入替代反射或 OSGi 动态加载。理解这些映射后，Channel 系统的架构意图便一目了然。