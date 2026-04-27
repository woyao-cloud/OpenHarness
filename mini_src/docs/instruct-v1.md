 扫描src目录下的python源代码并分析，规划从中抽离出只包含以下模块 core-loop,api-layer, engine, tool-system, memory 的最小可运行代码，交互直接命令行python 运行。先规划再执行。保存到mini-src目录下
 
 ● 
mini-src/ 全部完成。以下是提取结果：

  目录结构（24 个源文件）

  mini-src/
  ├── __init__.py              # 包标记
  ├── __main__.py              # CLI: python -m mini_src "prompt"
  ├── config.py                # 环境变量配置
  ├── requirements.txt         # 依赖: httpx, pydantic
  ├── api/
  │   ├── __init__.py
  │   ├── errors.py            # 错误类型 (copy)
  │   ├── usage.py             # UsageSnapshot (copy)
  │   └── client.py            # HTTPX-based: Anthropic + OpenAI SSE 流式客户端
  ├── tools/
  │   ├── __init__.py
  │   ├── base.py              # BaseTool, ToolRegistry (copy)
  │   └── builtin.py           # Read, Write, Edit, Bash, Glob, Grep 工具
  ├── memory/
  │   ├── __init__.py
  │   ├── types.py             # MemoryHeader (copy)
  │   ├── paths.py             # 简化版路径解析
  │   ├── scan.py              # 简化版文件扫描
  │   ├── search.py            # 简化版关键字搜索
  │   ├── memdir.py            # 简化版 memory prompt
  │   └── manager.py           # 简化版 CRUD (无文件锁)
  └── core/
      ├── __init__.py
      ├── messages.py           # ConversationMessage, ContentBlock (copy)
      ├── events.py             # StreamEvent 类型 (去除了 CompactProgressEvent)
      ├── cost_tracker.py       # Token 累计 (copy)
      ├── loop.py               # run_query() — 去除了 hooks/permissions/compaction
      └── engine.py             # QueryEngine — 去除了 coordinator/hooks/permissions

  核心剥离内容

  ┌──────────────────────────┬────────────────────────┐
  │        移除的依赖        │          替换          │
  ├──────────────────────────┼────────────────────────┤
  │ anthropic SDK            │ HTTPX 直接调用 SSE API │
  ├──────────────────────────┼────────────────────────┤
  │ openai SDK               │ HTTPX 直接调用 SSE API │
  ├──────────────────────────┼────────────────────────┤
  │ HookExecutor / HookEvent │ 完全移除               │
  ├──────────────────────────┼────────────────────────┤
  │ PermissionChecker        │ 完全移除               │
  ├──────────────────────────┼────────────────────────┤
  │ services/log             │ 完全移除               │
  ├──────────────────────────┼────────────────────────┤
  │ services/compact         │ 完全移除               │
  ├──────────────────────────┼────────────────────────┤
  │ coordinator              │ 完全移除               │
  ├──────────────────────────┼────────────────────────┤
  │ utils/file_lock          │ 简化为原子写入         │
  ├──────────────────────────┼────────────────────────┤
  │ utils/fs                 │ 简化为原子写入         │
  ├──────────────────────────┼────────────────────────┤
  │ config/paths             │ 内联到 config.py       │
  └──────────────────────────┴────────────────────────┘

  使用方式

  # 设置 API key（至少一个）
  export ANTHROPIC_API_KEY=sk-ant-...
  # 或 export OPENAI_API_KEY=sk-...

  # 单次查询
  python -m mini_src "列出当前目录的 Python 文件"

  # 交互模式
  python -m mini_src

  # 自定义模型
  export OPENHARNESS_MODEL=claude-sonnet-4-6
  python -m mini_src "你的提示"

  # 自定义端点
  export OPENHARNESS_BASE_URL=https://your-proxy.com/v1
  python -m mini_src "你的提示"

  已验证

  - 所有 24 个源文件导入通过
  - 基本对话流（mock）：AssistantTextDelta → AssistantTurnComplete
  - 单工具执行流：ToolExecutionStarted → ToolExecutionCompleted → 下一轮
  - 并发多工具执行：两个工具同时启动，结果正确聚合
  - Token 累计：跨轮次正确累加
  - MaxTurnsExceeded：达到上限时正确抛出


  如何调整代码以便使用最新的大模型deepseek-v4-flash

  ● 全部完成。使用 DeepSeek V4 Flash 只需设置环境变量：

  # 方式 1：最简单 —— 自动配置
  export DEEPSEEK_API_KEY=sk-your-key
  export OPENHARNESS_MODEL=deepseek-chat
  python -m mini_src "你好，请列出当前目录的文件"

  # 方式 2：显式指定（兼容所有 OpenAI API 提供商）
  export OPENAI_API_KEY=sk-your-key
  export OPENHARNESS_BASE_URL=https://api.deepseek.com/v1
  export OPENHARNESS_MODEL=deepseek-chat
  python -m mini_src "你好"

  改动的 3 个文件

  ┌───────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │     文件      │                                                                          改动                                                                          │
  ├───────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ config.py     │ 新增 PROVIDER_CONFIGS 支持 3 个内置 provider（anthropic/openai/deepseek）；新增 DEEPSEEK_API_KEY 环境变量自动检测；新增 needs_max_completion_tokens()  │
  │               │ 自动识别需要 max_completion_tokens 参数的模型（如 deepseek-reasoner）                                                                                  │
  ├───────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ api/client.py │ OpenAICompatibleClient._stream_once() 根据模型名自动选择 max_tokens 或 max_completion_tokens 参数                                                      │
  ├───────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ __main__.py   │ build_api_client() 识别 deepseek provider 并使用正确的基础 URL；文档添加了 DeepSeek 示例                                                               │
  └───────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  支持的模型命名

  - deepseek-chat — DeepSeek V3 / 最新对话模型（使用 max_tokens）
  - deepseek-reasoner — DeepSeek R1 推理模型（自动使用 max_completion_tokens）
  - deepseek-v4-flash — 直接设置 OPENHARNESS_MODEL=deepseek-v4-flash 即可