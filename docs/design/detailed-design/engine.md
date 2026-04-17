# Engine 模块详细设计文档

---

## 1. 模块概述

### 1.1 职责

Engine 模块是 OpenHarness 的核心运行时引擎，负责：

- 管理对话消息的生命周期（构建、序列化、校验）
- 驱动 Agent 循环（API 调用 -> 工具执行 -> 结果回传 -> 下一轮）
- 流式事件分发，供 UI 层实时渲染
- Token 用量累计与成本追踪
- 工具元数据（carryover）的跨轮次状态维护
- 自动压缩（auto-compact）与响应式压缩（reactive-compact）的触发与协调
- 权限检查、Hook 钩子执行等横切关注点的集成

### 1.2 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `engine/__init__.py` | 81 | 模块公开导出与延迟导入（lazy import） |
| `engine/messages.py` | 177 | 对话消息与内容块数据模型 |
| `engine/stream_events.py` | 90 | 流式事件类型定义 |
| `engine/cost_tracker.py` | 25 | Token 用量累加器 |
| `engine/query.py` | 746 | 核心查询循环、工具执行管线、元数据维护 |
| `engine/query_engine.py` | 206 | 有状态引擎门面类，持有对话历史与配置 |

**模块总行数：1,325 行**

### 1.3 依赖关系（本模块内部）

```
query_engine.py  ──>  query.py  ──>  messages.py
                     │               stream_events.py
                     │               cost_tracker.py
                     │               (外部: api/client, tools, hooks, permissions, services/compact)
                     └──>  messages.py
__init__.py  ──>  延迟导入 messages / query_engine / stream_events
cost_tracker.py  ──>  api/usage (UsageSnapshot)
stream_events.py  ──>  api/usage (UsageSnapshot), messages.py (ConversationMessage)
```

---

## 2. 核心类/接口

### 2.1 类图

```
                     ┌───────────────────┐
                     │    QueryEngine    │  (有状态门面)
                     │  query_engine.py  │
                     └────────┬──────────┘
                              │ 持有
              ┌───────────────┼───────────────┐
              v               v               v
     ┌────────────┐  ┌──────────────┐  ┌──────────────┐
     │ CostTracker│  │  QueryContext│  │ _messages[]  │
     │cost_tracker│  │   query.py  │  │ Conversation │
     └────────────┘  └──────┬───────┘  │  Message[]   │
                            │          └──────────────┘
                            │ 委托
                            v
                    ┌───────────────┐
                    │  run_query()  │  (无状态核心循环)
                    │   query.py    │
                    └───────┬───────┘
                            │ 调用
          ┌─────────────────┼─────────────────┐
          v                 v                 v
 ┌──────────────┐  ┌───────────────┐  ┌──────────────┐
 │_execute_tool_ │  │auto_compact   │  │api_client.   │
 │call()         │  │_if_needed()   │  │stream_message│
 │query.py       │  │services/compact│  │api/client    │
 └──────┬───────┘  └───────────────┘  └──────────────┘
        │
   ┌────┴─────┬──────────────┬──────────────┐
   v          v              v              v
ToolReg  PermissionChk  HookExecutor  ToolMetadata
(外部)    (外部)         (外部)       (carryover)
```

### 2.2 关键类型别名

```python
# query.py
PermissionPrompt = Callable[[str, str], Awaitable[bool]]
# 参数: (tool_name, reason) -> 用户是否确认

AskUserPrompt = Callable[[str], Awaitable[str]]
# 参数: (prompt_text) -> 用户输入字符串
```

### 2.3 Protocol / 接口依赖

Engine 模块不自行定义 Protocol，但依赖以下外部 Protocol：

| 接口 | 来源 | 用途 |
|------|------|------|
| `SupportsStreamingMessages` | `api/client` | 流式消息请求（`stream_message()`） |
| `ToolRegistry` | `tools/base` | 工具注册、查找、Schema 生成 |
| `PermissionChecker` | `permissions/checker` | 权限评估（`evaluate()`） |
| `HookExecutor` | `hooks` | 钩子执行（`execute(HookEvent, ...)`） |

---

## 3. 数据模型

### 3.1 ContentBlock 体系（messages.py）

使用 Pydantic `BaseModel` + 判别器（discriminator）实现联合类型：

```
ContentBlock = Annotated[
    TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]
```

#### 3.1.1 TextBlock

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | `Literal["text"]` | `"text"` | 判别器字段 |
| `text` | `str` | (必填) | 文本内容 |

#### 3.1.2 ImageBlock

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | `Literal["image"]` | `"image"` | 判别器字段 |
| `media_type` | `str` | (必填) | MIME 类型，如 `"image/png"` |
| `data` | `str` | (必填) | Base64 编码的图片数据 |
| `source_path` | `str` | `""` | 原始文件路径（仅用于追溯） |

