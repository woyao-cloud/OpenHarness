# Phase 5: 配置与权限系统深度解析

> 涉及文件:
> - `permissions/modes.py` (20行), `permissions/checker.py` (201行)
> - `config/settings.py` (870行), `config/paths.py` (100行), `config/schema.py` (109行)
> - `utils/fs.py` (99行), `utils/file_lock.py` (81行)

  权限决策的 9 级优先级 (从高到低):
  ① 内置敏感路径保护 (不可覆盖!) → ② 工具黑名单 → ③ 工具白名单
  → ④ 路径 deny 规则 → ⑤ 命令 deny 模式 → ⑥ FULL_AUTO 模式
  → ⑦ 只读判断 → ⑧ PLAN 模式拒绝 → ⑨ DEFAULT 模式确认框

  三个关键设计决策:

  1. 敏感路径硬保护 — .ssh/, .aws/, .gnupg/ 等, 即使 full_auto 模式也不可访问。这是 prompt injection 的纵深防御。
  2. 拒绝 = ToolResultBlock(is_error=True) — 权限拒绝不抛异常, 而是返回错误结果。保证对话历史完整 (每个 tool_use 都有 tool_result), 模型可以看到拒绝原因并调整策略。
  3. 配置三层合并 — 文件 → 环境变量 → CLI, 每层通过 materialize_active_profile() 将 profile 投影到 flat 字段, 确保一致性。运行时变更通过 refresh_runtime_client() 热生效。

  持久化安全: 所有配置写入使用 atomic_write_text (临时文件+原子替换) + exclusive_file_lock (跨进程互斥), 防崩溃和防并发。
  
---

## 1. 权限系统架构

```
PermissionMode (3种模式)          ← 枚举: DEFAULT, PLAN, FULL_AUTO
  ↓
PermissionSettings (5个维度)     ← 配置层: mode + 4种规则
  ↓
PermissionChecker.evaluate()     ← 决策引擎: 按优先级逐条检查
  ↓
PermissionDecision               ← 决策结果: allowed + requires_confirmation + reason
  ↓
Agent Loop 处理                  ← 放行 / 弹确认框 / 拒绝
```

---

## 2. PermissionMode — 三种模式

```python
class PermissionMode(str, Enum):
    DEFAULT = "default"      # 读操作自动放行, 写操作弹确认框
    PLAN = "plan"            # 读操作自动放行, 写操作直接拒绝
    FULL_AUTO = "full_auto"  # 一切操作自动放行
```

### 模式对工具的影响矩阵

| 工具类型 | DEFAULT | PLAN | FULL_AUTO |
|----------|---------|------|-----------|
| 只读工具 (read_file, grep, ...) | ✅ 放行 | ✅ 放行 | ✅ 放行 |
| 写入工具 (write_file, edit_file, ...) | 🔶 确认 | ❌ 拒绝 | ✅ 放行 |
| Shell 工具 (bash) | 🔶 确认 | ❌ 拒绝 | ✅ 放行 |
| 模式切换 (enter_plan_mode) | 🔶 确认 | ❌ 拒绝 | ✅ 放行 |

**关键理解**: PLAN 模式是"只看不摸"模式, 强制 Agent 只做分析不做修改。这给大型重构提供了一个安全工作方式: 先在 Plan 模式下审查, 确认方案后再切回 Default 执行。

---

## 3. PermissionSettings — 五维配置

```python
class PermissionSettings(BaseModel):
    mode: PermissionMode = PermissionMode.DEFAULT     # ① 主模式
    allowed_tools: list[str] = []                      # ② 工具白名单
    denied_tools: list[str] = []                       # ③ 工具黑名单
    path_rules: list[PathRuleConfig] = []             # ④ 路径规则
    denied_commands: list[str] = []                    # ⑤ 命令拒绝模式
```

### 各维度示例

