# OpenHarness 源码解读：从 Java 到 Python 的实战转型 — 索引

## 目录

| 章节 | 标题 | 涵盖模块 | 核心 Python 概念 |
|------|------|----------|------------------|
| 00 | [前言与阅读指南](00-preface.md) | 项目概览、pyproject.toml | venv、pip、项目结构 |
| 01 | [入口与 CLI](01-entry-points.md) | `__main__.py`, `cli.py` | `if __name__=="__main__"`, Typer |
| 02 | [数据模型：Pydantic](02-data-models-pydantic.md) | `config/schema.py`, `config/settings.py`, `engine/messages.py` | BaseModel, Field, validators |
| 03 | [数据类：@dataclass](03-dataclasses.md) | `api/provider.py`, `api/client.py`, `hooks/types.py`, `swarm/types.py` | frozen=True, Union types, field |
| 04 | [结构化子类型：Protocol](04-protocols.md) | `api/client.py`, `swarm/types.py`, `ui/protocol.py` | Protocol, @runtime_checkable |
| 05 | [抽象基类：ABC](05-abc-and-inheritance.md) | `tools/base.py`, `channels/impl/base.py`, `auth/flows.py` | ABC, @abstractmethod |
| 06 | [枚举与字面量类型](06-enums-and-literals.md) | `permissions/modes.py`, `swarm/types.py`, `hooks/schemas.py` | Enum, Literal, frozenset |
| 07 | [工具系统](07-tool-system.md) | `tools/` (40+ tools) | ABC 子类化, Pydantic 输入 schema |
| 08 | [异步编程](08-async-await.md) | `api/client.py`, `channels/bus/`, `channels/adapter.py` | async/await, asyncio.Queue |
| 09 | [配置系统](09-config-system.md) | `config/settings.py`, `config/schema.py`, `utils/fs.py` | Pydantic 组合, 原子写入 |
| 10 | [认证系统](10-auth-system.md) | `auth/flows.py`, `auth/manager.py`, `auth/storage.py` | Strategy 模式, OAuth |
| 11 | [引擎核心](11-engine-core.md) | `engine/query.py`, `engine/messages.py`, `engine/stream_events.py` | AsyncIterator, 流式架构 |
| 12 | [多提供商 API 抽象](12-api-providers.md) | `api/client.py`, `api/registry.py`, `api/provider.py` | frozen dataclass 注册表, Protocol |
| 13 | [渠道系统](13-channels.md) | `channels/bus/`, `channels/adapter.py`, `channels/impl/` | Bus/Adapter, asyncio.Queue |
| 14 | [钩子与事件](14-hooks-and-events.md) | `hooks/` | Pydantic 判别联合, 热重载 |
| 15 | [插件、技能与 MCP](15-plugins-skills-mcp.md) | `plugins/`, `skills/`, `mcp/` | 插件发现, 动态加载 |
| 16 | [权限与沙箱](16-permissions-and-sandbox.md) | `permissions/`, `sandbox/` | Enum 模式, 子进程包装 |
| 17 | [记忆与服务](17-memory-and-services.md) | `memory/`, `services/`, `state/` | 观察者模式, 原子写入, cron |
| 18 | [多智能体协作](18-swarm-and-coordinator.md) | `swarm/`, `coordinator/`, `bridge/` | Protocol, 文件邮箱, asyncio.subprocess |
| 19 | [UI 层与运行时装配](19-ui-and-runtime.md) | `ui/`, `themes/`, `keybindings/` | Callable 类型, 组合模式 |
| 20 | [工具与惯用法](20-utilities-and-idioms.md) | `utils/`, `platforms.py`, `__init__.py` | 原子写入, pathlib, contextlib |

---

## Python → Java 概念对照表

