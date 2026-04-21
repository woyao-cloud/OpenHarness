# 第十七章：内存、服务与会话管理

## 概述

OpenHarness 的运行时由多个关键服务支撑：可观察的应用状态、持久化的项目记忆、上下文压缩、定时任务、会话存储以及结构化日志。这些服务共同构成了系统的"基础设施层"，确保长时间运行的 AI 会话不会因上下文溢出而崩溃，同时为 UI 提供响应式的数据绑定。

本章将深入解析以下模块：

- `state/store.py` — AppStateStore（观察者模式）
- `memory/` — 文件型记忆管理系统
- `services/compact/` — 上下文压缩（微压缩与 LLM 摘要）
- `services/token_estimation.py` — Token 估算
- `services/cron_scheduler.py` — 定时任务调度器
- `services/session_storage.py` — 会话快照持久化
- `services/log/` — 结构化日志包
- `utils/file_lock.py` — 独占文件锁
- `dataclasses.replace()` — 不可变状态更新

> **Java 对比**：如果你来自 Java 世界，可以将 AppStateStore 理解为 PropertyChangeSupport 的简化版，MemoryManager 类似于基于文件系统的 Preferences API，而 CronScheduler 则是 Quartz 调度器的轻量替代。

---

## 1. AppStateStore：观察者模式的状态容器

### 项目代码详解

`state/store.py` 实现了一个极简但实用的可观察状态容器：

```python
# state/store.py
from dataclasses import replace
from openharness.state.app_state import AppState

Listener = Callable[[AppState], None]

class AppStateStore:
    """Very small observable state store."""

    def __init__(self, initial_state: AppState) -> None:
        self._state = initial_state
        self._listeners: list[Listener] = []

    def get(self) -> AppState:
        """Return the current state snapshot."""
        return self._state

    def set(self, **updates) -> AppState:
        """Update the state and notify listeners."""
        self._state = replace(self._state, **updates)
        for listener in list(self._listeners):
            listener(self._state)
        return self._state

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a listener and return an unsubscribe callback."""
        self._listeners.append(listener)
        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return _unsubscribe
```

而 `AppState` 本身是一个纯粹的 `@dataclass`：

```python
# state/app_state.py
@dataclass
class AppState:
    """Shared mutable UI/session state."""
    model: str
    permission_mode: str
    theme: str
    cwd: str = "."
    provider: str = "unknown"
    auth_status: str = "missing"
    # ... 更多字段
    keybindings: dict[str, str] = field(default_factory=dict)
```

### Java 类比

> **Java 对比**：Java 中实现类似功能通常需要：
> - `PropertyChangeSupport` + `PropertyChangeListener`（java.beans 包）
> - 或 RxJava 的 `BehaviorSubject<AppState>`
> - 或 Spring 的 `ApplicationEventPublisher`
>
> Python 的实现简洁得多：`list[Listener]` + `for listener in list(self._listeners)` 即可完成通知。`subscribe()` 返回一个取消函数，这比 Java 的 `removePropertyChangeListener()` 更符合函数式风格。

### 不可变状态更新：dataclasses.replace()

关键设计：`set()` 方法使用 `dataclasses.replace(self._state, **updates)` 创建新实例，而非修改原对象：

```python
def set(self, **updates) -> AppState:
    self._state = replace(self._state, **updates)  # 创建新对象！
    for listener in list(self._listeners):
        listener(self._state)
    return self._state
```

> **Java 对比**：Java 中实现不可变更新通常需要 Builder 模式：
> ```java
> AppState newState = AppState.builder()
>     .from(existingState)
>     .model("claude-4")
>     .theme("dark")
>     .build();
> ```
> Python 的 `dataclasses.replace()` 等价于 `withBuilder().from().field(value).build()` 的一行代码版本，更加简洁。

---

## 2. MemoryManager：基于文件的持久记忆

### 项目代码详解

OpenHarness 的记忆系统由多个模块协作完成：

**`memory/types.py`** — 定义记忆文件的元数据：

