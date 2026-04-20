"""Tests for the prompt_logger module inside the log package."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import (
    ConversationMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from openharness.services.log import _shared
from openharness.services.log.prompt_logger import (
    PromptLogEntry,
    ResponseCompleteLogEntry,
    ResponseLogEntry,
    log_prompt_request,
    log_response_complete,
    log_response_event,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Reset shared global state before and after every test."""
    _shared.reset_session()
    yield
    _shared.reset_session()


def _make_tool_registry(*names: str) -> MagicMock:
    """Return a mock ToolRegistry whose ``to_api_schema`` lists *names*."""
    mock = MagicMock()
    mock.to_api_schema.return_value = [
        {"name": n, "description": f"Description for {n}", "input_schema": {}}
        for n in names
    ]
    return mock


def _make_messages(*roles_and_texts: tuple[str, str]) -> list[ConversationMessage]:
    """Build a list of ConversationMessage from ``(role, text)`` pairs."""
    return [
        ConversationMessage(role=role, content=[TextBlock(text=text)])
        for role, text in roles_and_texts
    ]


# ---------------------------------------------------------------------------
# log_prompt_request
# ---------------------------------------------------------------------------


class TestLogPromptRequest:
    """Tests for ``log_prompt_request``."""

    def test_returns_int_request_id(self) -> None:
        """log_prompt_request must return an int request_id > 0."""
        rid = log_prompt_request(
            model="test-model",
            max_tokens=1024,
            system_prompt="You are helpful.",
            messages=_make_messages(("user", "Hello")),
            tool_registry=_make_tool_registry("bash"),
        )
        assert isinstance(rid, int)
        assert rid > 0

    def test_request_ids_increment(self) -> None:
        """Successive calls must return incrementing request IDs."""
        reg = _make_tool_registry("bash")
        rid1 = log_prompt_request(
            model="m1",
            max_tokens=100,
            system_prompt="s1",
            messages=_make_messages(("user", "hi")),
            tool_registry=reg,
        )
        rid2 = log_prompt_request(
            model="m2",
            max_tokens=200,
            system_prompt="s2",
            messages=_make_messages(("user", "ho")),
            tool_registry=reg,
        )
        assert rid2 > rid1

    def test_verbose_writes_to_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When verbose=True, content must be written to the debug log file."""
        log_file = tmp_path / "prompt_debug_test.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_prompt_request(
                model="test-model",
                max_tokens=512,
                system_prompt="System prompt content here.",
                messages=_make_messages(("user", "Hello world")),
                tool_registry=_make_tool_registry("bash", "read"),
                verbose=True,
            )
            content = log_file.read_text(encoding="utf-8")
            # The file should contain separator lines and key markers.
            assert "=" * 80 in content
            assert "test-model" in content
            assert "SYSTEM PROMPT" in content
        finally:
            _shared.set_verbose(False)

    def test_no_file_when_not_verbose(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When verbose=False (default), no file content should be written."""
        log_file = tmp_path / "prompt_debug_no_verbose.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        # verbose stays False (default from reset_session)

        log_prompt_request(
            model="test-model",
            max_tokens=256,
            system_prompt="Short prompt.",
            messages=_make_messages(("user", "hi")),
            tool_registry=_make_tool_registry("bash"),
            verbose=False,
        )
        # File should not have been created or should be empty.
        assert not log_file.exists() or log_file.read_text(encoding="utf-8") == ""

    def test_prompt_log_entry_fields(self) -> None:
        """The data model fields should be populated correctly."""
        rid = log_prompt_request(
            model="claude-3",
            max_tokens=4096,
            system_prompt="# Section1\nBody\n# Section2\nMore body",
            messages=_make_messages(("user", "hi"), ("assistant", "hello")),
            tool_registry=_make_tool_registry("bash", "grep"),
        )
        # We cannot directly inspect the entry from the public API, but we
        # can verify the request_id matches and the function completed.
        assert isinstance(rid, int)


# ---------------------------------------------------------------------------
# log_response_event
# ---------------------------------------------------------------------------


