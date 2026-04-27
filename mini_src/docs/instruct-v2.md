那目前mini_src 是否包含 管理 context window功能？

  Read 2 files (ctrl+o to expand)

● 不包含。 loop.py 第 1 行注释就说得很清楚：

  """Core tool-aware query loop — simplified without hooks/permissions/compaction."""

  具体来看，mini_src 在整个流程中完全没有 context window 管理：

  缺失的能力

  ┌─────────────────────────────────────────────────────────────────────────────────────────────────┬─────────────────┐
  │                                       OpenHarness 完整版                                        │    mini_src     │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ Token 估算 (services/token_estimation.py)                                                       │ ❌ 无           │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ 检测 prompt too long / context window 错误 (_is_prompt_too_long_error 虽然定义了，但从未被调用) │ ❌ 定义了但不用 │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ Microcompact — 自动清除旧 tool result                                                           │ ❌ 无           │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ Full compact — LLM 摘要压缩旧对话                                                               │ ❌ 无           │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ Auto-compact — token 超阈值自动触发                                                             │ ❌ 无           │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ 压缩后重建消息列表                                                                              │ ❌ 无           │
  ├─────────────────────────────────────────────────────────────────────────────────────────────────┼─────────────────┤
  │ 唯一的管理手段只有 max_turns（超限直接抛 MaxTurnsExceeded 错误）                                │ 仅有            │
  └─────────────────────────────────────────────────────────────────────────────────────────────────┴─────────────────┘

  mini_src 的对话流程

  用户消息 → API 调用 → 处理工具结果 → 追加到 messages 列表 → 下一轮
                                                             ↓
                                       messages 无限增长，永不压缩

  一旦对话变长超过模型 context window，只会从 API 收到一个 prompt too long 错误（loop.py:117-119），直接当作普通 API error 返回给用户——没有重试、没有压缩、没有 fallback。

 规划从Openharness 移植以下功能到mini_src:token 估算、 microcompact、auto-compact、 LLM 摘要边界压缩及context window 管理

 Here is Claude's plan:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Plan: Port Context Window Management to mini_src

 Context

 mini_src currently has no context window management — messages grow unbounded until the model's context window is exceeded, at which point the API returns a "prompt too
 long" error and the loop terminates. OpenHarness has a full compaction pipeline (microcompact → context collapse → session memory → full LLM summary), hook system, and
 attachment builders.

 This plan ports the core compaction pipeline in a simplified form: no hooks, no attachment builders, no progress callbacks. Only the essential 4-stage escalation and the
 glue to wire it into the existing loop.

 ---
 Files to Modify

 ┌──────────────────────────┬───────────────────────────────────────────────────────────────────────────┐
 │           File           │                                  Change                                   │
 ├──────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
 │ mini_src/core/compact.py │ NEW (~500 lines) — all compaction logic                                   │
 ├──────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
 │ mini_src/core/loop.py    │ Add compaction calls before model call + reactive compaction on PTL error │
 ├──────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
 │ mini_src/core/engine.py  │ Add compaction config to QueryEngine, wire through QueryContext           │
 ├──────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
 │ mini_src/config.py       │ Add 4 new get_*() env-var accessors                                       │
 ├──────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
 │ mini_src/__main__.py     │ Pass compaction config to QueryEngine                                     │
 └──────────────────────────┴───────────────────────────────────────────────────────────────────────────┘

 ---
 Step 1: mini_src/config.py — add env var accessors

 Add at end of file:

 def get_context_window_tokens() -> int | None  # OPENHARNESS_CONTEXT_WINDOW_TOKENS
 def get_auto_compact_threshold_tokens() -> int | None  # OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS
 def get_compact_preserve_recent() -> int  # OPENHARNESS_COMPACT_PRESERVE_RECENT, default 6
 def is_auto_compact_enabled() -> bool  # OPENHARNESS_AUTO_COMPACT_ENABLED, default true

 Step 2: mini_src/core/compact.py — new file (~500 lines)

 Structure (port of src/openharness/services/compact/__init__.py, simplified):

 2a. Constants & Types

 - COMPACTABLE_TOOLS — read_file, bash, grep, glob, write_file, edit_file
 - Threshold constants (same values as OpenHarness: AUTOCOMPACT_BUFFER_TOKENS=13000, etc.)
 - AutoCompactState — dataclass: compacted, turn_counter, consecutive_failures
 - CompactionResult — dataclass: boundary_marker, summary_messages, messages_to_keep, compact_metadata

 2b. Token Estimation

 - estimate_tokens(text) -> int — max(1, len(text)//4), zero deps
 - estimate_message_tokens(messages) -> int — walks TextBlock/ToolResultBlock/ToolUseBlock, applies * 4/3 padding

 2c. Context Window Helpers

 - get_context_window(model, *, context_window_tokens=None) -> int — 200K default
 - get_autocompact_threshold(model, *, ...) -> int — context_window - 33_000
 - should_autocompact(messages, model, state, *, ...) -> bool — estimate >= threshold, fail after 3 consecutive failures

 2d. Microcompact

 - microcompact_messages(messages, *, keep_recent=5) -> tuple[list[ConversationMessage], int]
 - Collects tool_use IDs for compactable tools, clears old ToolResultBlock.content → "[Old tool result content cleared]"

 2e. Context Collapse

 - _collapse_text(text) -> str — head-900 + "[collapsed N chars]" + tail-500
 - try_context_collapse(messages, *, preserve_recent) -> list | None — truncate oversized text blocks deterministically

 2f. Session Memory Compaction

 - _summarize_message_for_memory(message) -> str — one-line per message: role: text[:160] or tool calls -> names or tool results returned
 - try_session_memory_compaction(messages, *, ...) -> CompactionResult | None — cheap line-per-message summary, caps at 48 lines / 4000 chars

 2g. Full Compact Prompt & Formatting

 - get_compact_prompt(custom_instructions=None) -> str — shortened prompt (no OpenHarness-specific sections)
 - format_compact_summary(raw_summary) -> str — strip <analysis>, extract <summary>
 - build_compact_summary_message(summary, *, ...) -> str — "continued from previous conversation..."
 - create_compact_boundary_message(metadata) -> ConversationMessage — boundary marker with pre/post counts

 2h. Full Compact Execution

 - async compact_conversation(messages, *, api_client, model, system_prompt="", preserve_recent=6, ...) -> CompactionResult
   - Guard: if len <= preserve_recent, return passthrough
   - Microcompact → split older/newer → build compact prompt → call LLM → build summary message → rebuild
   - Uses existing SupportsStreamingMessages protocol (same api_client from loop)
   - Retry: PTL retries with truncate_head_for_ptl_retry() (up to 3), streaming retries (up to 2)
   - No hooks, no progress callbacks, no attachment builders

 2i. Auto-compact Orchestration

 - async auto_compact_if_needed(messages, *, api_client, model, ..., state, ...) -> tuple[list[ConversationMessage], bool]
   - Progressive: microcompact → context collapse → session memory → full compact
   - Returns (new_messages, was_compacted)
   - Same escalation logic as OpenHarness, minus hooks

 Step 3: mini_src/core/loop.py — wire compaction into run_query()

 3a. Add to QueryContext

 auto_compact_state: AutoCompactState | None = None
 context_window_tokens: int | None = None
 auto_compact_threshold_tokens: int | None = None
 preserve_recent: int = 6

 3b. Before the while loop in run_query()

 if context.auto_compact_state is not None:
     messages, was_compacted = await auto_compact_if_needed(
         messages, api_client=context.api_client, model=context.model,
         system_prompt=context.system_prompt, state=context.auto_compact_state,
         preserve_recent=context.preserve_recent,
         context_window_tokens=context.context_window_tokens,
         auto_compact_threshold_tokens=context.auto_compact_threshold_tokens,
     )
     if was_compacted:
         yield StatusEvent(message="Conversation compacted to free context window."), None

 3c. In the except Exception block — reactive compaction on PTL error

 if _is_prompt_too_long_error(exc) and context.auto_compact_state is not None:
     yield StatusEvent(message="Context window exceeded, compacting..."), None
     messages, was_compacted = await auto_compact_if_needed(
         messages, ..., force=True, trigger="reactive", ...
     )
     if was_compacted:
         continue  # retry

 3d. Use messages[:] = new_messages after compaction calls

 This ensures the caller (engine.py) sees the compacted list via the shared list reference.

 Step 4: mini_src/core/engine.py — add compaction config to QueryEngine

 4a. Constructor params

 auto_compact_enabled: bool = True
 context_window_tokens: int | None = None
 auto_compact_threshold_tokens: int | None = None
 preserve_recent: int = 6
 Creates self._auto_compact_state = AutoCompactState() if auto_compact_enabled else None.

 4b. Pass into QueryContext in submit_message()

 Step 5: mini_src/__main__.py — pass config

 Two places (run_once() and run_interactive()): import and pass is_auto_compact_enabled(), get_context_window_tokens(), etc. to QueryEngine.

 ---
 OpenHarness Features Explicitly NOT Ported

 ┌──────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
 │                         Feature                          │                           Reason                            │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ HookExecutor/HookEvent                                   │ No hook system in mini_src                                  │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ CompactAttachment + 9 builders                           │ OpenHarness domain concepts (plan mode, async agents, etc.) │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ CompactProgressEvent callback                            │ Replace via StatusEvent + logging                           │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ Checkpoint tracking (_record_compact_checkpoint)         │ Observability infrastructure                                │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ Legacy summarize_messages() / compact_messages()         │ Dead code in OpenHarness                                    │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ _extract_attachment_paths(), _extract_discovered_tools() │ Attachment-specific                                         │
 ├──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
 │ _build_passthrough_compaction_result()                   │ Use CompactionResult directly                               │
 └──────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘

 ---
 Verification

 1. Syntax check: python -c "from mini_src.core.compact import *"
 2. No-compact baseline: With OPENHARNESS_AUTO_COMPACT_ENABLED=0, existing behavior unchanged
 3. Manual trigger: Start interactive session, /compact command initiates manual compact
 4. Status events: Compaction progress visible as StatusEvent("ℹ ...") output
 5. Reactive compact: Send a very long conversation to trigger PTL, verify compact fires and retries

  迁移full compaction pipeline (microcompact → context collapse → session memory → full LLM summary), hook system, and
   attachment builders 到mini_src 是否可行？

● 问得好，拆开看更清楚：

  4-stage pipeline ✅ 可行

  ┌──────────────────┬─────────────┬───────────────────────────────────────────────────────────────────────────────────────┐
  │      Stage       │   可行性    │                                         依赖                                          │
  ├──────────────────┼─────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ Microcompact     │ ✅ 直接移植 │ ConversationMessage + COMPACTABLE_TOOLS，mini_src 已有                                │
  ├──────────────────┼─────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ Context collapse │ ✅ 直接移植 │ 纯文本处理，零依赖                                                                    │
  ├──────────────────┼─────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ Session memory   │ ✅ 直接移植 │ 消息模型已存在                                                                        │
  ├──────────────────┼─────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
  │ Full LLM summary │ ✅ 需要适配 │ SupportsStreamingMessages protocol 已存在，compact_conversation() 去掉 hooks 回调即可 │
  └──────────────────┴─────────────┴───────────────────────────────────────────────────────────────────────────────────────┘

  这 4 个阶段我之前计划的 ~500 行 compact.py 全部覆盖。

  Hook system ❌ 不可行

  OpenHarness 的 hook 系统依赖链：

  HookExecutor (243行) → HookEvent (enum) → HookDefinition (Pydantic, 58行)
    → HookResult / AggregatedHookResult → 支持 command/http/prompt/agent 四种 hook 类型
    → 内部调用 api_client.stream_message() / asyncio.create_subprocess_shell() 等

  这不是一个可以"顺便带过来"的小模块。mini_src 的 loop.py 第 1 行就声明了 without hooks，要移植需要：
  - 新增 mini_src/hooks/ 包，至少 4 个文件
  - 修改 loop.py 和 engine.py 增加 hook 触发点
  - 引入钩子的配置/权限逻辑，与 mini_src 的简洁设计相悖

  而且 compact 中用 hooks 只是做两件事：前置检查（是否允许压缩）和通知（压缩完成）。这两者都可以用更简单的方式替代（配置开关 + StatusEvent）。

  Attachment builders ⚠️ 部分可行，但大部分无意义

  ┌─────────────────────────────┬───────────────────────────────────┬────────────────────┐
  │           Builder           │    依赖 mini_src 不存在的状态     │        结论        │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_recent_files         │ read_file_state                   │ ❌ 无此状态        │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_task_focus           │ task_focus_state, permission_mode │ ❌ 无 plan 模式    │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_recent_verified_work │ recent_verified_work              │ ❌ 无 verification │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_invoked_skills       │ invoked_skills                    │ ❌ 无 skill 系统   │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_async_agent          │ async_agent_state                 │ ❌ 无 agent 系统   │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_work_log             │ recent_work_log                   │ ❌ 无 work log     │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ create_plan_attachment      │ permission_mode=="plan"           │ ❌ 无 plan mode    │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ _create_hook_attachments    │ HookExecutor                      │ ❌ 无 hooks        │
  ├─────────────────────────────┼───────────────────────────────────┼────────────────────┤
  │ _extract_attachment_paths   │ 纯文本扫描 ImageBlock.source_path │ ✅ 可移植          │
  └─────────────────────────────┴───────────────────────────────────┴────────────────────┘

  9 个 builder 中有 8 个依赖 mini_src 根本不存在的领域状态，移植了也是死代码。

  结论

  microcompact → context collapse → session memory → full LLM summary
     ✅ 可行                ✅                ✅              ✅ (去 hooks)

  + hook system        → ❌ 大型依赖链，与设计目标冲突
  + 9个 attachment builders → ❌ 8/9 依赖不存在状态

  推荐方案：只移植 4-stage pipeline，hooks 和 attachment builders 不在 mini_src 的范围内。压缩触发时的状态通知直接用 StatusEvent 就够了。

   9个 attachment builders 主要实现什么功能

  Read 1 file (ctrl+o to expand)

● 9 个 attachment builders，每个的功能都是从 tool_metadata 中提取特定领域状态，打包成 CompactAttachment（一个 kind + title + body
  的数据结构），压缩后注入回对话，让模型"记住"这些上下文。

  按 _build_compact_attachments 中的调用顺序：

  ┌─────┬─────────────────────────────────────────────────┬─────────────────────────────────┬─────────────────────┬──────────────────────────────────────────────────────┐
  │  #  │                     Builder                     │           读取的状态            │     生成的 kind     │                         作用                         │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │     │                                                 │ metadata["task_focus_state"] →  │                     │                                                      │
  │ 1   │ create_task_focus_attachment_if_needed          │ goal, recent_goals,             │ task_focus          │ 告诉模型压缩前正在做什么、当前目标、已验证状态、下一 │
  │     │                                                 │ active_artifacts,               │                     │ 步                                                   │
  │     │                                                 │ verified_state, next_step       │                     │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 2   │ create_recent_verified_work_attachment_if_neede │ metadata["recent_verified_work" │ recent_verified_wor │ 列出最近已验证完成的工作项                           │
  │     │ d                                               │ ] (列表)                        │ k                   │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │     │                                                 │ 扫描旧消息中                    │                     │                                                      │
  │ 3   │ _create_recent_attachments_attachment_if_needed │ ImageBlock.source_path +        │ recent_attachments  │ 保留对话中涉及的附件路径                             │
  │     │                                                 │ 正则提取 path:... 和            │                     │                                                      │
  │     │                                                 │ [attachment:...]                │                     │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 4   │ create_recent_files_attachment_if_needed        │ metadata["read_file_state"] →   │ recent_files        │ 列出最近读取过的文件及片段预览                       │
  │     │                                                 │ path, span, preview, timestamp  │                     │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 5   │ create_plan_attachment_if_needed                │ metadata["permission_mode"] ==  │ plan                │ 仅 plan 模式下生效，提醒模型仍在 plan                │
  │     │                                                 │ "plan" + plan_summary           │                     │ 模式，不要执行变更操作                               │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 6   │ create_invoked_skills_attachment_if_needed      │ metadata["invoked_skills"]      │ invoked_skills      │ 列出会话中调用过的 skills（如 debug、test）          │
  │     │                                                 │ (列表)                          │                     │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 7   │ create_async_agent_attachment_if_needed         │ metadata["async_agent_state"]   │ async_agents        │ 记录后台 agent 和异步任务的状态                      │
  │     │                                                 │ (列表)                          │                     │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 8   │ create_work_log_attachment_if_needed            │ metadata["recent_work_log"]     │ recent_work_log     │ 记录最近执行步骤和验证检查点                         │
  │     │                                                 │ (列表)                          │                     │                                                      │
  ├─────┼─────────────────────────────────────────────────┼─────────────────────────────────┼─────────────────────┼──────────────────────────────────────────────────────┤
  │ 9   │ _create_hook_attachments                        │ hook_note (字符串，来自 hook    │ hook_results        │ 将 hook 的返回 note 注入回对话                       │
  │     │                                                 │ 执行结果)                       │                     │                                                      │
  └─────┴─────────────────────────────────────────────────┴─────────────────────────────────┴─────────────────────┴──────────────────────────────────────────────────────┘

  所有这些 builder 最终通过 render_compact_attachment() 序列化为一个 ConversationMessage(role="user")
  消息，追加到压缩后消息列表的末尾。这样压缩后的对话里模型仍然能看到："你之前读过这些文件"、"你的当前目标是 X"、"这些工作已验证完成了"。

  对 mini_src 的结论

  8/9 依赖 OpenHarness
  领域状态（task_focus_state、read_file_state、invoked_skills、async_agent_state、recent_work_log、permission_mode、recent_verified_work、HookExecutor），这些在 mini_src
  中根本不存在——不是"暂时没有"而是设计上就没打算有。

  唯一可移植的是 _create_recent_attachments_attachment_if_needed（扫描旧消息找附件路径），但 mini_src 的 ImageBlock.source_path 是可选的、没有 [attachment:...]
  约定，移植了也只能匹配 path: 文本，价值不大。

  所以：全部跳过，不移植任何 attachment builder。

   在完整版 OpenHarness 中 hooks 的 4 种触发方式对应 4 种场景：

  ┌──────────┬──────────────────────────────────────────┬────────────────────────────────────────┐
  │ 触发方式 │                   示例                   │           mini_src 需要吗？            │
  ├──────────┼──────────────────────────────────────────┼────────────────────────────────────────┤
  │ command  │ 压缩前执行 git commit 检查工作区是否干净 │ 如果要当作工具用，可能有用             │
  ├──────────┼──────────────────────────────────────────┼────────────────────────────────────────┤
  │ http     │ 压缩前 POST 到监控系统记录状态           │ 对 mini_src 过于重量级                 │
  ├──────────┼──────────────────────────────────────────┼────────────────────────────────────────┤
  │ prompt   │ 让 LLM 判断是否应该压缩                  │ redundant — compact 已有自己的判断逻辑 │
  ├──────────┼──────────────────────────────────────────┼────────────────────────────────────────┤
  │ agent    │ 同上，但更深度推理                       │ redundant                              │
  └──────────┴──────────────────────────────────────────┴────────────────────────────────────────┘

  所以迁移 hooks 到 mini_src 后，compact 中调用的实际效果取决于用户是否配置了 hook——如果不配置任何 hook，HookExecutor.execute() 返回空结果，compact 行为不变。移植 hooks
  只是打开了扩展点，但默认没有任何副作用。