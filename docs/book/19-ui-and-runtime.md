# 第十九章：UI 层与运行时装配

## 概述

OpenHarness 的 `build_runtime()` 函数是整个系统的"装配线"——它将配置、API 客户端、工具注册表、Hook 系统、MCP 管理器、查询引擎等组件组装为一个可运行的 `RuntimeBundle`。UI 层则提供三种模式：React TUI（前后端分离）、Textual TUI（纯 Python 终端 UI）以及后端宿主模式。

本章将深入解析：

- `ui/runtime.py` — RuntimeBundle 数据类与 build_runtime() 函数
- `ui/protocol.py` — FrontendRequest 与 BackendEvent
- UI 三模式：React TUI、Textual TUI、后端宿主
- Callable 类型提示与回调注入
- 主题/样式加载
- 快捷键加载

> **Java 对比**：`build_runtime()` 可以类比为 Spring 的 `@Configuration` 类 + `@Bean` 方法——手动编排依赖关系。`RuntimeBundle` 对应 Spring 的 `ApplicationContext`，其中包含了所有已装配的 Bean。

---

## 1. RuntimeBundle：运行时数据包

### 项目代码详解

```python
# ui/runtime.py
@dataclass
class RuntimeBundle:
    """Shared runtime objects for one interactive session."""

    api_client: SupportsStreamingMessages
    cwd: str
    mcp_manager: McpClientManager
    tool_registry: ToolRegistry
    app_state: AppStateStore
    hook_executor: HookExecutor
    engine: QueryEngine
    commands: object
    external_api_client: bool
    enforce_max_turns: bool = True
    session_id: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)
    session_backend: SessionBackend = DEFAULT_SESSION_BACKEND
    extra_skill_dirs: tuple[str, ...] = ()
    extra_plugin_roots: tuple[str, ...] = ()

    def current_settings(self):
        """Return the effective settings for this session."""
        return load_settings().merge_cli_overrides(**self.settings_overrides)

    def hook_summary(self) -> str:
        return load_hook_registry(self.current_settings(), self.current_plugins()).summary()

    def mcp_summary(self) -> str:
        statuses = self.mcp_manager.list_statuses()
        # ... 格式化输出
```

> **Java 对比**：`RuntimeBundle` 等价于 Spring 的 `ApplicationContext`——一个包含所有已初始化 Bean 的容器。但 Python 版本是显式装配（手动构造），而 Spring 是声明式装配（注解驱动）。Python 的方式更透明、更易调试——每个依赖都是显式参数，没有"魔法"。

---

## 2. build_runtime()：核心装配函数

### 项目代码详解

这是 OpenHarness 中最关键的函数之一，按 10 个步骤组装整个运行时：

```python
async def build_runtime(
    *,
    prompt: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    api_key: str | None = None,
    api_format: str | None = None,
    permission_prompt: PermissionPrompt | None = None,
    ask_user_prompt: AskUserPrompt | None = None,
    # ... 更多参数
) -> RuntimeBundle:
```

**步骤 1：加载配置**

```python
settings_overrides = {"model": model, "max_turns": max_turns, ...}
settings = load_settings().merge_cli_overrides(**settings_overrides)
```

**步骤 2：加载插件**

```python
plugins = load_plugins(settings, cwd, extra_roots=normalized_plugin_roots)
```

**步骤 3：解析 API 客户端**

```python
if api_client:
    resolved_api_client = api_client
else:
    resolved_api_client = _resolve_api_client_from_settings(settings)
```

`_resolve_api_client_from_settings()` 根据 `api_format` 和 `provider` 选择合适的客户端实现：

```python
def _resolve_api_client_from_settings(settings) -> SupportsStreamingMessages:
    if settings.api_format == "copilot":
        return CopilotClient(model=copilot_model)
    if settings.provider == "openai_codex":
        return CodexApiClient(auth_token=auth.value, ...)
    if settings.provider == "anthropic_claude":
        return AnthropicApiClient(auth_token=..., claude_oauth=True, ...)
    if settings.api_format == "openai":
        return OpenAICompatibleClient(api_key=auth.value, ...)
    return AnthropicApiClient(api_key=auth.value, ...)
```

**步骤 4：创建 MCP 管理器**

```python
mcp_manager = McpClientManager(load_mcp_server_configs(settings, plugins))
await mcp_manager.connect_all()
```

**步骤 5：创建工具注册表**

```python
tool_registry = create_default_tool_registry(mcp_manager)
```

