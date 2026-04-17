# API 客户端与认证模块 — 详细设计

> 涵盖模块: `api/client.py`, `api/openai_client.py`, `api/codex_client.py`,
> `api/copilot_client.py`, `api/provider.py`, `api/errors.py`,
> `auth/manager.py`, `auth/storage.py`, `auth/flows.py`
>
> 以及关联模块: `auth/external.py`, `api/copilot_auth.py`, `api/registry.py`,
> `api/usage.py`, `engine/messages.py`

---

## 1. 模块概述

本组模块构成 OpenHarness 与大模型服务通信的核心链路，职责划分为三层：

| 层次 | 模块 | 职责 |
|------|------|------|
| **协议层** | `api/client.py` | 定义统一的流式消息协议 `SupportsStreamingMessages`、请求数据模型 `ApiMessageRequest`、流事件类型 `ApiStreamEvent` |
| **客户端层** | `api/openai_client.py`, `api/codex_client.py`, `api/copilot_client.py` | 各厂商 SDK/HTTP 客户端的具体实现，均遵循 `SupportsStreamingMessages` 协议 |
| **认证与存储层** | `auth/manager.py`, `auth/storage.py`, `auth/flows.py`, `auth/external.py` | 凭证存储、认证流、外部 CLI 凭证绑定、Profile 管理 |
| **辅助层** | `api/errors.py`, `api/provider.py`, `api/registry.py`, `api/usage.py` | 错误类型层级、Provider 探测与元数据、用量追踪 |

核心设计原则：

- **统一协议**: 四种客户端（Anthropic、OpenAI-Compatible、Codex、Copilot）全部实现 `SupportsStreamingMessages` Protocol，查询引擎无需关心底层客户端差异。
- **消息格式归一化**: 内部使用 Anthropic 风格的 `ConversationMessage` + `ContentBlock` 体系；各客户端在请求前将消息转换为目标厂商格式。
- **双重认证体系**: 支持 API Key 直接认证与 OAuth/外部订阅认证两种路径。
- **不可变数据模型**: 所有请求/事件数据类均为 `frozen=True`，防止运行时变异。

---

## 2. 核心类/接口

### 2.1 `SupportsStreamingMessages` 协议 (api/client.py)

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(
        self, request: ApiMessageRequest
    ) -> AsyncIterator[ApiStreamEvent]:
        """产生流式事件的统一接口。"""
```

这是整个 API 客户端层的核心抽象。所有客户端实现此协议，使查询引擎可以通过同一接口调用任何后端。

**实现者清单**:

| 类 | 模块 | 后端 |
|----|------|------|
| `AnthropicApiClient` | `api/client.py` | Anthropic SDK (`AsyncAnthropic`) |
| `OpenAICompatibleClient` | `api/openai_client.py` | OpenAI SDK (`AsyncOpenAI`) |
| `CodexApiClient` | `api/codex_client.py` | httpx 原生 SSE |
| `CopilotClient` | `api/copilot_client.py` | 委托 `OpenAICompatibleClient` |

### 2.2 `AnthropicApiClient` (api/client.py, ~267 行)

Anthropic 官方 SDK 的薄封装，增加重试逻辑和 Claude OAuth 订阅支持。

**构造参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `api_key` | `str \| None` | API Key 认证模式 |
| `auth_token` | `str \| None` | Claude OAuth 认证模式 |
| `base_url` | `str \| None` | 自定义 API 端点 |
| `claude_oauth` | `bool` | 是否启用 Claude 订阅 OAuth 模式 |
| `auth_token_resolver` | `Callable[[], str] \| None` | Token 刷新回调 |

**双认证模式**:

- **api_key 模式**: 使用标准 `x-api-key` 认证，直接传递给 `AsyncAnthropic`。
- **claude_oauth 模式**: 使用 `auth_token` + 特殊 headers（`claude_oauth_headers()` 返回的 `anthropic-beta`, `user-agent`, `x-app`, `X-Claude-Code-Session-Id`），调用 `self._client.beta.messages.stream()` 而非 `self._client.messages.stream()`。

**Token 刷新机制** (`_refresh_client_auth`):
- 仅在 `claude_oauth=True` 且 `auth_token_resolver` 非空时生效。
- 每次调用 `stream_message` 前执行，通过回调获取新 token。
- 若 token 发生变化，重新创建 `AsyncAnthropic` 实例。

### 2.3 `OpenAICompatibleClient` (api/openai_client.py, ~409 行)

面向 OpenAI 兼容 API 的通用客户端，支持 DashScope、GitHub Models、DeepSeek 等多家厂商。

**构造参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `api_key` | `str` | 必需的 API Key |
| `base_url` | `str \| None` | 自定义端点，经过 `_normalize_openai_base_url` 归一化 |
| `timeout` | `float \| None` | 请求超时秒数 |

**消息转换管线** (请求方向 Anthropic → OpenAI):

1. `_convert_messages_to_openai()`: 系统提示变成 `role="system"` 消息；`ToolResultBlock` 变成 `role="tool"` 消息；`ToolUseBlock` 变成 `tool_calls` 字段。
2. `_convert_tools_to_openai()`: `input_schema` → `parameters`，并包裹为 `{"type": "function", "function": {...}}`。
3. `_token_limit_param_for_model()`: 对 `gpt-5`, `o1`, `o3`, `o4` 前缀模型使用 `max_completion_tokens` 而非 `max_tokens`。

**Thinking 模型支持**:

- 解析流中的 `reasoning_content` 字段，存储在 `final_message._reasoning`。
- 回放时 `_convert_assistant_message()` 会将 `_reasoning` 写入 `reasoning_content` 字段。
- 某些厂商（如 Kimi）在工具调用时不允许空的 `reasoning_content`，因此当存在 `tool_calls` 时强制设置 `reasoning_content=""`。
- 当 `tools` 参数存在时，移除 `stream_options` 以避免触发需要 `reasoning_content` 的思维模式。

### 2.4 `CodexApiClient` (api/codex_client.py, ~392 行)

通过 chatgpt.com Codex Responses API 访问 Codex 订阅的客户端。使用 httpx 原生 SSE 而非 OpenAI SDK。

**构造参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `auth_token` | `str` | Codex 访问令牌（JWT） |
| `base_url` | `str \| None` | 默认 `https://chatgpt.com/backend-api` |

