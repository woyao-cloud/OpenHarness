# 第十五章：插件、技能与 MCP —— 可扩展性架构

## 概述

OpenHarness 的可扩展性由三层体系构成：**插件（Plugin）** 是最高层封装，一个插件可以包含技能、命令、Agent、Hook 和 MCP 服务器；**技能（Skill）** 是可被 AI Agent 调用的 Markdown 知识包；**MCP（Model Context Protocol）** 则提供了与外部工具服务器的标准通信协议。三层协同工作，让 OpenHarness 从一个单纯的聊天机器人框架演化为一个可无限扩展的 Agent 平台。

本章将从 PluginManifest 到 MCP 客户端管理，逐层解析这套扩展性架构。

## Java 类比

> **Java 对比**：PluginManifest 类似于 Java 的 `MANIFEST.MF` 或 Eclipse/IntelliJ 的 `plugin.xml`——它声明了插件的元数据和各组件的位置。SkillRegistry 的 dict 注册机制类似于 Java 的 `ServiceLoader`，但更灵活：`ServiceLoader` 只能按接口类型查找，而 SkillRegistry 支持按名称直接查找。Python 的 `importlib` 动态导入类似于 Java 的 `ClassLoader` 体系，但更轻量——不需要处理类加载器隔离问题。McpServerConfig 的联合类型类似于 Jackson 的 `@JsonTypeInfo` 判别反序列化。

## 项目代码详解

### PluginManifest：插件声明文件

位于 `plugins/schemas.py`，使用 Pydantic BaseModel 定义：

```python
class PluginManifest(BaseModel):
    """Plugin manifest stored in plugin.json or .claude-plugin/plugin.json."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    enabled_by_default: bool = True
    skills_dir: str = "skills"
    hooks_file: str = "hooks.json"
    mcp_file: str = "mcp.json"
    # Extended fields
    author: dict | None = None
    commands: str | list | dict | None = None
    agents: str | list | None = None
    skills: str | list | None = None
    hooks: str | dict | list | None = None
```

一个典型的 `plugin.json` 如下：

```json
{
    "name": "code-reviewer",
    "version": "1.0.0",
    "description": "Automated code review plugin",
    "skills_dir": "skills",
    "hooks_file": "hooks.json",
    "mcp_file": "mcp.json",
    "enabled_by_default": true,
    "commands": "commands",
    "agents": "agents"
}
```

关键设计点：
- **`enabled_by_default`**：控制插件是否默认启用，用户可在设置中覆盖
- **灵活的命令/Agent 配置**：`commands`、`agents`、`skills` 字段支持 `str`（目录路径）、`list`（多个路径）或 `dict`（详细配置）三种格式
- **默认值合理**：`skills_dir`、`hooks_file`、`mcp_file` 都有合理的默认值，最小化配置工作量

> **Java 对比**：Java 插件系统通常使用 `MANIFEST.MF`（JAR 格式）或 `plugin.xml`（Eclipse/IntelliJ）。OpenHarness 的 `plugin.json` 更像 Eclipse 的 `plugin.xml`，声明式地描述插件结构。区别在于 Pydantic 的自动验证——如果 `plugin.json` 中 `version` 写成了数字而非字符串，Pydantic 会自动转换或报错，而 Java 的 `Manifest` 读取需要手动解析。

### LoadedPlugin：运行时插件对象

位于 `plugins/types.py`：

```python
@dataclass(frozen=True)
class LoadedPlugin:
    """A loaded plugin and its contributed artifacts."""
    manifest: PluginManifest
    path: Path
    enabled: bool
    skills: list[SkillDefinition] = field(default_factory=list)
    commands: list[PluginCommandDefinition] = field(default_factory=list)
    agents: list[AgentDefinition] = field(default_factory=list)
    hooks: dict[str, list] = field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def description(self) -> str:
        return self.manifest.description
```

`LoadedPlugin` 是插件从磁盘加载后的运行时表示。它聚合了插件的所有组件：技能、命令、Agent、Hook 和 MCP 服务器配置。`frozen=True` 保证加载后不可变。

> **Java 对比**：`LoadedPlugin` 类似于 OSGi 的 `Bundle` 对象——加载后包含了所有注册的服务和扩展点。但 Python 版本更简洁，不需要 OSGi 那样复杂的生命周期管理。

### 插件发现与加载

`plugins/loader.py` 实现了三层插件发现机制：