**步骤 6：检测提供者**

```python
provider = detect_provider(settings)
```

**步骤 7：构建 Hook 执行器**

```python
hook_reloader = HookReloader(get_config_file_path())
hook_executor = HookExecutor(
    hook_reloader.current_registry(),
    HookExecutionContext(cwd=Path(cwd).resolve(), api_client=resolved_api_client, ...),
)
```

**步骤 8：组装系统提示词**

```python
system_prompt_text = build_runtime_system_prompt(
    settings, cwd=cwd, latest_user_prompt=prompt,
    extra_skill_dirs=normalized_skill_dirs,
    extra_plugin_roots=normalized_plugin_roots,
)
```

**步骤 9：构造查询引擎**

```python
engine = QueryEngine(
    api_client=resolved_api_client,
    tool_registry=tool_registry,
    permission_checker=PermissionChecker(settings.permission),
    cwd=cwd,
    model=settings.model,
    system_prompt=system_prompt_text,
    max_tokens=settings.max_tokens,
    context_window_tokens=settings.context_window_tokens or settings.memory.context_window_tokens,
    auto_compact_threshold_tokens=settings.auto_compact_threshold_tokens or ...,
    max_turns=engine_max_turns,
    permission_prompt=permission_prompt,
    ask_user_prompt=ask_user_prompt,
    hook_executor=hook_executor,
    tool_metadata={...},
    verbose=settings.verbose,
)
```

**步骤 10：创建 AppState 和 AppStateStore**

```python
app_state = AppStateStore(
    AppState(
        model=settings.model,
        permission_mode=settings.permission.mode.value,
        theme=settings.theme,
        cwd=cwd,
        provider=provider.name,
        auth_status=auth_status(settings),
        # ... 更多字段
    )
)
```

最终返回完整的 `RuntimeBundle`：

```python
return RuntimeBundle(
    api_client=resolved_api_client,
    cwd=cwd,
    mcp_manager=mcp_manager,
    tool_registry=tool_registry,
    app_state=app_state,
    hook_executor=hook_executor,
    engine=engine,
    commands=create_default_command_registry(...),
    external_api_client=api_client is not None,
    session_id=session_id,
    settings_overrides=settings_overrides,
    # ...
)
```

> **Java 对比**：`build_runtime()` 等价于 Spring 的 `@Configuration` 类中一系列 `@Bean` 方法。但 Spring 是自动装配（autowiring），而这里是手动装配。手动装配的优势在于：每个依赖关系都是显式的，不存在循环依赖的隐患，也不需要 `@Lazy` 注解来打破循环。

---

## 3. Callable 类型提示：回调注入

```python
PermissionPrompt = Callable[[str, str], Awaitable[bool]]
AskUserPrompt = Callable[[str], Awaitable[str]]
SystemPrinter = Callable[[str], Awaitable[None]]
StreamRenderer = Callable[[StreamEvent], Awaitable[None]]
ClearHandler = Callable[[], Awaitable[None]]
```

这些类型别名定义了 UI 层注入到运行时的回调函数签名。`build_runtime()` 接受这些回调作为可选参数，具体的 UI 实现负责提供具体函数。

> **Java 对比**：Python 的 `Callable[[str, str], Awaitable[bool]]` 对应 Java 的 `@FunctionalInterface`：

```java
@FunctionalInterface
interface PermissionPrompt {
    CompletableFuture<Boolean> apply(String toolName, String description);
}
```

Python 的类型别名更简洁——不需要定义接口，只需描述函数签名。Java 的 `@FunctionalInterface` 则需要完整的类定义。

---

## 4. UI 三模式

### React TUI 模式

前后端分离架构——Python 后端通过 `BackendEvent` 推送事件，React 前端通过 `FrontendRequest` 发送请求：

```python
# ui/protocol.py
class FrontendRequest(BaseModel):
    type: Literal[
        "submit_line", "permission_response", "question_response",
        "list_sessions", "select_command", "apply_select_command", "shutdown",
    ]
    line: str | None = None
    command: str | None = None
    value: str | None = None
    # ...

class BackendEvent(BaseModel):
    type: Literal[
        "ready", "state_snapshot", "tasks_snapshot", "transcript_item",
        "compact_progress", "assistant_delta", "assistant_complete",
        "line_complete", "tool_started", "tool_completed", "error", "shutdown",
    ]
    # ... 丰富的可选字段

    @classmethod
    def ready(cls, state: AppState, tasks: list[TaskRecord], commands: list[str]) -> "BackendEvent": ...

    @classmethod
    def state_snapshot(cls, state: AppState) -> "BackendEvent": ...
```