**Codex Responses API 格式**:

- 输入使用 `input` 字段（非 `messages`），包含 `function_call` 和 `function_call_output` 类型项。
- 工具调用使用 `function_call` 类型（含 `call_id`, `name`, `arguments`）。
- 工具结果使用 `function_call_output` 类型（含 `call_id`, `output`）。
- 流事件类型: `response.output_text.delta`, `response.output_item.done`, `response.completed`, `response.failed`, `error`。

**JWT Token 解析** (`_extract_account_id`):
- 从 JWT payload 中提取 `https://api.openai.com/auth.chatgpt_account_id`。
- 用于构建 `chatgpt-account-id` 请求头。
- 解析失败时抛出 `AuthenticationFailure`。

**SSE 解析** (`_iter_sse_events`):
- 手动解析 `data:` 行，空行分隔事件。
- `[DONE]` 标记结束流。
- JSON 解析失败时静默跳过。

### 2.5 `CopilotClient` (api/copilot_client.py, ~131 行)

GitHub Copilot API 客户端，封装 `OpenAICompatibleClient` 并替换其底层 SDK 实例。

**构造参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `github_token` | `str \| None` | GitHub OAuth token (`ghu_...`/`gho_...`) |
| `enterprise_url` | `str \| None` | GitHub Enterprise 域名 |
| `model` | `str \| None` | 默认模型，覆盖请求中的模型 |

**Copilot 专用 Headers**:

```python
{
    "User-Agent": "openharness/0.1.0",
    "Openai-Intent": "conversation-edits",
}
```

**内部委托机制**:
- 创建 `OpenAICompatibleClient` 实例作为 `self._inner`。
- 创建独立的 `AsyncOpenAI` 实例（含 Copilot headers），通过 `self._inner._client = raw_openai` 替换内部 SDK 客户端。
- `stream_message` 委托给 `self._inner.stream_message()`，可覆盖模型名称。

### 2.6 `AuthManager` (auth/manager.py, ~452 行)

统一的认证管理器，负责 Profile 生命周期、凭证读写、Provider 状态查询。

**核心方法**:

| 方法 | 说明 |
|------|------|
| `get_active_provider()` | 获取当前活跃 provider 名称 |
| `get_active_profile()` | 获取当前活跃 profile 名称 |
| `list_profiles()` | 返回所有已配置的 profile |
| `use_profile(name)` | 激活指定 profile |
| `upsert_profile(name, profile)` | 创建或替换 profile |
| `update_profile(name, **kwargs)` | 原地更新 profile 字段 |
| `remove_profile(name)` | 删除非内置 profile |
| `switch_provider(name)` | 智能路由：auth_source → profile → provider |
| `switch_auth_source(auth_source)` | 切换 profile 的认证来源 |
| `store_credential(provider, key, value)` | 存储凭证并同步 settings |
| `store_profile_credential(profile_name, key, value)` | 按 profile 命名空间存储凭证 |
| `clear_credential(provider)` | 清除 provider 凭证 |
| `get_auth_status()` | 所有 provider 的认证状态 |
| `get_auth_source_statuses()` | 所有 auth source 的详细状态 |
| `get_profile_statuses()` | 所有 profile 的配置与认证状态 |

**`switch_provider` 智能路由**:
1. 若 `name` 在 `_AUTH_SOURCES` 中 → 调用 `switch_auth_source(name)`。
2. 若 `name` 在 profile 列表中 → 调用 `use_profile(name)`。
3. 若 `name` 在 `_KNOWN_PROVIDERS` 中 → 通过 `_PROFILE_BY_PROVIDER` 映射到 profile 并调用 `use_profile()`。
4. 否则抛出 `ValueError`。

### 2.7 `AuthFlow` 及其子类 (auth/flows.py)

