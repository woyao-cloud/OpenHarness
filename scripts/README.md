# OpenHarness 测试脚本使用指南

本目录包含 OpenHarness 项目的端到端（E2E）测试和场景验证脚本。每个脚本都可以独立运行，用于验证不同子系统的功能正确性。

---

## 快速参考表

| 脚本 | 类型 | 需要 API | 需要 Docker | 需要 pexpect | 运行命令 |
|------|------|----------|------------|-------------|---------|
| `e2e_smoke.py` | 场景测试 | 是 | 否 | 否 | `python scripts/e2e_smoke.py [--scenario X]` |
| `local_system_scenarios.py` | 本地测试 | 否 | 否 | 否 | `python scripts/local_system_scenarios.py` |
| `react_tui_e2e.py` | TUI 测试 | 是 | 否 | 是 | `python scripts/react_tui_e2e.py [--scenario X]` |
| `test_cli_flags.py` | CLI 测试 | 是 | 否 | 否 | `python scripts/test_cli_flags.py` |
| `test_docker_sandbox_e2e.py` | 沙箱测试 | 否 | 是 | 否 | `python scripts/test_docker_sandbox_e2e.py` |
| `test_harness_features.py` | 功能测试 | 是 | 否 | 否 | `python scripts/test_harness_features.py` |
| `test_headless_rendering.py` | 渲染测试 | 是 | 否 | 否 | `python scripts/test_headless_rendering.py` |
| `test_react_tui_redesign.py` | TUI 重设计测试 | 是 | 否 | 是 | `python scripts/test_react_tui_redesign.py` |
| `test_real_skills_plugins.py` | 插件测试 | 是 | 否 | 否 | `python scripts/test_real_skills_plugins.py` |
| `test_tui_interactions.py` | TUI 交互测试 | 是 | 否 | 是 | `python scripts/test_tui_interactions.py` |

---

## 环境准备

### 通用前提

```bash
# 安装项目依赖
cd OpenHarness
uv sync --extra dev

# 或使用 pip
pip install -e ".[dev]"
```

### API 密钥配置

需要真实 API 调用的脚本需要配置以下环境变量：

```bash
# Anthropic 官方 API
export ANTHROPIC_AUTH_TOKEN="sk-ant-..."

# 或使用 Kimi 兼容端点（默认）
export ANTHROPIC_BASE_URL="https://api.moonshot.cn/anthropic"
export ANTHROPIC_MODEL="kimi-k2.5"

# 也可通过 stdin 传入密钥
python scripts/e2e_smoke.py --api-key-stdin
```

### Docker 环境（仅沙箱测试）

```bash
# 确保 Docker 守护进程运行中
docker info
```

### pexpect 依赖（仅 TUI 测试）

```bash
pip install pexpect
```

---

## 脚本详细说明

### 1. `e2e_smoke.py` — 端到端场景冒烟测试

**功能**：使用真实模型 API 调用验证 OpenHarness 各核心功能的端到端正确性。

**覆盖的场景（19 个）**：

| 场景 | 说明 | 涉及的工具 |
|------|------|-----------|
| `file_io` | 文件读写 | `write_file`, `read_file` |
| `search_edit` | 搜索与编辑 | `write_file`, `glob`, `grep`, `edit_file`, `read_file` |
| `phase48` | 工具搜索与 TODO | `tool_search`, `todo_write`, `read_file` |
| `task_flow` | 后台任务 | `task_create`, `sleep`, `task_output` |
| `skill_flow` | 技能加载 | `skill` |
| `mcp_model` | MCP 工具调用 | `mcp__fixture__hello` |
| `mcp_resource` | MCP 资源读取 | `list_mcp_resources`, `read_mcp_resource` |
| `context_flow` | 上下文注入（CLAUDE.md + Memory） | `write_file`, `read_file` |
| `agent_flow` | 子代理委派 | `agent`, `send_message`, `sleep`, `task_output` |
| `remote_agent_flow` | 远程代理模式 | `agent`, `send_message`, `sleep`, `task_output` |
| `plugin_combo` | 插件组合（技能 + MCP） | `skill`, `mcp__fixture-plugin_fixture__hello` |
| `ask_user_flow` | 用户交互 | `ask_user_question`, `write_file`, `read_file` |
| `task_update_flow` | 任务状态更新 | `task_create`, `task_update`, `task_get` |
| `notebook_flow` | Jupyter 笔记本 | `notebook_edit`, `read_file` |
| `lsp_flow` | LSP 语言服务 | `lsp` |
| `cron_flow` | 定时任务 | `cron_create`, `cron_list`, `remote_trigger`, `cron_delete` |
| `worktree_flow` | Git 工作树 | `enter_worktree`, `read_file`, `exit_worktree` |
| `issue_pr_context_flow` | Issue/PR 上下文 | `write_file`, `read_file` |
| `mcp_auth_flow` | MCP 认证重配置 | `mcp_auth`, `mcp__fixture__hello` |

