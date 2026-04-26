# OpenHarness Guide Book

> *从源码深剖 AI Agent 基础设施的完整实现*

## 关于本书

本书是一份 **OpenHarness 源码级指南**，从设计理念、架构原理到模块实现，由浅入深地剖析这个开源 AI Agent Harness 系统。

**目标读者：**
- 想要理解 AI Agent 内部工作原理的开发者
- 希望基于 OpenHarness 构建自定义 Agent 的工程师
- 对 LLM 工具调用、记忆管理、多智能体协作等技术感兴趣的研究者

## 目录

| 章节 | 主题 | 内容概要 |
|------|------|---------|
| **01** | [概述与架构全景](01-overview.md) | OpenHarness 解决什么问题、核心设计理念、系统架构总览 |
| **02** | [快速上手与核心流程](02-quickstart-core-loop.md) | 从用户输入到模型响应的完整链路 |
| **03** | [API 层与多 Provider 支持](03-api-layer.md) | 抽象协议、重试机制、Provider 注册与自动检测 |
| **04** | [会话引擎](04-engine.md) | Query Loop、消息模型、流式事件、Token 追踪 |
| **05** | [工具系统](05-tool-system.md) | 工具定义规范、注册中心、30+ 内置工具实现 |
| **06** | [记忆管理](06-memory.md) | 持久化记忆、对话压缩、Token 预算控制 |
| **07** | [权限与安全控制](07-permissions-hooks.md) | 多层权限模型、敏感路径保护、生命周期 Hook |
| **08** | [多 Agent 协调](08-coordinator.md) | Subagent 派生、团队管理、Coordinator 模式 |
| **09** | [插件与技能系统](09-plugins-skills.md) | 插件架构、技能加载、命令扩展 |
| **10** | [MCP 集成](10-mcp.md) | Model Context Protocol 客户端实现 |
| **11** | [聊天频道与 ohmo 个人 Agent](11-channels-ohmo.md) | 多渠道接入、消息总线、Gateway 架构 |
| **12** | [沙箱与安全执行](12-sandbox.md) | Docker 沙箱、命令隔离、路径验证 |
| **13** | [认证与 Provider 配置管理](13-auth.md) | 认证流程、凭据存储、Profile 管理 |
| **14** | [UI 层](14-ui.md) | React TUI、Textual TUI、前后端协议、Headless 模式 |
| **15** | [服务与基础设施](15-services.md) | Cron 调度、LSP、会话管理、Token 估算、日志 |
| **附录** | [关键设计模式总结](appendix-patterns.md) | 全书设计模式、架构决策记录 |

## 如何阅读

- **按顺序阅读**：每章建立在前一章的基础上，推荐从头开始
- **按主题查阅**：每章自包含，可直接跳转到感兴趣的主题
- **配合源码**：书中标注了关键源码路径（`module/file.py:line`），建议配合 IDE 阅读

## 代码约定

本书中所有代码示例均来自 OpenHarness v0.1.6 源码。路径相对于 `src/openharness/`。

## 核心结论

OpenHarness 的核心价值在于：**模型提供智能，Harness 提供双手、眼睛、记忆和安全边界。** 它将一个纯粹的 LLM 转变为一个真正能行动的 Agent。
