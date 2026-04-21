# 第十六章：权限与沙箱 —— 模式化访问控制与隔离执行

## 概述

当 AI Agent 拥有执行 shell 命令、读写文件、访问网络的能力时，权限控制和执行隔离就成了安全的关键防线。OpenHarness 的权限系统基于「模式」（Mode）——`DEFAULT`、`PLAN`、`FULL_AUTO` 三种模式决定了 Agent 的操作边界。沙箱系统则提供了两种隔离后端：`srt`（sandbox-runtime）和 Docker，确保不可信代码在受限环境中执行。

本章将详细解析 PermissionMode 枚举、PermissionChecker 的规则评估、PathValidator 的路径验证、SandboxAvailability 的平台检测，以及 DockerSandboxSession 的容器隔离机制。

## Java 类比

> **Java 对比**：`PermissionMode(str, Enum)` 等价于 Java 的 `enum PermissionMode { DEFAULT, PLAN, FULL_AUTO }`，但 Python 的 `str, Enum` 继承让枚举值可以直接当字符串比较。`PermissionDecision(frozen=True)` 类似于 Java 14+ 的 `record`——不可变数据载体。`PermissionChecker` 的规则评估逻辑类似于 Spring Security 的 `AccessDecisionManager`——多个投票器（路径规则、工具白名单、模式检查）按优先级依次评估。`SandboxAdapter` 包装 `srt` CLI 类似于 Java 的 `ProcessBuilder`，但 Python 的 `asyncio.create_subprocess_exec` 是异步的。`shutil.which()` 等价于手动遍历 `PATH` 搜索可执行文件。

## 项目代码详解

### PermissionMode：模式化权限控制

位于 `permissions/modes.py`：

```python
from enum import Enum


class PermissionMode(str, Enum):
    """Supported permission modes."""

    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"
```

三种模式的语义：

| 模式 | 读取操作 | 写入操作 | 说明 |
|------|---------|---------|------|
| `DEFAULT` | 自动允许 | 需要确认 | 默认安全模式，修改操作需用户明确批准 |
| `PLAN` | 自动允许 | 完全拒绝 | 规划模式，Agent 只能读不能写，用于分析和规划 |
| `FULL_AUTO` | 自动允许 | 自动允许 | 全自动模式，所有操作自动放行，信任 Agent |

> **Java 对比**：Java 的 `enum` 是一等公民类型，有构造函数、方法和字段。Python 的 `str, Enum` 继承更轻量——枚举值可以直接与字符串比较，在 JSON 序列化时自动转为字符串值，无需额外的 `@JsonValue` 注解：

```python
PermissionMode.DEFAULT == "default"   # True，可直接当字符串用
```

Java 中则需要 `PermissionMode.DEFAULT.name().equals("default")` 或 `@JsonValue` 注解。

### PermissionChecker：规则评估引擎

位于 `permissions/checker.py`，是权限系统的核心：

```python
@dataclass(frozen=True)
class PermissionDecision:
    """Result of checking whether a tool invocation may run."""
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PathRule:
    """A glob-based path permission rule."""
    pattern: str
    allow: bool  # True = allow, False = deny


class PermissionChecker:
    """Evaluate tool usage against the configured permission mode and rules."""

    def __init__(self, settings: PermissionSettings) -> None:
        self._settings = settings
        self._path_rules: list[PathRule] = []
        for rule in getattr(settings, "path_rules", []):
            pattern = getattr(rule, "pattern", None) or (rule.get("pattern") if isinstance(rule, dict) else None)
            allow = getattr(rule, "allow", True) if not isinstance(rule, dict) else rule.get("allow", True)
            if isinstance(pattern, str) and pattern.strip():
                self._path_rules.append(PathRule(pattern=pattern.strip(), allow=allow))
```

`PermissionChecker.evaluate()` 方法实现了多层检查逻辑：

