# 第 15 章：服务与基础设施

## 15.1 解决的问题

OpenHarness 核心功能之外，有一组支持服务提供关键的辅助能力：
1. **Cron 调度**：定时执行任务
2. **LSP 集成**：代码符号搜索和引用查找
3. **日志系统**：工具调用、技能加载、压缩等行为的记录
4. **会话管理**：会话快照的持久化和恢复
5. **Token 估算**：粗略的 Token 计数
6. **输出样式**：自定义输出格式

## 15.2 Cron 调度

### 15.2.1 Cron 作业存储

`services/cron.py` 使用 croniter 解析和验证 cron 表达式：

```python
def validate_cron_expression(expr: str) -> bool:
    """验证 cron 表达式是否有效。"""
    try:
        croniter(expr)
        return True
    except (ValueError, KeyError):
        return False

def upsert_cron_job(name: str, expression: str, prompt: str) -> dict:
    """创建或更新 cron 作业。"""
    jobs = load_cron_jobs()
    jobs[name] = {
        "expression": expression,
        "prompt": prompt,
        "enabled": True,
        "last_run": None,
        "created_at": time.time(),
    }
    save_cron_jobs(jobs)
    return jobs[name]

def get_next_run(expression: str) -> float:
    """计算下一次执行的时间戳。"""
    cron = croniter(expression, time.time())
    return cron.get_next(float)
```

### 15.2.2 Cron 工具

系统提供了 5 个 cron 相关工具（注册在 `tools/` 中）：

| 工具 | 功能 |
|------|------|
| `CronCreate` | 创建定时任务（表达式 + 提示词） |
| `CronList` | 列出所有定时任务 |
| `CronDelete` | 删除定时任务 |
| `CronToggle` | 启用/禁用定时任务 |
| `RemoteTrigger` | 远程触发（HTTP webhook） |

## 15.3 LSP 集成

### 15.3.1 轻量级 Python LSP

`services/lsp/__init__.py` 提供了基于 Python AST 的轻量级语言服务器：

```python
def list_document_symbols(filepath: str) -> list[dict]:
    """列出文件中的符号（类、函数、变量）。"""
    with open(filepath) as f:
        tree = ast.parse(f.read())
    
    symbols = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            symbols.append({
                "kind": "function",
                "name": node.name,
                "line": node.lineno,
                "end_line": node.end_lineno,
            })
        elif isinstance(node, ast.ClassDef):
            symbols.append({
                "kind": "class",
                "name": node.name,
                "line": node.lineno,
            })
    return symbols

def workspace_symbol_search(query: str, root_dir: str) -> list[dict]:
    """在整个项目中搜索符号。"""
    results = []
    for pyfile in Path(root_dir).rglob("*.py"):
        try:
            symbols = list_document_symbols(str(pyfile))
            for sym in symbols:
                if query.lower() in sym["name"].lower():
                    results.append({**sym, "file": str(pyfile)})
        except SyntaxError:
            continue
    return results

def go_to_definition(filepath: str, line: int, column: int) -> dict | None:
    """跳转到符号定义。"""
    # 解析 AST 查找引用位置的定义
    ...

def find_references(filepath: str, line: int, column: int) -> list[dict]:
    """查找符号的所有引用。"""
    ...
```

### 15.3.2 LSP 工具

`tools/lsp_tool.py` 提供 LSP 查询工具：

- 列出文件的符号结构
- 工作区符号搜索
- 跳转到定义
- 查找引用

## 15.4 日志系统

### 15.4.1 结构化日志

`services/log/` 下的日志服务提供不同维度的记录：

```python
# tool_logger.py
def log_tool_execution(request_id, tool_name, tool_input, tool_output, is_error, duration_seconds):
    """记录工具执行日志。"""
    log.info(json.dumps({
        "type": "tool_execution",
        "request_id": request_id,
        "tool_name": tool_name,
        "tool_input": _sanitize(tool_input),
        "output_length": len(tool_output),
        "is_error": is_error,
        "duration_seconds": duration_seconds,
    }))

# compact_logger.py
def log_compact_event(request_id, trigger, phase, before_tokens, after_tokens, summary):
    """记录压缩事件日志。"""
    ...

# prompt_logger.py
def log_prompt_request(step_remark, model, max_tokens, system_prompt, messages, tool_registry, verbose):
    """记录 API 请求。返回 request_id。"""
    ...
```

### 15.4.2 请求追踪

`_shared.py` 中的共享函数：

```python
def set_verbose(verbose: bool) -> None:
    """设置全局详细日志模式。"""

def log_simple(step_remark: str, message: str) -> None:
    """简单的日志记录（用于调试）。"""
    if _verbose:
        log.info("[%s] %s", step_remark, message)
```

## 15.5 会话管理

### 15.5.1 SessionBackend 协议

`services/session_backend.py`：

```python
class SessionBackend(Protocol):
    """会话持久化的统一接口。"""
    
    def save_snapshot(self, cwd, model, system_prompt, messages, usage, session_id, tool_metadata): ...
    def load_latest(self) -> SessionSnapshot | None: ...
    def list_snapshots(self) -> list[SessionSnapshot]: ...
    def load_by_id(self, session_id: str) -> SessionSnapshot | None: ...
    def export_markdown(self, session_id: str) -> str: ...
```

### 15.5.2 SessionSnapshot

