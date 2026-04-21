# 第十二章：多提供商 API 抽象 — 统一流式接口

## 概述

OpenHarness 支持 18+ 个 LLM 提供商，从 Anthropic 和 OpenAI 到阿里云 DashScope 和本地 Ollama。这个庞大的提供商矩阵需要一个统一的抽象层，使得上层引擎代码不关心底层是 Claude API 还是 OpenAI API。

这个抽象层的核心是 `SupportsStreamingMessages` 协议——一个 Python Protocol 类（结构化子类型），它定义了 `async def stream_message(request) -> AsyncIterator[ApiStreamEvent]` 方法。任何实现了这个方法的类都可以作为 API 客户端注入引擎。

## Java 类比

| Python 概念 | Java 对应 | 核心差异 |
|---|---|---|
| `PROVIDERS` 静态元组 | Spring Bean 注册表 | Python 编译时定义 vs Spring 运行时发现 |
| `ProviderSpec(frozen=True)` | Java `record` | dataclass 可有默认值和方法，record 更严格 |
| `SupportsStreamingMessages` Protocol | Java `interface` | Python Protocol 是结构化子类型，不需要显式声明 |
| `isinstance(exc, APIStatusError)` | `catch (APIStatusError e)` | Python 运行时类型检查 vs Java 编译时检查 |
| `detect_provider_from_registry()` | Spring Auto-Configuration | Python 显式优先级链 vs Spring 条件注解 |
| `dataclass(frozen=True)` | Java `record` | Python frozen dataclass 允许 `@property`，record 不允许 |

> **Java 对比**
>
> 在 Java 中，你会定义一个 `StreamingMessagesClient` 接口，然后让 `AnthropicApiClient`、`OpenAICompatibleClient` 等显式 `implements StreamingMessagesClient`。Spring 的依赖注入会自动发现所有实现类。Python 的 Protocol 不同——你不需要声明实现关系，只要类的方法签名匹配，它就自动满足 Protocol。这叫做**结构化子类型**（structural subtyping）或"鸭子类型的形式化版本"。

## 项目代码详解

### 1. ProviderSpec — 不可变数据类

`api/registry.py` 定义了提供商的元数据模型：

```python
@dataclass(frozen=True)
class ProviderSpec:
    """单个 LLM 提供商的元数据。"""

    # 身份
    name: str                        # 规范名称，如 "dashscope"
    keywords: tuple[str, ...]         # 模型名称子串，用于检测（小写）
    env_key: str                     # 主 API Key 环境变量
    display_name: str = ""           # 显示名称

    # 路由
    backend_type: str = "openai_compat"  # "anthropic" | "openai_compat" | "copilot"
    default_base_url: str = ""            # 回退 base URL

    # 自动检测信号
    detect_by_key_prefix: str = ""   # 匹配 API Key 前缀，如 "sk-or-"
    detect_by_base_keyword: str = "" # 匹配 base_url 中的子串

    # 分类标志
    is_gateway: bool = False         # 网关型（可路由任何模型）
    is_local: bool = False           # 本地部署（vLLM, Ollama）
    is_oauth: bool = False           # 使用 OAuth 而非 API Key

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()
```

> **Java 对比**
>
> `ProviderSpec(frozen=True)` 等价于 Java 17 的 `record`：
>
> ```java
> public record ProviderSpec(
>     String name,
>     List<String> keywords,
>     String envKey,
>     String displayName,
>     String backendType,
>     String defaultBaseUrl,
>     String detectByKeyPrefix,
>     String detectByBaseKeyword,
>     boolean isGateway,
>     boolean isLocal,
>     boolean isOAuth
> ) {
>     public String label() {
>         return displayName != null && !displayName.isEmpty() ? displayName : capitalize(name);
>     }
> }
> ```
>
> 但 Python `dataclass(frozen=True)` 比 Java `record` 更灵活：可以有带默认值的字段、可以有 `@property` 计算属性、可以有 `Field(default_factory=...)` 处理可变默认值。Java record 的所有字段必须在构造时提供。

