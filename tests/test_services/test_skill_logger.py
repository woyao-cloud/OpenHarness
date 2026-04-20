"""Tests for the skill_logger module inside the log package."""

from __future__ import annotations

from pathlib import Path

from openharness.services.log import _shared
from openharness.services.log.skill_logger import log_skill_load


def _reset() -> None:
    _shared.reset_session()
    _shared.set_verbose(False)


class TestLogSkillLoad:
    """Tests for ``log_skill_load``."""

    def setup_method(self) -> None:
        _reset()

    def teardown_method(self) -> None:
        _reset()

    def test_no_crash_basic(self) -> None:
        """log_skill_load must not raise for valid input."""
        log_skill_load(
            request_id=1,
            skill_name="architecture-review",
            skill_content="# Architecture Review Skill\nThis skill helps review code architecture.",
        )

    def test_no_crash_with_long_content(self) -> None:
        """log_skill_load must handle long skill content without error."""
        log_skill_load(
            request_id=1,
            skill_name="big-skill",
            skill_content="x" * 1000,
        )

    def test_verbose_writes_to_file(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=True, skill content should appear in the log file."""
        log_file = tmp_path / "prompt_debug_skill.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_skill_load(
                request_id=1,
                skill_name="architecture-review",
                skill_content="# Architecture Review Skill\nThis helps review code.",
            )
            content = log_file.read_text(encoding="utf-8")
            assert "SKILL" in content
            assert "architecture-review" in content
        finally:
            _shared.set_verbose(False)

    def test_verbose_truncates_long_content(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=True, long skill content should be truncated."""
        log_file = tmp_path / "prompt_debug_skill_long.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_skill_load(
                request_id=1,
                skill_name="big-skill",
                skill_content="x" * 1000,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "[truncated" in content
        finally:
            _shared.set_verbose(False)

    def test_no_file_when_not_verbose(self, tmp_path: Path, monkeypatch) -> None:
        """When verbose=False, no file content should be written."""
        log_file = tmp_path / "prompt_debug_no_verbose.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)

        log_skill_load(
            request_id=1,
            skill_name="test-skill",
            skill_content="short",
        )
        assert not log_file.exists() or log_file.read_text(encoding="utf-8") == ""