```json
{
  "permission": {
    "mode": "default",
    "allowed_tools": ["bash"],
    "denied_tools": ["write_file"],
    "path_rules": [
      {"pattern": "/etc/*", "allow": false},
      {"pattern": "/home/user/project/*", "allow": true}
    ],
    "denied_commands": ["rm -rf /", "DROP TABLE *"]
  }
}
```

---

## 4. PermissionChecker.evaluate() — 决策引擎 (核心 80 行)

决策按严格的优先级顺序进行, **高优先级的规则总是胜出**:

```
evaluate(tool_name, is_read_only, file_path, command)
│
├── ① 内置敏感路径保护 (最高优先级, 不可覆盖)
│   └── file_path 匹配 SENSITIVE_PATH_PATTERNS → ❌ 拒绝
│
├── ② 工具黑名单
│   └── tool_name in denied_tools → ❌ 拒绝
│
├── ③ 工具白名单
│   └── tool_name in allowed_tools → ✅ 放行
│
├── ④ 路径规则
│   └── file_path 匹配 path_rules 中 deny 规则 → ❌ 拒绝
│   └── (注意: 只检查 deny 规则, allow 规则不在此生效)
│
├── ⑤ 命令拒绝模式
│   └── command 匹配 denied_commands → ❌ 拒绝
│
├── ⑥ FULL_AUTO 模式
│   └── ✅ 放行一切
│
├── ⑦ 只读工具
│   └── is_read_only=True → ✅ 放行
│
├── ⑧ PLAN 模式 + 变更工具
│   └── ❌ 拒绝
│
└── ⑨ DEFAULT 模式 + 变更工具
    └── 🔶 需要用户确认 (requires_confirmation=True)
```

**关键细节**:

- ① 是硬编码保护, **用户配置无法覆盖**。这是防御 prompt injection 的纵深措施
- ④ 只检查 deny 规则 — path_rules 的 allow 规则不会让一个本来需要确认的操作自动放行
- ⑨ 返回 `requires_confirmation=True`, 不是直接拒绝 — Agent Loop 会弹确认框让用户决定

### 内置敏感路径保护

```python
SENSITIVE_PATH_PATTERNS = (
    "*/.ssh/*",                      # SSH 密钥
    "*/.aws/credentials",            # AWS 凭证
    "*/.aws/config",                 # AWS 配置
    "*/.config/gcloud/*",            # GCP 凭证
    "*/.azure/*",                    # Azure 凭证
    "*/.gnupg/*",                    # GPG 密钥
    "*/.docker/config.json",         # Docker 凭证
    "*/.kube/config",               # K8s 凭证
    "*/.openharness/credentials.json",  # OH 凭证
    "*/.openharness/copilot_auth.json", # Copilot 凭证
)
```

**为什么是硬编码**: LLM 可能被 prompt injection 诱导读取这些文件并泄露内容。即使用户设置了 `full_auto` 模式, 这些路径仍然被保护。这是**纵深防御** — 多层保护, 单层失守不等于全面失守。

### 路径匹配的技巧: `_policy_match_paths`

```python
def _policy_match_paths(file_path: str) -> tuple[str, ...]:
    normalized = file_path.rstrip("/")
    return (normalized, normalized + "/")
```

**为什么**: `grep` 和 `glob` 的 `root` 参数可能指向 `/home/user/.ssh` (无尾部斜杠)。但 deny 规则 `*/.ssh/*` 匹配的是目录下的文件。通过追加 `/`, 让 `/home/user/.ssh/` 也能匹配 `*/.ssh/*`, 确保目录本身也被保护。

### Bash 安装命令提示

```python
def _bash_permission_hint(command: str | None) -> str:
    # 检测 npm install, pip install, create-next-app 等
    # 返回额外提示信息, 说明为什么这些命令需要确认
```

这确保用户在 DEFAULT 模式下看到 `npm install` 时, 不仅看到通用提示, 还能看到"包安装和脚手架命令会修改工作区"。

