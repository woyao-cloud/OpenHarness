# 第十章：认证系统 — 基于抽象基类的策略模式

## 概述

OpenHarness 的认证系统支持多种身份验证方式：API Key 直连、GitHub OAuth 设备码流、Claude 订阅令牌、浏览器授权等。系统使用 Python 的 ABC（Abstract Base Class）实现策略模式，将不同认证流程统一在 `AuthFlow` 抽象之下。

`AuthManager` 作为门面类（Facade），协调 `AuthFlow`、凭据存储（`auth/storage.py`）和外部 CLI 绑定（`auth/external.py`），为上层提供统一的认证接口。

## Java 类比

| Python 概念 | Java 对应 | 核心差异 |
|---|---|---|
| `AuthFlow(ABC)` | `interface AuthFlow` | Python ABC 可以有默认方法实现 |
| `ApiKeyFlow(AuthFlow)` | `class ApiKeyFlow implements AuthFlow` | Python 用 `getpass.getpass()` 代替 Java `Console.readPassword()` |
| `DeviceCodeFlow(AuthFlow)` | `class DeviceCodeFlow implements AuthFlow` | Python 用 `subprocess.Popen()` 打开浏览器 |
| 文件凭据存储 (`credentials.json`) | Java `KeyStore` | Python 用 JSON+文件锁，Java 用二进制 KeyStore |
| `getpass.getpass()` | `System.console().readPassword()` | Python 跨平台更稳定，Java 在 IDE 中 `System.console()` 常返回 null |
| `subprocess.Popen(["open", url])` | `Desktop.browse(URI)` | Python 需要按平台选择命令，Java 有统一 API |

> **Java 对比**
>
> Java 的策略模式通常用接口 + 多个实现类完成，但 Java 接口不能有默认实现（Java 8 之前），也不能有 `@abstractmethod` 的细粒度控制。Python 的 ABC 介于 Java 接口和抽象类之间：你可以定义 `@abstractmethod` 强制子类实现，同时在 ABC 中提供默认方法。这比 Java 的 `interface` + `abstract class` 双层结构更简洁。

## 项目代码详解

### 1. AuthFlow ABC — 策略接口

`auth/flows.py` 定义了认证流程的抽象基类：

```python
class AuthFlow(ABC):
    """所有认证流程的抽象基类。"""

    @abstractmethod
    def run(self) -> str:
        """执行认证流程并返回获取的凭据值。"""
```

只有两个 `AuthFlow` 实现：

```python
class ApiKeyFlow(AuthFlow):
    """提示用户输入 API Key 并持久化存储。"""

    def __init__(self, provider: str, prompt_text: str | None = None) -> None:
        self.provider = provider
        self.prompt_text = prompt_text or f"Enter your {provider} API key"

    def run(self) -> str:
        import getpass
        key = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not key:
            raise ValueError("API key cannot be empty.")
        return key


class DeviceCodeFlow(AuthFlow):
    """GitHub OAuth 设备码认证流程。"""

    def __init__(
        self,
        client_id: str | None = None,
        github_domain: str = "github.com",
        enterprise_url: str | None = None,
        *,
        progress_callback: Any | None = None,
    ) -> None:
        from openharness.api.copilot_auth import COPILOT_CLIENT_ID
        self.client_id = client_id or COPILOT_CLIENT_ID
        self.enterprise_url = enterprise_url
        self.github_domain = github_domain if not enterprise_url else enterprise_url
        self.progress_callback = progress_callback

    def run(self) -> str:
        from openharness.api.copilot_auth import poll_for_access_token, request_device_code
        print("Starting GitHub device flow...", flush=True)
        dc = request_device_code(client_id=self.client_id, github_domain=self.github_domain)
        print(f"\n  Open: {dc.verification_uri}")
        print(f"  Code: {dc.user_code}\n")
        opened = self._try_open_browser(dc.verification_uri)
        # ... 轮询等待授权 ...
        token = poll_for_access_token(dc.device_code, dc.interval, ...)
        return token
```

