"""Environment-variable based configuration."""

from __future__ import annotations

import os
from pathlib import Path


# Known providers with default base URLs and models
PROVIDER_CONFIGS: dict[str, dict[str, str]] = {
    "anthropic": {
        "env_key": "ANTHROPIC_API_KEY",
        "default_base_url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-sonnet-4-6",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "default_base_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o",
    },
    "deepseek": {
        "env_key": "DEEPSEEK_API_KEY",
        "default_base_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-v4-flash",
    },
}

# Model families that use max_completion_tokens instead of max_tokens
MAX_COMPLETION_TOKEN_MODELS = (
    "gpt-5", "o1", "o3", "o4",
    "deepseek-reasoner",
)


# Model name → provider hints (used when multiple API keys are set)
MODEL_PROVIDER_HINTS: dict[str, str] = {
    "claude": "anthropic",
    "deepseek": "deepseek",
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "o4": "openai",
}


def get_api_key(provider_hint: str | None = None) -> str | None:
    """Return the API key from environment.

    If *provider_hint* is given, check that provider's env var first.
    """
    if provider_hint:
        cfg = PROVIDER_CONFIGS.get(provider_hint)
        if cfg:
            val = os.environ.get(cfg["env_key"])
            if val:
                return val
    for name, cfg in PROVIDER_CONFIGS.items():
        val = os.environ.get(cfg["env_key"])
        if val:
            return val
    return None


def get_api_provider() -> str:
    """Auto-detect the provider from available env vars or model name.

    Resolution order:
      1. OPENHARNESS_PROVIDER env var (explicit override)
      2. Model name hint (e.g. model starting with "deepseek" → deepseek)
         even if DEEPSEEK_API_KEY is not set — the model name is the intent
      3. First configured API key env var found
      4. Fallback to anthropic
    """
    explicit = os.environ.get("OPENHARNESS_PROVIDER")
    if explicit and explicit in PROVIDER_CONFIGS:
        return explicit

    model = os.environ.get("OPENHARNESS_MODEL", "")
    model_lower = model.strip().lower()
    for prefix, provider in MODEL_PROVIDER_HINTS.items():
        if model_lower.startswith(prefix):
            return provider

    for name, cfg in PROVIDER_CONFIGS.items():
        if os.environ.get(cfg["env_key"]):
            return name
    return "anthropic"


def get_provider_config(provider: str | None = None) -> dict[str, str]:
    """Return the resolved provider config (env overrides + defaults)."""
    if provider is None:
        provider = get_api_provider()
    cfg = PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["openai"])
    return {
        "env_key": cfg["env_key"],
        "base_url": os.environ.get("OPENHARNESS_BASE_URL") or cfg["default_base_url"],
        "model": os.environ.get("OPENHARNESS_MODEL") or cfg["default_model"],
    }


def get_model() -> str:
    """Return the model name from environment or provider default."""
    return get_provider_config()["model"]


def get_base_url() -> str | None:
    """Return the base URL from environment or provider default."""
    return os.environ.get("OPENHARNESS_BASE_URL") or None


def get_provider_base_url(provider: str) -> str:
    """Return the provider's default base URL if no env override."""
    return os.environ.get("OPENHARNESS_BASE_URL") or PROVIDER_CONFIGS.get(provider, PROVIDER_CONFIGS["openai"])["default_base_url"]


def needs_max_completion_tokens(model: str) -> bool:
    """Check whether the model requires max_completion_tokens instead of max_tokens."""
    normalized = model.strip().lower()
    # Strip provider prefix like "deepseek/" -> "deepseek-chat"
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return any(normalized.startswith(prefix) for prefix in MAX_COMPLETION_TOKEN_MODELS)


def get_max_tokens() -> int:
    """Return the max tokens setting."""
    return int(os.environ.get("OPENHARNESS_MAX_TOKENS", "4096"))


def get_max_turns() -> int:
    """Return the max agentic turns per prompt."""
    return int(os.environ.get("OPENHARNESS_MAX_TURNS", "200"))


def get_data_dir() -> Path:
    """Return the data directory for caches, history, etc."""
    env_dir = os.environ.get("OPENHARNESS_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
    else:
        data_dir = Path.home() / ".openharness" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


# ── Compaction config ─────────────────────────────────────────────────


def get_context_window_tokens() -> int | None:
    """Return explicit context window override (tokens) or None."""
    val = os.environ.get("OPENHARNESS_CONTEXT_WINDOW_TOKENS")
    return int(val) if val and val.strip() else None


def get_auto_compact_threshold_tokens() -> int | None:
    """Return explicit auto-compact threshold override or None."""
    val = os.environ.get("OPENHARNESS_AUTO_COMPACT_THRESHOLD_TOKENS")
    return int(val) if val and val.strip() else None


def get_compact_preserve_recent() -> int:
    """Number of recent messages to preserve verbatim during compaction."""
    return int(os.environ.get("OPENHARNESS_COMPACT_PRESERVE_RECENT", "6"))


def is_auto_compact_enabled() -> bool:
    """Whether auto-compaction is enabled (default: enabled)."""
    val = os.environ.get("OPENHARNESS_AUTO_COMPACT_ENABLED", "1")
    return val.lower() in ("1", "true", "yes")