**工厂方法：** `from_path(path: str | Path) -> ImageBlock`
- 通过 `mimetypes.guess_type` 推断 MIME
- 若 MIME 不以 `image/` 开头则抛出 `ValueError`
- 读取文件并 Base64 编码

#### 3.1.3 ToolUseBlock

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | `Literal["tool_use"]` | `"tool_use"` | 判别器字段 |
| `id` | `str` | `"toolu_{uuid4().hex}"` | 工具调用唯一标识，匹配 ToolResultBlock |
| `name` | `str` | (必填) | 工具名称 |
| `input` | `dict[str, Any]` | `{}` | 工具输入参数 |

#### 3.1.4 ToolResultBlock

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | `Literal["tool_result"]` | `"tool_result"` | 判别器字段 |
| `tool_use_id` | `str` | (必填) | 对应的 ToolUseBlock.id |
| `content` | `str` | (必填) | 工具输出文本 |
| `is_error` | `bool` | `False` | 是否为错误结果 |

### 3.2 ConversationMessage（messages.py）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `role` | `Literal["user", "assistant"]` | (必填) | 消息角色 |
| `content` | `list[ContentBlock]` | `[]` | 内容块列表 |

**校验器：** `_normalize_content(value)` — 若 `content` 为 `None` 则归一化为空列表。

**属性与方法：**

| 名称 | 签名 | 说明 |
|------|------|------|
| `text` | `@property -> str` | 拼接所有 TextBlock 的文本 |
| `tool_uses` | `@property -> list[ToolUseBlock]` | 提取所有 ToolUseBlock |
| `from_user_text(text)` | `@classmethod -> ConversationMessage` | 构造仅含 TextBlock 的用户消息 |
| `from_user_content(content)` | `@classmethod -> ConversationMessage` | 从显式 ContentBlock 列表构造用户消息 |
| `to_api_param()` | `-> dict[str, Any]` | 转换为 Anthropic SDK 消息参数格式 |
| `is_effectively_empty()` | `-> bool` | 判断消息是否不含任何有意义的内容 |

**`is_effectively_empty()` 判定逻辑：**
- 若 content 为空 → True
- 若存在非空 TextBlock（`.text.strip()` 非空）→ False
- 若存在 ImageBlock / ToolUseBlock / ToolResultBlock → False
- 否则 → True

### 3.3 辅助函数（messages.py）

| 函数 | 签名 | 说明 |
|------|------|------|
| `sanitize_conversation_messages` | `(list[ConversationMessage]) -> list[ConversationMessage]` | 过滤掉空 assistant 消息 |
| `serialize_content_block` | `(ContentBlock) -> dict[str, Any]` | 将本地 ContentBlock 序列化为 provider 线格式 |
| `assistant_message_from_api` | `(Any) -> ConversationMessage` | 将 Anthropic SDK 原始消息对象转为 ConversationMessage |

**`serialize_content_block` 线格式映射：**

| 本地类型 | 线格式 |
|----------|--------|
| TextBlock | `{"type": "text", "text": ...}` |
| ImageBlock | `{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}` |
| ToolUseBlock | `{"type": "tool_use", "id": ..., "name": ..., "input": ...}` |
| ToolResultBlock | `{"type": "tool_result", "tool_use_id": ..., "content": ..., "is_error": ...}` |

### 3.4 StreamEvent 体系（stream_events.py）

所有事件均为 `@dataclass(frozen=True)`，不可变。

```
StreamEvent = AssistantTextDelta
            | AssistantTurnComplete
            | ToolExecutionStarted
            | ToolExecutionCompleted
            | ErrorEvent
            | StatusEvent
            | CompactProgressEvent
```

| 事件类 | 字段 | 说明 |
|--------|------|------|
| **AssistantTextDelta** | `text: str` | 增量文本片段，供 UI 实时渲染 |
| **AssistantTurnComplete** | `message: ConversationMessage`, `usage: UsageSnapshot` | 模型轮次完成，携带完整消息和用量 |
| **ToolExecutionStarted** | `tool_name: str`, `tool_input: dict[str, Any]` | 工具即将执行 |
| **ToolExecutionCompleted** | `tool_name: str`, `output: str`, `is_error: bool = False` | 工具执行完毕 |
| **ErrorEvent** | `message: str`, `recoverable: bool = True` | 需展示给用户的错误 |
| **StatusEvent** | `message: str` | 临时状态消息（如重试提示） |
| **CompactProgressEvent** | `phase: Literal[9种]`, `trigger: Literal[3种]`, `message: str | None`, `attempt: int | None`, `checkpoint: str | None`, `metadata: dict | None` | 压缩进度事件 |

