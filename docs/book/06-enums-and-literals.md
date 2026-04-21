# 第六章：Enum 与 Literal —— Python 的枚举类型 vs Java enum

## 概述

Python 提供了多种方式来表示"一组有限的值"：`Enum`（枚举类）、`Literal`（字面量类型）和 `frozenset`（不可变集合）。Java 开发者通常只用 `enum` 一种方式，但 Python 的多范式设计让不同场景有不同的最佳选择。

OpenHarness 项目中有三个典型用例：

1. **`PermissionMode(str, Enum)`**（`permissions/modes.py`）—— 带值的枚举类
2. **`Literal["subprocess", "in_process", "tmux"]`**（`swarm/types.py`）—— 轻量级类型联合
3. **`AGENT_COLORS: frozenset[str]`**（`coordinator/agent_definitions.py`）—— 常量集合

本章将逐一分析这三种模式，并与 Java 中的等价写法对比。

---

## Java 类比

> **Java 对比：Python Enum vs Java enum**
>
> Java 的 `enum` 是功能强大的类型安全枚举：
>
> ```java
> public enum PermissionMode {
>     DEFAULT("default"),
>     PLAN("plan"),
>     FULL_AUTO("full_auto");
>
>     private final String value;
>
>     PermissionMode(String value) {
>         this.value = value;
>     }
>
>     public String getValue() { return value; }
>
>     // Java enum 可以有字段、方法、甚至抽象方法
>     public boolean isAuto() {
>         return this == FULL_AUTO;
>     }
> }
> ```
>
> Python 的 `Enum` 更轻量：
>
> ```python
> class PermissionMode(str, Enum):
>     DEFAULT = "default"
>     PLAN = "plan"
>     FULL_AUTO = "full_auto"
> ```
>
> 关键差异：
> 1. Python 的 `(str, Enum)` 多继承让枚举值同时也是字符串，可以直接比较：`mode == "default"`
> 2. Java 的 enum 是编译期类型安全的，Python 的 Enum 需要类型检查器（mypy）辅助
> 3. Java 的 enum 可以有构造函数、字段、方法，Python 的 Enum 也能但更少用
> 4. Python 的 `Literal` 提供了更轻量的替代方案

---

## 项目代码详解

### 6.1 PermissionMode —— (str, Enum) 的威力

`src/openharness/permissions/modes.py`：

```python
from enum import Enum

class PermissionMode(str, Enum):
    """Supported permission modes."""

    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"
```

`(str, Enum)` 这个多继承看似奇怪，实则非常实用：

1. **混合类继承**：`str` 是混入类（mixin），让 `PermissionMode` 的每个成员**同时也是一个字符串实例**。
2. **直接比较**：因为继承了 `str`，你可以直接写字符串比较：

   ```python
   mode = PermissionMode.FULL_AUTO
   mode == "full_auto"   # True！因为 PermissionMode.FULL_AUTO 本身就是 "full_auto"
   mode == PermissionMode.FULL_AUTO  # 也 True
   ```

3. **JSON 序列化友好**：`str(PermissionMode.DEFAULT)` 直接返回 `"default"`，不需要额外的 `.value` 访问器。这对于 API 交互非常重要——前端发送 `"default"` 字符串，后端可以直接 `PermissionMode("default")` 反序列化。

4. **Pydantic 集成**：当 `PermissionMode` 作为 Pydantic 模型字段时，`(str, Enum)` 让序列化/反序列化自动工作：

   ```python
   from pydantic import BaseModel

   class Config(BaseModel):
       permission_mode: PermissionMode = PermissionMode.DEFAULT

   Config(permission_mode="plan")  # 自动转换为 PermissionMode.PLAN
   ```

> **Java 对比：`class PermissionMode(str, Enum)` vs Java `enum PermissionMode`**
>
> | 维度 | Java enum | Python (str, Enum) |
> |------|-----------|-------------------|
> | 声明 | `enum PermissionMode { DEFAULT, PLAN, FULL_AUTO }` | `class PermissionMode(str, Enum)` |
> | 值比较 | `mode == PermissionMode.DEFAULT` | `mode == PermissionMode.DEFAULT` 或 `mode == "default"` |
> | JSON 序列 | 需要 `@JsonValue` / `@JsonCreator` | 自动：`str(mode)` → `"default"` |
> | 反序列化 | 需要 `PermissionMode.valueOf("DEFAULT")` | `PermissionMode("default")` |
> | 字符串操作 | 不支持 `mode.toUpperCase()` 等 | 支持：因为是 `str` 子类 |
> | switch/match | `switch (mode)` | `match mode:` (Python 3.10+) |

### 6.2 Literal —— 轻量级类型联合

`src/openharness/swarm/types.py` 中大量使用了 `Literal`：