### 2. PROVIDERS 注册表 — 静态提供者目录

```python
PROVIDERS: tuple[ProviderSpec, ...] = (
    # === GitHub Copilot (OAuth, 按 api_format 检测) ===
    ProviderSpec(
        name="github_copilot",
        keywords=("copilot",),
        env_key="",
        display_name="GitHub Copilot",
        backend_type="copilot",
        is_oauth=True,
    ),
    # === 网关（按 API Key 前缀 / base_url 关键字检测）===
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        backend_type="openai_compat",
        default_base_url="https://openrouter.ai/api/v1",
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        is_gateway=True,
    ),
    # === 标准云提供商（按模型名称关键字检测）===
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend_type="anthropic",
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt", "o1", "o3", "o4"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend_type="openai_compat",
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend_type="openai_compat",
        default_base_url="https://api.deepseek.com/v1",
        detect_by_base_keyword="deepseek",
    ),
    # ... 更多提供商：Gemini, DashScope, Moonshot, MiniMax, Zhipu, Groq, Mistral, StepFun, Baidu, Bedrock, Vertex, Ollama, vLLM
)
```

> **Java 对比**
>
> 在 Spring Boot 中，提供商通常通过 `@Bean` 注册：
>
> ```java
> @Bean
> ProviderSpec anthropicProvider() {
>     return new ProviderSpec("anthropic", ...);
> }
> ```
>
> Python 使用静态元组 `PROVIDERS` 而非 Spring 的运行时发现。优势是：(1) 添加新提供商只需加一行，无需修改配置类；(2) 检测优先级由元组顺序决定，不需要 `@Order` 注解；(3) 所有提供商一目了然，没有"魔法"。

### 3. detect_provider_from_registry() — 三级检测链

```python
def detect_provider_from_registry(
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> ProviderSpec | None:
    """检测最佳匹配的 ProviderSpec。
    
    检测优先级：
      1. api_key 前缀（如 "sk-or-" → OpenRouter）
      2. base_url 关键字（如 "aihubmix" → AiHubMix）
      3. model 名称关键字（如 "qwen" → DashScope）
    """
    # 1. API Key 前缀
    if api_key:
        for spec in PROVIDERS:
            if spec.detect_by_key_prefix and api_key.startswith(spec.detect_by_key_prefix):
                return spec

    # 2. Base URL 关键字
    if base_url:
        base_lower = base_url.lower()
        for spec in PROVIDERS:
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in base_lower:
                return spec

    # 3. Model 名称关键字
    if model:
        return _match_by_model(model)

    return None
```

这个三级检测链确保了：
- **网关优先**：OpenRouter 的 `sk-or-` 前缀 API Key 会被优先识别，不会误判为普通 OpenAI Key
- **URL 优先于模型名**：如果用户指定了 `base_url=https://api.moonshot.cn/v1`，即使模型名不包含 "moonshot"，也能正确识别
- **模型名兜底**：最后通过模型名中的关键字（如 "qwen" -> DashScope）匹配

### 4. SupportsStreamingMessages — Protocol 协议

`api/client.py` 中定义了引擎依赖的核心协议：

```python
class SupportsStreamingMessages(Protocol):
    """引擎在测试和生产中使用的协议。"""

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """为请求生成流式事件。"""
```

> **Java 对比**
>
> Python Protocol 对应 Java 的 `interface`，但有关键差异：
>
> ```java
> // Java — 显式声明实现关系
> public interface SupportsStreamingMessages {
>     Flux<ApiStreamEvent> streamMessage(ApiMessageRequest request);
> }
>
> public class AnthropicApiClient implements SupportsStreamingMessages {
>     @Override
>     public Flux<ApiStreamEvent> streamMessage(ApiMessageRequest request) { ... }
> }
> ```
>
> ```python
> # Python — 结构化子类型，不需要显式声明
> class SupportsStreamingMessages(Protocol):
>     async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]: ...
>
> class AnthropicApiClient:  # 没有 "implements SupportsStreamingMessages"
>     async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
>         ...
> ```
>
> `AnthropicApiClient` 自动满足 `SupportsStreamingMessages` Protocol，因为它有签名匹配的 `stream_message` 方法。这是"鸭子类型的形式化版本"——如果它走起来像鸭子，那它就是鸭子。

