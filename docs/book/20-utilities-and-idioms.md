# 第二十章：工具与 Python 惯用法

## 概述

最后一章聚焦 OpenHarness 中使用的 Python 惯用法和工具函数。这些横切关注点遍布整个代码库——原子文件写入、文件锁、平台检测、`__init__.py` 重导出模式等。理解这些细节，你就能读懂项目中任何模块的"潜台词"。

## 1. 原子文件写入

### 项目代码

**文件：** `src/openharness/utils/fs.py`

```python
def atomic_write_text(path: str | os.PathLike[str], data: str, *, encoding: str = "utf-8") -> None:
    """Write text content to a file atomically."""
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    target_mode = _resolve_target_mode(dst, mode)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{dst.name}.", suffix=".tmp", dir=str(dst.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        # Apply target mode, then atomic rename
        if target_mode is not None:
            os.chmod(tmp_path, target_mode)
        os.replace(tmp_path, dst)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes, *, mode: int | None = None) -> None:
    """Write bytes content to a file atomically."""
    # ... similar pattern
```

### Python 概念：原子写入的"三步曲"

原子写入是文件 I/O 的经典模式，Python 和 Java 的实现逻辑相同，但 Python 更简洁：

1. **创建临时文件** — `tempfile.mkstemp()` 在同一目录创建，保证 `os.replace()` 是同文件系统重命名
2. **写入 + 刷盘** — `flush()` + `fsync()` 确保数据落到磁盘
3. **原子替换** — `os.replace()` 在 POSIX 和 Windows 上都是原子操作

> **Java 对比**
>
> | Python | Java |
> |--------|------|
> | `tempfile.mkstemp(prefix, suffix, dir)` | `File.createTempFile(prefix, suffix, dir)` |
> | `os.fdopen(fd, "wb")` | `new FileOutputStream(fd)` |
> | `os.fsync(fileno)` | `fileChannel.force(true)` |
> | `os.replace(tmp, dst)` | `Files.move(tmp, dst, ATOMIC_MOVE)` |
> | `Path.unlink(missing_ok=True)` | `Files.deleteIfExists(path)` |
> | `Path.parent.mkdir(parents=True, exist_ok=True)` | `Files.createDirectories(dir)` |

### 为什么不能直接 `write_text()`？

项目文档解释得很清楚：如果进程在 `write_text()` 中途崩溃（SIGKILL、断电、磁盘满），磁盘上会留下截断文件。下次读取时要么得到空 JSON（`{}`），要么抛出 `JSONDecodeError`。原子写入保证读者只看到完整的旧版本或新版本。

## 2. 文件锁

**文件：** `src/openharness/utils/file_lock.py`

```python
import contextlib
import fcntl
import os
from pathlib import Path
from typing import Iterator

@contextmanager
def exclusive_file_lock(lock_path: Path) -> Iterator[int]:
    """Acquire an exclusive advisory lock for cross-process coordination."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
```

### Python 概念：`@contextmanager` 装饰器

`@contextmanager` 将普通生成器函数转换为上下文管理器，是 Python 中最优雅的资源管理模式之一：

- `yield` 之前的代码 = `__enter__`
- `yield` 的值 = `as` 变量
- `yield` 之后的代码 = `__exit__`（即使发生异常也会执行）
- 异常会自动从 `yield` 处传播到调用者

> **Java 对比**
>
> | Python | Java |
> |--------|------|
> | `@contextmanager` + `yield` | try-finally + Lock/Unlock |
> | `with exclusive_file_lock(path):` | `try { lock.lock(); } finally { lock.unlock(); }` |
> | `contextlib.suppress(OSError)` | `try { } catch (IOException ignored) { }` |
> | `pathlib.Path` | `java.nio.file.Path` |

## 3. 平台检测

**文件：** `src/openharness/platforms.py`

