# OpenHarness 知识与记忆模块 -- 详细设计文档

## 1. 模块概述

知识与记忆模块是 OpenHarness 的核心认知基础设施，负责将系统指令、项目知识、持久记忆和个性化规则组装为运行时系统提示词（System Prompt），使 AI 助手具备上下文感知和跨会话记忆能力。

### 1.1 三层知识架构

系统采用分层知识架构，由底至顶依次为：

| 层级 | 名称 | 来源 | 生命周期 | 典型内容 |
|------|------|------|----------|----------|
| **Layer 1** | 系统基座 | 硬编码 + 环境检测 | 始终存在 | `_BASE_SYSTEM_PROMPT` + 环境信息 + 技能列表 + 委派指南 |
| **Layer 2** | 项目知识 | 文件系统扫描 | 项目级持久 | `CLAUDE.md`（向上目录遍历）+ 本地规则（自动提取事实） |
| **Layer 3** | 动态知识 | 运行时检索 | 会话级动态 | 相关记忆（基于最新消息的关键词搜索）+ Issue/PR 上下文 |

### 1.2 模块关系总览

```
prompts/
  system_prompt.py  ─── Layer 1 基座提示词 + 环境段
  environment.py    ─── 环境检测（OS/Shell/Git 等）
  claudemd.py       ─── Layer 2 CLAUDE.md 发现与加载
  context.py        ─── 运行时系统提示词组装入口（11 段拼接）

skills/
  types.py          ─── SkillDefinition 数据模型
  registry.py       ─── 技能注册表
  loader.py         ─── 技能加载（Bundled → User → Extra → Plugin）

memory/
  types.py          ─── MemoryHeader 数据模型
  paths.py          ─── 项目记忆目录路径解析
  manager.py        ─── 记忆条目增删（原子写入 + 文件锁）
  scan.py           ─── 记忆文件扫描与解析
  search.py         ─── 启发式关键词搜索
  memdir.py         ─── 记忆提示段生成

personalization/
  rules.py          ─── 本地规则持久化
  extractor.py      ─── 事实提取（10 种模式）
  session_hook.py   ─── 会话结束时自动提取与合并
```

---

## 2. 核心类/接口

### 2.1 SkillDefinition（`skills/types.py`）

不可变数据类，描述一个已加载的技能。

```python
@dataclass(frozen=True)
class SkillDefinition:
    name: str             # 技能唯一名称，用于 skill tool 调用
    description: str      # 一行描述，出现在系统提示词的技能列表中
    content: str          # 完整 Markdown 内容，仅在 /skill 调用时加载
    source: str           # 来源标记："bundled" | "user" | "plugin"
    path: str | None      # 源文件绝对路径（可选）
```

**设计约束**：系统提示词仅列出 `name` + `description`，完整 `content` 在用户通过 `skill` 工具显式调用时才注入对话，避免提示词膨胀。

### 2.2 SkillRegistry（`skills/registry.py`）

技能注册表，以名称为键存储 `SkillDefinition`，支持注册、查询、列表。

```python
class SkillRegistry:
    def register(self, skill: SkillDefinition) -> None
    def get(self, name: str) -> SkillDefinition | None
    def list_skills(self) -> list[SkillDefinition]  # 按 name 排序
```

**覆盖语义**：后注册的同名技能覆盖先注册的，因此加载顺序决定了优先级（Bundled > User > Extra > Plugin）。

### 2.3 MemoryHeader（`memory/types.py`）

不可变数据类，记忆文件的元数据头部，用于搜索和索引展示。

```python
@dataclass(frozen=True)
class MemoryHeader:
    path: Path              # 记忆文件路径
    title: str              # 标题（来自 frontmatter name 或文件名）
    description: str        # 描述（来自 frontmatter description 或首行内容）
    modified_at: float       # mtime 时间戳
    memory_type: str = ""   # frontmatter type 字段
    body_preview: str = ""  # 正文预览（最多 300 字符）
```

### 2.4 EnvironmentInfo（`prompts/environment.py`）

运行时环境快照，用于构建系统提示词的环境信息段。

```python
@dataclass
class EnvironmentInfo:
    os_name: str
    os_version: str
    platform_machine: str
    shell: str
    cwd: str
    home_dir: str
    date: str
    python_version: str
    python_executable: str
    virtual_env: str | None
    is_git_repo: bool
    git_branch: str | None
    hostname: str
    extra: dict[str, str]
```