---

## 5. Agent Loop 中的权限处理流程

回顾 `_execute_tool_call()` (query.py:595), 权限检查在第 ④ 步:

```python
# 路径和命令解析 (在权限检查之前!)
_file_path = _resolve_permission_file_path(context.cwd, tool_input, parsed_input)
_command = _extract_permission_command(tool_input, parsed_input)

# 权限决策
decision = context.permission_checker.evaluate(
    tool_name,
    is_read_only=tool.is_read_only(parsed_input),
    file_path=_file_path,
    command=_command,
)

# 处理决策
if not decision.allowed:
    if decision.requires_confirmation and context.permission_prompt is not None:
        # 弹确认框
        confirmed = await context.permission_prompt(tool_name, decision.reason)
        if not confirmed:
            return ToolResultBlock(..., is_error=True)  # 用户拒绝
        # 用户确认 → 继续执行
    else:
        # 直接拒绝 (PLAN 模式或黑名单)
        return ToolResultBlock(..., is_error=True)
```

**关键**: 被拒绝的工具调用不是抛异常, 而是返回 `is_error=True` 的 ToolResultBlock。这确保:
1. 对话历史完整 — 每个 tool_use 都有对应的 tool_result
2. 模型看到拒绝原因, 可以调整策略 (如换一个只读方式)

### 权限路径解析 (`_resolve_permission_file_path`)

```python
def _resolve_permission_file_path(cwd, raw_input, parsed_input):
    # 从原始输入 dict 查找: file_path → path → root
    for key in ("file_path", "path", "root"):
        value = raw_input.get(key)
        if isinstance(value, str):
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            return str(path.resolve())

    # 再从 Pydantic 模型属性查找: file_path → path → root
    for attr in ("file_path", "path", "root"):
        value = getattr(parsed_input, attr, None)
        ...
```

**为什么查三个字段名**: 不同工具用不同的字段名:
- `read_file`: `path`
- `write_file`: `path`
- `grep`: `root`
- `edit_file`: `path`

统一检查 `file_path`, `path`, `root` 三个名字, 确保所有工具的路径都能被权限系统捕获。

---

## 6. 配置系统: 多层合并

### 配置解析优先级 (从高到低)

```
1. CLI 参数         (--model sonnet, --permission-mode full_auto)
2. 环境变量         (ANTHROPIC_API_KEY, OPENHARNESS_MODEL, OPENHARNESS_MAX_TURNS, ...)
3. 配置文件         (~/.openharness/settings.json)
4. 代码默认值        (Settings 类的字段默认值)
```

### 配置加载流程

```python
def load_settings(config_path=None):
    # 1. 读取文件 → Pydantic 验证
    if config_path.exists():
        raw = json.loads(config_path.read_text())
        settings = Settings.model_validate(raw)

    # 2. 兼容: 旧版无 profile → 从 flat 字段推断 profile
        if "profiles" not in raw or "active_profile" not in raw:
            profile_name, profile = _profile_from_flat_settings(settings)
            ...

    # 3. 物化: 将 active profile 投影到 flat 字段
        return _apply_env_overrides(settings.materialize_active_profile())

    # 4. 无文件: 用默认值
    return _apply_env_overrides(Settings().materialize_active_profile())
```

### Profile 物化 (materialize_active_profile)

```python
def materialize_active_profile(self) -> Settings:
    """将 active profile 的设置投影到 Settings 的 top-level 字段"""
    profile_name, profile = self.resolve_profile()
    return self.model_copy(update={
        "active_profile": profile_name,
        "provider": profile.provider,
        "api_format": profile.api_format,
        "base_url": profile.base_url,
        "model": resolve_model_setting(...),
        ...
    })
```

**为什么需要物化**: Settings 既有 `self.model` (flat 字段) 又有 `self.profiles["claude-api"].last_model` (profile 字段)。物化确保 flat 字段反映 active profile 的实际值, 避免两处不一致。

