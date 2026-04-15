# Phase 3: Agent Loop 核心深度解析

> 涉及文件: `engine/query_engine.py` (206行), `engine/query.py` (746行)
> 这是整个 OpenHarness 的心脏 — 理解了这里就理解了系统运转的一半

---

## 1. 架构总览: 两层结构

```
QueryEngine (高层)          ← 拥有对话历史, 管理会话状态
  └→ run_query() (底层)     ← 纯粹的循环逻辑, 无状态
```

**职责分离**:
- `QueryEngine` 是**有状态**的: 持有 `_messages`, `_cost_tracker`, 所有配置
- `run_query()` 是**无状态**的: 接收 `QueryContext` + `messages`, 只做循环

每次调用 `submit_message()` 时, QueryEngine 将自身状态打包进 `QueryContext`, 传给 `run_query()` 执行。

---

## 2. QueryEngine — 会话管理者

```
QueryEngine
├── 持有状态:
│   ├── _messages: list[ConversationMessage]     # 对话历史
│   ├── _cost_tracker: CostTracker               # 用量累计
│   ├── _api_client: SupportsStreamingMessages    # API 客户端
│   ├── _tool_registry: ToolRegistry              # 工具注册表
│   ├── _permission_checker: PermissionChecker    # 权限检查器
│   ├── _hook_executor: HookExecutor              # Hook 执行器
│   ├── _tool_metadata: dict                     # 工具元数据 (跨轮携带)
│   └── 配置: _model, _system_prompt, _max_tokens, _max_turns, ...
│
├── 公开方法:
│   ├── submit_message(prompt) → AsyncIterator[StreamEvent]  # 提交新消息, 启动循环
│   ├── continue_pending()    → AsyncIterator[StreamEvent]  # 继续被中断的工具循环
│   ├── load_messages()       # 恢复会话历史
│   ├── clear()               # 清空历史和用量
│   └── set_*()               # 运行时更新配置 (model, system_prompt, api_client, ...)
│
└── 内部:
    ├── _build_coordinator_context_message()  # Swarm 协调器注入上下文
    └── has_pending_continuation()            # 检查是否有未完成的工具循环
```

### submit_message 完整流程

```python
async def submit_message(self, prompt):
    # 1. 构造用户消息, 记录用户目标
    user_message = ConversationMessage.from_user_text(prompt)
    remember_user_goal(self._tool_metadata, user_message.text)
    self._messages.append(user_message)

    # 2. 打包 QueryContext (无状态上下文)
    context = QueryContext(
        api_client=self._api_client,
        tool_registry=self._tool_registry,
        permission_checker=self._permission_checker,
        ...
    )

    # 3. 准备消息列表 (可能追加协调器上下文)
    query_messages = list(self._messages)
    coordinator_context = self._build_coordinator_context_message()
    if coordinator_context:
        query_messages.append(coordinator_context)

    # 4. 进入核心循环
    async for event, usage in run_query(context, query_messages):
        if isinstance(event, AssistantTurnComplete):
            self._messages = list(query_messages)  # 同步历史
        if usage:
            self._cost_tracker.add(usage)
        yield event
```

### continue_pending vs submit_message

| | submit_message | continue_pending |
|---|---|---|
| 追加用户消息 | ✅ | ❌ |
| 启动新循环 | ✅ | ✅ (从现有消息继续) |
| 典型场景 | 用户输入新提示 | `/continue` 恢复被中断的循环 |

---

## 3. QueryContext — 循环的无状态上下文

```python
@dataclass
class QueryContext:
    api_client: SupportsStreamingMessages       # API 客户端
    tool_registry: ToolRegistry                 # 工具注册表
    permission_checker: PermissionChecker        # 权限检查器
    cwd: Path                                   # 工作目录
    model: str                                  # 模型 ID
    system_prompt: str                          # 系统提示词
    max_tokens: int                             # 最大输出 token
    context_window_tokens: int | None           # 上下文窗口大小
    auto_compact_threshold_tokens: int | None   # 自动压缩阈值
    permission_prompt: PermissionPrompt | None   # 权限确认回调
    ask_user_prompt: AskUserPrompt | None       # 用户提问回调
    max_turns: int | None = 200                 # 最大循环轮次
    hook_executor: HookExecutor | None          # Hook 执行器
    tool_metadata: dict | None                  # 跨轮携带元数据
```