```python
def discover_plugin_paths(cwd: str | Path, extra_roots=None) -> list[Path]:
    """Find plugin directories from user and project locations."""
    roots = [get_user_plugins_dir(), get_project_plugins_dir(cwd)]
    if extra_roots:
        for root in extra_roots:
            path = Path(root).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            roots.append(path)
    paths: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for path in sorted(root.iterdir()):
            if path.is_dir() and _find_manifest(path) is not None and path not in seen:
                seen.add(path)
                paths.append(path)
    return paths
```

三层发现源：
1. **用户目录**：`~/.openharness/plugins/`——全局可用
2. **项目目录**：`<project>/.openharness/plugins/`——项目级
3. **额外根目录**：通过 `extra_roots` 参数传入——第三方托管

`_find_manifest` 支持两种布局：

```python
def _find_manifest(plugin_dir: Path) -> Path | None:
    """Find plugin.json in standard or .claude-plugin/ locations."""
    for candidate in [
        plugin_dir / "plugin.json",
        plugin_dir / ".claude-plugin" / "plugin.json",
    ]:
        if candidate.exists():
            return candidate
    return None
```

这意味着插件可以放在根目录或 `.claude-plugin/` 子目录中，兼容不同的项目结构偏好。

#### 加载流程

```python
def load_plugin(path: Path, enabled_plugins: dict[str, bool]) -> LoadedPlugin | None:
    """Load one plugin directory."""
    manifest_path = _find_manifest(path)
    if manifest_path is None:
        return None

    # 1. 解析清单
    manifest = PluginManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    enabled = enabled_plugins.get(manifest.name, manifest.enabled_by_default)

    # 2. 加载各组件
    skills = _load_plugin_skills(path / manifest.skills_dir)
    commands = _load_plugin_commands(path, manifest)
    agents = _load_plugin_agents(path, manifest)
    hooks = _load_plugin_hooks(path / manifest.hooks_file)
    mcp = _load_plugin_mcp(path / manifest.mcp_file)

    # 3. 组装并返回
    return LoadedPlugin(
        manifest=manifest, path=path, enabled=enabled,
        skills=skills, commands=commands, agents=agents,
        hooks=hooks, mcp_servers=mcp,
    )
```

> **Java 对比**：Java 的 `ServiceLoader` 需要在 `META-INF/services/` 下声明接口实现，而 OpenHarness 通过目录结构自动发现——`skills/` 目录下的 `SKILL.md` 文件就是技能，`agents/` 目录下的 `.md` 文件就是 Agent 定义。这种约定优于配置（Convention over Configuration）的方式比 Java 的 SPI 机制更轻量。

### SkillDefinition：Markdown 即技能

```python
@dataclass(frozen=True)
class SkillDefinition:
    """A loaded skill."""
    name: str
    description: str
    content: str        # Markdown 内容
    source: str         # "bundled" | "user" | "plugin"
    path: str | None = None
```

技能是一个简单的 Markdown 文件，通过 YAML frontmatter 提供元数据：

```markdown
---
name: code-review
description: Perform a thorough code review
---

# Code Review Skill

You are an expert code reviewer. Analyze the given code for:
- Security vulnerabilities
- Performance issues
- Style inconsistencies
...
```

#### 技能加载的三层来源

```python
def load_skill_registry(cwd=None, *, extra_skill_dirs=None, extra_plugin_roots=None, settings=None):
    """Load bundled and user-defined skills."""
    registry = SkillRegistry()
    # 1. 内置技能
    for skill in get_bundled_skills():
        registry.register(skill)
    # 2. 用户自定义技能
    for skill in load_user_skills():
        registry.register(skill)
    # 3. 额外目录技能
    for skill in load_skills_from_dirs(extra_skill_dirs):
        registry.register(skill)
    # 4. 插件中的技能
    if cwd is not None:
        for plugin in load_plugins(settings, cwd, extra_roots=extra_plugin_roots):
            if not plugin.enabled:
                continue
            for skill in plugin.skills:
                registry.register(skill)
    return registry
```

优先级顺序：内置 < 用户 < 额外目录 < 插件。后注册的同名技能会覆盖先注册的，实现了「用户覆盖内置」的定制逻辑。

#### SkillRegistry：字典注册表

```python
class SkillRegistry:
    """Store loaded skills by name."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register one skill."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        """Return a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """Return all skills sorted by name."""
        return sorted(self._skills.values(), key=lambda skill: skill.name)
```

> **Java 对比**：Java 的 `ServiceLoader<Skill>` 只能遍历所有实现，不支持按名称查找。OpenHarness 的 `dict[str, SkillDefinition]` 提供了 O(1) 的名称查找，类似于 Spring 的 `ApplicationContext.getBean(name)`，但不需要 IoC 容器的开销。

### McpServerConfig：联合类型配置