```python
def evaluate(self, tool_name, *, is_read_only, file_path=None, command=None):
    # 1. 内置敏感路径保护（始终生效）
    if file_path:
        for pattern in SENSITIVE_PATH_PATTERNS:
            if fnmatch.fnmatch(candidate_path, pattern):
                return PermissionDecision(allowed=False, reason="Access denied: sensitive credential path")

    # 2. 工具黑名单
    if tool_name in self._settings.denied_tools:
        return PermissionDecision(allowed=False, reason=f"{tool_name} is explicitly denied")

    # 3. 工具白名单
    if tool_name in self._settings.allowed_tools:
        return PermissionDecision(allowed=True, reason=f"{tool_name} is explicitly allowed")

    # 4. 路径规则检查
    if file_path and self._path_rules:
        for rule in self._path_rules:
            if fnmatch.fnmatch(candidate_path, rule.pattern):
                if not rule.allow:
                    return PermissionDecision(allowed=False, ...)

    # 5. 命令拒绝模式
    if command:
        for pattern in self._settings.denied_commands:
            if fnmatch.fnmatch(command, pattern):
                return PermissionDecision(allowed=False, ...)

    # 6. FULL_AUTO 模式
    if self._settings.mode == PermissionMode.FULL_AUTO:
        return PermissionDecision(allowed=True, reason="Auto mode allows all tools")

    # 7. 只读工具始终允许
    if is_read_only:
        return PermissionDecision(allowed=True, reason="read-only tools are allowed")

    # 8. PLAN 模式阻止修改
    if self._settings.mode == PermissionMode.PLAN:
        return PermissionDecision(allowed=False, reason="Plan mode blocks mutating tools")

    # 9. DEFAULT 模式需要确认
    return PermissionDecision(allowed=False, requires_confirmation=True, ...)
```

**评估优先级**（从高到低）：
1. 内置敏感路径保护（不可覆盖）
2. 工具黑名单（显式拒绝）
3. 工具白名单（显式允许）
4. 路径规则（fnmatch glob 匹配）
5. 命令拒绝模式
6. 权限模式决定（FULL_AUTO > 只读 > PLAN > DEFAULT）

> **Java 对比**：这个多层评估逻辑类似于 Spring Security 的 `AccessDecisionManager`，它使用多个 `AccessDecisionVoter` 按优先级投票。内置敏感路径保护等价于 Spring Security 的 `FilterChainProxy` 中最先执行的 `SecurityFilter`——不可被后续规则覆盖。

### SENSITIVE_PATH_PATTERNS：内置安全防护

```python
SENSITIVE_PATH_PATTERNS: tuple[str, ...] = (
    "*/.ssh/*",                        # SSH 密钥
    "*/.aws/credentials",               # AWS 凭证
    "*/.aws/config",                    # AWS 配置
    "*/.config/gcloud/*",               # GCP 凭证
    "*/.azure/*",                       # Azure 凭证
    "*/.gnupg/*",                       # GPG 密钥
    "*/.docker/config.json",            # Docker 凭证
    "*/.kube/config",                   # Kubernetes 凭证
    "*/.openharness/credentials.json",  # OpenHarness 凭证
    "*/.openharness/copilot_auth.json",  # Copilot 认证
)
```

这些模式使用 `fnmatch` 语法，始终生效，即使用户设置 `FULL_AUTO` 模式也不能绕过。这是一个「纵深防御」（defence-in-depth）措施，防止 LLM 被 prompt injection 诱导读取凭证文件。

### SandboxSettings：沙箱配置

位于 `config/settings.py`：

