# 第 3 章：API 层与多 Provider 支持

## 3.1 解决的问题

OpenHarness 需要支持多种 LLM 后端（Anthropic Claude、OpenAI GPT、DeepSeek、本地 Ollama 等）。每种后端的认证方式、API 格式、流式机制都不同。API 层的核心任务是：

1. **统一接口**：让上层（Engine）无需关心后端差异
2. **自动重试**：处理网络抖动和限流
3. **错误翻译**：将不同后端的错误统一为语义化异常
4. **自动检测**：根据配置自动识别 Provider

## 3.2 核心设计：Protocol 接口

### 3.2.1 SupportsStreamingMessages

所有 API 客户端共同实现的协议（`api/client.py:79`）：

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(
        self, request: ApiMessageRequest
    ) -> AsyncIterator[ApiStreamEvent]: ...
```

这是一个 **Python Protocol**（PEP 544），使用结构化子类型（structural subtyping）而非继承。任何具有匹配 `stream_message` 方法的对象都可以作为 API 客户端。

### 3.2.2 ApiMessageRequest

统一的请求结构（`api/client.py:39`）：

```python
@dataclass(frozen=True)
class ApiMessageRequest:
    model: str
    messages: list[ConversationMessage]
    system_prompt: str | None = None
    max_tokens: int = 4096
    tools: list[dict[str, Any]] = field(default_factory=list)
```

### 3.2.3 ApiStreamEvent

统一的流式事件（`api/client.py:76`）：

```python
ApiStreamEvent = ApiTextDeltaEvent | ApiMessageCompleteEvent | ApiRetryEvent
```

- **`ApiTextDeltaEvent`**：模型输出的文本增量
- **`ApiMessageCompleteEvent`**：完整的响应消息（包含 Usage）
- **`ApiRetryEvent`**：重试通知（包含延迟、尝试次数）

## 3.3 四个 API Client 实现

### 3.3.1 AnthropicApiClient（`api/client.py:117`）

Anthropic 官方 SDK 的封装：

- 使用 `anthropic.AsyncAnthropic` SDK
- 支持 Claude OAuth（订阅认证）
- 通过 `_stream_once()` 调用 `client.messages.stream()`（或 `client.beta.messages.stream()` for OAuth）
- 解析流式事件，提取 text delta
- 最终通过 `stream.get_final_message()` 获取完整响应

**重试策略**（`api/client.py:164`）：

```python
for attempt in range(MAX_RETRIES + 1):  # 最多 3 次
    try:
        return await self._stream_once(request)
    except OpenHarnessApiError:
        raise  # 认证/限流错误 - 不重试
    except Exception as exc:
        if not _is_retryable(exc):
            raise _translate_api_error(exc)
        delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
        # 指数退避 + 25% 随机抖动
        jitter = random.uniform(0, delay * 0.25)
        await asyncio.sleep(delay + jitter)
```

**重试条件**（`_is_retryable` at line 86）：
- HTTP 429、500、502、503、529
- 网络错误（`ConnectionError`, `TimeoutError`）
- 通用 `APIError`

### 3.3.2 OpenAICompatibleClient（`api/openai_client.py:227`）

兼容 OpenAI API 格式的后端：

- DeepSeek、DashScope、Gemini、Groq、Ollama 等 20+ 后端
- 消息格式转换：Anthropic → OpenAI 格式
- 工具格式转换：Anthropic schema → OpenAI function-calling
- 支持 reasoning models（`max_completion_tokens` vs `max_tokens`）
- 支持 streaming + usage 信息

**关键转换逻辑**（`_convert_messages_to_openai` at line 79）：
- `system_prompt` → role="system" 消息
- `tool_use` blocks → `tool_calls` 字段
- `tool_result` blocks → role="tool" 消息
- `ImageBlock` → `data:image` URL

### 3.3.3 CodexApiClient（`api/codex_client.py:208`）

ChatGPT/Codex 订阅客户端的实现：

- 使用原生 HTTP 请求（httpx）而非 SDK
- SSE（Server-Sent Events）流式解析
- JWT token 解析提取 `chatgpt_account_id`
- 处理 `response.completed` / `response.failed` / `error` 事件类型
- 支持 `reasoning.encrypted_content`

### 3.3.4 CopilotClient（`api/copilot_client.py:48`）

GitHub Copilot 的封装：

- 底层使用 `OpenAICompatibleClient`
- 添加 Copilot-specific headers（`Openai-Intent: conversation-edits`）
- GitHub OAuth token 直接作为 Bearer token
- 默认模型 `gpt-4o`

## 3.4 Provider 注册与自动检测

### 3.4.1 ProviderSpec 注册表

`api/registry.py:55` 定义了 **30+ Provider** 的元数据表：

```python
@dataclass(frozen=True)
class ProviderSpec:
    name: str             # 规范名称
    keywords: tuple       # 模型名称关键词
    env_key: str          # 环境变量名
    backend_type: str     # "anthropic" | "openai_compat" | "copilot"
    default_base_url: str # 默认 API 地址
    detect_by_key_prefix: str  # API Key 前缀检测
    detect_by_base_keyword: str # URL 关键词检测
    is_gateway: bool      # 是否为网关（可路由任意模型）
    is_local: bool        # 是否为本地部署
