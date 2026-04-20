"""Tests for the tool_logger module inside the log package."""

from __future__ import annotations

from pathlib import Path

from openharness.services.log import _shared
from openharness.services.log.tool_logger import log_tool_execution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _reset() -> None:
    _shared.reset_session()
    _shared.set_verbose(False)


# ---------------------------------------------------------------------------
# log_tool_execution
# ---------------------------------------------------------------------------


class TestLogToolExecution:
    """Tests for ``log_tool_execution``."""

    def setup_method(self) -> None:
        _reset()

    def teardown_method(self) -> None:
        _reset()

    def test_no_crash_basic(self) -> None:
        """log_tool_execution must not raise for valid input."""
        log_tool_execution(
            request_id=1,
            tool_name="read_file",
            tool_input={"file_path": "/a.py"},
            tool_output="file contents here",
            is_error=False,
            duration_seconds=0.35,
        )

    def test_no_crash_with_long_output(self) -> None:
        """log_tool_execution must handle long output without error."""
        log_tool_execution(
            request_id=1,
            tool_name="bash",
            tool_input={"command": "cat huge_file.txt"},
            tool_output="x" * 1000,
            is_error=False,
            duration_seconds=1.5,
        )

    def test_no_crash_with_error(self) -> None:
        """log_tool_execution must handle error outputs."""
        log_tool_execution(
            request_id=1,
            tool_name="bash",
            tool_input={"command": "exit 1"},
            tool_output="Command failed with exit code 1",
            is_error=True,
            duration_seconds=0.01,
        )

    def test_verbose_writes_to_file(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=True, tool execution details should appear in the log file."""
        log_file = tmp_path / "prompt_debug_test.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_tool_execution(
                request_id=1,
                tool_name="read_file",
                tool_input={"file_path": "/path/main.py", "offset": 0},
                tool_output="import sys\n\ndef main():\n...",
                is_error=False,
                duration_seconds=0.35,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "TOOL" in content
            assert "read_file" in content
            assert "0.35s" in content
            assert "Input:" in content
            assert "file_path" in content
            assert "Error: False" in content
        finally:
            _shared.set_verbose(False)

    def test_verbose_truncates_long_output(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=True, long tool output should be truncated in the log file."""
        log_file = tmp_path / "prompt_debug_truncate.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            long_output = "x" * 1000
            log_tool_execution(
                request_id=1,
                tool_name="bash",
                tool_input={"command": "cat huge.txt"},
                tool_output=long_output,
                is_error=False,
                duration_seconds=1.5,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "[truncated" in content
        finally:
            _shared.set_verbose(False)

    def test_no_file_when_not_verbose(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=False (default), no file content should be written."""
        log_file = tmp_path / "prompt_debug_no_verbose.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)

        log_tool_execution(
            request_id=1,
            tool_name="bash",
            tool_input={"command": "ls"},
            tool_output="file1.txt\nfile2.txt",
            is_error=False,
            duration_seconds=0.1,
        )
        assert not log_file.exists() or log_file.read_text(encoding="utf-8") == ""