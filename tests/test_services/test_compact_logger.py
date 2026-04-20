"""Tests for the compact_logger module inside the log package."""

from __future__ import annotations

from pathlib import Path

from openharness.services.log import _shared
from openharness.services.log.compact_logger import log_compact_event


def _reset() -> None:
    _shared.reset_session()
    _shared.set_verbose(False)


class TestLogCompactEvent:
    """Tests for ``log_compact_event``."""

    def setup_method(self) -> None:
        _reset()

    def teardown_method(self) -> None:
        _reset()

    def test_no_crash_basic(self) -> None:
        """log_compact_event must not raise for valid input."""
        log_compact_event(
            request_id=1,
            trigger="auto",
            phase="compact_end",
            before_tokens=12000,
            after_tokens=4000,
            summary="Compacted messages 1-15",
        )

    def test_no_crash_minimal(self) -> None:
        """log_compact_event must work with only required args."""
        log_compact_event(
            request_id=0,
            trigger="manual",
            phase="compact_start",
        )

    def test_verbose_writes_to_file(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=True, compaction details should appear in the log file."""
        log_file = tmp_path / "prompt_debug_compact.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_compact_event(
                request_id=1,
                trigger="auto",
                phase="compact_end",
                before_tokens=12000,
                after_tokens=4000,
                summary="Compacted messages 1-15: User asked about architecture",
            )
            content = log_file.read_text(encoding="utf-8")
            assert "COMPACT" in content
            assert "trigger=auto" in content
            assert "12000" in content
            assert "4000" in content
            assert "67%" in content
        finally:
            _shared.set_verbose(False)

    def test_verbose_with_long_summary(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=True, long summaries should be truncated."""
        log_file = tmp_path / "prompt_debug_compact_long.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_compact_event(
                request_id=1,
                trigger="auto",
                phase="compact_end",
                summary="x" * 1000,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "[truncated" in content
        finally:
            _shared.set_verbose(False)

    def test_no_file_when_not_verbose(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=False, no file content should be written."""
        log_file = tmp_path / "prompt_debug_no_verbose.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)

        log_compact_event(
            request_id=1,
            trigger="auto",
            phase="compact_end",
            before_tokens=12000,
            after_tokens=4000,
        )
        assert not log_file.exists() or log_file.read_text(encoding="utf-8") == ""