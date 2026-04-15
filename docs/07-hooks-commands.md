# Phase 7: Hook 系统与命令系统深度解析

> 涉及文件:
> - `hooks/events.py` (23行) — HookEvent 枚举
> - `hooks/types.py` (38行) — HookResult / AggregatedHookResult
> - `hooks/schemas.py` (59行) — 四种 Hook 定义 Schema
> - `hooks/loader.py` (61行) — HookRegistry + load_hook_registry()
> - `hooks/executor.py` (243行) — HookExecutor 执行引擎
> - `hooks/hot_reload.py` (32行) — 设置文件热重载
> - `hooks/__init__.py` (51行) — 延迟导入导出
> - `commands/registry.py` (1676行) — 命令注册表 + ~50 个命令处理器
> - `commands/__init__.py` (17行) — 命令模块导出

 Hook 系统 — 4 种 Hook 类型:
  - Command: Shell 子进程, 环境变量注入, block_on_failure=False
  - Prompt: 短 API 调用验证, 返回 JSON {"ok": true/false}, block_on_failure=True
  - Http: POST 回调, block_on_failure=False
  - Agent: 深度 API 验证, 更长超时 (60s), block_on_failure=True

  关键机制: PRE_TOOL_USE Hook 可以阻断工具执行, POST_TOOL_USE 用于日志/通知。Matcher 用 glob 模式按工具名过滤。HookReloader 支持运行时热重载。

  命令系统 — ~50 个斜杠命令, 5 种实现模式:
  - 只读查询 (/status, /usage)
  - 设置修改+持久化 (/fast, /effort)
  - 设置修改+运行时重建 (/permissions, /provider — 需要 refresh_runtime=True)
  - 会话操作 (/compact, /rewind, /resume)
  - 模型提示词提交 (插件 Skill 命令)

  CommandResult 的 refresh_runtime 标志是最重要的信号 — 它告诉 TUI 层重建整个 RuntimeBundle (API Client, HookExecutor 等)。
---

## 1. Hook 系统架构总览

```
配置 (settings.json / plugins)
  │
  │  load_hook_registry()
  ▼
HookRegistry                    ← 内存注册表: event → [HookDefinition, ...]
  │
  │  execute(event, payload)
  ▼
HookExecutor                    ← 执行引擎: 遍历匹配的 hook, 聚合结果
  ├── CommandHookExecutor       ← 执行 shell 命令
  ├── HttpHookExecutor           ← POST 到 HTTP 端点
  ├── PromptHookExecutor         ← 模型验证 (简短)
  └── AgentHookExecutor         ← 模型验证 (深度)
        │
        ▼
AggregatedHookResult            ← 聚合结果: blocked? reason?
```

---

## 2. HookEvent — 生命周期事件

```python
class HookEvent(str, Enum):
    SESSION_START = "session_start"    # 会话启动
    SESSION_END = "session_end"        # 会话结束
    PRE_COMPACT = "pre_compact"        # 压缩前
    POST_COMPACT = "post_compact"      # 压缩后
    PRE_TOOL_USE = "pre_tool_use"      # 工具执行前
    POST_TOOL_USE = "post_tool_use"    # 工具执行后
```

**关键事件**: `PRE_TOOL_USE` 是最核心的事件 — 它可以在工具执行前**阻断**操作, 实现安全守卫。

---

## 3. 四种 Hook 定义 Schema

### 3.1 CommandHook — Shell 命令钩子

```python
class CommandHookDefinition(BaseModel):
    type: Literal["command"] = "command"
    command: str                       # 要执行的 shell 命令
    timeout_seconds: int = 30           # 超时 (1-600s)
    matcher: str | None = None         # glob 匹配模式
    block_on_failure: bool = False     # 命令失败时是否阻断
```

**执行方式**: 启动子进程, 环境变量注入 `OPENHARNESS_HOOK_EVENT` 和 `OPENHARNESS_HOOK_PAYLOAD`。

**`$ARGUMENTS` 模板替换**: 命令字符串中的 `$ARGUMENTS` 会被替换为 JSON 序列化的 payload, 并做 shell 转义。

