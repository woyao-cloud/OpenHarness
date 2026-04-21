# 第五章：ABC 与继承 —— Python 抽象基类 vs Java 抽象类

## 概述

Python 的 `ABC`（Abstract Base Class，抽象基类）来自 `abc` 模块，是与 Java 抽象类最接近的概念。但两者在机制和哲学上存在重要差异：Python ABC 依赖名义子类型（需要显式继承），但同时受到鸭子类型的补充；Python 支持多继承而 Java 只允许单继承；Python ABC 无法声明抽象字段，只能用类属性模拟。

OpenHarness 项目中有四处典型的 ABC 使用：

1. **`BaseTool`**（`tools/base.py`）—— 30+ 工具的统一抽象基类
2. **`ToolRegistry`**（`tools/base.py`）—— 字典驱动的服务定位器
3. **`BaseChannel`**（`channels/impl/base.py`）—— 聊天通道的抽象基类
4. **`AuthFlow`**（`auth/flows.py`）—— 认证流的继承体系
5. **`OpenHarnessApiError`**（`api/errors.py`）—— 异常继承层次

本章将逐一分析这些案例，并与 Java 中的等价模式进行对比。

---

## Java 类比

> **Java 对比：ABC + @abstractmethod vs Java abstract class + abstract method**
>
> Java 的抽象类：
>
> ```java
> // Java 抽象类
> public abstract class BaseTool {
>     protected String name;
>     protected String description;
>
>     public abstract ToolResult execute(BaseModel arguments, ToolExecutionContext context);
>
>     public boolean isReadOnly(BaseModel arguments) {
>         return false;  // 默认实现
>     }
>
>     public Map<String, Object> toApiSchema() {
>         return Map.of(
>             "name", name,
>             "description", description,
>             "input_schema", inputModel.getJsonSchema()
>         );
>     }
> }
> ```
>
> Python 的 ABC：
>
> ```python
> # Python ABC
> class BaseTool(ABC):
>     name: str                          # 类属性，不是抽象字段
>     description: str
>     input_model: type[BaseModel]
>
>     @abstractmethod
>     async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
>         """Execute the tool."""
>
>     def is_read_only(self, arguments: BaseModel) -> bool:
>         del arguments
>         return False                    # 默认实现
>
>     def to_api_schema(self) -> dict[str, Any]:
>         return {
>             "name": self.name,
>             "description": self.description,
>             "input_schema": self.input_model.model_json_schema(),
>         }
> ```
>
> 关键差异：
> 1. Python 的 `name`、`description` 是**类属性**，不是 `abstract` 字段——Python ABC 不支持抽象字段。
> 2. Python 的 `execute` 是 `async def`，Java 需要 `CompletableFuture`。
> 3. Python 的子类只需继承 `BaseTool` 并实现 `execute()` 即可，不需要 `@Override` 注解。

---

## 项目代码详解

### 5.1 BaseTool —— 30+ 工具的统一抽象基类

`src/openharness/tools/base.py` 是整个工具系统的基石：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from pydantic import BaseModel


@dataclass
class ToolExecutionContext:
    """Shared execution context for tool invocations."""
    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result."""
    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Base class for all OpenHarness tools."""

    name: str
    description: str
    input_model: type[BaseModel]

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """Execute the tool."""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """Return whether the invocation is read-only."""
        del arguments
        return False

    def to_api_schema(self) -> dict[str, Any]:
        """Return the tool schema expected by the Anthropic Messages API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }
```

这段代码体现了 ABC 的几个核心设计模式：

1. **`@abstractmethod`**：标记 `execute` 为抽象方法，任何子类必须实现它，否则无法实例化。
2. **类属性声明**：`name`、`description`、`input_model` 是类级别的类型声明（type hints），子类需要赋值覆盖。
3. **默认实现**：`is_read_only()` 和 `to_api_schema()` 提供了默认行为，子类可以选择性覆盖。
4. **`del arguments`**：`is_read_only` 方法中的 `del arguments` 是一个 Python 惯用法，表示"我确实收到了这个参数但不用它"——这比 `_ = arguments` 更明确地表达意图，也避免了 linter 警告。

> **Java 对比：Python ABC 不能声明抽象字段**
>
> Java 可以这样写：
>
> ```java
> public abstract class BaseTool {
>     public abstract String getName();        // 抽象 getter
>     public abstract String getDescription();
>     public abstract Class<? extends BaseModel> getInputModel();
> }
> ```
>
> Python 的 ABC 没有抽象字段的概念。OpenHarness 使用**类属性 + 类型注解**的方式模拟：
>
> ```python
> class BaseTool(ABC):
>     name: str           # 类型注解，不是抽象字段
>     description: str    # 子类必须赋值，否则 AttributeError
>     input_model: type[BaseModel]
> ```
>
> 如果子类忘记赋值 `name`，Python **不会在定义时报错**，而是在**访问时**抛出 `AttributeError`。这比 Java 的编译期检查弱。Python 3.12+ 可以使用 `@property + @abstractmethod` 来更严格地约束，但 OpenHarness 选择了更简洁的类属性方式。

### 5.2 ToolRegistry —— 字典驱动的服务定位器

同样在 `tools/base.py` 中：

```python
class ToolRegistry:
    """Map tool names to implementations."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Return a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def to_api_schema(self) -> list[dict[str, Any]]:
        """Return all tool schemas in API format."""
        return [tool.to_api_schema() for tool in self._tools.values()]
