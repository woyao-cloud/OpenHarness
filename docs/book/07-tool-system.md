# 第七章：工具系统 —— 30+ 工具的统一抽象

## 概述

OpenHarness 的工具系统是一个精心设计的插件架构：一个 `BaseTool` ABC 定义了统一契约，30+ 工具各自实现 `execute()` 方法，`ToolRegistry` 以字典方式管理注册与查找，`create_default_tool_registry()` 工厂函数负责组装。

这个系统的设计哲学是：**一个 ABC + 一个 Pydantic 模型 + 一个字典注册表 = 可扩展的工具体系**。没有 Spring 那样的 IoC 容器，没有反射扫描，没有注解驱动——一切都是显式的、Pythonic 的。

对于 Java 开发者来说，这就像是一个极简版本的 SPI（Service Provider Interface）机制，但用 Python 的方式实现。

---

## Java 类比

> **Java 对比：BaseTool ABC vs Java 抽象工具 + @Tool 注解**
>
> 如果用 Java 实现类似的工具系统，通常会这样写：
>
> ```java
> // Java 方式：注解 + 反射 + IoC 容器
> public abstract class BaseTool {
>     protected String name;
>     protected String description;
>     protected Class<? extends BaseModel> inputModel;
>
>     public abstract CompletableFuture<ToolResult> execute(BaseModel args, ToolExecutionContext ctx);
>
>     public boolean isReadOnly(BaseModel args) { return false; }
>
>     public Map<String, Object> toApiSchema() {
>         return Map.of("name", name, "description", description,
>                       "input_schema", inputModel.getJsonSchema());
>     }
> }
>
> @Component
> public class ToolRegistry {
>     private final Map<String, BaseTool> tools = new HashMap<>();
>
>     @Autowired
>     public ToolRegistry(List<BaseTool> allTools) {
>         allTools.forEach(t -> tools.put(t.name, t));
>     }
> }
> ```
>
> Python 方式：ABC + 手动注册
>
> ```python
> class BaseTool(ABC):
>     name: str
>     description: str
>     input_model: type[BaseModel]
>
>     @abstractmethod
>     async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult: ...
>
>     def is_read_only(self, arguments: BaseModel) -> bool:
>         del arguments
>         return False
>
>     def to_api_schema(self) -> dict[str, Any]:
>         return {"name": self.name, ...}
>
> class ToolRegistry:
>     def __init__(self) -> None:
>         self._tools: dict[str, BaseTool] = {}
>     def register(self, tool: BaseTool) -> None:
>         self._tools[tool.name] = tool
> ```
>
> 核心差异：
> 1. Java 用 `CompletableFuture<ToolResult>`，Python 用 `async def` —— 异步模型完全不同
> 2. Java 依赖 `@Autowired` 自动注入，Python 用工厂函数显式注册
> 3. Java 的 `Class<? extends BaseModel>` 需要反射获取 schema，Python 的 `type[BaseModel]` 直接调用 `.model_json_schema()`

---

## 项目代码详解

### 7.1 BaseTool ABC —— 工具的统一契约

`src/openharness/tools/base.py` 是整个工具系统的核心：

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

这个 ABC 定义了五个契约点：

| 契约点 | 类型 | 作用 | Java 等价 |
|--------|------|------|-----------|
| `name` | 类属性 | 工具唯一标识 | `protected String name` |
| `description` | 类属性 | 工具描述（给 LLM 看） | `protected String description` |
| `input_model` | 类属性 | 输入参数的 Pydantic 模型 | `Class<? extends BaseModel>` |
| `execute()` | 抽象方法 | 工具的核心执行逻辑 | `abstract CompletableFuture<ToolResult> execute(...)` |
| `is_read_only()` | 默认方法 | 判断是否只读操作 | `boolean isReadOnly(BaseModel args) { return false; }` |
| `to_api_schema()` | 默认方法 | 生成 API 所需的 JSON Schema | `Map<String, Object> toApiSchema()` |

