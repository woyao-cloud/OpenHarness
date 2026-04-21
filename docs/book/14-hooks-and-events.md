# 第十四章：Hooks 与事件 —— 装饰器、判别联合与热重载

## 概述

OpenHarness 的 Hook 系统（钩子系统）为生命周期事件提供了可扩展的拦截机制。它允许用户和插件在关键节点（会话开始、工具调用前后、上下文压缩等）注入自定义逻辑——执行命令、调用 HTTP 端点、让模型判断是否放行，甚至启动一个 Agent 深度审查。

本章将详细解析 Hook 的定义模型（基于 Pydantic 判别联合类型）、事件枚举、执行引擎、注册表、热重载机制，以及 fnmatch 模式匹配。

## Java 类比

> **Java 对比**：Hook 系统在 Java 生态中有多处对应。`HookDefinition` 的判别联合类似于 Spring 的 `@Component` + `@Qualifier` 组合——不同类型的 Hook 是不同的 Bean，通过类型标识选择具体实现。`HookExecutor` 基于 `isinstance` 的分发逻辑类似于 Java 的 Visitor 模式或 Spring 的 `@EventListener`。`watchfiles` 热重载等价于 Spring DevTools 的自动重启——但 Python 的模块重载比 JVM 的类重载更轻量。`fnmatch` 模式匹配等价于 Java NIO 的 `PathMatcher` 或 Ant 风格 glob 模式。

## 项目代码详解

### HookDefinition：Pydantic 判别联合类型

OpenHarness 支持四种 Hook 类型，定义在 `hooks/schemas.py` 中：

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

关键设计点：

1. **Literal 判别字段**：每个 Hook 类都有 `type: Literal["command"]` 这样的字面量类型标注，使得 Pydantic 可以根据 JSON 中的 `"type"` 字段自动反序列化为正确的子类——这就是「判别联合」（Discriminated Union）

2. **四种 Hook 的语义差异**：
   - `CommandHook`：执行 shell 命令，适合运行测试、格式化代码等确定性操作
   - `PromptHook`：让 LLM 判断是否放行，适合内容审查、合规检查等需要理解语义的场景
   - `HttpHook`：POST 到外部端点，适合与 CI/CD、通知系统等集成
   - `AgentHook`：更深的模型推理，timeout 更长（最多 1200 秒），适合复杂审查

3. **`block_on_failure`**：`CommandHook` 和 `HttpHook` 默认 `False`（失败不阻塞），而 `PromptHook` 和 `AgentHook` 默认 `True`（失败阻塞操作）——反映了「模型判断失败时应该保守」的设计哲学

> **Java 对比**：在 Java 中，判别联合通常用 Jackson 的 `@JsonTypeInfo` + `@JsonSubTypes` 实现：

```java
@JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "type")
@JsonSubTypes({
    @JsonSubTypes.Type(value = CommandHook.class, name = "command"),
    @JsonSubTypes.Type(value = PromptHook.class, name = "prompt"),
    @JsonSubTypes.Type(value = HttpHook.class, name = "http"),
    @JsonSubTypes.Type(value = AgentHook.class, name = "agent")
})
public abstract class HookDefinition { ... }
```

Python 的 `Literal` + 联合类型方案更简洁，不需要继承体系和注解堆叠。

### HookEvent：生命周期事件枚举

```python
from enum import Enum


class HookEvent(str, Enum):
    """Events that can trigger hooks."""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
```

`HookEvent` 继承了 `str` 和 `Enum`，这意味着每个枚举值可以直接当字符串使用——`HookEvent.PRE_TOOL_USE == "pre_tool_use"` 返回 `True`。这在 JSON 反序列化场景中非常方便。

> **Java 对比**：Java 的 `enum` 自带 `name()` 和 `toString()` 的区分，且不能直接当字符串用。Python 的 `str, Enum` 继承模式使得枚举值可以无缝参与字符串比较和 JSON 序列化。

### HookResult 和 AggregatedHookResult

