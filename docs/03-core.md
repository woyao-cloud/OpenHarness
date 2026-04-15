Phase 3 核心要点

  Agent Loop 的本质是一条 while True 循环, 每轮做 4 件事:

  ① auto-compact 检查 → ② API 流式调用 → ③ 工具执行(如有) → ④ 追加结果, 继续

  退出条件: 模型不再请求工具调用 (只有文字回复), 或达到 max_turns 上限。

  工具执行管道 (5 道关卡):
  PreToolUse Hook → 工具查找 → 输入验证(Pydantic) → 权限检查 → 执行 → PostToolUse Hook
  任何一道关卡失败, 都返回 is_error=True 的 ToolResultBlock, 而不是抛异常 — 保证对话历史的完整性。

  三个关键设计:
  1. 多工具并行 (asyncio.gather) + return_exceptions=True — 用户体验快, 且不会因单个工具失败导致缺少 tool_result
  2. Carryover 系统 (tool_metadata) — 上下文压缩后仍保留"读了什么文件、调了什么 Skill、当前目标"
  3. 双层压缩 — auto-compact (每轮检查) + reactive compact (API 报 prompt_too_long 时补救)