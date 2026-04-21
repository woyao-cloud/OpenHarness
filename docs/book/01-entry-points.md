# 第一章：应用入口——Python 程序如何启动

## 概述

每个 Java 开发者都知道 `public static void main(String[] args)` 是程序的起点。Python 同样有入口机制，但形式完全不同。本章将带你从 OpenHarness 的入口文件出发，理解：

1. `if __name__ == "__main__"` 模式——Python 的程序入口
2. Typer 框架——如何用声明式风格定义 CLI
3. 延迟导入——Python 的模块按需加载机制
4. 子应用架构——如何组织复杂的命令行工具

## Java 类比

| Java 概念 | Python / OpenHarness 对应 |
|-----------|--------------------------|
| `public static void main(String[] args)` | `if __name__ == "__main__": app()` |
| Picocli `@Command` 注解 | Typer `app = typer.Typer()` |
| `System.exit(code)` | `raise typer.Exit(code)` |
| 类路径加载（Classpath） | Python 延迟导入（lazy import） |
| `package-info.java` | `__init__.py` |
| JAR 的 `META-INF/MANIFEST.MF` | `pyproject.toml` 的 `[project.scripts]` |

## 项目代码详解

### 1. `__main__.py`——最简入口

OpenHarness 的入口文件 `src/openharness/__main__.py` 只有 6 行：

```python
"""Entry point for `python -m openharness`."""

from openharness.cli import app

if __name__ == "__main__":
    app()
```

这 6 行代码背后有三个关键概念：

**概念一：`__name__` 变量**

Python 的每个模块（.py 文件）都有一个内置变量 `__name__`。当模块被直接运行时，`__name__` 的值是 `"__main__"`；当模块被其他代码 `import` 时，`__name__` 的值是模块名（如 `"openharness"`）。

```python
# 直接运行：python -m openharness
# __name__ == "__main__" → 执行 app()

# 被 import：from openharness import something
# __name__ == "openharness" → 不执行 app()
```

> **Java 对比**：Java 的 `main` 方法只在 JAR 入口类中执行。Python 的 `if __name__ == "__main__"` 实现了相同的效果，但更加灵活——任何模块都可以有条件地执行代码，既可以作为库被导入，也可以作为脚本直接运行。

**概念二：`python -m openharness` 的执行机制**

当你运行 `python -m openharness` 时，Python 解释器会：

1. 在 `sys.path` 中搜索 `openharness` 包
2. 找到包目录下的 `__main__.py` 并执行它
3. 这等价于 `python path/to/openharness/__main__.py`，但会正确设置 `sys.path`

> **Java 对比**：这类似于 `java -jar app.jar`，JVM 会读取 MANIFEST.MF 中的 `Main-Class` 属性来找到入口。Python 的 `-m` 标志等价于指定了模块入口。

**概念三：`pyproject.toml` 中定义的可执行入口**

```toml
[project.scripts]
openharness = "openharness.cli:app"
oh = "openharness.cli:app"
ohmo = "ohmo.cli:app"
```

这告诉 pip 安装后创建三个可执行命令：`openharness`、`oh` 和 `ohmo`。用户安装后可以直接在终端运行 `oh --version`，而不需要 `python -m openharness`。

> **Java 对比**：这相当于 Maven Shade Plugin 生成可执行 JAR 时的 `Main-Class` 配置。Python 通过 pip 安装时自动生成平台脚本（Linux/macOS 是 shell 脚本，Windows 是 `.exe` wrapper），用户无需关心 `java -cp` 之类的路径问题。

### 2. `cli.py`——Typer 命令行框架

OpenHarness 使用 Typer 框架来定义 CLI 命令。先看核心结构：

```python
import typer

app = typer.Typer(
    name="openharness",
    help=(
        "Oh my Harness! An AI-powered coding assistant.\n\n"
        "Starts an interactive session by default, use -p/--print for non-interactive output."
    ),
    add_completion=False,
    rich_markup_mode="rich",
    invoke_without_command=True,
)
```

**Typer 的核心设计理念**是"用函数签名声明命令"——函数的参数名就是选项名，类型注解就是参数类型，docstring 就是帮助文本。

> **Java 对比**：Picocli 用 `@Option` 和 `@Command` 注解声明 CLI 参数；Typer 用 Python 的类型注解和默认值。两者都是声明式风格，但 Typer 更简洁，因为它利用了 Python 函数签名本身就是元数据的特性。

#### 子应用架构

OpenHarness 定义了 5 个子应用：

```python
mcp_app = typer.Typer(name="mcp", help="Manage MCP servers")
plugin_app = typer.Typer(name="plugin", help="Manage plugins")
auth_app = typer.Typer(name="auth", help="Manage authentication")
provider_app = typer.Typer(name="provider", help="Manage provider profiles")
cron_app = typer.Typer(name="cron", help="Manage cron scheduler and jobs")

app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
app.add_typer(provider_app)
app.add_typer(cron_app)
```

