"""Background task manager for mini_src."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from mini_src.config import get_data_dir
from mini_src.tasks.types import TaskRecord, TaskStatus, TaskType


class BackgroundTaskManager:
    """Manage shell and agent subprocess tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._waiters: dict[str, asyncio.Task[None]] = {}
        self._output_locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}

    async def create_shell_task(
        self,
        *,
        command: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_bash",
    ) -> TaskRecord:
        """Start a background shell command."""
        task_id = _task_id(task_type)
        tasks_dir = get_data_dir() / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        output_path = tasks_dir / f"{task_id}.log"
        record = TaskRecord(
            id=task_id,
            type=task_type,
            status="running",
            description=description,
            cwd=str(Path(cwd).resolve()),
            output_file=output_path,
            command=command,
            created_at=time.time(),
            started_at=time.time(),
        )
        output_path.write_text("", encoding="utf-8")
        self._tasks[task_id] = record
        self._output_locks[task_id] = asyncio.Lock()
        await self._start_process(task_id)
        return record

    async def create_agent_task(
        self,
        *,
        prompt: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_agent",
        model: str | None = None,
        api_key: str | None = None,
        command: str | None = None,
    ) -> TaskRecord:
        """Start a local agent task as a subprocess."""
        if command is None:
            effective_api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
            if not effective_api_key:
                raise ValueError(
                    "Local agent tasks require an API key or an explicit command override"
                )
            cmd_parts = ["python", "-m", "mini_src", "--task-worker"]
            if api_key:
                cmd_parts.extend(["--api-key", api_key])
            if model:
                cmd_parts.extend(["--model", model])
            import shlex
            command = " ".join(shlex.quote(p) for p in cmd_parts)

        record = await self.create_shell_task(
            command=command,
            description=description,
            cwd=cwd,
            task_type=task_type,
        )
        updated = replace(record, prompt=prompt)
        self._tasks[record.id] = updated
        await self.write_to_task(record.id, prompt)
        return updated

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Return one task record."""
        return self._tasks.get(task_id)

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        """Return all tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    async def stop_task(self, task_id: str) -> TaskRecord:
        """Terminate a running task."""
        task = self._require_task(task_id)
        process = self._processes.get(task_id)
        if process is None:
            if task.status in {"completed", "failed", "killed"}:
                return task
            raise ValueError(f"Task {task_id} is not running")

        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

        task.status = "killed"
        task.ended_at = time.time()
        return task

    async def write_to_task(self, task_id: str, data: str) -> None:
        """Write one line to task stdin."""
        task = self._require_task(task_id)
        process = self._processes.get(task_id)
        if process is None or process.stdin is None or process.returncode is not None:
            if task.type != "local_agent":
                raise ValueError(f"Task {task_id} does not accept input")
            process = await self._restart_agent_task(task)
        process.stdin.write((data.rstrip("\n") + "\n").encode("utf-8"))
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            if task.type != "local_agent":
                raise ValueError(f"Task {task_id} does not accept input") from None
            process = await self._restart_agent_task(task)
            process.stdin.write((data.rstrip("\n") + "\n").encode("utf-8"))
            await process.stdin.drain()

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str:
        """Return the tail of a task's output file."""
        task = self._require_task(task_id)
        content = task.output_file.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            return content[-max_bytes:]
        return content

    async def _watch_process(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        generation: int,
    ) -> None:
        reader = asyncio.create_task(self._copy_output(task_id, process))
        return_code = await process.wait()
        await reader

        current_generation = self._generations.get(task_id)
        if current_generation != generation:
            return

        task = self._tasks[task_id]
        task.return_code = return_code
        if task.status != "killed":
            task.status = "completed" if return_code == 0 else "failed"
        task.ended_at = time.time()
        self._processes.pop(task_id, None)
        self._waiters.pop(task_id, None)

    async def _copy_output(self, task_id: str, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            return
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                return
            async with self._output_locks[task_id]:
                with self._tasks[task_id].output_file.open("ab") as handle:
                    handle.write(chunk)

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        return task

    async def _start_process(self, task_id: str) -> asyncio.subprocess.Process:
        task = self._require_task(task_id)
        if task.command is None:
            raise ValueError(f"Task {task_id} does not have a command to run")

        generation = self._generations.get(task_id, 0) + 1
        self._generations[task_id] = generation
        process = await asyncio.create_subprocess_shell(
            task.command,
            cwd=task.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[task_id] = process
        self._waiters[task_id] = asyncio.create_task(
            self._watch_process(task_id, process, generation)
        )
        return process

    async def _restart_agent_task(self, task: TaskRecord) -> asyncio.subprocess.Process:
        if task.command is None:
            raise ValueError(f"Task {task.id} does not have a restart command")

        waiter = self._waiters.get(task.id)
        if waiter is not None and not waiter.done():
            await waiter

        restart_count = int(task.metadata.get("restart_count", "0")) + 1
        task.metadata["restart_count"] = str(restart_count)
        task.status = "running"
        task.started_at = time.time()
        task.ended_at = None
        task.return_code = None
        return await self._start_process(task.id)


_DEFAULT_MANAGER: BackgroundTaskManager | None = None
_DEFAULT_MANAGER_KEY: str | None = None


def get_task_manager() -> BackgroundTaskManager:
    """Return the singleton task manager."""
    global _DEFAULT_MANAGER, _DEFAULT_MANAGER_KEY
    current_key = str(get_data_dir().resolve())
    if _DEFAULT_MANAGER is None or _DEFAULT_MANAGER_KEY != current_key:
        _DEFAULT_MANAGER = BackgroundTaskManager()
        _DEFAULT_MANAGER_KEY = current_key
    return _DEFAULT_MANAGER


def _task_id(task_type: TaskType) -> str:
    prefixes = {"local_bash": "b", "local_agent": "a"}
    return f"{prefixes[task_type]}{uuid4().hex[:8]}"
