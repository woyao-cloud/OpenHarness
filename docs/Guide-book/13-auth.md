# 第 13 章：认证与 Provider 配置管理

## 13.1 解决的问题

OpenHarness 支持数十种 LLM 提供商，每种都有不同的认证方式。认证系统需要：

1. **多 Provider 认证**：API Key、OAuth、外部 CLI 凭据
2. **Profile 管理**：保存和切换不同的 Provider 配置
3. **凭据安全**：安全存储敏感信息
4. **自动检测**：根据配置自动选择合适的认证方式

## 13.2 认证流程

### 13.2.1 三种认证流程

`auth/flows.py` 定义了三种流程：

**1. ApiKeyFlow**：标准的 API Key 认证
```python
class ApiKeyFlow(AuthFlow):
    def run(self) -> str:
        key = getpass.getpass("Enter your API key: ").strip()
        if not key:
            raise ValueError("API key cannot be empty.")
        return key
```

**2. DeviceCodeFlow**：GitHub OAuth 设备码流程
```python
class DeviceCodeFlow(AuthFlow):
    def run(self) -> str:
        dc = request_device_code(client_id, github_domain)
        print(f"Code: {dc.user_code}")
        print(f"URL: {dc.verification_uri}")
        token = poll_for_access_token(dc.device_code, dc.interval)
        return token
```

**3. BrowserFlow**：通用浏览器认证
```python
class BrowserFlow(AuthFlow):
    def run(self) -> str:
        _try_open_browser(self.auth_url)
        token = getpass.getpass("Paste the token: ")
        return token
```

### 13.2.2 设备码流程详解

DeviceCodeFlow 的完整流程：

```
1. 请求设备码
   POST https://github.com/login/device/code
   → device_code, user_code, verification_uri, interval

2. 用户认证
   打开浏览器 → 访问 verification_uri → 输入 user_code → 授权

3. 轮询 Token
   POST https://github.com/login/oauth/access_token
   (每 interval 秒轮询一次)
   → access_token (成功后)
```

## 13.3 凭据存储

### 13.3.1 存储后端

`auth/storage.py` 提供两层存储：

```python
def store_credential(provider: str, key: str, value: str) -> None:
    """存储凭据。"""
    # 1. 尝试 keyring（系统密钥链）
    if _keyring_available:
        try:
            keyring.set_password("openharness", f"{provider}:{key}", value)
            return
        except Exception:
            pass
    
    # 2. 回退到文件存储
    creds = _load_credential_file()
    creds.setdefault(provider, {})[key] = value
    _save_credential_file(creds)

def load_credential(provider: str, key: str) -> str | None:
    """加载凭据。"""
    # 1. 尝试 keyring
    if _keyring_available:
        try:
            value = keyring.get_password("openharness", f"{provider}:{key}")
            if value:
                return value
        except Exception:
            pass
    
    # 2. 回退到文件
    creds = _load_credential_file()
    return creds.get(provider, {}).get(key)
```

### 13.3.2 凭据文件

文件存储使用 JSON 格式，权限设置为 600：

```json
{
  "anthropic": {
    "api_key": "sk-ant-..."
  },
  "openai": {
    "api_key": "sk-..."
  }
}
```

### 13.3.3 外部凭据

`auth/external.py` 对接外部 CLI 管理的凭据：

```python
def load_external_binding(provider: str) -> ExternalAuthBinding | None:
    """加载外部 CLI 凭据绑定。"""
    if provider == "anthropic_claude":
        # 从 ~/.claude/.credentials.json 读取
        creds_path = Path.home() / ".claude" / ".credentials.json"
        if creds_path.exists():
            data = json.loads(creds_path.read_text())
            return ExternalAuthBinding(
                source="claude",
                auth_token=data.get("auth_token"),
                ...
            )
    
    elif provider == "openai_codex":
        # 从 ~/.codex/auth.json 读取
        ...
```

## 13.4 AuthManager

### 13.4.1 核心功能