### 5. AnthropicApiClient — 重试与指数退避

`api/client.py` 中的 `AnthropicApiClient` 是主要的 API 客户端，具有完整的重试逻辑：

```python
class AnthropicApiClient:
    """Anthropic 异步 SDK 的薄封装，带重试逻辑。"""

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """流式传输文本增量和最终消息，遇瞬时错误自动重试。"""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):  # MAX_RETRIES = 3
            try:
                self._refresh_client_auth()
                async for event in self._stream_once(request):
                    yield event
                return  # 成功，退出重试
            except OpenHarnessApiError:
                raise  # 认证错误不重试
            except Exception as exc:
                last_error = exc
                if attempt >= MAX_RETRIES or not _is_retryable(exc):
                    raise _translate_api_error(exc) from exc

                delay = _get_retry_delay(attempt, exc)
                yield ApiRetryEvent(
                    message=str(exc),
                    attempt=attempt + 1,
                    max_attempts=MAX_RETRIES + 1,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
```

重试判断逻辑：

```python
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

def _is_retryable(exc: Exception) -> bool:
    """检查异常是否可重试。"""
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES
    if isinstance(exc, APIError):
        return True  # 网络错误可重试
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return False
```

> **Java 对比**
>
> Java 中等价的重试逻辑通常用 Resilience4j 或 Spring Retry 实现：
>
> ```java
> @Retry(name = "anthropicApi", fallbackMethod = "fallback")
> public Flux<ApiStreamEvent> streamMessage(ApiMessageRequest request) { ... }
> ```
>
> Python 版本更显式——重试逻辑是可见的 `for` 循环，而不是框架注解。这更易于调试和理解。`yield ApiRetryEvent` 让上层 UI 能显示重试状态（"请求失败，3 秒后重试..."），这是响应式框架中难以实现的特性。

### 6. OpenAICompatibleClient — OpenAI 协议适配

`api/openai_client.py` 实现了 OpenAI 兼容 API 的客户端：

```python
class OpenAICompatibleClient:
    """兼容 OpenAI API 的提供商客户端（DashScope, GitHub Models 等）。"""

    def __init__(self, api_key: str, *, base_url: str | None = None, timeout: float | None = None) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        normalized_base_url = _normalize_openai_base_url(base_url)
        if normalized_base_url:
            kwargs["base_url"] = normalized_base_url
        if timeout is not None:
            kwargs["timeout"] = timeout
        self._client = AsyncOpenAI(**kwargs)

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """流式传输，匹配 Anthropic 客户端接口。"""
        # ... 转换消息格式、流式解析、错误处理 ...
```

消息格式转换是关键——Anthropic 和 OpenAI 的 API 格式不同：

```python
def _convert_messages_to_openai(
    messages: list[ConversationMessage],
    system_prompt: str | None,
) -> list[dict[str, Any]]:
    """将 Anthropic 风格消息转换为 OpenAI 聊天格式。
    
    关键差异：
    - Anthropic: system prompt 是独立参数
    - OpenAI: system prompt 是 role="system" 的消息
    - Anthropic: tool_use / tool_result 是内容块
    - OpenAI: tool_calls 在 assistant 消息上，tool 结果是独立消息
    """
    openai_messages: list[dict[str, Any]] = []
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if msg.role == "assistant":
            openai_messages.append(_convert_assistant_message(msg))
        elif msg.role == "user":
            # 工具结果变成 role="tool" 的独立消息
            tool_results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
            user_blocks = [b for b in msg.content if isinstance(b, (TextBlock, ImageBlock))]
            for tr in tool_results:
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_use_id,
                    "content": tr.content,
                })
    return openai_messages
```

### 7. CopilotClient — OAuth 认证客户端

