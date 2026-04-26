"""Environment-variable based configuration."""

from __future__ import annotations

import os
from pathlib import Path


def get_api_key() -> str | None:
    """Return the API key from environment."""
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")


def get_api_provider() -> str:
    """Return the provider type: 'anthropic' or 'openai'."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


def get_model() -> str:
    """Return the model name from environment or a default."""
    return os.environ.get("OPENHARNESS_MODEL", "claude-sonnet-4-6")


def get_base_url() -> str | None:
    """Return an optional custom base URL."""
    return os.environ.get("OPENHARNESS_BASE_URL") or None


def get_max_tokens() -> int:
    """Return the max tokens setting."""
    return int(os.environ.get("OPENHARNESS_MAX_TOKENS", "4096"))


def get_max_turns() -> int:
    """Return the max agentic turns per prompt."""
    return int(os.environ.get("OPENHARNESS_MAX_TURNS", "20"))


def get_data_dir() -> Path:
    """Return the data directory for caches, history, etc."""
    env_dir = os.environ.get("OPENHARNESS_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
    else:
        data_dir = Path.home() / ".openharness" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