**设计关键**: `tool_metadata` 是一个可变 dict, 在循环过程中被 `_record_tool_carryover()` 持续更新, 携带跨轮状态 (已读文件、已调 Skill、工作日志等)。这确保了上下文压缩后, 关键状态不丢失。

---

## 4. run_query() — Agent Loop 核心 (746行中的核心 ~200行)

### 完整流程图

```
run_query(context, messages)
│
├── 初始化: compact_state, turn_count=0
│
└── while turn_count < max_turns:
    │
    ├── ① 自动压缩检查 (auto-compact)
    │   └── 如果估算 token 超过阈值 → 尝试压缩
    │       ├── 先做 microcompact (清除旧工具结果内容)
    │       └── 不够则做 LLM 摘要压缩
    │
    ├── ② 调用 API (流式)
    │   └── api_client.stream_message(request)
    │       ├── ApiTextDeltaEvent     → yield AssistantTextDelta
    │       ├── ApiRetryEvent         → yield StatusEvent (重试提示)
    │       └── ApiMessageCompleteEvent → 拿到 final_message + usage
    │
    ├── ③ 错误处理
    │   ├── prompt_too_long 且未尝试过 reactive compact
    │   │   └── 尝试强制压缩, 成功则 continue
    │   ├── 网络错误 → yield ErrorEvent
    │   └── 其他错误 → yield ErrorEvent, return
    │
    ├── ④ 空消息保护
    │   └── assistant 返回空消息 → yield ErrorEvent, return
    │
    ├── ⑤ 记录助手回复
    │   ├── messages.append(final_message)
    │   └── yield AssistantTurnComplete
    │
    ├── ⑥ 检查是否有工具调用
    │   └── if not final_message.tool_uses → return (循环结束!)
    │
    ├── ⑦ 执行工具
    │   ├── 单工具: 顺序执行, 实时 yield 事件
    │   └── 多工具: asyncio.gather 并行执行
    │       └── return_exceptions=True, 单个失败不影响其他
    │
    ├── ⑧ 追加工具结果
    │   └── messages.append(ConversationMessage(role="user", content=tool_results))
    │
    └── continue (回到 ①, 模型看到工具结果, 决定下一步)
```

### 循环退出条件

| 条件 | 结果 |
|------|------|
| 模型不请求工具调用 (只有文本) | 正常退出 |
| `turn_count >= max_turns` | 抛出 `MaxTurnsExceeded` |
| API 错误 (含网络) | yield ErrorEvent, 退出 |
| 空助手消息 | yield ErrorEvent, 退出 |

### 单工具 vs 多工具执行策略

```python
# 单工具: 顺序, 实时流式事件
if len(tool_calls) == 1:
    yield ToolExecutionStarted   # UI 立即看到
    result = await _execute_tool_call(...)
    yield ToolExecutionCompleted  # UI 立即看到

# 多工具: 并行, 事件延迟到全部完成后
else:
    for tc in tool_calls:
        yield ToolExecutionStarted    # 先发出所有 "开始" 事件
    raw_results = await asyncio.gather(  # 并行执行
        *[_run(tc) for tc in tool_calls],
        return_exceptions=True          # 单个失败不取消其他!
    )
    for tc, result in zip(tool_calls, tool_results):
        yield ToolExecutionCompleted    # 最后发出所有 "完成" 事件
```

**`return_exceptions=True` 的关键意义**: Anthropic API 要求每个 `tool_use` 都有对应的 `tool_result`, 缺少任何一个都会拒绝下一次请求。所以即使某个工具抛异常, 也必须产生一个 `is_error=True` 的 ToolResultBlock。

---

## 5. _execute_tool_call() — 单个工具的完整执行管道 (111行)

