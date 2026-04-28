"""Built-in tools: Read, Write, Edit, Bash, Glob, Grep."""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mini_src.tools.base import BaseTool, ToolExecutionContext, ToolResult


# ── File Read ──────────────────────────────────────────────────────────


class FileReadToolInput(BaseModel):
    path: str = Field(description="Path of the file to read")
    offset: int = Field(default=0, ge=0, description="Zero-based starting line")
    limit: int = Field(default=200, ge=1, le=2000, description="Number of lines to return")


class FileReadTool(BaseTool):
    """Read a UTF-8 text file with line numbers."""

    name = "read_file"
    description = "Read a text file from the local repository."
    input_model = FileReadToolInput

    def is_read_only(self, arguments: FileReadToolInput) -> bool:
        return True

    async def execute(self, arguments: FileReadToolInput, context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        if path.is_dir():
            return ToolResult(output=f"Cannot read directory: {path}", is_error=True)

        raw = path.read_bytes()
        if b"\x00" in raw:
            return ToolResult(output=f"Binary file cannot be read as text: {path}", is_error=True)

        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        selected = lines[arguments.offset: arguments.offset + arguments.limit]
        numbered = [
            f"{arguments.offset + index + 1:>6}\t{line}"
            for index, line in enumerate(selected)
        ]
        if not numbered:
            return ToolResult(output=f"(no content in selected range for {path})")
        return ToolResult(output="\n".join(numbered))


# ── File Write ─────────────────────────────────────────────────────────


class FileWriteToolInput(BaseModel):
    path: str = Field(description="Path of the file to write")
    content: str = Field(description="Full file contents")


class FileWriteTool(BaseTool):
    """Write complete file contents."""

    name = "write_file"
    description = "Create or overwrite a text file in the local repository."
    input_model = FileWriteToolInput

    async def execute(self, arguments: FileWriteToolInput, context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments.content, encoding="utf-8")
        return ToolResult(output=f"Wrote {path}")


# ── File Edit ──────────────────────────────────────────────────────────


class FileEditToolInput(BaseModel):
    path: str = Field(description="Path of the file to edit")
    old_str: str = Field(description="Existing text to replace")
    new_str: str = Field(description="Replacement text")
    replace_all: bool = Field(default=False)


class FileEditTool(BaseTool):
    """Replace text in an existing file."""

    name = "edit_file"
    description = "Edit an existing file by replacing a string."
    input_model = FileEditToolInput

    async def execute(self, arguments: FileEditToolInput, context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments.path)
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)

        original = path.read_text(encoding="utf-8")
        if arguments.old_str not in original:
            return ToolResult(output="old_str was not found in the file", is_error=True)

        if arguments.replace_all:
            updated = original.replace(arguments.old_str, arguments.new_str)
        else:
            updated = original.replace(arguments.old_str, arguments.new_str, 1)

        path.write_text(updated, encoding="utf-8")
        return ToolResult(output=f"Updated {path}")


# ── Bash ───────────────────────────────────────────────────────────────


class BashToolInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout_seconds: int = Field(default=600, ge=1, le=600)