`api/copilot_client.py` 包装了 GitHub Copilot 的 OAuth 认证：

```python
class CopilotClient:
    """Copilot 感知 API 客户端，实现 SupportsStreamingMessages 协议。"""

    def __init__(
        self,
        github_token: str | None = None,
        *,
        enterprise_url: str | None = None,
        model: str | None = None,
    ) -> None:
        auth_info = load_copilot_auth()
        token = github_token or (auth_info.github_token if auth_info else None)
        if not token:
            raise AuthenticationFailure("No GitHub Copilot token found. Run 'oh auth copilot-login' first.")

        base_url = copilot_api_base(ent_url)
        default_headers = {
            "User-Agent": f"openharness/{_VERSION}",
            "Openai-Intent": "conversation-edits",
        }
        raw_openai = AsyncOpenAI(api_key=token, base_url=base_url, default_headers=default_headers)
        self._inner = OpenAICompatibleClient(api_key=token, base_url=base_url)
        self._inner._client = raw_openai  # 替换底层 SDK 客户端

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        effective_model = self._model or request.model
        patched = ApiMessageRequest(model=effective_model, ...)
        async for event in self._inner.stream_message(patched):
            yield event
```

### 8. OpenHarnessApiError — 错误层次结构

`api/errors.py` 定义了清晰的错误层次：

```python
class OpenHarnessApiError(RuntimeError):
    """上游 API 失败的基类。"""

class AuthenticationFailure(OpenHarnessApiError):
    """上游服务拒绝提供的凭据。"""

class RateLimitFailure(OpenHarnessApiError):
    """上游服务因速率限制拒绝请求。"""

class RequestFailure(OpenHarnessApiError):
    """通用请求或传输失败。"""
```

错误转换逻辑在 `AnthropicApiClient._translate_api_error()` 中：

```python
def _translate_api_error(exc: APIError) -> OpenHarnessApiError:
    name = exc.__class__.__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return AuthenticationFailure(str(exc))
    if name == "RateLimitError":
        return RateLimitFailure(str(exc))
    return RequestFailure(str(exc))
```

> **Java 对比**
>
> Python 的异常层次比 Java 更简单：
>
> ```java
> // Java — 需要 catch 每种异常
> try {
>     apiClient.streamMessage(request);
> } catch (AuthenticationFailure e) {
>     // 认证错误
> } catch (RateLimitFailure e) {
>     // 限速错误
> } catch (RequestFailure e) {
>     // 通用错误
> }
> ```
>
> ```python
> # Python — 可以按层次捕获
> try:
>     async for event in client.stream_message(request):
>         yield event
> except AuthenticationFailure:
>     raise  # 认证错误不重试
> except OpenHarnessApiError:
>     raise  # 所有其他 API 错误
> except Exception as exc:
>     # 网络/连接错误 — 可能重试
> ```
>
> Python 的 `isinstance(exc, APIStatusError)` 比 Java 的 `catch (APIStatusError e)` 更灵活——你可以在任何地方用 `isinstance` 检查异常类型，不限于 `try/except` 块。

### 9. ProviderInfo 与 detect_provider — 运行时能力检测

`api/provider.py` 结合注册表和设置来推断运行时能力：

```python
@dataclass(frozen=True)
class ProviderInfo:
    """解析后的提供商元数据，用于 UI 和诊断。"""
    name: str
    auth_kind: str       # "api_key" | "oauth_device" | "external_oauth"
    voice_supported: bool
    voice_reason: str

def detect_provider(settings: Settings) -> ProviderInfo:
    """使用注册表推断活跃提供商和粗略能力集。"""
    if settings.provider == "openai_codex":
        return ProviderInfo(name="openai-codex", auth_kind="external_oauth",
                          voice_supported=False, voice_reason="...")
    # ... 特殊情况处理 ...
    spec = detect_provider_from_registry(
        model=settings.model,
        api_key=settings.api_key or None,
        base_url=settings.base_url,
    )
    if spec is not None:
        backend = spec.backend_type
        return ProviderInfo(
            name=spec.name,
            auth_kind=_AUTH_KIND.get(backend, "api_key"),
            voice_supported=False,
            voice_reason=_VOICE_REASON.get(backend, "voice mode is not supported for this provider"),
        )
    # 回退
    return ProviderInfo(name="anthropic", auth_kind="api_key",
                       voice_supported=False, voice_reason="...")
```