**用法**：

```bash
# 运行所有场景
python scripts/e2e_smoke.py

# 运行单个场景
python scripts/e2e_smoke.py --scenario file_io

# 指定模型和端点
python scripts/e2e_smoke.py --model kimi-k2.5 --base-url https://api.moonshot.cn/anthropic

# 通过 stdin 传入 API 密钥
echo "sk-ant-..." | python scripts/e2e_smoke.py --api-key-stdin
```

**验证逻辑**：每个场景会：
1. 在临时目录中设置测试环境
2. 发送提示词给模型
3. 流式收集工具调用事件
4. 验证最终输出包含预期标记（如 `FINAL_OK`）
5. 验证文件系统中的实际变更

---

### 2. `local_system_scenarios.py` — 本地系统场景测试

**功能**：不依赖真实 API 调用，测试本地子系统的正确性。

**覆盖的流程（5 个）**：

| 流程 | 说明 |
|------|------|
| `mcp_flow` | MCP 服务器连接、工具发现与调用 |
| `plugin_flow` | 插件安装、技能和 MCP 工具的发现与执行 |
| `plugin_command_flow` | 插件命令（install/enable/disable/uninstall）的执行 |
| `bridge_flow` | Bridge 会话生成、工作密钥编解码、SDK URL 构建 |
| `command_flow` | 斜杠命令（/memory, /output-style, /vim, /voice, /plan, /effort, /passes, /tasks, /init, /files, /session, /bridge, /privacy-settings, /rate-limit-options, /release-notes, /upgrade, /doctor） |

**用法**：

```bash
python scripts/local_system_scenarios.py
```

**注意**：此脚本使用 `FakeApiClient`，不会发送真实 API 请求。

---

### 3. `react_tui_e2e.py` — React TUI 端到端测试

**功能**：使用 pexpect 驱动真实 `oh` CLI 入口，测试 React TUI 的交互功能。

**覆盖的测试（3 个）**：

| 测试 | 说明 |
|------|------|
| `permission_file_io` | TUI 中的文件写入权限流程 |
| `question_flow` | TUI 中的用户问答弹窗流程 |
| `command_flow` | TUI 中的 /plan 命令和计划模式 |

**用法**：

```bash
# 运行所有 TUI 测试
python scripts/react_tui_e2e.py

# 运行单个场景
python scripts/react_tui_e2e.py --scenario permission_file_io
```

**前置条件**：
- 需要安装 `pexpect`
- 需要 `uv` 可执行（脚本通过 `uv run oh` 启动 CLI）
- 需要 Node.js 环境（React TUI 前端）

---

### 4. `test_cli_flags.py` — CLI 标志测试

**功能**：验证 `oh` 命令行界面的各种标志和子命令。

**覆盖的测试（6 个）**：

| 测试 | 说明 |
|------|------|
| `help_output` | `--help` 输出包含所有标志组 |
| `print_mode` | `-p` 非交互式模式（真实模型调用） |
| `print_json` | `--output-format json` JSON 输出模式 |
| `mcp_list` | `oh mcp list` 子命令 |
| `plugin_list` | `oh plugin list` 子命令 |
| `auth_status` | `oh auth status` 子命令 |

**用法**：

```bash
python scripts/test_cli_flags.py
```

**注意**：`print_mode` 和 `print_json` 会发起真实 API 调用。

---

### 5. `test_docker_sandbox_e2e.py` — Docker 沙箱端到端测试

**功能**：测试 Docker 沙箱后端的完整容器生命周期管理。

**覆盖的测试类别（8 类）**：