> **Java 对比：Pydantic BaseModel vs Java POJO + Bean Validation**
>
> `input_model: type[BaseModel]` 是这个系统最精妙的设计之一。
>
> Java 方式（POJO + Bean Validation）：
>
> ```java
> public class BashToolInput {
>     @NotBlank(message = "Command is required")
>     @Description("Shell command to execute")
>     private String command;
>
>     @Nullable
>     @Description("Working directory override")
>     private String cwd;
>
>     @Min(1) @Max(600)
>     @Description("Timeout in seconds")
>     private int timeoutSeconds = 600;
>
>     // getter, setter, builder ...
> }
>
> // 生成 JSON Schema 需要额外库（如 everit-org/json-schema）
> ```
>
> Python 方式（Pydantic BaseModel）：
>
> ```python
> class BashToolInput(BaseModel):
>     command: str = Field(description="Shell command to execute")
>     cwd: str | None = Field(default=None, description="Working directory override")
>     timeout_seconds: int = Field(default=600, ge=1, le=600)
> ```
>
> 优势对比：
> 1. **验证一体化**：Pydantic 的 `Field(constraints)` 在解析时自动验证，不需要单独的验证框架
> 2. **Schema 自动生成**：`.model_json_schema()` 一行代码生成完整的 JSON Schema
> 3. **类型注解即文档**：`str | None` 比 `@Nullable` 更简洁
> 4. **默认值即约束**：`default=600, ge=1, le=600` 同时定义了默认值和范围

### 7.2 BashTool —— 完整的工具实现示例

`src/openharness/tools/bash_tool.py` 是最复杂的工具之一，展示了完整的工具实现模式：

```python
class BashToolInput(BaseModel):
    """Arguments for the bash tool."""
    command: str = Field(description="Shell command to execute")
    cwd: str | None = Field(default=None, description="Working directory override")
    timeout_seconds: int = Field(default=600, ge=1, le=600)


class BashTool(BaseTool):
    """Execute a shell command with stdout/stderr capture."""

    name = "bash"
    description = "Run a shell command in the local repository."
    input_model = BashToolInput

    async def execute(self, arguments: BashToolInput, context: ToolExecutionContext) -> ToolResult:
        cwd = Path(arguments.cwd).expanduser() if arguments.cwd else context.cwd
        # ... 子进程管理、超时控制、错误处理
```

这个实现遵循了 BaseTool 的所有契约：

1. **`name = "bash"`**：类属性赋值，直接覆盖 ABC 中的类型声明
2. **`description = "Run a shell command in the local repository."`**：给 LLM 看的自然语言描述
3. **`input_model = BashToolInput`**：引用 Pydantic 模型类（注意是类本身，不是实例）
4. **`async def execute(...)`**：实现核心执行逻辑
5. **没有覆盖 `is_read_only()`**：因为 bash 命令可能修改文件系统，默认返回 `False` 是正确的

### 7.3 FileReadTool —— 只读工具的覆盖示例

```python
class FileReadToolInput(BaseModel):
    """Arguments for the file read tool."""
    path: str = Field(description="Path of the file to read")
    offset: int = Field(default=0, ge=0, description="Zero-based starting line")
    limit: int = Field(default=200, ge=1, le=2000, description="Number of lines to return")


class FileReadTool(BaseTool):
    """Read a UTF-8 text file with line numbers."""

    name = "read_file"
    description = "Read a text file from the local repository."
    input_model = FileReadToolInput

    def is_read_only(self, arguments: FileReadToolInput) -> bool:
        del arguments
        return True  # 读文件是只读操作！
```

这里 `is_read_only()` 返回 `True`——这是安全系统用来判断是否需要额外权限的关键信息。只读工具可以在更宽松的权限模式下运行。

### 7.4 ToolRegistry —— 字典驱动注册表

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

`ToolRegistry` 的设计极简：

- **内部存储**：一个 `dict[str, BaseTool]`，键是工具名称，值是工具实例
- **注册**：`register(tool)` —— O(1) 插入
- **查找**：`get(name)` —— O(1) 查找，返回 `None` 表示不存在
- **列表**：`list_tools()` —— 返回所有工具实例
- **Schema 生成**：`to_api_schema()` —— 将所有工具转换成 API 格式

> **Java 对比：ToolRegistry dict vs Spring @Component + @Autowired**
>
> | 维度 | Python ToolRegistry | Spring IoC |
> |------|---------------------|-----------|
> | 注册方式 | 手动 `register()` | 自动扫描 `@Component` |
> | 查找方式 | `dict.get(name)` | `@Autowired` 注入 |
> | 生命周期 | 简单实例 | Spring 容器管理 |
> | 依赖注入 | 构造函数传参 | `@Autowired` 注入 |
> | 作用域 | 单例（手动控制） | 可配置（singleton/prototype/...） |
> | 条件注册 | `if mcp_manager is not None:` | `@ConditionalOnProperty` |
>
> OpenHarness 选择手动注册的原因：
> 1. 注册顺序可控（MCP 工具必须在内置工具之后注册）
> 2. 条件注册清晰（`if mcp_manager is not None` 一目了然）
> 3. 无框架依赖，启动速度快
> 4. 调试简单——注册了什么，看工厂函数就知道