```python
class SandboxNetworkSettings(BaseModel):
    """OS-level network restrictions passed to sandbox-runtime."""
    allowed_domains: list[str] = Field(default_factory=list)
    denied_domains: list[str] = Field(default_factory=list)


class SandboxFilesystemSettings(BaseModel):
    """OS-level filesystem restrictions passed to sandbox-runtime."""
    allow_read: list[str] = Field(default_factory=list)
    deny_read: list[str] = Field(default_factory=list)
    allow_write: list[str] = Field(default_factory=lambda: ["."])
    deny_write: list[str] = Field(default_factory=list)


class DockerSandboxSettings(BaseModel):
    """Docker-specific sandbox configuration."""
    image: str = "openharness-sandbox:latest"
    auto_build_image: bool = True
    cpu_limit: float = 0.0
    memory_limit: str = ""
    extra_mounts: list[str] = Field(default_factory=list)
    extra_env: dict[str, str] = Field(default_factory=dict)


class SandboxSettings(BaseModel):
    """Sandbox-runtime integration settings."""
    enabled: bool = False
    backend: str = "srt"        # "srt" 或 "docker"
    fail_if_unavailable: bool = False
    enabled_platforms: list[str] = Field(default_factory=list)
    network: SandboxNetworkSettings = Field(default_factory=SandboxNetworkSettings)
    filesystem: SandboxFilesystemSettings = Field(default_factory=SandboxFilesystemSettings)
    docker: DockerSandboxSettings = Field(default_factory=DockerSandboxSettings)
```

关键配置项：
- `enabled`：是否启用沙箱（默认关闭）
- `backend`：选择 `srt`（sandbox-runtime）或 `docker` 后端
- `fail_if_unavailable`：沙箱不可用时是否报错（默认降级为无沙箱执行）
- `network`：网络域名白名单/黑名单
- `filesystem`：文件系统读写权限控制

### SandboxAvailability：平台检测

位于 `sandbox/adapter.py`：

```python
@dataclass(frozen=True)
class SandboxAvailability:
    """Computed sandbox-runtime availability for the current environment."""
    enabled: bool
    available: bool
    reason: str | None = None
    command: str | None = None

    @property
    def active(self) -> bool:
        """Return whether sandboxing should be applied to child processes."""
        return self.enabled and self.available
```

`get_sandbox_availability()` 执行一系列平台检测：

```python
def get_sandbox_availability(settings=None) -> SandboxAvailability:
    # 1. 检查沙箱是否启用
    if not resolved_settings.sandbox.enabled:
        return SandboxAvailability(enabled=False, available=False, reason="sandbox is disabled")

    # 2. 检查平台是否支持
    platform_name = get_platform()
    if not capabilities.supports_sandbox_runtime:
        if platform_name == "windows":
            reason = "sandbox runtime is not supported on native Windows; use WSL"
        return SandboxAvailability(enabled=True, available=False, reason=reason)

    # 3. 检查 srt 命令是否可用
    srt = shutil.which("srt")
    if not srt:
        return SandboxAvailability(enabled=True, available=False,
            reason="sandbox runtime CLI not found; install with npm install -g @anthropic-ai/sandbox-runtime")

    # 4. 检查平台特定依赖（Linux 需要 bwrap，macOS 需要 sandbox-exec）
    if platform_name in {"linux", "wsl"} and shutil.which("bwrap") is None:
        return SandboxAvailability(enabled=True, available=False, reason="bubblewrap required on Linux/WSL")

    return SandboxAvailability(enabled=True, available=True, command=srt)
```

> **Java 对比**：`shutil.which()` 等价于在 `$PATH` 中搜索可执行文件。Java 没有直接等价物，通常需要手动遍历 `System.getenv("PATH").split(File.pathSeparator)` 并检查每个目录。Python 的 `shutil.which()` 一步到位：

```python
shutil.which("docker")    # 返回 "/usr/bin/docker" 或 None
shutil.which("srt")       # 返回 "/usr/local/bin/srt" 或 None
```

### wrap_command_for_sandbox：命令包装

```python
def wrap_command_for_sandbox(command: list[str], *, settings=None) -> tuple[list[str], Path | None]:
    """Wrap an argv list with srt when sandboxing is active."""
    resolved_settings = settings or load_settings()
    if resolved_settings.sandbox.backend == "docker":
        return command, None  # Docker 后端不包装命令

    availability = get_sandbox_availability(resolved_settings)
    if not availability.active:
        if resolved_settings.sandbox.enabled and resolved_settings.sandbox.fail_if_unavailable:
            raise SandboxUnavailableError(availability.reason or "sandbox runtime is unavailable")
        return command, None

    settings_path = _write_runtime_settings(build_sandbox_runtime_config(resolved_settings))
    wrapped = [
        availability.command or "srt",
        "--settings", str(settings_path),
        "-c", shlex.join(command),
    ]
    return wrapped, settings_path
```

