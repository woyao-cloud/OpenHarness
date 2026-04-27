"""Hook event names — only the events needed by compaction."""

from __future__ import annotations

from enum import Enum


class HookEvent(str, Enum):
    """Events that can trigger hooks (compaction subset)."""

    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
