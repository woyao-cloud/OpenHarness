# OpenHarness 配置与权限模块详细设计

> 版本: 1.0 | 日期: 2026-04-17
> 覆盖模块: `config/settings.py` (~870行), `config/paths.py` (~117行), `config/schema.py` (~108行), `permissions/modes.py` (~14行), `permissions/checker.py` (~201行)

---

## 1. 模块概述

### 1.1 定位与职责

配置与权限模块是 OpenHarness 运行时的"控制面", 负责三个核心职责:

1. **配置解析与合并**: 将 CLI 参数、环境变量、配置文件、代码默认值四层来源合并为统一的 `Settings` 对象, 并通过 Profile 机制支持多 Provider 切换。
2. **路径约定管理**: 统一 `~/.openharness/` 目录下所有子目录和关键文件的路径解析, 支持 XDG 风格的环境变量覆盖。
3. **工具执行权限控制**: 通过 9 级决策链判定每次工具调用是否允许、是否需要用户确认或直接拒绝, 内置不可覆盖的敏感路径硬保护。

### 1.2 模块依赖关系

```
config/settings.py ──→ config/paths.py (延迟导入, 加载时获取配置文件路径)
                  ──→ permissions/modes.py (PermissionMode 枚举)
                  ──→ hooks/schemas.py (HookDefinition)
                  ──→ mcp/types.py (McpServerConfig)
                  ──→ utils/fs.py (atomic_write_text)
                  ──→ utils/file_lock.py (exclusive_file_lock)

permissions/checker.py ──→ permissions/modes.py (PermissionMode)
                       ──→ config/settings.py (PermissionSettings)

config/schema.py ──→ (无内部依赖, 独立兼容通道模型)

ui/runtime.py ──→ config/ (load_settings, build_runtime)
             ──→ permissions/ (PermissionChecker)
```

### 1.3 规模与复杂度

| 文件 | 行数 | 核心类/函数数 | 说明 |
|------|------|---------------|------|
| `config/settings.py` | ~870 | 12 类 + 18 函数 | 最大的单一配置文件, 含 Settings、Profile、权限/沙箱/记忆嵌套模型 |
| `config/paths.py` | ~117 | 10 函数 | 纯函数式路径解析, 无状态 |
| `config/schema.py` | ~108 | 13 类 | Pydantic 兼容通道模型, 独立于主 Settings |
| `permissions/modes.py` | ~14 | 1 枚举 | 极简, 3 个模式值 |
| `permissions/checker.py` | ~201 | 3 类 + 2 函数 | 9 级决策链核心逻辑 |

---

## 2. 核心类/接口

### 2.1 Settings (config/settings.py)

`Settings` 是整个配置系统的根模型, 继承 `pydantic.BaseModel`, 同时持有"扁平字段"(legacy) 和"Profile 字段"(结构化) 两套 Provider 配置。

```
Settings (BaseModel)
├── API 配置 (扁平字段)
│   ├── api_key: str = ""
│   ├── model: str = "claude-sonnet-4-6"
│   ├── max_tokens: int = 16384
│   ├── base_url: str | None = None
│   ├── timeout: float = 30.0
│   ├── context_window_tokens: int | None = None
│   ├── auto_compact_threshold_tokens: int | None = None
│   ├── api_format: str = "anthropic"
│   ├── provider: str = ""
│   ├── active_profile: str = "claude-api"
│   ├── profiles: dict[str, ProviderProfile]
│   └── max_turns: int = 200
│
├── 行为配置
│   ├── system_prompt: str | None = None
│   ├── permission: PermissionSettings
│   ├── hooks: dict[str, list[HookDefinition]]
│   ├── memory: MemorySettings
│   ├── sandbox: SandboxSettings
│   ├── enabled_plugins: dict[str, bool]
│   └── mcp_servers: dict[str, McpServerConfig]
│
└── UI 配置
    ├── theme: str = "default"
    ├── output_style: str = "default"
    ├── vim_mode: bool = False
    ├── voice_mode: bool = False
    ├── fast_mode: bool = False
    ├── effort: str = "medium"
    ├── passes: int = 1
    └── verbose: bool = False
```

**关键方法**:

| 方法 | 作用 | 返回 |
|------|------|------|
| `merged_profiles()` | 合并内置 Profile 目录与用户自定义 Profile | `dict[str, ProviderProfile]` |
| `resolve_profile(name)` | 解析当前活跃 Profile, 不存在则回退推断 | `(str, ProviderProfile)` |
| `materialize_active_profile()` | 将活跃 Profile 投影到扁平字段, 保证一致性 | `Settings` (新实例) |
| `sync_active_profile_from_flat_fields()` | 将扁平字段反向同步到 Profile | `Settings` (新实例) |
| `merge_cli_overrides(**overrides)` | 合并 CLI 覆盖值, 自动触发 Profile 同步/物化 | `Settings` (新实例) |
| `resolve_api_key()` | 解析 API 密钥 (实例值 > 环境变量) | `str` (找不到抛 ValueError) |
| `resolve_auth()` | 解析完整认证信息 (含订阅桥接、OAuth) | `ResolvedAuth` |

### 2.2 ProviderProfile (config/settings.py)

```python
class ProviderProfile(BaseModel):
    label: str                           # 用户可见标签
    provider: str                        # 运行时 Provider 标识
    api_format: str                      # API 协议格式 (anthropic/openai/copilot)
    auth_source: str                     # 认证来源标识
    default_model: str                    # 默认模型
    base_url: str | None = None          # 自定义 API 端点
    last_model: str | None = None        # 最近使用的模型
    credential_slot: str | None = None   # 独立密钥槽位
    allowed_models: list[str] = []       # 可选模型白名单
    context_window_tokens: int | None    # 上下文窗口覆盖
    auto_compact_threshold_tokens: int | None  # 自动压缩阈值覆盖
```

