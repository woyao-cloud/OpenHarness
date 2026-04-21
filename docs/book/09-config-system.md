# 第九章：配置系统 — Pydantic 模型层级与加载链

## 概述

OpenHarness 的配置系统围绕 Pydantic 模型层级构建，覆盖了从全局设置到渠道适配器配置的完整层级。配置加载遵循严格的优先级链：CLI 参数 > 环境变量 > 配置文件 > 默认值。同时，系统使用原子写入和文件锁确保配置持久化的安全性。

Pydantic 在 Python 生态中的地位类似于 Jackson + `@ConfigurationProperties` 在 Spring Boot 中的角色——但 Pydantic 更轻量、更 Pythonic，并且天然支持数据验证。

## Java 类比

| Python 概念 | Java 对应 | 核心差异 |
|---|---|---|
| `Settings(BaseModel)` | `@ConfigurationProperties` 类 | Pydantic 自动验证+类型转换，无需手动绑定 |
| `load_settings()` 优先级链 | Spring `@PropertySource` + `@Value` | Python 显式链更清晰，Spring 靠 Bean 生命周期隐式合并 |
| `atomic_write_text()` + `exclusive_file_lock` | `Files.write()` + `FileLock` | Python 原子写入用 tmp+rename，Java 通常直接覆盖 |
| `model_validate()` | `ObjectMapper.readValue()` | Pydantic 验证+转换一体化，Jackson 需要额外 `@Valid` |
| `model_copy(update={...})` | 不可变对象无直接对应 | Pydantic 原生支持浅拷贝+更新，Java 需 Builder 模式 |
| `ConfigDict(extra="allow")` | `@JsonIgnoreProperties(ignoreUnknown=true)` | Pydantic 正向：允许未知字段；Jackson 反向：忽略未知字段 |

> **Java 对比**
>
> Spring Boot 的配置绑定靠反射和 Bean 后处理器完成，开发者写 `@Value("${app.model}")` 依赖 Spring 容器。Pydantic 的配置绑定是纯数据层的——不需要容器，不需要注解扫描，`Settings.model_validate(raw_dict)` 一行搞定。而且 Pydantic 的错误消息非常友好：如果 `max_tokens` 传了 `"abc"`，你会得到 `Input should be a valid integer, unable to parse string as an integer [type=int_parsing]`，而不是 Spring 启动时的 `NumberFormatException` 堆栈。

## 项目代码详解

### 1. Settings 模型层级 — 深层嵌套的 Pydantic 模型

`config/settings.py` 中的 `Settings` 类是一个包含数十个字段的根模型，嵌套了多个子模型：

```python
class Settings(BaseModel):
    """OpenHarness 主设置模型。"""

    # API 配置
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 16384
    base_url: str | None = None
    timeout: float = 30.0
    context_window_tokens: int | None = None
    auto_compact_threshold_tokens: int | None = None
    api_format: str = "anthropic"
    provider: str = ""
    active_profile: str = "claude-api"
    profiles: dict[str, ProviderProfile] = Field(default_factory=default_provider_profiles)
    max_turns: int = 200

    # 行为配置
    system_prompt: str | None = None
    permission: PermissionSettings = Field(default_factory=PermissionSettings)
    hooks: dict[str, list[HookDefinition]] = Field(default_factory=dict)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    enabled_plugins: dict[str, bool] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    # UI 配置
    theme: str = "default"
    output_style: str = "default"
    vim_mode: bool = False
    voice_mode: bool = False
    fast_mode: bool = False
    effort: str = "medium"
    passes: int = 1
    verbose: bool = False
```

嵌套子模型展示：

```python
class PermissionSettings(BaseModel):
    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    path_rules: list[PathRuleConfig] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)

class SandboxSettings(BaseModel):
    enabled: bool = False
    backend: str = "srt"
    fail_if_unavailable: bool = False
    network: SandboxNetworkSettings = Field(default_factory=SandboxNetworkSettings)
    filesystem: SandboxFilesystemSettings = Field(default_factory=SandboxFilesystemSettings)
    docker: DockerSandboxSettings = Field(default_factory=DockerSandboxSettings)
```