---

## 3. 数据模型

### 3.1 系统提示词组装模型（11 段顺序）

`build_runtime_system_prompt()` 将以下 11 个段落按序拼接为最终系统提示词：

| 段序 | 名称 | 来源模块 | 所属层级 | 条件 |
|------|------|----------|----------|------|
| 1 | 基座提示词 + 环境信息 | `system_prompt.py` | Layer 1 | 始终 |
| 2 | Fast Mode 标记 | `context.py` | Layer 1 | `settings.fast_mode == True` |
| 3 | 推理设置（Effort/Passes） | `context.py` | Layer 1 | 始终 |
| 4 | 可用技能列表 | `context.py → _build_skills_section()` | Layer 1 | 非协调模式且有技能 |
| 5 | 委派与子代理指南 | `context.py → _build_delegation_section()` | Layer 1 | 非协调模式 |
| 6 | 项目指令（CLAUDE.md） | `claudemd.py → load_claude_md_prompt()` | Layer 2 | 存在 CLAUDE.md 文件 |
| 7 | 本地环境规则 | `personalization/rules.py → load_local_rules()` | Layer 2 | 存在提取事实 |
| 8 | Issue 上下文 | `context.py` | Layer 3 | `.openharness/issue.md` 存在且非空 |
| 9 | PR 评论上下文 | `context.py` | Layer 3 | `.openharness/pr_comments.md` 存在且非空 |
| 10 | 记忆索引段 | `memdir.py → load_memory_prompt()` | Layer 3 | `settings.memory.enabled` |
| 11 | 相关记忆段 | `search.py → find_relevant_memories()` | Layer 3 | `memory.enabled` 且有最新用户消息 |

**拼接规则**：非空段落以 `"\n\n"` 分隔连接，空段落跳过。

### 3.2 技能来源优先级模型

```
Bundled（内置） > User（用户目录） > Extra Dirs（额外目录） > Plugin（插件）
```

| 来源 | source 值 | 路径 | 优先级 |
|------|-----------|------|--------|
| Bundled | `"bundled"` | `openharness/skills/bundled/content/*.md` | 最高 |
| User | `"user"` | `~/.openharness/skills/<name>/SKILL.md` | 高 |
| Extra Dirs | `"user"` | 调用方传入的 `extra_skill_dirs` | 中 |
| Plugin | `"plugin"` | 插件 manifest 中 `skills_dir` 指定的目录 | 低 |

同名技能后注册覆盖先注册，因此 Bundled 技能不可被用户覆盖，User 技能可覆盖 Plugin 技能。

### 3.3 记忆存储模型

**目录结构**：
```
~/.openharness/data/memory/<project-name>-<sha1-hash>/
├── MEMORY.md              # 索引文件（最多 200 行）
├── .memory.lock            # 独占文件锁
├── database_design.md      # 记忆条目（Markdown）
├── deployment_steps.md
└── ...
```

**路径生成算法**：
1. 取 `cwd` 的绝对路径字符串
2. 计算 SHA-1 哈希，取前 12 位
3. 目录名 = `{path.name}-{digest}`，其中 `path.name` 是 cwd 的最后一级目录名

**MEMORY.md 索引格式**：
```markdown
# Memory Index
- [数据库设计](database_design.md)
- [部署步骤](deployment_steps.md)
```

### 3.4 CLAUDE.md 发现模型

从 `cwd` 向上遍历目录树，每级目录检查以下位置：

```
directory/CLAUDE.md
directory/.claude/CLAUDE.md
directory/.claude/rules/*.md     # 规则目录下所有 .md 文件
```

遍历在到达文件系统根目录时停止。使用 `seen: set[Path]` 防止符号链接导致的重复。

### 3.5 个性化事实模型

10 种事实类型及其正则模式：

| 类型 | 标签 | 检测模式示例 |
|------|------|-------------|
| `ssh_host` | SSH Hosts | `ssh user@host` |
| `ip_address` | Known Servers | IPv4 地址（排除 0./255./127.0.0.1） |
| `data_path` | Data Paths | `/ext|/mnt|/home|/data|/root` 下的数据路径 |
| `conda_env` | Python Environments | `conda activate <env>` |
| `python_env` | Python Versions | `Python 3.x.y` |
| `api_endpoint` | API Endpoints | `https://.../vN/` |
| `env_var` | Environment Variables | `export KEY=VALUE` |
| `git_remote` | Git Repositories | `github.com:/repo` |
| `ray_cluster` | Ray Cluster Config | `ray start/init --address` |
| `cron_schedule` | Scheduled Jobs | cron 表达式 |