### 7.5 create_default_tool_registry() —— 工厂函数

`src/openharness/tools/__init__.py` 是整个工具系统的组装入口：

```python
from openharness.tools.bash_tool import BashTool
from openharness.tools.file_read_tool import FileReadTool
from openharness.tools.file_write_tool import FileWriteTool
from openharness.tools.file_edit_tool import FileEditTool
from openharness.tools.glob_tool import GlobTool
from openharness.tools.grep_tool import GrepTool
# ... 30+ 导入

def create_default_tool_registry(mcp_manager=None) -> ToolRegistry:
    """Return the default built-in tool registry."""
    registry = ToolRegistry()
    for tool in (
        BashTool(),
        AskUserQuestionTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        NotebookEditTool(),
        LspTool(),
        McpAuthTool(),
        GlobTool(),
        GrepTool(),
        SkillTool(),
        ToolSearchTool(),
        WebFetchTool(),
        WebSearchTool(),
        ConfigTool(),
        BriefTool(),
        SleepTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TodoWriteTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        CronCreateTool(),
        CronListTool(),
        CronDeleteTool(),
        CronToggleTool(),
        RemoteTriggerTool(),
        TaskCreateTool(),
        TaskGetTool(),
        TaskListTool(),
        TaskStopTool(),
        TaskOutputTool(),
        TaskUpdateTool(),
        AgentTool(),
        SendMessageTool(),
        TeamCreateTool(),
        TeamDeleteTool(),
    ):
        registry.register(tool)
    if mcp_manager is not None:
        registry.register(ListMcpResourcesTool(mcp_manager))
        registry.register(ReadMcpResourceTool(mcp_manager))
        for tool_info in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_manager, tool_info))
    return registry
```

这个工厂函数的设计要点：

1. **显式注册列表**：所有内置工具逐一实例化并注册，一目了然
2. **条件注册**：MCP 工具只在 `mcp_manager` 存在时才注册
3. **MCP 适配器**：`McpToolAdapter` 将外部 MCP 工具包装成 `BaseTool` 接口

### 7.6 McpToolAdapter —— 适配器模式

`src/openharness/tools/mcp_tool.py` 展示了如何将外部工具适配到 `BaseTool` 接口：

```python
class McpToolAdapter(BaseTool):
    """Expose one MCP tool as a normal OpenHarness tool."""

    def __init__(self, manager: McpClientManager, tool_info: McpToolInfo) -> None:
        self._manager = manager
        self._tool_info = tool_info
        server_segment = _sanitize_tool_segment(tool_info.server_name)
        tool_segment = _sanitize_tool_segment(tool_info.name)
        self.name = f"mcp__{server_segment}__{tool_segment}"
        self.description = tool_info.description or f"MCP tool {tool_info.name}"
        self.input_model = _input_model_from_schema(self.name, tool_info.input_schema)

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        del context
        try:
            output = await self._manager.call_tool(
                self._tool_info.server_name,
                self._tool_info.name,
                arguments.model_dump(mode="json", exclude_none=True),
            )
        except McpServerNotConnectedError as exc:
            return ToolResult(output=str(exc), is_error=True)
        return ToolResult(output=output)
```

这是一个经典的**适配器模式**（Adapter Pattern）：`McpToolAdapter` 将 MCP（Model Context Protocol）的外部工具接口转换成 OpenHarness 的 `BaseTool` 接口。

关键设计决策：

1. **`name` 格式化**：`mcp__{server}__{tool}` 避免名称冲突
2. **`input_model` 动态生成**：`_input_model_from_schema()` 将 MCP 的 JSON Schema 转换成 Pydantic 模型
3. **`execute()` 委托**：核心逻辑委托给 `self._manager.call_tool()`
4. **错误处理**：MCP 服务器未连接时返回 `is_error=True` 而不是抛异常

> **Java 对比：McpToolAdapter vs Java 适配器模式**
>
> 适配器模式在 Java 和 Python 中概念相同，但实现细节不同：
>
> ```java
> // Java 适配器
> public class McpToolAdapter extends BaseTool {
>     private final McpClientManager manager;
>     private final McpToolInfo toolInfo;
>
>     public McpToolAdapter(McpClientManager manager, McpToolInfo toolInfo) {
>         this.manager = manager;
>         this.toolInfo = toolInfo;
>         this.name = "mcp__" + sanitize(toolInfo.getServerName())
>                   + "__" + sanitize(toolInfo.getName());
>     }
>
>     @Override
>     public CompletableFuture<ToolResult> execute(BaseModel args, ToolExecutionContext ctx) {
>         return manager.callTool(toolInfo.getServerName(), toolInfo.getName(),
>                                 args.toJson());
>     }
> }
> ```
>
> Python 版本更简洁：不需要 `@Override`，不需要构造函数的 `this.x = x` 样板（直接 `self._manager = manager`），动态生成 `input_model` 也更自然。