```python
@dataclass(frozen=True)
class MemoryHeader:
    """Metadata for one memory file."""
    path: Path
    title: str
    description: str
    modified_at: float
    memory_type: str = ""
    body_preview: str = ""
```

注意 `frozen=True`，这使得 `MemoryHeader` 是不可变的——任何修改都需要创建新实例。

**`memory/paths.py`** — XDG 风格的路径解析：

```python
def get_project_memory_dir(cwd: str | Path) -> Path:
    """Return the persistent memory directory for a project."""
    path = Path(cwd).resolve()
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    memory_dir = get_data_dir() / "memory" / f"{path.name}-{digest}"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir
```

路径策略：将项目绝对路径做 SHA1 哈希后取前 12 位，与项目名组合作为子目录名。这避免了路径中的特殊字符问题，同时保持人类可读性。

**`memory/manager.py`** — 增删记忆条目：

```python
def add_memory_entry(cwd: str | Path, title: str, content: str) -> Path:
    """Create a memory file and append it to MEMORY.md."""
    memory_dir = get_project_memory_dir(cwd)
    slug = sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_") or "memory"
    path = memory_dir / f"{slug}.md"
    with exclusive_file_lock(_memory_lock_path(cwd)):
        atomic_write_text(path, content.strip() + "\n")
        # ... 更新 MEMORY.md 索引
    return path
```

注意 `exclusive_file_lock` 的使用——在多进程环境下，文件操作必须加锁以防止竞态条件。

**`memory/scan.py`** — 扫描并解析记忆文件：

```python
def scan_memory_files(cwd: str | Path, *, max_files: int = 50) -> list[MemoryHeader]:
    """Return memory headers sorted by newest first."""
    memory_dir = get_project_memory_dir(cwd)
    headers: list[MemoryHeader] = []
    for path in memory_dir.glob("*.md"):
        if path.name == "MEMORY.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        header = _parse_memory_file(path, text)
        headers.append(header)
    headers.sort(key=lambda item: item.modified_at, reverse=True)
    return headers[:max_files]
```

**`memory/search.py`** — 基于启发式的记忆搜索：

```python
def find_relevant_memories(query: str, cwd: str | Path, *, max_results: int = 5) -> list[MemoryHeader]:
    """Return the memory files whose metadata and content overlap the query."""
    tokens = _tokenize(query)
    # ... 元数据匹配权重 2x，正文匹配权重 1x
    scored.sort(key=lambda item: (-item[0], -item[1].modified_at))
    return [header for _, header in scored[:max_results]]

def _tokenize(text: str) -> set[str]:
    """Extract search tokens, handling ASCII and Han ideographs."""
    ascii_tokens = {t for t in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(t) >= 3}
    han_chars = set(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    return ascii_tokens | han_chars
```

> **Java 对比**：Java 中通常使用 `java.util.prefs.Preferences`（注册表/文件后端）或 SQLite 做持久配置。OpenHarness 选择纯 Markdown 文件——既人类可读又版本控制友好。`exclusive_file_lock` 对应 Java 的 `FileLock`/`ReentrantLock`。

---

## 3. 上下文压缩：Compact 服务

### 微压缩与 LLM 摘要

`services/compact/__init__.py` 实现了两级压缩策略：

1. **微压缩（Microcompact）**：清除旧工具结果内容，用占位符替代，零 LLM 调用成本
2. **完整压缩（Full Compact）**：调用 LLM 生成结构化摘要，保留关键信息

关键常量：

```python
COMPACTABLE_TOOLS: frozenset[str] = frozenset({
    "read_file", "bash", "grep", "glob", "web_search",
    "web_fetch", "edit_file", "write_file",
})

AUTOCOMPACT_BUFFER_TOKENS = 13_000
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000
```

> **Java 对比**：这类似于 Java 应用的日志轮转策略——微压缩类似 `LogRotation`（截断旧日志），LLM 摘要类似日志聚合服务（生成摘要报告）。

### Token 估算

```python
# services/token_estimation.py
def estimate_tokens(text: str) -> int:
    """Estimate tokens from plain text using a rough character heuristic."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
```

