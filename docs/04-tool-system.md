# Phase 4: 工具系统深度解析

> 涉及文件: `tools/base.py` (76行), `tools/__init__.py` (104行), 以及 43+ 工具实现
> 核心: 理解工具如何被定义、注册、发现、执行

  工具系统的三层结构:
  BaseTool (接口) → ToolRegistry (注册表) → create_default_tool_registry() (工厂)

  每个工具的统一契约:
  - 输入: Pydantic BaseModel (自动验证 + 自动生成 JSON Schema)
  - 输出: ToolResult(output=str, is_error=bool) — 纯文本, 统一格式
  - 权限: is_read_only() — 直接影响权限决策链

  六种工具模式:

  ┌──────────────┬───────────────────────┬───────────────────────────────────────────┐
  │     模式     │         代表          │                   特点                    │
  ├──────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ A. 简单只读  │ read_file             │ Pydantic验证 → 业务逻辑 → 返回文本        │
  ├──────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ B. 写入      │ write_file, edit_file │ 沙箱检查 + 路径解析 + 权限确认            │
  ├──────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ C. Shell执行 │ bash                  │ 交互预检 + 超时 + 进程终止策略 + 输出截断 │
  ├──────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ D. 双策略    │ grep                  │ 优先ripgrep, fallback纯Python             │
  ├──────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ E. 模式切换  │ enter_plan_mode       │ 修改持久化Settings影响后续行为            │
  ├──────────────┼───────────────────────┼───────────────────────────────────────────┤
  │ F. 动态代理  │ McpToolAdapter        │ JSON Schema → Pydantic 动态生成           │
  └──────────────┴───────────────────────┴───────────────────────────────────────────┘

  写新工具只需 3 步: 定义 InputModel → 实现 BaseTool → 注册到 Registry。


## 1. 工具体系架构

```
BaseTool (ABC)           ← 所有工具的基类, 定义统一接口
  ├── input_model        ← Pydantic BaseModel, 声明式输入验证
  ├── execute()           ← 异步执行方法
  ├── is_read_only()      ← 影响权限决策
  └── to_api_schema()     ← 生成 API 所需的 JSON Schema

ToolRegistry              ← 工具注册表, name → BaseTool 映射
  ├── register()          ← 注册一个工具
  ├── get()               ← 按名称查找
  ├── list_tools()        ← 列出所有工具
  └── to_api_schema()     ← 生成全部工具的 Schema (传给 API 调用)

create_default_tool_registry()  ← 工厂函数, 注册 36 个内置工具 + MCP 动态工具
```

---

## 2. BaseTool 接口详解

```python
class BaseTool(ABC):
    name: str                          # 全局唯一标识, 如 "bash", "read_file"
    description: str                   # 给模型看的描述, 决定模型何时调用此工具
    input_model: type[BaseModel]       # Pydantic 模型, 自动生成 JSON Schema + 输入验证

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        """执行工具, 返回结果"""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """是否只读 — 影响权限决策 (默认 False)"""

    def to_api_schema(self) -> dict:
        """生成 Anthropic API 所需的工具 Schema:
        {
            "name": "read_file",
            "description": "Read a text file...",
            "input_schema": {  # JSON Schema
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "..."},
                    "offset": {"type": "integer", ...},
                    ...
                },
                "required": ["path"]
            }
        }
        """
```

**关键设计**: `input_model` 用 Pydantic BaseModel, 一石三鸟:
1. **Schema 生成**: `model_json_schema()` 自动生成 API 所需的 JSON Schema
2. **输入验证**: `model_validate(tool_input)` 在执行前验证, 无效输入返回错误而不是崩溃
3. **类型安全**: 工具内部拿到的是类型化对象, 不是 raw dict

---

## 3. ToolResult — 工具执行结果的统一格式

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                          # 文本输出 (唯一输出格式)
    is_error: bool = False               # 是否为错误
    metadata: dict[str, Any] = {}        # 可选元数据 (如 returncode, timed_out)