```python
@dataclass(frozen=True)
class HookResult:
    """Result from a single hook execution."""
    hook_type: str
    success: bool
    output: str = ""
    blocked: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregatedHookResult:
    """Aggregated result for a hook event."""
    results: list[HookResult] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Return whether any hook blocked continuation."""
        return any(result.blocked for result in self.results)

    @property
    def reason(self) -> str:
        """Return the first blocking reason, if any."""
        for result in self.results:
            if result.blocked:
                return result.reason or result.output
        return ""
```

关键设计点：
- **`frozen=True`**：使 dataclass 实例不可变，类似于 Java 的 `record`——一旦创建就不能修改
- **聚合逻辑**：`AggregatedHookResult.blocked` 属性检查所有结果中是否有任何一个阻塞了操作，只要有一个 `blocked=True` 就返回 `True`——这是「一票否决」的安全设计

### HookExecutor：执行引擎

`HookExecutor` 是 Hook 系统的核心，位于 `hooks/executor.py`：

```python
class HookExecutor:
    """Execute hooks for lifecycle events."""

    def __init__(self, registry: HookRegistry, context: HookExecutionContext) -> None:
        self._registry = registry
        self._context = context

    async def execute(self, event: HookEvent, payload: dict[str, Any]) -> AggregatedHookResult:
        """Execute all matching hooks for an event."""
        results: list[HookResult] = []
        for hook in self._registry.get(event):
            if not _matches_hook(hook, payload):
                continue
            if isinstance(hook, CommandHookDefinition):
                results.append(await self._run_command_hook(hook, event, payload))
            elif isinstance(hook, HttpHookDefinition):
                results.append(await self._run_http_hook(hook, event, payload))
            elif isinstance(hook, PromptHookDefinition):
                results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=False))
            elif isinstance(hook, AgentHookDefinition):
                results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=True))
        return AggregatedHookResult(results=results)
```

执行流程：
1. 从注册表获取该事件的所有 Hook
2. 用 `fnmatch` 检查每个 Hook 的 `matcher` 是否匹配当前操作
3. 根据 Hook 类型分发给不同的执行方法
4. 收集所有结果，返回聚合结果

> **Java 对比**：`isinstance` 分发模式等价于 Java 的 Visitor 模式。在 Java 中，你通常会定义 `interface HookVisitor { visit(CommandHook); visit(HttpHook); ... }`，然后让每个 Hook 类型实现 `accept(HookVisitor)` 方法。Python 的 `isinstance` 链更简洁直接，适合 Hook 类型较少的场景。

#### 命令 Hook 执行

```python
async def _run_command_hook(self, hook, event, payload) -> HookResult:
    command = _inject_arguments(hook.command, payload, shell_escape=True)
    process = await create_shell_subprocess(
        command,
        cwd=self._context.cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "OPENHARNESS_HOOK_EVENT": event.value,
            "OPENHARNESS_HOOK_PAYLOAD": json.dumps(payload),
        },
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(),
        timeout=hook.timeout_seconds,
    )
    success = process.returncode == 0
    return HookResult(
        hook_type=hook.type, success=success, output=output,
        blocked=hook.block_on_failure and not success, ...
    )
```

关键点：
- **环境变量注入**：通过 `OPENHARNESS_HOOK_EVENT` 和 `OPENHARNESS_HOOK_PAYLOAD` 将事件上下文传递给子进程
- **超时控制**：`asyncio.wait_for` 确保命令不会无限运行
- **沙箱集成**：使用 `create_shell_subprocess` 而非 `asyncio.create_subprocess_exec`，以便在可用时自动使用沙箱

#### HTTP Hook 执行

```python
async def _run_http_hook(self, hook, event, payload) -> HookResult:
    async with httpx.AsyncClient(timeout=hook.timeout_seconds) as client:
        response = await client.post(
            hook.url,
            json={"event": event.value, "payload": payload},
            headers=hook.headers,
        )
    success = response.is_success
    return HookResult(hook_type=hook.type, success=success, ...)
```

#### Prompt/Agent Hook 执行

