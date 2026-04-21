# OpenHarness 数据流图

> 本文档描述 OpenHarness 系统各核心模块之间的数据流转关系，涵盖启动序列、查询循环、渠道消息、认证流程、配置加载优先级以及多智能体协作六大场景。

---

## 1. 启动流程序列图 (Startup Sequence)

```
  python -m openharness
          |
          v
  +------------------+
  |   __main__.py    |   入口模块，导入 cli.app 并调用
  +------------------+
          |
          v
  +------------------+
  |   cli.py:main()  |   Typer 回调函数，解析所有 CLI 参数
  +------------------+
          |
          |  根据 --print / --task-worker / 默认 分派到三种模式
          |
    +-----+------------------+-----------------------+
    |                         |                       |
    v                         v                       v
+-----------+          +-------------+        +---------------+
| 交互模式   |          | 打印模式     |        | 任务工作器模式 |
| run_repl()|          |run_print_   |        |run_task_      |
|           |          |mode()       |        |worker()       |
+-----------+          +-------------+        +---------------+
    |                         |                       |
    v                         v                       v
+-----------------------------------------------------------+
|              build_runtime()  构建运行时                    |
|  (以下为组装步骤，按序号依次执行)                              |
|                                                             |
|  1. load_settings()                                         |
|     +-- merge_cli_overrides()  合并 CLI 覆盖参数             |
|                                                             |
|  2. load_plugins()                                          |
|     +-- 发现 skills / commands / agents / hooks / mcp 插件    |
|                                                             |
|  3. _resolve_api_client_from_settings()                     |
|     +-- copilot  --> CopilotClient                          |
|     +-- openai_codex --> CodexApiClient                     |
|     +-- anthropic_claude --> AnthropicApiClient             |
|     +-- openai  --> OpenAICompatibleClient                  |
|     +-- 默认 --> AnthropicApiClient                         |
|                                                             |
|  4. McpClientManager                                        |
|     +-- load_mcp_server_configs() 加载 MCP 服务器配置         |
|     +-- connect_all()  连接所有 MCP 服务器                   |
|                                                             |
|  5. create_default_tool_registry()                          |
|     +-- 注册 37 个内置工具                                    |
|     +-- 注册 MCP 动态工具 (McpToolAdapter)                   |
|                                                             |
|  6. detect_provider() --> ProviderInfo                      |
|                                                             |
|  7. load_hook_registry() --> HookExecutor                   |
|     +-- HookReloader 监控配置变更热重载                       |
|                                                             |
|  8. build_runtime_system_prompt()                           |
|     +-- 组装系统提示词 (包含 CLAUDE.md / skills / context)    |
|                                                             |
|  9. QueryEngine()                                           |
|     +-- 绑定 api_client / tool_registry / permissions        |
|     +-- 设置 max_turns / auto_compact 阈值                   |
|                                                             |
| 10. AppState --> AppStateStore                               |
|     +-- 持久化 UI 状态 (model / theme / provider / auth)     |
+-----------------------------------------------------------+
          |
          v
  +------------------+
  | start_runtime()  |   执行 SESSION_START 钩子
  +------------------+
          |
          v
    +-------------------+    +------------------+    +--------------------+
    | 交互: React TUI   |    | 打印: stream 输出|    | 工作器: stdin 循环  |
    | 输入循环           |    | 后直接退出        |    | 处理后退出          |
    +-------------------+    +------------------+    +--------------------+
```

### 启动流程说明

1. **入口调用链**: 用户执行 `python -m openharness` 时，Python 解释器加载 `__main__.py`，该模块从 `cli.py` 导入 Typer `app` 并调用。
2. **CLI 参数解析**: `cli.py:main()` 使用 Typer 解析所有命令行参数（包括 `--model`、`--print`、`--task-worker`、`--api-key` 等）。
3. **模式分派**: 根据参数选择三种运行模式之一：
   - **交互模式** (`run_repl()`): 启动 React TUI 界面，用户可进行多轮对话。
   - **打印模式** (`run_print_mode()`): 提交单条 prompt，流式输出后退出。
   - **任务工作器** (`run_task_worker()`): 从 stdin 读取输入循环处理，用于后台任务。
