# 第 12 章：沙箱与安全执行

## 12.1 解决的问题

AI Agent 可以执行任意 Shell 命令。沙箱系统提供额外的安全层：

1. **命令隔离**：在隔离环境中执行命令，防止影响主机
2. **资源限制**：限制 CPU、内存、网络访问
3. **文件系统隔离**：限制可访问的文件路径
4. **自动清理**：沙箱使用后自动回收资源

## 12.2 双后端架构

OpenHarness 支持两种沙箱后端：

| 后端 | 适用平台 | 机制 |
|------|---------|------|
| **srt CLI** | macOS, Linux | 系统调用过滤（seccomp/bwrap） |
| **Docker** | 所有平台 | 容器隔离 |

### 12.2.1 可用性检测

`platforms.py`（或沙箱模块）：
- macOS：srt 或 sandbox-exec
- Linux：bwrap（bubblewrap）或 Docker
- Windows：Docker（WSL2）

## 12.3 Docker 沙箱

### 12.3.1 会话管理

`sandbox/docker_backend.py`：

```python
class DockerSandboxSession:
    """Docker 容器沙箱会话。"""
    
    def __init__(self, image="python:3.11-slim"):
        self._container_id: str | None = None
        self._image = image
    
    async def start(self, config: SandboxConfig):
        """启动沙箱容器。"""
        # 创建容器
        result = await run_docker([
            "create",
            "--rm",                      # 退出时自动删除
            "--network", "none",         # 无网络（可选）
            f"--cpus={config.cpus}",     # CPU 限制
            f"--memory={config.memory}", # 内存限制
            "--security-opt", "no-new-privileges",
            self._image,
            "tail", "-f", "/dev/null",   # 保持运行
        ])
        self._container_id = result.strip()
        
        # 启动容器
        await run_docker(["start", self._container_id])
        
        # 复制项目文件
        if config.project_dir:
            await run_docker([
                "cp", str(config.project_dir),
                f"{self._container_id}:/workspace",
            ])
    
    async def exec_command(self, command: str) -> str:
        """在容器内执行命令。"""
        result = await run_docker([
            "exec",
            self._container_id,
            "sh", "-c", command,
        ])
        return result
    
    async def stop(self):
        """停止并清理容器。"""
        if self._container_id:
            await run_docker(["stop", self._container_id])
            self._container_id = None
```

### 12.3.2 Docker 镜像管理

`sandbox/docker_image.py`：

```python
def ensure_sandbox_image(image_name="openharness-sandbox"):
    """确保沙箱镜像存在，必要时构建。"""
    if not _image_exists(image_name):
        _build_image(image_name)

def _build_image(image_name):
    """构建沙箱镜像。"""
    dockerfile = """
    FROM python:3.11-slim
    RUN apt-get update && apt-get install -y \\
        git \\
        ripgrep \\
        bash \\
    && rm -rf /var/lib/apt/lists/*
    """
    subprocess.run(["docker", "build", "-t", image_name, "-"], 
                   input=dockerfile, text=True)
```

### 12.3.3 全局沙箱管理

`sandbox/session.py` 维护模块级单例：

```python
_sandbox: DockerSandboxSession | None = None

def get_docker_sandbox() -> DockerSandboxSession | None:
    return _sandbox

async def start_docker_sandbox(config) -> DockerSandboxSession:
    global _sandbox
    _sandbox = DockerSandboxSession()
    await _sandbox.start(config)
    return _sandbox

async def stop_docker_sandbox():
    global _sandbox
    if _sandbox:
        await _sandbox.stop()
        _sandbox = None

# 注册清理
atexit.register(lambda: asyncio.run(stop_docker_sandbox()))
```

## 12.4 srt CLI 沙箱

### 12.4.1 命令包装

`sandbox/adapter.py`：

```python
def wrap_command_for_sandbox(command: list[str], config: SandboxConfig) -> list[str]:
    """将命令包装在 srt 沙箱中。"""
    srt_args = ["srt", "--settings", json.dumps({
        "network": config.allow_network,
        "write_paths": config.write_paths,
        "read_paths": config.read_paths,
        "timeout": config.timeout_ms,
    })]
    return srt_args + ["-c", " ".join(command)]

def get_sandbox_availability() -> SandboxAvailability:
    """检查系统上可用的沙箱机制。"""
    if _check_srt_available():
        return SandboxAvailability.SRT
    if _check_bwrap_available():
        return SandboxAvailability.BWRAP
    if _check_sandbox_exec_available():
        return SandboxAvailability.SANDBOX_EXEC
    return SandboxAvailability.NONE
```

## 12.5 路径验证

`sandbox/path_validator.py`：

```python
def validate_sandbox_path(path: Path, project_root: Path, extra_allowed: list[Path]) -> bool:
    """验证路径是否在允许范围内。"""
    resolved = path.resolve()
    
    # 允许项目目录内的路径
    try:
        resolved.relative_to(project_root.resolve())
        return True
    except ValueError:
        pass
    
    # 允许额外指定的路径
    for allowed in extra_allowed:
        try:
            resolved.relative_to(allowed.resolve())
            return True
        except ValueError:
            pass
    
    return False
```

## 12.6 OpenHarness 内置的 Bash 沙箱

`tools/bash_tool.py` 中的 Bash 工具有可选的沙箱集成：

```python
class BashTool(BaseTool):
    name = "bash"
    description = "Execute a shell command"
    
    async def execute(self, args, context):
        sandbox = get_docker_sandbox()
        
        if sandbox and context.metadata.get("use_sandbox"):
            # 在沙箱中执行
            output = await sandbox.exec_command(args.command)
        else:
            # 直接在主机上执行
            output = await self._run_local(args.command, args.timeout)
        
        return ToolResult(output=output)
```

## 12.7 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| Docker 沙箱 | `sandbox/docker_backend.py` | `DockerSandboxSession` |
| Docker 镜像 | `sandbox/docker_image.py` | `ensure_sandbox_image()` |
| 沙箱适配器 | `sandbox/adapter.py` | `wrap_command_for_sandbox()` |
| 路径验证 | `sandbox/path_validator.py` | `validate_sandbox_path()` |
| 全局沙箱管理 | `sandbox/session.py` | `get_docker_sandbox()` |
| Bash 工具集成 | `tools/bash_tool.py` | BashTool 中可选沙箱 |

## 12.8 本章小结

沙箱系统通过 **Docker 容器 + srt CLI + 路径验证** 三层防护提供命令隔离。Docker 沙箱提供完整的容器级隔离（文件系统、网络、资源限制），适合需要深度隔离的场景。srt CLI 提供轻量级系统调用过滤，适合性能敏感场景。两种后端可根据可用性和场景自动选择。

> 下一章：[认证与 Provider 配置管理](13-auth.md) —— 认证流程与凭据管理。