```python
async def _run_prompt_like_hook(self, hook, event, payload, *, agent_mode) -> HookResult:
    prompt = _inject_arguments(hook.prompt, payload)
    prefix = (
        "You are validating whether a hook condition passes in OpenHarness. "
        'Return strict JSON: {"ok": true} or {"ok": false, "reason": "..."}.'
    )
    if agent_mode:
        prefix += " Be more thorough and reason over the payload before deciding."
    # ...调用 LLM API...
    text = "".join(text_chunks)
    parsed = _parse_hook_json(text)
    if parsed["ok"]:
        return HookResult(hook_type=hook.type, success=True, output=text)
    return HookResult(hook_type=hook.type, success=False, blocked=hook.block_on_failure, ...)
```

### fnmatch 模式匹配

```python
def _matches_hook(hook: HookDefinition, payload: dict[str, Any]) -> bool:
    matcher = getattr(hook, "matcher", None)
    if not matcher:
        return True  # 无 matcher 时匹配所有
    subject = str(payload.get("tool_name") or payload.get("prompt") or payload.get("event") or "")
    return fnmatch.fnmatch(subject, matcher)
```

`fnmatch` 支持 Unix shell 风格的通配符：
- `*` 匹配任意字符序列
- `?` 匹配单个字符
- `[seq]` 匹配 seq 中的任意字符
- `[!seq]` 匹配不在 seq 中的任意字符

示例：`matcher: "Bash*"` 会匹配 `Bash`、`Bash(command="rm")` 等所有以 `Bash` 开头的工具名。

> **Java 对比**：Java 的 `PathMatcher` 使用 glob 语法（与 fnmatch 类似），但仅限于文件路径匹配。Spring AntPathMatcher 也使用类似模式。Python 的 `fnmatch` 更通用，可用于任意字符串匹配。

### HookRegistry：注册与查询

```python
class HookRegistry:
    """Store hooks grouped by event."""

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookDefinition]] = defaultdict(list)

    def register(self, event: HookEvent, hook: HookDefinition) -> None:
        """Register one hook."""
        self._hooks[event].append(hook)

    def get(self, event: HookEvent) -> list[HookDefinition]:
        """Return hooks registered for an event."""
        return list(self._hooks.get(event, []))

    def summary(self) -> str:
        """Return a human-readable hook summary."""
        lines: list[str] = []
        for event in HookEvent:
            hooks = self.get(event)
            if not hooks:
                continue
            lines.append(f"{event.value}:")
            for hook in hooks:
                matcher = getattr(hook, "matcher", None)
                detail = getattr(hook, "command", None) or getattr(hook, "prompt", None) or getattr(hook, "url", None) or ""
                suffix = f" matcher={matcher}" if matcher else ""
                lines.append(f"  - {hook.type}{suffix}: {detail}")
        return "\n".join(lines)
```

注册表使用 `defaultdict(list)` 按事件分组存储 Hook，查询时返回列表副本（`list()`）保证注册表不会被外部修改。

### HookReloader：热重载

```python
class HookReloader:
    """Reload hook definitions when the settings file changes."""

    def __init__(self, settings_path: Path) -> None:
        self._settings_path = settings_path
        self._last_mtime_ns = -1
        self._registry = HookRegistry()

    def current_registry(self) -> HookRegistry:
        """Return the latest registry, reloading if needed."""
        try:
            stat = self._settings_path.stat()
        except FileNotFoundError:
            self._registry = HookRegistry()
            self._last_mtime_ns = -1
            return self._registry

        if stat.st_mtime_ns != self._last_mtime_ns:
            self._last_mtime_ns = stat.st_mtime_ns
            self._registry = load_hook_registry(load_settings(self._settings_path))
        return self._registry
```

`HookReloader` 通过比较文件修改时间戳（`st_mtime_ns`）来检测配置变更——每次调用 `current_registry()` 时检查，如果文件时间戳变了就重新加载。这种方式比 `watchfiles` 库的文件监视更轻量，适合低频率轮询场景。

> **Java 对比**：Spring DevTools 的自动重启监视 classpath 变更，重启整个 ApplicationContext。Python 的热重载更细粒度——只替换 Hook 注册表，不需要重启进程。`st_mtime_ns` 检查类似于 Java NIO 的 `WatchService`，但更简单直接。

## Python 概念说明

### Pydantic BaseModel 与判别联合

Pydantic 是 Python 最流行的数据验证库，其 `BaseModel` 提供了：
- 自动类型转换和验证（`Field(default=30, ge=1, le=600)` 约束超时范围）
- JSON 序列化/反序列化（`model_validate_json()` 方法）
- 不可变模式（`model_config = ConfigDict(frozen=True)`）

