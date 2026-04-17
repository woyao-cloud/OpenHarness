# Hooks 与 Commands 模块详细设计

> 涵盖文件: `hooks/events.py`, `hooks/types.py`, `hooks/schemas.py`, `hooks/loader.py`, `hooks/executor.py`, `hooks/hot_reload.py`, `commands/registry.py`, `commands/__init__.py`

---

## 1. 模块概述

Hooks 和 Commands 是 OpenHarness 运行时生命周期中两个核心扩展机制:

- **Hooks** 提供声明式事件拦截能力, 允许用户和插件在关键生命周期节点注入自定义逻辑. 最关键的事件是 `PRE_TOOL_USE`, 它可以在工具执行前阻断操作, 从而实现安全策略和合规检查.
- **Commands** 提供交互式斜杠命令 (`/command`) 机制, 用户可通过 TUI 直接操控会话状态、模型参数、权限模式、会话存储等运行时属性. 约 50 个内置命令覆盖会话管理、模型配置、权限控制、诊断调试等场景.

两者共同构成了 OpenHarness 的可编程控制面: Hooks 负责自动化的前置/后置拦截, Commands 负责人工交互式的即时操控.

---

## 2. 核心类/接口

### 2.1 HookEvent (hooks/events.py)

```python
class HookEvent(str, Enum):
    SESSION_START  = "session_start"
    SESSION_END    = "session_end"
    PRE_COMPACT    = "pre_compact"
    POST_COMPACT   = "post_compact"
    PRE_TOOL_USE   = "pre_tool_use"    # 最关键: 可阻断工具执行
    POST_TOOL_USE  = "post_tool_use"
```

继承 `str, Enum`, 使值可直接序列化为字符串, 方便从 settings JSON 中反序列化. 六个事件按功能分为三类:

| 类别 | 事件 | 典型用途 |
|------|------|----------|
| 会话生命周期 | `SESSION_START`, `SESSION_END` | 初始化环境、清理资源、通知外部系统 |
| 上下文压缩 | `PRE_COMPACT`, `POST_COMPACT` | 压缩前保存关键信息、压缩后验证完整性 |
| 工具执行拦截 | `PRE_TOOL_USE`, `POST_TOOL_USE` | 权限校验、审计日志、参数篡改、结果验证 |

**PRE_TOOL_USE 的重要性**: 此事件是唯一可阻断后续操作的钩子触发点. 若任何匹配的 Hook 返回 `blocked=True`, 则目标工具的执行将被中止, 这使得安全策略和合规规则可以在运行时强制执行.

### 2.2 HookDefinition 联合类型 (hooks/schemas.py)

四种 Hook 定义模式, 以 Pydantic `BaseModel` 建模并通过 `|` 运算符形成联合类型:

```python
HookDefinition = CommandHookDefinition | PromptHookDefinition | HttpHookDefinition | AgentHookDefinition
```

详细规格见第 3 节数据模型.

### 2.3 HookRegistry (hooks/loader.py)

```python
class HookRegistry:
    _hooks: dict[HookEvent, list[HookDefinition]]  # defaultdict(list)

    register(event, hook) -> None
    get(event) -> list[HookDefinition]       # 返回副本, 防止外部修改
    summary() -> str                          # 人类可读摘要
```

以事件类型为键的分组存储. `get()` 返回列表副本 (`list(self._hooks.get(event, []))`), 遵循不可变原则, 防止调用方意外修改内部状态.

### 2.4 HookExecutor (hooks/executor.py)

```python
class HookExecutor:
    __init__(registry: HookRegistry, context: HookExecutionContext)
    update_registry(registry) -> None
    update_context(*, api_client, default_model) -> None
    execute(event, payload) -> Awaitable[AggregatedHookResult]
```

执行引擎, 持有当前注册表和执行上下文, 支持运行时热替换注册表 (配合 `HookReloader`). 核心方法 `execute()` 遍历匹配的 Hook, 按类型分派执行, 聚合结果.

### 2.5 HookExecutionContext (hooks/executor.py)

```python
@dataclass
class HookExecutionContext:
    cwd: Path
    api_client: SupportsStreamingMessages
    default_model: str
```

执行上下文, 提供 Prompt/Agent 类型 Hook 所需的 API 客户端和默认模型信息.

### 2.6 HookReloader (hooks/hot_reload.py)

```python
class HookReloader:
    __init__(settings_path: Path)
    current_registry() -> HookRegistry   # 按需重载
```

监控 settings 文件的 `mtime_ns`, 当检测到变更时自动重新加载 Hook 注册表.

### 2.7 CommandResult (commands/registry.py)

```python
@dataclass
class CommandResult:
    message: str | None = None
    should_exit: bool = False
    clear_screen: bool = False
    replay_messages: list | None = None
    continue_pending: bool = False
    continue_turns: int | None = None
    refresh_runtime: bool = False
    submit_prompt: str | None = None
    submit_model: str | None = None
```

命令执行结果, 携带控制信号指导 TUI 和引擎的后续行为.

### 2.8 CommandContext (commands/registry.py)