```
_execute_tool_call(context, tool_name, tool_use_id, tool_input)
│
├── ① PreToolUse Hook
│   └── hook_executor.execute(PRE_TOOL_USE, {tool_name, tool_input})
│       └── 如果 blocked → 返回 ToolResultBlock(is_error=True)
│
├── ② 工具查找
│   └── tool_registry.get(tool_name)
│       └── 如果 not found → 返回 "Unknown tool" 错误
│
├── ③ 输入验证
│   └── tool.input_model.model_validate(tool_input)
│       └── 如果验证失败 → 返回 "Invalid input" 错误
│
├── ④ 权限检查
│   ├── 解析文件路径: _resolve_permission_file_path()
│   ├── 解析命令: _extract_permission_command()
│   ├── permission_checker.evaluate(tool_name, is_read_only, file_path, command)
│   └── 如果不允许:
│       ├── requires_confirmation=True → 调用 permission_prompt 让用户确认
│       │   └── 用户拒绝 → 返回 "Permission denied" 错误
│       └── 否则 → 直接返回 "Permission denied" 错误
│
├── ⑤ 工具执行
│   └── tool.execute(parsed_input, ToolExecutionContext(cwd, metadata))
│
├── ⑥ 状态携带 (carryover)
│   └── _record_tool_carryover(context, tool_name, tool_input, tool_output, ...)
│
└── ⑦ PostToolUse Hook
    └── hook_executor.execute(POST_TOOL_USE, {tool_name, tool_input, tool_output, ...})
```

### 权限路径解析逻辑

```python
def _resolve_permission_file_path(cwd, raw_input, parsed_input):
    # 从原始输入 dict 查找: file_path → path → root
    # 再从 Pydantic 模型属性查找: file_path → path → root
    # 相对路径 → 基于 cwd 转为绝对路径
```

```python
def _extract_permission_command(raw_input, parsed_input):
    # 从原始输入 dict 查找: command
    # 再从 Pydantic 模型属性查找: command
```

这确保权限检查能正确处理各种工具的路径/命令字段命名差异。

---

## 6. Tool Metadata / Carryover 系统 — 跨轮状态保持

`tool_metadata` 是一个可变 dict, 在 `_record_tool_carryover()` 中被持续更新。它在 `QueryEngine` 构造时初始化, 贯穿整个会话。

### 追踪的状态

| 键 | 用途 | 容量上限 | 由哪些工具触发 |
|----|------|----------|---------------|
| `read_file_state` | 最近读取的文件 (路径+行范围+预览) | 6 条 | `read_file` |
| `invoked_skills` | 最近调用的 Skill | 8 个 | `skill` |
| `async_agent_state` | 子 Agent 活动 | 8 条 | `agent`, `send_message` |
| `recent_work_log` | 工作日志 | 10 条 | 多种工具 |
| `recent_verified_work` | 已验证的工作 | 10 条 | 多种工具 |
| `active_artifacts` | 活跃文件/URL | 8 个 | `read_file`, `skill`, `web_fetch` |
| `permission_mode` | 当前权限模式 | 1 值 | `enter_plan_mode`, `exit_plan_mode` |
| `task_focus_state` | 任务聚焦状态 | 嵌套 | `remember_user_goal` |

### task_focus_state 子结构

```python
{
    "goal": "当前用户目标",
    "recent_goals": [],       # 最近5个目标
    "active_artifacts": [],   # 活跃文件/URL
    "verified_state": [],     # 已验证的工作
    "next_step": "",
}
```

**设计意图**: 上下文压缩 (compact) 会丢弃旧消息, 但 `tool_metadata` 保留。这样压缩后, 模型仍然知道"最近读了哪些文件"、"调过什么 Skill"、"当前目标是什么"。

---

## 7. 自动压缩集成

```python
# 每个 turn 开始前
async for event, usage in _stream_compaction(trigger="auto"):
    yield event, usage
messages, was_compacted = last_compaction_result
```

压缩流程:
1. **自动检查** (每轮): 估算 token → 超过阈值 → 压缩
2. **响应式压缩** (API 报错时): 如果 `prompt_too_long` → 强制压缩 → 重试
3. **压缩策略**: 先做 microcompact (清除旧工具结果, 便宜), 不够则 LLM 摘要
4. **进度流**: 通过 `CompactProgressEvent` 实时通知 UI

关键: `reactive_compact_attempted` 标志确保响应式压缩只尝试一次, 避免无限循环。

---

## 8. 完整数据流总结

