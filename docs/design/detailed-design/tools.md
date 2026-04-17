# 工具系统详细设计

## 1. 模块概述

工具系统（`tools/`）是 OpenHarness 的核心扩展层，负责将模型能力映射为可执行操作。系统围绕 `BaseTool` 抽象基类构建，采用 Pydantic 驱动的输入验证与 JSON Schema 自动生成，实现了 36 个内置工具和通过 MCP（Model Context Protocol）动态接入的第三方工具。

**源码分布：**

| 目录/文件 | 职责 |
|-----------|------|
| `tools/base.py` | 核心抽象：`BaseTool`、`ToolResult`、`ToolExecutionContext`、`ToolRegistry` |
| `tools/__init__.py` | 注册入口：`create_default_tool_registry()` 组装全部内置工具 |
| `tools/*.py` | 36 个独立工具实现文件，每个文件一个工具类 |
| `mcp/client.py` | MCP 客户端管理器：连接、调用、生命周期 |
| `mcp/config.py` | MCP 服务器配置加载与合并 |
| `mcp/types.py` | MCP 数据模型：服务器配置、工具/资源信息、连接状态 |
| `tools/mcp_tool.py` | MCP 工具适配器：动态 Pydantic 模型 + 三段式命名 |

**设计原则：**

- **声明式输入模型**：每个工具通过 Pydantic `BaseModel` 定义输入，自动完成验证与 JSON Schema 生成
- **统一返回契约**：所有工具返回不可变 `ToolResult`，通过 `is_error` 标记而非异常传递错误
- **权限感知**：`is_read_only()` 方法影响权限决策链路
- **路径安全**：相对路径统一通过 `context.cwd` 解析，Docker 沙箱模式下强制路径校验
- **双策略容错**：对 ripgrep 等外部依赖提供 Python 纯回退方案

---

## 2. 核心类/接口

### 2.1 BaseTool（抽象基类）

**文件**：`tools/base.py`（~76 行）

```python
class BaseTool(ABC):
    name: str                          # 全局唯一工具名
    description: str                   # 供模型理解的工具描述
    input_model: type[BaseModel]       # Pydantic 输入模型

    @abstractmethod
    async def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> ToolResult: ...

    def is_read_only(self, arguments: BaseModel) -> bool:
        return False                    # 默认写操作，子类按需覆写

    def to_api_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }
```

**关键设计决策：**

| 决策 | 理由 |
|------|------|
| `input_model` 为类属性而非方法 | 注册时即可获取 JSON Schema，无需实例化即可构建 API 声明 |
| `is_read_only` 接收 `arguments` 参数 | 允许根据参数动态判断（如 `bash` 中某些命令只读，某些写） |
| `to_api_schema()` 自动委托 Pydantic | 保证 API Schema 与输入验证逻辑永远一致，消除手写 Schema 漂移风险 |
| `execute` 为 `async` | 所有 I/O 操作（文件、进程、网络）天然异步 |

### 2.2 ToolResult（不可变结果）

**文件**：`tools/base.py`

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                                  # 文本输出（始终为 str）
    is_error: bool = False                       # 错误标记（非异常传播）
    metadata: dict[str, Any] = field(default_factory=dict)  # 附加元数据
```

**冻结（frozen=True）的意义：**

- 防止工具实现意外修改返回值
- 支持安全的缓存与日志记录
- `metadata` 字典虽可变内部，但外层引用不可替换

**`is_error` 而非异常的设计哲学：**

- 模型需要看到错误消息来修正行为，异常会中断对话循环
- 统一的 `ToolResult` 使调度器逻辑简单：永远 `output + is_error`
- `metadata` 携带结构化信息（如 `returncode`、`timed_out`）供上层决策

### 2.3 ToolExecutionContext（执行上下文）

**文件**：`tools/base.py`

```python
@dataclass
class ToolExecutionContext:
    cwd: Path                                    # 工作目录（路径解析基准）
    metadata: dict[str, Any] = field(default_factory=dict)  # 侧信道通信