**属性**:
- `resolved_model`: 返回活跃模型 ID, 优先 `last_model`, 回退 `default_model`, 并通过 `resolve_model_setting()` 解析别名。

### 2.3 嵌套配置模型

```
PermissionSettings (BaseModel)
├── mode: PermissionMode = DEFAULT
├── allowed_tools: list[str] = []
├── denied_tools: list[str] = []
├── path_rules: list[PathRuleConfig] = []
└── denied_commands: list[str] = []

MemorySettings (BaseModel)
├── enabled: bool = True
├── max_files: int = 5
├── max_entrypoint_lines: int = 200
├── context_window_tokens: int | None
└── auto_compact_threshold_tokens: int | None

SandboxSettings (BaseModel)
├── enabled: bool = False
├── backend: str = "srt"
├── fail_if_unavailable: bool = False
├── enabled_platforms: list[str] = []
├── network: SandboxNetworkSettings
├── filesystem: SandboxFilesystemSettings
└── docker: DockerSandboxSettings

SandboxNetworkSettings
├── allowed_domains: list[str]
└── denied_domains: list[str]

SandboxFilesystemSettings
├── allow_read: list[str]
├── deny_read: list[str]
├── allow_write: list[str] = ["."]
└── deny_write: list[str]

DockerSandboxSettings
├── image: str = "openharness-sandbox:latest"
├── auto_build_image: bool = True
├── cpu_limit: float = 0.0
├── memory_limit: str = ""
├── extra_mounts: list[str]
└── extra_env: dict[str, str]
```

### 2.4 PermissionChecker (permissions/checker.py)

```python
class PermissionChecker:
    """根据当前权限模式与规则, 判定工具调用是否允许。"""

    def __init__(self, settings: PermissionSettings) -> None
    def evaluate(
        self,
        tool_name: str,
        *,
        is_read_only: bool,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision
```

### 2.5 PermissionDecision (permissions/checker.py)

```python
@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool                        # 是否允许执行
    requires_confirmation: bool = False  # 是否需要用户确认
    reason: str = ""                     # 决策原因说明
```

### 2.6 PermissionMode (permissions/modes.py)

```python
class PermissionMode(str, Enum):
    DEFAULT = "default"       # 变更操作需用户确认
    PLAN = "plan"            # 只读模式, 阻断所有变更操作
    FULL_AUTO = "full_auto"  # 全自动, 允许所有操作 (敏感路径除外)
```

### 2.7 ResolvedAuth (config/settings.py)

```python
@dataclass(frozen=True)
class ResolvedAuth:
    provider: str    # Provider 标识
    auth_kind: str   # 认证类型 (api_key / oauth_device)
    value: str       # 认证值
    source: str      # 来源描述 (env:ANTHROPIC_API_KEY / file:anthropic 等)
    state: str = "configured"  # 状态
```

---

## 3. 数据模型

### 3.1 配置解析优先级

```
┌──────────────────────────────────────────────┐
│  优先级 1 (最高): CLI 参数                      │
│  --model sonnet --permission-mode full_auto   │
├──────────────────────────────────────────────┤
│  优先级 2: 环境变量                              │
│  ANTHROPIC_API_KEY, OPENHARNESS_MODEL, ...    │
├──────────────────────────────────────────────┤
│  优先级 3: 配置文件                              │
│  ~/.openharness/settings.json                 │
├──────────────────────────────────────────────┤
│  优先级 4 (最低): 代码默认值                      │
│  Settings 类字段默认值                           │
└──────────────────────────────────────────────┘
```

合并流程:
1. `load_settings()` 读取 `settings.json` → Pydantic 验证 → `Settings` 实例
2. `_apply_env_overrides(settings)` 将环境变量覆盖到 Settings
3. `materialize_active_profile()` 将活跃 Profile 投影到扁平字段
4. `merge_cli_overrides(**overrides)` 将 CLI 参数覆盖并重新物化

### 3.2 Profile 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                     Settings 实例                            │
│                                                             │
│  active_profile = "claude-api"                              │
│  profiles = {                                               │
│    "claude-api": ProviderProfile(provider="anthropic", ...),│
│    "openai-compatible": ProviderProfile(provider="openai",),│
│    ...                                                      │
│  }                                                          │
│                                                             │
│  # 扁平字段 (legacy, 从 Profile 物化而来):                    │
│  model = "claude-sonnet-4-6"                                │
│  provider = "anthropic"                                     │
│  api_format = "anthropic"                                   │
│  base_url = None                                            │
└─────────────────────────────────────────────────────────────┘
           │
           │  materialize_active_profile()
           ▼
  将 profiles["claude-api"] 的字段投影到扁平字段:
  provider ← profile.provider
  api_format ← profile.api_format
  base_url ← profile.base_url
  model ← resolve_model_setting(profile.resolved_model, ...)
```

### 3.3 内置 Profile 目录

| Profile 名称 | Label | Provider | API Format | Auth Source | Default Model |
|--------------|-------|----------|------------|-------------|---------------|
| `claude-api` | Anthropic-Compatible API | `anthropic` | `anthropic` | `anthropic_api_key` | `claude-sonnet-4-6` |
| `claude-subscription` | Claude Subscription | `anthropic_claude` | `anthropic` | `claude_subscription` | `claude-sonnet-4-6` |
| `openai-compatible` | OpenAI-Compatible API | `openai` | `openai` | `openai_api_key` | `gpt-5.4` |
| `codex` | Codex Subscription | `openai_codex` | `openai` | `codex_subscription` | `gpt-5.4` |
| `copilot` | GitHub Copilot | `copilot` | `copilot` | `copilot_oauth` | `gpt-5.4` |
| `moonshot` | Moonshot (Kimi) | `moonshot` | `openai` | `moonshot_api_key` | `kimi-k2.5` |
| `gemini` | Google Gemini | `gemini` | `openai` | `gemini_api_key` | `gemini-2.5-flash` |

### 3.4 模型别名解析表

| 用户设置 | Claude Provider 解析结果 |
|----------|-------------------------|
| `default` | `claude-sonnet-4-6` |
| `best` | `claude-opus-4-6` |
| `sonnet` | `claude-sonnet-4-6` |
| `opus` | `claude-opus-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `sonnet[1m]` | `claude-sonnet-4-6[1m]` |
| `opus[1m]` | `claude-opus-4-6[1m]` |
| `opusplan` | PLAN 模式: `claude-opus-4-6`; 其他: `claude-sonnet-4-6` |
| `anthropic/claude.sonnet.4.6` | `claude-sonnet-4-6` (去前缀 + 点转连字符) |