位于 `mcp/types.py`，支持三种传输协议：

```python
class McpStdioServerConfig(BaseModel):
    """stdio MCP server configuration."""
    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None


class McpHttpServerConfig(BaseModel):
    """HTTP MCP server configuration."""
    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class McpWebSocketServerConfig(BaseModel):
    """WebSocket MCP server configuration."""
    type: Literal["ws"] = "ws"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


McpServerConfig = McpStdioServerConfig | McpHttpServerConfig | McpWebSocketServerConfig
```

MCP（Model Context Protocol）是 Anthropic 提出的标准化协议，让 AI Agent 可以通过统一接口调用外部工具。三种传输方式：
- **stdio**：本地子进程通信，适合运行在本地的工具服务器
- **http**：HTTP SSE（Server-Sent Events），适合远程服务
- **ws**：WebSocket，适合需要双向实时通信的场景

> **Java 对比**：在 Java 中，判别反序列化通常用 Jackson 的 `@JsonTypeInfo` + `@JsonSubTypes`。Python 的 `Literal` + 联合类型方案更直观——`type` 字段值决定了反序列化为哪个子类，无需额外的注解体系。

### McpClientManager：连接管理

位于 `mcp/client.py`：

```python
class McpClientManager:
    """Manage MCP connections and expose tools/resources."""

    def __init__(self, server_configs: dict[str, object]) -> None:
        self._server_configs = server_configs
        self._statuses: dict[str, McpConnectionStatus] = {
            name: McpConnectionStatus(name=name, state="pending", transport=getattr(config, "type", "unknown"))
            for name, config in server_configs.items()
        }
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: dict[str, AsyncExitStack] = {}

    async def connect_all(self) -> None:
        """Connect all configured MCP servers."""
        for name, config in self._server_configs.items():
            if isinstance(config, McpStdioServerConfig):
                await self._connect_stdio(name, config)
            elif isinstance(config, McpHttpServerConfig):
                await self._connect_http(name, config)
            else:
                self._statuses[name] = McpConnectionStatus(
                    name=name, state="failed", transport=config.type, ...
                )

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        """Invoke one MCP tool and stringify the result."""
        session = self._sessions.get(server_name)
        if session is None:
            raise McpServerNotConnectedError(...)
        result: CallToolResult = await session.call_tool(tool_name, arguments)
        # ...处理结果...
```

关键设计点：
- **AsyncExitStack**：Python 的 `contextlib.AsyncExitStack` 用于管理多个异步上下文管理器的生命周期，确保连接关闭时资源正确释放
- **状态管理**：`McpConnectionStatus` 跟踪每个服务器的连接状态（pending/connected/failed/disabled）
- **工具发现**：连接成功后自动调用 `session.list_tools()` 和 `session.list_resources()` 获取远程工具清单

> **Java 对比**：`McpClientManager` 类似于 Spring 的 `ConnectionFactory` 或 gRPC 的 `ManagedChannel`——管理连接池和生命周期。`AsyncExitStack` 类似于 Java 7+ 的 try-with-resources，但支持异步资源管理。

### MCP 配置合并

`mcp/config.py` 实现了全局设置和插件配置的合并：

```python
def load_mcp_server_configs(settings, plugins: list[LoadedPlugin]) -> dict[str, object]:
    """Merge settings and plugin MCP server configs."""
    servers = dict(settings.mcp_servers)
    for plugin in plugins:
        if not plugin.enabled:
            continue
        for name, config in plugin.mcp_servers.items():
            servers.setdefault(f"{plugin.manifest.name}:{name}", config)
    return servers
```

`setdefault` 确保全局设置优先——插件的 MCP 服务器名称会被加上插件前缀以避免冲突。

## Python 概念说明

### Pydantic BaseModel：数据验证与序列化

Pydantic 是 Python 生态中最流行的数据验证库：

```python
class PluginManifest(BaseModel):
    name: str
    version: str = "0.0.0"
    enabled_by_default: bool = True
```

与 Java 的对比：
- Java 需要 getter/setter、构造函数、equals/hashCode
- Pydantic 自动生成这些，加上类型验证和 JSON 序列化
- `model_validate_json()` 等价于 Jackson 的 `ObjectMapper.readValue()`
- `Field(default=..., ge=1, le=600)` 提供了声明式验证，类似 Java Bean Validation 的 `@Min`/`@Max`

### dataclass(frozen=True) 与 field(default_factory)

`frozen=True` 使 dataclass 实例不可变，`field(default_factory=list)` 提供了可变默认值的安全初始化：

