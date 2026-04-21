# 第三章：数据类——@dataclass 与 BaseModel 的选择

## 概述

上一章我们详细讲解了 Pydantic `BaseModel`。然而 Python 还有另一种定义数据类的方式——标准库的 `@dataclass`。OpenHarness 同时使用了这两种模式，且有着清晰的分工：

- **BaseModel** 用于需要序列化/校验/JSON 互操作的配置模型
- **@dataclass** 用于内部传递的轻量值对象和事件类型

本章将回答一个关键问题：**什么时候用 `@dataclass`，什么时候用 `BaseModel`？**

## Java 类比

| Java 概念 | Python 对应 | 典型用途 |
|-----------|------------|---------|
| `record` | `@dataclass(frozen=True)` | 不可变值对象 |
| POJO + Jackson | `pydantic.BaseModel` | 需要序列化的数据模型 |
| `sealed interface` + `permits` | `X \| Y` 联合类型 | 有限类型集合 |
| `Set.of("a", "b")` | `frozenset({"a", "b"})` | 不可变常量集合 |

## 项目代码详解

### 1. `@dataclass(frozen=True)`——不可变值对象

**`api/provider.py`——ProviderInfo**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Resolved provider metadata for UI and diagnostics."""

    name: str
    auth_kind: str
    voice_supported: bool
    voice_reason: str
```

**`api/client.py`——API 事件模型**

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApiMessageRequest:
    """Input parameters for a model invocation."""

    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ApiTextDeltaEvent:
    """Incremental text produced by the model."""

    text: str


@dataclass(frozen=True)
class ApiMessageCompleteEvent:
    """Terminal event containing the full assistant message."""

    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None = None


@dataclass(frozen=True)
class ApiRetryEvent:
    """A recoverable upstream failure that will be retried automatically."""

    message: str
    attempt: int
    max_attempts: int
    delay_seconds: float
```

> **Java 对比**：
>
> ```java
> // Java 14+ record
> public record ProviderInfo(
>     String name,
>     String authKind,
>     boolean voiceSupported,
>     String voiceReason
> ) {}
>
> public record ApiTextDeltaEvent(String text) {}
>
> public record ApiRetryEvent(
>     String message,
>     int attempt,
>     int maxAttempts,
>     double delaySeconds
> ) {}
> ```
>
> Python 的 `@dataclass(frozen=True)` 与 Java `record` 几乎完全对应：
> - 都是不可变的（创建后不能修改字段）
> - 都自动生成 `equals`/`hashCode`/`toString`
> - 都只携带数据，不含复杂业务逻辑

**为什么用 `frozen=True`？**

```python
@dataclass(frozen=True)
class ApiTextDeltaEvent:
    text: str

event = ApiTextDeltaEvent(text="hello")
event.text = "world"  # ← FrozenInstanceError! 不允许修改
```

不可变保证意味着：
- 安全地作为字典 key 或放入集合
- 多线程安全（无需同步）
- 防止意外修改

> **Java 对比**：Java `record` 天然不可变——没有 setter，字段是 final 的。Python 需要显式 `frozen=True` 来达到同样效果。

### 2. 联合类型：`|` 运算符

**`api/client.py`——ApiStreamEvent**

```python
ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent
```

**`engine/stream_events.py`——StreamEvent**

```python
@dataclass(frozen=True)
class AssistantTextDelta:
    text: str

@dataclass(frozen=True)
class AssistantTurnComplete:
    message: ConversationMessage
    usage: UsageSnapshot

@dataclass(frozen=True)
class ToolExecutionStarted:
    tool_name: str
    tool_input: dict[str, Any]

@dataclass(frozen=True)
class ToolExecutionCompleted:
    tool_name: str
    output: str
    is_error: bool = False

@dataclass(frozen=True)
class ErrorEvent:
    message: str
    recoverable: bool = True

@dataclass(frozen=True)
class StatusEvent:
    message: str

@dataclass(frozen=True)
class CompactProgressEvent:
    phase: Literal["hooks_start", "context_collapse_start", ...]
    trigger: Literal["auto", "manual", "reactive"]
    message: str | None = None
    attempt: int | None = None
    checkpoint: str | None = None
    metadata: dict[str, Any] | None = None

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

> **Java 对比**：
>
> ```java
> // Java 密封接口 + permits
> public sealed interface StreamEvent
>     permits AssistantTextDelta, AssistantTurnComplete,
>             ToolExecutionStarted, ToolExecutionCompleted,
>             ErrorEvent, StatusEvent, CompactProgressEvent {}
>
> public record AssistantTextDelta(String text) implements StreamEvent {}
> public record AssistantTurnComplete(ConversationMessage message, UsageSnapshot usage) implements StreamEvent {}
> // ...
> ```
>
> Python 的 `X | Y` 联合类型与 Java 的 `sealed interface` 解决同一个问题：**限定一组允许的类型**。但实现方式不同：
>
> | 特性 | Java sealed interface | Python X \| Y |
> |------|----------------------|--------------|
> | 类型安全 | 编译期检查 | 运行时 + 类型检查器（mypy） |
> | 语法 | 需要显式 `implements` | 仅声明联合类型 |
> | 模式匹配 | `switch` + pattern matching | `isinstance()` |
> | 子类限制 | 必须在同一包内 | 无限制 |

### 3. `field(default_factory=dict)`——dataclass 版本

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApiMessageRequest:
    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)
```

注意 `dataclasses.field()` 与 Pydantic `Field()` 的区别：

| 特性 | `dataclasses.field()` | `pydantic.Field()` |
|------|----------------------|-------------------|
| 所属模块 | 标准库 `dataclasses` | 第三方 `pydantic` |
| `default_factory` | `field(default_factory=list)` | `Field(default_factory=list)` |
| 额外功能 | 无（只有默认值、repr 等） | 校验、别名、描述、discriminator |
| 校验 | 无 | 内置类型校验 |

> **Java 对比**：`dataclasses.field(default_factory=list)` 对应 Java 构造器中的 `new ArrayList<>()`。Java 无需特殊语法——因为 Java 字段初始化在构造器中执行，天然独立。Python 因为类属性共享机制，必须用 `default_factory`。

### 4. `frozenset`——不可变常量集合

**`coordinator/agent_definitions.py`**

```python
#: Valid color names for agents (matches AgentColorName in TS).
AGENT_COLORS: frozenset[str] = frozenset(
    {
        "red",
        "green",
        "blue",
        "yellow",
        "purple",
        "orange",
        "cyan",
        "magenta",
        "white",
        "gray",
    }
)
```

> **Java 对比**：
>
> ```java
> // Java 9+ 不可变集合
> public static final Set<String> AGENT_COLORS = Set.of(
>     "red", "green", "blue", "yellow", "purple",
>     "orange", "cyan", "magenta", "white", "gray"
> );
> ```
>
> `frozenset` 与 `Set.of()` 的共同点：
> - 创建后不可修改（添加/删除/修改元素会抛异常）
> - 可以安全地作为模块级常量
> - 可以用作字典的 key
>
> 不同点：
> - Java `Set.of()` 不允许 `null` 元素；Python `frozenset` 不允许 `None`（因为 `None` 是有效的 hashable 值，但语义上通常不用）
> - Java `Set.of()` 在有重复元素时抛异常；Python `frozenset` 静默去重

同文件中的不可变 `tuple` 常量：

```python
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high")

PERMISSION_MODES: tuple[str, ...] = (
    "default",
    "acceptEdits",
    "bypassPermissions",
    "plan",
    "dontAsk",
)

MEMORY_SCOPES: tuple[str, ...] = ("user", "project", "local")
```

> **Java 对比**：
>
> ```java
> // Java 用 List.of() 或数组
> public static final List<String> EFFORT_LEVELS = List.of("low", "medium", "high");
> // 或
> private static final String[] EFFORT_LEVELS = {"low", "medium", "high"};
> ```
>
> Python 的 `tuple[str, ...]` 表示"元素数量不确定的字符串元组"，比 `list[str]` 更安全——元组不可变，防止意外修改。

### 5. `@dataclass(frozen=True)` 与 `BaseModel` 共存模式

OpenHarness 中两种模式共存，但分工明确：

**使用 `@dataclass(frozen=True)` 的场景**（内部值对象）：

- `ProviderInfo`——检测到的提供商元数据
- `ApiMessageRequest`——API 请求参数
- `ApiTextDeltaEvent` / `ApiMessageCompleteEvent` / `ApiRetryEvent`——流式事件
- `AssistantTextDelta` / `ToolExecutionStarted` / `ToolExecutionCompleted` / `ErrorEvent` / `StatusEvent` / `CompactProgressEvent`——引擎事件
- `ResolvedAuth`——解析后的认证信息

**使用 `BaseModel` 的场景**（配置/消息模型）：

- `Settings`——主配置
- `PermissionSettings` / `MemorySettings` / `SandboxSettings`——子配置
- `ProviderProfile`——提供商配置
- `ConversationMessage` / `TextBlock` / `ToolUseBlock` / `ToolResultBlock`——消息模型
- `AgentDefinition`——Agent 定义

### 6. `ResolvedAuth`——dataclass 中的混合模式

**`config/settings.py`**

```python
@dataclass(frozen=True)
class ResolvedAuth:
    """Normalized auth material used to construct API clients."""

    provider: str
    auth_kind: str
    value: str
    source: str
    state: str = "configured"
```

这个类使用 `@dataclass(frozen=True)` 而非 `BaseModel`，原因是：

1. 它不参与 JSON 序列化/反序列化——它是运行时内部传递的值对象
2. 它不需要校验——字段在构造时已被上游保证合法
3. 它不需要 `model_validate` / `model_dump`——只在代码中构造和读取
4. 它的 `state` 有默认值 `"configured"`，但不需要 Pydantic 的高级特性

## Python 概念说明

### dataclass vs BaseModel——决策指南

```
                    ┌─────────────────────────────┐
                    │  你需要序列化/反序列化吗？    │
                    │  (JSON ↔ Python 对象)       │
                    └──────────┬──────────────────┘
                               │
                    ┌──── Yes ─┤── No ────┐
                    │          │          │
                    ▼          │          ▼
           ┌──────────────┐   │   ┌──────────────┐
           │  BaseModel   │   │   │  @dataclass  │
           └──────────────┘   │   └──────────────┘
                               │
                    ┌──────────┴──────────────────┐
                    │  你需要字段校验吗？           │
                    │  (类型转换、范围检查等)       │
                    └──────────┬──────────────────┘
                               │
                    ┌──── Yes ─┤── No ────┐
                    │          │          │
                    ▼          │          ▼
           ┌──────────────┐   │   ┌──────────────┐
           │  BaseModel   │   │   │  @dataclass  │
           └──────────────┘   │   └──────────────┘
                               │
                    ┌──────────┴──────────────────┐
                    │  你需要区分联合/多态吗？     │
                    │  (discriminated union)       │
                    └──────────┬──────────────────┘
                               │
                    ┌──── Yes ─┤── No ────┐
                    │          │          │
                    ▼          │          ▼
           ┌──────────────┐   │   ┌──────────────┐
           │  BaseModel   │   │   │  @dataclass  │
           │  (Annotated) │   │   └──────────────┘
           └──────────────┘   │
                               │
                    ┌──────────┴──────────────────┐
                    │  纯内部值对象？               │
                    │  (不需要 JSON/校验/嵌套)      │
                    └──────────┬──────────────────┘
                               │
                    ┌──── Yes ─┤── No ────┐
                    │          │          │
                    ▼          │          ▼
           ┌──────────────┐   │   ┌──────────────┐
           │  @dataclass  │   │   │  BaseModel   │
           │  (frozen)    │   │   └──────────────┘
           └──────────────┘   │
                               │
                        都不满足？
                               │
                               ▼
                      ┌──────────────┐
                      │  BaseModel   │
                      │  (默认选择)  │
                      └──────────────┘
```

### 完整对比表

| 特性 | `@dataclass(frozen=True)` | `pydantic.BaseModel` | Java `record` | Java POJO |
|------|--------------------------|---------------------|---------------|-----------|
| 不可变性 | `frozen=True` | 默认不可变 | 天然不可变 | 需要手写 |
| 序列化 | 需第三方库 | 内置 `model_dump` | 需第三方库 | 需 Jackson |
| 反序列化 | 需第三方库 | `model_validate` | 需第三方库 | 需 Jackson |
| 校验 | 无 | 内置 | 无 | Bean Validation |
| 默认值 | `field(default_factory=...)` | `Field(default_factory=...)` | 无（必须构造器传入） | 构造器初始化 |
| 性能 | 较快（纯 Python） | 稍慢（校验开销） | 快 | 中等 |
| 依赖 | 标准库 | 第三方（pydantic） | JDK 14+ | JDK 8+ |
| 区分联合 | 可手动实现 | `Annotated[X \| Y, ...]` | sealed interface | 无 |
| 嵌套组合 | 支持 | 支持 + 级联校验 | 支持 | 支持 |

### `X | Y` 联合类型详解

PEP 604（Python 3.10+）引入了 `|` 运算符来定义联合类型：

```python
# Python 3.9 及之前（需要 typing.Union）
from typing import Union
result: Union[str, int] = "hello"

# Python 3.10+（PEP 604）
result: str | int = "hello"
```

在 OpenHarness 中的三种用法：

**1. 可选类型（代替 `Optional`）**：

```python
# 旧写法
from typing import Optional
chat_id: Optional[str] = None

# 新写法（Python 3.10+）
chat_id: str | None = None
```

**2. 联合事件类型**：

```python
ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent

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

**3. 运行时类型检查（`isinstance`）**：

```python
# Python 3.10+ 支持 isinstance + 联合类型
def handle_event(event: StreamEvent) -> None:
    if isinstance(event, AssistantTextDelta):
        print(event.text)
    elif isinstance(event, ToolExecutionStarted):
        print(f"Tool: {event.tool_name}")
    elif isinstance(event, ErrorEvent):
        print(f"Error: {event.message}")
```

> **Java 对比**：
>
> ```java
> // Java 17+ pattern matching switch
> switch (event) {
>     case AssistantTextDelta e -> System.out.println(e.text());
>     case ToolExecutionStarted e -> System.out.println("Tool: " + e.toolName());
>     case ErrorEvent e -> System.out.println("Error: " + e.message());
> }
> ```
>
> Python 的 `isinstance` 链等价于 Java 的 pattern matching switch，但 Python 没有穷尽检查（exhaustiveness check）——如果你漏掉一个子类型，编译器不会报错。Java 的 `sealed interface` + `switch` 则会确保所有子类型都被处理。使用 mypy 的 `--strict` 模式可以部分弥补这个差距。

## 架构图

```
┌─────────────────────── OpenHarness 数据类型体系 ─────────────────────────┐
│                                                                         │
│  ┌───────────────────── pydantic.BaseModel ──────────────────────────┐  │
│  │                                                                   │  │
│  │  外部交互层：需要序列化/校验/JSON 互操作                          │  │
│  │                                                                   │  │
│  │  ├── Settings                    ← 主配置（读写 JSON）             │  │
│  │  ├── PermissionSettings         ← 子配置                          │  │
│  │  ├── ProviderProfile            ← 提供商配置                      │  │
│  │  ├── ConversationMessage         ← 消息模型（API 交互）            │  │
│  │  ├── TextBlock / ToolUseBlock   ← 内容块（区分联合）              │  │
│  │  └── AgentDefinition             ← Agent 定义（YAML 加载）         │  │
│  │                                                                   │  │
│  │  核心能力：model_validate / model_dump / model_copy               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌─────────────────── @dataclass(frozen=True) ──────────────────────┐   │
│  │                                                                   │  │
│  │  内部传递层：轻量值对象，无需序列化                               │  │
│  │                                                                   │  │
│  │  ├── ProviderInfo                ← 提供商元数据                   │  │
│  │  ├── ResolvedAuth               ← 认证信息                       │  │
│  │  ├── ApiMessageRequest          ← API 请求参数                    │  │
│  │  ├── ApiTextDeltaEvent          ← 流式增量文本                    │  │
│  │  ├── ApiMessageCompleteEvent    ← 流式完成事件                    │  │
│  │  ├── ApiRetryEvent              ← 重试事件                        │  │
│  │  ├── AssistantTextDelta         ← 引擎增量文本                    │  │
│  │  ├── AssistantTurnComplete      ← 引擎完成事件                    │  │
│  │  ├── ToolExecutionStarted       ← 工具开始事件                    │  │
│  │  ├── ToolExecutionCompleted     ← 工具完成事件                    │  │
│  │  ├── ErrorEvent                 ← 错误事件                        │  │
│  │  ├── StatusEvent                ← 状态事件                        │  │
│  │  └── CompactProgressEvent      ← 压缩进度事件                    │  │
│  │                                                                   │  │
│  │  核心能力：frozen=True / field(default_factory) / 无校验开销      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────── 不可变常量 ─────────────────────────────────┐   │
│  │                                                                   │  │
│  │  frozenset[str]  ← AGENT_COLORS (不可变集合)                      │  │
│  │  tuple[str, ...] ← EFFORT_LEVELS / PERMISSION_MODES (不可变序列)  │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────── 联合类型 ───────────────────────────────────┐   │
│  │                                                                   │  │
│  │  ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent     │  │
│  │                   | ApiRetryEvent                                 │  │
│  │                                                                   │  │
│  │  StreamEvent   = AssistantTextDelta | AssistantTurnComplete       │  │
│  │                   | ToolExecutionStarted | ...                    │  │
│  │                                                                   │  │
│  │  ContentBlock  = Annotated[TextBlock | ImageBlock | ...,          │  │
│  │                   Field(discriminator="type")]                    │  │
│  │                                              ↑ BaseModel 专用     │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## 小结

本章通过 OpenHarness 的真实代码，对比了 `@dataclass` 与 `BaseModel` 两种数据建模方式：

1. **`@dataclass(frozen=True)` ≈ Java `record`**：不可变值对象，适合内部传递，无需序列化
2. **`BaseModel` ≈ POJO + Jackson + Bean Validation**：需要序列化/校验/JSON 互操作时使用
3. **`X | Y` 联合类型 ≈ Java `sealed interface`**：限定一组允许的类型，Python 3.10+ 原生支持
4. **`field(default_factory=dict/list)`**：dataclass 版本的可变默认值安全写法
5. **`frozenset` ≈ Java `Set.of()`**：不可变常量集合，适合模块级常量
6. **决策核心**：需要 JSON 互操作和校验 → `BaseModel`；纯内部值传递 → `@dataclass(frozen=True)`

### dataclass vs BaseModel vs Java POJO vs Java record 选择指南

| 场景 | Python 选择 | Java 选择 |
|------|-----------|----------|
| 配置文件读写 | `BaseModel` | POJO + Jackson |
| API 请求/响应模型 | `BaseModel` | POJO + Jackson |
| 内部事件传递 | `@dataclass(frozen=True)` | `record` |
| 多态类型（区分联合） | `BaseModel` + `Annotated` | `sealed interface` |
| 简单不可变值 | `@dataclass(frozen=True)` | `record` |
| 需要校验的数据 | `BaseModel` | POJO + Bean Validation |

### 思考题

1. 如果 `ApiTextDeltaEvent` 改用 `BaseModel` 而非 `@dataclass(frozen=True)`，会有什么利弊？考虑序列化需求、性能、不可变性等维度。
2. `StreamEvent` 用 `|` 运算符定义联合类型，如果新增一个事件类型但忘记更新联合类型定义，mypy 能检测到吗？
3. `frozenset` 和 `tuple` 都是不可变的，为什么 OpenHarness 用 `frozenset` 定义颜色常量、用 `tuple` 定义顺序相关的模式列表？