```python
from typing import Literal, Protocol, runtime_checkable

BackendType = Literal["subprocess", "in_process", "tmux", "iterm2"]
"""All supported backend types."""

PaneBackendType = Literal["tmux", "iterm2"]
"""Subset of BackendType for pane-based (visual) backends only."""
```

以及 `TeammateSpawnConfig` 中：

```python
class TeammateSpawnConfig:
    system_prompt_mode: Literal["default", "replace", "append"] | None = None
    """How to apply the system prompt: replace or append to default."""
```

`Literal` 是 PEP 586 引入的类型注解，它定义了一个**类型级别的约束**：变量的值只能是指定的字面量之一。

```python
def set_backend(backend: BackendType) -> None:
    # mypy 会检查：只接受 "subprocess", "in_process", "tmux", "iterm2"
    ...

set_backend("tmux")      # OK
set_backend("docker")    # mypy 报错：不兼容的 Literal
```

> **Java 对比：`Literal["a", "b"]` vs Java enum with no methods**
>
> 在 Java 中，如果你只需要一组预定义的字符串值，通常会用 enum：
>
> ```java
> public enum BackendType {
>     SUBPROCESS, IN_PROCESS, TMUX, ITERM2
> }
> ```
>
> 但 Python 的 `Literal` 更适合以下场景：
>
> 1. **值本身就是字符串**：不需要额外的 `enum` 包装，直接用字符串字面量
> 2. **类型只在注解中使用**：`Literal` 不创建新的类，不增加运行时开销
> 3. **与外部 API 对齐**：如果 API 期望的值就是 `"subprocess"` 这样的字符串，用 `Literal` 避免 enum 到字符串的转换
> 4. **子集关系简单**：`PaneBackendType` 是 `BackendType` 的子集，用 `Literal` 定义更直观
>
> 如果 Java 的 enum 只用来约束值范围（没有方法、没有字段），Python 的 `Literal` 就是更好的选择——更轻量、更 Pythonic。

### 6.3 Hook 类型 Literal —— Pydantic 与 Literal 的配合

`src/openharness/hooks/schemas.py` 展示了 `Literal` 与 Pydantic 的深度集成：

```python
from typing import Literal
from pydantic import BaseModel, Field


class CommandHookDefinition(BaseModel):
    """A hook that executes a shell command."""
    type: Literal["command"] = "command"
    command: str
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False


class PromptHookDefinition(BaseModel):
    """A hook that asks the model to validate a condition."""
    type: Literal["prompt"] = "prompt"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = True


class HttpHookDefinition(BaseModel):
    """A hook that POSTs the event payload to an HTTP endpoint."""
    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    matcher: str | None = None
    block_on_failure: bool = False


class AgentHookDefinition(BaseModel):
    """A hook that performs a deeper model-based validation."""
    type: Literal["agent"] = "agent"
    prompt: str
    model: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=1200)
    matcher: str | None = None
    block_on_failure: bool = True


HookDefinition = (
    CommandHookDefinition
    | PromptHookDefinition
    | HttpHookDefinition
    | AgentHookDefinition
)
```

这是一个经典的**判别联合**（Discriminated Union）模式：

1. **每个变体用 `Literal` 标注 `type` 字段**：`type: Literal["command"]` 让 Pydantic 可以根据 `type` 字段的值来决定反序列化成哪个子类。
2. **`HookDefinition` 是联合类型**：`CommandHookDefinition | PromptHookDefinition | ...`，Pydantic v2 支持**判别联合反序列化**——传入 `{"type": "command", "command": "ls"}` 会自动解析成 `CommandHookDefinition`。
3. **每个变体有自己的字段**：`CommandHookDefinition` 有 `command`，`HttpHookDefinition` 有 `url`，等等。

> **Java 对比：判别联合 vs Jackson 多态反序列化**
>
> Java 中实现类似效果需要 Jackson 的 `@JsonTypeInfo` + `@JsonSubTypes`：
>
> ```java
> @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "type")
> @JsonSubTypes({
>     @JsonSubTypes.Type(value = CommandHookDefinition.class, name = "command"),
>     @JsonSubTypes.Type(value = PromptHookDefinition.class, name = "prompt"),
>     @JsonSubTypes.Type(value = HttpHookDefinition.class, name = "http"),
>     @JsonSubTypes.Type(value = AgentHookDefinition.class, name = "agent")
> })
> public interface HookDefinition {}
> ```
>
> Python 的 `Literal` + Pydantic 方案更简洁：
> - 不需要接口/抽象类
> - 不需要注解配置
> - Pydantic v2 自动根据 `Literal` 字段进行判别

### 6.4 frozenset —— 模块级常量集合

