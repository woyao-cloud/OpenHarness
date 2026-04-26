# 第 9 章：插件与技能系统

## 9.1 解决的问题

不同场景需要不同的知识和能力。插件和技能系统让用户可以：

1. **加载领域知识**：无需修改代码即可为 Agent 注入专业知识
2. **扩展命令**：添加新的斜杠命令
3. **自定义行为**：通过 Hook 修改 Agent 行为
4. **社区共享**：复用 [anthropics/skills](https://github.com/anthropics/skills) 和 [claude-code plugins](https://github.com/anthropics/claude-code/tree/main/plugins) 生态

## 9.2 技能系统

### 9.2.1 技能定义

`skills/types.py`：

```python
@dataclass
class SkillDefinition:
    name: str           # 技能名称
    description: str    # 描述（LLM 决定何时加载）
    content: str        # 完整 Markdown 内容
    source: str         # "bundled" | "user" | "plugin" | "extra"
    path: str | None    # 文件路径（可选）
```

### 9.2.2 技能文件格式

技能是 YAML frontmatter + Markdown 正文的 `.md` 文件：

```markdown
---
name: my-skill
description: Expert guidance for my specific domain
---

# My Skill

## When to use
Use when the user asks about [your domain].

## Workflow
1. Step one
2. Step two
3. Step three

## Guidelines
- Rule one
- Rule two
```

### 9.2.3 技能注册中心

`skills/registry.py`：

```python
class SkillRegistry:
    """名称 → SkillDefinition 的不可变映射。"""
    
    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}
    
    def register(self, skill: SkillDefinition) -> None:
        self._skills[skill.name] = skill
    
    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)
    
    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())
```

### 9.2.4 技能加载

`skills/loader.py` 中的 `load_skill_registry()` 从四个来源加载：

```python
def load_skill_registry(extra_dirs=None):
    registry = SkillRegistry()
    
    # 1. 内置技能（src/openharness/skills/bundled/）
    for path in BUNDLED_SKILLS_DIR.glob("*.md"):
        registry.register(_load_skill_from_file(path, source="bundled"))
    
    # 2. 用户技能（~/.openharness/skills/）
    for path in USER_SKILLS_DIR.glob("*/SKILL.md"):
        registry.register(_load_skill_from_file(path, source="user"))
    
    # 3. 插件技能（来自已安装插件的 skills/ 目录）
    for plugin_skill in plugin_skills:
        registry.register(plugin_skill)
    
    # 4. 额外目录（ohmo workspace 等）
    if extra_dirs:
        for extra_dir in extra_dirs:
            for path in Path(extra_dir).glob("*.md"):
                registry.register(_load_skill_from_file(path, source="extra"))
    
    return registry
```

### 9.2.5 技能加载工具

Skill 工具（`tools/skill_tool.py`）让 LLM 可以在运行时加载技能：

```python
class SkillTool(BaseTool):
    name = "skill"
    description = "Load a skill for domain-specific guidance"
    
    async def execute(self, args, context):
        skill = context.metadata["tool_registry"].skills.get(args.name)
        if skill is None:
            return ToolResult(output=f"Skill not found: {args.name}", is_error=True)
        return ToolResult(output=skill.content)
```

### 9.2.6 技能注入系统提示词

在 `build_runtime_system_prompt()` 中，可用技能列表被注入到系统提示词：

```markdown
# Available Skills

- **my-skill**: Expert guidance for my specific domain
  Load with: `/skill my-skill`
```

## 9.3 插件系统

### 9.3.1 插件清单

每个插件包含 `plugin.json` 清单文件：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin",
  "skills_dir": "skills",
  "hooks_file": "hooks/hooks.json",
  "mcp_file": "mcp.json",
  "commands": [
    {"name": "/my-command", "description": "Does something useful"}
  ],
  "agents": [
    {"name": "my-agent", "file": "agents/my-agent.md"}
  ]
}
```

### 9.3.2 插件目录结构

```
my-plugin/
  .claude-plugin/
    plugin.json              ← 插件清单
  skills/
    my-skill.md              ← 技能文件
  agents/
    my-agent.md              ← Agent 定义
  commands/
    my-command.md            ← 命令定义
  hooks/
    hooks.json               ← Hook 配置
  mcp.json                   ← MCP 服务器配置
```

### 9.3.3 插件加载

`plugins/loader.py`：

```python
def load_plugins(extra_roots=None):
    """发现并加载所有插件。"""
    plugins = []
    
    # 搜索路径
    search_paths = [
        USER_PLUGINS_DIR,           # ~/.openharness/plugins/
        PROJECT_PLUGINS_DIR,        # .openharness/plugins/
    ]
    if extra_roots:
        search_paths.extend(extra_roots)
    
    for root in search_paths:
        for plugin_dir in root.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
            if manifest_path.exists():
                plugin = _load_plugin(plugin_dir)
                if plugin:
                    plugins.append(plugin)
    
    return plugins
```

### 9.3.4 插件的贡献点

加载后的插件可以贡献：

| 贡献类型 | 说明 | 合并到 |
|---------|------|--------|
| Skills | 领域知识 | `SkillRegistry` |
| Commands | 斜杠命令 | `CommandRegistry` |
| Agents | Agent 定义 | Agent 注册表 |
| Hooks | 生命周期 Hook | `HookRegistry` |
| MCP Servers | 外部工具 | `McpClientManager` |

### 9.3.5 LoadedPlugin

`plugins/types.py`：

```python
@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    path: Path
    enabled: bool = True
    skills: list[SkillDefinition] = field(default_factory=list)
    commands: list[PluginCommandDefinition] = field(default_factory=list)
    agents: list[AgentDefinition] = field(default_factory=list)
    hooks: HookRegistry | None = None
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
```

### 9.3.6 命令定义

插件贡献的命令是 Markdown 文件：

```markdown
---
name: my-command
description: Does something useful
---

# /my-command

## Usage
Run this command to do something useful.

## Implementation
```python
# 命令处理器的 Python 代码
result = await do_something()
print(result)
```
```

## 9.4 与 Anthropic SDK 的兼容性

OpenHarness 兼容 **anthropics/skills** 和 **claude-code/plugins** 两个生态系统的内容。这意味着：

- 社区的 `.md` 技能文件可以直接复制到 `~/.openharness/skills/`
- 官方的插件可以安装到 `~/.openharness/plugins/`
- 命令、Agent、Hook 的格式保持兼容

## 9.5 关键源码路径

| 组件 | 文件 | 关键元素 |
|------|------|---------|
| 技能定义 | `skills/types.py` | `SkillDefinition` |
| 技能注册 | `skills/registry.py` | `SkillRegistry` |
| 技能加载 | `skills/loader.py` | `load_skill_registry()` |
| 技能工具 | `tools/skill_tool.py` | `SkillTool` |
| 插件清单 | `plugins/schemas.py` | `PluginManifest` |
| 插件加载 | `plugins/loader.py` | `load_plugins()` |
| 插件安装 | `plugins/installer.py` | `install_plugin_from_path()` |
| 插件类型 | `plugins/types.py` | `LoadedPlugin` |

## 9.6 本章小结

技能系统让 LLM 可以按需加载领域知识（相当于注入新的系统提示词段落）。插件系统则更强大——它可以贡献命令、Agent、Hook 和 MCP 服务器，从根本上扩展 Agent 的能力边界。两者都兼容社区生态，使得 OpenHarness 可以复用大量已有的开源资源。

> 下一章：[MCP 集成](10-mcp.md) —— Model Context Protocol 的客户端实现。