包装后的命令示例：

```
原始:  ["bash", "-c", "rm -rf /tmp/test"]
包装:  ["srt", "--settings", "/tmp/openharness-sandbox-abc123.json", "-c", "bash -c 'rm -rf /tmp/test'"]
```

`shlex.join()` 将命令列表安全地拼接为字符串，`shlex.quote()` 在需要时对参数进行 shell 转义。

> **Java 对比**：`shlex.join()` 和 `shlex.quote()` 类似于 Java 中手动拼接命令行参数时的引用处理。Java 的 `ProcessBuilder` 接受 `List<String>` 而不需要 shell 转义，但如果要传给 shell 执行则同样需要转义。Python 的 `shlex` 模块提供了标准化的 shell 转义处理。

### DockerSandboxSession：容器隔离

位于 `sandbox/docker_backend.py`：

```python
@dataclass
class DockerSandboxSession:
    """Manages a long-running Docker container for one OpenHarness session."""

    settings: Settings
    session_id: str
    cwd: Path
    _container_name: str = field(init=False)
    _running: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self._container_name = f"openharness-sandbox-{self.session_id}"

    async def start(self) -> None:
        """Create and start the sandbox container."""
        from openharness.sandbox.docker_image import ensure_image_available
        available = await ensure_image_available(...)
        argv = self._build_run_argv()
        process = await asyncio.create_subprocess_exec(*argv, ...)
        # ... 等待容器启动 ...

    async def stop(self) -> None:
        """Stop and remove the sandbox container."""
        # docker stop -t 5 <container_name>

    async def exec_command(self, argv, *, cwd, ...) -> asyncio.subprocess.Process:
        """Execute a command inside the sandbox container."""
        cmd = [docker, "exec", "-w", str(Path(cwd).resolve()), self._container_name]
        cmd.extend(argv)
        return await asyncio.create_subprocess_exec(*cmd, ...)
```

`DockerSandboxSession` 为每个 OpenHarness 会话创建一个独立的 Docker 容器：

```python
def _build_run_argv(self) -> list[str]:
    """Build the docker run argv for container creation."""
    argv = [
        docker, "run", "-d", "--rm",
        "--name", self._container_name,
    ]
    # 网络隔离
    if sandbox.network.allowed_domains:
        argv.extend(["--network", "bridge"])
    else:
        argv.extend(["--network", "none"])
    # 资源限制
    if docker_cfg.cpu_limit > 0:
        argv.extend(["--cpus", str(docker_cfg.cpu_limit)])
    if docker_cfg.memory_limit:
        argv.extend(["--memory", docker_cfg.memory_limit])
    # 挂载项目目录
    argv.extend(["-v", f"{cwd_str}:{cwd_str}"])
    argv.extend(["-w", cwd_str])
    # 启动长驻容器
    argv.extend([docker_cfg.image, "tail", "-f", "/dev/null"])
    return argv
```

关键设计点：
- **每个会话一个容器**：`openharness-sandbox-{session_id}` 确保隔离
- **网络隔离**：无 `allowed_domains` 时使用 `--network none` 完全断网
- **资源限制**：支持 CPU 和内存限制
- **目录映射**：`-v` 将项目目录映射到容器内相同路径，避免路径差异问题

> **Java 对比**：`DockerSandboxSession` 类似于 Java 中使用 `DockerClient`（如 docker-java 库）管理容器的方案。Python 版本直接调用 `docker` CLI，利用 `asyncio.create_subprocess_exec` 实现异步容器管理。Java 版本通常使用 Docker Java Client API，但 CLI 方式更简单直接。