```
用户输入 "读取 main.py"
    │
    ▼
QueryEngine.submit_message("读取 main.py")
    │
    ├─ 记住用户目标 → tool_metadata["task_focus_state"]["goal"]
    ├─ 构造 ConversationMessage(role="user", content=[TextBlock("读取 main.py")])
    │
    ▼
run_query(context, messages)
    │
    ├─ [Turn 1] auto-compact 检查 (首次不触发)
    ├─ API 调用 → 模型返回: TextBlock("我来读取") + ToolUseBlock(name="read_file", input={"file_path": "main.py"})
    ├─ yield AssistantTextDelta("我来读取")
    ├─ yield AssistantTurnComplete
    │
    ├─ 检测到 tool_uses → 进入工具执行
    │   ├─ PreToolUse Hook → 未阻断
    │   ├─ 工具查找 → FileReadTool ✓
    │   ├─ 输入验证 → {"file_path": "main.py"} ✓
    │   ├─ 权限检查 → read_only=True, default 模式 → 允许
    │   ├─ 执行 → ToolResult(output="1: import os\n2: ...")
    │   ├─ carryover → 更新 read_file_state, active_artifacts, work_log
    │   └─ PostToolUse Hook
    │
    ├─ yield ToolExecutionStarted / ToolExecutionCompleted
    ├─ 追加工具结果: ConversationMessage(role="user", content=[ToolResultBlock(...)])
    │
    ▼
    ├─ [Turn 2] auto-compact 检查 (可能不触发)
    ├─ API 调用 → 模型看到文件内容, 返回: TextBlock("这个文件是一个...")
    ├─ yield AssistantTextDelta("这个文件是一个...")
    ├─ yield AssistantTurnComplete
    │
    ├─ 没有 tool_uses → return (循环结束!)
    │
    ▼
返回 QueryEngine → 更新 messages, 累加 cost → 保存会话快照
```

---

## 9. 关键设计决策

### 9a: 为什么 QueryContext 是 dataclass 而不是 Pydantic?

`QueryContext` 是一次查询运行的临时上下文, 不需要序列化/验证。用 dataclass 更轻量, 且支持可变字段 (`tool_metadata`)。

### 9b: 为什么多工具并行而不是顺序?

用户体验: 模型同时请求 `read_file(a.py)` + `read_file(b.py)` 时, 并行执行节省等待时间。但 UI 事件是先发所有 Started, 再发所有 Completed, 避免 UI 交错闪烁。

### 9c: 为什么 return_exceptions=True?

Anthropic API 硬性要求: 每个 `tool_use_id` 必须有对应 `tool_result`。如果某个工具异常导致整个 gather 失败, 对话历史中会缺少 tool_result, 下一次 API 调用会被拒绝。所以必须把异常转为 `is_error=True` 的 ToolResultBlock。

### 9d: 为什么 carryover 存在?

上下文压缩 (compact) 会丢弃消息, 但 Agent 需要记住"我做了什么"。`tool_metadata` 在压缩过程中被保留, 作为压缩后系统提示词的补充信息注入。

---

## 10. 与其他模块的关系

```
                    ┌─────────────┐
                    │  QueryEngine │
                    └──────┬──────┘
                           │ 调用
                    ┌──────▼──────┐
                    │  run_query() │
                    └──────┬──────┘
                           │
        ┌──────────┬───────┼───────┬──────────┐
        │          │       │       │          │
   ┌────▼────┐ ┌───▼───┐ ┌─▼─┐ ┌──▼──┐ ┌────▼────┐
   │API Client│ │Tools  │ │P.C│ │Hooks│ │Compact  │
   │(上游)    │ │(执行) │ │(守门)│ │(拦截)│ │(压缩)   │
   └─────────┘ └───────┘ └───┘ └─────┘ └─────────┘
```

- **API Client**: 提供流式消息, 是循环的"输入源"
- **Tools**: 执行工具调用, 是循环的"手"
- **PermissionChecker**: 守门, 决定工具能否执行
- **Hooks**: 拦截, 可以在工具执行前后做任意操作 (含阻断)
- **Compact**: 压缩, 当上下文过长时压缩历史消息

---

## 速查: 看到这些词就知道在哪

| 概念 | 位置 | 说明 |
|------|------|------|
| `run_query()` | `engine/query.py:396` | 主循环入口 |
| `_execute_tool_call()` | `engine/query.py:595` | 工具执行管道 |
| `MaxTurnsExceeded` | `engine/query.py:70` | 超轮次异常 |
| `QueryContext` | `engine/query.py:78` | 循环上下文 |
| `remember_user_goal()` | `engine/query.py:144` | 记录用户目标 |
| `_record_tool_carryover()` | `engine/query.py:286` | 工具状态携带 |
| `QueryEngine.submit_message()` | `engine/query_engine.py:147` | 提交消息 |
| `QueryEngine.continue_pending()` | `engine/query_engine.py:184` | 继续循环 |