### 3.2 PromptHook — 模型验证 (轻量)

```python
class PromptHookDefinition(BaseModel):
    type: Literal["prompt"] = "prompt"
    prompt: str                        # 验证提示词
    model: str | None = None          # 指定模型 (默认用当前模型)
    timeout_seconds: int = 30
    matcher: str | None = None
    block_on_failure: bool = True      # 默认阻断 (模型说不通过就阻断)
```

**执行方式**: 向 API 发送简短验证请求, 期望返回 JSON `{"ok": true/false, "reason": "..."}`。

**System Prompt 固定**: "You are validating whether a hook condition passes in OpenHarness. Return strict JSON: {\"ok\": true} or {\"ok\": false, \"reason\": \"...\"}."

### 3.3 HttpHook — HTTP 回调

```python
class HttpHookDefinition(BaseModel):
    type: Literal["http"] = "http"
    url: str                           # POST 目标 URL
    headers: dict[str, str] = {}       # 自定义 Headers
    timeout_seconds: int = 30
    matcher: str | None = None
    block_on_failure: bool = False     # 默认不阻断
```

**执行方式**: POST `{"event": "...", "payload": {...}}` 到指定 URL, 根据 HTTP 状态码判断成功/失败。

### 3.4 AgentHook — 模型验证 (深度)

```python
class AgentHookDefinition(BaseModel):
    type: Literal["agent"] = "agent"
    prompt: str                        # 深度验证提示词
    model: str | None = None
    timeout_seconds: int = 60          # 更长超时 (1-1200s)
    matcher: str | None = None
    block_on_failure: bool = True      # 默认阻断
```

**与 PromptHook 的区别**: 超时更长 (60s vs 30s), system prompt 额外追加 "Be more thorough and reason over the payload before deciding.", `block_on_failure` 默认为 True。

### Schema 对比

| 方面 | Command | Prompt | Http | Agent |
|------|---------|--------|------|-------|
| 执行方式 | Shell 子进程 | API 调用 | HTTP POST | API 调用 (深度) |
| 默认超时 | 30s | 30s | 30s | 60s |
| 默认 block_on_failure | False | True | False | True |
| 最大超时 | 600s | 600s | 600s | 1200s |
| 用途 | 自动化脚本 | 快速验证 | 外部通知 | 深度审查 |

---

## 4. HookRegistry — Hook 注册与发现

```python
class HookRegistry:
    def __init__(self):
        self._hooks: dict[HookEvent, list[HookDefinition]] = defaultdict(list)

    def register(self, event: HookEvent, hook: HookDefinition) -> None:
        """注册一个 Hook 到指定事件"""

    def get(self, event: HookEvent) -> list[HookDefinition]:
        """获取某个事件的所有 Hook"""

    def summary(self) -> str:
        """人类可读的摘要"""
```

**加载来源** (双源头):

```python
def load_hook_registry(settings, plugins=None):
    registry = HookRegistry()
    # 1. 从 settings.hooks 加载用户配置的 Hook
    for raw_event, hooks in settings.hooks.items():
        event = HookEvent(raw_event)
        for hook in hooks:
            registry.register(event, hook)
    # 2. 从 plugin.hooks 加载插件提供的 Hook
    for plugin in plugins or []:
        for raw_event, hooks in plugin.hooks.items():
            event = HookEvent(raw_event)
            for hook in hooks:
                registry.register(event, hook)
    return registry
```

---

## 5. HookExecutor — 执行引擎

### 执行流程

```
execute(event, payload)
│
├── 遍历 registry.get(event) 中的每个 hook
│   ├── _matches_hook(hook, payload)?
│   │   ├── matcher 为 None → 匹配所有
│   │   └── matcher 为 glob → fnmatch(payload.tool_name/prompt/event, matcher)
│   │
│   └── 不匹配 → skip
│
├── 匹配时 → 按 hook 类型分发:
│   ├── CommandHookDefinition → _run_command_hook()
│   ├── HttpHookDefinition → _run_http_hook()
│   ├── PromptHookDefinition → _run_prompt_like_hook(agent_mode=False)
│   └── AgentHookDefinition → _run_prompt_like_hook(agent_mode=True)
│
└── 聚合所有结果 → AggregatedHookResult
    ├── blocked = any(result.blocked for result in results)
    └── reason = 第一个 blocked result 的 reason
```

