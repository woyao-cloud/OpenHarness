# Phase 8: 知识与记忆系统深度解析

> 涉及文件:
> - `skills/types.py` (15行) — SkillDefinition 数据模型
> - `skills/registry.py` (25行) — SkillRegistry 注册表
> - `skills/loader.py` (139行) — Skill 加载与解析
> - `skills/bundled/__init__.py` (69行) — 内置 Skill 加载
> - `memory/types.py` (12行) — MemoryHeader 数据模型
> - `memory/paths.py` (22行) — 记忆路径解析
> - `memory/manager.py` (59行) — 记忆文件增删
> - `memory/scan.py` (83行) — 记忆文件扫描与元数据提取
> - `memory/search.py` (49行) — 启发式记忆搜索
> - `memory/memdir.py` (34行) — 记忆 Prompt 构建
> - `prompts/system_prompt.py` (110行) — 基础系统提示词
> - `prompts/environment.py` (136行) — 环境信息检测
> - `prompts/claudemd.py` (49行) — CLAUDE.md 发现与加载
> - `prompts/context.py` (157行) — 运行时系统提示词组装
> - `personalization/rules.py` (65行) — 本地规则与事实持久化
> - `personalization/extractor.py` (139行) — 从对话提取环境事实
> - `personalization/session_hook.py` (65行) — 会话结束时更新规则

 知识系统三层架构:
  - Layer 1 (系统基础): _BASE_SYSTEM_PROMPT + 环境信息 + Skills 列表 + Delegation 指南 — 始终存在
  - Layer 2 (项目知识): CLAUDE.md (向上遍历目录树发现) + Local Rules (自动提取环境事实) — 项目级持久
  - Layer 3 (动态知识): Relevant Memories (基于用户消息搜索) + Issue/PR Context — 每次请求变化

  三种知识形态:
  - Memory: 项目级持久存储, /memory 命令管理, 启发式关键词搜索 (支持中英文混合), 单文件上限 8000 字符
  - Skill: 全局指令模板, 目录结构 skills/<name>/SKILL.md, YAML frontmatter 解析, 系统提示词只列名称和描述, 完整内容按需加载
  - CLAUDE.md: 项目指令, 向上遍历发现 (项目根 + .claude/ + .claude/rules/*.md), 单文件上限 12000 字符

  Personalization: 会话结束时自动提取 10 类环境事实 (SSH, IP, 数据路径, Conda, Python 版本, API 端点, 环境变量, Git Remote, Ray 集群, Cron 调度), 按 key 去重合并, 持久化到
  ~/.openharness/local_rules/。

  安全: Memory 路径 slug 化防遍历, CLAUDE.md 字符截断防溢出, Personalization IP 过滤防误匹配。
---

## 1. 系统提示词组装 — 知识注入的总入口

```
build_runtime_system_prompt(settings, cwd, latest_user_prompt)
│
│  ┌─ Coordinator 模式 ─┐     ┌─ 正常模式 ──────────┐
│  │ get_coordinator_    │  或  │ build_system_prompt() │
│  │ system_prompt()     │     │ = BASE + Environment │
│  └────────────────────┘     └──────────────────────┘
│
├── Fast Mode 标记 (可选)
│
├── Reasoning Settings (effort + passes)
│
├── Skills Section (可选)
│   └── load_skill_registry() → 列出所有可用 Skill
│
├── Delegation Section (子 Agent 使用指南)
│
├── CLAUDE.md (项目指令)
│   └── discover_claude_md_files() → 向上遍历目录树
│
├── Local Rules (自动提取的环境规则)
│
├── Issue Context (可选, .openharness/issue.md)
│
├── PR Comments Context (可选, .openharness/pr_comments.md)
│
├── Memory Section (如果启用)
│   ├── load_memory_prompt() → MEMORY.md 索引
│   └── find_relevant_memories() → 相关记忆文件
│
└── "\n\n".join(所有 section)
```

**这是整个知识系统的汇聚点** — 所有知识来源最终被组装成一个巨大的 system prompt 字符串, 注入到每次 API 调用中。

---

## 2. Skill 系统 — 可复用的指令模板

### 数据模型

```python
@dataclass(frozen=True)
class SkillDefinition:
    name: str            # Skill 名称 (唯一标识)
    description: str     # 简短描述 (帮助用户选择)
    content: str         # 完整 Skill 内容 (Markdown)
    source: str          # "bundled" / "user" / "plugin"
    path: str | None     # 源文件路径
```

### Skill 来源层次 (优先级从高到低)

```
1. Bundled Skills          ← 包内 skills/bundled/content/*.md
2. User Skills             ← ~/.openharness/skills/*/SKILL.md
3. Extra Skill Dirs        ← 调用方传入的额外目录
4. Plugin Skills            ← 插件提供的 Skill
```

后注册的 Skill 会覆盖同名的前一个 (`SkillRegistry.register()` 使用 `dict[name] = skill`)。

### Skill 加载流程

```python
def load_skill_registry(cwd, *, extra_skill_dirs, extra_plugin_roots, settings):
    registry = SkillRegistry()
    # 1. 内置 Skill
    for skill in get_bundled_skills():
        registry.register(skill)
    # 2. 用户 Skill
    for skill in load_user_skills():
        registry.register(skill)
    # 3. 额外目录 Skill
    for skill in load_skills_from_dirs(extra_skill_dirs):
        registry.register(skill)
    # 4. 插件 Skill (需要 cwd + settings)
    for plugin in load_plugins(settings, cwd, ...):
        if plugin.enabled:
            for skill in plugin.skills:
                registry.register(skill)
    return registry
```

### Skill 文件格式

```markdown
---
name: commit
description: Create a git commit with a conventional commit message
---

# Commit Skill

When the user asks you to commit changes...

(Skill 的完整指令内容)
```

支持两种格式:
1. **YAML frontmatter** (`---` 包裹) → `name` 和 `description` 字段
2. **Markdown 回退** → 第一个 `# Heading` 作为 name, 第一个段落作为 description

### Skill 文件发现规则

```
<root>/<skill-dir>/SKILL.md    ← 每个 Skill 是一个目录下的 SKILL.md 文件
```

例如:
```
~/.openharness/skills/
  commit/
    SKILL.md
  review/
    SKILL.md
```

### Skill 在系统提示词中的呈现

```python
def _build_skills_section(cwd, *, ...):
    registry = load_skill_registry(...)
    skills = registry.list_skills()
    lines = [
        "# Available Skills",
        "",
        "The following skills are available via the `skill` tool. "
        "When a user's request matches a skill, invoke it with `skill(name=\"<skill_name>\")` "
        "to load detailed instructions before proceeding.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{skill.name}**: {skill.description}")
    return "\n".join(lines)
```

**注意**: 系统提示词中只列出 Skill 的名称和描述。完整内容在用户调用 `/skill name` 时才加载到对话中。

---

## 3. Memory 系统 — 项目级持久化记忆

### 路径结构

```
~/.openharness/data/memory/<project-name>-<sha1-hash>/
├── MEMORY.md          ← 索引文件 (自动维护)
├── design.md          ← 设计决策记忆
├── api_patterns.md    ← API 模式记忆
└── ...                 ← 其他记忆文件
```

**路径生成**: `sha1(str(path).encode("utf-8")).hexdigest()[:12]` — 不同项目目录不会冲突。

### MemoryHeader — 记忆文件元数据

```python
@dataclass(frozen=True)
class MemoryHeader:
    path: Path               # 文件路径
    title: str                # 标题 (来自 YAML frontmatter 或文件名)
    description: str          # 描述 (来自 frontmatter 或首行)
    modified_at: float       # 修改时间戳
    memory_type: str = ""     # 类型标签 (来自 frontmatter)
    body_preview: str = ""    # 正文前 300 字符 (排除标题和描述行)
```

### 记忆文件增删

```python
# 添加记忆:
add_memory_entry(cwd, title="design", content="...")
# 1. 生成 slug: "Design Decision" → "design_decision"
# 2. 写入文件: <memory_dir>/design_decision.md
# 3. 追加到 MEMORY.md 索引: - [Design Decision](design_decision.md)
# 使用 exclusive_file_lock + atomic_write_text 保证原子性

# 删除记忆:
remove_memory_entry(cwd, name="design")
# 1. 查找匹配文件 (stem 或 name)
# 2. 删除文件
# 3. 从 MEMORY.md 移除对应行
# 同样使用文件锁保证一致性
```

### 记忆搜索 — 启发式关键词匹配

```python
def find_relevant_memories(query, cwd, *, max_results=5):
    tokens = _tokenize(query)   # ASCII 单词 (3+ 字符) + 中文字符
    
    for header in scan_memory_files(cwd, max_files=100):
        meta = f"{header.title} {header.description}".lower()
        body = header.body_preview.lower()
        
        # 元数据匹配权重 2x, 正文匹配权重 1x
        meta_hits = sum(1 for t in tokens if t in meta)
        body_hits = sum(1 for t in tokens if t in body)
        score = meta_hits * 2.0 + body_hits
    
    # 按分数降序, 同分按修改时间降序
    scored.sort(key=lambda x: (-x[0], -x[1].modified_at))
```

**分词策略**: 支持中英文混合搜索 — ASCII 单词需要 3+ 字符, 每个 CJK 字符独立作为 token。

### 记忆在系统提示词中的呈现

```
# Memory
- Persistent memory directory: ~/.openharness/data/memory/my-project-abc123/
- Use this directory to store durable user or project context.
- Prefer concise topic files plus an index entry in MEMORY.md.

## MEMORY.md
```md
# Memory Index
- [Design Decision](design_decision.md)
- [API Patterns](api_patterns.md)
```

# Relevant Memories            ← 基于用户最新消息搜索

## design_decision.md
```md
(设计决策的完整内容, 最多 8000 字符)
```
```

---

## 4. CLAUDE.md — 项目指令发现

### 发现算法

```python
def discover_claude_md_files(cwd):
    """从 cwd 向上遍历到根目录, 发现所有 CLAUDE.md"""
    current = Path(cwd).resolve()
    results = []
    seen = set()
    
    for directory in [current, *current.parents]:
        # 检查两个位置:
        # 1. directory/CLAUDE.md
        # 2. directory/.claude/CLAUDE.md
        for candidate in (directory / "CLAUDE.md", directory / ".claude" / "CLAUDE.md"):
            if candidate.exists() and candidate not in seen:
                results.append(candidate)
                seen.add(candidate)
        
        # 检查 .claude/rules/ 目录下的 .md 文件
        rules_dir = directory / ".claude" / "rules"
        if rules_dir.is_dir():
            for rule in sorted(rules_dir.glob("*.md")):
                if rule not in seen:
                    results.append(rule)
                    seen.add(rule)
        
        if directory.parent == directory:  # 到达根目录
            break
    
    return results
```

### 加载策略

```python
def load_claude_md_prompt(cwd, *, max_chars_per_file=12000):
    files = discover_claude_md_files(cwd)
    if not files:
        return None
    
    lines = ["# Project Instructions"]
    for path in files:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + "\n...[truncated]..."
        lines.extend(["", f"## {path}", "```md", content.strip(), "```"])
    return "\n".join(lines)
```

**每个文件最多 12000 字符** — 防止 CLAUDE.md 过大撑爆 context。

### 发现层级示例

```
/home/user/projects/myapp/CLAUDE.md          ← 项目根目录
/home/user/projects/myapp/.claude/CLAUDE.md  ← 项目 .claude 目录
/home/user/projects/myapp/.claude/rules/testing.md  ← 规则文件
/home/user/projects/myapp/.claude/rules/security.md  ← 规则文件
/home/user/CLAUDE.md                          ← 用户主目录 (全局)
/home/user/.claude/CLAUDE.md                  ← 用户全局 .claude
/home/user/.claude/rules/*.md                ← 用户全局规则
```

所有发现的文件按从近到远的顺序包含在系统提示词中。

---

## 5. Environment Info — 环境信息检测

```python
@dataclass
class EnvironmentInfo:
    os_name: str               # "Linux", "macOS", "Windows"
    os_version: str            # 版本号
    platform_machine: str      # "x86_64", "arm64" 等
    shell: str                 # "bash", "zsh", "fish" 等
    cwd: str                   # 当前工作目录
    home_dir: str              # 用户主目录
    date: str                  # 当前日期 YYYY-MM-DD
    python_version: str        # Python 版本
    python_executable: str     # Python 可执行文件路径
    virtual_env: str | None    # 虚拟环境路径
    is_git_repo: bool          # 是否在 Git 仓库中
    git_branch: str | None     # 当前分支名
    hostname: str              # 主机名
    extra: dict[str, str]     # 额外信息
```

**OS 检测策略**:
- Linux: 尝试 `distro` 库, 回退到 `platform.release()`
- macOS: `platform.mac_ver()[0]`
- Windows: `platform.version()`

**Shell 检测**: `SHELL` 环境变量 → 回退到 PATH 中的 `bash/zsh/fish/sh`

**虚拟环境**: `VIRTUAL_ENV` 环境变量 → 回退到检测 `pyvenv.cfg`

### 在系统提示词中的呈现

```
# Environment
- OS: Windows 10.0.26200
- Architecture: AMD64
- Shell: bash
- Working directory: D:\python-projects\openherness\OpenHarness
- Date: 2026-04-15
- Python: 3.12.0
- Python executable: D:\python-projects\openherness\OpenHarness\.venv\Scripts\python.exe
- Virtual environment: D:\python-projects\openherness\OpenHarness\.venv
- Git: yes (branch: dev_debug)
```

---

## 6. Personalization — 自动学习环境规则

### 架构

```
对话会话
  │
  │  会话结束时
  ▼
update_rules_from_session(messages)
  │
  ├── extract_facts_from_text(combined_text)
  │   ├── SSH 连接: ssh user@host
  │   ├── IP 地址: \d+\.\d+\.\d+\.\d+
  │   ├── 数据路径: /ext|mnt|home|data/.../data|landing|derived|reference/
  │   ├── Conda 环境: conda activate XXX
  │   ├── Python 版本: Python 3.x.x
  │   ├── API 端点: https?://... /v\d+/
  │   ├── 环境变量: export KEY=VALUE
  │   ├── Git Remote: github.com:user/repo
  │   ├── Ray 集群: ray start/init/submit
  │   └── Cron 调度: 分 时 日 月 周 命令
  │
  ├── merge_facts(existing, new_facts)
  │   └── 按 key 去重, 高置信度优先
  │
  ├── save_facts(merged)       → ~/.openharness/local_rules/facts.json
  └── save_local_rules(md)    → ~/.openharness/local_rules/rules.md
```

### 事实提取模式

| 类型 | 标签 | 正则模式 | 置信度 |
|------|------|----------|--------|
| `ssh_host` | SSH Hosts | `ssh\s+(?:-[io]\s+\S+\s+)*(\S+@[\d.]+\|\S+@\S+)` | 0.7 |
| `ip_address` | Known Servers | `\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}` (排除 0.x, 255.x, 127.0.0.1) | 0.7 |
| `data_path` | Data Paths | `/(?:ext\|mnt\|home\|data\|root)\S*/(?:data\S*\|landing\|derived\|reference)\S*` | 0.7 |
| `conda_env` | Python Environments | `conda\s+activate\s+(\S+)` | 0.7 |
| `python_env` | Python Versions | `[Pp]ython\s*(3\.\d+(?:\.\d+)?)` | 0.7 |
| `api_endpoint` | API Endpoints | `https?://\S+/v\d+/?\b` | 0.7 |
| `env_var` | Environment Variables | `export\s+([A-Z][A-Z0-9_]+=\S+)` | 0.7 |
| `git_remote` | Git Repositories | `(?:github\|gitlab)\.com[:/](\S+?)(?:\.git)?` | 0.7 |
| `ray_cluster` | Ray Cluster Config | `ray\s+(?:start\|init\|submit)\b.*?(--address\s+\S+\|\d+\.\d+\.\d+\.\d+:\d+)` | 0.7 |
| `cron_schedule` | Scheduled Jobs | `((?:\d+\|\*)\s+){4}(?:\d+\|\*)\s+\S+` | 0.7 |

### 事实去重与合并

```python
def merge_facts(existing, new_facts):
    by_key = {}
    # 旧事实先入 dict
    for f in existing.get("facts", []):
        by_key[f["key"]] = f
    # 新事实覆盖旧事实 (同 key 且置信度 >=)
    for f in new_facts:
        if f["key"] in by_key:
            if f.get("confidence", 0) >= by_key[f["key"]].get("confidence", 0):
                by_key[f["key"]] = f
        else:
            by_key[f["key"]] = f
    return {"facts": list(by_key.values())}
```

### 输出文件

```json
// ~/.openharness/local_rules/facts.json
{
  "facts": [
    {"key": "git_remote:user/openharness", "type": "git_remote", "label": "Git Repositories", "value": "user/openharness", "confidence": 0.7},
    {"key": "python_env:3.12.0", "type": "python_env", "label": "Python Versions", "value": "3.12.0", "confidence": 0.7}
  ],
  "last_updated": "2026-04-15T08:30:00+00:00"
}
```

```markdown
# Local Environment Rules

*Auto-generated from session history. Do not edit manually.*

## Git Repositories

- `user/openharness`

## Python Versions

- `3.12.0`
```

---

## 7. 基础系统提示词 — _BASE_SYSTEM_PROMPT

系统提示词的固定部分 (~1500 字符), 定义了 OpenHarness 的核心行为规范:

### 核心原则

| 类别 | 原则 |
|------|------|
| **身份** | "You are OpenHarness, an open-source AI coding assistant CLI" |
| **安全** | 不猜测 URL, 检测外部数据注入 |
| **工具优先** | Read > cat, Edit > sed, Glob > find, Grep > grep |
| **并发** | 独立调用可并行, 依赖调用必须顺序 |
| **风格** | 简洁, 直接给答案, 先说结论 |
| **安全** | 不引入 OWASP Top 10 漏洞, 不做超出要求的改动 |
| **谨慎** | 难以逆转的操作先确认; 本地可逆操作可自由执行 |

### 组装逻辑

```python
def build_system_prompt(custom_prompt=None, env=None, cwd=None):
    base = custom_prompt if custom_prompt is not None else _BASE_SYSTEM_PROMPT
    env_section = _format_environment_section(env or get_environment_info(cwd))
    return f"{base}\n\n{env_section}"
```

**`custom_prompt`** 可以完全替换基础提示词, 通过 `settings.system_prompt` 配置。

---

## 8. 运行时系统提示词的完整组成

`build_runtime_system_prompt()` 组装的最终系统提示词由以下 section 按顺序拼接:

| # | Section | 来源 | 条件 |
|---|---------|------|------|
| 1 | 基础提示词 + 环境 | `system_prompt.py` | 始终 |
| 2 | Fast Mode 标记 | `context.py` | `settings.fast_mode=True` |
| 3 | Reasoning Settings | `context.py` | 始终 |
| 4 | Available Skills | `skills/` | 有 Skill 时 |
| 5 | Delegation & Subagents | `context.py` | 非 Coordinator 模式 |
| 6 | Project Instructions | `claudemd.py` | 有 CLAUDE.md 时 |
| 7 | Local Environment Rules | `personalization/rules.py` | 有规则时 |
| 8 | Issue Context | `.openharness/issue.md` | 文件存在时 |
| 9 | PR Comments Context | `.openharness/pr_comments.md` | 文件存在时 |
| 10 | Memory Index | `memory/memdir.py` | `settings.memory.enabled=True` |
| 11 | Relevant Memories | `memory/search.py` | 启用 Memory + 有最新用户消息 |

**Section 之间用 `\n\n` 连接, 空 section 被过滤掉。**

---

## 9. 知识系统的三层架构

```
┌─────────────────────────────────────────────┐
│  Layer 3: 动态知识 (每次请求注入)           │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │ Relevant Memory │  │ Issue/PR Context │  │
│  │ (基于最新消息   │  │ (项目级上下文)    │  │
│  │  搜索)          │  │                  │  │
│  └─────────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────┤
│  Layer 2: 项目知识 (CLAUDE.md + 规则)       │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │ CLAUDE.md       │  │ Local Rules      │  │
│  │ (项目级指令,    │  │ (自动提取的      │  │
│  │  向上遍历目录)  │  │  环境事实)       │  │
│  └─────────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────┤
│  Layer 1: 系统基础 (始终存在)               │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │ System Prompt   │  │ Environment Info │  │
│  │ (核心行为规范)  │  │ (OS/Shell/Git)   │  │
│  └─────────────────┘  └──────────────────┘  │
│  ┌─────────────────┐  ┌──────────────────┐  │
│  │ Skills List     │  │ Delegation Guide │  │
│  │ (可用 Skill)    │  │ (子 Agent 指南)  │  │
│  └─────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────┘
```

**设计意图**:
- **Layer 1** 是不变的框架, 定义 Agent 的基本行为
- **Layer 2** 是项目级上下文, 在同一项目中一致
- **Layer 3** 是动态上下文, 根据每次对话内容变化

---

## 10. 记忆 vs Skill vs CLAUDE.md — 三种知识形态对比

| 方面 | Memory | Skill | CLAUDE.md |
|------|--------|-------|-----------|
| 存储位置 | `~/.openharness/data/memory/<hash>/` | `~/.openharness/skills/<name>/SKILL.md` | 项目根目录 `.claude/` |
| 作用域 | 项目级 (按路径哈希隔离) | 全局 + 项目级 | 项目级 (向上遍历) |
| 注入方式 | 动态搜索 + 相关片段 | 名称列表 + 按需加载 | 全文注入 |
| 更新方式 | 用户 `/memory add` 或自动提取 | 手动创建 `.md` 文件 | 手动编辑 |
| 持久性 | 跨会话持久 | 跨会话持久 | Git 跟踪 |
| 大小限制 | 单文件 8000 字符, 索引 200 行 | 单文件 12000 字符 | 单文件 12000 字符 |
| 搜索方式 | 启发式关键词匹配 | 精确名称 | 无搜索, 全文加载 |

---

## 11. 完整数据流: 用户消息 → 系统提示词组装

```
1. 用户输入: "帮我重构 auth 模块"

2. ui/app.py: handle_line(user_message)
   → build_runtime_system_prompt(settings, cwd, latest_user_prompt=user_message)

3. build_runtime_system_prompt():
   3a. 基础提示词 + 环境信息
   3b. Fast Mode 标记 (如果启用)
   3c. Reasoning Settings (effort=medium, passes=1)
   3d. Skills 列表 (列出所有可用 Skill 名+描述)
   3e. Delegation 指南
   3f. CLAUDE.md (发现并加载项目指令)
   3g. Local Rules (自动提取的环境事实)
   3h. Issue Context (如果有)
   3i. PR Comments (如果有)
   3j. Memory Index (MEMORY.md)
   3k. Relevant Memories (搜索 "帮我重构 auth 模块" → 匹配含 "auth" 的记忆文件)

4. 组装后的 system_prompt (可能数万字符) + 对话历史
   → api_client.stream_message(ApiMessageRequest(model=..., messages=..., system_prompt=assembled))

5. 会话结束时:
   → update_rules_from_session(messages)
   → 提取环境事实 (SSH, IP, Git Remote 等)
   → 合并到 ~/.openharness/local_rules/facts.json
   → 重新生成 ~/.openharness/local_rules/rules.md
   → 下次会话: Local Rules section 包含更新后的规则
```

---

## 12. 安全考虑

### CLAUDE.md 路径遍历防护
- `discover_claude_md_files()` 使用 `Path.resolve()` 和 `seen` 集合防止重复加载
- 每个文件最多 12000 字符截断

### Memory 路径遍历防护
- `add_memory_entry()` 使用 `slug` 生成安全文件名 (非字母数字变 `_`)
- `_resolve_memory_entry_path()` 在 `/memory` 命令中强制路径在 `memory_dir` 下
- 使用 `exclusive_file_lock + atomic_write_text` 保证并发安全

### Personalization 事实提取
- IP 地址过滤: 排除 `0.x`, `255.x`, `127.0.0.1` 等常见误匹配
- 所有事实存储在 `~/.openharness/local_rules/` (本地, 不上传)
- 事实去重使用 `key` 字段, 防止重复积累

### Skill 加载安全
- Skill 内容直接注入系统提示词, 但只有描述 (不含完整内容) 在系统提示词中
- 完整 Skill 内容在用户主动调用时才加载到对话
- Plugin Skill 需要插件 `enabled=True` 才会被加载