`src/openharness/coordinator/agent_definitions.py`：

```python
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

EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high")

PERMISSION_MODES: tuple[str, ...] = (
    "default",
    "acceptEdits",
    "bypassPermissions",
    "plan",
    "dontAsk",
)

MEMORY_SCOPES: tuple[str, ...] = ("user", "project", "local")

ISOLATION_MODES: tuple[str, ...] = ("worktree", "remote")
```

这里展示了两种常量集合模式：

1. **`frozenset[str]`**：用于无序、唯一值的集合。`AGENT_COLORS` 用 `frozenset` 因为颜色之间没有顺序关系，且需要快速判断 `"red" in AGENT_COLORS`。

2. **`tuple[str, ...]`**：用于有序值的序列。`EFFORT_LEVELS` 用 `tuple` 因为级别有顺序（低/中/高）。

> **Java 对比：`frozenset[str]` vs Java `Set.of()` 不可变集合**
>
> ```java
> // Java 9+ 不可变集合
> public static final Set<String> AGENT_COLORS = Set.of(
>     "red", "green", "blue", "yellow", "purple",
>     "orange", "cyan", "magenta", "white", "gray"
> );
>
> public static final List<String> EFFORT_LEVELS = List.of("low", "medium", "high");
> ```
>
> | 维度 | Python frozenset | Java Set.of() |
> |------|-----------------|---------------|
> | 不可变 | 是 | 是 |
> | 成员测试 | `"red" in AGENT_COLORS` O(1) | `AGENT_COLORS.contains("red")` O(1) |
> | 类型注解 | `frozenset[str]` | `Set<String>` |
> | 用作 dict key | 可以（因为不可变+可哈希） | 不适用 |
>
> Python 选择 `frozenset` 而非 `set` 的原因与 Java 选择 `Set.of()` 而非 `new HashSet<>()` 一样：**语义上表达"这是一个不变的常量集合"**。

### 6.5 模块级常量 vs Java `public static final`

OpenHarness 项目中大量使用模块级常量：

```python
# api/client.py
MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
```

```python
# swarm/types.py
OAUTH_BETA_HEADER = "oauth-2025-04-20"
```

Python 的模块级常量命名约定是 **全大写**（`UPPER_SNAKE_CASE`），但 Python 没有语言层面的 `const` 或 `final` 关键字——这完全靠约定。

> **Java 对比：模块级常量 vs `public static final`**
>
> ```java
> // Java 的常量必须在类中定义
> public class ApiConstants {
>     public static final int MAX_RETRIES = 3;
>     public static final double BASE_DELAY = 1.0;
>     public static final double MAX_DELAY = 30.0;
>     public static final Set<Integer> RETRYABLE_STATUS_CODES =
>         Set.of(429, 500, 502, 503, 529);
> }
> ```
>
> ```python
> # Python 的常量直接在模块顶层定义
> MAX_RETRIES = 3
> BASE_DELAY = 1.0
> MAX_DELAY = 30.0
> RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
> ```
>
> | 维度 | Java `static final` | Python 模块常量 |
> |------|---------------------|----------------|
> | 定义位置 | 必须在类中 | 模块顶层 |
> | 强制不可变 | 是（编译期检查） | 否（靠约定 + `frozenset`） |
> | 命名约定 | `UPPER_SNAKE_CASE` | `UPPER_SNAKE_CASE` |
> | 导入方式 | `import static pkg.Consts.MAX_RETRIES` | `from pkg import MAX_RETRIES` |
> | 类型安全 | 编译期类型检查 | 运行时 + mypy 类型检查 |
>
> Python 的哲学是"我们都是成年人"（We're all consenting adults）——如果常量命名是大写的，开发者就不应该修改它。如果你需要更强的不可变性保证，可以使用 `frozenset`（集合）或 `@dataclass(frozen=True)`（数据类）。

---

## Python 概念说明

### 何时使用 Enum vs Literal vs frozenset

这是 Java 开发者最常见的困惑。下表总结了三者的适用场景：

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| 需要方法/行为的枚举 | `Enum` | 可以添加方法，如 `PermissionMode.is_auto()` |
| 需要唯一值的命名常量 | `(str, Enum)` | 同时支持枚举比较和字符串操作 |
| 只需类型约束，无行为 | `Literal` | 零运行时开销，纯类型注解 |
| 需要与 JSON/API 字符串对齐 | `Literal` 或 `(str, Enum)` | 视是否需要方法而定 |
| 需要 Pydantic 判别联合 | `Literal` | 与 Pydantic 的判别联合完美配合 |
| 需要快速成员测试 | `frozenset` | O(1) 查找，不可变，语义明确 |
| 需要有序的常量序列 | `tuple[str, ...]` | 有序，不可变，可迭代 |
| 需要全局配置项 | 模块级常量 | 简单，直接 |