**CompactProgressEvent.phase 枚举值：**
`hooks_start`, `context_collapse_start`, `context_collapse_end`, `session_memory_start`, `session_memory_end`, `compact_start`, `compact_retry`, `compact_end`, `compact_failed`

**CompactProgressEvent.trigger 枚举值：**
`auto`（自动触发）, `manual`（用户手动触发）, `reactive`（API 报错后响应式触发）

> 所有 StreamEvent 均为瞬态信号，不做持久化存储。

### 3.5 UsageSnapshot 与 CostTracker（cost_tracker.py + api/usage.py）

**UsageSnapshot**（Pydantic BaseModel，位于 `api/usage.py`）：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `input_tokens` | `int` | `0` | 输入 Token 数 |
| `output_tokens` | `int` | `0` | 输出 Token 数 |

计算属性：`total_tokens -> int` = `input_tokens + output_tokens`

**CostTracker**：

| 方法/属性 | 签名 | 说明 |
|-----------|------|------|
| `__init__()` | `-> None` | 初始化 `_usage = UsageSnapshot()` |
| `add(usage)` | `(UsageSnapshot) -> None` | 不可变累加：创建新 UsageSnapshot |
| `total` | `@property -> UsageSnapshot` | 返回聚合用量 |

> `add()` 方法遵循不可变模式：每次调用创建新的 `UsageSnapshot` 实例而非原地修改。

### 3.6 QueryContext（query.py, 第 78 行）

```python
@dataclass
class QueryContext:
    """Context shared across a query run."""
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_client` | `SupportsStreamingMessages` | (必填) | 流式 API 客户端 |
| `tool_registry` | `ToolRegistry` | (必填) | 工具注册表 |
| `permission_checker` | `PermissionChecker` | (必填) | 权限检查器 |
| `cwd` | `Path` | (必填) | 当前工作目录 |
| `model` | `str` | (必填) | 模型标识符 |
| `system_prompt` | `str` | (必填) | 系统提示词 |
| `max_tokens` | `int` | (必填) | 单次最大生成 Token 数 |
| `context_window_tokens` | `int | None` | `None` | 模型上下文窗口大小 |
| `auto_compact_threshold_tokens` | `int | None` | `None` | 自动压缩阈值 |
| `permission_prompt` | `PermissionPrompt | None` | `None` | 用户确认回调 |
| `ask_user_prompt` | `AskUserPrompt | None` | `None` | 用户输入回调 |
| `max_turns` | `int | None` | `200` | 单次查询最大轮次数 |
| `hook_executor` | `HookExecutor | None` | `None` | 钩子执行器 |
| `tool_metadata` | `dict[str, object] | None` | `None` | 工具元数据/跨轮次状态 |

### 3.7 MaxTurnsExceeded（query.py, 第 70 行）

```python
class MaxTurnsExceeded(RuntimeError):
    def __init__(self, max_turns: int) -> None
```

继承自 `RuntimeError`，当 Agent 循环超过 `max_turns` 限制时抛出。

---

## 4. 关键算法

### 4.1 Agent 循环（run_query）

**入口签名：**

```python
async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]
```

**核心流程伪代码：**

```
初始化:
    compact_state = AutoCompactState()
    reactive_compact_attempted = False
    turn_count = 0

WHILE turn_count < max_turns:
    turn_count += 1

    ┌─────────────────────────────────────────────┐
    │ 步骤 1: 自动压缩检查 (auto-compact)          │
    │   _stream_compaction(trigger="auto")         │
    │   → 若触发压缩，yield CompactProgressEvent   │
    │   → 更新 messages 与 was_compacted           │
    └─────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────┐
    │ 步骤 2: API 流式调用                          │
    │   api_client.stream_message(ApiMessageRequest)│
    │   → ApiTextDeltaEvent → yield AssistantTextDelta│
    │   → ApiRetryEvent    → yield StatusEvent     │
    │   → ApiMessageCompleteEvent → 记录 final_message, usage │
    └─────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────┐
    │ 步骤 3: 错误处理                               │
    │   IF 异常 AND 是"prompt too long"错误:         │
    │     IF NOT reactive_compact_attempted:        │
    │       reactive_compact_attempted = True       │
    │       _stream_compaction(trigger="reactive", force=True)│
    │       → 若压缩成功，continue 重新进入循环      │
    │   ELIF 网络错误 (connect/timeout/network):     │
    │     yield ErrorEvent("Network error: ...")   │
    │   ELSE:                                        │
    │     yield ErrorEvent("API error: ...")       │
    │   RETURN                                       │
    └─────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────┐
    │ 步骤 4: 记录 assistant 消息                    │
    │   IF final_message 为空 → RuntimeError        │
    │   IF coordinator 上下文消息存在 → 暂时移除      │
    │   IF assistant 消息为空 → yield ErrorEvent, RETURN │
    │   messages.append(final_message)             │
    │   yield AssistantTurnComplete(message, usage) │
    │   IF coordinator 上下文消息存在 → 重新追加      │
    └─────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────┐
    │ 步骤 5: 检查工具调用                          │
    │   IF final_message.tool_uses 为空:            │
    │     RETURN  (对话自然结束)                     │
    │   tool_calls = final_message.tool_uses        │
    └─────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────┐
    │ 步骤 6: 执行工具                              │
    │   IF len(tool_calls) == 1:                    │
    │     顺序执行: yield Started → _execute_tool_call → yield Completed │
    │   ELSE:                                        │
    │     并发执行:                                   │
    │       yield 所有 Started 事件                    │
    │       asyncio.gather(*[_run(tc)], return_exceptions=True) │
    │       异常转为 ToolResultBlock(is_error=True)   │
    │       yield 所有 Completed 事件                 │
    └─────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────┐
    │ 步骤 7: 追加工具结果                           │
    │   messages.append(ConversationMessage(         │
    │     role="user", content=tool_results))        │
    │   → 回到 WHILE 循环顶部                        │
    └─────────────────────────────────────────────┘

IF 超过 max_turns:
    RAISE MaxTurnsExceeded
```