```python
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Mapping

PlatformName = Literal["macos", "linux", "windows", "wsl", "unknown"]

@dataclass(frozen=True)
class PlatformCapabilities:
    """Capabilities that drive shell, swarm, and sandbox decisions."""
    name: PlatformName
    supports_posix_shell: bool
    supports_native_windows_shell: bool
    supports_tmux: bool
    supports_swarm_mailbox: bool
    supports_sandbox_runtime: bool
    supports_docker_sandbox: bool

@lru_cache(maxsize=None)
def detect_platform(...) -> PlatformName:
    """Return the normalized platform name for the current process."""
    # ...
```

### Python 概念：`@lru_cache` 和 `Literal` 类型

1. **`@lru_cache(maxsize=None)`** — 无限制的最近最少使用缓存。Java 等价是 `@Cacheable` 或 `ConcurrentHashMap` + 计算函数。

2. **`Literal["macos", "linux", "windows", "wsl", "unknown"]`** — 轻量级枚举类型。与 `Enum` 不同，`Literal` 不需要定义类，直接在类型注解中使用。适用于值是简单字符串、不需要方法或行为的场景。

> **Java 对比**
>
> | Python | Java |
> |--------|------|
> | `@lru_cache(maxsize=None)` | `@Cacheable` / `ConcurrentHashMap.computeIfAbsent()` |
> | `PlatformName = Literal[...]` | `enum PlatformName` |
> | `@dataclass(frozen=True)` | Java `record` |
> | `platform.system()` | `System.getProperty("os.name")` |
> | `os.environ` | `System.getenv()` |

## 4. `__init__.py` 重导出模式

Python 包的 `__init__.py` 文件不仅标记目录为包，还控制公开 API 表面。OpenHarness 广泛使用重导出模式：

**文件：** `src/openharness/services/log/__init__.py`

```python
from openharness.services.log._shared import (
    get_log_file_path, is_verbose, next_request_id,
    reset_session, set_verbose, truncate, write_to_debug_file,
)
from openharness.services.log.prompt_logger import (
    PromptLogEntry, ResponseCompleteLogEntry, ResponseLogEntry,
    log_prompt_request, log_response_complete, log_response_event, log_simple,
)
from openharness.services.log.tool_logger import log_tool_execution
from openharness.services.log.compact_logger import log_compact_event
from openharness.services.log.skill_logger import log_skill_load

__all__ = [
    "get_log_file_path", "is_verbose", "next_request_id",
    # ... 20+ symbols
]
```

### 三种导出策略

| 策略 | 示例 | 效果 |
|------|------|------|
| **选择性重导出** | `from .module import ClassA, func_b` | 用户可 `from package import ClassA` |
| **`__all__` 白名单** | `__all__ = ["ClassA", "func_b"]` | `from package import *` 只导入这些 |
| **下划线私有** | `_shared.py`（前缀下划线） | 约定为内部模块，但 Python 不强制 |

> **Java 对比**
>
> | Python | Java |
> |--------|------|
> | `__init__.py` 重导出 | `package-info.java` / 公开 API |
> | `__all__` 白名单 | `module-info.java` 的 `exports` |
> | `_private.py` | Java `package-private` 访问控制 |
> | `from .module import X` | `import pkg.module.X`（Java 无等价，重导出是 Python 特有） |

## 5. `pathlib.Path` vs `os.path`

OpenHarness 全面采用 `pathlib.Path`，这是现代 Python 的推荐做法：

```python
# pathlib 风格（OpenHarness 使用）
path = Path.home() / ".openharness" / "settings.json"
path.parent.mkdir(parents=True, exist_ok=True)
content = path.read_text(encoding="utf-8")

# os.path 风格（传统）
import os
path = os.path.join(os.path.expanduser("~"), ".openharness", "settings.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
```

`pathlib.Path` 的优势：
- **`/` 运算符拼接路径** — 比 `os.path.join()` 更直观
- **链式方法调用** — `path.parent.mkdir(parents=True, exist_ok=True)` 比 `os.makedirs()` 更流畅
- **面向对象** — 路径是对象，不是字符串
- **类型安全** — 函数签名可以区分 `str | Path` vs 纯字符串