### 3.5 Auth Source 到 Provider 映射

| Auth Source | Storage Provider |
|------------|-----------------|
| `anthropic_api_key` | `anthropic` |
| `openai_api_key` | `openai` |
| `codex_subscription` | `openai_codex` |
| `claude_subscription` | `anthropic_claude` |
| `copilot_oauth` | `copilot` |
| `moonshot_api_key` | `moonshot` |
| `gemini_api_key` | `gemini` |
| `dashscope_api_key` | `dashscope` |
| `bedrock_api_key` | `bedrock` |
| `vertex_api_key` | `vertex` |

### 3.6 路径解析模型

```
~/.openharness/                           ← get_config_dir()
├── settings.json                         ← get_config_file_path()
├── credentials.json                      ← 凭证存储 (auth/storage.py)
├── copilot_auth.json                     ← Copilot OAuth (SENSITIVE_PATH_PATTERNS 保护)
├── data/                                 ← get_data_dir()
│   ├── sessions/                         ← get_sessions_dir()
│   ├── tasks/                            ← get_tasks_dir()
│   ├── feedback/                         ← get_feedback_dir()
│   │   └── feedback.log                  ← get_feedback_log_path()
│   └── cron_jobs.json                    ← get_cron_registry_path()
├── logs/                                 ← get_logs_dir()
└── <project>/.openharness/              ← get_project_config_dir(cwd)
    ├── issue.md                          ← get_project_issue_file(cwd)
    └── pr_comments.md                    ← get_project_pr_comments_file(cwd)
```

### 3.7 Schema 兼容模型 (config/schema.py)

`schema.py` 定义了多通道集成的 Pydantic 模型, 独立于主 `Settings` 体系, 采用 `extra="allow"` 容忍适配器额外字段:

```
Config
├── channels: ChannelConfigs
│   ├── send_progress: bool = True
│   ├── send_tool_hints: bool = True
│   ├── telegram: TelegramConfig (token, chat_id)
│   ├── slack: SlackConfig (bot_token, app_token, signing_secret)
│   ├── discord: DiscordConfig (token)
│   ├── feishu: FeishuConfig (app_id, app_secret, encrypt_key, verification_token)
│   ├── dingtalk: DingTalkConfig (client_id, client_secret, robot_code)
│   ├── email: EmailConfig (smtp_host, smtp_port, smtp_username, smtp_password, from_address)
│   ├── qq: QQConfig (token, app_id, app_secret)
│   ├── matrix: MatrixConfig (homeserver, access_token, user_id)
│   ├── whatsapp: WhatsAppConfig (access_token, phone_number_id, verify_token)
│   └── mochat: MochatConfig (endpoint, token)
└── providers: ProviderConfigs
    └── groq: ProviderApiKeyConfig (api_key)
```

每个通道配置继承 `BaseChannelConfig` (`enabled: bool`, `allow_from: list[str]`)。

---

## 4. 关键算法

### 4.1 配置解析与合并算法

```
load_settings(config_path=None)
│
├── config_path 为 None → get_config_file_path() 获取默认路径
│
├── 配置文件存在?
│   ├── 是 → json.loads() → Settings.model_validate(raw)
│   │       ├── raw 缺少 profiles/active_profile?
│   │       │   └── _profile_from_flat_settings(settings) 推断并填充
│   │       └── _apply_env_overrides(settings.materialize_active_profile())
│   │
│   └── 否 → _apply_env_overrides(Settings().materialize_active_profile())
│           (使用纯默认值 + 环境变量覆盖)
│
└── 返回 Settings 实例
```

### 4.2 环境变量覆盖算法

`_apply_env_overrides(settings)` 逐项检查环境变量, 仅覆盖非空值:

