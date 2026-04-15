 入口与启动流程

 开始 Phase 1: 入口与启动流程。先读三个关键文件。

  Read 3 files (ctrl+o to expand)

● 好, __main__.py 极简单 — 直接调 cli.app()。现在读 cli.py, 这是项目最大文件 (1420 行)。我先分段读, 找入口函数。

  Searched for 1 pattern, read 1 file, called plugin:oh-my-claudecode:t (ctrl+o to expand)

● 现在读取 ui/app.py — 这是 main() 实际调用的目标, 看 run_repl 和 run_print_mode 怎么组装核心对象。

  Read 1 file (ctrl+o to expand)

● 关键 — build_runtime 是组装核心对象的地方。读 ui/runtime.py:

  Read 1 file (ctrl+o to expand)

● 好了, Phase 1 的关键文件全部读完。现在来总结:

  ---
  Phase 1 总结: 入口与启动流程

  调用链总览

  python -m openharness          # __main__.py
    └→ cli.app()                # Typer CLI, 注册子命令 + main()
         └→ main()              # 解析 CLI 参数, 分三路:
             ├→ run_repl()      # 交互模式 (默认)
             ├→ run_print_mode()# 非交互模式 (-p)
             └→ run_task_worker()# 后台工作者模式 (--task-worker)

  核心对象组装: build_runtime()

  ui/runtime.py 的 build_runtime() 是所有模式共享的组装点, 按顺序创建:

  1. load_settings()              → 加载 ~/.openharness/settings.json
  2. load_plugins()               → 发现并加载插件
  3. _resolve_api_client()        → 根据 provider 创建 API 客户端
  4. McpClientManager()           → MCP 服务器管理器
  5. create_default_tool_registry()→ 注册 43+ 工具
  6. PermissionChecker()          → 权限检查器
  7. build_runtime_system_prompt() → 组装系统提示词
  8. QueryEngine()                → **核心引擎, 组装以上所有依赖**
  9. RuntimeBundle()              → 打包所有运行时对象

  RuntimeBundle — 运行时会话的"上帝对象"

  @dataclass
  class RuntimeBundle:
      api_client          # API 客户端 (Anthropic/OpenAI/Copilot/Codex)
      cwd                 # 工作目录
      mcp_manager         # MCP 管理器
      tool_registry       # 工具注册表
      app_state           # UI 状态
      hook_executor       # Hook 执行器
      engine              # QueryEngine — Agent Loop 核心
      commands            # 斜杠命令注册表
      external_api_client # 是否外部传入的 API 客户端
      enforce_max_turns   # 是否强制限制轮次
      session_id          # 会话 ID
      settings_overrides  # CLI 覆盖的设置
      session_backend     # 会话持久化后端
      extra_skill_dirs    # 额外 Skill 目录
      extra_plugin_roots  # 额外插件根目录

  handle_line() — 消息处理主循环

  runtime.py:handle_line() 是交互式处理的核心:
  1. 检查是否是斜杠命令 → 执行命令
  2. 否则 → build_runtime_system_prompt() → engine.submit_message(line) → 流式输出事件
  3. 保存会话快照 → sync_app_state()

  三种运行模式

  ┌────────────┬─────────────────────────────────┬───────────────────────────────────┐
  │    模式    │              入口               │               特点                │
  ├────────────┼─────────────────────────────────┼───────────────────────────────────┤
  │ 交互式     │ run_repl() → launch_react_tui() │ React/Ink TUI, 全功能             │
  ├────────────┼─────────────────────────────────┼───────────────────────────────────┤
  │ 非交互式   │ run_print_mode()                │ -p 参数, 流式输出到 stdout        │
  ├────────────┼─────────────────────────────────┼───────────────────────────────────┤
  │ 后台工作者 │ run_task_worker()               │ --task-worker, 无 TTY, stdin 驱动 │
  └────────────┴─────────────────────────────────┴───────────────────────────────────┘

  platforms.py — 平台能力矩阵

  detect_platform() 返回 5 种平台, get_platform_capabilities() 给出能力矩阵:

  ┌─────────────────┬─────────────┬──────┬───────────────┬────────────────┐
  │      平台       │ POSIX Shell │ tmux │ Swarm Mailbox │ Docker Sandbox │
  ├─────────────────┼─────────────┼──────┼───────────────┼────────────────┤
  │ macOS/Linux/WSL │ ✅          │ ✅   │ ✅            │ ✅             │
  ├─────────────────┼─────────────┼──────┼───────────────┼────────────────┤
  │ Windows         │ ❌          │ ❌   │ ❌            │ ❌             │
  └─────────────────┴─────────────┴──────┴───────────────┴────────────────┘

  这直接影响 Swarm 和 Bash 工具的行为差异。

  ---
  Phase 1 完成。核心要点:
  - cli.py:main() 是入口, 分三路到 ui/app.py
  - build_runtime() 按顺序组装所有依赖, 核心是 QueryEngine
  - RuntimeBundle 是运行时"上帝对象", 持有所有子系统引用
  - handle_line() 是交互处理的核心, 命令走 CommandRegistry, 普通消息走 QueryEngine

  准备进入 Phase 2 (核心数据类型) 时告诉我。