这是经典的"4 字符约等于 1 token"启发式算法。简单但实用——在生产环境中用于触发自动压缩的阈值判断。

---

## 4. CronScheduler：定时任务调度器

### 项目代码详解

`services/cron_scheduler.py` 实现了一个守护进程式的调度器：

```python
TICK_INTERVAL_SECONDS = 30

async def run_scheduler_loop(*, once: bool = False) -> None:
    """Main scheduler loop."""
    shutdown = asyncio.Event()

    def _on_signal() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    write_pid()
    try:
        while not shutdown.is_set():
            now = datetime.now(timezone.utc)
            jobs = load_cron_jobs()
            due = _jobs_due(jobs, now)
            if due:
                results = await asyncio.gather(
                    *(execute_job(job) for job in due), return_exceptions=True
                )
            if once:
                break
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=TICK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
    finally:
        remove_pid()
```

关键设计要点：
- 使用 `asyncio.Event` 作为优雅关闭信号
- `asyncio.gather()` 并发执行到期任务
- PID 文件机制防止重复启动
- 30 秒轮询间隔

> **Java 对比**：CronScheduler 对标 Java 的 Quartz 框架。但 OpenHarness 的实现要轻量得多——没有数据库持久化、没有集群支持，仅用 JSON 文件和 PID 文件。对于 CLI 工具来说，这已足够。Quartz 的 `JobDetail` + `Trigger` 模式被简化为 `load_cron_jobs()` + `_jobs_due()`。

---

## 5. SessionStorage：会话快照持久化

### 项目代码详解

`services/session_storage.py` 使用原子写入确保会话数据不会损坏：

```python
def save_session_snapshot(
    *,
    cwd: str | Path,
    model: str,
    system_prompt: str,
    messages: list[ConversationMessage],
    usage: UsageSnapshot,
    session_id: str | None = None,
    tool_metadata: dict[str, object] | None = None,
) -> Path:
    """Persist a session snapshot. Saves both by ID and as latest."""
    session_dir = get_project_session_dir(cwd)
    sid = session_id or uuid4().hex[:12]
    # ... 构造 payload
    data = json.dumps(payload, indent=2) + "\n"

    # Save as latest
    latest_path = session_dir / "latest.json"
    atomic_write_text(latest_path, data)

    # Save by session ID
    session_path = session_dir / f"session-{sid}.json"
    atomic_write_text(session_path, data)
    return latest_path
```

> **Java 对比**：Java 中通常使用 `ObjectOutputStream` 或 Jackson + 文件 I/O 做序列化。`atomic_write_text` 的"先写临时文件再重命名"模式对应 Java NIO 的 `Files.move(source, target, ATOMIC_MOVE)`。

---

## 6. 结构化日志包：services/log/

### 包架构

```
services/log/
  __init__.py        # 重新导出公共 API
  _shared.py         # 共享基础设施：请求计数、文件路径、verbose 开关
  prompt_logger.py    # LLM 请求/响应日志
  tool_logger.py      # 工具执行日志
  compact_logger.py   # 上下文压缩日志
  skill_logger.py     # 技能加载日志
```

**`_shared.py`** 提供线程安全的基础设施：

```python
_request_counter: int = 0
_counter_lock = threading.Lock()

def next_request_id() -> int:
    """Increment and return the global request counter (thread-safe)."""
    global _request_counter
    with _counter_lock:
        _request_counter += 1
        return _request_counter
```

**`__init__.py`** 使用选择性导出：

```python
from openharness.services.log._shared import (
    get_log_file_path, is_verbose, next_request_id,
    reset_session, set_verbose, truncate, write_to_debug_file,
)
from openharness.services.log.prompt_logger import (
    log_prompt_request, log_response_complete, log_response_event, log_simple,
)
# ...
__all__ = [
    "get_log_file_path", "is_verbose", "next_request_id",
    # ...
    "log_prompt_request", "log_response_complete",
    "log_tool_execution", "log_compact_event", "log_skill_load",
]
```