```

**核心约定**: 所有工具只返回文本。没有结构化返回值、没有二进制输出。这简化了整个系统 — 模型只消费文本, 工具只产出文本。

---

## 4. ToolExecutionContext — 执行上下文

```python
@dataclass
class ToolExecutionContext:
    cwd: Path                            # 工作目录
    metadata: dict[str, Any] = {}        # 运行时元数据 (跨工具共享)
```

`metadata` 由 QueryEngine 在调用工具时注入, 包含:

| 键 | 来源 | 被哪些工具使用 |
|----|------|---------------|
| `tool_registry` | QueryEngine.tool_metadata | Skill (查找 Skill), ToolSearch (搜索工具) |
| `ask_user_prompt` | QueryEngine.tool_metadata | AskUserQuestion (向用户提问) |
| `mcp_manager` | QueryEngine.tool_metadata | MCP 相关工具 |
| `bridge_manager` | QueryEngine.tool_metadata | Bridge 相关工具 |
| `extra_skill_dirs` | QueryEngine.tool_metadata | Skill (查找额外 Skill 目录) |
| `extra_plugin_roots` | QueryEngine.tool_metadata | Skill (查找插件 Skill) |
| `session_id` | QueryEngine.tool_metadata | 多个工具 |

**这是工具间通信的"侧信道"** — 工具不直接调用彼此, 而是通过 metadata 访问共享服务。

---

## 5. 工具注册清单: 36 内置 + N 个 MCP

### `create_default_tool_registry(mcp_manager)` 注册顺序

| # | 工具名 | 类 | read_only | 分类 |
|---|--------|-----|-----------|------|
| 1 | `bash` | BashTool | ❌ | Shell |
| 2 | `ask_user_question` | AskUserQuestionTool | ✅ | 交互 |
| 3 | `read_file` | FileReadTool | ✅ | 文件 I/O |
| 4 | `write_file` | FileWriteTool | ❌ | 文件 I/O |
| 5 | `edit_file` | FileEditTool | ❌ | 文件 I/O |
| 6 | `notebook_edit` | NotebookEditTool | ❌ | Notebook |
| 7 | `lsp` | LspTool | ✅ | 搜索 |
| 8 | `mcp_auth` | McpAuthTool | ❌ | MCP |
| 9 | `glob` | GlobTool | ✅ | 搜索 |
| 10 | `grep` | GrepTool | ✅ | 搜索 |
| 11 | `skill` | SkillTool | ✅ | 知识 |
| 12 | `tool_search` | ToolSearchTool | ✅ | 元 |
| 13 | `web_fetch` | WebFetchTool | ✅ | 搜索 |
| 14 | `web_search` | WebSearchTool | ✅ | 搜索 |
| 15 | `config` | ConfigTool | ❌ | 交互 |
| 16 | `brief` | BriefTool | ✅ | 交互 |
| 17 | `sleep` | SleepTool | ✅ | 交互 |
| 18 | `enter_worktree` | EnterWorktreeTool | ❌ | 模式 |
| 19 | `exit_worktree` | ExitWorktreeTool | ❌ | 模式 |
| 20 | `todo_write` | TodoWriteTool | ❌ | 交互 |
| 21 | `enter_plan_mode` | EnterPlanModeTool | ❌ | 模式 |
| 22 | `exit_plan_mode` | ExitPlanModeTool | ❌ | 模式 |
| 23 | `cron_create` | CronCreateTool | ❌ | 调度 |
| 24 | `cron_list` | CronListTool | ✅ | 调度 |
| 25 | `cron_delete` | CronDeleteTool | ❌ | 调度 |
| 26 | `cron_toggle` | CronToggleTool | ❌ | 调度 |
| 27 | `remote_trigger` | RemoteTriggerTool | ❌ | 调度 |
| 28 | `task_create` | TaskCreateTool | ❌ | Task |
| 29 | `task_get` | TaskGetTool | ✅ | Task |
| 30 | `task_list` | TaskListTool | ✅ | Task |
| 31 | `task_stop` | TaskStopTool | ❌ | Task |
| 32 | `task_output` | TaskOutputTool | ✅ | Task |
| 33 | `task_update` | TaskUpdateTool | ❌ | Task |
| 34 | `agent` | AgentTool | ❌ | Agent |
| 35 | `send_message` | SendMessageTool | ❌ | Agent |
| 36 | `team_create` | TeamCreateTool | ❌ | Agent |
| 37 | `team_delete` | TeamDeleteTool | ❌ | Agent |

MCP 动态注册 (条件性):

| # | 工具名 | 类 | 来源 |
|---|--------|-----|------|
| N | `list_mcp_resources` | ListMcpResourcesTool | 每个 session 1 个 |
| N | `read_mcp_resource` | ReadMcpResourceTool | 每个 session 1 个 |
| N | `mcp__{server}__{tool}` | McpToolAdapter | 每个 MCP 工具 1 个 |

### read_only 分布

```
✅ read_only (不需要用户确认): 16 个
   read_file, grep, glob, lsp, web_fetch, web_search, skill,
   tool_search, ask_user_question, brief, sleep, cron_list,
   task_get, task_list, task_output, list_mcp_resources