**关键设计决策：**

1. **单工具 vs 多工具执行策略** — 单工具顺序执行可立即流式输出事件；多工具使用 `asyncio.gather(return_exceptions=True)` 并发执行，确保单个工具失败不会取消其余工具（Anthropic API 要求所有 tool_use 都有对应的 tool_result）。
2. **响应式压缩** — 首次遇到 "prompt too long" 错误时，触发强制压缩并重试，仅尝试一次。
3. **Coordinator 上下文消息** — 若系统提示以 `"You are a **coordinator**."` 开头且最后一条用户消息以 `"# Coordinator User Context"` 开头，临时移除以避免干扰 API 调用，调用后恢复。

### 4.2 工具执行管线（_execute_tool_call）

**7 步管线：**

```
┌──────────────────────────────────────────────────────────────┐
│ 步骤 1: PreToolUse Hook                                      │
│   hook_executor.execute(HookEvent.PRE_TOOL_USE, {...})       │
│   IF blocked → 返回 ToolResultBlock(is_error=True,           │
│                   content=blocked.reason)                     │
├──────────────────────────────────────────────────────────────┤
│ 步骤 2: 工具查找                                              │
│   tool_registry.get(tool_name)                                │
│   IF None → 返回 ToolResultBlock(is_error=True,              │
│                  content="Unknown tool: {tool_name}")         │
├──────────────────────────────────────────────────────────────┤
│ 步骤 3: 输入校验                                              │
│   tool.input_model.model_validate(tool_input)                │
│   IF 异常 → 返回 ToolResultBlock(is_error=True,              │
│                  content="Invalid input: {exc}")              │
├──────────────────────────────────────────────────────────────┤
│ 步骤 4: 权限检查                                              │
│   _resolve_permission_file_path(cwd, raw_input, parsed_input)│
│   _extract_permission_command(raw_input, parsed_input)        │
│   decision = permission_checker.evaluate(                     │
│       tool_name, is_read_only, file_path, command)           │
│   IF NOT allowed:                                             │
│     IF requires_confirmation AND permission_prompt:           │
│       confirmed = await permission_prompt(tool_name, reason) │
│       IF NOT confirmed → 返回 ToolResultBlock(is_error=True)│
│     ELSE → 返回 ToolResultBlock(is_error=True)               │
├──────────────────────────────────────────────────────────────┤
│ 步骤 5: 执行工具                                              │
│   result = await tool.execute(parsed_input, ToolExecutionContext)│
│   ToolExecutionContext 包含:                                   │
│     - cwd                                                     │
│     - metadata: { tool_registry, ask_user_prompt,             │
│                   **(tool_metadata or {}) }                   │
│   记录执行耗时 (time.monotonic)                                │
├──────────────────────────────────────────────────────────────┤
│ 步骤 6: Carryover 记录                                        │
│   _record_tool_carryover(context, ...)                        │
│   → 更新 tool_metadata 中的 read_file_state,                  │
│     invoked_skills, async_agent_state, recent_work_log,       │
│     recent_verified_work, active_artifacts, permission_mode   │
├──────────────────────────────────────────────────────────────┤
│ 步骤 7: PostToolUse Hook                                     │
│   hook_executor.execute(HookEvent.POST_TOOL_USE, {...})      │
│   传入: tool_name, tool_input, tool_output, tool_is_error    │
└──────────────────────────────────────────────────────────────┘

返回 ToolResultBlock(tool_use_id, content, is_error)
```

### 4.3 工具元数据（Carryover）维护机制