| 类别 | 测试项 | 说明 |
|------|--------|------|
| **镜像管理** | `test_image_build` | 沙箱镜像构建与可用性 |
| | `test_image_has_expected_tools` | 镜像包含 bash、rg、git |
| **容器生命周期** | `test_start_and_stop` | 容器启动、可见、干净停止 |
| | `test_stop_sync` | 同步停止（atexit 处理器） |
| | `test_availability_check` | Docker 可用性检测 |
| **命令执行** | `test_echo` | 基本命令执行与输出 |
| | `test_exit_code_preserved` | 非零退出码传播 |
| | `test_env_vars_passed` | 环境变量传入容器 |
| | `test_working_directory` | 工作目录设置 |
| **文件系统隔离** | `test_bind_mount_readable` | 宿主文件可读 |
| | `test_bind_mount_writable` | 容器写入可见于宿主 |
| | `test_host_root_not_accessible` | 宿主根目录不可访问 |
| | `test_ripgrep_inside_container` | 容器内 ripgrep 可用 |
| **网络隔离** | `test_network_none_blocks_connectivity` | `--network=none` 阻断网络 |
| | `test_network_bridge_allows_connectivity` | `--network=bridge` 允许网络 |
| **资源限制** | `test_cpu_limit_applied` | CPU 限制生效 |
| | `test_memory_limit_applied` | 内存限制生效 |
| **会话集成** | `test_session_lifecycle` | 全局沙箱会话管理 |
| **Shell 集成** | `test_create_shell_subprocess_routes_through_docker` | Shell 命令路由到容器 |

**用法**：

```bash
# 直接运行
python scripts/test_docker_sandbox_e2e.py

# 或通过 pytest（Docker 不可用时自动跳过）
uv run pytest scripts/test_docker_sandbox_e2e.py -v
```

**前置条件**：需要 Docker 守护进程运行。

---

### 6. `test_harness_features.py` — Harness 功能测试

**功能**：验证 OpenHarness 的核心功能特性。

**覆盖的测试（9 个）**：

| 测试 | 说明 | 需要 API |
|------|------|----------|
| `api_retry_config` | API 重试配置（最大重试次数、可重试状态码、指数退避延迟） | 否 |
| `api_retry_real_call` | 带重试逻辑的真实 API 调用 | 是 |
| `skills_loaded` | 内置技能加载（commit, review, simplify, plan, test, debug） | 否 |
| `skills_in_system_prompt` | 技能元数据注入系统提示词 | 否 |
| `skill_tool_invocation` | SkillTool 加载技能内容 | 否 |
| `skill_real_model` | 模型通过真实 API 调用使用技能 | 是 |
| `parallel_tools_code` | 并行工具执行代码路径（`asyncio.gather`） | 否 |
| `path_permissions_deny` | 路径级别拒绝规则 | 否 |
| `command_deny_pattern` | 命令拒绝模式 | 否 |

**用法**：

```bash
python scripts/test_harness_features.py
```

---

### 7. `test_headless_rendering.py` — 无头渲染测试

**功能**：验证无头（headless）REPL 模式下的输出渲染质量。

**覆盖的测试（4 个）**：

| 测试 | 说明 | 需要 API |
|------|------|----------|
| `markdown_render` | Markdown 格式渲染（代码块、列表） | 否 |
| `tool_output_format` | 工具输出面板格式化 | 否 |
| `spinner_display` | 工具执行期间的 Spinner 指示器 | 否 |
| `real_model_headless` | 真实模型无头模式调用 | 是 |

**用法**：

```bash
python scripts/test_headless_rendering.py
```

---

### 8. `test_react_tui_redesign.py` — React TUI 重设计测试

**功能**：验证 React TUI 的重设计版本（新对话布局、欢迎横幅、状态栏）。

**覆盖的测试（3 个）**：

| 测试 | 说明 |
|------|------|
| `welcome_banner` | 启动时显示 "Oh my Harness!" 欢迎横幅 |
| `conversation_flow` | 对话使用垂直布局（无 SidePanel） |
| `status_bar` | 状态栏显示模型信息 |

**用法**：

```bash
python scripts/test_react_tui_redesign.py
```

**前置条件**：
- 需要安装 `pexpect`
- 需要 Node.js 和 npm（React TUI 前端）
- 需要 `frontend/terminal` 目录下的依赖已安装（`npm install`）

---

### 9. `test_real_skills_plugins.py` — 真实技能与插件测试