❌ read_write (需要确认): 21 个
   bash, write_file, edit_file, notebook_edit, config,
   enter_plan_mode, exit_plan_mode, enter_worktree, exit_worktree,
   todo_write, mcp_auth, cron_create, cron_delete, cron_toggle,
   remote_trigger, task_create, task_stop, task_update,
   agent, send_message, team_create, team_delete
```

---

## 6. 六种工具模式详解

### 模式 A: 简单只读工具 (read_file 为例)

```python
class FileReadToolInput(BaseModel):
    path: str = Field(description="Path of the file to read")
    offset: int = Field(default=0, ge=0)       # Pydantic 验证: >=0
    limit: int = Field(default=200, ge=1, le=2000)  # 验证: 1-2000

class FileReadTool(BaseTool):
    name = "read_file"
    description = "Read a text file from the local repository."
    input_model = FileReadToolInput

    def is_read_only(self, arguments) -> bool:
        return True                             # 只读, 免确认

    async def execute(self, arguments, context) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        # 沙箱检查 → 文件存在检查 → 二进制检查 → 读取+编号
        ...
```

**特征**: Pydantic 验证 → 沙箱检查 → 业务逻辑 → 返回文本。最简单的模式。

### 模式 B: 写入工具 (write_file / edit_file)

```python
# write_file: 全量写入
class FileWriteToolInput(BaseModel):
    path: str
    content: str
    create_directories: bool = True       # 自动创建目录

# edit_file: 字符串替换
class FileEditToolInput(BaseModel):
    path: str
    old_str: str                          # 必须唯一存在于文件中
    new_str: str
    replace_all: bool = False             # 全局替换 vs 首次替换
```

**共同特征**:
- `is_read_only = False` — 需要权限确认
- 沙箱路径验证 (`is_docker_sandbox_active()`)
- 相对路径 → 基于 cwd 的绝对路径解析

**edit_file 的安全设计**: `old_str not in original → is_error=True`, 确保不会意外修改错误的位置。

### 模式 C: Shell 执行 (bash)

```python
class BashToolInput(BaseModel):
    command: str
    cwd: str | None = None
    timeout_seconds: int = 600           # 默认 10 分钟超时
