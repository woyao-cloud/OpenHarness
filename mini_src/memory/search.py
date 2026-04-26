"""Simple heuristic memory search."""

from __future__ import annotations

import re
from pathlib import Path

from mini_src.memory.scan import scan_memory_files
from mini_src.memory.types import MemoryHeader


def find_relevant_memories(
    query: str,
    cwd: str | Path,
    *,
    max_results: int = 5,
) -> list[MemoryHeader]:
    """Return the memory files whose metadata and content overlap the query.

    Scoring weights frontmatter fields higher than body content so that
    well-annotated memories surface first.
    """
    tokens = _tokenize(query)
    if not tokens:
        return []

    scored: list[tuple[float, MemoryHeader]] = []
    for header in scan_memory_files(cwd, max_files=100):
        meta = f"{header.title} {header.description}".lower()
        body = header.body_preview.lower()

        meta_hits = sum(1 for t in tokens if t in meta)
        body_hits = sum(1 for t in tokens if t in body)
        score = meta_hits * 2.0 + body_hits
        if score > 0:
            scored.append((score, header))

    scored.sort(key=lambda item: (-item[0], -item[1].modified_at))
    return [header for _, header in scored[:max_results]]


def _tokenize(text: str) -> set[str]:
    """Extract search tokens from *text*, handling ASCII and Han ideographs."""
    ascii_tokens = {t for t in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(t) >= 3}
    han_chars = set(re.findall(r"[一-鿿㐀-䶿]", text))
    return ascii_tokens | han_chars