| 环境变量 | 覆盖字段 | 类型转换 |
|----------|----------|----------|
| `ANTHROPIC_MODEL` / `OPENHARNESS_MODEL` | `model` | strip_ansi_escape_sequences() |
| `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` / `OPENHARNESS_BASE_URL` | `base_url` | 直传 |
| `OPENHARNESS_MAX_TOKENS` | `max_tokens` | `int()` |
| `OPENHARNESS_TIMEOUT` | `timeout` | `float()` |
| `OPENHARNESS_MAX_TURNS` | `max_turns` | `int()` |
| `OPENHARNESS_CONTEXT_WINDOW_TOKENS` | `context_window_tokens` | `int()` |
| `OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` | `auto_compact_threshold_tokens` | `int()` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | `api_key` | 直传 |
| `OPENHARNESS_API_FORMAT` | `api_format` | 直传 |
| `OPENHARNESS_PROVIDER` | `provider` | 直传 |
| `OPENHARNESS_SANDBOX_ENABLED` | `sandbox.enabled` | `_parse_bool_env()` |
| `OPENHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | `sandbox.fail_if_unavailable` | `_parse_bool_env()` |
| `OPENHARNESS_SANDBOX_BACKEND` | `sandbox.backend` | 直传 |
| `OPENHARNESS_SANDBOX_DOCKER_IMAGE` | `sandbox.docker.image` | 直传 |

布尔解析: `"1"`, `"true"`, `"yes"`, `"on"` (不区分大小写) → `True`; 其余 → `False`。

### 4.3 CLI 覆盖与 Profile 同步算法

```
merge_cli_overrides(**overrides)
│
├── 过滤: 仅保留值非 None 的覆盖项
├── 对 model 字段: strip_ansi_escape_sequences()
├── model_copy(update=updates) → merged
│
├── 覆盖项涉及 Profile 相关字段?
│   ├── 不涉及 → 返回 merged
│   ├── 仅 active_profile → materialize_active_profile()
│   └── 涉及 provider/model/base_url 等 →
│       sync_active_profile_from_flat_fields()
│       .materialize_active_profile()
│
└── 返回最终 Settings 实例
```

**Profile 相关字段集合**: `model`, `base_url`, `api_format`, `provider`, `api_key`, `active_profile`, `profiles`, `context_window_tokens`, `auto_compact_threshold_tokens`。

### 4.4 Profile 物化算法 (materialize_active_profile)

```
materialize_active_profile()
│
├── resolve_profile() → (profile_name, profile)
│
├── 解析模型: profile.last_model or profile.default_model
│   → resolve_model_setting(configured_model, profile.provider,
│                          default_model=profile.default_model,
│                          permission_mode=self.permission.mode.value)
│
└── model_copy(update={
       active_profile: profile_name,
       profiles: merged_profiles(),
       provider: profile.provider,
       api_format: profile.api_format,
       base_url: profile.base_url,
       context_window_tokens: profile.context_window_tokens,
       auto_compact_threshold_tokens: profile.auto_compact_threshold_tokens,
       model: resolved_model,
   })
```

### 4.5 Profile 反向同步算法 (sync_active_profile_from_flat_fields)

```
sync_active_profile_from_flat_fields()
│
├── resolve_profile() → (profile_name, profile)
│
├── 计算覆盖值:
│   next_provider ← self.provider or profile.provider
│   next_api_format ← self.api_format or profile.api_format
│   next_base_url ← self.base_url (None 则取 profile.base_url)
│   next_context_window_tokens ← self 值 or profile 值
│   next_auto_compact_threshold_tokens ← self 值 or profile 值
│
├── 模型冲突检测:
│   flat_model ← self.model
│   resolved_profile_model ← profile 的解析模型
│   next_model ← (flat_model != resolved_profile_model) ? flat_model : profile.last_model
│
├── Auth source 重新推断:
│   当前 auth_source 为默认值 → 根据 next_provider + next_api_format 重新推断
│   否则保留原值
│
├── 更新 Profile: profile.model_copy(update={上述覆盖值})
├── 更新 profiles 字典: merged_profiles[profile_name] = updated_profile
│
└── model_copy(update={active_profile, profiles})
```

### 4.6 认证解析算法 (resolve_auth)

```
resolve_auth()
│
├── resolve_profile() → (profile_name, profile)
│
├── auth_source ∈ {"codex_subscription", "claude_subscription"}?
│   ├── claude_subscription + 第三方 Anthropic 端点 → ValueError
│   ├── load_external_binding(provider_name) → None? → ValueError
│   └── load_external_credential(binding, refresh_if_needed=...) → ResolvedAuth
│
├── auth_source == "copilot_oauth"?
│   └── ResolvedAuth(provider="copilot", auth_kind="oauth_device", ...)
│
├── profile.credential_slot 存在?
│   ├── load_credential(f"profile:{slot}", "api_key", use_keyring=False)
│   ├── 未找到 → load_credential(f"profile:{slot}", "api_key") (keyring)
│   └── 找到 → ResolvedAuth(auth_kind="api_key", source="file:profile:{slot}")
│
├── 环境变量查找:
│   auth_source → env_var 映射:
│     anthropic_api_key → ANTHROPIC_API_KEY
│     openai_api_key → OPENAI_API_KEY
│     dashscope_api_key → DASHSCOPE_API_KEY
│     moonshot_api_key → MOONSHOT_API_KEY
│   └── 找到 → ResolvedAuth(source="env:{env_var}")
│
├── 显式 api_key (非 credential_slot 时)?
│   └── ResolvedAuth(source="settings_or_env")
│
├── 文件/Keyring 存储:
│   load_credential(storage_provider, "api_key")
│   └── 找到 → ResolvedAuth(source="file:{provider}")
│
└── 以上均失败 → ValueError("No credentials found for auth source '{auth_source}'")
```

### 4.7 权限 9 级决策链算法

```
evaluate(tool_name, is_read_only, file_path, command)
│
│  ① 敏感路径硬保护 (不可覆盖)
│  file_path 非空?
│  └── 遍历 _policy_match_paths(file_path)
│      遍历 SENSITIVE_PATH_PATTERNS
│      fnmatch(candidate, pattern) 匹配?
│      └── 返回 PermissionDecision(allowed=False,
│           reason="Access denied: ... sensitive credential path")
│
│  ② 工具黑名单
│  tool_name ∈ denied_tools?
│  └── 返回 PermissionDecision(allowed=False, reason="... explicitly denied")
│
│  ③ 工具白名单
│  tool_name ∈ allowed_tools?
│  └── 返回 PermissionDecision(allowed=True, reason="... explicitly allowed")
│
│  ④ 路径 deny 规则
│  file_path 非空 且 path_rules 非空?
│  └── 遍历 _policy_match_paths(file_path)
│      遍历 path_rules
│      fnmatch(candidate, rule.pattern) 匹配 且 rule.allow == False?
│      └── 返回 PermissionDecision(allowed=False, reason="Path ... deny rule")
│
│  ⑤ 命令 deny 模式
│  command 非空?
│  遍历 denied_commands
│  fnmatch(command, pattern) 匹配?
│  └── 返回 PermissionDecision(allowed=False, reason="Command matches deny pattern")
│
│  ⑥ FULL_AUTO 模式
│  mode == FULL_AUTO?
│  └── 返回 PermissionDecision(allowed=True, reason="Auto mode allows all tools")
│
│  ⑦ 只读工具放行
│  is_read_only == True?
│  └── 返回 PermissionDecision(allowed=True, reason="read-only tools are allowed")
│
│  ⑧ PLAN 模式阻断
│  mode == PLAN?
│  └── 返回 PermissionDecision(allowed=False,
│       reason="Plan mode blocks mutating tools")
│
│  ⑨ DEFAULT 模式确认
│  └── 返回 PermissionDecision(allowed=False, requires_confirmation=True,
│       reason="Mutating tools require user confirmation in default mode. ...")
```

### 4.8 路径策略匹配算法 (_policy_match_paths)

```
_policy_match_paths(file_path)
│
├── normalized = file_path.rstrip("/")
├── normalized 为空? → 返回 (file_path,)
└── 返回 (normalized, normalized + "/")
    # 追加 "/" 使目录路径本身也能匹配 "*/.ssh/*" 等目录模式
