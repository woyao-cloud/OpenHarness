# 前言：用真实项目学 Python

## 为什么要通过真实项目学习 Python？

很多 Java 开发者在转学 Python 时，面对的最大困难不是语法本身——毕竟两种语言在控制流、面向对象等方面有大量相似之处——而是**思维方式的转换**。Python 的"Pythonic"写法与 Java 的惯用模式截然不同：

- Java 需要显式声明类型，Python 则推崇"鸭子类型"与类型提示的灵活组合
- Java 用 `interface` + `implements` 实现多态，Python 用协议（Protocol）和区分联合（Discriminated Union）
- Java 的 POJO 需要 getter/setter，Python 用属性（`@property`）和 Pydantic 模型一行搞定
- Java 的 `record` 是 Java 14+ 才引入的不可变载体类，Python 的 `@dataclass(frozen=True)` 则天然支持

如果只是看语法书，你很难体会到这些差异在实际工程中如何体现。**通过一个真实的、正在活跃开发的开源项目来学习**，能让你同时理解语法、惯用法和架构决策背后的原因。

OpenHarness 正是这样一个项目：它是 Claude Code 的开源 Python 移植版，包含 CLI 框架、数据建模、流式事件、多渠道适配等真实工程问题，代码规模适中，足以覆盖 Python 工程的方方面面。

## 如何阅读本书

本书按以下结构组织，每章包含固定模块：

| 模块 | 说明 |
|------|------|
| **概述** | 本章要解决什么问题，为什么重要 |
| **Java 类比** | 对应 Java 中的概念与模式 |
| **项目代码详解** | 逐行解读 OpenHarness 的真实源码 |
| **Python 概念说明** | 深入讲解 Python 语言特性 |
| **架构图** | 用 ASCII 图展示组件关系 |
| **小结** | 提炼关键知识点 |

建议阅读顺序：先通读本章（前言），然后按 01 → 02 → 03 的顺序阅读。每章结尾有小结和练习思考题。

## 前置知识

- **Java 经验**：熟悉 Java 8+ 语法，了解泛型、注解、接口、record 等概念
- **基础 Python**：了解 Python 变量、函数、类的基本写法
- **开发环境**：Python 3.10+、git、终端

## Python vs Java 概念速查表

以下是贯穿全书的核心概念对照，供随时查阅：

| 概念 | Java | Python |
|------|------|--------|
| 类 | `public class Foo { ... }` | `class Foo: ...` |
| 接口 | `interface Bar { ... }` | `Protocol` (typing) 或 ABC |
| 枚举 | `enum Color { RED, GREEN }` | `enum.Enum` 或 `Literal["red", "green"]` |
| Record / 不可变数据类 | `record Point(int x, int y) {}` | `@dataclass(frozen=True)` |
| POJO + 校验 + 序列化 | POJO + Jackson + Bean Validation | `pydantic.BaseModel` |
| 泛型 | `List<String>` | `list[str]` |
| 联合类型 | `sealed interface Result permits Ok, Err` | `Ok | Err` (PEP 604) |
| 异步 | `CompletableFuture<T>` | `async def` / `asyncio` |
| 包 | `package com.example;` | `__init__.py` + 目录结构 |
| 入口方法 | `public static void main(String[] args)` | `if __name__ == "__main__":` |
| 不可变集合 | `List.of(...)`, `Set.of(...)` | `frozenset`, `tuple` |
| 属性计算 | `getField()` 方法 | `@property` 装饰器 |
| CLI 框架 | Picocli, args4j | Typer, Click |
| 配置管理 | application.yml + @Value | Pydantic Settings + 环境变量 |

## 项目概览：OpenHarness

**OpenHarness** 是一个开源 AI 编码助手的 Python 实现，核心功能包括：

