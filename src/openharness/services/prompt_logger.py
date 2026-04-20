"""Backward-compatible re-export. Use openharness.services.log instead."""

from __future__ import annotations

import warnings

warnings.warn(
    "openharness.services.prompt_logger is deprecated. "
    "Use openharness.services.log instead.",
    DeprecationWarning,
    stacklevel=2,
)

from openharness.services.log import *  # noqa: F401,F403