```

**最复杂的内置工具**, 包含:

1. **交互式命令预检** (`_preflight_interactive_command`): 检测 `create-next-app` 等 scaffold 命令, 提前返回错误而不是卡住
2. **沙箱支持**: `create_shell_subprocess` 自动路由到 Docker sandbox
3. **超时处理**: 超时后 kill 进程, 收集部分输出, 提供交互式提示
4. **输出截断**: 超过 12000 字符自动截断
5. **进程终止策略**: 先 `terminate()` → 等待 2s → `kill()`

### 模式 D: 双策略工具 (grep)

```python
class GrepTool(BaseTool):
    async def execute(self, arguments, context):
        # 1. 优先用 ripgrep (rg) — 快
        matches = await _rg_grep(...)
        if matches is not None:
            return _format_rg_result(matches, ...)

        # 2. fallback 到纯 Python — 慢但可移植
        return _python_grep_files(...)
```

**关键逻辑**:
- `shutil.which("rg")` 检测 ripgrep 是否可用
- rg 不可用 → 返回 None → Python fallback
- rg 退出码 0=有匹配, 1=无匹配, 其他=错误(回退 Python)
- 超时处理 + 输出限制
- Docker sandbox 感知

### 模式 E: 模式切换工具 (enter_plan_mode / exit_plan_mode)

```python
class EnterPlanModeTool(BaseTool):
    name = "enter_plan_mode"
    input_model = EnterPlanModeToolInput  # 空 Model, 无参数

    async def execute(self, arguments, context):
        settings = load_settings()
        settings.permission.mode = PermissionMode.PLAN
        save_settings(settings)
        return ToolResult(output="Permission mode set to plan")
```

**特征**: 通过修改持久化 Settings 来影响后续行为。工具返回后, `handle_line()` 会调用 `refresh_runtime_client()` 重新加载配置。

### 模式 F: 动态代理工具 (MCP)

```python
class McpToolAdapter(BaseTool):
    def __init__(self, manager, tool_info):
        self.name = f"mcp__{server_name}__{tool_name}"    # 三段式命名
        self.description = tool_info.description
        self.input_model = _input_model_from_schema(...)   # 从 JSON Schema 动态生成 Pydantic Model

    async def execute(self, arguments, context):
        output = await self._manager.call_tool(
            self._tool_info.server_name,
            self._tool_info.name,
            arguments.model_dump(...)        # 序列化回 JSON
        )
        return ToolResult(output=output)
```

**关键**: `McpToolAdapter` 把 MCP 服务器上的任意工具适配为 BaseTool 接口:
1. 从 MCP JSON Schema 动态创建 Pydantic Model (`_input_model_from_schema`)
2. 执行时把 Pydantic 对象序列化回 JSON, 调用 MCP `call_tool`
3. 工具名三段式: `mcp__{server}__{tool}`, 避免命名冲突

### JSON Schema → Pydantic Model 映射

```python
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

# required 字段 → Field(default=...)
# optional 字段 → type | None, Field(default=None)
# 用 pydantic.create_model() 动态生成类
```

---

## 7. 编写自定义工具的完整示例

```python
from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

# Step 1: 定义输入模型
class MySearchInput(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=10, ge=1, le=100)

# Step 2: 实现工具
class MySearchTool(BaseTool):
    name = "my_search"                           # 全局唯一名
    description = "Search my custom database"      # 模型看的
    input_model = MySearchInput

    def is_read_only(self, arguments) -> bool:
        return True                               # 只读 = 免确认

    async def execute(self, arguments: MySearchInput, context: ToolExecutionContext) -> ToolResult:
        # 业务逻辑
        results = do_search(arguments.query, arguments.max_results)
        return ToolResult(output=results)         # 只返回文本!

