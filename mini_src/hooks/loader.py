"""Simplified hook loader — reads from a plain dict, no Settings object."""

from __future__ import annotations

from mini_src.hooks.events import HookEvent
from mini_src.hooks.schemas import HookDefinition


def load_hook_registry(hooks_config: dict[str, list[HookDefinition]] | None = None) -> dict[str, list[HookDefinition]]:
    """Load hooks from a plain event -> list[HookDefinition] dict.

    Expected format::

        {
            "pre_compact": [
                CommandHookDefinition(command="git diff --quiet", block_on_failure=True),
            ],
        }

    Returns an empty dict when *hooks_config* is None or empty.
    """
    if not hooks_config:
        return {}
    validated: dict[str, list[HookDefinition]] = {}
    for raw_event, hooks in hooks_config.items():
        try:
            event = HookEvent(raw_event)
        except ValueError:
            continue
        validated[event.value] = list(hooks)
    return validated