Engine 维护一个可变字典 `tool_metadata`，跨轮次传递上下文状态。每个子桶（bucket）有独立容量上限：

| 桶名 | 上限 | 记录内容 |
|------|------|----------|
| `read_file_state` | 6 | 已读文件路径、行范围、预览、时间戳 |
| `invoked_skills` | 8 | 已调用技能名 |
| `async_agent_state` | 8 | 异步 Agent 活动摘要 |
| `recent_work_log` | 10 | 最近操作日志 |
| `recent_verified_work` | 10 | 已验证工作记录 |
| `active_artifacts` | 8 | 活跃制品（文件路径、URL、技能名） |
| `permission_mode` | - | 当前权限模式（`"plan"` / `"default"`） |
| `task_focus_state` | - | 任务聚焦状态（goal, recent_goals, active_artifacts, verified_state, next_step） |

**去重策略 `_append_capped_unique(bucket, value, limit)`：**
1. 若 `value` 已存在于 `bucket` 中 → 移除旧位置
2. 追加 `value` 到末尾
3. 若长度超过 `limit` → 删除最旧的条目（保留最新 `limit` 个）

> 此策略实现了 LRU 语义：最近使用的条目始终在末尾。

**工具名到 Carryover 的映射：**

| 工具名 | 更新的桶 |
|--------|----------|
| `read_file` | read_file_state, active_artifacts, recent_verified_work, recent_work_log |
| `skill` | invoked_skills, active_artifacts, recent_verified_work, recent_work_log |
| `agent` / `send_message` | async_agent_state, recent_verified_work, recent_work_log |
| `enter_plan_mode` | permission_mode="plan", recent_work_log |
| `exit_plan_mode` | permission_mode="default", recent_work_log |
| `web_fetch` | active_artifacts, recent_verified_work |
| `web_search` | recent_verified_work |
| `glob` | recent_verified_work |
| `grep` | recent_verified_work, recent_work_log |
| `bash` | recent_verified_work, recent_work_log |
| (任意工具，若 resolved_file_path 非空) | active_artifacts |

### 4.4 权限路径解析

**`_resolve_permission_file_path(cwd, raw_input, parsed_input)`：**
1. 按优先级检查 `raw_input` 中的 `file_path`, `path`, `root` 键
2. 若找到非空字符串 → 解析为绝对路径（相对路径基于 `cwd`）
3. 未找到则检查 `parsed_input` 对象同名属性
4. 均未找到 → 返回 `None`

**`_extract_permission_command(raw_input, parsed_input)`：**
1. 检查 `raw_input["command"]`
2. 未找到则检查 `parsed_input.command`
3. 均未找到 → 返回 `None`

### 4.5 Prompt-Too-Long 检测

```python
def _is_prompt_too_long_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(needle in text for needle in (
        "prompt too long",
        "context length",
        "maximum context",
        "context window",
        "too many tokens",
        "too large for the model",
        "maximum context length",
    ))
```

通过在异常消息中搜索关键字来判定是否为上下文长度超限错误。

### 4.6 压缩流式进度

`_stream_compaction(trigger, force)` 内部实现：
1. 创建 `asyncio.Queue[CompactProgressEvent]`
2. 启动 `auto_compact_if_needed()` 为后台任务
3. 以 50ms 超时轮询队列，yield 进度事件
4. 后台任务完成后，排空队列剩余事件
5. 返回压缩结果 `(messages, was_compacted)`

---

## 5. 接口规范

### 5.1 QueryEngine（query_engine.py）

#### 构造函数

```python
def __init__(
    self,
    *,
    api_client: SupportsStreamingMessages,
    tool_registry: ToolRegistry,
    permission_checker: PermissionChecker,
    cwd: str | Path,
    model: str,
    system_prompt: str,
    max_tokens: int = 4096,
    context_window_tokens: int | None = None,
    auto_compact_threshold_tokens: int | None = None,
    max_turns: int | None = 8,
    permission_prompt: PermissionPrompt | None = None,
    ask_user_prompt: AskUserPrompt | None = None,
    hook_executor: HookExecutor | None = None,
    tool_metadata: dict[str, object] | None = None,
) -> None
```

> 注意：`max_turns` 默认值为 **8**（在 QueryEngine 中），而 QueryContext 中默认值为 **200**。QueryEngine 构造时传入的值会覆盖 QueryContext 的默认值。