> **Java 对比**
>
> 这对应 Spring Boot 中的 `@ConfigurationProperties` 嵌套类：
>
> ```java
> @ConfigurationProperties(prefix = "openharness")
> public class Settings {
>     private String model = "claude-sonnet-4-6";
>     private PermissionSettings permission = new PermissionSettings();
>     private SandboxSettings sandbox = new SandboxSettings();
>     // getter/setter...
> }
> ```
>
> 但 Pydantic 有几个 Spring 没有的优势：(1) 嵌套模型自动递归验证；(2) `Field(default_factory=...)` 确保每个实例获得独立的可变默认值，避免 Java 中常见的可变默认值共享引用 bug；(3) `model_copy(update={...})` 提供不可变式更新。

### 2. ProviderProfile — @property 计算字段

```python
class ProviderProfile(BaseModel):
    label: str
    provider: str
    api_format: str
    auth_source: str
    default_model: str
    base_url: str | None = None
    last_model: str | None = None
    credential_slot: str | None = None
    allowed_models: list[str] = Field(default_factory=list)
    context_window_tokens: int | None = None
    auto_compact_threshold_tokens: int | None = None

    @property
    def resolved_model(self) -> str:
        """返回此配置的活跃模型名称。"""
        return resolve_model_setting(
            (self.last_model or "").strip() or self.default_model,
            self.provider,
            default_model=self.default_model,
        )
```

> **Java 对比**
>
> `@property` 对应 Java 的 getter 方法，但 Python 的 `@property` 是真正的属性访问语法——`profile.resolved_model` 而不是 `profile.getResolvedModel()`。更重要的是，Pydantic 的 `@property` 不参与序列化（不是字段），而 Java 的 getter 默认会被 Jackson 序列化。如果需要序列化计算字段，Python 用 `@computed_field`（Pydantic v2.8+），Java 用 `@JsonProperty`。

### 3. 配置加载优先级链

```python
def load_settings(config_path: Path | None = None) -> Settings:
    """加载配置，优先级：CLI > 环境变量 > 配置文件 > 默认值。"""
    if config_path is None:
        from openharness.config.paths import get_config_file_path
        config_path = get_config_file_path()

    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        settings = Settings.model_validate(raw)
        if "profiles" not in raw or "active_profile" not in raw:
            profile_name, profile = _profile_from_flat_settings(settings)
            merged_profiles = settings.merged_profiles()
            merged_profiles[profile_name] = profile
            settings = settings.model_copy(
                update={"active_profile": profile_name, "profiles": merged_profiles},
            )
        return _apply_env_overrides(settings.materialize_active_profile())

    return _apply_env_overrides(Settings().materialize_active_profile())
```

环境变量覆盖逻辑：

```python
def _apply_env_overrides(settings: Settings) -> Settings:
    """应用环境变量覆盖。"""
    updates: dict[str, Any] = {}
    model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("OPENHARNESS_MODEL")
    if model:
        updates["model"] = strip_ansi_escape_sequences(model)

    base_url = (
        os.environ.get("ANTHROPIC_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENHARNESS_BASE_URL")
    )
    if base_url:
        updates["base_url"] = base_url

    # ... 更多环境变量
    if not updates:
        return settings
    return settings.model_copy(update=updates)
```

CLI 覆盖通过 `merge_cli_overrides()` 方法实现：

```python
def merge_cli_overrides(self, **overrides: Any) -> Settings:
    """返回应用 CLI 覆盖后的新 Settings（仅非 None 值）。"""
    updates = {k: v for k, v in overrides.items() if v is not None}
    if "model" in updates and isinstance(updates["model"], str):
        updates["model"] = strip_ansi_escape_sequences(updates["model"])
    merged = self.model_copy(update=updates)
    if not updates:
        return merged
    # 如果覆盖涉及配置层级字段，重新物化活跃配置
    profile_keys = {"model", "base_url", "api_format", "provider", ...}
    profile_updates = profile_keys.intersection(updates)
    if profile_updates:
        return merged.sync_active_profile_from_flat_fields().materialize_active_profile()
    return merged
```

