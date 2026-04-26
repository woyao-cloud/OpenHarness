# 第 6 章：记忆管理

## 6.1 解决的问题

LLM 的上下文窗口有限。记忆管理系统需要解决三个核心问题：

1. **跨会话持久化**：项目知识和经验在下一次会话中仍然可用
2. **Token 预算控制**：在有限的上下文窗口内保留最重要的信息
3. **信息检索**：快速找到与当前任务相关的历史知识

## 6.2 持久化项目记忆

### 6.2.1 存储结构

记忆存储在项目目录下的 `.claude/memory/` 中，使用**内容可寻址路径**：

```
项目目录/
  .claude/
    memory/
      a1b2c3d4e5f6/        ← SHA1(项目根路径) 的前 12 位作为目录名
        MEMORY.md           ← 索引文件（始终加载到上下文）
        user-profile.md     ← 单个记忆文件
        project-goals.md
        architecture.md
```

### 6.2.2 路径生成

`memory/paths.py`：

```python
def get_project_memory_dir(cwd: Path) -> Path:
    """基于项目根路径的 SHA1 哈希生成记忆目录路径。"""
    import hashlib
    root = find_project_root(cwd)
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
    return root / ".claude" / "memory" / digest

def get_memory_entrypoint(memory_dir: Path) -> Path:
    """返回 MEMORY.md 索引文件路径。"""
    return memory_dir / "MEMORY.md"
```

使用哈希路径的好处：
- 项目移动后记忆路径不变（基于项目根路径哈希）
- 避免特殊字符路径问题
- 目录名简短

### 6.2.3 记忆索引

`MEMORY.md` 是记忆的索引，每行一个条目：

```markdown
- [User Profile](user-profile.md) — User's tech stack and preferences
- [Project Goals](project-goals.md) — Current sprint objectives
- [Architecture](architecture.md) — System design decisions
```

### 6.2.4 记忆文件格式

每个记忆文件包含 YAML frontmatter + Markdown 正文：

```markdown
---
name: User Profile
description: User's tech stack and preferences
type: user
---

# User Profile

- Preferred language: Python
- Experienced with: FastAPI, React, PostgreSQL
```

### 6.2.5 CRUD 操作

`memory/manager.py`：

```python
def add_memory_entry(memory_dir, name, description, type, content):
    """创建新的记忆文件并更新索引。"""
    filename = slugify(name) + ".md"
    filepath = memory_dir / filename
    filepath.write_text(format_memory_file(name, description, type, content))
    _append_to_index(memory_dir / "MEMORY.md", name, description, filename)

def list_memory_files(memory_dir):
    """列出所有记忆文件（按修改时间排序）。"""
    return scan_memory_files(memory_dir)

def remove_memory_entry(memory_dir, filename):
    """删除记忆文件和索引条目。"""
    (memory_dir / filename).unlink()
    _remove_from_index(memory_dir / "MEMORY.md", filename)
```

### 6.2.6 关键词搜索

`memory/search.py`：

```python
def find_relevant_memories(memory_dir: Path, query: str) -> list[dict]:
    """关键词评分搜索：元数据权重 2x，正文权重 1x。
    
    支持：
    - ASCII token 匹配
    - Han 字形匹配（中文字符）
    """
    memories = scan_memory_files(memory_dir)
    scored = []
    for mem in memories:
        score = 0
        query_lower = query.lower()
        # 元数据匹配（2x 权重）
        if query_lower in mem.name.lower():
            score += 2
        if query_lower in mem.description.lower():
            score += 2
        # 正文匹配（1x 权重）
        if query_lower in mem.body_preview.lower():
            score += 1
        if score > 0:
            scored.append((score, mem))
    return [mem for _, mem in sorted(scored, key=lambda x: -x[0])]
```

### 6.2.7 记忆注入系统提示词

`memory/memdir.py` 中的 `load_memory_prompt()` 生成系统提示词的记忆部分：

```markdown
# Memory

## Index
- [User Profile](user-profile.md) — Tech stack: Python, FastAPI

## Relevant Memories
Content from user-profile.md:
- Preferred language: Python
- Experienced with: FastAPI, React, PostgreSQL
```

## 6.3 对话压缩

### 6.3.1 解决的问题

长时间对话消耗大量 Token。压缩系统在**不丢失关键上下文**的前提下减少 Token 消耗。