1. **交互式 CLI 会话**：用户在终端中与 AI 对话，执行代码编辑、文件操作等
2. **多模型提供商支持**：Anthropic Claude、OpenAI、GitHub Copilot、Moonshot 等
3. **流式响应**：实时接收 AI 输出，支持增量文本、工具调用等事件
4. **多渠道适配**：Telegram、Slack、Discord、飞书、钉钉、QQ 等
5. **插件与 MCP 系统**：可扩展的工具协议和插件管理
6. **权限与沙箱**：细粒度的工具权限控制和 Docker 沙箱隔离

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户入口 (CLI / 通道)                        │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────────────────────┐│
│  │  __main__.py │  │   cli.py      │  │  channels/ (Telegram等)  ││
│  │  if __name__ │  │   Typer App   │  │  适配器模式接收消息       ││
│  └──────┬───────┘  └───────┬───────┘  └───────────┬───────────────┘│
│         │                  │                       │                │
├─────────┴──────────────────┴───────────────────────┴────────────────┤
│                         配置层 (Config)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ settings.py  │  │  schema.py   │  │  paths.py (路径解析)     │  │
│  │ Settings     │  │  ChannelCfg  │  │                          │  │
│  │ ProviderProf │  │  _CompatMdl  │  │                          │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
│         │                  │                                        │
├─────────┴──────────────────┴────────────────────────────────────────┤
│                         引擎层 (Engine)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ messages.py  │  │stream_events │  │  query_engine.py         │  │
│  │ 会话消息模型 │  │  流式事件     │  │  查询编排引擎            │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘  │
│         │                  │                      │                  │
├─────────┴──────────────────┴──────────────────────┴──────────────────┤
│                         API 客户端层                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  client.py   │  │ provider.py │  │  registry.py (模型注册)   │  │
│  │  Anthropic   │  │ ProviderInf │  │                          │  │
│  │  流式客户端  │  │  检测与元数据│  │                          │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────────────┘  │
│         │                                                           │
├─────────┴───────────────────────────────────────────────────────────┤
│                         基础设施层                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │  auth/   │  │  mcp/   │  │ sandbox/ │  │  permissions/      │ │
│  │  认证    │  │ 工具协议 │  │  沙箱    │  │  权限检查          │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │  hooks/  │  │ plugins/ │  │ memory/  │  │  coordinator/      │ │
│  │  钩子系统│  │  插件    │  │  记忆    │  │  多 Agent 协调     │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## 环境搭建

在开始阅读代码之前，请确保你的开发环境已就绪：

```bash
# 1. 克隆项目
git clone https://github.com/novix-science/openharness.git
cd openharness

# 2. 创建并激活虚拟环境
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

# 3. 安装项目（含开发依赖）
pip install -e ".[dev]"

# 4. 验证安装
python -m openharness --version
# 或使用短命令
oh --version
```

> **Java 对比**：这相当于 Maven 的 `mvn install`，但 Python 的 `pip install -e .` 以"可编辑"模式安装，源码修改会立即生效——不需要重新编译。`-e` 类似于 Java 中把 JAR 作为模块依赖而非打包发布。

### 关键目录结构

```
openharness/
├── src/openharness/          # 主要源码包
│   ├── __main__.py           # python -m 入口
│   ├── cli.py                # Typer CLI 定义
│   ├── config/               # 配置（settings, schema, paths）
│   ├── engine/               # 核心引擎（消息、流式事件、查询）
│   ├── api/                  # API 客户端层
│   ├── channels/             # 多渠道适配器
│   ├── auth/                 # 认证管理
│   ├── mcp/                  # MCP 工具协议
│   ├── sandbox/              # 沙箱隔离
│   ├── permissions/          # 权限系统
│   ├── hooks/                # 钩子系统
│   ├── plugins/              # 插件框架
│   ├── memory/               # 会话记忆
│   ├── coordinator/           # 多 Agent 协调
│   └── services/             # 后台服务（日志、定时任务等）
├── tests/                    # 测试代码
├── pyproject.toml            # 项目元数据与依赖（相当于 pom.xml）
└── docs/                     # 文档
```

## 小结

- OpenHarness 是一个真实可运行的开源 AI 编码助手项目，功能完整、代码规范
- Java 与 Python 在类型系统、数据建模、并发模型等维度有本质差异
- 本书通过解读 OpenHarness 的真实源码来讲解 Python 概念，而非纸上谈兵
- 每章包含 Java 类比，帮助 Java 开发者快速建立概念映射
- 请先完成环境搭建，后续章节将直接引用项目代码