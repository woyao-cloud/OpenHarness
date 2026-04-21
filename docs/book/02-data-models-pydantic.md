# 第二章：数据建模——Pydantic BaseModel

## 概述

在 Java 中，一个典型的数据模型需要三层支撑：

- **POJO**：定义字段和 getter/setter
- **Jackson**：JSON 序列化/反序列化
- **Bean Validation**：字段校验（`@NotNull`、`@Size` 等）

Python 的 Pydantic 将这三者合为一体。一个继承 `BaseModel` 的类同时拥有：

- 字段定义与默认值
- 自动 JSON 序列化/反序列化
- 声明式字段校验
- 不可变更新（`model_copy`）
- 类型安全的嵌套组合

本章将通过 OpenHarness 的配置模型和消息模型，深入讲解 Pydantic 的核心用法。

## Java 类比

| Java 概念 | Pydantic 对应 |
|-----------|--------------|
| POJO + getter/setter | `BaseModel` + 字段声明 |
| `@JsonProperty` | 字段名即 JSON key |
| `@JsonIgnoreProperties(ignoreUnknown=true)` | `ConfigDict(extra="allow")` |
| `ObjectMapper.readValue(json, Cls.class)` | `Cls.model_validate(json)` |
| `ObjectMapper.writeValueAsString(obj)` | `obj.model_dump_json()` |
| `new ArrayList<>()` 字段初始化 | `Field(default_factory=list)` |
| Builder 模式（不可变更新） | `model_copy(update={...})` |
| `@NotNull` / `@Size` | Pydantic 内置校验 + `field_validator` |
| Java getter 方法 `getX()` | `@property` 装饰器 |
| Jackson 多态反序列化 `@JsonTypeInfo` | `Annotated[X \| Y, Field(discriminator="type")]` |

## 项目代码详解

### 1. 基础模型：字段、类型与默认值

**`config/schema.py`——通道配置模型**

```python
from pydantic import BaseModel, ConfigDict, Field


class _CompatModel(BaseModel):
    """Base model that tolerates adapter-specific extra fields."""

    model_config = ConfigDict(extra="allow")


class BaseChannelConfig(_CompatModel):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["*"])


class TelegramConfig(BaseChannelConfig):
    token: str = ""
    chat_id: str | None = None


class ChannelConfigs(_CompatModel):
    send_progress: bool = True
    send_tool_hints: bool = True
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    # ... 其他通道
```

逐行解读：

- `enabled: bool = False`：简单类型 + 默认值，等价于 Java 的 `private boolean enabled = false;`
- `chat_id: str | None = None`：联合类型，等价于 Java 的 `@Nullable String chatId`
- `allow_from: list[str] = Field(default_factory=lambda: ["*"])`：**必须用 `default_factory`**，绝不能写 `allow_from: list[str] = ["*"]`

> **Java 对比**：Python 中 `list`、`dict` 等可变对象的默认值存在"类共享"陷阱——所有实例会共享同一个列表对象。`Field(default_factory=list)` 等价于 Java 中在构造器里 `new ArrayList<>()`，确保每个实例有独立的默认值。

```java
// Java 等价写法
public class BaseChannelConfig {
    private boolean enabled = false;
    private List<String> allowFrom = new ArrayList<>(List.of("*"));

    // getter / setter ...
}
```

对比 Pydantic 版本：

```python
# Python + Pydantic：6 行完成 Java 20+ 行的工作
class BaseChannelConfig(BaseModel):
    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
```

无需 getter/setter，无需 Jackson 注解，一行即包含类型、默认值和 JSON 映射。

### 2. `ConfigDict(extra="allow")`——容错模型

```python
class _CompatModel(BaseModel):
    model_config = ConfigDict(extra="allow")
```

这行代码的含义是：**当 JSON 中包含模型未定义的字段时，不报错，而是保留这些字段**。

> **Java 对比**：
>
> ```java
> @JsonIgnoreProperties(ignoreUnknown = true)
> public class _CompatModel { ... }
> ```
>
> 这是 Jackson 反序列化时的经典注解，防止未知字段导致 `UnrecognizedPropertyException`。Pydantic 的 `extra="allow"` 不仅忽略未知字段，还把它们保留在模型中（可通过 `model_extra` 属性访问）。