**事实数据结构**：
```json
{
  "key": "ip_address:192.168.1.100",
  "type": "ip_address",
  "label": "Known Servers",
  "value": "192.168.1.100",
  "confidence": 0.7
}
```

**持久化文件**：
- `~/.openharness/local_rules/facts.json` -- 事实 JSON
- `~/.openharness/local_rules/rules.md` -- 生成的 Markdown 规则文档

---

## 4. 关键算法

### 4.1 系统提示词组装算法（`context.py: build_runtime_system_prompt`）

```
输入: Settings, cwd, latest_user_prompt, extra_skill_dirs, extra_plugin_roots
输出: 完整系统提示词字符串

1. IF 协调模式:
     sections ← [coordinator_system_prompt]
   ELSE:
     sections ← [build_system_prompt(custom_prompt, cwd)]

2. IF fast_mode:  sections.append(Fast Mode 段)
3. sections.append(Reasoning Settings 段)  # 始终

4. skills_section ← _build_skills_section(cwd, ...)
   IF skills_section 非空 AND 非协调模式: sections.append(skills_section)
5. IF 非协调模式: sections.append(Delegation 段)

6. claude_md ← load_claude_md_prompt(cwd)
   IF claude_md: sections.append(claude_md)

7. local_rules ← load_local_rules()
   IF local_rules: sections.append(Local Rules 段)

8. FOR (title, path) IN [("Issue Context", issue_path), ("PR Comments", pr_path)]:
     IF path.exists() AND content 非空: sections.append(截断至 12000 字符)

9. IF memory.enabled:
     sections.append(load_memory_prompt(cwd))
     IF latest_user_prompt 非空:
       relevant ← find_relevant_memories(latest_user_prompt, cwd)
       IF relevant: sections.append(Relevant Memories 段, 每文件截断至 8000 字符)

10. RETURN "\n\n".join(非空 sections)
```

### 4.2 技能加载算法（`loader.py: load_skill_registry`）

```
输入: cwd, extra_skill_dirs, extra_plugin_roots, settings
输出: SkillRegistry

registry ← SkillRegistry()

1. FOR skill IN get_bundled_skills():        registry.register(skill)  # 最高优先级
2. FOR skill IN load_user_skills():          registry.register(skill)  # 用户目录
3. FOR skill IN load_skills_from_dirs(extra): registry.register(skill)  # 额外目录
4. IF cwd 非空:
     FOR plugin IN load_plugins(settings, cwd):
       IF plugin.enabled:
         FOR skill IN plugin.skills:         registry.register(skill)  # 最低优先级

RETURN registry
```

**文件格式解析**（`_parse_skill_markdown`）：
1. 优先解析 YAML frontmatter（`---\n` 开头，`\n---\n` 结束），提取 `name` 和 `description`
2. YAML 解析失败时，回退到 Markdown 标题（`# heading`）作为 name，首个非标题非空行作为 description
3. 若均无结果，description 默认为 `"Skill: {name}"`

**目录扫描规则**（`load_skills_from_dirs`）：
- 每个根目录下，遍历子目录
- 每个子目录中查找 `SKILL.md` 文件
- 使用 `seen: set[Path]` 跳过重复路径

### 4.3 记忆条目写入算法（`manager.py: add_memory_entry`）

```
输入: cwd, title, content
输出: 写入的文件路径 Path

1. slug ← 正则替换 title: 非字母数字 → "_"，转小写，去首尾下划线
   IF slug 为空: slug ← "memory"
2. path ← memory_dir / f"{slug}.md"

3. WITH exclusive_file_lock(memory_dir / ".memory.lock"):  # 互斥锁
   a. atomic_write_text(path, content.strip() + "\n")       # 原子写入
   b. entrypoint ← MEMORY.md
   c. existing ← entrypoint.read_text() 或 "# Memory Index\n"
   d. IF path.name NOT IN existing:
        existing ← existing.rstrip() + f"\n- [{title}]({path.name})\n"
        atomic_write_text(entrypoint, existing)

RETURN path
```