### 7.7 TaskCreateTool —— 带条件的工具示例

```python
class TaskCreateToolInput(BaseModel):
    """Arguments for task creation."""
    type: str = Field(default="local_bash", description="Task type: local_bash or local_agent")
    description: str = Field(description="Short task description")
    command: str | None = Field(default=None, description="Shell command for local_bash")
    prompt: str | None = Field(default=None, description="Prompt for local_agent")
    model: str | None = Field(default=None)


class TaskCreateTool(BaseTool):
    """Create a background task."""

    name = "task_create"
    description = "Create a background shell or local-agent task."
    input_model = TaskCreateToolInput

    async def execute(self, arguments: TaskCreateToolInput, context: ToolExecutionContext) -> ToolResult:
        manager = get_task_manager()
        if arguments.type == "local_bash":
            if not arguments.command:
                return ToolResult(output="command is required for local_bash tasks", is_error=True)
            task = await manager.create_shell_task(
                command=arguments.command,
                description=arguments.description,
                cwd=context.cwd,
            )
        elif arguments.type == "local_agent":
            if not arguments.prompt:
                return ToolResult(output="prompt is required for local_agent tasks", is_error=True)
            # ...
```

注意这里 `execute()` 的返回值是 `ToolResult`，而不是抛出异常。这是工具系统的重要设计原则：**工具错误通过 `is_error=True` 的 ToolResult 返回，而非异常**。这让上层调用者可以统一处理成功和失败的情况。

---

## Python 概念说明

### async def vs CompletableFuture

> **Java 对比：Python async def vs Java CompletableFuture**
>
> | 维度 | Python `async def` | Java `CompletableFuture` |
> |------|-------------------|--------------------------|
> | 语法 | `async def execute(...)` | `CompletableFuture<ToolResult> execute(...)` |
> | 调用 | `result = await tool.execute(args, ctx)` | `ToolResult result = tool.execute(args, ctx).join()` |
> | 组合 | `async for event in stream()` | `thenApply()`, `thenCompose()` |
> | 取消 | `asyncio.Task.cancel()` | `future.cancel(true)` |
> | 异常 | `try/except` | `exceptionally()`, `handle()` |
>
> Python 的 `async/await` 语法比 Java 的 `CompletableFuture` 链式调用更直观。Java 21+ 的虚拟线程（Virtual Threads）提供了另一种选择，但 OpenHarness 的异步模型基于 Python 的 `asyncio`。

### Pydantic BaseModel 作为输入 Schema

Pydantic 是 Python 数据验证的事实标准。在工具系统中，每个工具的输入都由一个 `BaseModel` 子类定义：

1. **自动验证**：`BashToolInput` 的 `timeout_seconds: int = Field(default=600, ge=1, le=600)` 自动验证输入范围
2. **自动文档**：`description` 参数提供给 LLM 的工具描述
3. **自动 Schema**：`.model_json_schema()` 生成完整的 JSON Schema
4. **自动序列化**：`.model_dump()` 将模型实例序列化为字典

这种"一个模型类同时完成验证、文档、Schema 生成"的模式是 Python/Pydantic 的独特优势——Java 需要 Bean Validation + Swagger/SpringDoc + Jackson 三套框架才能达到同样效果。

### 工厂函数 vs IoC 容器

`create_default_tool_registry()` 是一个纯函数工厂——没有装饰器、没有类扫描、没有配置文件。这与 Java/Spring 的 IoC 容器理念完全不同：

| 维度 | Python 工厂函数 | Spring IoC |
|------|----------------|-----------|
| 发现方式 | 显式 import + 实例化 | `@ComponentScan` 自动发现 |
| 注册方式 | `registry.register(tool)` | `@Autowired` 自动注入 |
| 条件注册 | `if mcp_manager is not None:` | `@ConditionalOnProperty` |
| 顺序控制 | 工厂函数中的顺序 | `@Order` 注解 |
| 调试难度 | 低（读函数就知道） | 高（需要理解 Spring 生命周期） |
| 测试难度 | 低（直接 `ToolRegistry()` 即可） | 中（需要 `@SpringBootTest`） |

Python 社区普遍偏好"显式优于隐式"（Explicit is better than implicit），工厂函数正体现了这一哲学。