```

`ToolRegistry` 是一个经典的**服务定位器**（Service Locator）模式：通过名称字符串来查找对应的工具实例。

> **Java 对比：ToolRegistry (dict) vs Spring DI (@Component + @Autowired)**
>
> 在 Java/Spring 中，类似的功能通常依赖依赖注入框架：
>
> ```java
> @Service
> public class ToolRegistry {
>     private final Map<String, BaseTool> tools = new HashMap<>();
>
>     @Autowired
>     public ToolRegistry(List<BaseTool> toolList) {
>         toolList.forEach(tool -> tools.put(tool.getName(), tool));
>     }
> }
> ```
>
> Spring 的 `@Component` + `@Autowired` 自动扫描和注入，开发者不需要手动注册。
>
> OpenHarness 选择手动注册的原因：
>
> 1. **显式优于隐式**：Python 社区倾向"显式注册"而非"魔法注入"。
> 2. **无框架依赖**：不需要 Spring 这样的大型 IoC 容器。
> 3. **注册顺序可控**：工厂函数 `create_default_tool_registry()` 精确控制注册顺序和条件。
>
> ```python
> # tools/__init__.py 中的工厂函数
> def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
>     registry = ToolRegistry()
>     for tool in (
>         BashTool(),
>         FileReadTool(),
>         # ... 30+ 工具逐一注册
>     ):
>         registry.register(tool)
>     if mcp_manager is not None:
>         for tool_info in mcp_manager.list_tools():
>             registry.register(McpToolAdapter(mcp_manager, tool_info))
>     return registry
> ```

### 5.3 BaseChannel —— 聊天通道的抽象基类

`src/openharness/channels/impl/base.py` 展示了 ABC 的另一种用法——定义生命周期接口：

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
            logger.warning("%s: allow_from is empty — all access denied", self.name)
            return False
        if "*" in allow_list:
            return True
        sender_str = str(sender_id)
        return sender_str in allow_list or any(
            p in allow_list for p in sender_str.split("|") if p
        )
```

这个设计模式的亮点：

1. **`start()` / `stop()` / `send()` 三方法**：经典的**生命周期模式**——初始化、运行、清理。
2. **`is_allowed()` 默认实现**：提供了一个通用的权限检查方法，所有子类共享。
3. **`name` 类属性**：每个子类覆盖此属性来标识自己（如 `"telegram"`、`"discord"`）。
4. **`_running` 状态管理**：基类管理运行状态，子类通过 `start()` 和 `stop()` 控制生命周期。

> **Java 对比：Python ABC 的构造函数**
>
> Java 抽象类可以有构造函数，子类必须调用 `super()`：
>
> ```java
> public abstract class BaseChannel {
>     protected String name = "base";
>     protected MessageBus bus;
>
>     protected BaseChannel(Config config, MessageBus bus) {
>         this.bus = bus;
>     }
> }
> ```
>
> Python ABC 也可以有构造函数，且更加灵活：
>
> ```python
> class BaseChannel(ABC):
>     def __init__(self, config: Any, bus: MessageBus):
>         self.config = config   # 直接存储配置
>         self.bus = bus        # 直接注入依赖
>         self._running = False
> ```
>
> Python 的 `__init__` 是实例初始化方法，不是真正的"构造函数"（那是 `__new__`）。ABC 的 `__init__` 可以被子类调用 `super().__init__()` 但不是强制要求的。

### 5.4 AuthFlow —— 继承体系

`src/openharness/auth/flows.py` 展示了经典的多层继承：