**关键保证**：
- **互斥安全**：`exclusive_file_lock` 保证多进程并发安全
- **崩溃安全**：`atomic_write_text` 使用 temp+rename 模式，崩溃不会留下截断文件
- **幂等性**：若文件名已存在于 MEMORY.md 索引中，不重复添加

### 4.4 记忆搜索算法（`search.py: find_relevant_memories`）

```
输入: query, cwd, max_results=5
输出: 按相关度排序的 MemoryHeader 列表

1. tokens ← _tokenize(query)
   - ASCII 词元: re.findall(r"[A-Za-z0-9_]+", query.lower())，长度 ≥ 3
   - CJK 字符: re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", query)，每个汉字独立作为词元

2. FOR header IN scan_memory_files(cwd, max_files=100):
     meta ← f"{header.title} {header.description}".lower()
     body ← header.body_preview.lower()
     meta_hits ← COUNT(t IN tokens WHERE t IN meta)
     body_hits ← COUNT(t IN tokens WHERE t IN body)
     score ← meta_hits × 2.0 + body_hits × 1.0
     IF score > 0: scored.append((score, header))

3. scored.sort(by=(-score, -modified_at))  # 先按分数降序，同分按时间降序
4. RETURN top max_results headers
```

**评分权重**：元数据（title + description）权重 2 倍于正文，确保标注良好的记忆优先展示。

### 4.5 CLAUDE.md 发现算法（`claudemd.py: discover_claude_md_files`）

```
输入: cwd
输出: 有序 Path 列表

current ← Path(cwd).resolve()
results ← []
seen ← set()

FOR directory IN [current, *current.parents]:
  FOR candidate IN [directory/CLAUDE.md, directory/.claude/CLAUDE.md]:
    IF candidate.exists() AND candidate NOT IN seen:
      results.append(candidate); seen.add(candidate)

  rules_dir ← directory/.claude/rules
  IF rules_dir.is_dir():
    FOR rule IN sorted(rules_dir.glob("*.md")):
      IF rule NOT IN seen: results.append(rule); seen.add(rule)

  IF directory.parent == directory: BREAK  # 到达根目录

RETURN results
```

**加载截断**：每个文件最大 12000 字符，超出部分替换为 `...[truncated]...`。

### 4.6 个性化事实提取算法（`extractor.py: extract_facts_from_text`）

```
输入: text
输出: 事实字典列表

facts ← []
seen_keys ← set()

FOR (fact_type, label, pattern) IN _FACT_PATTERNS:
  FOR match IN pattern.finditer(text):
    value ← match.group(1) 或 match.group(0)
    value ← 去除尾部标点，strip

    # IP 过滤
    IF fact_type == "ip_address" AND value 以 "0."/"255."/"127.0.0.1" 开头: SKIP

    key ← f"{fact_type}:{value}"
    IF key IN seen_keys: SKIP
    seen_keys.add(key)

    facts.append({key, type, label, value, confidence: 0.7})

RETURN facts
```

**IP 过滤规则**：排除私有/保留地址段（0.x、255.x、127.0.0.1），减少误报。

### 4.7 事实合并算法（`rules.py: merge_facts`）

```
输入: existing: dict, new_facts: list[dict]
输出: 合并后 facts dict

by_key ← {f["key"]: f FOR f IN existing["facts"]}

FOR f IN new_facts:
  key ← f["key"]
  IF key IN by_key:
    old ← by_key[key]
    IF f.confidence >= old.confidence:  # 置信度优先
      by_key[key] ← f                   # 保留更高置信度的值
  ELSE:
    by_key[key] ← f

RETURN {"facts": list(by_key.values())}
```

**去重策略**：以 `key`（`type:value`）为唯一标识，相同 key 保留更高 confidence 的事实。

---

## 5. 接口规范

### 5.1 skills 模块

#### `skills/types.py`

| 成员 | 类型 | 说明 |
|------|------|------|
| `SkillDefinition.name` | `str` | 技能唯一标识名 |
| `SkillDefinition.description` | `str` | 一行摘要 |
| `SkillDefinition.content` | `str` | 完整 Markdown 内容 |
| `SkillDefinition.source` | `str` | `"bundled"` / `"user"` / `"plugin"` |
| `SkillDefinition.path` | `str \| None` | 源文件路径 |