| 类 | 认证方式 | 交互方式 |
|----|----------|----------|
| `ApiKeyFlow` | 终端输入 API Key | `getpass.getpass()` 安全输入 |
| `DeviceCodeFlow` | GitHub OAuth 设备码流程 | 打开浏览器 + 轮询等待 |
| `BrowserFlow` | 浏览器认证 + 手动粘贴 | 打开浏览器 + `getpass.getpass()` |

### 2.8 `ExternalAuthBinding` 与外部凭证 (auth/storage.py, auth/external.py)

```python
@dataclass(frozen=True)
class ExternalAuthBinding:
    provider: str          # "openai_codex" 或 "anthropic_claude"
    source_path: str       # 凭证文件路径或 "keychain:..." 前缀
    source_kind: str       # "codex_auth_json" | "claude_credentials_json" | "claude_credentials_keychain"
    managed_by: str        # "codex-cli" | "claude-cli"
    profile_label: str     # 显示标签
```

```python
@dataclass(frozen=True)
class ExternalAuthCredential:
    provider: str
    value: str             # 访问令牌
    auth_kind: str         # "api_key" | "auth_token"
    source_path: Path
    managed_by: str
    profile_label: str
    refresh_token: str     # 用于自动刷新
    expires_at_ms: int | None  # 过期时间戳
```

### 2.9 `ProviderSpec` 与 Provider 注册表 (api/registry.py)

```python
@dataclass(frozen=True)
class ProviderSpec:
    name: str              # 规范名称，如 "dashscope"
    keywords: tuple[str, ...]  # 模型名关键字
    env_key: str           # 环境变量名
    display_name: str      # 显示名称
    backend_type: str       # "anthropic" | "openai_compat" | "copilot"
    default_base_url: str  # 默认端点
    detect_by_key_prefix: str   # API Key 前缀匹配
    detect_by_base_keyword: str  # base_url 关键字匹配
    is_gateway: bool       # 网关型（路由任意模型）
    is_local: bool         # 本地部署
    is_oauth: bool         # OAuth 认证
```

**探测优先级**:
1. API Key 前缀匹配（如 `sk-or-` → OpenRouter）
2. base_url 关键字匹配（如 `aihubmix` → AiHubMix）
3. 模型名关键字匹配（如 `qwen` → DashScope）

---

## 3. 数据模型

### 3.1 请求数据模型 (api/client.py)

```python
@dataclass(frozen=True)
class ApiMessageRequest:
    model: str                                    # 模型标识符
    messages: list[ConversationMessage]           # 对话消息列表
    system_prompt: str | None = None              # 系统提示
    max_tokens: int = 4096                        # 最大生成 token 数
    tools: list[dict[str, Any]] = field(...)       # 工具定义列表
```

`ApiMessageRequest` 是所有客户端共享的请求结构。各客户端在内部将其转换为目标格式（如 OpenAI 的 `messages` 数组、Codex 的 `input` 数组）。

### 3.2 流事件数据模型 (api/client.py)

```python
@dataclass(frozen=True)
class ApiTextDeltaEvent:
    text: str                    # 增量文本片段

@dataclass(frozen=True)
class ApiMessageCompleteEvent:
    message: ConversationMessage  # 完整的助手消息
    usage: UsageSnapshot          # Token 用量
    stop_reason: str | None       # 停止原因 ("stop", "tool_use", "length", "error")

@dataclass(frozen=True)
class ApiRetryEvent:
    message: str                  # 错误描述
    attempt: int                  # 当前重试次数
    max_attempts: int             # 最大重试次数
    delay_seconds: float          # 等待秒数

ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent
```

`ApiStreamEvent` 是联合类型，消费者通过 `isinstance` 判断事件类型。`ApiRetryEvent` 允许 UI 层展示重试进度。

### 3.3 用量数据模型 (api/usage.py)

```python
class UsageSnapshot(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
```

使用 Pydantic `BaseModel` 而非 `dataclass`，便于后续序列化和验证扩展。

### 3.4 对话消息数据模型 (engine/messages.py)

```python
class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    media_type: str
    data: str                          # base64 编码
    source_path: str = ""

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str                             # 默认 "toolu_{uuid4().hex}"
    name: str
    input: dict[str, Any]

class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False

ContentBlock = Annotated[
    TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]

class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]
```

使用 Pydantic 的判别联合 (`discriminated union`) 实现 `ContentBlock`，确保反序列化时根据 `type` 字段自动选择正确的子类型。

### 3.5 Provider 信息 (api/provider.py)

```python
@dataclass(frozen=True)
class ProviderInfo:
    name: str               # 解析后的 provider 名称
    auth_kind: str          # "api_key" | "oauth_device" | "external_oauth"
    voice_supported: bool   # 语音支持状态（当前全部为 False）
    voice_reason: str       # 不支持语音的原因说明
```

### 3.6 Copilot 认证信息 (api/copilot_auth.py)

```python
@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int

@dataclass
class CopilotAuthInfo:
    github_token: str
    enterprise_url: str | None = None

    @property
    def api_base(self) -> str: ...
```

---

## 4. 关键算法

### 4.1 重试与退避算法

**通用策略**: 所有客户端采用相同的重试框架：