`extra` 的三个选项：

| 值 | 行为 | Java 对应 |
|----|------|----------|
| `"allow"` | 保留未知字段 | `@JsonIgnoreProperties(ignoreUnknown=false)` + 自定义逻辑 |
| `"ignore"` | 忽略未知字段 | `@JsonIgnoreProperties(ignoreUnknown=true)` |
| `"forbid"` | 未知字段报错 | 默认行为（Jackson 遇到未知字段抛异常） |

### 3. `Field(default_factory=...)`——可变默认值的安全写法

**`config/settings.py`——Settings 子模型**

```python
class PermissionSettings(BaseModel):
    """Permission mode configuration."""

    mode: PermissionMode = PermissionMode.DEFAULT
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    path_rules: list[PathRuleConfig] = Field(default_factory=list)
    denied_commands: list[str] = Field(default_factory=list)


class SandboxSettings(BaseModel):
    """Sandbox-runtime integration settings."""

    enabled: bool = False
    backend: str = "srt"
    fail_if_unavailable: bool = False
    enabled_platforms: list[str] = Field(default_factory=list)
    network: SandboxNetworkSettings = Field(default_factory=SandboxNetworkSettings)
    filesystem: SandboxFilesystemSettings = Field(default_factory=SandboxFilesystemSettings)
    docker: DockerSandboxSettings = Field(default_factory=DockerSandboxSettings)
```

> **Java 对比**：
>
> ```java
> // Java：必须在构造器中初始化可变字段
> public class PermissionSettings {
>     private List<String> allowedTools = new ArrayList<>();
>     private List<String> deniedTools = new ArrayList<>();
>     // ...
> }
> ```
>
> Python 的经典陷阱：
> ```python
> # 错误！所有实例共享同一个列表
> class Bad:
>     items: list[str] = []
>
> # 正确：每次创建新实例时调用 factory 函数
> class Good(BaseModel):
>     items: list[str] = Field(default_factory=list)
> ```

`default_factory` 的工作原理：

```
创建实例时：
  ┌──────────────────────────────────┐
  │  allowed_tools = Field(          │
  │    default_factory=list          │
  │  )                               │
  │         │                        │
  │         ▼                        │
  │  调用 list() → 返回新的空列表    │
  │  每个实例获得独立的 []            │
  └──────────────────────────────────┘
```

### 4. 序列化与反序列化：`model_validate` / `model_dump`

**`config/settings.py`——加载与保存**

```python
def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from config file, merging with defaults."""
    if config_path is None:
        from openharness.config.paths import get_config_file_path
        config_path = get_config_file_path()

    if config_path.exists():
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        settings = Settings.model_validate(raw)   # ← 反序列化
        # ...
        return _apply_env_overrides(settings.materialize_active_profile())

    return _apply_env_overrides(Settings().materialize_active_profile())


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """Persist settings to the config file."""
    # ...
    atomic_write_text(
        config_path,
        settings.model_dump_json(indent=2) + "\n",  # ← 序列化
    )
```

> **Java 对比**：
>
> ```java
> // 反序列化
> Settings settings = objectMapper.readValue(json, Settings.class);
>
> // 序列化
> String json = objectMapper.writeValueAsString(settings);
> ```
>
> ```python
> # 反序列化（Pydantic）
> settings = Settings.model_validate(raw)
>
> # 序列化（Pydantic）
> json_str = settings.model_dump_json(indent=2)
> ```

Pydantic 的序列化方法族：

| 方法 | 作用 | Java 对应 |
|------|------|----------|
| `model_validate(data)` | 从 dict/JSON 创建实例 | `ObjectMapper.readValue()` |
| `model_dump()` | 导出为 dict | `ObjectMapper.convertValue(obj, Map.class)` |
| `model_dump_json()` | 导出为 JSON 字符串 | `ObjectMapper.writeValueAsString()` |

### 5. 不可变更新：`model_copy(update={...})`

这是 Pydantic 最重要的模式之一——**永远不修改原对象，而是创建副本**。

