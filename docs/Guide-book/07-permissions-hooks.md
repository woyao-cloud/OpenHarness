# 第 7 章：权限与安全控制

## 7.1 解决的问题

AI Agent 可以执行任意 Shell 命令和修改文件——这带来了严重的安全风险。权限系统需要解决：

1. **防止误操作**：阻止对敏感系统文件的修改
2. **分级控制**：根据场景应用不同的安全策略
3. **用户参与**：需要用户确认的操作弹出提示
4. **可扩展安全**：支持用户自定义的安全规则

## 7.2 权限模型

### 7.2.1 三个权限模式

`permissions/modes.py`：

```python
class PermissionMode(Enum):
    DEFAULT = "default"      # 默认：写操作需要用户确认
    PLAN = "plan"            # 计划模式：阻止所有写操作
    FULL_AUTO = "full_auto"  # 自动模式：允许所有操作
```

| 模式 | 写操作 | 读操作 | 适用场景 |
|------|--------|--------|---------|
| DEFAULT | 需确认 | 自动允许 | 日常开发 |
| PLAN | 阻止 | 自动允许 | 大重构、先评审后执行 |
| FULL_AUTO | 自动允许 | 自动允许 | 沙箱环境、信任场景 |

### 7.2.2 PermissionChecker

`permissions/checker.py`：

```python
class PermissionChecker:
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT):
        self._mode = mode
    
    def evaluate(self, tool_name, *, is_read_only, file_path, command):
        """评估工具调用是否允许。"""
        # 1. 检查敏感路径（内置保护，始终生效）
        if file_path and self._is_sensitive_path(file_path):
            return Decision(allowed=False, reason="...", blocked=True)
        
        # 2. 检查显式拒绝规则
        if self._is_explicitly_denied(tool_name, file_path, command):
            return Decision(allowed=False, reason="...", blocked=True)
        
        # 3. 检查显式允许规则
        if self._is_explicitly_allowed(tool_name, file_path):
            return Decision(allowed=True)
        
        # 4. 模式判断
        if self._mode == FULL_AUTO:
            return Decision(allowed=True)
        if self._mode == PLAN and not is_read_only:
            return Decision(allowed=False, reason="...", blocked=True)
        
        # 5. 默认：读操作允许，写操作需要确认
        if is_read_only:
            return Decision(allowed=True)
        return Decision(allowed=False, requires_confirmation=True, reason="...")
```

### 7.2.3 敏感路径保护

内置的敏感路径（`SENSITIVE_PATH_PATTERNS`）：

```
~/.ssh/*            SSH 密钥
~/.aws/*            AWS 凭证
~/.kube/*           Kubernetes 配置
~/.gnupg/*          GPG 密钥
~/.config/github/*  GitHub CLI 凭证
~/.docker/*         Docker 配置
/etc/shadow         系统密码
/etc/sudoers        权限配置
/proc/*             进程信息
```

这些路径**始终被阻止**，不受权限模式影响。

### 7.2.4 路径级规则

用户可以配置自定义路径规则：

```json
{
  "permission": {
    "path_rules": [
      {"pattern": "/etc/*", "allow": false},
      {"pattern": "/home/user/work/*", "allow": true}
    ],
    "denied_commands": [
      "rm -rf /",
      "DROP TABLE *",
      "> /dev/sda"
    ]
  }
}
```

## 7.3 生命周期 Hook

### 7.3.1 解决的问题

Hook 系统允许用户在特定生命周期事件发生时注入自定义逻辑——执行 Shell 命令、调用 HTTP API、或用 LLM 验证操作。

### 7.3.2 Hook 事件

`hooks/events.py`：

```python
class HookEvent(Enum):
    SESSION_START    = "session_start"     # 会话开始
    SESSION_END      = "session_end"       # 会话结束
    PRE_COMPACT      = "pre_compact"       # 压缩前
    POST_COMPACT     = "post_compact"      # 压缩后
    PRE_TOOL_USE     = "pre_tool_use"      # 工具执行前
    POST_TOOL_USE    = "post_tool_use"     # 工具执行后
```

### 7.3.3 Hook 定义类型

`hooks/schemas.py` 定义了四种 Hook：

**1. Command Hook**：执行 Shell 命令
```json
{
  "type": "command",
  "command": "gitleaks detect --path={{path}}",
  "timeout_ms": 5000,
  "matcher": "\"leak\"",
  "block_on_failure": false
}
```

