"""Shared infrastructure for the log package.

Provides thread-safe request counting, log file path management with
rotation, verbose-mode gating, and text truncation utilities.

This module is the single source of truth for globals and helpers that
are consumed by the specialised logger modules (prompt_logger,
tool_logger, etc.).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from openharness.config.paths import get_logs_dir

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_DEBUG_FILES = 15
_TRUNCATE_LIMIT = 500

# ---------------------------------------------------------------------------
# Thread-safe request counter
# ---------------------------------------------------------------------------

_request_counter: int = 0
_counter_lock = threading.Lock()


def next_request_id() -> int:
    """Increment and return the global request counter (thread-safe)."""
    global _request_counter
    with _counter_lock:
        _request_counter += 1
        return _request_counter


# ---------------------------------------------------------------------------
# Verbose gate
# ---------------------------------------------------------------------------

_verbose_enabled: bool = False


def set_verbose(enabled: bool) -> None:
    """Set the global verbose flag."""
    global _verbose_enabled
    _verbose_enabled = enabled


def is_verbose() -> bool:
    """Return whether verbose debug logging is enabled."""
    return _verbose_enabled


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def truncate(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    """Truncate *text* to *limit* characters, appending a marker when truncated.

    If ``len(text) > limit``, the return value is
    ``text[:limit] + "... [truncated, total N chars]"`` where *N* is the
    original length.  Otherwise *text* is returned unchanged.
    """
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated, total {len(text)} chars]"


# ---------------------------------------------------------------------------
# Log file path management
# ---------------------------------------------------------------------------

_log_file_path: Path | None = None
_log_file_lock = threading.Lock()


def get_log_file_path() -> Path:
    """Return (and lazily create) the session prompt debug log file path.

    The path is computed once and cached for the rest of the session.
    When the cached path is first created, old debug files beyond
    ``_MAX_DEBUG_FILES`` are rotated away.

    Thread-safe: uses ``_log_file_lock`` to prevent races.
    """
    global _log_file_path
    with _log_file_lock:
        if _log_file_path is not None:
            return _log_file_path

        logs_dir = get_logs_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_file_path = logs_dir / f"prompt_debug_{timestamp}.log"

        # Rotate: remove oldest files beyond the limit.
        existing = sorted(logs_dir.glob("prompt_debug_*.log"))
        while len(existing) >= _MAX_DEBUG_FILES:
            oldest = existing.pop(0)
            try:
                oldest.unlink()
            except OSError:
                pass

        return _log_file_path


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------


def write_to_debug_file(content: str) -> None:
    """Append *content* to the session debug log file.

    If ``is_verbose()`` is ``False``, this is a no-op — the function
    returns immediately without touching the filesystem.
    """
    if not is_verbose():
        return

    try:
        log_path = get_log_file_path()
        with _log_file_lock:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(content)
                f.write("\n\n")
    except OSError:
        # Non-critical: debug logging should never break the main flow.
        log.warning("Failed to write prompt debug log to %s", _log_file_path)


# ---------------------------------------------------------------------------
# Session reset (for testing)
# ---------------------------------------------------------------------------


def reset_session() -> None:
    """Reset session state — counter and cached log file path.

    Primarily intended for use in test teardowns so that tests are
    isolated from each other.
    """
    global _request_counter, _log_file_path
    with _counter_lock:
        _request_counter = 0
    with _log_file_lock:
        _log_file_path = None