> **Java 对比**
>
> 在 Java 中，这会写成：
>
> ```java
> public interface AuthFlow {
>     String run();  // throws AuthException
> }
>
> public class ApiKeyFlow implements AuthFlow {
>     private final String provider;
>     private final String promptText;
>
>     @Override
>     public String run() {
>         Console console = System.console();
>         if (console == null) throw new IllegalStateException("No console");
>         char[] key = console.readPassword(promptText + ": ");
>         return new String(key);
>     }
> }
> ```
>
> Python 的 `getpass.getpass()` 比 Java 的 `System.console().readPassword()` 更可靠：后者在 IDE 内运行时返回 null，而 `getpass` 在所有终端环境下都能工作。

### 2. AuthManager — 门面类

`auth/manager.py` 中的 `AuthManager` 是认证系统的统一入口：

```python
class AuthManager:
    """提供商认证状态的中央权威。

    通过 auth.storage 模块读写凭据，
    并通过 settings 跟踪当前活跃的提供商。
    """

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> Any:
        if self._settings is None:
            from openharness.config import load_settings
            self._settings = load_settings()
        return self._settings

    def get_active_provider(self) -> str:
        return self._provider_from_settings()

    def get_auth_status(self) -> dict[str, Any]:
        """返回所有已知提供商的认证状态。"""
        active = self.get_active_provider()
        result: dict[str, Any] = {}
        for provider in _KNOWN_PROVIDERS:
            configured = False
            source = "missing"
            if provider == "anthropic":
                if os.environ.get("ANTHROPIC_API_KEY"):
                    configured = True
                    source = "env"
                elif load_credential("anthropic", "api_key") or getattr(self.settings, "api_key", ""):
                    configured = True
                    source = "file"
            # ... 其他提供商 ...
            result[provider] = {
                "configured": configured,
                "source": source,
                "active": provider == active,
            }
        return result

    def store_credential(self, provider: str, key: str, value: str) -> None:
        """存储提供商凭据。"""
        store_credential(provider, key, value)
        # 同步到 settings 中的扁平化 api_key 字段（兼容性）

    def clear_credential(self, provider: str) -> None:
        """清除提供商的所有存储凭据。"""
        clear_provider_credentials(provider)
```

> **Java 对比**
>
> `AuthManager` 对应 Spring 中的 `@Service` 门面 bean，但它不依赖 Spring 容器——它通过延迟导入 `load_settings()` 来避免循环依赖，这是 Python 中常见的"延迟导入"模式。在 Java 中，依赖注入框架自动解决循环依赖问题；在 Python 中，函数级导入是惯用方案。

### 3. 凭据存储 — 文件 + Keyring 双后端

`auth/storage.py` 实现了双后端凭据存储：

```python
_CREDS_FILE_NAME = "credentials.json"
_KEYRING_SERVICE = "openharness"

def store_credential(provider: str, key: str, value: str, *, use_keyring: bool | None = None) -> None:
    """持久化凭据，优先使用系统 Keyring。"""
    if use_keyring is None:
        use_keyring = _keyring_available()

    if use_keyring:
        try:
            import keyring
            keyring.set_password(_KEYRING_SERVICE, f"{provider}:{key}", value)
            return
        except Exception as exc:
            log.warning("Keyring store failed, falling back to file: %s", exc)

    # 回退到文件存储
    with exclusive_file_lock(_creds_lock_path()):
        data = _load_creds_file()
        data.setdefault(provider, {})[key] = value
        _save_creds_file(data)  # mode=0o600
```

文件存储使用 JSON 格式，结构如下：

```
~/.openharness/credentials.json  (mode 600)
{
  "anthropic": {
    "api_key": "sk-ant-...",
    "external_binding": { ... }
  },
  "openai": {
    "api_key": "sk-..."
  }
}
```

> **Java 对比**
>
> Java 的 `KeyStore`（JKS/PKCS12）是二进制格式，专用于公钥/私钥/证书。Python 的 `keyring` 包是对操作系统凭据管理器的统一抽象：macOS Keychain、Windows Credential Manager、Linux Secret Service。OpenHarness 的双后端策略（keyring > 文件）比 Java 更实用——在无 GUI 环境（容器/WSL）中自动回退到文件存储。