### Textual TUI 模式

纯 Python 终端 UI，使用 Textual 框架。直接调用 `RuntimeBundle` 的方法，无需前后端通信。

### 后端宿主模式

无 UI 的纯后端模式，用于嵌入式场景（如 CI/CD 管道）。

> **Java 对比**：三种 UI 模式对应 Java 应用的多种前端实现——Swing/JavaFX（桌面）、Spring MVC（Web）、纯后端服务。Python 的 `Callable` 类型注入比 Java 的接口注入更轻量——不需要为每种 UI 模式实现完整的接口类，只需传入符合签名的函数即可。

---

## 5. 主题与快捷键加载

### 主题加载

```python
# themes/loader.py (简化)
def load_theme(theme_name: str) -> dict[str, str]:
    """Load a theme by name from the themes directory."""
    # 从内置主题或用户自定义主题加载
```

### 快捷键加载

```python
# keybindings/loader.py (简化)
def load_keybindings() -> dict[str, str]:
    """Load and resolve keybindings from config."""
```

> **Java 对比**：主题/快捷键加载类似于 Java 应用的 ResourceBundle + Properties 加载。Python 的 `pathlib.Path` + `json.loads()` 比 Java 的 `ResourceBundle.getBundle()` 更灵活——可以轻松支持用户自定义路径。

---

## 6. sync_app_state：状态同步

```python
def sync_app_state(bundle: RuntimeBundle) -> None:
    """Refresh UI state from current settings and dynamic keybindings."""
    settings = bundle.current_settings()
    if bundle.enforce_max_turns:
        bundle.engine.set_max_turns(settings.max_turns)
    provider = detect_provider(settings)
    bundle.app_state.set(
        model=settings.model,
        permission_mode=settings.permission.mode.value,
        theme=settings.theme,
        cwd=bundle.cwd,
        provider=provider.name,
        # ... 更多字段
    )
```

`app_state.set(**updates)` 调用触发观察者通知，UI 组件自动刷新——这是经典的观察者模式在状态同步中的应用。

---

## 架构图

```
                    build_runtime()
                         |
         +-------+-------+-------+-------+
         |       |       |       |       |
         v       v       v       v       v
   +-------+ +-------+ +-------+ +-------+ +-------+
   |Settings| |Plugins| |API    | |MCP    | |Hooks  |
   |       | |       | |Client | |Manager| |       |
   +-------+ +-------+ +-------+ +-------+ +-------+
         |       |       |       |       |
         v       v       v       v       v
   +-------------------------------------------+
   |           RuntimeBundle                   |
   |  api_client | tool_registry | engine      |
   |  app_state  | hook_executor | commands    |
   +-------------------------------------------+
         |                    |
         v                    v
   +-----------+      +-----------+
   | React TUI |      |Textual TUI|
   | (FrontendR|      | (direct   |
   |  equest/  |      |  calls)   |
   |  BackendE |      |           |
   |  vent)    |      |           |
   +-----------+      +-----------+
         |
         v
   +-----------+
   |BackendHost|
   |(headless) |
   +-----------+
```

---

## 小结

| 组件 | 核心机制 | Java 等价物 |
|------|---------|------------|
| `RuntimeBundle` | 数据类容器 + 显式装配 | Spring ApplicationContext |
| `build_runtime()` | 10 步手动装配 | @Configuration + @Bean |
| `Callable` 类型提示 | 函数签名注入 | @FunctionalInterface |
| `FrontendRequest/BackendEvent` | Pydantic 消息模型 | DTO + Jackson |
| `AppStateStore.set()` | 观察者通知 | PropertyChangeSupport |
| `sync_app_state()` | 设置变更 -> 状态同步 | Spring Event |
| 三种 UI 模式 | 回调注入 | Strategy Pattern |

关键设计原则：
1. **显式装配**：`build_runtime()` 每个步骤都是透明、可追踪的
2. **回调注入**：通过 `Callable` 类型签名注入 UI 回调，避免 UI 依赖
3. **观察者驱动**：`AppStateStore` 的 `set()` 自动通知所有 UI 组件
4. **多模式兼容**：同一 `RuntimeBundle` 可驱动三种不同的 UI 前端
5. **设置覆盖**：CLI 参数覆盖配置文件，但不会写回磁盘——`settings_overrides` 保持运行时覆盖