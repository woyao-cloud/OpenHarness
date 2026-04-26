"""Helpers for managing memory files."""

from __future__ import annotations

from pathlib import Path
from re import sub

from mini_src.memory.paths import get_memory_entrypoint, get_project_memory_dir


def _memory_lock_path(cwd: str | Path) -> Path:
    return get_project_memory_dir(cwd) / ".memory.lock"


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically (simplified — no file locking)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def list_memory_files(cwd: str | Path) -> list[Path]:
    """List memory markdown files for the project."""
    memory_dir = get_project_memory_dir(cwd)
    return sorted(path for path in memory_dir.glob("*.md"))


def add_memory_entry(cwd: str | Path, title: str, content: str) -> Path:
    """Create a memory file and append it to MEMORY.md."""
    memory_dir = get_project_memory_dir(cwd)
    slug = sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_") or "memory"
    path = memory_dir / f"{slug}.md"
    _atomic_write_text(path, content.strip() + "\n")

    entrypoint = get_memory_entrypoint(cwd)
    existing = entrypoint.read_text(encoding="utf-8") if entrypoint.exists() else "# Memory Index\n"
    if path.name not in existing:
        existing = existing.rstrip() + f"\n- [{title}]({path.name})\n"
        _atomic_write_text(entrypoint, existing)
    return path


def remove_memory_entry(cwd: str | Path, name: str) -> bool:
    """Delete a memory file and remove its index entry."""
    memory_dir = get_project_memory_dir(cwd)
    matches = [path for path in memory_dir.glob("*.md") if path.stem == name or path.name == name]
    if not matches:
        return False
    path = matches[0]
    if path.exists():
        path.unlink()

    entrypoint = get_memory_entrypoint(cwd)
    if entrypoint.exists():
        lines = [
            line
            for line in entrypoint.read_text(encoding="utf-8").splitlines()
            if path.name not in line
        ]
        _atomic_write_text(entrypoint, "\n".join(lines).rstrip() + "\n")
    return True
