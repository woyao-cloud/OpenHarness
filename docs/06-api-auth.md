# Phase 6: API 客户端与认证系统深度解析

> 涉及文件:
> - `api/client.py` (267行) — AnthropicApiClient + Protocol + 事件模型
> - `api/openai_client.py` (409行) — OpenAICompatibleClient + 消息格式转换
> - `api/codex_client.py` (392行) — CodexApiClient (Codex Responses API)
> - `api/copilot_client.py` (131行) — CopilotClient (包装 OpenAICompatibleClient)
> - `api/provider.py` (126行) — ProviderInfo + detect_provider
> - `api/errors.py` (20行) — 错误层级
> - `auth/manager.py` (452行) — AuthManager
> - `auth/storage.py` (270行) — 凭证存储
> - `auth/flows.py` (179行) — 三种认证流

---

## 1. API 客户端架构

```
SupportsStreamingMessages (Protocol)     ← 接口: stream_message(request) → AsyncIterator
  │
  ├── AnthropicApiClient               ← Anthropic/Claude API (原生)
  ├── OpenAICompatibleClient            ← OpenAI / DashScope / DeepSeek / Ollama 等
  ├── CodexApiClient                    ← ChatGPT Codex 订阅
  └── CopilotClient                     ← GitHub Copilot (包装 OpenAICompatibleClient)
```

