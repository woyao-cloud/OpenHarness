# 日志系统增强设计

> 日期: 2026-04-19
> 状态: 已批准

## 1. 背景

当前 `prompt_logger.py` 存在多个 bug 和架构问题：

- `log_content_block()` 接收 list 而非单个 block，导致 isinstance 检查全失败
- `log_simple()` / `log_content_block()` 无视 verbose 标志，始终写文件
- OpenAI 客户端绕过结构化日志直接调用 `log_simple`，导致两条路径输出不对称
- 缺少工具执行、压缩过程、Skill 加载的结构化日志
- 长文本无截断，日志文件可能无限膨胀

目标：修复 bug + 拆分为专用模块 + 记录请求/响应/工具/压缩/Skill 全量信息 + 文本超过 500 字截断。

## 2. 架构

### 2.1 目录结构

```
src/openharness/services/
  log/                        # 新包
    __init__.py               # 公共 API 重导出
    _shared.py                # 共享状态与基础设施
    prompt_logger.py           # 请求/响应日志
    tool_logger.py             # 工具执行日志
    compact_logger.py          # 压缩日志
    skill_logger.py            # Skill 加载日志
  prompt_logger.py             # 向后兼容薄重导出（DeprecationWarning）
```

### 2.2 `_shared.py` — 共享基础设施

```python
_MAX_DEBUG_FILES = 15
_TRUNCATE_LIMIT = 500

_request_counter: int = 0
_counter_lock = threading.Lock()
_log_file_path: Path | None = None
_log_file_lock = threading.Lock()
_verbose_enabled: bool = False

def next_request_id() -> int
def set_verbose(enabled: bool) -> None
def is_verbose() -> bool
def truncate(text: str, limit: int = _TRUNCATE_LIMIT) -> str
    # 截断逻辑：超长文本取前 limit 字符 + "... [truncated, total N chars]"
def write_to_debug_file(content: str) -> None
    # 检查 is_verbose()，为 False 时静默返回
def get_log_file_path() -> Path
    # 带轮转，线程安全（加 _log_file_lock）
def reset_session() -> None
```

### 2.3 `__init__.py` — 统一入口

```python
from openharness.services.log._shared import (set_verbose, is_verbose, truncate, reset_session)
from openharness.services.log.prompt_logger import (log_prompt_request, log_response_event, log_response_complete)
from openharness.services.log.tool_logger import log_tool_execution
from openharness.services.log.compact_logger import log_compact_event
from openharness.services.log.skill_logger import log_skill_load
```

### 2.4 向后兼容

`src/openharness/services/prompt_logger.py` 保留为薄重导出文件：

```python
import warnings
warnings.warn("Use openharness.services.log instead", DeprecationWarning, stacklevel=2)
from openharness.services.log import *
```

## 3. 各 Logger 详细规格

### 3.1 `prompt_logger.py` — 请求/响应日志

**数据模型：**

- `PromptLogEntry` — 请求摘要（request_id, timestamp, model, max_tokens, system_prompt_sections, message_count_by_role, message_total_chars, tool_count, tool_names）
- `PromptLogDetail` — 请求完整内容（entry + system_prompt_full + messages_full_content + tool_schemas_full）
- `ResponseLogEntry` — 流式 delta 摘要（request_id, text_length, text_preview）
- `ResponseCompleteLogEntry` — 完整响应摘要（request_id, model, text, tool_uses, stop_reason, input_tokens, output_tokens）

**公共 API：**

```python
def log_prompt_request(
    *,
    step_remark: str = "",
    model: str,
    max_tokens: int,
    system_prompt: str,
    messages: list[ConversationMessage],
    tool_registry: ToolRegistry,
    verbose: bool = False,
) -> int
    # 返回 request_id
    # Python logging: DEBUG 级别摘要
    # verbose 文件: 完整 system_prompt, 逐条 message 内容(截断500), tool schema 名称+描述(截断500)
```

**verbose 文件输出格式（请求）：**