`auth/manager.py` 中的 `AuthManager` 是认证的中心门面：

```python
class AuthManager:
    def __init__(self, settings=None):
        self._settings = settings
    
    # Provider/Profile 管理
    def list_profiles(self) -> dict[str, ProviderProfile]: ...
    def get_active_profile(self) -> str: ...
    def use_profile(self, name: str) -> None: ...
    def upsert_profile(self, name, profile) -> None: ...
    def remove_profile(self, name) -> None: ...
    
    # 凭据管理
    def store_credential(self, provider, key, value) -> None: ...
    def clear_credential(self, provider) -> None: ...
    
    # 状态查询
    def get_auth_status(self) -> dict: ...
    def get_profile_statuses(self) -> dict: ...
    def get_auth_source_statuses(self) -> dict: ...
```

### 13.4.2 认证状态查询

`get_auth_status()` 返回所有 Provider 的认证状态：

```python
{
    "anthropic": { "configured": true, "source": "env", "active": true },
    "openai": { "configured": true, "source": "file", "active": false },
    "openai_codex": { "configured": false, "source": "missing", "active": false },
    "copilot": { "configured": true, "source": "file", "active": false },
    "dashscope": { "configured": false, "source": "missing", "active": false },
    ...
}
```

## 13.5 Provider Profile 管理

### 13.5.1 ProviderProfile

`config/settings.py`（引用）：

```python
@dataclass
class ProviderProfile:
    label: str                      # 显示名称
    provider: str                   # Provider 类型
    api_format: str                 # API 格式
    base_url: str | None            # API 地址
    auth_source: str                # 认证来源
    default_model: str | None       # 默认模型
    last_model: str | None          # 上次使用的模型
    credential_slot: str | None     # 凭据槽位
    allowed_models: list[str]       # 允许的模型列表
    context_window_tokens: int | None  # 上下文窗口
    auto_compact_threshold_tokens: int | None  # 压缩阈值
```

### 13.5.2 Profile 切换

```python
# CLI 切换 Provider
oh provider list           # 查看所有 Profile
oh provider use codex      # 切换到 Codex
oh provider use claude-api # 切换到 Claude API

# 添加自定义端点
oh provider add my-endpoint \
  --label "My Endpoint" \
  --provider openai \
  --api-format openai \
  --auth-source openai_api_key \
  --model my-model \
  --base-url https://example.com/v1
```

### 13.5.3 内置 Profile

| Profile | Provider | 认证方式 | 默认模型 |
|---------|----------|---------|---------|
| `claude-api` | Anthropic | API Key | claude-sonnet-4-6 |
| `claude-subscription` | Anthropic | OAuth | claude-sonnet-4-6 |
| `openai-compatible` | OpenAI | API Key | gpt-4o |
| `codex` | OpenAI-Codex | OAuth | gpt-4o-codex |
| `copilot` | GitHub-Copilot | OAuth | gpt-4o |
| `moonshot` | Moonshot | API Key | kimi-k2.5 |
| `gemini` | Gemini | API Key | gemini-2.5-flash |

## 13.6 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| 认证流程 | `auth/flows.py` | `ApiKeyFlow`, `DeviceCodeFlow` |
| AuthManager | `auth/manager.py` | `AuthManager` |
| 凭据存储 | `auth/storage.py` | `store_credential()`, `load_credential()` |
| 外部凭据 | `auth/external.py` | `load_external_binding()` |
| Provider Profile | `config/settings.py` | `ProviderProfile` |
| Provider 检测 | `api/provider.py` | `detect_provider()`, `auth_status()` |
| Provider 注册表 | `api/registry.py` | `ProviderSpec` registry |

## 13.7 本章小结

认证系统通过**三种认证流程 + 两层凭据存储 + Profile 管理体系**，灵活支持了 30+ Provider 的认证需求。AuthManager 提供统一的管理接口，通过 Profile 切换可以在不同 Provider 之间无缝切换。

> 下一章：[UI 层](14-ui.md) —— 三套用户界面的实现。