```python
# settings.py 中的典型用法
def merge_cli_overrides(self, **overrides: Any) -> Settings:
    """Return a new Settings with CLI overrides applied (non-None values only)."""
    updates = {k: v for k, v in overrides.items() if v is not None}
    merged = self.model_copy(update=updates)   # ← 创建新实例，不修改 self
    # ...
    return merged
```

```python
# profile 合并
def merged_profiles(self) -> dict[str, ProviderProfile]:
    merged = default_provider_profiles()
    for name, raw_profile in self.profiles.items():
        profile = (
            raw_profile.model_copy(deep=True)           # 深拷贝
            if isinstance(raw_profile, ProviderProfile)
            else ProviderProfile.model_validate(raw_profile)
        )
        builtin = merged.get(name)
        if builtin is not None and profile.base_url is None and builtin.base_url is not None:
            profile = profile.model_copy(update={"base_url": builtin.base_url})  # ← 不可变更新
        merged[name] = profile
    return merged
```

> **Java 对比**：
>
> Java 实现不可变更新通常需要 Builder 模式：
>
> ```java
> // Java Builder 模式
> Settings merged = settings.toBuilder()
>     .model(newModel)
>     .baseUrl(newUrl)
>     .build();
> ```
>
> ```python
> # Python Pydantic model_copy
> merged = settings.model_copy(update={
>     "model": new_model,
>     "base_url": new_url,
> })
> ```
>
> Pydantic 的 `model_copy` 天然内置，无需手写 Builder 类。`update={}` 只包含要修改的字段，其他字段自动从原实例复制。

`model_copy` 的工作流程：

```
原始 Settings 对象                      新 Settings 对象
┌──────────────────────┐     ┌──────────────────────┐
│ model: "sonnet"      │     │ model: "opus"         │  ← 覆盖
│ api_key: "sk-xxx"    │ ──→ │ api_key: "sk-xxx"    │  ← 复制
│ max_tokens: 16384    │     │ max_tokens: 16384    │  ← 复制
│ ...                  │     │ ...                  │
└──────────────────────┘     └──────────────────────┘
      model_copy(update={"model": "opus"})
```

### 6. 嵌套模型组合

**`config/settings.py`——Settings 主模型**

```python
class Settings(BaseModel):
    """Main settings model for OpenHarness."""

    # API 配置
    api_key: str = ""
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 16384
    # ...

    # 行为配置（嵌套模型）
    permission: PermissionSettings = Field(default_factory=PermissionSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)

    # 动态配置
    profiles: dict[str, ProviderProfile] = Field(default_factory=default_provider_profiles)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
```

这展示了 Pydantic 的三种嵌套方式：

1. **单模型嵌套**：`permission: PermissionSettings`——一对一关系
2. **字典嵌套**：`profiles: dict[str, ProviderProfile]`——映射关系
3. **动态工厂**：`Field(default_factory=default_provider_profiles)`——用函数返回默认值

> **Java 对比**：
>
> ```java
> public class Settings {
>     // 嵌套对象
>     @Valid
>     private PermissionSettings permission = new PermissionSettings();
>
>     // Map 嵌套
>     @Valid
>     private Map<String, ProviderProfile> profiles = new HashMap<>();
> }
> ```
>
> Pydantic 的嵌套模型自动获得级联校验——内层字段不合法时，外层也会校验失败，与 Java 的 `@Valid` 注解效果一致。

### 7. 区分联合（Discriminated Union）

**`engine/messages.py`——消息内容块**

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    media_type: str
    data: str
    source_path: str = ""


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str = Field(default_factory=lambda: f"toolu_{uuid4().hex}")
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[
    TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]