4. **运行时组装**: `build_runtime()` 按固定顺序完成 10 步组装，依次为：加载配置、发现插件、解析 API 客户端、连接 MCP 服务器、注册工具、检测 Provider、加载钩子、构建系统提示词、创建查询引擎、初始化应用状态。
5. **钩子启动**: `start_runtime()` 执行 `SESSION_START` 生命周期钩子，完成后进入主循环。

---

## 2. 查询循环数据流图 (Query Loop Data Flow)

```
  用户输入
     |
     v
+-------------------+
| handle_line()     |    判断是斜杠命令还是普通 prompt
+-------------------+
     |                            |
     | 斜杠命令                    | 普通 prompt
     v                            v
+------------------+    +-------------------------+
| commands.lookup() |    | engine.submit_message() |
| 执行命令处理函数   |    +-------------------------+
+------------------+              |
                                  v
                    +---------------------------+
                    |      QueryEngine          |
                    |  1. 追加用户消息到历史      |
                    |  2. remember_user_goal()   |
                    |  3. 构建 QueryContext      |
                    +---------------------------+
                                  |
                                  v
              +----------------------------------------+
              |           run_query() 循环              |
              |                                        |
              |  +---------+                           |
              |  | Turn N  |<--------------------------+
              |  +---------+                            |
              |       |                                 |
              |       v                                 |
              |  +----------------------------+        |
              |  | auto_compact_if_needed()    |        |
              |  |  检查 token 阈值，          |        |
              |  |  超限则执行微压缩或 LLM 摘要 |        |
              |  +----------------------------+        |
              |       |                                 |
              |       v                                 |
              |  +----------------------------+        |
              |  | api_client.stream_message()|        |
              |  |  发送消息流式接收响应        |        |
              |  +----------------------------+        |
              |       |                                 |
              |       v                                 |
              |  +----------------------------+        |
              |  | 解析流事件                  |        |
              |  +----------------------------+        |
              |       |                                 |
              |       +-- ApiTextDeltaEvent             |
              |       |   --> yield AssistantTextDelta   |
              |       |                                  |
              |       +-- ApiMessageCompleteEvent        |
              |           --> 提取 tool_use blocks       |
              |       |                                  |
              |       v                                 |
              |  +----------------------------+        |
              |  | assistant 有 tool_use ?    |        |
              |  +----------------------------+        |
              |     |                 |                |
              |     | 否              | 是              |
              |     v                 v                |
              |  返回结果      +-------------------+    |
              |               | _execute_tool_call|   |
              |               +-------------------+    |
              |                    |                   |
              |                    v                   |
              |               +-------------------+   |
              |               | 1. pre_tool_use   |   |
              |               |    钩子检查        |   |
              |               +-------------------+   |
              |                    |                   |
              |                    v                   |
              |               +-------------------+   |
              |               | 2. permission      |   |
              |               |    权限检查         |   |
              |               |  (允许/确认/拒绝)   |   |
              |               +-------------------+   |
              |                    |                   |
              |                    v                   |
              |               +-------------------+   |
              |               | 3. tool.execute()  |   |
              |               |    执行工具          |   |
              |               +-------------------+   |
              |                    |                   |
              |                    v                   |
              |               +-------------------+   |
              |               | 4. post_tool_use   |   |
              |               |    钩子执行         |   |
              |               | 5. _record_carryover|  |
              |               |    记录工具元数据     |  |
              |               +-------------------+   |
              |                    |                   |
              |                    v                   |
              |          tool_result --> 作为用户消息   |
              |          追加到 messages 列表            |
              |                    |                   |
              |                    +----> Turn N+1 ---+
              |
              |  直到: 无 tool_use 或 达到 max_turns
              v
        +------------------+
        | MaxTurnsExceeded |  (可选)
        | 保存快照到会话后端 |
        +------------------+

  --- 自动压缩路径 (Auto-Compact) ---
  每个 Turn 开始前:
  token 估算 > 阈值?
       |
       | 是
       v
  microcompact (清除旧 tool_result 内容)
       |
       v
  仍超限?
       |
       | 是
       v
  LLM 全量摘要压缩 (auto_compact_if_needed)

  --- 反应式压缩路径 (Reactive-Compact) ---
  API 返回 "prompt too long" 错误:
       |
       v
  强制执行全量压缩后重试当前 Turn
```

### 查询循环说明

