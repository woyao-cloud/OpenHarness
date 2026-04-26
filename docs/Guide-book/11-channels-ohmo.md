# 第 11 章：聊天频道与 ohmo 个人 Agent

## 11.1 解决的问题

OpenHarness 不仅是一个 CLI 工具，还是一个**多渠道个人 AI Agent**。ohmo 允许用户通过 Telegram、Slack、Discord、飞书等平台与 AI Agent 交互。需要解决：

1. **多渠道接入**：统一接口对接不同的聊天平台
2. **消息路由**：将不同渠道的消息路由到正确的会话
3. **长时间运行**：Gateway 服务需要 7x24 小时在线
4. **会话隔离**：不同频道、不同会话互不干扰

## 11.2 消息总线

### 11.2.1 MessageBus

`channels/bus/queue.py`：

```python
class MessageBus:
    """基于 asyncio.Queue 的消息总线，解耦频道和引擎。"""
    
    def __init__(self):
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
    
    async def publish_inbound(self, message: InboundMessage) -> None:
        """频道 → 引擎"""
        await self._inbound.put(message)
    
    async def consume_inbound(self) -> InboundMessage:
        """引擎消费入站消息"""
        return await self._inbound.get()
    
    async def publish_outbound(self, message: OutboundMessage) -> None:
        """引擎 → 频道"""
        await self._outbound.put(message)
    
    async def consume_outbound(self) -> OutboundMessage:
        """频道消费出站消息"""
        return await self._outbound.get()
```

### 11.2.2 消息类型

```python
@dataclass
class InboundMessage:
    channel: str                   # 来源频道
    sender_id: str                 # 发送者 ID
    chat_id: str                   # 聊天 ID
    content: str                   # 消息内容
    media: list[MediaAttachment] | None  # 附件
    metadata: dict | None          # 额外元数据
    session_key: str | None        # 会话路由键

@dataclass
class OutboundMessage:
    channel: str                   # 目标频道
    chat_id: str                   # 目标聊天
    content: str                   # 消息内容
    metadata: dict | None          # 额外元数据
```

## 11.3 频道适配器

### 11.3.1 BaseChannel

`channels/impl/base.py`：

```python
class BaseChannel(ABC):
    """频道适配器的基类。"""
    
    name: str = ""              # 频道名称
    
    @abstractmethod
    async def start(self) -> None:
        """启动频道连接（如 Telegram 长轮询）。"""
    
    @abstractmethod
    async def stop(self) -> None:
        """停止频道连接。"""
    
    @abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """发送消息到频道。"""
    
    def is_allowed(self, sender_id: str) -> bool:
        """检查发送者是否在允许列表中。"""
        if not self._allow_list:
            return True
        return sender_id in self._allow_list
```

### 11.3.2 ChannelBridge

`channels/adapter.py` 将消息总线和引擎连接：

```python
class ChannelBridge:
    """连接 MessageBus 和 QueryEngine。"""
    
    def __init__(self, bus, engine):
        self._bus = bus
        self._engine = engine
    
    async def run(self):
        """持续消费入站消息并处理。"""
        while True:
            inbound = await self._bus.consume_inbound()
            
            # 处理消息
            async for event in self._engine.submit_message(inbound.content):
                if isinstance(event, AssistantTextDelta):
                    # 累积文本
                    ...
                elif isinstance(event, AssistantTurnComplete):
                    # 发送完整回复到频道
                    reply = OutboundMessage(
                        channel=inbound.channel,
                        chat_id=inbound.chat_id,
                        content=event.message.text,
                    )
                    await self._bus.publish_outbound(reply)
```

### 11.3.3 已实现频道

| 频道 | 文件 | 依赖 |
|------|------|------|
| Telegram | `impl/telegram.py` | `python-telegram-bot` |
| Slack | `impl/slack.py` | `slack-sdk` |
| Discord | `impl/discord.py` | `discord.py` |
| Feishu | `impl/feishu.py` | `lark-oapi` |
| DingTalk | `impl/dingtalk.py` | 自有 API |
| WhatsApp | `impl/whatsapp.py` | Web API |
| QQ | `impl/qq.py` | 自有协议 |
| Matrix | `impl/matrix.py` | Matrix 协议 |
| Mochat | `impl/mochat.py` | 自有 API |
| Email | `impl/email.py` | SMTP/IMAP |

### 11.3.4 ChannelManager

`channels/impl/manager.py`：

```python
class ChannelManager:
    """管理所有频道的生命周期。"""
    
    def __init__(self, bus: MessageBus):
        self._bus = bus
        self._channels: dict[str, BaseChannel] = {}
    
    async def start_channels(self, configs: list[ChannelConfig]):
        """启动配置中的所有频道。"""
        for config in configs:
            channel = self._create_channel(config)
            await channel.start()
            self._channels[config.name] = channel
    
    async def stop_all(self):
        """停止所有频道。"""
        for channel in self._channels.values():
            await channel.stop()
    
    async def dispatch_outbound(self, message: OutboundMessage):
        """将出站消息分发到目标频道。"""
        channel = self._channels.get(message.channel)
        if channel:
            await channel.send(message)
```

## 11.4 ohmo 个人 Agent

### 11.4.1 工作空间

ohmo 使用独立的 `~/.ohmo/` 工作空间：

```
~/.ohmo/
  soul.md                   ← Agent 人格（你是谁）
  identity.md               ← 身份（你是谁）
  user.md                   ← 用户画像
  BOOTSTRAP.md              ← 首次启动引导
  memory/                   ← 个人记忆
    MEMORY.md
  gateway.json              ← Gateway 配置
  sessions/                 ← 会话快照
  logs/                     ← 运行日志
  skills/                   ← 额外技能
  plugins/                  ← 额外插件
```