#### `skills/registry.py`

| 方法 | 签名 | 说明 |
|------|------|------|
| `register` | `(skill: SkillDefinition) -> None` | 注册/覆盖技能 |
| `get` | `(name: str) -> SkillDefinition \| None` | 按名查询 |
| `list_skills` | `() -> list[SkillDefinition]` | 全部技能，按 name 排序 |

#### `skills/loader.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_user_skills_dir` | `() -> Path` | 返回 `~/.openharness/skills/`，自动创建 |
| `load_skill_registry` | `(cwd, *, extra_skill_dirs, extra_plugin_roots, settings) -> SkillRegistry` | 加载全部来源技能 |
| `load_user_skills` | `() -> list[SkillDefinition]` | 仅加载用户目录技能 |
| `load_skills_from_dirs` | `(directories, *, source="user") -> list[SkillDefinition]` | 从指定目录加载 |

### 5.2 memory 模块

#### `memory/types.py`

| 成员 | 类型 | 说明 |
|------|------|------|
| `MemoryHeader.path` | `Path` | 文件路径 |
| `MemoryHeader.title` | `str` | 标题 |
| `MemoryHeader.description` | `str` | 描述 |
| `MemoryHeader.modified_at` | `float` | 修改时间戳 |
| `MemoryHeader.memory_type` | `str` | frontmatter type（默认空） |
| `MemoryHeader.body_preview` | `str` | 正文预览（默认空，最多 300 字符） |

#### `memory/paths.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_project_memory_dir` | `(cwd: str \| Path) -> Path` | 返回 `~/.openharness/data/memory/<name>-<hash>/` |
| `get_memory_entrypoint` | `(cwd: str \| Path) -> Path` | 返回 `MEMORY.md` 路径 |

#### `memory/manager.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `list_memory_files` | `(cwd) -> list[Path]` | 列出所有 .md 记忆文件 |
| `add_memory_entry` | `(cwd, title: str, content: str) -> Path` | 创建记忆条目并更新索引 |
| `remove_memory_entry` | `(cwd, name: str) -> bool` | 删除条目并移除索引，成功返回 True |

#### `memory/scan.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `scan_memory_files` | `(cwd, *, max_files=50) -> list[MemoryHeader]` | 扫描记忆文件，按修改时间降序 |

#### `memory/search.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `find_relevant_memories` | `(query, cwd, *, max_results=5) -> list[MemoryHeader]` | 启发式关键词搜索 |

#### `memory/memdir.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_memory_prompt` | `(cwd, *, max_entrypoint_lines=200) -> str \| None` | 生成记忆提示段 |

### 5.3 prompts 模块

#### `prompts/system_prompt.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_base_system_prompt` | `() -> str` | 返回 `_BASE_SYSTEM_PROMPT` 常量 |
| `build_system_prompt` | `(custom_prompt=None, env=None, cwd=None) -> str` | 构建基座 + 环境信息 |

#### `prompts/environment.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `detect_os` | `() -> tuple[str, str]` | 检测 OS 名称和版本 |
| `detect_shell` | `() -> str` | 检测用户 Shell |
| `detect_git_info` | `(cwd) -> tuple[bool, str \| None]` | 检测 Git 状态和分支 |
| `get_environment_info` | `(cwd=None) -> EnvironmentInfo` | 聚合全部环境信息 |

#### `prompts/claudemd.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `discover_claude_md_files` | `(cwd) -> list[Path]` | 向上遍历发现 CLAUDE.md |
| `load_claude_md_prompt` | `(cwd, *, max_chars_per_file=12000) -> str \| None` | 加载为提示词段落 |

#### `prompts/context.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `build_runtime_system_prompt` | `(settings, *, cwd, latest_user_prompt, extra_skill_dirs, extra_plugin_roots) -> str` | 运行时提示词组装入口 |

### 5.4 personalization 模块

#### `personalization/rules.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_local_rules` | `() -> str` | 加载 rules.md，不存在返回空串 |
| `save_local_rules` | `(content: str) -> Path` | 写入 rules.md |
| `load_facts` | `() -> dict` | 加载 facts.json |
| `save_facts` | `(facts: dict) -> None` | 持久化 facts.json |
| `merge_facts` | `(existing, new_facts) -> dict` | 去重合并，置信度优先 |