1. **输入分发**: `handle_line()` 判断输入是否为斜杠命令。若是，执行命令处理函数；若否，提交给 QueryEngine。
2. **消息提交**: `engine.submit_message()` 将用户消息追加到对话历史，调用 `remember_user_goal()` 记录用户意图，构建 `QueryContext`。
3. **Agentic 循环**: `run_query()` 是核心循环，每个 Turn 执行以下步骤：
   - **自动压缩检查**: 估算 token 数，超过阈值先尝试微压缩（清除旧 tool_result），不够则执行 LLM 摘要压缩。
   - **API 调用**: 通过 `api_client.stream_message()` 流式获取模型响应。
   - **事件解析**: 区分文本增量和消息完成事件，从中提取 `tool_use` 块。
   - **工具执行**: 对每个 `tool_use` 依次执行：pre_tool_use 钩子 -> 权限检查 -> 工具执行 -> post_tool_use 钩子 -> 元数据记录。
   - **结果反馈**: 工具结果作为用户消息追加到 messages，进入下一轮 Turn。
4. **循环终止**: 当模型不再请求工具调用，或超过 `max_turns` 限制时，循环终止。
5. **反应式压缩**: 若 API 返回 "prompt too long" 错误，触发强制压缩后重试。

---

## 3. 渠道消息数据流图 (Channel Message Data Flow)

```
  用户 (Telegram / Slack / Discord / 飞书 / 钉钉 / QQ / Matrix / WhatsApp / Email / Mochat)
     |
     v
+------------------------------------------------------------------+
|  BaseChannel.start()                                              |
|  渠道适配器监听平台消息                                             |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  BaseChannel._handle_message(sender_id, chat_id, content, ...)    |
|  1. is_allowed(sender_id)  权限检查 (allow_from 白名单)           |
|  2. 构建 InboundMessage                                           |
+------------------------------------------------------------------+
     |  权限通过
     v
+------------------------------------------------------------------+
|  MessageBus.publish_inbound(msg)                                  |
|  写入 asyncio.Queue[InboundMessage]                               |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  ChannelBridge._loop()                                            |
|  bus.consume_inbound()  阻塞等待下一条入站消息                       |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  ChannelBridge._handle(msg)                                       |
|  engine.submit_message(msg.content)                                |
|     |                                                             |
|     v                                                             |
|  AsyncIterator[StreamEvent]                                       |
|     |                                                             |
|     +-- AssistantTextDelta  --> 收集文本片段                        |
|     +-- AssistantTurnComplete --> Turn 完成                         |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  拼接所有文本片段为完整回复                                          |
|  构建 OutboundMessage(channel, chat_id, content)                  |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  MessageBus.publish_outbound(outbound)                            |
|  写入 asyncio.Queue[OutboundMessage]                               |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  ChannelManager._dispatch_outbound()                               |
|  bus.consume_outbound()  阻塞等待下一条出站消息                       |
+------------------------------------------------------------------+
     |
     v
+------------------------------------------------------------------+
|  路由到目标渠道:                                                    |
|  channels[msg.channel].send(msg)                                  |
|  根据 msg.channel 字段选择对应渠道实例                               |
+------------------------------------------------------------------+
     |
     v
  +--------------+  +--------------+  +--------------+
  | Telegram.send |  | Slack.send   |  | Discord.send |
  +--------------+  +--------------+  +--------------+
     |
     v
  用户收到回复
```

### 渠道消息数据流说明

1. **消息接入**: 各渠道适配器（Telegram、Slack、Discord、飞书、钉钉、QQ、Matrix、WhatsApp、Email、Mochat）在 `start()` 时连接对应平台并监听消息。
2. **权限过滤**: `_handle_message()` 首先调用 `is_allowed(sender_id)` 检查发送者是否在 `allow_from` 白名单中。空列表拒绝所有访问，`["*"]` 允许所有人。
3. **入站发布**: 通过消息的渠道消息写入 `MessageBus.inbound` 队列（asyncio.Queue）。
4. **桥接消费**: `ChannelBridge._loop()` 持续从 inbound 队列消费消息，提交给 `QueryEngine`。
5. **引擎处理**: `engine.submit_message()` 执行完整的 Agentic 循环，流式产生 `StreamEvent`。
6. **回复组装**: 桥接收集所有 `AssistantTextDelta` 事件拼接为完整文本，构建 `OutboundMessage`。
7. **出站发布**: 写入 `MessageBus.outbound` 队列。
8. **出站分发**: `ChannelManager._dispatch_outbound()` 从 outbound 队列消费，根据 `msg.channel` 字段路由到对应渠道的 `send()` 方法，最终发送到用户所在的聊天平台。

