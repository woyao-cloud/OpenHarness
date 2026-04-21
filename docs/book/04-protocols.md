# 第四章：Protocol —— Python 的结构化子类型

## 概述

Python 的 `Protocol` 是 `typing` 模块提供的一种特殊类型，用于定义**结构化子类型**（structural subtyping），也叫"鸭子类型"的类型注解版本。与 Java 的接口（interface）不同，Protocol 不要求实现类显式声明"我实现了这个协议"——只要一个类拥有 Protocol 所描述的方法和属性，类型检查器就认为它兼容。

OpenHarness 项目中有两处典型的 Protocol 使用：

1. `api/client.py` 中的 `SupportsStreamingMessages` —— 查询引擎的依赖抽象
2. `swarm/types.py` 中的 `PaneBackend` 和 `TeammateExecutor` —— 带 `@runtime_checkable` 的运行时可检测协议

本章将深入对比 Protocol 与 Java interface 的本质差异，帮助 Java 开发者理解 Python 的鸭子类型哲学。

---

## Java 类比

> **Java 对比：Protocol（结构化子类型）vs Java Interface（名义子类型）**
>
> 在 Java 中，一个类要实现接口必须显式使用 `implements` 关键字：
>
> ```java
> // Java —— 名义子类型（Nominal Subtyping）
> public interface StreamingMessages {
>     AsyncIterator<StreamEvent> streamMessage(MessageRequest request);
> }
>
> public class AnthropicClient implements StreamingMessages {
>     // 必须声明 implements，否则编译器不认
>     @Override
>     public AsyncIterator<StreamEvent> streamMessage(MessageRequest request) { ... }
> }
> ```
>
> 而在 Python 的 Protocol 中，不需要任何声明：
>
> ```python
> # Python —— 结构化子类型（Structural Subtyping）
> class SupportsStreamingMessages(Protocol):
>     async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]: ...
>
> class AnthropicApiClient:  # 无需声明 "implements SupportsStreamingMessages"
>     async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
>         ...
> ```
>
> `AnthropicApiClient` 因为碰巧拥有签名匹配的 `stream_message` 方法，mypy/pyright 就会认为它**满足** `SupportsStreamingMessages` 协议。这就是"如果你走起来像鸭子、叫起来像鸭子，那你就是鸭子"。

---

## 项目代码详解

### 4.1 SupportsStreamingMessages —— 最简 Protocol

在 `src/openharness/api/client.py` 中，定义了一个精简的 Protocol：

```python
from typing import Any, AsyncIterator, Callable, Protocol

class SupportsStreamingMessages(Protocol):
    """Protocol used by the query engine in tests and production."""

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Yield streamed events for the request."""
```

这段代码的关键要素：

1. **继承自 `Protocol`**：这是 `typing` 模块的特殊基类，告诉类型检查器"这是一个协议定义，不是普通基类"。
2. **方法只有签名，没有实现**：方法体用 `...`（Ellipsis）表示，这是纯占位符。
3. **`async def`**：协议方法可以是异步的，与普通方法一样标注。
4. **没有 `@abstractmethod`**：Protocol 的方法天然就是"必须实现的"——但这个"必须"是由类型检查器在**使用时**检查的，而非在定义时。

> **Java 对比：Protocol 方法 vs interface 抽象方法**
>
> Java 的 `interface` 方法默认就是 `public abstract`，子类必须实现。Python Protocol 的方法也类似，但检查时机不同：
>
> | 维度 | Java interface | Python Protocol |
> |------|---------------|-----------------|
> | 检查时机 | 编译期（定义类时） | 类型检查时（使用类时） |
> | 声明要求 | 必须 `implements X` | 无需声明 |
> | 运行时检查 | `instanceof X` | 需要 `@runtime_checkable` |
> | 默认方法 | Java 8+ 支持 `default` | Protocol 也支持默认实现 |

同一个文件中的 `AnthropicApiClient` 类实现了 `stream_message` 方法：

```python
class AnthropicApiClient:
    """Thin wrapper around the Anthropic async SDK with retry logic."""

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Yield text deltas and the final assistant message with retry on transient errors."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                self._refresh_client_auth()
                async for event in self._stream_once(request):
                    yield event
                return  # Success
            except OpenHarnessApiError:
                raise  # Auth errors are not retried
            except Exception as exc:
                # ... retry logic
```

虽然 `AnthropicApiClient` **没有**写 `SupportsStreamingMessages`，但 mypy 会根据结构匹配判定它满足该协议。查询引擎可以声明依赖 `SupportsStreamingMessages`，在测试中传入 Mock 对象，在生产中传入 `AnthropicApiClient`。

