# 第 5 章：工具系统

## 5.1 解决的问题

LLM 需要通过工具与世界交互。工具系统负责：定义工具规范、验证输入、注册查找、安全执行。OpenHarness 内置了 30+ 工具。

## 5.2 核心抽象

### 5.2.1 BaseTool

`tools/base.py` 定义了所有工具的基类：

```python
class BaseTool(ABC):
    name: str = ""                        # 工具名称（LLM 调用时使用）
    description: str = ""                 # 描述（告诉 LLM 何时使用）
    input_model: type[BaseModel] = ...    # Pydantic 输入验证模型

    @abstractmethod
    async def execute(self, arguments, context) -> ToolResult:
        """执行工具逻辑"""
    
    def to_api_schema(self) -> dict:
        """生成 JSON Schema（供 API 调用）"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }
    
    def is_read_only(self, parsed_input) -> bool:
        """此调用是否为只读？默认 False，子类可覆盖"""
        return False
```

**精妙之处**：
- `input_model` 是 Pydantic 模型 → 自动生成 JSON Schema → LLM 理解参数格式
- `to_api_schema()` 将工具描述转换为 API 可消费的格式
- `is_read_only()` 支持权限系统判断是否需要用户确认

### 5.2.2 ToolResult

```python
@dataclass
class ToolResult:
    output: str         # 执行结果文本
    is_error: bool      # 是否出错
    metadata: dict | None = None  # 额外元数据
```

### 5.2.3 ToolExecutionContext

```python
@dataclass
class ToolExecutionContext:
    cwd: Path                        # 当前工作目录
    metadata: dict[str, Any] | None  # 共享元数据（ask_user_prompt, tool_registry 等）
```

### 5.2.4 ToolRegistry

```python
class ToolRegistry:
    _tools: dict[str, BaseTool]
    
    def register(self, tool: BaseTool) -> None: ...
    def get(self, name: str) -> BaseTool | None: ...
    def list_tools(self) -> list[BaseTool]: ...
    def to_api_schema(self) -> list[dict]: ...
```

## 5.3 30+ 内置工具

`tools/__init__.py` 中的 `create_default_tool_registry()` 注册所有工具。

### 5.3.1 文件操作

| 工具 | 文件 | 功能 | 只读？ |
|------|------|------|--------|
| `Bash` | `bash_tool.py` | 执行 Shell 命令 | 否 |
| `Read` | `file_read_tool.py` | 读取文件内容 | 是 |
| `Write` | `file_write_tool.py` | 写入文件 | 否 |
| `Edit` | `file_edit_tool.py` | 编辑文件（精确替换） | 否 |
| `Glob` | `glob_tool.py` | 文件模式匹配 | 是 |
| `Grep` | `grep_tool.py` | 内容搜索 | 是 |
| `NotebookEdit` | `notebook_edit_tool.py` | Jupyter 单元格编辑 | 否 |

### 5.3.2 搜索

| 工具 | 功能 | 只读？ |
|------|------|--------|
| `WebFetch` | 获取网页内容 | 是 |
| `WebSearch` | 网络搜索 | 是 |
| `ToolSearch` | 在已注册工具中搜索 | 是 |

### 5.3.3 Agent 与协作

| 工具 | 功能 | 说明 |
|------|------|------|
| `Agent` | 派生异步子 Agent | 后台运行，有独立会话 |
| `SendMessage` | 向异步 Agent 发送消息 | 任务间通信 |
| `TeamCreate` | 创建 Agent 团队 | 多 Agent 协作 |
| `TeamDelete` | 删除 Agent 团队 | |

### 5.3.4 任务管理

| 工具 | 功能 |
|------|------|
| `TaskCreate` | 创建后台任务 |
| `TaskGet` | 获取任务详情 |
| `TaskList` | 列出所有任务 |
| `TaskUpdate` | 更新任务 |
| `TaskStop` | 停止任务 |
| `TaskOutput` | 获取任务输出 |

### 5.3.5 定时与远程