```

**设计意图**: 目录级工具 (grep, glob) 可能以目录根 (如 `/home/user/.ssh`) 作为操作目标。追加尾部斜杠使 `fnmatch("/home/user/.ssh/", "*/.ssh/*")` 能匹配, 从而阻止对敏感目录根的访问。

### 4.9 持久化安全算法

```
save_settings(settings, config_path=None)
│
├── config_path 为 None → get_config_file_path()
│
├── sync_active_profile_from_flat_fields()
│   .materialize_active_profile()
│   → 确保扁平字段与 Profile 一致
│
├── lock_path = config_path.with_suffix(".json.lock")
│
├── with exclusive_file_lock(lock_path):
│   │  # 排他文件锁: POSIX 用 fcntl.flock, Windows 用 msvcrt.locking
│   │  # 保证多进程并发写安全
│   │
│   └── atomic_write_text(
│           config_path,
│           settings.model_dump_json(indent=2) + "\n",
│       )
│       # 原子写: temp文件 + flush + fsync + os.replace
│       # 保证崩溃不丢失, 读者永远看到完整文件
│
└── 完成
```

### 4.10 Profile 名称推断算法

```
_infer_profile_name_from_flat_settings(settings)
│
├── provider == "openai_codex" → "codex"
├── provider == "anthropic_claude" → "claude-subscription"
├── provider == "copilot" or api_format == "copilot" → "copilot"
├── provider == "openai" and no base_url → "openai-compatible"
├── provider == "anthropic" and no base_url → "claude-api"
├── base_url 非空 → _slugify_profile_name(Path(base_url).name or base_url)
├── provider 非空 → _slugify_profile_name(provider)
└── 否则 → "claude-api"
```

`_slugify_profile_name()`: 非字母数字字符替换为 `-`, 连续 `-` 合并, 转小写, 空结果回退 `"custom"`。

---

## 5. 接口规范

### 5.1 config/settings.py 公开接口

#### load_settings

```python
def load_settings(config_path: Path | None = None) -> Settings
```

- **功能**: 加载配置文件并合并默认值与环境变量覆盖
- **参数**: `config_path` — 配置文件路径, None 则使用默认位置
- **返回**: 已物化活跃 Profile 的 Settings 实例
- **副作用**: 无
- **异常**: 文件格式错误时 Pydantic ValidationError; JSON 解析错误时 json.JSONDecodeError

#### save_settings

```python
def save_settings(settings: Settings, config_path: Path | None = None) -> None
```

- **功能**: 持久化 Settings 到磁盘
- **参数**: `settings` — 待保存的 Settings; `config_path` — 目标路径, None 则使用默认位置
- **副作用**: 写入文件, 获取排他文件锁
- **异常**: 文件系统 I/O 错误; 文件锁不可用时 SwarmLockUnavailableError

#### resolve_model_setting

```python
def resolve_model_setting(
    model_setting: str,
    provider: str,
    *,
    default_model: str | None = None,
    permission_mode: str | None = None,
) -> str
```

- **功能**: 将用户可见的模型设置解析为运行时模型 ID
- **参数**: `model_setting` — 用户设置值; `provider` — Provider 标识; `default_model` — 回退默认模型; `permission_mode` — 当前权限模式 (影响 opusplan 别名)
- **返回**: 具体模型 ID 字符串
- **副作用**: 无

#### strip_ansi_escape_sequences

```python
def strip_ansi_escape_sequences(text: str) -> str
```

- **功能**: 移除文本中的 ANSI 转义序列 (防止终端格式化代码污染 API 请求)
- **参数**: `text` — 输入文本
- **返回**: 清理后的文本

#### default_provider_profiles

```python
def default_provider_profiles() -> dict[str, ProviderProfile]
```

- **功能**: 返回内置 Provider Profile 目录 (每次调用返回新实例)
- **返回**: `{profile_name: ProviderProfile}` 字典

### 5.2 config/paths.py 公开接口

| 函数 | 签名 | 返回 | 副作用 |
|------|------|------|--------|
| `get_config_dir()` | `() → Path` | 配置目录路径 | 自动创建目录 |
| `get_config_file_path()` | `() → Path` | settings.json 路径 | 无 |
| `get_data_dir()` | `() → Path` | 数据目录路径 | 自动创建目录 |
| `get_logs_dir()` | `() → Path` | 日志目录路径 | 自动创建目录 |
| `get_sessions_dir()` | `() → Path` | 会话存储目录 | 自动创建目录 |
| `get_tasks_dir()` | `() → Path` | 后台任务目录 | 自动创建目录 |
| `get_feedback_dir()` | `() → Path` | 反馈目录 | 自动创建目录 |
| `get_feedback_log_path()` | `() → Path` | feedback.log 路径 | 无 |
| `get_cron_registry_path()` | `() → Path` | cron_jobs.json 路径 | 无 |
| `get_project_config_dir(cwd)` | `(str|Path) → Path` | 项目级 .openharness 目录 | 自动创建目录 |
| `get_project_issue_file(cwd)` | `(str|Path) → Path` | 项目级 issue.md 路径 | 无 |
| `get_project_pr_comments_file(cwd)` | `(str|Path) → Path` | 项目级 pr_comments.md 路径 | 无 |

### 5.3 permissions/checker.py 公开接口

#### PermissionChecker.\_\_init\_\_

```python
def __init__(self, settings: PermissionSettings) -> None
```

- **功能**: 构造权限检查器, 解析 path_rules 为 PathRule 列表
- **参数**: `settings` — 权限配置
- **副作用**: 无 (path_rules 解析为内部列表)
- **异常**: 无 (无效 rule 记录 warning 并跳过)

#### PermissionChecker.evaluate

```python
def evaluate(
    self,
    tool_name: str,
    *,
    is_read_only: bool,
    file_path: str | None = None,
    command: str | None = None,
) -> PermissionDecision
```

- **功能**: 执行 9 级决策链判定工具调用权限
- **参数**: `tool_name` — 工具名称; `is_read_only` — 是否只读; `file_path` — 涉及的文件路径; `command` — Shell 命令 (bash 工具)
- **返回**: `PermissionDecision(allowed, requires_confirmation, reason)`
- **副作用**: 无
- **异常**: 无

### 5.4 config/schema.py 公开接口

`schema.py` 导出 `Config` 类作为通道配置的入口模型。通道适配器通过 `Config.model_validate(raw_data)` 加载, 所有子模型均允许 `extra` 字段以适配不同通道的扩展参数。

---

## 6. 错误处理

### 6.1 配置加载错误

| 场景 | 异常类型 | 处理策略 |
|------|----------|----------|
| settings.json 格式错误 | `json.JSONDecodeError` | 向上传播, CLI 层显示友好错误信息 |
| 字段验证失败 | `pydantic.ValidationError` | 向上传播, 标注具体字段与错误原因 |
| 配置文件不存在 | — | 静默使用默认值, 不抛异常 |
| 环境变量类型转换失败 | `ValueError` / `TypeError` | `_apply_env_overrides` 中 int()/float() 可能抛出, 由调用方捕获 |

### 6.2 认证解析错误

| 场景 | 异常类型 | 错误信息 |
|------|----------|----------|
| 无 API 密钥 | `ValueError` | "No API key found. Set ANTHROPIC_API_KEY..." |
| Claude 订阅 + 第三方端点 | `ValueError` | "Claude subscription auth only supports direct Anthropic/Claude endpoints..." |
| 无外部认证绑定 | `ValueError` | "No external auth binding found for {auth_source}. Run 'oh auth ...' first." |
| 无凭证 | `ValueError` | "No credentials found for auth source '{auth_source}'..." |
| Claude 订阅 Provider 调用 resolve_api_key() | `ValueError` | "Current provider uses Anthropic auth tokens instead of API keys..." |

### 6.3 权限检查错误

权限检查**不抛异常**。所有判定结果通过 `PermissionDecision` 返回:

- `allowed=True` → 直接执行
- `allowed=False, requires_confirmation=True` → 弹出用户确认框
- `allowed=False, requires_confirmation=False` → 返回 `ToolResultBlock(is_error=True)`

### 6.4 持久化错误

| 场景 | 异常类型 | 处理策略 |
|------|----------|----------|
| 磁盘满 / 权限不足 | `OSError` | `atomic_write_text` 中 temp 文件写失败 → 删除临时文件 → 向上传播 |
| 跨文件系统 rename | `OSError` | `tempfile.mkstemp(dir=dst.parent)` 确保同目录, 避免 |
| 文件锁不可用 | `SwarmLockUnavailableError` | 不支持的平台 (罕见), 向上传播 |
| 文件锁竞争 | — | `fcntl.LOCK_EX` / `msvcrt.LK_LOCK` 阻塞等待, 不超时 |

### 6.5 无效 PathRule 处理

`PermissionChecker.__init__` 中遍历 `settings.path_rules`, 对缺少 `pattern` 字段或 pattern 为空字符串的规则记录 `log.warning` 并跳过, 不抛异常。这容忍了旧版配置文件中可能存在的不规范规则。

---

## 7. 配置项

### 7.1 Settings 字段默认值一览

#### API 配置

| 字段 | 类型 | 默认值 | 环境变量 |
|------|------|--------|----------|
| `api_key` | `str` | `""` | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |
| `model` | `str` | `"claude-sonnet-4-6"` | `ANTHROPIC_MODEL` / `OPENHARNESS_MODEL` |
| `max_tokens` | `int` | `16384` | `OPENHARNESS_MAX_TOKENS` |
| `base_url` | `str \| None` | `None` | `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` / `OPENHARNESS_BASE_URL` |
| `timeout` | `float` | `30.0` | `OPENHARNESS_TIMEOUT` |
| `context_window_tokens` | `int \| None` | `None` | `OPENHARNESS_CONTEXT_WINDOW_TOKENS` |
| `auto_compact_threshold_tokens` | `int \| None` | `None` | `OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` |
| `api_format` | `str` | `"anthropic"` | `OPENHARNESS_API_FORMAT` |
| `provider` | `str` | `""` | `OPENHARNESS_PROVIDER` |
| `active_profile` | `str` | `"claude-api"` | — |
| `profiles` | `dict[str, ProviderProfile]` | 7 个内置 Profile | — |
| `max_turns` | `int` | `200` | `OPENHARNESS_MAX_TURNS` |

#### 行为配置

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `system_prompt` | `str \| None` | `None` |
| `permission` | `PermissionSettings` | `mode=DEFAULT, 空列表` |
| `hooks` | `dict[str, list[HookDefinition]]` | `{}` |
| `memory` | `MemorySettings` | `enabled=True, max_files=5, max_entrypoint_lines=200` |
| `sandbox` | `SandboxSettings` | `enabled=False, backend="srt"` |
| `enabled_plugins` | `dict[str, bool]` | `{}` |
| `mcp_servers` | `dict[str, McpServerConfig]` | `{}` |

#### UI 配置

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `theme` | `str` | `"default"` |
| `output_style` | `str` | `"default"` |
| `vim_mode` | `bool` | `False` |
| `voice_mode` | `bool` | `False` |
| `fast_mode` | `bool` | `False` |
| `effort` | `str` | `"medium"` |
| `passes` | `int` | `1` |
| `verbose` | `bool` | `False` |

### 7.2 路径配置环境变量

| 环境变量 | 覆盖目标 | 默认值 |
|----------|----------|--------|
| `OPENHARNESS_CONFIG_DIR` | 配置根目录 | `~/.openharness/` |
| `OPENHARNESS_DATA_DIR` | 数据目录 | `~/.openharness/data/` |
| `OPENHARNESS_LOGS_DIR` | 日志目录 | `~/.openharness/logs/` |

### 7.3 沙箱配置环境变量

| 环境变量 | 覆盖字段 | 类型 |
|----------|----------|------|
| `OPENHARNESS_SANDBOX_ENABLED` | `sandbox.enabled` | bool |
| `OPENHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | `sandbox.fail_if_unavailable` | bool |
| `OPENHARNESS_SANDBOX_BACKEND` | `sandbox.backend` | str |
| `OPENHARNESS_SANDBOX_DOCKER_IMAGE` | `sandbox.docker.image` | str |