# Step 3: 注册
from openharness.tools import ToolRegistry
registry = ToolRegistry()
registry.register(MySearchTool())
```

**必须遵守的约定**:
1. 输入必须是 Pydantic BaseModel
2. 返回必须是 `ToolResult` (文本 + is_error)
3. 正确设置 `is_read_only()` — 这直接影响权限决策
4. 错误情况返回 `ToolResult(output="...", is_error=True)`, 不要抛异常
5. 相对路径必须基于 `context.cwd` 解析为绝对路径

---

## 8. 工具间依赖关系

```
                    ┌──────────────┐
                    │  ToolRegistry │ ←── 36 个内置工具 + MCP 动态工具
                    └──────┬───────┘
                           │ execute() 调用
                    ┌──────▼──────┐
                    │  BaseTool    │
                    └──────┬──────┘
                           │ 通过 context.metadata 访问
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │ SkillTool    │ │ AgentTool   │ │ MCP 相关    │
    │ → load_      │ │ → swarm/    │ │ → mcp/      │
    │   skill_     │ │   registry  │ │   client    │
    │   registry   │ │ → tasks/    │ │             │
    │              │ │   manager   │ │             │
    └─────────────┘ └─────────────┘ └─────────────┘
```

工具间不直接调用, 而是各自访问 `context.metadata` 中的共享服务:
- SkillTool → `metadata["extra_skill_dirs"]`, `metadata["extra_plugin_roots"]`
- AgentTool → `swarm.registry` (直接 import)
- TaskCreateTool → `tasks.manager` (直接 import)
- MCP 工具 → `metadata["mcp_manager"]`

---

## 9. 沙箱集成模式

写入工具 (read_file, write_file, edit_file) 和 bash/grep 都集成了沙箱检查:

```python
# 文件工具模式
if is_docker_sandbox_active():
    allowed, reason = validate_sandbox_path(path, context.cwd)
    if not allowed:
        return ToolResult(output=f"Sandbox: {reason}", is_error=True)

# Shell 工具模式
process = await create_shell_subprocess(...)  # 自动路由到 Docker sandbox
```

沙箱是透明的 — 工具代码不需要知道自己在不在沙箱里, `create_shell_subprocess` 和 `is_docker_sandbox_active()` 处理了所有差异。

---

## 10. 工具与 Agent Loop 的交互点回顾

从 Phase 3 我们知道 `_execute_tool_call()` 是调用工具的管道:

```
PreToolUse Hook
  → tool_registry.get(tool_name)          # 工具查找
  → tool.input_model.model_validate(...)  # 输入验证 (Pydantic!)
  → permission_checker.evaluate(...)      # 权限检查 (用 is_read_only!)
  → tool.execute(parsed_input, context)   # 执行
  → _record_tool_carryover(...)           # 状态携带
  → PostToolUse Hook
```

**`is_read_only()` 的关键作用**: 权限检查器调用 `tool.is_read_only(parsed_input)` 来决定:
- read_only=True → 默认模式直接放行
- read_only=False → 默认模式需要用户确认, auto 模式放行, plan 模式阻断

所以 **每个新工具必须正确实现 `is_read_only()`**, 否则权限系统会做出错误决策。

---

## 速查: 按功能找工具

| 我想... | 工具 | 文件 |
|---------|------|------|
| 读文件 | `read_file` | `file_read_tool.py` |
| 写文件 | `write_file` | `file_write_tool.py` |
| 编辑文件 | `edit_file` | `file_edit_tool.py` |
| 运行命令 | `bash` | `bash_tool.py` |
| 搜索内容 | `grep` | `grep_tool.py` |
| 搜索文件名 | `glob` | `glob_tool.py` |
| 访问网页 | `web_fetch` | `web_fetch_tool.py` |
| 搜索网页 | `web_search` | `web_search_tool.py` |
| LSP 操作 | `lsp` | `lsp_tool.py` |
| 加载知识 | `skill` | `skill_tool.py` |
| 生成子Agent | `agent` | `agent_tool.py` |
| 创建后台任务 | `task_create` | `task_create_tool.py` |
| 调 MCP 工具 | `mcp__{server}__{tool}` | `mcp_tool.py` |
| 进入计划模式 | `enter_plan_mode` | `enter_plan_mode_tool.py` |
| 写 Todo | `todo_write` | `todo_write_tool.py` |
| 问用户问题 | `ask_user_question` | `ask_user_question_tool.py` |
| 创建定时任务 | `cron_create` | `cron_create_tool.py` |