  Phase 2 总结: 核心数据类型

  1. 消息模型 (engine/messages.py) — 全系统最核心的数据结构

  四种内容块 (ContentBlock), 用 discriminator="type" 实现多态:

  ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock

  ┌─────────────────┬────────────────────┬────────────────────────────────┬──────────────────┐
  │      类型       │        标识        │            关键字段            │      谁产生      │
  ├─────────────────┼────────────────────┼────────────────────────────────┼──────────────────┤
  │ TextBlock       │ type="text"        │ text: str                      │ 用户/模型        │
  ├─────────────────┼────────────────────┼────────────────────────────────┼──────────────────┤
  │ ImageBlock      │ type="image"       │ media_type, data(base64)       │ 用户             │
  ├─────────────────┼────────────────────┼────────────────────────────────┼──────────────────┤
  │ ToolUseBlock    │ type="tool_use"    │ id, name, input                │ 模型请求调用工具 │
  ├─────────────────┼────────────────────┼────────────────────────────────┼──────────────────┤
  │ ToolResultBlock │ type="tool_result" │ tool_use_id, content, is_error │ 工具执行后返回   │
  └─────────────────┴────────────────────┴────────────────────────────────┴──────────────────┘

  ConversationMessage — 一条对话消息:
  role: "user" | "assistant"
  content: list[ContentBlock]  # 可以混合多种块!

  关键设计: 一条 assistant 消息可以同时包含文本和多个工具调用。例如模型回复"我来读取文件"并附带 3 个 ToolUseBlock, 全在一条消息里。

  辅助方法:
  - text 属性 → 提取所有文本块拼接
  - tool_uses 属性 → 提取所有工具调用块
  - from_user_text() → 快捷构造纯文本用户消息
  - to_api_param() → 序列化为 API 请求格式
  - is_effectively_empty() → 判断是否空消息 (过滤遗留空 assistant 消息)

  2. 事件流 (engine/stream_events.py) — Agent Loop 的输出信号

  QueryEngine 不直接返回结果, 而是异步生成 StreamEvent:

  StreamEvent = AssistantTextDelta       # 流式文本增量
             | AssistantTurnComplete     # 一轮完成 (含完整消息+用量)
             | ToolExecutionStarted      # 即将执行工具
             | ToolExecutionCompleted    # 工具执行完毕
             | ErrorEvent               # 错误 (可恢复/不可恢复)
             | StatusEvent              # 状态提示
             | CompactProgressEvent     # 上下文压缩进度

  消息 vs 事件的区别:
  - ConversationMessage 是持久数据, 存储在对话历史中
  - StreamEvent 是瞬态信号, 用于 UI 实时渲染, 不持久化

  3. 用量追踪 (engine/cost_tracker.py + api/usage.py)

  极简设计:
  UsageSnapshot:  input_tokens + output_tokens (不可变 Pydantic 模型)
  CostTracker:    累加器, add() 合并 UsageSnapshot

  4. 配置系统 (config/)

  路径约定 (paths.py):
  ~/.openharness/                    # 基础目录
    ├── settings.json                # 全局配置
    ├── data/                        # 数据
    │   ├── sessions/                # 会话快照
    │   ├── tasks/                   # 后台任务
    │   └── cron_jobs.json           # 定时任务
    ├── logs/                        # 日志
    └── {project}/.openharness/      # 项目级配置

  所有目录都支持 OPENHARNESS_*_DIR 环境变量覆盖。

  Settings 模型 (settings.py, 870 行) — 项目最大的配置文件:

  Settings (Pydantic BaseModel)
  ├── API: model, max_tokens, base_url, api_format, provider, timeout
  ├── Profiles: active_profile, profiles{dict[str, ProviderProfile]}
  ├── Behavior: permission{PermissionSettings}, hooks, memory{MemorySettings}, sandbox{SandboxSettings}
  ├── Integrations: mcp_servers, enabled_plugins
  ├── UI: theme, output_style, vim_mode, voice_mode, fast_mode, effort
  └── 方法: resolve_profile(), resolve_auth(), merge_cli_overrides()

  配置解析优先级 (从高到低):
  1. CLI 参数 (--model, --api-key 等)
  2. 环境变量 (ANTHROPIC_API_KEY, OPENHARNESS_MODEL 等)
  3. 配置文件 (~/.openharness/settings.json)
  4. 代码默认值

  ProviderProfile — 多 Provider 架构的核心:
  class ProviderProfile:
      label: str              # "Anthropic-Compatible API"
      provider: str           # "anthropic" | "openai" | "copilot" 等
      api_format: str         # "anthropic" | "openai" | "copilot"
      auth_source: str        # "anthropic_api_key" | "copilot_oauth" 等
      default_model: str      # "claude-sonnet-4-6"
      base_url: str | None    # 自定义端点
      last_model: str | None  # 用户上次选择的模型
      credential_slot: str | None  # 独立密钥槽位

  模型别名解析:
  "sonnet" → "claude-sonnet-4-6"
  "opus"   → "claude-opus-4-6"
  "haiku"  → "claude-haiku-4-5"
  "best"   → "claude-opus-4-6"
  "opusplan" → plan模式用opus, 否则用sonnet
  "default" → 跟随 profile 的 default_model

  Channel 配置 (schema.py) — ohmo 消息通道的配置模型, 每个通道有 enabled + allow_from + 特定字段。

  ---
  Phase 2 关键收获:
  - ConversationMessage + 4 种 ContentBlock 是数据流经全系统的唯一格式
  - StreamEvent 是 Agent Loop 对外的异步信号, UI 据此渲染
  - Settings 是多层合并 (文件 → env → CLI → profile materialization), 比表面看起来复杂