class BashTool(BaseTool):
    """Execute a shell command with stdout/stderr capture."""

    name = "bash"
    description = "Run a shell command in the local repository."
    input_model = BashToolInput

    async def execute(self, arguments: BashToolInput, context: ToolExecutionContext) -> ToolResult:
        process = await asyncio.create_subprocess_shell(
            arguments.command,
            cwd=str(context.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=arguments.timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ToolResult(
                output=f"Command timed out after {arguments.timeout_seconds} seconds.",
                is_error=True,
            )

        output = (await process.stdout.read()).decode("utf-8", errors="replace") if process.stdout else ""
        output = output.replace("\r\n", "\n").strip()
        if not output:
            output = "(no output)"
        if len(output) > 12000:
            output = f"{output[:12000]}\n...[truncated]..."
        return ToolResult(output=output, is_error=process.returncode != 0)


# ── Glob ───────────────────────────────────────────────────────────────


class GlobToolInput(BaseModel):
    pattern: str = Field(description="Glob pattern relative to the working directory")
    root: str | None = Field(default=None, description="Optional search root")
    limit: int = Field(default=200, ge=1, le=5000)


class GlobTool(BaseTool):
    """List files matching a glob pattern."""

    name = "glob"
    description = "List files matching a glob pattern."
    input_model = GlobToolInput

    def is_read_only(self, arguments: GlobToolInput) -> bool:
        return True

    async def execute(self, arguments: GlobToolInput, context: ToolExecutionContext) -> ToolResult:
        root = _resolve_path(context.cwd, arguments.root) if arguments.root else context.cwd

        rg = shutil.which("rg")
        if rg and ("**" in arguments.pattern or "/" in arguments.pattern):
            cmd = [rg, "--files"]
            if _looks_like_git_repo(root):
                cmd.append("--hidden")
            cmd.extend(["--glob", arguments.pattern, "."])

            process = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(root),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            assert process.stdout is not None
            lines = await _read_lines(process.stdout, arguments.limit)
            if len(lines) >= arguments.limit and process.returncode is None:
                process.terminate()
            await process.wait()
            lines.sort()
            if not lines:
                return ToolResult(output="(no matches)")
            return ToolResult(output="\n".join(lines))

        matches = sorted(str(p.relative_to(root)) for p in root.glob(arguments.pattern))[:arguments.limit]
        if not matches:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(matches))


def _looks_like_git_repo(path: Path) -> bool:
    current = path
    for _ in range(6):
        if (current / ".git").exists():
            return True
        if current.parent == current:
            break
        current = current.parent
    return False


# ── Grep ───────────────────────────────────────────────────────────────


class GrepToolInput(BaseModel):
    pattern: str = Field(description="Regular expression to search for")
    root: str | None = Field(default=None, description="Search root directory")
    file_glob: str = Field(default="**/*")
    case_sensitive: bool = Field(default=True)
    limit: int = Field(default=200, ge=1, le=2000)
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class GrepTool(BaseTool):
    """Search text files for a regex pattern."""

    name = "grep"
    description = "Search file contents with a regular expression."
    input_model = GrepToolInput

    def is_read_only(self, arguments: GrepToolInput) -> bool:
        return True

    async def execute(self, arguments: GrepToolInput, context: ToolExecutionContext) -> ToolResult:
        root = _resolve_path(context.cwd, arguments.root) if arguments.root else context.cwd

        rg = shutil.which("rg")
        if rg:
            return await self._rg_grep(root, arguments, rg)

        return self._python_grep(root, arguments)

    async def _rg_grep(self, root: Path, arguments: GrepToolInput, rg: str) -> ToolResult:
        cmd = [rg, "--no-heading", "--line-number", "--color", "never"]
        if (root / ".git").exists():
            cmd.append("--hidden")
        if not arguments.case_sensitive:
            cmd.append("-i")
        if arguments.file_glob:
            cmd.extend(["--glob", arguments.file_glob])
        cmd.extend(["--", arguments.pattern, "."])

        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(root),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        matches: list[str] = []
        try:
            await asyncio.wait_for(
                self._collect_matches(process, matches, arguments.limit),
                timeout=arguments.timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.terminate()
            await process.wait()
            output = "\n".join(matches) if matches else "(no matches)"
            return ToolResult(output=f"{output}\n\n[grep timed out after {arguments.timeout_seconds}s]", is_error=True)
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()

        if not matches:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(matches))

    async def _collect_matches(self, process: asyncio.subprocess.Process, matches: list[str], limit: int) -> None:
        assert process.stdout is not None
        lines = await _read_lines(process.stdout, limit)
        matches.extend(lines)

    def _python_grep(self, root: Path, arguments: GrepToolInput) -> ToolResult:
        flags = 0 if arguments.case_sensitive else re.IGNORECASE
        compiled = re.compile(arguments.pattern, flags)
        collected: list[str] = []

        for path in root.glob(arguments.file_glob):
            if len(collected) >= arguments.limit:
                break
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    try:
                        rel = str(path.relative_to(root))
                    except ValueError:
                        rel = str(path)
                    collected.append(f"{rel}:{line_no}:{line}")
                    if len(collected) >= arguments.limit:
                        break

        if not collected:
            return ToolResult(output="(no matches)")
        return ToolResult(output="\n".join(collected))


# ── Helpers ────────────────────────────────────────────────────────────


async def _read_lines(stream: asyncio.StreamReader, max_lines: int) -> list[str]:
    """Read lines from a stream, handling lines that exceed the asyncio buffer limit."""
    lines: list[str] = []
    buf = b""
    while len(lines) < max_lines:
        chunk = await stream.read(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf and len(lines) < max_lines:
            raw_line, buf = buf.split(b"\n", 1)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                lines.append(line)
    if buf and len(lines) < max_lines:
        line = buf.decode("utf-8", errors="replace").strip()
        if line:
            lines.append(line)
    return lines


def _resolve_path(base: Path, candidate: str) -> Path:
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def create_default_tool_registry(*, coordinator_mode: bool = False) -> list[Any]:
    """Return a list of default tool instances.

    When *coordinator_mode* is True, also register coordinator tools
    (agent, send_message, task_stop, task_output, task_list, task_get).
    """
    tools: list[Any] = [
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ]

    if coordinator_mode:
        from mini_src.tools.agent_tool import AgentTool
        from mini_src.tools.send_message_tool import SendMessageTool
        from mini_src.tools.task_get_tool import TaskGetTool
        from mini_src.tools.task_list_tool import TaskListTool
        from mini_src.tools.task_output_tool import TaskOutputTool
        from mini_src.tools.task_stop_tool import TaskStopTool

        tools.extend([
            AgentTool(),
            SendMessageTool(),
            TaskStopTool(),
            TaskOutputTool(),
            TaskListTool(),
            TaskGetTool(),
        ])

    return tools