| 参数 | Anthropic | OpenAI-Compatible | Codex |
|------|-----------|-------------------|-------|
| MAX_RETRIES | 3 | 3 | 3 |
| BASE_DELAY | 1.0s | 1.0s | 1.0s |
| MAX_DELAY | 30.0s | 30.0s | 30.0s |
| 最大尝试次数 | 4 (3+1) | 4 (3+1) | 4 (3+1) |

**可重试状态码**:

| 客户端 | 状态码集合 |
|--------|-----------|
| Anthropic | `{429, 500, 502, 503, 529}` |
| OpenAI-Compatible | `{429, 500, 502, 503}` |
| Codex | `{429, 500, 502, 503, 504}` |
| 通用 | `ConnectionError`, `TimeoutError`, `OSError` |

**指数退避 + 抖动** (Anthropic 客户端):

```
delay = min(BASE_DELAY * (2 ^ attempt), MAX_DELAY)
jitter = random.uniform(0, delay * 0.25)
final_delay = delay + jitter
```

**Retry-After 优先** (Anthropic 客户端):
- 当异常为 `APIStatusError` 且响应头包含 `retry-after` 时，优先使用该值（不超过 `MAX_DELAY`）。
- 解析失败时回退到指数退避。

**OpenAI-Compatible 退避**:
- 使用纯指数退避 `min(BASE_DELAY * (2 ^ attempt), MAX_DELAY)`，无抖动。

**Codex 退避**:
- 同样使用纯指数退避。

**重试流程伪代码**:

```
for attempt in 0..MAX_RETRIES:
    try:
        yield* _stream_once(request)
        return
    except OpenHarnessApiError:
        raise          # 认证/业务错误不重试
    except Exception as exc:
        if attempt == MAX_RETRIES or not is_retryable(exc):
            raise translate_error(exc)
        yield ApiRetryEvent(...)   # 通知 UI 正在重试
        sleep(delay)
```

### 4.2 消息格式转换算法

#### 4.2.1 Anthropic → OpenAI 消息转换

```
输入: messages: list[ConversationMessage], system_prompt: str | None
输出: openai_messages: list[dict]

1. 若 system_prompt 非空 → 插入 {"role": "system", "content": system_prompt}
2. 遍历每条消息:
   a. role == "assistant":
      - 文本块合并为 content 字段
      - ToolUseBlock 转为 tool_calls 数组
      - 若有 _reasoning 属性 → 设 reasoning_content 字段
      - 若有 tool_calls 但无 reasoning → reasoning_content = ""
   b. role == "user":
      - ToolResultBlock → 单独的 {"role": "tool", "tool_call_id": ..., "content": ...}
      - TextBlock + ImageBlock → 用户消息内容
      - 无内容 → 空字符串用户消息
```

#### 4.2.2 Anthropic → Codex 消息转换

```
输入: messages: list[ConversationMessage]
输出: codex_input: list[dict]

1. 遍历每条消息:
   a. role == "user":
      - TextBlock → {"type": "input_text", "text": ...}
      - ImageBlock → {"type": "input_image", "image_url": "data:...;base64,..."}
      - ToolResultBlock → {"type": "function_call_output", "call_id": ..., "output": ...}
   b. role == "assistant":
      - 文本 → {"type": "message", "role": "assistant", "content": [{"type": "output_text", ...}]}
      - ToolUseBlock → {"type": "function_call", "id": "fc_{id[:58]}", "call_id": ..., "name": ..., "arguments": JSON}
```

#### 4.2.3 工具定义转换

**Anthropic → OpenAI**:
```
{"name": ..., "description": ..., "input_schema": {...}}
→ {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
```

**Anthropic → Codex**:
```
{"name": ..., "description": ..., "input_schema": {...}}
→ {"type": "function", "name": ..., "description": ..., "parameters": {...}}
```

### 4.3 Claude OAuth Token 刷新算法 (auth/external.py)

```
1. 检查 is_credential_expired(credential):
   - expires_at_ms <= 当前毫秒时间戳 → 已过期
2. 若 refresh_token 为空 → 抛出 ValueError
3. 尝试每个 CLAUDE_OAUTH_TOKEN_ENDPOINTS:
   a. POST grant_type=refresh_token, refresh_token, client_id, scope
   b. 200 → 返回 {access_token, refresh_token, expires_at_ms, scopes}
   c. HTTPError 且含 "invalid_grant" → 记录错误，尝试下一个端点
   d. 其他错误 → 记录错误，尝试下一个端点
4. 全部端点失败 → 抛出 ValueError
5. 刷新成功后:
   - Keychain 模式 → 调用 security add-generic-password 写回
   - 文件模式 → 调用 write_claude_credentials 写回
```

### 4.4 Provider 探测算法 (api/registry.py)

```
detect_provider_from_registry(model, api_key, base_url):
1. 若 api_key 非空 → 遍历 PROVIDERS, 匹配 detect_by_key_prefix
2. 若 base_url 非空 → 遍历 PROVIDERS, 匹配 detect_by_base_keyword (子串)
3. 若 model 非空 → _match_by_model:
   a. 提取模型前缀 (model.split("/")[0])
   b. 前缀精确匹配 provider name → 返回
   c. 遍历 keywords 子串匹配 → 返回
4. 无匹配 → 返回 None
```