---

## 4. 认证流程序列图 (Authentication Flow)

```
  oh auth login / oh setup
          |
          v
  +------------------------+
  |  选择认证流程            |
  |  AuthManager 根据       |
  |  provider 类型分派       |
  +------------------------+
          |
          +------------------+-------------------+
          |                  |                   |
          v                  v                   v
  +----------------+  +------------------+  +------------------+
  |  ApiKeyFlow    |  | DeviceCodeFlow   |  |  BrowserFlow     |
  |  API 密钥流程   |  | 设备码授权流程    |  |  浏览器授权流程   |
  +----------------+  +------------------+  +------------------+
          |                  |                   |
          v                  v                   v
  +----------------+  +------------------+  +------------------+
  | getpass 提示    |  | request_device_  |  | 打开浏览器       |
  | 用户输入密钥    |  | code()           |  | 用户认证          |
  |                |  | 获取 client_id   |  |                  |
  +----------------+  | 请求设备码        |  | 粘贴 token       |
          |           +------------------+  +------------------+
          v                  |                   |
  +----------------+         v                   v
  | store_         |  +------------------+  +------------------+
  | credential()   |  | 打印验证 URL      |  | getpass 提示     |
  | 存储到         |  | 和用户码          |  | 用户粘贴 token   |
  | credentials.  |  +------------------+  +------------------+
  | json 或 keyring|         |                   |
  +----------------+         v                   v
                    +------------------+  +------------------+
                    | poll_for_access_ |  | store_           |
                    | token()          |  | credential()     |
                    | 轮询等待用户授权  |  | 存储凭据          |
                    +------------------+  +------------------+
                             |
                             v
                    +------------------+
                    | store_credential |
                    | ()               |
                    +------------------+


  --- 供应商配置管理 (Profile CRUD) ---

  +---------------------------------------------+
  |           AuthManager                       |
  +---------------------------------------------+
          |
          +--- list_profiles()  列出所有供应商配置
          |
          +--- use_profile(name)  切换活跃配置
          |       |
          |       v
          |   settings.active_profile = name
          |   save_settings()
          |
          +--- update_profile(name, ...)  更新配置字段
          |       |
          |       v
          |   profiles[name] = updated_profile
          |   save_settings()
          |
          +--- upsert_profile(name, profile)  创建/替换配置
          |       |
          |       v
          |   profiles[name] = profile
          |   save_settings()
          |
          +--- remove_profile(name)  删除自定义配置
          |       |
          |       v
          |   del profiles[name]
          |   save_settings()
          |
          +--- switch_provider(name)  统一切换入口
          |       |-- 名称在 _AUTH_SOURCES 中 --> switch_auth_source()
          |       |-- 名称在 profiles 中 --> use_profile()
          |       |-- 名称在 _KNOWN_PROVIDERS 中 --> 映射后 use_profile()
          |
          +--- store_credential(provider, key, value)
          |       |
          |       +-- keyring 可用 --> keyring.set_password()
          |       +-- 否则 --> credentials.json (mode 600)
          |
          +--- clear_credential(provider)
                  |
                  +-- keyring.delete_password()
                  +-- 从 credentials.json 中删除
```

### 认证流程说明

1. **三种认证流程**:
   - **ApiKeyFlow**: 最简单的流程，通过 `getpass` 提示用户输入 API 密钥，直接返回字符串。
   - **DeviceCodeFlow**: GitHub OAuth 设备码流程。先请求设备码，打印验证 URL 和用户码，尝试自动打开浏览器，然后轮询等待用户在浏览器中完成授权，获取 access token。
   - **BrowserFlow**: 打开浏览器让用户完成认证，用户完成后将 token 粘贴回来。