```

**`metadata` 侧信道传递的关键对象：**

| 键 | 来源 | 用途 |
|----|------|------|
| `ask_user_prompt` | TUI 层 | `AskUserQuestionTool` 向用户提问的回调 |
| `tool_registry` | 调度器 | `ToolSearchTool` 查询可用工具 |
| `mcp_manager` | 启动阶段 | `McpAuthTool` 重新连接 MCP 服务器 |
| `extra_skill_dirs` | 插件系统 | `SkillTool` 加载额外技能目录 |
| `extra_plugin_roots` | 插件系统 | `SkillTool` 加载插件根路径 |

### 2.4 ToolRegistry（工具注册表）

**文件**：`tools/base.py`

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:    # 按 name 注册
    def get(self, name: str) -> BaseTool | None:    # 按 name 查找
    def list_tools(self) -> list[BaseTool]:         # 返回全部已注册工具
    def to_api_schema(self) -> list[dict]:          # 生成完整 API Schema 列表
```

**命名冲突处理**：`register()` 直接覆盖同名工具，MCP 工具的三段式命名（`mcp__server__tool`）天然避免与内置工具冲突。

---

## 3. 数据模型

### 3.1 工具输入模型一览

| 工具名 | 输入模型 | 关键字段 |
|--------|----------|----------|
| `read_file` | `FileReadToolInput` | `path`, `offset`(0), `limit`(200) |
| `write_file` | `FileWriteToolInput` | `path`, `content`, `create_directories`(True) |
| `edit_file` | `FileEditToolInput` | `path`, `old_str`, `new_str`, `replace_all`(False) |
| `notebook_edit` | `NotebookEditToolInput` | `path`, `cell_index`, `new_source`, `cell_type`, `mode`, `create_if_missing` |
| `bash` | `BashToolInput` | `command`, `cwd`(None), `timeout_seconds`(600) |
| `grep` | `GrepToolInput` | `pattern`, `root`, `file_glob`("**/*"), `case_sensitive`(True), `limit`(200), `timeout_seconds`(20) |
| `glob` | `GlobToolInput` | `pattern`, `root`, `limit`(200) |
| `lsp` | `LspToolInput` | `operation`, `file_path`, `symbol`, `line`, `character`, `query` |
| `web_fetch` | `WebFetchToolInput` | `url`, `max_chars`(12000) |
| `web_search` | `WebSearchToolInput` | `query`, `max_results`(5), `search_url` |
| `skill` | `SkillToolInput` | `name` |
| `tool_search` | `ToolSearchToolInput` | `query` |
| `agent` | `AgentToolInput` | `description`, `prompt`, `subagent_type`, `model`, `command`, `team`, `mode` |
| `task_create` | `TaskCreateToolInput` | `type`, `description`, `command`, `prompt`, `model` |
| `task_get` | `TaskGetToolInput` | `task_id` |
| `task_list` | `TaskListToolInput` | `status` |
| `task_output` | `TaskOutputToolInput` | `task_id`, `max_bytes`(12000) |
| `task_stop` | `TaskStopToolInput` | `task_id` |
| `task_update` | `TaskUpdateToolInput` | `task_id`, `description`, `progress`, `status_note` |
| `send_message` | `SendMessageToolInput` | `task_id`, `message` |
| `team_create` | `TeamCreateToolInput` | `name`, `description` |
| `team_delete` | `TeamDeleteToolInput` | `name` |
| `config` | `ConfigToolInput` | `action`, `key`, `value` |
| `cron_create` | `CronCreateToolInput` | `name`, `schedule`, `command`, `cwd`, `enabled` |
| `cron_list` | `CronListToolInput` | (无字段) |
| `cron_delete` | `CronDeleteToolInput` | `name` |
| `cron_toggle` | `CronToggleToolInput` | `name`, `enabled` |
| `remote_trigger` | `RemoteTriggerToolInput` | `name`, `timeout_seconds`(120) |
| `enter_plan_mode` | `EnterPlanModeToolInput` | (无字段) |
| `exit_plan_mode` | `ExitPlanModeToolInput` | (无字段) |
| `enter_worktree` | `EnterWorktreeToolInput` | `branch`, `path`, `create_branch`(True), `base_ref` |
| `exit_worktree` | `ExitWorktreeToolInput` | `path` |
| `todo_write` | `TodoWriteToolInput` | `item`, `checked`, `path` |
| `ask_user_question` | `AskUserQuestionToolInput` | `question` |
| `brief` | `BriefToolInput` | `text`, `max_chars`(200) |
| `sleep` | `SleepToolInput` | `seconds`(1.0) |
| `list_mcp_resources` | `ListMcpResourcesToolInput` | (无字段) |
| `read_mcp_resource` | `ReadMcpResourceToolInput` | `server`, `uri` |
| `mcp_auth` | `McpAuthToolInput` | `server_name`, `mode`, `value`, `key` |
| `mcp__*` | 动态生成 | 由 `_input_model_from_schema()` 创建 |

