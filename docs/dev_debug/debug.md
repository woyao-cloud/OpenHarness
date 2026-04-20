 1. src/openharness/services/prompt_logger.py (~327行) — 核心提示日志模块：
    - PromptLogEntry / PromptLogDetail 数据类
    - log_prompt_request() — 主要入口，调用前记录每个LLM API请求
    - _categorize_system_prompt() — 根据#标题将组合的系统提示分割成各个部分
    - _summarize_messages() — 统计角色、字符数和预览
    - 摘要模式：Python logging.debug 每个请求一行
    - 详细模式：完整内容写入~/.openharness/logs/prompt_debug_YYYYMMDD_HHMMSS.log
    - 会话范围的日志文件，带轮转（保留最近15个）

  修改文件

  2. src/openharness/engine/query.py — 将verbose: bool = False添加到QueryContext，在stream_message()前导入并调用log_prompt_request()
  3. src/openharness/engine/query_engine.py — 将verbose参数添加到QueryEngine.__init__()，并将其传递给submit_message()和continue_pending()中的QueryContext
  4. src/openharness/ui/runtime.py — 将verbose=settings.verbose传递给build_runtime()中的QueryEngine()构造函数
  5. src/openharness/config/settings.py — 在_apply_env_overrides()中添加OPENHARNESS_VERBOSE环境变量处理
  6. src/openharness/cli.py — 当--verbose传递时，设置os.environ["OPENHARNESS_VERBOSE"] = "1"，并流入所有代码路径
  7. src/openharness/config/paths.py — 添加get_prompt_debug_log_dir()辅助函数

  如何使用

  - oh --verbose "hello" — 启用完整提示调试日志记录，写入~/.openharness/logs/prompt_debug_*.log
  - OPENHARNESS_VERBOSE=1 oh "hello" — 同样，通过环境变量
  - OPENHARNESS_LOG_LEVEL=DEBUG oh "hello" — 查看每个API请求的一行摘要（无详细文件输出）
  - oh "hello" — 无提示日志记录（默认行为不受影响）

settings.verbose=True
QueryEngine has verbose param: True
engine._verbose=True
INTEGRATION_OK



● 实现完成。以下是改动的总结：·

  src/openharness/services/prompt_logger.py:
  - 新增 ResponseLogEntry 和 ResponseCompleteLogEntry 两个数据类
  - log_prompt_request() 现在返回 int（request_id），便于关联请求与响应
  - 新增 log_response_event()：记录每个流式文字片段（delta）
  - 新增 log_response_complete()：记录完整响应（文本全文 + 工具调用 + 用量）
  - 新增 _format_response_delta_summary()、_format_response_complete_summary()、_format_response_complete_detail()
  格式化函数
  - 修复了原代码中 detail.append() 的 bug（str.append 不存在）

  src/openharness/engine/query.py:
  - 导入新增的 log_response_event 和 log_response_complete
  - log_prompt_request() 返回值赋给 request_id
  - 收到 ApiTextDeltaEvent 时调用 log_response_event() 记录流式片段
  - 收到 ApiMessageCompleteEvent 时调用 log_response_complete() 记录完整响应

  日志输出方式：
  - Python logging DEBUG 级别（始终）：流式 delta 单行 + 完整响应多行摘要
  - verbose 模式写文件 prompt_debug_*.log：流式 delta + 完整响应全文（含工具调用详情和用量）