```python
@dataclass
class CommandContext:
    engine: QueryEngine
    hooks_summary: str = ""
    mcp_summary: str = ""
    plugin_summary: str = ""
    cwd: str = "."
    tool_registry: ToolRegistry | None = None
    app_state: AppStateStore | None = None
    session_backend: SessionBackend = DEFAULT_SESSION_BACKEND
    session_id: str | None = None
    extra_skill_dirs: Iterable[str | Path] | None = None
    extra_plugin_roots: Iterable[str | Path] | None = None
```

命令处理器可用的完整上下文, 包含引擎、工具注册表、会话存储、应用状态等.

### 2.9 SlashCommand (commands/registry.py)

```python
@dataclass
class SlashCommand:
    name: str
    description: str
    handler: CommandHandler          # Callable[[str, CommandContext], Awaitable[CommandResult]]
    remote_invocable: bool = True
    remote_admin_opt_in: bool = False
```

### 2.10 CommandRegistry (commands/registry.py)

```python
class CommandRegistry:
    _commands: dict[str, SlashCommand]

    register(command: SlashCommand) -> None
    lookup(raw_input: str) -> tuple[SlashCommand, str] | None
    help_text() -> str
    list_commands() -> list[SlashCommand]
```

命令注册表. `lookup()` 解析 `/name args` 格式的原始输入, 返回匹配的命令和参数字符串.

---

## 3. 数据模型

### 3.1 Hook 定义 Schema (hooks/schemas.py)

四种 Hook 定义均继承 `pydantic.BaseModel`, 具备 JSON 序列化/反序列化和字段校验能力.

#### CommandHookDefinition -- Shell 子进程执行

| 字段 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `type` | `Literal["command"]` | `"command"` | -- | 类型判别器 |
| `command` | `str` | -- | 必填 | Shell 命令模板, 支持 `$ARGUMENTS` 占位符 |
| `timeout_seconds` | `int` | `30` | `ge=1, le=600` | 子进程超时 (秒) |
| `matcher` | `str \| None` | `None` | -- | Glob 模式匹配 tool_name/prompt/event |
| `block_on_failure` | `bool` | `False` | -- | 失败时是否阻断事件流 |

#### PromptHookDefinition -- 短 API 验证

| 字段 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `type` | `Literal["prompt"]` | `"prompt"` | -- | 类型判别器 |
| `prompt` | `str` | -- | 必填 | 发送给模型的验证提示 |
| `model` | `str \| None` | `None` | -- | 指定模型, 缺省使用 `default_model` |
| `timeout_seconds` | `int` | `30` | `ge=1, le=600` | API 超时 (秒) |
| `matcher` | `str \| None` | `None` | -- | Glob 匹配器 |
| `block_on_failure` | `bool` | `True` | -- | 默认阻断: 验证类 Hook 通常要求严格 |

#### HttpHookDefinition -- HTTP POST 回调

| 字段 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `type` | `Literal["http"]` | `"http"` | -- | 类型判别器 |
| `url` | `str` | -- | 必填 | 回调 URL |
| `headers` | `dict[str, str]` | `{}` | -- | 自定义 HTTP 请求头 |
| `timeout_seconds` | `int` | `30` | `ge=1, le=600` | HTTP 超时 (秒) |
| `matcher` | `str \| None` | `None` | -- | Glob 匹配器 |
| `block_on_failure` | `bool` | `False` | -- | 默认不阻断: 通知类 Hook 容错优先 |

#### AgentHookDefinition -- 深度 API 验证

| 字段 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `type` | `Literal["agent"]` | `"agent"` | -- | 类型判别器 |
| `prompt` | `str` | -- | 必填 | 深度验证提示 |
| `model` | `str \| None` | `None` | -- | 指定模型 |
| `timeout_seconds` | `int` | `60` | `ge=1, le=1200` | 更长超时: 深度推理需要更多时间 |
| `matcher` | `str \| None` | `None` | -- | Glob 匹配器 |
| `block_on_failure` | `bool` | `True` | -- | 默认阻断: 深度验证类 Hook 要求严格 |

**block_on_failure 差异设计**:

| Hook 类型 | 默认 block_on_failure | 设计理由 |
|-----------|----------------------|----------|
| Command | `False` | Shell 命令可能因环境问题失败, 不应因此阻断工作流 |
| Prompt | `True` | 验证类 Hook 意味着安全/合规要求, 未通过应阻断 |
| Http | `False` | 回调通知类, 对端不可达不应阻断主流程 |
| Agent | `True` | 深度验证类, 同 Prompt 但允许更长超时和更复杂推理 |

### 3.2 Hook 运行时结果 (hooks/types.py)

```python
@dataclass(frozen=True)
class HookResult:
    hook_type: str                    # "command" | "prompt" | "http" | "agent"
    success: bool                     # 执行是否成功
    output: str = ""                  # 标准输出/响应文本
    blocked: bool = False             # 是否阻断事件流
    reason: str = ""                 # 阻断原因
    metadata: dict[str, Any] = field(default_factory=dict)  # 附加元数据 (returncode, status_code 等)

@dataclass(frozen=True)
class AggregatedHookResult:
    results: list[HookResult] = field(default_factory=list)

    @property
    blocked(self) -> bool:
        """任一 Hook 阻断 → 整体阻断"""
        return any(result.blocked for result in self.results)

    @property
    reason(self) -> str:
        """返回第一个阻断原因"""
        ...
```