### 3.2 MCP 数据模型

**文件**：`mcp/types.py`

```python
# 服务器配置（三种传输层）
class McpStdioServerConfig(BaseModel):     # type="stdio"
    command: str; args: list[str]; env: dict|None; cwd: str|None

class McpHttpServerConfig(BaseModel):      # type="http"
    url: str; headers: dict[str, str]

class McpWebSocketServerConfig(BaseModel):  # type="ws"
    url: str; headers: dict[str, str]

McpServerConfig = McpStdioServerConfig | McpHttpServerConfig | McpWebSocketServerConfig

# 运行时数据
@dataclass(frozen=True)
class McpToolInfo:
    server_name: str; name: str; description: str; input_schema: dict

@dataclass(frozen=True)
class McpResourceInfo:
    server_name: str; name: str; uri: str; description: str = ""

@dataclass
class McpConnectionStatus:
    name: str; state: Literal["connected","failed","pending","disabled"]
    detail: str; transport: str; auth_configured: bool
    tools: list[McpToolInfo]; resources: list[McpResourceInfo]
```

---

## 4. 关键算法

### 4.1 六种工具实现模式

#### 模式 A：简单只读（read_file、glob、lsp、skill 等）

```
Pydantic 验证 → 沙箱路径检查 → 业务逻辑 → 返回文本
```

以 `FileReadTool` 为例：

1. `_resolve_path(context.cwd, arguments.path)` 解析相对路径为绝对路径
2. 若 Docker 沙箱激活，调用 `validate_sandbox_path()` 校验
3. 检查文件存在性、非目录、非二进制
4. UTF-8 解码后按 `offset/limit` 切片，加行号格式化

**特点**：`is_read_only()` 返回 `True`；无副作用；不修改任何文件系统状态。

#### 模式 B：写入操作（write_file、edit_file、notebook_edit、todo_write）

```
Pydantic 验证 → 沙箱路径检查 → 权限确认 → 路径解析 → 写入磁盘 → 返回确认
```

以 `FileEditTool` 为例：

1. 路径解析 + 沙箱校验
2. 读取原文件内容
3. 查找 `old_str`，若不存在返回 `is_error=True`
4. 执行 `str.replace(old_str, new_str, 1 或 -1)` 替换
5. `path.write_text()` 写回磁盘

**特点**：`is_read_only()` 返回 `False`（默认值）；修改文件系统；需权限系统放行。

#### 模式 C：Shell 执行（bash、remote_trigger）

```
交互预检 → 进程创建 → 超时等待 → 输出截断 → 进程终止 → 格式化
```

以 `BashTool` 为例的完整流程：

1. **交互预检**（`_preflight_interactive_command`）：检测脚手架命令（`create-next-app`、`npm create` 等），若未带非交互标志（`--yes`、`-y` 等）则拒绝执行，引导用户使用非交互模式
2. **进程创建**：`create_shell_subprocess()` 支持 PTY 模式，合并 stdout/stderr
3. **超时控制**：`asyncio.wait_for()` 限时等待，超时后：
   - `_drain_available_output()` 尝试读取已有输出（50ms 读取窗口）
   - `_terminate_process(force=True)` 强制 kill
   - `_format_timeout_output()` 格式化超时消息 + 交互提示
4. **输出截断**：超过 12000 字符截断并附加 `...[truncated]...`
5. **进程终止策略**：
   - `terminate()` → `wait(2s)` → `kill()` （优雅 → 强制）
   - `CancelledError` 时优雅终止，避免僵尸进程

#### 模式 D：双策略搜索（grep、glob）

```
shutil.which("rg") → 存在 → ripgrep 子进程 → 退出码校验 → 返回
                    → 不存在 → Python 纯回退 → 返回
```

以 `GrepTool` 为例：

1. `shutil.which("rg")` 检测 ripgrep 可用性
2. **ripgreg 路径**：
   - 构建 `rg --no-heading --line-number --color never` 命令
   - 检测 `.git` 或 `.gitignore` 决定是否 `--hidden`
   - 流式逐行读取，达到 `limit` 提前终止
   - 退出码 0/1 正常，-15/-9 被终止也正常，其他退出码回退到 Python