### 4.5 XOR 混淆算法 (auth/storage.py)

**警告: 此算法仅为轻量级混淆，不是加密。**

```
_obfuscation_key():
    seed = Path.home().encode() + b"openharness-v1"
    key = SHA-256(seed)    # 32 字节密钥

_obfuscate(plaintext):
    key = _obfuscation_key()
    data = plaintext.encode("utf-8")
    xored = bytes(b ^ key[i % 32] for i, b in enumerate(data))
    return base64.urlsafe_b64encode(xored)

_deobfuscate(ciphertext):
    key = _obfuscation_key()
    data = base64.urlsafe_b64decode(ciphertext)
    xored = bytes(b ^ key[i % 32] for i, b in enumerate(data))
    return xored.decode("utf-8")
```

安全性说明:
- 密钥固定派生自用户主目录路径，同一机器上的任何进程均可重现。
- 不抵御任何形式的密码分析攻击。
- 仅用于会话令牌等非敏感数据的混淆，**绝不**用于 API Key 或密码。

---

## 5. 接口规范

### 5.1 SupportsStreamingMessages 协议

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(
        self, request: ApiMessageRequest
    ) -> AsyncIterator[ApiStreamEvent]:
        """流式生成模型响应事件。

        事件顺序保证:
        1. 0..N 个 ApiTextDeltaEvent（增量文本）
        2. 0..M 个 ApiRetryEvent（重试通知）
        3. 恰好 1 个 ApiMessageCompleteEvent（终止事件）

        异常:
        - AuthenticationFailure: 凭证无效
        - RateLimitFailure: 请求频率超限
        - RequestFailure: 通用请求失败
        """
```

### 5.2 AuthManager 公共接口

```python
class AuthManager:
    def __init__(self, settings: Any | None = None)
    def get_active_provider(self) -> str
    def get_active_profile(self) -> str
    def list_profiles(self) -> dict[str, ProviderProfile]
    def use_profile(self, name: str) -> None
    def upsert_profile(self, name: str, profile: ProviderProfile) -> None
    def update_profile(self, name: str, **kwargs) -> None
    def remove_profile(self, name: str) -> None
    def switch_provider(self, name: str) -> None
    def switch_auth_source(self, auth_source: str, *, profile_name: str | None = None) -> None
    def store_credential(self, provider: str, key: str, value: str) -> None
    def store_profile_credential(self, profile_name: str, key: str, value: str) -> None
    def clear_credential(self, provider: str) -> None
    def clear_profile_credential(self, profile_name: str) -> None
    def get_auth_status(self) -> dict[str, Any]
    def get_auth_source_statuses(self) -> dict[str, Any]
    def get_profile_statuses(self) -> dict[str, Any]
```

### 5.3 AuthFlow 接口

```python
class AuthFlow(ABC):
    @abstractmethod
    def run(self) -> str:
        """执行认证流程，返回获取的凭证值。"""

class ApiKeyFlow(AuthFlow):
    def __init__(self, provider: str, prompt_text: str | None = None)
    def run(self) -> str

class DeviceCodeFlow(AuthFlow):
    def __init__(self, client_id: str | None, github_domain: str, enterprise_url: str | None, *, progress_callback: Any | None)
    def run(self) -> str

class BrowserFlow(AuthFlow):
    def __init__(self, auth_url: str, prompt_text: str)
    def run(self) -> str
