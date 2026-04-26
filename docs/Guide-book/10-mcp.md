# 第 10 章：MCP 集成

## 10.1 解决的问题

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，允许 LLM 应用与外部工具和数据源交互。OpenHarness 的 MCP 客户端负责：

1. **连接管理**：连接 STDIO、HTTP 和 WebSocket 三种传输方式的 MCP 服务器
2. **工具发现**：从 MCP 服务器获取可用工具列表
3. **工具调用**：将 MCP 工具作为内置工具的扩展透明接入
4. **资源管理**：读取 MCP 服务器提供的资源

## 10.2 MCP 服务器配置

### 10.2.1 配置格式

`mcp/types.py` 定义了三种传输配置：

```python
@dataclass
class McpStdioServerConfig:
    command: str            # 启动命令
    args: list[str]         # 命令行参数
    env: dict[str, str] | None  # 环境变量

@dataclass
class McpHttpServerConfig:
    url: str                # HTTP 端点
    headers: dict[str, str] | None  # HTTP 头

@dataclass
class McpWebSocketServerConfig:
    url: str                # WebSocket 端点
```

### 10.2.2 配置加载

`mcp/config.py` 从 Settings + Plugins 合并配置：

```python
def load_mcp_server_configs(settings, plugins):
    """合并 settings 和 plugin 中的 MCP 配置。"""
    configs = []
    
    # 1. 从设置文件加载
    for cfg in settings.mcp_servers:
        configs.append(_parse_config(cfg))
    
    # 2. 从插件加载
    for plugin in plugins:
        for mcp_cfg in plugin.mcp_servers:
            configs.append(mcp_cfg)
    
    return configs
```

## 10.3 McpClientManager

`mcp/client.py`：

```python
class McpClientManager:
    """管理多个 MCP 服务器的连接生命周期。"""
    
    def __init__(self):
        self._servers: dict[str, McpConnection] = {}
        self._exit_stack = AsyncExitStack()
    
    async def connect_all(self, configs: list[McpServerConfig]) -> None:
        """连接到所有配置的 MCP 服务器。"""
        for cfg in configs:
            try:
                await self._connect_one(cfg)
            except Exception as exc:
                log.warning("Failed to connect MCP server %s: %s", cfg.name, exc)
    
    async def _connect_one(self, config: McpServerConfig) -> None:
        """连接单个 MCP 服务器。"""
        if isinstance(config, McpStdioServerConfig):
            # STDIO 传输
            stdio_params = {
                "command": config.command,
                "args": config.args,
            }
            if config.env:
                stdio_params["env"] = config.env
            transport = self._exit_stack.enter_context(
                stdio_client(**stdio_params)
            )
        elif isinstance(config, McpHttpServerConfig):
            # HTTP 传输
            transport = self._exit_stack.enter_context(
                streamable_http_client(config.url, config.headers)
            )
        
        read, write = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        
        self._servers[config.name] = McpConnection(
            name=config.name,
            session=session,
            transport_type=type(config).__name__,
        )
```

### 10.3.1 工具发现

连接后自动获取 MCP 服务器提供的工具：

```python
async def list_tools(self) -> list[McpToolInfo]:
    """列出所有 MCP 服务器提供的工具。"""
    tools = []
    for conn in self._servers.values():
        try:
            result = await conn.session.list_tools()
            for tool in result.tools:
                tools.append(McpToolInfo(
                    server_name=conn.name,
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.inputSchema,
                ))
        except Exception as exc:
            log.warning("Failed to list tools from %s: %s", conn.name, exc)
    return tools
```

### 10.3.2 工具调用

```python
async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
    """调用 MCP 服务器上的工具。"""
    conn = self._servers.get(server_name)
    if conn is None:
        raise ValueError(f"MCP server not found: {server_name}")
    
    result = await conn.session.call_tool(tool_name, arguments)
    
    # 收集输出
    output_parts = []
    for content in result.content:
        if content.type == "text":
            output_parts.append(content.text)
        elif content.type == "resource":
            output_parts.append(f"[Resource: {content.resource.uri}]")
    
    return "\n".join(output_parts)
```

### 10.3.3 资源操作

```python
async def list_resources(self) -> list[McpResourceInfo]:
    """列出所有 MCP 资源。"""
    resources = []
    for conn in self._servers.values():
        try:
            result = await conn.session.list_resources()
            for resource in result.resources:
                resources.append(McpResourceInfo(
                    server_name=conn.name,
                    uri=resource.uri,
                    name=resource.name,
                    description=resource.description,
                ))
        except Exception as exc:
            log.warning("Failed to list resources from %s: %s", conn.name, exc)
    return resources

async def read_resource(self, server_name: str, uri: str) -> str:
    """读取 MCP 资源。"""
    conn = self._servers.get(server_name)
    if conn is None:
        raise ValueError(f"MCP server not found: {server_name}")
    
    result = await conn.session.read_resource(uri)
    # 处理并返回资源内容
    ...
```

## 10.4 MCP 工具适配器

### 10.4.1 McpToolAdapter

MCP 工具通过 `McpToolAdapter` 适配为 OpenHarness 的标准工具：

```python
class McpToolAdapter(BaseTool):
    """将 MCP 工具包装为 OpenHarness 工具。"""
    
    def __init__(self, mcp_tool: McpToolInfo, manager: McpClientManager):
        self.name = mcp_tool.name
        self.description = mcp_tool.description
        self._mcp_tool = mcp_tool
        self._manager = manager
        
        # 从 MCP Schema 动态生成 Pydantic 模型
        self.input_model = self._create_input_model(mcp_tool.input_schema)
    
    async def execute(self, arguments, context) -> ToolResult:
        try:
            output = await self._manager.call_tool(
                self._mcp_tool.server_name,
                self._mcp_tool.name,
                arguments.model_dump(),
            )
            return ToolResult(output=output)
        except Exception as exc:
            return ToolResult(output=str(exc), is_error=True)
```

### 10.4.2 工具注册

在 `create_default_tool_registry()` 中，所有 MCP 工具被注册：

```python
if mcp_manager:
    for mcp_tool in mcp_manager.list_tools():
        registry.register(McpToolAdapter(mcp_tool, mcp_manager))
```

这样，MCP 工具对 LLM 来说就和内置工具没有区别。

## 10.5 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| MCP 类型 | `mcp/types.py` | 服务器配置类型 |
| 客户端管理 | `mcp/client.py` | `McpClientManager` |
| 配置加载 | `mcp/config.py` | `load_mcp_server_configs()` |
| 工具适配器 | `tools/mcp_tool.py` | `McpToolAdapter` |
| MCP 认证 | `tools/mcp_auth_tool.py` | `McpAuthTool` |
| MCP 资源工具 | `tools/list_mcp_resources_tool.py` | `ListMcpResourcesTool` |
| MCP 资源读取 | `tools/read_mcp_resource_tool.py` | `ReadMcpResourceTool` |

## 10.6 本章小结

MCP 集成通过**适配器模式**将外部工具无缝接入 OpenHarness 的工具系统。`McpClientManager` 管理服务器的连接生命周期和自动重连。`McpToolAdapter` 将 MCP 工具包装为标准的 `BaseTool`，LLM 无需关心工具是内置的还是来自 MCP 服务器。

> 下一章：[聊天频道与 ohmo 个人 Agent](11-channels-ohmo.md) —— 多渠道接入与个人 Agent 架构。