```

这是 Pydantic 最强大的特性之一——**区分联合**。四个模型共享 `type` 字段，但 `type` 的值不同：

- `type="text"` → 解析为 `TextBlock`
- `type="image"` → 解析为 `ImageBlock`
- `type="tool_use"` → 解析为 `ToolUseBlock`
- `type="tool_result"` → 解析为 `ToolResultBlock`

> **Java 对比**：
>
> ```java
> // Jackson 多态反序列化
> @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "type")
> @JsonSubTypes({
>     @JsonSubTypes.Type(value = TextBlock.class, name = "text"),
>     @JsonSubTypes.Type(value = ImageBlock.class, name = "image"),
>     @JsonSubTypes.Type(value = ToolUseBlock.class, name = "tool_use"),
>     @JsonSubTypes.Type(value = ToolResultBlock.class, name = "tool_result")
> })
> public abstract class ContentBlock { ... }
> ```
>
> Pydantic 用 `Annotated[X | Y, Field(discriminator="type")]` 一行实现相同效果。`Literal["text"]` 确保每个子类的 `type` 值是固定的，反序列化时根据 `type` 值自动选择正确的类。

然后在 `ConversationMessage` 中使用：

```python
class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock] = Field(default_factory=list)
```

这意味着 `content` 列表可以混合不同类型的块，反序列化时自动识别。

### 8. `@property` 装饰器——计算属性

**`config/settings.py`——ProviderProfile**

```python
class ProviderProfile(BaseModel):
    label: str
    provider: str
    api_format: str
    auth_source: str
    default_model: str
    base_url: str | None = None
    last_model: str | None = None
    # ...

    @property
    def resolved_model(self) -> str:
        """Return the active model for this profile."""
        return resolve_model_setting(
            (self.last_model or "").strip() or self.default_model,
            self.provider,
            default_model=self.default_model,
        )