两个数据类均为 `frozen=True`, 遵循不可变原则. 聚合策略为 **短路阻断**: 只要任何一个 Hook 返回 `blocked=True`, 整个事件即被阻断, 使用第一个阻断原因.

### 3.3 PluginCommandDefinition (plugins/types.py)

```python
@dataclass(frozen=True)
class PluginCommandDefinition:
    name: str
    description: str
    content: str                      # 命令的 prompt 内容
    path: str | None = None
    source: str = "plugin"
    base_dir: str | None = None       # Skill 基目录
    argument_hint: str | None = None
    when_to_use: str | None = None
    version: str | None = None
    model: str | None = None          # 指定 Skill 使用的模型
    effort: str | int | None = None
    disable_model_invocation: bool = False  # 为 True 时只渲染 prompt 不提交模型
    user_invocable: bool = True
    is_skill: bool = False
    display_name: str | None = None
```

---

## 4. 关键算法

### 4.1 Hook 匹配算法 (_matches_hook)

```
输入: hook (HookDefinition), payload (dict)
输出: bool

1. 获取 hook.matcher 属性
2. 若 matcher 为 None 或空字符串 → 返回 True (无条件匹配)
3. 从 payload 中按优先级选取匹配目标:
   a. payload["tool_name"]   (PRE/POST_TOOL_USE 事件)
   b. payload["prompt"]      (包含 prompt 字段的场景)
   c. payload["event"]       (通用事件名)
   d. 空字符串               (兜底)
4. 使用 fnmatch.fnmatch(subject, matcher) 进行 Glob 模式匹配
5. 返回匹配结果
```

Glob 模式支持 `*` (匹配任意字符)、`?` (匹配单个字符)、`[seq]` (字符集) 等 fnmatch 语法. 典型用法: `matcher: "Bash"` 仅拦截 Bash 工具, `matcher: "*"` 拦截所有工具.

### 4.2 $ARGUMENTS 模板注入 (_inject_arguments)

```
输入: template (str), payload (dict), shell_escape (bool)
输出: str

1. 将 payload 序列化为 JSON (ensure_ascii=True)
2. 若 shell_escape 为 True:
   a. 对序列化结果调用 shlex.quote() 进行 Shell 转义
3. 将 template 中所有 "$ARGUMENTS" 替换为序列化结果
4. 返回替换后的字符串
```

**安全设计**: Command 类型 Hook 的 `shell_escape=True`, 确保注入的 JSON 字符串不会因特殊字符 (空格、引号、`$` 等) 导致 Shell 注入或解析错误. Prompt/Agent 类型 Hook 的 `shell_escape=False`, 因为模板直接作为 API 文本输入, 不经过 Shell 解析.

### 4.3 Hook 执行调度 (HookExecutor.execute)

```
输入: event (HookEvent), payload (dict)
输出: AggregatedHookResult

1. results = []
2. 对 registry.get(event) 中的每个 hook:
   a. 调用 _matches_hook(hook, payload)
   b. 若不匹配 → 跳过
   c. 根据 hook 类型分派:
      - CommandHookDefinition → _run_command_hook()
      - HttpHookDefinition    → _run_http_hook()
      - PromptHookDefinition  → _run_prompt_like_hook(agent_mode=False)
      - AgentHookDefinition   → _run_prompt_like_hook(agent_mode=True)
   d. 将结果追加到 results
3. 返回 AggregatedHookResult(results=results)
```

**顺序执行**: Hook 按注册顺序逐一执行 (非并行), 这保证了:
- 早期 Hook 的阻断可以阻止后续 Hook 执行 (当前实现不提前退出, 但 `blocked` 属性在聚合时生效)
- Hook 之间的副作用具有确定性顺序

### 4.4 Command Hook 执行 (_run_command_hook)

```
输入: hook, event, payload
输出: HookResult

1. 调用 _inject_arguments(hook.command, payload, shell_escape=True)
2. 调用 create_shell_subprocess(command, cwd, stdout=PIPE, stderr=PIPE,
      env={**os.environ,
           "OPENHARNESS_HOOK_EVENT": event.value,
           "OPENHARNESS_HOOK_PAYLOAD": json.dumps(payload)})
3. 若抛出 SandboxUnavailableError:
   → 返回 HookResult(success=False, blocked=hook.block_on_failure, reason=...)
4. 等待子进程完成 (timeout=hook.timeout_seconds):
   a. 超时 → kill 进程, 返回 HookResult(success=False, blocked=hook.block_on_failure)
   b. 完成 → 合并 stdout + stderr, 根据 returncode 判断成功
5. 返回 HookResult(success=(returncode==0),
                   blocked=(hook.block_on_failure and not success),
                   metadata={"returncode": returncode})
```

**环境变量注入**: `OPENHARNESS_HOOK_EVENT` 和 `OPENHARNESS_HOOK_PAYLOAD` 允许子进程获取完整的事件上下文, 无需解析命令行参数.

### 4.5 Prompt/Agent Hook 执行 (_run_prompt_like_hook)