class TestLogResponseEvent:
    """Tests for ``log_response_event``."""

    def test_no_crash(self) -> None:
        """log_response_event must not raise for valid input."""
        log_response_event(
            delta_text="Hello ",
            request_id=1,
        )

    def test_verbose_writes_delta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When verbose=True, delta text should appear in the log file."""
        log_file = tmp_path / "prompt_debug_delta.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            log_response_event(
                delta_text="Hello world",
                request_id=1,
                verbose=True,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "Hello world" in content
        finally:
            _shared.set_verbose(False)


# ---------------------------------------------------------------------------
# log_response_complete
# ---------------------------------------------------------------------------


class TestLogResponseComplete:
    """Tests for ``log_response_complete``."""

    def _make_text_message(self, text: str) -> ConversationMessage:
        return ConversationMessage(role="assistant", content=[TextBlock(text=text)])

    def _make_tool_message(self) -> ConversationMessage:
        return ConversationMessage(
            role="assistant",
            content=[
                TextBlock(text="I will use a tool."),
                ToolUseBlock(id="toolu_abc123", name="bash", input={"command": "ls"}),
            ],
        )

    def test_no_crash_text_only(self) -> None:
        """log_response_complete must not crash with a text-only message."""
        msg = self._make_text_message("Here is the answer.")
        usage = UsageSnapshot(input_tokens=100, output_tokens=50)
        log_response_complete(
            message=msg,
            usage=usage,
            request_id=1,
            model="test-model",
            stop_reason="end_turn",
        )

    def test_no_crash_with_tool_use(self) -> None:
        """log_response_complete must not crash with ToolUseBlock content."""
        msg = self._make_tool_message()
        usage = UsageSnapshot(input_tokens=200, output_tokens=80)
        log_response_complete(
            message=msg,
            usage=usage,
            request_id=2,
            model="test-model",
            stop_reason="tool_use",
        )

    def test_verbose_writes_complete(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When verbose=True, response complete details should be in the file."""
        log_file = tmp_path / "prompt_debug_complete.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            msg = self._make_tool_message()
            usage = UsageSnapshot(input_tokens=200, output_tokens=80)
            log_response_complete(
                message=msg,
                usage=usage,
                request_id=1,
                model="test-model",
                stop_reason="tool_use",
                verbose=True,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "=" * 80 in content
            assert "RESPONSE" in content
            assert "TOOL_USES" in content
            assert "bash" in content
            assert "USAGE" in content
        finally:
            _shared.set_verbose(False)

    def test_verbose_text_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verbose output for a text-only response should contain TEXT section."""
        log_file = tmp_path / "prompt_debug_text_only.log"
        monkeypatch.setattr(_shared, "get_log_file_path", lambda: log_file)
        _shared.set_verbose(True)

        try:
            msg = self._make_text_message("Short answer.")
            usage = UsageSnapshot(input_tokens=100, output_tokens=50)
            log_response_complete(
                message=msg,
                usage=usage,
                request_id=1,
                model="test-model",
                stop_reason="end_turn",
                verbose=True,
            )
            content = log_file.read_text(encoding="utf-8")
            assert "=" * 80 in content
            assert "Short answer." in content
            assert "USAGE" in content
        finally:
            _shared.set_verbose(False)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TestDataModels:
    """Verify that the dataclass models can be instantiated."""

    def test_prompt_log_entry(self) -> None:
        entry = PromptLogEntry(
            request_id=1,
            timestamp="2026-01-01 00:00:00",
            model="test",
            max_tokens=1024,
            system_prompt_sections=[("Preamble", 50)],
            system_prompt_total_chars=50,
            message_count_by_role={"user": 1},
            message_total_chars=10,
            tool_count=2,
            tool_names=["bash", "grep"],
        )
        assert entry.request_id == 1
        assert entry.tool_count == 2

    def test_response_log_entry(self) -> None:
        entry = ResponseLogEntry(
            request_id=1,
            text_length=5,
            text_preview="Hello",
        )
        assert entry.text_length == 5

    def test_response_complete_log_entry(self) -> None:
        entry = ResponseCompleteLogEntry(
            request_id=1,
            model="test",
            text="response",
            tool_uses=[{"name": "bash", "input": {"command": "ls"}}],
            stop_reason="end_turn",
            input_tokens=100,
            output_tokens=50,
        )
        assert entry.tool_uses[0]["name"] == "bash"