| 工具 | 功能 |
|------|------|
| `CronCreate` | 创建定时任务 |
| `CronList` | 列出定时任务 |
| `CronDelete` | 删除定时任务 |
| `CronToggle` | 启用/禁用定时任务 |
| `RemoteTrigger` | 远程触发执行 |

### 5.3.6 MCP

| 工具 | 功能 |
|------|------|
| `McpToolAdapter` | 调用 MCP 服务器工具 |
| `McpAuthTool` | MCP 认证 |
| `ListMcpResourcesTool` | 列出 MCP 资源 |
| `ReadMcpResourceTool` | 读取 MCP 资源 |

### 5.3.7 工作流与模式

| 工具 | 功能 |
|------|------|
| `EnterPlanMode` | 进入计划模式 |
| `ExitPlanMode` | 退出计划模式 |
| `EnterWorktree` | 进入 Git Worktree |
| `ExitWorktree` | 退出 Git Worktree |
| `AskUserQuestion` | 向用户提问 |
| `TodoWrite` | 写入 Todo 列表 |
| `Sleep` | 等待指定时间 |

### 5.3.8 元工具

| 工具 | 功能 |
|------|------|
| `Skill` | 加载技能知识 |
| `Config` | 修改配置 |
| `Brief` | 显示系统摘要 |

## 5.4 工具注册

### 5.4.1 创建默认注册中心

```python
def create_default_tool_registry(
    mcp_manager: McpClientManager | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    
    # 注册所有内置工具
    registry.register(BashTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    # ... 30+ 工具
    registry.register(ToolSearchTool(registry))  # 工具搜索引用自身
    
    # 注册 MCP 工具
    if mcp_manager:
        for mcp_tool in mcp_manager.list_tools():
            registry.register(McpToolAdapter(mcp_tool, mcp_manager))
    
    return registry
```

### 5.4.2 JSON Schema 生成

每个工具通过 `to_api_schema()` 生成供 LLM 使用的 Schema：

```python
# 例如 BashTool 的 Schema
{
    "name": "bash",
    "description": "Execute a shell command",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run"},
            "timeout": {"type": "number", "description": "Timeout in ms"}
        },
        "required": ["command"]
    }
}
```

## 5.5 关键设计模式

### 5.5.1 只读检测

`is_read_only()` 用于权限判断：

```python
# Read 工具是只读的
class FileReadTool(BaseTool):
    name = "Read"
    description = "Read file contents"
    
    def is_read_only(self, parsed_input) -> bool:
        return True

# Write 工具不是只读的（默认）
class FileWriteTool(BaseTool):
    name = "Write"
    description = "Write content to a file"
    # 不覆盖 is_read_only → 默认 False
```

### 5.5.2 递归引用

`ToolSearchTool` 接收 `ToolRegistry` 作为参数，实现在线工具搜索：

```python
class ToolSearchTool(BaseTool):
    name = "tool_search"
    description = "Search available tools"
    
    def __init__(self, registry: ToolRegistry):
        self._registry = registry
    
    async def execute(self, arguments, context):
        query = arguments.query.lower()
        results = [
            t for t in self._registry.list_tools()
            if query in t.name.lower() or query in t.description.lower()
        ]
        return ToolResult(output=format_tool_list(results))
```

## 5.6 关键源码路径

| 组件 | 文件 |
|------|------|
| BaseTool | `tools/base.py` |
| ToolRegistry | `tools/base.py` |
| ToolResult | `tools/base.py` |
| 默认注册 | `tools/__init__.py` |
| 文件工具 | `tools/file_read_tool.py`, `file_write_tool.py`, `file_edit_tool.py` |
| Bash 工具 | `tools/bash_tool.py` |
| Agent 工具 | `tools/agent_tool.py`, `tools/send_message_tool.py` |
| MCP 工具 | `tools/mcp_tool.py` |

## 5.7 本章小结

工具系统通过 **BaseTool 抽象 + Pydantic 验证 + 注册中心 + Schema 导出**，为 LLM 提供了结构化的"能力接口"。30+ 工具覆盖了文件操作、搜索、执行、协作、定时、工作流等领域。

> 下一章：[记忆管理](06-memory.md) —— 持久化记忆、对话压缩与 Token 预算控制。