> **Java 对比**
>
> | Python `pathlib.Path` | Java `java.nio.file.Path` |
> |----------------------|--------------------------|
> | `Path.home()` | `Path.of(System.getProperty("user.home"))` |
> | `path / "file.txt"` | `path.resolve("file.txt")` |
> | `path.read_text()` | `Files.readString(path)` |
> | `path.parent.mkdir(parents=True)` | `Files.createDirectories(path.getParent())` |
> | `path.exists()` | `Files.exists(path)` |
> | `path.glob("*.md")` | `Files.newDirectoryStream(path, "*.md")` |

## 6. 其他惯用法

### `contextlib.suppress` — 静默忽略异常

```python
from contextlib import suppress

# Python
with suppress(FileNotFoundError):
    path.unlink()

# Java 等价
try { Files.deleteIfExists(path); } catch (NoSuchFileException ignored) {}
```

### 模块级常量与 `frozenset`

```python
# Python: 模块级常量
MAX_RETRIES = 3
BASE_DELAY = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Java 等价
public static final int MAX_RETRIES = 3;
public static final double BASE_DELAY = 1.0;
public static final Set<Integer> RETRYABLE_STATUS_CODES = Set.of(429, 500, 502, 503, 529);
```

Python 的模块级常量不需要 `static final` 修饰符——按约定，全大写的变量名就是常量。

### 类型别名

```python
# Python
PermissionPrompt = Callable[[str, str], Awaitable[bool]]
PaneId = str

# Java 等价（无法直接等价，需要接口）
@FunctionalInterface
interface PermissionPrompt {
    CompletableFuture<Boolean> apply(String a, String b);
}
// PaneId 没有等价物，Java 不支持类型别名
```

### `from __future__ import annotations`

几乎所有 OpenHarness 模块的第一行都是：

```python
from __future__ import annotations
```

这启用了 PEP 604 语法（`X | Y` 联合类型）和延迟注解求值，使得前向引用无需引号包裹。在 Python 3.10+ 中这是默认行为，但项目使用它来保持 3.9 兼容性。

## 小结

| Python 惯用法 | 项目示例 | Java 等价 |
|-------------|---------|----------|
| 原子写入 | `atomic_write_text()` | `Files.write()` + `ATOMIC_MOVE` |
| `@contextmanager` | `exclusive_file_lock()` | try-finally + Lock |
| `contextlib.suppress` | `with suppress(OSError):` | `catch (IOException ignored) {}` |
| `pathlib.Path` | 全项目使用 | `java.nio.file.Path` |
| `__init__.py` 重导出 | `services/log/__init__.py` | `package-info.java` |
| `@lru_cache` | `detect_platform()` | `@Cacheable` / memoization |
| `Literal["a", "b"]` | `PlatformName`, `BackendType` | Java `enum` |
| 模块级常量 | `MAX_RETRIES = 3` | `public static final int` |
| `X \| Y` 联合类型 | `str \| None`, `Path \| None` | `Optional<String>`, `@Nullable` |
| `from __future__ import annotations` | 全项目 | 无需（Java 天然支持前向引用） |

### 思考题

1. `atomic_write_text()` 为什么要在同一目录创建临时文件？如果临时文件在不同文件系统会怎样？
2. `contextlib.suppress()` 和 `try: ... except: pass` 有什么区别？哪种更 Pythonic？
3. 为什么 `__init__.py` 中用 `_shared.py` 而不是 `shared.py`？这种命名约定有什么好处？

---

> **全书结语**
>
> 恭喜你读完了这本 OpenHarness 源码解读！我们从最简单的入口点和数据模型开始，一路深入到异步编程、多智能体协作、运行时装配和底层惯用法。
>
> 回顾一下关键对比：
> - Python `BaseModel` ≈ Java POJO + Jackson + Bean Validation
> - Python `Protocol` ≈ Java `interface`（但是结构化子类型）
> - Python `@dataclass(frozen=True)` ≈ Java `record`
> - Python `async/await` ≈ Java `CompletableFuture` / virtual threads
> - Python `with` 语句 ≈ Java try-with-resources
> - Python `__init__.py` 重导出 ≈ Java `module-info.java`
>
> 最重要的区别不是语法，而是**哲学**：Python 追求简洁和显式，Java 追求安全和显式声明。理解了这个哲学差异，你就能在两个语言之间自如切换。