```

**`api/usage.py`——UsageSnapshot**

```python
class UsageSnapshot(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Return the total number of accounted tokens."""
        return self.input_tokens + self.output_tokens
```

> **Java 对比**：
>
> ```java
> // Java getter 方法
> public class UsageSnapshot {
>     private int inputTokens;
>     private int outputTokens;
>
>     public int getTotalTokens() {
>         return inputTokens + outputTokens;
>     }
> }
> ```
>
> ```python
> # Python @property
> class UsageSnapshot(BaseModel):
>     input_tokens: int = 0
>     output_tokens: int = 0
>
>     @property
>     def total_tokens(self) -> int:
>         return self.input_tokens + self.output_tokens
> ```
>
> 调用方式：
> - Java：`snapshot.getTotalTokens()`（方法调用）
> - Python：`snapshot.total_tokens`（像属性一样访问，无需括号）

`@property` 将方法伪装为属性，调用者无需关心它是存储值还是计算值。Python 不需要 Java 那样为每个字段写 `getX()`/`setX()`，因为字段天然可访问；只在需要计算逻辑时才用 `@property`。

## Python 概念说明

### Pydantic 的校验层次

```
┌─────────────────────────────────────────────────┐
│  输入数据 (dict / JSON / kwargs)                 │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  1. 类型校验                               │  │
│  │     str → 必须是字符串                     │  │
│  │     int → 必须是整数                       │  │
│  │     list[str] → 列表中每个元素必须是字符串  │  │
│  └──────────────────┬────────────────────────┘  │
│                     ▼                           │
│  ┌───────────────────────────────────────────┐  │
│  │  2. 字段校验器 (field_validator)           │  │
│  │     自定义校验逻辑                         │  │
│  │     如：_normalize_content()               │  │
│  └──────────────────┬────────────────────────┘  │
│                     ▼                           │
│  ┌───────────────────────────────────────────┐  │
│  │  3. 模型校验器 (model_validator)           │  │
│  │     跨字段校验                             │  │
│  └──────────────────┬────────────────────────┘  │
│                     ▼                           │
│           产出不可变的 BaseModel 实例           │
└─────────────────────────────────────────────────┘
```

### `model_validate` vs 构造器

```python
# 方式一：构造器（只接受关键字参数）
s = Settings(model="opus", api_key="sk-xxx")

# 方式二：model_validate（接受 dict/JSON/其他格式）
s = Settings.model_validate({"model": "opus", "api_key": "sk-xxx"})
s = Settings.model_validate('{"model": "opus", "api_key": "sk-xxx"}')

# model_validate 更灵活：自动类型转换
s = Settings.model_validate({"max_tokens": "16384"})  # 字符串 "16384" → int 16384
```

> **Java 对比**：`ObjectMapper.readValue()` 也支持类似类型推断，但 Pydantic 的类型转换更激进——字符串 `"16384"` 会自动转为整数 `16384`，这在 Jackson 中需要额外配置 `DeserializationFeature.FAIL_ON_NUMBERS_FOR_STRINGS`。

## 架构图

```
┌─────────────────────────── Pydantic 模型体系 ──────────────────────────────┐
│                                                                           │
│  BaseModel (pydantic)                                                     │
│  ├── _CompatModel ──────────────────────────────────────┐                 │
│  │   model_config = ConfigDict(extra="allow")           │                │
│  │                                                       │ 容错基类      │
│  ├── BaseChannelConfig(_CompatModel) ────────┐          │                │
│  │   enabled: bool = False                   │          │                │
│  │   allow_from: list[str]                   │ 继承链   │                │
│  │                                           │          │                │
│  ├── TelegramConfig(BaseChannelConfig)       │          │                │
│  ├── SlackConfig(BaseChannelConfig)          │          │                │
│  ├── DiscordConfig(BaseChannelConfig) ───────┘          │                │
│  │                                                      │                │
│  ├── PermissionSettings ──────────────────────────────┐ │                │
│  │   allowed_tools: list[str] = Field(...)             │ │                │
│  │   denied_tools: list[str] = Field(...)             │ │                │
│  │                                                     │ │ 子模型       │
│  ├── MemorySettings                                   │ │ (可独立使用)  │
│  ├── SandboxSettings                                  │ │               │
│  │   ├── SandboxNetworkSettings                       │ │               │
│  │   ├── SandboxFilesystemSettings ───────────────────┘ │               │
│  │   └── DockerSandboxSettings                         │                │
│  │                                                      │                │
│  ├── ProviderProfile ────────────────────────────────┐ │                │
│  │   @property resolved_model → 计算属性             │ │ 组合到         │
│  │                                                    │ │ Settings      │
│  ├── Settings(BaseModel) ───────────────────────────┘ │                │
│  │   permission: PermissionSettings                     │                │
│  │   memory: MemorySettings                             │                │
│  │   sandbox: SandboxSettings                          │                │
│  │   profiles: dict[str, ProviderProfile]               │                │
│  │                                                      │                │
│  │   model_validate() → 反序列化                        │ 核心方法       │
│  │   model_dump_json() → 序列化                         │                │
│  │   model_copy(update={}) → 不可变更新                  │                │
│  └──────────────────────────────────────────────────────┘                │
│                                                                           │
│  区分联合 (engine/messages.py)                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ ContentBlock = Annotated[                                          │  │
│  │   TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock,         │  │
│  │   Field(discriminator="type")                                      │  │
│  │ ]                                                                   │  │
│  │                                                                     │  │
│  │ ConversationMessage.content: list[ContentBlock]                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

## 小结

本章深入讲解了 Pydantic `BaseModel` 的核心用法，通过 OpenHarness 的真实代码展示了 Python 数据建模与 Java 的本质差异：

1. **BaseModel = POJO + Jackson + Bean Validation**：一个类搞定数据定义、序列化和校验
2. **`Field(default_factory=...)`**：解决可变默认值的共享陷阱，等价于 Java 构造器中的 `new ArrayList<>()`
3. **`model_validate` / `model_dump`**：一行代码完成 JSON 与对象的互转
4. **`model_copy(update={})`**：不可变更新模式，替代 Java 的 Builder 模式
5. **`ConfigDict(extra="allow")`**：容错反序列化，等价于 `@JsonIgnoreProperties(ignoreUnknown=true)`
6. **区分联合 `Annotated[X | Y, Field(discriminator="type")]`**：一行实现 Jackson 多态反序列化
7. **`@property`**：计算属性，比 Java getter 更优雅——调用者无需区分存储值和计算值

### 思考题

1. 如果 `PermissionSettings` 不用 `Field(default_factory=list)` 而直接写 `allowed_tools: list[str] = []`，创建两个 `PermissionSettings` 实例后修改其中一个的 `allowed_tools`，另一个会受影响吗？为什么？
2. `model_copy(update={...})` 与直接修改属性 `settings.model = "opus"` 有什么区别？为什么 OpenHarness 选择前者？
3. 区分联合中的 `discriminator="type"` 是如何工作的？如果两个子类的 `type` 值相同会怎样？