### Matcher 机制

```python
def _matches_hook(hook, payload):
    matcher = hook.matcher
    if not matcher:
        return True  # 无 matcher → 匹配所有
    # 尝试从 payload 中提取匹配主题
    subject = str(
        payload.get("tool_name")      # PRE/POST_TOOL_USE: 工具名
        or payload.get("prompt")       # 其他: 提示词
        or payload.get("event")        # 回退: 事件名
        or ""
    )
    return fnmatch(subject, matcher)   # glob 模式匹配
```

**示例**: `matcher: "bash"` → 只匹配 bash 工具调用; `matcher: "*"` → 匹配所有。

### Command Hook 执行细节

```python
async def _run_command_hook(hook, event, payload):
    # 1. $ARGUMENTS 模板替换 + shell 转义
    command = _inject_arguments(hook.command, payload, shell_escape=True)
    
    # 2. 在沙箱子进程中执行
    process = await create_shell_subprocess(command, cwd=..., env={
        "OPENHARNESS_HOOK_EVENT": event.value,
        "OPENHARNESS_HOOK_PAYLOAD": json.dumps(payload),
    })
    
    # 3. 超时处理
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=hook.timeout_seconds)
    
    # 4. 结果判定
    success = process.returncode == 0
    blocked = hook.block_on_failure and not success
```

### Prompt/Agent Hook 执行细节

```python
async def _run_prompt_like_hook(hook, event, payload, agent_mode=False):
    # 1. 注入 payload 到 prompt
    prompt = _inject_arguments(hook.prompt, payload)  # 无 shell 转义
    
    # 2. 构造 system prompt
    prefix = "You are validating whether a hook condition passes..."
    if agent_mode:
        prefix += " Be more thorough and reason over the payload before deciding."
    
    # 3. 调用 API (复用 api_client)
    request = ApiMessageRequest(
        model=hook.model or default_model,
        messages=[ConversationMessage.from_user_text(prompt)],
        system_prompt=prefix,
        max_tokens=512,
    )
    
    # 4. 流式收集响应
    async for event_item in api_client.stream_message(request):
        ...
    
    # 5. 解析 JSON 响应
    parsed = _parse_hook_json(text)
    # 支持: {"ok": true/false, "reason": "..."}
    # 降级: "ok"/"true"/"yes" → {"ok": true}
```

### _inject_arguments — 模板注入

```python
def _inject_arguments(template, payload, *, shell_escape=False):
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)  # Command Hook 需要 shell 安全
    return template.replace("$ARGUMENTS", serialized)
```

---

## 6. HookResult 与 AggregatedHookResult

```python
@dataclass(frozen=True)
class HookResult:
    hook_type: str          # "command" / "prompt" / "http" / "agent"
    success: bool           # 执行是否成功
    output: str = ""        # 输出内容
    blocked: bool = False   # 是否阻断后续操作
    reason: str = ""        # 阻断原因
    metadata: dict = {}     # 额外数据 (如 returncode, status_code)

@dataclass(frozen=True)
class AggregatedHookResult:
    results: list[HookResult] = []
    
    @property
    def blocked(self) -> bool:
        """任一 hook 阻断 → 整体阻断"""
        return any(r.blocked for r in self.results)
    
    @property
    def reason(self) -> str:
        """第一个阻断结果的 reason"""
        for r in self.results:
            if r.blocked:
                return r.reason or r.output
        return ""
```

**阻断语义**: 任何一个 hook 返回 `blocked=True`, 整个事件被阻断。在 Agent Loop 中, `PRE_TOOL_USE` 的 `blocked=True` 会阻止工具执行。

---

## 7. HookReloader — 热重载