#### 公开方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `submit_message` | `(prompt: str \| ConversationMessage) -> AsyncIterator[StreamEvent]` | 追加用户消息并执行查询循环 |
| `continue_pending` | `(*, max_turns: int \| None = None) -> AsyncIterator[StreamEvent]` | 继续被中断的工具循环（不追加新消息） |
| `load_messages` | `(messages: list[ConversationMessage]) -> None` | 替换内存中的对话历史 |
| `clear` | `() -> None` | 清空对话历史并重置 CostTracker |
| `set_system_prompt` | `(prompt: str) -> None` | 更新系统提示词 |
| `set_model` | `(model: str) -> None` | 更新模型标识符 |
| `set_api_client` | `(api_client: SupportsStreamingMessages) -> None` | 更新 API 客户端 |
| `set_max_turns` | `(max_turns: int \| None) -> None` | 更新最大轮次（None 表示无限制，否则取 max(1, int(max_turns))） |
| `set_permission_checker` | `(checker: PermissionChecker) -> None` | 更新权限检查器 |
| `has_pending_continuation` | `() -> bool` | 检查对话是否以未回复的 tool_result 结尾 |

#### 公开属性

| 属性 | 返回类型 | 说明 |
|------|----------|------|
| `messages` | `list[ConversationMessage]` | 当前对话历史（副本） |
| `max_turns` | `int \| None` | 最大轮次数 |
| `api_client` | `SupportsStreamingMessages` | 活跃 API 客户端 |
| `model` | `str` | 活跃模型标识符 |
| `system_prompt` | `str` | 活跃系统提示词 |
| `tool_metadata` | `dict[str, object]` | 可变工具元数据/carryover 状态 |
| `total_usage` | `UsageSnapshot` | 跨轮次聚合用量 |

#### `submit_message` 内部流程

1. 若 `prompt` 为 `str` → 调用 `ConversationMessage.from_user_text(prompt)`
2. 若用户文本非空 → 调用 `remember_user_goal(tool_metadata, text)`
3. 追加 `user_message` 到 `self._messages`
4. 构建 `QueryContext`（从自身字段复制）
5. 构建 Coordinator 上下文消息（若适用）并追加到 `query_messages`
6. 迭代 `run_query(context, query_messages)`:
   - 若事件为 `AssistantTurnComplete` → 将 `query_messages` 同步回 `self._messages`
   - 若 `usage` 非空 → `self._cost_tracker.add(usage)`
   - yield 事件

#### `has_pending_continuation` 判定逻辑

1. 若消息列表为空 → False
2. 若最后一条消息的 role 不是 "user" → False
3. 若最后一条消息不含 ToolResultBlock → False
4. 向前遍历寻找最近的 assistant 消息 → 返回其 `tool_uses` 是否非空

### 5.2 run_query（query.py）

```python
async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]
```

返回异步迭代器，每步产出 `(StreamEvent, UsageSnapshot | None)` 元组。`usage` 仅在 `AssistantTurnComplete` 事件时非 None。

### 5.3 _execute_tool_call（query.py）

```python
async def _execute_tool_call(
    context: QueryContext,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, object],
) -> ToolResultBlock
```

内部函数，执行 7 步工具管线，始终返回 `ToolResultBlock`（错误情况也返回 `is_error=True` 的结果而非抛异常）。

### 5.4 remember_user_goal（query.py）

```python
def remember_user_goal(
    tool_metadata: dict[str, object] | None,
    prompt: str,
) -> None
```

将用户目标摘要记入 `task_focus_state.goal` 和 `task_focus_state.recent_goals`。

### 5.5 模块公开导出（__init__.py）

通过 `__all__` 和延迟导入 `__getattr__` 导出：

| 导出名 | 来源 |
|--------|------|
| `ConversationMessage` | `engine/messages.py` |
| `TextBlock` | `engine/messages.py` |
| `ImageBlock` | `engine/messages.py` |
| `ToolUseBlock` | `engine/messages.py` |
| `ToolResultBlock` | `engine/messages.py` |
| `QueryEngine` | `engine/query_engine.py` |
| `AssistantTextDelta` | `engine/stream_events.py` |
| `AssistantTurnComplete` | `engine/stream_events.py` |
| `ToolExecutionStarted` | `engine/stream_events.py` |
| `ToolExecutionCompleted` | `engine/stream_events.py` |

> 注意：`ErrorEvent`、`StatusEvent`、`CompactProgressEvent`、`CostTracker`、`QueryContext`、`run_query` 不在 `__all__` 中，属于内部实现。

---

## 6. 错误处理

### 6.1 异常层级

```
RuntimeError
  └── MaxTurnsExceeded  (max_turns 超限)
```

### 6.2 错误码/分类

Engine 模块本身不定义数字错误码，而是通过 `ToolResultBlock.is_error=True` 和 `ErrorEvent` 进行分类：