### PathValidator：路径边界验证

位于 `sandbox/path_validator.py`：

```python
def validate_sandbox_path(path: Path, cwd: Path, extra_allowed=None) -> tuple[bool, str]:
    """Check whether path falls within the sandbox boundary."""
    resolved = path.resolve()
    resolved_cwd = cwd.resolve()

    # 主检查：路径必须在项目目录内
    try:
        resolved.relative_to(resolved_cwd)
        return True, ""
    except ValueError:
        pass

    # 辅助检查：额外允许的路径
    for allowed in extra_allowed or []:
        allowed_path = Path(allowed).expanduser().resolve()
        try:
            resolved.relative_to(allowed_path)
            return True, ""
        except ValueError:
            continue

    return False, f"path {resolved} is outside the sandbox boundary ({resolved_cwd})"
```

`validate_sandbox_path` 使用 `Path.relative_to()` 实现路径边界检查——如果 `resolved` 不能表示为 `resolved_cwd` 的子路径，就拒绝访问。`resolve()` 确保符号链接被解析，防止 `../../../etc/passwd` 类路径穿越攻击。

> **Java 对比**：`Path.relative_to()` 类似于 Java 的 `Path.relativize()`。Python 的 `resolve()` 会解析所有符号链接和 `..`，等价于 Java 的 `Path.toRealPath()`。`expanduser()` 解析 `~` 为用户主目录，Java 需要手动 `System.getProperty("user.home")`。

### tempfile.NamedTemporaryFile：临时文件

`_write_runtime_settings()` 使用 `tempfile.NamedTemporaryFile` 创建临时配置文件：

```python
def _write_runtime_settings(payload: dict[str, Any]) -> Path:
    """Persist a temporary settings file for one sandboxed child process."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        prefix="openharness-sandbox-",
        suffix=".json",
        delete=False,
    )
    try:
        json.dump(payload, tmp)
        tmp.write("\n")
    finally:
        tmp.close()
    return Path(tmp.name)
```

> **Java 对比**：`tempfile.NamedTemporaryFile(delete=False)` 等价于 Java 的 `File.createTempFile("openharness-sandbox-", ".json")`。Python 版本的 `delete=False` 确保文件在关闭后不被删除——因为子进程需要读取它。Java 的 `File.createTempFile()` 默认不删除，需要手动 `deleteOnExit()`。

## Python 概念说明

### str + Enum：字符串枚举

Python 的 `str, Enum` 多重继承让枚举值同时具备字符串语义：

```python
class PermissionMode(str, Enum):
    DEFAULT = "default"

# 直接与字符串比较
PermissionMode.DEFAULT == "default"  # True

# JSON 序列化自动转为字符串
json.dumps(PermissionMode.FULL_AUTO)  # '"full_auto"'
```

这在配置文件解析中非常方便——`HookEvent("pre_tool_use")` 可以直接从 YAML/JSON 字符串构造枚举值，不需要额外的 `fromString()` 转换方法。

### dataclass(frozen=True)：不可变数据类

`frozen=True` 创建不可变 dataclass，等价于 Java 14+ 的 `record`：

```python
@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
```

尝试修改 `frozen=True` 的实例字段会抛出 `FrozenInstanceError`。这保证了权限判定结果一旦生成就不会被意外修改。

### fnmatch：glob 模式匹配

`fnmatch` 模块提供 Unix shell 风格的模式匹配：

```python
import fnmatch

fnmatch.fnmatch("/home/user/.ssh/id_rsa", "*/.ssh/*")        # True
fnmatch.fnmatch("Bash(command='rm -rf /')", "Bash*")          # True
fnmatch.fnmatch("/etc/passwd", "*/.ssh/*")                    # False
```

在权限系统中，`fnmatch` 用于：
- 敏感路径模式匹配（`*/.ssh/*`）
- 工具名模式匹配（`Bash*`）
- 命令拒绝模式（`rm *`）
- 路径规则匹配（`*.log`）

### shutil.which()：可执行文件发现