3. **Python 回退路径**：
   - `root.glob(file_glob)` 遍历文件
   - `re.compile()` 逐行匹配
   - 跳过二进制文件（`\x00` 检测）
   - 格式：`relative_path:line_number:content`

**GlobTool 的双策略**：ripgrep 的 `--files` + `--glob` 过滤 vs Python `Path.glob()`。

#### 模式 E：模式切换（enter_plan_mode、exit_plan_mode）

```
加载设置 → 修改权限模式 → 保存设置 → 返回确认
```

以 `EnterPlanModeTool` 为例：

1. `load_settings()` 加载持久化设置
2. `settings.permission.mode = PermissionMode.PLAN`
3. `save_settings(settings)` 写回磁盘
4. 调度器通过 `CommandResult(refresh_runtime=True)` 刷新运行时权限

**特点**：修改全局状态；影响后续所有工具调用的权限决策；`is_read_only()` 返回 `False`。

#### 模式 F：MCP 动态代理（McpToolAdapter）

```
McpToolInfo(input_schema) → _input_model_from_schema() → 动态 Pydantic 模型
execute → manager.call_tool(server, name, dict_args) → 字符串化结果
```

详见 4.2 节。

### 4.2 MCP 工具适配算法

**三段式命名**：

```python
name = f"mcp__{server_segment}__{tool_segment}"
```

- `server_segment` = `_sanitize_tool_segment(server_name)`，替换非字母数字字符为 `_`，确保首字符为字母
- `tool_segment` = `_sanitize_tool_segment(tool.name)`，同理

**JSON Schema → Pydantic 动态模型**：

```python
_JSON_TYPE_MAP = {
    "string":  str,
    "integer": int,
    "number":  float,
    "boolean": bool,
    "array":   list,
    "object":  dict,
}

def _input_model_from_schema(tool_name, schema):
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = {}
    for key, prop in properties.items():
        py_type = _JSON_TYPE_MAP.get(prop.get("type"), object)
        if key in required:
            fields[key] = (py_type, Field(default=...))    # 必填
        else:
            fields[key] = (py_type | None, Field(default=None))  # 可选
    return create_model(f"{tool_name}Input", **fields)
```

**局限**：不支持嵌套 `object` 或 `array.items` 的递归类型映射，复杂 Schema 退化为 `object` 或 `list`。

### 4.3 MCP 客户端管理器连接算法

**`McpClientManager.connect_all()`**：

1. 遍历所有 `server_configs`
2. 根据配置类型分发：
   - `McpStdioServerConfig` → `_connect_stdio()`：通过 `stdio_client()` 启动子进程
   - `McpHttpServerConfig` → `_connect_http()`：通过 `streamable_http_client()` + `httpx.AsyncClient` 连接
   - 其他类型 → 标记 `state="failed"`
3. 注册成功连接的会话：
   - `ClientSession(read_stream, write_stream)` + `initialize()`
   - `list_tools()` + `list_resources()` 发现工具与资源
   - 构建 `McpConnectionStatus(state="connected")`

**`call_tool()` 调用链路**：

1. 查找 `self._sessions[server_name]`
2. 若不存在，抛出 `McpServerNotConnectedError`
3. `session.call_tool(tool_name, arguments)` 调用远程工具
4. 遍历 `result.content`，提取 `text` 类型内容；非文本内容 `model_dump_json()`
5. 拼接并返回字符串

### 4.4 路径解析算法

所有文件操作工具共享相同的路径解析模式：

```python
def _resolve_path(base: Path, candidate: str) -> Path:
    path = Path(candidate).expanduser()       # 展开 ~/
    if not path.is_absolute():
        path = base / candidate               # 相对路径基于 cwd
    return path.resolve()                     # 解析符号链接与 ..
```

### 4.5 交互命令检测算法

`_looks_like_interactive_scaffold()` 检测常见的脚手架命令：

| 正向标记（命中即需检查） | 负向标记（存在则放行） |
|--------------------------|------------------------|
| `create-next-app` | `--yes`、` -y` |
| `npm create`、`pnpm create`、`yarn create` | `--skip-install` |
| `bun create`、`pnpm dlx` | `--defaults`、`--non-interactive` |
| `npx create-`、`bunx create-` | `--ci` |
| `npm init`、`pnpm init` | |