判别联合（Discriminated Union）通过 `Literal` 类型字段实现，Pydantic 在反序列化 JSON 时根据 `type` 字段的值选择正确的子类：

```json
{"type": "command", "command": "pytest", "timeout_seconds": 60}
```

会被自动解析为 `CommandHookDefinition` 实例。

### dataclass(frozen=True)：不可变数据类

`@dataclass(frozen=True)` 创建不可变数据类，等价于 Java 14+ 的 `record`：

```python
@dataclass(frozen=True)
class HookResult:
    hook_type: str
    success: bool
    # 创建后不能修改任何字段
```

### fnmatch：Unix 风格模式匹配

Python 标准库的 `fnmatch` 模块提供了 Unix shell 风格的通配符匹配，比正则表达式更简单直观：

```python
import fnmatch
fnmatch.fnmatch("Bash(command='rm -rf /')", "Bash*")  # True
fnmatch.fnmatch("Read", "Re*")                         # True
fnmatch.fnmatch("Write", "Re*")                        # False
```

### defaultdict：默认值字典

`defaultdict(list)` 在访问不存在的键时自动创建空列表，避免 `KeyError`：

```python
from collections import defaultdict
hooks = defaultdict(list)
hooks[HookEvent.PRE_TOOL_USE].append(some_hook)  # 无需先初始化键
```

## 架构图

```
                    配置文件 (settings.yaml / hooks.json)
                              |
                              v
                    +-------------------+
                    | load_hook_registry |  (加载 + 注册)
                    +---------+---------+
                              |
                              v
                    +-------------------+
                    |   HookRegistry    |  (按事件分组存储)
                    | HookEvent -> [HookDefinition, ...]
                    +---------+---------+
                              |
              +---------------+---------------+
              |                               |
              v                               v
+---------------------------+     +----------------------+
|     HookExecutor          |     |    HookReloader      |
|  execute(event, payload)  |     | current_registry()   |
|     |                     |     |  (检查 mtime_ns 变化 |
|     +-- _matches_hook()   |     |   自动重载)           |
|     |                     |     +----------------------+
|     +-- isinstance 分发   |
|         |  |  |  |        |
+---------+--+--+--+--------+
          |     |     |      |
          v     v     v      v
     +-------+ +----+ +-----+ +-------+
     |Command| |HTTP| |Prompt| |Agent  |
     |Hook   | |Hook| |Hook  | |Hook   |
     |(shell)|(POST)|( LLM  )|(LLM   )|
     +-------+ +----+ +-----+ +-------+
          |     |     |      |
          v     v     v      v
     +-----------------------------+
     |    AggregatedHookResult     |
     |  .blocked (一票否决)         |
     |  .reason (首个阻塞原因)       |
     +-----------------------------+
```

## 小结

本章详细解析了 OpenHarness 的 Hook 系统：

1. **HookDefinition** 使用 Pydantic 的 `Literal` 判别字段实现类型安全的联合类型，支持四种 Hook：Command、Prompt、HTTP、Agent
2. **HookEvent** 枚举定义了 6 个生命周期事件，`str, Enum` 继承使枚举值可直接参与字符串比较
3. **HookResult / AggregatedHookResult** 使用 `frozen=True` dataclass，实现了不可变结果和「一票否决」的聚合逻辑
4. **HookExecutor** 通过 `isinstance` 分发实现多态执行，环境变量注入、超时控制、沙箱集成等一应俱全
5. **HookRegistry** 使用 `defaultdict(list)` 按事件分组管理 Hook
6. **HookReloader** 通过文件时间戳检测实现轻量级热重载
7. **fnmatch** 模式匹配为 Hook 提供了灵活的事件过滤机制

对于 Java 开发者，核心映射关系是：`Literal` 判别联合 ↔ Jackson `@JsonTypeInfo`、`frozen=True` dataclass ↔ Java `record`、`isinstance` 分发 ↔ Visitor 模式、`fnmatch` ↔ `PathMatcher`。理解这些映射后，Hook 系统的设计意图和实现方式便清晰可见。