2. **凭据存储**: 所有流程获取的凭据最终通过 `store_credential()` 持久化。优先使用系统 keyring（如果可用），否则存储到 `~/.openharness/credentials.json`（文件权限 600）。
3. **配置管理**: `AuthManager` 提供完整的供应商配置 CRUD 操作：
   - `list_profiles()`: 列出所有配置。
   - `use_profile()`: 切换活跃配置。
   - `update_profile()`: 更新配置字段。
   - `remove_profile()`: 删除自定义配置（内置配置不可删除）。
   - `switch_provider()`: 统一切换入口，支持按认证源、配置名或供应商名切换。

---

## 5. 配置加载优先级图 (Configuration Loading Priority)

```
  优先级 (高 --> 低)

  +=============================================================+
  |  CLI 命令行参数 (最高优先级)                                    |
  |  --model sonnet  --base-url https://...  --api-key sk-...   |
  +=============================================================+
          |  覆盖
          v
  +=============================================================+
  |  环境变量                                                     |
  |  OPENHARNESS_MODEL / ANTHROPIC_MODEL                         |
  |  ANTHROPIC_API_KEY / OPENAI_API_KEY                         |
  |  OPENHARNESS_BASE_URL / ANTHROPIC_BASE_URL                  |
  |  OPENHARNESS_API_FORMAT / OPENHARNESS_PROVIDER              |
  |  OPENHARNESS_MAX_TOKENS / OPENHARNESS_MAX_TURNS             |
  |  OPENHARNESS_VERBOSE / OPENHARNESS_SANDBOX_ENABLED          |
  +=============================================================+
          |  覆盖
          v
  +=============================================================+
  |  ~/.openharness/settings.json (用户配置文件)                   |
  |  {                                                           |
  |    "model": "claude-sonnet-4-6",                             |
  |    "api_key": "",                                            |
  |    "base_url": "",                                           |
  |    "profiles": { ... },                                      |
  |    "mcp_servers": { ... }                                    |
  |  }                                                           |
  +=============================================================+
          |  覆盖
          v
  +=============================================================+
  |  内置默认值 (最低优先级)                                        |
  |  Settings() 构造函数中的默认值                                  |
  |  model = "claude-sonnet-4-6"                                |
  |  max_tokens = 16384                                          |
  |  max_turns = 200                                             |
  |  permission_mode = "default"                                 |
  +=============================================================+


  --- 配置合并流程: merge_cli_overrides() ---

  +------------------+
  |  Settings()      |  内置默认值
  +------------------+
          |
          v
  +------------------+       +-------------------+
  |  load_settings() |  <--  | settings.json     |
  |  从文件加载       |       | 读取并验证 JSON    |
  +------------------+       +-------------------+
          |
          v
  +------------------------+
  |  _apply_env_overrides |
  |  ()                    |
  |  环境变量覆盖文件值     |
  |  ANTHROPIC_MODEL       |
  |  --> settings.model    |
  |  ANTHROPIC_API_KEY     |
  |  --> settings.api_key  |
  +------------------------+
          |
          v
  +----------------------------+
  |  merge_cli_overrides()     |
  |  CLI 参数覆盖环境变量和文件值|
  |  仅非 None 值参与覆盖       |
  |  model=model  -->          |
  |    settings.model = model  |
  |  api_key=key   -->         |
  |    settings.api_key = key  |
  +----------------------------+
          |
          v
  +----------------------------+
  |  最终生效的 Settings 实例     |
  |  settings.model = "sonnet" |
  |  (来自 CLI --model 参数)    |
  +----------------------------+


  --- 示例: model 字段的优先级覆盖链 ---

  CLI: --model sonnet
    --> 生效值: "sonnet" (CLI 最高优先级)

  环境变量: OPENHARNESS_MODEL=claude-opus-4-5
    --> 生效值: "claude-opus-4-5" (环境变量覆盖文件)

  settings.json: {"model": "claude-sonnet-4-6"}
    --> 生效值: "claude-sonnet-4-6" (文件覆盖默认值)

  默认值: Settings().model = "claude-sonnet-4-6"
    --> 生效值: "claude-sonnet-4-6" (无更高优先级时使用默认值)
```

### 配置加载优先级说明