逻辑：`any(正向) and not any(负向)` → 拒绝执行。

### 4.6 输出截断算法

Bash 工具统一截断策略：

```python
MAX_OUTPUT = 12000  # 字符

def _format_output(buffer: bytearray) -> str:
    text = buffer.decode("utf-8", errors="replace").replace("\r\n", "\n").strip()
    if not text:
        return "(no output)"
    if len(text) > 12000:
        return f"{text[:12000]}\n...[truncated]..."
    return text
```

WebFetch 工具使用可配置 `max_chars`（默认 12000，上限 50000）。

---

## 5. 接口规范

### 5.1 BaseTool 抽象接口

```python
class BaseTool(ABC):
    # 类属性（子类必须定义）
    name: str                    # 全局唯一标识符，如 "read_file"、"bash"
    description: str             # 供模型理解的简短描述
    input_model: type[BaseModel] # Pydantic 输入模型类

    # 抽象方法（子类必须实现）
    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult

    # 可选覆写
    def is_read_only(self, arguments: BaseModel) -> bool  # 默认 False

    # 自动生成
    def to_api_schema(self) -> dict[str, Any]              # 生成 Anthropic API 格式
```

### 5.2 ToolRegistry 接口

| 方法 | 签名 | 说明 |
|------|------|------|
| `register` | `(tool: BaseTool) -> None` | 注册工具，按 `tool.name` 索引 |
| `get` | `(name: str) -> BaseTool \| None` | 按名称查找 |
| `list_tools` | `() -> list[BaseTool]` | 返回所有已注册工具 |
| `to_api_schema` | `() -> list[dict[str, Any]]` | 生成完整 API Schema 列表 |

### 5.3 McpClientManager 接口

| 方法 | 签名 | 说明 |
|------|------|------|
| `connect_all` | `async () -> None` | 连接所有配置的 MCP 服务器 |
| `reconnect_all` | `async () -> None` | 关闭后重新连接所有服务器 |
| `close` | `async () -> None` | 关闭所有活跃会话 |
| `list_statuses` | `() -> list[McpConnectionStatus]` | 返回所有服务器连接状态 |
| `list_tools` | `() -> list[McpToolInfo]` | 返回所有已发现的 MCP 工具 |
| `list_resources` | `() -> list[McpResourceInfo]` | 返回所有已发现的 MCP 资源 |
| `call_tool` | `async (server, tool, args) -> str` | 调用远程工具并字符串化结果 |
| `read_resource` | `async (server, uri) -> str` | 读取远程资源并字符串化结果 |
| `update_server_config` | `(name, config) -> None` | 运行时替换服务器配置 |
| `get_server_config` | `(name) -> object \| None` | 获取单个服务器配置 |

### 5.4 McpToolAdapter 接口

`McpToolAdapter` 继承 `BaseTool`，其构造函数：

```python
McpToolAdapter(manager: McpClientManager, tool_info: McpToolInfo)
```

`execute()` 内部委托 `manager.call_tool(server_name, name, model_dump())`。

### 5.5 Anthropic API Schema 格式

```python
{
    "name": "read_file",
    "description": "Read a text file from the local repository.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to read"},
            "offset": {"type": "integer", "default": 0, ...},
            "limit": {"type": "integer", "default": 200, ...}
        },
        "required": ["path"]
    }
}
```

由 `BaseTool.to_api_schema()` 自动从 Pydantic 模型生成，保证 API Schema 与验证逻辑的一致性。

---

## 6. 错误处理

### 6.1 统一错误返回模式

所有工具错误通过 `ToolResult(is_error=True)` 返回，绝不抛出异常到调度器层。

```python
# 正确方式
return ToolResult(output=f"File not found: {path}", is_error=True)

# 错误方式（禁止）
raise FileNotFoundError(path)
```

**例外**：`asyncio.CancelledError` 会重新抛出，确保任务取消信号正确传播。

### 6.2 按工具类型的错误场景