### CLI 覆盖 (merge_cli_overrides)

```python
def merge_cli_overrides(self, **overrides) -> Settings:
    # 只应用非 None 的覆盖
    updates = {k: v for k, v in overrides.items() if v is not None}

    # 如果覆盖了 profile 相关字段 → 同步 + 物化
    if profile_updates:
        return merged.sync_active_profile_from_flat_fields().materialize_active_profile()

    # 如果只切了 profile → 直接物化
    if profile_updates == {"active_profile"}:
        return merged.materialize_active_profile()

    return merged
```

### 环境变量覆盖

```python
def _apply_env_overrides(settings):
    # 支持的环境变量:
    ANTHROPIC_MODEL / OPENHARNESS_MODEL         → model
    ANTHROPIC_BASE_URL / OPENAI_BASE_URL / OPENHARNESS_BASE_URL → base_url
    OPENHARNESS_MAX_TOKENS                      → max_tokens
    OPENHARNESS_TIMEOUT                         → timeout
    OPENHARNESS_MAX_TURNS                       → max_turns
    OPENHARNESS_CONTEXT_WINDOW_TOKENS           → context_window_tokens
    OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS   → auto_compact_threshold_tokens
    ANTHROPIC_API_KEY / OPENAI_API_KEY          → api_key
    OPENHARNESS_API_FORMAT                      → api_format
    OPENHARNESS_PROVIDER                        → provider
    OPENHARNESS_SANDBOX_ENABLED                 → sandbox.enabled
    OPENHARNESS_SANDBOX_BACKEND                 → sandbox.backend
    OPENHARNESS_SANDBOX_DOCKER_IMAGE            → sandbox.docker.image
```

---

## 7. Settings 完整结构

```python
class Settings(BaseModel):
    # ── API ──
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 16384
    base_url: str | None = None
    timeout: float = 30.0
    context_window_tokens: int | None = None
    auto_compact_threshold_tokens: int | None = None
    api_format: str = "anthropic"            # "anthropic" | "openai" | "copilot"
    provider: str = ""
    active_profile: str = "claude-api"
    profiles: dict[str, ProviderProfile]       # 7 个内置 + 自定义
    max_turns: int = 200

    # ── 行为 ──
    system_prompt: str | None = None
    permission: PermissionSettings
    hooks: dict[str, list[HookDefinition]]
    memory: MemorySettings
    sandbox: SandboxSettings
    enabled_plugins: dict[str, bool]
    mcp_servers: dict[str, McpServerConfig]

    # ── UI ──
    theme: str = "default"
    output_style: str = "default"
    vim_mode: bool = False
    voice_mode: bool = False
    fast_mode: bool = False
    effort: str = "medium"
    passes: int = 1
    verbose: bool = False
```

### 关键嵌套 Settings

```
PermissionSettings
├── mode: PermissionMode
├── allowed_tools: list[str]
├── denied_tools: list[str]
├── path_rules: list[PathRuleConfig]
└── denied_commands: list[str]

MemorySettings
├── enabled: bool = True
├── max_files: int = 5
├── max_entrypoint_lines: int = 200
├── context_window_tokens: int | None
└── auto_compact_threshold_tokens: int | None

SandboxSettings
├── enabled: bool = False
├── backend: str = "srt"
├── fail_if_unavailable: bool = False
├── network: SandboxNetworkSettings
├── filesystem: SandboxFilesystemSettings
└── docker: DockerSandboxSettings

ProviderProfile
├── label, provider, api_format, auth_source
├── default_model, last_model, base_url
├── credential_slot: str | None     # 独立密钥槽位
├── context_window_tokens
└── auto_compact_threshold_tokens
```

---

## 8. 认证解析 (`Settings.resolve_auth()`)