```python
class HookReloader:
    def __init__(self, settings_path: Path):
        self._settings_path = settings_path
        self._last_mtime_ns = -1         # 上次文件修改时间
        self._registry = HookRegistry()
    
    def current_registry(self) -> HookRegistry:
        stat = self._settings_path.stat()
        if stat.st_mtime_ns != self._last_mtime_ns:
            # 文件变了 → 重新加载
            self._last_mtime_ns = stat.st_mtime_ns
            self._registry = load_hook_registry(load_settings(self._settings_path))
        return self._registry
```

**用途**: 运行时修改 `settings.json` 中的 hook 配置, 无需重启会话即可生效。

---

## 8. Hook 在 Agent Loop 中的集成点

```python
# engine/query.py 中的工具执行流程:

async def _execute_tool_call(query_ctx, tool_use, ...):
    # === PRE_TOOL_USE Hook ===
    pre_result = await hook_executor.execute(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": tool_use.name, "tool_input": tool_use.input},
    )
    if pre_result.blocked:
        # Hook 阻断 → 返回 ToolResultBlock 说明被阻断
        return ToolResultBlock(tool_use_id=tool_use.id, content=pre_result.reason)
    
    # === 执行工具 ===
    result = await tool_registry.execute(tool_use.name, tool_use.input, context)
    
    # === POST_TOOL_USE Hook ===
    post_result = await hook_executor.execute(
        HookEvent.POST_TOOL_USE,
        {"tool_name": tool_use.name, "tool_output": result.output},
    )
    # POST Hook 通常不阻断, 但可以用于日志、通知等
```

---

## 9. 命令系统架构

```
用户输入: /compact 6
    │
    ▼
CommandRegistry.lookup("/compact 6")
    │
    ├── 解析: name="compact", args="6"
    └── 返回: (SlashCommand, "6")
    │
    ▼
SlashCommand.handler(args, context)
    │
    ▼
CommandResult(message="Compacted conversation from 42 to 6 messages.")
```

### 核心数据结构

```python
@dataclass
class CommandResult:
    message: str | None = None           # 命令输出文本
    should_exit: bool = False            # 是否退出会话
    clear_screen: bool = False            # 是否清屏
    replay_messages: list | None = None  # 重放消息 (用于 /resume)
    continue_pending: bool = False        # 继续挂起的工具循环
    continue_turns: int | None = None    # 继续的轮次限制
    refresh_runtime: bool = False        # 是否需要刷新运行时 (切换 Provider 等)
    submit_prompt: str | None = None     # 提交给模型的提示词 (Skill 命令)
    submit_model: str | None = None      # 指定模型

@dataclass
class CommandContext:
    engine: QueryEngine                   # 当前查询引擎
    hooks_summary: str = ""              # Hook 配置摘要
    mcp_summary: str = ""                # MCP 服务器摘要
    plugin_summary: str = ""              # 插件摘要
    cwd: str = "."                        # 当前工作目录
    tool_registry: ToolRegistry | None = None
    app_state: AppStateStore | None = None
    session_backend: SessionBackend = DEFAULT_SESSION_BACKEND
    session_id: str | None = None
    extra_skill_dirs: ... | None = None
    extra_plugin_roots: ... | None = None

@dataclass
class SlashCommand:
    name: str                             # 命令名 (不含 /)
    description: str                      # 帮助文本
    handler: CommandHandler              # async (args, context) → CommandResult
    remote_invocable: bool = True        # 远程是否可调用
    remote_admin_opt_in: bool = False    # 远程是否需要管理员确认
```

### CommandRegistry

```python
class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, SlashCommand] = {}
    
    def register(self, command: SlashCommand):
        """注册一个命令"""
    
    def lookup(self, raw_input: str) -> tuple[SlashCommand, str] | None:
        """解析输入, 返回 (命令, 参数) 或 None"""
        # "/compact 6" → (SlashCommand("compact", ...), "6")
    
    def help_text(self) -> str:
        """格式化的帮助文本"""
    
    def list_commands(self) -> list[SlashCommand]:
        """返回所有命令"""
```

---

## 10. 全部命令一览 (~50 个)

