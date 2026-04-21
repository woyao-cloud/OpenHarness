# OpenHarness 配置参考手册

> 版本：0.1.6 | 源码：`src/openharness/config/settings.py`, `src/openharness/config/schema.py`, `src/openharness/config/paths.py`

---

## 1. Settings 主模型字段

**源码：** `src/openharness/config/settings.py` — `class Settings(BaseModel)`

### API 配置

| 字段 | 类型 | 默认值 | 环境变量 | 说明 |
|------|------|--------|----------|------|
| `api_key` | str | "" | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | API 密钥 |
| `model` | str | claude-sonnet-4-6 | `ANTHROPIC_MODEL` / `OPENHARNESS_MODEL` | 使用的模型 |
| `max_tokens` | int | 16384 | `OPENHARNESS_MAX_TOKENS` | 最大输出 token 数 |
| `base_url` | str \| None | None | `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` / `OPENHARNESS_BASE_URL` | API 基础 URL |
| `timeout` | float | 30.0 | `OPENHARNESS_TIMEOUT` | 请求超时（秒） |
| `context_window_tokens` | int \| None | None | `OPENHARNESS_CONTEXT_WINDOW_TOKENS` | 上下文窗口大小 |
| `auto_compact_threshold_tokens` | int \| None | None | `OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` | 自动压缩阈值 |
| `api_format` | str | anthropic | `OPENHARNESS_API_FORMAT` | API 格式（anthropic/openai/copilot） |
| `provider` | str | "" | `OPENHARNESS_PROVIDER` | 提供商标识 |
| `active_profile` | str | claude-api | — | 当前活跃配置名 |
| `profiles` | dict[str, ProviderProfile] | 内置 7 个 | — | 提供商配置字典 |
| `max_turns` | int | 200 | `OPENHARNESS_MAX_TURNS` | 最大工具调用轮数 |

### 行为配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system_prompt` | str \| None | None | 自定义系统提示 |
| `permission` | PermissionSettings | — | 权限配置（见下） |
| `hooks` | dict[str, list[HookDefinition]] | {} | 钩子配置 |
| `memory` | MemorySettings | — | 记忆配置（见下） |
| `sandbox` | SandboxSettings | — | 沙箱配置（见下） |
| `enabled_plugins` | dict[str, bool] | {} | 启用的插件 |
| `mcp_servers` | dict[str, McpServerConfig] | {} | MCP 服务器配置 |

### UI 配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `theme` | str | default | UI 主题 |
| `output_style` | str | default | 输出风格 |
| `vim_mode` | bool | False | Vim 编辑模式 |
| `voice_mode` | bool | False | 语音模式 |
| `fast_mode` | bool | False | 快速模式 |
| `effort` | str | medium | 推理努力级别（low/medium/high） |
| `passes` | int | 1 | 执行轮次 |
| `verbose` | bool | False | 详细日志 |

---

## 2. 嵌套模型字段

### PermissionSettings

**源码：** `src/openharness/config/settings.py`

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | PermissionMode | DEFAULT | 权限模式（default/plan/full_auto） |
| `allowed_tools` | list[str] | [] | 工具白名单 |
| `denied_tools` | list[str] | [] | 工具黑名单 |
| `path_rules` | list[PathRuleConfig] | [] | 路径访问规则 |
| `denied_commands` | list[str] | [] | 拒绝的命令模式 |

### PathRuleConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pattern` | str | — | Glob 匹配模式 |
| `allow` | bool | True | True=允许，False=拒绝 |

### MemorySettings

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | True | 启用记忆系统 |
| `max_files` | int | 5 | 最大记忆文件数 |
| `max_entrypoint_lines` | int | 200 | 入口文件最大行数 |
| `context_window_tokens` | int \| None | None | 记忆上下文窗口 |
| `auto_compact_threshold_tokens` | int \| None | None | 自动压缩阈值 |

### SandboxSettings