#### `personalization/extractor.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `extract_facts_from_text` | `(text: str) -> list[dict]` | 从文本提取事实 |
| `extract_local_rules` | `(session_messages: list[dict]) -> list[dict]` | 从消息列表提取事实 |
| `facts_to_rules_markdown` | `(facts: list[dict]) -> str` | 事实转 Markdown 文档 |

#### `personalization/session_hook.py`

| 函数 | 签名 | 说明 |
|------|------|------|
| `update_rules_from_session` | `(messages: list[ConversationMessage]) -> int` | 会话结束时提取并持久化，返回新增事实数 |

---

## 6. 错误处理

### 6.1 技能加载

| 场景 | 处理方式 |
|------|----------|
| YAML frontmatter 解析失败 | `logger.debug` 记录，回退到 Markdown 标题解析 |
| 技能目录不存在 | `mkdir(parents=True, exist_ok=True)` 自动创建 |
| 技能文件读取失败 | 由 Python IO 层抛出异常，上层捕获 |
| 重复技能路径 | `seen: set[Path]` 去重，跳过已加载文件 |

### 6.2 记忆系统

| 场景 | 处理方式 |
|------|----------|
| 记忆目录不存在 | `mkdir(parents=True, exist_ok=True)` 自动创建 |
| 记忆文件读取失败（scan） | `except OSError: continue` 跳过该文件 |
| 记忆文件写入冲突 | `exclusive_file_lock` 保证互斥，`atomic_write_text` 保证原子性 |
| 文件锁获取失败 | `SwarmLockError` / `SwarmLockUnavailableError` 向上传播 |
| 不支持的平台文件锁 | `SwarmLockUnavailableError` 异常 |
| MEMORY.md 不存在 | 使用默认 `# Memory Index\n` 作为起始内容 |
| 搜索无结果 | 返回空列表 `[]` |

### 6.3 CLAUDE.md 发现

| 场景 | 处理方式 |
|------|----------|
| 文件不存在 | 跳过，不报错 |
| 文件编码问题 | `errors="replace"` 容错读取 |
| 文件超过 12000 字符 | 截断并追加 `...[truncated]...` |
| 符号链接循环 | `seen: set[Path]` 防止重复 |

### 6.4 环境检测

| 场景 | 处理方式 |
|------|----------|
| `git` 命令不存在 | `FileNotFoundError` 捕获，返回 `(False, None)` |
| `git` 命令超时 | 5 秒超时，`TimeoutExpired` 捕获，返回 `(False, None)` |
| `distro` 包未安装 | `ImportError` 捕获，回退到 `platform.release()` |
| Shell 环境变量未设置 | 遍历 PATH 检测常见 shell，最终返回 `"unknown"` |

### 6.5 个性化提取

| 场景 | 处理方式 |
|------|----------|
| 无匹配事实 | 返回空列表 |
| IP 误报（0.x/255.x/127.0.0.1） | 硬编码过滤 |
| 事实值过短（< 3 字符） | 跳过 |
| facts.json 损坏/不存在 | 返回 `{"facts": [], "last_updated": None}` |

---

## 7. 配置项

### 7.1 MemorySettings（`config/settings.py`）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | `bool` | `True` | 是否启用记忆系统 |
| `max_files` | `int` | `5` | 搜索返回的最大记忆文件数 |
| `max_entrypoint_lines` | `int` | `200` | MEMORY.md 在提示词中的最大行数 |
| `context_window_tokens` | `int \| None` | `None` | 上下文窗口令牌数（未使用） |
| `auto_compact_threshold_tokens` | `int \| None` | `None` | 自动压缩阈值（未使用） |

### 7.2 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENHARNESS_CONFIG_DIR` | 配置目录 | `~/.openharness/` |
| `OPENHARNESS_DATA_DIR` | 数据目录 | `~/.openharness/data/` |
| `OPENHARNESS_LOGS_DIR` | 日志目录 | `~/.openharness/logs/` |
| `SHELL` | 用户 Shell | 检测 fallback |
| `VIRTUAL_ENV` | Python 虚拟环境路径 | 自动检测 |

### 7.3 硬编码常量