```

### 5.4 凭证存储接口 (auth/storage.py)

```python
def store_credential(provider: str, key: str, value: str, *, use_keyring: bool | None = None) -> None
def load_credential(provider: str, key: str, *, use_keyring: bool | None = None) -> str | None
def clear_provider_credentials(provider: str, *, use_keyring: bool | None = None) -> None
def list_stored_providers() -> list[str]
def store_external_binding(binding: ExternalAuthBinding) -> None
def load_external_binding(provider: str) -> ExternalAuthBinding | None
```

### 5.5 外部凭证接口 (auth/external.py)

```python
def default_binding_for_provider(provider: str) -> ExternalAuthBinding
def load_external_credential(binding: ExternalAuthBinding, *, refresh_if_needed: bool = False) -> ExternalAuthCredential
def describe_external_binding(binding: ExternalAuthBinding) -> ExternalAuthState
def is_credential_expired(credential: ExternalAuthCredential, *, now_ms: int | None = None) -> bool
def refresh_claude_oauth_credential(refresh_token: str, *, scopes: list[str] | None = None) -> dict[str, Any]
def write_claude_credentials(source_path: Path, *, access_token: str, refresh_token: str, expires_at_ms: int) -> None
def claude_oauth_betas() -> list[str]
def claude_attribution_header() -> str
def claude_oauth_headers() -> dict[str, str]
def get_claude_code_version() -> str
def get_claude_code_session_id() -> str
def is_third_party_anthropic_endpoint(base_url: str | None) -> bool
```

### 5.6 Copilot 认证接口 (api/copilot_auth.py)

```python
COPILOT_CLIENT_ID: str = "Ov23li8tweQw6odWQebz"
def copilot_api_base(enterprise_url: str | None = None) -> str
def request_device_code(*, client_id: str, github_domain: str) -> DeviceCodeResponse
def poll_for_access_token(device_code: str, interval: int, *, client_id: str, github_domain: str, timeout: float, progress_callback: Any | None) -> str
def save_copilot_auth(token: str, *, enterprise_url: str | None = None) -> None
def load_copilot_auth() -> CopilotAuthInfo | None
def clear_github_token() -> None
```

### 5.7 Provider 探测接口 (api/provider.py)

```python
def detect_provider(settings: Settings) -> ProviderInfo
def auth_status(settings: Settings) -> str
```

### 5.8 Provider 注册表接口 (api/registry.py)

```python
def find_by_name(name: str) -> ProviderSpec | None
def detect_provider_from_registry(model: str, api_key: str | None = None, base_url: str | None = None) -> ProviderSpec | None
```

---

## 6. 错误处理

### 6.1 错误类型层级 (api/errors.py)

```
OpenHarnessApiError (RuntimeError)
├── AuthenticationFailure     # 401, 403 — 凭证无效/权限不足
├── RateLimitFailure          # 429 — 请求频率超限
└── RequestFailure            # 其他请求/传输失败
```

**设计决策**: 错误层级保持扁平（一级子类），不按 HTTP 状态码逐级细分。这简化了调用方的错误匹配逻辑——只需处理三种语义类型。

### 6.2 错误转换规则

| 客户端 | 输入异常 | 输出异常 |
|--------|----------|----------|
| Anthropic | `AuthenticationError`, `PermissionDeniedError` | `AuthenticationFailure` |
| Anthropic | `RateLimitError` | `RateLimitFailure` |
| Anthropic | 其他 `APIError` | `RequestFailure` |
| OpenAI-Compatible | HTTP 401/403 | `AuthenticationFailure` |
| OpenAI-Compatible | HTTP 429 | `RateLimitFailure` |
| OpenAI-Compatible | 其他异常 | `RequestFailure` |
| Codex | HTTP 401/403 | `AuthenticationFailure` |
| Codex | HTTP 429 | `RateLimitFailure` |
| Codex | 其他 `httpx.HTTPStatusError` | `RequestFailure` |
| Codex | 其他 `httpx.HTTPError` | `RequestFailure` |
| Codex | 已经是 `OpenHarnessApiError` | 原样返回 |

### 6.3 Codex 特殊错误格式化

`_format_error_message`: 从 HTTP 响应体中提取可读错误信息，按优先级尝试:
1. `response.error.message` (JSON 嵌套)
2. `response.detail` (FastAPI 风格)
3. 原始文本
4. 回退: `"Codex request failed with status {status_code}"`

`_format_codex_stream_error`: 从 SSE 错误事件中提取，格式为 `"{message} (code={code}) [request_id={request_id}]"`。

### 6.4 错误处理原则

1. **不可重试错误立即抛出**: `OpenHarnessApiError`（含 `AuthenticationFailure`）不被重试。
2. **可重试错误通知 UI**: 通过 `ApiRetryEvent` 告知上层当前重试状态。
3. **重试耗尽后转换异常**: 底层 SDK 异常在重试耗尽后转换为 `OpenHarnessApiError` 子类。
4. **Codex 流内错误**: `response.failed` 和 `error` SSE 事件类型直接抛出 `RequestFailure`。
5. **凭证过期处理**: Claude OAuth 凭证过期时自动尝试刷新（`refresh_if_needed=True`），刷新失败抛出 `ValueError`。

---

## 7. 配置项

### 7.1 重试配置

| 常量 | 模块 | 值 | 说明 |
|------|------|-----|------|
| `MAX_RETRIES` | client.py, openai_client.py, codex_client.py | 3 | 最大重试次数（实际最多 4 次尝试） |
| `BASE_DELAY` | client.py, openai_client.py | 1.0 秒 | 初始退避延迟 |
| `MAX_DELAY` | client.py, openai_client.py | 30.0 秒 | 最大退避延迟 |
| `BASE_DELAY_SECONDS` | codex_client.py | 1.0 秒 | Codex 初始退避延迟 |
| `MAX_DELAY_SECONDS` | codex_client.py | 30.0 秒 | Codex 最大退避延迟 |
| `RETRYABLE_STATUS_CODES` | client.py | `{429, 500, 502, 503, 529}` | Anthropic 可重试状态码 |

### 7.2 端点配置

| 常量 | 模块 | 值 |
|------|------|-----|
| `DEFAULT_CODEX_BASE_URL` | codex_client.py | `https://chatgpt.com/backend-api` |
| `COPILOT_DEFAULT_API_BASE` | copilot_auth.py | `https://api.githubcopilot.com` |
| `COPILOT_CLIENT_ID` | copilot_auth.py | `Ov23li8tweQw6odWQebz` |
| `CLAUDE_OAUTH_CLIENT_ID` | auth/external.py | `9d1c250a-e61b-44d9-88ed-5944d1962f5e` |
| `CLAUDE_OAUTH_TOKEN_ENDPOINTS` | auth/external.py | `("https://platform.claude.com/v1/oauth/token", "https://console.anthropic.com/v1/oauth/token")` |
| `OAUTH_BETA_HEADER` | client.py | `oauth-2025-04-20` |