| 字段 | 类型 | 默认值 | 环境变量 | 说明 |
|------|------|--------|----------|------|
| `enabled` | bool | False | `OPENHARNESS_SANDBOX_ENABLED` | 启用沙箱 |
| `backend` | str | srt | `OPENHARNESS_SANDBOX_BACKEND` | 后端类型（srt/docker） |
| `fail_if_unavailable` | bool | False | `OPENHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | 不可用时是否报错 |
| `enabled_platforms` | list[str] | [] | — | 启用沙箱的平台列表 |
| `network` | SandboxNetworkSettings | — | — | 网络规则 |
| `filesystem` | SandboxFilesystemSettings | — | — | 文件系统规则 |
| `docker` | DockerSandboxSettings | — | — | Docker 配置 |

### SandboxNetworkSettings

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `allowed_domains` | list[str] | [] | 允许的网络域名 |
| `denied_domains` | list[str] | [] | 拒绝的网络域名 |

### SandboxFilesystemSettings

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `allow_read` | list[str] | [] | 允许读取的路径 |
| `deny_read` | list[str] | [] | 拒绝读取的路径 |
| `allow_write` | list[str] | ["."] | 允许写入的路径（默认当前目录） |
| `deny_write` | list[str] | [] | 拒绝写入的路径 |

### DockerSandboxSettings

| 字段 | 类型 | 默认值 | 环境变量 | 说明 |
|------|------|--------|----------|------|
| `image` | str | openharness-sandbox:latest | `OPENHARNESS_SANDBOX_DOCKER_IMAGE` | Docker 镜像名 |
| `auto_build_image` | bool | True | — | 自动构建镜像 |
| `cpu_limit` | float | 0.0 | — | CPU 限制（0=不限制） |
| `memory_limit` | str | "" | — | 内存限制 |
| `extra_mounts` | list[str] | [] | — | 额外挂载 |
| `extra_env` | dict[str, str] | {} | — | 额外环境变量 |

### ProviderProfile

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `label` | str | — | 显示名称 |
| `provider` | str | — | 提供商标识 |
| `api_format` | str | — | API 格式 |
| `auth_source` | str | — | 认证来源 |
| `default_model` | str | — | 默认模型 |
| `base_url` | str \| None | None | API 基础 URL |
| `last_model` | str \| None | None | 上次使用的模型 |
| `credential_slot` | str \| None | None | 凭据槽位 |
| `allowed_models` | list[str] | [] | 允许的模型列表 |
| `context_window_tokens` | int \| None | None | 上下文窗口大小 |
| `auto_compact_threshold_tokens` | int \| None | None | 自动压缩阈值 |

---

## 3. 环境变量完整参考

### API 相关

| 变量名 | 对应字段 | 说明 |
|--------|---------|------|
| `ANTHROPIC_API_KEY` | api_key | Anthropic API 密钥 |
| `OPENAI_API_KEY` | api_key | OpenAI API 密钥 |
| `ANTHROPIC_MODEL` | model | Anthropic 模型名 |
| `OPENHARNESS_MODEL` | model | 通用模型名覆盖 |
| `ANTHROPIC_BASE_URL` | base_url | Anthropic API 基础 URL |
| `OPENAI_BASE_URL` | base_url | OpenAI API 基础 URL |
| `OPENHARNESS_BASE_URL` | base_url | 通用 API 基础 URL 覆盖 |
| `OPENHARNESS_MAX_TOKENS` | max_tokens | 最大输出 token |
| `OPENHARNESS_TIMEOUT` | timeout | 请求超时（秒） |
| `OPENHARNESS_MAX_TURNS` | max_turns | 最大工具调用轮数 |
| `OPENHARNESS_CONTEXT_WINDOW_TOKENS` | context_window_tokens | 上下文窗口大小 |
| `OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS` | auto_compact_threshold_tokens | 自动压缩阈值 |
| `OPENHARNESS_API_FORMAT` | api_format | API 格式 |
| `OPENHARNESS_PROVIDER` | provider | 提供商标识 |
| `OPENHARNESS_VERBOSE` | verbose | 详细日志 |

### 沙箱相关

| 变量名 | 对应字段 | 说明 |
|--------|---------|------|
| `OPENHARNESS_SANDBOX_ENABLED` | sandbox.enabled | 启用沙箱 |
| `OPENHARNESS_SANDBOX_FAIL_IF_UNAVAILABLE` | sandbox.fail_if_unavailable | 不可用时报错 |
| `OPENHARNESS_SANDBOX_BACKEND` | sandbox.backend | 沙箱后端类型 |
| `OPENHARNESS_SANDBOX_DOCKER_IMAGE` | sandbox.docker.image | Docker 镜像名 |

### 路径相关

| 变量名 | 对应函数 | 说明 |
|--------|---------|------|
| `OPENHARNESS_CONFIG_DIR` | get_config_dir() | 配置目录覆盖（默认 ~/.openharness/） |
| `OPENHARNESS_DATA_DIR` | get_data_dir() | 数据目录覆盖（默认 ~/.openharness/data/） |
| `OPENHARNESS_LOGS_DIR` | get_logs_dir() | 日志目录覆盖（默认 ~/.openharness/logs/） |
| `OPENHARNESS_CHANNEL_MEDIA_DIR` | resolve_channel_media_dir() | 渠道媒体目录 |
| `OHMO_WORKSPACE` | — | Ohmo 工作空间路径 |

---

## 4. CLI 选项参考

**源码：** `src/openharness/cli.py`

### 主命令选项

| 选项 | 短选项 | 类型 | 默认值 | 对应字段 |
|------|--------|------|--------|---------|
| `--model` | -m | str | claude-sonnet-4-6 | model |
| `--permission-mode` | — | str | default | permission.mode |
| `--system-prompt` | — | str | None | system_prompt |
| `--base-url` | — | str | None | base_url |
| `--api-key` | — | str | None | api_key |
| `--api-format` | — | str | anthropic | api_format |
| `--max-turns` | — | int | 200 | max_turns |
| `--verbose` | -v | bool | False | verbose |
| `--debug` | — | bool | False | — |
| `--bare` | — | bool | False | — |
| `--theme` | — | str | default | theme |
| `--effort` | — | str | medium | effort |
| `--dangerously-skip-permissions` | — | bool | False | permission.mode=full_auto |
| `--allowed-tools` | — | str | None | permission.allowed_tools |
| `--disallowed-tools` | — | str | None | permission.denied_tools |
| `--print` | -p | str | None | — (非交互模式) |
| `--output` | -o | str | text | — (输出格式) |
| `--continue` | -c | bool | False | — (恢复上次会话) |
| `--resume` | — | str | None | — (恢复指定会话) |
| `--task-worker` | — | bool | False | — (无头工作进程) |
| `--backend-only` | — | bool | False | — (仅后端) |
| `--version` | — | bool | False | — |
| `--settings` | — | str | None | — (配置文件路径) |

---

## 5. 渠道配置参考

**源码：** `src/openharness/config/schema.py`

### BaseChannelConfig（所有渠道共用）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | False | 启用此渠道 |
| `allow_from` | list[str] | ["*"] | 允许的发送者（"*" = 全部） |

### TelegramConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `token` | str | "" | Bot Token |
| `chat_id` | str \| None | None | 允许的 Chat ID |

### SlackConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `bot_token` | str | "" | Bot Token (xoxb-) |
| `app_token` | str | "" | App Token (xapp-) |
| `signing_secret` | str | "" | 签名密钥 |

### DiscordConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `token` | str | "" | Bot Token |

### FeishuConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `app_id` | str | "" | 应用 ID |
| `app_secret` | str | "" | 应用密钥 |
| `encrypt_key` | str | "" | 加密密钥 |
| `verification_token` | str | "" | 验证令牌 |

### DingTalkConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `client_id` | str | "" | 客户端 ID |
| `client_secret` | str | "" | 客户端密钥 |
| `robot_code` | str | "" | 机器人编码 |

### EmailConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `smtp_host` | str | "" | SMTP 主机 |
| `smtp_port` | int | 587 | SMTP 端口 |
| `smtp_username` | str | "" | SMTP 用户名 |
| `smtp_password` | str | "" | SMTP 密码 |
| `from_address` | str | "" | 发件人地址 |

### QQConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `token` | str | "" | Bot Token |
| `app_id` | str | "" | 应用 ID |
| `app_secret` | str | "" | 应用密钥 |

### MatrixConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `homeserver` | str | "" | Matrix 服务器 URL |
| `access_token` | str | "" | 访问令牌 |
| `user_id` | str | "" | 用户 ID |

### WhatsAppConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `access_token` | str | "" | 访问令牌 |
| `phone_number_id` | str | "" | 电话号码 ID |
| `verify_token` | str | "" | 验证令牌 |

### MochatConfig

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `endpoint` | str | "" | 自定义端点 URL |
| `token` | str | "" | 访问令牌 |

### ChannelConfigs（顶层容器）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `send_progress` | bool | True | 发送进度更新 |
| `send_tool_hints` | bool | True | 发送工具提示 |
| `telegram` | TelegramConfig | — | Telegram 配置 |
| `slack` | SlackConfig | — | Slack 配置 |
| `discord` | DiscordConfig | — | Discord 配置 |
| `feishu` | FeishuConfig | — | 飞书配置 |
| `dingtalk` | DingTalkConfig | — | 钉钉配置 |
| `email` | EmailConfig | — | Email 配置 |
| `qq` | QQConfig | — | QQ 配置 |
| `matrix` | MatrixConfig | — | Matrix 配置 |
| `whatsapp` | WhatsAppConfig | — | WhatsApp 配置 |
| `mochat` | MochatConfig | — | Mochat 配置 |

---

## 6. 权限配置参考

### PermissionMode 值

**源码：** `src/openharness/permissions/modes.py`

| 值 | 行为 |
|-----|------|
| `default` | 变更操作需用户确认 |
| `plan` | 阻止所有变更操作（只允许读取） |
| `full_auto` | 允许所有操作（`--dangerously-skip-permissions` 设置此模式） |

### 工具白名单/黑名单配置

```json
{
  "permission": {
    "mode": "default",
    "allowed_tools": ["FileReadTool", "GrepTool", "GlobTool"],
    "denied_tools": ["BashTool"]
  }
}
```

### 路径规则配置

```json
{
  "permission": {
    "path_rules": [
      {"pattern": "/etc/**", "allow": false},
      {"pattern": "/home/user/projects/**", "allow": true}
    ]
  }
}
```

### 命令拒绝模式

```json
{
  "permission": {
    "denied_commands": ["rm -rf *", "mkfs*", "dd *"]
  }
}
```

### 内置敏感路径保护

以下路径**始终拒绝访问**，不可通过配置覆盖：

- `~/.ssh/`（SSH 密钥）
- `~/.aws/credentials`（AWS 凭证）
- `~/.config/gcloud/`（GCP 凭证）
- `~/.azure/`（Azure 凭证）
- `~/.gnupg/`（GPG 密钥）
- `~/.docker/config.json`（Docker 凭证）
- `~/.kube/config`（Kubernetes 配置）
- `~/.openharness/credentials.json`（OpenHarness 凭证）

---

## 7. 路径配置参考

**源码：** `src/openharness/config/paths.py`

| 函数 | 默认路径 | 环境变量覆盖 | 说明 |
|------|---------|-------------|------|
| `get_config_dir()` | `~/.openharness/` | `OPENHARNESS_CONFIG_DIR` | 配置根目录 |
| `get_config_file_path()` | `~/.openharness/settings.json` | — | 设置文件 |
| `get_data_dir()` | `~/.openharness/data/` | `OPENHARNESS_DATA_DIR` | 数据目录 |
| `get_logs_dir()` | `~/.openharness/logs/` | `OPENHARNESS_LOGS_DIR` | 日志目录 |
| `get_sessions_dir()` | `~/.openharness/data/sessions/` | — | 会话存储 |
| `get_tasks_dir()` | `~/.openharness/data/tasks/` | — | 后台任务输出 |
| `get_cron_registry_path()` | `~/.openharness/data/cron_jobs.json` | — | 定时任务注册表 |
| `get_project_config_dir(cwd)` | `<cwd>/.openharness/` | — | 项目级配置 |

---

## 8. 配置优先级详解

### 加载流程

```
1. 读取 ~/.openharness/settings.json → 基础 Settings
2. 应用环境变量覆盖
   ├── ANTHROPIC_API_KEY → settings.api_key
   ├── OPENHARNESS_MODEL → settings.model
   └── ... (见第 3 节完整列表)