| 常量 | 值 | 位置 | 说明 |
|------|-----|------|------|
| `_BASE_SYSTEM_PROMPT` | ~2KB 文本 | `system_prompt.py` | 基座系统提示词 |
| `max_chars_per_file` (CLAUDE.md) | `12000` | `claudemd.py` | 单文件最大字符数 |
| `body_preview` 最大长度 | `300` 字符 | `scan.py` | 记忆正文预览截断 |
| 记忆单文件内容截断 | `8000` 字符 | `context.py` | 相关记忆段单文件上限 |
| Issue/PR 内容截断 | `12000` 字符 | `context.py` | Issue/PR 上下文上限 |
| MEMORY.md 最大行数 | `200` | `memdir.py` / 设置 | 索引文件展示行数 |
| `scan_memory_files` 默认上限 | `50` | `scan.py` | 扫描文件数上限 |
| `find_relevant_memories` 扫描上限 | `100` | `search.py` | 搜索扫描的文件数 |
| 事实置信度 | `0.7` | `extractor.py` | 所有提取事实的默认置信度 |
| git 命令超时 | `5` 秒 | `environment.py` | Git 检测超时 |

---

## 8. 与其它模块的交互

### 8.1 模块依赖关系图

```
prompts/context.py (顶层组装器)
  ├── prompts/system_prompt.py
  │     └── prompts/environment.py
  ├── prompts/claudemd.py
  ├── skills/loader.py
  │     ├── skills/types.py
  │     ├── skills/registry.py
  │     ├── skills/bundled/__init__.py
  │     ├── config/paths.py
  │     ├── config/settings.py
  │     └── plugins/loader.py → plugins/types.py
  ├── memory/
  │     ├── memdir.py → paths.py
  │     ├── search.py → scan.py → paths.py, types.py
  │     └── manager.py → paths.py, utils/file_lock.py, utils/fs.py
  ├── personalization/
  │     ├── rules.py
  │     ├── extractor.py
  │     └── session_hook.py → extractor.py, rules.py
  └── config/paths.py (project_issue_file, project_pr_comments_file)
```

### 8.2 与 config 模块的交互

- **config/paths.py**：提供 `get_config_dir()`（用户技能目录）、`get_data_dir()`（记忆数据目录）、`get_project_issue_file()` / `get_project_pr_comments_file()`（Issue/PR 上下文文件）
- **config/settings.py**：提供 `Settings` 和 `MemorySettings`，控制系统提示词组装行为（fast_mode、effort/passes、memory 开关等）

### 8.3 与 plugins 模块的交互

- `skills/loader.py` 在 `load_skill_registry()` 中调用 `plugins.loader.load_plugins()` 加载插件
- `LoadedPlugin.skills` 是 `list[SkillDefinition]`，由插件的 `skills_dir` 目录加载而来
- 插件技能的 `source` 标记为 `"plugin"`，优先级最低

### 8.4 与 engine 模块的交互

- `engine/query_engine.py` 调用 `build_runtime_system_prompt()` 生成每次请求的系统提示词
- `personalization/session_hook.py` 接收 `engine.messages.ConversationMessage`，在会话结束时提取事实

### 8.5 与 coordinator 模块的交互

- `prompts/context.py` 通过 `is_coordinator_mode()` 判断是否处于协调模式
- 协调模式下，系统提示词仅包含协调器提示词，跳过技能列表和委派指南段

### 8.6 与 utils 模块的交互

- **utils/file_lock.py**：`exclusive_file_lock()` 提供跨平台文件锁（POSIX fcntl / Windows msvcrt）
- **utils/fs.py**：`atomic_write_text()` 提供原子写入（temp+rename），保证崩溃安全

### 8.7 数据流向

```
用户会话开始
  │
  ├──→ detect environment → EnvironmentInfo
  ├──→ load_skills → SkillRegistry
  ├──→ discover CLAUDE.md → 项目指令文本
  ├──→ load_local_rules → 本地规则文本
  ├──→ load_memory_prompt → 记忆索引段
  ├──→ find_relevant_memories → 相关记忆段
  │
  └──→ build_runtime_system_prompt() → 完整系统提示词 → LLM API

用户会话中
  │
  ├──→ /skill invoke → 从 SkillRegistry 获取 content → 注入对话
  └──→ add_memory_entry → 写入记忆文件 + 更新 MEMORY.md

用户会话结束
  │
  └──→ update_rules_from_session → extract_facts → merge_facts → save_facts + save_local_rules
```