### 4.2 @runtime_checkable Protocol —— PaneBackend 和 TeammateExecutor

`swarm/types.py` 中定义了两个带 `@runtime_checkable` 装饰器的 Protocol：

```python
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

@runtime_checkable
class PaneBackend(Protocol):
    """Protocol for pane management backends (tmux / iTerm2)."""

    @property
    def type(self) -> BackendType: ...

    @property
    def display_name(self) -> str: ...

    @property
    def supports_hide_show(self) -> bool: ...

    async def is_available(self) -> bool: ...

    async def is_running_inside(self) -> bool: ...

    async def create_teammate_pane_in_swarm_view(
        self, name: str, color: str | None = None
    ) -> CreatePaneResult: ...

    async def send_command_to_pane(
        self, pane_id: PaneId, command: str, *, use_external_session: bool = False
    ) -> None: ...

    # ... 更多方法
```

```python
@runtime_checkable
class TeammateExecutor(Protocol):
    """Protocol for teammate execution backends."""

    type: BackendType

    def is_available(self) -> bool: ...

    async def spawn(self, config: TeammateSpawnConfig) -> SpawnResult: ...

    async def send_message(self, agent_id: str, message: TeammateMessage) -> None: ...

    async def shutdown(self, agent_id: str, *, force: bool = False) -> bool: ...
```

> **Java 对比：@runtime_checkable vs Java instanceof + interface check**
>
> 在 Java 中，你可以在运行时检查一个对象是否实现了某接口：
>
> ```java
> if (obj instanceof PaneBackend) {
>     PaneBackend backend = (PaneBackend) obj;
> }
> ```
>
> 在 Python 中，普通的 Protocol **不支持** `isinstance()` 检查。如果你需要运行时类型判断，必须加 `@runtime_checkable`：
>
> ```python
> from openharness.swarm.types import PaneBackend
>
> # 没有 @runtime_checkable 时，这会报 TypeError
> # 加了 @runtime_checkable 后，可以运行时检查
> if isinstance(some_obj, PaneBackend):
>     # 确认 some_obj 拥有 PaneBackend 要求的所有方法
> ```
>
> 但注意：`@runtime_checkable` 的 `isinstance()` 检查只验证**方法名的存在**，不检查方法签名。这比 Java 的 `instanceof` 弱得多。

### 4.3 TYPE_CHECKING 守卫 —— 避免循环导入

在 `swarm/types.py` 的顶部：

```python
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass  # 此处可以放置仅类型检查时需要的导入
```

虽然这段文件的 `TYPE_CHECKING` 块目前为空（`pass`），但在项目的其他文件中大量使用了这一模式：

```python
# 典型模式：channels/adapter.py
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openharness.engine.query import QueryEngine  # 避免循环导入
```

> **Java 对比：TYPE_CHECKING vs Java 包可见性**
>
> Java 的包（package）系统和访问修饰符（`public`、`protected`、`private`）天然防止了循环依赖问题——编译器直接拒绝循环引用。
>
> Python 没有 Java 那样的编译期依赖图检查，循环导入是常见的运行时陷阱。`TYPE_CHECKING` 是 Python 社区的约定：这些导入只在类型检查工具（mypy/pyright）运行时生效，在 Python 解释器实际执行时**被跳过**，从而打破循环依赖链。
>
> ```python
> from __future__ import annotations  # 让所有注解变成字符串，延迟求值
> from typing import TYPE_CHECKING
>
> if TYPE_CHECKING:
>     from openharness.engine.query import QueryEngine  # 仅类型检查时导入
>
> class MyChannel(BaseChannel):
>     def __init__(self, engine: QueryEngine):  # 安全：QueryEngine 在运行时不求值
>         ...
> ```
>
> `from __future__ import annotations`（PEP 563）将所有类型注解变成字符串，延迟求值，与 `TYPE_CHECKING` 配合使用可以彻底解决循环导入。

---

## Python 概念说明

### 鸭子类型哲学

Python 的鸭子类型（Duck Typing）是语言核心哲学之一："如果它走起来像鸭子、叫起来像鸭子，那它就是鸭子。"

在 Protocol 出现之前（PEP 544，Python 3.8），Python 的鸭子类型只能在运行时隐式生效，类型检查器无法验证。Protocol 的引入让鸭子类型有了**静态类型检查的支持**。

三种对比视角：

| 特性 | Java Interface | Python ABC | Python Protocol |
|------|---------------|------------|------------------|
| 子类型方式 | 名义（nominal） | 名义为主 | 结构（structural） |
| 需要显式声明 | `implements X` | 继承 `X` | 无需声明 |
| 静态类型检查 | 编译期 | mypy 检查 | mypy 检查 |
| 运行时 isinstance | 天然支持 | 天然支持 | 需 `@runtime_checkable` |
| 适合场景 | API 契约 | 共享实现代码 | 松耦合接口 |