### 7.3 Claude OAuth Beta 标志

| 常量 | 值 |
|------|-----|
| `CLAUDE_COMMON_BETAS` | `("interleaved-thinking-2025-05-14", "fine-grained-tool-streaming-2025-05-14")` |
| `CLAUDE_OAUTH_ONLY_BETAS` | `("claude-code-20250219", "oauth-2025-04-20")` |

### 7.4 Token 限制模型前缀

| 常量 | 模块 | 值 |
|------|------|-----|
| `_MAX_COMPLETION_TOKEN_MODEL_PREFIXES` | openai_client.py | `("gpt-5", "o1", "o3", "o4")` |

这些模型前缀触发 `max_completion_tokens` 参数（代替 `max_tokens`）。

### 7.5 凭证存储路径

| 常量 | 模块 | 值 |
|------|------|-----|
| `_CREDS_FILE_NAME` | storage.py | `credentials.json` |
| `_AUTH_FILE_NAME` | copilot_auth.py | `copilot_auth.json` |
| `_KEYRING_SERVICE` | storage.py | `"openharness"` |
| `_POLL_SAFETY_MARGIN` | copilot_auth.py | 3.0 秒 |

文件存储根目录通过 `get_config_dir()` 解析:
1. `OPENHARNESS_CONFIG_DIR` 环境变量
2. 默认 `~/.openharness/`

凭证文件权限: `0o600`（仅所有者可读写）。

### 7.6 Copilot 默认模型

| 常量 | 模块 | 值 |
|------|------|-----|
| `COPILOT_DEFAULT_MODEL` | copilot_client.py | `"gpt-4o"` |

### 7.7 已知 Provider 与 Auth Source

```python
_KNOWN_PROVIDERS = [
    "anthropic", "anthropic_claude", "openai", "openai_codex",
    "copilot", "dashscope", "bedrock", "vertex", "moonshot", "gemini",
]

_AUTH_SOURCES = [
    "anthropic_api_key", "openai_api_key", "codex_subscription",
    "claude_subscription", "copilot_oauth", "dashscope_api_key",
    "bedrock_api_key", "vertex_api_key", "moonshot_api_key", "gemini_api_key",
]

_PROFILE_BY_PROVIDER = {
    "anthropic": "claude-api",
    "anthropic_claude": "claude-subscription",
    "openai": "openai-compatible",
    "openai_codex": "codex",
    "copilot": "copilot",
    "moonshot": "moonshot",
    "gemini": "gemini",
}
```

### 7.8 Auth Kind 映射

```python
_AUTH_KIND = {
    "anthropic": "api_key",
    "openai_compat": "api_key",
    "copilot": "oauth_device",
    "openai_codex": "external_oauth",
    "anthropic_claude": "external_oauth",
}
```

---

## 8. 与其它模块的交互

### 8.1 依赖关系图

```
                    ┌──────────────────┐
                    │   查询引擎        │
                    │ (query engine)    │
                    └────────┬─────────┘
                             │ stream_message()
                    ┌────────▼─────────┐
                    │ SupportsStreaming │
                    │ Messages Protocol │
                    └────────┬─────────┘
              ┌──────────────┼──────────────┬──────────────┐
              │              │              │              │
    ┌─────────▼──────┐ ┌────▼─────────┐ ┌──▼───────────┐ ┌▼──────────────┐
    │ AnthropicApi   │ │ OpenAICompat │ │ CodexApi     │ │ CopilotClient │
    │ Client         │ │ Client       │ │ Client       │ │ (wrapper)     │
    └────────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
             │                │                │                │
    ┌────────▼───────┐ ┌──────▼───────┐ ┌──────▼───────┐ ┌────▼──────────┐
    │ anthropic SDK  │ │ openai SDK   │ │ httpx SSE    │ │ openai SDK   │
    │ AsyncAnthropic │ │ AsyncOpenAI  │ │              │ │ (替换实例)    │
    └────────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

    ┌──────────────────────────────────────────────────────────┐
    │                    Auth 子系统                            │
    │                                                          │
    │  ┌──────────────┐    ┌───────────────┐    ┌────────────┐ │
    │  │ AuthManager  │───▶│ auth/storage  │───▶│ Keyring    │ │
    │  │              │    │               │    │ (optional) │ │
    │  └──────┬───────┘    └───────┬───────┘    └────────────┘ │
    │         │                    │                           │
    │  ┌──────▼───────┐    ┌──────▼───────┐    ┌────────────┐ │
    │  │ auth/flows   │    │ auth/external │───▶│ codex-cli  │ │
    │  │ (3 flows)    │    │               │    │ claude-cli │ │
    │  └──────────────┘    └──────────────┘    └────────────┘ │
    └──────────────────────────────────────────────────────────┘
```

### 8.2 与查询引擎的交互

查询引擎是 `SupportsStreamingMessages` 的主要消费者:

1. 引擎通过 `ApiMessageRequest` 构建请求（包含模型名、消息列表、系统提示、工具定义）。
2. 调用客户端的 `stream_message()` 获取异步迭代器。
3. 遍历 `ApiStreamEvent`:
   - `ApiTextDeltaEvent` → 实时展示给用户。
   - `ApiRetryEvent` → 显示重试进度。
   - `ApiMessageCompleteEvent` → 提取助手消息和工具调用，继续 Agent 循环。

### 8.3 与配置系统的交互

- `AuthManager` 通过 `Settings` 对象读取活跃 profile、API Key、base_url 等。
- `ProviderInfo` 的 `detect_provider()` 和 `auth_status()` 均接收 `Settings` 参数。
- Profile 切换 (`use_profile`, `switch_provider`) 会调用 `save_settings()` 持久化到 `settings.json`。
- 凭证存储同步: `store_credential()` 在存储 API Key 时同时更新 `settings.api_key` 并保存。

### 8.4 与 CLI 的交互

- `ApiKeyFlow.run()` 通过 `getpass.getpass()` 从终端安全读取 API Key。
- `DeviceCodeFlow.run()` 输出设备码到终端，尝试打开浏览器，轮询等待用户授权。
- `BrowserFlow.run()` 打开浏览器后等待用户粘贴 token。
- CLI 命令 `oh auth copilot-login` → `DeviceCodeFlow` → `save_copilot_auth()`。
- CLI 命令 `oh auth claude-login` → 读取外部绑定 → `load_external_credential()`。
- CLI 命令 `oh auth codex-login` → 读取外部绑定 → `load_external_credential()`。

### 8.5 外部 CLI 凭证绑定交互

**Codex 订阅绑定**:

1. `default_binding_for_provider("openai_codex")` → 指向 `~/.codex/auth.json`。
2. `load_external_credential(binding)` → 读取 `tokens.access_token` 或 `OPENAI_API_KEY`。
3. `CodexApiClient` 构造时接收 `auth_token`，从 JWT 解析 `chatgpt-account-id`。

**Claude 订阅绑定**:

1. `default_binding_for_provider("anthropic_claude")`:
   - macOS → Keychain (`security find-generic-password`)。
   - 其他 → `~/.claude/.credentials.json`。
2. `load_external_credential(binding)` → 读取 `claudeAiOauth.accessToken`。
3. `AnthropicApiClient` 构造时启用 `claude_oauth=True`，使用 `auth_token` + 特殊 headers。
4. Token 过期时自动刷新（`refresh_claude_oauth_credential`），写回源文件或 Keychain。

### 8.6 Profile 与 credential_slot 交互

`credential_slot` 字段允许同一 provider 的多个 profile 使用不同的凭证存储槽位:

- `credential_storage_provider_name(profile_name, profile)` 将 profile 名称与 slot 组合为存储命名空间。
- `store_profile_credential()` 和 `clear_profile_credential()` 使用此命名空间，实现多端点凭证隔离。
- 典型场景: 同一 Anthropic 账户在不同 region 使用不同 API Key。

### 8.7 Provider 注册表与客户端选择的交互

1. `detect_provider_from_registry()` 根据 model/api_key/base_url 返回 `ProviderSpec`。
2. `ProviderSpec.backend_type` 决定客户端类型:
   - `"anthropic"` → `AnthropicApiClient`
   - `"openai_compat"` → `OpenAICompatibleClient`
   - `"copilot"` → `CopilotClient`
3. `ProviderSpec.is_oauth` 标识需要 OAuth 流程的 provider。
4. `ProviderSpec.default_base_url` 提供未指定 base_url 时的回退值。

### 8.8 消息模型的跨模块流转

```
ConversationMessage (engine/messages.py)
    │
    ├─→ AnthropicApiClient: message.to_api_param() → Anthropic SDK 原生格式
    │
    ├─→ OpenAICompatibleClient: _convert_messages_to_openai() → OpenAI chat format
    │
    ├─→ CodexApiClient: _convert_messages_to_codex() → Codex Responses format
    │
    └─→ CopilotClient: 委托给 OpenAICompatibleClient 的转换
```

所有客户端最终产生的 `ApiMessageCompleteEvent.message` 都是 `ConversationMessage` 类型，保证下游（查询引擎、工具执行器）使用统一的消息模型。

### 8.9 凭证存储的 Keyring 回退机制

```
store_credential(provider, key, value):
    1. use_keyring 为 True 且 keyring 可用 → keyring.set_password("openharness", "provider:key", value)
    2. keyring 失败 → 回退到文件存储
    3. 文件存储: 排他文件锁 → 读取 credentials.json → 更新 → 原子写入

load_credential(provider, key):
    1. use_keyring 为 True 且 keyring 可用 → keyring.get_password("openharness", "provider:key")
    2. keyring 中未找到 → 回退到文件存储
    3. 文件存储: 读取 credentials.json → 返回 provider.key
```

**Keyring 可用性检测** (`_keyring_available`):
- 首次调用时尝试 `keyring.get_password("openharness", "__probe__")`。
- `ImportError` → 不可用（未安装 keyring 包）。
- 其他异常 → 不可用（无后端，如容器/WSL/无头环境）。
- 结果缓存到 `_keyring_usable` 全局变量。