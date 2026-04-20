uv run oh --api-format openai --base-url http://localhost:11434 --api-key ollama --model glm-5.1:cloud

 好的，选方案 A，最简单。不需要改代码，直接配置环境变量即可。

  配置方法如下：

  启动前设置环境变量

  export OPENHARNESS_API_FORMAT=openai
  export OPENHARNESS_BASE_URL=http://localhost:11434
  export OPENAI_API_KEY=ollama
  export OPENHARNESS_MODEL=glm-5.1:cloud

  然后正常启动：
  oh

  或单次运行时通过 CLI 参数指定：
  oh --api-format openai --base-url http://localhost:11434 --api-key ollama --model glm-5.1:cloud

  说明

  ┌────────────┬───────────────────────────┬─────────────────────────────────────────────────────────────┐
  │   配置项   │            值             │                            原因                             │
  ├────────────┼───────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ api_format │ openai                    │ Ollama 提供 OpenAI 兼容接口，使用 OpenAICompatibleClient    │
  ├────────────┼───────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ base_url   │ http://localhost:11434 │ Ollama 默认的 OpenAI 兼容端点                               │
  ├────────────┼───────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ api_key    │ ollama（任意占位值）      │ Ollama 不验证认证，但 OpenAICompatibleClient 构造需要非空值 │
  ├────────────┼───────────────────────────┼─────────────────────────────────────────────────────────────┤
  │ model      │ glm-5.1:cloud             │ 你要使用的 Ollama 模型名                                    │
  └────────────┴───────────────────────────┴─────────────────────────────────────────────────────────────┘

  注意事项

  1. Ollama 必须先启动：确保 ollama serve 已运行且 glm-5.1:cloud 模型已拉取（ollama pull glm-5.1:cloud）
  2. 工具调用兼容性：Ollama 的 function calling 支持取决于具体模型，glm-5.1:cloud 如果不支持 tool use，agent loop
  中的工具调用会失败
  3. 持久化：如果不想每次设环境变量，可以写入 shell 配置文件（如 .bashrc）或 Windows 的系统环境变量


  ● 开启 FULL_AUTO 模式有以下方式：

  方式 1：CLI 启动参数（推荐）

  oh --permission-mode full_auto

  或使用快捷别名：

  oh --dangerously-skip-permissions

  方式 2：运行中切换（交互模式）
  在 REPL 中输入斜杠命令：

  /permissions full_auto

  或：
  /permissions set full_auto

  方式 3：配置文件持久化
  编辑 ~/.openharness/settings.json：