### 何时使用 Protocol vs ABC

在 OpenHarness 项目中，Protocol 和 ABC 各有适用场景：

**使用 Protocol 的场景**（`SupportsStreamingMessages`、`PaneBackend`、`TeammateExecutor`）：

- 不想让实现类继承任何基类（保持灵活性）
- 需要第三方类隐式满足接口（如第三方 SDK 的客户端类）
- 接口定义和方法实现分散在不同模块/包中
- 纯粹定义"行为契约"，不提供任何默认实现

**使用 ABC 的场景**（`BaseTool`、`BaseChannel`、`AuthFlow`——将在第五章详细介绍）：

- 需要提供默认实现（如 `BaseTool.is_read_only()`、`BaseTool.to_api_schema()`）
- 需要类属性约束（如 `name`、`description`、`input_model`）
- 所有子类共享某些通用逻辑
- 运行时需要 `isinstance()` 检查

一个简单的决策流程：

```
需要共享实现代码吗？
├── 是 → 使用 ABC（抽象基类）
└── 否 → 只定义行为契约？
    ├── 是 → 使用 Protocol
    └── 否 → 需要运行时 isinstance 检查？
        ├── 是 → 使用 @runtime_checkable Protocol
        └── 否 → 纯 Protocol 即可
```

---

## 架构图

```
Protocol 在 OpenHarness 中的层次结构
=====================================

         类型系统层面
         ──────────
              │
              ▼
    ┌─────────────────────┐
    │  SupportsStreaming   │  api/client.py
    │  Messages (Protocol) │  ─── 最简 Protocol，单方法
    └──────────┬──────────┘
               │ 结构匹配（无需 implements）
               ▼
    ┌─────────────────────┐
    │  AnthropicApiClient  │  api/client.py
    │  (实现 stream_message)│  ─── 满足协议但不继承 Protocol
    └──────────────────────┘


         运行时层面
         ──────────
              │
              ▼
    ┌─────────────────────┐    @runtime_checkable
    │  PaneBackend         │  swarm/types.py
    │  (Protocol)          │  ─── 可用 isinstance() 检查
    └──────────┬──────────┘
               │ 结构匹配
        ┌──────┴──────┐
        ▼              ▼
  ┌──────────┐  ┌──────────┐
  │  Tmux    │  │  iTerm2  │  channels/impl/
  │  Backend │  │  Backend │  ─── 各自实现 PaneBackend 方法
  └──────────┘  └──────────┘

    ┌─────────────────────┐    @runtime_checkable
    │  TeammateExecutor   │  swarm/types.py
    │  (Protocol)          │  ─── 跨后端执行协议
    └──────────┬──────────┘
               │ 结构匹配
        ┌──────┼──────┐
        ▼      ▼      ▼
  Subprocess  InProcess  TmuxExecutor
  Backend     Backend    Backend

         Protocol vs ABC 选择
         ────────────────────
              │
    ┌─────────┴─────────┐
    │                   │
    ▼                   ▼
  Protocol              ABC
  (结构子类型)          (名义子类型)
  ├─ 纯契约             ├─ 有默认实现
  ├─ 无需声明           ├─ 需要继承
  ├─ 松耦合             ├─ 共享逻辑
  └─ duck typing       └─ is_read_only, to_api_schema
```

---

## 小结

1. **Protocol 是 Python 的结构化子类型机制**：与 Java interface 的名义子类型不同，Protocol 只关心对象是否拥有符合签名的方法，而不要求显式声明 `implements`。

2. **`@runtime_checkable` 让 Protocol 支持 `isinstance()`**：但检查粒度较弱，只验证方法名是否存在，不验证方法签名。Java 的 `instanceof` + interface 则是完整验证。

3. **`TYPE_CHECKING` 守卫解决循环导入**：这是 Python 特有的问题（Java 的编译器天然拒绝循环依赖），通过将类型导入限制在类型检查阶段来解决。

4. **Protocol vs ABC 的选择原则**：纯行为契约用 Protocol；需要共享实现代码或类属性约束用 ABC。OpenHarness 中 `SupportsStreamingMessages`、`PaneBackend`、`TeammateExecutor` 是 Protocol 的典范，而 `BaseTool`、`BaseChannel`、`AuthFlow` 则是 ABC 的用例（下一章详述）。

5. **鸭子类型的类型安全**：Protocol 让 Python 的鸭子类型哲学得到了静态类型检查的加持，既保持了灵活性，又获得了 IDE 自动补全和 mypy 检查的好处。