**统一接口**: 所有客户端实现 `SupportsStreamingMessages` Protocol, QueryEngine 不知道也不关心底层是哪个 Provider。

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Yield streamed events for the request."""
```

---

## 2. API 事件模型 — 客户端与 Agent Loop 的通信协议

### 请求 (Agent Loop → API Client)

```python
@dataclass(frozen=True)
class ApiMessageRequest:
    model: str                              # 模型 ID
    messages: list[ConversationMessage]      # 对话历史
    system_prompt: str | None               # 系统提示词
    max_tokens: int = 4096                  # 最大输出 token
    tools: list[dict] = []                  # 工具 Schema 列表
```

### 响应流 (API Client → Agent Loop)

```python
ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent

@dataclass(frozen=True)
class ApiTextDeltaEvent:           # 流式文本增量
    text: str

@dataclass(frozen=True)
class ApiMessageCompleteEvent:     # 最终完整消息
    message: ConversationMessage
    usage: UsageSnapshot
    stop_reason: str | None

@dataclass(frozen=True)
class ApiRetryEvent:               # 重试通知 (Agent Loop 转为 StatusEvent 展示给用户)
    message: str
    attempt: int
    max_attempts: int
    delay_seconds: float
```

**关键**: 重试对 Agent Loop 是透明的 — 客户端 yield `ApiRetryEvent`, Loop 把它转为 `StatusEvent` 告诉用户"正在重试", 然后继续等待。

---

## 3. AnthropicApiClient — 主客户端详解

### 构造参数

```python
class AnthropicApiClient:
    def __init__(
        self,
        api_key: str | None = None,          # 标准 API Key
        auth_token: str | None = None,        # Claude 订阅 OAuth Token
        base_url: str | None = None,          # 自定义端点
        claude_oauth: bool = False,           # 是否 Claude 订阅模式
        auth_token_resolver: Callable | None, # Token 刷新回调
    ):
```

**双认证模式**:
- `api_key` 模式: 标准 Anthropic API, 用 `AsyncAnthropic(api_key=...)`
- `claude_oauth` 模式: Claude 订阅, 用 `AsyncAnthropic(auth_token=...)` + 特殊 Headers + Betas

### 重试逻辑

```
stream_message(request)
│
└── for attempt in 0..3:                    # 最多 4 次尝试 (1 + 3 retries)
    │
    ├── _refresh_client_auth()             # Claude 订阅: 刷新 Token
    ├── _stream_once(request)               # 单次流式请求
    │   ├── yield ApiTextDeltaEvent        # 文本增量
    │   └── yield ApiMessageCompleteEvent   # 最终消息
    │
    └── 失败处理:
        ├── OpenHarnessApiError → 直接抛出 (认证错误不重试)
        ├── _is_retryable(exc) → True:
        │   ├── 计算 delay (指数退避 + 抖动)
        │   ├── yield ApiRetryEvent (通知 Agent Loop)
        │   └── await asyncio.sleep(delay)
        └── _is_retryable(exc) → False:
            └── 抛出转换后的错误
```

### 可重试状态码

```python
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
# 429 = 速率限制, 500-503 = 服务器错误, 529 = 过载
```

### 指数退避策略

```python
def _get_retry_delay(attempt, exc):
    # 1. 优先使用 Retry-After Header (429 响应常见)
    if isinstance(exc, APIStatusError) and exc.headers.get("retry-after"):
        return min(float(retry_after), MAX_DELAY)

    # 2. 指数退避: 1s → 2s → 4s → 8s → ... (上限 30s)
    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)

    # 3. 随机抖动: 0 ~ 25% 的 delay
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter
```

### Claude 订阅的特殊处理

```python
# _stream_once 中的 Claude OAuth 特殊逻辑:
if self._claude_oauth:
    # 1. 添加 attribution header (标识来源)
    params["system"] = f"{claude_attribution_header()}\n{params['system']}"

    # 2. 使用 beta API 端点
    stream_api = self._client.beta.messages

    # 3. 添加 betas + metadata + request ID
    params["betas"] = claude_oauth_betas()
    params["metadata"] = {"user_id": json.dumps({...})}
    params["extra_headers"] = {"x-client-request-id": str(uuid.uuid4())}
```

### Token 自动刷新

```python
def _refresh_client_auth(self):
    if not self._claude_oauth or self._auth_token_resolver is None:
        return
    next_token = self._auth_token_resolver()  # 回调 Settings.resolve_auth()
    if next_token and next_token != self._auth_token:
        self._auth_token = next_token
        self._client = self._create_client()  # 重建 SDK 客户端
```

每次 API 调用前刷新, 确保 Claude 订阅的短期 Token 始终有效。

---

## 4. OpenAICompatibleClient — 兼容客户端 + 格式转换

### 核心挑战: Anthropic ↔ OpenAI 格式差异

| 方面 | Anthropic 格式 | OpenAI 格式 |
|------|---------------|-------------|
| System Prompt | 单独参数 `system=` | `role="system"` 消息 |
| 工具调用 | assistant 消息的 `content` 中的 `tool_use` 块 | `tool_calls` 字段 |
| 工具结果 | `role="user"` 消息中的 `tool_result` 块 | `role="tool"` 消息 |
| 工具 Schema | `input_schema` | `parameters` |
| 流式输出 | `content_block_delta` | `choices[0].delta` |

### 消息转换详解

```
Anthropic → OpenAI 消息转换:

[system_prompt]
  → {"role": "system", "content": "..."}

[assistant message with tool_uses]
  → {"role": "assistant", "content": "text", "tool_calls": [...]}
  → thinking model: 追加 "reasoning_content" 字段

[user message with tool_results]
  → 每个 ToolResultBlock → {"role": "tool", "tool_call_id": "...", "content": "..."}
  → 其余 TextBlock/ImageBlock → {"role": "user", "content": "..."}
```

### 工具 Schema 转换

```python
# Anthropic 格式
{"name": "bash", "description": "...", "input_schema": {...}}

# OpenAI 格式
{"type": "function", "function": {"name": "bash", "description": "...", "parameters": {...}}}
```

### 思维模型 (Thinking Model) 支持

Kimi k2.5 等推理模型需要 `reasoning_content` 字段:

```python
# 流式收集 reasoning
reasoning_piece = getattr(delta, "reasoning_content", None) or ""
if reasoning_piece:
    collected_reasoning += reasoning_piece

# 存储到消息对象 (非标准属性)
if collected_reasoning:
    final_message._reasoning = collected_reasoning  # type: ignore[attr-defined]

# 发送回 API 时回放
if tool_uses:
    openai_msg["reasoning_content"] = getattr(msg, "_reasoning", "") or ""
```

### Token 限制参数适配

```python
def _token_limit_param_for_model(model, max_tokens):
    # GPT-5, o1/o3/o4 系列用 max_completion_tokens
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": max_tokens}
    # 其他用 max_tokens
    return {"max_tokens": max_tokens}
```

### base_url 规范化

```python
def _normalize_openai_base_url(base_url):
    # "https://api.example.com" → "https://api.example.com/v1"
    # "https://api.example.com/v1" → "https://api.example.com/v1"
    # "https://api.example.com/custom" → "https://api.example.com/custom"
```

---

## 5. CodexApiClient — Codex 订阅客户端

### 与 OpenAI 兼容客户端的区别

| 方面 | OpenAICompatibleClient | CodexApiClient |
|------|----------------------|-----------------|
| SDK | `openai.AsyncOpenAI` | 原生 `httpx` (SSE) |
| 认证 | `api_key` | `Bearer token` (JWT) |
| 端点 | `/v1/chat/completions` | `/backend-api/codex/responses` |
| 消息格式 | OpenAI Chat | Codex Responses API |
| 流式协议 | SDK 内置 | 手动解析 SSE |

### Codex Responses API 消息格式

```python
# 工具调用
{"type": "function_call", "id": "fc_xxx", "call_id": "toolu_xxx", "name": "bash", "arguments": "{...}"}

# 工具结果
{"type": "function_call_output", "call_id": "toolu_xxx", "output": "result"}

# 文本输出
{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "..."}]}

# 输入
{"type": "input_text", "text": "user prompt"}
```

### JWT Token 解析

```python
def _extract_account_id(token):
    # 解码 JWT payload
    payload = json.loads(base64.urlsafe_b64decode(parts[1]))
    # 提取 chatgpt_account_id
    account_id = payload["https://api.openai.com/auth"]["chatgpt_account_id"]
    # 用于 Header: chatgpt-account-id
```

---

## 6. CopilotClient — 最薄的包装

```python
class CopilotClient:
    def __init__(self, github_token=None, *, enterprise_url=None, model=None):
        # 1. 加载 GitHub OAuth Token
        token = github_token or load_copilot_auth().github_token

        # 2. 构造带 Copilot Headers 的 OpenAI Client
        raw_openai = AsyncOpenAI(
            api_key=token,
            base_url=copilot_api_base(enterprise_url),
            default_headers={"User-Agent": "openharness/0.1.0", "Openai-Intent": "conversation-edits"},
        )

        # 3. 包装为 OpenAICompatibleClient, 替换底层 SDK 客户端
        self._inner = OpenAICompatibleClient(api_key=token, base_url=base_url)
        self._inner._client = raw_openai  # Swap!

    async def stream_message(self, request):
        # 直接委托给内部 OpenAI 客户端
        async for event in self._inner.stream_message(patched_request):
            yield event
```

**设计精髓**: Copilot API 本质上是 OpenAI 兼容的, 只是多了几个 Header。所以直接复用 `OpenAICompatibleClient`, 只替换底层 SDK 实例。

---

## 7. 错误层级

```
OpenHarnessApiError (基类)
├── AuthenticationFailure    # 401/403 — 认证失败, 不重试
├── RateLimitFailure         # 429 — 速率限制, 可重试
└── RequestFailure           # 其他 — 请求失败
```

**在 Agent Loop 中的处理**:
- `AuthenticationFailure` → yield `ErrorEvent`, 不重试
- `RateLimitFailure` → 自动重试 (客户端内)
- `RequestFailure` → 重试, 如果仍然失败 → yield `ErrorEvent`

---

## 8. 客户端选择流程

```python
# ui/runtime.py: _resolve_api_client_from_settings(settings)

if settings.api_format == "copilot":
    return CopilotClient(model=copilot_model)

if settings.provider == "openai_codex":
    return CodexApiClient(auth_token=auth.value, base_url=settings.base_url)

if settings.provider == "anthropic_claude":
    return AnthropicApiClient(
        auth_token=auth.value,
        base_url=settings.base_url,
        claude_oauth=True,
        auth_token_resolver=lambda: settings.resolve_auth().value,
    )

if settings.api_format == "openai":
    return OpenAICompatibleClient(api_key=auth.value, base_url=settings.base_url)

# 默认: Anthropic API
return AnthropicApiClient(api_key=auth.value, base_url=settings.base_url)
```

---

## 9. 认证系统架构

```
AuthManager (高层)                     ← CLI 交互, Profile 管理
  │
  ├── AuthFlow (ABC)                  ← 认证流程接口
  │   ├── ApiKeyFlow                   ← 终端输入 API Key
  │   ├── DeviceCodeFlow              ← GitHub OAuth Device Flow
  │   └── BrowserFlow                 ← 浏览器 + 粘贴 Token
  │
  └── storage.py (底层)              ← 凭证持久化
      ├── Keyring (优先)              ← 系统 Keyring (安全)
      └── credentials.json (fallback) ← 文件存储 (mode 600)
```

### 三种认证流程

#### ApiKeyFlow — 最简单

```python
class ApiKeyFlow(AuthFlow):
    def run(self) -> str:
        key = getpass.getpass(f"Enter your {provider} API key: ").strip()
        if not key:
            raise ValueError("API key cannot be empty.")
        return key
```

#### DeviceCodeFlow — GitHub Copilot

```
用户执行: oh auth copilot-login
  │
  ├── 1. request_device_code() → 获取 user_code + verification_uri
  ├── 2. 打开浏览器 → 用户在 GitHub 授权
  ├── 3. poll_for_access_token() → 轮询等待 Token
  └── 4. 返回 OAuth Token → 存储到 copilot_auth.json
```

#### BrowserFlow — 通用浏览器认证

```
1. 打开浏览器 → 显示认证 URL
2. 用户在浏览器中完成认证
3. 用户粘贴 Token/Code 到终端
```

---

## 10. 凭证存储 (`auth/storage.py`)

### 双后端: Keyring (优先) + 文件 (fallback)

```python
def store_credential(provider, key, value, *, use_keyring=None):
    if use_keyring is None:
        use_keyring = _keyring_available()     # 自动检测

    if use_keyring:
        keyring.set_password("openharness", f"{provider}:{key}", value)
        return

    # fallback: 文件存储
    with exclusive_file_lock(lock_path):
        data = _load_creds_file()
        data.setdefault(provider, {})[key] = value
        _save_creds_file(data)                 # atomic_write_text, mode=0o600
```

### Keyring 可用性检测

```python
def _keyring_available() -> bool:
    # import keyring 后, 尝试 get_password 做探针
    # 如果抛异常 (无后端) → 返回 False
    # 常见场景: 容器、CI、WSL、headless Linux → 无 Keyring
```

### 文件存储结构

```json
// ~/.openharness/credentials.json (mode 600)
{
  "anthropic": {
    "api_key": "sk-ant-..."
  },
  "openai": {
    "api_key": "sk-..."
  },
  "profile:my-custom-endpoint": {
    "api_key": "sk-custom-..."
  },
  "anthropic_claude": {
    "external_binding": {
      "provider": "anthropic_claude",
      "source_path": "~/.claude/.credentials.json",
      "source_kind": "claude_cli",
      "managed_by": "claude"
    }
  }
}
```

### 外部绑定 (ExternalAuthBinding)

Claude 订阅和 Codex 订阅的密钥不由 OpenHarness 管理, 而是存储在第三方 CLI 的目录中:

```python
@dataclass(frozen=True)
class ExternalAuthBinding:
    provider: str            # "anthropic_claude" / "openai_codex"
    source_path: str         # "~/.claude/.credentials.json"
    source_kind: str         # "claude_cli" / "codex_cli"
    managed_by: str          # "claude" / "codex"
    profile_label: str = ""
```

OpenHarness 存储"指针" (binding), 运行时通过指针读取实际密钥。

### XOR 混淆 (非加密!)

```python
def _obfuscate(plaintext):  # XOR + Base64
    key = SHA256(home_dir + "openharness-v1")
    xored = bytes(b ^ key[i] for i, b in enumerate(data))
    return base64(xored)

def _deobfuscate(ciphertext):  # 逆操作
    ...
```

**明确警告**: 这不是加密! 仅用于非秘密数据 (如 Session Token) 的轻度混淆, 防止偶然读取。API Key 和密码必须用 Keyring 或文件权限保护。

---

## 11. AuthManager — CLI 认证管理入口

### Profile 管理 API

```python
class AuthManager:
    # 查询
    get_active_provider()          → 当前 Provider 名
    get_active_profile()          → 当前 Profile 名
    list_profiles()               → 所有 Profile 字典
    get_auth_status()             → 所有 Provider 认证状态
    get_profile_statuses()        → 所有 Profile 认证状态

    # 修改
    use_profile(name)             → 切换活跃 Profile
    upsert_profile(name, profile) → 创建/替换 Profile
    update_profile(name, **kwargs)→ 更新 Profile 字段
    remove_profile(name)          → 删除自定义 Profile
    switch_provider(name)         → 兼容入口: name 可以是 Provider/AuthSource/Profile

    # 凭证
    store_credential(provider, key, value)
    store_profile_credential(profile_name, key, value)
    clear_credential(provider)
    clear_profile_credential(profile_name)
```

### `switch_provider` 的智能路由

```python
def switch_provider(self, name):
    if name in _AUTH_SOURCES:       # "anthropic_api_key" → 切换 auth source
        self.switch_auth_source(name)
    elif name in profiles:           # "claude-api" → 切换 profile
        self.use_profile(name)
    elif name in _KNOWN_PROVIDERS:   # "anthropic" → 查找对应 profile
        self.use_profile(_PROFILE_BY_PROVIDER[name])
```

---

## 12. ProviderInfo — 运行时 Provider 元数据

```python
@dataclass(frozen=True)
class ProviderInfo:
    name: str                 # "anthropic", "openai-compatible", "claude-subscription" 等
    auth_kind: str            # "api_key", "oauth_device", "external_oauth"
    voice_supported: bool     # 当前版本全部 False
    voice_reason: str         # 为什么不支持语音
```

**用途**: UI 状态栏显示当前 Provider + 认证类型, 以及语音模式不可用的原因。

---

## 13. 完整数据流: 从 `oh provider use kimi` 到 API 调用

```
1. 用户: oh provider use kimi

2. CLI: cli.py → auth_switch("kimi")
   → AuthManager.switch_provider("kimi")
   → AuthManager.use_profile("moonshot")
   → Settings.active_profile = "moonshot"
   → save_settings()  # 持久化到 ~/.openharness/settings.json

3. 下次启动: load_settings()
   → 读取 settings.json
   → materialize_active_profile()
   → provider="moonshot", api_format="openai", base_url="https://api.moonshot.cn/v1"

4. build_runtime():
   → _resolve_api_client_from_settings(settings)
   → api_format="openai" → OpenAICompatibleClient(
       api_key=load_credential("moonshot", "api_key"),
       base_url="https://api.moonshot.cn/v1"
   )

5. Agent Loop:
   → api_client.stream_message(ApiMessageRequest(model="kimi-k2.5", ...))
   → OpenAICompatibleClient._stream_once()
     → _convert_messages_to_openai()     # Anthropic → OpenAI 格式转换
     → _convert_tools_to_openai()        # 工具 Schema 转换
     → client.chat.completions.create()  # 调用 Kimi API
     → _parse_assistant_response()       # OpenAI → ConversationMessage
     → yield ApiTextDeltaEvent / ApiMessageCompleteEvent
```

---

## 14. 四种客户端对比

| | AnthropicApiClient | OpenAICompatibleClient | CodexApiClient | CopilotClient |
|---|---|---|---|---|
| **SDK** | anthropic SDK | openai SDK | httpx (原生) | 包装 OpenAI |
| **认证** | api_key / auth_token | api_key | JWT Bearer | GitHub OAuth |
| **消息格式** | Anthropic 原生 | 转换 Anthropic→OpenAI | 转换为 Codex Responses | 委托 OpenAI |
| **流式** | SDK 内置 | SDK 内置 | 手动 SSE 解析 | 委托 OpenAI |
| **重试** | 指数退避+抖动 | 指数退避 | 指数退避 | 委托 OpenAI |
| **Token 刷新** | ✅ auth_token_resolver | ❌ | ❌ | ❌ |
| **特殊逻辑** | Claude OAuth headers/betas | reasoning_content, max_completion_tokens | JWT 解析, chatgpt-account-id | Copilot Headers |

---

## 速查: 认证问题排查

| 现象 | 可能原因 | 排查方法 |
|------|----------|----------|
| "No API key found" | 未配置密钥 | `oh auth status` 检查 |
| AuthenticationFailure | 密钥无效/过期 | 重新 `oh setup` |
| RateLimitFailure | 速率限制 | 等待或换 Key |
| "prompt too long" | 上下文超出 | 自动触发 compact |
| Copilot "missing" | 未执行 OAuth | `oh auth copilot-login` |
| Codex "missing" | 未执行 login | `oh auth codex-login` |
| Claude "missing" | 未读取 ~/.claude/ | `oh auth claude-login` |
| Profile 切换无效 | 需要刷新运行时 | `/permissions` 或重启 |