> **Java 对比**
>
> Spring Boot 的配置优先级是框架固定的（1-17 级），开发者不能改变顺序。OpenHarness 的优先级链是显式代码实现的：`load_settings()` 先读文件，再调用 `_apply_env_overrides()`，最后由调用方通过 `merge_cli_overrides()` 覆盖。每一步都返回新的 `Settings` 对象（不可变模式），而不是在原对象上修改。

### 4. 原子写入与文件锁

```python
def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """将配置持久化到文件，使用原子写入和排他锁。"""
    if config_path is None:
        from openharness.config.paths import get_config_file_path
        config_path = get_config_file_path()

    settings = settings.sync_active_profile_from_flat_fields().materialize_active_profile()
    lock_path = config_path.with_suffix(config_path.suffix + ".lock")
    with exclusive_file_lock(lock_path):
        atomic_write_text(
            config_path,
            settings.model_dump_json(indent=2) + "\n",
        )
```

`atomic_write_text` 的实现模式：先写 `.tmp` 文件，再 `os.replace()` 原子替换。这确保了即使写入过程中断电，原文件也不会损坏。

> **Java 对比**
>
> Java 中对应的操作是 `Files.write(path, content)` 配合 `FileChannel.lock()`。但 Java 的 `FileLock` 是 JVM 级别的（同一个 JVM 内多个线程可能看不到彼此的锁），而 Python 的 `fcntl.flock()`（Linux）或 `msvcrt.locking()`（Windows）是操作系统级别的。OpenHarness 使用 `portalocker` 库来跨平台实现排他锁。

### 5. ConfigDict(extra="allow") — 前向兼容性

`config/schema.py` 中的渠道配置模型使用了 `ConfigDict(extra="allow")`：

```python
class _CompatModel(BaseModel):
    """容忍适配器特有额外字段的基模型。"""
    model_config = ConfigDict(extra="allow")

class BaseChannelConfig(_CompatModel):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["*"])

class TelegramConfig(BaseChannelConfig):
    token: str = ""
    chat_id: str | None = None

class SlackConfig(BaseChannelConfig):
    bot_token: str = ""
    app_token: str = ""
    signing_secret: str = ""
```

> **Java 对比**
>
> `ConfigDict(extra="allow")` 对应 Jackson 的 `@JsonIgnoreProperties(ignoreUnknown = true)`。但语义方向相反：Pydantic 默认**拒绝**未知字段（严格模式），`extra="allow"` 显式放宽；Jackson 默认**忽略**未知字段（宽松模式），`@JsonIgnoreProperties` 用于加严。OpenHarness 使用 `extra="allow"` 是因为渠道适配器的配置可能包含渠道特有的字段（如 Telegram 的 `chat_id`），全局模型不应因未知字段而拒绝整个配置。

### 6. 路径解析 — XDG 风格的目录层次

`config/paths.py` 实现了类 XDG 的路径解析：

```python
_DEFAULT_BASE_DIR = ".openharness"
_CONFIG_FILE_NAME = "settings.json"

def get_config_dir() -> Path:
    """返回配置目录（如不存在则创建）。
    优先级：OPENHARNESS_CONFIG_DIR 环境变量 > ~/.openharness/
    """
    env_dir = os.environ.get("OPENHARNESS_CONFIG_DIR")
    if env_dir:
        config_dir = Path(env_dir)
    else:
        config_dir = Path.home() / _DEFAULT_BASE_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_config_file_path() -> Path:
    return get_config_dir() / _CONFIG_FILE_NAME

def get_data_dir() -> Path:
    env_dir = os.environ.get("OPENHARNESS_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
    else:
        data_dir = get_config_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
```

> **Java 对比**
>
> 这对应 Spring Boot 的 `spring.config.location` 和 `spring.config.name` 属性，以及 `@DataDirectory` 注解。但 Python 版更透明：`get_config_dir()` 直接返回路径对象，不依赖框架魔法。Java 开发者常常困惑 Spring 的配置搜索顺序，而 Python 版是显式函数调用链。