```python
def resolve_auth(self) -> ResolvedAuth:
    profile_name, profile = self.resolve_profile()

    # ┌─ 订阅型认证 ─┐
    # Claude Subscription / Codex Subscription
    if auth_source in {"claude_subscription", "codex_subscription"}:
        binding = load_external_binding(...)
        credential = load_external_credential(binding, refresh_if_needed=...)
        return ResolvedAuth(auth_kind=credential.auth_kind, value=credential.value, ...)

    # ┌─ OAuth 型认证 ─┐
    # GitHub Copilot
    if auth_source == "copilot_oauth":
        return ResolvedAuth(auth_kind="oauth_device", value="copilot-managed", ...)

    # ┌─ API Key 型认证 ─┐
    # 优先级: profile slot → 环境变量 → settings.api_key → 文件存储

    # 1. Profile 独立槽位
    if profile.credential_slot:
        scoped = load_credential(f"profile:{slot}", "api_key")
        if scoped: return ResolvedAuth(value=scoped, source="file:profile:...")

    # 2. 环境变量
    env_var = {"anthropic_api_key": "ANTHROPIC_API_KEY", ...}.get(auth_source)
    if env_var and os.environ.get(env_var):
        return ResolvedAuth(value=os.environ[env_var], source=f"env:{env_var}")

    # 3. Settings 中的 api_key
    if self.api_key:
        return ResolvedAuth(value=self.api_key, source="settings_or_env")

    # 4. 文件存储
    stored = load_credential(provider, "api_key")
    if stored: return ResolvedAuth(value=stored, source=f"file:{provider}")

    raise ValueError("No credentials found")
```

**三种认证类型**:

| 类型 | auth_source | 密钥来源 | 刷新 |
|------|-------------|----------|------|
| 订阅桥接 | `claude_subscription`, `codex_subscription` | 外部文件 (`.credentials.json`) | ✅ Claude 需要 |
| OAuth | `copilot_oauth` | Copilot 管理 | N/A |
| API Key | `*_api_key` | env/slot/file/settings | ❌ |

**Profile 独立槽位** (`credential_slot`): 解决多个兼容端点共享同一 auth_source 但需要不同密钥的问题。例如两个 OpenAI 兼容 profile, 各自有自己的 API key。

---

## 9. 持久化安全: 原子写入 + 文件锁

### 原子写入 (`utils/fs.py`)

```python
def atomic_write_text(path, data, encoding="utf-8", mode=None):
    # 1. 写入同目录临时文件
    fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=parent)
    # 2. flush + fsync (确保落盘)
    tmp_file.write(data); tmp_file.flush(); os.fsync(fd)
    # 3. 原子替换 (os.replace 在 POSIX 和 Windows 上都是原子的)
    os.replace(tmp_path, dst)
```

**为什么**: 如果 `Path.write_text()` 在写入中途崩溃, 磁盘上留下截断文件, 下次读取返回空或损坏数据。原子写入确保: 读者要么看到旧数据, 要么看到新数据, 永远不会看到半写的数据。

### 文件锁 (`utils/file_lock.py`)

```python
@contextmanager
def exclusive_file_lock(lock_path, *, platform_name=None):
    if platform == "windows":
        # msvcrt.locking — 锁定文件首字节
    elif platform in {"macos", "linux", "wsl"}:
        # fcntl.flock — POSIX 文件锁
```

**用途**: 配合原子写入, 解决多个 `oh` 进程并发写 `settings.json` 的问题:

```python
# settings.py: save_settings()
lock_path = config_path.with_suffix(".lock")
with exclusive_file_lock(lock_path):
    atomic_write_text(config_path, settings.model_dump_json(indent=2) + "\n")
```

---

## 10. 配置系统目录结构