```python
class AuthFlow(ABC):
    """Abstract base for all auth flows."""

    @abstractmethod
    def run(self) -> str:
        """Execute the flow and return the obtained credential value."""


class ApiKeyFlow(AuthFlow):
    """Prompt the user for an API key and persist it."""

    def __init__(self, provider: str, prompt_text: str | None = None) -> None:
        self.provider = provider
        self.prompt_text = prompt_text or f"Enter your {provider} API key"

    def run(self) -> str:
        import getpass
        key = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not key:
            raise ValueError("API key cannot be empty.")
        return key


class DeviceCodeFlow(AuthFlow):
    """GitHub OAuth device-code flow."""

    def __init__(self, client_id: str | None = None, ...) -> None:
        self.client_id = client_id or COPILOT_CLIENT_ID
        # ...

    def run(self) -> str:
        # ... OAuth 流程，启动浏览器，轮询 token
```

```python
class BrowserFlow(AuthFlow):
    """Open a browser URL and wait for the user to complete authentication."""

    def __init__(self, auth_url: str, prompt_text: str = "Paste the token from your browser") -> None:
        self.auth_url = auth_url
        self.prompt_text = prompt_text

    def run(self) -> str:
        # ... 打开浏览器，等待用户粘贴 token
```

这个继承体系简洁明了：

```
        AuthFlow (ABC)
        ┌────┴────┐────────┐
   ApiKeyFlow  DeviceCodeFlow  BrowserFlow
```

每个子类只需实现 `run()` 方法，返回认证凭据字符串。`DeviceCodeFlow` 还包含了 `@staticmethod` 方法 `_try_open_browser()` 来复用浏览器打开逻辑。

> **Java 对比：Python 的继承更加轻量**
>
> Java 版本会涉及更多样板代码：
>
> ```java
> public abstract class AuthFlow {
>     public abstract String run();
> }
>
> public class ApiKeyFlow extends AuthFlow {
>     private final String provider;
>     private final String promptText;
>
>     public ApiKeyFlow(String provider, String promptText) {
>         this.provider = provider;
>         this.promptText = promptText != null ? promptText : "Enter your " + provider + " API key";
>     }
>
>     @Override
>     public String run() {
>         // ...
>     }
> }
> ```
>
> Python 版本更加简洁：无需 `@Override`、无需 `private final`、无需显式构造函数赋值。

### 5.5 OpenHarnessApiError —— 异常继承层次

`src/openharness/api/errors.py` 展示了 Python 异常类的继承设计：

```python
class OpenHarnessApiError(RuntimeError):
    """Base class for upstream API failures."""


class AuthenticationFailure(OpenHarnessApiError):
    """Raised when the upstream service rejects the provided credentials."""


class RateLimitFailure(OpenHarnessApiError):
    """Raised when the upstream service rejects the request due to rate limits."""


class RequestFailure(OpenHarnessApiError):
    """Raised for generic request or transport failures."""
```

这种层次结构允许调用者灵活地捕获不同粒度的异常：

```python
try:
    await client.stream_message(request)
except AuthenticationFailure:
    # 只捕获认证错误
    log.error("Authentication failed")
except RateLimitFailure:
    # 只捕获限流错误
    log.warning("Rate limited")
except OpenHarnessApiError:
    # 捕获所有 API 错误
    log.error("API error")
```

> **Java 对比：异常层次**
>
> Java 的异常层次设计类似，但需要区分受检异常（checked exception）和非受检异常（unchecked exception）：
>
> ```java
> // Java 受检异常（必须声明或捕获）
> public class OpenHarnessApiError extends Exception { ... }
>
> // Java 非受检异常（类似 Python 的 RuntimeError）
> public class OpenHarnessApiError extends RuntimeException { ... }
> ```
>
> Python 的异常体系更简单——所有异常都是非受检的，不需要在方法签名中声明 `throws`。OpenHarness 选择继承 `RuntimeError`（非受检的语义），而不是 `Exception`，暗示这些是"运行时不可预测的 API 失败"。

---

## Python 概念说明

### 多继承 vs 单继承