| 工具类型 | 错误场景 | 错误消息模式 |
|----------|----------|-------------|
| 文件读取 | 文件不存在 | `File not found: {path}` |
| 文件读取 | 是目录 | `Cannot read directory: {path}` |
| 文件读取 | 二进制文件 | `Binary file cannot be read as text: {path}` |
| 文件写入 | 沙箱路径拒绝 | `Sandbox: {reason}` |
| 文件编辑 | old_str 未找到 | `old_str was not found in the file` |
| Bash | 交互命令 | `This command appears to require interactive input...` |
| Bash | 超时 | `Command timed out after {N} seconds.` |
| Bash | 非零退出码 | `is_error=True`，`metadata={"returncode": N}` |
| Bash | 沙箱不可用 | `SandboxUnavailableError` 字符串化 |
| Grep | ripgrep 失败 | 自动回退到 Python 实现 |
| MCP | 服务器未连接 | `MCP server '{name}' is not connected: {detail}` |
| MCP | 调用失败 | `MCP server '{name}' call failed: {exc}` |
| LSP | 文件不存在 | `File not found: {path}` |
| LSP | 非 Python 文件 | `The lsp tool currently supports Python files only.` |
| Cron | 表达式无效 | `Invalid cron expression: {expr}` |
| Cron | 任务不存在 | `Cron job not found: {name}` |
| Task | 任务不存在 | `No task found with ID: {id}` |
| Agent | 生成失败 | 异常字符串化 |
| WebFetch | URL 无效 | `web_fetch failed: {error_message}` |
| WebFetch | HTTP 错误 | `web_fetch failed: {exc}` |

### 6.3 MCP 连接失败的分类

`McpConnectionStatus.state` 四种状态：

| 状态 | 含义 | 恢复方式 |
|------|------|----------|
| `pending` | 尚未尝试连接 | `connect_all()` |
| `connected` | 连接正常 | 自动保持 |
| `failed` | 连接失败 | `reconnect_all()` 或 `mcp_auth` 修复配置 |
| `disabled` | 被禁用 | 修改配置后重连 |

### 6.4 进程终止的容错

```python
async def _terminate_process(process, *, force=False):
    if process.returncode is not None:
        return                     # 已退出，无需操作
    if force:
        process.kill()             # SIGKILL
        await process.wait()
        return
    process.terminate()            # SIGTERM
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        process.kill()             # 2 秒后强制终止
        await process.wait()
```

---

## 7. 配置项

### 7.1 工具级默认值

| 工具 | 参数 | 默认值 | 范围 |
|------|------|--------|------|
| `bash` | `timeout_seconds` | 600 | [1, 600] |
| `grep` | `limit` | 200 | [1, 2000] |
| `grep` | `timeout_seconds` | 20 | [1, 120] |
| `glob` | `limit` | 200 | [1, 5000] |
| `read_file` | `limit` | 200 | [1, 2000] |
| `web_fetch` | `max_chars` | 12000 | [500, 50000] |
| `web_search` | `max_results` | 5 | [1, 10] |
| `sleep` | `seconds` | 1.0 | [0.0, 30.0] |
| `remote_trigger` | `timeout_seconds` | 120 | [1, 600] |
| `task_output` | `max_bytes` | 12000 | [1, 100000] |
| `brief` | `max_chars` | 200 | [20, 2000] |

### 7.2 MCP 服务器配置

通过 `settings.mcp_servers` 字典配置，键为服务器名称，值为 `McpServerConfig` 联合类型。

**stdio 配置示例**：
```json
{
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "env": {"API_KEY": "xxx"}
}
```

**http 配置示例**：
```json
{
    "type": "http",
    "url": "http://localhost:3001/mcp",
    "headers": {"Authorization": "Bearer token"}
}
```

**配置合并优先级**：

1. `settings.mcp_servers`（用户全局设置）
2. 插件贡献的 `plugin.mcp_servers`，键名加前缀 `{plugin_name}:{server_name}`

通过 `mcp/config.py` 的 `load_mcp_server_configs(settings, plugins)` 合并，插件配置使用 `setdefault` 不覆盖用户设置。

### 7.3 MCP 认证配置

`mcp_auth` 工具支持三种模式：

| 模式 | 适用传输层 | 行为 |
|------|-----------|------|
| `bearer` | stdio | 设置环境变量 `MCP_AUTH_TOKEN=Bearer {value}` |
| `env` | stdio | 设置自定义环境变量 `key={value}` |
| `header` | http/ws | 设置 HTTP 头 `Authorization={value}` |
| `bearer` | http/ws | 设置 HTTP 头 `Authorization=Bearer {value}` |

认证更新后自动尝试 `mcp_manager.reconnect_all()`。

---