## 架构图

```
+---------------------------------------------------------------------+
|                     PROVIDERS 注册表 (18+ 提供商)                     |
|  github_copilot | openrouter | aihubmix | siliconflow | volcengine  |
|  anthropic | openai | deepseek | gemini | dashscope | moonshot      |
|  minimax | zhipu | groq | mistral | stepfun | baidu                   |
|  bedrock | vertex | ollama | vllm                                     |
+---------------------------------------------------------------------+
         |                         |                          |
         | detect_provider_from_registry()                    |
         | 1. API Key 前缀       | 2. Base URL 关键字        | 3. 模型名关键字
         v                         v                          v
+---------------------------------------------------------------------+
|                    ProviderSpec(frozen=True)                          |
| name | keywords | env_key | backend_type | detect_by_* | is_*      |
+---------------------------------------------------------------------+
         |
         | backend_type 路由
         v
+----------+     +------------------+     +--------------------+
|anthropic |     | openai_compat    |     | copilot            |
| backend  |     | backend          |     | backend            |
+----------+     +------------------+     +--------------------+
      |                  |                        |
      v                  v                        v
+----------+     +------------------+     +--------------------+
|Anthropic |     |OpenAICompatible  |     |CopilotClient       |
|ApiClient |     |Client            |     |(wraps OpenAICompat)|
+----------+     +------------------+     +--------------------+
      |                  |                        |
      |                  |  CodexApiClient        |
      |                  +------------------------+
      |                           |
      v                           v
+---------------------------------------------------------------------+
|          SupportsStreamingMessages Protocol                          |
|  async def stream_message(request) -> AsyncIterator[ApiStreamEvent] |
+---------------------------------------------------------------------+
         |
         v
+---------------------------------------------------------------------+
|                     QueryEngine                                      |
|  async for event in api_client.stream_message(request):              |
|      yield StreamEvent                                               |
+---------------------------------------------------------------------+

错误层次:
  OpenHarnessApiError
  ├── AuthenticationFailure    (401/403)
  ├── RateLimitFailure          (429)
  └── RequestFailure            (其他)
```

## 小结

OpenHarness 的多提供商 API 抽象层展示了 Python 在设计模式上的独特优势：

1. **Protocol 结构化子类型**：`SupportsStreamingMessages` 不需要类显式声明实现——只要方法签名匹配就行。这比 Java 接口更灵活，同时仍然提供类型检查支持。

2. **静态注册表**：`PROVIDERS` 元组是一个编译时定义的提供商目录，添加新提供商只需加一个 `ProviderSpec` 实例。比 Spring 的 `@Bean` + `@ConditionalOnProperty` 更透明。

3. **三级检测链**：API Key 前缀 > Base URL 关键字 > 模型名称关键字，优先级由代码顺序显式决定，不需要 `@Order` 注解。

4. **统一错误层次**：`OpenHarnessApiError` -> `AuthenticationFailure` / `RateLimitFailure` / `RequestFailure`，让引擎可以区分认证错误（不重试）和瞬时错误（重试）。

5. **重试与事件流**：`yield ApiRetryEvent` 让上层 UI 能显示重试进度——这在 Java 的异常链中是做不到的。

6. **消息格式适配**：`OpenAICompatibleClient` 将 Anthropic 格式转换为 OpenAI 格式，使得引擎代码不需要关心底层 API 协议差异。

从 Java 转向 Python 的核心认知：**Python 的 Protocol + dataclass(frozen=True) + 类型联合 提供了比 Java interface + record + sealed class 更简洁的抽象**——不需要工厂模式，不需要依赖注入，不需要运行时发现。