```

### 3.4.2 自动检测优先级

`detect_provider_from_registry()`（`api/registry.py:394`）：

```
1. API Key 前缀匹配
   "sk-or-" → OpenRouter
   "gsk_" → Groq

2. Base URL 关键词匹配
   "openrouter" → OpenRouter
   "siliconflow" → SiliconFlow
   "deepseek" → DeepSeek

3. 模型名称关键词匹配
   "claude-*" → Anthropic
   "gpt-*" → OpenAI
   "deepseek-*" → DeepSeek
   "qwen-*" → DashScope
```

### 3.4.3 API 格式检测

`api/provider.py:41` 中的 `detect_provider()` 根据 Settings 推断活跃 Provider：

| Settings 配置 | 检测结果 |
|--------------|---------|
| `provider="openai_codex"` | OpenAI-Codex |
| `provider="anthropic_claude"` | Claude-Subscription |
| `api_format="copilot"` | GitHub-Copilot |
| 模型名匹配 registry | 对应 Provider |
| 回退 | Anthropic 或 OpenAI-Compat |

## 3.5 错误处理体系

### 3.5.1 异常层次结构

```
RuntimeError
  └── OpenHarnessApiError        (api/errors.py:6)
        ├── AuthenticationFailure  (api/errors.py:10)  ← 认证失败
        ├── RateLimitFailure       (api/errors.py:14)  ← 限流
        └── RequestFailure         (api/errors.py:18)  ← 请求失败
```

### 3.5.2 错误翻译

各客户端的翻译逻辑：

**Anthropic**（`api/client.py:260`）：
```python
if name in {"AuthenticationError", "PermissionDeniedError"} → AuthenticationFailure
if name == "RateLimitError" → RateLimitFailure
else → RequestFailure
```

**OpenAI**（`api/openai_client.py:401`）：
```python
if status == 401 or 403 → AuthenticationFailure
if status == 429 → RateLimitFailure
else → RequestFailure
```

**Codex**（`api/codex_client.py:200`）：
```python
if status in {401, 403} → AuthenticationFailure
if status == 429 → RateLimitFailure
else → RequestFailure
```

### 3.5.3 错误向上传播

```
API Client (translate_error → OpenHarnessApiError)
    │
    ▼
run_query() catch Exception (query.py:533)
    │
    ├─ prompt too long → 反应式压缩 (reactive compact)
    ├─ connect/timeout/network → ErrorEvent("Network error: ...")
    └─ 其他 → ErrorEvent("API error: {error_msg}")
```

## 3.6 关键源码路径

| 组件 | 文件 | 行号 |
|------|------|------|
| Protocol 定义 | `api/client.py` | 79 |
| Anthropic 客户端 | `api/client.py` | 117 |
| OpenAI 客户端 | `api/openai_client.py` | 227 |
| Codex 客户端 | `api/codex_client.py` | 208 |
| Copilot 客户端 | `api/copilot_client.py` | 48 |
| Provider 注册表 | `api/registry.py` | 55 |
| Provider 检测 | `api/provider.py` | 41 |
| 错误类型 | `api/errors.py` | 1-18 |
| 错误翻译 (Anthropic) | `api/client.py` | 260 |
| 错误翻译 (OpenAI) | `api/openai_client.py` | 401 |

## 3.7 本章小结

API 层通过 **Protocol 接口统一 + 四种客户端实现 + Provider 自动检测 + 分层错误处理** 的设计，让上层引擎可以透明地使用任意 LLM 后端。新增一个 Provider 只需要注册元数据或实现客户端协议，无需修改引擎代码。

> 下一章：[会话引擎](04-engine.md) —— Agent Loop 的完整实现与消息模型。