```
输入: hook, event, payload, agent_mode (bool)
输出: HookResult

1. 调用 _inject_arguments(hook.prompt, payload, shell_escape=False)
2. 构建 system_prompt:
   基础: "You are validating whether a hook condition passes in OpenHarness.
           Return strict JSON: {\"ok\": true} or {\"ok\": false, \"reason\": \"...\"}."
   若 agent_mode: 追加 "Be more thorough and reason over the payload before deciding."
3. 构建 ApiMessageRequest(model=hook.model or default_model, messages=[用户提示], system_prompt, max_tokens=512)
4. 流式调用 api_client.stream_message(request):
   a. 收集文本片段
   b. 捕获 ApiMessageCompleteEvent 作为最终文本
5. 调用 _parse_hook_json(text) 解析响应
6. 若 ok=true → HookResult(success=True)
   若 ok=false → HookResult(success=False, blocked=hook.block_on_failure, reason=...)
```

**Agent 模式差异**: Agent Hook 使用更长超时 (60s vs 30s)、更宽松的上限 (1200s vs 600s), 并在 system prompt 中追加更深层推理指令, 适合需要多步分析的复杂验证场景.

### 4.6 Hook JSON 解析 (_parse_hook_json)

```
输入: text (str)
输出: dict ({"ok": bool, "reason": str} | {"ok": bool})

1. 尝试 json.loads(text):
   若结果为 dict 且含 "ok" (bool 类型) → 返回解析结果
2. 若 JSON 解析失败:
   a. 检查 text 是否为简单确认词: "ok", "true", "yes" → {"ok": True}
   b. 否则 → {"ok": False, "reason": text.strip() or "hook returned invalid JSON"}
```

容错设计: 即使模型返回非严格 JSON (如纯文本 "ok" 或 "yes"), 仍可正确解析为通过. 未通过时以原始文本作为 reason, 保证阻断原因的可见性.

### 4.7 Hook 热重载 (HookReloader.current_registry)

```
输入: 无 (内部状态: _settings_path, _last_mtime_ns, _registry)
输出: HookRegistry

1. 调用 _settings_path.stat()
2. 若 FileNotFoundError → 返回空 HookRegistry, 重置 _last_mtime_ns=-1
3. 若 stat.st_mtime_ns != _last_mtime_ns:
   a. 更新 _last_mtime_ns
   b. 调用 load_settings(_settings_path) 加载最新设置
   c. 调用 load_hook_registry(settings) 构建新注册表
   d. 更新 _registry
4. 返回 _registry
```

**最佳努力 (Best-effort)**: 文件不存在时返回空注册表面非抛异常, 保证运行时稳定性. 仅在文件实际变更时触发重载, 避免不必要的 I/O.

### 4.8 Hook 注册表加载 (load_hook_registry)

```
输入: settings (Settings), plugins (list[LoadedPlugin] | None)
输出: HookRegistry

1. 创建空 HookRegistry
2. 遍历 settings.hooks:
   a. 尝试 HookEvent(raw_event) 解析事件名
   b. 若 ValueError → 跳过 (容错处理未知事件名)
   c. 对每个 hook 定义: registry.register(event, hook)
3. 遍历 plugins (仅 enabled=True):
   a. 同上流程注册插件贡献的 Hook
4. 返回 registry
```

**合并策略**: Settings 和 Plugin 的 Hook 共存于同一注册表. 若同一事件有多个 Hook, 按加载顺序 (settings 先, plugins 后) 依次注册和执行.

### 4.9 Plugin 命令 Prompt 渲染 (_render_plugin_command_prompt)

```
输入: command (PluginCommandDefinition), args (str), session_id (str | None)
输出: str

1. prompt = command.content
2. 若 command.is_skill 且 command.base_dir 存在:
   prompt = "Base directory for this skill: {base_dir}\n\n{prompt}"
3. 替换 "${ARGUMENTS}" 和 "$ARGUMENTS" 为 args
4. 若 session_id 存在: 替换 "${CLAUDE_SESSION_ID}" 为 session_id
5. 若 args 非空且模板不含 $ARGUMENTS 占位符:
   prompt += "\n\nArguments: {args}"
6. 返回 prompt
```

### 4.10 Command 查找 (CommandRegistry.lookup)

```
输入: raw_input (str)
输出: tuple[SlashCommand, str] | None

1. 若 raw_input 不以 "/" 开头 → 返回 None
2. 解析: name = "/" 后第一个空格前的子串, args = 空格后的剩余部分
3. 在 _commands 中查找 name
4. 若未找到 → 返回 None
5. 返回 (command, args.strip())
```

---

## 5. 接口规范

### 5.1 Hooks 模块公共接口