### 7.4 敏感路径保护模式 (不可覆盖)

```
SENSITIVE_PATH_PATTERNS = (
    "*/.ssh/*",                         # SSH 密钥和配置
    "*/.aws/credentials",               # AWS 凭证
    "*/.aws/config",                    # AWS 配置
    "*/.config/gcloud/*",               # GCP 凭证
    "*/.azure/*",                       # Azure 凭证
    "*/.gnupg/*",                        # GPG 密钥
    "*/.docker/config.json",            # Docker 凭证
    "*/.kube/config",                   # Kubernetes 凭证
    "*/.openharness/credentials.json",  # OpenHarness 凭证
    "*/.openharness/copilot_auth.json", # Copilot OAuth 凭证
)
```

这些模式使用 `fnmatch` 语法, 匹配完全解析后的绝对路径。即使 `FULL_AUTO` 模式或用户白名单也无法覆盖此保护。

---

## 8. 与其它模块的交互

### 8.1 与 ui/runtime.py 的交互

`ui/runtime.py` 的 `build_runtime()` 是配置模块的主要消费者:

```
build_runtime()
│
├── load_settings() → Settings
│   (配置加载 + 环境变量覆盖 + Profile 物化)
│
├── _resolve_api_client(settings)
│   ├── settings.resolve_auth() → ResolvedAuth
│   └── 根据 provider + api_format 创建对应 API 客户端
│
├── PermissionChecker(settings.permission)
│   (传入 PermissionSettings 构造权限检查器)
│
├── build_runtime_system_prompt(settings, ...)
│   (读取 settings.system_prompt, settings.fast_mode, settings.effort 等)
│
└── RuntimeBundle(api_client, engine, ..., permission_checker, ...)
```