## 8. 与其它模块的交互

### 8.1 模块依赖关系

```
tools/
 ├── base.py ─────────── Pydantic (数据验证/Schema 生成)
 ├── __init__.py ─────── tools/*.py (工具注册)
 ├── file_*_tool.py ──── sandbox/session.py, sandbox/path_validator.py
 ├── bash_tool.py ────── sandbox/, utils/shell.py
 ├── grep_tool.py ────── sandbox/session.py
 ├── glob_tool.py ────── sandbox/session.py
 ├── lsp_tool.py ─────── services/lsp.py
 ├── agent_tool.py ───── coordinator/agent_definitions.py,
 │                      coordinator/coordinator_mode.py,
 │                      swarm/registry.py, swarm/types.py
 ├── task_*_tool.py ──── tasks/manager.py
 ├── cron_*_tool.py ──── services/cron.py, services/cron_scheduler.py
 ├── send_message ────── swarm/registry.py, tasks/manager.py
 ├── team_*_tool.py ──── coordinator/coordinator_mode.py
 ├── config_tool.py ──── config/settings.py
 ├── plan_mode ───────── config/settings.py, permissions.py
 ├── worktree ────────── git (subprocess)
 ├── mcp_tool.py ────── mcp/client.py, mcp/types.py
 ├── mcp_auth ────────── mcp/client.py, mcp/types.py, config/settings.py
 ├── web_*_tool.py ───── utils/network_guard.py, httpx
 ├── skill_tool.py ───── skills/
 └── ask_user ────────── TUI 层 (通过 metadata 回调)
```

### 8.2 与权限系统的交互

权限决策链路：

```
模型请求 tool_use(name, input)
    → 查找 registry.get(name)
    → 调用 tool.is_read_only(arguments)
    → 权限系统根据当前模式 + is_read_only 结果决策
    → 允许 → 执行 execute()
    → 拒绝 → 返回权限错误
```

`is_read_only=True` 的工具在 PLAN 模式下可执行，`is_read_only=False` 的工具需要用户确认或更高权限模式。

### 8.3 与沙箱系统的交互

文件操作工具（read_file、write_file、edit_file）在 `execute()` 开头检查 Docker 沙箱状态：

```python
from openharness.sandbox.session import is_docker_sandbox_active

if is_docker_sandbox_active():
    from openharness.sandbox.path_validator import validate_sandbox_path
    allowed, reason = validate_sandbox_path(path, context.cwd)
    if not allowed:
        return ToolResult(output=f"Sandbox: {reason}", is_error=True)
```

Shell 执行工具（bash、grep、glob）通过 `get_docker_sandbox()` 获取沙箱会话，在沙箱内执行命令：

```python
from openharness.sandbox.session import get_docker_sandbox
session = get_docker_sandbox()
if session is not None and session.is_running:
    process = await session.exec_command(cmd, cwd=root, ...)
else:
    process = await asyncio.create_subprocess_exec(*cmd, cwd=str(root), ...)
```

### 8.4 与配置系统的交互

**读取**：`config_tool`、`enter_plan_mode`、`exit_plan_mode`、`mcp_auth` 均通过 `load_settings()` 读取。

**写入**：修改后通过 `save_settings(settings)` 持久化，影响全局运行时行为。

**运行时刷新**：`mcp_auth` 修改认证后触发 `mcp_manager.reconnect_all()`，`plan_mode` 修改权限模式后调度器刷新运行时。

### 8.5 与任务系统的交互

`task_*` 工具族通过全局单例 `get_task_manager()` 交互：

- `task_create` → `manager.create_shell_task()` / `manager.create_agent_task()`
- `task_get` → `manager.get_task()`
- `task_list` → `manager.list_tasks()`
- `task_output` → `manager.read_task_output()`
- `task_stop` → `manager.stop_task()`
- `task_update` → `manager.update_task()`

`agent` 工具通过 `get_backend_registry()` 的 subprocess 执行器生成代理，注册到任务系统。

### 8.6 与 Swarm/协调系统的交互

- `agent` 工具：通过 `get_backend_registry()` 获取 subprocess 执行器，`spawn()` 生成代理；若指定 `team`，通过 `get_team_registry()` 注册代理到团队
- `send_message` 工具：若 `task_id` 含 `@` 则路由到 swarm 后端（`agent_id` 格式 `name@team`），否则委托任务管理器
- `team_create/team_delete`：通过 `get_team_registry()` 管理内存中的团队