### 4. 外部 CLI 绑定 — ProcessBuilder 模式

`auth/external.py` 是最复杂的认证模块，它绑定了外部 CLI 工具（Claude CLI、Codex CLI）管理的凭据：

```python
@dataclass(frozen=True)
class ExternalAuthBinding:
    """指向外部 CLI 管理的凭据的指针。"""
    provider: str
    source_path: str       # 凭据文件路径
    source_kind: str       # "codex_auth_json" | "claude_credentials_json" | "claude_credentials_keychain"
    managed_by: str        # "codex-cli" | "claude-cli"
    profile_label: str = ""

@dataclass(frozen=True)
class ExternalAuthCredential:
    """运行时使用的规范化外部凭据。"""
    provider: str
    value: str             # 访问令牌
    auth_kind: str         # "api_key" | "auth_token"
    source_path: Path
    managed_by: str
    profile_label: str = ""
    refresh_token: str = ""
    expires_at_ms: int | None = None
```

关键的凭据加载逻辑：

```python
def load_external_credential(
    binding: ExternalAuthBinding,
    *,
    refresh_if_needed: bool = False,
) -> ExternalAuthCredential:
    """从外部认证绑定读取运行时凭据。"""
    if binding.provider == CODEX_PROVIDER:
        source_path = Path(binding.source_path).expanduser()
        if not source_path.exists():
            raise ValueError(f"External auth source not found: {source_path}")
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        return _load_codex_credential(payload, source_path, binding)

    if binding.provider == CLAUDE_PROVIDER:
        payload, source_path, keychain_service, keychain_account = _load_claude_payload(binding)
        credential = _load_claude_credential(payload, source_path, binding, ...)
        if refresh_if_needed and is_credential_expired(credential):
            refreshed = refresh_claude_oauth_credential(credential.refresh_token)
            # 写回刷新后的令牌
            write_claude_credentials(source_path, ...)
            credential = ExternalAuthCredential(value=refreshed["access_token"], ...)
        return credential
```

> **Java 对比**
>
> 这段代码的 Java 等价物会使用 `ProcessBuilder` 来执行外部 CLI（如 `claude --version`），用 `KeyStore.getInstance("KeychainStore")` 访问 macOS Keychain，用 `ObjectMapper.readValue()` 解析 JSON。Python 版的优势是：跨平台路径处理（`Path.home()` / `expanduser()`）、直接用 `json.loads()` 读取凭据文件、`subprocess.run()` 执行外部命令——全部是标准库，无需第三方依赖。

### 5. 安全输入 — getpass 模块

`ApiKeyFlow.run()` 使用 `getpass.getpass()` 进行安全输入：

```python
def run(self) -> str:
    import getpass
    key = getpass.getpass(f"{self.prompt_text}: ").strip()
    if not key:
        raise ValueError("API key cannot be empty.")
    return key
```

`getpass` 模块确保输入不在终端回显——与 `input()` 不同，它不会在屏幕上显示用户输入的内容。`BrowserFlow` 也使用 `getpass` 来获取粘贴的令牌：

```python
class BrowserFlow(AuthFlow):
    def run(self) -> str:
        import getpass
        print(f"Opening browser for authentication: {self.auth_url}")
        opened = DeviceCodeFlow._try_open_browser(self.auth_url)
        token = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not token:
            raise ValueError("No token provided.")
        return token
```

> **Java 对比**
>
> Java 的 `System.console().readPassword()` 功能等价，但有两个致命缺陷：(1) 在 IDE 中运行时 `System.console()` 返回 null，需要额外处理；(2) 返回 `char[]` 而非 `String`，虽然更安全（可主动清零），但使用不便。Python 的 `getpass` 在所有终端环境下都能正常工作。

### 6. 凭据刷新 — OAuth 令牌轮转

`refresh_claude_oauth_credential()` 展示了如何在不修改本地文件的情况下刷新 OAuth 令牌：