| 错误场景 | 处理方式 | 是否可恢复 |
|----------|----------|------------|
| 工具未找到 | ToolResultBlock(is_error=True, content="Unknown tool: ...") | 是（模型可修正调用） |
| 输入校验失败 | ToolResultBlock(is_error=True, content="Invalid input: ...") | 是（模型可修正参数） |
| PreToolUse Hook 阻止 | ToolResultBlock(is_error=True, content=blocked.reason) | 取决于 hook |
| 权限拒绝 | ToolResultBlock(is_error=True, content=decision.reason) | 是（用户可重新确认） |
| Prompt Too Long | 响应式压缩 → 重试，若压缩失败 → ErrorEvent | 条件性可恢复 |
| 网络错误 | ErrorEvent(message="Network error: ...", recoverable=True) | 是 |
| 其他 API 错误 | ErrorEvent(message="API error: ...", recoverable=True) | 视情况 |
| 空助手消息 | ErrorEvent(message="Model returned empty..."), 忽略该轮 | 是 |
| 模型流无最终消息 | RuntimeError("Model stream finished without a final message") | 否（编程错误） |
| 超过 max_turns | MaxTurnsExceeded(max_turns) | 否 |
| 并发工具执行异常 | ToolResultBlock(is_error=True, content="Tool X failed: ...") | 是（其余工具正常） |

### 6.3 恢复策略

1. **工具级错误** — 以 `ToolResultBlock(is_error=True)` 回传给模型，模型可自主决定修正策略。
2. **API 级错误** — 通过 `ApiRetryEvent` 实现重试（由 api_client 层处理），Engine 仅 yield StatusEvent 通知 UI。
3. **上下文超限** — 首次触发响应式压缩（仅一次），压缩后重试；若压缩失败则终止并 yield ErrorEvent。
4. **并发工具异常** — `asyncio.gather(return_exceptions=True)` 确保单个工具异常不影响其他工具的 tool_result 生成，避免违反 Anthropic API 的 tool_use/tool_result 配对约束。
5. **网络中断** — yield ErrorEvent 并终止循环，由上层决定是否重试。

---

## 7. 配置项

### 7.1 QueryEngine 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_tokens` | `int` | `4096` | 单次 API 调用的最大生成 Token 数 |
| `context_window_tokens` | `int \| None` | `None` | 模型上下文窗口大小，None 时由压缩服务推断 |
| `auto_compact_threshold_tokens` | `int \| None` | `None` | 触发自动压缩的 Token 阈值 |
| `max_turns` | `int \| None` | `8` | 单次 submit_message 的最大 Agent 轮次，None 为无限制 |

### 7.2 QueryContext 配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_turns` | `int \| None` | `200` | run_query 内部默认值（被 QueryEngine 传入的 8 覆盖） |
| `permission_prompt` | `PermissionPrompt \| None` | `None` | 用户确认回调，None 则跳过确认直接拒绝 |
| `ask_user_prompt` | `AskUserPrompt \| None` | `None` | 用户输入回调 |
| `hook_executor` | `HookExecutor \| None` | `None` | Hook 执行器，None 则跳过所有 Hook |

### 7.3 Carryover 桶容量常量

| 常量 | 值 | 说明 |
|------|------|------|
| `MAX_TRACKED_READ_FILES` | 6 | 已读文件状态最大条目数 |
| `MAX_TRACKED_SKILLS` | 8 | 已调用技能最大条目数 |
| `MAX_TRACKED_ASYNC_AGENT_EVENTS` | 8 | 异步 Agent 事件最大条目数 |
| `MAX_TRACKED_WORK_LOG` | 10 | 操作日志最大条目数 |
| `MAX_TRACKED_USER_GOALS` | 5 | 用户目标最大条目数 |
| `MAX_TRACKED_ACTIVE_ARTIFACTS` | 8 | 活跃制品最大条目数 |
| `MAX_TRACKED_VERIFIED_WORK` | 10 | 已验证工作最大条目数 |

### 7.4 状态消息常量

| 常量 | 值 | 说明 |
|------|------|------|
| `AUTO_COMPACT_STATUS_MESSAGE` | `"Auto-compacting conversation memory to keep things fast and focused."` | 自动压缩状态消息 |
| `REACTIVE_COMPACT_STATUS_MESSAGE` | `"Prompt too long; compacting conversation memory and retrying."` | 响应式压缩状态消息 |

---

## 8. 与其它模块的交互

### 8.1 模块调用关系

```
                    ┌─────────────┐
                    │   TUI / UI  │  (消费 StreamEvent)
                    └──────┬──────┘
                           │ 调用
                    ┌──────▼──────┐
                    │ QueryEngine │  (engine/query_engine.py)
                    └──────┬──────┘
                           │ 委托
          ┌────────────────┼────────────────┐
          v                v                v
   ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
   │  run_query   │ │ CostTracker  │ │ ConversationMsg[]│
   │ (query.py)   │ │cost_tracker  │ │   (messages.py)  │
   └──────┬───────┘ └──────────────┘ └──────────────────┘
          │
   ┌──────┼──────────────────────────────┐
   v      v              v                v
┌───────┐┌──────────┐┌──────────┐┌──────────────┐
│api/   ││services/ ││tools/    ││permissions/  │
│client ││compact   ││base      ││checker       │
└───────┘└──────────┘└──────────┘└──────────────┘
   │                    │               │
   v                    v               v
┌──────────┐    ┌──────────┐   ┌──────────────┐
│Anthropic │    │Hook      │   │Permission    │
│API       │    │Executor  │   │Decision      │
└──────────┘    └──────────┘   └──────────────┘
```