### 6.3.2 AutoCompactState

`services/compact/__init__.py`：

```python
class AutoCompactState:
    before_tokens: int | None = None
    after_tokens: int | None = None
    last_compact_time: float = 0
```

### 6.3.3 自动压缩触发

在 `run_query()` 的每次循环开始时触发（`query.py:480`）：

```python
async for event, usage in _stream_compaction(trigger="auto"):
    yield event, usage
messages, was_compacted = last_compaction_result
```

### 6.3.4 反应式压缩

当 API 返回 "prompt too long" 错误时，触发强制压缩（`query.py:535`）：

```python
if not reactive_compact_attempted and _is_prompt_too_long_error(exc):
    reactive_compact_attempted = True
    yield StatusEvent(message=REACTIVE_COMPACT_STATUS_MESSAGE)
    async for event, usage in _stream_compaction(trigger="reactive", force=True):
        yield event, usage
    messages, was_compacted = last_compaction_result
    if was_compacted:
        continue  # 压缩成功 → 重试
```

### 6.3.5 压缩策略

`services/compact/__init__.py` 实现了两级压缩：

1. **Microcompact（微压缩）**：清除旧的 tool_result 内容（无损、快速）
   - 保留最早的 N 条 tool_result
   - 清除中间 tool_result 的详细内容，保留摘要
   
2. **LLM 压缩**：使用模型生成消息摘要（有损、需要 API 调用）
   - 选择较旧的消息
   - 调用模型生成紧凑摘要
   - 用摘要替换原始消息

### 6.3.6 压缩事件

压缩过程产生 `CompactProgressEvent` 用于 UI 展示：

```python
@dataclass
class CompactProgressEvent:
    phase: Literal[
        "hooks_start", "context_collapse_start", "context_collapse_end",
        "session_memory_start", "session_memory_end",
        "compact_start", "compact_retry", "compact_end", "compact_failed",
    ]
    trigger: Literal["auto", "manual", "reactive"]
    message: str | None = None
```

## 6.4 Token 预算控制

### 6.4.1 Token 估算

`services/token_estimation.py`：

```python
def estimate_tokens(text: str) -> int:
    """粗略估算：len(text) // 4（英文约 4 字符/token）"""
    return len(text) // 4
```

这是一个简化估算。实际 API 调用时会使用模型的精确计数。

### 6.4.2 上下文窗口配置

```python
# 配置示例
context_window_tokens: 200000        # 模型的上下文窗口
auto_compact_threshold_tokens: 100000  # 达到此阈值触发自动压缩
```

### 6.4.3 预算分配

系统提示词的各部分对 Token 的消耗：

| 部分 | 大小 | 控制方式 |
|------|------|---------|
| 基础系统提示词 | ~2000 tokens | 固定 |
| CLAUDE.md | ~500-2000 tokens | 项目文件控制 |
| 记忆索引 | ~200 tokens | 自动 |
| 相关记忆 | ~500-2000 tokens | 搜索匹配 |
| 工具 Schema | ~1000-3000 tokens | 工具数量控制 |
| 对话历史 | 动态 | 自动压缩控制 |

## 6.5 关键源码路径

| 组件 | 文件 | 关键函数 |
|------|------|---------|
| 记忆目录路径 | `memory/paths.py` | `get_project_memory_dir()` |
| 记忆管理 | `memory/manager.py` | `add_memory_entry()` |
| 记忆搜索 | `memory/search.py` | `find_relevant_memories()` |
| 记忆注入 | `memory/memdir.py` | `load_memory_prompt()` |
| 记忆扫描 | `memory/scan.py` | `scan_memory_files()` |
| 对话压缩 | `services/compact/__init__.py` | `auto_compact_if_needed()` |
| Token 估算 | `services/token_estimation.py` | `estimate_tokens()` |
| 压缩触发 | `engine/query.py` | `_stream_compaction()` |

## 6.6 本章小结

记忆管理系统通过**三层架构**解决信息持久化问题：**文件级持久化**（项目记忆）提供跨会话知识，**对话压缩**管理 Token 预算，**关键词搜索**实现信息检索。三者协同工作，让 Agent 在长期交互中保持对上下文的理解。

> 下一章：[权限与安全控制](07-permissions-hooks.md) —— 多层权限模型与生命周期 Hook。