**功能**：使用真实的 [anthropics/skills](https://github.com/anthropics/skills) 和兼容插件仓库验证技能和插件系统。

**覆盖的测试（12 个）**：

**技能测试（6 个）**：

| 测试 | 说明 |
|------|------|
| `install_real_skills` | 从 anthropics/skills 安装真实技能 |
| `real_skills_loaded` | 验证已安装技能被注册表加载 |
| `real_skill_content_quality` | 验证技能内容质量（非空/非存根） |
| `skill_tool_real` | SkillTool 加载真实技能（pdf/xlsx） |
| `skills_in_prompt_real` | 真实技能名称出现在系统提示词中 |
| `model_uses_real_skill` | 模型通过真实 API 调用使用技能 |

**插件测试（6 个）**：

| 测试 | 说明 |
|------|------|
| `install_real_plugins` | 安装真实兼容插件 |
| `real_plugins_loaded` | 验证插件被加载器发现 |
| `plugin_commands_discovered` | 插件命令和技能被发现 |
| `plugin_hook_structure` | 插件钩子结构验证（如 security-guidance 的 PreToolUse） |
| `commit_command_content` | commit-commands 插件命令内容验证 |
| `model_with_plugins` | 安装插件后的模型调用（无崩溃） |

**用法**：

```bash
# 需要先克隆技能和插件仓库
git clone https://github.com/anthropics/skills /tmp/anthropic-skills

python scripts/test_real_skills_plugins.py
```

---

### 10. `test_tui_interactions.py` — TUI 交互测试

**功能**：测试 React TUI 的交互功能：命令选择器、权限弹窗、快捷键提示。

**覆盖的测试（4 个）**：

| 测试 | 说明 |
|------|------|
| `no_headless_flag` | `--headless` 标志已移除（不在 `--help` 中） |
| `command_picker` | 输入 `/` 触发命令选择器 |
| `shortcut_hints` | 键盘快捷键提示可见 |
| `permission_flow` | 权限弹窗出现且 y/n 响应生效 |

**用法**：

```bash
python scripts/test_tui_interactions.py
```

**前置条件**：同 `react_tui_e2e.py`。

---

## 按需运行指南

### 只跑不需要 API 的测试

```bash
# 本地系统场景（无 API 调用）
python scripts/local_system_scenarios.py

# Docker 沙箱测试（需要 Docker，无 API）
python scripts/test_docker_sandbox_e2e.py
```

### 只跑功能验证测试

```bash
# Harness 功能（部分需要 API）
python scripts/test_harness_features.py

# 无头渲染（部分需要 API）
python scripts/test_headless_rendering.py
```

### 只跑 CLI 测试

```bash
# CLI 标志测试
python scripts/test_cli_flags.py
```

### 只跑 TUI 测试

```bash
# React TUI E2E
python scripts/react_tui_e2e.py

# TUI 重设计
python scripts/test_react_tui_redesign.py

# TUI 交互
python scripts/test_tui_interactions.py
```

### 跑完整冒烟测试套件

```bash
# 按顺序运行所有脚本（需要 API + Docker + pexpect）
python scripts/local_system_scenarios.py && \
python scripts/test_cli_flags.py && \
python scripts/test_harness_features.py && \
python scripts/test_headless_rendering.py && \
python scripts/e2e_smoke.py && \
python scripts/react_tui_e2e.py && \
python scripts/test_react_tui_redesign.py && \
python scripts/test_tui_interactions.py && \
python scripts/test_real_skills_plugins.py && \
python scripts/test_docker_sandbox_e2e.py
```

---

## 常见问题

### Q: 脚本报错 "Missing API key"

**A**: 需要设置 `ANTHROPIC_AUTH_TOKEN` 环境变量，或使用 `--api-key-stdin` 选项通过标准输入传入。

### Q: Docker 沙箱测试被跳过

**A**: 确保 Docker 守护进程正在运行（`docker info`），脚本会自动检测 Docker 可用性。

### Q: pexpect 相关报错

**A**: 安装 pexpect：`pip install pexpect`。注意 pexpect 在 Windows 上功能有限，TUI 测试建议在 Linux/macOS/WSL 上运行。

### Q: React TUI 测试超时

**A**: 确保已在 `frontend/terminal` 目录下运行 `npm install` 安装依赖。可能需要增加超时时间（修改脚本中的 `timeout` 参数）。

### Q: 真实技能/插件测试找不到仓库

**A**: 需要先克隆对应的仓库到指定路径：
- 技能：`git clone https://github.com/anthropics/skills /tmp/anthropic-skills`
- 插件：将兼容插件放置在 `/tmp/openharness-test-plugins/plugins/`

### Q: 如何在 CI 中使用

**A**: 建议分层运行：
1. **快速层**（无外部依赖）：`local_system_scenarios.py`
2. **API 层**（需要密钥）：`test_cli_flags.py`, `test_harness_features.py`, `test_headless_rendering.py`, `e2e_smoke.py`
3. **Docker 层**（需要 Docker）：`test_docker_sandbox_e2e.py`
4. **TUI 层**（需要显示环境）：`react_tui_e2e.py`, `test_react_tui_redesign.py`, `test_tui_interactions.py`