1. **四层优先级**: 从高到低依次为 CLI 命令行参数、环境变量、用户配置文件 (`~/.openharness/settings.json`)、内置默认值。
2. **加载流程**: `load_settings()` 先从 `settings.json` 读取并验证 JSON，然后调用 `_apply_env_overrides()` 用环境变量覆盖文件值。运行时通过 `merge_cli_overrides()` 用 CLI 参数覆盖当前值。
3. **合并策略**: `merge_cli_overrides()` 仅接受非 None 值作为覆盖，避免将未指定的 CLI 参数误写为空值。覆盖后自动同步活跃配置 (`sync_active_profile_from_flat_fields()`)。
4. **示例说明**: 以 `model` 字段为例，`--model sonnet` (CLI) 覆盖 `OPENHARNESS_MODEL=claude-opus-4-5` (环境变量) 覆盖 `settings.json` 中的 `"claude-sonnet-4-6"` (文件值) 覆盖默认值 `"claude-sonnet-4-6"`。
5. **动态刷新**: 运行时通过 `RuntimeBundle.current_settings()` 重新加载配置并应用 CLI 覆盖，确保斜杠命令修改配置后 UI 状态与磁盘一致。

---

## 6. 多智能体协作数据流图 (Multi-Agent Swarm Data Flow)

```
  +================================================================+
  |                    主会话 (Leader Agent)                         |
  |  is_coordinator_mode() = True                                   |
  |  系统提示词以 "You are a coordinator" 开头                       |
  +================================================================+
          |
          |  用户请求复杂任务
          v
  +----------------------------------------------+
  |  AgentTool.execute()                         |
  |  1. get_agent_definition(subagent_type)      |
  |  2. get_backend_registry()                   |
  |  3. executor.spawn(config)                   |
  +----------------------------------------------+
          |
          |  BackendRegistry 检测可用后端
          |
          +------------------+-----------------------+------------------+
          |                  |                       |                  |
          v                  v                       v                  v
  +---------------+  +---------------+  +------------------+  +---------------+
  | subprocess    |  | in_process    |  | tmux             |  | iTerm2        |
  | 后端 (默认)    |  | 进程内后端    |  | 终端分屏后端      |  | 终端分屏后端   |
  +---------------+  +---------------+  +------------------+  +---------------+
          |                  |                       |                  |
          v                  v                       v                  v
  +----------------+  +-----------+  +--------------------+  +------------+
  | Worker Agent 1 |  | Worker 2  |  | Worker 3 (tmux    |  | Worker 4   |
  | 子进程          |  | 进程内    |  | 窗格可见)         |  | iTerm2 窗格|
  +----------------+  +-----------+  +--------------------+  +------------+


  --- 消息通信机制: TeammateMailbox (基于 JSON 文件) ---

  +==================================================================+
  |  ~/.openharness/teams/<team_name>/                               |
  |    agents/                                                       |
  |      worker1@team/                                               |
  |        inbox/                                                    |
  |          1703123456.789_abc123.json    <-- 单条消息文件            |
  |          1703123457.123_def456.json                               |
  |      worker2@team/                                               |
  |        inbox/                                                    |
  |          1703123458.456_ghi789.json                               |
  +==================================================================+

  消息类型 (MessageType):
  +--------------------+--------------------------------------------+
  | user_message       | 普通用户/协调者消息                          |
  | permission_request | 工作器请求权限 (worker --> leader)           |
  | permission_response| 协调者响应权限 (leader --> worker)           |
  | sandbox_permission  | 沙箱权限请求 (worker --> leader)            |
  | _request           |                                            |
  | sandbox_permission  | 沙箱权限响应 (leader --> worker)            |
  | _response          |                                            |
  | shutdown           | 关闭请求                                    |
  | idle_notification  | 工作器空闲通知                               |
  +--------------------+--------------------------------------------+


  --- 权限请求/响应流程 ---

  Worker Agent 执行工具时遇到权限检查:
     |
     v
  +------------------------------+
  | create_permission_request_   |
  | message()                    |
  | worker --> leader            |
  | 包含: tool_name, input,      |
  | description, request_id      |
  +------------------------------+
     |
     v  写入 leader 的 inbox
  +------------------------------+
  | TeammateMailbox.write()      |
  | 原子写入: .tmp --> .json     |
  +------------------------------+
     |
     v  Leader 读取
  +------------------------------+
  | TeammateMailbox.read_all()   |
  | 按时间戳排序返回未读消息       |
  +------------------------------+
     |
     v  Leader 做出决策
  +------------------------------+
  | create_permission_response_  |
  | message()                    |
  | leader --> worker             |
  | 包含: subtype (success/error)|
  | updated_input, permission_   |
  | updates                      |
  +------------------------------+
     |
     v  写入 worker 的 inbox
  +------------------------------+
  | TeammateMailbox.write()      |
  | 原子写入                     |
  +------------------------------+


  --- 消息投递路径: send_message 工具 ---

  +---------------------------+
  | SendMessageTool.execute() |
  +---------------------------+
     |
     +-- task_id 含 "@" (agent_id 格式: name@team)
     |       |
     |       v
     |   +-------------------------+
     |   | _send_swarm_message()   |
     |   | registry.get_executor()|
     |   | executor.send_message() |
     |   +-------------------------+
     |
     +-- task_id 为普通 ID
             |
             v
         +-------------------------+
         | TaskManager.write_to_  |
         | task()                  |
         | 写入子进程 stdin         |
         +-------------------------+


  --- 协调者模式编排 ---

  +====================================================================+
  |                     Coordinator 模式                               |
  |                                                                    |
  |  1. 研究阶段 (Research):                                            |
  |     Leader 并行派出多个 Worker 执行只读研究任务                        |
  |     agent(description="研究认证缺陷", prompt="...")                 |
  |     agent(description="调研安全存储", prompt="...")                 |
  |                                                                    |
  |  2. 综合阶段 (Synthesis):                                          |
  |     Leader 读取 Worker 返回的 <task-notification> XML              |
  |     理解发现后编写具体实施规格                                       |
  |                                                                    |
  |  3. 实施阶段 (Implementation):                                     |
  |     Leader 派出 Worker 执行具体代码修改                              |
  |     send_message(to="agent-a1b", message="修复方案...")             |
  |                                                                    |
  |  4. 验证阶段 (Verification):                                       |
  |     Leader 派出独立 Worker 验证实施结果                              |
  |     独立测试、运行类型检查                                           |
  +====================================================================+


  --- Bridge 会话 (连接外部会话) ---

  +---------------------------+      +----------------------------+
  | BridgeSessionManager      |      | spawn_session()            |
  | +-- spawn(session_id,     | --->  | 创建子进程 (stdout=PIPE)   |
  |      command, cwd)        |      | 返回 SessionHandle         |
  | +-- list_sessions()       |      +----------------------------+
  | +-- stop(session_id)      |                |
  | +-- read_output(id)       |                v
  +---------------------------+      +----------------------------+
                                      | SessionHandle              |
                                      | process: asyncio.subprocess|
                                      | cwd: 工作目录              |
                                      | started_at: 启动时间        |
                                      +----------------------------+
```