```
================================================================================
REQUEST #42 (model=claude-sonnet-4-6, max_tokens=4096, step=Turn run_query()-1)
================================================================================
SYSTEM PROMPT (8420 chars):
  You are an AI assistant...
  ... [truncated, total 8420 chars]

MESSAGES (5):
  --- Message 1 (role=user, 156 chars) ---
  Read the main.py file
  --- Message 2 (role=assistant, 89 chars) ---
  I'll read that file for you.
  --- Message 3 (role=assistant, 1 tool_use) ---
    tool_use: read_file(id=toolu_abc123)
      input: {"file_path": "/path/main.py", "offset": 0, "limit": 200}
  --- Message 4 (role=user, 1 tool_result) ---
    tool_result(id=toolu_abc123, is_error=False):
      import sys\n\ndef main():\n...
      ... [truncated, total 2340 chars]
  --- Message 5 (role=user, 45 chars) ---
  What does the main function do?

TOOLS (12):
  1. read_file: Read file contents from local filesystem...
  2. bash: Execute bash commands...
  ...
```

```python
def log_response_event(
    *,
    delta_text: str,
    request_id: int,
    verbose: bool = False,
) -> None
    # Python logging: DEBUG 单行摘要
    # verbose 文件: delta 文本(截断500)
```

```python
def log_response_complete(
    *,
    message: ConversationMessage,
    usage: UsageSnapshot,
    request_id: int,
    model: str = "",
    stop_reason: str | None = None,
    verbose: bool = False,
) -> None
    # Python logging: DEBUG 多行摘要
    # verbose 文件: 完整文本(截断500), tool_uses详情, usage
```

**verbose 文件输出格式（响应完成）：**

```
================================================================================
RESPONSE #42 (model=claude-sonnet-4-6, stop=end_turn, in=1204 out=156)
================================================================================
TEXT (156 chars):
  Hello, I'll help you read the main.py file...

TOOL_USES:
  1. read_file(file_path="/path/main.py", offset=0, limit=200)

USAGE:
  input_tokens=1204 output_tokens=156
```

**移除：** `log_simple()` — 功能拆分到各自专用 logger。`log_content_block()` 改为内部辅助函数，接收 `list[ContentBlock]` 并遍历。

### 3.2 `tool_logger.py` — 工具执行日志

```python
def log_tool_execution(
    *,
    request_id: int,
    tool_name: str,
    tool_input: dict,
    tool_output: str,
    is_error: bool,
    duration_seconds: float,
) -> None
    # Python logging: DEBUG 单行摘要
    # verbose 文件: 工具名, 输入详情(每个value截断500), 输出(截断500), 耗时, 是否错误
```

**verbose 文件输出格式：**

```
================================================================================
TOOL (request=42) read_file (0.35s)
================================================================================
Input:
  file_path: /path/to/main.py
  offset: 0
  limit: 200
Output (156 chars):
  import sys\n\ndef main():\n...
  ... [truncated, total 2340 chars]
Error: False
```

### 3.3 `compact_logger.py` — 压缩日志

```python
def log_compact_event(
    *,
    request_id: int,
    trigger: str,           # "auto" | "manual" | "reactive"
    phase: str,             # 与 CompactProgressEvent.phase 对齐
    message: str | None = None,
    before_tokens: int | None = None,
    after_tokens: int | None = None,
    summary: str | None = None,
) -> None
    # Python logging: DEBUG 单行摘要
    # verbose 文件: 触发原因, 阶段, 前后 token 数, 压缩摘要(截断500)
```

**verbose 文件输出格式：**

```
================================================================================
COMPACT (request=42) trigger=auto phase=compact_end
================================================================================
Before: ~12000 tokens
After:  ~4000 tokens (saved 67%)
Summary:
  Compacted messages 1-15: "User asked about the project architecture..."
  ... [truncated, total 890 chars]
```

### 3.4 `skill_logger.py` — Skill 加载日志

```python
def log_skill_load(
    *,
    request_id: int,
    skill_name: str,
    skill_content: str,
) -> None
    # Python logging: DEBUG 单行摘要
    # verbose 文件: skill 名称, 内容(截断500)
```

**verbose 文件输出格式：**