| 组件 | 来源 | 接口签名 | 说明 |
|------|------|----------|------|
| `HookEvent` | events.py | `str, Enum` | 事件枚举, 6 个成员 |
| `HookResult` | types.py | `@dataclass(frozen=True)` | 单个 Hook 执行结果 |
| `AggregatedHookResult` | types.py | `@dataclass(frozen=True)` | 聚合结果, `.blocked` / `.reason` 属性 |
| `HookDefinition` | schemas.py | `TypeAlias` | 四种定义的联合类型 |
| `CommandHookDefinition` | schemas.py | `BaseModel` | Shell 命令 Hook |
| `PromptHookDefinition` | schemas.py | `BaseModel` | 短 API 验证 Hook |
| `HttpHookDefinition` | schemas.py | `BaseModel` | HTTP POST 回调 Hook |
| `AgentHookDefinition` | schemas.py | `BaseModel` | 深度 API 验证 Hook |
| `HookRegistry` | loader.py | `.register()`, `.get()`, `.summary()` | Hook 注册表 |
| `load_hook_registry` | loader.py | `(settings, plugins=None) -> HookRegistry` | 从设置和插件加载注册表 |
| `HookExecutor` | executor.py | `.execute(event, payload) -> AggregatedHookResult` | 执行引擎 |
| `HookExecutionContext` | executor.py | `@dataclass` | 执行上下文 |
| `HookReloader` | hot_reload.py | `.current_registry() -> HookRegistry` | 热重载器 |

### 5.2 Commands 模块公共接口

| 组件 | 来源 | 接口签名 | 说明 |
|------|------|----------|------|
| `CommandResult` | registry.py | `@dataclass` | 命令执行结果, 9 个控制字段 |
| `CommandContext` | registry.py | `@dataclass` | 命令处理器上下文 |
| `SlashCommand` | registry.py | `@dataclass` | 命令定义, 含远程调用控制标志 |
| `CommandRegistry` | registry.py | `.register()`, `.lookup()`, `.help_text()`, `.list_commands()` | 命令注册表 |
| `CommandHandler` | registry.py | `Callable[[str, CommandContext], Awaitable[CommandResult]]` | 命令处理器类型别名 |
| `create_default_command_registry` | registry.py | `(plugin_commands=None) -> CommandRegistry` | 创建内置命令注册表 |

### 5.3 CommandResult 控制字段语义

| 字段 | 类型 | 说明 | 典型使用场景 |
|------|------|------|-------------|
| `message` | `str \| None` | 显示给用户的文本 | 所有命令 |
| `should_exit` | `bool` | 请求退出会话 | `/exit` |
| `clear_screen` | `bool` | 清除 TUI 屏幕 | `/clear` |
| `replay_messages` | `list \| None` | 要回放的消息列表 | `/resume` |
| `continue_pending` | `bool` | 继续挂起的工具循环 | `/continue` |
| `continue_turns` | `int \| None` | 继续的轮次限制 | `/continue N` |
| `refresh_runtime` | `bool` | 信号: 重建 RuntimeBundle | `/permissions`, `/provider`, `/model`, `/plan` |
| `submit_prompt` | `str \| None` | 提交给模型的 prompt | Plugin Skill 命令 |
| `submit_model` | `str \| None` | 指定提交使用的模型 | Plugin Skill 命令 |

### 5.4 SlashCommand 远程调用控制

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `remote_invocable` | `bool` | `True` | 是否可被远程会话调用 |
| `remote_admin_opt_in` | `bool` | `False` | 远程调用是否需要管理员确认 |

安全敏感命令 (如 `/permissions`, `/plan`) 设置 `remote_invocable=False`, 防止远程会话绕过权限控制.

---

## 6. 错误处理

### 6.1 Hooks 错误处理策略

| 错误场景 | 处理方式 | 阻断行为 |
|----------|----------|----------|
| Sandbox 不可用 (`SandboxUnavailableError`) | 返回 `HookResult(success=False)`, 原因记录异常信息 | 取决于 `block_on_failure` |
| Command Hook 子进程超时 | `process.kill()` + `process.wait()`, 返回超时结果 | 取决于 `block_on_failure` |
| Command Hook 非零退出码 | `success=False`, reason 包含退出码 | `block_on_failure and not success` |
| HTTP Hook 请求异常 | 捕获所有 `Exception`, 返回失败结果 | 取决于 `block_on_failure` |
| HTTP Hook 非 2xx 响应 | `success=False`, reason 包含状态码 | `block_on_failure and not success` |
| Prompt/Agent Hook JSON 解析失败 | 降级为文本匹配 ("ok"/"true"/"yes") 或标记失败 | 取决于 `block_on_failure` |
| Settings 中未知事件名 | `load_hook_registry` 中 `ValueError` 被捕获, 跳过该事件 | 不影响其他 Hook |
| Settings 文件不存在 | `HookReloader` 返回空注册表 | 不阻断, 无 Hook 执行 |
| Settings 文件格式错误 | 由 `load_settings()` 层处理, 不在 Hook 层捕获 | 取决于 settings 加载逻辑 |

**核心原则**: Hook 失败不应导致运行时崩溃. 所有异常路径均返回结构化的 `HookResult`, 由 `block_on_failure` 决定是否升级为事件阻断.

### 6.2 Commands 错误处理策略