这产生了如下命令结构：

```
oh                    # 启动交互式会话（主命令）
oh mcp list           # 列出 MCP 服务器
oh mcp add            # 添加 MCP 服务器
oh plugin install     # 安装插件
oh auth login         # 登录认证
oh provider list      # 列出提供商配置
oh cron start         # 启动定时调度器
```

> **Java 对比**：这类似 Picocli 的子命令模式：

```java
// Picocli 子命令
@Command(subcommands = {McpCommand.class, AuthCommand.class})
public class MainCommand implements Callable<Integer> { ... }
```

```python
# Typer 子应用
app.add_typer(mcp_app)    # 注册子命令组
```

Typer 用 `add_typer()` 注册子应用，而 Picocli 用 `subcommands` 注解。Typer 的写法更简洁，且自动生成帮助文本和参数校验。

#### 主命令回调：`main()`

```python
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", ...),
    continue_session: bool = typer.Option(False, "--continue", "-c", ...),
    model: str | None = typer.Option(None, "--model", "-m", ...),
    # ... 更多选项
) -> None:
    """Start an interactive session or run a single prompt."""
    if ctx.invoked_subcommand is not None:
        return
    # ... 启动逻辑
```

关键点：

- `@app.callback(invoke_without_command=True)` 表示即使没有子命令也执行此函数
- `ctx: typer.Context` 是上下文对象，类似于 Picocli 的 `CommandLine.Context`
- 每个参数自动成为 CLI 选项，类型注解决定参数类型
- `str | None` 表示可选字符串参数（对应 `Optional<String>`）

### 3. 延迟导入（Lazy Import）

OpenHarness 在 CLI 命令中广泛使用延迟导入：

```python
@mcp_app.command("list")
def mcp_list() -> None:
    """List configured MCP servers."""
    from openharness.config import load_settings      # ← 函数内部导入
    from openharness.mcp.config import load_mcp_server_configs
    from openharness.plugins import load_plugins

    settings = load_settings()
    plugins = load_plugins(settings, str(Path.cwd()))
    configs = load_mcp_server_configs(settings, plugins)
    # ...
```

**为什么不把 import 放在文件顶部？**

1. **启动速度**：如果每个子命令都加载所有依赖，`oh --version` 也要等所有模块导入完成。延迟导入让启动时间只取决于被调用命令的依赖
2. **循环依赖**：某些模块可能互相引用，延迟导入可以打破循环
3. **可选依赖**：某些功能依赖重的包（如 `questionary`），只在需要时加载

> **Java 对比**：Java 的类加载器（ClassLoader）默认就是延迟加载的——类的字节码只有在首次使用时才加载。Python 则不同，`import` 语句在模块级别会立即执行。因此 Python 需要显式把 import 移到函数内部来实现延迟效果。类比：

| 机制 | Java | Python |
|------|------|--------|
| 延迟加载 | ClassLoader 自动延迟 | 函数内 `import` 显式延迟 |
| 类路径 | `CLASSPATH` 环境变量 | `sys.path` + `PYTHONPATH` |
| 模块发现 | 反射 `Class.forName()` | `importlib.import_module()` |

### 4. `typer.Exit()` 与 `System.exit()`

```python
def _version_callback(value: bool) -> None:
    if value:
        print(f"openharness {__version__}")
        raise typer.Exit()    # ← 相当于 System.exit(0)
```

```python
@mcp_app.command("remove")
def mcp_remove(name: str = typer.Argument(..., help="Server name to remove")) -> None:
    """Remove an MCP server configuration."""
    settings = load_settings()
    if not isinstance(settings.mcp_servers, dict) or name not in settings.mcp_servers:
        print(f"MCP server not found: {name}", file=sys.stderr)
        raise typer.Exit(1)    # ← 相当于 System.exit(1)
```

> **Java 对比**：
> - `raise typer.Exit()` ≈ `System.exit(0)`
> - `raise typer.Exit(1)` ≈ `System.exit(1)`
>
> 区别在于 Typer 的 Exit 是异常而非进程终止，可以被 `try/except` 捕获，更加可控。而 `System.exit()` 会直接终止 JVM。

## Python 概念说明

### `if __name__ == "__main__"` 详解

这是 Python 中最重要的惯用法之一。每个 `.py` 文件都是模块，模块可以：

1. **被导入**（`import module`）—— `__name__` 等于模块名
2. **被直接运行**（`python module.py`）—— `__name__` 等于 `"__main__"`

```python
# my_module.py
def greet(name: str) -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    # 只在直接运行时执行
    print(greet("World"))
```

这种模式让模块既是可导入的库，又是可运行的脚本。Java 没有这种灵活性——一个类要么是入口（有 `main` 方法），要么是普通类。