### 会话管理

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/help` | 显示所有命令 | `registry.help_text()` |
| `/exit` | 退出会话 | `should_exit=True` |
| `/clear` | 清空对话 | `engine.clear()` + `clear_screen=True` |
| `/status` | 会话状态 | 消息数、用量、Profile |
| `/resume [ID]` | 恢复会话 | 从 `session_backend` 加载 |
| `/session [show\|ls\|path\|tag\|clear]` | 会话存储管理 | 查看/标签/清除 |
| `/export` | 导出转录 | Markdown 格式 |
| `/share` | 创建可分享快照 | 同 export |
| `/rewind [N]` | 回退 N 轮对话 | `_rewind_turns()` 逆序 pop |
| `/continue [N]` | 继续挂起的工具循环 | `continue_pending=True` |

### 模型与推理

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/model [show\|NAME]` | 查看/切换模型 | `manager.update_profile()` + `engine.set_model()` |
| `/effort [show\|low\|medium\|high]` | 推理强度 | 修改 `settings.effort` |
| `/passes [show\|N]` | 推理轮次 | 修改 `settings.passes` |
| `/turns [show\|unlimited\|N]` | 最大 Agent 轮次 | 修改 `engine.max_turns` |
| `/fast [show\|on\|off\|toggle]` | 快速模式 | 修改 `settings.fast_mode` |

### Provider 与认证

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/provider [show\|list\|PROFILE]` | 查看/切换 Provider | `manager.use_profile()` + `refresh_runtime` |
| `/login [API_KEY]` | 存储 API Key | `manager.store_profile_credential()` |
| `/logout` | 清除 API Key | `manager.clear_profile_credential()` |

### 权限与配置

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/permissions [show\|MODE]` | 查看/切换权限模式 | `PermissionMode` 枚举 + `refresh_runtime` |
| `/plan [on\|off]` | 切换 Plan 模式 | Plan = 权限模式设为 `PLAN` |
| `/config [show\|set KEY VALUE]` | 查看/修改配置 | `save_settings()` |
| `/context` | 显示当前 system prompt | `build_runtime_system_prompt()` |

### 对话操作

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/summary [N]` | 总结对话 | `summarize_messages()` |
| `/compact [N]` | 压缩对话 | `compact_conversation()` → `build_post_compact_messages()` |
| `/copy [TEXT]` | 复制到剪贴板 | `pyperclip` + fallback |
| `/cost` | 估算费用 | 基于 Claude 定价 |
| `/usage` | Token 用量 | 实际 + 估算 |

### 工具与插件

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/skills [NAME]` | 列出/显示 Skill | `load_skill_registry()` |
| `/mcp [auth ...]` | MCP 服务器管理 | 修改 `settings.mcp_servers` |
| `/plugin [list\|enable\|disable\|install\|uninstall]` | 插件管理 | `load_plugins()` + `save_settings()` |
| `/reload-plugins` | 重新加载插件 | 发现 + 注册 |
| `/hooks` | 显示 Hook 配置 | `context.hooks_summary` |

### 项目与文件

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/files [N\|dirs\|FILTER]` | 列出工作区文件 | `rglob("*")` 过滤 |
| `/memory [list\|show\|add\|remove]` | 项目记忆管理 | 内存条目增删查 |
| `/init` | 初始化项目配置 | 创建 CLAUDE.md, .openharness/ 等 |
| `/issue [show\|set\|clear]` | Issue 上下文 | 读写 `.openharness/issue.md` |
| `/pr_comments [show\|add\|clear]` | PR 评论上下文 | 读写 `.openharness/pr_comments.md` |

### Git 操作

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/diff [full]` | Git diff | `git diff` / `git diff --stat` |
| `/branch [show\|list]` | Git 分支 | `git branch` |
| `/commit [MSG]` | Git 提交 | `git add -A && git commit` |

### 任务与 Agent

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/tasks [list\|run\|stop\|show\|update\|output]` | 后台任务管理 | `TaskManager` CRUD |
| `/agents [help\|show ID]` | 子 Agent 管理 | 查看 worker task |
| `/subagents` | 同 `/agents` | 别名 |

### UI 与样式

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/theme [list\|show\|NAME\|preview]` | 主题管理 | `load_theme()` |
| `/output-style [show\|list\|NAME]` | 输出样式 | `load_output_styles()` |
| `/keybindings` | 快捷键 | `load_keybindings()` |
| `/vim [show\|on\|off\|toggle]` | Vim 模式 | `settings.vim_mode` |
| `/voice [show\|on\|off\|toggle\|keyterms]` | 语音模式 | `settings.voice_mode` |