| 错误场景 | 处理方式 | 示例命令 |
|----------|----------|----------|
| 无效参数 | 返回用法提示 `CommandResult(message="Usage: ...")` | `/effort extreme` |
| 未知配置键 | 返回错误信息 `"Unknown config key: {key}"` | `/config set foo bar` |
| 值类型转换失败 | 抛出 `ValueError` 后返回友好消息 | `/passes abc` |
| 不存在的会话 | 返回 `"Session not found: {sid}"` | `/resume nonexistent` |
| Git 不可用 | 返回 `"git is not installed."` | `/diff`, `/branch` |
| Git 命令失败 | 返回 stderr 或默认错误消息 | `/commit` (无变更) |
| 剪贴板不可用 | 降级写入文件, 返回文件路径 | `/copy` |
| 主题/样式不存在 | 返回可用列表 | `/theme unknown` |
| 权限模型不允许 | 返回允许模型列表 | `/model disallowed-model` |
| 插件未找到 | 返回 `"Plugin not found"` | `/plugin uninstall x` |
| Memory 条目不存在 | 返回 `"Memory entry not found"` | `/memory remove x` |

**核心原则**: 命令永远返回 `CommandResult`, 绝不向 TUI 抛出未捕获异常. 用户看到的是友好错误消息而非堆栈跟踪.

---

## 7. 配置项

### 7.1 Hooks 相关配置 (settings.json)

```json
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "audit-logger $ARGUMENTS",
        "timeout_seconds": 30,
        "matcher": "Bash",
        "block_on_failure": false
      },
      {
        "type": "prompt",
        "prompt": "Is this tool call safe? $ARGUMENTS",
        "model": "claude-haiku-4-5",
        "block_on_failure": true
      },
      {
        "type": "http",
        "url": "https://hooks.example.com/tool-use",
        "headers": {"X-Auth-Token": "secret"},
        "block_on_failure": false
      },
      {
        "type": "agent",
        "prompt": "Analyze whether this operation complies with security policy. $ARGUMENTS",
        "timeout_seconds": 60,
        "block_on_failure": true
      }
    ],
    "session_start": [...],
    "session_end": [...],
    "pre_compact": [...],
    "post_compact": [...],
    "post_tool_use": [...]
  }
}
```

### 7.2 Hook 热重载配置

| 配置 | 说明 |
|------|------|
| `settings_path` | `HookReloader` 监控的文件路径, 通常为 `~/.openharness/settings.json` |
| 检测机制 | 比较 `stat().st_mtime_ns`, 文件修改时自动重载 |
| 重载范围 | 仅重载 Hook 定义, 不影响正在执行的 Hook |

### 7.3 Plugin 贡献 Hook

插件通过 `LoadedPlugin.hooks` 字典贡献 Hook, 格式与 `settings.hooks` 相同. 仅 `enabled=True` 的插件 Hook 被加载. 合并顺序: settings Hook 先注册, 插件 Hook 后注册.

### 7.4 命令无持久化配置

命令本身不使用独立配置文件. 命令的副作用 (如修改 `effort`, `model`, `permissions`) 通过 `save_settings(settings)` 持久化到 settings.json, 命令注册表本身是运行时构建的.

---

## 8. 与其它模块的交互

### 8.1 Hooks 与 Settings 模块

```
settings.json ──(load_settings)──→ Settings.hooks
                                        │
                                  (load_hook_registry)
                                        │
                                        ▼
                                   HookRegistry
                                        │
                              (HookReloader 监控 mtime_ns)
                                        │
                              (文件变更时重新调用 load_settings + load_hook_registry)
```

- **读取**: `load_hook_registry` 从 `Settings.hooks` 字典读取 Hook 定义
- **写入**: Hooks 模块本身不写 settings; 修改 Hook 配置通过 `/config set` 或手动编辑 settings.json 完成
- **热重载**: `HookReloader` 监控 settings 文件修改时间, 自动重建注册表

### 8.2 Hooks 与 Plugin 模块

```
Plugin Loader ──(load_plugins)──→ list[LoadedPlugin]
                                        │
                                  每个 LoadedPlugin.hooks
                                        │
                                  (load_hook_registry 合并)
                                        ▼
                                   HookRegistry
```

- 插件通过 `LoadedPlugin.hooks` 字典贡献 Hook 定义 (格式同 settings)
- 仅 `enabled=True` 的插件 Hook 被纳入注册表
- 插件 Hook 和 settings Hook 共存, 按 settings → plugins 顺序注册

### 8.3 Hooks 与 Sandbox 模块

```
HookExecutor._run_command_hook()
    │
    ├── 正常路径: create_shell_subprocess(command, ...) → 子进程执行
    │
    └── 异常路径: SandboxUnavailableError → HookResult(success=False, blocked=hook.block_on_failure)
```

- Command Hook 依赖 `create_shell_subprocess` 在沙箱中执行 Shell 命令
- 沙箱不可用时优雅降级, 根据 `block_on_failure` 决定是否阻断

### 8.4 Hooks 与 API Client 模块

```
HookExecutor._run_prompt_like_hook()
    │
    └── HookExecutionContext.api_client (SupportsStreamingMessages)
            │
            ├── stream_message(ApiMessageRequest) → 流式响应
            │
            └── 解析 ApiMessageCompleteEvent 获取最终文本
```

- Prompt/Agent Hook 依赖 `api_client.stream_message()` 调用模型 API
- 使用固定 system prompt 引导模型返回结构化 JSON
- `max_tokens=512` 限制响应长度, 确保快速返回

### 8.5 Hooks 与 HTTP 客户端 (httpx)