### 11.4.2 系统提示词

`ohmo/prompts.py` 构建 ohmo 专属系统提示词：

```python
def build_ohmo_system_prompt(cwd, workspace=None):
    sections = []
    
    # 1. 基础系统提示词
    sections.append(BASE_PROMPT)
    
    # 2. SOUL.md（人格设定）
    soul = workspace / "soul.md"
    if soul.exists():
        sections.append(soul.read_text())
    
    # 3. identity.md
    identity = workspace / "identity.md"
    if identity.exists():
        sections.append(identity.read_text())
    
    # 4. user.md（用户画像）
    user = workspace / "user.md"
    if user.exists():
        sections.append(user.read_text())
    
    # 5. BOOTSTRAP.md（引导提示）
    bootstrap = workspace / "BOOTSTRAP.md"
    if bootstrap.exists():
        sections.append(bootstrap.read_text())
    
    # 6. 记忆
    memory_dir = workspace / "memory"
    sections.append(load_memory_prompt(memory_dir))
    
    return "\n\n".join(sections)
```

### 11.4.3 Gateway 架构

`ohmo/gateway/service.py` 中的 `OhmoGatewayService` 是核心 Gateway：

```python
class OhmoGatewayService:
    """24/7 运行的个人 Agent Gateway。"""
    
    async def start(self):
        """启动 Gateway。"""
        # 1. 初始化频道
        await self._channel_manager.start_channels(
            self._config.channels
        )
        
        # 2. 启动消息处理循环
        self._task = asyncio.create_task(self._run_loop())
    
    async def _run_loop(self):
        """消息处理主循环。"""
        while True:
            inbound = await self._bus.consume_inbound()
            
            # 路由到正确的会话
            session_key = session_key_for_message(inbound)
            
            # 获取或创建会话 Runtime
            runtime = await self._pool.get_or_create(session_key)
            
            # 处理消息
            async for event in runtime.process(inbound.content):
                if isinstance(event, AssistantTurnComplete):
                    reply = OutboundMessage(
                        channel=inbound.channel,
                        chat_id=inbound.chat_id,
                        content=event.message.text,
                    )
                    await self._bus.publish_outbound(reply)
```

### 11.4.4 会话池

`ohmo/gateway/runtime.py` 中的 `OhmoSessionRuntimePool` 管理每个聊天会话的 Runtime：

```python
class OhmoSessionRuntimePool:
    """每个聊天会话一个 RuntimeBundle 实例。"""
    
    def __init__(self):
        self._runtimes: dict[str, RuntimeBundle] = {}
    
    async def get_or_create(self, session_key: str) -> RuntimeBundle:
        """获取或创建会话 Runtime。"""
        if session_key not in self._runtimes:
            bundle = await self._create_runtime(session_key)
            self._runtimes[session_key] = bundle
        return self._runtimes[session_key]
    
    async def _create_runtime(self, session_key: str) -> RuntimeBundle:
        """创建新的会话 Runtime。"""
        # 尝试恢复已有会话
        snapshot = self._session_backend.load_latest(session_key)
        
        bundle = await build_runtime(
            model=self._config.model,
            system_prompt=build_ohmo_system_prompt(cwd, workspace),
            session_backend=OhmoSessionBackend(workspace),
            ...
        )
        
        if snapshot:
            bundle.engine.load_messages(snapshot.messages)
        
        return bundle
```

### 11.4.5 会话路由

`ohmo/gateway/router.py` 实现消息到会话的映射：

```python
def session_key_for_message(message: InboundMessage) -> str:
    """根据消息生成会话路由键。"""
    # 使用 channel + chat_id 作为默认键
    if message.session_key:
        return message.session_key
    
    # 根据频道特性处理
    if message.channel == "telegram":
        # Telegram: 每个 chat 一个会话
        return f"telegram:{message.chat_id}"
    elif message.channel == "slack":
        # Slack: 每个 thread 一个会话
        thread = message.metadata.get("thread_ts")
        if thread:
            return f"slack:{message.chat_id}:{thread}"
        return f"slack:{message.chat_id}"
    # ...
```

## 11.5 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| 消息总线 | `channels/bus/queue.py` | `MessageBus` |
| 消息类型 | `channels/bus/events.py` | `InboundMessage`, `OutboundMessage` |
| 频道基类 | `channels/impl/base.py` | `BaseChannel` |
| 频道管理 | `channels/impl/manager.py` | `ChannelManager` |
| 桥接器 | `channels/adapter.py` | `ChannelBridge` |
| ohmo 提示词 | `ohmo/prompts.py` | `build_ohmo_system_prompt()` |
| ohmo Gateway | `ohmo/gateway/service.py` | `OhmoGatewayService` |
| 会话池 | `ohmo/gateway/runtime.py` | `OhmoSessionRuntimePool` |
| 会话路由 | `ohmo/gateway/router.py` | `session_key_for_message()` |
| 频道实现 | `channels/impl/*.py` | Telegram, Slack, Discord 等 |

## 11.6 本章小结

聊天频道系统通过 **MessageBus（异步队列） + BaseChannel（适配器模式）+ ChannelManager（生命周期管理）** 的设计，实现了多渠道接入的解耦。ohmo 在此基础上构建了**个人 Agent Gateway**：每个聊天会话维护一个独立的 RuntimeBundle，支持 7x24 小时运行，通过 SessionPool 实现资源管理。

> 下一章：[沙箱与安全执行](12-sandbox.md) —— 命令隔离与 Docker 沙箱。