### 诊断与调试

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/doctor` | 环境诊断 | 完整状态摘要 |
| `/privacy-settings` | 隐私与存储 | 配置目录路径 |
| `/rate-limit-options` | 限速建议 | 减少请求的方法 |
| `/stats` | 会话统计 | 消息/token/工具/记忆/任务 |
| `/version` | 版本号 | `importlib.metadata` |
| `/upgrade` | 升级指引 | 安装命令 |
| `/release-notes` | 发布说明 | 读 RELEASE_NOTES.md |
| `/feedback TEXT` | 反馈日志 | 追加到本地日志文件 |
| `/onboarding` | 新手引导 | 快速入门说明 |

### 桥接

| 命令 | 描述 | 关键操作 |
|------|------|----------|
| `/bridge [show\|encode\|decode\|sdk\|spawn\|list\|output\|stop]` | Bridge 会话管理 | `BridgeManager` 操作 |

---

## 11. 命令实现的关键模式

### 模式 A: 只读查询

```python
# /status, /usage, /cost, /hooks 等
async def _status_handler(_, context: CommandContext) -> CommandResult:
    usage = context.engine.total_usage
    return CommandResult(message=f"Messages: {len(context.engine.messages)}\n...")
```

### 模式 B: 设置修改 + 持久化

```python
# /fast, /effort, /passes, /vim, /voice, /theme, /output-style 等
async def _fast_handler(args, context: CommandContext) -> CommandResult:
    settings = load_settings()
    settings.fast_mode = enabled
    save_settings(settings)                    # 1. 修改设置 → 持久化
    if context.app_state is not None:
        context.app_state.set(fast_mode=enabled)  # 2. 更新运行时状态
    return CommandResult(message=f"Fast mode {'enabled' if enabled else 'disabled'}.")
```

### 模式 C: 设置修改 + 运行时重建

```python
# /permissions, /plan, /provider, /model 等
async def _permissions_handler(args, context: CommandContext) -> CommandResult:
    settings.permission.mode = PermissionMode(target_mode)
    save_settings(settings)                                    # 1. 持久化
    context.engine.set_permission_checker(PermissionChecker(settings.permission))  # 2. 重建权限检查器
    if context.app_state is not None:
        context.app_state.set(permission_mode=settings.permission.mode.value)     # 3. 更新状态
    return CommandResult(message=f"...", refresh_runtime=True)  # 4. 标记需要刷新运行时
```

`refresh_runtime=True` 信号告诉 TUI 层重建 `RuntimeBundle`, 因为 Provider/API Client 等核心对象已经变了。

### 模式 D: 会话操作

```python
# /resume, /clear, /rewind, /compact 等
async def _compact_handler(args, context: CommandContext) -> CommandResult:
    compacted = await compact_conversation(context.engine.messages, ...)
    context.engine.load_messages(compacted)     # 直接修改 engine 的消息列表
    return CommandResult(message=f"Compacted from {before} to {len(compacted)}.")
```

### 模式 E: 提交模型提示词

```python
# Plugin commands (Skill 类命令)
async def _plugin_command_handler(args, context, *, command=plugin_command):
    prompt = _render_plugin_command_prompt(command, args, session_id)
    if command.disable_model_invocation:
        return CommandResult(message=prompt)  # 只显示, 不调用模型
    return CommandResult(submit_prompt=prompt, submit_model=command.model)  # 提交给模型
```

---

## 12. _coerce_setting_value — 配置值类型转换

```python
def _coerce_setting_value(settings, key, raw):
    """将字符串输入转换为 Settings 字段的正确类型"""
    field = Settings.model_fields.get(key)
    annotation = field.annotation
    if annotation is bool:       # "true"/"yes"/"on"/"1" → True
        ...
    if annotation is int:        # 字符串 → int
        return int(raw)
    if annotation is str:        # 原样返回
        return raw
    if annotation is Literal:    # 枚举检查
        ...