---

## 架构图

```
OpenHarness 工具系统架构
=========================

+-------------------+     +-------------------+
|   BashToolInput   |     |   FileReadInput   |  ... 30+ input models
| (Pydantic BaseModel)     | (Pydantic BaseModel)|
+-------------------+     +-------------------+
         |                         |
         | input_model              | input_model
         v                         v
+-------------------+     +-------------------+
|     BashTool      |     |   FileReadTool    |  ... 30+ tool implementations
|  name = "bash"   |     |  name = "read_file" |
|  execute(async)   |     |  execute(async)     |
|  is_read_only=F   |     |  is_read_only=T    |
+-------------------+     +-------------------+
         |                         |
         +------------+------------+
                      |
                      | register()
                      v
              +-------------------+
              |   ToolRegistry    |  (dict[str, BaseTool])
              |  _tools: dict     |
              |  register(tool)   |
              |  get(name)        |
              |  list_tools()     |
              |  to_api_schema()  |
              +-------------------+
                      |
                      | created by
                      v
              +-------------------+
              | create_default_    |
              | tool_registry()    |  工厂函数
              |                   |
              | ┌─ BashTool()      |
              | ├─ FileReadTool()  |
              | ├─ FileWriteTool() |
              | ├─ FileEditTool()  |
              | ├─ GlobTool()      |
              | ├─ GrepTool()      |
              | ├─ ... 30+ tools  |
              | └─ if mcp_manager: |
              |    McpToolAdapter  | ←── 适配外部 MCP 工具
              +-------------------+
                      |
                      | used by
                      v
              +-------------------+
              |   QueryEngine     |  查询引擎
              |  调用 tool.execute |
              |  处理 ToolResult  |
              +-------------------+


BaseTool ABC 详解
==================

class BaseTool(ABC):
    │
    ├── name: str ────────── 工具唯一标识 (例: "bash", "read_file")
    │
    ├── description: str ──── 工具描述 (给 LLM 看)
    │
    ├── input_model: type[BaseModel] ──── 输入参数模型
    │
    ├── @abstractmethod
    │   async def execute(arguments, context) -> ToolResult
    │   └── 子类必须实现的核心执行逻辑
    │
    ├── def is_read_only(arguments) -> bool
    │   └── 默认返回 False；只读工具覆盖为 True
    │
    └── def to_api_schema() -> dict[str, Any]
        └── 自动生成 Anthropic Messages API 所需的 JSON Schema


McpToolAdapter 适配器
======================

    MCP Server (外部)
         │
         │ tool_info: McpToolInfo
         │   (name, description, input_schema)
         v
    +---------------------------+
    |     McpToolAdapter        |
    |  name = "mcp__{s}__{t}"  |
    |  input_model = 动态生成   |
    |  execute() → manager.call_tool()
    +---------------------------+
         │
         │ 符合 BaseTool 接口
         v
    ToolRegistry.register(adapter)


ToolResult 统一返回
====================

    @dataclass(frozen=True)
    class ToolResult:
        output: str          ──── 工具输出（文本）
        is_error: bool       ──── 是否为错误（默认 False）
        metadata: dict       ──── 额外元数据
```

---

## 小结

1. **BaseTool ABC 定义了五个契约点**：`name`、`description`、`input_model` 三个类属性 + `execute()` 一个抽象方法 + `is_read_only()` 和 `to_api_schema()` 两个默认方法。这种"类属性 + 抽象方法 + 默认方法"的组合是 Python ABC 的典型设计模式。

2. **Pydantic BaseModel 作为输入 Schema 是系统的亮点**：一个模型类同时完成验证、文档、Schema 生成和序列化——Java 需要 Bean Validation + Swagger + Jackson 三套框架才能达到同样效果。

3. **ToolRegistry 用字典代替 IoC 容器**：`dict[str, BaseTool]` 简洁高效，工厂函数 `create_default_tool_registry()` 显式控制注册流程，条件注册一目了然。

4. **McpToolAdapter 展示了适配器模式**：将外部 MCP 工具接口转换成 `BaseTool` 接口，动态生成 `input_model`，体现了"面向接口编程"的设计原则。

5. **错误通过 ToolResult 返回，而非异常**：`is_error=True` 的 ToolResult 让调用者可以统一处理成功和失败，这是工具系统的重要设计决策。

6. **工厂函数 vs IoC 容器**：Python 社区偏好显式注册而非自动注入。`create_default_tool_registry()` 让注册顺序和条件完全可控，调试简单，测试方便——这比 Spring 的魔法更 Pythonic。