```python
def refresh_claude_oauth_credential(
    refresh_token: str,
    *,
    scopes: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """刷新 Claude OAuth 令牌（不修改本地文件）。"""
    requested_scopes = list(scopes or CLAUDE_AI_OAUTH_SCOPES)
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLAUDE_OAUTH_CLIENT_ID,
        "scope": " ".join(requested_scopes),
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"claude-cli/{get_claude_code_version()} (external, cli)",
    }
    for endpoint in CLAUDE_OAUTH_TOKEN_ENDPOINTS:
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if "invalid_grant" in body:
                continue  # 令牌过期，尝试下一个端点
            raise
        return {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token", refresh_token),
            "expires_at_ms": int(time.time() * 1000) + result.get("expires_in", 3600) * 1000,
        }
```

注意这里使用 `urllib.request` 而非 `aiohttp` 或 `httpx`——因为 OAuth 令牌刷新通常在非异步上下文（CLI 命令处理）中执行。

## 架构图

```
+-------------------+     +-------------------+     +-------------------+
|    AuthFlow(ABC)  |     |    AuthManager    |     |   Settings        |
|    + run(): str   |<----|   (Facade)        |---->|   (Config)        |
+-------------------+     |                   |     +-------------------+
         |                | get_auth_status() |             |
         |                | store_credential()|             | resolve_auth()
         |                | clear_credential() |             v
         v                +-------------------+     +-------------------+
+-------------------+                |                | ResolvedAuth      |
|  ApiKeyFlow       |                |                | provider,         |
|  DeviceCodeFlow   |                |                | auth_kind,        |
|  BrowserFlow      |                |                | value,            |
+-------------------+                |                | source            |
                                     v                +-------------------+
                            +-------------------+
                            | auth/storage.py   |
                            |                   |
                            | store_credential()|---> 优先: keyring
                            | load_credential() |---> 回退: credentials.json
                            | clear_provider_   |     (mode 600 + 排他锁)
                            |   credentials()   |
                            +-------------------+
                                     |
                                     | 外部绑定
                                     v
                            +-------------------+
                            | auth/external.py  |
                            |                   |
                            | ExternalAuth       |
                            |   Binding/Cred    |
                            |                   |
                            | Claude CLI  ----->| ~/.claude/.credentials.json
                            |   (OAuth 令牌)    |   或 macOS Keychain
                            |                   |
                            | Codex CLI  ------>| ~/.codex/auth.json
                            |   (JWT 令牌)      |
                            +-------------------+

凭据优先级链:
  1. 环境变量 (ANTHROPIC_API_KEY, OPENAI_API_KEY)
  2. Keyring (系统凭据管理器)
  3. ~/.openharness/credentials.json (文件存储)
  4. Settings 中的 api_key 字段
  5. 外部 CLI 绑定 (Claude CLI / Codex CLI)
```

## 小结

OpenHarness 认证系统的设计遵循了 Python 的惯用模式：

1. **ABC 策略模式**：`AuthFlow(ABC)` 定义了 `run()` 抽象方法，`ApiKeyFlow` 和 `DeviceCodeFlow` 是两个具体实现。Python ABC 比 Java 接口更灵活，因为可以在抽象类中提供默认实现。

2. **门面模式**：`AuthManager` 统一了凭据查询、存储、切换提供商等操作，隐藏了存储后端的复杂性。

3. **双后端凭据存储**：优先使用 `keyring`（操作系统凭据管理器），回退到 JSON 文件（mode 600 + 排他锁）。这比 Java KeyStore 更实用，因为 `keyring` 包对 macOS/Windows/Linux 提供了统一抽象。

4. **外部 CLI 绑定**：通过 `ExternalAuthBinding` 数据类指向外部工具管理的凭据文件，避免重复存储敏感信息。

5. **安全输入**：`getpass.getpass()` 比 Java 的 `System.console().readPassword()` 更可靠——后者在 IDE 中返回 null。

6. **延迟导入**：`AuthManager.__init__` 不立即加载 `Settings`，而是通过 `@property` 延迟导入，避免循环依赖——这是 Python 中处理模块间依赖的惯用模式。