```

**用途**: `/config set KEY VALUE` 命令将用户输入的字符串转换为 Settings 中定义的类型。

---

## 13. _resolve_memory_entry_path — 安全路径解析

```python
def _resolve_memory_entry_path(memory_dir, candidate):
    """安全解析 memory 条目路径, 防止路径遍历"""
    # 1. 尝试原样解析
    resolved, invalid = _resolve_memory_candidate(base, candidate)
    # 2. 追加 .md 后缀重试
    # 3. slug 化 (非字母数字变 _) 重试
    # 所有路径必须 resolve 到 memory_dir 下 (防止 ../ 攻击)
```

---

## 14. 插件命令注册

```python
# create_default_command_registry() 末尾:
for plugin_command in plugin_commands or ():
    if not plugin_command.user_invocable:
        continue  # 非用户可调用 → 跳过
    
    # 动态创建 handler (闭包捕获 plugin_command)
    async def _plugin_command_handler(args, context, *, command=plugin_command):
        prompt = _render_plugin_command_prompt(command, args, session_id)
        if command.disable_model_invocation:
            return CommandResult(message=prompt)
        return CommandResult(submit_prompt=prompt, submit_model=command.model)
    
    registry.register(SlashCommand(
        plugin_command.name,
        plugin_command.description,
        _plugin_command_handler,
    ))
```

**关键**: 使用闭包默认参数 `command=plugin_command` 避免循环变量捕获问题。

---

## 15. 命令与 Hook 的对比

| 方面 | Hook 系统 | 命令系统 |
|------|-----------|----------|
| 触发方式 | 自动 (事件驱动) | 手动 (用户输入 `/xxx`) |
| 执行时机 | Agent Loop 内 | REPL 主循环内 |
| 能否阻断 | 是 (PRE_TOOL_USE) | 否 |
| 配置方式 | `settings.json` + 插件 | 代码注册 |
| 热重载 | 支持 (`HookReloader`) | 不支持 |
| 可扩展性 | 插件可添加 | 插件可添加 |
| 执行环境 | 沙箱子进程 / API 调用 | 当前进程 |

---

## 16. 完整数据流: 从 `/provider use kimi` 到 Provider 切换

```
1. 用户输入: /provider use kimi

2. CommandRegistry.lookup("/provider use kimi")
   → (SlashCommand("provider", ...), "use kimi")

3. _provider_handler("use kimi", context)
   → AuthManager.use_profile("kimi")
   → load_settings()  # 重新读取 (因为 use_profile 修改了 settings)
   → context.engine.set_model(updated.model)
   → context.app_state.set(model=..., provider=..., auth_status=..., base_url=...)
   → return CommandResult(message="Switched to kimi", refresh_runtime=True)

4. TUI 层收到 refresh_runtime=True
   → 重建 RuntimeBundle
   → _resolve_api_client_from_settings(settings)  # 新的 API Client
   → 重建 HookExecutor, PermissionChecker 等
```

---

## 17. 安全考虑

### Hook 安全

1. **Command Hook** 使用 `create_shell_subprocess()` (可能在沙箱中执行)
2. **`$ARGUMENTS` 注入**: Command Hook 使用 `shlex.quote()` 做 shell 转义; Prompt Hook 不需要
3. **超时**: 所有 Hook 都有超时限制, 防止挂起
4. **阻断语义**: `block_on_failure` 是可配置的 — 默认 Command/Http 不阻断, Prompt/Agent 阻断

### 命令安全

1. **路径遍历**: `/memory` 命令使用 `_resolve_memory_entry_path()` 防止 `../` 攻击
2. **敏感命令**: `/permissions` 和 `/plan` 设置 `remote_invocable=False`, `remote_admin_opt_in=True`
3. **配置修改**: `/config set` 通过 `_coerce_setting_value()` 做类型检查
4. **模型限制**: `/model` 检查 `profile.allowed_models` 白名单
5. **Git 操作**: `/commit` 使用 `git add -A` (注意: 会添加所有修改)