### 多智能体协作数据流说明

1. **协调者模式**: 当环境变量 `CLAUDE_CODE_COORDINATOR_MODE=1` 时，主会话以协调者身份运行，系统提示词声明 "You are a coordinator"。协调者负责调度工人代理完成任务。
2. **Worker 派生**: `AgentTool` 通过 `BackendRegistry` 获取执行器并调用 `spawn()` 创建工人代理。后端检测优先级为：in_process 降级 > tmux > subprocess (默认回退)。
3. **消息通信**: 使用基于 JSON 文件的 `TeammateMailbox` 实现 Leader-Worker 间通信。每个 Agent 的 inbox 目录下，每条消息是一个独立的 JSON 文件，通过 `.tmp` + `os.replace` 实现原子写入，防止并发读取到不完整的消息。
4. **权限同步**: Worker 执行需要权限的工具时，向 Leader 的 inbox 写入 `permission_request` 消息。Leader 读取后做出决策，将 `permission_response` 写回 Worker 的 inbox。Worker 据此决定是否执行工具。
5. **消息投递**: `SendMessageTool` 根据 `task_id` 格式路由消息：含 `@` 的 agent_id 格式走 swarm 路径（通过 TeammateMailbox），普通 task_id 走 TaskManager（写入子进程 stdin）。
6. **协作编排**: 协调者按四个阶段编排任务：研究（并行派出多个 Worker 执行只读任务）-> 综合（Leader 理解发现并编写具体规格）-> 实施（派出 Worker 执行代码修改）-> 验证（独立 Worker 测试结果）。
7. **Bridge 会话**: `BridgeSessionManager` 管理桥接子进程会话，每个会话通过 `spawn_session()` 创建子进程，输出被异步复制到日志文件，支持查看和终止操作。