### 8.7 与插件系统的交互

`load_mcp_server_configs(settings, plugins)` 合并插件贡献的 MCP 服务器配置。`SkillTool` 通过 `load_skill_registry(cwd, extra_skill_dirs, extra_plugin_roots)` 加载插件提供的额外技能。

### 8.8 与 TUI 层的交互

`AskUserQuestionTool` 通过 `context.metadata["ask_user_prompt"]` 回调与 TUI 层交互，该回调由 TUI 层注入，工具本身不直接依赖 TUI。

### 8.9 工具注册完整清单

`create_default_tool_registry()` 注册的 36 个内置工具，按功能分类：

| 分类 | 工具名 | is_read_only |
|------|--------|-------------|
| **文件 I/O** | `read_file` | True |
| | `write_file` | False |
| | `edit_file` | False |
| | `notebook_edit` | False |
| | `glob` | True |
| | `grep` | True |
| **Shell** | `bash` | False |
| **搜索** | `tool_search` | True |
| | `web_fetch` | True |
| | `web_search` | True |
| | `lsp` | True |
| | `skill` | True |
| | `brief` | True |
| **代理** | `agent` | False |
| | `send_message` | False |
| | `team_create` | False |
| | `team_delete` | False |
| **任务** | `task_create` | False |
| | `task_get` | True |
| | `task_list` | True |
| | `task_output` | True |
| | `task_stop` | False |
| | `task_update` | False |
| **调度** | `cron_create` | False |
| | `cron_list` | True |
| | `cron_delete` | False |
| | `cron_toggle` | False |
| | `remote_trigger` | False |
| **MCP** | `list_mcp_resources` | True |
| | `read_mcp_resource` | True |
| | `mcp_auth` | False |
| **交互** | `ask_user_question` | True |
| | `todo_write` | False |
| | `sleep` | True |
| | `config` | False |
| **模式** | `enter_plan_mode` | False |
| | `exit_plan_mode` | False |
| | `enter_worktree` | False |
| | `exit_worktree` | False |

**统计**：16 个只读工具 + 21 个写工具 = 37 个注册位（含 `list_mcp_resources`）。

MCP 动态工具在 `mcp_manager is not None` 时额外注册：
- `list_mcp_resources`
- `read_mcp_resource`
- 每个已连接 MCP 工具 → `McpToolAdapter` 实例（名称 `mcp__{server}__{tool}`）

---

## 附录：编写新工具的三步流程

### 步骤 1：定义输入模型

在工具文件中定义 Pydantic `BaseModel`，所有字段附带 `Field(description=...)`：

```python
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    target: str = Field(description="操作目标")
    dry_run: bool = Field(default=False, description="试运行模式")
```

### 步骤 2：实现 BaseTool 子类

```python
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

class MyTool(BaseTool):
    name = "my_tool"                    # 全局唯一
    description = "执行自定义操作"        # 供模型理解
    input_model = MyToolInput

    def is_read_only(self, arguments: MyToolInput) -> bool:
        return not arguments.dry_run     # 可根据参数动态判断

    async def execute(self, arguments: MyToolInput, context: ToolExecutionContext) -> ToolResult:
        # 1. 路径解析（如涉及文件操作）
        # 2. 沙箱校验（如涉及文件/进程）
        # 3. 业务逻辑
        # 4. 返回 ToolResult
        return ToolResult(output=f"Done: {arguments.target}")
```

### 步骤 3：注册到 Registry

在 `tools/__init__.py` 的 `create_default_tool_registry()` 中添加：

```python
from openharness.tools.my_tool import MyTool

# 在 for tool in (...) 循环中加入：
MyTool(),
```

### 约定检查清单

- [ ] `input_model` 必须为 Pydantic `BaseModel` 子类
- [ ] 返回值必须为 `ToolResult`，错误时 `is_error=True`
- [ ] 错误绝不以异常形式抛出到调度器层（`CancelledError` 除外）
- [ ] 相对路径必须通过 `context.cwd` 解析为绝对路径
- [ ] 涉及文件写入的工具须检查沙箱路径
- [ ] `is_read_only()` 按实际语义覆写
- [ ] 所有输入字段附带 `Field(description=...)` 供模型理解
- [ ] 输出文本长度合理，避免超出上下文窗口