**运行时热生效**:
```
settings 修改 → save_settings() → CommandResult(refresh_runtime=True)
    → refresh_runtime_client() → 重建 RuntimeBundle
      (API Client, PermissionChecker, HookExecutor 等全部重建)
```

### 8.2 与 auth/ 模块的交互

`Settings.resolve_auth()` 延迟导入 `auth.storage` 和 `auth.external`:

```python
from openharness.auth.storage import load_credential, load_external_binding
from openharness.auth.external import load_external_credential, is_third_party_anthropic_endpoint
```

依赖链:
- `resolve_auth()` → `load_credential(storage_provider, "api_key")` (文件/Keyring 双后端)
- `resolve_auth()` → `load_external_binding(provider_name)` (外部认证绑定)
- `resolve_auth()` → `load_external_credential(binding)` (OAuth/订阅凭证)

### 8.3 与 engine/ 模块的交互

Agent Loop (`engine/query.py`) 在工具执行管道中调用 `PermissionChecker.evaluate()`:

```
_execute_tool_call(context, tool_call)
│
├── ...
├── permission_checker.evaluate(
│       tool_name=tool_call.name,
│       is_read_only=tool.is_read_only(parsed_input),
│       file_path=parsed_input.file_path (如有),
│       command=parsed_input.command (如有),
│   ) → PermissionDecision
│
├── allowed → 执行工具
├── requires_confirmation → 弹出确认框, 用户批准则执行
└── denied → ToolResultBlock(is_error=True, content=decision.reason)
```

### 8.4 与 hooks/ 模块的交互

`Settings.hooks` 字段存储 Hook 配置 (`dict[str, list[HookDefinition]]`), 由 `HookExecutor` 在运行时读取:

- `PreToolUse` Hook 在权限检查前执行, 可阻断工具调用
- `PostToolUse` Hook 在工具执行后执行
- Hook 修改 Settings 后通过 `save_settings()` 持久化

### 8.5 与 sandbox/ 模块的交互

`Settings.sandbox` (SandboxSettings) 被沙箱系统读取:

- `sandbox.enabled` → 决定工具是否路由到沙箱
- `sandbox.docker.image` → Docker 沙箱镜像名
- `sandbox.network.allowed_domains` → 网络 ACL
- `sandbox.filesystem` → 文件系统 ACL
- Shell 工具调用 `create_shell_subprocess()` 时检查 `sandbox.enabled`