| Python 概念 | Java 等价 | 本书章节 |
|-------------|-----------|---------|
| `class` | `class` | 02, 05 |
| Pydantic `BaseModel` | POJO + Jackson + Bean Validation | 02, 09 |
| `@dataclass(frozen=True)` | Java `record` | 03 |
| `@dataclass` | Java POJO (Lombok `@Data`) | 03 |
| `Protocol` (structural subtyping) | Java `interface` (nominal subtyping) | 04 |
| `ABC` + `@abstractmethod` | Java `abstract class` + `abstract method` | 05 |
| `Enum` (str, Enum) | Java `enum` | 06 |
| `Literal["a", "b"]` | Java `enum` (简单枚举) | 06 |
| `frozenset[str]` | Java `Set.of()` | 06 |
| `async def` / `await` | Java `CompletableFuture` / virtual threads | 08 |
| `AsyncIterator` | Java `Flux<T>` / `Stream<T>` | 08, 11 |
| `asyncio.Queue` | Java `BlockingQueue<T>` | 08, 13 |
| `@contextmanager` / `with` | Java try-with-resources | 17, 20 |
| `contextlib.suppress` | Java `catch (Exception ignored) {}` | 20 |
| `pathlib.Path` | Java `java.nio.file.Path` | 20 |
| `dict[str, Any]` | Java `Map<String, Object>` | 07 |
| `list[str]` | Java `List<String>` | 02 |
| `X \| Y` 联合类型 | Java `sealed interface X permits Y, Z` | 03 |
| `Optional[X]` / `X \| None` | Java `Optional<X>` / `@Nullable` | 02, 09 |
| `Callable[[X, Y], Z]` | Java `@FunctionalInterface` / `BiFunction<X, Y, Z>` | 19 |
| `@property` | Java getter 方法 | 02, 09 |
| `field(default_factory=list)` | Java `new ArrayList<>()` 字段初始化 | 02, 03 |
| `model_copy(update={})` | Java Builder 模式 | 02 |
| `model_validate()` | Jackson `ObjectMapper.readValue()` | 02, 09 |
| `__init__.py` 重导出 | Java `package-info.java` / `module-info.java` | 17, 20 |
| `__all__` 白名单 | Java `module-info.java` `exports` | 20 |
| `_private.py` 前缀 | Java `package-private` 访问控制 | 20 |
| `from __future__ import annotations` | 无需（Java 天然支持前向引用） | 20 |
| `@lru_cache` | Spring `@Cacheable` | 20 |
| 模块级常量 `MAX_RETRIES = 3` | Java `public static final int MAX_RETRIES = 3` | 20 |
| `os.replace()` 原子重命名 | Java `Files.move(path, ATOMIC_MOVE)` | 20 |
| `threading.Lock()` | Java `ReentrantLock` / `synchronized` | 17 |
| `@dataclass` `replace()` | Java 不可变 Builder | 17 |
| `logging` 模块 | SLF4J + Logback | 17 |

---

## Java → Python 概念对照表

| Java 概念 | Python 等价 | 本书章节 |
|-----------|------------|---------|
| `public static void main(String[] args)` | `if __name__ == "__main__"` | 01 |
| `interface` / `implements` | `Protocol` (无需声明 implements) | 04 |
| `abstract class` / `abstract method` | `ABC` + `@abstractmethod` | 05 |
| `enum` | `Enum(str, Enum)` 或 `Literal[...]` | 06 |
| `record` / `@Value` (Lombok) | `@dataclass(frozen=True)` | 03 |
| `@Data` (Lombok) | `@dataclass` | 03 |
| POJO + Jackson + Validation | Pydantic `BaseModel` | 02 |
| `CompletableFuture<T>` | `async def` / `Awaitable[T]` | 08 |
| `Flux<T>` / `Stream<T>` | `AsyncIterator[T]` | 08, 11 |
| `BlockingQueue<T>` | `asyncio.Queue[T]` | 08, 13 |
| `try-with-resources` | `with` 语句 | 17, 20 |
| `catch (Exception ignored) {}` | `contextlib.suppress(Exception)` | 20 |
| `java.nio.file.Path` | `pathlib.Path` | 20 |
| `Map<String, Object>` | `dict[str, Any]` | 07 |
| `List<String>` | `list[str]` | 02 |
| `sealed interface` | `X \| Y` 联合类型 | 03 |
| `Optional<T>` | `T \| None` 或 `Optional[T]` | 02, 09 |
| `@FunctionalInterface` | `Callable[[X, Y], Z]` 类型别名 | 19 |
| getter 方法 | `@property` 装饰器 | 02 |
| Builder 模式 | `model_copy(update={})` | 02 |
| Jackson `ObjectMapper` | Pydantic `model_validate()` | 02, 09 |
| `package-info.java` | `__init__.py` 重导出 | 17, 20 |
| `module-info.java` `exports` | `__all__` 白名单 | 20 |
| package-private | `_private.py` 前缀 | 20 |
| Spring `@Configuration` + `@Bean` | `build_runtime()` 组装函数 | 19 |
| Spring `@Component` + `@Autowired` | 字典注册表 (ToolRegistry) | 05, 07 |
| Spring `@Cacheable` | `@lru_cache` | 20 |
| Spring `@PropertySource` | `load_settings()` 优先级链 | 09 |
| Quartz Scheduler | `croniter` + `threading` | 17 |
| SLF4J + Logback | Python `logging` 模块 | 17 |
| `System.getProperty("os.name")` | `platform.system()` | 20 |
| `Files.writeString()` | `atomic_write_text()` (temp+fsync+rename) | 20 |
| `Files.move(path, ATOMIC_MOVE)` | `os.replace()` | 20 |
| `ReentrantLock` | `threading.Lock()` | 17 |
| `PropertyChangeSupport` | `AppStateStore` 观察者 | 17 |
| `ServiceLoader<S>` | 插件发现 + `importlib` | 15 |
| `ProcessBuilder` | `asyncio.create_subprocess_exec()` | 18 |
| JMS Message Queue | 文件型 Mailbox | 18 |
| `FileChannel.lock()` | `fcntl.flock()` | 17, 20 |

