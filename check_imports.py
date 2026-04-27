"""Quick syntax check for the compaction port."""
import sys
sys.path.insert(0, ".")

# Test imports - check everything is importable
from mini_src.core.compact import (
    AutoCompactState,
    CompactionResult,
    estimate_tokens,
    estimate_message_tokens,
    should_autocompact,
    microcompact_messages,
    try_context_collapse,
    try_session_memory_compaction,
    compact_conversation,
    auto_compact_if_needed,
    get_context_window,
    get_autocompact_threshold,
    COMPACTABLE_TOOLS,
)

from mini_src.hooks.events import HookEvent
from mini_src.hooks.types import HookResult, AggregatedHookResult
from mini_src.hooks.schemas import (
    CommandHookDefinition,
    PromptHookDefinition,
    HttpHookDefinition,
    AgentHookDefinition,
)
from mini_src.hooks.executor import HookExecutor, HookExecutionContext
from mini_src.hooks.loader import load_hook_registry

from mini_src.config import (
    get_context_window_tokens,
    get_auto_compact_threshold_tokens,
    get_compact_preserve_recent,
    is_auto_compact_enabled,
)

# Test engine import (which also uses auto_compact_if_needed)
from mini_src.core.engine import QueryEngine

state = AutoCompactState()
print(f"All imports OK. Compactable tools: {len(COMPACTABLE_TOOLS)}, failures: {state.consecutive_failures}")