```python
@dataclass(frozen=True)
class LoadedPlugin:
    skills: list[SkillDefinition] = field(default_factory=list)
```

这避免了 Python 中经典的「可变默认参数」陷阱——如果写成 `skills: list[SkillDefinition] = []`，所有实例会共享同一个列表。

### Path：跨平台路径操作

Python 的 `pathlib.Path` 提供了比 Java 的 `java.nio.file.Path` 更直观的路径操作：

```python
path = Path("plugins") / "my-plugin" / "plugin.json"
path.mkdir(parents=True, exist_ok=True)  # 等价于 Java Files.createDirectories()
content = path.read_text(encoding="utf-8")  # 等价于 Files.readString()
```

### 联合类型（Union Type）

Python 3.10+ 的 `X | Y` 语法等价于 `Union[X, Y]`：

```python
commands: str | list | dict | None = None
McpServerConfig = McpStdioServerConfig | McpHttpServerConfig | McpWebSocketServerConfig
```

Java 17+ 的 sealed interface + pattern matching 提供了类似功能，但更冗长。

## 架构图

```
+------------------+     +------------------+     +------------------+
| 用户目录          |     | 项目目录           |     | 额外目录           |
| ~/.openharness/  |     | .openharness/    |     | extra_roots      |
| plugins/         |     | plugins/         |     |                  |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         v                        v                        v
+------------------------------------------------------------------+
|              discover_plugin_paths()                              |
|              (发现 + 去重 + 按 manifest 过滤)                       |
+------------------------------------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
|              load_plugin()                                        |
|  1. PluginManifest.model_validate_json() 解析 plugin.json         |
|  2. 检查 enabled_plugins 覆盖默认启用状态                           |
|  3. 加载 skills, commands, agents, hooks, mcp_servers             |
+------------------------------------------------------------------+
         |            |            |            |           |
         v            v            v            v           v
   SkillDefinition  PluginCmd   AgentDef    Hook Dict   McpConfig
         |            |            |            |           |
         v            v            v            v           v
+------------------------------------------------------------------+
|                    LoadedPlugin (frozen dataclass)                |
|  .manifest  .path  .enabled  .skills  .commands  .agents  ...    |
+------------------------------------------------------------------+

+-------------------+     +-------------------+
| 内置技能            |     | 用户技能             |
| (bundled/)        |     | (~/.openharness/   |
|                   |     |  skills/)          |
+--------+----------+     +--------+----------+
         |                        |
         v                        v
+------------------------------------------------------------------+
|                    SkillRegistry                                 |
|                    dict[str, SkillDefinition]                     |
|                    (后注册覆盖先注册)                                |
+------------------------------------------------------------------+

+-------------------+     +-------------------+     +-------------------+
| McpStdioConfig    |     | McpHttpConfig     |     | McpWsConfig       |
| (本地子进程)        |     | (HTTP SSE)        |     | (WebSocket)       |
+--------+----------+     +--------+----------+     +--------+----------+
         |                        |                        |
         v                        v                        v
+------------------------------------------------------------------+
|                    McpClientManager                               |
|  connect_all()  ->  为每个配置建立连接                               |
|  call_tool()    ->  调用远程工具                                     |
|  list_tools()   ->  发现可用工具                                     |
+------------------------------------------------------------------+
```

## 小结

本章详细解析了 OpenHarness 的三层可扩展性架构：

1. **PluginManifest** 使用 Pydantic BaseModel 声明插件元数据，支持灵活的 `str | list | dict | None` 类型字段
2. **LoadedPlugin** 作为运行时插件对象，聚合了技能、命令、Agent、Hook 和 MCP 服务器
3. **插件发现** 采用三层发现机制（用户/项目/额外），`_find_manifest` 兼容两种目录布局
4. **SkillDefinition** 实现「Markdown 即技能」的理念，通过 YAML frontmatter 提供元数据
5. **SkillRegistry** 使用字典注册表提供 O(1) 名称查找，后注册覆盖先注册
6. **McpServerConfig** 使用 `Literal` 判别联合支持 stdio/http/ws 三种传输方式
7. **McpClientManager** 使用 `AsyncExitStack` 管理 MCP 连接生命周期，自动发现远程工具

对于 Java 开发者，核心映射关系是：`PluginManifest` ↔ `plugin.xml`、`SkillRegistry dict` ↔ `ServiceLoader`、`Literal` 判别联合 ↔ `@JsonTypeInfo`、`importlib` 延迟导入 ↔ `ClassLoader` 动态加载。OpenHarness 的扩展性架构体现了 Python 的「简洁即力量」哲学——更少的样板代码，更灵活的类型系统，更直接的动态加载。