### 8.6 与 mcp/ 模块的交互

`Settings.mcp_servers` (`dict[str, McpServerConfig]`) 存储用户配置的 MCP 服务器连接信息, 由 `McpClientManager` 在运行时读取并建立连接。

### 8.7 与 commands/ 模块的交互

斜杠命令通过 `CommandResult(refresh_runtime=True)` 触发配置热生效:

- `/permissions full_auto` → 修改 `settings.permission.mode` → `save_settings()` → 刷新运行时
- `/model opus` → 修改 `settings.model` → `merge_cli_overrides()` → `save_settings()`
- `/provider use moonshot` → 修改 `settings.active_profile` → 物化 → 保存

### 8.8 与 memory/ 模块的交互

`Settings.memory` (MemorySettings) 控制:
- `enabled` → 是否启用项目级持久记忆
- `max_files` → 最大记忆文件数
- `max_entrypoint_lines` → CLAUDE.md 最大行数
- `context_window_tokens` / `auto_compact_threshold_tokens` → 可覆盖全局值

### 8.9 与 services/ 模块的交互

上下文压缩服务读取 `Settings` 的以下字段:
- `context_window_tokens` → 上下文窗口大小估算
- `auto_compact_threshold_tokens` → 自动压缩触发阈值
- 两者可从全局 Settings 或活跃 Profile 获取 (Profile 级覆盖优先)

### 8.10 与 utils/ 模块的交互

配置与权限模块是 `utils/` 的重要消费者:

| 工具 | 消费者 | 用途 |
|------|--------|------|
| `atomic_write_text` | `save_settings()` | 原子写入配置文件 |
| `exclusive_file_lock` | `save_settings()` | 排他文件锁防止并发写 |
| `_policy_match_paths` | `PermissionChecker.evaluate()` | 路径规范化 (内部函数) |

### 8.11 与 config/__init__.py 的交互

`config/__init__.py` 作为包入口, 重新导出最常用的接口:

```python
__all__ = [
    "ProviderProfile",
    "Settings",
    "auth_source_provider_name",
    "default_auth_source_for_provider",
    "default_provider_profiles",
    "get_config_dir",
    "get_config_file_path",
    "get_data_dir",
    "get_logs_dir",
    "load_settings",
    "save_settings",
]
```

外部模块通过 `from openharness.config import load_settings, Settings` 导入, 无需关心内部文件结构。

### 8.12 与 permissions/__init__.py 的交互

`permissions/__init__.py` 使用延迟导入 (`__getattr__`), 避免模块加载时触发 `PermissionChecker` 对 `PermissionSettings` 的导入:

```python
def __getattr__(name: str):
    if name in {"PermissionChecker", "PermissionDecision"}:
        from openharness.permissions.checker import ...
    if name == "PermissionMode":
        from openharness.permissions.modes import PermissionMode
```

这使得 `from openharness.permissions import PermissionMode` 在不需要 Checker 的场景下避免了循环依赖风险。

---

## 附录 A: 敏感路径保护设计哲学

敏感路径保护是 OpenHarness 安全架构的核心纵深防御措施, 设计上具有以下不可妥协特性:

1. **不可覆盖**: 即使 `FULL_AUTO` 模式、用户白名单 (`allowed_tools`)、路径允许规则 (`path_rules`) 均无法绕过敏感路径保护。这是 9 级决策链的第 1 级, 最先执行。
2. **硬编码**: `SENSITIVE_PATH_PATTERNS` 是模块级常量元组, 不从配置文件读取, 不可通过 settings.json 修改。
3. **覆盖范围**: SSH 密钥、AWS/GCP/Azure 凭证、GPG 密钥环、Docker 配置、Kubernetes 配置、OpenHarness 自身凭证存储。
4. **防御目标**: 防止 LLM 通过 prompt injection 或指令跟随间接读取/泄露用户的高价值凭证文件。

## 附录 B: Profile 双向同步机制

OpenHarness 的 Settings 模型同时存在"扁平字段" (如 `self.model`) 和"结构化字段" (如 `self.profiles["claude-api"].last_model`)。双向同步保证两者一致性:

**正向 (Profile → 扁平)**: `materialize_active_profile()` 将活跃 Profile 的字段投影到扁平字段。在 `load_settings()` 和 `merge_cli_overrides()` 末尾自动调用。

**反向 (扁平 → Profile)**: `sync_active_profile_from_flat_fields()` 将扁平字段的修改折回活跃 Profile。在 `save_settings()` 和 `merge_cli_overrides()` (涉及 Provider 字段时) 自动调用。

```
                 materialize_active_profile()
    Profile ───────────────────────────────────→ 扁平字段
      ↑                                            │
      │          sync_active_profile_from_flat_fields()
      └────────────────────────────────────────────┘
```

**不调用同步的后果**: 如果只修改扁平字段而不调用 `sync_active_profile_from_flat_fields()`, `save_settings()` 会在持久化前自动调用, 但运行时实例内的 Profile 与扁平字段可能短暂不一致。

## 附录 C: 原子写 + 文件锁保证

```
                     时间线
  ─────────────────────────────────────────────→

  进程 A:  [获取锁] [写临时文件] [fsync] [os.replace] [释放锁]
  进程 B:              [等待锁...↓]                    [获取锁] [写临时文件] ...

  崩溃场景:
  进程 A:  [获取锁] [写临时文件(半)] ←── 崩溃!
           临时文件留在磁盘, 但 os.replace 未执行
           下次读取: 旧文件完整 → 不受影响
           临时文件: 下次 mkstemp 清理或被覆盖

  读者:    读取到 os.replace 前的旧 inode 或 replace 后的新 inode
           永远不会看到半写文件 (os.replace 是原子操作)
```