```
HookExecutor._run_http_hook()
    │
    └── httpx.AsyncClient(timeout=hook.timeout_seconds)
            │
            └── POST {url, json={"event": ..., "payload": ...}, headers=hook.headers}
```

- Http Hook 使用 `httpx.AsyncClient` 发送异步 POST 请求
- 请求体为 `{"event": event.value, "payload": payload}` 结构
- 超时、异常、非 2xx 响应均转化为 `HookResult`

### 8.6 Commands 与 QueryEngine 模块

```
CommandContext.engine (QueryEngine)
    │
    ├── .messages           → 读取/加载/清空会话消息
    ├── .total_usage        → 获取 token 使用量
    ├── .model              → 当前模型
    ├── .system_prompt      → 当前系统提示
    ├── .max_turns          → 最大轮次
    ├── .set_model()        → 切换模型
    ├── .set_system_prompt() → 更新系统提示
    ├── .set_max_turns()    → 设置最大轮次
    ├── .set_permission_checker() → 更新权限检查器
    ├── .load_messages()    → 加载消息 (用于 /resume, /rewind)
    ├── .clear()            → 清空会话 (用于 /clear)
    └── .has_pending_continuation() → 检查挂起工具结果 (用于 /continue)
```

### 8.7 Commands 与 Settings 模块

```
Commands Handler ──(load_settings)──→ Settings
                        │
                   (修改 settings 字段)
                        │
                   (save_settings) ──→ settings.json
```

多数设置修改类命令 (如 `/fast`, `/effort`, `/model`) 遵循相同模式:
1. `load_settings()` 读取当前设置
2. 修改目标字段
3. `save_settings(settings)` 持久化
4. 同步更新 `app_state` (若存在)

### 8.8 Commands 与 AppState 模块

```
CommandContext.app_state (AppStateStore | None)
    │
    ├── .get() → 当前应用状态 (model, effort, theme 等)
    └── .set(**kwargs) → 更新应用状态 (触发 TUI 响应式更新)
```

`app_state` 是可选依赖 (TUI 环境中存在, 非 TUI 环境中为 `None`). 命令处理器始终检查 `app_state is not None` 后再调用.

### 8.9 Commands 与 Session Backend 模块

```
CommandContext.session_backend (SessionBackend)
    │
    ├── .load_latest(cwd)         → 加载最新会话
    ├── .load_by_id(cwd, sid)     → 按 ID 加载会话
    ├── .list_snapshots(cwd)      → 列出可用会话
    ├── .save_snapshot(...)       → 保存会话快照
    ├── .export_markdown(...)     → 导出 Markdown 转录
    └── .get_session_dir(cwd)     → 获取会话存储目录
```

用于 `/resume`, `/session`, `/export`, `/share`, `/tag` 等会话管理命令.

### 8.10 Commands 与 Plugin/Skill 模块

```
create_default_command_registry(plugin_commands)
    │
    ├── 内置命令: 约 50 个静态注册的 SlashCommand
    │
    └── 插件命令: 遍历 plugin_commands, 为每个 user_invocable 命令:
            │
            ├── 创建闭包处理器 (捕获 command 默认参数)
            ├── 若 command.is_skill: 前置 "Base directory: ..." 信息
            ├── 替换 $ARGUMENTS / ${ARGUMENTS} / ${CLAUDE_SESSION_ID}
            ├── 若 disable_model_invocation: CommandResult(message=prompt)
            └── 否则: CommandResult(submit_prompt=prompt, submit_model=command.model)
```

### 8.11 Commands 与 Task 模块

```
CommandContext → get_task_manager()
    │
    ├── .list_tasks()          → /tasks list
    ├── .create_shell_task()   → /tasks run
    ├── .stop_task()           → /tasks stop
    ├── .get_task()            → /tasks show
    ├── .update_task()         → /tasks update
    └── .read_task_output()    → /tasks output
```

### 8.12 Commands 与 Bridge 模块

```
get_bridge_manager()
    │
    ├── .list_sessions()    → /bridge list
    ├── .spawn(...)         → /bridge spawn
    ├── .read_output(sid)   → /bridge output
    └── .stop(sid)          → /bridge stop
```

### 8.13 CommandResult 与 TUI 的交互

```
CommandResult
    │
    ├── message           → TUI 显示文本
    ├── should_exit=True  → TUI 触发退出流程
    ├── clear_screen=True → TUI 清除屏幕
    ├── replay_messages   → TUI 回放消息 (恢复会话)
    ├── continue_pending  → TUI 继续工具循环
    ├── refresh_runtime=True → TUI 重建 RuntimeBundle (重新加载系统提示、工具权限等)
    └── submit_prompt     → TUI 将 prompt 提交给模型 (Skill 命令触发模型调用)
```

`refresh_runtime=True` 是关键的运行时重建信号, 用于以下命令:
- `/permissions` / `/plan` -- 权限模式变更需要重新生成权限检查器和系统提示
- `/model` / `/provider` -- 模型/提供商变更需要重建 API 客户端和运行时上下文

### 8.14 五种命令实现模式总结