OpenHarness 中的实际选择：

- `PermissionMode(str, Enum)` —— 需要枚举值和字符串互操作
- `BackendType = Literal[...]` —— 只需类型约束，无行为
- `AGENT_COLORS: frozenset[str]` —— 需要成员测试，无需方法
- `MAX_RETRIES = 3` —— 简单数值常量

### (str, Enum) 的陷阱

`(str, Enum)` 虽然方便，但有一些需要注意的陷阱：

1. **比较语义混淆**：

   ```python
   mode = PermissionMode.DEFAULT
   mode == "default"      # True
   mode == PermissionMode.DEFAULT  # True
   mode is PermissionMode.DEFAULT  # True（CPython 缓存）
   "default" == PermissionMode.DEFAULT  # True（对称）
   ```

   但如果用纯 `Enum`（不继承 `str`）：

   ```python
   class PermissionMode(Enum):
       DEFAULT = "default"
       # ...

   mode = PermissionMode.DEFAULT
   mode == "default"      # False！必须用 mode.value == "default"
   ```

2. **`json.dumps()` 行为**：`(str, Enum)` 在 JSON 序列化时直接输出字符串值，而纯 `Enum` 需要自定义序列化器。

3. **类型检查的微妙差异**：mypy 对 `(str, Enum)` 和纯 `Enum` 的类型推断不同——前者在某些场景下可能过于宽泛。

---

## 架构图

```
Python 值约束类型系统
======================

                    需要约束有限值集合？
                           │
               ┌───────────┼───────────┐
               │           │           │
          需要方法/行为？  只需类型约束？  需要成员测试？
               │           │           │
               ▼           ▼           ▼
           (str, Enum)   Literal    frozenset
               │           │           │
               │           │           │
    ┌──────────┤     ┌────┴────┐      │
    │          │     │         │      │
  唯一值    字符串   判别联合   类型   集合约束
  命名常量  互操作   (Pydantic) 注解
    │          │     │         │      │
    ▼          ▼     ▼         ▼      ▼
Permission  API   Hook      Backend  AGENT_COLORS
  Mode      交互  Definition  Type   EFFORT_LEVELS


OpenHarness 中的使用分布
==========================

Enum (str, Enum):
  └── PermissionMode ──── 需要枚举名 + 字符串值的双向映射

Literal:
  ├── BackendType ──────── 后端类型约束
  ├── PaneBackendType ──── 后端子集约束
  ├── system_prompt_mode ─ 系统提示词模式
  ├── HookDefinition.type ── Pydantic 判别联合
  │     ├── Literal["command"]
  │     ├── Literal["prompt"]
  │     ├── Literal["http"]
  │     └── Literal["agent"]
  └── (其他轻量类型约束)

frozenset:
  └── AGENT_COLORS ─────── 颜色值约束（无序，唯一）

tuple:
  ├── EFFORT_LEVELS ────── 努力级别（有序）
  ├── PERMISSION_MODES ──── 权限模式（有序）
  ├── MEMORY_SCOPES ────── 内存范围（有序）
  └── ISOLATION_MODES ──── 隔离模式（有序）

模块常量 (UPPER_SNAKE_CASE):
  ├── MAX_RETRIES = 3
  ├── BASE_DELAY = 1.0
  ├── MAX_DELAY = 30.0
  └── RETRYABLE_STATUS_CODES = {429, ...}
```

---

## 小结

1. **`(str, Enum)` 是 Python 枚举的最佳实践**：继承了 `str` 让枚举值可以直接当字符串使用，JSON 序列化友好，与 Pydantic 完美配合。`PermissionMode` 是标准范例。

2. **`Literal` 适合轻量级类型约束**：当你只需要"这几个字符串之一"的约束，不需要方法或复杂行为时，`Literal` 比 `Enum` 更轻量、更 Pythonic。`BackendType` 和 Hook 的 `type` 字段是典型用例。

3. **`frozenset` 用于不可变常量集合**：语义上表达"这是一个不可变的、用于成员测试的集合"。比 `set` 更安全（不可变），比 `tuple` 更适合无序场景。

4. **判别联合是 Literal + Pydantic 的杀手组合**：`HookDefinition` 展示了如何用 `Literal` 字段作为判别标签，配合 Pydantic 的联合类型实现多态反序列化——比 Java 的 Jackson `@JsonTypeInfo` 更简洁。

5. **模块级常量靠约定**：Python 没有 `const` 或 `final` 关键字，`UPPER_SNAKE_CASE` 命名约定就是"不要修改这个变量"的信号。如果需要更强的不可变性，使用 `frozenset`、`@dataclass(frozen=True)` 或 `typing.Final`。