### 8.2 数据流向

#### 8.2.1 用户输入 → 模型响应

```
用户文本 → QueryEngine.submit_message()
         → ConversationMessage.from_user_text()
         → remember_user_goal()
         → QueryContext 构建
         → run_query(context, messages)
         → [auto-compact 检查]
         → api_client.stream_message()
         → 流式 yield: AssistantTextDelta / StatusEvent
         → 最终: ApiMessageCompleteEvent
         → yield AssistantTurnComplete
```

#### 8.2.2 工具调用流

```
AssistantTurnComplete (含 tool_uses)
→ 检测 tool_calls
→ 单工具: 顺序执行
   ToolExecutionStarted → _execute_tool_call → ToolExecutionCompleted
→ 多工具: 并发执行
   [ToolExecutionStarted × N] → asyncio.gather → [ToolExecutionCompleted × N]
→ ConversationMessage(role="user", content=tool_results)
→ 回到循环顶部
```

#### 8.2.3 错误恢复流

```
API 异常
├── "prompt too long" (首次)
│   → StatusEvent(reactive compact)
│   → auto_compact_if_needed(force=True)
│   → 成功 → 重新进入循环
│   → 失败 → ErrorEvent → 终止
├── 网络错误
│   → ErrorEvent("Network error: ...") → 终止
└── 其他 API 错误
    → ErrorEvent("API error: ...") → 终止
```

#### 8.2.4 用量追踪流

```
ApiMessageCompleteEvent.usage (UsageSnapshot)
→ run_query yield (event, usage)
→ QueryEngine: cost_tracker.add(usage)
→ QueryEngine.total_usage → 累积的 UsageSnapshot
```

### 8.3 外部模块依赖表

| 外部模块 | 引用位置 | 用途 |
|----------|----------|------|
| `api/client` | query.py, query_engine.py | 流式消息请求（`SupportsStreamingMessages`, `ApiMessageRequest` 等） |
| `api/usage` | cost_tracker.py, stream_events.py, query.py | Token 用量模型（`UsageSnapshot`） |
| `tools/base` | query.py, query_engine.py | 工具注册与执行（`ToolRegistry`, `ToolExecutionContext`） |
| `permissions/checker` | query.py, query_engine.py | 权限评估（`PermissionChecker`） |
| `hooks` | query.py, query_engine.py | Hook 事件执行（`HookEvent`, `HookExecutor`） |
| `services/compact` | query.py | 自动压缩（`AutoCompactState`, `auto_compact_if_needed`） |
| `coordinator/coordinator_mode` | query_engine.py | Coordinator 上下文构建（`get_coordinator_user_context`） |

### 8.4 被外部引用

Engine 模块的公开 API 被以下上层模块消费：

- **TUI / UI 层** — 消费 `StreamEvent` 流，展示给用户
- **Session 管理** — 调用 `QueryEngine.submit_message()` / `continue_pending()`
- **Coordinator 模式** — 通过 `QueryEngine._build_coordinator_context_message()` 注入上下文

---

## 附录 A: CompactProgressEvent.phase 完整枚举

| phase | 触发时机 |
|-------|----------|
| `hooks_start` | Hook 处理开始 |
| `context_collapse_start` | 上下文折叠开始 |
| `context_collapse_end` | 上下文折叠结束 |
| `session_memory_start` | 会话记忆处理开始 |
| `session_memory_end` | 会话记忆处理结束 |
| `compact_start` | LLM 压缩开始 |
| `compact_retry` | LLM 压缩重试 |
| `compact_end` | LLM 压缩完成 |
| `compact_failed` | LLM 压缩失败 |

## 附录 B: StreamEvent 类型与产出场景

| 事件类型 | 产出场景 | 携带 usage |
|----------|----------|------------|
| AssistantTextDelta | API 流式返回文本增量 | 否 |
| AssistantTurnComplete | 模型完成一个完整轮次 | 是 |
| ToolExecutionStarted | 工具即将执行 | 否 |
| ToolExecutionCompleted | 工具执行完成 | 否 |
| ErrorEvent | API 错误或空助手消息 | 条件性 |
| StatusEvent | 重试提示、压缩状态 | 否 |
| CompactProgressEvent | 压缩进度更新 | 否 |