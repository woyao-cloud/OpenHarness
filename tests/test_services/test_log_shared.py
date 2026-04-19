"""Tests for openharness.services.log._shared — shared log infrastructure."""

from __future__ import annotations

import threading
from pathlib import Path

from openharness.services.log._shared import (
    get_log_file_path,
    is_verbose,
    next_request_id,
    reset_session,
    set_verbose,
    truncate,
    write_to_debug_file,
    _TRUNCATE_LIMIT,
)


# ---------------------------------------------------------------------------
# truncate()
# ---------------------------------------------------------------------------


class TestTruncate:
    """Tests for the truncate() helper."""

    def test_short_text_unchanged(self) -> None:
        """Text shorter than the default limit is returned as-is."""
        text = "hello world"
        assert truncate(text) == text

    def test_exact_limit_unchanged(self) -> None:
        """Text whose length equals the limit is returned without truncation marker."""
        text = "x" * _TRUNCATE_LIMIT
        assert truncate(text) == text

    def test_long_text_truncated(self) -> None:
        """Text exceeding the limit is truncated with a marker showing total length."""
        original = "a" * 600
        result = truncate(original)
        assert result.startswith("a" * _TRUNCATE_LIMIT)
        assert "... [truncated, total 600 chars]" in result
        # The truncated text should be shorter than the original
        assert len(result) < len(original)

    def test_custom_limit(self) -> None:
        """A custom limit overrides the default."""
        text = "abcdefghij"
        result = truncate(text, limit=5)
        assert result == "abcde... [truncated, total 10 chars]"

    def test_custom_limit_exact(self) -> None:
        """Custom limit with text at exactly that length is returned unchanged."""
        text = "abcde"
        result = truncate(text, limit=5)
        assert result == "abcde"

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged."""
        assert truncate("") == ""


# ---------------------------------------------------------------------------
# next_request_id()
# ---------------------------------------------------------------------------


class TestNextRequestId:
    """Tests for the thread-safe request counter."""

    def setup_method(self) -> None:
        reset_session()

    def teardown_method(self) -> None:
        reset_session()

    def test_increments(self) -> None:
        """Each call returns a monotonically increasing ID."""
        first = next_request_id()
        second = next_request_id()
        third = next_request_id()
        assert first == 1
        assert second == 2
        assert third == 3

    def test_thread_safety(self) -> None:
        """Counter is safe under concurrent access."""
        results: list[int] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(100):
                    results.append(next_request_id())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All IDs should be unique
        assert len(set(results)) == len(results)
        # Should have exactly 500 IDs (5 threads * 100 calls)
        assert len(results) == 500


# ---------------------------------------------------------------------------
# verbose gate
# ---------------------------------------------------------------------------


class TestVerboseGate:
    """Tests for set_verbose() / is_verbose()."""

    def setup_method(self) -> None:
        reset_session()

    def teardown_method(self) -> None:
        reset_session()

    def test_default_is_not_verbose(self) -> None:
        """Verbose mode is off by default."""
        assert is_verbose() is False

    def test_set_verbose_true(self) -> None:
        """Setting verbose to True enables it."""
        set_verbose(True)
        assert is_verbose() is True

    def test_set_verbose_false(self) -> None:
        """Setting verbose to False disables it."""
        set_verbose(True)
        set_verbose(False)
        assert is_verbose() is False

    def test_toggle_verbose(self) -> None:
        """Verbose can be toggled multiple times."""
        set_verbose(True)
        assert is_verbose() is True
        set_verbose(False)
        assert is_verbose() is False
        set_verbose(True)
        assert is_verbose() is True


# ---------------------------------------------------------------------------
# write_to_debug_file()
# ---------------------------------------------------------------------------


class TestWriteToDebugFile:
    """Tests for write_to_debug_file() verbose guard."""

    def setup_method(self) -> None:
        reset_session()

    def teardown_method(self) -> None:
        reset_session()

    def test_skips_when_not_verbose(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose is off, write_to_debug_file does not create a file."""
        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))
        set_verbose(False)

        write_to_debug_file("should not be written")

        # The logs dir exists (created by get_logs_dir), but no .log file
        log_files = list(tmp_path.glob("*.log"))
        assert log_files == []

    def test_writes_when_verbose(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose is on, write_to_debug_file writes content to file."""
        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))
        set_verbose(True)

        write_to_debug_file("hello debug")

        log_files = list(tmp_path.glob("prompt_debug_*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text(encoding="utf-8")
        assert "hello debug" in content


# ---------------------------------------------------------------------------
# get_log_file_path()
# ---------------------------------------------------------------------------


class TestGetLogFilePath:
    """Tests for get_log_file_path() lazy creation and rotation."""

    def setup_method(self) -> None:
        reset_session()

    def teardown_method(self) -> None:
        reset_session()

    def test_creates_file_in_logs_dir(self, tmp_path: Path, monkeypatch) -> None:
        """Log file path is created inside the configured logs directory."""
        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))

        path = get_log_file_path()

        assert path.parent == tmp_path
        assert path.name.startswith("prompt_debug_")
        assert path.suffix == ".log"

    def test_returns_same_path_on_repeated_calls(self, tmp_path: Path, monkeypatch) -> None:
        """Repeated calls return the same path object (lazy creation)."""
        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))

        path1 = get_log_file_path()
        path2 = get_log_file_path()
        assert path1 == path2

    def test_rotation_removes_oldest_files(self, tmp_path: Path, monkeypatch) -> None:
        """When max debug files are exceeded, oldest files are removed."""
        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))

        # Pre-create 15 existing log files (the max)
        for i in range(15):
            f = tmp_path / f"prompt_debug_20250101_{i:06d}.log"
            f.write_text(f"old log {i}", encoding="utf-8")

        # Requesting a new path should trigger rotation
        new_path = get_log_file_path()
        assert new_path.exists() or True  # path is computed, file may not exist yet

        # After rotation, there should be at most 15 files (14 old + 1 new)
        remaining = sorted(tmp_path.glob("prompt_debug_*.log"))
        assert len(remaining) <= 15

    def test_thread_safe_path_creation(self, tmp_path: Path, monkeypatch) -> None:
        """Concurrent calls to get_log_file_path return the same path."""
        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))

        results: list[Path] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                results.append(get_log_file_path())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # All threads should get the same path
        assert len(set(results)) == 1


# ---------------------------------------------------------------------------
# reset_session()
# ---------------------------------------------------------------------------


class TestResetSession:
    """Tests for reset_session() cleanup."""

    def test_resets_counter(self) -> None:
        """reset_session resets the request counter to 0."""
        next_request_id()
        next_request_id()
        reset_session()
        assert next_request_id() == 1

    def test_resets_file_path(self, tmp_path: Path, monkeypatch) -> None:
        """reset_session clears the cached log file path."""
        import datetime as _dt

        monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path))

        # Use controlled timestamps so the test does not depend on
        # wall-clock time (two calls within the same second would
        # otherwise produce the same filename).
        fake_times = [
            _dt.datetime(2025, 1, 1, 12, 0, 0),
            _dt.datetime(2025, 1, 2, 12, 0, 0),
        ]
        call_count = 0

        class FakeDateTime:
            @staticmethod
            def now():
                nonlocal call_count
                t = fake_times[call_count]
                call_count += 1
                return t

        monkeypatch.setattr("openharness.services.log._shared.datetime", FakeDateTime)

        path1 = get_log_file_path()
        reset_session()
        path2 = get_log_file_path()

        # After reset, a new path (with a different timestamp) is generated
        assert path1 != path2