---

## 源文件索引

| 模块 | 章节 |
|------|------|
| `__main__.py` | 01 |
| `cli.py` | 01 |
| `api/client.py` | 04, 08, 12 |
| `api/registry.py` | 06, 12 |
| `api/provider.py` | 03, 12 |
| `api/errors.py` | 05, 12 |
| `api/copilot_client.py` | 10, 12 |
| `api/codex_client.py` | 12 |
| `api/openai_client.py` | 12 |
| `api/usage.py` | 02 |
| `auth/flows.py` | 05, 10 |
| `auth/manager.py` | 10 |
| `auth/storage.py` | 10 |
| `auth/external.py` | 10 |
| `bridge/` | 18 |
| `channels/bus/queue.py` | 08, 13 |
| `channels/bus/events.py` | 03, 13 |
| `channels/adapter.py` | 08, 13 |
| `channels/impl/base.py` | 05, 13 |
| `channels/impl/manager.py` | 13 |
| `config/schema.py` | 02, 09 |
| `config/settings.py` | 02, 06, 09, 16 |
| `config/paths.py` | 09 |
| `coordinator/agent_definitions.py` | 06, 18 |
| `coordinator/coordinator_mode.py` | 18 |
| `engine/query.py` | 11 |
| `engine/messages.py` | 02, 11 |
| `engine/stream_events.py` | 03, 11 |
| `engine/cost_tracker.py` | 11 |
| `hooks/schemas.py` | 06, 14 |
| `hooks/types.py` | 03, 14 |
| `hooks/executor.py` | 14 |
| `hooks/hot_reload.py` | 14 |
| `keybindings/` | 19 |
| `mcp/types.py` | 06, 15 |
| `mcp/client.py` | 15 |
| `memory/manager.py` | 17 |
| `memory/types.py` | 17 |
| `permissions/modes.py` | 06, 16 |
| `permissions/checker.py` | 16 |
| `platforms.py` | 20 |
| `plugins/schemas.py` | 15 |
| `plugins/types.py` | 15 |
| `plugins/loader.py` | 15 |
| `services/log/` | 17, 20 |
| `services/compact/` | 17 |
| `services/cron_scheduler.py` | 17 |
| `services/session_storage.py` | 17 |
| `state/store.py` | 17 |
| `swarm/types.py` | 04, 06, 18 |
| `swarm/mailbox.py` | 08, 18 |
| `swarm/registry.py` | 18 |
| `swarm/subprocess_backend.py` | 18 |
| `swarm/in_process.py` | 18 |
| `tools/base.py` | 05, 07 |
| `tools/__init__.py` | 07 |
| `tools/bash_tool.py` | 07 |
| `ui/runtime.py` | 19 |
| `ui/protocol.py` | 04, 19 |
| `utils/fs.py` | 09, 20 |
| `utils/file_lock.py` | 17, 20 |
| `utils/shell.py` | 20 |

---

## Python 术语速查（面向 Java 开发者）

| Python 术语 | 含义 | Java 近似 |
|------------|------|----------|
| `venv` | 虚拟环境，隔离依赖 | Maven scope (不完全等价) |
| `pip` | 包管理器 | Maven / Gradle |
| `pyproject.toml` | 项目配置 | `pom.xml` / `build.gradle` |
| `__init__.py` | 包标记和导出 | `package-info.java` |
| `__main__.py` | 模块入口 | `public static void main` |
| `__all__` | 公开 API 白名单 | `module-info.java` `exports` |
| `from __future__ import annotations` | 启用延迟注解求值 | 无需（Java 天然支持） |
| `pip install -e ".[dev]"` | 可编辑模式安装 | Maven `mvn install` |
| `pytest` | 测试框架 | JUnit |
| `mypy` | 静态类型检查 | javac (编译时检查) |
| `ruff` | 代码格式化 + lint | Checkstyle + Spotless |
| `dataclass` | 数据类注解 | Lombok `@Data` / Java `record` |
| `BaseModel` (Pydantic) | 带验证的数据模型 | POJO + Jackson + Bean Validation |
| `Protocol` | 结构化子类型 | Java `interface` |
| `ABC` | 抽象基类 | Java `abstract class` |
| `Literal` | 字面量类型 | Java `enum` (简单) |
| `frozenset` | 不可变集合 | Java `Set.of()` |
| `asyncio` | 异步事件循环 | Java NIO / virtual threads |
| `with` 语句 | 上下文管理器 | try-with-resources |
| `@contextmanager` | 上下文管理器装饰器 | 手写 `__enter__`/`__exit__` |
| `pathlib.Path` | 面向对象路径 | `java.nio.file.Path` |
| `os.replace()` | 原子重命名 | `Files.move(path, ATOMIC_MOVE)` |
| `@lru_cache` | 最近最少使用缓存 | Spring `@Cacheable` |