```
~/.openharness/
├── settings.json             # 全局设置 (原子写入 + 文件锁)
├── settings.json.lock        # 写入锁文件
├── credentials.json          # API 密钥存储 (加密)
├── copilot_auth.json         # Copilot OAuth 令牌
├── data/
│   ├── sessions/             # 会话快照
│   ├── tasks/                # 后台任务输出
│   ├── cron_jobs.json        # 定时任务注册表
│   └── feedback/             # 用户反馈
├── logs/                     # 运行日志
├── skills/                   # 用户自定义 Skill (.md)
├── hooks/                    # 用户自定义 Hook
└── plugins/                  # 用户安装的插件
```

项目级:
```
{project}/.openharness/
├── issue.md                  # Issue 上下文
└── pr_comments.md            # PR 评论上下文
```

环境变量覆盖:
```
OPENHARNESS_CONFIG_DIR   → 覆盖 ~/.openharness/
OPENHARNESS_DATA_DIR     → 覆盖 ~/.openharness/data/
OPENHARNESS_LOGS_DIR     → 覆盖 ~/.openharness/logs/
```

---

## 11. 配置变更的运行时传播

当用户在交互模式下修改配置 (如切换权限模式), 变更如何传播?

```
用户执行 /permissions full_auto
    │
    ▼
CommandRegistry 找到 /permissions 命令
    │
    ▼
命令处理器修改 Settings → save_settings()
    │
    ▼
CommandResult.refresh_runtime = True
    │
    ▼
handle_line() 调用 refresh_runtime_client(bundle)
    │
    ├─ load_settings()                # 重新从文件读取
    ├─ _resolve_api_client_from_settings()  # 可能换 API 客户端
    ├─ bundle.engine.set_api_client()  # 更新引擎
    ├─ bundle.engine.set_model()       # 更新模型
    └─ sync_app_state(bundle)          # 刷新 UI 状态
```

**关键**: 每次修改 Settings 后, 不需要重启, `refresh_runtime_client()` 会重新加载配置并更新引擎。但已有的 `PermissionChecker` 不会自动更新 — 它在 `QueryEngine` 构造时被创建, 之后不会变。

**例外**: `enter_plan_mode` / `exit_plan_mode` 工具通过修改 Settings + carryover (`tool_metadata["permission_mode"]`) 来影响后续行为, 不依赖 PermissionChecker 的重新加载。

---

## 12. 速查: 权限决策流程

```
"bash 工具执行 rm -rf /tmp/test" 在 DEFAULT 模式下的完整路径:

① 敏感路径检查: /tmp/test 不匹配 SENSITIVE_PATH_PATTERNS → 继续
② 工具黑名单: "bash" 不在 denied_tools → 继续
③ 工具白名单: "bash" 不在 allowed_tools → 继续
④ 路径规则: 无 file_path (bash 没有 path 字段) → 继续
⑤ 命令拒绝: "rm -rf /tmp/test" 不匹配 denied_commands → 继续
⑥ FULL_AUTO: 否 → 继续
⑦ 只读: bash.is_read_only() = False → 继续
⑧ PLAN: 否 → 继续
⑨ DEFAULT + 非只读 → requires_confirmation=True, 弹确认框
   └─ 用户点"允许" → 执行
   └─ 用户点"拒绝" → ToolResultBlock(is_error=True, content="Permission denied")
```

---

## 13. 速查: 配置路径

| 概念 | 位置 | 函数 |
|------|------|------|
| 配置目录 | `~/.openharness/` | `get_config_dir()` |
| 设置文件 | `~/.openharness/settings.json` | `get_config_file_path()` |
| 数据目录 | `~/.openharness/data/` | `get_data_dir()` |
| 日志目录 | `~/.openharness/logs/` | `get_logs_dir()` |
| 会话目录 | `~/.openharness/data/sessions/` | `get_sessions_dir()` |
| 任务目录 | `~/.openharness/data/tasks/` | `get_tasks_dir()` |
| 定时任务 | `~/.openharness/data/cron_jobs.json` | `get_cron_registry_path()` |
| 项目配置 | `{cwd}/.openharness/` | `get_project_config_dir()` |