```
================================================================================
SKILL (request=42) architecture-review
================================================================================
Content (2340 chars, showing first 500):
  # Architecture Review Skill
  This skill helps review code architecture...
  ... [truncated, total 2340 chars]
```

## 4. Bug 修复清单

| # | Bug | 修复 |
|---|-----|------|
| 1 | `log_content_block()` 接收 list 而非单个 block | 改为遍历 list 逐个记录 |
| 2 | `log_simple()` / `log_content_block()` 无视 verbose | 移除 `log_simple`；所有写入走 `_shared.write_to_debug_file()` 受 verbose 门控 |
| 3 | OpenAI 客户端直接调用 `log_simple`/`log_content_block` | 移除 `openai_client.py` L328 和 L376 的调用（已被 `query.py` 的结构化日志覆盖） |
| 4 | `cli.py`/`app.py`/`runtime.py` 中的 `log_simple` 调用 | 改为 `log.debug()` 标准日志（启动状态信息不属于 prompt/response 范畴） |
| 5 | `step_remark` 日志格式不规范 | 合并到 `_format_summary()` |
| 6 | `_get_log_file_path()` 线程安全漏洞 | 在函数内加 `_log_file_lock` |

## 5. 统一日志路径（改动后）

```
请求（统一，不区分 Anthropic/OpenAI）:
  query.py → log_prompt_request() → write_to_debug_file()

响应（统一）:
  query.py → log_response_event()  (每个 delta)
  query.py → log_response_complete() (完整响应)

工具（新增）:
  query.py → log_tool_execution()

压缩（新增）:
  query.py → log_compact_event()

Skill（新增）:
  skill tool → log_skill_load()

不再使用:
  openai_client.py → log_simple()        ← 删除
  openai_client.py → log_content_block() ← 删除
  cli.py/app.py/runtime.py → log_simple() ← 改为 log.debug()
```

## 6. 调用位置改动详情

### `query.py`

| 位置 | 改动 |
|------|------|
| 循环开头 | `set_verbose(context.verbose)` |
| `log_prompt_request()` 调用处 | 改用新模块路径，保存 `request_id` |
| `ApiTextDeltaEvent` 处理 | 调用 `log_response_event()` |
| `ApiMessageCompleteEvent` 处理 | 调用 `log_response_complete()` |
| `_execute_tool_call()` 返回后 | 调用 `log_tool_execution()`，`request_id` 通过闭包捕获（`_execute_tool_call` 是 `run_query` 内的嵌套调用，`request_id` 在外层循环变量中）|
| `_stream_compaction()` 中 | 调用 `log_compact_event()`，`request_id` 同理通过闭包捕获 |

**`request_id` 传递方式**：`run_query()` 的 while 循环内 `request_id` 是局部变量。`_execute_tool_call()` 和 `_stream_compaction()` 都在 `run_query()` 内部定义或调用，可直接通过闭包或参数传递 `request_id`。具体选择：将 `request_id` 加入 `_execute_tool_call()` 的参数列表（最清晰）。`_stream_compaction()` 已是 `run_query` 内嵌函数，闭包捕获即可。

### `openai_client.py`

| 位置 | 改动 |
|------|------|
| L328 `log_simple()` | 删除 |
| L376 `log_content_block()` | 删除 |

### `cli.py` / `app.py` / `runtime.py`

| 位置 | 改动 |
|------|------|
| `log_simple("Starting ...")` | 改为 `log.debug("Starting ...")` |

## 7. 截断规则

所有文本字段统一用 `_shared.truncate(text, limit=500)` 处理：

- 文本 <= 500 字：原样输出
- 文本 > 500 字：取前 500 字符 + `"... [truncated, total N chars]"`
- 二进制/非文本内容（如 ImageBlock）：输出类型 + 大小信息，不输出 data

## 8. 不在范围内

以下内容明确不在本次设计范围内：

- JSON Lines 结构化输出格式
- 实时日志 WebSocket 推送
- 日志查看/过滤 UI
- Python logging 自定义 Handler
- 大小轮转（保留现有计数轮转，15 文件上限）