> **Java 对比：Python 多继承 vs Java 单继承**
>
> Java 只允许单继承（一个类只能 extends 一个类），但可以实现多个接口（implements 多个 interface）。
>
> Python 允许真正的多继承：
>
> ```python
> class MyTool(BaseTool, SomeMixin, AnotherMixin):
>     # 同时继承 BaseTool 和多个 Mixin
>     pass
> ```
>
> Python 通过 **MRO（Method Resolution Order）** 解决菱形继承问题：
>
> ```python
> >>> MyTool.__mro__
> (MyTool, BaseTool, SomeMixin, AnotherMixin, ABC, object)
> ```
>
> OpenHarness 项目中，`BaseChannel` 就混合了 `ABC` 的抽象能力与具体的初始化逻辑——这在 Java 中需要用 `abstract class + interface` 的组合来实现。

### ABC 的高级特性

Python ABC 还有几个 Java 中没有的特性：

1. **`ABCMeta` 元类**：`ABC` 的底层是 `ABCMeta` 元类，它使得 `@abstractmethod` 装饰器生效——如果一个类有未实现的抽象方法，尝试实例化会抛出 `TypeError`。

2. **虚拟子类**：通过 `ABC.register()`，可以让一个类"声明"自己是某 ABC 的子类，而不需要真正继承：
   ```python
   MyABC.register(MyClass)  # MyClass 现在通过 isinstance 检查
   ```
   这在 Java 中没有等价物。

3. **`__abstractmethods__` 集合**：ABC 自动维护一个 `__abstractmethods__` frozenset，记录所有未实现的抽象方法名。只有这个集合为空时，类才能实例化。

---

## 架构图

```
OpenHarness ABC 继承体系
==========================

                    ABC (abc 模块)
                      │
          ┌───────────┼───────────┐──────────┐
          │           │           │          │
     BaseTool    BaseChannel   AuthFlow   OpenHarnessApiError
     (tools/)    (channels/)  (auth/)      (api/)
          │           │           │          │
    ┌─────┼─────┐   ┌┴──┐    ┌──┼──┐    ┌──┼──────┐
    │     │     │   │   │    │     │    │  │      │
  Bash  File  Task  Tel  Dis  Api  Dev  Auth  Rate  Req
  Tool   Read  Tool  egr  cor  Key  ice  enti  Lim   uest
         Tool   │   am   d    Flow  Cod  cati  it    Fail
                │              eFlow  onFail ure
              MCP              │
            ToolAd         Browser
            apter           Flow


ToolRegistry 服务定位器
========================

    ┌──────────────────────────────┐
    │     ToolRegistry             │
    │  _tools: dict[str, BaseTool] │
    │                              │
    │  register(tool) ───────►     │
    │  get(name) ───────────►      │
    │  list_tools() ────────►      │
    │  to_api_schema() ─────►      │
    └──────────────────────────────┘
               ▲
               │ register()
    ┌──────────┴──────────────────┐
    │  create_default_tool_registry│  (工厂函数)
    │  ┌─── BashTool()            │
    │  ├─── FileReadTool()        │
    │  ├─── FileWriteTool()       │
    │  ├─── ... 30+ tools         │
    │  └─── McpToolAdapter(...)   │
    └─────────────────────────────┘


异常层次
========

    RuntimeError
         │
    OpenHarnessApiError
         │
    ┌────┼──────────┐
    │    │           │
Auth   Rate       Request
Fail   Limit      Failure
ure    Failure
```

---

## 小结

1. **ABC + @abstractmethod 是 Python 的抽象类机制**：与 Java 的 `abstract class` + `abstract method` 功能类似，但 Python 不支持抽象字段，需要用类属性模拟。

2. **ToolRegistry 用字典代替 Spring DI**：Python 社区偏好显式注册而非自动注入，`dict[str, BaseTool]` 简洁明了，工厂函数控制注册流程。

3. **BaseChannel 展示了 ABC 的生命周期模式**：`start()` / `stop()` / `send()` 三个抽象方法定义了接口，`is_allowed()` 提供了共享的默认实现。

4. **AuthFlow 展示了简洁的继承体系**：`AuthFlow(ABC)` 只有一个抽象方法 `run()`，三个子类各自实现认证逻辑。Python 的继承比 Java 更轻量——没有 `@Override`、没有受检异常、没有 `private final` 的啰嗦。

5. **Python 支持多继承**：通过 MRO（方法解析顺序）解决菱形继承问题，这是 Java 单继承模型中没有的概念。Mix-in 模式在 Python 中很常见，允许在不修改继承链的情况下添加功能。

6. **异常层次也是 ABC 的用例**：`OpenHarnessApiError` 继承 `RuntimeError`，三个子类提供细粒度的错误类型，调用者可以按需捕获。Python 异常都是非受检的，不需要 `throws` 声明。