### 7. strip_ansi_escape_sequences — 防御性工具函数

```python
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi_escape_sequences(text: str) -> str:
    """清除文本中的 ANSI 转义序列。
    
    环境变量可能包含终端格式化代码（如 '[1m' 表示粗体），
    这会破坏 API 请求。
    """
    if not text:
        return text
    return _ANSI_ESCAPE_PATTERN.sub("", text)
```

这个工具函数在 `load_settings()` 和 `merge_cli_overrides()` 中被用来清理模型名称等字段。Java 开发者可能觉得奇怪——为什么环境变量里会有 ANSI 转义码？答案是在某些终端工具（如 `oh` CLI）中，shell 环境变量可能从带格式的提示中继承。

## 架构图

```
+---------------------+
|    CLI Arguments     |  最高优先级
+----------+----------+
           |
           v
+---------------------+
| Environment Vars     |  ANTHROPIC_MODEL, OPENHARNESS_BASE_URL, ...
+----------+----------+
           |
           v
+---------------------+
| ~/.openharness/      |  JSON 配置文件
| settings.json        |
+----------+----------+
           |
           v
+---------------------+
| Pydantic Defaults    |  最低优先级
+---------------------+

           |
           | model_validate()
           v
+---------------------+        +---------------------+
|   Settings(BaseModel) |------>|  PermissionSettings  |
+----------+----------+        +---------------------+
           |                    +---------------------+
           |-------------------->|  SandboxSettings     |
           |                    |    network: ...       |
           |                    |    filesystem: ...     |
           |                    |    docker: ...         |
           |                    +---------------------+
           |                    +---------------------+
           |-------------------->|  MemorySettings      |
           |                    +---------------------+
           |                    +---------------------+
           +-------------------->|  ProviderProfile     |
                                |    resolved_model     |
                                |    (computed @property)|
                                +---------------------+

+---------------------+        +---------------------+
| _CompatModel        |------>|  BaseChannelConfig    |
| extra="allow"       |        +---------------------+
+---------------------+                  |
                                         v
                                +---------------------+
                                |  TelegramConfig       |
                                |  SlackConfig          |
                                |  DiscordConfig        |
                                |  FeishuConfig         |
                                |  DingTalkConfig       |
                                |  EmailConfig          |
                                |  QQConfig             |
                                |  MatrixConfig         |
                                |  WhatsAppConfig        |
                                |  MochatConfig         |
                                +---------------------+

保存路径:
  ~/.openharness/settings.json        (主配置)
  ~/.openharness/credentials.json     (凭据，mode 600)
  ~/.openharness/data/                (数据目录)
  ~/.openharness/logs/                (日志目录)
  ~/.openharness/data/sessions/       (会话存储)
```

## 小结

OpenHarness 配置系统的设计体现了 Python 的核心理念：显式优于隐式。

1. **Pydantic 模型层级**：`Settings` 包含 `PermissionSettings`、`SandboxSettings`、`MemorySettings` 等嵌套模型，每个子模型有独立默认值。这比 Spring `@ConfigurationProperties` 的反射绑定更直接、更可测试。

2. **加载优先级链**：CLI > 环境变量 > 配置文件 > 默认值，每一步都是纯函数调用，不依赖框架魔法。

3. **原子写入+排他锁**：`save_settings()` 使用 `.tmp` + `os.replace()` + `exclusive_file_lock` 三重保障，确保并发安全。

4. **ConfigDict(extra="allow")**：渠道配置的基模型允许未知字段，实现前向兼容。

5. **ProviderProfile 的 @property**：`resolved_model` 是计算字段，自动解析模型别名和上下文窗口参数。

6. **strip_ansi_escape_sequences**：防御性工具函数，清理环境变量中可能混入的终端格式化代码。

从 Java 转向 Python 配置管理的核心认知转换：**Pydantic 是数据层工具，不依赖任何容器或依赖注入框架**。你可以直接 `Settings.model_validate({"model": "abc"})` 而不需要启动 Spring 上下文。