### Typer 框架核心模式

```python
# 1. 创建应用
app = typer.Typer()

# 2. 定义命令（函数即命令）
@app.command()
def hello(name: str = typer.Argument(..., help="Your name")) -> None:
    print(f"Hello, {name}!")

# 3. 启动（通常在 __main__.py 中）
if __name__ == "__main__":
    app()
```

Typer 的类型注解映射：

| Python 类型 | CLI 行为 | Java Picocli 对应 |
|-------------|---------|-------------------|
| `str` | 必选位置参数 | `@Parameters` |
| `str \| None` | 可选位置参数 | `@Parameters(required=false)` |
| `bool` | `--flag/--no-flag` | `@Option(names="--flag")` |
| `int` | 整数参数 | `@Option(type = Integer.class)` |
| `list[str]` | 可重复选项 | `@Option(split=",")` |

### Python 模块系统 vs Java 包系统

```
Python                              Java
────────────────────────────────    ────────────────────────────────
openharness/                        package com.openharness;
  __init__.py    ← 包标识            (隐式，目录即包)
  cli.py         ← 模块             class Cli { ... }
  config/                           package com.openharness.config;
    __init__.py  ← 包标识            (隐式)
    settings.py  ← 模块             class Settings { ... }
```

关键差异：

1. Python 的 `__init__.py` 是包的显式标记（Python 3.3+ 的"命名空间包"可省略）
2. Python 导入用 `.` 分隔，Java 也是，但 Python 的 `from X import Y` 更灵活
3. Python 没有 `public/private` 访问修饰符，约定用 `_` 前缀表示私有

## 架构图

```
┌───────────────────────────────────────────────────────────────┐
│                    用户运行命令                                 │
│                                                               │
│   $ oh --model sonnet -p "explain this code"                  │
│   $ python -m openharness                                     │
│   $ openharness auth login                                    │
└───────────┬───────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────┐
│               __main__.py (6行入口)                            │
│                                                               │
│   from openharness.cli import app                             │
│   if __name__ == "__main__":                                  │
│       app()                          ← Typer 应用入口         │
└───────────┬───────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────┐
│                 cli.py (Typer App)                             │
│                                                               │
│   app = typer.Typer(invoke_without_command=True)              │
│                                                               │
│   ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│   │  mcp_app    │  │  plugin_app  │  │  auth_app           │  │
│   │  list       │  │  list         │  │  login              │  │
│   │  add        │  │  install      │  │  status             │  │
│   │  remove     │  │  uninstall    │  │  logout             │  │
│   └─────────────┘  └──────────────┘  │  switch             │  │
│                                       │  copilot-login      │  │
│   ┌─────────────┐  ┌──────────────┐  │  codex-login        │  │
│   │ provider_  │  │  cron_app    │  │  claude-login       │  │
│   │  app        │  │  start       │  └────────────────────┘  │
│   │  list       │  │  stop        │                           │
│   │  use        │  │  status      │  ┌────────────────────┐  │
│   │  add        │  │  list        │  │  主命令 main()      │  │
│   │  remove     │  │  toggle      │  │  --model / -m       │  │
│   └─────────────┘  └──────────────┘  │  --continue / -c   │  │
│                                       │  --print / -p      │  │
│                                       │  --verbose         │  │
│                                       │  --api-key / -k    │  │
│                                       └────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
            │
            ▼ 延迟导入（只在执行时才加载）
┌───────────────────────────────────────────────────────────────┐
│                      应用核心层                                 │
│                                                               │
│   config.load_settings() → Settings 模型                       │
│   engine.query_engine  → 查询引擎                              │
│   channels.adapter     → 多渠道适配                             │
│   ...                                                          │
└───────────────────────────────────────────────────────────────┘
```

## 小结

本章围绕"Python 应用如何启动"这个核心问题，解读了 OpenHarness 的入口架构：

1. **`__main__.py` + `if __name__ == "__main__"`**：Python 模块既是库又是脚本的入口模式，比 Java 的 `main` 方法更灵活
2. **Typer 框架**：用函数签名声明 CLI 命令，比 Picocli 的注解更简洁，自动生成帮助文本和参数校验
3. **延迟导入**：Python 没有自动的类加载延迟，需要显式在函数内部 import 来实现按需加载
4. **`typer.Exit()`**：以异常形式退出，比 `System.exit()` 更可控
5. **`pyproject.toml` 的 `[project.scripts]`**：声明式定义可执行入口，pip 安装后自动生成平台脚本

### 思考题

1. 如果把所有 import 放在 `cli.py` 顶部，会有什么性能影响？
2. `invoke_without_command=True` 在 Typer 中有什么作用？如果去掉，直接运行 `oh` 会发生什么？
3. 为什么 `mcp_list()` 中的 `from openharness.config import load_settings` 不放在文件顶部？这样做有什么好处和坏处？