**2. Prompt Hook**：LLM 验证（结构化 JSON 响应）
```json
{
  "type": "prompt",
  "prompt": "Is this security-sensitive? JSON: {\"ok\": true/false}"
}
```

**3. HTTP Hook**：POST 到 URL
```json
{
  "type": "http",
  "url": "https://hooks.slack.com/...",
  "method": "POST"
}
```

**4. Agent Hook**：更复杂的模型验证
```json
{
  "type": "agent",
  "model": "claude-sonnet-4-6",
  "agent_prompt": "Verify this change is safe..."
}
```

### 7.3.4 Hook 注册

`hooks/loader.py` 从配置文件和插件中加载 Hook：

```python
class HookRegistry:
    _hooks: dict[HookEvent, list[HookDefinition]]
    
    def add(self, event: HookEvent, hook: HookDefinition) -> None: ...
    def get(self, event: HookEvent) -> list[HookDefinition]: ...
    def clear(self) -> None: ...
```

### 7.3.5 Hook 执行

`hooks/executor.py`：

```python
class HookExecutor:
    async def execute(self, event: HookEvent, payload: dict) -> AggregatedHookResult:
        """执行事件对应的所有 Hook。"""
        results = []
        for hook in self._registry.get(event):
            try:
                result = await self._run_hook(hook, payload)
                results.append(result)
            except Exception as exc:
                results.append(HookResult(error=str(exc)))
        
        # 聚合结果
        blocked = any(r.blocked for r in results)
        return AggregatedHookResult(
            results=results,
            blocked=blocked,
            reason=next((r.reason for r in results if r.blocked), None),
        )
    
    async def _run_hook(self, hook, payload):
        """根据 Hook 类型执行。"""
        if isinstance(hook, CommandHookDefinition):
            return await self._run_command_hook(hook, payload)
        elif isinstance(hook, HttpHookDefinition):
            return await self._run_http_hook(hook, payload)
        elif isinstance(hook, PromptHookDefinition):
            return await self._run_prompt_hook(hook, payload)
        elif isinstance(hook, AgentHookDefinition):
            return await self._run_agent_hook(hook, payload)
```

### 7.3.6 PRE_TOOL_USE 拦截

PRE_TOOL_USE Hook 可以**阻止工具执行**（`query.py:660`）：

```python
if context.hook_executor is not None:
    pre_hooks = await context.hook_executor.execute(
        HookEvent.PRE_TOOL_USE, {...}
    )
    if pre_hooks.blocked:
        return ToolResultBlock(
            content=pre_hooks.reason or f"pre_tool_use hook blocked {tool_name}",
            is_error=True,
        )
```

## 7.4 权限检查在工具执行中的位置

```
_execute_tool_call()
  ├─ 1. PRE_TOOL_USE Hook          ← Hook 可以阻止
  ├─ 2. 工具查找
  ├─ 3. 输入验证
  ├─ 4. 权限检查                  ← PermissionChecker 判断
  │    ├─ 敏感路径？→ 阻止
  │    ├─ 拒绝规则？→ 阻止
  │    ├─ 允许规则？→ 放行
  │    ├─ PLAN + 写操作？→ 阻止
  │    └─ DEFAULT + 写操作？→ 需要用户确认
  ├─ 5. 执行工具
  ├─ 6. 记录元数据
  └─ 7. POST_TOOL_USE Hook
```

## 7.5 关键源码路径

| 组件 | 文件 | 行号 |
|------|------|------|
| 权限模式 | `permissions/modes.py` | 全部 |
| 权限检查器 | `permissions/checker.py` | 全部 |
| 敏感路径列表 | `permissions/checker.py` | SENSITIVE_PATH_PATTERNS |
| Hook 事件 | `hooks/events.py` | 全部 |
| Hook 定义 | `hooks/schemas.py` | 全部 |
| Hook 注册 | `hooks/loader.py` | 全部 |
| Hook 执行 | `hooks/executor.py` | 全部 |
| 权限在工具执行中 | `engine/query.py` | 654-724 |

## 7.6 本章小结

权限系统通过**三级模式 + 内置敏感路径保护 + 自定义规则**构建安全边界。Hook 系统通过**六种生命周期事件 + 四种 Hook 类型**提供可扩展的安全和自动化能力。两者协同，在 Agent 自主性和安全性之间取得平衡。

> 下一章：[多 Agent 协调](08-coordinator.md) —— Subagent 派生、团队管理与 Coordinator 模式。