> **Java 对比**：Python 日志模块对应 Java 的 SLF4J/Logback。`_shared.py` 的 `next_request_id()` 用 `threading.Lock` 保护全局计数器，类似 Java 的 `AtomicInteger.incrementAndGet()`。`__init__.py` 的选择性导出模式类似 Java 的 `package-info.java` + 公共接口，但更灵活——可以直接从包级别导入子模块的函数。

---

## 7. exclusive_file_lock：跨平台文件锁

### 项目代码详解

`utils/file_lock.py` 实现了跨平台的独占文件锁：

```python
@contextmanager
def exclusive_file_lock(lock_path: Path, *, platform_name: PlatformName | None = None) -> Iterator[None]:
    """Acquire an exclusive file lock for the duration of the context."""
    resolved_platform = platform_name or get_platform()
    if resolved_platform == "windows":
        with _exclusive_windows_lock(lock_path):
            yield
        return
    if resolved_platform in {"macos", "linux", "wsl"}:
        with _exclusive_posix_lock(lock_path):
            yield
        return
    raise SwarmLockUnavailableError(...)

@contextmanager
def _exclusive_posix_lock(lock_path: Path) -> Iterator[None]:
    import fcntl
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UNLCK)

@contextmanager
def _exclusive_windows_lock(lock_path: Path) -> Iterator[None]:
    import msvcrt
    # ... msvcrt.locking 实现
```

> **Java 对比**：Java 中文件锁使用 `FileChannel.lock()` 或 `ReentrantLock`。Python 的 `@contextmanager` 装饰器将获取/释放资源的模式封装为 `with` 语句——这等价于 Java 7 的 `try-with-resources`，但更灵活（可用于非资源的场景）。

---

## 架构图

```
+-------------------+     +-------------------+
| AppStateStore     | --> |  Observers        |
| (subscribe/notify)|     |  (UI components)  |
+-------------------+     +-------------------+
         |
         v
+-------------------+     +-------------------+
| MemoryManager     |     | SessionStorage    |
| (CLAUDE.md files) |     | (JSON persistence)|
+-------------------+     +-------------------+
         |
         v
+-------------------+     +-------------------+
| CompactService    |     | CronScheduler     |
| (context mgmt)    |     | (background jobs) |
+-------------------+     +-------------------+
         |                         |
         v                         v
+-------------------+     +-------------------+
| token_estimation  |     | log/ package      |
| (4:1 heuristic)   |     | (_shared.py,      |
+-------------------+     |  prompt_logger,   |
                          |  tool_logger,     |
                          |  compact_logger,  |
                          |  skill_logger)    |
                          +-------------------+
                                   |
                                   v
                          +-------------------+
                          | exclusive_file_lock|
                          | (cross-platform)  |
                          +-------------------+
```

---

## 小结

本章涵盖了 OpenHarness 运行时的核心服务层：

| 模块 | 核心机制 | Java 等价物 |
|------|---------|------------|
| `AppStateStore` | 观察者模式 + 不可变更新 | PropertyChangeSupport / RxJava BehaviorSubject |
| `MemoryManager` | 文件型 Markdown 持久化 | java.util.prefs.Preferences |
| `CompactService` | 微压缩 + LLM 摘要 | 日志轮转 + 聚合 |
| `token_estimation` | 4:1 字符启发式 | 自定义 TokenCounter |
| `CronScheduler` | asyncio 事件循环 + PID | Quartz Scheduler |
| `SessionStorage` | JSON + 原子写入 | Jackson + Files.move(ATOMIC_MOVE) |
| `log/` 包 | 线程安全请求计数 + 双通道日志 | SLF4J/Logback |
| `exclusive_file_lock` | fcntl/msvcrt 跨平台锁 | FileChannel.lock() / ReentrantLock |

关键设计原则：
1. **不可变状态**：`dataclasses.replace()` 替代可变 setter
2. **原子写入**：所有文件操作使用 temp+fsync+rename 模式
3. **跨平台**：文件锁、路径处理均抽象了平台差异
4. **选择性导出**：`__init__.py` 的 `__all__` 控制公共 API 表面积
5. **双通道日志**：DEBUG 级别 Python logging + 可选的 verbose 详细文件