```python
import shutil

shutil.which("docker")   # "/usr/bin/docker" 或 None
shutil.which("srt")      # "/usr/local/bin/srt" 或 None
shutil.which("bwrap")    # "/usr/bin/bwrap" 或 None
```

`shutil.which()` 在 `PATH` 中搜索可执行文件，类似于 Unix 的 `which` 命令。Java 没有直接等价物，通常需要手动遍历 PATH 环境变量。

## 架构图

```
+-------------------+     +-------------------+
| PermissionMode    |     | PermissionChecker  |
| (str, Enum)      | --> | (mode-based rules) |
| DEFAULT           |     |                    |
| PLAN              |     |  1. SENSITIVE_PATH |
| FULL_AUTO         |     |  2. denied_tools   |
+-------------------+     |  3. allowed_tools   |
                          |  4. path_rules      |
                          |  5. denied_commands |
                          |  6. mode decision   |
                          +--------+-----------+
                                   |
                          +--------+-----------+
                          |                    |
                          v                    v
                +------------------+  +------------------+
                | PermissionDecision|  | SandboxAdapter  |
                | (frozen=True)    |  | (srt / docker)   |
                | .allowed         |  +--------+---------+
                | .requires_       |           |
                |   confirmation   |     +-----+------+
                | .reason          |     |             |
                +------------------+     v             v
                                +---------------+  +------------------+
                                | srt (sandbox  |  | DockerSandbox    |
                                |  runtime CLI) |  | Session          |
                                | wrap_command_ |  | per-session      |
                                | for_sandbox() |  | container        |
                                +-------+-------+  +--------+---------+
                                        |                  |
                                        v                  v
                                +------------------+  +------------------+
                                | PathValidator    |  | SandboxSettings |
                                | (fnmatch rules)  |  | .network        |
                                | project boundary  |  | .filesystem     |
                                | check             |  | .docker         |
                                +------------------+  +--------+---------+
                                                              |
                                                              v
                                                    +------------------+
                                                    | SandboxAvailability
                                                    | .enabled         |
                                                    | .available       |
                                                    | .active          |
                                                    | .reason          |
                                                    | .command         |
                                                    +------------------+
```

## 小结

本章详细解析了 OpenHarness 的权限与沙箱系统：

1. **PermissionMode(str, Enum)** 定义了三种权限模式——DEFAULT（需要确认）、PLAN（只读）、FULL_AUTO（全自动），`str` 继承使枚举值可直接参与字符串比较和 JSON 序列化
2. **PermissionChecker** 实现了多层优先级评估：内置敏感路径保护（不可覆盖）> 工具黑名单 > 工具白名单 > 路径规则 > 命令拒绝 > 模式决定
3. **PermissionDecision(frozen=True)** 保证权限判定结果不可变，类似 Java `record`
4. **SandboxSettings** 使用 Pydantic 嵌套模型配置网络、文件系统和 Docker 参数
5. **SandboxAvailability** 通过多步平台检测确定沙箱是否可用——检查配置、平台支持、CLI 可用性和系统依赖
6. **wrap_command_for_sandbox()** 将命令包装为 `srt` 调用，通过临时 JSON 文件传递沙箱配置
7. **DockerSandboxSession** 为每个会话创建独立 Docker 容器，支持网络隔离和资源限制
8. **validate_sandbox_path()** 使用 `Path.relative_to()` 实现路径边界检查，防止路径穿越攻击

对于 Java 开发者，核心映射关系是：`str, Enum` ↔ Java `enum`、`frozen=True` dataclass ↔ Java `record`、`PermissionChecker` ↔ Spring Security `AccessDecisionManager`、`shutil.which()` ↔ 手动 PATH 搜索、`asyncio.create_subprocess_exec` ↔ `ProcessBuilder`（异步版）。OpenHarness 的权限与沙箱系统体现了「纵深防御」理念——多层检查、不可变决策、容器隔离，为 AI Agent 的执行安全提供了系统性保障。