```python
@dataclass
class SessionSnapshot:
    id: str
    timestamp: float
    cwd: str
    model: str
    system_prompt: str
    messages: list[ConversationMessage]
    usage: UsageSnapshot
    tool_metadata: dict | None
```

### 15.5.3 OpenHarnessSessionBackend

JSON 文件存储实现：

```python
class OpenHarnessSessionBackend:
    def __init__(self, storage_dir=None):
        self._dir = storage_dir or get_data_dir() / "sessions"
        self._dir.mkdir(parents=True, exist_ok=True)
    
    def save_snapshot(self, **kwargs):
        """保存会话快照到 JSON 文件。"""
        snapshot = SessionSnapshot(
            id=kwargs["session_id"] or str(uuid.uuid4()),
            timestamp=time.time(),
            cwd=kwargs["cwd"],
            model=kwargs["model"],
            system_prompt=kwargs["system_prompt"],
            messages=kwargs["messages"],
            usage=kwargs["usage"],
            tool_metadata=kwargs["tool_metadata"],
        )
        path = self._dir / f"{snapshot.id}.json"
        path.write_text(json.dumps(asdict(snapshot), default=str))
        return snapshot
    
    def load_latest(self):
        """加载最新的会话快照。"""
        files = sorted(self._dir.glob("*.json"), key=os.path.getmtime)
        if not files:
            return None
        return self._load_file(files[-1])
```

### 15.5.4 会话生命周期

在 `handle_line()` 中，每次引擎调用后保存快照：

```python
bundle.session_backend.save_snapshot(
    cwd=bundle.cwd,
    model=bundle.engine.model,
    system_prompt=system_prompt,
    messages=bundle.engine.messages,
    usage=bundle.engine.total_usage,
    session_id=bundle.session_id,
    tool_metadata=bundle.engine.tool_metadata,
)
```

### 15.5.5 会话恢复

`/resume` 命令列出并恢复之前的会话：

```python
# 列出会话
snapshots = session_backend.list_snapshots()

# 恢复
snapshot = session_backend.load_by_id(session_id)
engine.load_messages(snapshot.messages)
```

### 15.5.6 ohmo 会话存储

`ohmo/session_storage.py` 中的 `OhmoSessionBackend` 支持按 session_key 分片：

```python
class OhmoSessionBackend(OpenHarnessSessionBackend):
    def __init__(self, workspace_root):
        storage_dir = workspace_root / "sessions"
        super().__init__(storage_dir)
    
    def save_snapshot(self, **kwargs):
        # 使用 session_key 作为文件名前缀
        session_key = kwargs.get("session_key", "default")
        kwargs["session_id"] = f"{session_key}_{uuid.uuid4()}"
        return super().save_snapshot(**kwargs)
```

## 15.6 Token 估算

`services/token_estimation.py`：

```python
def estimate_tokens(text: str) -> int:
    """粗略估算 Token 数量。
    
    这是一个简化的估算方法，用于压缩决策等场景。
    精确的 Token 计数由 API 返回的 usage 信息提供。
    """
    return len(text) // 4  # 英文约 4 字符/token
```

用于压缩触发决策和系统提示词组装时的 Token 预算管理。

## 15.7 输出样式

`output_styles/loader.py`：

```python
@dataclass
class OutputStyle:
    name: str       # 样式名称
    content: str    # Markdown 样式定义
    source: str     # "built-in" | "user"

BUILTIN_STYLES = {
    "default": OutputStyle(
        name="default",
        content="Use rich formatting with syntax highlighting.",
        source="built-in",
    ),
    "minimal": OutputStyle(
        name="minimal",
        content="Use minimal formatting, no syntax highlighting.",
        source="built-in",
    ),
    "codex": OutputStyle(
        name="codex",
        content="Compact output format for Codex-style terminals.",
        source="built-in",
    ),
}

def load_output_styles():
    """加载内置 + 用户自定义输出样式。"""
    styles = dict(BUILTIN_STYLES)
    user_dir = get_config_dir() / "output_styles"
    if user_dir.exists():
        for path in user_dir.glob("*.md"):
            style = _load_style_from_file(path)
            styles[style.name] = style
    return styles
```

## 15.8 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| Cron 作业 | `services/cron.py` | `upsert_cron_job()` |
| LSP | `services/lsp/__init__.py` | `list_document_symbols()` |
| 日志工具 | `services/log/tool_logger.py` | `log_tool_execution()` |
| 日志压缩 | `services/log/compact_logger.py` | `log_compact_event()` |
| 日志请求 | `services/log/prompt_logger.py` | `log_prompt_request()` |
| 会话后端 | `services/session_backend.py` | `SessionBackend` |
| 会话存储 | `services/session_storage.py` | OpenHarnessSessionBackend |
| Token 估算 | `services/token_estimation.py` | `estimate_tokens()` |
| 输出样式 | `output_styles/loader.py` | `OutputStyle`, `load_output_styles()` |

## 15.9 本章小结

支持服务是整个系统的"基础设施层"，它们在幕后支撑着核心功能的运行。Cron 作业实现了定时任务自动化，LSP 提供了代码智能，日志系统支持调试和监控，会话管理实现了持久化和恢复，Token 估算辅助了预算控制。

> 下一章：[附录：关键设计模式总结](appendix-patterns.md)