| 模式 | 描述 | 代表命令 | 特征 |
|------|------|----------|------|
| **A. 只读查询** | 读取运行时状态, 返回信息 | `/status`, `/usage`, `/cost`, `/version`, `/doctor` | 无副作用, 不修改 settings |
| **B. 设置修改+持久化** | 修改 settings 并保存 | `/fast`, `/effort`, `/passes`, `/theme`, `/vim` | `save_settings()` + 可选 `app_state.set()` |
| **C. 设置修改+运行时重建** | 修改 settings + 触发 RuntimeBundle 重建 | `/permissions`, `/plan`, `/model`, `/provider` | 同 B + `refresh_runtime=True` |
| **D. 会话操作** | 操作会话消息/存储 | `/compact`, `/rewind`, `/resume`, `/export`, `/clear` | 通过 `engine.load_messages()` 或 `session_backend` 操作 |
| **E. 模型 Prompt 提交** | 构建 prompt 并提交给模型 | Plugin Skill 命令 | `CommandResult(submit_prompt=..., submit_model=...)` |

---

## 附录: 完整命令清单

约 50 个内置斜杠命令, 按功能域分组:

### 会话 (Session)
| 命令 | 描述 |
|------|------|
| `/help` | 显示可用命令 |
| `/exit` | 退出 OpenHarness |
| `/clear` | 清除对话历史 |
| `/status` | 显示会话状态 |
| `/resume` | 恢复已保存的会话 |
| `/session` | 检查会话存储 |
| `/export` | 导出当前转录 |
| `/share` | 创建可分享的转录快照 |
| `/rewind` | 移除最近的对话轮次 |
| `/continue` | 继续中断的工具循环 |

### 模型 (Model)
| 命令 | 描述 |
|------|------|
| `/model` | 显示或更新默认模型 |
| `/effort` | 显示或更新推理强度 (low/medium/high) |
| `/passes` | 显示或更新推理遍数 |
| `/turns` | 显示或更新最大轮次 |
| `/fast` | 显示或更新快速模式 |

### 提供商 (Provider)
| 命令 | 描述 |
|------|------|
| `/provider` | 显示或切换提供商配置 |
| `/login` | 显示认证状态或存储 API 密钥 |
| `/logout` | 清除存储的 API 密钥 |

### 权限 (Permissions)
| 命令 | 描述 |
|------|------|
| `/permissions` | 显示或更新权限模式 (remote_invocable=False, remote_admin_opt_in=True) |
| `/plan` | 切换 Plan 权限模式 (remote_invocable=False, remote_admin_opt_in=True) |
| `/config` | 显示或更新配置 |

### 对话 (Conversation)
| 命令 | 描述 |
|------|------|
| `/summary` | 总结对话历史 |
| `/compact` | 压缩旧对话历史 |
| `/copy` | 复制最新响应或指定文本 |
| `/cost` | 显示 token 使用量和估算成本 |
| `/usage` | 显示使用量和 token 估算 |

### 工具 (Tools)
| 命令 | 描述 |
|------|------|
| `/skills` | 列出或显示可用技能 |
| `/mcp` | 显示 MCP 状态或配置认证 |
| `/plugin` | 管理插件 (list/enable/disable/install/uninstall) |
| `/reload-plugins` | 重新加载插件发现 |
| `/hooks` | 显示已配置的 Hook |

### 项目 (Project)
| 命令 | 描述 |
|------|------|
| `/files` | 列出工作区文件 |
| `/memory` | 检查和管理项目记忆 |
| `/init` | 初始化项目 OpenHarness 文件 |
| `/issue` | 显示或更新项目 Issue 上下文 |
| `/pr_comments` | 显示或更新项目 PR 评论上下文 |

### Git
| 命令 | 描述 |
|------|------|
| `/diff` | 显示 git diff 输出 |
| `/branch` | 显示 git 分支信息 |
| `/commit` | 显示状态或创建 git 提交 |

### 任务 (Tasks)
| 命令 | 描述 |
|------|------|
| `/tasks` | 管理后台任务 |
| `/agents` | 列出或检查 Agent 和 Teammate 任务 |
| `/subagents` | 显示子 Agent 使用情况 (别名) |

### UI
| 命令 | 描述 |
|------|------|
| `/theme` | 列出/设置/预览 TUI 主题 |
| `/output-style` | 显示或更新输出样式 |
| `/keybindings` | 显示已解析的键绑定 |
| `/vim` | 显示或更新 Vim 模式 |
| `/voice` | 显示或更新语音模式 |

### 诊断 (Diagnostics)
| 命令 | 描述 |
|------|------|
| `/doctor` | 显示环境诊断 |
| `/privacy-settings` | 显示本地隐私和存储设置 |
| `/rate-limit-options` | 显示减少提供商速率压力的方法 |
| `/stats` | 显示会话统计 |
| `/version` | 显示安装版本 |
| `/upgrade` | 显示升级说明 |
| `/release-notes` | 显示发布说明 |
| `/feedback` | 保存反馈到本地日志 |
| `/onboarding` | 显示快速入门指南 |

### Bridge
| 命令 | 描述 |
|------|------|
| `/bridge` | 检查 Bridge 助手和生成 Bridge 会话 |

### 上下文
| 命令 | 描述 |
|------|------|
| `/context` | 显示当前运行时系统提示 |
| `/tag` | 创建会话命名快照 (别名, 委托给 /session tag) |