3. 应用 CLI 参数覆盖 (merge_cli_overrides)
   ├── --model → settings.model
   ├── --api-key → settings.api_key
   └── ... (见第 4 节完整列表)
4. 激活配置 (materialize_active_profile)
   └── 将 active_profile 的字段回写到顶层
```

### 示例

```bash
# settings.json 中: {"model": "gpt-5.4", "max_tokens": 4096}
# 环境变量: OPENHARNESS_MODEL=claude-opus-4-6
# CLI: oh --max-tokens 8192

# 最终结果:
#   model = "claude-opus-4-6"    (环境变量覆盖了 settings.json)
#   max_tokens = 8192            (CLI 覆盖了环境变量和 settings.json)
```

---

## 9. 提供商配置参考

### 内置提供商配置

| 配置名 | label | provider | api_format | auth_source | default_model | base_url |
|--------|-------|----------|------------|-------------|---------------|----------|
| `claude-api` | Anthropic-Compatible API | anthropic | anthropic | anthropic_api_key | claude-sonnet-4-6 | — |
| `claude-subscription` | Claude Subscription | anthropic_claude | anthropic | claude_subscription | claude-sonnet-4-6 | — |
| `openai-compatible` | OpenAI-Compatible API | openai | openai | openai_api_key | gpt-5.4 | — |
| `codex` | Codex Subscription | openai_codex | openai | codex_subscription | gpt-5.4 | — |
| `copilot` | GitHub Copilot | copilot | copilot | copilot_oauth | gpt-5.4 | — |
| `moonshot` | Moonshot (Kimi) | moonshot | openai | moonshot_api_key | kimi-k2.5 | api.moonshot.cn/v1 |
| `gemini` | Google Gemini | gemini | openai | gemini_api_key | gemini-2.5-flash | generativelanguage.googleapis.com/v1beta/openai |

### 模型别名解析

| 别名 | 目标模型 | 说明 |
|------|---------|------|
| `default` | claude-sonnet-4-6 | 推荐模型 |
| `best` | claude-opus-4-6 | 最强模型 |
| `sonnet` | claude-sonnet-4-6 | Sonnet |
| `opus` | claude-opus-4-6 | Opus |
| `haiku` | claude-haiku-4-5 | Haiku |
| `sonnet[1m]` | claude-sonnet-4-6[1m] | 1M 上下文 Sonnet |
| `opus[1m]` | claude-opus-4-6[1m] | 1M 上下文 Opus |
| `opusplan` | plan=opus, else=sonnet | 根据模式切换 |

### 添加自定义提供商

```json
{
  "profiles": {
    "my-custom": {
      "label": "My Custom Provider",
      "provider": "deepseek",
      "api_format": "openai",
      "auth_source": "deepseek_api_key",
      "default_model": "deepseek-chat",
      "base_url": "https://api.deepseek.com/v1"
    }
  }
}
```